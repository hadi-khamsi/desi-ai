import os
import select
import sys
import termios
import tty

from openai import OpenAI

from config import get_config
from prompts import SYSTEM_PROMPT
from voice import VoiceHandler


class RawTerminal:
    """Context manager for raw keyboard input"""
    def __init__(self):
        self.old_settings = None

    def __enter__(self):
        self.old_settings = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())
        return self

    def __exit__(self, *args):
        if self.old_settings:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.old_settings)


class LLMClient:
    def __init__(self, config):
        self.client = OpenAI(api_key=config.api_key, base_url=config.base_url)
        self.config = config

    def stream(self, messages: list[dict]):
        """Stream response chunks"""
        response = self.client.chat.completions.create(
            model=self.config.model,
            messages=messages,
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
            stream=True,
        )
        for chunk in response:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


class ChatSession:
    def __init__(self, client: LLMClient):
        self.client = client
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    def send(self, user_input: str):
        """Send message and stream response"""
        self.messages.append({"role": "user", "content": user_input})
        full_response = ""
        for chunk in self.client.stream(self.messages):
            full_response += chunk
            yield chunk
        self.messages.append({"role": "assistant", "content": full_response})


def create_voice_handler(config):
    """Create VoiceHandler with config from .env"""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return VoiceHandler(
        voice=os.getenv("VOICE", "en-IN-PrabhatNeural"),
        music_folder=os.path.join(project_root, "music"),
        music_enabled=os.getenv("MUSIC_ENABLED", "true").lower() == "true",
        music_volume=float(os.getenv("MUSIC_VOLUME", "0.2")),
        music_file=os.getenv("MUSIC_FILE"),
        groq_api_key=config.api_key,
    )


def check_spacebar():
    """Non-blocking spacebar check"""
    if select.select([sys.stdin], [], [], 0)[0]:
        return sys.stdin.read(1) == ' '
    return False


def wait_for_space():
    """Block until spacebar (True) or Q (False)"""
    while True:
        if select.select([sys.stdin], [], [], 0.05)[0]:
            key = sys.stdin.read(1)
            if key == ' ':
                return True
            if key == 'q':
                return False


def voice_mode(voice, session):
    """Voice input mode - speak to chat"""
    print("\n" + "=" * 40)
    print("VOICE MODE")
    print("=" * 40)
    print("speak → space to send")
    print("q to go back")
    print("=" * 40 + "\n")

    with RawTerminal():
        while True:
            try:
                print("[listening... space to send]", end="\r", flush=True)
                audio_path = voice.record_until_space()

                if not audio_path:
                    continue

                print("[processing...]             ", end="\r", flush=True)
                user_input = voice.transcribe(audio_path)
                os.unlink(audio_path)

                if not user_input:
                    continue

                print(f"You: {user_input}")

                # Exit check
                if any(cmd in user_input.lower() for cmd in ["exit", "quit", "stop", "bye"]):
                    print("Desi: Take care Haadi!")
                    voice.speak("Take care Haadi!")
                    break

                # Get and speak response (with interrupt hint)
                print("Desi: [space to interrupt] ", end="", flush=True)
                voice.speak_streaming(
                    session.send(user_input),
                    interrupt_check=check_spacebar
                )
                print("\n")

            except KeyboardInterrupt:
                voice.stop_speaking()
                termios.tcflush(sys.stdin, termios.TCIFLUSH)
                break


def chat_mode(voice, session):
    """Text input mode - type to chat"""
    print("\n" + "=" * 40)
    print("CHAT MODE")
    print("=" * 40)
    print("type message, AI speaks back")
    print("'q' to go back")
    print("=" * 40 + "\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input or user_input.lower() == 'q':
            break

        print("Desi: [space to interrupt] ", end="", flush=True)
        with RawTerminal():
            voice.speak_streaming(session.send(user_input), interrupt_check=check_spacebar)
        print("\n")


def main():
    config = get_config()

    if not config.api_key:
        print("Error: GROQ_API_KEY not set. Check .env file.")
        sys.exit(1)

    print("Starting Desi AI...")
    voice = create_voice_handler(config)
    client = LLMClient(config)
    session = ChatSession(client)

    print(f"\nUsing {config.model}")

    while True:
        print("\n[v]oice  [c]hat  [q]uit: ", end="", flush=True)

        # Read single keypress, no Enter needed
        with RawTerminal():
            key = sys.stdin.read(1).lower()

        if key == 'v':
            print("voice")
            voice_mode(voice, session)
        elif key == 'c':
            print("chat")
            chat_mode(voice, session)
        elif key == 'q':
            print("quit\nTake care!")
            break


if __name__ == "__main__":
    main()

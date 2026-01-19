import os
import select
import sys
import termios
import time
import tty

from openai import OpenAI

from config import get_config
from prompts import get_system_prompt
from voice import VoiceHandler


def check_spacebar():
    """Non-blocking check if spacebar was pressed"""
    if select.select([sys.stdin], [], [], 0)[0]:
        key = sys.stdin.read(1)
        return key == ' '
    return False


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
        self.config = config
        self.client = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )

    def chat(self, messages: list[dict]) -> str:
        response = self.client.chat.completions.create(
            model=self.config.model,
            messages=messages,
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
        )
        return response.choices[0].message.content

    def chat_stream(self, messages: list[dict]):
        """Stream chat response, yielding text chunks as they arrive"""
        stream = self.client.chat.completions.create(
            model=self.config.model,
            messages=messages,
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
            stream=True,
        )
        for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


class ChatSession:
    def __init__(self, client):
        self.client = client
        self.messages = [{"role": "system", "content": get_system_prompt()}]

    def send(self, user_input: str) -> str:
        self.messages.append({"role": "user", "content": user_input})
        try:
            response = self.client.chat(self.messages)
            self.messages.append({"role": "assistant", "content": response})
            return response
        except Exception as e:
            self.messages.pop()
            raise e

    def send_stream(self, user_input: str):
        """Stream response, yielding chunks."""
        self.messages.append({"role": "user", "content": user_input})
        self._pending_response = ""
        try:
            for chunk in self.client.chat_stream(self.messages):
                self._pending_response += chunk
                yield chunk
            self.messages.append({"role": "assistant", "content": self._pending_response})
        except Exception as e:
            self.messages.pop()
            raise e


def create_voice_handler(config):
    """Create VoiceHandler with current config"""
    tts_provider = os.getenv("TTS_PROVIDER", "edge")
    voice = os.getenv("VOICE", "en-IN-PrabhatNeural")
    music_volume = float(os.getenv("MUSIC_VOLUME", "0.2"))
    music_file = os.getenv("MUSIC_FILE") or None

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    music_path = os.path.join(project_root, "music")

    return VoiceHandler(
        tts_provider=tts_provider,
        voice=voice,
        music_folder=music_path,
        music_volume=music_volume,
        music_file=music_file,
        groq_api_key=config.api_key,
    )


def wait_for_space():
    """Wait for spacebar (returns True) or Q (returns False)"""
    while True:
        if select.select([sys.stdin], [], [], 0.05)[0]:
            key = sys.stdin.read(1)
            if key == ' ':
                return True
            if key == 'q':
                return False


def conversation_mode(voice_handler, session):
    """
    Voice conversation with spacebar control.
    - Auto-listens immediately
    - SPACE to send your message
    - SPACE to interrupt AI anytime
    - Q to quit
    """
    print("\n" + "=" * 40)
    print("CONVERSATION MODE")
    print("=" * 40)
    print("Speaking → SPACE to send")
    print("AI talking → SPACE to interrupt")
    print("Q to quit")
    print("=" * 40 + "\n")

    with RawTerminal():
        while True:
            try:
                # Start recording immediately
                print("[Listening... SPACE to send]", end="\r", flush=True)
                audio_path = voice_handler.record_until_space()

                if not audio_path:
                    continue

                # Transcribe
                print("[Processing...]             ", end="\r", flush=True)
                user_input = voice_handler.transcribe(audio_path)
                os.unlink(audio_path)

                if not user_input:
                    print("                            ", end="\r")
                    continue

                print(f"You: {user_input}                    ")

                # Check for exit
                lower_input = user_input.lower().strip()
                if any(cmd in lower_input for cmd in ["exit", "quit", "stop", "goodbye", "bye"]):
                    print("Desi: Take care Haadi!")
                    voice_handler.speak("Take care Haadi!")
                    time.sleep(2)
                    break

                # AI response with TTS
                print("Desi: ", end="", flush=True)
                response = voice_handler.speak_streaming(
                    session.send_stream(user_input),
                    interrupt_check=check_spacebar
                )
                print(response)
                print()

            except KeyboardInterrupt:
                print("\n\nExiting...")
                voice_handler.stop_speaking()
                termios.tcflush(sys.stdin, termios.TCIFLUSH)
                break
            except Exception as e:
                print(f"\nError: {e}")
                continue

    print()


def main():
    config = get_config()

    if not config.api_key:
        print("Error: GROQ_API_KEY not set. Check your .env file.")
        sys.exit(1)

    # Initialize voice (starts music immediately)
    print("Starting...")
    voice_handler = create_voice_handler(config)

    print(f"\nUsing Groq ({config.model})")
    print("\nCommands:")
    print("  'convo'  - Voice conversation mode")
    print("  'speak [on/off]' - Voice output for text chat")
    print("  'exit/quit' - Exit\n")

    client = LLMClient(config)
    session = ChatSession(client)
    speak_enabled = False

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit"):
            print("Take care!")
            break

        # Conversation mode - the main feature
        if user_input.lower() in ("convo", "conversation", "talk", "chat"):
            conversation_mode(voice_handler, session)
            continue

        if user_input.lower().startswith("speak "):
            setting = user_input[6:].strip().lower()
            if setting in ["on", "off"]:
                speak_enabled = setting == "on"
                print(f"\n-> Voice output {'ON' if speak_enabled else 'OFF'}\n")
            else:
                print("\nUsage: speak [on/off]\n")
            continue

        # Regular text input
        try:
            if speak_enabled and voice_handler:
                print("\nDesi: ", end="", flush=True)
                response = voice_handler.speak_streaming(session.send_stream(user_input))
                print(response)
                print()
            else:
                response = session.send(user_input)
                print(f"\nDesi: {response}\n")

        except Exception as e:
            print(f"\nError: {e}\n")


if __name__ == "__main__":
    main()

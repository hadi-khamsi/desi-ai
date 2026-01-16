
import os
import sys

from openai import OpenAI

from config import get_config
from prompts import get_system_prompt
from voice import VoiceHandler


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


class ChatSession:
    def __init__(self, client, language: str = "english"):
        self.client = client
        self.language = language
        self.messages = [{"role": "system", "content": get_system_prompt(language)}]

    def set_language(self, language: str):
        self.language = language
        self.messages[0] = {"role": "system", "content": get_system_prompt(language)}

    def send(self, user_input: str) -> str:
        self.messages.append({"role": "user", "content": user_input})
        try:
            response = self.client.chat(self.messages)
            self.messages.append({"role": "assistant", "content": response})
            return response
        except Exception as e:
            self.messages.pop()
            raise e


def main():
    config = get_config()

    if not config.api_key:
        print("Error: GROQ_API_KEY not set. Check your .env file.")
        sys.exit(1)

    language = os.getenv("LANGUAGE", "english").lower()

    print(f"Using Groq ({config.model})")
    print(f"Language: {language.upper()}")
    print("Commands: 'speak [on/off]' | 'voice' | 'lang [english/hindi/urdu]' | 'exit/quit'\n")

    client = LLMClient(config)
    session = ChatSession(client, language)
    voice_handler = None
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

        if user_input.lower().startswith("lang "):
            new_lang = user_input[5:].strip().lower()
            if new_lang in ["english", "hindi", "urdu"]:
                session.set_language(new_lang)
                print(f"\n✓ Language changed to {new_lang.upper()}\n")
            else:
                print("\nAvailable: english, hindi, urdu\n")
            continue

        if user_input.lower().startswith("speak "):
            setting = user_input[6:].strip().lower()
            
            if setting not in ["on", "off"]:
                print("\nUsage: speak [on/off]\n")
                continue

            if voice_handler is None:
                print("\nInitializing voice...")
                tts_provider = os.getenv("TTS_PROVIDER", "edge")
                voice = os.getenv("VOICE", "en-IN-PrabhatNeural")
                music_volume = float(os.getenv("MUSIC_VOLUME", "0.15"))
                music_file = os.getenv("MUSIC_FILE")

                api_key = None
                if tts_provider == "elevenlabs":
                    api_key = os.getenv("ELEVENLABS_API_KEY")
                elif tts_provider == "openai":
                    api_key = os.getenv("OPENAI_API_KEY")

                voice_handler = VoiceHandler(
                    model_size="base",
                    tts_provider=tts_provider,
                    voice=voice,
                    music_folder="./music",
                    music_volume=music_volume,
                    music_file=music_file,
                    api_key=api_key,
                )

            speak_enabled = setting == "on"
            status = "ON" if speak_enabled else "OFF"
            print(f"\n✓ Voice output {status}\n")
            continue

        if user_input.lower() == "voice":
            if voice_handler is None:
                print("\nInitializing voice mode...")
                tts_provider = os.getenv("TTS_PROVIDER", "edge")
                voice = os.getenv("VOICE", "en-IN-PrabhatNeural")
                music_volume = float(os.getenv("MUSIC_VOLUME", "0.15"))
                music_file = os.getenv("MUSIC_FILE")

                api_key = None
                if tts_provider == "elevenlabs":
                    api_key = os.getenv("ELEVENLABS_API_KEY")
                elif tts_provider == "openai":
                    api_key = os.getenv("OPENAI_API_KEY")

                voice_handler = VoiceHandler(
                    model_size="base",
                    tts_provider=tts_provider,
                    voice=voice,
                    music_folder="./music",
                    music_volume=music_volume,
                    music_file=music_file,
                    api_key=api_key,
                )

            try:
                print("\n[Speak now - Ctrl+C to cancel]")
                user_input = voice_handler.listen(duration=5)
                print(f"You: {user_input}\n")

                if not user_input:
                    print("No speech detected.\n")
                    continue

                response = session.send(user_input)
                print(f"Desi: {response}\n")
                print("Speaking...")
                voice_handler.speak(response)
                print()
            except KeyboardInterrupt:
                print("\nCancelled.\n")
                continue
            except Exception as e:
                print(f"\nError: {e}\n")
            continue

        try:
            response = session.send(user_input)
            print(f"\nDesi: {response}\n")
            
            if speak_enabled and voice_handler:
                print("Speaking...")
                voice_handler.speak(response)  # runs in parallel

        except Exception as e:
            print(f"\nError: {e}\n")


if __name__ == "__main__":
    main()

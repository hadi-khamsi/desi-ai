import sys

from openai import OpenAI

from config import APIConfig, get_config
from prompts import get_system_prompt
from voice import VoiceHandler


class LLMClient:
    def __init__(self, config: APIConfig):
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
    def __init__(self, client: LLMClient, language: str = "english"):
        self.client = client
        self.language = language
        self.messages: list[dict] = [{"role": "system", "content": get_system_prompt(language)}]

    def set_language(self, language: str):
        """Change the conversation language."""
        self.language = language
        # Update system message
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
        print("Error: API key not configured. Check your .env file.")
        sys.exit(1)

    # Get language setting
    import os
    language = os.getenv("LANGUAGE", "english").lower()

    print(f"Using Hugging Face ({config.model})")
    print(f"Language: {language.upper()}")
    print("Commands: 'voice' = voice | 'lang [english/hindi/urdu]' = change language | 'exit/quit' = end\n")

    client = LLMClient(config)
    session = ChatSession(client, language=language)
    voice_handler = None  # Lazy load on first use
    current_language = language

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit"):
            print("Take care! Feel free to come back anytime.")
            break

        # Language change
        if user_input.lower().startswith("lang "):
            new_lang = user_input[5:].strip().lower()
            if new_lang in ["english", "hindi", "urdu"]:
                session.set_language(new_lang)
                current_language = new_lang
                print(f"\n✓ Language changed to {new_lang.upper()}\n")
            else:
                print("\nAvailable languages: english, hindi, urdu\n")
            continue

        # Voice mode
        if user_input.lower() == "voice":
            if voice_handler is None:
                print("\nInitializing voice mode...")
                import os
                tts_provider = os.getenv("TTS_PROVIDER", "edge")
                voice = os.getenv("VOICE", "en-IN-PrabhatNeural")
                music_volume = float(os.getenv("MUSIC_VOLUME", "0.15"))
                music_file = os.getenv("MUSIC_FILE")

                # Get API key if using premium provider
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
                print("\n[Press Ctrl+C to cancel recording]")
                user_input = voice_handler.listen(duration=5)
                print(f"You said: {user_input}\n")

                if not user_input:
                    print("No speech detected. Try again.\n")
                    continue

                response = session.send(user_input)
                print(f"Desi: {response}\n")
                print("Speaking response...")
                voice_handler.speak(response)
                print()
            except KeyboardInterrupt:
                print("\nVoice input cancelled.\n")
                continue
            except Exception as e:
                print(f"\nVoice error: {e}\n")
            continue

        # Text mode
        try:
            response = session.send(user_input)
            print(f"\nDesi: {response}\n")
        except Exception as e:
            print(f"\nError: {e}\n")


if __name__ == "__main__":
    main()

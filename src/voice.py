import asyncio
import os
import random
import subprocess
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path

import edge_tts
import numpy as np
import sounddevice as sd
import soundfile as sf
from elevenlabs import VoiceSettings
from elevenlabs.client import ElevenLabs
from faster_whisper import WhisperModel
from pydub import AudioSegment


class TTSProvider(ABC):
    """Base class for Text-to-Speech providers."""

    @abstractmethod
    def generate(self, text: str, output_path: str):
        """Generate speech and save to file."""
        pass


class EdgeTTSProvider(TTSProvider):
    """Microsoft Edge TTS - Free, decent quality."""

    def __init__(self, voice: str = "en-IN-PrabhatNeural"):
        self.voice = voice

    def generate(self, text: str, output_path: str):
        """Generate speech using Edge TTS with improved prosody."""
        asyncio.run(self._async_generate(text, output_path))

    async def _async_generate(self, text: str, output_path: str):
        # Add SSML for younger, more passionate delivery
        rate = "+25%"  # Faster, more energetic/youthful
        pitch = "+10Hz"  # Higher pitch for younger sound

        communicate = edge_tts.Communicate(text, self.voice, rate=rate, pitch=pitch)
        await communicate.save(output_path)


class ElevenLabsProvider(TTSProvider):
    """ElevenLabs - Premium quality, very natural."""

    def __init__(self, api_key: str, voice_id: str = "pNInz6obpgDQGcFmaJgB"):
        """
        Initialize ElevenLabs TTS.

        Args:
            api_key: ElevenLabs API key
            voice_id: Voice ID (default is Adam - warm, deep male voice)
        """
        self.client = ElevenLabs(api_key=api_key)
        self.voice_id = voice_id

    def generate(self, text: str, output_path: str):
        """Generate speech using ElevenLabs."""
        audio = self.client.text_to_speech.convert(
            voice_id=self.voice_id,
            text=text,
            model_id="eleven_multilingual_v2",
            voice_settings=VoiceSettings(
                stability=0.5,
                similarity_boost=0.75,
                style=0.6,  # More expressive
                use_speaker_boost=True,
            ),
        )

        # Save audio
        with open(output_path, "wb") as f:
            for chunk in audio:
                f.write(chunk)


class OpenAITTSProvider(TTSProvider):
    """OpenAI TTS - Very natural, good quality."""

    def __init__(self, api_key: str, voice: str = "onyx"):
        """
        Initialize OpenAI TTS.

        Args:
            api_key: OpenAI API key
            voice: Voice name (alloy, echo, fable, onyx, nova, shimmer)
        """
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key)
        self.voice = voice

    def generate(self, text: str, output_path: str):
        """Generate speech using OpenAI TTS."""
        response = self.client.audio.speech.create(
            model="tts-1-hd",
            voice=self.voice,
            input=text,
        )
        response.stream_to_file(output_path)


class VoiceHandler:
    """Handles voice input/output with background music mixing."""

    def __init__(
        self,
        model_size: str = "base",
        tts_provider: str = "edge",
        voice: str = "en-IN-PrabhatNeural",
        music_folder: str = "./music",
        music_volume: float = 0.15,
        music_file: str = None,
        api_key: str = None,
    ):
        """
        Initialize voice handler.

        Args:
            model_size: Whisper model size (tiny, base, small, medium, large)
            tts_provider: TTS provider (edge, elevenlabs, openai)
            voice: Voice ID for the selected provider
            music_folder: Folder containing background music files
            music_volume: Background music volume (0.0 to 1.0)
            music_file: Specific music file to use (if None, picks randomly)
            api_key: API key for premium TTS providers
        """
        print(f"Loading Whisper model '{model_size}'...")
        self.whisper = WhisperModel(model_size, device="cpu", compute_type="int8")
        self.sample_rate = 16000
        self.music_folder = Path(music_folder)
        self.music_volume = music_volume
        self.music_file = music_file

        # Initialize TTS provider
        if tts_provider == "edge":
            self.tts = EdgeTTSProvider(voice)
        elif tts_provider == "elevenlabs":
            if not api_key:
                raise ValueError("ElevenLabs requires an API key")
            self.tts = ElevenLabsProvider(api_key, voice)
        elif tts_provider == "openai":
            if not api_key:
                raise ValueError("OpenAI TTS requires an API key")
            self.tts = OpenAITTSProvider(api_key, voice)
        else:
            raise ValueError(f"Unknown TTS provider: {tts_provider}")

    def record_audio(self, duration: int = 5) -> str:
        """Record audio from microphone."""
        print(f"Recording for {duration} seconds... Speak now!")
        audio_data = sd.rec(
            int(duration * self.sample_rate),
            samplerate=self.sample_rate,
            channels=1,
            dtype=np.int16,
        )
        sd.wait()
        print("Recording finished!")

        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        sf.write(temp_file.name, audio_data, self.sample_rate)
        return temp_file.name

    def transcribe(self, audio_path: str) -> str:
        """Transcribe audio to text using Whisper."""
        segments, info = self.whisper.transcribe(audio_path, beam_size=5)
        text = " ".join([segment.text for segment in segments])
        return text.strip()

    def _get_random_music(self) -> Path | None:
        """Get music file - specific file if set, otherwise random."""
        if not self.music_folder.exists():
            return None

        # If specific music file is set, use that
        if self.music_file:
            specific_path = self.music_folder / self.music_file
            if specific_path.exists():
                return specific_path

        # Otherwise pick random
        music_files = list(self.music_folder.glob("*.mp3")) + list(
            self.music_folder.glob("*.wav")
        )
        if not music_files:
            return None

        return random.choice(music_files)

    def _mix_with_music(self, speech_path: str, output_path: str):
        """Mix speech with background music."""
        speech = AudioSegment.from_file(speech_path)
        music_file = self._get_random_music()

        if not music_file:
            # No music available, just copy speech
            speech.export(output_path, format="mp3")
            return

        # Load and prepare background music
        music = AudioSegment.from_file(str(music_file))

        # Reduce music volume
        music = music - (20 * (1 - self.music_volume))  # Convert to dB reduction

        # Loop music if speech is longer
        if len(music) < len(speech):
            repeats = (len(speech) // len(music)) + 1
            music = music * repeats

        # Trim music to speech length
        music = music[: len(speech)]

        # Fade in/out for cinematic effect
        music = music.fade_in(1000).fade_out(2000)

        # Mix audio
        mixed = speech.overlay(music)

        # Export
        mixed.export(output_path, format="mp3")

    def speak(self, text: str):
        """Convert text to speech with background music and play it."""
        # Generate speech
        temp_speech = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        temp_speech.close()

        self.tts.generate(text, temp_speech.name)

        # Mix with background music
        temp_mixed = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        temp_mixed.close()

        try:
            self._mix_with_music(temp_speech.name, temp_mixed.name)

            # Play the mixed audio
            if os.name == "posix":  # macOS/Linux
                subprocess.run(["afplay", temp_mixed.name], check=True)
            else:  # Windows
                subprocess.run(
                    [
                        "powershell",
                        "-c",
                        f"(New-Object Media.SoundPlayer '{temp_mixed.name}').PlaySync()",
                    ],
                    check=True,
                )
        finally:
            # Cleanup
            Path(temp_speech.name).unlink(missing_ok=True)
            Path(temp_mixed.name).unlink(missing_ok=True)

    def listen(self, duration: int = 5) -> str:
        """Record audio and transcribe to text."""
        audio_path = self.record_audio(duration)
        try:
            text = self.transcribe(audio_path)
            return text
        finally:
            Path(audio_path).unlink(missing_ok=True)

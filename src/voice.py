import asyncio
import os
import random
import subprocess
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
import threading

import edge_tts
import numpy as np
import sounddevice as sd
import soundfile as sf
from elevenlabs import VoiceSettings
from elevenlabs.client import ElevenLabs
from faster_whisper import WhisperModel


def to_spoken_style(text: str) -> str:
    text = text.replace("*", "").replace("\n", " ")
    text = text.replace(". ", "... ").replace(", ", ", ")
    text = text.replace(" Haadi", " Haadi, ").replace(" yaar", " yaar, ")
    forbidden = ["<", ">", "=", "/", "break", "time", "ms"]
    for f in forbidden:
        text = text.replace(f, "")
    return text.strip()


class TTSProvider(ABC):
    @abstractmethod
    def generate_stream(self, text: str):
        pass


class EdgeTTSProvider:
    def __init__(self, voice: str = "en-IN-PrabhatNeural"):
        self.voice = voice

    def generate_stream_to_file(self, text: str, output_path: str):
        """Generate full TTS file for non-blocking playback"""
        styled = to_spoken_style(text)
        asyncio.run(edge_tts.Communicate(styled, self.voice).save(output_path))


class VoiceHandler:
    def __init__(
        self,
        model_size: str = "base",
        tts_provider: str = "edge",
        voice: str = "en-IN-PrabhatNeural",
        music_folder: str = "./music",
        music_volume: float = 0.05,  # lower volume
        music_file: str = None,
        api_key: str = None,
    ):
        print(f"Loading Whisper model '{model_size}'...")
        self.whisper = WhisperModel(model_size, device="cpu", compute_type="int8")
        self.sample_rate = 16000

        self.music_folder = Path(music_folder)
        self.music_volume = music_volume
        self.music_file = music_file

        # TTS
        if tts_provider == "edge":
            self.tts = EdgeTTSProvider(voice)
        else:
            raise ValueError(f"Unknown TTS provider: {tts_provider}")

        # Start background music immediately
        self.music_thread = threading.Thread(target=self._play_music_loop, daemon=True)
        self.music_thread.start()

    def _get_random_music(self) -> Path | None:
        if not self.music_folder.exists():
            return None
        if self.music_file:
            specific = self.music_folder / self.music_file
            if specific.exists():
                return specific
        files = list(self.music_folder.glob("*.mp3")) + list(self.music_folder.glob("*.wav"))
        return random.choice(files) if files else None

    def _play_music_loop(self):
        music_file = self._get_random_music()
        if not music_file:
            return
        while True:
            if os.name == "posix":
                # Reduce volume to self.music_volume (0.0 - 1.0)
                subprocess.run(["afplay", "-v", str(self.music_volume), str(music_file)])
            else:
                # For Windows: TODO volume adjustment
                subprocess.run(
                    ["powershell", "-c", f"(New-Object Media.SoundPlayer '{music_file}').PlaySync()"]
                )


    def speak(self, text: str):
        """Generate TTS fully async, then play non-blocking"""
        def _speak_thread():
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
            temp_file.close()

            # Generate full audio
            self.tts.generate_stream_to_file(text, temp_file.name)

            # Play in background
            def play_audio():
                if os.name == "posix":
                    subprocess.run(["afplay", temp_file.name])
                else:
                    subprocess.run(
                        ["powershell", "-c", f"(New-Object Media.SoundPlayer '{temp_file.name}').PlaySync()"]
                    )
                Path(temp_file.name).unlink(missing_ok=True)

            threading.Thread(target=play_audio, daemon=True).start()

        threading.Thread(target=_speak_thread, daemon=True).start()

    def listen(self, duration: int = 5) -> str:
        audio_path = self.record_audio(duration)
        try:
            return self.transcribe(audio_path)
        finally:
            os.unlink(audio_path)

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

def to_spoken_style(text: str) -> str:
    """Edge-friendly speech formatting WITHOUT SSML"""

    text = text.replace("*", "")
    text = text.replace("\n", " ")

    # Natural pauses using punctuation ONLY
    text = text.replace(". ", "... ")
    text = text.replace(", ", ", ")
    
    # Add small rhythm helpers
    text = text.replace(" Haadi", " Haadi, ")
    text = text.replace(" yaar", " yaar, ")

    # Remove anything that sounds like code
    forbidden = ["<", ">", "=", "/", "break", "time", "ms"]
    for f in forbidden:
        text = text.replace(f, "")

    return text.strip()



class TTSProvider(ABC):
    @abstractmethod
    def generate(self, text: str, output_path: str):
        pass


class EdgeTTSProvider(TTSProvider):
    def __init__(self, voice: str = "en-IN-PrabhatNeural"):
        self.voice = voice

    def generate(self, text: str, output_path: str):
        styled = to_spoken_style(text)
        asyncio.run(self._async_generate(styled, output_path))

    async def _async_generate(self, text: str, output_path: str):
        communicate = edge_tts.Communicate(
            text,
            self.voice,
            rate="+14%",   
            pitch="+3Hz"
        )
        await communicate.save(output_path)


class ElevenLabsProvider(TTSProvider):
    def __init__(self, api_key: str, voice_id: str = "pNInz6obpgDQGcFmaJgB"):
        self.client = ElevenLabs(api_key=api_key)
        self.voice_id = voice_id

    def generate(self, text: str, output_path: str):
        audio = self.client.text_to_speech.convert(
            voice_id=self.voice_id,
            text=text,
            model_id="eleven_multilingual_v2",
            voice_settings=VoiceSettings(
                stability=0.5,
                similarity_boost=0.75,
                style=0.6,
                use_speaker_boost=True,
            ),
        )
        with open(output_path, "wb") as f:
            for chunk in audio:
                f.write(chunk)


class OpenAITTSProvider(TTSProvider):
    def __init__(self, api_key: str, voice: str = "onyx"):
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key)
        self.voice = voice

    def generate(self, text: str, output_path: str):
        response = self.client.audio.speech.create(
            model="tts-1-hd",
            voice=self.voice,
            input=text,
        )
        response.stream_to_file(output_path)


class VoiceHandler:
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
        print(f"Loading Whisper model '{model_size}'...")
        self.whisper = WhisperModel(model_size, device="cpu", compute_type="int8")
        self.sample_rate = 16000
        self.music_folder = Path(music_folder)
        self.music_volume = music_volume
        self.music_file = music_file

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
        segments, info = self.whisper.transcribe(audio_path, beam_size=5)
        text = " ".join([segment.text for segment in segments])
        return text.strip()

    def _get_random_music(self) -> Path | None:
        if not self.music_folder.exists():
            return None

        if self.music_file:
            specific_path = self.music_folder / self.music_file
            if specific_path.exists():
                return specific_path

        music_files = list(self.music_folder.glob("*.mp3")) + list(
            self.music_folder.glob("*.wav")
        )
        if not music_files:
            return None

        return random.choice(music_files)
        
    def _mix_with_music(self, speech_path: str, output_path: str):
        speech = AudioSegment.from_file(speech_path)

        # If music disabled → just export clean speech
        if not hasattr(self, "music_volume") or self.music_volume <= 0:
            speech.export(output_path, format="mp3", bitrate="192k")
            return

        music_file = self._get_random_music()
        if not music_file:
            speech.export(output_path, format="mp3", bitrate="192k")
            return

        music = AudioSegment.from_file(str(music_file))

        # ---- SAFE NORMALIZATION ----
        speech = speech.normalize(headroom=1.0)
        music = music.normalize(headroom=1.0)

        # Clamp volume between 0–1
        vol = max(0.0, min(1.0, float(self.music_volume)))

        # Map volume to a SAFE range: music stays -28dB → -18dB under voice
        music_gain = -28 + (vol * 10)
        music = music + music_gain

        # Match length
        if len(music) < len(speech):
            repeats = (len(speech) // len(music)) + 1
            music = music * repeats

        music = music[: len(speech)]

        # Gentle fades to kill bass pops
        music = music.fade_in(1200).fade_out(2000)

        # ---- SAFE OVERLAY WITH HEADROOM ----
        mixed = speech.overlay(
            music,
            gain_during_overlay=-2  # prevents clipping
        )

        # Final limiter-style normalize
        mixed = mixed.normalize(headroom=0.8)

        mixed.export(output_path, format="mp3", bitrate="192k")

    def speak(self, text: str):
        temp_speech = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        temp_speech.close()

        self.tts.generate(text, temp_speech.name)

        temp_mixed = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        temp_mixed.close()

        try:
            self._mix_with_music(temp_speech.name, temp_mixed.name)

            if os.name == "posix":
                subprocess.run(["afplay", temp_mixed.name], check=True)
            else:
                subprocess.run(
                    [
                        "powershell",
                        "-c",
                        f"(New-Object Media.SoundPlayer '{temp_mixed.name}').PlaySync()",
                    ],
                    check=True,
                )
        finally:
            Path(temp_speech.name).unlink(missing_ok=True)
            Path(temp_mixed.name).unlink(missing_ok=True)

    def listen(self, duration: int = 5) -> str:
        audio_path = self.record_audio(duration)
        try:
            text = self.transcribe(audio_path)
            return text
        finally:
            Path(audio_path).unlink(missing_ok=True)
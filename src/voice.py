import asyncio
import atexit
import os
import random
import re
import select
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import edge_tts
import numpy as np
import sounddevice as sd
import soundfile as sf
from groq import Groq


# Pre-compiled patterns for speed
ELLIPSIS_PATTERN = re.compile(r'\.{2,}')
SENTENCE_END_PATTERN = re.compile(r'[.!?]\s')


def clean_for_tts(text: str) -> str:
    """Remove markdown and special chars that break TTS"""
    text = text.replace("*", "").replace("\n", " ")
    for char in "<>=/#_`":
        text = text.replace(char, "")
    return text.strip()


class VoiceHandler:
    def __init__(
        self,
        voice: str = "en-IN-PrabhatNeural",
        music_folder: str = "./music",
        music_enabled: bool = True,
        music_volume: float = 0.2,
        music_file: str = None,
        groq_api_key: str = None,
    ):
        self.voice = voice
        self.sample_rate = 16000
        self.groq = Groq(api_key=groq_api_key) if groq_api_key else None

        # Music config
        self.music_folder = Path(music_folder)
        self.music_enabled = music_enabled
        self.music_volume = music_volume
        self.music_file = music_file
        self._music_proc = None
        self._stop_music = False

        # Speech state
        self._speech_proc = None
        self._stop_streaming = False

        # Start music if enabled
        self._selected_music = self._pick_music() if music_enabled else None
        if self._selected_music:
            threading.Thread(target=self._music_loop, daemon=True).start()

        atexit.register(self.cleanup)

    def cleanup(self):
        """Stop all audio on exit"""
        self._stop_music = True
        self.stop_speaking()
        if self._music_proc and self._music_proc.poll() is None:
            self._music_proc.terminate()

    def stop_speaking(self):
        """Stop current speech"""
        self._stop_streaming = True
        if self._speech_proc and self._speech_proc.poll() is None:
            self._speech_proc.terminate()

    def _pick_music(self) -> Path | None:
        """Pick music file (specific or random)"""
        if not self.music_folder.exists():
            return None
        if self.music_file:
            path = self.music_folder / self.music_file
            if path.exists():
                return path
        files = list(self.music_folder.glob("*.mp3")) + list(self.music_folder.glob("*.wav"))
        return random.choice(files) if files else None

    def _music_loop(self):
        """Play background music, rotating through tracks (or loop one if specified)"""
        if self.music_file:
            # Specific file set - loop it
            tracks = [self._selected_music]
        else:
            # Shuffle all tracks
            tracks = list(self.music_folder.glob("*.mp3")) + list(self.music_folder.glob("*.wav"))
            if not tracks:
                return
            random.shuffle(tracks)
        idx = 0
        while not self._stop_music:
            self._music_proc = subprocess.Popen(
                ["afplay", "-v", str(self.music_volume), str(tracks[idx])],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_IGN)
            )
            self._music_proc.wait()
            idx = (idx + 1) % len(tracks)

    def transcribe(self, audio_path: str) -> str:
        """Speech-to-text via Groq Whisper"""
        if not self.groq:
            raise ValueError("Groq API key required")
        with open(audio_path, "rb") as f:
            result = self.groq.audio.transcriptions.create(
                file=f,
                model="whisper-large-v3-turbo",
                response_format="text",
            )
        return result.strip()

    def _generate_tts(self, text: str, output_path: str):
        """Generate TTS audio file"""
        cleaned = clean_for_tts(text)
        if len(cleaned) < 2:
            return False
        asyncio.run(edge_tts.Communicate(cleaned, self.voice).save(output_path))
        return True

    def _play_audio(self, path: str, interrupt_check=None):
        """Play audio file, optionally interruptible"""
        self._speech_proc = subprocess.Popen(["afplay", path])
        while self._speech_proc.poll() is None:
            if self._stop_streaming:
                self._speech_proc.terminate()
                break
            if interrupt_check and interrupt_check():
                self._stop_streaming = True
                self._speech_proc.terminate()
                break
            time.sleep(0.05)

    def speak(self, text: str):
        """Generate and play TTS (non-blocking)"""
        def _run():
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
            tmp.close()
            try:
                if self._generate_tts(text, tmp.name):
                    self._play_audio(tmp.name)
            finally:
                Path(tmp.name).unlink(missing_ok=True)
        threading.Thread(target=_run, daemon=True).start()

    def speak_streaming(self, text_generator, interrupt_check=None, print_live=True):
        """Stream text and speak sentences as they complete"""
        self._stop_streaming = False
        full_text = ""
        buffer = ""

        def extract_sentence(text):
            """Get first complete sentence"""
            temp = ELLIPSIS_PATTERN.sub('…', text)  # Protect ...
            match = SENTENCE_END_PATTERN.search(temp)
            if match:
                pos = match.end()
                return text[:pos].strip(), text[pos:]
            return None, text

        def speak_sentence(sentence):
            if len(clean_for_tts(sentence)) < 3:
                return
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
            tmp.close()
            try:
                if self._generate_tts(sentence, tmp.name):
                    self._play_audio(tmp.name, interrupt_check)
            finally:
                Path(tmp.name).unlink(missing_ok=True)

        for chunk in text_generator:
            if self._stop_streaming:
                break
            if interrupt_check and interrupt_check():
                self._stop_streaming = True
                break

            full_text += chunk
            buffer += chunk

            if print_live:
                print(chunk, end="", flush=True)

            while True:
                if self._stop_streaming:
                    break
                sentence, buffer = extract_sentence(buffer)
                if sentence:
                    speak_sentence(sentence)
                else:
                    break

        # Speak remaining text
        if buffer.strip() and not self._stop_streaming:
            speak_sentence(buffer.strip())

        return full_text

    def record_until_space(self) -> str | None:
        """Record audio until spacebar. Returns temp file path."""
        chunks = []
        chunk_size = int(self.sample_rate * 0.1)

        stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype=np.float32,
            blocksize=chunk_size
        )

        with stream:
            while len(chunks) < 600:  # Max 60 seconds
                if select.select([sys.stdin], [], [], 0)[0]:
                    if sys.stdin.read(1) == ' ':
                        break
                chunk, _ = stream.read(chunk_size)
                chunks.append(chunk.copy())

        if not chunks:
            return None

        audio = np.concatenate(chunks)
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        tmp.close()
        sf.write(tmp.name, audio, self.sample_rate)
        return tmp.name

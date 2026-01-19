import asyncio
import atexit
import os
import random
import re
import select
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


def to_spoken_style(text: str) -> str:
    """Clean text for TTS"""
    text = text.replace("*", "").replace("\n", " ")
    for char in ["<", ">", "=", "/", "break", "time", "ms", "#", "_", "`"]:
        text = text.replace(char, "")
    return text.strip()


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
        tts_provider: str = "edge",
        voice: str = "en-IN-PrabhatNeural",
        music_folder: str = "./music",
        music_volume: float = 0.2,
        music_file: str = None,
        groq_api_key: str = None,
    ):
        self.sample_rate = 16000
        self.groq_client = Groq(api_key=groq_api_key) if groq_api_key else None

        self.music_folder = Path(music_folder)
        self.music_volume = music_volume
        self.music_file = music_file

        # Track subprocesses for cleanup
        self._music_process = None
        self._stop_music = False
        self._speech_processes = []
        self._current_speech_proc = None  # Track current speech for interruption
        self._is_speaking = False
        self._stop_streaming = False  # Flag to abort streaming TTS

        # TTS
        if tts_provider == "edge":
            self.tts = EdgeTTSProvider(voice)
        else:
            raise ValueError(f"Unknown TTS provider: {tts_provider}")

        # Register cleanup on exit
        atexit.register(self.cleanup)

        # Pick music once at start (keeps same song for whole session)
        self._selected_music = self._get_music_file()

        # Start background music immediately
        self.music_thread = threading.Thread(target=self._play_music_loop, daemon=True)
        self.music_thread.start()

    def cleanup(self):
        """Stop music and cleanup processes on exit"""
        self._stop_music = True
        self.stop_speaking()
        if self._music_process and self._music_process.poll() is None:
            self._music_process.terminate()
            try:
                self._music_process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self._music_process.kill()
        for proc in self._speech_processes:
            if proc and proc.poll() is None:
                proc.terminate()

    def stop_speaking(self):
        """Immediately stop any ongoing speech and pending TTS"""
        self._is_speaking = False
        self._stop_streaming = True  # Flag to stop streaming TTS

        if self._current_speech_proc and self._current_speech_proc.poll() is None:
            self._current_speech_proc.terminate()
            try:
                self._current_speech_proc.wait(timeout=0.5)
            except:
                self._current_speech_proc.kill()
            self._current_speech_proc = None

        # Kill all speech processes
        for proc in self._speech_processes[:]:
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=0.5)
                except:
                    proc.kill()
        self._speech_processes.clear()

    def _get_music_file(self) -> Path | None:
        if not self.music_folder.exists():
            return None
        if self.music_file:
            specific = self.music_folder / self.music_file
            if specific.exists():
                return specific
        files = list(self.music_folder.glob("*.mp3")) + list(self.music_folder.glob("*.wav"))
        return random.choice(files) if files else None

    def _play_music_loop(self):
        import signal
        while not self._stop_music:
            if not self._selected_music:
                return
            if os.name == "posix":
                # Start music process, ignore SIGINT so Ctrl+C doesn't kill it
                self._music_process = subprocess.Popen(
                    ["afplay", "-v", str(self.music_volume), str(self._selected_music)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_IGN)
                )
                self._music_process.wait()
            else:
                self._music_process = subprocess.Popen(
                    ["powershell", "-c", f"(New-Object Media.SoundPlayer '{self._selected_music}').PlaySync()"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                self._music_process.wait()

    def transcribe(self, audio_path: str) -> str:
        """Transcribe audio using Groq Whisper API"""
        if not self.groq_client:
            raise ValueError("Groq API key required for transcription")

        with open(audio_path, "rb") as audio_file:
            transcription = self.groq_client.audio.transcriptions.create(
                file=audio_file,
                model="whisper-large-v3-turbo",
                response_format="text",
            )
        return transcription.strip()

    def speak(self, text: str):
        """Generate TTS and play non-blocking"""
        def _speak_thread():
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
            temp_file.close()
            self.tts.generate_stream_to_file(text, temp_file.name)

            if os.name == "posix":
                proc = subprocess.Popen(["afplay", temp_file.name])
            else:
                proc = subprocess.Popen(
                    ["powershell", "-c", f"(New-Object Media.SoundPlayer '{temp_file.name}').PlaySync()"]
                )
            self._speech_processes.append(proc)
            self._current_speech_proc = proc
            self._is_speaking = True
            proc.wait()
            self._is_speaking = False
            Path(temp_file.name).unlink(missing_ok=True)

        threading.Thread(target=_speak_thread, daemon=True).start()

    def speak_streaming(self, text_generator, interrupt_check=None):
        """Stream text to TTS, playing sentences as they complete."""
        self._stop_streaming = False
        full_text = ""
        buffer = ""
        queued_sentences = []

        def queue_tts(sentence):
            """Generate TTS in background, add to queue"""
            if len(to_spoken_style(sentence)) < 3:
                return
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
            temp_file.close()
            try:
                self.tts.generate_stream_to_file(sentence, temp_file.name)
                queued_sentences.append(temp_file.name)
            except Exception:
                Path(temp_file.name).unlink(missing_ok=True)

        def extract_sentence(text):
            """Extract first complete sentence if exists, return (sentence, remaining)"""
            # Collapse ... to single char for splitting
            temp = re.sub(r'\.{2,}', '…', text)
            # Find sentence end followed by space
            match = re.search(r'[.!?]\s', temp)
            if match:
                pos = match.end()
                sentence = text[:pos].strip()
                remaining = text[pos:]
                return sentence, remaining
            return None, text

        # Collect full text and queue sentences as they complete
        for chunk in text_generator:
            if self._stop_streaming:
                break
            if interrupt_check and interrupt_check():
                self._stop_streaming = True
                break

            full_text += chunk
            buffer += chunk

            # Extract and queue complete sentences
            while True:
                sentence, buffer = extract_sentence(buffer)
                if sentence:
                    threading.Thread(target=queue_tts, args=(sentence,), daemon=True).start()
                else:
                    break

        # Queue remaining buffer
        if buffer.strip():
            threading.Thread(target=queue_tts, args=(buffer.strip(),), daemon=True).start()

        # Wait a bit for TTS threads to finish
        time.sleep(0.3)

        # Play all queued audio in order
        for audio_path in queued_sentences:
            if self._stop_streaming:
                break
            if interrupt_check and interrupt_check():
                self._stop_streaming = True
                break

            if os.path.exists(audio_path):
                proc = subprocess.Popen(["afplay", audio_path])
                self._current_speech_proc = proc
                self._is_speaking = True

                while proc.poll() is None:
                    if self._stop_streaming or (interrupt_check and interrupt_check()):
                        proc.terminate()
                        break
                    time.sleep(0.05)

                self._is_speaking = False
                Path(audio_path).unlink(missing_ok=True)

        return full_text

    def record_until_space(self) -> str | None:
        """Record audio until spacebar pressed. Returns path to audio file."""
        chunk_duration = 0.1
        chunk_samples = int(self.sample_rate * chunk_duration)
        audio_chunks = []

        stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype=np.float32,
            blocksize=chunk_samples
        )

        with stream:
            while True:
                # Check for spacebar
                if select.select([sys.stdin], [], [], 0)[0]:
                    key = sys.stdin.read(1)
                    if key == ' ':
                        break

                chunk, _ = stream.read(chunk_samples)
                audio_chunks.append(chunk.copy())

                # Safety limit (60 seconds)
                if len(audio_chunks) > 600:
                    break

        if not audio_chunks:
            return None

        audio = np.concatenate(audio_chunks)
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        temp_file.close()
        sf.write(temp_file.name, audio, self.sample_rate)
        return temp_file.name

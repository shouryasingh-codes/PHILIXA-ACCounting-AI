"""
Day 12 (Accuracy Fix): Live Audio Collection Buffer
Simplified: No more chunk-based inference.
Collects full audio silently, writes to WAV on stop,
then passes to existing transcription_service for one-shot accurate transcription.
"""

import asyncio
import os
import tempfile
import wave
import numpy as np
import logging

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000  # Whisper native format


class LiveTranscriptionBuffer:
    """
    Per-WebSocket-connection stateful audio buffer.
    Silently collects all raw PCM audio from the browser.
    On stop: writes full audio to a temp WAV file for one-shot Whisper transcription.
    """

    def __init__(
        self,
        client_names: list[str] | None = None,
        browser_sample_rate: int = 16000,
    ):
        self.audio_chunks: list[np.ndarray] = []
        self.client_names = client_names or []
        self.total_samples: int = 0
        self.browser_sample_rate = browser_sample_rate
        self._lock = asyncio.Lock()

    @staticmethod
    def resample_to_16k(audio: np.ndarray, from_rate: int) -> np.ndarray:
        """Linear interpolation resampling to 16kHz."""
        if from_rate == SAMPLE_RATE:
            return audio
        new_len = int(len(audio) * SAMPLE_RATE / from_rate)
        resampled = np.interp(
            np.linspace(0, len(audio), new_len),
            np.arange(len(audio)),
            audio,
        )
        logger.debug(
            f"Resampled {from_rate}Hz → {SAMPLE_RATE}Hz "
            f"({len(audio)} → {new_len} samples)"
        )
        return resampled.astype(np.float32)

    async def add_chunk(self, pcm_bytes: bytes) -> None:
        """
        Browser AudioWorklet se aaya raw Int16 PCM bytes buffer mein daalo.
        Int16 little-endian → Float32 -1.0 to 1.0 convert karta hai.
        Resampling agar browser sample rate different ho.
        """
        async with self._lock:
            audio_np = (
                np.frombuffer(pcm_bytes, dtype=np.int16)
                .astype(np.float32)
                / 32768.0
            )
            if self.browser_sample_rate != SAMPLE_RATE:
                audio_np = self.resample_to_16k(audio_np, self.browser_sample_rate)
            self.audio_chunks.append(audio_np)
            self.total_samples += len(audio_np)

    async def get_full_audio_wav_path(self) -> str | None:
        """
        Poora collected audio ek temporary WAV file mein likhta hai.
        Returns temp file path (caller must delete after use).
        Returns None agar koi audio nahi mila.
        """
        async with self._lock:
            if not self.audio_chunks or self.total_samples == 0:
                logger.warning("No audio collected — nothing to transcribe.")
                return None

            all_audio = np.concatenate(self.audio_chunks)
            duration = len(all_audio) / SAMPLE_RATE
            logger.info(f"Full audio collected: {duration:.1f}s ({self.total_samples} samples)")

            # Float32 → Int16 for WAV
            audio_int16 = (all_audio * 32767).astype(np.int16)

            # Write to temp WAV file
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
            tmp_path = tmp.name
            tmp.close()

            with wave.open(tmp_path, "wb") as wf:
                wf.setnchannels(1)           # Mono
                wf.setsampwidth(2)           # 16-bit = 2 bytes
                wf.setframerate(SAMPLE_RATE) # 16000 Hz
                wf.writeframes(audio_int16.tobytes())

            logger.info(f"WAV written to temp file: {tmp_path}")
            return tmp_path

import abc
import asyncio
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

class LiveTranscriptionSession(abc.ABC):
    """Unified interface for real-time and local audio processing."""
    
    @abc.abstractmethod
    async def add_chunk(self, pcm_bytes: bytes) -> None:
        pass

    @abc.abstractmethod
    async def finish(self) -> str:
        pass

    async def close(self) -> None:
        """Release a cancelled session without interpreting unfinished audio."""
        pass


class LocalTranscriptionSession(LiveTranscriptionSession):
    def __init__(self, client_names: list[str], sample_rate: int, diarize: bool):
        from app.services.live_transcription_service import LiveTranscriptionBuffer
        self.buffer = LiveTranscriptionBuffer(client_names=client_names, browser_sample_rate=sample_rate)
        self.client_names = client_names
        self.diarize = diarize

    async def initialize(self) -> None:
        # Local buffer doesn't need async startup
        pass

    async def add_chunk(self, pcm_bytes: bytes) -> None:
        await self.buffer.add_chunk(pcm_bytes)

    async def finish(self) -> str:
        wav_path = await self.buffer.get_full_audio_wav_path()
        transcript = ""
        if wav_path:
            try:
                from app.services.transcription_service import transcription_service
                transcript = await asyncio.to_thread(
                    transcription_service.transcribe_audio,
                    wav_path,
                    self.client_names,
                    self.diarize,
                )
                logger.info(f"Local Transcription complete: {len(transcript)} chars")
            except Exception as exc:
                logger.error(f"Local Transcription error: {exc}")
            finally:
                if os.path.exists(wav_path):
                    os.remove(wav_path)
                    logger.info(f"Temp WAV deleted: {wav_path}")
        return transcript.strip()


class DeepgramTranscriptionSession(LiveTranscriptionSession):
    def __init__(self, api_key: str, sample_rate: int, diarize: bool):
        from deepgram import DeepgramClient
        self.deepgram = DeepgramClient(api_key=api_key)
        self.dg_connection = self.deepgram.listen.asynclive.v("1")
        self.sample_rate = sample_rate
        self.diarize = diarize
        self.transcript_buffer = []
        self.is_finished = False
        self.finalized = asyncio.Event()
        self.keepalive_task = None

    async def initialize(self) -> None:
        from deepgram import LiveTranscriptionEvents, LiveOptions
        
        async def on_message(self_conn, result, **kwargs):
            try:
                if result.channel and result.channel.alternatives:
                    sentence = result.channel.alternatives[0].transcript
                    if sentence and result.is_final:
                        self.transcript_buffer.append(sentence)
                    if getattr(result, "from_finalize", False):
                        self.finalized.set()
            except Exception as e:
                logger.error(f"Deepgram message parsing error: {e}")

        async def on_error(self_conn, error, **kwargs):
            logger.error(f"Deepgram Error: {error}")

        async def on_close(self_conn, close, **kwargs):
            logger.info("Deepgram Connection Closed")

        self.dg_connection.on(LiveTranscriptionEvents.Transcript, on_message)
        self.dg_connection.on(LiveTranscriptionEvents.Error, on_error)
        self.dg_connection.on(LiveTranscriptionEvents.Close, on_close)

        options = LiveOptions(
            model="nova-3",
            language="hi", # Use Hindi model for perfect Hinglish transcription
            smart_format=True,
            endpointing=300, # Fix for nova-3 timeout: Force finalization on 300ms pause
            encoding="linear16",
            channels=1,
            sample_rate=self.sample_rate,
            diarize=self.diarize,
            interim_results=False # We only need finalized sentences for the buffer
        )
        
        success = await self.dg_connection.start(options)
        if not success:
            logger.error("Failed to connect to Deepgram")
            raise RuntimeError("Deepgram connection failed")

        # Start a background keepalive task to prevent net0001 timeout during silence
        self.keepalive_task = asyncio.create_task(self._keepalive_loop())

    async def _keepalive_loop(self) -> None:
        while not self.is_finished:
            await asyncio.sleep(5)
            if not self.is_finished:
                try:
                    if hasattr(self.dg_connection, 'keep_alive'):
                        await self.dg_connection.keep_alive()
                except Exception as e:
                    logger.debug(f"Deepgram keepalive error: {e}")

    async def add_chunk(self, pcm_bytes: bytes) -> None:
        if not hasattr(self, 'raw_audio_buffer'):
            self.raw_audio_buffer = bytearray()
        self.raw_audio_buffer.extend(pcm_bytes)
        
        if not self.is_finished:
            try:
                await self.dg_connection.send(pcm_bytes)
            except Exception as e:
                logger.error(f"Error sending bytes to Deepgram: {e}")

    async def finish(self) -> str:
        try:
            # Explicitly flush queued audio before closing the provider socket.
            await self.dg_connection.finalize()
            try:
                await asyncio.wait_for(self.finalized.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass
        finally:
            await self.close()
        return " ".join(self.transcript_buffer).strip()

    async def close(self) -> None:
        if self.is_finished:
            return
        self.is_finished = True
        if self.keepalive_task:
            self.keepalive_task.cancel()
            try:
                await self.keepalive_task
            except asyncio.CancelledError:
                pass
        await self.dg_connection.finish()

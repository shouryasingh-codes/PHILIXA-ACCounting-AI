import logging
import os
import torch
import soundfile as sf

try:
    import torchaudio
except ImportError:
    torchaudio = None

# torchaudio will automatically fall back to soundfile if torchcodec is uninstalled

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None

try:
    from pyannote.audio import Pipeline
except ImportError:
    Pipeline = None

from app.core.config import get_settings

logger = logging.getLogger(__name__)

class TranscriptionService:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(TranscriptionService, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        
        settings = get_settings()
        
        # 1. Load Whisper
        model_size = 'large-v3-turbo'
        logger.info(f'Loading faster-whisper model {model_size} in int8 mode...')
        try:
            if WhisperModel is not None:
                self.model = WhisperModel(model_size, device='cpu', compute_type='int8')
                logger.info('WhisperModel loaded successfully.')
            else:
                self.model = None
                logger.warning('faster_whisper not installed; WhisperModel disabled.')
        except Exception as e:
            logger.error(f'Failed to load WhisperModel: {e}')
            self.model = None

        # 2. Load PyAnnote Diarization Pipeline
        logger.info('Loading PyAnnote Diarization Pipeline...')
        try:
            if not settings.hf_token or Pipeline is None:
                logger.warning('No HF_TOKEN found or pyannote not installed! Diarization will be disabled.')
                self.diarization_pipeline = None
            else:
                os.environ["HF_TOKEN"] = settings.hf_token
                self.diarization_pipeline = Pipeline.from_pretrained(
                    "pyannote/speaker-diarization-3.1"
                )
                if self.diarization_pipeline is None:
                    logger.error("Failed to initialize PyAnnote pipeline (Auth token might be invalid).")
                else:
                    if torch is not None:
                        device = torch.device("cpu")
                        self.diarization_pipeline.to(device)
                    logger.info('PyAnnote Pipeline loaded successfully.')
        except Exception as e:
            logger.error(f'Failed to load PyAnnote: {e}')
            self.diarization_pipeline = None

        self._initialized = True

    def _get_speaker_for_segment(self, start: float, end: float, diarization) -> str:
        if not diarization:
            return "Speaker"
            
        # In PyAnnote 3.1, the output is a DiarizeOutput object, we need its 'speaker_diarization' attribute
        if hasattr(diarization, "speaker_diarization"):
            diarization_annotation = diarization.speaker_diarization
        else:
            diarization_annotation = diarization
            
        max_intersection = 0
        best_speaker = "Unknown"
        
        for turn, _, speaker in diarization_annotation.itertracks(yield_label=True):
            intersection = min(end, turn.end) - max(start, turn.start)
            if intersection > max_intersection:
                max_intersection = intersection
                best_speaker = speaker
                
        return best_speaker

    def _build_initial_prompt(self, client_names: list[str] | None) -> str:
        """Builds a dynamic Whisper initial_prompt injecting known client names
        to prevent phonetic hallucinations on Indian names."""
        base = (
            "This is a financial meeting discussing business loans in Hinglish. "
            "Words: loan, crore, Monday, cancel, deal, HDFC, bank, client."
        )
        if client_names:
            names_str = ", ".join(client_names[:20])  # cap at 20 to stay within prompt limit
            return f"{base} Names: {names_str}."
        return base

    def transcribe_audio(self, file_path: str, client_names: list[str] | None = None, diarize: bool = True) -> str:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f'Audio file not found at {file_path}')

        logger.info(f'Starting transcription for {file_path}')
        normalized_audio_path = None
        try:
            # Normalize every browser/phone recording before recognition.  This
            # removes container/codec differences between m4a, mp3 and wav and
            # gives Whisper one predictable, speech-friendly input format.
            import subprocess
            import tempfile

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_wav:
                normalized_audio_path = temp_wav.name
            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", file_path,
                    "-af", "afftdn=nf=-30,highpass=f=200,lowpass=f=3000",
                    "-vn", "-ac", "1", "-ar", "16000",
                    "-c:a", "pcm_s16le", normalized_audio_path,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )

            # PHILIXA's V1 target recordings are Hindi/Hinglish meetings.
            # Automatic detection can select Urdu for spoken Hindi and make
            # Indian client names harder for the extraction model to match.
            # Keep Hindi recognition, but never translate: the original
            # transcript remains evidence for the downstream extractor.
            segments_generator, info = self.model.transcribe(
                normalized_audio_path,
                beam_size=5,
                language=None,   # Auto-detect: Hinglish ke liye best — Monday/names English mein, Hindi sentences Hindi mein
                task="transcribe",
                condition_on_previous_text=False,
                vad_filter=True,
                vad_parameters=dict(threshold=0.5, min_speech_duration_ms=250, min_silence_duration_ms=500, speech_pad_ms=400),
                initial_prompt=self._build_initial_prompt(client_names)
            )
            logger.info(f'Detected language {info.language} with probability {info.language_probability}')
            segments = list(segments_generator)
            
            # 2. PyAnnote Diarization (only if diarize=True)
            diarization = None
            if diarize and self.diarization_pipeline:
                logger.info('Running PyAnnote Diarization on normalized audio...')
                # Bypass torchaudio/torchcodec by using soundfile directly
                waveform_np, sample_rate = sf.read(normalized_audio_path)
                if waveform_np.ndim == 1:
                    waveform_np = waveform_np[:, None]
                waveform = torch.from_numpy(waveform_np).T.float()
                
                diarization = self.diarization_pipeline({"waveform": waveform, "sample_rate": sample_rate})
            elif not diarize:
                logger.info('Diarization skipped (Solo mode — single speaker).')
            
            # 3. Merge Logic
            transcript_text = ''
            for segment in segments:
                if segment.no_speech_prob > 0.6 and segment.avg_logprob < -1.0:
                    continue
                if segment.compression_ratio > 2.4:
                    continue
                if diarize and diarization:
                    # Meeting mode — speaker labels lagao
                    speaker = self._get_speaker_for_segment(segment.start, segment.end, diarization)
                    transcript_text += f"[{speaker}]: {segment.text.strip()}\n"
                else:
                    # Solo mode — sirf clean text, koi prefix nahi
                    transcript_text += f"{segment.text.strip()}\n"
                
            final_text = transcript_text.strip()
            logger.info('Transcription & Diarization completed.')
            return final_text
            
        except Exception as e:
            logger.error(f'Transcription/Diarization failed: {e}')
            raise
        finally:
            if normalized_audio_path and os.path.exists(normalized_audio_path):
                os.remove(normalized_audio_path)

# Singleton instance
transcription_service = TranscriptionService()

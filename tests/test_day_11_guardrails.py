import os
import tempfile
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

# ------------------------------------------------------------------
# CRITICAL: Mock heavy ML libraries BEFORE importing application code.
# This prevents downloading/loading large models during unit tests.
# ------------------------------------------------------------------
import sys
sys.modules['faster_whisper'] = MagicMock()
sys.modules['pyannote.audio'] = MagicMock()

# Now it is safe to import app modules
from app.services.transcription_service import transcription_service
from app.jobs.transcription_jobs import process_meeting_transcription
from app.models.enums import MeetingStatus
from app.models.meeting import Meeting


class MockSegment:
    """Mock implementation of faster_whisper.Segment for testing hallucination gating."""
    def __init__(self, no_speech_prob: float, avg_logprob: float, compression_ratio: float, start: float, end: float, text: str):
        self.no_speech_prob = no_speech_prob
        self.avg_logprob = avg_logprob
        self.compression_ratio = compression_ratio
        self.start = start
        self.end = end
        self.text = text


class MockInfo:
    """Mock implementation of faster_whisper transcription info."""
    language = "hi"
    language_probability = 0.99


@pytest.fixture
def temp_audio_file():
    """Fixture to provide a temporary audio file path for tests."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(b"dummy audio content")
        name = f.name
    yield name
    if os.path.exists(name):
        try:
            os.remove(name)
        except OSError:
            pass


@pytest.mark.asyncio
async def test_hallucination_gating(temp_audio_file):
    """
    Test 1 (Hallucination Gating):
    Verify that segments with high no_speech_prob and low avg_logprob,
    or a high compression_ratio are filtered out correctly by the TranscriptionService.
    """
    # Create mock segments representing different gating scenarios
    mock_segments = [
        # Valid Segment
        MockSegment(0.1, -0.5, 1.5, 0.0, 2.0, "This is valid speech."),
        
        # Hallucination 1: high no_speech_prob (> 0.6) and low avg_logprob (< -1.0)
        MockSegment(0.8, -1.2, 1.5, 2.0, 4.0, "Thank you for watching."),
        
        # Hallucination 2: high compression ratio (> 2.4)
        MockSegment(0.1, -0.5, 2.6, 4.0, 6.0, "repeatrepeatrepeatrepeat"),
        
        # Valid Segment
        MockSegment(0.2, -0.8, 1.8, 6.0, 8.0, "This is also valid.")
    ]
    
    mock_transcribe = MagicMock()
    mock_transcribe.return_value = (iter(mock_segments), MockInfo())
    
    # Apply mocks to the transcription service singleton
    transcription_service.model = MagicMock()
    transcription_service.model.transcribe = mock_transcribe
    transcription_service.diarization_pipeline = None  # Disable diarization
    
    # Mock subprocess.run to bypass ffmpeg normalization
    with patch("subprocess.run") as mock_subprocess:
        mock_subprocess.return_value = MagicMock(returncode=0)
        
        # Execute the method under test
        final_text = transcription_service.transcribe_audio(temp_audio_file)
        
        # Verify the filtered results
        assert "This is valid speech." in final_text, "Valid segment should be included"
        assert "This is also valid." in final_text, "Valid segment should be included"
        
        # Hallucinated segments should be explicitly excluded
        assert "Thank you for watching." not in final_text, "Segment with high no_speech_prob/low logprob should be gated out"
        assert "repeatrepeatrepeatrepeat" not in final_text, "Segment with high compression_ratio should be gated out"
        
        # We expect exactly 2 lines (since 2 valid segments remain)
        lines = [line for line in final_text.split('\n') if line.strip()]
        assert len(lines) == 2, f"Expected 2 lines, got {len(lines)}"


@pytest.mark.asyncio
async def test_arq_ml_error_boundary(temp_audio_file):
    """
    Test 2 (ARQ ML Error Boundary):
    Verify that an ML exception (like OOM) raised during `transcribe_audio` is caught gracefully,
    does NOT trigger ARQ Retry exceptions, and sets the meeting status to MANUAL_REVIEW_REQUIRED.
    """
    # 1. Setup mock meeting
    mock_meeting = MagicMock(spec=Meeting)
    mock_meeting.id = 123
    mock_meeting.organization_id = None
    mock_meeting.user_id = None
    mock_meeting.status = MeetingStatus.QUEUED.value
    mock_meeting.raw_notes = None

    # Setup mock DB session and factory
    mock_session = AsyncMock()
    # Handle the db.execute(stmt).scalar_one_or_none() chain
    mock_session.execute.return_value.scalar_one_or_none.return_value = mock_meeting
    
    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__.return_value = mock_session

    # Setup ARQ job context
    ctx = {
        "job_try": 1,
        "max_tries": 3,
        "db_session_factory": mock_session_factory
    }

    # 2. Patch dependencies
    with patch("app.jobs.transcription_jobs.minio_service.get_audio_file_stream") as mock_minio, \
         patch("app.jobs.transcription_jobs.transcription_service.transcribe_audio") as mock_transcribe, \
         patch("app.jobs.transcription_jobs._notify_meeting_processed") as mock_notify:
         
        # Mock MinIO stream download
        mock_stream = MagicMock()
        mock_stream.stream.return_value = [b"dummy audio chunks"]
        mock_minio.return_value = mock_stream
        
        # Simulate a fatal ML Error during transcription (e.g., CUDA OOM)
        mock_transcribe.side_effect = RuntimeError("CUDA out of memory")
        
        # 3. Execute job
        result = await process_meeting_transcription(ctx, meeting_id=123, audio_file_path="mock/path.wav")
        
        # 4. Assertions
        
        # Ensure job completed safely and returned False (did not crash or raise Retry)
        assert result is False, "Job should return False upon ML error"
        
        # Verify state mutation for manual review
        assert mock_meeting.status == MeetingStatus.MANUAL_REVIEW_REQUIRED.value, "Meeting status must be updated to MANUAL_REVIEW_REQUIRED"
        assert "[ML/Processing Error]" in mock_meeting.raw_notes, "Error note should be appended"
        assert "CUDA out of memory" in mock_meeting.raw_notes, "Original exception message should be logged in raw_notes"
        
        # Verify db commit was called appropriately (once for TRANSCRIBING, once for MANUAL_REVIEW_REQUIRED)
        assert mock_session.commit.call_count >= 2, "Session commit should be called for state updates"
        
        # Verify notification was dispatched for failure
        mock_notify.assert_called_once_with(
            mock_session, 123, client_name=None, success=False, organization_id="default", user_id=None
        )

from sqlalchemy.ext.asyncio import AsyncSession
import asyncio
import logging
from datetime import date
from typing import Any

from pydantic import ValidationError

from app.ai.provider import AIExtractionError, get_ai_provider, ExtractionResult
from app.core.config import Settings
from app.models.ai_extraction_log import AIExtractionLog
from app.schemas.ai_extraction import MeetingExtraction
from app.services.json_utils import to_json

logger = logging.getLogger(__name__)

class AIRoutingService:
    def __init__(self, db: AsyncSession, settings: Settings):
        self.db = db
        self.settings = settings

    async def route_and_extract(self, raw_notes: str, meeting_date: date, meeting_id: int) -> dict[str, Any]:
        """
        Executes the Economy -> Review escalation path.
        Returns the validated raw payload dict if successful.
        Raises AIExtractionError if BOTH models fail.
        """
        
        # Pre-processing: LLM Translation Layer to normalize Hinglish to English
        clean_notes = raw_notes
        try:
            trans_provider = get_ai_provider(self.settings.ai_economy_provider, self.settings)
            logger.info("Starting LLM pre-processing translation layer (Economy)...")
            clean_notes = await asyncio.to_thread(trans_provider.translate_transcript, raw_notes)
            
            if not clean_notes or len(clean_notes.strip()) < 5:
                raise ValueError("Economy translation returned empty or invalid string.")
        except Exception as e:
            logger.warning(f"Economy translation failed: {e}. Escalating to Review Provider for translation.")
            try:
                review_provider = get_ai_provider(self.settings.ai_review_provider, self.settings)
                logger.info("Starting LLM pre-processing translation layer (Review)...")
                clean_notes = await asyncio.to_thread(review_provider.translate_transcript, raw_notes)
                if not clean_notes or len(clean_notes.strip()) < 5:
                    raise ValueError("Review translation returned empty or invalid string.")
            except Exception as e2:
                logger.warning(f"Review translation failed: {e2}. Falling back to raw notes.")
                clean_notes = raw_notes

        # Attempt 1: Economy Model
        try:
            result = await self._call_and_validate(clean_notes, meeting_date, self.settings.ai_economy_provider, self.settings.ai_economy_model, meeting_id)
            return result.payload
        except (AIExtractionError, ValidationError) as e:
            logger.warning(f"Economy model failed: {e}. Escalating to Review model.")

        # Attempt 2: Escalation to Review Model
        try:
            result = await self._call_and_validate(clean_notes, meeting_date, self.settings.ai_review_provider, self.settings.ai_review_model, meeting_id)
            return result.payload
        except (AIExtractionError, ValidationError) as e:
            logger.error(f"Review model also failed: {e}. Manual review required.")
            raise AIExtractionError("All AI models failed to produce a valid extraction.") from e

    async def _call_and_validate(self, raw_notes: str, meeting_date: date, provider_name: str, model_name: str, meeting_id: int) -> ExtractionResult:
        try:
            provider = get_ai_provider(provider_name, self.settings)
            result = await asyncio.to_thread(provider.extract_meeting_intelligence, raw_notes, meeting_date, model_name)
            
            payload = result.payload if isinstance(result, ExtractionResult) else result
            # Schema validation check:
            MeetingExtraction.model_validate(payload)
            res_obj = result if isinstance(result, ExtractionResult) else ExtractionResult(payload=payload)

            # Low confidence is fine — client identification service
            # will handle it by showing confirmation panel to user.
            await self._log_audit(meeting_id, provider_name, model_name, res_obj, success=True)
            return res_obj

        except Exception as e:
            # We log failures too!
            err_msg = str(e)
            raw_response = getattr(e, "raw_response", None)
            await self._log_audit(meeting_id, provider_name, model_name, None, success=False, error_msg=err_msg, raw_response=raw_response)
            raise

    async def _log_audit(self, meeting_id: int, provider_name: str, model: str, result: ExtractionResult | None, success: bool, error_msg: str | None = None, raw_response: str | None = None):
        log = AIExtractionLog(
            meeting_id=meeting_id,
            provider=provider_name,
            model=model,
            prompt_version=self.settings.prompt_version,
            # Provider responses may echo raw meeting notes and customer PII.
            # The validated payload remains available for confirmation instead.
            raw_response_json='{"stored": false}',
            parsed_response_json=to_json(result.payload) if result else "{}",
            success=success,
            error_message=error_msg,
            latency_ms=result.latency_ms if result else 0,
            cost_usd=self._calculate_cost(provider_name, model, result) if result else 0.0
        )
        self.db.add(log)
        await self.db.flush()

    def _calculate_cost(self, provider: str, model: str, result: ExtractionResult) -> float:
        if provider == "local":
            return 0.0
        p_tokens = result.prompt_tokens or 0
        c_tokens = result.completion_tokens or 0
        if "flash" in model or "8b" in model:
            return (p_tokens * 0.00001) + (c_tokens * 0.00002)
        return (p_tokens * 0.0001) + (c_tokens * 0.0002)

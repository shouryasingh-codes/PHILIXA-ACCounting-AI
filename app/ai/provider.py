from __future__ import annotations

import json
import re
import socket
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any


@dataclass
class ExtractionResult:
    """Wraps raw AI extraction payload with telemetry metadata."""
    payload: dict[str, Any]
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0

from app.ai.prompts import MEETING_EXTRACTION_SYSTEM_PROMPT
from app.core.config import Settings, get_settings
from app.utils.text_normalization import normalize_text


class AIExtractionError(RuntimeError):
    pass


class AIProvider(ABC):
    provider_name: str
    model_name: str

    @abstractmethod
    def extract_meeting_intelligence(
        self, raw_notes: str, meeting_date: date, model_override: str | None = None
    ) -> ExtractionResult:
        raise NotImplementedError

    @abstractmethod
    def translate_transcript(self, raw_notes: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def generate_json(self, model: str, prompt: str, schema: dict[str, Any]) -> str:
        raise NotImplementedError

    @abstractmethod
    def generate_text(self, model: str, system_prompt: str, user_prompt: str) -> str:
        raise NotImplementedError


class LocalHeuristicProvider(AIProvider):
    provider_name = "local"
    model_name = "local-heuristic-v1"

    def extract_meeting_intelligence(
        self, raw_notes: str, meeting_date: date, model_override: str | None = None
    ) -> ExtractionResult:
        sentences = _split_sentences(raw_notes)
        client_name, client_confidence = _extract_client_name(raw_notes)
        client_email = _extract_email(raw_notes)
        client_whatsapp_phone = _extract_whatsapp_phone(raw_notes)
        products_owned = _extract_products(sentences)
        concerns = _extract_concerns(sentences)
        commitments = _extract_commitments(sentences, meeting_date)
        summary = _make_summary(client_name, sentences, concerns, commitments)
        key_points = _key_points(sentences)

        identification_status = "identified" if client_name else "unknown"
        payload = {
            "client_identification": {
                "status": identification_status,
                "matched_client_id": None,
                "suggested_client_name": client_name,
                "suggested_client_email": client_email,
                "suggested_client_whatsapp_phone": client_whatsapp_phone,
                "confidence": client_confidence,
                "requires_confirmation": not bool(client_name),
            },
            "meeting_summary": summary,
            "key_discussion_points": key_points,
            "products_owned": products_owned,
            "concerns": concerns,
            "commitments": commitments,
            "action_items": [item["description"] for item in commitments],
            "warnings": [] if client_name else ["Client identification required."],
        }
        return ExtractionResult(payload=payload)

    def generate_json(self, model: str, prompt: str, schema: dict[str, Any]) -> str:
        return '{"answer": "Local heuristic provider cannot answer free-form queries.", "source_meetings": []}'

    def generate_text(self, model: str, system_prompt: str, user_prompt: str) -> str:
        return "I am the local heuristic provider and cannot process conversational voice commands."

    def translate_transcript(self, raw_notes: str) -> str:
        return raw_notes


class GroqProvider(AIProvider):
    provider_name = "groq"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model_name = settings.ai_model or "llama-3.1-8b-instant"
        self.base_url = (
            settings.ai_base_url or "https://api.groq.com/openai/v1/chat/completions"
        )

    def extract_meeting_intelligence(
        self, raw_notes: str, meeting_date: date, model_override: str | None = None
    ) -> ExtractionResult:
        import time as _time
        api_key = self.settings.ai_api_key or self.settings.groq_api_key
        if not api_key:
            raise AIExtractionError("Groq provider selected but PHILIXA_AI_API_KEY/PHILIXA_GROQ_API_KEY is missing.")
        model = (model_override or self.model_name).replace("groq/", "")
        from datetime import timedelta
        calendar_ref = {"tomorrow": (meeting_date + timedelta(days=1)).isoformat()}
        for i in range(1, 8):
            day_name = (meeting_date + timedelta(days=i)).strftime("%A").lower()
            calendar_ref[f"next_{day_name}"] = (meeting_date + timedelta(days=i)).isoformat()

        payload = {
            "model": model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": MEETING_EXTRACTION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "meeting_date": f"{meeting_date.isoformat()} ({meeting_date.strftime('%A')})",
                            "calendar_reference": calendar_ref,
                            "raw_notes": raw_notes,
                        }
                    ),
                },
            ],
            "response_format": {"type": "json_object"},
        }
        t0 = _time.monotonic()
        data = _post_json(
            self.base_url,
            payload,
            {"Authorization": f"Bearer {api_key}"},
            timeout_seconds=self.settings.ai_timeout_seconds,
        )
        latency_ms = int((_time.monotonic() - t0) * 1000)
        usage = data.get("usage", {})
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
        return ExtractionResult(
            payload=json.loads(content),
            latency_ms=latency_ms,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
        )

    def generate_json(self, model: str, prompt: str, schema: dict[str, Any]) -> str:
        api_key = self.settings.ai_api_key or self.settings.groq_api_key
        if not api_key:
            raise AIExtractionError("Groq provider selected but API key is missing.")
        
        system_content = "You are a helpful assistant. Return JSON strictly conforming to the requested schema.\nSchema:\n" + json.dumps(schema)
        
        payload = {
            "model": model.replace("groq/", ""),
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": prompt}
            ],
            "response_format": {"type": "json_object"},
        }
        data = _post_json(
            self.base_url,
            payload,
            {"Authorization": f"Bearer {api_key}"},
            timeout_seconds=self.settings.ai_timeout_seconds,
        )
        return data["choices"][0]["message"]["content"]

    def generate_text(self, model: str, system_prompt: str, user_prompt: str) -> str:
        api_key = self.settings.ai_api_key or self.settings.groq_api_key
        if not api_key:
            raise AIExtractionError("Groq provider selected but API key is missing.")
        
        payload = {
            "model": model.replace("groq/", ""),
            "temperature": 0.3,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
        }
        data = _post_json(
            self.base_url,
            payload,
            {"Authorization": f"Bearer {api_key}"},
            timeout_seconds=self.settings.ai_timeout_seconds,
        )
        return data["choices"][0]["message"]["content"]

    def translate_transcript(self, raw_notes: str) -> str:
        api_key = self.settings.ai_api_key or self.settings.groq_api_key
        if not api_key:
            return raw_notes
            
        system_content = (
            "You are an expert transcriber. This is an ASR transcript of a Hinglish business meeting. "
            "It may contain phonetic STT errors (e.g. 'Dil' instead of 'Deal', 'Mande' instead of 'Monday'). "
            "Your ONLY job is to translate this transcript into clean, professional English, correcting any phonetic mistakes based on the business context. "
            "CRITICAL: Preserve Indian names accurately using standard English spelling. Do NOT anglicize names (e.g., if the phonetic Hindi is 'दक्स', write 'Daksh', not 'Dex'). "
            "CRITICAL: Ensure ALL named entities (like competitor banks, companies, people) mentioned in the notes are preserved in the English translation. Do not summarize or omit anything. "
            "CRITICAL: Correct any numerical formatting errors made by STT. For example, if a phone number sequence is misformatted as time (e.g., '106' misformatted as '01:06', or '9196 01:06 2 152'), reconstruct the continuous phone number (e.g. '9196 106 2 152'). "
            "CRITICAL: If an email address is dictated with spaces or phonetic words like 'at the rate', 'dot', combine them into a valid email string without spaces (e.g. 'raj sharma 3937 at the rate gmail dot com' becomes 'rajsharma3937@gmail.com'). "
            "Return ONLY the translated English text, nothing else."
        )
        
        payload = {
            "model": self.model_name.replace("groq/", ""),
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": raw_notes}
            ]
        }
        try:
            data = _post_json(
                self.base_url,
                payload,
                {"Authorization": f"Bearer {api_key}"},
                timeout_seconds=self.settings.ai_timeout_seconds,
            )
            return data.get("choices", [{}])[0].get("message", {}).get("content", raw_notes)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Groq translation failed: {e}")
            return raw_notes


class GeminiProvider(AIProvider):
    provider_name = "gemini"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        # Use ai_review_model (PHILIXA_AI_REVIEW_MODEL) — NOT ai_model which is Groq's model
        self.model_name = settings.ai_review_model or "gemini-2.5-flash"

    def _build_url(self, model: str) -> str:
        api_key = self.settings.gemini_api_key or self.settings.ai_api_key
        return (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={api_key}"
        )

    def extract_meeting_intelligence(
        self, raw_notes: str, meeting_date: date, model_override: str | None = None
    ) -> ExtractionResult:
        import time as _time
        api_key = self.settings.gemini_api_key or self.settings.ai_api_key
        if not api_key:
            raise AIExtractionError("Gemini provider selected but PHILIXA_GEMINI_API_KEY is missing.")
        model = model_override or self.model_name
        url = self._build_url(model)
        from datetime import timedelta
        calendar_ref = {"tomorrow": (meeting_date + timedelta(days=1)).isoformat()}
        for i in range(1, 8):
            day_name = (meeting_date + timedelta(days=i)).strftime("%A").lower()
            calendar_ref[f"next_{day_name}"] = (meeting_date + timedelta(days=i)).isoformat()

        prompt = {
            "system": MEETING_EXTRACTION_SYSTEM_PROMPT,
            "meeting_date": f"{meeting_date.isoformat()} ({meeting_date.strftime('%A')})",
            "calendar_reference": calendar_ref,
            "raw_notes": raw_notes,
        }
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": (
                                "Return strict JSON for this PHILIXA extraction input:\n"
                                + json.dumps(prompt)
                            )
                        }
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": 2048,
                "response_mime_type": "application/json",
            },
        }
        t0 = _time.monotonic()
        data = _post_json(
            url,
            payload,
            {},
            timeout_seconds=self.settings.ai_timeout_seconds,
        )
        latency_ms = int((_time.monotonic() - t0) * 1000)
        try:
            content = data["candidates"][0]["content"]["parts"][0]["text"]
            return ExtractionResult(
                payload=_parse_json_object(content),
                latency_ms=latency_ms,
            )
        except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValueError) as exc:
            raise AIExtractionError("Gemini returned an invalid JSON extraction.") from exc

    def generate_json(self, model: str, prompt: str, schema: dict[str, Any]) -> str:
        api_key = self.settings.gemini_api_key or self.settings.ai_api_key
        if not api_key:
            raise AIExtractionError("Gemini API key is missing.")
        url = self._build_url(model)
        full_prompt = prompt + "\n\nYou MUST return a JSON object that conforms to the following schema:\n" + json.dumps(schema)
        payload = {
            "contents": [{"parts": [{"text": full_prompt}]}],
            "generationConfig": {
                "temperature": 0,
                "response_mime_type": "application/json",
            }
        }
        data = _post_json(
            url,
            payload,
            {},
            timeout_seconds=self.settings.ai_timeout_seconds,
        )
        return data["candidates"][0]["content"]["parts"][0]["text"]

    def generate_text(self, model: str, system_prompt: str, user_prompt: str) -> str:
        api_key = self.settings.gemini_api_key or self.settings.ai_api_key
        if not api_key:
            raise AIExtractionError("Gemini API key is missing.")
        url = self._build_url(model)
        payload = {
            "systemInstruction": {
                "parts": [{"text": system_prompt}]
            },
            "contents": [{"parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": 0.3,
            }
        }
        data = _post_json(
            url,
            payload,
            {},
            timeout_seconds=self.settings.ai_timeout_seconds,
        )
        return data["candidates"][0]["content"]["parts"][0]["text"]

    def translate_transcript(self, raw_notes: str) -> str:
        api_key = self.settings.gemini_api_key or self.settings.ai_api_key
        if not api_key:
            return raw_notes
            
        system_content = (
            "You are an expert transcriber. This is an ASR transcript of a Hinglish business meeting. "
            "It may contain phonetic STT errors (e.g. 'Dil' instead of 'Deal', 'Mande' instead of 'Monday'). "
            "Your ONLY job is to translate this transcript into clean, professional English, correcting any phonetic mistakes based on the business context. "
            "CRITICAL: Preserve Indian names accurately using standard English spelling. Do NOT anglicize names (e.g., if the phonetic Hindi is 'दक्स', write 'Daksh', not 'Dex'). "
            "CRITICAL: Ensure ALL named entities (like competitor banks, companies, people) mentioned in the notes are preserved in the English translation. Do not summarize or omit anything. "
            "CRITICAL: Correct any numerical formatting errors made by STT. For example, if a phone number sequence is misformatted as time (e.g., '106' misformatted as '01:06', or '9196 01:06 2 152'), reconstruct the continuous phone number (e.g. '9196 106 2 152'). "
            "CRITICAL: If an email address is dictated with spaces or phonetic words like 'at the rate', 'dot', combine them into a valid email string without spaces (e.g. 'raj sharma 3937 at the rate gmail dot com' becomes 'rajsharma3937@gmail.com'). "
            "Return ONLY the translated English text, nothing else."
        )
        url = self._build_url(self.model_name)
        payload = {
            "system_instruction": {"parts": [{"text": system_content}]},
            "contents": [{"parts": [{"text": raw_notes}]}],
            "generationConfig": {
                "temperature": 0,
            }
        }
        try:
            data = _post_json(
                url,
                payload,
                {},
                timeout_seconds=self.settings.ai_timeout_seconds,
            )
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Gemini translation failed: {e}")
            return raw_notes


def get_ai_provider(provider_name: str | None = None, settings: Settings | None = None) -> AIProvider:
    """Return the appropriate AIProvider instance.
    
    Args:
        provider_name: Override provider name. If None, reads from settings.ai_provider.
        settings: Optional Settings instance. If None, calls get_settings().
    """
    settings = settings or get_settings()
    name = (provider_name or settings.ai_provider or "local").lower().strip()
    if name == "local":
        return LocalHeuristicProvider()
    if name == "groq":
        return GroqProvider(settings)
    if name == "gemini":
        return GeminiProvider(settings)
    raise AIExtractionError(f"Unsupported AI provider: {name}")


def _post_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    *,
    timeout_seconds: int,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; PhilixaAI/6.0; +https://philixa.ai)",
            **headers,
        },
    )
    retryable_statuses = {429, 500, 502, 503, 504}
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in retryable_statuses or attempt == 2:
                detail = exc.read().decode("utf-8", errors="replace")[:400]
                raise AIExtractionError(
                    f"AI provider request failed: HTTP Error {exc.code}: {exc.reason}. {detail}"
                ) from exc
            retry_after = exc.headers.get("Retry-After")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else 0.8 * (attempt + 1)
            time.sleep(delay)
        except (TimeoutError, socket.timeout) as exc:
            last_error = exc
            raise AIExtractionError(
                f"AI provider timed out after {timeout_seconds} seconds."
            ) from exc
        except urllib.error.URLError as exc:
            last_error = exc
            if isinstance(exc.reason, (TimeoutError, socket.timeout)) or "timed out" in str(exc).lower():
                raise AIExtractionError(
                    f"AI provider timed out after {timeout_seconds} seconds."
                ) from exc
            if attempt == 2:
                raise AIExtractionError(f"AI provider request failed: {exc}") from exc
            time.sleep(0.8 * (attempt + 1))
        except (KeyError, json.JSONDecodeError) as exc:
            raise AIExtractionError(f"AI provider returned invalid response: {exc}") from exc
    raise AIExtractionError(f"AI provider request failed: {last_error}")


def _parse_json_object(content: str) -> dict[str, Any]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        parsed = json.loads(cleaned[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("AI response must be a JSON object.")
    return parsed


def _split_sentences(raw_notes: str) -> list[str]:
    chunks = re.split(r"[\n.!?]+", raw_notes)
    return [chunk.strip() for chunk in chunks if chunk.strip()]


def _extract_client_name(raw_notes: str) -> tuple[str | None, float]:
    patterns = [
        r"(?i:\bmet\s+)([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\b",
        r"(?i:\bwith\s+)([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\b",
        r"(?i:\bclient\s+)([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\b",
    ]
    excluded = {
        "Interested",
        "Concerned",
        "Promised",
        "Asked",
        "Customer",
        "Approval",
        "Documents",
    }
    for pattern in patterns:
        match = re.search(pattern, raw_notes)
        if match:
            name = match.group(1).strip()
            parts = [part for part in name.split() if part not in excluded]
            if parts:
                return " ".join(parts), 0.92 if len(parts) >= 2 else 0.82
    return None, 0.0


def _extract_email(raw_notes: str) -> str | None:
    match = re.search(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", raw_notes, flags=re.I)
    return match.group(0) if match else None


def _extract_whatsapp_phone(raw_notes: str) -> str | None:
    """Extract a phone number only when it is explicitly labelled as mobile or WhatsApp."""
    match = re.search(
        r"\b(?:whatsapp|mobile|phone|number)\s*(?:number)?\s*(?:is|:|-)?\s*(\+?\d[\d\s()-]{7,}\d)",
        raw_notes,
        flags=re.I,
    )
    if not match:
        return None
    value = re.sub(r"[\s()-]", "", match.group(1))
    return value if 8 <= len(value.lstrip("+")) <= 15 else None


def _extract_concerns(sentences: list[str]) -> list[dict[str, Any]]:
    concerns = []
    for sentence in sentences:
        lowered = sentence.lower()
        if any(keyword in lowered for keyword in ["concern", "worried", "issue", "problem"]):
            cleaned = re.sub(r"^(client\s+)?(is\s+)?concerned\s+about\s+", "", sentence, flags=re.I)
            concerns.append(
                {
                    "description": cleaned.strip().rstrip("."),
                    "severity": "medium",
                    "confidence": 0.86,
                }
            )
    return concerns


def _extract_commitments(sentences: list[str], meeting_date: date) -> list[dict[str, Any]]:
    commitments: list[dict[str, Any]] = []
    patterns = [
        r"\bI(?:'ll| will)\s+(.+)",
        r"\bpromised\s+(.+)",
        r"\bwill\s+(send|call|provide|share|update|get|deliver)\s+(.+)",
        r"\bstill\s+need\s+to\s+(.+)",
        r"\bneed\s+to\s+(.+)",
        r"\b(approval\s+(?:status\s+)?update.+)",
    ]
    for sentence in sentences:
        lowered = sentence.lower()
        is_action = any(re.search(pattern, sentence, flags=re.I) for pattern in patterns)
        if "approval" in lowered and "update" in lowered:
            is_action = True
        if not is_action and "wants callback" not in lowered:
            continue
        description = _extract_description(sentence)
        due_date, due_text, due_confidence = _extract_due_date(sentence, meeting_date)
        urgency_level = _infer_urgency(sentence, due_text, due_confidence)
        commitments.append(
            {
                "description": description[:500],
                "owner": "RM",
                "due_date_text": due_text,
                "due_date": due_date.isoformat() if due_date else None,
                "due_date_confidence": due_confidence,
                "urgency_level": urgency_level,
                "status": "pending",
                "confidence": 0.9,
            }
        )
    return _dedupe_local(commitments)


def _extract_description(sentence: str) -> str:
    value = sentence.strip()
    value = re.sub(r"^I(?:'ll| will)\s+", "", value, flags=re.I)
    value = re.sub(r"^promised\s+", "", value, flags=re.I)
    value = re.sub(r"^reminder:\s*", "", value, flags=re.I)
    value = re.sub(r"^still\s+need\s+to\s+", "", value, flags=re.I)
    value = re.sub(r"^need\s+to\s+", "", value, flags=re.I)
    value = re.sub(
        r"\b(by|on|in|next)\s+.+$|\b(tomorrow|soon|later|when possible)\b.*$",
        "",
        value,
        flags=re.I,
    ).strip()
    value = value.rstrip(".")
    if value.lower().startswith("documents"):
        value = "Send documents"
    elif "callback" in value.lower():
        value = "Call client back"
    elif "approval" in value.lower() and "update" in value.lower():
        value = "Provide approval status update"
    elif value:
        value = value[:1].upper() + value[1:]
    return value or "Follow up with client"


def _extract_due_date(sentence: str, meeting_date: date) -> tuple[date | None, str | None, float]:
    lowered = sentence.lower()
    if re.search(r"\bsoon\b|\blater\b|\bsometime next week\b|\bwhen possible\b", lowered):
        return None, _matched_due_text(sentence), 0.3
    if "tomorrow" in lowered:
        return meeting_date + timedelta(days=1), "tomorrow", 0.9
    in_days = re.search(r"\bin\s+(\d+)\s+days?\b", lowered)
    if in_days:
        days = int(in_days.group(1))
        return meeting_date + timedelta(days=days), in_days.group(0), 0.88
    weekdays = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    for word, index in weekdays.items():
        match = re.search(rf"\b((?:by|next|on)\s+)?{word}\b", sentence, flags=re.I)
        if match:
            delta = (index - meeting_date.weekday()) % 7
            if delta == 0:
                delta = 7
            due_text = match.group(0)
            return meeting_date + timedelta(days=delta), due_text, 0.82
    exact = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", sentence)
    if exact:
        try:
            return date.fromisoformat(exact.group(1)), exact.group(1), 0.95
        except ValueError:
            return None, exact.group(1), 0.2
    return None, _matched_due_text(sentence), 0.0


def _matched_due_text(sentence: str) -> str | None:
    match = re.search(
        r"\b(tomorrow|soon|later|sometime next week|when possible|next\s+\w+|by\s+\w+|in\s+\d+\s+days?)\b",
        sentence,
        flags=re.I,
    )
    return match.group(0) if match else None


def _infer_urgency(
    sentence: str,
    due_text: str | None,
    due_confidence: float,
) -> str:
    lowered = sentence.casefold()
    due_lower = (due_text or "").casefold()
    if any(token in lowered for token in ["urgent", "asap", "immediately", "today"]):
        return "high"
    if "tomorrow" in due_lower or "in 1 day" in due_lower:
        return "high"
    if "approval status" in lowered or "callback" in lowered:
        return "high"
    if any(token in due_lower for token in ["by ", "next ", "in 2 days", "in 3 days", "in 4 days", "in 5 days"]):
        return "medium"
    if due_confidence >= 0.75:
        return "medium"
    return "low"


def _extract_products(sentences: list[str]) -> list[str]:
    seen: set[str] = set()
    products: list[str] = []
    catalog = [
        ("business loan", "Business Loan"),
        ("home loan", "Home Loan"),
        ("term insurance", "Term Insurance"),
        ("insurance", "Insurance"),
        ("investment", "Investment"),
        ("wealth", "Wealth Product"),
        ("credit card", "Credit Card"),
        ("loan", "Loan"),
    ]
    for sentence in sentences:
        lowered = sentence.casefold()
        for needle, label in catalog:
            if label == "Loan" and {"Business Loan", "Home Loan"} & seen:
                continue
            if needle in lowered and label not in seen:
                seen.add(label)
                products.append(label)
    return products


def _dedupe_local(commitments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result = []
    for item in commitments:
        key = normalize_text(item["description"])
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _make_summary(
    client_name: str | None,
    sentences: list[str],
    concerns: list[dict[str, Any]],
    commitments: list[dict[str, Any]],
) -> str:
    subject = client_name or "The client"
    if not sentences:
        return f"{subject} meeting notes were processed."
    parts: list[str] = []
    topic = _meeting_topic(sentences)
    if topic:
        parts.append(f"{subject} discussed {topic}.")
    else:
        first = next((item for item in sentences if not item.lower().startswith("met ")), sentences[0])
        parts.append(f"{subject} discussed {first.rstrip('.').lower()}.")
    if concerns:
        concern_text = str(concerns[0].get("description") or "").strip().rstrip(".")
        if concern_text:
            parts.append(f"{subject} expressed concerns about {concern_text}.")
    if commitments:
        if len(commitments) == 1:
            parts.append(
                f"One follow-up commitment was created: {_commitment_phrase(commitments[0])}."
            )
        else:
            formatted = "; ".join(_commitment_phrase(item) for item in commitments[:2])
            parts.append(
                f"{len(commitments)} follow-up commitments were created: {formatted}."
            )
    return " ".join(parts).strip()


def _meeting_topic(sentences: list[str]) -> str | None:
    for sentence in sentences:
        text = sentence.strip().rstrip(".")
        lowered = text.casefold()
        if lowered.startswith("met "):
            continue
        if "interested in " in lowered:
            topic = text[text.lower().index("interested in ") + len("interested in ") :].strip()
            return _normalize_topic(topic)
        if lowered.startswith("discussed "):
            return _normalize_topic(text[10:].strip())
        if any(word in lowered for word in ["loan", "investment", "approval", "documents"]):
            return _normalize_topic(text)
    return None


def _normalize_topic(topic: str) -> str:
    topic = topic.strip().rstrip(".")
    lowered = topic.casefold()
    if lowered.startswith(("a ", "an ", "the ")):
        return topic
    if "loan" in lowered:
        return f"a {topic}"
    return topic


def _commitment_phrase(item: dict[str, Any]) -> str:
    description = str(item.get("description") or "Follow up").strip()
    due = item.get("due_date_text") or item.get("due_date")
    if due:
        return f"{description} {due}".replace("  ", " ").strip()
    return description


def _key_points(sentences: list[str]) -> list[str]:
    points = []
    for sentence in sentences:
        lowered = sentence.lower()
        if any(word in lowered for word in ["interested", "concern", "loan", "investment", "approval"]):
            points.append(sentence.rstrip("."))
    return points[:6]

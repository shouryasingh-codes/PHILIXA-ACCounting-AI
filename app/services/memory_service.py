from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Principal
from app.models.client import Client
from app.models.commitment import Commitment
from app.models.meeting import Meeting
from app.services.commitment_service import CommitmentService
from app.services.json_utils import from_json


class MemoryService:
    def __init__(self) -> None:
        self.commitments = CommitmentService()

    async def update_client_memory(self, db: AsyncSession, client_id: int) -> Client:
        client = await db.get(Client, client_id)
        if not client:
            raise ValueError("Client not found.")
        meetings = list(
            (await db.scalars(
                select(Meeting)
                .where(Meeting.client_id == client_id, Meeting.organization_id == client.organization_id)
                .order_by(Meeting.meeting_date.desc(), Meeting.created_at.desc())
                .limit(5)
            )).all()
        )
        pending = await self.commitments.pending_for_client(db, client_id)
        concerns = self._collect_concerns(meetings)
        latest_meeting = meetings[0] if meetings else None
        products_owned = from_json(client.products_owned_json, [])
        products_interested = from_json(client.products_interested_json, [])
        client.rolling_summary = self._build_rolling_summary(
            client.name,
            latest_meeting,
            pending,
            concerns,
            products_owned,
            products_interested,
        )
        db.add(client)
        await db.flush()
        return client

    async def get_client_memory(
        self,
        db: AsyncSession,
        client_id: int,
        principal: Principal | None = None,
    ) -> dict:
        if principal is not None:
            from app.repositories.client_repository import ClientRepository
            client = await ClientRepository().get_by_id(db, principal, client_id)
        else:
            client = await db.get(Client, client_id)

        if not client:
            raise ValueError("Client not found.")

        last_meeting = await db.scalar(
            select(Meeting)
            .where(Meeting.client_id == client_id, Meeting.organization_id == client.organization_id)
            .order_by(Meeting.meeting_date.desc(), Meeting.created_at.desc())
        )
        recent_meetings = list(
            (await db.scalars(
                select(Meeting)
                .where(Meeting.client_id == client_id, Meeting.organization_id == client.organization_id)
                .order_by(Meeting.meeting_date.desc(), Meeting.created_at.desc())
                .limit(5)
            )).all()
        )
        major_concerns = self._collect_concerns(recent_meetings)
        pending_commitments = await self.commitments.pending_for_client(db, client_id)
        products_owned = from_json(client.products_owned_json, [])
        products_interested = from_json(client.products_interested_json, [])
        last_meeting_summary = self._meeting_display_summary(
            client.name,
            last_meeting,
            pending_commitments,
        )
        return {
            "client_id": client.id,
            "client_name": client.name,
            "last_meeting_summary": last_meeting_summary,
            "pre_meeting_brief": self._build_pre_meeting_brief(
                products_owned,
                last_meeting,
                pending_commitments,
                major_concerns,
                products_interested=products_interested,
            ),
            "products_owned": products_owned,
            "products_interested": products_interested,
            "pending_commitments": pending_commitments,
            "major_concerns": major_concerns[:5],
            "recent_relationship_notes": [
                f"[{meeting.meeting_date.isoformat()}] "
                f"{self._meeting_display_summary(client.name, meeting, [])}"
                for meeting in recent_meetings
                if meeting.summary
            ],
            "rolling_summary": client.rolling_summary
            or self._build_rolling_summary(
                client.name,
                last_meeting,
                pending_commitments,
                major_concerns,
                products_owned,
                products_interested,
            ),
        }

    def _collect_concerns(self, meetings: list[Meeting]) -> list[dict]:
        seen: set[str] = set()
        concerns: list[dict] = []
        for meeting in meetings:
            for item in from_json(meeting.concerns_json, []):
                description = str(item.get("description") or "").strip()
                if not description:
                    continue
                key = description.casefold()
                if key in seen:
                    continue
                seen.add(key)
                concerns.append(item)
        return concerns

    def _build_rolling_summary(
        self,
        client_name: str,
        latest_meeting: Meeting | None,
        pending: list[Commitment],
        concerns: list[dict],
        products_owned: list[str],
        products_interested: list[str] | None = None,
    ) -> str:
        parts: list[str] = []
        if latest_meeting:
            summary = (latest_meeting.summary or "").strip()
            if summary and "Concerns noted:" not in summary:
                parts.append(summary.rstrip(".") + ".")
            else:
                topic = self._meeting_topic(latest_meeting)
                if topic:
                    parts.append(f"{client_name} recently discussed {topic}.")
                else:
                    parts.append(f"{client_name} had a recent client interaction.")
        if products_owned:
            parts.append(f"Tracked products include {', '.join(products_owned[:3])}.")
        if products_interested:
            parts.append(f"Client expressed interest in {', '.join(products_interested[:3])}.")
        if concerns:
            first_concern = self._format_concern(concerns[0].get("description"))
            if first_concern:
                if len(concerns) > 1:
                    second_concern = self._format_concern(concerns[1].get("description"))
                    parts.append(f"Key concerns include: {first_concern} and {second_concern}.")
                else:
                    parts.append(f"A key concern is: {first_concern}.")
        if pending:
            if len(pending) == 1:
                parts.append(
                    f"One follow-up commitment is still open: {self._format_commitment_brief(pending[0])}."
                )
            else:
                parts.append(
                    f"{len(pending)} follow-up commitments are still open, led by {self._format_commitment_brief(pending[0])}."
                )
        return " ".join(parts).strip() or f"{client_name} has no stored briefing yet."

    def _build_pre_meeting_brief(
        self,
        products_owned: list[str],
        last_meeting: Meeting | None,
        pending: list[Commitment],
        concerns: list[dict],
        products_interested: list[str] | None = None,
    ) -> dict:
        interested = products_interested or []
        top_concern = self._format_concern(concerns[0].get("description")) if concerns else ""
        return {
            "title": "Client Brief",
            "products_owned": products_owned[:3],
            "products_interested": interested[:3],
            "last_meeting": self._meeting_title(last_meeting),
            "pending": [self._format_commitment_brief(item) for item in pending[:3]],
            "concern": self._sentence_case(top_concern) if top_concern else "No major concern captured",
            "highest_urgency": self._highest_urgency(pending),
            "suggested_talking_point": self._suggested_talking_point(
                products_owned,
                last_meeting,
                pending,
                top_concern,
                products_interested=interested,
            ),
        }

    def _meeting_title(self, last_meeting: Meeting | None) -> str:
        if not last_meeting:
            return "No recent meeting"
        key_points = from_json(last_meeting.key_discussion_points_json, [])
        candidates = [str(item).strip() for item in key_points if str(item).strip()]
        if candidates:
            first = candidates[0]
            lowered = first.casefold()
            if "business loan" in lowered:
                return "Business Loan Discussion"
            if "home loan" in lowered:
                return "Home Loan Discussion"
            return first[:1].upper() + first[1:]
        if last_meeting.summary:
            summary = last_meeting.summary.strip().rstrip(".")
            return summary if len(summary) <= 48 else summary[:45].rstrip() + "..."
        return "Recent Client Discussion"

    def _suggested_talking_point(
        self,
        products_owned: list[str],
        last_meeting: Meeting | None,
        pending: list[Commitment],
        top_concern: str,
        products_interested: list[str] | None = None,
    ) -> str:
        concern_lower = top_concern.casefold()
        if "processing time" in concern_lower or "timeline" in concern_lower:
            return "Explain loan processing timeline."
        if "approval" in concern_lower:
            return "Share a clear approval status update and next step."
        if products_interested:
            return f"Follow up on client's interest in {products_interested[0]}."
        if products_owned:
            return f"Reconfirm the client's priority around {products_owned[0]} and align on the next step."
        if pending:
            return f"Start by confirming progress on {pending[0].description.casefold()}."
        if last_meeting and last_meeting.summary:
            return "Reconfirm the previous discussion and align on the next action."
        return "Start with a quick recap and confirm the client's current priority."

    def _meeting_display_summary(
        self,
        client_name: str,
        meeting: Meeting | None,
        pending: list[Commitment],
    ) -> str:
        if not meeting:
            return ""
        summary = (meeting.summary or "").strip()
        parts: list[str] = []
        if summary and "Concerns noted:" not in summary and "Commitments captured:" not in summary:
            parts.append(summary.rstrip(".") + ".")
        else:
            topic = self._meeting_topic(meeting)
            if topic:
                parts.append(f"{client_name} discussed {topic}.")

        concerns = self._collect_concerns([meeting])
        if concerns:
            parts.append(
                f"A key concern is: {self._format_concern(concerns[0].get('description'))}."
            )
        if pending:
            if len(pending) == 1:
                parts.append(
                    f"One follow-up commitment is open: {self._format_commitment_brief(pending[0])}."
                )
            else:
                parts.append(
                    f"{len(pending)} follow-up commitments are open, including {self._format_commitment_brief(pending[0])}."
                )
        return " ".join(parts).strip() or summary

    def _meeting_topic(self, meeting: Meeting) -> str | None:
        key_points = from_json(meeting.key_discussion_points_json, [])
        for item in key_points:
            text = str(item or "").strip().rstrip(".")
            if not text:
                continue
            lowered = text.casefold()
            if "interested in " in lowered:
                topic = text[text.lower().index("interested in ") + len("interested in ") :].strip()
                return self._normalize_topic(topic)
            if any(word in lowered for word in ["loan", "investment", "approval"]):
                return self._normalize_topic(text)
        return None

    @staticmethod
    def _normalize_topic(topic: str) -> str:
        topic = topic.strip()
        lowered = topic.casefold()
        if lowered.startswith(("a ", "an ", "the ")):
            return topic
        if "loan" in lowered:
            return f"a {topic}"
        return topic

    def _format_commitment_brief(self, commitment: Commitment) -> str:
        description = commitment.description
        due = commitment.due_date.isoformat() if commitment.due_date else None
        if due:
            return f"{description} ({due})".strip()
        return description

    @staticmethod
    def _highest_urgency(pending: list[Commitment]) -> str:
        ranking = {"high": 3, "medium": 2, "low": 1}
        current = "low"
        for item in pending:
            urgency = (item.urgency_level or "low").casefold()
            if ranking.get(urgency, 1) > ranking.get(current, 1):
                current = urgency
        return current if pending else "none"

    @staticmethod
    def _format_concern(value: object) -> str:
        text = str(value or "").strip().rstrip(".")
        if not text:
            return ""
        if text.casefold().endswith("concern"):
            text = text[: -len("concern")].strip()
        return text

    @staticmethod
    def _sentence_case(text: str) -> str:
        return text[:1].upper() + text[1:] if text else text

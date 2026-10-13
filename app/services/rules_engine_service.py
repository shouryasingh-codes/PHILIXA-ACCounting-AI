from __future__ import annotations

from datetime import date
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.commitment import Commitment
from app.models.follow_up_task import FollowUpTask
from app.models.meeting import Meeting
from app.models.risk_signal import RiskSignal
from app.services.json_utils import from_json


class RulesEngineService:
    @staticmethod
    async def sync_client_tasks_and_risks(db: AsyncSession, client_id: int) -> None:
        # 1. Sync FollowUpTasks from Commitments
        commitments = (await db.scalars(select(Commitment).where(Commitment.client_id == client_id))).all()

        today = date.today()

        for comm in commitments:
            task = await db.scalar(select(FollowUpTask).where(FollowUpTask.commitment_id == comm.id))

            # Calculate overdue/due-today before creating or updating the task
            is_completed = (comm.status == "completed")
            is_overdue = False
            is_due_today = False
            if not is_completed and comm.due_date:
                is_overdue = comm.due_date < today
                is_due_today = comm.due_date == today

            if not task:
                task = FollowUpTask(
                    organization_id=comm.organization_id,
                    user_id=comm.user_id,
                    client_id=client_id,
                    commitment_id=comm.id,
                    description=comm.description,
                    due_date=comm.due_date,
                    is_completed=is_completed,
                    is_overdue=is_overdue,
                    is_due_today=is_due_today,
                )
                db.add(task)
            else:
                task.description = comm.description
                task.due_date = comm.due_date
                task.is_completed = is_completed
                task.is_overdue = is_overdue
                task.is_due_today = is_due_today

        # 2. Sync RiskSignals from Meetings' concerns
        meetings = (await db.scalars(select(Meeting).where(Meeting.client_id == client_id))).all()
        for meeting in meetings:
            concerns = from_json(meeting.concerns_json, [])

            existing_risks = list((await db.scalars(select(RiskSignal).where(RiskSignal.meeting_id == meeting.id))).all())
            existing_by_desc = {r.description: r for r in existing_risks}

            for c in concerns:
                desc = c.get("description", "")
                if not desc:
                    continue
                severity = c.get("severity", "medium").lower()
                confidence = float(c.get("confidence", 0.0))

                risk = existing_by_desc.get(desc)
                if not risk:
                    risk = RiskSignal(
                        organization_id=meeting.organization_id,
                        user_id=meeting.user_id,
                        client_id=client_id,
                        meeting_id=meeting.id,
                    )
                    db.add(risk)

                risk.description = desc
                risk.severity_level = severity
                risk.confidence = confidence

                # Rule: High risk if severity is high or critical, OR if severity is medium but confidence is high (>0.85)
                risk.is_high_risk = severity in ("high", "critical") or (severity == "medium" and confidence > 0.85)
                risk.requires_review = risk.is_high_risk

        await db.flush()

from __future__ import annotations

from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.dependencies import CurrentPrincipal
from app.core.rate_limit import limiter
from app.database.session import get_db
from app.models.client import Client
from app.models.commitment import Commitment
from app.models.follow_up_task import FollowUpTask
from app.models.meeting import Meeting
from app.models.risk_signal import RiskSignal
from app.models.user import User
from app.models.organization_membership import OrganizationMembership
from app.schemas.dashboard import (
    DailyPrioritiesResponse,
    FollowUpTaskRead,
    RiskSignalRead,
    TeamMemberStats,
    TeamPerformanceResponse,
)
from app.schemas.portfolio_copilot import CopilotRequest, CopilotResponse
from app.services.portfolio_copilot_service import process_copilot_query

router = APIRouter(
    prefix="/dashboard",
    tags=["dashboard"],
)


@router.get("/priorities", response_model=DailyPrioritiesResponse)
async def get_daily_priorities(
    principal: CurrentPrincipal,
    db: AsyncSession = Depends(get_db),
) -> DailyPrioritiesResponse:
    today = date.today()

    client_subq = select(Client.id).where(Client.organization_id == principal.organization_id)
    task_stmt = select(FollowUpTask).options(selectinload(FollowUpTask.client)).where(
        FollowUpTask.organization_id == principal.organization_id,
        FollowUpTask.is_completed == False,  # noqa: E712
        or_(FollowUpTask.due_date == today, FollowUpTask.due_date < today),
    )
    risk_stmt = select(RiskSignal).options(selectinload(RiskSignal.client)).where(
        RiskSignal.organization_id == principal.organization_id,
        or_(RiskSignal.is_high_risk == True, RiskSignal.requires_review == True),  # noqa: E712
    )

    if principal.role.lower() == "member":
        client_subq = client_subq.where(Client.user_id == principal.user_id)
        task_stmt = task_stmt.where(FollowUpTask.user_id == principal.user_id)
        risk_stmt = risk_stmt.where(RiskSignal.user_id == principal.user_id)

    tasks = (await db.scalars(task_stmt.order_by(FollowUpTask.due_date.asc()))).all()
    risks = (await db.scalars(risk_stmt.order_by(RiskSignal.confidence.desc()))).all()

    task_reads = [
        FollowUpTaskRead(
            id=t.id,
            client_id=t.client_id,
            client_name=t.client.name if t.client else None,
            commitment_id=t.commitment_id,
            description=t.description,
            due_date=t.due_date,
            is_completed=t.is_completed,
            is_overdue=bool(t.due_date and t.due_date < today),
            is_due_today=bool(t.due_date and t.due_date == today),
        )
        for t in tasks
    ]

    risk_reads = [
        RiskSignalRead(
            id=r.id,
            client_id=r.client_id,
            client_name=r.client.name if r.client else None,
            meeting_id=r.meeting_id,
            description=r.description,
            severity_level=r.severity_level,
            confidence=r.confidence,
            is_high_risk=r.is_high_risk,
            requires_review=r.requires_review,
        )
        for r in risks
    ]

    return DailyPrioritiesResponse(tasks=task_reads, risks=risk_reads)


@router.get("/metrics")
async def get_dashboard_metrics(
    principal: CurrentPrincipal,
    db: AsyncSession = Depends(get_db),
) -> dict:
    client_stmt = select(func.count(Client.id)).where(Client.organization_id == principal.organization_id)
    # Only count meetings that are linked to a client (avoid confusing the user with orphaned meeting counts)
    meeting_stmt = select(func.count(Meeting.id)).where(
        Meeting.organization_id == principal.organization_id,
        Meeting.client_id.is_not(None)
    )
    pending_comm_stmt = select(func.count(Commitment.id)).where(
        Commitment.organization_id == principal.organization_id,
        Commitment.status == "pending",
    )

    if principal.role.lower() == "member":
        client_stmt = client_stmt.where(Client.user_id == principal.user_id)
        meeting_stmt = meeting_stmt.where(Meeting.user_id == principal.user_id)
        pending_comm_stmt = pending_comm_stmt.where(Commitment.user_id == principal.user_id)

    total_clients = await db.scalar(client_stmt) or 0
    total_meetings = await db.scalar(meeting_stmt) or 0
    pending_commitments = await db.scalar(pending_comm_stmt) or 0

    return {
        "metrics": {
            "total_clients": total_clients,
            "total_meetings": total_meetings,
            "pending_commitments": pending_commitments,
        },
        "total_clients": total_clients,
        "active_clients": total_clients,
        "pending_commitments": pending_commitments,
    }

@router.get("/team-performance", response_model=TeamPerformanceResponse)
async def get_team_performance(
    principal: CurrentPrincipal,
    db: AsyncSession = Depends(get_db),
) -> TeamPerformanceResponse:
    if principal.role.lower() not in ("owner", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only owners and admins can view team performance.",
        )

    try:
        # Get all users in the organization (excluding the owner who is viewing it)
        users_stmt = select(User).join(
            OrganizationMembership, User.id == OrganizationMembership.user_id
        ).where(
            OrganizationMembership.organization_id == principal.organization_id,
            User.id != principal.user_id
        )
        users = (await db.scalars(users_stmt)).all()

        members_stats = []
        for user in users:
            # We can run grouped queries, but since N is small (e.g. 2-5 members), simple queries are fine
            client_count = await db.scalar(
                select(func.count(Client.id)).where(
                    Client.organization_id == principal.organization_id, Client.user_id == user.id
                )
            ) or 0
            
            meeting_count = await db.scalar(
                select(func.count(Meeting.id)).where(
                    Meeting.organization_id == principal.organization_id, Meeting.user_id == user.id
                )
            ) or 0
            
            commitments_total = await db.scalar(
                select(func.count(Commitment.id)).where(
                    Commitment.organization_id == principal.organization_id, Commitment.user_id == user.id
                )
            ) or 0
            
            commitments_pending = await db.scalar(
                select(func.count(Commitment.id)).where(
                    Commitment.organization_id == principal.organization_id,
                    Commitment.user_id == user.id,
                    Commitment.status == "pending"
                )
            ) or 0
            
            commitments_completed = commitments_total - commitments_pending
            
            members_stats.append(
                TeamMemberStats(
                    user_id=user.id,
                    email=user.email,
                    total_clients=client_count,
                    total_meetings=meeting_count,
                    total_commitments=commitments_total,
                    pending_commitments=commitments_pending,
                    completed_commitments=commitments_completed
                )
            )

        return TeamPerformanceResponse(members=members_stats)
    except Exception as e:
        import traceback
        error_msg = f"{str(e)} | {traceback.format_exc()}"
        raise HTTPException(status_code=500, detail=error_msg)

@router.post("/copilot/ask", response_model=CopilotResponse)
@limiter.limit("20/minute")
async def ask_portfolio_copilot(
    request: Request,
    copilot_request: CopilotRequest,
    principal: CurrentPrincipal,
    db: AsyncSession = Depends(get_db),
) -> CopilotResponse:
    # Demo guest limit: max 5 Copilot queries per day tracked in Redis.
    if principal.user.email.startswith("demo_guest_"):
        from app.core.redis import get_redis_client
        redis = await get_redis_client()
        key = f"philixa:demo_copilot:{principal.user_id}"
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 86400)  # 24-hour TTL on first use
        if count > 5:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Demo limit reached (Max 5 Copilot queries). Please create a free Philixa account to continue!",
            )
    result = await process_copilot_query(copilot_request.query, principal.organization_id, principal.user_id, principal.role, db)
    return CopilotResponse(**result)

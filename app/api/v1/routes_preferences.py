from __future__ import annotations

import uuid
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentPrincipal
from app.database.session import get_db
from app.models.notification import NotificationPreference
from app.schemas.notification import (
    NotificationPreferenceCreate,
    NotificationPreferenceResponse,
    NotificationPreferenceUpdate,
)

router = APIRouter(
    prefix="/preferences",
    tags=["preferences"],
)


@router.get("", response_model=NotificationPreferenceResponse)
async def get_preferences(
    principal: CurrentPrincipal,
    db: AsyncSession = Depends(get_db),
) -> Any:
    pref = await db.scalar(
        select(NotificationPreference).where(
            NotificationPreference.organization_id == principal.organization_id,
            NotificationPreference.user_id == principal.user_id,
        )
    )

    if not pref:
        pref = NotificationPreference(
            id=str(uuid.uuid4()),
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            is_opted_in=True,
        )
        db.add(pref)
        await db.commit()
        await db.refresh(pref)

    return pref


@router.put("", response_model=NotificationPreferenceResponse)
async def update_preferences(
    preference_update: NotificationPreferenceUpdate,
    principal: CurrentPrincipal,
    db: AsyncSession = Depends(get_db),
) -> Any:
    pref = await db.scalar(
        select(NotificationPreference).where(
            NotificationPreference.organization_id == principal.organization_id,
            NotificationPreference.user_id == principal.user_id,
        )
    )

    if not pref:
        pref = NotificationPreference(
            id=str(uuid.uuid4()),
            organization_id=principal.organization_id,
            user_id=principal.user_id,
        )
        db.add(pref)

    update_data = preference_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(pref, key, value)

    await db.commit()
    await db.refresh(pref)
    return pref

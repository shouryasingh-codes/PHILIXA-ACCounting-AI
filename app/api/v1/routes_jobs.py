from __future__ import annotations

from typing import Any, Optional
from arq.jobs import Job, JobStatus
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.arq import get_arq_pool
from app.core.dependencies import CurrentPrincipal


class JobStateResponse(BaseModel):
    job_id: str
    status: str
    result: Optional[Any] = None
    error: Optional[str] = None


router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobStateResponse)
async def get_job_status(
    job_id: str,
    principal: CurrentPrincipal,
) -> JobStateResponse:
    pool = get_arq_pool()
    if not pool:
        raise HTTPException(status_code=503, detail="ARQ Redis pool not initialized")

    job = Job(job_id, pool)

    try:
        status = await job.status()

        response = JobStateResponse(
            job_id=job_id,
            status=status.value if isinstance(status, JobStatus) else str(status),
        )

        if status == JobStatus.complete:
            try:
                info = await job.result_info()
                if info:
                    response.result = info.result
                    response.error = info.error
            except Exception:
                pass

        return response
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Job not found or error retrieving status: {str(e)}")

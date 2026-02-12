"""GET /status/{job_id} — check the status of a conversion job."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from service.auth import authenticate_client
from service.database import get_session
from service.models import Client, Job
from service.schemas import StatusResponse

router = APIRouter()


@router.get(
    "/status/{job_id}",
    response_model=StatusResponse,
    responses={404: {"description": "Job not found"}},
)
async def get_status(
    job_id: uuid.UUID,
    client: Client = Depends(authenticate_client),
    session: AsyncSession = Depends(get_session),
) -> StatusResponse:
    """Return the current status of a conversion job."""
    result = await session.execute(select(Job).where(Job.id == job_id, Job.client_id == client.id))
    job = result.scalar_one_or_none()

    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    return StatusResponse(
        job_id=job.id,
        status=job.status.value,
        filename=job.filename,
        depth=job.depth,
        progress=job.progress,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        error=job.error_message,
    )

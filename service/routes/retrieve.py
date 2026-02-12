"""GET /retrieve/{job_id} — download the conversion result as tar.gz."""

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from service.auth import authenticate_client
from service.bundle import create_tar_gz_bundle
from service.database import get_session
from service.models import Client, Job, JobStatus
from service.schemas import ErrorResponse

router = APIRouter()


@router.get(
    "/retrieve/{job_id}",
    response_class=Response,
    responses={
        200: {"content": {"application/gzip": {}}},
        404: {"model": ErrorResponse, "description": "Job not found"},
        409: {"model": ErrorResponse, "description": "Job not yet completed"},
    },
)
async def retrieve_result(
    job_id: uuid.UUID,
    client: Client = Depends(authenticate_client),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Return the conversion output as a streaming tar.gz bundle."""
    result = await session.execute(select(Job).where(Job.id == job_id, Job.client_id == client.id))
    job = result.scalar_one_or_none()

    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status == JobStatus.failed:
        raise HTTPException(status_code=409, detail=f"Job failed: {job.error_message}")

    if job.status != JobStatus.completed:
        raise HTTPException(status_code=409, detail="Job not yet completed")

    if not job.output_path:
        raise HTTPException(status_code=410, detail="Output no longer available")

    output_dir = Path(job.output_path)
    if not output_dir.exists():
        raise HTTPException(status_code=410, detail="Output no longer available")

    stem = Path(job.filename).stem
    archive = create_tar_gz_bundle(output_dir)

    return Response(
        content=archive,
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{stem}.tar.gz"'},
    )

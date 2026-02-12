"""POST /submit_paper — accept a PDF and enqueue a conversion job."""

import uuid

import structlog
from arq import ArqRedis
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from service.auth import authenticate_client
from service.config import Settings, get_settings
from service.database import get_session
from service.models import Client, Job
from service.schemas import Depth, SubmitResponse

logger = structlog.get_logger()
router = APIRouter()


@router.post(
    "/submit_paper",
    response_model=SubmitResponse,
    status_code=202,
    responses={401: {"description": "Authentication failed"}},
)
async def submit_paper(
    request: Request,
    file: UploadFile = File(..., description="PDF file to convert"),
    depth: Depth = Form(Depth.medium),
    client: Client = Depends(authenticate_client),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> SubmitResponse:
    """Accept a PDF upload and create an async conversion job."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=422, detail="File must be a PDF")

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=422, detail="File is empty")

    # Persist upload to disk
    job_id = uuid.uuid4()
    upload_dir = settings.upload_dir / str(job_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = upload_dir / file.filename
    pdf_path.write_bytes(content)

    # Create job record
    job = Job(
        id=job_id,
        client_id=client.id,
        filename=file.filename,
        depth=depth.value,
        file_size_bytes=len(content),
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    # Enqueue to arq
    redis: ArqRedis = request.app.state.arq_pool
    await redis.enqueue_job("convert_paper", str(job_id))

    logger.info("job_submitted", job_id=str(job_id), filename=file.filename, depth=depth.value)

    return SubmitResponse(
        job_id=job.id,
        status=job.status.value,
        created_at=job.created_at,
    )

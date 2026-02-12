"""Pydantic request/response schemas."""

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class Depth(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class SubmitResponse(BaseModel):
    """Response for POST /submit_paper."""

    job_id: uuid.UUID
    status: str
    created_at: datetime


class StatusResponse(BaseModel):
    """Response for GET /status/{job_id}."""

    job_id: uuid.UUID
    status: str
    filename: str
    depth: str
    progress: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    error: str | None


class ErrorResponse(BaseModel):
    """Standard error response."""

    detail: str

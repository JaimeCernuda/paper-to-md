"""Tests for GET /status/{job_id} endpoint."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from nacl.signing import SigningKey
from sqlalchemy.ext.asyncio import AsyncSession

from service.models import Job
from tests.test_service.conftest import sign_request


@pytest.mark.asyncio
async def test_status_queued_job(
    app_client: AsyncClient,
    signing_key: SigningKey,
    db_session: AsyncSession,
    client_id: uuid.UUID,
) -> None:
    """Status endpoint returns job details for a queued job."""
    job_id = uuid.uuid4()
    job = Job(
        id=job_id,
        client_id=client_id,
        filename="test.pdf",
        depth="medium",
        file_size_bytes=1024,
    )
    db_session.add(job)
    await db_session.commit()

    headers = sign_request(signing_key, "GET", f"/status/{job_id}")
    response = await app_client.get(f"/status/{job_id}", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == str(job_id)
    assert body["status"] == "queued"
    assert body["filename"] == "test.pdf"
    assert body["depth"] == "medium"


@pytest.mark.asyncio
async def test_status_not_found(
    app_client: AsyncClient,
    signing_key: SigningKey,
) -> None:
    """Status endpoint returns 404 for unknown job_id."""
    fake_id = uuid.uuid4()
    headers = sign_request(signing_key, "GET", f"/status/{fake_id}")
    response = await app_client.get(f"/status/{fake_id}", headers=headers)

    assert response.status_code == 404

"""Tests for GET /retrieve/{job_id} endpoint."""

from __future__ import annotations

import io
import tarfile
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from nacl.signing import SigningKey
from sqlalchemy.ext.asyncio import AsyncSession

from service.models import Job, JobStatus
from tests.test_service.conftest import sign_request


@pytest.mark.asyncio
async def test_retrieve_completed_job(
    app_client: AsyncClient,
    signing_key: SigningKey,
    db_session: AsyncSession,
    client_id: uuid.UUID,
    tmp_path: Path,
) -> None:
    """Retrieve returns a tar.gz bundle for a completed job."""
    # Create mock output directory
    output_dir = tmp_path / "test"
    output_dir.mkdir()
    (output_dir / "test.md").write_text("# Test Paper")
    img_dir = output_dir / "img"
    img_dir.mkdir()
    (img_dir / "figure1.png").write_bytes(b"fake png")

    job_id = uuid.uuid4()
    job = Job(
        id=job_id,
        client_id=client_id,
        filename="test.pdf",
        depth="medium",
        file_size_bytes=1024,
        status=JobStatus.completed,
        output_path=str(output_dir),
    )
    db_session.add(job)
    await db_session.commit()

    headers = sign_request(signing_key, "GET", f"/retrieve/{job_id}")
    response = await app_client.get(f"/retrieve/{job_id}", headers=headers)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/gzip"
    assert "test.tar.gz" in response.headers["content-disposition"]

    # Verify archive contents
    tar_bytes = io.BytesIO(response.content)
    with tarfile.open(fileobj=tar_bytes, mode="r:gz") as tar:
        names = tar.getnames()
        assert any("test.md" in n for n in names)
        assert any("figure1.png" in n for n in names)


@pytest.mark.asyncio
async def test_retrieve_not_completed_returns_409(
    app_client: AsyncClient,
    signing_key: SigningKey,
    db_session: AsyncSession,
    client_id: uuid.UUID,
) -> None:
    """Retrieve returns 409 for a job still in progress."""
    job_id = uuid.uuid4()
    job = Job(
        id=job_id,
        client_id=client_id,
        filename="test.pdf",
        depth="medium",
        file_size_bytes=1024,
        status=JobStatus.processing,
    )
    db_session.add(job)
    await db_session.commit()

    headers = sign_request(signing_key, "GET", f"/retrieve/{job_id}")
    response = await app_client.get(f"/retrieve/{job_id}", headers=headers)

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_retrieve_not_found(
    app_client: AsyncClient,
    signing_key: SigningKey,
) -> None:
    """Retrieve returns 404 for unknown job_id."""
    fake_id = uuid.uuid4()
    headers = sign_request(signing_key, "GET", f"/retrieve/{fake_id}")
    response = await app_client.get(f"/retrieve/{fake_id}", headers=headers)

    assert response.status_code == 404

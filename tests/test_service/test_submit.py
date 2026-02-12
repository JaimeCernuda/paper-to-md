"""Tests for POST /submit_paper endpoint."""

from __future__ import annotations

import io

import pytest
from httpx import AsyncClient
from nacl.signing import SigningKey

from tests.test_service.conftest import sign_request


@pytest.mark.asyncio
async def test_submit_paper_success(
    app_client: AsyncClient,
    signing_key: SigningKey,
) -> None:
    """Submitting a valid PDF returns 202 with job info."""
    pdf_content = b"%PDF-1.4 fake pdf content"
    headers = sign_request(signing_key, "POST", "/submit_paper")

    response = await app_client.post(
        "/submit_paper",
        files={"file": ("paper.pdf", io.BytesIO(pdf_content), "application/pdf")},
        data={"depth": "medium"},
        headers=headers,
    )

    assert response.status_code == 202
    body = response.json()
    assert "job_id" in body
    assert body["status"] == "queued"
    assert "created_at" in body


@pytest.mark.asyncio
async def test_submit_non_pdf_rejected(
    app_client: AsyncClient,
    signing_key: SigningKey,
) -> None:
    """Submitting a non-PDF file returns 422."""
    headers = sign_request(signing_key, "POST", "/submit_paper")

    response = await app_client.post(
        "/submit_paper",
        files={"file": ("paper.txt", io.BytesIO(b"not a pdf"), "text/plain")},
        headers=headers,
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_submit_empty_file_rejected(
    app_client: AsyncClient,
    signing_key: SigningKey,
) -> None:
    """Submitting an empty file returns 422."""
    headers = sign_request(signing_key, "POST", "/submit_paper")

    response = await app_client.post(
        "/submit_paper",
        files={"file": ("paper.pdf", io.BytesIO(b""), "application/pdf")},
        headers=headers,
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_submit_no_auth_returns_422(
    app_client: AsyncClient,
) -> None:
    """Request without auth headers returns 422 (missing required headers)."""
    response = await app_client.post(
        "/submit_paper",
        files={"file": ("paper.pdf", io.BytesIO(b"%PDF"), "application/pdf")},
    )

    assert response.status_code == 422

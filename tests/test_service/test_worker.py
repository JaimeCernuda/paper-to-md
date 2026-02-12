"""Tests for the arq worker convert_paper task."""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from service.models import Base, Client, Job, JobStatus

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture()
async def worker_db():
    """Set up an in-memory database for worker tests."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    yield engine, factory

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture()
async def worker_job(worker_db, tmp_path: Path) -> tuple[str, Path]:
    """Create a test job and return (job_id, upload_dir)."""
    engine, factory = worker_db
    client_id = uuid.uuid4()
    job_id = uuid.uuid4()

    async with factory() as session:
        client = Client(
            id=client_id,
            name="test-worker-client",
            public_key_b64="dGVzdA==",
            active=True,
        )
        session.add(client)

        job = Job(
            id=job_id,
            client_id=client_id,
            filename="paper.pdf",
            depth="low",
            file_size_bytes=1024,
        )
        session.add(job)
        await session.commit()

    # Create upload dir with a fake PDF
    upload_dir = tmp_path / "uploads" / str(job_id)
    upload_dir.mkdir(parents=True)
    (upload_dir / "paper.pdf").write_bytes(b"%PDF-1.4 fake")

    return str(job_id), tmp_path


@pytest.mark.asyncio
async def test_convert_paper_low_depth(worker_db, worker_job: tuple[str, Path]) -> None:
    """Worker processes a low-depth job through stages 1 and 2 only."""
    job_id, tmp_path = worker_job
    engine, factory = worker_db

    data_dir = tmp_path / "data"
    data_dir.mkdir()

    # Mock the pipeline functions
    def fake_extract(pdf_path, output_dir, **kwargs):
        out = output_dir / "paper"
        out.mkdir(parents=True)
        md = out / "paper.md"
        md.write_text("# Fake Paper\nContent here.")
        return md, []

    def fake_process(content, images=None):
        return f"# Processed\n{content}"

    with (
        patch("service.worker.get_settings") as mock_settings,
        patch("pdf2md.extraction.docling.extract_with_docling", side_effect=fake_extract),
        patch("pdf2md.postprocess.process_markdown", side_effect=fake_process),
        patch("service.database.get_session_factory", return_value=factory),
    ):
        settings = MagicMock()
        settings.upload_dir = tmp_path / "uploads"
        settings.data_dir = data_dir
        settings.images_scale = 2.0
        settings.min_image_width = 200
        settings.min_image_height = 150
        settings.min_image_area = 40000
        mock_settings.return_value = settings

        from service.worker import convert_paper

        ctx: dict = {}
        await convert_paper(ctx, job_id)

    # Verify job was updated to completed
    async with factory() as session:
        from sqlalchemy import select

        result = await session.execute(select(Job).where(Job.id == uuid.UUID(job_id)))
        job = result.scalar_one()
        assert job.status == JobStatus.completed
        assert job.output_path is not None
        assert job.error_message is None


@pytest.mark.asyncio
async def test_convert_paper_failure(worker_db, worker_job: tuple[str, Path]) -> None:
    """Worker marks job as failed when an exception occurs."""
    job_id, tmp_path = worker_job
    engine, factory = worker_db

    data_dir = tmp_path / "data"
    data_dir.mkdir()

    with (
        patch("service.worker.get_settings") as mock_settings,
        patch(
            "pdf2md.extraction.docling.extract_with_docling",
            side_effect=RuntimeError("Docling failed"),
        ),
        patch("service.database.get_session_factory", return_value=factory),
    ):
        settings = MagicMock()
        settings.upload_dir = tmp_path / "uploads"
        settings.data_dir = data_dir
        settings.images_scale = 2.0
        settings.min_image_width = 200
        settings.min_image_height = 150
        settings.min_image_area = 40000
        mock_settings.return_value = settings

        from service.worker import convert_paper

        ctx: dict = {}
        with pytest.raises(RuntimeError, match="Docling failed"):
            await convert_paper(ctx, job_id)

    # Verify job was marked as failed
    async with factory() as session:
        from sqlalchemy import select

        result = await session.execute(select(Job).where(Job.id == uuid.UUID(job_id)))
        job = result.scalar_one()
        assert job.status == JobStatus.failed
        assert "Docling failed" in (job.error_message or "")

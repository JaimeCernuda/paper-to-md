"""arq worker that runs the pdf2md conversion pipeline."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import structlog
from arq.connections import RedisSettings

from service.config import get_settings

logger = structlog.get_logger()


async def _update_job(
    ctx: dict,
    job_id: str,
    *,
    status: str | None = None,
    progress: str | None = None,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    output_path: str | None = None,
    error_message: str | None = None,
    result_metadata: dict | None = None,
) -> None:
    """Update job record in the database."""
    from sqlalchemy import update

    from service.database import get_session_factory
    from service.models import Job, JobStatus

    factory = get_session_factory()
    async with factory() as session:
        values: dict = {}
        if status is not None:
            values["status"] = JobStatus(status)
        if progress is not None:
            values["progress"] = progress
        if started_at is not None:
            values["started_at"] = started_at
        if completed_at is not None:
            values["completed_at"] = completed_at
        if output_path is not None:
            values["output_path"] = output_path
        if error_message is not None:
            values["error_message"] = error_message
        if result_metadata is not None:
            values["result_metadata"] = result_metadata

        await session.execute(update(Job).where(Job.id == UUID(job_id)).values(**values))
        await session.commit()


async def _get_job_info(ctx: dict, job_id: str) -> dict:
    """Fetch job filename, depth, and upload path."""
    from sqlalchemy import select

    from service.database import get_session_factory
    from service.models import Job

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(select(Job).where(Job.id == UUID(job_id)))
        job = result.scalar_one()
        return {
            "filename": job.filename,
            "depth": job.depth,
            "job_id": str(job.id),
        }


async def convert_paper(ctx: dict, job_id: str) -> None:
    """Run the full pdf2md conversion pipeline for a job.

    Pipeline stages (controlled by depth):
        1. Docling extraction (always)
        2. Rule-based post-processing (always)
        3. LLM retouch via Claude Agent SDK (medium+)
        4. Enrichments extraction (high only)
    """
    settings = get_settings()
    log = logger.bind(job_id=job_id)

    try:
        await _update_job(
            ctx,
            job_id,
            status="processing",
            started_at=datetime.now(timezone.utc),
            progress="Step 1/4: Extracting PDF with Docling",
        )

        info = await _get_job_info(ctx, job_id)
        filename = info["filename"]
        depth = info["depth"]

        upload_dir = settings.upload_dir / job_id
        pdf_path = upload_dir / filename
        output_dir = settings.data_dir / job_id
        output_dir.mkdir(parents=True, exist_ok=True)

        log.info("pipeline_start", filename=filename, depth=depth)

        # Stage 1: Docling extraction
        from pdf2md.extraction.docling import extract_with_docling

        md_path, image_paths = extract_with_docling(
            pdf_path,
            output_dir,
            images_scale=settings.images_scale,
            min_image_width=settings.min_image_width,
            min_image_height=settings.min_image_height,
            min_image_area=settings.min_image_area,
        )
        image_names = [p.name for p in image_paths]
        log.info("stage_1_complete", md_path=str(md_path), num_images=len(image_paths))

        # Stage 2: Rule-based post-processing
        await _update_job(ctx, job_id, progress="Step 2/4: Post-processing")

        from pdf2md.postprocess import process_markdown

        content = md_path.read_text(encoding="utf-8")
        content = process_markdown(content, image_names)
        md_path.write_text(content, encoding="utf-8")
        log.info("stage_2_complete")

        # Stage 3: LLM retouch (medium and high depth)
        if depth in ("medium", "high"):
            await _update_job(ctx, job_id, progress="Step 3/4: LLM retouch")

            from pdf2md.agent.cleanup import run_cleanup_with_backend

            img_dir = md_path.parent / "img"
            summary = await run_cleanup_with_backend(
                md_path,
                img_dir if img_dir.exists() else None,
                backend="claude",
            )
            log.info("stage_3_complete", summary=summary)
        else:
            log.info("stage_3_skipped", reason="depth=low")

        # Stage 4: Enrichments (high depth only)
        result_meta: dict = {"num_images": len(image_paths)}
        if depth == "high":
            await _update_job(ctx, job_id, progress="Step 4/4: Extracting enrichments")

            from pdf2md.extraction.enrichments import extract_enrichments

            enrichments = extract_enrichments(pdf_path, output_dir)
            result_meta.update(
                {
                    "num_code_blocks": len(enrichments.code_blocks),
                    "num_equations": len(enrichments.equations),
                    "num_figures": len(enrichments.figures),
                }
            )
            log.info("stage_4_complete", **result_meta)
        else:
            log.info("stage_4_skipped", reason=f"depth={depth}")

        # Determine the actual output subdirectory (Docling creates stem/ subdir)
        stem = Path(filename).stem
        actual_output = output_dir / stem

        await _update_job(
            ctx,
            job_id,
            status="completed",
            completed_at=datetime.now(timezone.utc),
            progress="Completed",
            output_path=str(actual_output),
            result_metadata=result_meta,
        )
        log.info("pipeline_complete", output_path=str(actual_output))

    except (Exception, asyncio.CancelledError) as exc:
        log.error("pipeline_failed", error=str(exc))
        try:
            await asyncio.shield(
                _update_job(
                    ctx,
                    job_id,
                    status="failed",
                    completed_at=datetime.now(timezone.utc),
                    progress="Failed",
                    error_message=str(exc) or "Cancelled (timeout)",
                )
            )
        except Exception:
            log.error("failed_to_record_failure", job_id=job_id, original_error=str(exc))
        raise


def _parse_redis_settings() -> RedisSettings:
    """Parse redis URL into arq RedisSettings."""
    from urllib.parse import urlparse

    settings = get_settings()
    parsed = urlparse(settings.redis_url)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=int(parsed.path.lstrip("/") or "0"),
    )


class WorkerSettings:
    """arq worker configuration."""

    functions = [convert_paper]
    max_jobs = get_settings().worker_max_jobs
    job_timeout = 1800  # 30 min — large PDFs with LLM retouch can take a while
    redis_settings = _parse_redis_settings()
    on_startup = None
    on_shutdown = None

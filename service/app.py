"""FastAPI application factory with lifespan management."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from urllib.parse import urlparse

import structlog
from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI

from service.config import get_settings
from service.database import dispose_engine, get_engine
from service.routes import retrieve, status, submit

logger = structlog.get_logger()


def _redis_settings() -> RedisSettings:
    """Parse redis URL into arq RedisSettings."""
    settings = get_settings()
    parsed = urlparse(settings.redis_url)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=int(parsed.path.lstrip("/") or "0"),
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage startup/shutdown of database and Redis connections."""
    settings = get_settings()

    # Ensure directories exist
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)

    # Initialize database engine (validates connection)
    get_engine()
    logger.info("database_connected", url=settings.database_url.split("@")[-1])

    # Connect to Redis for job enqueuing
    app.state.arq_pool = await create_pool(_redis_settings())
    logger.info("redis_connected", url=settings.redis_url)

    yield

    # Shutdown
    await app.state.arq_pool.close()
    await dispose_engine()
    logger.info("shutdown_complete")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="pdf2md Service",
        description="Async PDF-to-Markdown conversion microservice",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.include_router(submit.router, tags=["jobs"])
    app.include_router(status.router, tags=["jobs"])
    app.include_router(retrieve.router, tags=["jobs"])

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()

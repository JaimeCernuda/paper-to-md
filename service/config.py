"""Service configuration via environment variables."""

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    database_url: str = "postgresql+asyncpg://pdf2md:pdf2md@localhost:5432/pdf2md"

    # Redis
    redis_url: str = "redis://localhost:6379"

    # Data storage
    data_dir: Path = Path("/data")
    upload_dir: Path = Path("/data/uploads")

    # Auth
    auth_timestamp_tolerance_seconds: int = 300  # 5 minutes

    # Worker
    worker_max_jobs: int = 1

    # Docling extraction defaults
    images_scale: float = 2.0
    min_image_width: int = 200
    min_image_height: int = 150
    min_image_area: int = 40000

    model_config = {"env_prefix": "PDF2MD_SERVICE_"}


def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()

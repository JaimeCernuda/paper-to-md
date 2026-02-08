"""Base class for agent backends."""

from abc import ABC, abstractmethod
from pathlib import Path


class AgentBackend(ABC):
    """Abstract base class for agent backends."""

    @abstractmethod
    async def run_cleanup(
        self,
        md_path: Path,
        img_dir: Path | None = None,
        *,
        provider: str | None = None,
        model: str | None = None,
        verbose: bool = False,
    ) -> str | None:
        """Run cleanup agent on markdown file.

        Args:
            md_path: Path to markdown file to clean
            img_dir: Path to images directory (optional)
            provider: LLM provider name (backend-specific)
            model: Model name to use
            verbose: Print progress

        Returns:
            Summary of changes made, or None if failed
        """
        ...

    @abstractmethod
    async def run_describe_figures(
        self,
        img_dir: Path,
        *,
        provider: str | None = None,
        model: str | None = None,
        verbose: bool = False,
    ) -> list[dict]:
        """Generate VLM descriptions for figures.

        Args:
            img_dir: Path to directory containing figure*.png images
            provider: LLM provider name (backend-specific)
            model: VLM model name to use
            verbose: Print progress

        Returns:
            List of {figure_id, description} dicts
        """
        ...

"""Claude Agent SDK backend (existing implementation wrapper)."""

from pathlib import Path

from .base import AgentBackend


class ClaudeBackend(AgentBackend):
    """Backend using Claude Agent SDK.

    This wraps the existing implementation in pdf2md/agent/cleanup.py
    """

    async def run_cleanup(
        self,
        md_path: Path,
        img_dir: Path | None = None,
        *,
        provider: str | None = None,
        model: str | None = None,
        text_endpoint: str | None = None,
        verbose: bool = False,
    ) -> str | None:
        """Run cleanup using Claude Agent SDK.

        Note: provider, model, and text_endpoint are ignored for this backend.
        """
        from ..cleanup import run_cleanup_agent

        return await run_cleanup_agent(md_path, img_dir, verbose=verbose)

    async def run_describe_figures(
        self,
        img_dir: Path,
        *,
        provider: str | None = None,
        model: str | None = None,
        vlm_endpoint: str | None = None,
        verbose: bool = False,
    ) -> list[dict]:
        """Not implemented for Claude backend (uses Docling VLM pipeline instead)."""
        raise NotImplementedError(
            "Claude backend uses Docling's VLM pipeline for figure descriptions"
        )

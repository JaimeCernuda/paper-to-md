"""Agent backend registry."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import AgentBackend


class BackendNotInstalledError(ImportError):
    """Raised when a backend's dependencies are not installed."""

    def __init__(self, backend: str, install_cmd: str) -> None:
        super().__init__(f"{backend} backend is not installed. Install with: {install_cmd}")


def get_backend(name: str = "claude") -> AgentBackend:
    """Get an agent backend by name.

    Args:
        name: Backend name ('claude' or 'local')

    Returns:
        AgentBackend instance

    Raises:
        BackendNotInstalledError: If backend dependencies not installed
        ValueError: If backend name is unknown
    """
    if name == "claude":
        try:
            from .claude import ClaudeBackend

            return ClaudeBackend()
        except ImportError:
            raise BackendNotInstalledError("claude", "pip install 'pdf2md[agent]'")

    elif name == "local":
        try:
            from .local import LocalBackend

            return LocalBackend()
        except ImportError:
            raise BackendNotInstalledError("local", "pip install 'pdf2md[agent-local]'")

    else:
        raise ValueError(f"Unknown backend: {name}. Available: claude, local")


__all__ = ["get_backend", "BackendNotInstalledError"]

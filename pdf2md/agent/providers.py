"""Provider configuration for local LLM backends.

LiteLLM provider prefixes:
  - LM Studio: ``lm_studio/<model>`` — reads ``LM_STUDIO_API_BASE`` env var
  - Ollama:    ``ollama_chat/<model>`` — requires ``api_base`` parameter
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# =============================================================================
# Defaults — override via environment variables
# =============================================================================

DEFAULT_TEXT_MODEL = os.getenv("PDF2MD_TEXT_MODEL", "qwen3-4b")
DEFAULT_VLM_MODEL = os.getenv("PDF2MD_VLM_MODEL", "qwen3-vl-4b")
DEFAULT_PROVIDER = os.getenv("PDF2MD_PROVIDER", "lm_studio")

DEFAULT_LM_STUDIO_HOST = os.getenv("LM_STUDIO_HOST", "http://localhost:1234/v1")
DEFAULT_VLM_HOST = os.getenv("PDF2MD_VLM_HOST", "http://localhost:1234/v1")
DEFAULT_OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")


@dataclass
class ProviderConfig:
    """Configuration for an LLM provider."""

    model: str  # LiteLLM-format: lm_studio/<name> or ollama_chat/<name>
    api_base: str | None = None  # Only needed for ollama


def resolve_provider(local: bool, provider: str | None = None) -> str | None:
    """Resolve provider, defaulting to lm_studio when --local is set."""
    if local and not provider:
        return "lm_studio"
    return provider


def get_provider_config(provider: str | None = None, model: str | None = None) -> ProviderConfig:
    """Get configuration for the specified provider.

    Args:
        provider: Provider name (lm_studio, ollama). Defaults to PDF2MD_PROVIDER env / lm_studio.
        model: Model name override (without prefix).

    Returns:
        ProviderConfig with LiteLLM-compatible model string.
    """
    provider = provider or DEFAULT_PROVIDER
    if provider == "ollama":
        return _get_ollama_config(model)
    if provider == "lm_studio":
        return _get_lm_studio_config(model)
    raise ValueError(f"Unknown provider '{provider}'. Supported: lm_studio, ollama")


def get_vlm_config(provider: str | None = None, model: str | None = None) -> ProviderConfig:
    """Get configuration for VLM (vision language model).

    Uses PDF2MD_VLM_HOST (separate endpoint) so VLM can run on a different
    node/port than the text model.
    """
    provider = provider or DEFAULT_PROVIDER
    vlm_model = model or DEFAULT_VLM_MODEL

    if provider == "ollama":
        return ProviderConfig(
            model=f"ollama_chat/{vlm_model}",
            api_base=DEFAULT_OLLAMA_HOST,
        )
    if provider == "lm_studio":
        return ProviderConfig(
            model=f"lm_studio/{vlm_model}",
            api_base=DEFAULT_VLM_HOST,
        )
    raise ValueError(f"Unknown provider '{provider}'. Supported: lm_studio, ollama")


def _get_lm_studio_config(model: str | None) -> ProviderConfig:
    """LM Studio: return lm_studio/ prefix + api_base."""
    model_name = model or DEFAULT_TEXT_MODEL
    return ProviderConfig(
        model=f"lm_studio/{model_name}",
        api_base=DEFAULT_LM_STUDIO_HOST,
    )


def _get_ollama_config(model: str | None) -> ProviderConfig:
    """Ollama: return ollama_chat/ prefix + api_base."""
    model_name = model or DEFAULT_TEXT_MODEL
    return ProviderConfig(
        model=f"ollama_chat/{model_name}",
        api_base=DEFAULT_OLLAMA_HOST,
    )


def list_defaults() -> dict[str, str]:
    """Return current default model settings."""
    return {
        "text_model": DEFAULT_TEXT_MODEL,
        "vlm_model": DEFAULT_VLM_MODEL,
        "provider": DEFAULT_PROVIDER,
        "lm_studio_host": DEFAULT_LM_STUDIO_HOST,
        "vlm_host": DEFAULT_VLM_HOST,
        "ollama_host": DEFAULT_OLLAMA_HOST,
    }

"""Provider configuration for local LLM backends.

LiteLLM provider prefixes:
  - LM Studio: ``lm_studio/<model>`` — uses ``api_base`` parameter
  - Ollama:    ``ollama_chat/<model>`` — uses ``api_base`` parameter

Environment variables (read at call time, not import time):
  PDF2MD_TEXT_MODEL, PDF2MD_VLM_MODEL, PDF2MD_PROVIDER,
  LM_STUDIO_HOST, PDF2MD_VLM_HOST, OLLAMA_HOST
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger("pdf2md.providers")


@dataclass
class ProviderConfig:
    """Configuration for an LLM provider."""

    model: str  # LiteLLM-format: lm_studio/<name> or ollama_chat/<name>
    api_base: str | None = None


# =============================================================================
# Helpers: read env at call time
# =============================================================================


def _env(name: str, default: str) -> str:
    """Read an environment variable, falling back to *default*."""
    return os.getenv(name, default)


def _text_model() -> str:
    return _env("PDF2MD_TEXT_MODEL", "qwen3-4b")


def _vlm_model() -> str:
    return _env("PDF2MD_VLM_MODEL", "qwen3-vl-4b")


def _provider() -> str:
    return _env("PDF2MD_PROVIDER", "lm_studio")


def _lm_studio_host() -> str:
    return _env("LM_STUDIO_HOST", "http://localhost:1234/v1")


def _vlm_host() -> str:
    return _env("PDF2MD_VLM_HOST", "http://localhost:1234/v1")


def _ollama_host() -> str:
    return _env("OLLAMA_HOST", "http://localhost:11434")


# =============================================================================
# Model auto-detection from running endpoints
# =============================================================================


def _detect_loaded_model(
    api_base: str,
    *,
    prefer: str | None = None,
) -> str | None:
    """Query an OpenAI-compatible ``/v1/models`` endpoint for loaded models.

    Args:
        api_base: Base URL (e.g. ``http://host:1234/v1``).
        prefer: Substring to prefer in model IDs (e.g. ``"vl"`` for VLMs,
                ``"nemotron"`` for Nemotron). Case-insensitive.

    Returns:
        The model ID string, or *None* if unreachable / empty.
    """
    import json as _json
    import urllib.request

    base = api_base.rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"

    try:
        req = urllib.request.Request(f"{base}/models", method="GET")
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = _json.loads(resp.read())
    except Exception:
        return None

    models = data.get("data", [])
    if not models:
        return None

    # Prefer a model matching the hint
    if prefer:
        hint = prefer.lower()
        for m in models:
            mid = m.get("id", "")
            if hint in mid.lower():
                logger.info("Auto-detected model %s (matched %r)", mid, prefer)
                return mid

    # Fall back to the first model
    first = models[0].get("id", "")
    if first:
        logger.info("Auto-detected model %s", first)
    return first or None


# =============================================================================
# Public API
# =============================================================================


def resolve_provider(local: bool, provider: str | None = None) -> str | None:
    """Resolve provider, defaulting to lm_studio when ``--local`` is set."""
    if local and not provider:
        return "lm_studio"
    return provider


def get_provider_config(
    provider: str | None = None,
    model: str | None = None,
    *,
    api_base: str | None = None,
    auto_detect: bool = True,
) -> ProviderConfig:
    """Get configuration for the text LLM provider.

    Args:
        provider: ``lm_studio`` or ``ollama``. Falls back to env / lm_studio.
        model: Explicit model name (without prefix). When *None* and
               *auto_detect* is True, queries the endpoint for loaded models.
        api_base: Explicit endpoint URL override. Takes precedence over env.
        auto_detect: When True and *model* is None, query the endpoint's
                     ``/v1/models`` to pick the first loaded model.
    """
    provider = provider or _provider()
    if provider == "ollama":
        return _get_ollama_config(model, api_base=api_base, auto_detect=auto_detect)
    if provider == "lm_studio":
        return _get_lm_studio_config(model, api_base=api_base, auto_detect=auto_detect)
    raise ValueError(f"Unknown provider '{provider}'. Supported: lm_studio, ollama")


def get_vlm_config(
    provider: str | None = None,
    model: str | None = None,
    *,
    api_base: str | None = None,
    auto_detect: bool = True,
) -> ProviderConfig:
    """Get configuration for the VLM (vision language model).

    Uses ``PDF2MD_VLM_HOST`` (separate endpoint) so the VLM can run on
    a different node than the text model.
    """
    vlm_provider = _env("PDF2MD_VLM_PROVIDER", "") or provider or _provider()
    base = api_base or _vlm_host()
    vlm_model = model or _vlm_model()

    # Auto-detect if no explicit model given
    if vlm_model == "qwen3-vl-4b" and auto_detect and not model:
        detected = _detect_loaded_model(base, prefer="vl")
        if detected:
            vlm_model = detected

    if vlm_provider == "ollama":
        return ProviderConfig(
            model=f"ollama_chat/{vlm_model}",
            api_base=_ollama_host() if api_base is None else api_base,
        )
    if vlm_provider == "lm_studio":
        return ProviderConfig(
            model=f"lm_studio/{vlm_model}",
            api_base=base,
        )
    raise ValueError(f"Unknown VLM provider '{vlm_provider}'. Supported: lm_studio, ollama")


def _get_lm_studio_config(
    model: str | None,
    *,
    api_base: str | None = None,
    auto_detect: bool = True,
) -> ProviderConfig:
    """LM Studio: return ``lm_studio/`` prefix + api_base."""
    base = api_base or _lm_studio_host()
    model_name = model or _text_model()

    # Auto-detect if using the compiled-in default
    if model_name == "qwen3-4b" and auto_detect and not model:
        detected = _detect_loaded_model(base, prefer="nemotron")
        if detected:
            model_name = detected

    return ProviderConfig(
        model=f"lm_studio/{model_name}",
        api_base=base,
    )


def _get_ollama_config(
    model: str | None,
    *,
    api_base: str | None = None,
    auto_detect: bool = True,
) -> ProviderConfig:
    """Ollama: return ``ollama_chat/`` prefix + api_base."""
    base = api_base or _ollama_host()
    model_name = model or _text_model()

    if model_name == "qwen3-4b" and auto_detect and not model:
        detected = _detect_loaded_model(base)
        if detected:
            model_name = detected

    return ProviderConfig(
        model=f"ollama_chat/{model_name}",
        api_base=base,
    )


def list_defaults() -> dict[str, str]:
    """Return current default model settings (reads env at call time)."""
    return {
        "text_model": _text_model(),
        "vlm_model": _vlm_model(),
        "provider": _provider(),
        "lm_studio_host": _lm_studio_host(),
        "vlm_host": _vlm_host(),
        "ollama_host": _ollama_host(),
    }

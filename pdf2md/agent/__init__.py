"""Agent for open-ended markdown cleanup.

Supports two backends:
- Claude: Cloud-based via Claude Agent SDK
- Local: Local LLM via LM Studio/Ollama + OpenAI Agents SDK
"""

from pdf2md.agent.cleanup import run_cleanup_agent, run_cleanup_with_backend_sync

__all__ = ["run_cleanup_agent", "run_cleanup_with_backend_sync"]

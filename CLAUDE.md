# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Run Commands

```bash
uv sync                        # Install all dependencies
uv run pdf2md download-models  # Pre-download Docling ML models (one-time)
uv run pdf2md convert paper.pdf ./output  # Basic conversion
uv run pytest                  # Run all tests
uv run pytest tests/test_figures.py::TestBuildFigureMap::test_standard_naming  # Single test
uv run ruff check .            # Lint
uv run ruff format .           # Format
```

## Architecture

pdf2md converts academic PDFs to markdown through a 4-stage pipeline:

```
PDF → Docling Extraction → Rule-Based Postprocess → LLM Retouch → RAG Enrichments
      (extraction/)         (postprocess/)          (agent/)      (extraction/enrichments.py)
```

### Depth Levels Control Pipeline Stages
- `low`: Docling + postprocess only (no AI)
- `medium`: + LLM retouch for cleanup
- `high`: + VLM figure descriptions + code/equation enrichments

### Key Modules

**`pdf2md/extraction/docling.py`**: Wraps Docling library for PDF→markdown. Filters logos by min dimensions (200x150px, 40000 area).

**`pdf2md/postprocess/`**: Deterministic regex-based fixes applied in order:
1. `sections.py` - Numbered section headers (1.1, 3.1.2)
2. `citations.py` - `[7]` → `[[7]](#ref-7)`, range expansion
3. `figures.py` - Embeds `![Figure N]` above captions
4. `bibliography.py` - Adds `<a id="ref-N">` anchors
5. `cleanup.py` - Image comments, ligatures, GLYPH artifacts, OCR garbage, hyphenation, paragraph merging, blank lines, whitespace

**`pdf2md/agent/`**: LLM-based cleanup for issues regex can't handle:
- Two backends: `claude` (cloud via Claude Agent SDK) or `local` (LM Studio via OpenAI Agents SDK)
- Prompt in `cleanup.py` handles lettered sections (A. B.), figure relocation, OCR artifacts, author formatting
- `providers.py` configures local models via env vars: `PDF2MD_TEXT_MODEL`, `PDF2MD_VLM_MODEL`

**`pdf2md/extraction/enrichments.py`**: Extracts RAG metadata (code blocks, equations, figures with optional VLM descriptions).

### Agent Backend Pattern

```python
from pdf2md.agent.backends import get_backend
backend = get_backend("claude")  # or "local"
await backend.run_cleanup(md_path)
```

Backends implement `AgentBackend` ABC from `backends/base.py`.

## Environment Variables

```bash
PDF2MD_TEXT_MODEL=qwen3-4b                        # LLM for retouch
PDF2MD_VLM_MODEL=qwen3-vl-4b                      # VLM for figure descriptions
LM_STUDIO_HOST=http://localhost:1234/v1
OLLAMA_HOST=http://localhost:11434
```

## Optional Dependencies

All conversion dependencies (Docling, Claude Agent SDK, LiteLLM) are included by default.
- `pip install paper-to-md[service]` - FastAPI/Redis/PostgreSQL for Docker microservice
- `pip install paper-to-md[dev]` - pytest + ruff for development

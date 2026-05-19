# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Run Commands

```bash
uv sync --all-extras                    # Install all dependencies
uv run pdf2md download-models           # Pre-download Docling ML models for enrich
uv run pdf2md convert paper.pdf ./out   # Basic conversion
uv run pdf2md convert paper.pdf -d high --local  # Full local AI pipeline
uv run pytest                           # Run all tests
uv run ruff check .                     # Lint
uv run ruff format .                    # Format
```

## Architecture

pdf2md converts academic PDFs to markdown through a multi-stage pipeline:

```
PDF → PyMuPDF Extraction → Rule-Based Postprocess → LLM Retouch → VLM Descriptions → Synthesis
      (extraction/)        (postprocess/)          (agent/)      (agent/)            (agent/)
```

### Depth Levels Control Pipeline Stages
- `low`: PyMuPDF + postprocess only (no AI)
- `medium`: + LLM retouch for author formatting and lettered sections
- `high`: + VLM figure descriptions + synthesis pass for equations and garbled unicode cleanup

### Key Modules

**`pdf2md/extraction/pymupdf.py`**: Extracts text, renders vector figures by locating captions and cropping page regions, and extracts tables with PyMuPDF.

**`pdf2md/extraction/docling.py`**: Docling-backed extraction used by the standalone `enrich` command.

**`pdf2md/postprocess/`**: Deterministic regex-based fixes applied in order:
1. `sections.py` - Numbered section headers (1.1, 3.1.2)
2. `citations.py` - `[7]` → `[[7]](#ref-7)`, range expansion
3. `figures.py` - Embeds `![Figure N]` above captions
4. `bibliography.py` - Adds `<a id="ref-N">` anchors
5. `tables.py` - Inserts extracted tables near table captions
6. `cleanup.py` - Image comments, ligatures, math font degarbling, OCR garbage, hyphenation, paragraph merging, blank lines, whitespace

**`pdf2md/agent/`**: LLM-based cleanup for issues regex cannot handle:
- Two backends: `claude` (cloud via Claude Agent SDK) or `local` (LM Studio/Ollama via LiteLLM)
- Prompt in `cleanup.py` handles lettered sections (A. B.) and author formatting
- `backends/local.py` handles VLM descriptions, equation reconstruction, and synthesis
- `providers.py` configures local models via env vars: `PDF2MD_TEXT_MODEL`, `PDF2MD_VLM_MODEL`

**`pdf2md/extraction/enrichments.py`**: Extracts RAG metadata (code blocks, equations, figures with optional VLM descriptions).

### Agent Backend Pattern

```python
from pdf2md.agent.backends import get_backend
backend = get_backend("claude")  # or "local"
await backend.run_cleanup(md_path)
await backend.run_describe_figures(img_dir)
await backend.run_synthesis(md_path, figures, tables, equations)
```

Backends implement `AgentBackend` ABC from `backends/base.py`.

## Environment Variables

```bash
PDF2MD_TEXT_MODEL=nemotron-cascade-2-30b-a3b-i1   # Text LLM
PDF2MD_VLM_MODEL=qwen3-vl-30b                     # VLM
LM_STUDIO_HOST=http://192.168.86.143:1234/v1      # Text endpoint
PDF2MD_VLM_HOST=http://192.168.86.141:8081/v1     # VLM endpoint
OLLAMA_HOST=http://localhost:11434                # Ollama endpoint
```

## Optional Dependencies

All conversion dependencies (Docling, Claude Agent SDK, LiteLLM) are included by default.
- `pip install paper-to-md[service]` - FastAPI/Redis/PostgreSQL for Docker microservice
- `pip install paper-to-md[dev]` - pytest + ruff for development

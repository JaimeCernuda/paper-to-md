# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build and Run

```bash
uv sync --all-extras                     # Install all dependencies
uv run pdf2md convert paper.pdf ./out    # Basic conversion
uv run pdf2md convert paper.pdf ./out -d high --local  # Full pipeline
uv run pytest                            # Run all tests (116)
uv run ruff check .                      # Lint
uv run ruff format .                     # Format
```

## Architecture

pdf2md converts academic PDFs to markdown through a multi-stage pipeline:

```
PDF → PyMuPDF (text + figures + tables) → Postprocess → LLM Retouch → VLM Descriptions → Synthesis
      (extraction/pymupdf.py)            (postprocess/)  (agent/)      (agent/)            (agent/)
```

### Depth Levels Control Pipeline Stages
- `low`: PyMuPDF + postprocess only (no AI)
- `medium`: + LLM retouch for author formatting and lettered sections
- `high`: + VLM figure descriptions + synthesis pass (equations, garbled unicode cleanup)

### Key Modules

**`pdf2md/extraction/pymupdf.py`**: Extracts text, renders vector figures at 200 DPI by locating "Figure N:" captions and capturing the page region above them. Extracts tables using `page.find_tables()`. Skips axis labels and chart annotations when determining figure boundaries.

**`pdf2md/postprocess/`**: Deterministic regex-based fixes applied in order:
1. `sections.py` — Numbered section headers with hierarchy (supports split-line patterns where the number and title are on separate lines)
2. `citations.py` — `[7]` → `[[7]](#ref-7)`, range expansion for `[6-11]`, `[N]-[M]`, and line-break ranges
3. `figures.py` — Embeds `![Figure N]` above captions
4. `bibliography.py` — Adds `<a id="ref-N">` anchors
5. `cleanup.py` — Ligatures, math font degarbling (Hangul codepoints from PDF math italic fonts → ASCII), GLYPH artifacts, OCR garbage, hyphenation, paragraph merging

**`pdf2md/agent/backends/local.py`**: LLM-based cleanup and synthesis:
- Author formatting via targeted LLM call
- Lettered section classification (A./B./C. header vs sentence)
- VLM figure descriptions with multi-shot prompts, low temperature, thinking model support
- Equation detection (unicode math char concentration) and LLM reconstruction to LaTeX
- Edit-based synthesis that preserves all original text while fixing garbled unicode per-section

**`pdf2md/agent/providers.py`**: Endpoint configuration via env vars: `PDF2MD_TEXT_MODEL`, `PDF2MD_VLM_MODEL`, `LM_STUDIO_HOST`, `PDF2MD_VLM_HOST`

**`pdf2md/cli.py`**: CLI entry point with `convert`, `retouch`, `postprocess`, and `enrich` commands. Dynamic step numbering based on enabled features.

### Agent Backend Pattern

```python
from pdf2md.agent.backends import get_backend
backend = get_backend("local")  # or "claude"
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
PDF2MD_VLM_HOST=http://192.168.86.141:8081/v1      # VLM endpoint
```

## Optional Dependencies

- `pip install pdf2md[agent-local]` — LiteLLM for local LLM/VLM endpoints
- `pip install pdf2md[agent]` — Claude Agent SDK for cloud backend
- `pip install pdf2md[docling]` — Docling for the `enrich` command

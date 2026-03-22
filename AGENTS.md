# AGENTS.md

Instructions for AI agents using pdf2md to convert academic PDFs to markdown.

## When to Use pdf2md

Use pdf2md when you need to convert an academic PDF paper to clean markdown for:
- Academic paper review or analysis
- Feeding paper content to an LLM for summarization, critique, or discussion
- Extracting structured data (figures, equations, tables) from papers
- Building a knowledge base from research papers

## Installation

The tool is installed at `~/tools/paper-to-md`. To use it from any directory:

```bash
cd ~/tools/paper-to-md && uv run pdf2md convert <pdf_path> <output_dir> [OPTIONS]
```

## Quick Reference

### Convert a PDF (recommended for most uses)

```bash
# Fast, no AI (instant, good for initial scan)
cd ~/tools/paper-to-md && uv run pdf2md convert paper.pdf /tmp/output/ -d low

# With LLM retouch (30s, fixes authors and sections)
cd ~/tools/paper-to-md && \
  LM_STUDIO_HOST=http://192.168.86.143:1234/v1 \
  PDF2MD_TEXT_MODEL=nemotron-cascade-2-30b-a3b-i1 \
  uv run pdf2md convert paper.pdf /tmp/output/ -d medium --local

# Full pipeline with VLM figure descriptions (5 min, best quality)
cd ~/tools/paper-to-md && \
  LM_STUDIO_HOST=http://192.168.86.143:1234/v1 \
  PDF2MD_TEXT_MODEL=nemotron-cascade-2-30b-a3b-i1 \
  PDF2MD_VLM_HOST=http://192.168.86.141:8081/v1 \
  PDF2MD_VLM_MODEL=qwen3-vl-30b \
  uv run pdf2md convert paper.pdf /tmp/output/ -d high --local
```

### Output Location

The output goes to `<output_dir>/<pdf_stem>/`:
- `<pdf_stem>.md` is the final markdown
- `img/` contains rendered figure PNGs
- `figures.json` has VLM descriptions (depth=high only)
- `tables.json` has extracted tables
- `equations.json` has reconstructed LaTeX

### Read the Result

After conversion, the primary artifact is the markdown file:

```
<output_dir>/<pdf_stem>/<pdf_stem>.md
```

Figure images are referenced as `./img/figureN.png` relative to the markdown file.

## Depth Levels

Choose the depth based on your quality needs and time budget:

| Depth | Time | Quality | Use When |
|-------|------|---------|----------|
| `low` | < 1s | Basic extraction with linked citations and sections | Quick scan, batch processing, endpoints unavailable |
| `medium` | ~30s | + LLM-formatted authors and lettered section headers | Standard review, most use cases |
| `high` | ~5 min | + VLM figure descriptions, LaTeX equations, full synthesis | Thorough review, archival quality, feeding to review agents |

## Homelab Endpoints

Two GPU endpoints are available:

| Endpoint | Host | Model | Use |
|----------|------|-------|-----|
| Text/reasoning | dynamo (192.168.86.143:1234) | Nemotron-Cascade-2-30B-A3B | Retouch, synthesis, equation reconstruction |
| Vision | mini (192.168.86.141:8081) | Qwen3-VL-30B-A3B-Thinking | Figure descriptions |

```bash
export LM_STUDIO_HOST=http://192.168.86.143:1234/v1
export PDF2MD_TEXT_MODEL=nemotron-cascade-2-30b-a3b-i1
export PDF2MD_VLM_HOST=http://192.168.86.141:8081/v1
export PDF2MD_VLM_MODEL=qwen3-vl-30b
```

## Output Quality at depth=high

The markdown will have:
- Correct section hierarchy (`##`, `###`, `####`)
- All figures embedded as `![Figure N](./img/figureN.png)` with VLM-generated captions in blockquotes
- Linked citations (`[[1]](#ref-1)`) with expanded ranges
- Bibliography with anchor IDs for citation links
- LaTeX equations reconstructed from garbled PDF unicode
- Math font garble cleaned to ASCII
- Paragraphs split across page breaks rejoined
- Ligatures fixed, OCR artifacts removed

## CLI Flags

```
pdf2md convert <pdf> <output> [OPTIONS]

Core:
  -d, --depth           low | medium | high (default: medium)
  -l, --local           Use local LLM endpoints
  -p, --provider        lm_studio (default) | ollama

Feature:
  --no-vlm              Skip VLM figure descriptions
  --no-synthesis        Skip synthesis pass
  --keep-raw            Save raw extraction alongside
  --raw                 Output raw text only

Model:
  -m, --model           Override text LLM model
  --vlm-model           Override VLM model
  --text-endpoint       Override text LLM URL
  --vlm-endpoint        Override VLM URL
```

## Common Agent Workflows

### Convert a paper for review

```bash
cd ~/tools/paper-to-md && \
  LM_STUDIO_HOST=http://192.168.86.143:1234/v1 \
  PDF2MD_TEXT_MODEL=nemotron-cascade-2-30b-a3b-i1 \
  PDF2MD_VLM_HOST=http://192.168.86.141:8081/v1 \
  PDF2MD_VLM_MODEL=qwen3-vl-30b \
  uv run pdf2md convert ~/path/to/paper.pdf /tmp/review/ -d high --local
# Result: /tmp/review/<paper-stem>/<paper-stem>.md
```

### Fast batch conversion

```bash
for pdf in ~/papers/*.pdf; do
  cd ~/tools/paper-to-md && uv run pdf2md convert "$pdf" /tmp/batch/ -d low
done
```

### Re-run postprocessing on existing markdown

```bash
cd ~/tools/paper-to-md && uv run pdf2md postprocess /path/to/paper.md
```

## Development

```bash
uv sync --all-extras          # Install all dependencies
uv run pytest                  # Run tests (116 tests)
uv run ruff check .            # Lint
uv run ruff format .           # Format
```

Ruff config: `line-length = 100`, target `py310`. Follow PEP 8 naming conventions.

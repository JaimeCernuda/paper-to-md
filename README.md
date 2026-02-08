# pdf2md

Convert academic PDF papers to clean, readable markdown with linked citations, embedded figures, and structured metadata for RAG systems.

## What It Does

**pdf2md** takes a PDF academic paper and produces:

1. **Clean Markdown** - Properly formatted with linked citations, embedded figures, and fixed extraction artifacts
2. **Extracted Figures** - All figures as high-resolution PNG files
3. **RAG-Ready Metadata** - JSON files with figure captions, classifications, equations, and code blocks

## Quick Start

```bash
# Install with uv
uv sync --all-extras

# Basic conversion (medium depth — Docling + postprocess + LLM retouch)
uv run pdf2md convert paper.pdf ./output

# Fast conversion (no AI)
uv run pdf2md convert paper.pdf ./output -d low

# Full pipeline with local LLM
uv run pdf2md convert paper.pdf ./output -d high --local
```

## Depth Levels

pdf2md uses a depth-based system to control how much processing is applied:

| Depth | What happens | Speed |
|-------|-------------|-------|
| `low` | Docling extraction + rule-based postprocessing (citations, figures, sections, cleanup) | Fast, no AI |
| `medium` | + LLM retouch (author formatting, lettered section detection) | Moderate |
| `high` | + VLM figure descriptions + code/equation enrichments | Slow |

## Commands

### `pdf2md convert` - Main Conversion

```bash
uv run pdf2md convert paper.pdf ./output [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `-d, --depth` | Analysis depth: `low`, `medium` (default), `high` |
| `-l, --local` | Use local LLM/VLM instead of cloud (Claude) |
| `-p, --provider` | LLM provider: `lm_studio` (default), `ollama` |
| `-m, --model` | Override LLM/VLM model name |
| `--keep-raw` | Save raw Docling extraction alongside processed output |
| `--raw` | Skip all processing, output only raw extraction |
| `--images-scale N` | Image resolution multiplier (default: 2.0) |
| `--min-image-width` | Minimum image width in pixels, filters logos (default: 200) |
| `--min-image-height` | Minimum image height in pixels (default: 150) |
| `--min-image-area` | Minimum image area in pixels (default: 40000) |

**Output:**
```
output/paper/
├── paper.md              # Final processed markdown
├── paper_raw.md          # Raw Docling output (if --keep-raw)
├── img/
│   ├── figure1.png
│   ├── figure2.png
│   └── ...
├── enrichments.json      # All metadata (depth=high only)
├── figures.json          # Figure metadata
├── equations.json        # Equations with LaTeX
└── code_blocks.json      # Code with language detection
```

### `pdf2md retouch` - LLM Cleanup Only

Run LLM-based cleanup on an existing markdown file:

```bash
uv run pdf2md retouch paper.md [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `-l, --local` | Use local LLM instead of cloud (Claude) |
| `-p, --provider` | LLM provider: `lm_studio`, `ollama` |
| `-m, --model` | Override LLM model name |
| `-i, --images` | Path to images directory (default: `./img`) |
| `-v, --verbose` | Show detailed LLM progress |

The retouch step fixes:
- **Author formatting** - Extracts and formats author names, affiliations, emails
- **Lettered section headers** - Classifies `A. Background` vs `A. We conducted...`

### `pdf2md postprocess` - Rule-Based Fixes Only

```bash
uv run pdf2md postprocess paper.md [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `-i, --images` | Path to images directory (default: `./img`) |
| `-o, --output` | Output path (default: overwrite input file) |

### `pdf2md enrich` - Extract RAG Metadata

```bash
uv run pdf2md enrich paper.pdf ./output [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--describe` | Generate VLM descriptions for figures |
| `-l, --local` | Use local VLM instead of cloud |
| `-p, --provider` | VLM provider: `lm_studio`, `ollama` |
| `-m, --model` | Override VLM model |
| `--images-scale N` | Image resolution multiplier (default: 2.0) |

## Processing Pipeline

### 1. Docling Extraction

Uses [Docling](https://github.com/DS4SD/docling) (ML-based) to extract:
- Text with structure (headings, paragraphs, lists)
- Tables with formatting
- Figures as images
- Equations

### 2. Deterministic Post-Processing

Applied at all depth levels (including `low`):

**Citations:**
- `[7]` → `[[7]](#ref-7)` (clickable links)
- `[11]-[14]` → expanded to four individual linked citations
- Anchors added to reference entries for link targets

**Sections:**
- `Abstract -Text here` → `## Abstract\n\nText here`
- Hierarchical section numbering → proper markdown headers

**Figures:**
- Embeds `![Figure N](./img/figureN.png)` above line-start captions
- Each figure embedded exactly once

**Bibliography:**
- Adds `<a id="ref-N"></a>` anchors to reference entries
- Ensures proper spacing between entries

**Cleanup:**
- Fixes ligatures (ﬁ→fi, ﬂ→fl)
- Removes GLYPH artifacts from OCR
- Fixes hyphenated word breaks across lines
- Merges split paragraphs
- Removes OCR garbage near figure embeds

### 3. LLM Retouch (medium, high depth)

Uses LLM to fix issues that need judgment:
- **Author formatting** - Extracts names, affiliations, emails into structured `## Authors` section
- **Lettered sections** - Classifies `A. Background` as header vs `A. We conducted...` as sentence

### 4. VLM + Enrichments (high depth)

Extracts structured data for RAG:

| File | Contents |
|------|----------|
| `figures.json` | Caption, classification, VLM description, page number |
| `equations.json` | LaTeX representation, surrounding context |
| `code_blocks.json` | Code text, detected language |
| `enrichments.json` | All of the above combined |

## Local AI Setup

pdf2md supports running entirely locally using LM Studio or Ollama:

```bash
# Using LM Studio (default local provider)
export LM_STUDIO_HOST=http://localhost:1234/v1
uv run pdf2md convert paper.pdf ./output --local

# Using Ollama
export OLLAMA_HOST=http://localhost:11434
uv run pdf2md convert paper.pdf ./output --local --provider ollama

# Override model
uv run pdf2md convert paper.pdf ./output --local --model qwen3-8b

# VLM on a separate node
export PDF2MD_VLM_HOST=http://192.168.1.100:1234/v1
uv run pdf2md convert paper.pdf ./output -d high --local
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PDF2MD_TEXT_MODEL` | `qwen3-4b` | Text LLM for retouch |
| `PDF2MD_VLM_MODEL` | `qwen3-vl-4b` | VLM for figure descriptions |
| `PDF2MD_PROVIDER` | `lm_studio` | Default provider |
| `LM_STUDIO_HOST` | `http://localhost:1234/v1` | LM Studio endpoint |
| `PDF2MD_VLM_HOST` | `http://localhost:1234/v1` | VLM endpoint (can differ from text) |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama endpoint |

## Installation

```bash
# Full installation (all features)
pip install pdf2md[all]

# Or install groups selectively:
pip install pdf2md[docling]       # PDF extraction
pip install pdf2md[agent]         # Claude cloud backend
pip install pdf2md[agent-local]   # Local LLM backend (LiteLLM)
pip install pdf2md[all-agents]    # Both backends

# Development
pip install pdf2md[dev]           # pytest + ruff
```

### Requirements

- Python 3.10-3.12
- [uv](https://docs.astral.sh/uv/) for dependency management
- **Docling**: Automatically downloads ML models on first use (~500MB)

## Batch Processing

```bash
# Convert all PDFs in a directory
uv run python scripts/batch_convert.py papers/ output/

# Fast batch (no AI)
uv run python scripts/batch_convert.py papers/ output/ --depth low

# Full batch with local LLM
uv run python scripts/batch_convert.py papers/ output/ --depth high --local

# Dry run to see what would be processed
uv run python scripts/batch_convert.py papers/ output/ --dry-run
```

## License

MIT

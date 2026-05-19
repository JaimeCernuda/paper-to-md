# pdf2md

Convert academic PDF papers to clean, readable markdown with linked citations, embedded figures, and structured metadata for RAG systems.

## Contents

- [Quick Start](#quick-start) — install and convert a paper
- [Depth Levels](#depth-levels) — control how much processing is applied
- [Direct CLI Usage](#direct-cli-usage) — convert PDFs locally
- [Service Mode](#service-mode) — Docker microservice for remote/homelab use
- [Claude Code Integration](#claude-code-integration) — MCP server + `/convert-paper` command
- [Processing Pipeline](#processing-pipeline) — what happens at each stage
- [Local AI Setup](#local-ai-setup) — run with LM Studio or Ollama
- [Installation](#installation) — extras and requirements
- [Batch Processing](#batch-processing) — convert many papers at once

## Quick Start

```bash
# Install
uv tool install paper-to-md

# Optional: pre-download Docling ML models for the enrich command (~500MB)
pdf2md download-models

# Convert a paper — uses medium depth by default (PyMuPDF + postprocess + LLM retouch)
pdf2md convert paper.pdf

# Output goes to ./paper/paper.md (same directory as the PDF)
# Or specify an output directory explicitly:
pdf2md convert paper.pdf ./output
```

## Depth Levels

pdf2md uses a depth-based system to control how much processing is applied.
**The default is `medium`.**

| Depth | Default? | What happens | AI required? |
|-------|----------|-------------|-------------|
| `low` | | PyMuPDF extraction + rule-based postprocessing (citations, figures, tables, sections, cleanup) | No |
| **`medium`** | **yes** | Everything in `low` + LLM retouch via [Claude Agent SDK](https://github.com/anthropics/claude-code-sdk-python) or local LiteLLM backend (author formatting, lettered section headers) | Yes (Claude API or `--local`) |
| `high` | | Everything in `medium` + VLM figure descriptions + synthesis pass for equations and garbled unicode cleanup | Yes (Claude API or `--local`) |

```bash
# Fast, no AI needed
pdf2md convert paper.pdf -d low

# Default — includes agentic LLM cleanup (Claude)
pdf2md convert paper.pdf

# Full pipeline — adds VLM figure descriptions and synthesis
pdf2md convert paper.pdf -d high

# Any depth with a local LLM instead of Claude
pdf2md convert paper.pdf --local
pdf2md convert paper.pdf -d high --local
```

## Direct CLI Usage

### `pdf2md convert` — Main Conversion

```bash
pdf2md convert paper.pdf [output_dir] [OPTIONS]
```

If `output_dir` is omitted, output goes to the same directory as the PDF.

| Option | Description |
|--------|-------------|
| `-d, --depth` | Analysis depth: `low`, `medium` (default), `high` |
| `-l, --local` | Use local LLM/VLM instead of cloud (Claude) |
| `-p, --provider` | LLM provider: `lm_studio` (default), `ollama` |
| `-m, --model` | Override text LLM model name |
| `--vlm-model` | Override VLM model name |
| `--text-endpoint` | Override text LLM endpoint URL |
| `--vlm-endpoint` | Override VLM endpoint URL |
| `--no-vlm` | Skip VLM figure descriptions at high depth |
| `--synthesis/--no-synthesis` | Enable or disable the high-depth synthesis pass |
| `--keep-raw` | Save raw PyMuPDF extraction alongside processed output |
| `--raw` | Skip all processing, output only raw extraction |
| `--images-scale N` | Image resolution multiplier (default: 2.0) |
| `--min-image-width` | Minimum image width in pixels, filters logos (default: 200) |
| `--min-image-height` | Minimum image height in pixels (default: 150) |
| `--min-image-area` | Minimum image area in pixels (default: 40000) |

**Output:**
```
output/paper/
├── paper.md              # Final processed markdown
├── paper_raw.md          # Raw PyMuPDF output (if --keep-raw)
├── img/
│   ├── figure1.png
│   ├── figure2.png
│   └── ...
├── figures.json          # VLM descriptions (depth=high)
├── tables.json           # Extracted tables as markdown
└── equations.json        # Reconstructed LaTeX equations
```

### `pdf2md retouch` — LLM Cleanup Only

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
- **Author formatting** — Extracts and formats author names, affiliations, emails
- **Lettered section headers** — Classifies `A. Background` as header vs `A. We conducted...` as sentence

### `pdf2md postprocess` — Rule-Based Fixes Only

```bash
uv run pdf2md postprocess paper.md [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `-i, --images` | Path to images directory (default: `./img`) |
| `-o, --output` | Output path (default: overwrite input file) |

### `pdf2md enrich` — Extract RAG Metadata

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

## Service Mode

Run pdf2md as a Docker microservice for remote or homelab use. The service provides an HTTP API with Ed25519 signature authentication and async job processing via Redis/arq.

### Docker Deployment

```bash
# Start all services (API, worker, PostgreSQL, Redis)
docker compose up -d --build

# Run database migrations
docker compose exec api alembic upgrade head

# Check logs
docker compose logs -f worker
```

### API Endpoints

All endpoints require Ed25519 signature authentication (see [Auth Setup](#auth-setup)).

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/submit_paper` | Upload a PDF and enqueue conversion. Returns `job_id`. |
| `GET` | `/status/{job_id}` | Check job status, progress, and errors. |
| `GET` | `/retrieve/{job_id}` | Download completed results as `tar.gz`. |

**Submit example:**
```bash
curl -X POST http://your-server:8000/submit_paper \
  -F "file=@paper.pdf" \
  -F "depth=medium" \
  -H "Authorization: Signature <base64-sig>" \
  -H "X-Timestamp: $(date +%s)" \
  -H "X-Client-Id: <your-uuid>"
```

### Auth Setup

The service uses Ed25519 keypairs for authentication. Each client has a UUID and a public key stored in the database; requests are signed with the corresponding private key.

**Signature format:** `METHOD\nPATH\nTIMESTAMP` signed with the client's Ed25519 private key.

**Headers required:**
- `Authorization: Signature <base64-signature>`
- `X-Timestamp: <unix-epoch>`
- `X-Client-Id: <client-uuid>`

Timestamps must be within 5 minutes of server time (configurable via `PDF2MD_SERVICE_AUTH_TIMESTAMP_TOLERANCE_SECONDS`).

### Service Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PDF2MD_SERVICE_DATABASE_URL` | `postgresql+asyncpg://...` | PostgreSQL connection string |
| `PDF2MD_SERVICE_REDIS_URL` | `redis://localhost:6379` | Redis connection string |
| `PDF2MD_SERVICE_DATA_DIR` | `/data` | Root data directory |
| `PDF2MD_SERVICE_UPLOAD_DIR` | `/data/uploads` | PDF upload storage |
| `PDF2MD_SERVICE_AUTH_TIMESTAMP_TOLERANCE_SECONDS` | `300` | Signature freshness window |
| `PDF2MD_SERVICE_WORKER_MAX_JOBS` | `1` | Concurrent conversion jobs |

## Claude Code Integration

### MCP Server

The `mcp/server.py` script exposes the service API as MCP tools for Claude Code. It loads credentials from a `.env` file in the repo root.

**Register the server:**
```bash
claude mcp add --scope user pdf2md-service -- uv run /path/to/paper-to-md/mcp/server.py
```

**Required `.env` variables** (not committed — see `.env.example`):
```
PDF2MD_SERVICE_URL=http://your-server:8000
PDF2MD_CLIENT_ID=00000000-0000-0000-0000-000000000001
PDF2MD_PRIVATE_KEY=<base64-ed25519-private-key>
```

**Tools provided:**

| Tool | Description |
|------|-------------|
| `pdf2md_submit` | Upload a PDF and start conversion. Returns job ID. |
| `pdf2md_status` | Poll job status and progress. |
| `pdf2md_retrieve` | Download and extract completed results. |

### `/convert-paper` Command

A project-level slash command in `.claude/commands/convert-paper.md` that orchestrates the full conversion workflow.

```
/convert-paper path/to/paper.pdf
```

This submits the PDF, polls for completion, downloads results, and reports extracted files. Auto-discovered by Claude Code when working in this repo.

## Processing Pipeline

### 1. PyMuPDF Extraction

Uses PyMuPDF to extract:
- Text per page
- Vector figures rendered as page-region PNGs by locating `Figure N:` captions
- Tables via `page.find_tables()`
- Raw text for deterministic post-processing

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

**Tables:**
- Inserts structured markdown tables near matching `Table N:` captions
- Keeps `tables.json` as a sidecar with extracted table data

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
- **Author formatting** — Extracts names, affiliations, emails into structured `## Authors` section
- **Lettered sections** — Classifies `A. Background` as header vs `A. We conducted...` as sentence

### 4. VLM + Synthesis (high depth)

Generates figure descriptions and runs an edit-based cleanup pass:

| File | Contents |
|------|----------|
| `figures.json` | Figure IDs, image paths, and VLM descriptions |
| `tables.json` | Extracted table data as markdown |
| `equations.json` | Reconstructed LaTeX equations |

Figure descriptions are also inserted after figure images as invisible HTML comments so rendered markdown keeps the paper's original captions while downstream tools can still parse the VLM context.

### 5. Docling Enrichments

The standalone `pdf2md enrich` command still uses Docling for RAG metadata extraction, including code blocks and equation metadata.

## Local AI Setup

pdf2md supports running entirely locally using LM Studio or Ollama:

```bash
# Using LM Studio (default local provider)
export LM_STUDIO_HOST=http://localhost:1234/v1
export PDF2MD_TEXT_MODEL=nemotron-cascade-2-30b-a3b-i1
uv run pdf2md convert paper.pdf ./output --local

# Using Ollama
export OLLAMA_HOST=http://localhost:11434
uv run pdf2md convert paper.pdf ./output --local --provider ollama

# Override model
uv run pdf2md convert paper.pdf ./output --local --model qwen3-8b

# VLM on a separate node
export PDF2MD_VLM_HOST=http://192.168.1.100:1234/v1
export PDF2MD_VLM_MODEL=qwen3-vl-30b
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

### Local AI Notes

- `--local` defaults to LM Studio unless `--provider` or `PDF2MD_PROVIDER` is set.
- Text and vision endpoints are independent. Use `LM_STUDIO_HOST` for retouch/synthesis and `PDF2MD_VLM_HOST` for figure descriptions.
- If default model names are left in place, pdf2md queries `/v1/models` and prefers a loaded Nemotron text model or loaded VLM model when the endpoint exposes one.
- High-depth figure descriptions are intentionally long. VLM calls allow larger responses and longer timeouts so thinking VLMs can finish exhaustive chart and diagram descriptions.
- Thinking tags are stripped from final figure descriptions. If a thinking model emits only an unclosed `<think>` block before hitting its token limit, pdf2md keeps the useful text instead of returning an empty caption.
- In the homelab setup, the tested endpoints are `http://192.168.86.143:1234/v1` for Nemotron text work and `http://192.168.86.141:8081/v1` for Qwen3-VL figure descriptions.

## Installation

```bash
# Install as a standalone tool (recommended)
uv tool install paper-to-md

# Pre-download Docling ML models (~500MB, one-time)
pdf2md download-models
```

Alternative install methods:

```bash
# Install into a project
uv add paper-to-md

# pip works too
pip install paper-to-md

# Docker microservice dependencies
uv tool install paper-to-md[service]

# Development (pytest + ruff)
uv pip install paper-to-md[dev]
```

### Requirements

- Python 3.10-3.12
- [uv](https://docs.astral.sh/uv/) recommended for installation and dependency management

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

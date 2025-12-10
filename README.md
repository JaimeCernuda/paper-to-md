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

# Basic conversion
uv run pdf2md convert paper.pdf ./output

# Full pipeline (recommended)
uv run pdf2md convert paper.pdf ./output --keep-raw --enrich --agent
```

## Commands

### `pdf2md convert` - Main Conversion

```bash
uv run pdf2md convert paper.pdf ./output [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--keep-raw` | Save the raw Docling extraction alongside processed output |
| `--enrich` | Extract metadata (captions, classifications) for RAG |
| `--describe` | Generate VLM descriptions for figures (slow, requires --enrich) |
| `--agent` | Run Claude agent for intelligent cleanup |
| `--raw` | Skip all processing, output only raw extraction |
| `--images-scale N` | Image resolution multiplier (default: 2.0) |

**Output:**
```
output/paper/
├── paper.md              # Final processed markdown
├── paper_raw.md          # Raw Docling output (if --keep-raw)
├── img/
│   ├── figure1.png
│   ├── figure2.png
│   └── ...
├── enrichments.json      # All metadata (if --enrich)
├── figures.json          # Figure metadata (if --enrich)
├── equations.json        # Equations with LaTeX (if --enrich)
└── code_blocks.json      # Code with language detection (if --enrich)
```

### `pdf2md enrich` - Extract Metadata Only

Extract structured metadata from a PDF without full conversion:

```bash
uv run pdf2md enrich paper.pdf ./output [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--no-code` | Skip code language detection |
| `--no-formulas` | Skip equation/LaTeX extraction |
| `--no-classify` | Skip figure classification |
| `--describe` | Generate AI descriptions for figures (slow) |

**Example output (`figures.json`):**
```json
{
  "figure_id": 1,
  "caption": "Fig. 1. ChronoLog design overview",
  "classification": "other (0.86)",
  "page": 6,
  "image_path": "./img/figure1.png"
}
```

### `pdf2md postprocess` - Re-process Existing Markdown

```bash
uv run pdf2md postprocess existing.md --output cleaned.md
```

### `pdf2md agent` - Run AI Cleanup Only

```bash
uv run pdf2md agent existing.md --verbose
```

## Processing Pipeline

### 1. Docling Extraction

Uses [Docling](https://github.com/DS4SD/docling) (ML-based) to extract:
- Text with structure (headings, paragraphs, lists)
- Tables with formatting
- Figures as images
- Equations

### 2. Deterministic Post-Processing

**Citations:**
- `[7]` → `[[7]](#ref-7)` (clickable links)
- `[11]-[14]` → `[[11]](#ref-11), [[12]](#ref-12), [[13]](#ref-13), [[14]](#ref-14)` (range expansion)

**Sections:**
- `Abstract -Text here` → `## Abstract\n\nText here` (artifact cleanup)
- `Index Terms -keywords` → `## Index Terms\n\nkeywords`

**Figures:**
- Embeds `![Figure N](./img/figureN.png)` above captions

**Bibliography:**
- Adds anchors: `<a id="ref-1"></a>[1] Author...`
- Ensures blank lines between entries

**Cleanup:**
- Fixes ligatures (ﬁ→fi, ﬂ→fl)
- Removes excessive blank lines

### 3. AI Agent Cleanup (Optional)

When `--agent` is specified, Claude reviews and fixes:

- **Misplaced figures** - Moves images to the section that references them
- **OCR artifacts** - Removes garbage text extracted from figure images
- **Formatting issues** - Tables, headers, lists that didn't convert properly
- **Any other problems** - Open-ended review for quality

### 4. RAG Enrichments (Optional)

When `--enrich` is specified, extracts structured data:

| File | Contents |
|------|----------|
| `figures.json` | Caption, classification (bar_chart, line_chart, etc.), page number |
| `equations.json` | LaTeX representation, surrounding context |
| `code_blocks.json` | Code text, detected language |
| `enrichments.json` | All of the above combined |

## Requirements

- Python 3.10-3.12
- [uv](https://docs.astral.sh/uv/) for dependency management
- **Docling**: Automatically downloads ML models on first use (~500MB)
- **Agent**: Requires `claude-agent-sdk` and Claude API access

## Example Workflow

```bash
# 1. Convert with all features
uv run pdf2md convert paper.pdf ./output --keep-raw --enrich --agent

# 2. Check the outputs
ls ./output/paper/
# paper.md          - Final clean markdown
# paper_raw.md      - Original for comparison
# img/              - All figures
# figures.json      - Figure metadata for RAG
# enrichments.json  - All structured data

# 3. Use in your RAG system
cat ./output/paper/figures.json | jq '.[] | .caption'
# "Fig. 1. ChronoLog design overview"
# "Fig. 2. ChronoLog API"
# ...
```

## Untested

- **Equations**: LaTeX extraction depends on PDF structure; some papers may not extract well
- **Code blocks**: Only detected if the PDF has proper structure; scanned PDFs won't work

## License

MIT

"""PyMuPDF-based PDF extraction. No ML models, no CPU overhead.

Extracts text, images, and tables using PyMuPDF (fitz). Figures are
extracted by rendering page regions around figure captions at high
resolution, which correctly captures vector graphics (charts, diagrams).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import fitz

logger = logging.getLogger("pdf2md.extraction.pymupdf")

# Rendering DPI for figure region capture
_RENDER_DPI = 200

# Caption patterns
_FIGURE_CAPTION_RE = re.compile(
    r"(Figure|Fig\.?)\s+(\d+)\s*[:.]\s",
    re.IGNORECASE,
)

_TABLE_CAPTION_RE = re.compile(
    r"Table\s+\d+\s*[:.]\s",
    re.IGNORECASE,
)

# Section headers like "3.1 Problem Formulation"
_SECTION_HEADER_RE = re.compile(r"^\d+(\.\d+)*\s+[A-Z]")

# Minimum figure region height in PDF points (skip if too thin)
_MIN_FIGURE_HEIGHT = 20

# Near-white pixel threshold for whitespace trimming
_WHITE_THRESHOLD = 245


# Common academic section names (case-insensitive matching)
_KNOWN_SECTION_NAMES = {
    "abstract",
    "introduction",
    "background",
    "related work",
    "methodology",
    "methods",
    "method",
    "approach",
    "design",
    "implementation",
    "architecture",
    "system",
    "system design",
    "system overview",
    "evaluation",
    "experiments",
    "experimental setup",
    "experimental results",
    "results",
    "analysis",
    "discussion",
    "limitations",
    "conclusion",
    "conclusions",
    "future work",
    "acknowledgments",
    "acknowledgements",
    "references",
    "appendix",
    "overview",
    "motivation",
    "problem statement",
    "problem formulation",
    "preliminaries",
    "setup",
    "performance",
    "contributions",
}


def _looks_like_section_title(text: str) -> bool:
    """Check if text looks like an academic section title.

    Used to protect section numbers from being stripped as line numbers.
    Conservative: only matches known section names to avoid false positives
    from table data categories like "Alignment characteristics".
    """
    if not text or not text[0].isupper():
        return False

    # Only match against known section names
    return text.lower().rstrip(".:") in _KNOWN_SECTION_NAMES


def _block_text(block: dict) -> str:
    """Extract all text from a text block."""
    parts = []
    for line in block.get("lines", []):
        for span in line.get("spans", []):
            parts.append(span.get("text", ""))
    return "".join(parts).strip()


def _detect_content_margins(doc: fitz.Document) -> tuple[float, float]:
    """Find x-bounds of body text content, excluding line number margins.

    Scans multi-line wide text blocks across pages to find where body
    text starts and ends horizontally. Line numbers sit outside these
    bounds and get excluded from figure crop regions.
    """
    left_edges: list[float] = []
    right_edges: list[float] = []

    for page_num in range(min(len(doc), 10)):
        page = doc[page_num]
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
        for block in blocks:
            if block["type"] != 0:
                continue
            bbox = block["bbox"]
            width = bbox[2] - bbox[0]
            height = bbox[3] - bbox[1]
            # Only consider multi-line body-text-like blocks
            if width > page.rect.width * 0.25 and height > 15:
                left_edges.append(bbox[0])
                right_edges.append(bbox[2])

    if not left_edges:
        page = doc[0]
        return page.rect.x0 + 30, page.rect.x1 - 30

    return min(left_edges), max(right_edges)


def _is_body_text_block(block: dict, col_width: float) -> bool:
    """Identify body text paragraphs by width, height, and text structure.

    Body text spans most of the column width and wraps across multiple
    lines. This distinguishes it from figure-internal labels like axis
    labels, legends, and data annotations, which are narrower or shorter.
    """
    bbox = block["bbox"]
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    text = _block_text(block)

    if not text:
        return False

    # Body text has words separated by spaces
    if " " not in text:
        return False

    # Must be reasonably wide relative to column
    if width < col_width * 0.4:
        return False

    # Multi-line blocks (>= ~2 lines at 9-10pt each) are body text
    if height >= 18:
        return True

    # Wide single-line blocks that are section headers
    if height >= 9 and width >= col_width * 0.5:
        if _SECTION_HEADER_RE.match(text) or _looks_like_section_title(text):
            return True

    return False


def _strip_line_numbers(pages_text: list[str]) -> list[str]:
    """Remove margin line numbers from extracted page text.

    Anonymous submissions often have line numbers (1, 2, 3, ...) in the left
    margin. PyMuPDF extracts these as standalone integer lines interspersed
    with body text. This function detects monotonically increasing sequences
    of standalone integers that span pages and strips them.
    """
    # First pass: build a global sequence of standalone integers across all pages
    # to confirm they form a continuous line-number sequence.
    global_ints: list[tuple[int, int, int]] = []  # (page_idx, line_idx, value)
    for page_idx, text in enumerate(pages_text):
        for line_idx, line in enumerate(text.split("\n")):
            stripped = line.strip()
            if stripped.isdigit() and 1 <= int(stripped) <= 9999:
                global_ints.append((page_idx, line_idx, int(stripped)))

    if len(global_ints) < 20:
        return pages_text  # not enough to be line numbers

    # Check if the integers form a mostly-monotonic sequence (allow small gaps
    # from missed extractions, but the trend must be increasing).
    increasing = 0
    for k in range(1, len(global_ints)):
        if global_ints[k][2] > global_ints[k - 1][2]:
            increasing += 1

    if increasing < len(global_ints) * 0.8:
        return pages_text  # not a line-number sequence

    # Build set of (page_idx, line_idx) to remove, protecting section numbers.
    # A standalone integer followed by a section-title-like line is a section
    # number, not a line number. Protect it from stripping.
    values_in_seq = {v for _, _, v in global_ints}
    pages_lines = [text.split("\n") for text in pages_text]

    to_strip: set[tuple[int, int]] = set()
    for page_idx, line_idx, val in global_ints:
        # Only strip if neighbors exist in the sequence
        if not ((val - 1) in values_in_seq or (val + 1) in values_in_seq):
            continue

        # Protect section numbers: check if next non-empty line looks like a title
        lines = pages_lines[page_idx]
        next_line = ""
        for nli in range(line_idx + 1, min(line_idx + 3, len(lines))):
            candidate = lines[nli].strip()
            if candidate:
                next_line = candidate
                break

        if next_line and _looks_like_section_title(next_line):
            logger.debug(
                "Preserving section number %d (followed by %r)",
                val,
                next_line[:40],
            )
            continue

        to_strip.add((page_idx, line_idx))

    if not to_strip:
        return pages_text

    result = []
    for page_idx, lines in enumerate(pages_lines):
        filtered = [
            line for line_idx, line in enumerate(lines) if (page_idx, line_idx) not in to_strip
        ]
        result.append("\n".join(filtered))

    logger.info("Stripped %d line-number lines across %d pages", len(to_strip), len(pages_text))
    return result


def _deduplicate_headers(pages_text: list[str]) -> list[str]:
    """Remove repeated page headers and footers.

    Running headers (paper title, conference name) and footers (page numbers)
    repeat on every page. Detect short lines appearing on 3+ pages and remove
    all occurrences except the first.
    """
    if len(pages_text) < 3:
        return pages_text

    # Count how many pages each short line appears on
    line_page_count: dict[str, list[int]] = {}
    for page_idx, text in enumerate(pages_text):
        seen_on_page: set[str] = set()
        for line in text.split("\n"):
            normalized = line.strip()
            if not normalized or len(normalized) > 150:
                continue
            if normalized in seen_on_page:
                continue
            seen_on_page.add(normalized)
            line_page_count.setdefault(normalized, []).append(page_idx)

    # Lines appearing on 3+ pages are headers/footers
    header_lines: set[str] = set()
    for line_text, page_indices in line_page_count.items():
        if len(page_indices) >= 3:
            # Skip lines that are just a number (could be legitimate repeated content)
            if line_text.isdigit():
                continue
            # Skip very short lines (single words that might be common)
            if len(line_text) < 5:
                continue
            header_lines.add(line_text)

    if not header_lines:
        return pages_text

    # For lines that appear on page 0 as well: keep only the page 0 occurrence.
    # For lines that DON'T appear on page 0 (running headers that differ from
    # the actual title on page 1): remove ALL occurrences, since the real
    # content is already present in a different form on page 0.
    on_page_zero = {
        lt for lt, pages in line_page_count.items() if lt in header_lines and 0 in pages
    }

    first_seen: dict[str, tuple[int, int]] = {}
    result = []
    for page_idx, text in enumerate(pages_text):
        lines = text.split("\n")
        filtered = []
        for line_idx, line in enumerate(lines):
            normalized = line.strip()
            if normalized in header_lines:
                if normalized in on_page_zero:
                    # Keep only the first occurrence (on page 0)
                    if normalized not in first_seen:
                        first_seen[normalized] = (page_idx, line_idx)
                        filtered.append(line)
                # else: remove all occurrences (running header not on page 0)
            else:
                filtered.append(line)
        result.append("\n".join(filtered))

    logger.info(
        "Deduplicated %d repeated header/footer lines",
        len(header_lines),
    )
    return result


def _find_figure_regions(
    doc: fitz.Document,
    content_margins: tuple[float, float],
) -> list[dict]:
    """Locate figure regions by caption position and body text boundaries.

    Uses the full caption text block bbox (not just the "Figure N:" prefix)
    for accurate column vs full-width detection. Positively identifies body
    text paragraphs (by width and height) to determine where figures begin.
    Figure-internal elements like axis labels, legends, and data annotations
    are inherently excluded because they fail the body text checks.
    """
    content_left, content_right = content_margins
    figures: list[dict] = []
    seen_ids: set[int] = set()

    for page_num in range(len(doc)):
        page = doc[page_num]
        page_rect = page.rect

        # Get all text blocks once per page
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]

        # Find figure captions directly from text blocks so we get the
        # full block bbox (not just the short "Figure N:" prefix).
        for caption_block in blocks:
            if caption_block["type"] != 0:
                continue

            caption_txt = _block_text(caption_block)
            m = _FIGURE_CAPTION_RE.match(caption_txt)
            if not m:
                continue

            fig_id = int(m.group(2))
            if fig_id in seen_ids:
                continue
            seen_ids.add(fig_id)

            caption_bbox = caption_block["bbox"]
            caption_y0 = caption_bbox[1]
            caption_width = caption_bbox[2] - caption_bbox[0]
            caption_center = (caption_bbox[0] + caption_bbox[2]) / 2

            # Determine column vs full-width layout using the full
            # caption block width, not just the "Figure N:" prefix.
            page_mid_x = page_rect.width / 2
            is_centered = abs(caption_center - page_mid_x) < page_mid_x * 0.15
            is_wide_caption = caption_width > page_rect.width * 0.35
            is_full_width = caption_width > page_rect.width * 0.5 or (
                is_centered and is_wide_caption
            )

            if is_full_width:
                col_x0 = max(content_left - 2, page_rect.x0)
                col_x1 = min(content_right + 2, page_rect.x1)
            elif caption_center < page_mid_x:
                # Left column
                col_x0 = max(content_left - 2, page_rect.x0)
                col_x1 = page_mid_x - 5
            else:
                # Right column
                col_x0 = page_mid_x + 5
                col_x1 = min(content_right + 2, page_rect.x1)

            col_width = col_x1 - col_x0

            # Find the figure region above the caption by identifying
            # the nearest body text paragraph boundary.
            above_y = page_rect.y0  # default: page top
            for block in blocks:
                if block["type"] != 0:
                    continue

                block_bbox = block["bbox"]
                block_bottom = block_bbox[3]
                block_center_x = (block_bbox[0] + block_bbox[2]) / 2

                # Must be above caption
                if block_bottom >= caption_y0 - 2:
                    continue

                # Must be in the same column region
                in_column = (col_x0 <= block_center_x <= col_x1) or (
                    block_bbox[2] - block_bbox[0] > page_rect.width * 0.5
                )
                if not in_column:
                    continue

                block_txt = _block_text(block)

                # Figure and table captions set boundaries
                if _FIGURE_CAPTION_RE.match(block_txt):
                    above_y = max(above_y, block_bottom + 5)
                    continue
                if _TABLE_CAPTION_RE.match(block_txt):
                    above_y = max(above_y, block_bottom + 5)
                    continue

                # Only body text paragraphs set the upper boundary.
                # Figure-internal elements (axis labels, legends, data
                # annotations) are narrow or short and fail this check.
                if _is_body_text_block(block, col_width):
                    above_y = max(above_y, block_bottom)

            # Build figure rect
            fig_rect = fitz.Rect(
                col_x0,
                max(above_y, page_rect.y0),
                col_x1,
                caption_y0 - 2,
            )

            if fig_rect.height < _MIN_FIGURE_HEIGHT:
                logger.debug(
                    "Skipping figure %d on page %d: region too thin (%.0f pt)",
                    fig_id,
                    page_num + 1,
                    fig_rect.height,
                )
                continue

            figures.append(
                {
                    "page": page_num,
                    "figure_id": fig_id,
                    "caption": caption_txt[:60],
                    "rect": fig_rect,
                }
            )

    return figures


def _trim_whitespace(pix: fitz.Pixmap) -> fitz.Pixmap:
    """Trim whitespace rows from top and bottom of a rendered figure.

    Scans for near-white rows and crops them, leaving a small padding.
    Handles cases where the detected region extends above the actual
    figure content (e.g., page headers or tables above the figure).

    PyMuPDF pixmaps from clipped rendering retain absolute page
    coordinates (irect origin is NOT (0,0)), so crop rects must
    use the pixmap's coordinate system.
    """
    n = pix.n
    stride = pix.stride
    samples = pix.samples

    # Find first non-white row from top (0-based pixel row)
    top = 0
    for y in range(pix.height):
        offset = y * stride
        row = samples[offset : offset + pix.width * n]
        if min(row) < _WHITE_THRESHOLD:
            top = y
            break
    else:
        return pix  # entirely white

    # Find last non-white row from bottom
    bottom = pix.height
    for y in range(pix.height - 1, top - 1, -1):
        offset = y * stride
        row = samples[offset : offset + pix.width * n]
        if min(row) < _WHITE_THRESHOLD:
            bottom = y + 1
            break

    # Add padding (in pixel rows)
    top = max(0, top - 10)
    bottom = min(pix.height, bottom + 10)

    if bottom - top < 30 or (top == 0 and bottom == pix.height):
        return pix

    # Convert pixel-row offsets to the pixmap's absolute coordinate system
    irect = pix.irect
    if isinstance(irect, tuple):
        px0, py0, px1, _py1 = irect
    else:
        px0, py0, px1, _py1 = irect.x0, irect.y0, irect.x1, irect.y1

    crop = fitz.IRect(px0, py0 + top, px1, py0 + bottom)
    cropped = fitz.Pixmap(pix.colorspace, crop, pix.alpha)
    cropped.copy(pix, crop)
    return cropped


def _render_figure_region(
    doc: fitz.Document,
    page_num: int,
    rect: fitz.Rect,
    output_path: Path,
    dpi: int = _RENDER_DPI,
) -> bool:
    """Render a specific page region to a PNG file at high resolution."""
    page = doc[page_num]
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, clip=rect)

    if pix.width < 50 or pix.height < 30:
        return False

    # Trim whitespace rows from top/bottom
    pix = _trim_whitespace(pix)
    if pix.width < 50 or pix.height < 30:
        return False

    pix.save(str(output_path))
    return True


def _extract_images_fallback(
    doc: fitz.Document,
    img_dir: Path,
    min_width: int,
    min_height: int,
    min_area: int,
) -> list[Path]:
    """Fall back to extracting embedded raster XObjects when no captions found.

    For non-academic PDFs that lack "Figure N:" captions, extract images
    directly from the PDF's internal image objects.
    """
    images: list[Path] = []
    seen_xrefs: set[int] = set()

    for page_num in range(len(doc)):
        page = doc[page_num]
        image_list = page.get_images(full=True)
        for img_idx, img_info in enumerate(image_list):
            xref = img_info[0]
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)
            try:
                pix = fitz.Pixmap(doc, xref)
                if pix.width < min_width or pix.height < min_height:
                    continue
                if pix.width * pix.height < min_area:
                    continue
                # Convert CMYK or other colorspaces to RGB
                if pix.n > 4:
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                img_path = img_dir / f"image_p{page_num + 1}_{img_idx + 1}.png"
                pix.save(str(img_path))
                images.append(img_path)
            except Exception as e:
                logger.debug("Failed to extract image xref %d: %s", xref, e)

    return images


def extract_with_pymupdf(
    pdf_path: Path,
    output_dir: Path,
    *,
    images_scale: float = 2.0,
    min_image_width: int = 200,
    min_image_height: int = 150,
    min_image_area: int = 40000,
    extract_tables: bool = True,
) -> tuple[Path, list[Path], list[dict]]:
    """Extract markdown text, figures, and tables from a PDF using PyMuPDF.

    Figures are extracted by rendering page regions around figure captions
    at high resolution. This captures vector graphics (charts, diagrams,
    flowcharts) that are invisible to raster-only extraction. Tables are
    extracted using PyMuPDF's built-in table detector (no ML).

    Returns:
        Tuple of (markdown_path, list_of_image_paths, list_of_table_dicts)
    """
    pdf_stem = pdf_path.stem
    doc_dir = output_dir / pdf_stem
    doc_dir.mkdir(parents=True, exist_ok=True)
    img_dir = doc_dir / "img"
    img_dir.mkdir(exist_ok=True)

    doc = fitz.open(str(pdf_path))

    # ── Extract text ──────────────────────────────────────────────────
    md_parts: list[str] = []
    for page_num, page in enumerate(doc):
        text = page.get_text("text")
        if text.strip():
            md_parts.append(text)

    # Strip margin line numbers (anonymous submissions)
    md_parts = _strip_line_numbers(md_parts)

    # Remove repeated page headers/footers
    md_parts = _deduplicate_headers(md_parts)

    full_text = "\n\n".join(md_parts)

    # ── Detect content margins (excludes line number gutters) ────────
    content_margins = _detect_content_margins(doc)

    # ── Extract figures by rendering page regions ─────────────────────
    images: list[Path] = []
    figure_regions = _find_figure_regions(doc, content_margins)

    render_dpi = int(72 * images_scale) if images_scale != 2.0 else _RENDER_DPI

    for fig_info in figure_regions:
        fig_id = fig_info["figure_id"]
        img_path = img_dir / f"figure{fig_id}.png"

        ok = _render_figure_region(
            doc,
            fig_info["page"],
            fig_info["rect"],
            img_path,
            dpi=render_dpi,
        )
        if ok:
            images.append(img_path)
            logger.debug(
                "Rendered figure %d from page %d",
                fig_id,
                fig_info["page"] + 1,
            )
        else:
            logger.warning(
                "Failed to render figure %d from page %d",
                fig_id,
                fig_info["page"] + 1,
            )

    # Fall back to embedded image extraction if no captions found
    if not figure_regions:
        images = _extract_images_fallback(
            doc, img_dir, min_image_width, min_image_height, min_image_area
        )
        if images:
            logger.info(
                "No figure captions found; extracted %d embedded images as fallback",
                len(images),
            )

    # Warn if we found fewer figures than captions in the text
    caption_ids = set()
    for m in _FIGURE_CAPTION_RE.finditer(full_text):
        caption_ids.add(int(m.group(2)))
    rendered_ids = {fig["figure_id"] for fig in figure_regions}
    missed = caption_ids - rendered_ids
    if missed:
        logger.warning(
            "Missed figures (caption found but region not extracted): %s",
            sorted(missed),
        )

    # Sort images by figure number
    def _fig_sort_key(p: Path) -> int:
        m = re.search(r"\d+", p.stem)
        return int(m.group()) if m else 0

    images.sort(key=_fig_sort_key)

    # ── Extract tables ────────────────────────────────────────────────
    tables: list[dict] = []
    if extract_tables:
        for page_num, page in enumerate(doc):
            try:
                page_tables = page.find_tables()
                for t_idx, table in enumerate(page_tables.tables):
                    cells = table.extract()
                    if not cells or len(cells) < 2:
                        continue

                    # Validate: reject false positive tables
                    num_cols = len(cells[0]) if cells else 0
                    num_rows = len(cells)

                    # Reject tiny tables (2 cols, <3 rows) — often two-column layout artifacts
                    if num_cols <= 2 and num_rows < 3:
                        continue

                    # Reject tables with overly long cells (paragraphs, not table data)
                    has_long_cell = any(len(str(c).strip()) > 50 for row in cells for c in row if c)
                    if has_long_cell:
                        logger.debug(
                            "Skipping false-positive table on page %d: cell >50 chars",
                            page_num + 1,
                        )
                        continue

                    # Reject tables where header contains newlines (complex layout)
                    header_has_newlines = any("\n" in str(c) for c in cells[0] if c)
                    if header_has_newlines:
                        logger.debug(
                            "Skipping false-positive table on page %d: header has newlines",
                            page_num + 1,
                        )
                        continue

                    md_rows: list[str] = []
                    header = cells[0]
                    header_cols = [str(c).strip() if c else "" for c in header]
                    md_rows.append("| " + " | ".join(header_cols) + " |")
                    md_rows.append("| " + " | ".join("---" for _ in header_cols) + " |")
                    for row in cells[1:]:
                        row_cols = [str(c).strip() if c else "" for c in row]
                        md_rows.append("| " + " | ".join(row_cols) + " |")

                    tables.append(
                        {
                            "page": page_num + 1,
                            "table_index": t_idx,
                            "markdown": "\n".join(md_rows),
                            "num_rows": len(cells),
                            "num_cols": len(cells[0]) if cells else 0,
                        }
                    )
            except Exception as e:
                logger.debug(
                    "Table extraction failed on page %d: %s",
                    page_num + 1,
                    e,
                )

    doc.close()

    # Write markdown
    md_path = doc_dir / f"{pdf_stem}.md"
    md_path.write_text(full_text, encoding="utf-8")

    logger.info(
        "Extracted %d chars, %d figures, %d tables from %s",
        len(full_text),
        len(images),
        len(tables),
        pdf_path.name,
    )

    return md_path, images, tables

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

# Minimum figure region height in PDF points (skip if too thin)
_MIN_FIGURE_HEIGHT = 30

# Short text blocks inside chart areas (axis labels, annotations)
# are identified by their height and character count
_ANNOTATION_MAX_HEIGHT = 15  # points
_ANNOTATION_MAX_CHARS = 40


def _find_figure_regions(doc: fitz.Document) -> list[dict]:
    """Locate figure regions by searching for caption text on each page.

    Uses page.search_for() to find the exact position of each
    "Figure N:" caption, then determines the figure region above it
    by looking at the gap between text lines.
    """
    figures: list[dict] = []
    seen_ids: set[int] = set()

    for page_num in range(len(doc)):
        page = doc[page_num]
        page_rect = page.rect
        text = page.get_text("text")

        # Find all caption matches in the page text
        for m in _FIGURE_CAPTION_RE.finditer(text):
            fig_id = int(m.group(2))
            if fig_id in seen_ids:
                continue

            # Search for the caption text position on the page
            search_text = m.group(0).strip()
            rects = page.search_for(search_text, quads=False)
            if not rects:
                continue

            # Use the first match (topmost occurrence)
            caption_rect = rects[0]
            seen_ids.add(fig_id)

            # Determine the column the caption is in
            page_mid_x = page_rect.width / 2
            if caption_rect.x0 < page_mid_x:
                # Left column
                col_x0 = page_rect.x0 + 5
                col_x1 = page_mid_x - 5
            else:
                # Right column
                col_x0 = page_mid_x + 5
                col_x1 = page_rect.x1 - 5

            # For full-width figures (caption spans both columns)
            if caption_rect.width > page_rect.width * 0.5:
                col_x0 = page_rect.x0 + 5
                col_x1 = page_rect.x1 - 5

            # Find the figure region above the caption.
            # Get all text blocks and find the nearest text above the
            # caption that's in the same column.
            blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]

            above_y = page_rect.y0  # default: page top
            for block in blocks:
                if block["type"] != 0:
                    continue

                block_bbox = block["bbox"]
                block_bottom = block_bbox[3]
                block_center_x = (block_bbox[0] + block_bbox[2]) / 2

                # Must be above caption
                if block_bottom >= caption_rect.y0 - 2:
                    continue

                # Must be in the same column region
                in_column = (
                    (col_x0 <= block_center_x <= col_x1) or
                    (block_bbox[2] - block_bbox[0] > page_rect.width * 0.5)
                )
                if not in_column:
                    continue

                block_text = ""
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        block_text += span.get("text", "")
                block_text = block_text.strip()

                # Skip another figure's caption
                if _FIGURE_CAPTION_RE.match(block_text):
                    above_y = max(above_y, block_bottom + 5)
                    continue

                block_height = block_bbox[3] - block_bbox[1]

                # Skip short annotation-like blocks (axis labels,
                # data labels) that sit inside the chart area
                if (
                    block_height <= _ANNOTATION_MAX_HEIGHT
                    and len(block_text) <= _ANNOTATION_MAX_CHARS
                ):
                    continue

                # Skip blocks that are mostly numeric data (heatmap
                # values, chart data rendered as text inside figures)
                alpha_chars = sum(1 for c in block_text if c.isalpha())
                if len(block_text) > 20 and alpha_chars < len(block_text) * 0.3:
                    continue

                # Skip concatenated axis labels (no spaces = labels
                # extracted as a single run, e.g. "ABCDEFGActivity")
                if " " not in block_text and len(block_text) < 60:
                    continue

                above_y = max(above_y, block_bottom)

            # Build figure rect
            fig_rect = fitz.Rect(
                col_x0,
                max(above_y, page_rect.y0),
                col_x1,
                caption_rect.y0 - 2,
            )

            if fig_rect.height < _MIN_FIGURE_HEIGHT:
                logger.debug(
                    "Skipping figure %d on page %d: region too thin (%.0f pt)",
                    fig_id, page_num + 1, fig_rect.height,
                )
                continue

            figures.append({
                "page": page_num,
                "figure_id": fig_id,
                "caption": search_text,
                "rect": fig_rect,
            })

    return figures


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

    pix.save(str(output_path))
    return True


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

    full_text = "\n\n".join(md_parts)

    # ── Extract figures by rendering page regions ─────────────────────
    images: list[Path] = []
    figure_regions = _find_figure_regions(doc)

    render_dpi = int(72 * images_scale) if images_scale != 2.0 else _RENDER_DPI

    for fig_info in figure_regions:
        fig_id = fig_info["figure_id"]
        img_path = img_dir / f"figure{fig_id}.png"

        ok = _render_figure_region(
            doc, fig_info["page"], fig_info["rect"], img_path, dpi=render_dpi,
        )
        if ok:
            images.append(img_path)
            logger.debug(
                "Rendered figure %d from page %d",
                fig_id, fig_info["page"] + 1,
            )
        else:
            logger.warning(
                "Failed to render figure %d from page %d",
                fig_id, fig_info["page"] + 1,
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

                    md_rows: list[str] = []
                    header = cells[0]
                    header_cols = [str(c).strip() if c else "" for c in header]
                    md_rows.append("| " + " | ".join(header_cols) + " |")
                    md_rows.append("| " + " | ".join("---" for _ in header_cols) + " |")
                    for row in cells[1:]:
                        row_cols = [str(c).strip() if c else "" for c in row]
                        md_rows.append("| " + " | ".join(row_cols) + " |")

                    tables.append({
                        "page": page_num + 1,
                        "table_index": t_idx,
                        "markdown": "\n".join(md_rows),
                        "num_rows": len(cells),
                        "num_cols": len(cells[0]) if cells else 0,
                    })
            except Exception as e:
                logger.debug(
                    "Table extraction failed on page %d: %s", page_num + 1, e,
                )

    doc.close()

    # Write markdown
    md_path = doc_dir / f"{pdf_stem}.md"
    md_path.write_text(full_text, encoding="utf-8")

    logger.info(
        "Extracted %d chars, %d figures, %d tables from %s",
        len(full_text), len(images), len(tables), pdf_path.name,
    )

    return md_path, images, tables

"""Table processing: embed structured markdown tables at their captions.

Replaces garbled flat-text table content with properly formatted markdown
tables extracted by PyMuPDF's page.find_tables().
"""

from __future__ import annotations

import re

_TABLE_CAPTION_RE = re.compile(
    r"^\s*(?:\*\*)?Table\s+(\d+)\s*[.:]\s*",
    re.IGNORECASE,
)


def process_tables(content: str, tables: list[dict]) -> str:
    """Insert structured markdown tables after their captions.

    Matches extracted tables to "Table N:" captions by sequential order
    (both are in page order). Inserts the formatted markdown table after
    the caption and removes garbled flat-text that PyMuPDF extracted as
    the same table content.

    Args:
        content: Markdown content
        tables: List of table dicts from PyMuPDF extraction, each with
                "page", "markdown", "num_rows", "num_cols" keys.

    Returns:
        Content with structured markdown tables inserted.
    """
    if not tables:
        return content

    # Build a queue of tables to insert (in page order, already sorted)
    table_queue = list(tables)

    lines = content.split("\n")
    result: list[str] = []
    used_tables: set[int] = set()
    i = 0

    while i < len(lines):
        line = lines[i]

        cap_match = _TABLE_CAPTION_RE.match(line.strip())
        if cap_match and table_queue:
            # Found a table caption, insert the next available table
            table_idx = _find_best_table(table_queue, used_tables)
            result.append(line)

            if table_idx is not None:
                used_tables.add(table_idx)
                table_md = table_queue[table_idx]["markdown"]
                result.append("")
                result.append(table_md)
                result.append("")

                # Skip garbled flat-text lines after the caption that
                # look like table data (short fragments, lots of numbers,
                # no sentence structure)
                i += 1
                skipped = 0
                while i < len(lines) and skipped < 30:
                    next_stripped = lines[i].strip()
                    if not next_stripped:
                        # Allow one blank line in the garbled region
                        if i + 1 < len(lines) and _is_table_garble(lines[i + 1].strip()):
                            i += 1
                            skipped += 1
                            continue
                        break
                    if _is_table_garble(next_stripped):
                        i += 1
                        skipped += 1
                        continue
                    break
                continue
            else:
                i += 1
                continue

        result.append(line)
        i += 1

    return "\n".join(result)


def _find_best_table(table_queue: list[dict], used: set[int]) -> int | None:
    """Find the next unused table in the queue."""
    for idx in range(len(table_queue)):
        if idx not in used:
            return idx
    return None


def _is_table_garble(line: str) -> bool:
    """Check if a line looks like garbled flat-text table data.

    Table data in flat text has lots of numbers, short fragments,
    dimension-like patterns (N × N), and no proper sentence structure.
    """
    if not line:
        return False

    # Don't remove structural lines
    if line.startswith("#") or line.startswith("![") or line.startswith("|"):
        return False
    if line.startswith(">") or line.startswith("- ") or line.startswith("```"):
        return False

    # Don't remove figure/table captions or section numbers
    if re.match(r"^(Figure|Fig\.?|Table)\s+\d+", line, re.IGNORECASE):
        return False
    if re.match(r"^\d+(\.\d+)*\s+[A-Z]", line):
        return False

    # Table garble indicators: lots of numbers, dimension patterns,
    # very short fragments with mixed numbers and words
    digit_chars = sum(1 for c in line if c.isdigit())
    total_chars = len(line)

    # High digit density (>40% digits) in short lines
    if total_chars < 100 and total_chars > 0 and digit_chars / total_chars > 0.4:
        return True

    # Dimension patterns like "100 × 500 × 500"
    if re.search(r"\d+\s*[×x]\s*\d+", line):
        return True

    # Very short fragments without sentence structure (no period at end)
    if total_chars < 40 and not re.search(r"[.!?]$", line) and digit_chars > 2:
        return True

    return False

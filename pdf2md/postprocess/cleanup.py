"""General text cleanup: ligatures, whitespace, OCR artifacts, split paragraphs."""

from __future__ import annotations

import re


def cleanup_text(content: str) -> str:
    """
    Apply general text cleanup to markdown content.

    Handles (in order):
    1. Remove <!-- image --> placeholder comments
    2. Fix ligatures (fi, fl, ff, etc.)
    3. Fix GLYPH<N> artifacts from Docling
    4. Remove OCR-extracted garbage near figure embeds
    5. Fix hyphenated words split at line endings
    6. Merge paragraphs split by page breaks
    7. Collapse excessive blank lines
    8. Strip trailing whitespace
    """
    content = _remove_image_comments(content)
    content = _fix_ligatures(content)
    content = _fix_math_font_garble(content)
    content = _fix_glyph_artifacts(content)
    content = _remove_ocr_artifacts_near_figures(content)
    content = _fix_hyphenated_words(content)
    content = _merge_split_paragraphs(content)
    content = _fix_excessive_blank_lines(content)
    content = _fix_trailing_whitespace(content)
    return content


# ---------------------------------------------------------------------------
# Individual cleanup functions
# ---------------------------------------------------------------------------


def _remove_image_comments(content: str) -> str:
    """Remove <!-- image --> placeholder comments left by Docling."""
    lines = content.split("\n")
    return "\n".join(line for line in lines if line.strip() != "<!-- image -->")


def _fix_ligatures(content: str) -> str:
    """Replace common ligature characters with their ASCII equivalents."""
    ligatures = {
        "\ufb01": "fi",
        "\ufb02": "fl",
        "\ufb00": "ff",
        "\ufb03": "ffi",
        "\ufb04": "ffl",
        "\ufb05": "ft",
        "\ufb06": "st",
        # Common dash variants
        "\u2013": "-",  # en-dash to hyphen
    }

    for ligature, replacement in ligatures.items():
        content = content.replace(ligature, replacement)

    return content


def _fix_math_font_garble(content: str) -> str:
    """Fix garbled math font characters from PDF extraction.

    PDF math fonts use codepoints in the Mathematical Alphanumeric Symbols
    block (U+1D400-U+1D7FF). Some extractors truncate these to the BMP,
    producing Hangul syllables (U+D400-U+D7FF) or other wrong characters.
    This function maps them back to plain ASCII letters.
    """
    # Build mapping: Hangul-range codepoints → intended ASCII letters
    # Mathematical Italic Capital: U+1D434 (A) → extracted as U+D434
    # Mathematical Italic Small: U+1D44E (a) → extracted as U+D44E
    mapping = {}

    # Italic capitals A-Z (U+1D434-U+1D44D → U+D434-D44D)
    for i in range(26):
        mapping[chr(0xD434 + i)] = chr(ord("A") + i)

    # Italic smalls a-z (U+1D44E-U+1D467 → U+D44E-D467)
    for i in range(26):
        mapping[chr(0xD44E + i)] = chr(ord("a") + i)

    # Bold capitals A-Z (U+1D400-U+1D419 → U+D400-D419)
    for i in range(26):
        mapping[chr(0xD400 + i)] = chr(ord("A") + i)

    # Bold smalls a-z (U+1D41A-U+1D433 → U+D41A-D433)
    for i in range(26):
        mapping[chr(0xD41A + i)] = chr(ord("a") + i)

    # Script/calligraphic capitals (U+1D49C → U+D49C, etc.)
    for i in range(26):
        mapping[chr(0xD49C + i)] = chr(ord("A") + i)

    # Common math symbols that get garbled
    extra = {
        "\u210E": "h",  # PLANCK CONSTANT (ℎ)
        "\u2113": "l",  # SCRIPT SMALL L (ℓ)
        "\u2102": "C",  # DOUBLE-STRUCK C (ℂ)
        "\u211D": "R",  # DOUBLE-STRUCK R (ℝ)
        "\u2115": "N",  # DOUBLE-STRUCK N (ℕ)
        "\u2124": "Z",  # DOUBLE-STRUCK Z (ℤ)
    }
    mapping.update(extra)

    # Fast path: check if any Hangul-range math chars are present
    if not re.search(r"[\uD400-\uD4FF]|[\u210E\u2113\u2102\u211D\u2115\u2124]", content):
        return content

    for garbled, fixed in mapping.items():
        content = content.replace(garbled, fixed)

    return content


def _fix_glyph_artifacts(content: str) -> str:
    """Remove GLYPH<N> artifacts from Docling extraction.

    These appear when Docling cannot map a PDF glyph to Unicode.
    Both raw angle brackets and HTML-entity variants are handled.
    """
    content = re.sub(r"GLYPH<\d+>", "", content)
    content = re.sub(r"GLYPH&lt;\d+&gt;", "", content)
    return content


def _remove_ocr_artifacts_near_figures(content: str) -> str:
    """Remove OCR-extracted garbage text appearing before figure embeds.

    Docling sometimes OCRs text from figure images (axis labels, legend
    fragments, subplot markers like '(a)', '(b)') and places them as body
    text above the figure. These appear as clusters of short lines directly
    preceding ![Figure N] embeds.

    Heuristic: 2+ consecutive short (<60 char) non-structural lines that
    don't end with sentence punctuation, appearing right before a figure
    embed, are treated as OCR artifacts and removed.
    """
    lines = content.split("\n")
    to_remove: set[int] = set()

    for i, line in enumerate(lines):
        if not re.match(r"^!\[Figure \d+\]", line.strip()):
            continue

        # Scan backwards from the figure embed, collecting artifact candidates
        candidates: list[int] = []
        j = i - 1
        while j >= 0:
            stripped = lines[j].strip()
            if not stripped:
                j -= 1
                continue  # skip blank lines

            # Stop if we hit real content
            if (
                len(stripped) > 60
                or stripped.startswith("#")
                or stripped.startswith("![")
                or stripped.startswith("|")
                or re.match(r"^\d+[.)]\s", stripped)
                or re.match(r"^[-*]\s", stripped)
                or re.match(r"^(Fig|Figure|Table)\b", stripped)
                or re.search(r"[.!?:;]$", stripped)
            ):
                break

            candidates.append(j)
            j -= 1

        # Only remove if 2+ short non-structural lines form a cluster
        if len(candidates) >= 2:
            for idx in candidates:
                to_remove.add(idx)
            # Also remove blank lines interspersed in the cluster
            cluster_start = min(candidates)
            for k in range(cluster_start, i):
                if not lines[k].strip():
                    to_remove.add(k)

    return "\n".join(line for i, line in enumerate(lines) if i not in to_remove)


def _fix_hyphenated_words(content: str) -> str:
    """Fix words broken by hyphenation at line endings.

    Handles both direct newlines and blank-line-separated breaks:
    - "band-\\nwidth" -> "bandwidth"
    - "band-\\n\\nwidth" -> "bandwidth"
    - "client-\\n\\nto-server" -> "client-to-server" (compound preserved)

    Skips headings and code fences to avoid corrupting markdown structure.
    """
    lines = content.split("\n")
    protected: set[int] = set()
    in_code_fence = False

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_fence = not in_code_fence
            protected.add(i)
            continue
        if in_code_fence:
            protected.add(i)
            continue
        if stripped.startswith("#"):
            protected.add(i)

    # Rebuild content, replacing only unprotected line boundaries
    result: list[str] = list(lines)
    to_remove: set[int] = set()

    for i in range(len(result) - 1):
        if i in protected or i in to_remove:
            continue
        line = result[i]
        # Check for word-hyphen at end of line
        m = re.search(r"(\w+)-$", line.rstrip())
        if not m:
            continue

        # Find next non-blank line
        next_idx = i + 1
        blank_gap = False
        if next_idx < len(result) and result[next_idx].strip() == "":
            blank_gap = True
            next_idx = i + 2

        if next_idx >= len(result) or next_idx in protected:
            continue

        next_line = result[next_idx].strip()
        if not next_line or not next_line[0].islower():
            continue

        # Check if it's a compound word (continuation has its own hyphen)
        compound = re.match(r"^([a-z]\w*)-", next_line)
        if compound:
            # Preserve the hyphen: "client-" + "to-server" → "client-to-server"
            merged = line.rstrip().rstrip("-") + "-" + next_line
        else:
            # Remove the hyphen: "band-" + "width" → "bandwidth"
            merged = line.rstrip().rstrip("-") + next_line

        result[i] = merged
        to_remove.add(next_idx)
        if blank_gap:
            to_remove.add(i + 1)

    return "\n".join(line for idx, line in enumerate(result) if idx not in to_remove)


def _merge_split_paragraphs(content: str) -> str:
    """Merge paragraphs split by page breaks.

    Detects: line ending without sentence termination (.!?:;)
    followed by blank line, followed by continuation (lowercase start
    or common continuation words like parenthetical).
    """
    lines = content.split("\n")
    result: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]

        if (
            i + 2 < len(lines)
            and line.strip()
            and not line.strip().startswith("#")
            and not line.strip().startswith("![")
            and not line.strip().startswith("-")
            and not line.strip().startswith("*")
            and not line.strip().startswith("|")
            and not re.match(r"^\d+[.)]\s", line.strip())
            and not re.search(r'[.!?:;"\)>]$', line.rstrip())
            and lines[i + 1].strip() == ""
            and lines[i + 2].strip()
            and not lines[i + 2].strip().startswith("#")
            and not lines[i + 2].strip().startswith("![")
            and not lines[i + 2].strip().startswith("-")
            and not lines[i + 2].strip().startswith("*")
            and not lines[i + 2].strip().startswith("|")
            and not re.match(r"^\d+[.)]\s", lines[i + 2].strip())
            and not re.match(r"^(Fig|Figure|Table)\b", lines[i + 2].strip())
        ):
            next_line = lines[i + 2].strip()
            if next_line and (next_line[0].islower() or next_line.startswith("(")):
                result.append(line.rstrip() + " " + next_line)
                i += 3
                continue

        result.append(line)
        i += 1

    return "\n".join(result)


def _fix_excessive_blank_lines(content: str) -> str:
    """Reduce multiple consecutive blank lines to maximum of 2."""
    return re.sub(r"\n{3,}", "\n\n", content)


def _fix_trailing_whitespace(content: str) -> str:
    """Remove trailing whitespace from each line."""
    lines = content.split("\n")
    return "\n".join(line.rstrip() for line in lines)

"""Section processing: fix headers and subsection detection.

Handles hierarchical section numbering in academic papers:
- Section: ## 1. INTRODUCTION or ## I. INTRODUCTION
- Subsection: ### 1.1 Background
- Subsubsection: #### 1.1.1 Details
- Paragraph: ##### 1.1.1.1 Fine details

Note: Lettered sections (A., B., etc.) are handled by the Claude agent
in cleanup.py since they require context to distinguish from sentences
starting with letters (e.g., "A. We conducted..." vs "A. Background").
"""

from __future__ import annotations

import re

# Maximum title length for a section header (longer text is likely a paragraph)
MAX_TITLE_LENGTH = 120


def process_sections(content: str) -> str:
    """
    Process section headers in markdown content.

    Handles:
    - Abstract artifacts: "Abstract -Modern HPC..." → "## Abstract\\n\\nModern HPC..."
    - Index Terms: "Index Terms -keywords" → "## Index Terms\\n\\nkeywords"
    - Numbered sections: "3.1.1 Design overview." → "#### 3.1.1 Design overview"
    - Bullet subsections: "- 1) Title:" → "### 1) Title"

    Note: Lettered sections (A., B.) are delegated to the Claude agent
    for better context-aware detection.

    Args:
        content: Markdown content

    Returns:
        Content with fixed section headers
    """
    content = _fix_abstract_header(content)
    content = _fix_index_terms_header(content)
    content = _fix_unnumbered_sections(content)
    content = _fix_hierarchical_sections(content)
    # Lettered sections removed - handled by agent (see cleanup.py)
    content = _fix_numbered_bullet_subsections(content)
    return content


def _fix_abstract_header(content: str) -> str:
    """
    Fix Abstract header artifacts.

    "Abstract -Modern HPC..." → "## Abstract\\n\\nModern HPC..."
    "Abstract-Modern HPC..." → "## Abstract\\n\\nModern HPC..."
    "Abstract" (standalone) → "## Abstract"
    """
    # Pattern 1: Abstract followed by dash then text
    pattern = r"^(#+\s*)?Abstract\s*[-–—]\s*"
    content = re.sub(
        pattern, "## Abstract\n\n", content, count=1, flags=re.MULTILINE | re.IGNORECASE
    )

    # Pattern 2: Standalone "Abstract" on its own line (not already a header)
    content = re.sub(
        r"^(?!#)Abstract\s*$",
        "## Abstract",
        content,
        count=1,
        flags=re.MULTILINE | re.IGNORECASE,
    )
    return content


def _fix_index_terms_header(content: str) -> str:
    """
    Fix Index Terms header artifacts.

    "Index Terms -keywords" → "## Index Terms\\n\\nkeywords"
    """
    pattern = r"^(#+\s*)?Index Terms\s*[-–—]\s*"
    replacement = "## Index Terms\n\n"
    return re.sub(pattern, replacement, content, count=1, flags=re.MULTILINE | re.IGNORECASE)


# Known academic section names that can appear without numbering
_UNNUMBERED_SECTIONS = {
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
    "system overview",
    "system design",
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
    "contributions",
    "ccs concepts",
    "keywords",
    "index terms",
    "background and related work",
    "research overview",
    "related work and background",
    "system architecture",
    "experimental evaluation",
    "performance evaluation",
    "implementation and evaluation",
    "problem definition",
    "threat model",
    "use cases",
    "case study",
    "case studies",
}


def _fix_unnumbered_sections(content: str) -> str:
    """Convert standalone known section names to markdown headers.

    Handles papers where section titles appear on their own line without
    numbering, common in ACM-format anonymous submissions. Also detects
    section titles merged into paragraph starts after reflow (e.g.,
    "Background and Related Work In this section...").
    """
    lines = content.split("\n")
    result = []

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Skip already-processed headers
        if stripped.startswith("#"):
            result.append(line)
            continue

        # Check if this line is a known section name (standalone)
        normalized = stripped.lower().rstrip(".:")
        if normalized in _UNNUMBERED_SECTIONS and len(stripped) < 50:
            # Verify it's on its own line (not part of a sentence)
            prev_line = lines[i - 1].strip() if i > 0 else ""
            prev_ok = (
                i == 0
                or not prev_line
                or prev_line.startswith("#")
                # Multi-word section names (2+ words) are specific enough
                # to be safe even without a blank preceding line, as long
                # as the previous line ends a sentence.
                or (len(normalized.split()) >= 2 and re.search(r"[.!?]$", prev_line))
            )
            next_ok = i + 1 < len(lines)
            if prev_ok and next_ok:
                result.append(f"## {stripped}")
                if i + 1 < len(lines) and lines[i + 1].strip():
                    result.append("")
                continue

        # Check if line STARTS with a known section title merged into body text.
        # After reflow, "Background and Related Work In this section..." becomes
        # one line. Split it into a header + paragraph.
        split_line = _try_split_merged_section(stripped)
        if split_line:
            title, body = split_line
            prev_ok = i == 0 or not lines[i - 1].strip() or lines[i - 1].strip().startswith("#")
            if prev_ok:
                result.append(f"## {title}")
                result.append("")
                result.append(body)
                continue

        result.append(line)

    return "\n".join(result)


def _try_split_merged_section(text: str) -> tuple[str, str] | None:
    """Try to split a line where a section title merged into body text.

    Checks if the line starts with a known multi-word section title
    followed by body text. Returns (title, body) or None.
    """
    text_lower = text.lower()

    # Sort by length descending so longer titles match first
    # ("Background and Related Work" before "Background")
    for section_name in sorted(_UNNUMBERED_SECTIONS, key=len, reverse=True):
        if len(section_name) < 8:
            continue  # Skip short names that could match mid-sentence

        if text_lower.startswith(section_name):
            rest = text[len(section_name) :]
            # The body must start with a space and then text
            if rest and rest[0] in " .":
                body = rest.lstrip(". ")
                if body and len(body) > 20:
                    title = text[: len(section_name)]
                    return title, body

    return None


def _is_title_like(text: str) -> bool:
    """Check if text looks like a section title rather than table data or body text.

    Section titles are short (1-8 words), mostly capitalized, and do not contain
    units, commas separating items, parenthetical expressions, or table caption
    prefixes.
    """
    words = text.split()
    if len(words) > 8:
        return False

    # Reject table captions
    if re.match(r"^Table\s+\d+", text, re.IGNORECASE):
        return False

    # Reject lines with units (table data)
    if re.search(
        r"\b(Hz|kHz|MHz|GHz|Hours?|Days?|Weeks?|Months?|Years?|Seconds?|"
        r"mA|mW|µA|ms|µs|ns|MB|GB|TB|KB|Bytes?)\b",
        text,
    ):
        return False

    # Reject comma-separated items (table rows, lists)
    if "," in text:
        return False

    # Reject lines with parentheses (inline math, citations)
    if "(" in text or ")" in text:
        return False

    # At least one word should start with uppercase
    upper_words = sum(1 for w in words if w and w[0].isupper())
    if upper_words == 0:
        return False

    return True


def _has_following_paragraph(following_lines: list[str]) -> bool:
    """Check that the following lines look like body text, not table data.

    Section headers are followed by paragraph text. Table cells are followed
    by more short lines with standalone numbers. Only examines the first
    continuous block of text (stops at blank lines) to avoid looking across
    section boundaries.
    """
    # Collect the first continuous block of non-empty lines (skip leading blanks)
    # Stop at blank lines, figure/table captions, and structural markers
    first_block: list[str] = []
    started = False
    for ln in following_lines:
        stripped = ln.strip()
        if not stripped:
            if started:
                break  # end of first block
            continue
        # Stop at figure/table captions and structural markers
        if re.match(r"^(Figure|Fig\.?|Table)\s+\d+", stripped, re.IGNORECASE):
            break
        if stripped.startswith("#") or stripped.startswith("!["):
            break
        started = True
        first_block.append(stripped)

    if not first_block:
        return True  # no following content — allow it

    # If any line in the first block is long, it's paragraph text
    if any(len(ln) > 50 for ln in first_block):
        return True

    # If a standalone number appears, it's table data
    if any(ln.isdigit() for ln in first_block[:3]):
        return False

    # Multiple consecutive short lines in the same block suggest table data
    if len(first_block) >= 3 and all(len(ln) < 40 for ln in first_block[:3]):
        return False

    return True


def _determine_header_level(numbering: str) -> int:
    """
    Determine the markdown header level based on section numbering depth.

    Args:
        numbering: The section number (e.g., "3", "3.1", "3.1.1", "3.1.1.1")

    Returns:
        Header level (2 for ##, 3 for ###, etc.)

    Examples:
        "3" or "III" → 2 (## Section)
        "3.1" → 3 (### Subsection)
        "3.1.1" → 4 (#### Subsubsection)
        "3.1.1.1" → 5 (##### Paragraph)
    """
    # Count the number of parts separated by dots
    parts = numbering.split(".")
    depth = len(parts)

    # Map depth to header level (depth 1 = ##, depth 2 = ###, etc.)
    # Cap at level 6 (######) which is the max in markdown
    return min(depth + 1, 6)


def _is_section_title(title: str, following_lines: list[str]) -> bool:
    """
    Determine if text is likely a section title vs regular paragraph text.

    Heuristics:
    - Title should be reasonably short
    - Title typically ends with period, colon, or nothing (not mid-sentence)
    - Should be followed by paragraph text (not another numbered item immediately)

    Args:
        title: The potential title text
        following_lines: Lines following this potential header

    Returns:
        True if this looks like a section title
    """
    # Too long to be a title
    if len(title) > MAX_TITLE_LENGTH:
        return False

    # Reject titles with garbled unicode (algorithm pseudocode, math symbols)
    if re.search(r"[\u0080-\uffff]{3,}", title):
        return False

    # Reject unit-like short titles that are actually table data
    # e.g., "Hz", "Hours", "Days", "Hand, Chest, Ankle"
    if len(title.split()) <= 3 and re.search(
        r"\b(Hz|kHz|MHz|GHz|Hours?|Days?|Weeks?|Months?|Years?|"
        r"mA|mW|µA|ms|µs|ns|MB|GB|TB|KB)\b",
        title,
    ):
        return False

    # Reject if title is just comma-separated short items (table row data)
    if ", " in title and len(title) < 40:
        return False

    # Title should not contain certain patterns that indicate it's body text
    # (e.g., multiple sentences, parenthetical asides that are too long)
    if title.count(". ") > 1:  # Multiple sentences
        return False

    # Check if followed by content (not immediately by another section number)
    for line in following_lines:
        stripped = line.strip()
        if not stripped:
            continue
        # If next non-empty line is another section number, this is still a title
        if re.match(r"^\d+(\.\d+)*\s+\w", stripped):
            return True
        # If it's a lettered section, this is still a title
        if re.match(r"^[A-Z]\.\s+\w", stripped):
            return True
        # If it starts with regular text, it's a title
        return True

    return True


def _fix_hierarchical_sections(content: str) -> str:
    """
    Convert hierarchical numbered sections to proper markdown headers.

    Patterns handled:
    - "3.1 Title" → "### 3.1 Title"
    - "3.1.1 Title text." → "#### 3.1.1 Title text"
    - "3.1.1 Title. Body text..." → "#### 3.1.1 Title\\n\\nBody text..."
    - "3.1.1.1 Fine detail" → "##### 3.1.1.1 Fine detail"

    Only converts if not already a header and looks like a section title.
    """
    lines = content.split("\n")
    result = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Skip if already a header
        if stripped.startswith("#"):
            result.append(line)
            i += 1
            continue

        # Pattern 0: Standalone section number on its own line, title on next
        # PyMuPDF often extracts "1\nIntroduction" or "2.1\nBackground"
        # Only match numbers starting with 1-9 (not 0.x decimals)
        standalone_num = re.match(r"^([1-9]\d*(?:\.\d+)*)\s*$", stripped)
        if standalone_num and i + 1 < len(lines):
            numbering_p0 = standalone_num.group(1)
            top_level_p0 = int(numbering_p0.split(".")[0])

            # Reject unreasonable numbers and decimals like "1.0"
            if top_level_p0 > 20 or ("." in numbering_p0 and re.match(r"^\d+\.0+$", numbering_p0)):
                result.append(line)
                i += 1
                continue

            next_stripped = lines[i + 1].strip()
            # Next line must look like a section title:
            # - Starts with uppercase letter
            # - 1-8 words, mostly capitalized (title case or ALL CAPS)
            # - No commas, parentheses, math symbols, or units
            # - Not a table caption ("Table N:")
            # Check if next line has "Title. Body text..." that needs splitting
            title_body = re.match(r"^([A-Z][^.]{2,50})\.\s+(.+)$", next_stripped)
            if title_body and len(title_body.group(1)) <= 60:
                # Split: title goes in header, body stays as paragraph
                title_part = title_body.group(1).strip()
                body_part = title_body.group(2).strip()
                numbering = standalone_num.group(1)
                level = _determine_header_level(numbering)
                header_prefix = "#" * level
                result.append(f"{header_prefix} {numbering} {title_part}")
                result.append("")
                result.append(body_part)
                i += 2
                continue

            if (
                next_stripped
                and next_stripped[0].isupper()
                and len(next_stripped) <= MAX_TITLE_LENGTH
                and ". " not in next_stripped[:40]
                and not next_stripped[0].isdigit()
                and not re.search(r"[\u0080-\uffff]{3,}", next_stripped)
                and _is_title_like(next_stripped)
                and _is_section_title(next_stripped, lines[i + 2 : i + 6])
                and _has_following_paragraph(lines[i + 2 : i + 8])
            ):
                numbering = standalone_num.group(1)
                level = _determine_header_level(numbering)
                header_prefix = "#" * level
                result.append(f"{header_prefix} {numbering} {next_stripped}")
                if i + 2 < len(lines) and lines[i + 2].strip():
                    result.append("")
                i += 2
                continue

        # Pattern 1: N Title or N.N.N Title on its own line
        # e.g., "1 Introduction" or "3.1.1 Design overview."
        # Requires the number part to start with 1-9 (not 0.x decimals)
        section_match = re.match(r"^([1-9]\d*(?:\.\d+)*)\s+([A-Z][^.]+?)\.?\s*$", stripped)

        if section_match:
            numbering = section_match.group(1)
            title = section_match.group(2).strip()

            # Reject unreasonable section numbers
            top_level = int(numbering.split(".")[0])
            if top_level > 20:
                result.append(line)
                i += 1
                continue

            # Reject decimal numbers like "1.0" or "7.00" (not section numbering)
            if "." in numbering and re.match(r"^\d+\.0+$", numbering):
                result.append(line)
                i += 1
                continue

            following = lines[i + 1 : i + 5] if i + 1 < len(lines) else []

            if (
                _is_section_title(title, following)
                and _is_title_like(title)
                and _has_following_paragraph(lines[i + 1 : i + 8])
            ):
                level = _determine_header_level(numbering)
                header_prefix = "#" * level
                result.append(f"{header_prefix} {numbering} {title}")
                if i + 1 < len(lines) and lines[i + 1].strip():
                    result.append("")
                i += 1
                continue

        # Pattern 2: N.N.N Title. Body text on same line
        inline_match = re.match(r"^([1-9]\d*(?:\.\d+)+)\s+([A-Z][^.]{2,50})\.\s+(.+)$", stripped)

        if inline_match:
            numbering = inline_match.group(1)
            title = inline_match.group(2).strip()
            body = inline_match.group(3).strip()

            if len(title) <= 60:
                level = _determine_header_level(numbering)
                header_prefix = "#" * level
                result.append(f"{header_prefix} {numbering} {title}")
                result.append("")
                result.append(body)
                i += 1
                continue

        result.append(line)
        i += 1

    return "\n".join(result)


def _fix_numbered_bullet_subsections(content: str) -> str:
    """
    Convert numbered bullet items that are actually subsections to headers.

    Heuristic: A "- N)" pattern is a subsection if:
    1. The title ends with a colon (indicating a titled section)
    2. It's followed by paragraph text

    "- 1) Title with colon:" followed by paragraphs → "### 1) Title with colon"
    "- 1) Short item" → "1. Short item" (just a numbered list item)
    """
    lines = content.split("\n")
    result = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # Check for pattern: "- N) Title:" (with colon - likely subsection)
        subsection_match = re.match(r"^-\s*(\d+[).])\s*(.+):\s*$", line)
        if subsection_match:
            # Look ahead to see if this is followed by paragraph text
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1

            has_following_paragraphs = False
            if j < len(lines):
                next_line = lines[j].strip()
                # Check it's not another list item
                if (
                    next_line
                    and not re.match(r"^[-*•]\s", next_line)
                    and not re.match(r"^\d+[).]\s", next_line)
                ):
                    has_following_paragraphs = True

            if has_following_paragraphs:
                # Convert to subsection header
                num = subsection_match.group(1)
                title = subsection_match.group(2)
                result.append(f"### {num} {title}")
                result.append("")  # Blank line after header
                i += 1
                continue

        # Check for standalone "- N)" bullet patterns that should be numbered lists
        bullet_match = re.match(r"^-\s*(\d+)\)\s*(.+)$", line)
        if bullet_match:
            # Convert "- 1) item" to "1. item"
            num = bullet_match.group(1)
            text = bullet_match.group(2)
            result.append(f"{num}. {text}")
        else:
            result.append(line)

        i += 1

    return "\n".join(result)

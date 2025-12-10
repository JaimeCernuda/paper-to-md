"""Section processing: fix headers and subsection detection."""

from __future__ import annotations

import re


def process_sections(content: str) -> str:
    """
    Process section headers in markdown content.

    Handles:
    - Abstract artifacts: "Abstract -Modern HPC..." → "## Abstract\\n\\nModern HPC..."
    - Index Terms: "Index Terms -keywords" → "## Index Terms\\n\\nkeywords"
    - Numbered subsections: "- 1) Title:" with multiple paragraphs → "### 1) Title"

    Args:
        content: Markdown content

    Returns:
        Content with fixed section headers
    """
    content = _fix_abstract_header(content)
    content = _fix_index_terms_header(content)
    content = _fix_numbered_subsections(content)
    return content


def _fix_abstract_header(content: str) -> str:
    """
    Fix Abstract header artifacts.

    "Abstract -Modern HPC..." → "## Abstract\\n\\nModern HPC..."
    "Abstract-Modern HPC..." → "## Abstract\\n\\nModern HPC..."
    """
    # Pattern: Abstract followed by dash (with optional spaces) then text
    pattern = r"^(#+\s*)?Abstract\s*[-–—]\s*"
    replacement = "## Abstract\n\n"
    return re.sub(pattern, replacement, content, count=1, flags=re.MULTILINE | re.IGNORECASE)


def _fix_index_terms_header(content: str) -> str:
    """
    Fix Index Terms header artifacts.

    "Index Terms -keywords" → "## Index Terms\\n\\nkeywords"
    """
    pattern = r"^(#+\s*)?Index Terms\s*[-–—]\s*"
    replacement = "## Index Terms\n\n"
    return re.sub(pattern, replacement, content, count=1, flags=re.MULTILINE | re.IGNORECASE)


def _fix_numbered_subsections(content: str) -> str:
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
                if next_line and not re.match(r"^[-*•]\s", next_line) and not re.match(
                    r"^\d+[).]\s", next_line
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

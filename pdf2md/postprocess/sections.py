"""Section processing: fix headers and subsection detection.

Handles hierarchical section numbering in academic papers:
- Section: ## 1. INTRODUCTION or ## I. INTRODUCTION
- Subsection: ### 1.1 Background or ### A. Background
- Subsubsection: #### 1.1.1 Details
- Paragraph: ##### 1.1.1.1 Fine details or ##### A. Lettered items
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
    - Lettered sections: "A. RAM management." → "##### A. RAM management"
    - Bullet subsections: "- 1) Title:" → "### 1) Title"

    Args:
        content: Markdown content

    Returns:
        Content with fixed section headers
    """
    content = _fix_abstract_header(content)
    content = _fix_index_terms_header(content)
    content = _fix_hierarchical_sections(content)
    content = _fix_lettered_sections(content)
    content = _fix_numbered_bullet_subsections(content)
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

        # Pattern 1: N.N.N Title on its own line (title ends with period or nothing)
        # e.g., "3.1.1 Design overview." or "3.1.1 Design overview"
        section_match = re.match(
            r"^(\d+(?:\.\d+)+)\s+([A-Z][^.]+?)\.?\s*$",
            stripped
        )

        if section_match:
            numbering = section_match.group(1)
            title = section_match.group(2).strip()

            # Get following lines for context
            following = lines[i + 1 : i + 5] if i + 1 < len(lines) else []

            if _is_section_title(title, following):
                level = _determine_header_level(numbering)
                header_prefix = "#" * level
                result.append(f"{header_prefix} {numbering} {title}")
                # Add blank line after header if not already there
                if i + 1 < len(lines) and lines[i + 1].strip():
                    result.append("")
                i += 1
                continue

        # Pattern 2: N.N.N Title. Body text on same line
        # e.g., "3.1.1 Design overview. Hermes is designed as a middleware..."
        # Split into header and body paragraph
        inline_match = re.match(
            r"^(\d+(?:\.\d+)+)\s+([A-Z][^.]{2,50})\.\s+(.+)$",
            stripped
        )

        if inline_match:
            numbering = inline_match.group(1)
            title = inline_match.group(2).strip()
            body = inline_match.group(3).strip()

            # Validate this looks like a section title (short, capitalized)
            if len(title) <= 60:  # Title should be reasonably short
                level = _determine_header_level(numbering)
                header_prefix = "#" * level
                result.append(f"{header_prefix} {numbering} {title}")
                result.append("")  # Blank line after header
                result.append(body)  # Body text as new paragraph
                i += 1
                continue

        result.append(line)
        i += 1

    return "\n".join(result)


def _fix_lettered_sections(content: str) -> str:
    """
    Convert lettered section markers to proper markdown headers.

    Patterns handled:
    - "A. RAM management." → "##### A. RAM management"
    - "B. Metadata management." → "##### B. Metadata management"
    - "A. Title. Body text..." → "##### A. Title\\n\\nBody text..."

    These typically appear as sub-items within numbered sections,
    so they get a deeper header level (#####).
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

        # Pattern 1: Single letter section on its own line
        # "A. Title here." or "A. Title here:" or "A. Title here"
        lettered_match = re.match(
            r"^([A-Z])\.\s+([A-Z][^.]+?)(?:\.|\:)?\s*$",
            stripped
        )

        if lettered_match:
            letter = lettered_match.group(1)
            title = lettered_match.group(2).strip()

            # Get following lines for context
            following = lines[i + 1 : i + 5] if i + 1 < len(lines) else []

            # Check it's a title, not a sentence starting with "A. " meaning something else
            if len(title) <= MAX_TITLE_LENGTH and _is_section_title(title, following):
                # Check that it's followed by paragraph content
                has_content = False
                for fl in following:
                    if fl.strip() and not re.match(r"^[A-Z]\.\s", fl.strip()):
                        has_content = True
                        break

                if has_content:
                    # Use level 5 for lettered sections (##### A. Title)
                    result.append(f"##### {letter}. {title}")
                    # Add blank line after header if not already there
                    if i + 1 < len(lines) and lines[i + 1].strip():
                        result.append("")
                    i += 1
                    continue

        # Pattern 2: Lettered section with body on same line
        # "A. RAM management. We have designed..." → split into header + body
        inline_lettered_match = re.match(
            r"^([A-Z])\.\s+([A-Z][^.]{2,50})(?:\.|\:)\s+(.+)$",
            stripped
        )

        if inline_lettered_match:
            letter = inline_lettered_match.group(1)
            title = inline_lettered_match.group(2).strip()
            body = inline_lettered_match.group(3).strip()

            # Use level 5 for lettered sections
            result.append(f"##### {letter}. {title}")
            result.append("")  # Blank line after header
            result.append(body)  # Body text as new paragraph
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

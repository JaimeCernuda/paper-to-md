"""Bibliography processing: format reference entries."""

from __future__ import annotations

import re


def process_bibliography(content: str) -> str:
    """
    Process the bibliography/references section.

    Handles:
    - Ensuring blank lines between reference entries
    - Adding anchor IDs for citation linking

    Args:
        content: Markdown content

    Returns:
        Content with formatted bibliography
    """
    # Find the references section
    references_patterns = [
        r"^## References\s*$",
        r"^## REFERENCES\s*$",
        r"^# References\s*$",
        r"^References\s*$",
    ]

    for pattern in references_patterns:
        match = re.search(pattern, content, re.MULTILINE)
        if match:
            before = content[: match.end()]
            after = content[match.end() :]
            after = _format_reference_entries(after)
            return before + after

    return content


def _format_reference_entries(references_text: str) -> str:
    """
    Ensure proper spacing between reference entries.

    Each [N] entry should be separated by a blank line.
    Handles entries with or without anchor tags.
    """
    lines = references_text.split("\n")
    result = []
    prev_was_reference = False

    for line in lines:
        # Check if this line starts a new reference entry
        # Match: [N], <a...></a>[N], or - [N]
        is_reference_start = bool(
            re.match(r"^\s*(?:<a[^>]*></a>)?(?:-\s*)?\[(\d{1,3})\]", line)
        )

        # Add blank line before new reference if previous line wasn't blank
        if is_reference_start and prev_was_reference:
            if result and result[-1].strip() != "":
                result.append("")

        result.append(line)
        prev_was_reference = is_reference_start or (
            prev_was_reference and line.strip() != "" and not is_reference_start
        )

    return "\n".join(result)


def extract_reference_count(content: str) -> int:
    """
    Count the number of references in the bibliography.

    Args:
        content: Markdown content

    Returns:
        Number of reference entries found
    """
    # Find all [N] patterns that look like reference entries
    # (at start of line, after anchor, or after blank line)
    matches = re.findall(r"^\s*(?:<a[^>]*></a>)?\[(\d+)\]", content, re.MULTILINE)
    return len(matches)

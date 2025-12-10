"""General text cleanup: ligatures, whitespace, etc."""

from __future__ import annotations

import re


def cleanup_text(content: str) -> str:
    """
    Apply general text cleanup to markdown content.

    Handles:
    - Ligature replacement (ﬁ→fi, ﬂ→fl, ﬀ→ff, etc.)
    - Excessive blank lines (max 2 consecutive)
    - Trailing whitespace

    Args:
        content: Markdown content

    Returns:
        Cleaned content
    """
    content = _fix_ligatures(content)
    content = _fix_excessive_blank_lines(content)
    content = _fix_trailing_whitespace(content)
    return content


def _fix_ligatures(content: str) -> str:
    """
    Replace common ligature characters with their ASCII equivalents.
    """
    ligatures = {
        "ﬁ": "fi",
        "ﬂ": "fl",
        "ﬀ": "ff",
        "ﬃ": "ffi",
        "ﬄ": "ffl",
        "ﬅ": "ft",
        "ﬆ": "st",
        # Common dash variants
        "–": "-",  # en-dash to hyphen (keep em-dash for intentional use)
        # Quotes (optional - some may want to keep smart quotes)
        # """: "\"",
        # """: "\"",
        # "'": "'",
        # "'": "'",
    }

    for ligature, replacement in ligatures.items():
        content = content.replace(ligature, replacement)

    return content


def _fix_excessive_blank_lines(content: str) -> str:
    """
    Reduce multiple consecutive blank lines to maximum of 2.
    """
    # Replace 3+ consecutive newlines with 2
    return re.sub(r"\n{3,}", "\n\n", content)


def _fix_trailing_whitespace(content: str) -> str:
    """
    Remove trailing whitespace from each line.
    """
    lines = content.split("\n")
    return "\n".join(line.rstrip() for line in lines)


def fix_hyphenated_words(content: str) -> str:
    """
    Fix words broken by hyphenation at line endings.

    Note: This is aggressive and may have false positives.
    Use with caution or as part of agent review.

    Example: "docu-\\nment" → "document"
    """
    # Pattern: word-\nword where the hyphen is at end of line
    # Only fix if the combined word is likely correct (lowercase continuation)
    pattern = r"(\w+)-\n(\s*)([a-z]\w*)"

    def fix_hyphen(match: re.Match) -> str:
        word1 = match.group(1)
        indent = match.group(2)
        word2 = match.group(3)
        # Join the words, preserve any indentation for the rest of the line
        return f"{word1}{word2}"

    return re.sub(pattern, fix_hyphen, content)

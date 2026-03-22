"""Citation processing: link citations to references and expand ranges."""

from __future__ import annotations

import re


def process_citations(content: str) -> str:
    """
    Process citations in markdown content.

    Handles:
    - Single citations: [7] → [[7]](#ref-7)
    - Ranges: [11]-[14] → [[11]](#ref-11), [[12]](#ref-12), [[13]](#ref-13), [[14]](#ref-14)
    - Lists: [7], [8] → [[7]](#ref-7), [[8]](#ref-8)

    Does NOT process citations within the References section.

    Args:
        content: Markdown content

    Returns:
        Content with linked citations
    """
    # Split content into main body and references section
    references_patterns = [
        r"^## References\s*$",
        r"^## REFERENCES\s*$",
        r"^# References\s*$",
        r"^References\s*$",
    ]

    main_body = content
    references_section = ""

    for pattern in references_patterns:
        match = re.search(pattern, content, re.MULTILINE)
        if match:
            main_body = content[: match.start()]
            references_section = content[match.start() :]
            break

    # Process main body only
    main_body = _expand_citation_ranges(main_body)
    main_body = _link_single_citations(main_body)

    # Process references section (add anchors)
    if references_section:
        references_section = _add_reference_anchors(references_section)

    return main_body + references_section


def _expand_citation_ranges(content: str) -> str:
    """
    Expand citation ranges to individual citations.

    Handles:
    - [11]-[14] → [11], [12], [13], [14]
    - [6-11]    → [6], [7], [8], [9], [10], [11]
    - [6–11]    → same (en-dash)
    - [6–\\n11]  → same (line break inside bracket)
    """
    # First, fix line breaks inside bracket citation ranges: [6–\n11] → [6–11]
    content = re.sub(
        r"\[(\d+)\s*[-–—]\s*\n\s*(\d+)\]",
        r"[\1-\2]",
        content,
    )

    def expand_range(match: re.Match) -> str:
        start = int(match.group(1))
        end = int(match.group(2))
        if start > end:
            start, end = end, start
        if end - start > 50:
            return match.group(0)
        citations = [f"[{i}]" for i in range(start, end + 1)]
        return ", ".join(citations)

    # Match [N]-[M] pattern (two bracket pairs)
    content = re.sub(
        r"\[(\d+)\]\s*[-–—]\s*\[(\d+)\]", expand_range, content
    )

    # Match [N-M] pattern (single bracket pair with dash)
    content = re.sub(
        r"\[(\d+)\s*[-–—]\s*(\d+)\]", expand_range, content
    )

    return content


def _link_single_citations(content: str) -> str:
    """
    Convert single citations to links: [7] → [[7]](#ref-7)

    Avoids already-linked citations and image/link syntax.
    """

    def link_citation(match: re.Match) -> str:
        # Check if this is already part of a link or image
        prefix = match.string[max(0, match.start() - 2) : match.start()]
        if prefix.endswith("](") or prefix.endswith("!["):
            return match.group(0)
        # Already linked: [[N]](#ref-N) — the outer [ precedes our match
        if prefix.endswith("["):
            return match.group(0)

        num = match.group(1)
        return f"[[{num}]](#ref-{num})"

    # Match [N] where N is 1-3 digits, not preceded by ] or followed by (
    pattern = r"(?<!\])\[(\d{1,3})\](?!\()"
    return re.sub(pattern, link_citation, content)


def _add_reference_anchors(references: str) -> str:
    """
    Add anchor IDs to reference entries and clean up formatting.

    - [1] Author... → <a id="ref-1"></a>[1] Author...
    [1] Author... → <a id="ref-1"></a>[1] Author...
    """
    # First, remove bullet prefixes from reference entries
    # "- [1]" → "[1]"
    references = re.sub(r"^-\s*\[(\d{1,3})\]", r"[\1]", references, flags=re.MULTILINE)

    # Match [N] at start of line, allowing leading whitespace (indented refs)
    pattern = r"^(\s*)\[(\d{1,3})\]"

    def add_anchor_with_indent(match: re.Match) -> str:
        indent = match.group(1)
        num = match.group(2)
        full_match = match.group(0)
        if f'id="ref-{num}"' in match.string[max(0, match.start() - 50) : match.start()]:
            return full_match
        return f'{indent}<a id="ref-{num}"></a>[{num}]'

    return re.sub(pattern, add_anchor_with_indent, references, flags=re.MULTILINE)

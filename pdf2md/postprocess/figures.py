"""Figure processing: embed images at their captions."""

from __future__ import annotations

import re
from pathlib import Path


def process_figures(content: str, image_files: list[str]) -> str:
    """
    Embed figure images at their captions in markdown content.

    Finds captions like "Fig. 1." or "Figure 1:" and inserts the corresponding
    image above the caption.

    Args:
        content: Markdown content
        image_files: List of available image filenames (e.g., ["figure1.png", "figure2.png"])

    Returns:
        Content with embedded figure images
    """
    if not image_files:
        return content

    # Build mapping of figure number to image file
    figure_map = _build_figure_map(image_files)

    if not figure_map:
        return content

    # Find and process figure captions
    content = _embed_figures_at_captions(content, figure_map)

    return content


def _build_figure_map(image_files: list[str]) -> dict[int, str]:
    """
    Build a mapping of figure numbers to image filenames.

    Handles patterns like:
    - figure1.png, figure2.png
    - fig1.png, fig2.png
    - Figure_1.png
    """
    figure_map: dict[int, str] = {}

    for filename in image_files:
        # Extract number from filename
        match = re.search(r"(?:figure|fig)[_-]?(\d+)", filename, re.IGNORECASE)
        if match:
            num = int(match.group(1))
            figure_map[num] = filename

    return figure_map


def _embed_figures_at_captions(content: str, figure_map: dict[int, str]) -> str:
    """
    Find figure captions and embed images above them.

    Handles patterns like:
    - "Fig. 1." or "Fig. 1:"
    - "Figure 1." or "Figure 1:"
    - "Fig 1" (no punctuation)
    """
    lines = content.split("\n")
    result = []
    embedded_figures: set[int] = set()

    for i, line in enumerate(lines):
        # Check if this line contains a figure caption
        # Pattern: "Fig." or "Figure" followed by number
        caption_match = re.search(
            r"(?:^|\s)(Fig(?:ure)?\.?\s*(\d+))[.:\s]",
            line,
            re.IGNORECASE,
        )

        if caption_match:
            fig_num = int(caption_match.group(2))

            # Only embed if we have the image and haven't embedded it yet
            if fig_num in figure_map and fig_num not in embedded_figures:
                img_file = figure_map[fig_num]
                # Insert image before the caption line
                result.append(f"![Figure {fig_num}](./img/{img_file})")
                result.append("")  # Blank line between image and caption
                embedded_figures.add(fig_num)

        result.append(line)

    return "\n".join(result)


def find_unembedded_figures(content: str, image_files: list[str]) -> list[str]:
    """
    Find images that weren't embedded (no matching caption found).

    Useful for diagnostics or appending unused figures at the end.

    Args:
        content: Markdown content (after embedding)
        image_files: List of available image filenames

    Returns:
        List of image filenames that weren't embedded
    """
    figure_map = _build_figure_map(image_files)
    embedded: set[int] = set()

    # Find which figures are referenced in the content
    for match in re.finditer(r"!\[Figure (\d+)\]", content):
        embedded.add(int(match.group(1)))

    # Return filenames of unembedded figures
    unembedded = []
    for num, filename in sorted(figure_map.items()):
        if num not in embedded:
            unembedded.append(filename)

    return unembedded

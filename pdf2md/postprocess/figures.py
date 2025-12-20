"""Figure processing: embed images at their captions."""

from __future__ import annotations

import re
from pathlib import Path

# Minimum dimensions to filter out logos/badges (in pixels)
# Images smaller than this are likely logos, badges, or artifacts
MIN_IMAGE_WIDTH = 200
MIN_IMAGE_HEIGHT = 150
MIN_IMAGE_AREA = 40000  # ~200x200


def filter_logo_images(image_dir: Path) -> tuple[list[str], list[str]]:
    """
    Filter out small images that are likely logos/badges from an image directory.
    
    Args:
        image_dir: Path to the img/ directory containing extracted images
        
    Returns:
        Tuple of (valid_images, filtered_logos) - lists of filenames
    """
    try:
        from PIL import Image
    except ImportError:
        # If PIL not available, return all images as valid
        images = [f.name for f in image_dir.glob("*.png")]
        return images, []
    
    valid_images: list[str] = []
    filtered_logos: list[str] = []
    
    for img_path in sorted(image_dir.glob("*.png")):
        try:
            with Image.open(img_path) as img:
                width, height = img.size
                area = width * height
                
                if (width < MIN_IMAGE_WIDTH or 
                    height < MIN_IMAGE_HEIGHT or 
                    area < MIN_IMAGE_AREA):
                    filtered_logos.append(img_path.name)
                else:
                    valid_images.append(img_path.name)
        except Exception:
            # If we can't read the image, include it to be safe
            valid_images.append(img_path.name)
    
    return valid_images, filtered_logos


def renumber_figures_after_filtering(
    image_dir: Path,
    valid_images: list[str],
) -> dict[str, str]:
    """
    Renumber figure files after filtering out logos, so figures are sequential.
    
    Args:
        image_dir: Path to the img/ directory
        valid_images: List of valid image filenames (after filtering)
        
    Returns:
        Mapping of old filename -> new filename
    """
    rename_map: dict[str, str] = {}
    
    # Sort by existing number to maintain order
    def get_num(filename: str) -> int:
        match = re.search(r"(\d+)", filename)
        return int(match.group(1)) if match else 0
    
    sorted_images = sorted(valid_images, key=get_num)
    
    for new_num, old_name in enumerate(sorted_images, start=1):
        new_name = f"figure{new_num}.png"
        if old_name != new_name:
            rename_map[old_name] = new_name
            old_path = image_dir / old_name
            new_path = image_dir / new_name
            if old_path.exists() and not new_path.exists():
                old_path.rename(new_path)
    
    return rename_map


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

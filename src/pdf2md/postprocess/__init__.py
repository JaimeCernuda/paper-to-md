"""Deterministic post-processing for extracted markdown."""

from pdf2md.postprocess.citations import process_citations
from pdf2md.postprocess.sections import process_sections
from pdf2md.postprocess.figures import process_figures
from pdf2md.postprocess.bibliography import process_bibliography
from pdf2md.postprocess.cleanup import cleanup_text


def process_markdown(content: str, images: list[str] | None = None) -> str:
    """
    Apply all deterministic post-processing steps to markdown content.

    Args:
        content: Raw markdown content from extraction
        images: List of available image filenames (e.g., ["figure1.png", "figure2.png"])

    Returns:
        Processed markdown content
    """
    # Order matters: sections first, then citations, then figures, then bibliography
    content = process_sections(content)
    content = process_citations(content)
    content = process_figures(content, images or [])
    content = process_bibliography(content)
    content = cleanup_text(content)
    return content


__all__ = [
    "process_markdown",
    "process_citations",
    "process_sections",
    "process_figures",
    "process_bibliography",
    "cleanup_text",
]

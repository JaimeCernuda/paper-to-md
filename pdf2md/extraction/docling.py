"""Docling-based PDF extraction."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL.Image import Image as PILImage

# Minimum dimensions to filter out logos/badges (in pixels)
# Images smaller than this are likely logos, badges, or artifacts
MIN_IMAGE_WIDTH = 200
MIN_IMAGE_HEIGHT = 150
# Minimum area threshold (width * height)
MIN_IMAGE_AREA = 40000  # ~200x200


class DoclingNotInstalledError(ImportError):
    """Raised when Docling is not installed."""

    def __init__(self) -> None:
        super().__init__(
            "Docling is not installed. Install with: pip install pdf2md[docling]\n"
            "Note: Docling requires ~500MB for ML models."
        )


def extract_with_docling(
    pdf_path: Path,
    output_dir: Path,
    *,
    images_scale: float = 2.0,
    generate_pictures: bool = True,
) -> tuple[Path, list[Path]]:
    """
    Extract markdown and images from a PDF using Docling.

    Args:
        pdf_path: Path to the PDF file
        output_dir: Directory to save output (creates pdf_stem/ subdirectory)
        images_scale: Resolution multiplier for extracted images (default: 2.0)
        generate_pictures: Whether to extract figure images (default: True)

    Returns:
        Tuple of (markdown_path, list_of_image_paths)

    Raises:
        DoclingNotInstalledError: If Docling is not installed
        RuntimeError: If conversion fails
    """
    try:
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.datamodel.base_models import ConversionStatus, InputFormat
    except ImportError as e:
        raise DoclingNotInstalledError() from e

    pdf_stem = pdf_path.stem
    doc_dir = output_dir / pdf_stem
    doc_dir.mkdir(parents=True, exist_ok=True)
    img_dir = doc_dir / "img"
    img_dir.mkdir(exist_ok=True)

    # Configure pipeline for image extraction
    pipeline_options = PdfPipelineOptions()
    pipeline_options.images_scale = images_scale
    pipeline_options.generate_picture_images = generate_pictures

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )
    result = converter.convert(str(pdf_path))

    if result.status not in [ConversionStatus.SUCCESS, ConversionStatus.PARTIAL_SUCCESS]:
        errors = getattr(result, "errors", [])
        error_msg = "; ".join(str(e) for e in errors) if errors else "Unknown error"
        raise RuntimeError(f"Docling conversion failed ({result.status}): {error_msg}")

    # Extract and save images (filtering out small logos/badges)
    images: list[Path] = []
    figure_num = 1  # Track actual figure numbers after filtering
    if hasattr(result.document, "pictures"):
        for picture in result.document.pictures:
            try:
                pil_image: PILImage | None = picture.get_image(result.document)
                if pil_image is not None:
                    # Filter out small images (likely logos, badges, artifacts)
                    width, height = pil_image.size
                    area = width * height
                    
                    if (width < MIN_IMAGE_WIDTH or 
                        height < MIN_IMAGE_HEIGHT or 
                        area < MIN_IMAGE_AREA):
                        # Skip small images - likely logos/badges
                        continue
                    
                    img_path = img_dir / f"figure{figure_num}.png"
                    pil_image.save(str(img_path), "PNG")
                    images.append(img_path)
                    figure_num += 1
            except Exception:
                # Skip images that fail to extract
                pass

    # Export markdown
    md_path = doc_dir / f"{pdf_stem}.md"
    md_content = result.document.export_to_markdown()
    md_path.write_text(md_content, encoding="utf-8")

    return md_path, images

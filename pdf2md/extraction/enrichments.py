"""Extract enrichments (code, equations, figures) from Docling documents for RAG."""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docling.datamodel.document import ConversionResult


@dataclass
class CodeBlock:
    """Extracted code block with metadata."""

    text: str
    language: str | None
    page: int | None
    context: str  # Surrounding text for RAG context


@dataclass
class Equation:
    """Extracted equation with LaTeX representation."""

    latex: str
    text: str  # Original text representation
    page: int | None
    context: str


@dataclass
class FigureInfo:
    """Extracted figure metadata."""

    figure_id: int
    caption: str
    classification: str | None  # chart, diagram, photo, etc.
    description: str | None  # VLM-generated description if available
    page: int | None
    image_path: str | None


@dataclass
class Enrichments:
    """Container for all extracted enrichments."""

    code_blocks: list[CodeBlock]
    equations: list[Equation]
    figures: list[FigureInfo]
    metadata: dict


def extract_enrichments(
    pdf_path: Path,
    output_dir: Path,
    *,
    enable_code: bool = True,
    enable_formulas: bool = True,
    enable_picture_classification: bool = True,
    enable_picture_description: bool = False,  # Requires VLM, disabled by default
    images_scale: float = 2.0,
) -> Enrichments:
    """
    Extract enrichments from a PDF using Docling with enrichment options enabled.

    This function runs a separate extraction pass with enrichments enabled,
    extracting code blocks, equations, and figure metadata for RAG purposes.

    Args:
        pdf_path: Path to the PDF file
        output_dir: Directory to save enrichment outputs
        enable_code: Extract code language detection
        enable_formulas: Extract LaTeX from equations
        enable_picture_classification: Classify figure types
        enable_picture_description: Generate VLM descriptions (slow, requires model)
        images_scale: Image resolution multiplier

    Returns:
        Enrichments object containing all extracted data
    """
    try:
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.datamodel.base_models import ConversionStatus, InputFormat
    except ImportError as e:
        raise ImportError(
            "Docling is not installed. Install with: pip install pdf2md[docling]"
        ) from e

    pdf_stem = pdf_path.stem
    doc_dir = output_dir / pdf_stem
    doc_dir.mkdir(parents=True, exist_ok=True)

    # Configure pipeline with enrichments
    pipeline_options = PdfPipelineOptions()
    pipeline_options.images_scale = images_scale
    pipeline_options.generate_picture_images = True
    pipeline_options.enable_remote_services = True  # Required for Ollama API

    # Enable enrichments
    if enable_code:
        pipeline_options.do_code_enrichment = True
    if enable_formulas:
        pipeline_options.do_formula_enrichment = True
    if enable_picture_classification:
        pipeline_options.do_picture_classification = True
    if enable_picture_description:
        # Configure VLM for picture descriptions via Ollama API
        from docling.datamodel.pipeline_options import PictureDescriptionApiOptions
        pipeline_options.do_picture_description = True
        pipeline_options.picture_description_options = PictureDescriptionApiOptions(
            url="http://localhost:11434/v1/chat/completions",
            params=dict(
                model="llava:7b",
                max_tokens=1024,
            ),
            prompt="Describe this image in detail. Focus on the key elements, text, diagrams, charts, or visual information present.",
            timeout=120,
            picture_area_threshold=0.02,  # Lower threshold to include smaller figures (default 0.05)
        )

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )
    result = converter.convert(str(pdf_path))

    if result.status not in [ConversionStatus.SUCCESS, ConversionStatus.PARTIAL_SUCCESS]:
        raise RuntimeError(f"Docling conversion failed: {result.status}")

    # Extract enrichments from the document
    enrichments = _extract_from_document(result, pdf_path)

    # Save enrichments to JSON files
    _save_enrichments(enrichments, doc_dir)

    return enrichments


def _extract_from_document(result: "ConversionResult", pdf_path: Path) -> Enrichments:
    """Extract enrichments from a converted Docling document."""
    doc = result.document
    code_blocks: list[CodeBlock] = []
    equations: list[Equation] = []
    figures: list[FigureInfo] = []

    # Extract code blocks
    if hasattr(doc, "texts"):
        for item in doc.texts:
            # Check if this is a code item
            if hasattr(item, "code_language") and item.code_language:
                code_blocks.append(
                    CodeBlock(
                        text=item.text if hasattr(item, "text") else str(item),
                        language=item.code_language,
                        page=_get_page_number(item),
                        context=_get_surrounding_context(doc, item),
                    )
                )

    # Extract equations/formulas
    if hasattr(doc, "equations") or hasattr(doc, "formulas"):
        formula_items = getattr(doc, "equations", []) or getattr(doc, "formulas", [])
        for item in formula_items:
            latex = ""
            if hasattr(item, "latex"):
                latex = item.latex
            elif hasattr(item, "original"):
                latex = item.original

            equations.append(
                Equation(
                    latex=latex,
                    text=item.text if hasattr(item, "text") else str(item),
                    page=_get_page_number(item),
                    context=_get_surrounding_context(doc, item),
                )
            )

    # Extract figure information
    if hasattr(doc, "pictures"):
        for idx, picture in enumerate(doc.pictures):
            # Get caption text
            caption = ""
            if hasattr(picture, "caption_text") and picture.caption_text:
                caption = picture.caption_text(doc)
            elif hasattr(picture, "captions") and picture.captions:
                # Resolve caption references
                caption_parts = []
                for cap_ref in picture.captions:
                    if hasattr(cap_ref, "cref"):
                        # Try to resolve the reference
                        try:
                            cap_text = _resolve_ref(doc, cap_ref.cref)
                            if cap_text:
                                caption_parts.append(cap_text)
                        except Exception:
                            pass
                caption = " ".join(caption_parts)

            # Get classification from annotations
            classification = None
            confidence = None
            if hasattr(picture, "annotations") and picture.annotations:
                for annotation in picture.annotations:
                    if hasattr(annotation, "predicted_classes") and annotation.predicted_classes:
                        # Get the top predicted class
                        top_class = annotation.predicted_classes[0]
                        if hasattr(top_class, "class_name"):
                            classification = top_class.class_name
                        if hasattr(top_class, "confidence"):
                            confidence = top_class.confidence

            # Get VLM description if available
            description = None
            if hasattr(picture, "annotations") and picture.annotations:
                for annotation in picture.annotations:
                    if hasattr(annotation, "kind") and annotation.kind == "description":
                        if hasattr(annotation, "text"):
                            description = annotation.text

            figures.append(
                FigureInfo(
                    figure_id=idx + 1,
                    caption=caption,
                    classification=f"{classification} ({confidence:.2f})" if classification and confidence else classification,
                    description=description,
                    page=_get_page_number(picture),
                    image_path=f"./img/figure{idx + 1}.png",
                )
            )

    # Document metadata
    metadata = {
        "source": str(pdf_path),
        "title": doc.title if hasattr(doc, "title") else pdf_path.stem,
        "num_pages": len(doc.pages) if hasattr(doc, "pages") else None,
        "num_code_blocks": len(code_blocks),
        "num_equations": len(equations),
        "num_figures": len(figures),
    }

    return Enrichments(
        code_blocks=code_blocks,
        equations=equations,
        figures=figures,
        metadata=metadata,
    )


def _get_page_number(item) -> int | None:
    """Extract page number from a document item."""
    if hasattr(item, "prov") and item.prov:
        prov = item.prov[0] if isinstance(item.prov, list) else item.prov
        if hasattr(prov, "page_no"):
            return prov.page_no
    if hasattr(item, "page"):
        return item.page
    return None


def _get_surrounding_context(doc, item, context_chars: int = 200) -> str:
    """Get surrounding text context for an item (useful for RAG)."""
    # This is a simplified implementation - in practice you'd want
    # to find neighboring text items in the document structure
    return ""


def _resolve_ref(doc, cref: str) -> str | None:
    """
    Resolve a document reference like '#/texts/47' to its text content.

    Args:
        doc: The DoclingDocument
        cref: Reference string like '#/texts/47'

    Returns:
        The text content if found, None otherwise
    """
    if not cref or not cref.startswith("#/"):
        return None

    parts = cref[2:].split("/")  # Remove '#/' prefix
    if len(parts) < 2:
        return None

    collection_name = parts[0]  # e.g., 'texts'
    try:
        index = int(parts[1])
    except ValueError:
        return None

    # Get the collection
    collection = getattr(doc, collection_name, None)
    if collection is None or not isinstance(collection, (list, tuple)):
        return None

    if index < 0 or index >= len(collection):
        return None

    item = collection[index]

    # Get text content
    if hasattr(item, "text"):
        return item.text
    if hasattr(item, "export_to_markdown"):
        try:
            return item.export_to_markdown(doc)
        except Exception:
            pass

    return str(item)


def _save_enrichments(enrichments: Enrichments, output_dir: Path) -> None:
    """Save enrichments to JSON files."""
    # Save all enrichments to a single JSON file
    all_data = {
        "metadata": enrichments.metadata,
        "code_blocks": [asdict(cb) for cb in enrichments.code_blocks],
        "equations": [asdict(eq) for eq in enrichments.equations],
        "figures": [asdict(fig) for fig in enrichments.figures],
    }

    enrichments_path = output_dir / "enrichments.json"
    with open(enrichments_path, "w", encoding="utf-8") as f:
        json.dump(all_data, f, indent=2, ensure_ascii=False)

    # Also save individual files for easier RAG ingestion
    if enrichments.code_blocks:
        code_path = output_dir / "code_blocks.json"
        with open(code_path, "w", encoding="utf-8") as f:
            json.dump([asdict(cb) for cb in enrichments.code_blocks], f, indent=2)

    if enrichments.equations:
        equations_path = output_dir / "equations.json"
        with open(equations_path, "w", encoding="utf-8") as f:
            json.dump([asdict(eq) for eq in enrichments.equations], f, indent=2)

    if enrichments.figures:
        figures_path = output_dir / "figures.json"
        with open(figures_path, "w", encoding="utf-8") as f:
            json.dump([asdict(fig) for fig in enrichments.figures], f, indent=2)

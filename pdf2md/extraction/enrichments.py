"""Extract enrichments (code, equations, figures) from Docling documents for RAG."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
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
    enable_picture_description: bool = False,
    images_scale: float = 2.0,
    # VLM options for figure descriptions
    use_local_vlm: bool = False,
    vlm_model: str | None = None,
    vlm_provider: str | None = None,
) -> Enrichments:
    """
    Extract enrichments from a PDF using Docling with enrichment options enabled.

    Args:
        pdf_path: Path to the PDF file
        output_dir: Directory to save enrichment outputs
        enable_code: Extract code language detection
        enable_formulas: Extract LaTeX from equations
        enable_picture_classification: Classify figure types
        enable_picture_description: Generate VLM descriptions for figures
        images_scale: Image resolution multiplier
        use_local_vlm: Use local VLM (LM Studio/Ollama) instead of cloud
        vlm_model: Override VLM model name

    Returns:
        Enrichments object containing all extracted data
    """
    try:
        from docling.datamodel.base_models import ConversionStatus, InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption
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
    pipeline_options.enable_remote_services = not use_local_vlm

    # Enable enrichments
    if enable_code:
        pipeline_options.do_code_enrichment = True
    if enable_formulas:
        pipeline_options.do_formula_enrichment = True
    if enable_picture_classification:
        pipeline_options.do_picture_classification = True

    # Configure VLM for picture descriptions (Docling-native path, non-local only)
    # When use_local_vlm is set, we skip Docling's VLM and use LocalBackend
    # after extraction (handles thinking models, uses LiteLLM provider config).
    if enable_picture_description and not use_local_vlm:
        pipeline_options.do_picture_description = True
        pipeline_options.picture_description_options = _get_vlm_options(
            model=vlm_model,
            provider=vlm_provider,
        )

    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
    )
    result = converter.convert(str(pdf_path))

    if result.status not in [ConversionStatus.SUCCESS, ConversionStatus.PARTIAL_SUCCESS]:
        raise RuntimeError(f"Docling conversion failed: {result.status}")

    # Extract enrichments from the document
    enrichments = _extract_from_document(result, pdf_path)

    # Local VLM descriptions via LocalBackend (post-extraction)
    if enable_picture_description and use_local_vlm:
        _add_local_vlm_descriptions(enrichments, doc_dir / "img", vlm_provider, vlm_model)

    # Save enrichments to JSON files
    _save_enrichments(enrichments, doc_dir)

    return enrichments


def _add_local_vlm_descriptions(
    enrichments: Enrichments,
    img_dir: Path,
    provider: str | None = None,
    model: str | None = None,
) -> None:
    """Use LocalBackend to add VLM descriptions to figures."""
    import asyncio

    from pdf2md.agent.backends.local import LocalBackend

    backend = LocalBackend()

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as pool:
            results = pool.submit(
                asyncio.run,
                backend.run_describe_figures(img_dir, provider=provider, model=model, verbose=True),
            ).result()
    else:
        results = asyncio.run(
            backend.run_describe_figures(img_dir, provider=provider, model=model, verbose=True)
        )

    # Merge descriptions into enrichments by figure_id
    desc_map = {r["figure_id"]: r["description"] for r in results if r.get("description")}
    for fig in enrichments.figures:
        if fig.figure_id in desc_map:
            fig.description = desc_map[fig.figure_id]


def _get_vlm_options(model: str | None = None, provider: str | None = None):
    """Get VLM configuration for Docling picture descriptions (non-local path).

    Used when Docling's built-in VLM pipeline handles descriptions.
    Reads defaults from providers.py to avoid hardcoded endpoints.
    """
    from docling.datamodel.pipeline_options import PictureDescriptionApiOptions

    from pdf2md.agent.providers import DEFAULT_OLLAMA_HOST, DEFAULT_VLM_HOST, DEFAULT_VLM_MODEL

    vlm_model = model or DEFAULT_VLM_MODEL
    provider = provider or "lm_studio"

    if provider == "ollama":
        api_url = f"{DEFAULT_OLLAMA_HOST}/v1/chat/completions"
    else:
        api_url = f"{DEFAULT_VLM_HOST}/chat/completions"

    return PictureDescriptionApiOptions(
        url=api_url,
        params=dict(
            model=vlm_model,
        ),
        prompt=(
            "Describe this scientific figure in detail. "
            "Identify the type (chart, diagram, flowchart, etc.), "
            "key elements, labels, and any data or relationships shown."
        ),
        timeout=300,
        picture_area_threshold=0.02,
    )


def _extract_from_document(result: "ConversionResult", pdf_path: Path) -> Enrichments:
    """Extract enrichments from a converted Docling document."""
    doc = result.document
    code_blocks: list[CodeBlock] = []
    equations: list[Equation] = []
    figures: list[FigureInfo] = []

    # Extract code blocks
    if hasattr(doc, "texts"):
        for item in doc.texts:
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
            caption = _get_caption(doc, picture)
            classification, confidence = _get_classification(picture)
            description = _get_description(picture)

            figures.append(
                FigureInfo(
                    figure_id=idx + 1,
                    caption=caption,
                    classification=(
                        f"{classification} ({confidence:.2f})"
                        if classification and confidence
                        else classification
                    ),
                    description=description,
                    page=_get_page_number(picture),
                    image_path=f"./img/figure{idx + 1}.png",
                )
            )

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


def _get_caption(doc, picture) -> str:
    """Extract caption text from a picture."""
    if hasattr(picture, "caption_text") and picture.caption_text:
        return picture.caption_text(doc)

    if hasattr(picture, "captions") and picture.captions:
        caption_parts = []
        for cap_ref in picture.captions:
            if hasattr(cap_ref, "cref"):
                try:
                    cap_text = _resolve_ref(doc, cap_ref.cref)
                    if cap_text:
                        caption_parts.append(cap_text)
                except Exception:
                    pass
        return " ".join(caption_parts)

    return ""


def _get_classification(picture) -> tuple[str | None, float | None]:
    """Extract classification from picture annotations."""
    if hasattr(picture, "annotations") and picture.annotations:
        for annotation in picture.annotations:
            if hasattr(annotation, "predicted_classes") and annotation.predicted_classes:
                top_class = annotation.predicted_classes[0]
                class_name = getattr(top_class, "class_name", None)
                confidence = getattr(top_class, "confidence", None)
                return class_name, confidence
    return None, None


def _get_description(picture) -> str | None:
    """Extract VLM description from picture annotations."""
    if hasattr(picture, "annotations") and picture.annotations:
        for annotation in picture.annotations:
            if hasattr(annotation, "kind") and annotation.kind == "description":
                if hasattr(annotation, "text"):
                    return annotation.text
    return None


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
    """Get surrounding text context for an item (useful for RAG).

    Finds the item's position among document texts and returns
    text from the preceding and following items.
    """
    texts = getattr(doc, "texts", None)
    if not texts:
        return ""

    # Find the item's index in the texts collection
    item_idx = None
    for i, t in enumerate(texts):
        if t is item:
            item_idx = i
            break

    if item_idx is None:
        return ""

    # Collect surrounding text
    parts = []
    # Before
    for i in range(max(0, item_idx - 2), item_idx):
        text = getattr(texts[i], "text", "")
        if text:
            parts.append(text)
    # After
    for i in range(item_idx + 1, min(len(texts), item_idx + 3)):
        text = getattr(texts[i], "text", "")
        if text:
            parts.append(text)

    context = " ".join(parts)
    if len(context) > context_chars:
        context = context[:context_chars] + "..."
    return context


def _resolve_ref(doc, cref: str) -> str | None:
    """Resolve a document reference like '#/texts/47' to its text content."""
    if not cref or not cref.startswith("#/"):
        return None

    parts = cref[2:].split("/")
    if len(parts) < 2:
        return None

    collection_name = parts[0]
    try:
        index = int(parts[1])
    except ValueError:
        return None

    collection = getattr(doc, collection_name, None)
    if collection is None or not isinstance(collection, (list, tuple)):
        return None

    if index < 0 or index >= len(collection):
        return None

    item = collection[index]

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
    all_data = {
        "metadata": enrichments.metadata,
        "code_blocks": [asdict(cb) for cb in enrichments.code_blocks],
        "equations": [asdict(eq) for eq in enrichments.equations],
        "figures": [asdict(fig) for fig in enrichments.figures],
    }

    enrichments_path = output_dir / "enrichments.json"
    with open(enrichments_path, "w", encoding="utf-8") as f:
        json.dump(all_data, f, indent=2, ensure_ascii=False)

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

"""Command-line interface for pdf2md."""

from __future__ import annotations

import shutil
from enum import Enum
from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer(
    name="pdf2md",
    help="Convert academic PDF papers to clean markdown.",
    no_args_is_help=True,
)
console = Console()


class Depth(str, Enum):
    """Analysis depth levels."""

    low = "low"
    medium = "medium"
    high = "high"


# =============================================================================
# Main convert command
# =============================================================================


@app.command()
def convert(
    pdf_path: Path = typer.Argument(
        ...,
        help="Path to the PDF file to convert",
        exists=True,
        dir_okay=False,
        resolve_path=True,
    ),
    output_dir: Path = typer.Argument(
        ...,
        help="Output directory for extracted content",
        resolve_path=True,
    ),
    # --- Core options ---
    depth: Depth = typer.Option(
        Depth.medium,
        "--depth",
        "-d",
        help="Analysis depth: low (fast), medium (balanced), high (thorough)",
    ),
    local: bool = typer.Option(
        False,
        "--local",
        "-l",
        help="Use local LLM/VLM instead of cloud (Claude)",
    ),
    provider: str = typer.Option(
        None,
        "--provider",
        "-p",
        help="LLM provider: lm_studio (default), ollama",
    ),
    # --- Output options ---
    raw: bool = typer.Option(
        False,
        "--raw",
        help="Skip all processing, output raw Docling extraction only",
    ),
    keep_raw: bool = typer.Option(
        False,
        "--keep-raw",
        help="Save raw extraction alongside processed output",
    ),
    # --- Model options ---
    model: str = typer.Option(
        None,
        "--model",
        "-m",
        help="Override LLM model (retouch) or VLM model (figure descriptions)",
    ),
    # --- Image options ---
    images_scale: float = typer.Option(
        2.0,
        "--images-scale",
        help="Image resolution multiplier",
    ),
    min_image_width: int = typer.Option(
        200,
        "--min-image-width",
        help="Minimum image width in pixels (filters logos)",
    ),
    min_image_height: int = typer.Option(
        150,
        "--min-image-height",
        help="Minimum image height in pixels (filters logos)",
    ),
    min_image_area: int = typer.Option(
        40000,
        "--min-image-area",
        help="Minimum image area in pixels (filters logos)",
    ),
) -> None:
    """
    Convert an academic PDF paper to clean markdown.

    \b
    DEPTH LEVELS:
        low     Docling extraction + rule-based post-processing (no AI)
        medium  + LLM retouch (fix headers, figures, paragraphs)
        high    + VLM figure descriptions + code/equation enrichments

    \b
    BACKENDS:
        cloud   Claude (default) - requires Claude subscription or API key
        local   LM Studio - run models locally (--local flag)

    \b
    EXAMPLES:
        pdf2md convert paper.pdf ./out                  # medium, cloud
        pdf2md convert paper.pdf ./out -d low           # fast, no AI
        pdf2md convert paper.pdf ./out -d high          # thorough
        pdf2md convert paper.pdf ./out --local          # medium, local LLM
        pdf2md convert paper.pdf ./out -l -d high       # local LLM + VLM
    """
    from pdf2md.agent.providers import resolve_provider
    from pdf2md.extraction.docling import DoclingNotInstalledError, extract_with_docling
    from pdf2md.postprocess import process_markdown

    pdf_stem = pdf_path.stem
    doc_dir = output_dir / pdf_stem

    # Determine what features are enabled based on depth
    use_retouch = depth in (Depth.medium, Depth.high) and not raw
    use_enrichments = depth == Depth.high and not raw
    use_vlm_descriptions = depth == Depth.high and not raw

    provider = resolve_provider(local, provider)

    # Display configuration
    if local:
        backend_str = f"local ({provider})"
    else:
        backend_str = "cloud (Claude)"
    console.print(f"\n[bold]Converting:[/bold] {pdf_path.name}")
    console.print(f"[bold]Output:[/bold] {doc_dir}")
    console.print(f"[bold]Depth:[/bold] {depth.value} | [bold]Backend:[/bold] {backend_str}\n")

    # Step 1: Extract with Docling
    console.print("[1/4] Extracting with Docling...")
    try:
        md_path, images = extract_with_docling(
            pdf_path,
            output_dir,
            images_scale=images_scale,
            min_image_width=min_image_width,
            min_image_height=min_image_height,
            min_image_area=min_image_area,
        )
    except DoclingNotInstalledError as e:
        console.print(f"[red]ERROR:[/red] {e}")
        raise typer.Exit(1)
    except RuntimeError as e:
        console.print(f"[red]ERROR:[/red] {e}")
        raise typer.Exit(1)

    console.print(f"      Extracted {len(images)} figures")

    # Step 2: Save raw if requested
    if keep_raw or raw:
        raw_path = doc_dir / f"{pdf_stem}_raw.md"
        shutil.copy(md_path, raw_path)
        console.print(f"      Saved raw: {raw_path.name}")

    # Step 3: Deterministic post-processing
    if not raw:
        console.print("[2/4] Post-processing (rule-based)...")
        content = md_path.read_text(encoding="utf-8")
        image_files = [img.name for img in images]
        processed = process_markdown(content, image_files)
        md_path.write_text(processed, encoding="utf-8")
        console.print("      Applied: citations, sections, figures, bibliography")
    else:
        console.print("[2/4] Post-processing... [dim]skipped (--raw)[/dim]")

    # Step 4: LLM retouch (medium, high depth)
    if use_retouch:
        from pdf2md.agent.backends import BackendNotInstalledError
        from pdf2md.agent.cleanup import run_cleanup_with_backend_sync

        backend = "local" if local else "claude"
        console.print(f"[3/4] Retouching with LLM ({backend_str})...")

        try:
            result = run_cleanup_with_backend_sync(
                md_path,
                backend=backend,
                provider=provider,
                model=model,
                verbose=False,
            )
            if result:
                console.print("      Fixed: authors, lettered sections")
            else:
                console.print("[yellow]      No changes needed[/yellow]")
        except BackendNotInstalledError as e:
            console.print(f"[yellow]      Skipped:[/yellow] {e}")
    else:
        console.print("[3/4] Retouching (LLM)... [dim]skipped (depth=low)[/dim]")

    # Step 5: Enrichments + VLM descriptions (high depth)
    if use_enrichments:
        console.print("[4/4] Enriching (VLM + analysis)...")
        try:
            from pdf2md.extraction.enrichments import extract_enrichments

            enrichments = extract_enrichments(
                pdf_path,
                output_dir,
                images_scale=images_scale,
                enable_picture_description=use_vlm_descriptions,
                use_local_vlm=local,
                vlm_model=model,
                vlm_provider=provider,
            )
            console.print(
                f"      Code: {enrichments.metadata['num_code_blocks']}, "
                f"Equations: {enrichments.metadata['num_equations']}, "
                f"Figures: {enrichments.metadata['num_figures']}"
            )
            if use_vlm_descriptions:
                described = sum(1 for f in enrichments.figures if f.description)
                console.print(f"      VLM descriptions: {described}/{len(enrichments.figures)}")
        except Exception as e:
            console.print(f"[yellow]      Failed:[/yellow] {e}")
    else:
        console.print("[4/4] Enriching (VLM)... [dim]skipped (requires depth=high)[/dim]")

    # Summary
    content = md_path.read_text(encoding="utf-8")
    line_count = content.count("\n")

    console.print("\n[bold green]Done![/bold green]")
    console.print(f"  Markdown: {md_path} ({line_count} lines)")
    console.print(f"  Images:   {doc_dir / 'img'} ({len(images)} figures)")
    if use_enrichments:
        console.print(f"  Enrichments: {doc_dir / 'enrichments.json'}")


# =============================================================================
# Standalone commands
# =============================================================================


@app.command()
def retouch(
    md_path: Path = typer.Argument(
        ...,
        help="Path to the markdown file to retouch",
        exists=True,
        dir_okay=False,
        resolve_path=True,
    ),
    images_dir: Path = typer.Option(
        None,
        "--images",
        "-i",
        help="Path to images directory (default: ./img relative to markdown)",
    ),
    local: bool = typer.Option(
        False,
        "--local",
        "-l",
        help="Use local LLM instead of cloud (Claude)",
    ),
    provider: str = typer.Option(
        None,
        "--provider",
        "-p",
        help="LLM provider: lm_studio (default), ollama",
    ),
    model: str = typer.Option(
        None,
        "--model",
        "-m",
        help="Override LLM model name",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show detailed LLM progress",
    ),
) -> None:
    """
    Retouch an existing markdown file using LLM.

    Uses AI to fix extraction artifacts that need LLM judgment:

    \b
        - Author formatting (names, affiliations, emails)
        - Lettered section headers (A., B., C.)

    \b
    EXAMPLES:
        pdf2md retouch paper.md                 # cloud (Claude)
        pdf2md retouch paper.md --local         # local (LM Studio)
        pdf2md retouch paper.md -l -m llama3    # local with specific model
    """
    from pdf2md.agent.backends import BackendNotInstalledError
    from pdf2md.agent.cleanup import run_cleanup_with_backend_sync
    from pdf2md.agent.providers import resolve_provider

    if images_dir is None:
        images_dir = md_path.parent / "img"

    provider = resolve_provider(local, provider)

    backend = "local" if local else "claude"
    if local:
        backend_str = f"local ({provider})"
    else:
        backend_str = "cloud (Claude)"
    model_str = f" [{model}]" if model else ""

    console.print(f"\n[bold]Retouching:[/bold] {md_path.name}")
    console.print(f"[bold]Backend:[/bold] {backend_str}{model_str}\n")

    try:
        result = run_cleanup_with_backend_sync(
            md_path,
            images_dir,
            backend=backend,
            provider=provider,
            model=model,
            verbose=verbose,
        )
        if result:
            console.print("\n[bold green]Retouch complete![/bold green]")
            if not verbose:
                console.print(f"\n{result}")
        else:
            console.print("[yellow]No changes needed[/yellow]")
    except BackendNotInstalledError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command()
def postprocess(
    md_path: Path = typer.Argument(
        ...,
        help="Path to the markdown file to process",
        exists=True,
        dir_okay=False,
        resolve_path=True,
    ),
    images_dir: Path = typer.Option(
        None,
        "--images",
        "-i",
        help="Path to images directory (default: ./img relative to markdown)",
    ),
    output: Path = typer.Option(
        None,
        "--output",
        "-o",
        help="Output path (default: overwrite input file)",
    ),
) -> None:
    """
    Run rule-based post-processing on an existing markdown file.

    Applies deterministic fixes without any AI/LLM:

    \b
        - Citation formatting [1] → superscript
        - Section header detection (numbered sections)
        - Figure embedding at captions
        - Bibliography cleanup

    This is equivalent to depth=low processing.
    """
    from pdf2md.postprocess import process_markdown

    if images_dir is None:
        images_dir = md_path.parent / "img"

    image_files = []
    if images_dir.exists():
        image_files = [f.name for f in images_dir.glob("*.png")]
        image_files.extend(f.name for f in images_dir.glob("*.jpg"))
        image_files.extend(f.name for f in images_dir.glob("*.jpeg"))

    console.print(f"\n[bold]Post-processing:[/bold] {md_path.name}")
    console.print(f"[bold]Images:[/bold] {len(image_files)} found\n")

    content = md_path.read_text(encoding="utf-8")
    processed = process_markdown(content, image_files)

    output_path = output or md_path
    output_path.write_text(processed, encoding="utf-8")

    console.print(f"[bold green]Done![/bold green] Output: {output_path}")


@app.command()
def enrich(
    pdf_path: Path = typer.Argument(
        ...,
        help="Path to the PDF file to extract enrichments from",
        exists=True,
        dir_okay=False,
        resolve_path=True,
    ),
    output_dir: Path = typer.Argument(
        ...,
        help="Output directory for enrichment files",
        resolve_path=True,
    ),
    describe: bool = typer.Option(
        False,
        "--describe",
        help="Generate VLM descriptions for figures (requires VLM)",
    ),
    local: bool = typer.Option(
        False,
        "--local",
        "-l",
        help="Use local VLM instead of cloud",
    ),
    provider: str = typer.Option(
        None,
        "--provider",
        "-p",
        help="VLM provider: lm_studio (default), ollama",
    ),
    model: str = typer.Option(
        None,
        "--model",
        "-m",
        help="Override VLM model",
    ),
    images_scale: float = typer.Option(
        2.0,
        "--images-scale",
        help="Image resolution multiplier",
    ),
) -> None:
    """
    Extract enrichments from a PDF for RAG applications.

    Extracts structured data for retrieval-augmented generation:

    \b
        - Code blocks with language detection
        - Equations with LaTeX representation
        - Figure metadata (classification, captions)
        - Optional: VLM-generated figure descriptions (--describe)

    \b
    EXAMPLES:
        pdf2md enrich paper.pdf ./out                   # basic enrichments
        pdf2md enrich paper.pdf ./out --describe        # + VLM descriptions
        pdf2md enrich paper.pdf ./out --describe -l     # local VLM
        pdf2md enrich paper.pdf ./out -d -l -m llava    # local with model
    """
    from pdf2md.agent.providers import resolve_provider
    from pdf2md.extraction.enrichments import extract_enrichments

    pdf_stem = pdf_path.stem
    doc_dir = output_dir / pdf_stem

    provider = resolve_provider(local, provider)

    console.print(f"\n[bold]Extracting enrichments:[/bold] {pdf_path.name}")
    console.print(f"[bold]Output:[/bold] {doc_dir}")

    if describe:
        if local:
            vlm_str = f"local ({provider})"
        else:
            vlm_str = "cloud"
        if model:
            vlm_str += f" [{model}]"
        console.print(f"[bold]VLM:[/bold] {vlm_str}")
    console.print()

    console.print("[*] Analyzing PDF with Docling...")
    try:
        enrichments = extract_enrichments(
            pdf_path,
            output_dir,
            images_scale=images_scale,
            enable_picture_description=describe,
            use_local_vlm=local,
            vlm_model=model,
            vlm_provider=provider,
        )
    except ImportError as e:
        console.print(f"[red]ERROR:[/red] {e}")
        raise typer.Exit(1)
    except RuntimeError as e:
        console.print(f"[red]ERROR:[/red] {e}")
        raise typer.Exit(1)

    console.print("\n[bold green]Done![/bold green]")
    console.print(f"  Code blocks: {enrichments.metadata['num_code_blocks']}")
    console.print(f"  Equations:   {enrichments.metadata['num_equations']}")
    console.print(f"  Figures:     {enrichments.metadata['num_figures']}")

    if describe:
        described = sum(1 for f in enrichments.figures if f.description)
        console.print(f"  VLM descriptions: {described}/{len(enrichments.figures)}")

    console.print(f"  Output: {doc_dir / 'enrichments.json'}")


@app.command("download-models")
def download_models() -> None:
    """
    Pre-download Docling ML models (~500MB).

    Downloads and caches the models Docling needs for PDF extraction.
    Run this once after installation to avoid slow first-run downloads.
    Models are cached in ~/.cache/docling/ and reused across runs.

    \b
    EXAMPLES:
        pdf2md download-models
    """
    from pdf2md.extraction.docling import DoclingNotInstalledError

    console.print("\n[bold]Downloading Docling ML models...[/bold]")
    console.print("Models will be cached in ~/.cache/docling/\n")

    try:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption
    except ImportError as e:
        raise DoclingNotInstalledError() from e

    pipeline_options = PdfPipelineOptions()
    pipeline_options.generate_picture_images = True

    console.print("[*] Initializing DocumentConverter (this triggers model downloads)...")
    DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
    )

    console.print("\n[bold green]Done![/bold green] Docling models are cached and ready.")


if __name__ == "__main__":
    app()

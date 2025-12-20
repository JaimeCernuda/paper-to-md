"""Command-line interface for pdf2md."""

from __future__ import annotations

import shutil
from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer(
    name="pdf2md",
    help="Convert academic PDF papers to clean markdown.",
    no_args_is_help=True,
)
console = Console()


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
    raw: bool = typer.Option(
        False,
        "--raw",
        help="Skip all post-processing, output raw Docling extraction",
    ),
    agent: bool = typer.Option(
        False,
        "--agent",
        help="Run Claude agent for additional cleanup",
    ),
    keep_raw: bool = typer.Option(
        False,
        "--keep-raw",
        help="Save raw extraction alongside processed output",
    ),
    enrich: bool = typer.Option(
        False,
        "--enrich",
        help="Extract enrichments (code, equations, figures) for RAG",
    ),
    describe: bool = typer.Option(
        False,
        "--describe",
        help="Generate VLM descriptions for figures (slow, requires --enrich)",
    ),
    images_scale: float = typer.Option(
        2.0,
        "--images-scale",
        help="Image resolution multiplier (default: 2.0)",
    ),
) -> None:
    """
    Convert an academic PDF paper to clean markdown.

    Uses Docling for extraction with optional deterministic post-processing
    and Claude agent cleanup.

    Creates:
        output_dir/pdf_name/
            pdf_name.md           (final processed)
            pdf_name_raw.md       (if --keep-raw)
            img/
                figure1.png, figure2.png, ...
            enrichments.json      (if --enrich)
    """
    from pdf2md.extraction.docling import extract_with_docling, DoclingNotInstalledError
    from pdf2md.postprocess import process_markdown
    from pdf2md.agent.cleanup import run_cleanup_agent_sync, AgentNotInstalledError

    pdf_stem = pdf_path.stem
    doc_dir = output_dir / pdf_stem

    console.print(f"\n[bold]Converting:[/bold] {pdf_path.name}")
    console.print(f"[bold]Output:[/bold] {doc_dir}\n")

    # Step 1: Extract with Docling
    console.print("[*] Extracting with Docling...")
    try:
        md_path, images = extract_with_docling(
            pdf_path,
            output_dir,
            images_scale=images_scale,
        )
    except DoclingNotInstalledError as e:
        console.print(f"[red]ERROR:[/red] {e}")
        raise typer.Exit(1)
    except RuntimeError as e:
        console.print(f"[red]ERROR:[/red] {e}")
        raise typer.Exit(1)

    console.print(f"    Extracted {len(images)} figures")

    # Step 2: Save raw if requested
    if keep_raw or raw:
        raw_path = doc_dir / f"{pdf_stem}_raw.md"
        shutil.copy(md_path, raw_path)
        console.print(f"    Saved raw extraction: {raw_path.name}")

    # Step 3: Extract enrichments for RAG (if --enrich)
    if enrich:
        console.print("[*] Extracting enrichments for RAG...")
        try:
            from pdf2md.extraction.enrichments import extract_enrichments

            enrichments = extract_enrichments(pdf_path, output_dir, images_scale=images_scale, enable_picture_description=describe)
            console.print(
                f"    Extracted: {enrichments.metadata['num_code_blocks']} code blocks, "
                f"{enrichments.metadata['num_equations']} equations, "
                f"{enrichments.metadata['num_figures']} figures"
            )
        except Exception as e:
            console.print(f"[yellow]Warning:[/yellow] Enrichment extraction failed: {e}")

    # Step 4: Post-processing (unless --raw)
    if not raw:
        console.print("[*] Running post-processing...")
        content = md_path.read_text(encoding="utf-8")
        image_files = [img.name for img in images]
        processed = process_markdown(content, image_files)
        md_path.write_text(processed, encoding="utf-8")
        console.print("    Applied: citations, sections, figures, bibliography, cleanup")

    # Step 5: Agent cleanup (if --agent)
    if agent and not raw:
        console.print("[*] Running Claude agent cleanup...")
        try:
            result = run_cleanup_agent_sync(md_path, verbose=False)
            if result:
                console.print("    Agent completed cleanup")
            else:
                console.print("[yellow]    Agent returned no changes[/yellow]")
        except AgentNotInstalledError as e:
            console.print(f"[yellow]Warning:[/yellow] {e}")

    # Summary
    content = md_path.read_text(encoding="utf-8")
    line_count = content.count("\n")

    console.print(f"\n[bold green]Done![/bold green]")
    console.print(f"  Markdown: {md_path} ({line_count} lines)")
    console.print(f"  Images:   {doc_dir / 'img'} ({len(images)} figures)")
    if enrich:
        console.print(f"  Enrichments: {doc_dir / 'enrichments.json'}")


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
    Run post-processing on an existing markdown file.

    Useful for re-processing or processing markdown from other sources.
    
    Note: Logo/badge filtering is done during extraction (pdf2md convert),
    not during postprocessing. Existing extractions with logos will retain them.
    """
    from pdf2md.postprocess import process_markdown

    # Determine images directory
    if images_dir is None:
        images_dir = md_path.parent / "img"

    # Get list of image files
    image_files = []
    if images_dir.exists():
        image_files = [f.name for f in images_dir.glob("*.png")]
        image_files.extend(f.name for f in images_dir.glob("*.jpg"))
        image_files.extend(f.name for f in images_dir.glob("*.jpeg"))

    console.print(f"[*] Processing: {md_path.name}")
    console.print(f"    Found {len(image_files)} images")

    content = md_path.read_text(encoding="utf-8")
    processed = process_markdown(content, image_files)

    # Write output
    output_path = output or md_path
    output_path.write_text(processed, encoding="utf-8")

    console.print(f"[bold green]Done![/bold green] Output: {output_path}")


@app.command()
def agent(
    md_path: Path = typer.Argument(
        ...,
        help="Path to the markdown file to clean",
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
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show agent progress",
    ),
) -> None:
    """
    Run Claude agent cleanup on an existing markdown file.

    The agent performs open-ended review and fixes extraction artifacts.
    """
    from pdf2md.agent.cleanup import run_cleanup_agent_sync, AgentNotInstalledError

    if images_dir is None:
        images_dir = md_path.parent / "img"

    console.print(f"[*] Running agent on: {md_path.name}")

    try:
        result = run_cleanup_agent_sync(md_path, images_dir, verbose=verbose)
        if result:
            console.print(f"\n[bold green]Agent completed![/bold green]")
            if not verbose:
                console.print(f"\n{result}")
        else:
            console.print("[yellow]Agent returned no changes[/yellow]")
    except AgentNotInstalledError as e:
        console.print(f"[red]ERROR:[/red] {e}")
        raise typer.Exit(1)


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
    enable_code: bool = typer.Option(
        True,
        "--code/--no-code",
        help="Extract code language detection",
    ),
    enable_formulas: bool = typer.Option(
        True,
        "--formulas/--no-formulas",
        help="Extract LaTeX from equations",
    ),
    enable_classification: bool = typer.Option(
        True,
        "--classify/--no-classify",
        help="Classify figure types",
    ),
    enable_description: bool = typer.Option(
        False,
        "--describe/--no-describe",
        help="Generate VLM descriptions for figures (slow, requires model)",
    ),
    images_scale: float = typer.Option(
        2.0,
        "--images-scale",
        help="Image resolution multiplier (default: 2.0)",
    ),
) -> None:
    """
    Extract enrichments (code, equations, figures) from a PDF for RAG.

    Runs Docling with enrichment options enabled and saves structured
    data to JSON files for use in RAG systems.

    Creates:
        output_dir/pdf_name/
            enrichments.json      (all enrichments)
            code_blocks.json      (if code found)
            equations.json        (if equations found)
            figures.json          (figure metadata)
    """
    from pdf2md.extraction.enrichments import extract_enrichments

    pdf_stem = pdf_path.stem
    doc_dir = output_dir / pdf_stem

    console.print(f"\n[bold]Extracting enrichments:[/bold] {pdf_path.name}")
    console.print(f"[bold]Output:[/bold] {doc_dir}\n")

    console.print("[*] Running Docling with enrichments...")
    try:
        enrichments = extract_enrichments(
            pdf_path,
            output_dir,
            enable_code=enable_code,
            enable_formulas=enable_formulas,
            enable_picture_classification=enable_classification,
            enable_picture_description=enable_description,
            images_scale=images_scale,
        )
    except ImportError as e:
        console.print(f"[red]ERROR:[/red] {e}")
        raise typer.Exit(1)
    except RuntimeError as e:
        console.print(f"[red]ERROR:[/red] {e}")
        raise typer.Exit(1)

    console.print(f"\n[bold green]Done![/bold green]")
    console.print(f"  Code blocks: {enrichments.metadata['num_code_blocks']}")
    console.print(f"  Equations:   {enrichments.metadata['num_equations']}")
    console.print(f"  Figures:     {enrichments.metadata['num_figures']}")
    console.print(f"  Output:      {doc_dir / 'enrichments.json'}")


if __name__ == "__main__":
    app()

"""Command-line interface for pdf2md."""

from __future__ import annotations

import asyncio
import shutil
from concurrent.futures import ThreadPoolExecutor
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


def _run_async(coro):
    """Run an async coroutine safely from sync context.

    Avoids the LiteLLM event loop binding issue that occurs when
    asyncio.run() is called multiple times in the same process.
    Uses a dedicated thread with its own event loop.
    """
    result = None
    exception = None

    def _thread_target():
        nonlocal result, exception
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(coro)
        except Exception as e:
            exception = e
        finally:
            loop.close()

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_thread_target)
        future.result()

    if exception:
        raise exception
    return result


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
    # --- Feature flags ---
    no_vlm: bool = typer.Option(
        False,
        "--no-vlm",
        help="Skip VLM figure descriptions (faster runs)",
    ),
    synthesis: bool = typer.Option(
        True,
        "--synthesis/--no-synthesis",
        help="Enable/disable Nemotron synthesis pass (default: enabled at high depth)",
    ),
    # --- Output options ---
    raw: bool = typer.Option(
        False,
        "--raw",
        help="Skip all processing, output raw PyMuPDF extraction only",
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
        help="Override LLM model for retouch/synthesis",
    ),
    vlm_model: str = typer.Option(
        None,
        "--vlm-model",
        help="Override VLM model for figure descriptions",
    ),
    # --- Endpoint options ---
    text_endpoint: str = typer.Option(
        None,
        "--text-endpoint",
        help="Override text LLM endpoint URL (e.g. http://host:1234/v1)",
    ),
    vlm_endpoint: str = typer.Option(
        None,
        "--vlm-endpoint",
        help="Override VLM endpoint URL (e.g. http://host:8081/v1)",
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
        low     PyMuPDF extraction + rule-based post-processing (no AI)
        medium  + LLM retouch (fix headers, figures, paragraphs)
        high    + VLM figure descriptions + synthesis pass + equations

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
        pdf2md convert paper.pdf ./out -l -d high       # local LLM + VLM + synthesis
        pdf2md convert paper.pdf ./out -l -d high --no-vlm  # skip VLM descriptions
    """
    import json as _json
    import os

    from pdf2md.agent.providers import resolve_provider
    from pdf2md.extraction.pymupdf import extract_with_pymupdf
    from pdf2md.postprocess import process_markdown

    pdf_stem = pdf_path.stem
    doc_dir = output_dir / pdf_stem

    # Override endpoints via CLI flags if provided
    if text_endpoint:
        os.environ["LM_STUDIO_HOST"] = text_endpoint
    if vlm_endpoint:
        os.environ["PDF2MD_VLM_HOST"] = vlm_endpoint

    # Determine what features are enabled based on depth
    use_retouch = depth in (Depth.medium, Depth.high) and not raw
    use_vlm_descriptions = depth == Depth.high and not raw and not no_vlm
    use_synthesis = depth == Depth.high and not raw and synthesis

    provider = resolve_provider(local, provider)

    # Display configuration
    if local:
        backend_str = f"local ({provider})"
    else:
        backend_str = "cloud (Claude)"

    total_steps = 3  # extract + postprocess + retouch
    if use_vlm_descriptions:
        total_steps += 1
    if use_synthesis:
        total_steps += 1

    console.print(f"\n[bold]Converting:[/bold] {pdf_path.name}")
    console.print(f"[bold]Output:[/bold] {doc_dir}")
    console.print(f"[bold]Depth:[/bold] {depth.value} | [bold]Backend:[/bold] {backend_str}")
    if depth == Depth.high:
        flags = []
        if no_vlm:
            flags.append("VLM disabled")
        if not synthesis:
            flags.append("synthesis disabled")
        if flags:
            console.print(f"[bold]Flags:[/bold] {', '.join(flags)}")
    console.print()

    step = 0

    # ── Step 1: Extract ───────────────────────────────────────────────
    step += 1
    console.print(f"[{step}/{total_steps}] Extracting with PyMuPDF...")
    try:
        md_path, images, tables = extract_with_pymupdf(
            pdf_path,
            output_dir,
            images_scale=images_scale,
            min_image_width=min_image_width,
            min_image_height=min_image_height,
            min_image_area=min_image_area,
        )
    except RuntimeError as e:
        console.print(f"[red]ERROR:[/red] {e}")
        raise typer.Exit(1)

    console.print(f"      Extracted {len(images)} figures, {len(tables)} tables")

    # ── Step 2: Save raw if requested ─────────────────────────────────
    if keep_raw or raw:
        raw_path = doc_dir / f"{pdf_stem}_raw.md"
        shutil.copy(md_path, raw_path)
        console.print(f"      Saved raw: {raw_path.name}")

    # ── Step 3: Deterministic post-processing ─────────────────────────
    step += 1
    if not raw:
        console.print(f"[{step}/{total_steps}] Post-processing (rule-based)...")
        content = md_path.read_text(encoding="utf-8")
        image_files = [img.name for img in images]
        processed = process_markdown(content, image_files)
        md_path.write_text(processed, encoding="utf-8")
        console.print("      Applied: citations, sections, figures, bibliography")
    else:
        console.print(f"[{step}/{total_steps}] Post-processing... [dim]skipped (--raw)[/dim]")

    # ── Step 4: LLM retouch ───────────────────────────────────────────
    step += 1
    if use_retouch:
        from pdf2md.agent.backends import BackendNotInstalledError
        from pdf2md.agent.cleanup import run_cleanup_with_backend_sync

        backend = "local" if local else "claude"
        console.print(f"[{step}/{total_steps}] Retouching with LLM ({backend_str})...")

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
        console.print(f"[{step}/{total_steps}] Retouching (LLM)... [dim]skipped (depth=low)[/dim]")

    # ── Step 5: VLM figure descriptions ───────────────────────────────
    figure_results: list[dict] = []
    if use_vlm_descriptions and images:
        step += 1
        console.print(f"[{step}/{total_steps}] Describing {len(images)} figures with VLM...")
        try:
            from pdf2md.agent.backends.local import LocalBackend

            backend_obj = LocalBackend()
            img_dir = doc_dir / "img"

            figure_results = _run_async(
                backend_obj.run_describe_figures(
                    img_dir,
                    provider=provider,
                    model=vlm_model,
                    verbose=True,
                )
            )
            described = sum(1 for r in figure_results if r.get("description"))
            console.print(f"      VLM descriptions: {described}/{len(figure_results)}")

            # Save figures.json
            (doc_dir / "figures.json").write_text(
                _json.dumps(figure_results, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as e:
            console.print(f"[yellow]      VLM failed:[/yellow] {e}")
    elif use_vlm_descriptions:
        step += 1
        console.print(f"[{step}/{total_steps}] Enriching... [dim]no figures to describe[/dim]")

    # ── Step 6: Synthesis pass ────────────────────────────────────────
    if use_synthesis:
        step += 1
        console.print(f"[{step}/{total_steps}] Running synthesis pass (Nemotron)...")
        try:
            from pdf2md.agent.backends.local import LocalBackend

            backend_obj = LocalBackend()
            result = _run_async(
                backend_obj.run_synthesis(
                    md_path,
                    figures=figure_results,
                    tables=tables,
                    equations=[],
                    provider=provider,
                    model=model,
                    verbose=True,
                )
            )
            console.print(f"      Synthesis complete ({len(result)} chars)")
        except Exception as e:
            console.print(f"[yellow]      Synthesis failed:[/yellow] {e}")

    # ── Summary ───────────────────────────────────────────────────────
    content = md_path.read_text(encoding="utf-8")
    line_count = content.count("\n")

    console.print("\n[bold green]Done![/bold green]")
    console.print(f"  Markdown: {md_path} ({line_count} lines)")
    console.print(f"  Images:   {doc_dir / 'img'} ({len(images)} figures)")
    if tables:
        console.print(f"  Tables:   {len(tables)} extracted")
    if figure_results:
        console.print(f"  Figures:  {doc_dir / 'figures.json'}")


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


if __name__ == "__main__":
    app()

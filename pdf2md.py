#!/usr/bin/env python3
"""
pdf2md - Convert academic PDF papers to clean markdown using Docling + Claude cleanup.

Usage:
    python pdf2md.py <pdf_path> <output_dir>
    python pdf2md.py <pdf_path> <output_dir> --raw  # Skip cleanup agent

Examples:
    python pdf2md.py ./pdfs/paper.pdf ./extracted
    python pdf2md.py ./pdfs/paper.pdf ./extracted --raw
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer(
    help="Convert academic PDF papers to clean markdown.",
    no_args_is_help=True,
)
console = Console()


def extract_with_docling(pdf_path: Path, output_dir: Path) -> tuple[Path, list[Path]]:
    """
    Extract markdown and images using Docling.
    """
    try:
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.datamodel.base_models import ConversionStatus, InputFormat
    except ImportError:
        console.print("[red]ERROR:[/red] Docling not installed.")
        console.print("Install with: [bold]pip install docling[/bold]")
        raise typer.Exit(1)

    pdf_stem = pdf_path.stem
    doc_dir = output_dir / pdf_stem
    doc_dir.mkdir(parents=True, exist_ok=True)
    img_dir = doc_dir / "img"
    img_dir.mkdir(exist_ok=True)

    console.print("[*] Extracting with Docling...")

    # Configure pipeline for image extraction
    pipeline_options = PdfPipelineOptions()
    pipeline_options.images_scale = 2.0
    pipeline_options.generate_picture_images = True

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )
    result = converter.convert(str(pdf_path))

    if result.status not in [ConversionStatus.SUCCESS, ConversionStatus.PARTIAL_SUCCESS]:
        console.print(f"[red]ERROR:[/red] Conversion failed: {result.status}")
        raise typer.Exit(1)

    # Save images
    images = []
    if hasattr(result.document, 'pictures'):
        for idx, picture in enumerate(result.document.pictures):
            img_path = img_dir / f"figure{idx+1}.png"
            try:
                pil_image = picture.get_image(result.document)
                if pil_image:
                    pil_image.save(str(img_path), "PNG")
                    images.append(img_path)
            except Exception:
                pass

    console.print(f"    Extracted {len(images)} figures")

    # Export markdown
    md_path = doc_dir / f"{pdf_stem}.md"
    md_content = result.document.export_to_markdown()
    md_path.write_text(md_content, encoding="utf-8")

    return md_path, images


async def run_cleanup_agent(md_path: Path, images: list[Path]) -> None:
    """
    Run Claude Code agent to clean up extracted markdown.

    The agent handles:
    - Section headers (Abstract -, numbered subsections like "1) Title:")
    - Citation linking with range expansion ([11]-[14] -> all linked)
    - Figure embedding at captions
    - Bullet/enumeration cleanup
    """
    from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, TextBlock

    doc_dir = md_path.parent
    img_dir = doc_dir / "img"

    # List available images
    image_list = "\n".join([f"  - {img.name}" for img in images]) if images else "  (none)"

    prompt = f"""You are cleaning up an academic paper extracted from PDF to markdown.

## Files
- **Markdown:** {md_path}
- **Images in ./img/:**
{image_list}

## Cleanup Tasks

### 1. Fix Section Headers
- `Abstract -Text` or `Abstract-Text` → `## Abstract\\n\\nText` (artifact dash removal)
- `Index Terms -` → `## Index Terms\\n\\n`
- Patterns like `- 1) Title with colon:` followed by multiple paragraphs are SUBSECTIONS, not bullets
  - Convert to: `### 1) Title with colon\\n\\nParagraph text...`
  - Clue: if numbered item has a descriptive title AND multiple following paragraphs, it's a subsection

### 2. Fix Enumerations
- `- 1)` `- 2)` `- 3)` as single-line items → `1.` `2.` `3.` (remove redundant bullet)
- Keep actual bullet lists as bullets

### 3. Link Citations
- `[7]` → `[[7]](#ref-7)` in the main text (NOT in References section)
- `[11]-[14]` → `[[11]](#ref-11), [[12]](#ref-12), [[13]](#ref-13), [[14]](#ref-14)` (expand range)
- `[7], [8]` → `[[7]](#ref-7), [[8]](#ref-8)`
- In REFERENCES section, add anchors: `[1] Author...` → `<a id="ref-1"></a>[1] Author...`

### 4. Embed Figures
- Find captions like `Fig. 1.` or `Figure 1:`
- Insert image ABOVE the caption: `![Figure 1](./img/figure1.png)\\n\\nFig. 1. Caption...`
- Match figure numbers to image files (figure1.png for Fig. 1, etc.)

### 5. General Cleanup
- Fix ligatures: ﬁ→fi, ﬂ→fl, ﬀ→ff
- Remove excessive blank lines (max 2 consecutive)
- Ensure consistent heading hierarchy

## Output
Edit the markdown file IN PLACE. Do not create a new file.
After editing, briefly confirm what you changed.
"""

    options = ClaudeAgentOptions(
        allowed_tools=["Read", "Edit", "Glob"],
        permission_mode="acceptEdits",
        cwd=str(doc_dir),
    )

    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        # Could print agent progress here if desired
                        pass
    except Exception as e:
        console.print(f"[yellow]Warning:[/yellow] Cleanup agent failed: {e}")


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
        help="Skip cleanup agent (output raw docling extraction)",
    ),
) -> None:
    """
    Convert an academic PDF paper to clean markdown.

    Uses Docling for extraction and Claude Code for intelligent cleanup.

    Creates:
        output_dir/pdf_name/
            pdf_name.md
            img/
                figure1.png, figure2.png, ...
    """
    pdf_stem = pdf_path.stem
    doc_dir = output_dir / pdf_stem

    console.print(f"\n[bold]Converting:[/bold] {pdf_path.name}")
    console.print(f"[bold]Output:[/bold] {doc_dir}\n")

    # Step 1: Extract with Docling
    md_path, images = extract_with_docling(pdf_path, output_dir)
    console.print(f"[+] Extraction complete")

    # Step 2: Run cleanup agent (unless --raw)
    if not raw:
        console.print("[*] Running cleanup agent...")
        asyncio.run(run_cleanup_agent(md_path, images))
        console.print("[+] Cleanup complete")

    # Summary
    content = md_path.read_text(encoding="utf-8")
    line_count = content.count('\n')

    console.print(f"\n[bold green]Done![/bold green]")
    console.print(f"  Markdown: {md_path} ({line_count} lines)")
    console.print(f"  Images:   {doc_dir / 'img'} ({len(images)} figures)")


if __name__ == "__main__":
    app()

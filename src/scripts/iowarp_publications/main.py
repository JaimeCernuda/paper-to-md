#!/usr/bin/env python3
"""
IOWarp Publications Downloader

Scans YAML publication files for Anthony Kougkas papers,
generates a summary document, and downloads PDFs and citations.
"""

import argparse
import sys
from pathlib import Path

import httpx
import yaml


def find_kougkas_papers(folder_path: Path) -> list[dict]:
    """Find all papers authored by Kougkas, excluding posters."""
    papers = []
    yaml_files = list(folder_path.glob("*.yaml"))

    for yaml_file in yaml_files:
        try:
            with open(yaml_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if not data:
                continue

            # Check if Kougkas is an author (case-insensitive)
            authors = data.get("authors", [])
            is_kougkas_paper = any(
                "kougkas" in author.lower() for author in authors
            )

            if not is_kougkas_paper:
                continue

            # Filter out posters
            pub_type = data.get("type", "")
            if pub_type.lower() == "poster":
                continue

            # Add source file info
            data["_source_file"] = yaml_file.name
            papers.append(data)

        except Exception as e:
            print(f"Warning: Failed to parse {yaml_file.name}: {e}")

    # Sort by year (newest first), then by title
    papers.sort(key=lambda p: (-p.get("year", 0), p.get("title", "")))

    return papers


def write_summary(papers: list[dict], output_path: Path) -> Path:
    """Write a markdown summary of all papers."""
    summary_file = output_path / "summary.md"

    with open(summary_file, "w", encoding="utf-8") as f:
        f.write("# IOWarp Publications (Anthony Kougkas)\n\n")
        f.write(f"Total papers: {len(papers)}\n\n")
        f.write("---\n\n")

        for paper in papers:
            title = paper.get("title", "Untitled")
            links = paper.get("links", {})
            year = paper.get("year", "N/A")
            venue = paper.get("venue", "N/A")
            slug = paper.get("slug", "unknown")

            pdf_link = links.get("pdf", "N/A")
            # Prefer bibtex, fallback to citation
            citation_link = links.get("bibtex") or links.get("citation", "N/A")

            f.write(f"## {title}\n\n")
            f.write(f"- **Year:** {year}\n")
            f.write(f"- **Venue:** {venue}\n")
            f.write(f"- **Slug:** {slug}\n")
            f.write(f"- **PDF:** {pdf_link}\n")
            f.write(f"- **Citation:** {citation_link}\n")
            f.write("\n---\n\n")

    return summary_file


def download_files(papers: list[dict], output_path: Path) -> dict:
    """Download PDFs and citations for all papers."""
    pdfs_dir = output_path / "pdfs"
    citations_dir = output_path / "citations"

    pdfs_dir.mkdir(parents=True, exist_ok=True)
    citations_dir.mkdir(parents=True, exist_ok=True)

    stats = {"pdf_success": 0, "pdf_failed": 0, "citation_success": 0, "citation_failed": 0}

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        for paper in papers:
            slug = paper.get("slug", "unknown")
            links = paper.get("links", {})
            title = paper.get("title", "Untitled")[:50]

            # Download PDF
            pdf_url = links.get("pdf")
            if pdf_url:
                pdf_file = pdfs_dir / f"{slug}.pdf"
                try:
                    print(f"Downloading PDF: {title}...")
                    response = client.get(pdf_url)
                    response.raise_for_status()
                    pdf_file.write_bytes(response.content)
                    stats["pdf_success"] += 1
                except Exception as e:
                    print(f"  Failed to download PDF for {slug}: {e}")
                    stats["pdf_failed"] += 1
            else:
                print(f"  No PDF link for: {title}")
                stats["pdf_failed"] += 1

            # Download citation (prefer bibtex)
            citation_url = links.get("bibtex") or links.get("citation")
            if citation_url:
                # Determine extension from URL
                ext = ".bib" if "bibtex" in links and links.get("bibtex") else ".txt"
                citation_file = citations_dir / f"{slug}{ext}"
                try:
                    print(f"Downloading citation: {title}...")
                    response = client.get(citation_url)
                    response.raise_for_status()
                    citation_file.write_bytes(response.content)
                    stats["citation_success"] += 1
                except Exception as e:
                    print(f"  Failed to download citation for {slug}: {e}")
                    stats["citation_failed"] += 1
            else:
                print(f"  No citation link for: {title}")
                stats["citation_failed"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Download IOWarp/Kougkas publications"
    )
    parser.add_argument(
        "--folder",
        type=Path,
        required=True,
        help="Path to the publications YAML folder"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output directory (default: <folder>/../downloads)"
    )

    args = parser.parse_args()

    folder = args.folder.resolve()
    if not folder.exists():
        print(f"Error: Folder does not exist: {folder}")
        sys.exit(1)

    # Default output to sibling 'downloads' folder
    output = args.output.resolve() if args.output else folder.parent / "downloads"
    output.mkdir(parents=True, exist_ok=True)

    print(f"Scanning: {folder}")
    print(f"Output:   {output}")
    print()

    # Find papers
    papers = find_kougkas_papers(folder)
    print(f"Found {len(papers)} Kougkas papers (excluding posters)")
    print()

    if not papers:
        print("No papers found. Exiting.")
        sys.exit(0)

    # Write summary
    summary_file = write_summary(papers, output)
    print(f"Summary written to: {summary_file}")
    print()

    # Download files
    print("Downloading files...")
    print("-" * 50)
    stats = download_files(papers, output)
    print("-" * 50)
    print()

    # Print stats
    print("Download Statistics:")
    print(f"  PDFs:      {stats['pdf_success']} success, {stats['pdf_failed']} failed")
    print(f"  Citations: {stats['citation_success']} success, {stats['citation_failed']} failed")
    print()
    print("Done!")


if __name__ == "__main__":
    main()

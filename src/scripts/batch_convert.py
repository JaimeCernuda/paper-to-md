#!/usr/bin/env python3
"""Batch convert PDFs to markdown using pdf2md.

Usage:
    uv run python scripts/batch_convert.py INPUT_FOLDER OUTPUT_FOLDER [OPTIONS]

Example:
    uv run python scripts/batch_convert.py grc-context/downloads/pdfs grc_parsed_pdfs --agent --describe
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


def get_pdf_files(input_dir: Path) -> list[Path]:
    """Get all PDF files in directory, sorted alphabetically."""
    return sorted(input_dir.glob("*.pdf"))


def convert_pdf(
    pdf_path: Path,
    output_dir: Path,
    log_file: Path | None = None,
    *,
    keep_raw: bool = True,
    enrich: bool = True,
    describe: bool = True,
    agent: bool = True,
) -> tuple[bool, float, str]:
    """
    Convert a single PDF using pdf2md CLI.

    Returns:
        Tuple of (success: bool, duration_seconds: float, output: str)
    """
    cmd = ["uv", "run", "pdf2md", "convert", str(pdf_path), str(output_dir)]

    if keep_raw:
        cmd.append("--keep-raw")
    if enrich:
        cmd.append("--enrich")
    if describe:
        cmd.append("--describe")
    if agent:
        cmd.append("--agent")

    start_time = time.time()
    start_timestamp = datetime.now().isoformat()

    # Write log header immediately so we know it started
    if log_file:
        with open(log_file, "w", encoding="utf-8") as f:
            f.write(f"# PDF Conversion Log: {pdf_path.name}\n")
            f.write(f"# Started: {start_timestamp}\n")
            f.write(f"# Command: {' '.join(cmd)}\n")
            f.write(f"# Status: IN PROGRESS...\n")
            f.write("=" * 60 + "\n\n")

    try:
        # Stream output to log file in real-time
        if log_file:
            with open(log_file, "a", encoding="utf-8") as f:
                result = subprocess.run(
                    cmd,
                    stdout=f,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
        else:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
            )

        duration = time.time() - start_time

        # Append completion info to log
        if log_file:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write("\n\n" + "=" * 60 + "\n")
                f.write(f"# Completed: {datetime.now().isoformat()}\n")
                f.write(f"# Duration: {duration:.1f}s\n")
                f.write(f"# Exit code: {result.returncode}\n")
                f.write(f"# Status: {'SUCCESS' if result.returncode == 0 else 'FAILED'}\n")

        output = ""
        if not log_file and result.stdout:
            output = result.stdout

        return result.returncode == 0, duration, output
    except Exception as e:
        duration = time.time() - start_time
        error_msg = f"Error: {e}"
        if log_file:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"\n\n# EXCEPTION: {e}\n")
                f.write(f"# Duration: {duration:.1f}s\n")
        return False, duration, error_msg


def write_summary_log(
    log_file: Path,
    results: list[tuple[str, bool, float]],
    total_duration: float,
    args,
) -> None:
    """Write a summary log of the batch conversion."""
    successful = sum(1 for _, success, _ in results if success)
    failed = len(results) - successful

    with open(log_file, "w", encoding="utf-8") as f:
        f.write("=" * 60 + "\n")
        f.write("BATCH CONVERSION SUMMARY\n")
        f.write(f"Generated: {datetime.now().isoformat()}\n")
        f.write("=" * 60 + "\n\n")

        f.write(f"Input:      {args.input_dir.absolute()}\n")
        f.write(f"Output:     {args.output_dir.absolute()}\n")
        f.write(f"Total PDFs: {len(results)}\n")
        f.write(f"Successful: {successful}\n")
        f.write(f"Failed:     {failed}\n")
        f.write(f"Duration:   {total_duration/60:.1f} minutes ({total_duration:.1f}s)\n")
        f.write(f"Average:    {total_duration/len(results):.1f}s per PDF\n\n")

        f.write("Options:\n")
        f.write(f"  - Keep raw:      {not args.no_raw}\n")
        f.write(f"  - Enrich:        {not args.no_enrich}\n")
        f.write(f"  - VLM describe:  {not args.no_describe}\n")
        f.write(f"  - Agent cleanup: {not args.no_agent}\n\n")

        # Results table
        f.write("-" * 60 + "\n")
        f.write("RESULTS BY PDF\n")
        f.write("-" * 60 + "\n\n")

        for name, success, duration in results:
            status = "OK" if success else "FAILED"
            f.write(f"[{status:6s}] {duration:7.1f}s  {name}\n")

        if failed > 0:
            f.write("\n" + "-" * 60 + "\n")
            f.write("FAILED PDFs (review individual logs)\n")
            f.write("-" * 60 + "\n\n")
            for name, success, _ in results:
                if not success:
                    log_name = Path(name).stem + ".log"
                    f.write(f"  - {name}\n")
                    f.write(f"    Log: logs/{log_name}\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Batch convert PDFs to markdown using pdf2md",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Convert all PDFs with full processing (VLM descriptions + agent cleanup)
  uv run python scripts/batch_convert.py grc-context/downloads/pdfs grc_parsed_pdfs

  # Fast conversion without VLM descriptions or agent cleanup
  uv run python scripts/batch_convert.py input_pdfs output_md --no-describe --no-agent

  # Skip first 5 PDFs (useful for resuming after failure)
  uv run python scripts/batch_convert.py input_pdfs output_md --skip 5

Output structure:
  OUTPUT_DIR/
  ├── logs/                    # Individual conversion logs
  │   ├── paper-name-1.log
  │   ├── paper-name-2.log
  │   └── ...
  ├── batch_summary.log        # Overall summary with success/fail
  ├── paper-name-1/            # Converted paper 1
  │   ├── paper-name-1.md
  │   ├── paper-name-1_raw.md
  │   ├── enrichments.json
  │   └── img/
  └── paper-name-2/            # Converted paper 2
      └── ...
        """,
    )
    parser.add_argument(
        "input_dir",
        type=Path,
        help="Directory containing PDF files",
    )
    parser.add_argument(
        "output_dir",
        type=Path,
        help="Directory to output converted markdown (all PDFs bundled here)",
    )
    parser.add_argument(
        "--no-raw",
        action="store_true",
        help="Don't keep raw markdown (before agent cleanup)",
    )
    parser.add_argument(
        "--no-enrich",
        action="store_true",
        help="Don't extract enrichments (code, equations, figures)",
    )
    parser.add_argument(
        "--no-describe",
        action="store_true",
        help="Don't generate VLM descriptions for figures (faster)",
    )
    parser.add_argument(
        "--no-agent",
        action="store_true",
        help="Don't run Claude agent cleanup (faster)",
    )
    parser.add_argument(
        "--skip",
        type=int,
        default=0,
        help="Skip first N PDFs (useful for resuming)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only process first N PDFs (after skip)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List PDFs that would be processed without actually processing",
    )

    args = parser.parse_args()

    # Validate input directory
    if not args.input_dir.exists():
        print(f"Error: Input directory does not exist: {args.input_dir}")
        return 1

    if not args.input_dir.is_dir():
        print(f"Error: Input path is not a directory: {args.input_dir}")
        return 1

    # Get PDF files
    pdf_files = get_pdf_files(args.input_dir)

    if not pdf_files:
        print(f"No PDF files found in {args.input_dir}")
        return 1

    # Apply skip and limit
    if args.skip > 0:
        pdf_files = pdf_files[args.skip:]
    if args.limit is not None:
        pdf_files = pdf_files[:args.limit]

    total_pdfs = len(pdf_files)

    print(f"{'=' * 60}")
    print(f"PDF Batch Conversion")
    print(f"{'=' * 60}")
    print(f"Input:  {args.input_dir.absolute()}")
    print(f"Output: {args.output_dir.absolute()}")
    print(f"PDFs:   {total_pdfs} files")
    print(f"Options:")
    print(f"  - Keep raw:    {not args.no_raw}")
    print(f"  - Enrich:      {not args.no_enrich}")
    print(f"  - VLM describe:{not args.no_describe}")
    print(f"  - Agent cleanup:{not args.no_agent}")
    if args.skip > 0:
        print(f"  - Skipping first {args.skip} PDFs")
    print(f"{'=' * 60}")

    if args.dry_run:
        print("\nDRY RUN - Files that would be processed:")
        for i, pdf in enumerate(pdf_files, 1):
            print(f"  {i:3d}. {pdf.name}")
        return 0

    # Create output and logs directories
    args.output_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = args.output_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nLogs directory: {logs_dir.absolute()}")
    print(f"Summary log:    {args.output_dir.absolute() / 'batch_summary.log'}")

    # Track results
    results: list[tuple[str, bool, float]] = []
    total_start = time.time()

    for i, pdf_path in enumerate(pdf_files, 1):
        print(f"\n[{i}/{total_pdfs}] Processing: {pdf_path.name}")
        print(f"    Log: logs/{pdf_path.stem}.log")
        print("-" * 60)

        # Individual log file for this PDF
        log_file = logs_dir / f"{pdf_path.stem}.log"

        success, duration, output = convert_pdf(
            pdf_path,
            args.output_dir,
            log_file=log_file,
            keep_raw=not args.no_raw,
            enrich=not args.no_enrich,
            describe=not args.no_describe,
            agent=not args.no_agent,
        )

        results.append((pdf_path.name, success, duration))

        status = "SUCCESS" if success else "FAILED"
        print(f"\n[{i}/{total_pdfs}] {status} in {duration:.1f}s: {pdf_path.name}")

        # Update summary log after each PDF (for monitoring progress)
        total_duration_so_far = time.time() - total_start
        write_summary_log(
            args.output_dir / "batch_summary.log",
            results,
            total_duration_so_far,
            args,
        )

    # Final summary
    total_duration = time.time() - total_start
    successful = sum(1 for _, success, _ in results if success)
    failed = total_pdfs - successful

    # Write final summary log
    write_summary_log(
        args.output_dir / "batch_summary.log",
        results,
        total_duration,
        args,
    )

    print(f"\n{'=' * 60}")
    print("BATCH CONVERSION COMPLETE")
    print(f"{'=' * 60}")
    print(f"Total:      {total_pdfs} PDFs")
    print(f"Successful: {successful}")
    print(f"Failed:     {failed}")
    print(f"Duration:   {total_duration/60:.1f} minutes ({total_duration:.1f}s)")
    print(f"Average:    {total_duration/total_pdfs:.1f}s per PDF")
    print(f"Output:     {args.output_dir.absolute()}")
    print(f"Summary:    {args.output_dir.absolute() / 'batch_summary.log'}")
    print(f"Logs:       {logs_dir.absolute()}")

    if failed > 0:
        print(f"\nFailed PDFs (see individual logs for details):")
        for name, success, _ in results:
            if not success:
                print(f"  - {name}")
                print(f"    Log: logs/{Path(name).stem}.log")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

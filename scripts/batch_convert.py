#!/usr/bin/env python3
"""Batch convert PDFs to markdown using pdf2md.

Usage:
    uv run python scripts/batch_convert.py INPUT_FOLDER OUTPUT_FOLDER [OPTIONS]

Example:
    uv run python scripts/batch_convert.py papers/ output/ --depth high --local
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
    depth: str = "medium",
    local: bool = False,
    provider: str | None = None,
    model: str | None = None,
    keep_raw: bool = True,
) -> tuple[bool, float, str]:
    """
    Convert a single PDF using pdf2md CLI.

    Returns:
        Tuple of (success: bool, duration_seconds: float, output: str)
    """
    cmd = ["uv", "run", "pdf2md", "convert", str(pdf_path), str(output_dir)]
    cmd.extend(["--depth", depth])

    if keep_raw:
        cmd.append("--keep-raw")
    if local:
        cmd.append("--local")
    if provider:
        cmd.extend(["--provider", provider])
    if model:
        cmd.extend(["--model", model])

    start_time = time.time()
    start_timestamp = datetime.now().isoformat()

    if log_file:
        with open(log_file, "w", encoding="utf-8") as f:
            f.write(f"# PDF Conversion Log: {pdf_path.name}\n")
            f.write(f"# Started: {start_timestamp}\n")
            f.write(f"# Command: {' '.join(cmd)}\n")
            f.write("# Status: IN PROGRESS...\n")
            f.write("=" * 60 + "\n\n")

    try:
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
    avg_time = total_duration / len(results) if results else 0

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
        f.write(f"Duration:   {total_duration / 60:.1f} minutes ({total_duration:.1f}s)\n")
        f.write(f"Average:    {avg_time:.1f}s per PDF\n\n")

        f.write("Options:\n")
        f.write(f"  - Depth:    {args.depth}\n")
        f.write(f"  - Local:    {args.local}\n")
        f.write(f"  - Provider: {args.provider or 'default'}\n")
        f.write(f"  - Model:    {args.model or 'default'}\n")
        f.write(f"  - Keep raw: {not args.no_raw}\n\n")

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
  # Convert all PDFs with default settings (medium depth, cloud backend)
  uv run python scripts/batch_convert.py papers/ output/

  # Fast conversion (no AI)
  uv run python scripts/batch_convert.py papers/ output/ --depth low

  # Full processing with local LLM
  uv run python scripts/batch_convert.py papers/ output/ --depth high --local

  # Skip first 5 PDFs (useful for resuming after failure)
  uv run python scripts/batch_convert.py papers/ output/ --skip 5
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
        help="Directory to output converted markdown",
    )
    parser.add_argument(
        "--depth",
        choices=["low", "medium", "high"],
        default="medium",
        help="Analysis depth: low (fast), medium (balanced), high (thorough)",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Use local LLM/VLM instead of cloud (Claude)",
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="LLM provider: lm_studio (default), ollama",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override LLM/VLM model name",
    )
    parser.add_argument(
        "--no-raw",
        action="store_true",
        help="Don't keep raw markdown",
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

    if not args.input_dir.exists():
        print(f"Error: Input directory does not exist: {args.input_dir}")
        return 1

    if not args.input_dir.is_dir():
        print(f"Error: Input path is not a directory: {args.input_dir}")
        return 1

    pdf_files = get_pdf_files(args.input_dir)

    if not pdf_files:
        print(f"No PDF files found in {args.input_dir}")
        return 1

    if args.skip > 0:
        pdf_files = pdf_files[args.skip :]
    if args.limit is not None:
        pdf_files = pdf_files[: args.limit]

    if not pdf_files:
        print("No PDF files to process after applying --skip/--limit")
        return 0

    total_pdfs = len(pdf_files)

    backend_str = f"local ({args.provider or 'lm_studio'})" if args.local else "cloud (Claude)"
    print(f"{'=' * 60}")
    print("PDF Batch Conversion")
    print(f"{'=' * 60}")
    print(f"Input:   {args.input_dir.absolute()}")
    print(f"Output:  {args.output_dir.absolute()}")
    print(f"PDFs:    {total_pdfs} files")
    print(f"Depth:   {args.depth}")
    print(f"Backend: {backend_str}")
    if args.model:
        print(f"Model:   {args.model}")
    if args.skip > 0:
        print(f"Skipped: first {args.skip} PDFs")
    print(f"{'=' * 60}")

    if args.dry_run:
        print("\nDRY RUN - Files that would be processed:")
        for i, pdf in enumerate(pdf_files, 1):
            print(f"  {i:3d}. {pdf.name}")
        return 0

    args.output_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = args.output_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nLogs directory: {logs_dir.absolute()}")
    print(f"Summary log:    {args.output_dir.absolute() / 'batch_summary.log'}")

    results: list[tuple[str, bool, float]] = []
    total_start = time.time()

    for i, pdf_path in enumerate(pdf_files, 1):
        print(f"\n[{i}/{total_pdfs}] Processing: {pdf_path.name}")
        print(f"    Log: logs/{pdf_path.stem}.log")
        print("-" * 60)

        log_file = logs_dir / f"{pdf_path.stem}.log"

        success, duration, output = convert_pdf(
            pdf_path,
            args.output_dir,
            log_file=log_file,
            depth=args.depth,
            local=args.local,
            provider=args.provider,
            model=args.model,
            keep_raw=not args.no_raw,
        )

        results.append((pdf_path.name, success, duration))

        status = "SUCCESS" if success else "FAILED"
        print(f"\n[{i}/{total_pdfs}] {status} in {duration:.1f}s: {pdf_path.name}")

        total_duration_so_far = time.time() - total_start
        write_summary_log(
            args.output_dir / "batch_summary.log",
            results,
            total_duration_so_far,
            args,
        )

    total_duration = time.time() - total_start
    successful = sum(1 for _, success, _ in results if success)
    failed = total_pdfs - successful
    avg_time = total_duration / total_pdfs if total_pdfs else 0

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
    print(f"Duration:   {total_duration / 60:.1f} minutes ({total_duration:.1f}s)")
    print(f"Average:    {avg_time:.1f}s per PDF")
    print(f"Output:     {args.output_dir.absolute()}")
    print(f"Summary:    {args.output_dir.absolute() / 'batch_summary.log'}")
    print(f"Logs:       {logs_dir.absolute()}")

    if failed > 0:
        print("\nFailed PDFs (see individual logs for details):")
        for name, success, _ in results:
            if not success:
                print(f"  - {name}")
                print(f"    Log: logs/{Path(name).stem}.log")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

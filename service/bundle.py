"""Tar.gz streaming utility for packaging job output."""

import io
import tarfile
from pathlib import Path


def create_tar_gz_bundle(output_dir: Path) -> bytes:
    """Create a tar.gz archive of the output directory.

    Args:
        output_dir: Directory containing the conversion output (e.g. paper.md, img/).

    Returns:
        The tar.gz archive as bytes.
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(str(output_dir), arcname=output_dir.name)
    buf.seek(0)
    return buf.read()

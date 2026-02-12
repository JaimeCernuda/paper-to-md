# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp[cli]", "httpx", "pynacl", "python-dotenv"]
# ///
"""MCP server exposing pdf2md homelab service (submit, status, retrieve)."""

import base64
import os
import tarfile
import time
from io import BytesIO
from pathlib import Path

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from nacl.signing import SigningKey

_REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_REPO_ROOT / ".env")

BASE_URL = os.environ.get("PDF2MD_SERVICE_URL", "http://localhost:8000")
CLIENT_ID = os.environ["PDF2MD_CLIENT_ID"]
PRIVATE_KEY_B64 = os.environ["PDF2MD_PRIVATE_KEY"]

_sk = SigningKey(base64.b64decode(PRIVATE_KEY_B64))

mcp = FastMCP("pdf2md-service")


def _sign(method: str, path: str) -> dict[str, str]:
    """Build Ed25519 auth headers for the service."""
    ts = str(int(time.time()))
    payload = f"{method}\n{path}\n{ts}".encode()
    sig = _sk.sign(payload).signature
    return {
        "Authorization": f"Signature {base64.b64encode(sig).decode()}",
        "X-Timestamp": ts,
        "X-Client-Id": CLIENT_ID,
    }


@mcp.tool()
async def pdf2md_submit(pdf_path: str, depth: str = "medium") -> str:
    """Submit a PDF for conversion. Returns job ID."""
    p = Path(pdf_path)
    if not p.exists():
        return f"Error: {pdf_path} not found"
    async with httpx.AsyncClient(timeout=60) as client:
        with open(p, "rb") as f:
            resp = await client.post(
                f"{BASE_URL}/submit_paper",
                files={"file": (p.name, f, "application/pdf")},
                data={"depth": depth},
                headers=_sign("POST", "/submit_paper"),
            )
    if resp.status_code not in (200, 202):
        return f"Error {resp.status_code}: {resp.text[:200]}"
    data = resp.json()
    return f"job_id: {data['job_id']}, status: {data.get('status', 'queued')}"


@mcp.tool()
async def pdf2md_status(job_id: str) -> str:
    """Check conversion job status."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{BASE_URL}/status/{job_id}",
            headers=_sign("GET", f"/status/{job_id}"),
        )
    if resp.status_code != 200:
        return f"Error {resp.status_code}: {resp.text[:200]}"
    d = resp.json()
    parts = [f"status: {d['status']}"]
    if d.get("progress"):
        parts.append(f"progress: {d['progress']}")
    if d.get("filename"):
        parts.append(f"file: {d['filename']}")
    if d.get("error"):
        parts.append(f"error: {d['error']}")
    return ", ".join(parts)


@mcp.tool()
async def pdf2md_retrieve(job_id: str, output_dir: str) -> str:
    """Download and extract conversion results."""
    dest = Path(output_dir)
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.get(
            f"{BASE_URL}/retrieve/{job_id}",
            headers=_sign("GET", f"/retrieve/{job_id}"),
        )
    if resp.status_code != 200:
        return f"Error {resp.status_code}: {resp.text[:200]}"
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=BytesIO(resp.content), mode="r:gz") as tar:
        tar.extractall(dest)
    files = [str(p.relative_to(dest)) for p in sorted(dest.rglob("*")) if p.is_file()]
    return f"Extracted to {dest}: {', '.join(files)}"


if __name__ == "__main__":
    mcp.run()

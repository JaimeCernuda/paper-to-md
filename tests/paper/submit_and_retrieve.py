"""Submit real papers to the homelab service, monitor, and retrieve results."""

import base64
import json
import sys
import tarfile
import time
from io import BytesIO
from pathlib import Path

import requests
from nacl.signing import SigningKey

BASE_URL = "http://10.0.0.102:8000"
CLIENT_ID = "00000000-0000-0000-0000-000000000001"
PRIVATE_KEY_B64 = "7nc8BePXyuokHZ90WwrOemJ5is1UlAcEB9h4YyYpVGY="
PAPER_DIR = Path(__file__).parent
DEPTH = "low"  # low = Docling + postprocess only, no Claude agent needed

sk = SigningKey(base64.b64decode(PRIVATE_KEY_B64))


def sign(method: str, path: str) -> dict[str, str]:
    ts = str(int(time.time()))
    payload = f"{method}\n{path}\n{ts}".encode()
    sig = sk.sign(payload).signature
    return {
        "Authorization": f"Signature {base64.b64encode(sig).decode()}",
        "X-Timestamp": ts,
        "X-Client-Id": CLIENT_ID,
    }


def submit(pdf_path: Path) -> str:
    with open(pdf_path, "rb") as f:
        resp = requests.post(
            f"{BASE_URL}/submit_paper",
            files={"file": (pdf_path.name, f, "application/pdf")},
            data={"depth": DEPTH},
            headers=sign("POST", "/submit_paper"),
        )
    resp.raise_for_status()
    data = resp.json()
    return data["job_id"]


def status(job_id: str) -> dict:
    resp = requests.get(
        f"{BASE_URL}/status/{job_id}",
        headers=sign("GET", f"/status/{job_id}"),
    )
    resp.raise_for_status()
    return resp.json()


def retrieve(job_id: str, dest: Path) -> None:
    resp = requests.get(
        f"{BASE_URL}/retrieve/{job_id}",
        headers=sign("GET", f"/retrieve/{job_id}"),
    )
    resp.raise_for_status()
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=BytesIO(resp.content), mode="r:gz") as tar:
        tar.extractall(dest)
    print(f"    Extracted to {dest}")


# ── Main ──────────────────────────────────────────────────────
pdfs = sorted(PAPER_DIR.glob("*.pdf"))
print(f"Found {len(pdfs)} papers: {[p.name for p in pdfs]}")
print(f"Depth: {DEPTH}\n")

# Submit all papers at once
jobs: list[tuple[str, str]] = []  # (job_id, filename)
for pdf in pdfs:
    size_mb = pdf.stat().st_size / 1_048_576
    print(f"Submitting {pdf.name} ({size_mb:.1f} MB) ...", end=" ", flush=True)
    jid = submit(pdf)
    print(f"job_id={jid}")
    jobs.append((jid, pdf.name))

print(f"\n{'='*70}")
print(f"Submitted {len(jobs)} jobs. Monitoring queue (max_jobs=1)...")
print(f"{'='*70}\n")

# Poll until all done
pending = {jid for jid, _ in jobs}
last_progress: dict[str, str | None] = {jid: None for jid, _ in jobs}
name_map = {jid: name for jid, name in jobs}
order_started: list[str] = []
order_completed: list[str] = []

while pending:
    for jid in list(pending):
        s = status(jid)
        prog = f"{s['status']}: {s['progress'] or ''}"
        if prog != last_progress[jid]:
            last_progress[jid] = prog
            elapsed = ""
            if s.get("started_at"):
                # rough elapsed since we can't easily parse ISO here
                pass
            print(f"  [{name_map[jid][:25]:25s}] {prog}")

            if s["status"] == "processing" and jid not in order_started:
                order_started.append(jid)
            if s["status"] in ("completed", "failed"):
                order_completed.append(jid)
                pending.discard(jid)
                if s["status"] == "failed":
                    print(f"    ERROR: {s.get('error')}")
    time.sleep(3)

# Print processing order
print(f"\n{'='*70}")
print("Processing order (should be sequential, one at a time):")
for i, jid in enumerate(order_started, 1):
    s = status(jid)
    print(f"  {i}. {name_map[jid]}")
    print(f"     started:   {s.get('started_at')}")
    print(f"     completed: {s.get('completed_at')}")

# Verify sequential: each job's started_at >= previous job's completed_at
print("\nSequential check:")
for i in range(1, len(order_started)):
    prev_jid = order_started[i - 1]
    curr_jid = order_started[i]
    prev_s = status(prev_jid)
    curr_s = status(curr_jid)
    prev_done = prev_s.get("completed_at", "")
    curr_start = curr_s.get("started_at", "")
    ok = curr_start >= prev_done if (curr_start and prev_done) else "?"
    sym = "OK" if ok else "OVERLAP"
    print(f"  {name_map[prev_jid]} -> {name_map[curr_jid]}: {sym}")

# Retrieve completed results
print(f"\n{'='*70}")
print("Retrieving results...")
output_dir = PAPER_DIR / "converted"
for jid, name in jobs:
    s = status(jid)
    if s["status"] == "completed":
        print(f"  Downloading {name} ...", end=" ", flush=True)
        retrieve(jid, output_dir)
    else:
        print(f"  SKIPPING {name} (status={s['status']})")

# List what we got
print(f"\n{'='*70}")
print("Retrieved files:")
if output_dir.exists():
    for p in sorted(output_dir.rglob("*")):
        if p.is_file():
            rel = p.relative_to(output_dir)
            size = p.stat().st_size
            print(f"  {rel}  ({size:,} bytes)")

print(f"\n{'='*70}")
print("DONE")

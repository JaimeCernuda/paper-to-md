"""Local LLM backend — targeted fixes via LiteLLM.

Uses LLM calls only for tasks requiring judgment (author formatting,
lettered section detection). Mechanical fixes (image comments, split
paragraphs, hyphenation, OCR artifacts) are handled by the postprocess
stage and are NOT duplicated here.

VLM support for figure descriptions via run_describe_figures().
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

from .base import AgentBackend

# ---------------------------------------------------------------------------
# Lettered section detection (programmatic candidate finding)
# ---------------------------------------------------------------------------


def _find_lettered_section_candidates(content: str) -> list[tuple[int, str]]:
    """Find lines that might be lettered section headers.

    Returns (line_number, line_text) for candidates matching:
    ^[A-Z]. followed by 1-4 capitalized/short words, then period/colon/newline.
    """
    candidates = []
    lines = content.split("\n")

    for i, line in enumerate(lines):
        stripped = line.strip()
        # Pattern: Letter + dot + space + short title (1-4 words)
        m = re.match(r"^([A-Z])\.\s+(.+)$", stripped)
        if not m:
            continue

        title_part = m.group(2).rstrip(".:")
        words = title_part.split()

        # Heuristic: 1-4 words, mostly capitalized, is likely a header
        if 1 <= len(words) <= 5 and any(w[0].isupper() for w in words if w):
            # Additional check: next non-blank line should be content
            for j in range(i + 1, min(i + 3, len(lines))):
                if lines[j].strip():
                    candidates.append((i, stripped))
                    break

    return candidates


# ---------------------------------------------------------------------------
# LLM-assisted fixes (only for tasks needing judgment)
# ---------------------------------------------------------------------------

AUTHOR_PROMPT = """\
Below is the beginning of an academic paper converted from PDF to markdown.
Author names, affiliations, and emails may appear before the abstract,
after the abstract, or scattered in the first section due to PDF extraction.

DOCUMENT HEAD:
{doc_head}

Return ONLY a markdown Authors section in this exact format (no other text):
## Authors
- **Name**, Institution, email
- **Name**, Institution

Rules:
- Find ALL authors regardless of where they appear in the text above
- Match authors to their institutions and emails
- If email is missing for an author, omit it
- If institution is missing for an author, omit it
- Handle any affiliation format (superscripts, inline, footnotes, etc.)
- Never invent information not present in the text"""


LETTERED_SECTION_PROMPT = """\
Classify each line as a section HEADER or regular SENTENCE.

A section header is a lettered label (A., B., C.) followed by a short title (1-4 words).
A regular sentence just happens to start with a letter and period.

Lines to classify:
{candidates}

Return ONLY a list like:
1. HEADER
2. SENTENCE
3. HEADER

One classification per line, nothing else."""


FIGURE_DESCRIPTION_PROMPT = """\
Describe this academic figure concisely. Include:
- Figure type (chart, diagram, flowchart, architecture, graph, table, etc.)
- Key elements, labels, and axes
- Data trends or relationships shown
- Any notable annotations

Be factual and concise (2-4 sentences). Do not speculate."""


async def _llm_call(prompt: str, system: str, config, max_tokens: int = 500) -> str:
    """Single LLM completion call via LiteLLM. Handles reasoning/thinking models."""
    import litellm

    # Budget extra tokens for thinking models (reasoning tokens don't count
    # toward visible output, but LM Studio counts them toward max_tokens
    # for some model backends).
    thinking_budget = max_tokens * 3

    kwargs: dict = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": thinking_budget,
        "temperature": 0.1,
        "timeout": 120,
    }

    if config.api_base:
        kwargs["api_base"] = config.api_base

    response = await litellm.acompletion(**kwargs)

    msg = response.choices[0].message
    content = msg.content or ""

    # Thinking models may put answer in reasoning_content if content is empty
    if not content.strip():
        reasoning = getattr(msg, "reasoning_content", None) or ""
        if reasoning.strip():
            content = reasoning

    # Strip <think>...</think> tags if model embeds them in content
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

    # Thinking models (e.g. Nemotron) may dump reasoning without <think> tags.
    # If the response contains a markdown header (## ), extract from there.
    if "\n## " in content:
        idx = content.index("\n## ")
        # Only strip if there's substantial text before the header (reasoning)
        if idx > 200:
            content = content[idx:].strip()

    return content


async def _vlm_call(image_b64: str, prompt: str, config, max_tokens: int = 500) -> str:
    """Single VLM completion call via LiteLLM with base64 image."""
    import litellm

    kwargs: dict = {
        "model": config.model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        "max_tokens": max_tokens,
        "temperature": 0.1,
        "timeout": 180,
    }

    if config.api_base:
        kwargs["api_base"] = config.api_base

    response = await litellm.acompletion(**kwargs)

    msg = response.choices[0].message
    content = msg.content or ""

    # Strip thinking tags from VLM output too
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

    return content


def _is_author_noise(line: str) -> bool:
    """Return True if line looks like orphaned author/affiliation/email text.

    These are lines Docling scattered outside the preamble that should be
    removed once authors are properly formatted.
    """
    s = line.strip()
    if not s or s.startswith("#") or s.startswith("![") or s.startswith("-"):
        return False
    # Standalone email line
    if re.match(r"^[\w.-]+@[\w.-]+\.\w{2,}$", s):
        return True
    # Numbered affiliation block: "1 University ... 2 Lab ..."
    if re.match(r"^\d\s+[A-Z]", s) and len(re.findall(r"\d\s+[A-Z]", s)) >= 2:
        return True
    # Correspondence / contact line (common footnote artifact)
    if re.match(r"^(Correspondence|Contact)\s+to:", s, re.IGNORECASE):
        return True
    # Short line with Name + Institution + email pattern (not a paragraph)
    if (
        len(s) < 300
        and re.search(
            r"University|Institute|Lab\b|Inc\b|CSIRO|Department|College",
            s,
        )
        and re.search(r"@[\w.-]+\.\w{2,}", s)
    ):
        return True
    return False


def _validate_author_block(result: str) -> bool:
    """Check that LLM output is a well-formed authors block.

    Requires ## Authors header AND at least one - **Name** entry.
    Rejects truncated/garbage output.
    """
    if "## Authors" not in result:
        return False
    # Must have at least one author bullet
    if not re.search(r"^- \*\*.+\*\*", result, re.MULTILINE):
        return False
    # Reject if excessive non-author content (> 50% of lines aren't bullets/header/blank)
    lines = [ln.strip() for ln in result.strip().split("\n")]
    noise = sum(1 for ln in lines if ln and not ln.startswith("## ") and not ln.startswith("- **"))
    if noise > len(lines) // 2:
        return False
    return True


async def _format_authors(content: str, config, verbose: bool) -> tuple[str, bool]:
    """Use LLM to extract and format authors from the document head.

    Returns (content, changed) — changed=False if no modification was made.
    """
    lines = content.split("\n")

    # Find title line (first ## header) and abstract/first-section boundary
    title_line = None
    preamble_end = 0
    for i, line in enumerate(lines):
        if line.startswith("## ") and title_line is None:
            title_line = i
        elif re.match(r"^## (Abstract|ABSTRACT|1\.?\s)", line):
            preamble_end = i
            break

    if title_line is None or preamble_end == 0 or preamble_end <= title_line:
        if verbose:
            print("  Authors: no title/abstract boundary found, skipping")
        return content, False

    # Send a generous chunk: ~3000 chars gives the LLM full context
    doc_head = content[:3000]

    if verbose:
        print(
            f"  Authors: sending {len(doc_head)} chars to LLM...",
            end="",
            flush=True,
        )

    try:
        result = await _llm_call(
            AUTHOR_PROMPT.format(doc_head=doc_head),
            "You extract and format author information from academic papers.",
            config,
            max_tokens=800,
        )

        if not _validate_author_block(result):
            if verbose:
                print(" skipped (bad/partial LLM output)")
            return content, False

        # Extract only the Authors block (strip any extra LLM commentary)
        author_start = result.index("## Authors")
        author_block = result[author_start:].strip()

        # Build new content: title + formatted authors + rest from Abstract on
        new_lines = lines[:title_line]  # anything before title (usually empty)
        new_lines.append(lines[title_line])  # title
        new_lines.append("")
        new_lines.append(author_block)
        new_lines.append("")
        new_lines.extend(lines[preamble_end:])

        # Remove orphaned author/affiliation noise from the document head.
        # Docling scatters affiliations after the abstract or into the early
        # body text (footnotes rendered inline). Scan from the Authors block
        # through the first ~20% of lines (capped at 60) — safely covers all
        # observed cases without risking removal of real body content.
        cleaned = []
        total_lines = len(new_lines)
        noise_cutoff = min(total_lines // 5, 60)
        past_authors = False
        for i, line in enumerate(new_lines):
            if line.startswith("## Authors"):
                past_authors = True
            if past_authors and i < noise_cutoff and _is_author_noise(line):
                continue
            cleaned.append(line)

        # Collapse runs of 3+ blank lines left by removals
        result = "\n".join(cleaned)
        result = re.sub(r"\n{4,}", "\n\n\n", result)

        if verbose:
            print(" done")
        return result, True

    except Exception as e:
        if verbose:
            print(f" failed: {e}")
        return content, False


async def _classify_lettered_sections(
    content: str, candidates: list[tuple[int, str]], config, verbose: bool
) -> str:
    """Use LLM to classify lettered section candidates as headers or sentences."""
    if not candidates:
        return content

    candidate_text = "\n".join(f"{i + 1}. {text}" for i, (_, text) in enumerate(candidates))

    if verbose:
        print(f"  Lettered sections: {len(candidates)} candidates...", end="", flush=True)

    try:
        result = await _llm_call(
            LETTERED_SECTION_PROMPT.format(candidates=candidate_text),
            "You classify text lines as section headers or regular sentences.",
            config,
            max_tokens=200,
        )

        # Parse classifications
        lines = content.split("\n")
        classifications = re.findall(r"(HEADER|SENTENCE)", result, re.IGNORECASE)

        converted = 0
        for j, classification in enumerate(classifications):
            if j >= len(candidates):
                break
            if classification.upper() == "HEADER":
                line_num, line_text = candidates[j]
                lines[line_num] = f"##### {line_text}"
                converted += 1

        if verbose:
            print(f" {converted} converted")
        return "\n".join(lines)

    except Exception as e:
        if verbose:
            print(f" failed: {e}")
        return content


# ---------------------------------------------------------------------------
# Backend class
# ---------------------------------------------------------------------------


class LocalBackend(AgentBackend):
    """Local LLM backend — targeted fixes.

    LLM only for judgment calls (authors, lettered sections).
    Mechanical cleanup is handled by the postprocess stage.
    Typically 1-2 small LLM calls regardless of document size.
    """

    async def run_cleanup(
        self,
        md_path: Path,
        img_dir: Path | None = None,
        *,
        provider: str | None = None,
        model: str | None = None,
        verbose: bool = False,
    ) -> str | None:
        try:
            import litellm  # noqa: F401
        except ImportError as e:
            raise ImportError(
                "Local backend dependencies not installed. "
                "Install with: pip install paper-to-md"
            ) from e

        from ..providers import get_provider_config

        provider = provider or "lm_studio"
        config = get_provider_config(provider, model)

        content = md_path.read_text(encoding="utf-8")
        changes: list[str] = []

        # 1. Format authors (LLM call #1 — small, focused)
        content, authors_changed = await _format_authors(content, config, verbose)
        if authors_changed:
            changes.append("Formatted authors section")

        # 2. Classify lettered section candidates (LLM call #2 — small, focused)
        candidates = _find_lettered_section_candidates(content)
        if candidates:
            content = await _classify_lettered_sections(content, candidates, config, verbose)
            changes.append(f"Checked {len(candidates)} lettered section candidates")
        elif verbose:
            print("  No lettered section candidates found")

        # Write result
        md_path.write_text(content, encoding="utf-8")

        summary = "; ".join(changes)
        return summary

    async def run_describe_figures(
        self,
        img_dir: Path,
        *,
        provider: str | None = None,
        model: str | None = None,
        verbose: bool = False,
    ) -> list[dict]:
        try:
            import litellm  # noqa: F401
        except ImportError as e:
            raise ImportError(
                "Local backend dependencies not installed. "
                "Install with: pip install paper-to-md"
            ) from e

        from ..providers import get_vlm_config

        provider = provider or "lm_studio"
        config = get_vlm_config(provider, model)

        # Find all figure images
        def _fig_sort_key(p: Path) -> int:
            m = re.search(r"\d+", p.stem)
            return int(m.group()) if m else 0

        figure_files = sorted(img_dir.glob("figure*.png"), key=_fig_sort_key)
        if not figure_files:
            if verbose:
                print("  No figure images found")
            return []

        if verbose:
            print(f"  Describing {len(figure_files)} figures with VLM ({config.model})...")

        results: list[dict] = []
        for fig_path in figure_files:
            # Extract figure number from filename (figure1.png -> 1)
            m = re.match(r"figure(\d+)", fig_path.stem)
            figure_id = int(m.group(1)) if m else 0

            if verbose:
                print(f"    Figure {figure_id}...", end="", flush=True)

            try:
                image_b64 = base64.b64encode(fig_path.read_bytes()).decode("ascii")
                description = await _vlm_call(
                    image_b64,
                    FIGURE_DESCRIPTION_PROMPT,
                    config,
                    max_tokens=500,
                )
                results.append({"figure_id": figure_id, "description": description})
                if verbose:
                    print(f" done ({len(description)} chars)")
            except Exception as e:
                if verbose:
                    print(f" failed: {e}")
                results.append({"figure_id": figure_id, "description": None})

        return results

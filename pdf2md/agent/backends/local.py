"""Local LLM backend via LiteLLM.

Uses LLM calls only for tasks requiring judgment (author formatting,
lettered section detection). Mechanical fixes (image comments, split
paragraphs, hyphenation, OCR artifacts) are handled by the postprocess
stage and are NOT duplicated here.

VLM support for figure descriptions via run_describe_figures().
Synthesis pass via run_synthesis() produces the final integrated markdown.
"""

from __future__ import annotations

import base64
import json
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
        m = re.match(r"^([A-Z])\.\s+(.+)$", stripped)
        if not m:
            continue

        title_part = m.group(2).rstrip(".:")
        words = title_part.split()

        if 1 <= len(words) <= 5 and any(w[0].isupper() for w in words if w):
            for j in range(i + 1, min(i + 3, len(lines))):
                if lines[j].strip():
                    candidates.append((i, stripped))
                    break

    return candidates


# ---------------------------------------------------------------------------
# Equation detection (heuristic, no ML)
# ---------------------------------------------------------------------------

# Unicode math characters that indicate equation content
_MATH_CHARS = set(
    "∀∃∄∅∆∇∈∉∊∋∌∍∎∏∐∑−∓∔∕∖∗∘∙√∛∜∝∞∟∠∡∢∣∤∥∦∧∨∩∪∫∬∭∮∯∰∱∲∳"
    "∴∵∶∷∸∹∺∻∼∽∾∿≀≁≂≃≄≅≆≇≈≉≊≋≌≍≎≏≐≑≒≓≔≕≖≗≘≙≚≛≜≝≞≟"
    "≠≡≢≣≤≥≦≧≨≩≪≫≬≭≮≯≰≱≲≳≴≵≶≷≸≹≺≻≼≽≾≿⊀⊁⊂⊃⊄⊅⊆⊇⊈⊉⊊⊋"
    "⊌⊍⊎⊏⊐⊑⊒⊓⊔⊕⊖⊗⊘⊙⊚⊛⊜⊝⊞⊟⊠⊡⊢⊣⊤⊥⊦⊧⊨⊩⊪⊫⊬⊭⊮⊯⊰⊱"
    "⊲⊳⊴⊵⊶⊷⊸⊹⊺⊻⊼⊽⊾⊿⋀⋁⋂⋃⋄⋅⋆⋇⋈⋉⋊⋋⋌⋍⋎⋏⋐⋑⋒⋓⋔⋕⋖⋗"
    "⋘⋙⋚⋛⋜⋝⋞⋟⋠⋡⋢⋣⋤⋥⋦⋧⋨⋩⋪⋫⋬⋭⋮⋯⋰⋱"
    "αβγδεζηθικλμνξοπρςστυφχψωΓΔΘΛΞΠΣΦΨΩ"
    "𝑎𝑏𝑐𝑑𝑒𝑓𝑔ℎ𝑖𝑗𝑘𝑙𝑚𝑛𝑜𝑝𝑞𝑟𝑠𝑡𝑢𝑣𝑤𝑥𝑦𝑧"
    "₀₁₂₃₄₅₆₇₈₉⁰¹²³⁴⁵⁶⁷⁸⁹"
)

# Minimum fraction of math chars in a line to consider it a display equation
_MATH_CHAR_THRESHOLD = 0.30
_MIN_MATH_CHARS_ABSOLUTE = 4


def _is_display_equation_line(line: str, prev_line: str, next_line: str) -> bool:
    """Check if a line is a standalone display equation, not inline math.

    Display equations are on their own line, have high math character density,
    and are surrounded by blank or short lines (not embedded in paragraphs).
    """
    stripped = line.strip()
    if not stripped:
        return False

    math_count = sum(1 for c in stripped if c in _MATH_CHARS)
    if math_count < _MIN_MATH_CHARS_ABSOLUTE:
        return False

    density = math_count / max(len(stripped), 1)

    # High density: clearly an equation
    if density >= 0.50:
        return True

    # Medium density: only if the line is short (not a paragraph with some math)
    if density >= _MATH_CHAR_THRESHOLD and len(stripped) < 80:
        # Must not be embedded in a paragraph (prev/next should be blank or short)
        prev_is_para = len(prev_line.strip()) > 40 and not prev_line.strip().startswith("#")
        next_is_para = len(next_line.strip()) > 40 and not next_line.strip().startswith("#")
        if prev_is_para and next_is_para:
            return False  # inline math within a paragraph
        return True

    return False


def detect_equations(content: str) -> list[dict]:
    """Detect display equation regions in extracted text.

    Only detects equations that appear as standalone display equations
    (on their own line, not inline math fragments within paragraphs).
    Finds lines with high concentration of math unicode characters
    that represent garbled equation extraction from PDFs.

    Returns list of {line_start, line_end, raw_text} dicts.
    """
    lines = content.split("\n")
    equations: list[dict] = []
    i = 0

    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        prev_line = lines[i - 1] if i > 0 else ""
        next_line = lines[i + 1] if i + 1 < len(lines) else ""

        if _is_display_equation_line(line, prev_line, next_line):
            start = i
            eq_lines = [lines[i]]
            i += 1
            # Extend through consecutive math lines
            while i < len(lines):
                next_stripped = lines[i].strip()
                if not next_stripped:
                    i += 1
                    continue
                after = lines[i + 1] if i + 1 < len(lines) else ""
                if _is_display_equation_line(next_stripped, eq_lines[-1], after):
                    eq_lines.append(lines[i])
                    i += 1
                else:
                    break

            equations.append(
                {
                    "line_start": start,
                    "line_end": i - 1,
                    "raw_text": "\n".join(eq_lines),
                }
            )
        else:
            i += 1

    return equations


# ---------------------------------------------------------------------------
# Section hierarchy and splitting helpers
# ---------------------------------------------------------------------------

# Pattern: numbered section like "1 Introduction", "2.1 Background", "A NP-Hardness"
_NUMBERED_SECTION_RE = re.compile(r"^##\s+(\d+(?:\.\d+)*)\s+(.+)$")

_APPENDIX_SECTION_RE = re.compile(r"^##\s+([A-Z])\s+([A-Z].+)$")


def _fix_section_hierarchy(content: str) -> str:
    """Convert flat ## headers with numbering into proper hierarchy.

    ## 1 Introduction        →  ## Introduction
    ## 2.1 System Components →  ### System Components
    ## 3.2.1 Energy          →  #### Energy
    ## A NP-Hardness Proof   →  ## Appendix A: NP-Hardness Proof
    """
    lines = content.split("\n")
    result = []

    for line in lines:
        m = _NUMBERED_SECTION_RE.match(line)
        if m:
            number = m.group(1)
            title = m.group(2).strip()
            depth = number.count(".") + 1
            # Map depth to heading level: 1=##, 2=###, 3=####
            hashes = "#" * (depth + 1)
            result.append(f"{hashes} {title}")
            continue

        m = _APPENDIX_SECTION_RE.match(line)
        if m:
            letter = m.group(1)
            title = m.group(2).strip()
            result.append(f"## Appendix {letter}: {title}")
            continue

        result.append(line)

    return "\n".join(result)


def _deduplicate_paragraphs(content: str) -> str:
    """Remove duplicate paragraphs from the document.

    The synthesis pass sometimes duplicates content (e.g., a figure
    analysis paragraph appears at both its natural position and in a
    later section). Paragraphs longer than 100 characters that appear
    more than once are reduced to the first occurrence.
    """
    blocks = content.split("\n\n")
    seen: set[str] = set()
    result: list[str] = []

    for block in blocks:
        stripped = block.strip()
        # Only deduplicate substantial prose paragraphs
        if len(stripped) < 100 or stripped.startswith("#") or stripped.startswith("|"):
            result.append(block)
            continue

        # Normalize whitespace for comparison
        normalized = " ".join(stripped.split())
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(block)

    return "\n\n".join(result)


def _split_into_sections(content: str) -> list[str]:
    """Split markdown content into sections at ## boundaries.

    Each section includes its heading and all content until the next
    heading of equal or higher level (## or #).
    """
    lines = content.split("\n")
    sections: list[str] = []
    current: list[str] = []

    for line in lines:
        if line.startswith("## ") and current:
            sections.append("\n".join(current))
            current = []
        current.append(line)

    if current:
        sections.append("\n".join(current))

    return sections


# ---------------------------------------------------------------------------
# Prompts
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


FIGURE_DESCRIPTION_SYSTEM = """\
You are an expert at analyzing figures from academic research papers. \
You produce precise, factual descriptions that capture the key information \
conveyed by each figure. Your descriptions will be embedded in the paper's \
markdown as figure captions for downstream academic review."""

FIGURE_DESCRIPTION_PROMPT = """\
Describe this figure from an academic research paper. Follow these guidelines:

STRUCTURE YOUR DESCRIPTION AS:
1. **Type**: What kind of figure this is (bar chart, line graph, architecture diagram, \
flowchart, heatmap, scatter plot, system diagram, photograph, etc.)
2. **Content**: The key elements, labels, axes, data series, or components shown
3. **Findings**: The main trend, comparison, or relationship the figure demonstrates
4. **Details**: Notable annotations, legends, color coding, or scale information

EXAMPLE DESCRIPTIONS:

Example 1 (performance chart):
"Bar chart comparing throughput (MB/s) across four storage systems (ext4, XFS, BtrFS, \
ZFS) for sequential and random I/O workloads. Sequential reads reach 2.1 GB/s on XFS \
while random writes peak at 450 MB/s on ext4. Error bars show standard deviation across \
5 runs. ZFS shows the highest variance in random workloads."

Example 2 (architecture diagram):
"System architecture diagram showing three layers: a client tier with REST API gateway, \
a processing tier with four worker nodes connected via message queue, and a storage tier \
with distributed object store and metadata database. Arrows indicate data flow from \
ingestion through processing to storage. The processing tier highlights GPU-accelerated \
inference nodes in orange."

YOUR DESCRIPTION (2-5 sentences, factual, no speculation):"""


EQUATION_RECONSTRUCTION_PROMPT = """\
The following text was extracted from an academic PDF and contains garbled \
unicode representing mathematical equations. Reconstruct the LaTeX for each \
equation.

GARBLED TEXT:
{raw_text}

Return ONLY the LaTeX equation(s), one per line, wrapped in $$ delimiters. \
If there are multiple equations, separate them with blank lines. \
Do not include any explanation or commentary.

Example output:
$$E = mc^2$$

$$\\frac{{\\partial u}}{{\\partial t}} = \\alpha \\nabla^2 u$$"""


SECTION_CLEANUP_PROMPT = """\
You are cleaning up a SINGLE SECTION of an academic paper that was extracted \
from PDF. Fix ONLY these issues:

1. GARBLED UNICODE: Replace /u1D4XX escape sequences and garbled math-like \
unicode with proper LaTeX (\\( \\) for inline, \\[ \\] for display). If you \
cannot determine the intended symbol, leave it as-is.
2. SPLIT PARAGRAPHS: Merge lines that were broken mid-sentence by page breaks. \
A paragraph continuation is indicated by a line not ending in sentence-terminal \
punctuation followed by a line starting with a lowercase letter.
3. CONCATENATED WORDS: Fix words run together (e.g., "CrewReadinessMonitoring" \
→ "Crew Readiness Monitoring").
4. ORPHANED TEXT: Remove stray single words or fragments that are clearly \
extraction artifacts (not part of a sentence).

DO NOT:
- Remove, summarize, or shorten ANY content
- Change the meaning of any sentence
- Add information not present in the input
- Modify citation links like [[1]](#ref-1)
- Remove or modify reference anchors like <a id="ref-1"></a>

Return the COMPLETE cleaned section text, preserving every sentence."""


# ---------------------------------------------------------------------------
# LLM / VLM call helpers
# ---------------------------------------------------------------------------


async def _llm_call(
    prompt: str,
    system: str,
    config,
    *,
    max_tokens: int = 16384,
    temperature: float = 0.3,
) -> str:
    """Single LLM completion call via LiteLLM. Handles reasoning/thinking models."""
    import litellm

    kwargs: dict = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "timeout": 600,
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


async def _vlm_call(
    image_b64: str,
    prompt: str,
    config,
    *,
    system: str | None = None,
    max_tokens: int = 2048,
    temperature: float = 0.2,
) -> str:
    """Single VLM completion call via LiteLLM with base64 image.

    Uses low temperature for factual descriptions. Extracts useful
    reasoning from thinking models (Qwen3-VL-Thinking) instead of
    discarding it entirely.
    """
    import litellm

    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})

    messages.append(
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
    )

    kwargs: dict = {
        "model": config.model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "timeout": 300,
    }

    if config.api_base:
        kwargs["api_base"] = config.api_base

    response = await litellm.acompletion(**kwargs)

    msg = response.choices[0].message
    content = msg.content or ""

    # For thinking models: extract reasoning summary if present
    thinking_match = re.search(r"<think>(.*?)</think>", content, flags=re.DOTALL)
    thinking_summary = ""
    if thinking_match:
        thinking_text = thinking_match.group(1).strip()
        # Extract the last 1-2 sentences of thinking as supplementary detail
        sentences = re.split(r"(?<=[.!?])\s+", thinking_text)
        if len(sentences) > 2:
            thinking_summary = " ".join(sentences[-2:])
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

    # Append condensed reasoning if it adds value
    if thinking_summary and content and len(thinking_summary) < len(content):
        content = content.rstrip() + " " + thinking_summary

    return content


# ---------------------------------------------------------------------------
# Author formatting helpers
# ---------------------------------------------------------------------------


def _is_author_noise(line: str) -> bool:
    """Return True if line looks like orphaned author/affiliation/email text."""
    s = line.strip()
    if not s or s.startswith("#") or s.startswith("![") or s.startswith("-"):
        return False
    if re.match(r"^[\w.-]+@[\w.-]+\.\w{2,}$", s):
        return True
    if re.match(r"^\d\s+[A-Z]", s) and len(re.findall(r"\d\s+[A-Z]", s)) >= 2:
        return True
    if re.match(r"^(Correspondence|Contact)\s+to:", s, re.IGNORECASE):
        return True
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
    """Check that LLM output is a well-formed authors block."""
    if "## Authors" not in result:
        return False
    if not re.search(r"^- \*\*.+\*\*", result, re.MULTILINE):
        return False
    lines = [ln.strip() for ln in result.strip().split("\n")]
    noise = sum(1 for ln in lines if ln and not ln.startswith("## ") and not ln.startswith("- **"))
    if noise > len(lines) // 2:
        return False
    return True


# ---------------------------------------------------------------------------
# LLM-assisted fixes
# ---------------------------------------------------------------------------


async def _format_authors(content: str, config, verbose: bool) -> tuple[str, bool]:
    """Use LLM to extract and format authors from the document head."""
    lines = content.split("\n")

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
        )

        if not _validate_author_block(result):
            if verbose:
                print(" skipped (bad/partial LLM output)")
            return content, False

        author_start = result.index("## Authors")
        author_block = result[author_start:].strip()

        new_lines = lines[:title_line]
        new_lines.append(lines[title_line])
        new_lines.append("")
        new_lines.append(author_block)
        new_lines.append("")
        new_lines.extend(lines[preamble_end:])

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
        )

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


async def _reconstruct_equations(equations: list[dict], config, verbose: bool) -> list[dict]:
    """Send garbled equation text to LLM for LaTeX reconstruction."""
    if not equations:
        return equations

    if verbose:
        print(f"  Equations: reconstructing {len(equations)} regions...", end="", flush=True)

    results = []
    for eq in equations:
        try:
            latex = await _llm_call(
                EQUATION_RECONSTRUCTION_PROMPT.format(raw_text=eq["raw_text"]),
                "You reconstruct LaTeX equations from garbled unicode text extracted from PDFs.",
                config,
                max_tokens=2048,
                temperature=0.1,
            )
            results.append({**eq, "latex": latex.strip()})
        except Exception as e:
            if verbose:
                print(f" failed on line {eq['line_start']}: {e}")
            results.append({**eq, "latex": None})

    if verbose:
        reconstructed = sum(1 for r in results if r.get("latex"))
        print(f" {reconstructed}/{len(results)} reconstructed")

    return results


# ---------------------------------------------------------------------------
# Backend class
# ---------------------------------------------------------------------------


class LocalBackend(AgentBackend):
    """Local LLM backend with targeted fixes, VLM descriptions, and synthesis.

    LLM handles judgment calls (authors, lettered sections, equation
    reconstruction). VLM handles figure descriptions. Synthesis pass
    integrates everything into final clean markdown.
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
                "Install with: pip install 'pdf2md[agent-local]'"
            ) from e

        from ..providers import get_provider_config

        provider = provider or "lm_studio"
        config = get_provider_config(provider, model)

        content = md_path.read_text(encoding="utf-8")
        changes: list[str] = []

        content, authors_changed = await _format_authors(content, config, verbose)
        if authors_changed:
            changes.append("Formatted authors section")

        candidates = _find_lettered_section_candidates(content)
        if candidates:
            content = await _classify_lettered_sections(content, candidates, config, verbose)
            changes.append(f"Checked {len(candidates)} lettered section candidates")
        elif verbose:
            print("  No lettered section candidates found")

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
                "Install with: pip install 'pdf2md[agent-local]'"
            ) from e

        from ..providers import get_vlm_config

        provider = provider or "lm_studio"
        config = get_vlm_config(provider, model)

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
                    system=FIGURE_DESCRIPTION_SYSTEM,
                )
                results.append({"figure_id": figure_id, "description": description})
                if verbose:
                    print(f" done ({len(description)} chars)")
            except Exception as e:
                if verbose:
                    print(f" failed: {e}")
                results.append({"figure_id": figure_id, "description": None})

        return results

    async def run_synthesis(
        self,
        md_path: Path,
        figures: list[dict],
        tables: list[dict],
        equations: list[dict],
        *,
        provider: str | None = None,
        model: str | None = None,
        verbose: bool = False,
    ) -> str:
        """Synthesize final markdown by programmatic integration + LLM cleanup.

        This is an edit-based approach that preserves every character of
        original text. It programmatically inserts figures, tables, and
        equations at the right positions, fixes section hierarchy, then
        uses the LLM only for targeted cleanup of garbled unicode and
        split paragraphs in each section.
        """
        try:
            import litellm  # noqa: F401
        except ImportError as e:
            raise ImportError(
                "Local backend dependencies not installed. "
                "Install with: pip install 'pdf2md[agent-local]'"
            ) from e

        from ..providers import get_provider_config

        provider = provider or "lm_studio"
        config = get_provider_config(provider, model)

        content = md_path.read_text(encoding="utf-8")

        # ── Step 1: Detect and reconstruct equations ──────────────────
        detected_equations = detect_equations(content)
        if detected_equations and verbose:
            print(f"  Detected {len(detected_equations)} equation regions")

        if detected_equations:
            detected_equations = await _reconstruct_equations(detected_equations, config, verbose)

        all_equations = equations + [e for e in detected_equations if e.get("latex")]

        # ── Step 2: Replace garbled equation text with LaTeX ──────────
        lines = content.split("\n")
        # Process in reverse order to preserve line numbers
        for eq in sorted(all_equations, key=lambda e: e.get("line_start", 0), reverse=True):
            latex = eq.get("latex")
            if not latex:
                continue
            start = eq.get("line_start", -1)
            end = eq.get("line_end", start)
            if 0 <= start < len(lines):
                lines[start : end + 1] = [latex]

        content = "\n".join(lines)

        # ── Step 3: Fix section hierarchy programmatically ────────────
        content = _fix_section_hierarchy(content)

        # ── Step 4: Insert figure captions with VLM descriptions ──────
        if figures:
            fig_desc_map = {}
            for fig in figures:
                fid = fig.get("figure_id")
                desc = fig.get("description")
                if fid and desc:
                    fig_desc_map[fid] = desc

            lines = content.split("\n")
            new_lines = []
            for line in lines:
                new_lines.append(line)
                # After a figure image line, add the VLM description
                img_match = re.match(r"!\[Figure\s+(\d+)\]", line)
                if img_match:
                    fid = int(img_match.group(1))
                    if fid in fig_desc_map:
                        # Check if the next line already has a caption
                        # (from postprocess). Enhance it with VLM desc.
                        pass  # Description will be on the caption line

            # Add VLM descriptions as HTML comments after figure image lines
            # so they're invisible in rendered markdown but parseable by code.
            # The figures.json sidecar remains the canonical store.
            new_lines2 = []
            for line in new_lines:
                new_lines2.append(line)
                img_match2 = re.match(r"!\[Figure\s+(\d+)\]", line)
                if img_match2:
                    fid = int(img_match2.group(1))
                    if fid in fig_desc_map:
                        desc = fig_desc_map[fid].replace("-->", "—>")
                        new_lines2.append(f"<!-- VLM: {desc} -->")

            content = "\n".join(new_lines2)

        # ── Step 5: Remove formula-not-decoded placeholders ───────────
        content = re.sub(
            r"\n*<!-- formula-not-decoded -->\n*",
            "\n",
            content,
        )

        # ── Step 6: LLM cleanup for garbled unicode per section ───────
        sections = _split_into_sections(content)
        if verbose:
            print(f"  Cleanup: {len(sections)} sections to process")

        cleaned_sections = []
        for i, section in enumerate(sections):
            # Only send sections that have garbled unicode to the LLM
            has_garble = bool(
                re.search(r"/u1D[0-9A-F]{3}", section)
                or re.search(r"[\U0001D400-\U0001D7FF]", section)
                or re.search(r"[\uD400-\uD7FF]", section)
                or re.search(r"\u0000", section)
            )
            if has_garble:
                if verbose:
                    print(
                        f"    Section {i + 1}/{len(sections)}: {len(section)} chars, cleaning...",
                        end="",
                        flush=True,
                    )
                try:
                    cleaned = await _llm_call(
                        section,
                        SECTION_CLEANUP_PROMPT,
                        config,
                        max_tokens=32768,
                        temperature=0.1,
                    )
                    # Sanity check: cleaned should be similar length
                    if len(cleaned) >= len(section) * 0.7:
                        cleaned_sections.append(cleaned)
                        if verbose:
                            print(f" done ({len(cleaned)} chars)")
                    else:
                        # LLM truncated the section, keep original
                        cleaned_sections.append(section)
                        if verbose:
                            print(" KEPT ORIGINAL (LLM truncated)")
                except Exception as e:
                    cleaned_sections.append(section)
                    if verbose:
                        print(f" failed: {e}")
            else:
                cleaned_sections.append(section)

        content = "\n\n".join(cleaned_sections)

        # ── Step 7: Deduplicate paragraphs ────────────────────────────
        content = _deduplicate_paragraphs(content)

        # ── Step 8: Final cleanup passes ──────────────────────────────
        # Collapse excessive blank lines
        content = re.sub(r"\n{4,}", "\n\n\n", content)
        # Strip trailing whitespace
        content = re.sub(r"[ \t]+$", "", content, flags=re.MULTILINE)

        # Write output
        md_path.write_text(content, encoding="utf-8")

        # Save enrichment data
        doc_dir = md_path.parent
        if figures:
            (doc_dir / "figures.json").write_text(
                json.dumps(figures, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        if tables:
            (doc_dir / "tables.json").write_text(
                json.dumps(tables, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        if all_equations:
            (doc_dir / "equations.json").write_text(
                json.dumps(
                    all_equations,
                    indent=2,
                    ensure_ascii=False,
                    default=str,
                ),
                encoding="utf-8",
            )

        return content

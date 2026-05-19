"""Algorithm detection: wrap pseudocode blocks in fenced code blocks.

Detects "Algorithm N:" blocks with Input/Output lines, numbered steps,
assignment operators (←), comments (//), and control-flow keywords.
Wraps them in markdown code fences so paragraph reflow preserves them.
"""

from __future__ import annotations

import re

_ALGO_START_RE = re.compile(
    r"^Algorithm\s+\d+\s*:",
    re.IGNORECASE,
)

# Broader pattern for "Algorithm N Title" without colon.
# Matches when the text after "Algorithm N " is a short title
# (capitalized words, not a sentence starting with a verb).
_ALGO_START_NO_COLON_RE = re.compile(
    r"^Algorithm\s+\d+\s+([A-Z][A-Za-z]*(?:\s+[A-Za-z]+){0,6})\s*$",
    re.IGNORECASE,
)

# Patterns that indicate a line is algorithm pseudocode
_PSEUDOCODE_INDICATORS = re.compile(
    r"←|"  # assignment
    r"^//\s|"  # comment
    r"^\d+\s+[A-ZΠΣ←]|"  # numbered step: "1 ΠS ←..."
    r"^\d+:\s|"  # numbered step: "1: Input: ..."
    r"^(foreach|while|for|if|else|end|return|do|then|Input|Output|Function)\b",
    re.IGNORECASE,
)

# Patterns that end an algorithm block
_BODY_TEXT_RE = re.compile(
    r"^(#{1,6}\s|!\[|Figure\s+\d+|Fig\.?\s+\d+|Table\s+\d+)",
    re.IGNORECASE,
)


def _is_algo_line(line: str) -> bool:
    """Check if a line looks like algorithm pseudocode content."""
    stripped = line.strip()
    if not stripped:
        return True  # blank lines within algorithm are OK

    # Structural markers end the block
    if _BODY_TEXT_RE.match(stripped):
        return False

    # Pseudocode indicators
    if _PSEUDOCODE_INDICATORS.search(stripped):
        return True

    # Lines with high unicode density (math variables from PDF)
    unicode_chars = sum(1 for c in stripped if ord(c) > 0x0370)
    if len(stripped) > 0 and unicode_chars / len(stripped) > 0.15:
        return True

    # Very short lines are algorithm fragments (variable names,
    # partial expressions, operator lines like ";")
    if len(stripped) < 40:
        return True

    # Medium lines without sentence structure (no period at end)
    if len(stripped) < 80 and not re.search(r"[.!?]$", stripped):
        return True

    return False


def process_algorithms(content: str) -> str:
    """Detect algorithm blocks and wrap them in fenced code blocks.

    Finds "Algorithm N:" headers and collects pseudocode lines until
    body text resumes. Wraps each block in a markdown code fence so
    paragraph reflow in cleanup.py preserves the structure.

    Args:
        content: Markdown content (before cleanup/reflow)

    Returns:
        Content with algorithm blocks wrapped in code fences.
    """
    lines = content.split("\n")
    result: list[str] = []
    i = 0

    while i < len(lines):
        stripped = lines[i].strip()

        if _ALGO_START_RE.match(stripped) or _ALGO_START_NO_COLON_RE.match(stripped):
            # Collect the algorithm header (may span multiple lines)
            algo_lines: list[str] = [stripped]
            i += 1

            # Check if title continues on next line (short continuation
            # that isn't Input/Output/comment)
            if i < len(lines):
                next_s = lines[i].strip()
                if (
                    next_s
                    and not _PSEUDOCODE_INDICATORS.search(next_s)
                    and len(next_s) < 60
                    and not next_s.startswith("//")
                ):
                    algo_lines[0] = algo_lines[0] + " " + next_s
                    i += 1

            # Collect pseudocode lines
            consecutive_non_algo = 0
            while i < len(lines):
                stripped_line = lines[i].strip()

                if _is_algo_line(stripped_line):
                    algo_lines.append(stripped_line)
                    consecutive_non_algo = 0
                    i += 1
                else:
                    # Body text or structural element ends the block.
                    # But allow one borderline line (Input continuation
                    # lines can be longish) before fully stopping.
                    consecutive_non_algo += 1
                    if consecutive_non_algo >= 1:
                        break
                    algo_lines.append(stripped_line)
                    i += 1

            # Trim trailing blank lines from the block
            while algo_lines and not algo_lines[-1]:
                algo_lines.pop()

            # Only wrap if we collected meaningful pseudocode (>3 lines)
            if len(algo_lines) > 3:
                result.append("")
                result.append("```")
                result.extend(algo_lines)
                result.append("```")
                result.append("")
            else:
                result.extend(algo_lines)

            continue

        result.append(lines[i])
        i += 1

    return "\n".join(result)

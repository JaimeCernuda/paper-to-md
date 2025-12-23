"""Claude agent for open-ended markdown cleanup."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class AgentNotInstalledError(ImportError):
    """Raised when Claude Agent SDK is not installed."""

    def __init__(self) -> None:
        super().__init__(
            "Claude Agent SDK is not installed. Install with: pip install pdf2md[agent]"
        )


# Open-ended prompt with specific guidance for common PDF extraction issues
CLEANUP_PROMPT = """You are reviewing and improving an academic paper that was extracted from PDF to markdown.

## Files
- **Markdown:** {md_path}
- **Images directory:** {img_dir}

## Your Goal

Review the markdown file and fix extraction artifacts. This is an open-ended task - use your judgment.

## Priority Tasks

### 1. Fix Section Headers (IMPORTANT - Requires Context)

The regex-based preprocessor handles numbered sections (1.1, 3.1.2, etc.) but CANNOT reliably detect:

**Lettered sections** - These need YOUR judgment because they can be:
- Real section headers: "A. Background" or "B. Related Work"
- Regular sentences: "A. We conducted an experiment..." (NOT a header!)

**How to identify lettered section headers:**
1. Look for patterns like `A.`, `B.`, `C.` at line start followed by a short title
2. They should be followed by paragraph content (not be part of a sentence)
3. The "title" should be 1-4 words, typically capitalized
4. They usually appear WITHIN numbered sections as sub-items

**Examples to FIX (convert to headers):**
```
A. RAM management.                    → ##### A. RAM management
B. Metadata management:               → ##### B. Metadata management  
C. Data placement                     → ##### C. Data placement
```

**Examples to LEAVE ALONE (not headers):**
```
A. We conducted experiments on...     (This is a sentence starting with "A.")
B. In our evaluation, we found...     (This is a continuation)
```

**Header level guidance:**
- Lettered sections are typically sub-items, use level 5 (#####)
- Or match the level of surrounding numbered sections + 1

Also check for:
- Roman numeral sections (I., II., III.) that weren't converted
- Mixed numbering (1.A, 2.B) patterns
- Sections with unusual formatting

### 2. Relocate Misplaced Figures (Image + Caption Together)

PDF extraction places figures where they appear in the LaTeX layout (often at page tops), NOT where they're referenced. A figure consists of THREE parts that must be moved TOGETHER:

1. `![Figure N](./img/figureN.png)` - the image embed
2. `Fig. N. Caption text here` - the caption line
3. `<!-- image -->` - a placeholder comment (delete this)

**How to fix:**
- Search for figure references in the text like "Fig. 1", "Figure 2", "as shown in Fig. 3"
- Find the FIRST section/subsection (any heading with #) that references each figure
- Move BOTH the image embed AND its caption to the START of that section (right after the heading)
- DELETE the `<!-- image -->` placeholder entirely

**IMPORTANT:** The image and caption are often separated in the original. You need to:
1. Find `![Figure N]` - this is the image
2. Find `Fig. N. ...` (the caption) - this may be elsewhere in the document
3. Move them BOTH together to the new location
4. Remove any leftover `<!-- image -->` placeholders

Example BEFORE:
```
![Figure 2](./img/figure2.png)    <- Image here at top of page

## III. METHODOLOGY

Text that says "as shown in Fig. 2"...

Fig. 2. Architecture overview    <- Caption is separate!

<!-- image -->                   <- Delete this
```

Example AFTER:
```
## III. METHODOLOGY

![Figure 2](./img/figure2.png)
*Fig. 2. Architecture overview*

Text that says "as shown in Fig. 2"...
```

### 3. Remove OCR Artifacts Above Captions

Docling sometimes extracts garbage text from figure images via OCR. These appear as:
- Short random text sequences (single words, fragments)
- Appear directly ABOVE figure captions
- Often look like axis labels, legend text, or garbled characters

Remove these artifacts. The caption itself (starting with "Fig." or "Figure") should remain.

### 4. Format Authors Section

Academic papers often have messy author formatting after PDF extraction. Create a clean **Authors** section right after the title.

**Target format:**
```markdown
## Authors

- **Author Name**, Institution Name, email@example.com
- **Author Name**, Institution Name, email@example.com
```

**How to find author information:**
1. Look at the beginning of the document for author names (often right after the title)
2. Look for institution names, department names, university names
3. Look for email addresses (often formatted as author@domain.edu or in footnotes)
4. ACM/IEEE papers often have superscript numbers mapping authors to institutions

**Common patterns to handle:**
- Authors listed with superscript numbers: John Smith1, Jane Doe2 with institutions listed separately below
- Authors with inline affiliations: John Smith (MIT), Jane Doe (Stanford)
- Email addresses in footnotes or at the end of author block
- Multiple authors from same institution - list each author separately with the same institution

**If information is missing:**
- If email is not found, omit it: - **Author Name**, Institution Name
- If institution is unclear, use what's available
- Never invent information - only use what's actually in the document

### 5. Merge Split Paragraphs

PDF extraction often splits paragraphs at page boundaries, creating awkward line breaks mid-sentence.

**Pattern to detect:**
- A line that ends WITHOUT sentence termination (no `.` `!` `?` `:`)
- Followed by a blank line
- Followed by a line that CONTINUES the sentence (starts lowercase, or continues a phrase)

**Example BEFORE:**
```
Data is written into the log in indivisible entries, rather than individual bytes. More importantly, a log

entry is the smallest unit of addressing: a reader always starts reading from a particular entry (or from the next
```

**Example AFTER:**
```
Data is written into the log in indivisible entries, rather than individual bytes. More importantly, a log entry is the smallest unit of addressing: a reader always starts reading from a particular entry (or from the next
```

**How to fix:**
- Find lines ending mid-sentence (no terminal punctuation)
- If followed by blank line + continuation text, merge them into one paragraph
- Be careful NOT to merge intentionally separate paragraphs or list items

### 6. General Cleanup

- Fix section headers not properly detected
- Remove broken/garbled text
- Fix table formatting issues
- Clean up list formatting
- Any other obvious extraction problems

## Guidelines

1. **Read the file first** - understand its structure before making changes
2. **Be conservative** - only fix clear problems, don't rewrite content
3. **Preserve meaning** - never change the academic content
4. **Work systematically** - handle figures by number (Fig 1, Fig 2, etc.)

## Output

Edit the markdown file in place. When done, briefly summarize:
- How many section headers were fixed (especially lettered sections like A., B.)
- How many figures were relocated (with their captions)
- What OCR artifacts were removed
- How the authors section was formatted
- How many split paragraphs were merged
- Any other changes made
"""


async def run_cleanup_agent(
    md_path: Path,
    img_dir: Path | None = None,
    *,
    verbose: bool = False,
) -> str | None:
    """
    Run Claude agent for open-ended markdown cleanup.

    Args:
        md_path: Path to the markdown file to clean
        img_dir: Path to the images directory (optional)
        verbose: Print agent progress (default: False)

    Returns:
        Agent's summary of changes, or None if agent failed

    Raises:
        AgentNotInstalledError: If Claude Agent SDK is not installed
    """
    try:
        from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, TextBlock
    except ImportError as e:
        raise AgentNotInstalledError() from e

    doc_dir = md_path.parent
    if img_dir is None:
        img_dir = doc_dir / "img"

    prompt = CLEANUP_PROMPT.format(
        md_path=md_path,
        img_dir=img_dir,
    )

    options = ClaudeAgentOptions(
        allowed_tools=["Read", "Edit", "Glob", "Grep"],
        permission_mode="acceptEdits",
        cwd=str(doc_dir),
    )

    final_response: list[str] = []

    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        if verbose:
                            print(block.text)
                        final_response.append(block.text)
    except Exception as e:
        if verbose:
            print(f"Agent error: {e}")
        return None

    return "\n".join(final_response) if final_response else None


def run_cleanup_agent_sync(
    md_path: Path,
    img_dir: Path | None = None,
    *,
    verbose: bool = False,
) -> str | None:
    """
    Synchronous wrapper for run_cleanup_agent.

    Args:
        md_path: Path to the markdown file to clean
        img_dir: Path to the images directory (optional)
        verbose: Print agent progress (default: False)

    Returns:
        Agent's summary of changes, or None if agent failed
    """
    return asyncio.run(run_cleanup_agent(md_path, img_dir, verbose=verbose))

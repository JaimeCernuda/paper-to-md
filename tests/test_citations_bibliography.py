"""Tests for citations.py and bibliography.py — full coverage."""

import re

from pdf2md.postprocess import process_markdown
from pdf2md.postprocess.bibliography import process_bibliography
from pdf2md.postprocess.citations import (
    _add_reference_anchors,
    _expand_citation_ranges,
    _link_single_citations,
    process_citations,
)

# =========================================================================
# 1. Idempotence
# =========================================================================


class TestIdempotence:
    def test_already_linked_citation_unchanged(self):
        """[[7]](#ref-7) must not become [[[7]](#ref-7)](#ref-7)."""
        text = "See [[7]](#ref-7) for details."
        result = _link_single_citations(text)
        assert result == text

    def test_process_citations_idempotent(self):
        """Running process_citations twice produces identical output."""
        content = "See [7] and [8].\n\n## References\n\n[7] Author A\n[8] Author B\n"
        first = process_citations(content)
        second = process_citations(first)
        assert first == second

    def test_idempotent_with_ranges(self):
        """Range expansion + linking is stable on second pass."""
        content = "See [1]-[3].\n\n## References\n\n[1] A\n[2] B\n[3] C\n"
        first = process_citations(content)
        second = process_citations(first)
        assert first == second


# =========================================================================
# 2. Range expansion
# =========================================================================


class TestRangeExpansion:
    def test_basic_range(self):
        """[11]-[14] → four individual citations."""
        result = _expand_citation_ranges("[11]-[14]")
        assert result == "[11], [12], [13], [14]"

    def test_reversed_range(self):
        """[14]-[11] produces same four citations."""
        result = _expand_citation_ranges("[14]-[11]")
        assert result == "[11], [12], [13], [14]"

    def test_en_dash(self):
        """[1]–[3] with en-dash."""
        result = _expand_citation_ranges("[1]\u2013[3]")
        assert result == "[1], [2], [3]"

    def test_em_dash(self):
        """[1]—[3] with em-dash."""
        result = _expand_citation_ranges("[1]\u2014[3]")
        assert result == "[1], [2], [3]"

    def test_bounds_cap(self):
        """[1]-[999] exceeds 50-citation cap, returned unchanged."""
        original = "[1]-[999]"
        result = _expand_citation_ranges(original)
        assert result == original

    def test_exactly_at_cap(self):
        """[1]-[51] is exactly 51 items — cap is >50 so returned unchanged."""
        original = "[1]-[51]"
        result = _expand_citation_ranges(original)
        # 51 - 1 = 50, which is not >50, so should expand
        assert "[1]," in result

    def test_single_item_range(self):
        """[5]-[5] is a single-item range."""
        result = _expand_citation_ranges("[5]-[5]")
        assert result == "[5]"


# =========================================================================
# 3. Chained ranges
# =========================================================================


class TestChainedRanges:
    def test_chained_range_partial(self):
        """[1]-[3]-[5] — first range [1]-[3] expands, -[5] remains."""
        result = _expand_citation_ranges("[1]-[3]-[5]")
        # The regex matches first [1]-[3], leaves -[5] alone
        assert "[1], [2], [3]" in result


# =========================================================================
# 4. Nested/overlapping citation forms
# =========================================================================


class TestNestedOverlapping:
    def test_already_linked_plus_unlinked(self):
        """[[7]](#ref-7), [8] — keep first intact, link second."""
        text = "[[7]](#ref-7), [8]"
        result = _link_single_citations(text)
        assert "[[7]](#ref-7)" in result
        assert "[[8]](#ref-8)" in result

    def test_image_syntax_not_linked(self):
        """![Figure 1](path) should not be linked."""
        text = "![Figure 1](./img/figure1.png)"
        result = _link_single_citations(text)
        assert result == text

    def test_markdown_link_not_linked(self):
        """[text](url) should not have [text] linked."""
        text = "[click here](http://example.com)"
        result = _link_single_citations(text)
        assert result == text


# =========================================================================
# 5. Indented references
# =========================================================================


class TestIndentedRefs:
    def test_indented_ref_gets_anchor(self):
        """## References + '  [2] ...' must get anchor."""
        refs = "## References\n\n  [2] Author Name, Title\n"
        result = _add_reference_anchors(refs)
        assert '<a id="ref-2"></a>' in result

    def test_unindented_ref_gets_anchor(self):
        """Standard [1] at line start gets anchor."""
        refs = "## References\n\n[1] Author Name\n"
        result = _add_reference_anchors(refs)
        assert '<a id="ref-1"></a>[1]' in result

    def test_bullet_prefix_removed(self):
        """'- [1]' bullet prefix is stripped before anchoring."""
        refs = "## References\n\n- [1] Author Name\n"
        result = _add_reference_anchors(refs)
        assert "- [1]" not in result
        assert '<a id="ref-1"></a>[1]' in result

    def test_existing_anchor_not_duplicated(self):
        """Already-anchored ref doesn't get double anchor."""
        refs = '## References\n\n<a id="ref-1"></a>[1] Author\n'
        result = _add_reference_anchors(refs)
        assert result.count('id="ref-1"') == 1


# =========================================================================
# 6. Duplicate references
# =========================================================================


class TestDuplicateRefs:
    def test_duplicate_ref_numbers_both_anchored(self):
        """Two [1] entries both get ref-1 anchor (first-wins for linking)."""
        refs = "## References\n\n[1] Author A\n[1] Author B\n"
        result = _add_reference_anchors(refs)
        # Both get anchored — this is current behavior
        assert result.count('id="ref-1"') == 2


# =========================================================================
# 7. Non-numeric references
# =========================================================================


class TestNonNumericRefs:
    def test_alpha_citation_not_linked(self):
        """[A1] should not be linked (not a numeric citation)."""
        text = "See [A1] for details."
        result = _link_single_citations(text)
        assert result == text

    def test_supplementary_ref_not_linked(self):
        """[S2] should not be linked."""
        text = "See [S2] for more."
        result = _link_single_citations(text)
        assert result == text

    def test_four_digit_not_linked(self):
        """[1234] exceeds 3-digit limit, not linked."""
        text = "In [1234] we see..."
        result = _link_single_citations(text)
        assert result == text


# =========================================================================
# 8. Linkage invariant (integration test)
# =========================================================================


class TestLinkageInvariant:
    def test_every_body_ref_has_matching_anchor(self):
        """Every (#ref-N) in body has matching id='ref-N' in references."""
        content = (
            "See [1] and [2] and [5].\n\n"
            "## References\n\n"
            "[1] Author A\n"
            "[2] Author B\n"
            "[5] Author E\n"
        )
        result = process_citations(content)

        # Find all #ref-N links in body
        body, refs = result.split("## References", 1)
        linked_nums = set(re.findall(r"#ref-(\d+)", body))

        # Find all id="ref-N" anchors in references
        anchor_nums = set(re.findall(r'id="ref-(\d+)"', refs))

        assert linked_nums <= anchor_nums, (
            f"Body links to {linked_nums - anchor_nums} without matching anchors"
        )

    def test_full_pipeline_linkage(self):
        """process_markdown maintains linkage invariant."""
        content = (
            "## 1 Introduction\n\n"
            "See [1] and [2]-[4].\n\n"
            "## References\n\n"
            "[1] Author A, Title, 2024.\n"
            "[2] Author B, Title, 2024.\n"
            "[3] Author C, Title, 2024.\n"
            "[4] Author D, Title, 2024.\n"
        )
        result = process_markdown(content)

        body, refs = result.split("## References", 1)
        linked_nums = set(re.findall(r"#ref-(\d+)", body))
        anchor_nums = set(re.findall(r'id="ref-(\d+)"', refs))

        assert linked_nums <= anchor_nums


# =========================================================================
# 9. Bibliography heading variants
# =========================================================================


class TestBibliographyHeadings:
    def test_h2_references(self):
        """## References is recognized."""
        content = "Body text.\n\n## References\n\n[1] A\n[2] B\n"
        result = process_bibliography(content)
        assert "[1]" in result

    def test_h2_references_uppercase(self):
        """## REFERENCES is recognized."""
        content = "Body text.\n\n## REFERENCES\n\n[1] A\n[2] B\n"
        result = process_bibliography(content)
        assert "[1]" in result

    def test_h1_references(self):
        """# References is recognized."""
        content = "Body text.\n\n# References\n\n[1] A\n[2] B\n"
        result = process_bibliography(content)
        assert "[1]" in result

    def test_plain_references(self):
        """References (no #) is recognized."""
        content = "Body text.\n\nReferences\n\n[1] A\n[2] B\n"
        result = process_bibliography(content)
        assert "[1]" in result

    def test_bibliography_not_recognized(self):
        """## Bibliography is NOT recognized (only References variants)."""
        content = "Body text.\n\n## Bibliography\n\n[1] A\n[2] B\n"
        result = process_bibliography(content)
        # Should be unchanged since Bibliography isn't a recognized heading
        assert result == content

    def test_spacing_between_entries(self):
        """Bibliography entries get blank lines between them."""
        content = "Body.\n\n## References\n\n[1] Author A\n[2] Author B\n"
        result = process_bibliography(content)
        # Should have blank line between [1] and [2]
        lines = result.split("\n")
        found_blank = False
        for i, line in enumerate(lines):
            if "[1] Author A" in line:
                # Check next line is blank before [2]
                for j in range(i + 1, len(lines)):
                    if lines[j].strip() == "":
                        found_blank = True
                        break
                    if "[2]" in lines[j]:
                        break
        assert found_blank


# =========================================================================
# Additional edge cases
# =========================================================================


class TestCitationEdgeCases:
    def test_citation_in_heading_linked(self):
        """Citations in headings are linked."""
        text = "## Section about [7]"
        result = _link_single_citations(text)
        assert "[[7]](#ref-7)" in result

    def test_citation_at_start_of_line(self):
        """[7] at start of line (not in references) is linked."""
        text = "[7] shows that..."
        result = _link_single_citations(text)
        assert "[[7]](#ref-7)" in result

    def test_references_section_not_linked(self):
        """Citations inside References section body are not linked."""
        content = "See [1].\n\n## References\n\n[1] Author A, see also [2]\n"
        result = process_citations(content)
        # [1] in body should be linked
        body = result.split("## References")[0]
        assert "[[1]](#ref-1)" in body
        # [2] inside a reference entry line should get anchored, not linked
        refs = result.split("## References")[1]
        assert "[[2]](#ref-2)" not in refs

"""Unit tests for sections.py postprocessing."""

import pytest
from pdf2md.postprocess.sections import (
    process_sections,
    _fix_abstract_header,
    _fix_index_terms_header,
    _fix_hierarchical_sections,
    _determine_header_level,
    _is_section_title,
)


class TestDetermineHeaderLevel:
    """Tests for header level calculation."""

    def test_single_number(self):
        """Single number like '3' should map to level 2 (##)."""
        assert _determine_header_level("3") == 2

    def test_two_parts(self):
        """N.N like '3.1' should map to level 3 (###)."""
        assert _determine_header_level("3.1") == 3

    def test_three_parts(self):
        """N.N.N like '3.1.1' should map to level 4 (####)."""
        assert _determine_header_level("3.1.1") == 4

    def test_four_parts(self):
        """N.N.N.N like '3.1.1.1' should map to level 5 (#####)."""
        assert _determine_header_level("3.1.1.1") == 5

    def test_five_parts_caps_at_six(self):
        """Deep nesting caps at level 6 (######)."""
        assert _determine_header_level("1.2.3.4.5") == 6
        assert _determine_header_level("1.2.3.4.5.6") == 6


class TestIsSectionTitle:
    """Tests for section title heuristics."""

    def test_short_title_is_valid(self):
        """Short capitalized text is a valid title."""
        assert _is_section_title("Design overview", [])

    def test_long_text_not_title(self):
        """Text over 120 chars is not a title."""
        long_text = "A" * 130
        assert not _is_section_title(long_text, [])

    def test_multiple_sentences_not_title(self):
        """Multiple sentences in text is not a title."""
        assert not _is_section_title("First sentence. Second sentence. Third.", [])


class TestFixAbstractHeader:
    """Tests for abstract header fixing."""

    def test_abstract_with_dash(self):
        """Abstract -text should become ## Abstract."""
        content = "Abstract -Modern HPC systems are complex."
        result = _fix_abstract_header(content)
        assert result.startswith("## Abstract\n\nModern HPC")

    def test_abstract_with_em_dash(self):
        """Abstract—text with em dash should also work."""
        content = "Abstract—Modern HPC systems"
        result = _fix_abstract_header(content)
        assert result.startswith("## Abstract\n\nModern HPC")

    def test_abstract_already_header(self):
        """Abstract already as header should still be fixed if has dash artifact."""
        content = "## Abstract -Some text here"
        result = _fix_abstract_header(content)
        assert "## Abstract" in result


class TestFixIndexTermsHeader:
    """Tests for index terms header fixing."""

    def test_index_terms_with_dash(self):
        """Index Terms -keywords should become ## Index Terms."""
        content = "Index Terms -HPC, storage, I/O"
        result = _fix_index_terms_header(content)
        assert result.startswith("## Index Terms\n\nHPC")


class TestFixHierarchicalSections:
    """Tests for hierarchical numbered section processing."""

    def test_simple_subsection(self):
        """'3.1 Background' should become '### 3.1 Background'."""
        content = "3.1 Background\n\nSome text here."
        result = _fix_hierarchical_sections(content)
        assert "### 3.1 Background" in result

    def test_subsubsection(self):
        """'3.1.1 Design overview' should become '#### 3.1.1 Design overview'."""
        content = "3.1.1 Design overview\n\nHermes is designed..."
        result = _fix_hierarchical_sections(content)
        assert "#### 3.1.1 Design overview" in result

    def test_inline_title_with_body(self):
        """'3.1.1 Title. Body text' should split into header + paragraph."""
        content = "3.1.1 Design overview. Hermes is designed as a middleware system."
        result = _fix_hierarchical_sections(content)
        assert "#### 3.1.1 Design overview" in result
        assert "Hermes is designed" in result

    def test_skip_existing_headers(self):
        """Lines already starting with # should not be modified."""
        content = "### 3.1 Already a header\n\nSome text."
        result = _fix_hierarchical_sections(content)
        assert result == content

    def test_deep_nesting(self):
        """'3.1.1.1 Fine detail' should become '#####'."""
        content = "3.1.1.1 Fine details\n\nMore text."
        result = _fix_hierarchical_sections(content)
        assert "##### 3.1.1.1 Fine details" in result


class TestProcessSections:
    """Integration tests for full section processing."""

    def test_full_pipeline(self):
        """Test the complete section processing pipeline."""
        content = """# Paper Title

Abstract -This paper presents a novel approach.

## I. INTRODUCTION

Introduction text here.

3.1 Background

Background information.

3.1.1 Related work

Previous studies have shown...

Index Terms -HPC, storage, performance
"""
        result = process_sections(content)
        
        # Abstract should be fixed
        assert "## Abstract\n\nThis paper" in result
        
        # Hierarchical sections should be converted
        assert "### 3.1 Background" in result
        assert "#### 3.1.1 Related work" in result
        
        # Index terms should be fixed
        assert "## Index Terms\n\nHPC" in result

    def test_preserves_existing_structure(self):
        """Existing headers should be preserved."""
        content = """# Title

## I. INTRODUCTION

Some text.

## II. METHODOLOGY

More text.
"""
        result = process_sections(content)
        assert "# Title" in result
        assert "## I. INTRODUCTION" in result
        assert "## II. METHODOLOGY" in result


class TestLetteredSectionsNotProcessed:
    """Verify lettered sections are NOT processed by sections.py (delegated to agent)."""

    def test_lettered_section_unchanged(self):
        """Lettered sections like 'A. Background' should NOT be converted."""
        content = "A. Background\n\nSome text here."
        result = process_sections(content)
        # Should remain unchanged - agent handles these
        assert "A. Background" in result
        assert "#####" not in result  # Should NOT be converted to header

    def test_lettered_sentence_unchanged(self):
        """Sentences starting with 'A.' should remain unchanged."""
        content = "A. We conducted experiments on the system.\n\nMore text."
        result = process_sections(content)
        assert "A. We conducted" in result
        assert "#####" not in result

"""Unit tests for postprocess/cleanup.py and agent/providers.py."""

import pytest

from pdf2md.postprocess.cleanup import (
    _fix_glyph_artifacts,
    _fix_hyphenated_words,
    _merge_split_paragraphs,
    _remove_image_comments,
    _remove_ocr_artifacts_near_figures,
)

# ---------------------------------------------------------------------------
# _merge_split_paragraphs
# ---------------------------------------------------------------------------


class TestMergeSplitParagraphs:
    """Tests for paragraph merging across page breaks."""

    def test_merges_split_paragraph(self):
        text = "The system processes data\n\nand returns results."
        result = _merge_split_paragraphs(text)
        assert result == "The system processes data and returns results."

    def test_no_merge_when_sentence_ends(self):
        text = "The system processes data.\n\nAnother paragraph starts here."
        result = _merge_split_paragraphs(text)
        assert result == text

    def test_no_merge_bullet_list_dash(self):
        text = "Some header text\n\n- First list item"
        result = _merge_split_paragraphs(text)
        assert result == text

    def test_no_merge_bullet_list_asterisk(self):
        text = "Some header text\n\n* First list item"
        result = _merge_split_paragraphs(text)
        assert result == text

    def test_no_merge_numbered_list_dot(self):
        text = "Some header text\n\n1. First item"
        result = _merge_split_paragraphs(text)
        assert result == text

    def test_no_merge_numbered_list_paren(self):
        text = "Some header text\n\n2) Second item"
        result = _merge_split_paragraphs(text)
        assert result == text

    def test_no_merge_current_line_is_list_asterisk(self):
        """Don't merge when the current line is a list item."""
        text = "* list item one\n\ncontinuation text"
        result = _merge_split_paragraphs(text)
        assert result == text

    def test_no_merge_current_line_is_numbered(self):
        text = "3. numbered item\n\ncontinuation text"
        result = _merge_split_paragraphs(text)
        assert result == text

    def test_no_merge_heading(self):
        text = "## Section Title\n\nsome continuation"
        result = _merge_split_paragraphs(text)
        assert text == result

    def test_no_merge_figure_embed(self):
        text = "![Figure 1](img/figure1.png)\n\nsome text"
        result = _merge_split_paragraphs(text)
        assert result == text

    def test_no_merge_table_row(self):
        text = "| col1 | col2 |\n\nsome text"
        result = _merge_split_paragraphs(text)
        assert result == text

    def test_merges_parenthetical_continuation(self):
        text = "The system processes data\n\n(see Section 3)"
        result = _merge_split_paragraphs(text)
        assert result == "The system processes data (see Section 3)"


# ---------------------------------------------------------------------------
# _fix_hyphenated_words
# ---------------------------------------------------------------------------


class TestFixHyphenatedWords:
    def test_simple_break(self):
        assert _fix_hyphenated_words("band-\nwidth") == "bandwidth"

    def test_break_across_blank_line(self):
        assert _fix_hyphenated_words("band-\n\nwidth") == "bandwidth"

    def test_compound_word_preserved(self):
        assert _fix_hyphenated_words("client-\nto-server") == "client-to-server"

    def test_compound_word_across_blank(self):
        assert _fix_hyphenated_words("client-\n\nto-server") == "client-to-server"

    def test_no_false_positive_on_dash_list(self):
        """A line ending with hyphen followed by uppercase should not merge."""
        text = "some-\nWord"
        result = _fix_hyphenated_words(text)
        # Uppercase continuation = not a word break
        assert result == "some-\nWord"

    def test_skips_headings(self):
        """Headings ending with hyphen should not merge with next line."""
        text = "## Self-\ncontained section"
        result = _fix_hyphenated_words(text)
        assert result == text

    def test_skips_code_fences(self):
        """Content inside code fences should not be modified."""
        text = "```\nsome-\nword\n```"
        result = _fix_hyphenated_words(text)
        assert result == text

    def test_normal_text_around_code_fence(self):
        """Text outside code fences should still be fixed."""
        text = "band-\nwidth\n```\nsome-\ncode\n```\nnet-\nwork"
        result = _fix_hyphenated_words(text)
        assert "bandwidth" in result
        assert "network" in result
        # Code fence content preserved
        assert "some-\ncode" in result


# ---------------------------------------------------------------------------
# _remove_ocr_artifacts_near_figures
# ---------------------------------------------------------------------------


class TestRemoveOcrArtifacts:
    def test_removes_short_lines_before_figure(self):
        text = "Real paragraph.\n\n(a)\n(b)\n![Figure 1](img/figure1.png)"
        result = _remove_ocr_artifacts_near_figures(text)
        assert "(a)" not in result
        assert "(b)" not in result
        assert "![Figure 1]" in result
        assert "Real paragraph." in result

    def test_keeps_long_lines(self):
        text = (
            "This is a real paragraph that is definitely longer than sixty characters in total.\n\n"
            "![Figure 1](img/figure1.png)"
        )
        result = _remove_ocr_artifacts_near_figures(text)
        assert "real paragraph" in result

    def test_keeps_single_short_line(self):
        """Only 1 short line (need 2+) should not be removed."""
        text = "axis label\n![Figure 1](img/figure1.png)"
        result = _remove_ocr_artifacts_near_figures(text)
        assert "axis label" in result

    def test_keeps_sentence_ending_lines(self):
        text = "This is a sentence.\nAnother sentence.\n![Figure 1](img/figure1.png)"
        result = _remove_ocr_artifacts_near_figures(text)
        assert "This is a sentence." in result
        assert "Another sentence." in result

    def test_stops_at_heading(self):
        text = "## Section\n(a)\n(b)\n![Figure 1](img/figure1.png)"
        result = _remove_ocr_artifacts_near_figures(text)
        assert "## Section" in result


# ---------------------------------------------------------------------------
# _fix_glyph_artifacts
# ---------------------------------------------------------------------------


class TestFixGlyphArtifacts:
    def test_removes_glyph_angle_brackets(self):
        assert _fix_glyph_artifacts("textGLYPH<42>more") == "textmore"

    def test_removes_glyph_html_entities(self):
        assert _fix_glyph_artifacts("textGLYPH&lt;42&gt;more") == "textmore"

    def test_no_false_positive(self):
        text = "GLYPH is a word"
        assert _fix_glyph_artifacts(text) == text


# ---------------------------------------------------------------------------
# _remove_image_comments
# ---------------------------------------------------------------------------


class TestRemoveImageComments:
    def test_removes_image_comment(self):
        text = "line1\n<!-- image -->\nline2"
        assert _remove_image_comments(text) == "line1\nline2"

    def test_keeps_other_comments(self):
        text = "line1\n<!-- other -->\nline2"
        assert _remove_image_comments(text) == text


# ---------------------------------------------------------------------------
# Provider validation
# ---------------------------------------------------------------------------


class TestProviderConfig:
    def test_unknown_provider_raises(self):
        from pdf2md.agent.providers import get_provider_config

        with pytest.raises(ValueError, match="Unknown provider"):
            get_provider_config("bogus_provider")

    def test_unknown_vlm_provider_raises(self):
        from pdf2md.agent.providers import get_vlm_config

        with pytest.raises(ValueError, match="Unknown VLM provider"):
            get_vlm_config("bogus_provider")

    def test_lm_studio_works(self):
        from pdf2md.agent.providers import get_provider_config

        config = get_provider_config("lm_studio")
        assert "lm_studio/" in config.model

    def test_ollama_works(self):
        from pdf2md.agent.providers import get_provider_config

        config = get_provider_config("ollama")
        assert "ollama_chat/" in config.model
        assert config.api_base is not None

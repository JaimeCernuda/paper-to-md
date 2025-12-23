"""Unit tests for figures.py postprocessing."""

import pytest
from pdf2md.postprocess.figures import (
    process_figures,
    _build_figure_map,
    _embed_figures_at_captions,
    find_unembedded_figures,
)


class TestBuildFigureMap:
    """Tests for figure filename to number mapping."""

    def test_standard_naming(self):
        """figure1.png, figure2.png should map correctly."""
        files = ["figure1.png", "figure2.png", "figure3.png"]
        result = _build_figure_map(files)
        assert result == {1: "figure1.png", 2: "figure2.png", 3: "figure3.png"}

    def test_fig_prefix(self):
        """fig1.png naming should also work."""
        files = ["fig1.png", "fig2.png"]
        result = _build_figure_map(files)
        assert result == {1: "fig1.png", 2: "fig2.png"}

    def test_underscore_naming(self):
        """figure_1.png with underscore should work."""
        files = ["figure_1.png", "figure_2.png"]
        result = _build_figure_map(files)
        assert result == {1: "figure_1.png", 2: "figure_2.png"}

    def test_mixed_case(self):
        """Figure1.png with capital F should work."""
        files = ["Figure1.png", "Figure2.png"]
        result = _build_figure_map(files)
        assert result == {1: "Figure1.png", 2: "Figure2.png"}

    def test_empty_list(self):
        """Empty file list returns empty map."""
        assert _build_figure_map([]) == {}

    def test_non_figure_files_ignored(self):
        """Files without figure pattern are ignored."""
        files = ["logo.png", "header.png", "figure1.png"]
        result = _build_figure_map(files)
        assert result == {1: "figure1.png"}


class TestEmbedFiguresAtCaptions:
    """Tests for figure embedding at captions."""

    def test_basic_embedding(self):
        """Figure should be embedded above its caption."""
        content = "Some text.\n\nFig. 1. A sample figure caption.\n\nMore text."
        figure_map = {1: "figure1.png"}
        result = _embed_figures_at_captions(content, figure_map)
        
        assert "![Figure 1](./img/figure1.png)" in result
        # Image should come before caption
        img_pos = result.find("![Figure 1]")
        caption_pos = result.find("Fig. 1.")
        assert img_pos < caption_pos

    def test_figure_word_caption(self):
        """'Figure 1.' style caption should also work."""
        content = "Text.\n\nFigure 1. Caption here.\n\nMore."
        figure_map = {1: "figure1.png"}
        result = _embed_figures_at_captions(content, figure_map)
        assert "![Figure 1](./img/figure1.png)" in result

    def test_no_duplicate_embedding(self):
        """Same figure referenced twice should only be embedded once."""
        content = "Fig. 1. First mention.\n\nFig. 1 appears again.\n\nMore."
        figure_map = {1: "figure1.png"}
        result = _embed_figures_at_captions(content, figure_map)
        assert result.count("![Figure 1]") == 1

    def test_multiple_figures(self):
        """Multiple different figures should each be embedded."""
        content = "Fig. 1. First figure.\n\nFig. 2. Second figure.\n\nText."
        figure_map = {1: "figure1.png", 2: "figure2.png"}
        result = _embed_figures_at_captions(content, figure_map)
        assert "![Figure 1]" in result
        assert "![Figure 2]" in result

    def test_missing_figure_not_embedded(self):
        """Caption without matching image file should not add embed."""
        content = "Fig. 5. A figure we don't have.\n\nText."
        figure_map = {1: "figure1.png"}  # No figure 5
        result = _embed_figures_at_captions(content, figure_map)
        assert "![Figure 5]" not in result


class TestProcessFigures:
    """Integration tests for figure processing."""

    def test_empty_image_list(self):
        """No images should return content unchanged."""
        content = "Some text.\n\nFig. 1. Caption.\n\nMore."
        result = process_figures(content, [])
        assert result == content

    def test_full_processing(self):
        """Complete figure processing pipeline."""
        content = """# Introduction

Some introductory text.

## Methods

Fig. 1. Overview of our system architecture.

More methodology text here.

Fig. 2. Results comparison chart.

Conclusion text.
"""
        image_files = ["figure1.png", "figure2.png"]
        result = process_figures(content, image_files)
        
        assert "![Figure 1](./img/figure1.png)" in result
        assert "![Figure 2](./img/figure2.png)" in result


class TestFindUnembeddedFigures:
    """Tests for finding figures that weren't embedded."""

    def test_all_embedded(self):
        """No unembedded figures when all are referenced."""
        content = "![Figure 1](./img/figure1.png)\n\n![Figure 2](./img/figure2.png)"
        files = ["figure1.png", "figure2.png"]
        result = find_unembedded_figures(content, files)
        assert result == []

    def test_some_unembedded(self):
        """Should return figures not embedded in content."""
        content = "![Figure 1](./img/figure1.png)"
        files = ["figure1.png", "figure2.png", "figure3.png"]
        result = find_unembedded_figures(content, files)
        assert "figure2.png" in result
        assert "figure3.png" in result
        assert "figure1.png" not in result

    def test_no_embeddings(self):
        """All figures unembedded if content has no embeds."""
        content = "Just some text, no figures embedded."
        files = ["figure1.png", "figure2.png"]
        result = find_unembedded_figures(content, files)
        assert len(result) == 2


class TestNoDeadCode:
    """Verify dead code was removed from figures.py."""

    def test_no_filter_logo_images_function(self):
        """filter_logo_images should not exist in module."""
        from pdf2md.postprocess import figures
        assert not hasattr(figures, 'filter_logo_images')

    def test_no_renumber_figures_function(self):
        """renumber_figures_after_filtering should not exist in module."""
        from pdf2md.postprocess import figures
        assert not hasattr(figures, 'renumber_figures_after_filtering')

    def test_no_min_image_constants(self):
        """MIN_IMAGE_WIDTH etc constants should not exist in module."""
        from pdf2md.postprocess import figures
        assert not hasattr(figures, 'MIN_IMAGE_WIDTH')
        assert not hasattr(figures, 'MIN_IMAGE_HEIGHT')
        assert not hasattr(figures, 'MIN_IMAGE_AREA')

from __future__ import annotations

"""
Integration tests that run against real PDF files in data/raw/.

These tests require the PDF files to be present; individual tests are skipped
if their PDF is missing. Run the full suite with:

    uv run pytest tests/test_integration.py -v

OCR tests (chaos_again) are slower — they invoke Tesseract on every page.
"""

import yaml
import pytest
import fitz
from pathlib import Path

from ttrpg_ocr.schemas import BookProfile
from ttrpg_ocr.classify import classify_pages, PageStrategy
from ttrpg_ocr.extract_chapters import (
    _assign_columns,
    _detect_column_count,
    _detect_font_tiers,
    _page_spans,
    extract_chapters,
)

RAW = Path(__file__).parents[1] / "data" / "raw"
BATCH = RAW / "batch_01"
CONFIG = Path(__file__).parents[1] / "config"


# ── fixtures ──────────────────────────────────────────────────────────────────

def _pdf(path: Path):
    if not path.exists():
        pytest.skip(f"PDF not found: {path}")
    return path


def _profile(name: str) -> BookProfile:
    return BookProfile(**yaml.safe_load((CONFIG / f"{name}.yaml").open()))


@pytest.fixture
def bitd_pdf():
    return _pdf(RAW / "blades_in_the_dark.pdf")


@pytest.fixture
def bitd_profile():
    return _profile("blades_in_the_dark")


@pytest.fixture
def forest_pdf():
    return _pdf(RAW / "forest_of_hate.pdf")


@pytest.fixture
def forest_profile():
    return _profile("forest_of_hate")


@pytest.fixture
def all_at_sea_pdf():
    return _pdf(BATCH / "all_at_sea.pdf")


@pytest.fixture
def all_at_sea_profile():
    return _profile("all_at_sea")


@pytest.fixture
def chaos_again_pdf():
    return _pdf(BATCH / "chaos_again.pdf")


@pytest.fixture
def chaos_again_profile():
    return _profile("chaos_again")


# ── classify_pages ────────────────────────────────────────────────────────────

class TestClassifyPages:
    def test_all_at_sea_native_pages(self, all_at_sea_pdf, all_at_sea_profile):
        """11-page native PDF: 10 native + 1 explicit drop (page 10)."""
        decisions = classify_pages(all_at_sea_pdf, all_at_sea_profile)
        native = [d for d in decisions if d.strategy == PageStrategy.NATIVE_TEXT]
        skipped = [d for d in decisions if d.strategy == PageStrategy.SKIP]
        assert len(native) == 10
        assert len(skipped) == 1
        assert skipped[0].page_num == 10
        assert all(d.text_chars >= 500 for d in native)

    def test_chaos_again_all_ocr(self, chaos_again_pdf, chaos_again_profile):
        """9-page scan: enable_ocr=True, 0 native chars → all pages SCAN_OCR."""
        decisions = classify_pages(chaos_again_pdf, chaos_again_profile)
        assert len(decisions) == 9
        assert all(d.strategy == PageStrategy.SCAN_OCR for d in decisions)
        assert all(d.text_chars == 0 for d in decisions)

    def test_blades_drop_pages(self, bitd_pdf, bitd_profile):
        """BitD pages 0-8 are in drop_pages → all SKIP."""
        decisions = classify_pages(bitd_pdf, bitd_profile)
        for d in decisions:
            if d.page_num in bitd_profile.drop_pages:
                assert d.strategy == PageStrategy.SKIP, (
                    f"page {d.page_num} should be SKIP"
                )

    def test_blades_native_text_pages(self, bitd_pdf, bitd_profile):
        """Spot-check a few known BitD content pages (10, 50, 100) are NATIVE_TEXT."""
        decisions = classify_pages(bitd_pdf, bitd_profile)
        by_page = {d.page_num: d for d in decisions}
        for pn in [10, 50, 100, 200]:
            assert by_page[pn].strategy == PageStrategy.NATIVE_TEXT, (
                f"page {pn} expected NATIVE_TEXT, got {by_page[pn].strategy}"
            )


# ── column ordering on a known two-column page ────────────────────────────────

class TestColumnOrdering:
    """
    BitD page 265 is a district detail page with a clear two-column layout:
    left column (xc ~85-170): district description and notables
    right column (xc ~306-350): trait ratings (Wealth, Security, etc.)

    In raw content-stream order the right-column blocks come first.
    After the fix they must all follow the left-column blocks.
    """

    PAGE = 265

    def _blocks(self, pdf_path: Path, profile: BookProfile):
        with fitz.open(pdf_path) as doc:
            page = doc[self.PAGE]
            h = page.rect.height
            header_y = h * profile.header_height_pct
            footer_y = h * (1 - profile.footer_height_pct)
            blocks = [
                b for b in page.get_text("dict")["blocks"]
                if b.get("type") == 0
                and b["bbox"][1] >= header_y
                and b["bbox"][3] <= footer_y
            ]
            return page.rect.width, blocks

    def test_detects_two_columns(self, bitd_pdf, bitd_profile):
        w, blocks = self._blocks(bitd_pdf, bitd_profile)
        x_centers = [(b["bbox"][0] + b["bbox"][2]) / 2 for b in blocks]
        n_cols = _detect_column_count(
            x_centers, w,
            bitd_profile.column_count_max,
            bitd_profile.column_gap_min_pct,
        )
        assert n_cols == 2, f"expected 2 columns on page {self.PAGE}, got {n_cols}"

    def test_col0_before_col1_in_sorted_order(self, bitd_pdf, bitd_profile):
        """After sort, no col-1 block precedes a col-0 block."""
        w, blocks = self._blocks(bitd_pdf, bitd_profile)
        x_centers = [(b["bbox"][0] + b["bbox"][2]) / 2 for b in blocks]
        n_cols = _detect_column_count(
            x_centers, w,
            bitd_profile.column_count_max,
            bitd_profile.column_gap_min_pct,
        )
        col_indices = _assign_columns(x_centers, n_cols)
        order = sorted(range(len(blocks)),
                       key=lambda i: (col_indices[i], blocks[i]["bbox"][1]))
        sorted_cols = [col_indices[i] for i in order]

        col0_last = max((i for i, c in enumerate(sorted_cols) if c == 0), default=-1)
        col1_first = min((i for i, c in enumerate(sorted_cols) if c == 1),
                         default=len(sorted_cols))
        assert col0_last < col1_first, (
            f"col-0 ends at position {col0_last}, col-1 starts at {col1_first}"
        )

    def test_spans_left_column_before_right(self, bitd_pdf, bitd_profile):
        """
        In _page_spans output, 'notables' (left col) must appear before
        'Wealth' (right col). Without the fix, Wealth comes first in
        content-stream order.
        """
        with fitz.open(bitd_pdf) as doc:
            _, tiers = _detect_font_tiers(doc, [self.PAGE])
            spans = _page_spans(doc[self.PAGE], bitd_profile, tiers)

        texts = [text for _, text, _ in spans]

        notables_idx = next(
            (i for i, t in enumerate(texts) if "notables" in t.lower()), None
        )
        wealth_idx = next(
            (i for i, t in enumerate(texts) if "Wealth" in t), None
        )

        assert notables_idx is not None, f"'notables' not found in spans: {texts[:10]}"
        assert wealth_idx is not None, f"'Wealth' not found in spans: {texts[:10]}"
        assert notables_idx < wealth_idx, (
            f"'notables' (idx={notables_idx}) must precede 'Wealth' (idx={wealth_idx})"
        )

    def test_content_stream_order_was_wrong(self, bitd_pdf, bitd_profile):
        """
        Regression: verify that raw content-stream order on page 265 does NOT
        already have left-col text before right-col. This confirms the fix is
        actually needed and doing work.
        """
        with fitz.open(bitd_pdf) as doc:
            page = doc[self.PAGE]
            h = page.rect.height
            header_y = h * bitd_profile.header_height_pct
            footer_y = h * (1 - bitd_profile.footer_height_pct)
            blocks = [
                b for b in page.get_text("dict")["blocks"]
                if b.get("type") == 0
                and b["bbox"][1] >= header_y
                and b["bbox"][3] <= footer_y
            ]

        w = 432.0  # known page width for BitD
        x_centers = [(b["bbox"][0] + b["bbox"][2]) / 2 for b in blocks]
        # Boundary between columns is around x=238 (midpoint of the large gap)
        # In raw stream order, the FIRST block should be from the right column
        first_xc = x_centers[0]
        assert first_xc > w / 2, (
            f"Expected raw stream to start with a right-col block (xc > {w/2:.0f}), "
            f"got xc={first_xc:.0f}. The fix may be unnecessary for this page."
        )


# ── chapter extraction ────────────────────────────────────────────────────────

class TestExtractChapters:
    def test_forest_of_hate_six_chapters(self, forest_pdf, forest_profile):
        """forest_of_hate.yaml defines 6 chapters; extraction must produce exactly 6."""
        decisions = classify_pages(forest_pdf, forest_profile)
        book = extract_chapters(forest_pdf, decisions, forest_profile)

        assert book.profile_name == forest_profile.name
        assert len(book.chapters) == 6
        assert book.chapters[0].title == "Forest of Hate"
        assert book.chapters[-1].title == "Appendix"

    def test_forest_chapters_have_text(self, forest_pdf, forest_profile):
        """Every section must have non-empty text and at least one span."""
        decisions = classify_pages(forest_pdf, forest_profile)
        book = extract_chapters(forest_pdf, decisions, forest_profile)

        for ch in book.chapters:
            for sec in ch.sections:
                assert sec.text, f"empty text in {ch.title!r} → {sec.title!r}"
                assert sec.spans, f"empty spans in {ch.title!r} → {sec.title!r}"
                assert all(sp.page_num >= 0 for sp in sec.spans)

    def test_spans_page_nums_in_chapter_range(self, forest_pdf, forest_profile):
        """All span page numbers must fall within the chapter's page range."""
        decisions = classify_pages(forest_pdf, forest_profile)
        book = extract_chapters(forest_pdf, decisions, forest_profile)

        markers = sorted(forest_profile.chapters, key=lambda c: c.page)
        for i, ch in enumerate(book.chapters):
            end = markers[i + 1].page if i + 1 < len(markers) else 9999
            for sec in ch.sections:
                for sp in sec.spans:
                    assert markers[i].page <= sp.page_num < end, (
                        f"{ch.title!r}: span page {sp.page_num} outside "
                        f"[{markers[i].page}, {end})"
                    )

    def test_all_at_sea_chapter_structure(self, all_at_sea_pdf, all_at_sea_profile):
        """all_at_sea has no manual chapters; auto mode must yield at least one chapter."""
        decisions = classify_pages(all_at_sea_pdf, all_at_sea_profile)
        book = extract_chapters(all_at_sea_pdf, decisions, all_at_sea_profile)

        assert len(book.chapters) >= 1
        total_sections = sum(len(ch.sections) for ch in book.chapters)
        assert total_sections >= 1

    def test_spans_text_field_is_joined_spans(self, forest_pdf, forest_profile):
        """SectionEntry.text must equal the joined body of its spans (backwards compat)."""
        decisions = classify_pages(forest_pdf, forest_profile)
        book = extract_chapters(forest_pdf, decisions, forest_profile)

        for ch in book.chapters:
            for sec in ch.sections:
                joined = " ".join(sp.text for sp in sec.spans).strip()
                assert sec.text == joined, (
                    f"{ch.title!r} → {sec.title!r}: text field doesn't match joined spans"
                )

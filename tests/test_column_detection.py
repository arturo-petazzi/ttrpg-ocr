from __future__ import annotations

import pytest
from ttrpg_ocr.extract_chapters import _assign_columns, _clean_native_text, _detect_column_count


class TestDetectColumnCount:
    def test_two_column_normal(self):
        # Two clusters at ~100 and ~300 on a 400pt-wide page; gap ~200pt >> 32pt threshold
        x = [90.0, 100.0, 110.0, 120.0, 280.0, 290.0, 300.0, 310.0]
        assert _detect_column_count(x, 400.0, 3, 0.08) == 2

    def test_single_column_no_gap(self):
        # All x-centers within ~50pts; no gap exceeds 8% of 400pt = 32pt
        x = [100.0, 110.0, 120.0, 130.0, 140.0, 150.0]
        assert _detect_column_count(x, 400.0, 3, 0.08) == 1

    def test_three_column_uncapped(self):
        # Three clusters with large inter-cluster gaps
        x = [50.0, 60.0, 200.0, 210.0, 350.0, 360.0]
        assert _detect_column_count(x, 400.0, 3, 0.08) == 3

    def test_three_column_capped_at_two(self):
        # Same three clusters but max_cols=2 caps the result
        x = [50.0, 60.0, 200.0, 210.0, 350.0, 360.0]
        assert _detect_column_count(x, 400.0, 2, 0.08) == 2

    def test_too_few_blocks_returns_one(self):
        # Fewer than 4 blocks — always falls back to single column
        assert _detect_column_count([100.0, 200.0, 300.0], 400.0, 3, 0.08) == 1
        assert _detect_column_count([100.0, 200.0], 400.0, 3, 0.08) == 1
        assert _detect_column_count([], 400.0, 3, 0.08) == 1

    def test_gap_exactly_at_threshold_counts(self):
        # Gap of exactly min_gap (32pt for 8% of 400) should count
        x = [100.0, 110.0, 120.0, 152.0]  # gap 152-120=32 == threshold
        assert _detect_column_count(x, 400.0, 3, 0.08) == 2

    def test_gap_just_below_threshold_ignored(self):
        # Gap of 31pt < 32pt threshold — stays single column
        x = [100.0, 110.0, 120.0, 151.0]  # gap 31pt
        assert _detect_column_count(x, 400.0, 3, 0.08) == 1

    def test_left_shifted_two_column(self):
        # Both columns in the left portion of a wide page (CLAUDE.md page-14 regression).
        # x_centers at ~100 and ~250 on a 600pt page; gap ~150pt >> 48pt threshold.
        x = [90.0, 100.0, 110.0, 240.0, 250.0, 260.0]
        assert _detect_column_count(x, 600.0, 2, 0.08) == 2

    def test_single_column_max_cols_one(self):
        # max_cols=1 forces single column regardless of gaps
        x = [50.0, 60.0, 200.0, 210.0, 350.0, 360.0]
        assert _detect_column_count(x, 400.0, 1, 0.08) == 1


class TestAssignColumns:
    def test_single_column_all_zero(self):
        assert _assign_columns([100.0, 150.0, 200.0, 250.0], 1) == [0, 0, 0, 0]

    def test_two_column_clear_split(self):
        # x < 200 → col 0; x >= 200 → col 1  (boundary = midpoint of gap 100→300 = 200)
        x = [80.0, 100.0, 300.0, 320.0]
        assert _assign_columns(x, 2) == [0, 0, 1, 1]

    def test_two_column_preserves_input_order(self):
        # Input not sorted — output indices must correspond to input positions
        x = [300.0, 100.0, 80.0, 320.0]
        cols = _assign_columns(x, 2)
        assert cols == [1, 0, 0, 1]

    def test_three_columns(self):
        # Three clusters: 50, 200, 350 — boundaries at 125 and 275
        x = [50.0, 200.0, 350.0]
        assert _assign_columns(x, 3) == [0, 1, 2]

    def test_three_columns_mixed_order(self):
        x = [350.0, 50.0, 200.0]
        assert _assign_columns(x, 3) == [2, 0, 1]

    def test_single_element_per_column(self):
        # Degenerate: one block in each of two very distinct positions
        x = [10.0, 390.0, 10.0, 390.0]  # two left, two right — need 4 for detection
        assert _assign_columns(x, 2) == [0, 1, 0, 1]

    def test_output_length_matches_input(self):
        x = [1.0, 2.0, 3.0, 400.0, 401.0, 402.0]
        cols = _assign_columns(x, 2)
        assert len(cols) == len(x)


class TestCleanNativeText:
    def test_c1_bullet_replaced(self):
        assert _clean_native_text('\x90 A player or GM') == '• A player or GM'

    def test_multiple_c1_bullets(self):
        assert _clean_native_text('\x90 \x90 Keep this book') == '• • Keep this book'

    def test_solo_c1_becomes_bullet(self):
        # The caller filters this out; function itself just maps it
        assert _clean_native_text('\x90') == '•'

    def test_pua_prefix_stripped(self):
        # Wingdings-Regular filled-dot rating glyphs before action name
        assert _clean_native_text('hunt') == 'hunt'

    def test_soft_hyphen_removed(self):
        assert _clean_native_text('unwanted\xad—') == 'unwanted—'

    def test_clean_text_unchanged(self):
        s = 'Blades in the Dark is a game about scoundrels.'
        assert _clean_native_text(s) == s

    def test_whitespace_collapsed(self):
        assert _clean_native_text('hello   world') == 'hello world'

    def test_strips_leading_trailing_space(self):
        assert _clean_native_text('  hello  ') == 'hello'

from __future__ import annotations

import pytest

from hqa import holdout


def test_holdout_days_is_183():
    assert holdout.HOLDOUT_DAYS == 183


def test_final_returns_full_end_and_empty_note():
    end, note = holdout.effective_backtest_end("2020-01-02", "2026-06-30", final=True)
    assert end == "2026-06-30"
    assert note == ""


def test_non_final_cuts_183_days_and_returns_note():
    end, note = holdout.effective_backtest_end("2020-01-02", "2026-06-30", final=False)
    assert end == "2025-12-29"
    assert note == "HOLDOUT: last 183 days reserved; run --final ONCE before promotion (D-21)"


def test_window_too_short_raises():
    # cut end (2025-12-29) falls before start -> not enough room for the holdout.
    with pytest.raises(ValueError):
        holdout.effective_backtest_end("2026-01-01", "2026-06-30", final=False)


def test_cut_end_equal_to_start_raises():
    # cut end == start must also raise (cut end <= start).
    with pytest.raises(ValueError):
        holdout.effective_backtest_end("2025-12-29", "2026-06-30", final=False)


def test_cut_end_just_after_start_is_valid():
    end, note = holdout.effective_backtest_end("2025-12-28", "2026-06-30", final=False)
    assert end == "2025-12-29"
    assert note

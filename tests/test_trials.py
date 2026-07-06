from __future__ import annotations

from hqa.trials import append_trial, count_trials, overfit_warning


def _record(final: bool = False) -> dict:
    return {
        "ts": "2026-07-06T09:00:00",
        "start": "2020-01-02",
        "end": "2026-06-30",
        "final": final,
        "sharpe": 1.2,
    }


def test_append_and_count_round_trip(tmp_path):
    log = tmp_path / "factor_trials.jsonl"
    append_trial("mom_12m", _record(), log)
    append_trial("mom_12m", _record(final=True), log)
    append_trial("other", _record(), log)
    assert count_trials("mom_12m", log) == 2
    assert count_trials("other", log) == 1


def test_count_missing_log_is_zero(tmp_path):
    assert count_trials("mom_12m", tmp_path / "missing.jsonl") == 0


def test_warning_empty_below_threshold():
    assert overfit_warning("mom_12m", 2) == ""


def test_warning_at_threshold():
    msg = overfit_warning("mom_12m", 3)
    assert msg == (
        "OVERFIT WARNING: trial 3 for mom_12m — 回测结果可信度随迭代次数下降；"
        "参考 D-21/复盘库，考虑 holdout --final 或收手"
    )

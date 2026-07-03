from __future__ import annotations

import json

from hqa import signals

FACTOR_LAB = "cache_status=recomputed cache_path=x universe=etf symbol=QQQ benchmark=QQQ cross_rows=5 timing_rows=5"

CAND_HI = {"ticker": "NVDA", "strategy": "sell_put", "global_score": 91.5, "iv_rank": 0.88, "run_date": "2026-07-01"}
CAND_LO = {"ticker": "KO", "strategy": "covered_call", "global_score": 40.0, "iv_rank": 0.2, "run_date": "2026-07-01"}
CAND_NULL_IV = {"ticker": "XYZ", "strategy": "sell_put", "global_score": 95.0, "iv_rank": None, "run_date": "2026-07-01"}


def test_load_scan_candidates_reads_jsonl(tmp_path):
    (tmp_path / "2026-07-01.jsonl").write_text(
        json.dumps(CAND_HI) + "\n" + json.dumps(CAND_LO) + "\n", encoding="utf-8"
    )
    cands = signals.load_scan_candidates(tmp_path, "2026-07-01")
    assert [c["ticker"] for c in cands] == ["NVDA", "KO"]
    assert signals.load_scan_candidates(tmp_path, "2026-06-30") == []


def test_parse_factor_lab():
    lab = signals.parse_factor_lab(FACTOR_LAB)
    assert lab == {"symbol": "QQQ", "cross_rows": "5", "timing_rows": "5"}


def test_evaluate_signals_collect_mode_never_fires():
    has_signal, sigs = signals.evaluate_signals([CAND_HI, CAND_NULL_IV])  # no thresholds (D-15)
    assert has_signal is False
    assert sigs == []


def test_evaluate_signals_thresholds_fire_and_require_iv():
    has_signal, sigs = signals.evaluate_signals(
        [CAND_HI, CAND_LO, CAND_NULL_IV], min_score=90.0, min_iv_rank=0.8
    )
    assert has_signal is True
    assert len(sigs) == 1  # null iv_rank excluded when min_iv_rank is set
    assert "NVDA" in sigs[0] and "sell_put" in sigs[0] and "91.5" in sigs[0]


def test_summarize_scores_distribution():
    s = signals.summarize_scores([CAND_HI, CAND_LO, CAND_NULL_IV])
    assert s["count"] == 3
    assert s["score_max"] == 95.0
    assert s["score_p50"] == 91.5
    assert s["iv_rank_known"] == 2

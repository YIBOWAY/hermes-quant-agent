from __future__ import annotations

import json

import pytest

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


@pytest.mark.parametrize(
    "contents",
    [
        '{"ticker":"AAPL","ticker":"MSFT"}\n',
        '{"ticker":"AAPL","global_score":NaN}\n',
        '{"ticker":"AAPL"}\n\n',
        '{"ticker":"AAPL"}',
    ],
)
def test_load_scan_candidates_rejects_corrupt_jsonl(contents, tmp_path):
    (tmp_path / "2026-07-01.jsonl").write_text(contents, encoding="utf-8")

    with pytest.raises(ValueError):
        signals.load_scan_candidates(tmp_path, "2026-07-01")


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


def test_structured_signal_identity_distinguishes_contracts_and_ignores_observation_time():
    first = {
        "ticker": "AAPL",
        "strategy": "covered_call",
        "global_score": 175.9234,
        "iv_rank": 78.12,
        "run_date": "2026-07-10",
        "candidate": {
            "symbol": "US.AAPL260731C315000",
            "underlying": "US.AAPL",
        },
    }
    second = {
        **first,
        "global_score": 163.4211,
        "candidate": {
            "symbol": "US.AAPL260807C315000",
            "underlying": "US.AAPL",
        },
    }

    initial = signals.build_signal_records(
        [first, second],
        min_score=150.0,
        min_iv_rank=None,
        source_date="2026-07-10",
        observed_at="2026-07-10T18:00:39Z",
    )
    repeated = signals.build_signal_records(
        [first, second],
        min_score=150.0,
        min_iv_rank=None,
        source_date="2026-07-10",
        observed_at="2026-07-10T20:39:49Z",
    )

    assert len(initial) == 2
    assert initial[0]["signal_id"] != initial[1]["signal_id"]
    assert [record["signal_id"] for record in initial] == [
        record["signal_id"] for record in repeated
    ]
    assert initial[0]["instrument"]["contract_symbol"] == "US.AAPL260731C315000"
    assert initial[0]["source"]["row_sha256"] != initial[1]["source"]["row_sha256"]
    assert initial[0]["eligibility"] == {
        "status": "not_actionable",
        "route": None,
        "reason_code": "paper_options_route_unavailable",
        "deadline_at": None,
    }


def test_structured_signal_with_missing_contract_identity_is_unknown():
    records = signals.build_signal_records(
        [CAND_HI],
        min_score=90.0,
        min_iv_rank=None,
        source_date="2026-07-01",
        observed_at="2026-07-01T00:00:00Z",
    )

    assert len(records) == 1
    assert records[0]["signal_id"].startswith("sig_")
    assert records[0]["instrument"]["contract_symbol"] is None
    assert records[0]["eligibility"] == {
        "status": "unknown",
        "route": None,
        "reason_code": "missing_contract_identity",
        "deadline_at": None,
    }


def test_structured_signal_rejects_source_date_drift() -> None:
    candidate = {
        "ticker": "AAPL",
        "strategy": "covered_call",
        "global_score": 175.0,
        "iv_rank": 78.0,
        "run_date": "2026-07-09",
        "candidate": {"symbol": "US.AAPL260731C315000"},
    }

    with pytest.raises(ValueError, match="run_date"):
        signals.build_signal_records(
            [candidate],
            min_score=150.0,
            min_iv_rank=None,
            source_date="2026-07-10",
            observed_at="2026-07-10T18:00:39Z",
        )


@pytest.mark.parametrize("invalid", [True, float("nan"), float("inf")])
def test_structured_signal_rejects_nonfinite_or_boolean_threshold(invalid) -> None:
    with pytest.raises(ValueError, match="min_score"):
        signals.build_signal_records(
            [CAND_HI],
            min_score=invalid,
            min_iv_rank=None,
            source_date="2026-07-01",
            observed_at="2026-07-01T00:00:00Z",
        )

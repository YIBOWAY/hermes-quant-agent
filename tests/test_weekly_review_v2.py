from __future__ import annotations

import json
import math

from hqa import weekly_review


AS_OF = "2026-07-12T01:00:00Z"


def _opportunity(
    signal_id: str,
    *,
    observed_at: str,
    resolution: str,
    missed_reason: str | None = None,
    assessed_at: str | None = None,
) -> dict:
    return {
        "signal_id": signal_id,
        "signal": {"observed_at": observed_at},
        "resolution": resolution,
        "missed_assessment": (
            None
            if missed_reason is None
            else {"reason_code": missed_reason, "assessed_at": assessed_at}
        ),
    }


def test_weekly_projection_empty_sources_are_exact_and_proposal_only() -> None:
    artifact = weekly_review.build_weekly_artifact(
        as_of=AS_OF,
        reviews=[],
        safety_runs=[],
        signal_runs=[],
        predictions=[],
        opportunities=[],
    )

    assert set(artifact) == {
        "schema_version",
        "kind",
        "generated_at",
        "status",
        "reason_codes",
        "data",
    }
    assert artifact["kind"] == "weekly_review"
    assert artifact["status"] == "available"
    assert artifact["reason_codes"] == []
    assert artifact["data"] == {
        "week_id": "2026-W28",
        "period_start": "2026-07-05T01:00:00Z",
        "period_end": AS_OF,
        "safety_alert_count": 0,
        "unique_signal_count": 0,
        "review_draft_count": 0,
        "review_confirmed_count": 0,
        "prediction_created_count": 0,
        "prediction_scored_count": 0,
        "prediction_hit_count": 0,
        "mean_direction_brier": None,
        "opportunity_observed_count": 0,
        "opportunity_missed_count": 0,
        "opportunity_coverage_unknown_count": 0,
        "limitations": [],
        "proposal_only": True,
        "trading_allowed": False,
    }


def test_weekly_projection_uses_half_open_event_times_and_unique_ids() -> None:
    artifact = weekly_review.build_weekly_artifact(
        as_of=AS_OF,
        reviews=[
            {"id": "old", "ts": "2026-07-05T00:59:59Z", "status": "draft"},
            {"id": "draft", "ts": "2026-07-05T01:00:00Z", "status": "draft"},
            {"id": "confirmed", "ts": "2026-07-12T00:59:59Z", "status": "confirmed"},
            {"id": "future", "ts": AS_OF, "status": "confirmed"},
        ],
        safety_runs=[
            {"ts": "2026-07-05T01:00:00Z", "alert": True},
            {"ts": "2026-07-12T00:59:59Z", "alert": False},
        ],
        signal_runs=[
            {
                "ts": "2026-07-06T00:00:00Z",
                "signal_records": [
                    {"signal_id": "sig_a"},
                    {"signal_id": "sig_a"},
                    {"signal_id": "sig_b"},
                ],
            },
        ],
        predictions=[
            {"created_at": "2026-07-05T01:00:00Z", "status": "open"},
            {
                "created_at": "2026-07-01T00:00:00Z",
                "status": "scored",
                "scored_at": "2026-07-11T00:00:00Z",
                "direction_correct": True,
                "direction_brier": 0.04,
            },
            {
                "created_at": "2026-07-06T00:00:00Z",
                "status": "scored",
                "scored_at": AS_OF,
                "direction_correct": False,
                "direction_brier": 0.64,
            },
        ],
        opportunities=[
            _opportunity(
                "sig_a",
                observed_at="2026-07-06T00:00:00Z",
                resolution="missed",
                missed_reason="no_decision",
                assessed_at="2026-07-10T00:00:00Z",
            ),
            _opportunity(
                "sig_c",
                observed_at="2026-07-11T00:00:00Z",
                resolution="expired_coverage_unknown",
            ),
        ],
    )

    data = artifact["data"]
    assert data["safety_alert_count"] == 1
    assert data["unique_signal_count"] == 3
    assert data["review_draft_count"] == 1
    assert data["review_confirmed_count"] == 1
    assert data["prediction_created_count"] == 2
    assert data["prediction_scored_count"] == 1
    assert data["prediction_hit_count"] == 1
    assert data["mean_direction_brier"] == 0.04
    assert data["opportunity_observed_count"] == 2
    assert data["opportunity_missed_count"] == 1
    assert data["opportunity_coverage_unknown_count"] == 1


def test_weekly_projection_degrades_malformed_rows_without_nonfinite_output() -> None:
    artifact = weekly_review.build_weekly_artifact(
        as_of=AS_OF,
        reviews=[{"ts": "not-a-time", "status": "draft"}],
        safety_runs=[{"ts": None, "alert": True}],
        signal_runs=[{"ts": AS_OF, "signal_records": "not-a-list"}],
        predictions=[
            {
                "created_at": "2026-07-06T00:00:00Z",
                "status": "scored",
                "scored_at": "2026-07-10T00:00:00Z",
                "direction_correct": True,
                "direction_brier": math.nan,
            }
        ],
        opportunities=[{"signal_id": "bad"}],
    )

    assert artifact["status"] == "degraded"
    assert artifact["reason_codes"]
    assert artifact["data"]["limitations"] == artifact["reason_codes"]
    json.dumps(artifact, allow_nan=False)


def test_opportunity_summary_has_exact_count_invariants() -> None:
    rows = [
        _opportunity(
            "sig_a",
            observed_at="2026-07-06T00:00:00Z",
            resolution="missed",
            missed_reason="no_decision",
            assessed_at="2026-07-10T00:00:00Z",
        ),
        _opportunity(
            "sig_b",
            observed_at="2026-07-07T00:00:00Z",
            resolution="acted",
        ),
        _opportunity(
            "sig_old",
            observed_at="2026-07-01T00:00:00Z",
            resolution="declined",
        ),
    ]

    artifact = weekly_review.build_opportunity_summary(
        as_of=AS_OF,
        opportunities=rows,
    )

    data = artifact["data"]
    assert data["total_count"] == 2
    assert set(data["resolution_counts"]) == {
        "open",
        "deferred",
        "acted",
        "action_failed",
        "declined",
        "missed",
        "expired_coverage_unknown",
        "not_actionable",
        "unknown",
    }
    assert sum(data["resolution_counts"].values()) == data["total_count"]
    assert data["resolution_counts"]["missed"] == 1
    assert data["resolution_counts"]["acted"] == 1
    assert data["miss_reason_counts"] == {
        "no_decision": 1,
        "act_without_action": 0,
        "defer_expired": 0,
    }
    assert (
        sum(data["miss_reason_counts"].values()) == data["resolution_counts"]["missed"]
    )
    assert data["proposal_only"] is True
    assert data["trading_allowed"] is False


def test_projection_write_is_atomic_private_and_round_trips(tmp_path) -> None:
    artifact = weekly_review.build_opportunity_summary(as_of=AS_OF, opportunities=[])
    path = tmp_path / "projections" / "opportunity-summary.v1.json"

    weekly_review.write_projection(path, artifact)

    assert path.stat().st_mode & 0o777 == 0o600
    assert json.loads(path.read_text(encoding="utf-8")) == artifact
    assert not list(path.parent.glob("*.tmp"))

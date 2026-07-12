from __future__ import annotations

import json

import pytest

from hqa import hermes_artifacts, research_automation, weekly_review


AS_OF = "2026-07-12T01:05:00Z"


class EmptySource:
    def list(self):
        return []


def _receipt(job: str, completed_at: str) -> dict:
    return {
        "schema_version": "1.0",
        "run_id": f"run:{job}",
        "request_id": f"request:{job}",
        "job": job,
        "as_of": completed_at,
        "started_at": completed_at,
        "completed_at": completed_at,
        "status": "available",
        "replayed": False,
        "steps": [],
        "notifications": {
            "planned": 0,
            "delivered": 0,
            "fallback_persisted": 0,
            "delivery_unknown": 0,
            "suppressed": 0,
        },
    }


def _feed(tmp_path):
    weekly_path = tmp_path / "projections" / "weekly.json"
    opportunity_path = tmp_path / "projections" / "opportunity.json"
    automation_path = tmp_path / "projections" / "automation.json"
    weekly_review.write_projection(
        weekly_path,
        weekly_review.build_weekly_artifact(
            as_of=AS_OF,
            reviews=[],
            safety_runs=[],
            signal_runs=[],
            predictions=[],
            opportunities=[],
        ),
    )
    weekly_review.write_projection(
        opportunity_path,
        weekly_review.build_opportunity_summary(as_of=AS_OF, opportunities=[]),
    )
    weekly_review.write_projection(
        automation_path,
        research_automation.build_automation_status(
            as_of=AS_OF,
            receipts=[
                _receipt("daily_close", "2026-07-11T00:15:00Z"),
                _receipt("freshness", "2026-07-12T00:17:00Z"),
                _receipt("weekly", "2026-07-12T01:00:00Z"),
                _receipt("notification_drain", "2026-07-12T01:00:00Z"),
            ],
        ),
    )
    feed = hermes_artifacts.HermesArtifactFeed(
        tmp_path / "feed" / "manifest.v1.json",
        portfolio_risk_path=tmp_path / "missing-risk.jsonl",
        prediction_ledger=EmptySource(),
        foresight_publisher=EmptySource(),
        weekly_review_path=weekly_path,
        opportunity_summary_path=opportunity_path,
        automation_status_path=automation_path,
        now=lambda: AS_OF,
    )
    return feed, weekly_path, opportunity_path, automation_path


def test_rebuild_v11_publishes_six_exact_sources_and_three_new_items(tmp_path) -> None:
    feed, _, _, _ = _feed(tmp_path)

    manifest = feed.rebuild()

    assert manifest["schema_version"] == "1.1"
    assert [source["kind"] for source in manifest["sources"]] == [
        "portfolio_risk",
        "prediction",
        "market_foresight",
        "weekly_review",
        "opportunity_summary",
        "automation_status",
    ]
    assert {item["kind"] for item in manifest["items"]} == {
        "weekly_review",
        "opportunity_summary",
        "automation_status",
    }
    assert feed.read() == manifest
    assert feed.feed_path.stat().st_mode & 0o777 == 0o600


def test_v11_corrupt_projection_degrades_only_that_source(tmp_path) -> None:
    feed, _, opportunity_path, _ = _feed(tmp_path)
    document = json.loads(opportunity_path.read_text(encoding="utf-8"))
    document["data"]["total_count"] = 1
    opportunity_path.write_text(json.dumps(document), encoding="utf-8")

    manifest = feed.rebuild()

    assert manifest["read_status"] == "degraded"
    assert {item["kind"] for item in manifest["items"]} == {
        "weekly_review",
        "automation_status",
    }
    source = next(
        source
        for source in manifest["sources"]
        if source["kind"] == "opportunity_summary"
    )
    assert source == {
        "kind": "opportunity_summary",
        "status": "degraded",
        "latest_at": None,
        "reason_code": "opportunity_summary_source_corrupt",
    }


def test_v11_accepts_truthful_queued_notification_state(tmp_path) -> None:
    feed, _, _, automation_path = _feed(tmp_path)
    document = json.loads(automation_path.read_text(encoding="utf-8"))
    document["data"]["jobs"][0]["notification_status"] = "queued"
    automation_path.write_text(json.dumps(document), encoding="utf-8")

    manifest = feed.rebuild()

    source = next(
        source
        for source in manifest["sources"]
        if source["kind"] == "automation_status"
    )
    assert source["status"] == "available"
    automation = next(
        item for item in manifest["items"] if item["kind"] == "automation_status"
    )
    assert automation["data"]["jobs"][0]["notification_status"] == "queued"


def test_v11_requires_all_projection_paths_or_none(tmp_path) -> None:
    with pytest.raises(ValueError, match="all three"):
        hermes_artifacts.HermesArtifactFeed(
            tmp_path / "feed.json",
            portfolio_risk_path=tmp_path / "risk.jsonl",
            prediction_ledger=EmptySource(),
            foresight_publisher=EmptySource(),
            weekly_review_path=tmp_path / "weekly.json",
            now=lambda: AS_OF,
        )

from __future__ import annotations

import json

from hqa import market_foresight_cli


def test_propose_emits_json_artifact_and_refreshes_feed(monkeypatch, capsys) -> None:
    artifact = {
        "schema_version": "1.0",
        "id": "mfp_test",
        "kind": "market_foresight",
        "occurred_at": "2026-07-11T04:00:00Z",
        "status": "proposed",
    }

    class Publisher:
        def publish(self, request):
            assert request["symbol"] == "AAPL"
            assert request["request_id"] == "hermes-turn-1"
            return artifact

    class Feed:
        refreshed = False

        def rebuild(self):
            self.refreshed = True
            return {"read_status": "available"}

    feed = Feed()
    monkeypatch.setattr(
        market_foresight_cli,
        "_runtime",
        lambda: (Publisher(), feed),
    )

    exit_code = market_foresight_cli.main(
        [
            "propose",
            "--symbol",
            "AAPL",
            "--direction",
            "up",
            "--horizon-date",
            "2026-07-17",
            "--confidence",
            "0.7",
            "--falsifier",
            "close below 300",
            "--request-id",
            "hermes-turn-1",
        ]
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == artifact
    assert feed.refreshed is True

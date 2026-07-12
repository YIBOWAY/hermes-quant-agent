from __future__ import annotations

import json

from hqa import hermes_artifacts_cli


def test_refresh_emits_one_json_manifest(monkeypatch, capsys) -> None:
    manifest = {
        "schema_version": "1.0",
        "read_status": "empty",
        "as_of": "2026-07-11T05:00:00Z",
        "items": [],
        "sources": [],
        "warnings": [],
    }

    class Feed:
        def rebuild(self, *, limit):
            assert limit == 20
            return manifest

    monkeypatch.setattr(hermes_artifacts_cli, "_runtime", lambda: Feed())

    exit_code = hermes_artifacts_cli.main(["refresh", "--limit", "20"])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == manifest


def test_show_maps_corrupt_manifest_to_nonzero_json_error(monkeypatch, capsys) -> None:
    class Feed:
        def read(self):
            raise hermes_artifacts_cli.HermesArtifactFeedError(
                "hermes_artifact_feed_corrupt",
                "Hermes artifact feed is unreadable or unsupported",
            )

    monkeypatch.setattr(hermes_artifacts_cli, "_runtime", lambda: Feed())

    exit_code = hermes_artifacts_cli.main(["show"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload == {
        "error": {
            "code": "hermes_artifact_feed_corrupt",
            "message": "Hermes artifact feed is unreadable or unsupported",
            "retryable": False,
        }
    }

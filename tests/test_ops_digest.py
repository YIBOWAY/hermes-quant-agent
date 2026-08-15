import json

import pytest

from hqa.ops_digest import OpsDigestError, ingest_observation
from hqa import ops_digest_cli


def test_seed_mtm_is_rejected() -> None:
    with pytest.raises(OpsDigestError) as rejected:
        ingest_observation(
            {
                "kind": "seed_mtm",
                "pnl_usd": 6817.0,
                "source": "preview_seed",
            }
        )
    assert rejected.value.code == "seed_mtm_rejected"

    with pytest.raises(OpsDigestError) as demo:
        ingest_observation(
            {
                "kind": "hung_observation",
                "sleeve_id": "sleeve-e5591ffb7441",
                "source_digest": "a" * 64,
                "metadata": {"preview_label": "hung_observation_demo"},
            }
        )
    assert demo.value.code == "seed_mtm_rejected"


def test_hung_observation_receipt_is_accepted() -> None:
    receipt = ingest_observation(
        {
            "kind": "hung_observation",
            "sleeve_id": "sleeve-73b1c482d4d4",
            "source_digest": "b" * 64,
        }
    )
    assert receipt["status"] == "accepted"
    assert receipt["kind"] == "hung_observation"
    assert receipt["sleeve_id"] == "sleeve-73b1c482d4d4"


def test_honest_failure_is_accepted() -> None:
    receipt = ingest_observation(
        {"kind": "honest_failure", "reason": "no hung-sleeve observation today"}
    )
    assert receipt["status"] == "accepted"
    assert receipt["kind"] == "honest_failure"


def test_cli_rejects_seed_and_accepts_observation(capsys, monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.stdin",
        type("S", (), {"read": lambda self: json.dumps({"kind": "seed_mtm"})})(),
    )
    # json.load needs a real file-like
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"kind": "preview_seed_mtm"})))
    assert ops_digest_cli.main(["ingest"]) == 2
    assert "seed_mtm_rejected" in capsys.readouterr().out

    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(
            json.dumps(
                {
                    "kind": "honest_failure",
                    "reason": "market closed; no observation",
                }
            )
        ),
    )
    assert ops_digest_cli.main(["ingest"]) == 0
    assert "honest_failure" in capsys.readouterr().out

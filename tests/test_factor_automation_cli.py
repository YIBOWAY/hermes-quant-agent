from __future__ import annotations

import json
from pathlib import Path

from hqa import factor_automation_cli as cli


def _request(source: Path) -> dict:
    source.write_text("# factor\n", encoding="utf-8")
    import hashlib

    return {
        "schema_version": "hqa.factor_automation_request/v1",
        "automation_id": "automation-0123456789abcdef",
        "intake_receipt_id": "paper-intake-receipt:sha256:" + "a" * 64,
        "intake_contract_digest": "b" * 64,
        "source_file_ref": str(source),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "goal": "fixture factor",
        "universe": ["SPY", "QQQ"],
        "provider": "futu",
        "start": "2021-01-01",
        "end": "2025-12-31",
        "base_commit": "c" * 40,
        "policy_evidence": {
            "universe": ["SPY", "QQQ"],
            "sample_rows": 756,
            "out_of_sample_rows": 126,
            "data_coverage_ratio": 0.995,
            "transaction_cost_bps": 10.0,
            "max_drawdown": -0.12,
            "turnover": 1.2,
            "lookahead_static_check_passed": True,
        },
    }


def test_run_once_flags_off_is_read_only(tmp_path: Path, monkeypatch, capsys) -> None:
    queue = tmp_path / "queue"
    queue.mkdir()
    request = _request(tmp_path / "factor.py")
    (queue / "request.json").write_text(json.dumps(request), encoding="utf-8")
    monkeypatch.setattr(cli.config, "FACTOR_AUTOMATION_QUEUE_DIR", queue)
    monkeypatch.setattr(cli.config, "FACTOR_AUTOMATION_RUN_DIR", tmp_path / "runs")
    monkeypatch.delenv("HQA_FACTOR_AUTOMATION_MODE", raising=False)
    monkeypatch.delenv("HQA_FACTOR_AUTOMATION_AUTO_LAND", raising=False)

    assert cli.main(["run-once"]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "disabled"
    assert (queue / "request.json").exists()
    assert not (tmp_path / "runs").exists()


def test_enqueue_stages_exact_source_and_writes_one_idempotent_request(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    queue = tmp_path / "queue"
    source = tmp_path / "generated-factor.py"
    request = _request(source)
    request_file = tmp_path / "request.json"
    request_file.write_text(json.dumps(request), encoding="utf-8")
    monkeypatch.setattr(cli.config, "FACTOR_AUTOMATION_QUEUE_DIR", queue)
    monkeypatch.setenv("HQA_FACTOR_AUTOMATION_MODE", "true")
    monkeypatch.setenv("HQA_FACTOR_AUTOMATION_AUTO_LAND", "true")

    assert cli.main(["enqueue", "--request-file", str(request_file)]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["state"] == "queued"
    queued = json.loads((queue / "automation-0123456789abcdef.json").read_text())
    staged = Path(queued["source_file_ref"])
    assert staged.parent == queue / "sources"
    assert staged.read_bytes() == source.read_bytes()
    assert staged.stat().st_mode & 0o777 == 0o600

    assert cli.main(["enqueue", "--request-file", str(request_file)]) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["idempotent_replay"] is True


def test_enqueue_flags_off_writes_nothing(tmp_path: Path, monkeypatch, capsys) -> None:
    queue = tmp_path / "queue"
    request_file = tmp_path / "request.json"
    request_file.write_text(
        json.dumps(_request(tmp_path / "generated-factor.py")),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli.config, "FACTOR_AUTOMATION_QUEUE_DIR", queue)
    monkeypatch.delenv("HQA_FACTOR_AUTOMATION_MODE", raising=False)
    monkeypatch.delenv("HQA_FACTOR_AUTOMATION_AUTO_LAND", raising=False)

    assert cli.main(["enqueue", "--request-file", str(request_file)]) == 1
    assert json.loads(capsys.readouterr().out)["code"] == "factor_automation_disabled"
    assert not queue.exists()


def test_request_parser_rejects_unbound_or_extra_fields(tmp_path: Path) -> None:
    document = _request(tmp_path / "factor.py")
    parsed, base = cli.parse_request(document)
    assert parsed.automation_id == document["automation_id"]
    assert base == "c" * 40

    document["unexpected"] = True
    try:
        cli.parse_request(document)
    except cli.FactorAutomationDriverError as exc:
        assert str(exc) == "request_schema_invalid"
    else:
        raise AssertionError("extra request fields must fail closed")


def test_run_once_enabled_maintains_sleeves_even_when_queue_is_empty(
    tmp_path: Path,
    monkeypatch,
) -> None:
    queue = tmp_path / "queue"
    queue.mkdir()
    monkeypatch.setattr(cli.config, "FACTOR_AUTOMATION_QUEUE_DIR", queue)
    monkeypatch.setenv("HQA_FACTOR_AUTOMATION_MODE", "true")
    monkeypatch.setenv("HQA_FACTOR_AUTOMATION_AUTO_LAND", "true")
    monkeypatch.setattr(
        cli.quant_cli,
        "run_factor_automation_maintain",
        lambda: (
            0,
            '{"checked":2,"paused":1,"quarantined":0,"state":"maintained"}\n',
        ),
    )

    result = cli.run_once()

    assert result == {
        "state": "idle",
        "queued": 0,
        "maintenance": {
            "state": "maintained",
            "checked": 2,
            "paused": 1,
            "quarantined": 0,
        },
    }

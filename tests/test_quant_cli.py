from __future__ import annotations

import subprocess

import pytest

from hqa import config, quant_cli


class _FakeProc:
    def __init__(self, returncode, stdout):
        self.returncode = returncode
        self.stdout = stdout


def test_run_doctor_invokes_cli_with_cwd(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        return _FakeProc(0, "safety.dry_run=true\n")

    monkeypatch.setattr(quant_cli.subprocess, "run", fake_run)
    code, out = quant_cli.run_doctor()
    assert code == 0
    assert "safety.dry_run=true" in out
    assert seen["argv"][0].endswith("quant-system")
    assert seen["argv"][1] == "doctor"
    assert seen["kwargs"]["cwd"] == str(config.AIQP_DIR)
    assert seen["kwargs"]["stderr"] is subprocess.STDOUT
    assert seen["kwargs"]["timeout"] == 300


def test_run_options_sample_scan_argv(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return _FakeProc(0, "candidates=1000\n")

    monkeypatch.setattr(quant_cli.subprocess, "run", fake_run)
    code, out = quant_cli.run_options_sample_scan()
    assert code == 0 and "candidates=1000" in out
    assert seen["argv"][1:] == ["options", "daily-scan", "--provider", "sample"]


def test_run_options_scan_default_argv_futu(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        return _FakeProc(0, "candidates=1000\n")

    monkeypatch.setattr(quant_cli.subprocess, "run", fake_run)
    code, out = quant_cli.run_options_scan()
    assert code == 0
    assert seen["argv"][1:] == ["options", "daily-scan", "--provider", "futu"]
    assert seen["kwargs"]["timeout"] == 3600


def test_run_factor_lab_default_argv_futu(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return _FakeProc(0, "cross_rows=5 timing_rows=5\n")

    monkeypatch.setattr(quant_cli.subprocess, "run", fake_run)
    code, out = quant_cli.run_factor_lab()
    assert code == 0
    assert seen["argv"][1:] == ["factor", "refresh-lab", "--provider", "futu"]


def test_run_propose_factor_argv(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return _FakeProc(0, "candidate_id=factor-x-1 status=pending")

    monkeypatch.setattr(quant_cli.subprocess, "run", fake_run)
    code, out = quant_cli.run_propose_factor("momentum 20d", "/tmp/factor_src.py", "SPY,QQQ")
    assert code == 0
    assert "candidate_id=factor-x-1" in out
    assert seen["argv"][1:] == [
        "agent",
        "propose-factor",
        "--goal",
        "momentum 20d",
        "--universe",
        "SPY,QQQ",
        "--source-file",
        "/tmp/factor_src.py",
    ]


def test_run_list_candidates_argv(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return _FakeProc(0, "candidate_id=factor-x-1 status=pending")

    monkeypatch.setattr(quant_cli.subprocess, "run", fake_run)
    code, out = quant_cli.run_list_candidates()
    assert code == 0
    assert "candidate_id=factor-x-1" in out
    assert seen["argv"][1:] == ["agent", "list-candidates"]


def test_run_agent_review_argv(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return _FakeProc(0, "ok")

    monkeypatch.setattr(quant_cli.subprocess, "run", fake_run)
    quant_cli.run_agent_review("factor-x-1", "approve", "translation confirmed")
    assert seen["argv"][1:] == [
        "agent",
        "review",
        "--candidate-id",
        "factor-x-1",
        "--decision",
        "approve",
        "--note",
        "translation confirmed",
    ]


def test_run_experiment_config_argv(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return _FakeProc(0, "experiment_id=e-1")

    monkeypatch.setattr(quant_cli.subprocess, "run", fake_run)
    quant_cli.run_experiment_config("/tmp/exp.json", provider="tiingo")
    assert seen["argv"][1:] == [
        "experiment",
        "run-config",
        "--config",
        "/tmp/exp.json",
        "--provider",
        "tiingo",
        "--include-approved-candidates",
    ]


def test_run_experiment_config_can_omit_approved_candidates(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return _FakeProc(0, "experiment_id=e-1")

    monkeypatch.setattr(quant_cli.subprocess, "run", fake_run)
    quant_cli.run_experiment_config("/tmp/exp.json", provider="tiingo", include_approved=False)
    assert "--include-approved-candidates" not in seen["argv"]


@pytest.mark.skipif(
    True, reason="manual — requires working quant-system environment; run with --no-skip to verify live"
)
def test_run_doctor_integration_real():
    code, out = quant_cli.run_doctor()
    assert code == 0
    assert "safety.dry_run=" in out

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


def test_run_options_sample_scan_argv(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return _FakeProc(0, "candidates=1000\n")

    monkeypatch.setattr(quant_cli.subprocess, "run", fake_run)
    code, out = quant_cli.run_options_sample_scan()
    assert code == 0 and "candidates=1000" in out
    assert seen["argv"][1:] == ["options", "daily-scan", "--provider", "sample"]


@pytest.mark.skipif(
    not config.QUANT_SYSTEM_BIN.exists(), reason="quant-system binary not present"
)
def test_run_doctor_integration_real():
    code, out = quant_cli.run_doctor()
    assert code == 0
    assert "safety.dry_run=" in out

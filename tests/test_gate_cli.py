from __future__ import annotations

import json

from hqa import gate_cli


def test_gate_cli_reports_and_never_gates(tmp_path, capsys):
    cfg = {"kill_switch_enabled": False}
    path = tmp_path / "strat.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    rc = gate_cli.main(["check", str(path)])
    assert rc == 0  # report-only, never non-zero
    out = capsys.readouterr().out
    assert "OVERALL: FAIL" in out
    assert "kill_switch_hook" in out

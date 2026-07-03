from __future__ import annotations

import importlib
from pathlib import Path

import hqa.config as config


def test_repo_and_platform_paths():
    assert config.REPO_DIR.name == "Hermes-quant-agent"
    assert config.AIQP_DIR == Path("/Users/sunyibo/programs/ai-quant-platform")
    assert config.QUANT_SYSTEM_BIN == config.AIQP_DIR / "ai-quant" / "bin" / "quant-system"
    assert config.LOG_DIR == config.REPO_DIR / "logs"
    assert config.OPTIONS_SCAN_DIR == config.AIQP_DIR / "data" / "options_scans"


def test_expected_safety_baseline():
    assert config.EXPECTED_SAFETY == {
        "dry_run": "true",
        "paper_trading": "true",
        "live_trading_enabled": "false",
        "kill_switch": "true",
    }


def test_log_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("HQA_LOG_DIR", str(tmp_path / "mylogs"))
    try:
        importlib.reload(config)
        assert config.LOG_DIR == tmp_path / "mylogs"
    finally:
        monkeypatch.undo()
        importlib.reload(config)

from __future__ import annotations

import importlib
import json
from pathlib import Path

import hqa.config as config


def test_repo_and_platform_paths():
    assert config.REPO_DIR.name == "Hermes-quant-agent"
    assert config.AIQP_DIR == Path("/Users/sunyibo/programs/ai-quant-platform")
    assert (
        config.QUANT_SYSTEM_BIN == config.AIQP_DIR / "ai-quant" / "bin" / "quant-system"
    )
    assert config.LOG_DIR == config.REPO_DIR / "logs"
    assert config.PREDICTION_DIR == config.REPO_DIR / "predictions"
    assert config.OPPORTUNITY_DIR == config.REPO_DIR / "opportunities"
    assert config.MARKET_FORESIGHT_DIR == config.REPO_DIR / "market_foresight"
    assert (
        config.HERMES_ARTIFACT_FEED_PATH
        == config.REPO_DIR / "artifacts" / "hermes-feed" / "manifest.v1.json"
    )
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


def test_prediction_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("HQA_PREDICTION_DIR", str(tmp_path / "predictions"))
    try:
        importlib.reload(config)
        assert config.PREDICTION_DIR == tmp_path / "predictions"
    finally:
        monkeypatch.undo()
        importlib.reload(config)


def test_opportunity_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("HQA_OPPORTUNITY_DIR", str(tmp_path / "opportunities"))
    try:
        importlib.reload(config)
        assert config.OPPORTUNITY_DIR == tmp_path / "opportunities"
    finally:
        monkeypatch.undo()
        importlib.reload(config)


def test_artifact_paths_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("HQA_MARKET_FORESIGHT_DIR", str(tmp_path / "foresight"))
    monkeypatch.setenv("HQA_ARTIFACT_FEED_PATH", str(tmp_path / "feed.json"))
    try:
        importlib.reload(config)
        assert config.MARKET_FORESIGHT_DIR == tmp_path / "foresight"
        assert config.HERMES_ARTIFACT_FEED_PATH == tmp_path / "feed.json"
    finally:
        monkeypatch.undo()
        importlib.reload(config)


def test_default_data_provider_is_futu():
    assert config.DEFAULT_DATA_PROVIDER == "futu"


def test_load_signal_thresholds_missing_file_is_collect(tmp_path):
    result = config.load_signal_thresholds(tmp_path / "missing.json")
    assert result["min_score"] is None
    assert result["min_iv_rank"] is None
    assert result["source"] == "none"


def test_load_signal_thresholds_from_file(tmp_path):
    path = tmp_path / "signal_thresholds.json"
    path.write_text(
        json.dumps({"min_score": 150, "min_iv_rank": None}), encoding="utf-8"
    )
    result = config.load_signal_thresholds(path)
    assert result["min_score"] == 150.0
    assert result["min_iv_rank"] is None
    assert result["source"] == "file"


def test_load_signal_thresholds_env_overrides_file(tmp_path, monkeypatch):
    path = tmp_path / "signal_thresholds.json"
    path.write_text(json.dumps({"min_score": 150}), encoding="utf-8")
    monkeypatch.setenv("HQA_MIN_SCORE", "140")
    try:
        result = config.load_signal_thresholds(path)
        assert result["min_score"] == 140.0
        assert result["source"] == "env"
    finally:
        monkeypatch.delenv("HQA_MIN_SCORE", raising=False)

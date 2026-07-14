from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

REPO_DIR = Path(__file__).resolve().parent.parent
AIQP_DIR = Path(
    os.environ.get("HQA_AIQP_DIR", "/Users/sunyibo/programs/ai-quant-platform")
)
QUANT_SYSTEM_BIN = Path(
    os.environ.get(
        "HQA_QUANT_SYSTEM_BIN", str(AIQP_DIR / "ai-quant" / "bin" / "quant-system")
    )
)
LOG_DIR = Path(os.environ.get("HQA_LOG_DIR", str(REPO_DIR / "logs")))
REVIEW_DIR = Path(os.environ.get("HQA_REVIEW_DIR", str(REPO_DIR / "review")))
PREDICTION_DIR = Path(
    os.environ.get("HQA_PREDICTION_DIR", str(REPO_DIR / "predictions"))
)
OPPORTUNITY_DIR = Path(
    os.environ.get("HQA_OPPORTUNITY_DIR", str(REPO_DIR / "opportunities"))
)
MARKET_FORESIGHT_DIR = Path(
    os.environ.get(
        "HQA_MARKET_FORESIGHT_DIR",
        str(REPO_DIR / "market_foresight"),
    )
)
HERMES_ARTIFACT_FEED_PATH = Path(
    os.environ.get(
        "HQA_ARTIFACT_FEED_PATH",
        str(REPO_DIR / "artifacts" / "hermes-feed" / "manifest.v1.json"),
    )
)
AUTOMATION_DIR = Path(
    os.environ.get("HQA_AUTOMATION_DIR", str(REPO_DIR / "automation"))
)
AUTOMATION_RUNS_PATH = AUTOMATION_DIR / "runs.jsonl"
NOTIFICATION_OUTBOX_PATH = Path(
    os.environ.get(
        "HQA_NOTIFICATION_OUTBOX_PATH",
        str(AUTOMATION_DIR / "notification-outbox.jsonl"),
    )
)
FULL9H_PROJECTION_DIR = Path(
    os.environ.get(
        "HQA_FULL9H_PROJECTION_DIR",
        str(REPO_DIR / "artifacts" / "hermes-feed" / "projections"),
    )
)
WEEKLY_REVIEW_PROJECTION_PATH = FULL9H_PROJECTION_DIR / "weekly-review.v1.json"
OPPORTUNITY_SUMMARY_PROJECTION_PATH = (
    FULL9H_PROJECTION_DIR / "opportunity-summary.v1.json"
)
AUTOMATION_STATUS_PROJECTION_PATH = (
    FULL9H_PROJECTION_DIR / "automation-status.v1.json"
)
FULL9H_NOTIFY_TARGET = os.environ.get("HQA_FULL9H_NOTIFY_TARGET", "local")
OPTIONS_SCAN_DIR = Path(
    os.environ.get("HQA_OPTIONS_SCAN_DIR", str(AIQP_DIR / "data" / "options_scans"))
)
RUNTIME_DIR = Path(
    os.environ.get("HQA_RUNTIME_DIR", str(REPO_DIR / "data" / "_runtime"))
)
FACTOR_GATE1_DIR = Path(
    os.environ.get("HQA_FACTOR_GATE1_DIR", str(RUNTIME_DIR / "factor-gate1"))
)
FACTOR_EXPERIMENT_OUTPUT_DIR = Path(
    os.environ.get(
        "HQA_FACTOR_EXPERIMENT_OUTPUT_DIR",
        str(RUNTIME_DIR / "factor-experiments"),
    )
)
SIGNAL_THRESHOLDS_PATH = Path(
    os.environ.get("HQA_SIGNAL_THRESHOLDS", str(RUNTIME_DIR / "signal_thresholds.json"))
)

# These two admission anchors are intentionally not environment-overridable.
# Tests monkeypatch the module constants directly.
HERMES_GATEWAY_CAPABILITIES_PATH = (
    REPO_DIR / "config" / "hermes-gateway-capabilities.v1.json"
)
HERMES_GATEWAY_REVIEW_PATH = (
    REPO_DIR / "config" / "hermes-gateway-capabilities.v1.review.json"
)
HERMES_BIN_PATH = Path(
    os.environ.get("HQA_HERMES_BIN_PATH", "/Users/sunyibo/.local/bin/hermes")
)
HERMES_SOURCE_DIR = Path(
    os.environ.get(
        "HQA_HERMES_SOURCE_DIR",
        "/Users/sunyibo/.hermes/hermes-agent",
    )
)

# Nominal safety baseline. Any deviation from these values is an alert.
EXPECTED_SAFETY = {
    "dry_run": "true",
    "paper_trading": "true",
    "live_trading_enabled": "false",
    "kill_switch": "true",
}

# Default Scene-B / research data provider. Matches platform default_data_provider
# (futu). Tiingo requires an explicit opt-in when a token is configured.
DEFAULT_DATA_PROVIDER = os.environ.get("HQA_DEFAULT_DATA_PROVIDER", "futu")


def load_signal_thresholds(path: Optional[Path] = None) -> dict[str, Any]:
    """Load Scene-A alert thresholds.

    Returns ``{"min_score": float|None, "min_iv_rank": float|None, "source": str}``.
    Missing / invalid file → both thresholds None (collect mode, D-15).
    Env overrides: ``HQA_MIN_SCORE``, ``HQA_MIN_IV_RANK`` (when set) win over file.
    """
    path = path or SIGNAL_THRESHOLDS_PATH
    min_score: Optional[float] = None
    min_iv_rank: Optional[float] = None
    source = "none"

    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            data = {}
        if isinstance(data, dict):
            if data.get("min_score") is not None:
                try:
                    min_score = float(data["min_score"])
                    source = "file"
                except (TypeError, ValueError):
                    min_score = None
            if data.get("min_iv_rank") is not None:
                try:
                    min_iv_rank = float(data["min_iv_rank"])
                    source = "file" if source == "none" else source
                except (TypeError, ValueError):
                    min_iv_rank = None

    env_score = os.environ.get("HQA_MIN_SCORE")
    if env_score is not None and env_score.strip() != "":
        try:
            min_score = float(env_score)
            source = "env"
        except ValueError:
            pass
    env_iv = os.environ.get("HQA_MIN_IV_RANK")
    if env_iv is not None and env_iv.strip() != "":
        try:
            min_iv_rank = float(env_iv)
            source = "env" if source == "none" else source
        except ValueError:
            pass

    return {"min_score": min_score, "min_iv_rank": min_iv_rank, "source": source}

from __future__ import annotations

import os
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
AIQP_DIR = Path(os.environ.get("HQA_AIQP_DIR", "/Users/sunyibo/programs/ai-quant-platform"))
QUANT_SYSTEM_BIN = Path(
    os.environ.get("HQA_QUANT_SYSTEM_BIN", str(AIQP_DIR / "ai-quant" / "bin" / "quant-system"))
)
LOG_DIR = Path(os.environ.get("HQA_LOG_DIR", str(REPO_DIR / "logs")))
REVIEW_DIR = Path(os.environ.get("HQA_REVIEW_DIR", str(REPO_DIR / "review")))
OPTIONS_SCAN_DIR = Path(os.environ.get("HQA_OPTIONS_SCAN_DIR", str(AIQP_DIR / "data" / "options_scans")))

# Nominal safety baseline. Any deviation from these values is an alert.
EXPECTED_SAFETY = {
    "dry_run": "true",
    "paper_trading": "true",
    "live_trading_enabled": "false",
    "kill_switch": "true",
}

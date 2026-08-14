#!/bin/bash
# Full 9H post-close read-only reconciliation cycle.
set -euo pipefail
unset PYTHONPATH PYTHONHOME
# Explicit, receipt-backed history fallback when Futu is briefly offline at
# 08:15: the artifact records the Futu error and the Tiingo provenance.
export HQA_PORTFOLIO_RISK_HISTORY_FALLBACK=tiingo
export HQA_AIQP_DIR="__HQA_PLATFORM_DIR__"
export HQA_QUANT_SYSTEM_BIN="__HQA_PLATFORM_DIR__/ai-quant/bin/quant-system"
cd __HQA_REPO_DIR__
exec /usr/bin/env python3 -m hqa.research_automation_cli daily_close "$@"

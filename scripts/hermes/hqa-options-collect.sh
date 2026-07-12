#!/bin/bash
# HQA options scan collection (real futu chains; requires OpenD running).
# The platform-dir placeholder is replaced by install.sh at deploy time (HQA_AIQP_DIR).
# --top 100: futu rate limit ≈33s/symbol → 100 symbols ≈56min (+ OpenD/retry
# headroom). Hermes cron `script_timeout_seconds` must be ≥7200 (raised 2026-07-09
# after 3600s kills left no 07-08/09 meta). top-100 score dist is enough for D-15
# thresholds; full 516-symbol universe would need ~4.8h.
set -euo pipefail
unset PYTHONPATH PYTHONHOME
cd __HQA_PLATFORM_DIR__
exec __HQA_PLATFORM_DIR__/ai-quant/bin/quant-system \
  options daily-task --provider futu --top 100 "$@"

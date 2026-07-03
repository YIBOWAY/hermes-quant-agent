#!/bin/bash
# HQA options scan collection (real futu chains; requires OpenD running).
# The platform-dir placeholder is replaced by install.sh at deploy time (HQA_AIQP_DIR).
# --top 100: futu rate limit ≈33s/symbol → 100 symbols ≈56min, fits the 3600s
# cron script timeout; the top-100 score distribution is sufficient for D-15
# threshold statistics (full 516-symbol universe would need ~4.8h).
set -euo pipefail
cd __HQA_PLATFORM_DIR__
exec __HQA_PLATFORM_DIR__/ai-quant/bin/quant-system \
  options daily-task --provider futu --top 100 "$@"

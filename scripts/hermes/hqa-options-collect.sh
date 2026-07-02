#!/bin/bash
# HQA options scan collection (real futu chains; requires OpenD running).
# The platform-dir placeholder is replaced by install.sh at deploy time (HQA_AIQP_DIR).
set -euo pipefail
cd __HQA_PLATFORM_DIR__
exec __HQA_PLATFORM_DIR__/ai-quant/bin/quant-system \
  options daily-task --provider futu "$@"

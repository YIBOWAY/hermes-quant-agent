#!/bin/bash
# HQA pre-market digest wrapper (deployed into ~/.hermes/scripts/).
# __HQA_REPO_DIR__ is replaced by install.sh at deploy time.
set -euo pipefail
cd __HQA_REPO_DIR__
exec /usr/bin/env python3 -m hqa.premarket_digest "$@"

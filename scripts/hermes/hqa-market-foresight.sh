#!/bin/bash
# HQA proposal-only market-foresight wrapper (deployed into ~/.hermes/scripts/).
set -euo pipefail
unset PYTHONPATH PYTHONHOME
cd __HQA_REPO_DIR__
exec /usr/bin/env python3 -m hqa.market_foresight_cli "$@"

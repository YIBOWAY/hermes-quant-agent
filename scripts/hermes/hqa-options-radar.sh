#!/bin/bash
# HQA options-radar summary wrapper (deployed into ~/.hermes/scripts/).
# The repo-dir placeholder is replaced by install.sh at deploy time.
set -euo pipefail
cd __HQA_REPO_DIR__
exec /usr/bin/env python3 -m hqa.options_radar "$@"

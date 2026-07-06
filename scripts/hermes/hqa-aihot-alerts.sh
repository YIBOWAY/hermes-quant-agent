#!/bin/bash
# HQA AI-HOT alerts watchdog wrapper (deployed into ~/.hermes/scripts/).
# The repo-dir placeholder is replaced by install.sh at deploy time.
set -euo pipefail
cd __HQA_REPO_DIR__
exec /usr/bin/env python3 -m hqa.aihot_alerts "$@"

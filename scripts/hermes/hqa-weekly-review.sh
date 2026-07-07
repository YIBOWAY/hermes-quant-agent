#!/bin/bash
# HQA weekly review wrapper.
set -euo pipefail
unset PYTHONPATH PYTHONHOME
cd __HQA_REPO_DIR__
exec /usr/bin/env python3 -m hqa.weekly_review "$@"

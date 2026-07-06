#!/bin/bash
# HQA weekly review wrapper.
set -euo pipefail
cd __HQA_REPO_DIR__
exec /usr/bin/env python3 -m hqa.weekly_review "$@"

#!/bin/bash
# Full 9H local source/job freshness projection.
set -euo pipefail
unset PYTHONPATH PYTHONHOME
cd __HQA_REPO_DIR__
exec /usr/bin/env python3 -m hqa.research_automation_cli freshness "$@"

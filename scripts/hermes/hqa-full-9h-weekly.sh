#!/bin/bash
# Full 9H structured weekly review and feed projection.
set -euo pipefail
unset PYTHONPATH PYTHONHOME
cd __HQA_REPO_DIR__
exec /usr/bin/env python3 -m hqa.research_automation_cli weekly "$@"

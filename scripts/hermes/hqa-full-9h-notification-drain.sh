#!/bin/bash
# Full 9H bounded notification outbox drain (no LLM).
set -euo pipefail
unset PYTHONPATH PYTHONHOME
cd __HQA_REPO_DIR__
exec /usr/bin/env python3 -m hqa.research_automation_cli notification_drain "$@"

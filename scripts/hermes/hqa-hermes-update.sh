#!/bin/bash
# Operator-only updater. Never install this wrapper into cron or no-agent jobs.
set -euo pipefail

cd __HQA_REPO_DIR__
exec python3 -m hqa.hermes_update_cli "$@"

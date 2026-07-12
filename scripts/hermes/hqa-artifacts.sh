#!/bin/bash
# HQA read-only/rebuildable Hermes artifact-feed wrapper.
set -euo pipefail
unset PYTHONPATH PYTHONHOME
cd __HQA_REPO_DIR__
exec /usr/bin/env python3 -m hqa.hermes_artifacts_cli "$@"

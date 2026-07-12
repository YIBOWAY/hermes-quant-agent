#!/bin/bash
# HQA opportunity ledger: records evidence and assessments only; never executes.
set -euo pipefail
unset PYTHONPATH PYTHONHOME
cd __HQA_REPO_DIR__
exec /usr/bin/env python3 -m hqa.opportunity_cli "$@"

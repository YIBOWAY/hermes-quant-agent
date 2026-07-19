#!/bin/bash
set -euo pipefail

if [ "$#" -ne 0 ]; then
  echo "hqa-intent-payload-reconcile accepts no arguments" >&2
  exit 2
fi

cd __HQA_REPO_DIR__
exec python3 -m hqa.intent_retention_cli

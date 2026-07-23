#!/bin/bash
set -euo pipefail

if [ "$#" -ne 0 ]; then
  echo "hqa-hermes-compatibility-watch accepts no arguments" >&2
  exit 2
fi

cd __HQA_REPO_DIR__
exec python3 -m hqa.hermes_compatibility_cli check \
  --no-agent \
  --profile local_agent_v0_2 \
  --platform-root __HQA_PLATFORM_DIR__

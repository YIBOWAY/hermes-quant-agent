#!/bin/bash
set -euo pipefail

if [ "$#" -ne 0 ]; then
  echo "hqa-hermes-compatibility-watch accepts no arguments" >&2
  exit 2
fi

HQA_INSTALLED_HERMES_SOURCE_DIR=__HQA_HERMES_SOURCE_DIR__
case "$HQA_INSTALLED_HERMES_SOURCE_DIR" in
  __*__)
    echo "hqa-hermes-compatibility-watch has an unsubstituted Hermes source" >&2
    exit 2
    ;;
esac
case "$HQA_INSTALLED_HERMES_SOURCE_DIR" in
  /*) ;;
  *)
    echo "hqa-hermes-compatibility-watch Hermes source must be absolute" >&2
    exit 2
    ;;
esac
export HQA_HERMES_COMPAT_HERMES_REPO="$HQA_INSTALLED_HERMES_SOURCE_DIR"

cd __HQA_REPO_DIR__
exec python3 -m hqa.hermes_compatibility_cli check \
  --no-agent \
  --profile local_agent_v0_2 \
  --platform-root __HQA_PLATFORM_DIR__

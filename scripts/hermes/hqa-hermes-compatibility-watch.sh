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

HQA_INSTALLED_HQA_REPO=__HQA_REPO_DIR__
case "$HQA_INSTALLED_HQA_REPO" in
  __*__)
    echo "hqa-hermes-compatibility-watch has an unsubstituted HQA path" >&2
    exit 2
    ;;
  /*) ;;
  *)
    echo "hqa-hermes-compatibility-watch HQA path must be absolute" >&2
    exit 2
    ;;
esac
export HQA_HERMES_COMPAT_HQA_REPO="$HQA_INSTALLED_HQA_REPO"

HQA_INSTALLED_HERMES_API_KEY_FILE=__HQA_HERMES_API_KEY_FILE__
case "$HQA_INSTALLED_HERMES_API_KEY_FILE" in
  __*__)
    echo "hqa-hermes-compatibility-watch has an unsubstituted API-key path" >&2
    exit 2
    ;;
esac
if [ -n "$HQA_INSTALLED_HERMES_API_KEY_FILE" ]; then
  case "$HQA_INSTALLED_HERMES_API_KEY_FILE" in
    /*) ;;
    *)
      echo "hqa-hermes-compatibility-watch API-key path must be absolute" >&2
      exit 2
      ;;
  esac
fi
export HQA_HERMES_COMPAT_HERMES_API_KEY_FILE="$HQA_INSTALLED_HERMES_API_KEY_FILE"

if [ -x "$HQA_INSTALLED_HERMES_SOURCE_DIR/.venv/bin/hermes" ]; then
  HQA_INSTALLED_HERMES_CLI="$HQA_INSTALLED_HERMES_SOURCE_DIR/.venv/bin/hermes"
elif [ -x "$HQA_INSTALLED_HERMES_SOURCE_DIR/venv/bin/hermes" ]; then
  HQA_INSTALLED_HERMES_CLI="$HQA_INSTALLED_HERMES_SOURCE_DIR/venv/bin/hermes"
else
  echo "hqa-hermes-compatibility-watch Hermes CLI is unavailable" >&2
  exit 2
fi
export HQA_HERMES_COMPAT_HERMES_CLI="$HQA_INSTALLED_HERMES_CLI"

cd __HQA_REPO_DIR__
exec python3 -m hqa.hermes_compatibility_cli check \
  --no-agent \
  --profile local_agent_v0_2 \
  --platform-root __HQA_PLATFORM_DIR__

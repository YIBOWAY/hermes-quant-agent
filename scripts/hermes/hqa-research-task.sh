#!/bin/bash
set -euo pipefail

case "${1:-}" in
  show|events|audit|rebuild)
    ;;
  *)
    printf '%s\n' '{"error":{"code":"workflow_invalid_request","message":"workflow command is invalid","retryable":false}}'
    exit 2
    ;;
esac

cd __HQA_REPO_DIR__
exec python3 -m hqa.workflow_authority_cli "$@"

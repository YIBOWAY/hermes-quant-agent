#!/bin/bash
# Fixed paper-only automation ingress. The persistent driver consumes the
# owner-controlled queue independently of the Hermes/Codex/Claude terminal.
set -euo pipefail

if [ "${1:-}" != "enqueue" ]; then
  printf '%s\n' \
    '{"state":"failed","code":"factor_automation_operation_not_allowed"}' >&2
  exit 2
fi

export HQA_AIQP_DIR="__HQA_PLATFORM_DIR__"
export HQA_QUANT_SYSTEM_BIN="__HQA_PLATFORM_DIR__/ai-quant/bin/quant-system"
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONINSPECT
export PYTHONNOUSERSITE=1
cd "__HQA_REPO_DIR__"
exec /usr/bin/python3 -s -m hqa.factor_automation_cli "$@"

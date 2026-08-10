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
HQA_FACTOR_AUTOMATION_DRIVER="__HQA_PLATFORM_DIR__/scripts/run_factor_automation_driver.sh"
if [ ! -f "$HQA_FACTOR_AUTOMATION_DRIVER" ] || [ -L "$HQA_FACTOR_AUTOMATION_DRIVER" ]; then
  printf '%s\n' \
    '{"state":"failed","code":"factor_automation_driver_unavailable"}' >&2
  exit 78
fi
exec /bin/bash "$HQA_FACTOR_AUTOMATION_DRIVER" "$@"

#!/bin/bash
# Fixed Scene-B factor-reproduction ingress. Installation freezes both owned
# repositories so Hermes cannot drift back to a different Platform checkout.
set -euo pipefail

case "${1:-}" in
  propose|list|detail|approve|backtest|promote)
    ;;
  *)
    printf '%s\n' \
      '{"contract":"hqa-factor-repro-wrapper/v1","ok":false,"error":{"code":"factor_repro_operation_not_allowed","message":"factor reproduction operation is not allowed","retryable":false}}' \
      >&2
    exit 2
    ;;
esac

export HQA_AIQP_DIR="__HQA_PLATFORM_DIR__"
export HQA_QUANT_SYSTEM_BIN="__HQA_PLATFORM_DIR__/ai-quant/bin/quant-system"
export HQA_FACTOR_REPRO_BIN="__HERMES_SCRIPTS_DIR__/hqa-factor-repro.sh"
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONINSPECT
export PYTHONNOUSERSITE=1
cd "__HQA_REPO_DIR__"
exec /usr/bin/python3 -s -m hqa.factor_repro_cli "$@"

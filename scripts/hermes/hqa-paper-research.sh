#!/bin/bash
# Human-gated paper-research coordinator; stdin may carry one encrypted-store
# intent body, while argv/env/stdout remain body-free.
set -euo pipefail

case "${1:-}" in
  stage-source)
    if [ "$#" -ne 1 ]; then
      printf '%s\n' 'paper_source_stage_error=arguments_not_allowed' >&2
      exit 2
    fi
    ;;
  prepare-intent|start-plan|confirm-plan|open-gate1|open-gate2|open-gate3|complete-after-human-commit)
    ;;
  *)
    printf '%s\n' '{"contract":"agent-v0.2-paper-research-cli/v1","operation":"invalid","ok":false,"error":{"code":"paper_research_invalid_arguments","message":"paper research operation is invalid","retryable":false}}'
    exit 2
    ;;
esac

export HQA_AIQP_DIR="__HQA_PLATFORM_DIR__"
export HQA_QUANT_SYSTEM_BIN="__HQA_PLATFORM_DIR__/ai-quant/bin/quant-system"
export HQA_PAPER_GATE_PORT_BIN="__HERMES_SCRIPTS_DIR__/hqa-paper-gate-show.py"
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONINSPECT PYTHONUSERBASE
export PYTHONNOUSERSITE=1
cd __HQA_REPO_DIR__
if [ "$1" = "stage-source" ]; then
  exec /usr/bin/python3 -I "__HERMES_SCRIPTS_DIR__/hqa-paper-source-stage.py"
fi
exec /usr/bin/python3 -s -m hqa.paper_research_cli "$@"

#!/bin/bash
# Natural-language Vertical-A ingress. The platform binds stdin to the exact
# managed Hermes Run selectors and performs one durable Futu read-only call.
set -euo pipefail

if [ "$#" -ne 0 ]; then
  printf '%s\n' '{"contract":"agent-v0.2-options-research/v1","ok":false,"status":"unavailable","error_code":"vertical_a_request_invalid","message":"options research accepts JSON on stdin only"}'
  exit 2
fi

export HQA_AIQP_DIR="__HQA_PLATFORM_DIR__"
cd "__HQA_PLATFORM_DIR__"
exec "__HQA_PLATFORM_DIR__/ai-quant/bin/quant-system" \
  hermes vertical-a execute-from-hermes

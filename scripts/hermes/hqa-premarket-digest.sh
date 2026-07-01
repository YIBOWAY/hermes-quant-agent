#!/bin/bash
# HQA pre-market digest wrapper (deployed into ~/.hermes/scripts/).
set -euo pipefail
cd /Users/sunyibo/programs/Hermes-quant-agent
exec /usr/bin/env python3 -m hqa.premarket_digest "$@"

#!/bin/bash
# HQA weekly review wrapper.
set -euo pipefail
cd /Users/sunyibo/programs/Hermes-quant-agent
exec /usr/bin/env python3 -m hqa.weekly_review "$@"

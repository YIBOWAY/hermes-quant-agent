#!/bin/bash
# HQA Scene-A market-signal watchdog wrapper.
set -euo pipefail
cd /Users/sunyibo/programs/Hermes-quant-agent
exec /usr/bin/env python3 -m hqa.signal_watchdog "$@"

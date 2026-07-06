#!/bin/bash
# HQA Scene-A market-signal watchdog wrapper.
set -euo pipefail
cd __HQA_REPO_DIR__
exec /usr/bin/env python3 -m hqa.signal_watchdog "$@"

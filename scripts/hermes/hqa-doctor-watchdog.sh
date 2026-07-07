#!/bin/bash
# HQA safety-invariant watchdog wrapper (deployed into ~/.hermes/scripts/).
# Thin wrapper: Hermes blocks symlinks/abs paths, so this physical file cd's
# into the repo and exec's the version-controlled Python module.
# The repo-dir placeholder is replaced by install.sh at deploy time.
set -euo pipefail
unset PYTHONPATH PYTHONHOME
cd __HQA_REPO_DIR__
exec /usr/bin/env python3 -m hqa.doctor_watchdog "$@"

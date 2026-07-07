#!/bin/bash
# HQA read-only gate wrapper for pre-authorized platform queries (D-25 ③).
# The Hermes command_allowlist gets ONE entry pointing at this single wrapper;
# it never grants bare `quant-system`. The wrapper re-checks the subcommand
# against a hardcoded read-only allowlist, so an over-broad glob upstream can
# never smuggle a write/trade command through. Miss → refuse (exit 2), no exec.
#
# __HQA_PLATFORM_DIR__ (ai-quant-platform, from HQA_AIQP_DIR — matches
# hqa/config.py) is substituted by scripts/install.sh at deploy time.
#
# Allowlist provenance: every entry below was confirmed side-effect-free via
# `quant-system <cmd> --help`. Commands that refresh inputs, delete caches,
# download data, run loops, start servers, or write candidate/approval files
# are deliberately EXCLUDED — those keep human approval. Two-word entries match
# the first two args (Typer subcommand groups); "doctor" is a single word.
set -euo pipefail
unset PYTHONPATH PYTHONHOME

PLATFORM_DIR="__HQA_PLATFORM_DIR__"

READONLY_ALLOWLIST=(
  "doctor"
  "config show"
  "factor list"
  "options daily-scan"
  "options buyside-screen"
  "paper account-show"
  "agent list-candidates"
)

refuse() {
  echo "REFUSED: not in read-only allowlist" >&2
  exit 2
}

# Empty args → refuse (no bare-CLI passthrough).
[ "$#" -ge 1 ] || refuse

one="$1"
two=""
if [ "$#" -ge 2 ]; then
  two="$1 $2"
fi

matched=""
for entry in "${READONLY_ALLOWLIST[@]}"; do
  if [ "$entry" = "$one" ] || { [ -n "$two" ] && [ "$entry" = "$two" ]; }; then
    matched=1
    break
  fi
done
[ -n "$matched" ] || refuse

cd "$PLATFORM_DIR"
exec "$PLATFORM_DIR/ai-quant/bin/quant-system" "$@"

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
# download data, run loops, start servers, write scan snapshots, or write
# candidate/approval files are deliberately EXCLUDED — those keep human
# approval. Two-word entries match the first two args (Typer subcommand groups);
# "doctor" is a single word.
#
# Audit F4 / D-25 purity: `options daily-scan` and `options buyside-screen` were
# removed — they write under data/options_scans/ and burn Futu quota. Full scans
# stay behind approval (or the dedicated collect cron wrapper).
set -euo pipefail
unset PYTHONPATH PYTHONHOME

PLATFORM_DIR="__HQA_PLATFORM_DIR__"

READONLY_ALLOWLIST=(
  "doctor"
  "config show"
  "data prices"
  "factor list"
  "paper account-show"
  "hermes paper-gate show"
)

refuse() {
  echo "REFUSED: not in read-only allowlist" >&2
  exit 2
}

# Empty args → refuse (no bare-CLI passthrough).
[ "$#" -ge 1 ] || refuse

# Exact Gate continuation read. The wrapper validates all three selectors and
# the fixed launcher encodes them into JSON stdin, so shell metacharacters can
# never become either an argv extension or a second command. No other
# paper-gate leaf is admitted.
if [ "$#" -eq 9 ] \
  && [ "$1" = "hermes" ] \
  && [ "$2" = "paper-gate" ] \
  && [ "$3" = "show" ] \
  && [ "$4" = "--gate-id" ] \
  && [[ "$5" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]] \
  && [ "$6" = "--workspace-id" ] \
  && [[ "$7" =~ ^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$ ]] \
  && [ "$8" = "--platform-session-id" ] \
  && [[ "$9" =~ ^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$ ]]; then
  SCRIPT_DIR="$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
  exec /usr/bin/python3 "$SCRIPT_DIR/hqa-paper-gate-show.py" "$5" "$7" "$9"
fi

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

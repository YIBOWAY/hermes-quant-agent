#!/bin/bash
# HQA async completion push wrapper (D-25 ①).
# Usage: hqa-notify.sh "<target>" "<message>"
#
# Pushes a task-completion notice to Discord through the no-LLM `hermes send`
# channel (bot-token delivery, no gateway/agent loop needed). If hermes is not
# on PATH OR delivery fails, the notice is NOT dropped: it is appended as one
# JSON line to logs/notify_fallback.jsonl (D-7 local-fallback pattern) and
# echoed to stdout, so a human/log still sees the result.
#
# __HQA_REPO_DIR__ (Hermes repo) is substituted by scripts/install.sh at deploy
# time so the fallback log resolves per-machine.
set -euo pipefail

REPO_DIR="__HQA_REPO_DIR__"

if [ "$#" -lt 2 ]; then
  echo "usage: hqa-notify.sh <target> <message>" >&2
  exit 2
fi

target="$1"
body="$2"
ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
message="[HQA] $ts $body"

# Map the caller's target to a hermes `--to` value: a bare `#channel` becomes a
# Discord channel; a bare platform word or an already-qualified `platform:...`
# target is passed through untouched.
case "$target" in
  discord|telegram|slack|signal) to="$target" ;;
  *:*) to="$target" ;;
  *) to="discord:$target" ;;
esac

# Primary path: no-LLM delivery via the configured Discord bot token. Guarded so
# `set -e` never aborts on a missing binary or a delivery error — either falls
# through to the local fallback below.
if command -v hermes >/dev/null 2>&1 && hermes send --to "$to" "$message"; then
  exit 0
fi

# Local fallback: persist + surface so the completion notice is never lost.
# python3 encodes the JSON so quotes/backslashes in the message can't corrupt
# the log line (same python3 dependency every HQA wrapper already relies on).
mkdir -p "$REPO_DIR/logs"
/usr/bin/env python3 -c '
import json, sys
ts, target, message = sys.argv[1:4]
print(json.dumps({"ts": ts, "target": target, "message": message}, ensure_ascii=False))
' "$ts" "$target" "$message" >> "$REPO_DIR/logs/notify_fallback.jsonl"
echo "$message"

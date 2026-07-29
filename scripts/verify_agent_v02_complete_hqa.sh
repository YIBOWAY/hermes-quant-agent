#!/bin/bash -p
set -euo pipefail
umask 077

fail() {
  echo "complete_hqa_error=$1" >&2
  exit 78
}

for argument in "$@"; do
  case "$argument" in
    --repository-root | --repository-root=* | \
      --public-entrypoint | --public-entrypoint=* | \
      --public-argv | --public-argv=*)
      fail "public_argument_forbidden"
      ;;
  esac
done

SCRIPT_SOURCE="${BASH_SOURCE[0]}"
if [[ "$SCRIPT_SOURCE" == /* ]]; then
  SCRIPT_ABSOLUTE="$SCRIPT_SOURCE"
else
  SCRIPT_ABSOLUTE="$(pwd -P)/$SCRIPT_SOURCE"
fi
[[ -f "$SCRIPT_ABSOLUTE" && ! -L "$SCRIPT_ABSOLUTE" ]] ||
  fail "script_unsafe"
SCRIPT_DIR="$(cd -P "$(dirname "$SCRIPT_ABSOLUTE")" && pwd -P)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"
SCRIPT_PATH="$SCRIPT_DIR/$(basename "$SCRIPT_SOURCE")"
HELPER="$SCRIPT_DIR/complete_hqa_gate.py"
[[ "$SCRIPT_PATH" == "$ROOT/scripts/verify_agent_v02_complete_hqa.sh" ]] ||
  fail "script_not_authoritative"
[[ -f "$HELPER" && ! -L "$HELPER" ]] || fail "helper_not_found"
[[ -x /usr/bin/python3 ]] || fail "system_python_not_found"

exec /usr/bin/env -i \
  HOME="/tmp" \
  LANG="C" \
  LC_ALL="C" \
  PATH="/usr/bin:/bin" \
  PYTHONNOUSERSITE="1" \
  TMPDIR="/tmp" \
  /usr/bin/python3 -I -B "$HELPER" \
  --repository-root "$ROOT" \
  --public-entrypoint "$SCRIPT_PATH" \
  --public-argv "$@"

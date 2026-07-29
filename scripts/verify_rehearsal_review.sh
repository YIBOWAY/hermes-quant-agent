#!/usr/bin/env bash
set -euo pipefail

fail() {
  echo "rehearsal_review_error=$1" >&2
  exit 78
}

for argument in "$@"; do
  case "$argument" in
    --hqa-root | --hqa-root=* | --public-entrypoint | --public-entrypoint=*)
      fail "public_argument_forbidden"
      ;;
  esac
done

SCRIPT_DIR="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"
HELPER="$SCRIPT_DIR/verify_rehearsal_review.py"
PYTHON="$ROOT/.venv/bin/python"

[[ -f "$HELPER" && ! -L "$HELPER" ]] || fail "helper_not_found"
[[ -x "$PYTHON" ]] || fail "python_not_found"

exec /usr/bin/env -i \
  HOME="/tmp" \
  LANG="C" \
  LC_ALL="C" \
  PATH="/usr/bin:/bin" \
  PYTHONNOUSERSITE="1" \
  TMPDIR="/tmp" \
  "$PYTHON" -I -B "$HELPER" \
  --hqa-root "$ROOT" \
  --public-entrypoint "$0" \
  "$@"

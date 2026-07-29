#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT/.venv/bin/python"
SANDBOX="/usr/bin/sandbox-exec"
PROFILE="(version 1) (allow default) (deny network*)"

if [[ ! -x "$PYTHON" ]]; then
  echo "hqa_backup_restore_error=python_not_executable" >&2
  exit 78
fi
if [[ ! -x "$SANDBOX" ]]; then
  echo "hqa_backup_restore_error=network_sandbox_unavailable" >&2
  exit 78
fi

exec "$SANDBOX" -p "$PROFILE" \
  /usr/bin/env -i \
  HOME=/var/empty \
  LANG=C \
  LC_ALL=C \
  PATH=/usr/bin:/bin \
  PYTHONNOUSERSITE=1 \
  "$PYTHON" -I -S -c \
  'import runpy,sys; root=sys.argv.pop(1); sys.path.insert(0,root); runpy.run_module("hqa.backup_restore_gate",run_name="__main__")' \
  "$ROOT" "$@"

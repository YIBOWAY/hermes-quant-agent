#!/bin/bash
# Deploy HQA cron wrappers into ~/.hermes/scripts/.
# Hermes requires scripts to physically reside there; symlinks and absolute
# paths are rejected by the scheduler's escape check, so we COPY the wrappers.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${HERMES_HOME:-$HOME/.hermes}/scripts"
mkdir -p "$DEST"
for src in "$REPO_DIR"/scripts/hermes/hqa-*.sh; do
  name="$(basename "$src")"
  rm -f "$DEST/$name"
  cp "$src" "$DEST/$name"
  chmod +x "$DEST/$name"
  echo "installed: $DEST/$name"
done

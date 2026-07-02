#!/bin/bash
# Deploy HQA cron wrappers into ~/.hermes/scripts/.
# Hermes requires scripts to physically reside there; symlinks and absolute
# paths are rejected by the scheduler's escape check, so we COPY the wrappers.
# The __HQA_REPO_DIR__ placeholder in each wrapper is replaced with the actual
# repo path at install time so the wrappers are portable across machines/users.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${HERMES_HOME:-$HOME/.hermes}/scripts"
mkdir -p "$DEST"
for src in "$REPO_DIR"/scripts/hermes/hqa-*.sh; do
  name="$(basename "$src")"
  rm -f "$DEST/$name"
  sed "s|__HQA_REPO_DIR__|$REPO_DIR|g" "$src" > "$DEST/$name"
  chmod +x "$DEST/$name"
  echo "installed: $DEST/$name"
done

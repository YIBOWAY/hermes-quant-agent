#!/bin/bash
# Deploy HQA cron wrappers into ~/.hermes/scripts/.
# Hermes requires scripts to physically reside there; symlinks and absolute
# paths are rejected by the scheduler's escape check, so we COPY the wrappers.
# __HQA_REPO_DIR__ (Hermes repo) and __HQA_PLATFORM_DIR__ (ai-quant-platform,
# from HQA_AIQP_DIR — matches hqa/config.py) are replaced at install time so
# the wrappers are portable across machines/users.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLATFORM_DIR="${HQA_AIQP_DIR:-/Users/sunyibo/programs/ai-quant-platform}"
DEST="${HERMES_HOME:-$HOME/.hermes}/scripts"
mkdir -p "$DEST"
for src in "$REPO_DIR"/scripts/hermes/hqa-*.sh; do
  name="$(basename "$src")"
  rm -f "$DEST/$name"
  sed -e "s|__HQA_REPO_DIR__|$REPO_DIR|g" \
      -e "s|__HQA_PLATFORM_DIR__|$PLATFORM_DIR|g" "$src" > "$DEST/$name"
  chmod +x "$DEST/$name"
  echo "installed: $DEST/$name"
done

# Deploy Hermes skill cards to ~/.hermes/skills/<name>/SKILL.md. Same placeholder
# substitution as the wrappers, plus __HERMES_SCRIPTS_DIR__ so the card can point
# Hermes at the deployed read-only gate / notifier wrappers by absolute path.
SKILLS_DEST="${HERMES_HOME:-$HOME/.hermes}/skills"
for card in "$REPO_DIR"/skills/hermes/*/SKILL.md; do
  [ -e "$card" ] || continue
  skill_name="$(basename "$(dirname "$card")")"
  mkdir -p "$SKILLS_DEST/$skill_name"
  sed -e "s|__HQA_REPO_DIR__|$REPO_DIR|g" \
      -e "s|__HQA_PLATFORM_DIR__|$PLATFORM_DIR|g" \
      -e "s|__HERMES_SCRIPTS_DIR__|$DEST|g" "$card" > "$SKILLS_DEST/$skill_name/SKILL.md"
  echo "installed: $SKILLS_DEST/$skill_name/SKILL.md"
done

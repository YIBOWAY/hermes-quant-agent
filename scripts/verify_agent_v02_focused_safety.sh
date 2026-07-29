#!/bin/bash -p
set -euo pipefail

export PATH="/usr/bin:/bin"
unset CDPATH

fail() {
  echo "hqa_focused_safety_error=$1" >&2
  exit 78
}

file_owner_and_mode() {
  local path="$1"
  if /usr/bin/stat -f "%u %Lp" "$path" >/dev/null 2>&1; then
    /usr/bin/stat -f "%u %Lp" "$path"
  else
    /usr/bin/stat -c "%u %a" "$path"
  fi
}

path_has_symlink_component() {
  local candidate="$1"
  local component
  local current=""
  local remainder="${candidate#/}"

  while [[ -n "$remainder" ]]; do
    if [[ "$remainder" == */* ]]; then
      component="${remainder%%/*}"
      remainder="${remainder#*/}"
    else
      component="$remainder"
      remainder=""
    fi
    [[ -z "$component" ]] && continue
    current="$current/$component"
    [[ -L "$current" ]] && return 0
  done
  return 1
}

path_is_canonical_absolute() {
  local candidate="$1"
  [[ "$candidate" == /* && "$candidate" != "/" && "$candidate" != */ ]] ||
    return 1
  case "$candidate" in
    *//* | */./* | */../* | */. | */..)
      return 1
      ;;
  esac
  return 0
}

require_safe_owned_mode() {
  local path="$1"
  local label="$2"
  local metadata
  local mode
  local owner
  local permissions

  metadata="$(file_owner_and_mode "$path")" ||
    fail "${label}_stat_failed"
  read -r owner mode <<<"$metadata"
  [[ "$owner" == "$(/usr/bin/id -u)" ]] ||
    fail "${label}_wrong_owner"
  [[ "$mode" =~ ^0?[0-7]{3}$ ]] || fail "${label}_mode_invalid"
  permissions="${mode#0}"
  case "${permissions:1:1}" in
    2 | 3 | 6 | 7)
      fail "${label}_unsafe_mode"
      ;;
  esac
  case "${permissions:2:1}" in
    2 | 3 | 6 | 7)
      fail "${label}_unsafe_mode"
      ;;
  esac
}

require_safe_regular_file() {
  local path="$1"
  local label="$2"
  [[ -f "$path" && ! -L "$path" ]] || fail "${label}_unsafe"
  require_safe_owned_mode "$path" "$label"
}

require_safe_directory() {
  local path="$1"
  local label="$2"
  [[ -d "$path" && ! -L "$path" ]] || fail "${label}_unsafe"
  require_safe_owned_mode "$path" "$label"
}

require_empty_output_path() {
  local path="$1"
  local label="$2"
  local parent

  path_is_canonical_absolute "$path" || fail "path_not_canonical"
  path_has_symlink_component "$path" && fail "${label}_unsafe"
  parent="$(dirname "$path")"
  require_safe_directory "$parent" "${label}_parent"
  if [[ -e "$path" || -L "$path" ]]; then
    require_safe_directory "$path" "$label"
    [[ -z "$(/usr/bin/find "$path" -mindepth 1 -maxdepth 1 -print -quit)" ]] ||
      fail "${label}_must_be_empty"
  fi
}

git_read() {
  /usr/bin/env -i \
    HOME="$SAFE_HOME" \
    LANG=C \
    LC_ALL=C \
    PATH="/usr/bin:/bin" \
    GIT_CONFIG_NOSYSTEM=1 \
    /usr/bin/git \
    --no-replace-objects \
    -c core.fsmonitor=false \
    -c core.hooksPath=/dev/null \
    -c credential.helper= \
    -C "$INTEGRATION_WORKTREE" \
    "$@"
}

capture_integration_identity() {
  local branch
  local common_directory
  local git_directory
  local head
  local remote
  local status_output
  local toplevel
  local tree

  toplevel="$(git_read rev-parse --show-toplevel)" ||
    fail "integration_git_invalid"
  [[ "$toplevel" == "$INTEGRATION_WORKTREE" ]] ||
    fail "integration_git_root_mismatch"
  branch="$(git_read branch --show-current)" ||
    fail "integration_git_invalid"
  [[ "$branch" == "codex/agent-v0-2-release" ]] ||
    fail "integration_branch_mismatch"
  remote="$(git_read remote get-url origin)" ||
    fail "integration_git_invalid"
  [[ "$remote" == "https://github.com/NousResearch/hermes-agent.git" ]] ||
    fail "integration_remote_mismatch"
  head="$(git_read rev-parse --verify HEAD^{commit})" ||
    fail "integration_git_invalid"
  tree="$(git_read rev-parse --verify HEAD^{tree})" ||
    fail "integration_git_invalid"
  [[ "$head" =~ ^[0-9a-f]{40}$ && "$tree" =~ ^[0-9a-f]{40}$ ]] ||
    fail "integration_git_invalid"
  status_output="$(git_read status --porcelain=v1 --untracked-files=all)" ||
    fail "integration_git_invalid"
  [[ -z "$status_output" ]] || fail "integration_dirty"

  common_directory="$(
    git_read rev-parse --path-format=absolute --git-common-dir
  )" || fail "integration_git_invalid"
  git_directory="$(
    git_read rev-parse --path-format=absolute --git-dir
  )" || fail "integration_git_invalid"
  path_is_canonical_absolute "$common_directory" ||
    fail "integration_git_invalid"
  path_is_canonical_absolute "$git_directory" ||
    fail "integration_git_invalid"
  path_has_symlink_component "$common_directory" &&
    fail "integration_git_unsafe"
  path_has_symlink_component "$git_directory" &&
    fail "integration_git_unsafe"
  require_safe_directory "$common_directory" "integration_git_common"
  require_safe_directory "$git_directory" "integration_git_directory"
  case "$common_directory" in
    "$HERMES_LIVE"/*)
      ;;
    *)
      fail "integration_git_outside_hermes"
      ;;
  esac
  case "$git_directory" in
    "$HERMES_LIVE"/*)
      ;;
    *)
      fail "integration_git_outside_hermes"
      ;;
  esac

  /usr/bin/printf '%s\n%s\n%s\n%s\n%s\n%s\n%s\n' \
    "$toplevel" \
    "$branch" \
    "$remote" \
    "$head" \
    "$tree" \
    "$common_directory" \
    "$git_directory"
}

[[ "$#" -eq 10 ]] || fail "arguments_invalid"
[[ "$1" == "--python" &&
  "$3" == "--basetemp" &&
  "$5" == "--hermes-live" &&
  "$7" == "--integration-worktree" &&
  "$9" == "--hermes-python" ]] ||
  fail "arguments_invalid"

PYTHON="$2"
BASETEMP="$4"
HERMES_LIVE="$6"
INTEGRATION_WORKTREE="$8"
HERMES_PYTHON="${10}"
path_is_canonical_absolute "$PYTHON" || fail "path_not_canonical"
path_is_canonical_absolute "$BASETEMP" || fail "path_not_canonical"
path_is_canonical_absolute "$HERMES_LIVE" || fail "path_not_canonical"
path_is_canonical_absolute "$INTEGRATION_WORKTREE" ||
  fail "path_not_canonical"
path_is_canonical_absolute "$HERMES_PYTHON" || fail "path_not_canonical"
SCRIPT_SOURCE="${BASH_SOURCE[0]}"
[[ ! -L "$SCRIPT_SOURCE" ]] || fail "script_unsafe"
if [[ "$SCRIPT_SOURCE" == /* ]]; then
  SCRIPT_SOURCE_ABSOLUTE="$SCRIPT_SOURCE"
else
  SCRIPT_SOURCE_ABSOLUTE="$(pwd -L)/$SCRIPT_SOURCE"
fi
path_has_symlink_component "$SCRIPT_SOURCE_ABSOLUTE" && fail "script_unsafe"
path_has_symlink_component "$PYTHON" && fail "python_unsafe"
path_has_symlink_component "$BASETEMP" && fail "basetemp_unsafe"
path_has_symlink_component "$HERMES_LIVE" && fail "hermes_live_unsafe"
path_has_symlink_component "$INTEGRATION_WORKTREE" &&
  fail "integration_worktree_unsafe"
path_has_symlink_component "$(dirname "$HERMES_PYTHON")" &&
  fail "hermes_python_unsafe"

SCRIPT_DIR="$(cd -P "$(dirname "$SCRIPT_SOURCE_ABSOLUTE")" && pwd -P)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"
SCRIPT_PATH="$SCRIPT_DIR/$(basename "$SCRIPT_SOURCE")"
[[ "$SCRIPT_PATH" == "$ROOT/scripts/verify_agent_v02_focused_safety.sh" ]] ||
  fail "script_not_authoritative"
require_safe_regular_file "$SCRIPT_PATH" "script"
[[ -x "$SCRIPT_PATH" ]] || fail "script_not_executable"
require_safe_directory "$ROOT" "release_root"
require_safe_directory "$SCRIPT_DIR" "scripts_directory"
require_safe_directory "$ROOT/tests" "tests_directory"
[[ "$PYTHON" == "$ROOT/.venv/"* ]] ||
  fail "python_must_be_release_local"
require_safe_regular_file "$PYTHON" "python"
[[ -x "$PYTHON" ]] || fail "python_not_executable"
PYTHON_DIRECTORY="$(dirname "$PYTHON")"
while [[ "$PYTHON_DIRECTORY" == "$ROOT/.venv" ||
  "$PYTHON_DIRECTORY" == "$ROOT/.venv/"* ]]; do
  require_safe_directory "$PYTHON_DIRECTORY" "python_directory"
  [[ "$PYTHON_DIRECTORY" == "$ROOT/.venv" ]] && break
  PYTHON_DIRECTORY="$(dirname "$PYTHON_DIRECTORY")"
done
[[ "$PYTHON_DIRECTORY" == "$ROOT/.venv" ]] ||
  fail "python_must_be_release_local"
[[ "$INTEGRATION_WORKTREE" == \
  "$HERMES_LIVE/.claude/worktrees/v2-integration" ]] ||
  fail "integration_worktree_not_authoritative"
[[ "$HERMES_PYTHON" == "$HERMES_LIVE/venv/bin/python" ]] ||
  fail "hermes_python_not_authoritative"
require_safe_directory "$HERMES_LIVE" "hermes_live"
require_safe_directory "$INTEGRATION_WORKTREE" "integration_worktree"
require_safe_regular_file \
  "$INTEGRATION_WORKTREE/gateway/run.py" \
  "integration_gateway"
[[ -f "$HERMES_PYTHON" && -x "$HERMES_PYTHON" ]] ||
  fail "hermes_python_unsafe"
if [[ -L "$HERMES_PYTHON" ]]; then
  require_safe_owned_mode "$HERMES_PYTHON" "hermes_python_link"
fi
HERMES_PYTHON_TARGET="$(/bin/realpath "$HERMES_PYTHON")" ||
  fail "hermes_python_unsafe"
path_is_canonical_absolute "$HERMES_PYTHON_TARGET" ||
  fail "hermes_python_unsafe"
path_has_symlink_component "$HERMES_PYTHON_TARGET" &&
  fail "hermes_python_target_unsafe"
require_safe_regular_file "$HERMES_PYTHON_TARGET" "hermes_python_target"
[[ -x "$HERMES_PYTHON_TARGET" ]] || fail "hermes_python_not_executable"
case "$BASETEMP" in
  "$ROOT" | "$ROOT"/*)
    fail "basetemp_must_be_external"
    ;;
esac
require_empty_output_path "$BASETEMP" "basetemp"
PYCACHE_ROOT="${BASETEMP}.pycache"
require_empty_output_path "$PYCACHE_ROOT" "pycache"
SAFE_HOME="${BASETEMP}.home"
SAFE_TMP="${BASETEMP}.tmp"
require_empty_output_path "$SAFE_HOME" "home"
require_empty_output_path "$SAFE_TMP" "tmp"
[[ ! -e "$SAFE_HOME" && ! -L "$SAFE_HOME" ]] ||
  fail "home_must_not_exist"
[[ ! -e "$SAFE_TMP" && ! -L "$SAFE_TMP" ]] ||
  fail "tmp_must_not_exist"

SELECTORS=(
  tests/test_gate.py
  tests/test_gate_cli.py
  tests/test_hermes_run_acceptance.py
  tests/test_hermes_run_acceptance_live.py
  tests/test_hermes_run_adapter.py
  tests/test_hermes_run_cli.py
  tests/test_intent_workflow.py
  tests/test_paper_gate_cli.py
  tests/test_release_evidence.py
  tests/test_release_manifest.py
  tests/test_release_process_boundaries.py
  tests/test_research_workflow_saga.py
  tests/test_workflow_authority.py
  tests/test_workflow_contract.py
)

for selector in "${SELECTORS[@]}"; do
  path_has_symlink_component "$ROOT/$selector" && fail "selector_unsafe"
  require_safe_regular_file "$ROOT/$selector" "selector"
done

HOME_CREATED=false
TMP_CREATED=false
cleanup_transient() {
  local exit_code=$?
  trap - EXIT
  if [[ "$TMP_CREATED" == true ]]; then
    /bin/rm -R "$SAFE_TMP" || {
      echo "hqa_focused_safety_error=tmp_cleanup_failed" >&2
      exit 78
    }
  fi
  if [[ "$HOME_CREATED" == true ]]; then
    /bin/rm -R "$SAFE_HOME" || {
      echo "hqa_focused_safety_error=home_cleanup_failed" >&2
      exit 78
    }
  fi
  exit "$exit_code"
}
trap cleanup_transient EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

/bin/mkdir -m 0700 "$SAFE_HOME"
HOME_CREATED=true
require_safe_directory "$SAFE_HOME" "home"
/bin/mkdir -m 0700 "$SAFE_TMP"
TMP_CREATED=true
require_safe_directory "$SAFE_TMP" "tmp"

INTEGRATION_IDENTITY_BEFORE="$(capture_integration_identity)" ||
  fail "integration_identity_failed"

cd "$ROOT"
umask 077

set +e
/usr/bin/env -i \
  HOME="$SAFE_HOME" \
  HQA_HERMES_INTEGRATION_WT="$INTEGRATION_WORKTREE" \
  HQA_HERMES_LIVE="$HERMES_LIVE" \
  HQA_HERMES_VENV_PYTHON="$HERMES_PYTHON" \
  LANG=C.UTF-8 \
  LC_ALL=C.UTF-8 \
  PATH="$(dirname "$PYTHON"):/usr/bin:/bin" \
  HQA_PROVIDER_ACCESS=disabled \
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  PYTHONNOUSERSITE=1 \
  PYTHONPYCACHEPREFIX="$PYCACHE_ROOT" \
  TEMP="$SAFE_TMP" \
  TMP="$SAFE_TMP" \
  TMPDIR="$SAFE_TMP" \
  QS_DATABASE_AUTO_MIGRATE=false \
  QS_DATABASE_ENABLED=false \
  QS_DEFAULT_DATA_PROVIDER=sample \
  QS_FUTU_ENABLED=false \
  QS_KILL_SWITCH=true \
  QS_LIVE_TRADING_ENABLED=false \
  "$PYTHON" \
  -X int_max_str_digits=0 \
  -I \
  -m pytest \
  -q \
  "--basetemp=$BASETEMP" \
  "${SELECTORS[@]}"
PYTEST_EXIT=$?
set -e

[[ "$(/bin/realpath "$HERMES_PYTHON")" == "$HERMES_PYTHON_TARGET" ]] ||
  fail "hermes_python_changed"
require_safe_regular_file "$HERMES_PYTHON_TARGET" "hermes_python_target"
INTEGRATION_IDENTITY_AFTER="$(capture_integration_identity)" ||
  fail "integration_identity_failed"
[[ "$INTEGRATION_IDENTITY_AFTER" == "$INTEGRATION_IDENTITY_BEFORE" ]] ||
  fail "integration_identity_changed"
exit "$PYTEST_EXIT"

#!/bin/bash
# HQA entrypoint for the platform-owned Hermes command connector.
#
# This wrapper is deliberately pinned to one platform CLI leaf.  It can run a
# one-shot reconciliation cycle (`--once`) or forward lifecycle flags for the
# deterministic loop, but it cannot select another platform command.  The
# delivered worker reconciles PostgreSQL-owned command facts only; this shell
# does not read a prompt, provider credential, bearer token, or secret.
#
# __HQA_PLATFORM_DIR__ is substituted by scripts/install.sh at deploy time.
set -euo pipefail
unset PYTHONPATH PYTHONHOME

PLATFORM_DIR="__HQA_PLATFORM_DIR__"

refuse() {
  # Never echo the rejected value: it may itself be sensitive input.
  echo "REFUSED: unsupported connector-worker argument" >&2
  exit 2
}

forward=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    --once|--help)
      forward+=("$1")
      shift
      ;;
    --poll-interval-seconds)
      [ "$#" -ge 2 ] || refuse
      [[ "$2" =~ ^[0-9]+([.][0-9]+)?$ ]] || refuse
      forward+=("$1" "$2")
      shift 2
      ;;
    --max-cycles|--reconcile-limit)
      [ "$#" -ge 2 ] || refuse
      [[ "$2" =~ ^[1-9][0-9]*$ ]] || refuse
      forward+=("$1" "$2")
      shift 2
      ;;
    --mode)
      [ "$#" -ge 2 ] || refuse
      case "$2" in
        reconcile_only|supervised_dispatch) ;;
        *) refuse ;;
      esac
      forward+=("$1" "$2")
      shift 2
      ;;
    --worker-id)
      [ "$#" -ge 2 ] || refuse
      [[ "$2" =~ ^[A-Za-z0-9._-]{1,64}$ ]] || refuse
      forward+=("$1" "$2")
      shift 2
      ;;
    --fixed-input)
      [ "$#" -ge 2 ] || refuse
      # Bound length without echoing the value.
      if [ "${#2}" -lt 1 ] || [ "${#2}" -gt 4096 ]; then
        refuse
      fi
      forward+=("$1" "$2")
      shift 2
      ;;
    *)
      refuse
      ;;
  esac
done

cd "$PLATFORM_DIR"
exec "$PLATFORM_DIR/ai-quant/bin/quant-system" \
  hermes connector-worker "${forward[@]}"

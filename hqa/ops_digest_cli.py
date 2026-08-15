"""CLI for hqa ops digest intake.

Usage:
  python -m hqa.ops_digest_cli ingest < receipt.json
"""

from __future__ import annotations

import json
import sys

from hqa.ops_digest import OpsDigestError, ingest_observation


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] != "ingest":
        sys.stderr.write("usage: python -m hqa.ops_digest_cli ingest < receipt.json\n")
        return 2
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.stdout.write(json.dumps({"ok": False, "code": "observation_receipt_required"}) + "\n")
        return 2
    try:
        receipt = ingest_observation(payload)
    except OpsDigestError as exc:
        sys.stdout.write(json.dumps({"ok": False, "code": exc.code}) + "\n")
        return 2
    sys.stdout.write(json.dumps({"ok": True, **receipt}, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

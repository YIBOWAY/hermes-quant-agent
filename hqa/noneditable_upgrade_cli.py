"""Repository-authoritative CLI for the HQA non-editable upgrade rehearsal."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Sequence

from hqa.noneditable_upgrade import (
    CANONICAL_AUTHORITY,
    NoneditableUpgradeError,
    verify_noneditable_upgrade,
)


_BOOTSTRAP_FIELDS = {
    "archive_sha256",
    "commit",
    "repository_root",
    "schema_version",
    "source_file_count",
    "source_manifest_sha256",
    "tree",
    "wrapper_sha256",
}


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _read_bootstrap(path: Path, expected_sha256: str) -> dict[str, object]:
    if re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
        raise NoneditableUpgradeError("bootstrap authority digest is malformed")
    metadata = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_nlink != 1
    ):
        raise NoneditableUpgradeError("bootstrap authority is not a private file")
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise NoneditableUpgradeError("bootstrap authority digest changed")
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NoneditableUpgradeError("bootstrap authority is not JSON") from exc
    if (
        not isinstance(document, dict)
        or set(document) != _BOOTSTRAP_FIELDS
        or document.get("schema_version")
        != "hqa.noneditable-upgrade-bootstrap.v1"
        or _canonical_json_bytes(document) != payload
        or document.get("repository_root")
        != str(CANONICAL_AUTHORITY.absolute_checkout_path)
        or not isinstance(document.get("source_file_count"), int)
        or document["source_file_count"] <= 0
    ):
        raise NoneditableUpgradeError("bootstrap authority fields are invalid")
    for field in (
        "archive_sha256",
        "source_manifest_sha256",
        "wrapper_sha256",
    ):
        if re.fullmatch(r"[0-9a-f]{64}", str(document.get(field))) is None:
            raise NoneditableUpgradeError("bootstrap authority digest is invalid")
    for field in ("commit", "tree"):
        if re.fullmatch(
            r"[0-9a-f]{40}|[0-9a-f]{64}",
            str(document.get(field)),
        ) is None:
            raise NoneditableUpgradeError("bootstrap Git identity is invalid")
    return document


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scripts/verify_agent_v02_noneditable_upgrade.sh",
        description=(
            "Run the exact published-baseline to final offline, non-editable "
            "HQA upgrade/import/CLI-smoke rehearsal."
        ),
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--bootstrap-authority", help=argparse.SUPPRESS)
    parser.add_argument("--bootstrap-authority-sha256", help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.bootstrap_authority or not args.bootstrap_authority_sha256:
        raise NoneditableUpgradeError(
            "use the repository verification script, not the module directly"
        )
    bootstrap = _read_bootstrap(
        Path(args.bootstrap_authority),
        args.bootstrap_authority_sha256,
    )
    result = verify_noneditable_upgrade(
        repository_root=CANONICAL_AUTHORITY.absolute_checkout_path,
        output_dir=Path(args.output_dir),
        authority=CANONICAL_AUTHORITY,
        bootstrap_authority=bootstrap,
    )
    print(
        json.dumps(
            {
                "commit": result["repository_after"]["commit"],
                "receipt": str(
                    Path(args.output_dir).resolve()
                    / "noneditable-upgrade-receipt.json"
                ),
                "status": result["status"],
                "tree": result["repository_after"]["tree"],
            },
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

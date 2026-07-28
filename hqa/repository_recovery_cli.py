"""CLI for repository recovery packages, restore receipts and detached roots."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hqa.detached_manifest import build_manifest, verify_manifest
from hqa.repository_recovery import (
    capture_and_drill_closure_repository,
    capture_repository,
    restore_drill,
    verify_closure_package,
    verify_package,
    verify_receipt,
)


def _emit(value: object) -> None:
    print(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m hqa.repository_recovery_cli")
    commands = parser.add_subparsers(dest="command", required=True)

    capture = commands.add_parser("capture")
    capture.add_argument("--repository", required=True)
    capture.add_argument("--package", required=True)

    verify = commands.add_parser("verify-package")
    verify.add_argument("--package", required=True)

    closure = commands.add_parser("capture-closure-v2")
    closure.add_argument("--repository", required=True)
    closure.add_argument("--repository-id", required=True)
    closure.add_argument("--publication-url", required=True)
    closure.add_argument("--publication-remote-name", required=True)
    closure.add_argument("--operator-identity", required=True)
    closure.add_argument("--package", required=True)
    closure.add_argument("--first-destination", required=True)
    closure.add_argument("--second-destination", required=True)
    closure.add_argument("--rehearsal-patch", required=True)
    closure.add_argument("--rehearsal-patch-sha256", required=True)

    verify_closure = commands.add_parser("verify-closure-v2")
    verify_closure.add_argument("--package", required=True)

    drill = commands.add_parser("drill")
    drill.add_argument("--package", required=True)
    drill.add_argument("--destination", required=True)
    drill.add_argument("--receipt", required=True)

    receipt = commands.add_parser("verify-receipt")
    receipt.add_argument("--package", required=True)
    receipt.add_argument("--receipt", required=True)

    seal = commands.add_parser("build-detached-manifest")
    seal.add_argument("--root", required=True)

    verify_seal = commands.add_parser("verify-detached-manifest")
    verify_seal.add_argument("--root", required=True)

    args = parser.parse_args()
    exit_code = 0
    if args.command == "capture":
        result = capture_repository(Path(args.repository), Path(args.package))
    elif args.command == "verify-package":
        result = verify_package(Path(args.package))
    elif args.command == "capture-closure-v2":
        result = capture_and_drill_closure_repository(
            Path(args.repository),
            Path(args.package),
            Path(args.first_destination),
            Path(args.second_destination),
            Path(args.rehearsal_patch),
            rehearsal_patch_sha256=args.rehearsal_patch_sha256,
            repository_id=args.repository_id,
            publication_url=args.publication_url,
            publication_remote_name=args.publication_remote_name,
            operator_identity=args.operator_identity,
        )
        if result["restore_verified"] is not True:
            exit_code = 2
    elif args.command == "verify-closure-v2":
        result = verify_closure_package(Path(args.package))
        if result["restore_verified"] is not True:
            exit_code = 2
    elif args.command == "drill":
        result = restore_drill(
            Path(args.package),
            Path(args.destination),
            Path(args.receipt),
        )
    elif args.command == "verify-receipt":
        result = verify_receipt(Path(args.package), Path(args.receipt))
    elif args.command == "build-detached-manifest":
        manifest = build_manifest(Path(args.root))
        result = {"manifest": str(manifest), **verify_manifest(Path(args.root))}
    else:
        result = verify_manifest(Path(args.root))
    _emit(result)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

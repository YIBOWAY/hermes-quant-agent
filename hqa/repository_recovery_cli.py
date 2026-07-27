"""CLI for repository recovery packages, restore receipts and detached roots."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hqa.detached_manifest import build_manifest, verify_manifest
from hqa.repository_recovery import (
    capture_repository,
    restore_drill,
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
    if args.command == "capture":
        result = capture_repository(Path(args.repository), Path(args.package))
    elif args.command == "verify-package":
        result = verify_package(Path(args.package))
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from hqa import config
from hqa.hermes_capabilities import (
    CapabilityContractError,
    evaluate_chat_gate,
    load_capabilities,
)


class _ArgumentError(ValueError):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _ArgumentError(message)


def _emit(document: dict) -> None:
    sys.stdout.write(
        json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="hqa-hermes-capabilities")
    sub = parser.add_subparsers(dest="command", required=True)
    show = sub.add_parser("show")
    show.add_argument(
        "--contract",
        type=Path,
        default=config.HERMES_GATEWAY_CAPABILITIES_PATH,
    )
    sub.add_parser("verify-chat")
    return parser


def _read(path: Path) -> dict:
    capabilities = load_capabilities(path)
    gate = evaluate_chat_gate(capabilities)
    contract = asdict(capabilities)
    contract["relevant_methods_observed"] = sorted(
        capabilities.relevant_methods_observed
    )
    return {"contract": contract, "declared_gate": gate.to_dict()}


def _git_bytes(*args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(config.REPO_DIR), *args],
        check=True,
        capture_output=True,
        shell=False,
        timeout=5,
    ).stdout


def _probe_review(contract_path: Path) -> dict:
    if contract_path != config.HERMES_GATEWAY_CAPABILITIES_PATH:
        return {
            "trusted": False,
            "verdict": "unreviewed",
            "blocker": "custom_contract_unreviewed",
        }
    try:
        contract_bytes = contract_path.read_bytes()
        review_bytes = config.HERMES_GATEWAY_REVIEW_PATH.read_bytes()
        review = json.loads(review_bytes.decode("utf-8"))
        if not isinstance(review, dict) or set(review) != {
            "schema_version",
            "contract_sha256",
            "reviewed_commit",
            "reviewed_at",
            "verdict",
            "reason",
        }:
            raise ValueError("invalid review schema")
        if review["schema_version"] != "1.0" or review["verdict"] not in {
            "blocked",
            "ready",
        }:
            raise ValueError("unsupported review")
        digest = hashlib.sha256(contract_bytes).hexdigest()
        if (
            not re.fullmatch(r"[0-9a-f]{64}", str(review["contract_sha256"]))
            or review["contract_sha256"] != digest
            or not re.fullmatch(r"[0-9a-f]{40}", str(review["reviewed_commit"]))
            or not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z",
                str(review["reviewed_at"]),
            )
            or not isinstance(review["reason"], str)
            or not review["reason"].strip()
        ):
            raise ValueError("invalid review identity")
        contract_rel = contract_path.relative_to(config.REPO_DIR).as_posix()
        review_rel = config.HERMES_GATEWAY_REVIEW_PATH.relative_to(
            config.REPO_DIR
        ).as_posix()
        ancestor = subprocess.run(
            [
                "git",
                "-C",
                str(config.REPO_DIR),
                "merge-base",
                "--is-ancestor",
                str(review["reviewed_commit"]),
                "HEAD",
            ],
            check=False,
            capture_output=True,
            shell=False,
            timeout=5,
        )
        if ancestor.returncode != 0:
            raise ValueError("reviewed commit is not an ancestor")
        if _git_bytes("show", f"HEAD:{contract_rel}") != contract_bytes:
            raise ValueError("contract is not checked in at HEAD")
        if _git_bytes("show", f'{review["reviewed_commit"]}:{contract_rel}') != contract_bytes:
            raise ValueError("reviewed contract differs")
        if _git_bytes("show", f"HEAD:{review_rel}") != review_bytes:
            raise ValueError("review record is not checked in")
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
        subprocess.SubprocessError,
    ):
        return {
            "trusted": False,
            "verdict": "unreviewed",
            "blocker": "contract_unreviewed",
        }
    verdict = str(review["verdict"])
    return {
        "trusted": True,
        "verdict": verdict,
        "blocker": None if verdict == "ready" else "contract_review_blocked",
        "contract_sha256": str(review["contract_sha256"]),
        "reviewed_commit": str(review["reviewed_commit"]),
    }


def _append_blocker(values: list[str], blocker: str) -> list[str]:
    return values if blocker in values else [*values, blocker]


def _close_gate(gate: dict, blocker: str, *, close_read: bool) -> dict:
    closed = {
        **gate,
        "chat_write_enabled": False,
        "stream_enabled": False,
        "resume_enabled": False,
        "approval_enabled": False,
        "stop_enabled": False,
    }
    if close_read:
        closed["chat_read_enabled"] = False
    for field in (
        "blockers",
        "resume_blockers",
        "approval_blockers",
        "stop_blockers",
    ):
        closed[field] = _append_blocker(list(closed.get(field, [])), blocker)
    return closed


def _apply_review_gate(document: dict, contract_path: Path) -> dict:
    review = _probe_review(contract_path)
    gate = dict(document["declared_gate"])
    blocker = review["blocker"]
    if blocker is not None:
        gate = _close_gate(gate, blocker, close_read=not review["trusted"])
    return {
        **document,
        "snapshot_readable": True,
        "gate": gate,
        "review": review,
    }


def _probe_installation() -> dict:
    version = subprocess.run(
        [str(config.HERMES_BIN_PATH), "--version"],
        check=True,
        capture_output=True,
        text=True,
        shell=False,
        timeout=5,
    ).stdout
    match = re.search(
        r"^Hermes Agent v(?P<version>\S+).*upstream (?P<upstream>[0-9a-f]+)$",
        version,
        flags=re.MULTILINE,
    )
    if match is None:
        raise ValueError("unrecognized Hermes version output")
    checkout = subprocess.run(
        ["git", "-C", str(config.HERMES_SOURCE_DIR), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        shell=False,
        timeout=5,
    ).stdout.strip()
    tracked_status = subprocess.run(
        [
            "git",
            "-C",
            str(config.HERMES_SOURCE_DIR),
            "status",
            "--porcelain",
            "--untracked-files=no",
        ],
        check=True,
        capture_output=True,
        text=True,
        shell=False,
        timeout=5,
    ).stdout
    server_bytes = (config.HERMES_SOURCE_DIR / "tui_gateway" / "server.py").read_bytes()
    return {
        "hermes_version": match.group("version"),
        "upstream_commit": match.group("upstream"),
        "source_checkout_commit": checkout,
        "server_source_sha256": hashlib.sha256(server_bytes).hexdigest(),
        "source_tracked_clean": not tracked_status.strip(),
    }


def _apply_installation_gate(document: dict) -> dict:
    expected = {
        key: document["contract"][key]
        for key in (
            "hermes_version",
            "upstream_commit",
            "source_checkout_commit",
            "server_source_sha256",
        )
    }
    try:
        actual = _probe_installation()
        actual_identity = {key: actual.get(key) for key in expected}
        if actual.get("source_tracked_clean") is not True:
            blocker = "installation_source_dirty"
        else:
            blocker = (
                None
                if actual_identity == expected
                else "installation_fingerprint_mismatch"
            )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        actual = {"error": type(exc).__name__}
        blocker = "installation_probe_failed"
    gate = document["gate"]
    if blocker is not None:
        gate = _close_gate(gate, blocker, close_read=True)
    return {
        **document,
        "gate": gate,
        "installation": {"matches_snapshot": blocker is None, "actual": actual},
    }


def main(argv: Optional[list[str]] = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except _ArgumentError as exc:
        _emit({"error": {"code": "invalid_arguments", "message": str(exc)}})
        return 2
    try:
        contract_path = (
            args.contract
            if args.command == "show"
            else config.HERMES_GATEWAY_CAPABILITIES_PATH
        )
        document = _read(contract_path)
        document = _apply_review_gate(document, contract_path)
        document = _apply_installation_gate(document)
    except CapabilityContractError as exc:
        _emit({"error": {"code": "capability_contract_invalid", "message": str(exc)}})
        return 1
    if args.command == "show":
        _emit(document)
        return 0
    enabled = (
        document["gate"]["chat_write_enabled"] is True
        and document["gate"]["stream_enabled"] is True
    )
    _emit({"status": "ready" if enabled else "blocked", **document})
    return 0 if enabled else 3


if __name__ == "__main__":
    raise SystemExit(main())

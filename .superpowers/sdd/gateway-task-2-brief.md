### Task 2: JSON-only capability CLI

**Files:**

- Create: <code>tests/test_hermes_capability_cli.py</code>
- Create: <code>hqa/hermes_capability_cli.py</code>
- Modify: <code>hqa/config.py</code> to add the fixed review-record path if it was not committed in Task 1.

**Interfaces:**

- Consumes: <code>config.HERMES_GATEWAY_CAPABILITIES_PATH</code>, the fixed <code>config.HERMES_GATEWAY_REVIEW_PATH</code>, and the local Hermes binary/source fingerprint. Only <code>show</code> accepts an optional diagnostic <code>--contract</code>; <code>verify-chat</code> always uses the default contract.
- Produces: one strict JSON document and exit 0 for <code>show</code>; exit 0/3 for safe/blocked <code>verify-chat</code>; exit 1/2 for contract/argument failures. The effective gate is fail-closed after review provenance and installation comparison. Bridge admission requires both write and stream gates; approval, stop, and resume remain independent.

- [ ] **Step 1: Write the failing CLI tests**

~~~python
from __future__ import annotations

import json

from hqa import hermes_capability_cli


def _contract() -> dict:
    return {
        "hermes_version": "0.18.2",
        "upstream_commit": "e4ea0a0e",
        "source_checkout_commit": "4281151ae859241351ba14d8c7682dc67ff4c126",
        "server_source_sha256": "2a05d8979ee3e4edb0e534f4db1c421d2064f36c8290234c3cf1496365ba7d17",
        "source_tracked_clean": True,
    }


def _gate(*, write: bool, stream: bool, read: bool = True) -> dict:
    blocker = [] if write else ["missing_request_recovery"]
    return {
        "chat_read_enabled": read,
        "chat_write_enabled": write,
        "stream_enabled": stream,
        "resume_enabled": stream,
        "approval_enabled": False,
        "stop_enabled": False,
        "blockers": blocker + ([] if stream or not write else ["missing_event_replay"]),
        "resume_blockers": blocker + ([] if stream else ["missing_event_replay"]),
        "approval_blockers": ["missing_approval_binding"],
        "stop_blockers": ["missing_stop_contract"],
    }


def _install_declared(monkeypatch, gate: dict) -> None:
    monkeypatch.setattr(
        hermes_capability_cli,
        "_read",
        lambda _path: {"contract": _contract(), "declared_gate": gate},
    )
    monkeypatch.setattr(hermes_capability_cli, "_probe_installation", _contract)


def test_custom_show_is_diagnostic_but_never_authoritative(
    monkeypatch, capsys, tmp_path
) -> None:
    contract = tmp_path / "capabilities.json"
    contract.write_text("{}", encoding="utf-8")
    _install_declared(monkeypatch, _gate(write=True, stream=True))
    monkeypatch.setattr(
        hermes_capability_cli,
        "_probe_review",
        lambda _path: {
            "trusted": False,
            "verdict": "unreviewed",
            "blocker": "custom_contract_unreviewed",
        },
    )

    assert hermes_capability_cli.main(["show", "--contract", str(contract)]) == 0
    document = json.loads(capsys.readouterr().out)
    assert document["snapshot_readable"] is True
    assert document["declared_gate"]["chat_write_enabled"] is True
    assert document["gate"]["chat_read_enabled"] is False
    assert document["gate"]["chat_write_enabled"] is False
    assert "custom_contract_unreviewed" in document["gate"]["blockers"]


def test_verify_chat_returns_three_for_known_blocked_contract(monkeypatch, capsys) -> None:
    _install_declared(monkeypatch, _gate(write=False, stream=False))
    monkeypatch.setattr(
        hermes_capability_cli,
        "_probe_review",
        lambda _path: {
            "trusted": True,
            "verdict": "blocked",
            "blocker": "contract_review_blocked",
        },
    )

    assert hermes_capability_cli.main(["verify-chat"]) == 3
    document = json.loads(capsys.readouterr().out)
    assert document["status"] == "blocked"
    assert document["gate"]["chat_read_enabled"] is True


def test_verify_chat_requires_replay_even_when_submit_is_safe(monkeypatch, capsys) -> None:
    _install_declared(monkeypatch, _gate(write=True, stream=False))
    monkeypatch.setattr(
        hermes_capability_cli,
        "_probe_review",
        lambda _path: {"trusted": True, "verdict": "ready", "blocker": None},
    )

    assert hermes_capability_cli.main(["verify-chat"]) == 3
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"


def test_ready_review_and_matching_installation_open_bridge_admission(
    monkeypatch, capsys
) -> None:
    _install_declared(monkeypatch, _gate(write=True, stream=True))
    monkeypatch.setattr(
        hermes_capability_cli,
        "_probe_review",
        lambda _path: {"trusted": True, "verdict": "ready", "blocker": None},
    )

    assert hermes_capability_cli.main(["verify-chat"]) == 0
    document = json.loads(capsys.readouterr().out)
    assert document["status"] == "ready"
    # Approval and stop are independent from ordinary safe chat admission.
    assert document["gate"]["approval_enabled"] is False
    assert document["gate"]["stop_enabled"] is False


def test_matching_ready_snapshot_stays_blocked_when_installation_drifted(
    monkeypatch, capsys
) -> None:
    _install_declared(monkeypatch, _gate(write=True, stream=True))
    monkeypatch.setattr(
        hermes_capability_cli,
        "_probe_review",
        lambda _path: {"trusted": True, "verdict": "ready", "blocker": None},
    )
    monkeypatch.setattr(
        hermes_capability_cli,
        "_probe_installation",
        lambda: {**_contract(), "server_source_sha256": "0" * 64},
    )

    assert hermes_capability_cli.main(["verify-chat"]) == 3
    document = json.loads(capsys.readouterr().out)
    assert document["gate"]["chat_read_enabled"] is False
    assert document["gate"]["chat_write_enabled"] is False
    assert "installation_fingerprint_mismatch" in document["gate"]["blockers"]


def test_missing_review_closes_reads_and_writes(monkeypatch, capsys) -> None:
    _install_declared(monkeypatch, _gate(write=True, stream=True))
    monkeypatch.setattr(
        hermes_capability_cli,
        "_probe_review",
        lambda _path: {
            "trusted": False,
            "verdict": "unreviewed",
            "blocker": "contract_unreviewed",
        },
    )

    assert hermes_capability_cli.main(["verify-chat"]) == 3
    gate = json.loads(capsys.readouterr().out)["gate"]
    assert gate["chat_read_enabled"] is False
    assert gate["chat_write_enabled"] is False


def test_tracked_source_dirty_closes_reads_and_writes(monkeypatch, capsys) -> None:
    _install_declared(monkeypatch, _gate(write=True, stream=True))
    monkeypatch.setattr(
        hermes_capability_cli,
        "_probe_review",
        lambda _path: {"trusted": True, "verdict": "ready", "blocker": None},
    )
    monkeypatch.setattr(
        hermes_capability_cli,
        "_probe_installation",
        lambda: {**_contract(), "source_tracked_clean": False},
    )

    assert hermes_capability_cli.main(["verify-chat"]) == 3
    gate = json.loads(capsys.readouterr().out)["gate"]
    assert gate["chat_read_enabled"] is False
    assert "installation_source_dirty" in gate["blockers"]


def test_verify_chat_rejects_contract_override(capsys) -> None:
    assert hermes_capability_cli.main(
        ["verify-chat", "--contract", "/tmp/all-true.json"]
    ) == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "invalid_arguments"
~~~

Also add table-driven tests for <code>_probe_review</code> that use a temporary Git repository and reject: missing/unknown review fields, an invalid digest or commit, contract bytes that differ from <code>contract_sha256</code>, a reviewed commit that is not an ancestor of HEAD, contract bytes at the reviewed commit that differ from the working default contract, working default-contract bytes that differ from the checked-in HEAD blob even when they match an older reviewed ancestor, and review-record bytes that differ from the checked-in HEAD blob. Add a probe-exception test proving <code>installation_probe_failed</code> closes reads and every mutation gate without leaking subprocess stderr.

- [ ] **Step 2: Run the focused test and confirm RED**

Run: <code>./.venv/bin/pytest -q tests/test_hermes_capability_cli.py</code>

Expected: collection fails because <code>hqa.hermes_capability_cli</code> does not exist.

- [ ] **Step 3: Implement the CLI without service or provider calls**

Create <code>hqa/hermes_capability_cli.py</code>:

~~~python
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
~~~

- [ ] **Step 4: Run CLI tests and live read-only display**

Run:

~~~bash
./.venv/bin/pytest -q tests/test_hermes_capability_cli.py
./.venv/bin/python -m hqa.hermes_capability_cli show
./.venv/bin/python -m hqa.hermes_capability_cli verify-chat
~~~

Expected before Task 4: tests pass; <code>show</code> exits 0, reports <code>snapshot_readable=true</code> and <code>installation.matches_snapshot=true</code>, but the effective read/write gates remain closed with <code>contract_unreviewed</code>. <code>verify-chat</code> exits 3. No Hermes session appears and no provider usage changes.

- [ ] **Step 5: Commit the CLI**

~~~bash
git add hqa/config.py hqa/hermes_capability_cli.py tests/test_hermes_capability_cli.py
git commit -m "feat(hqa): expose Hermes chat readiness as strict JSON"
~~~

---


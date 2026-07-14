from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from hqa import config, hermes_capability_cli


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


def test_banner_upstream_drift_does_not_close_matching_local_fingerprint(
    monkeypatch, capsys
) -> None:
    """Hermes banner 'upstream' is origin/main tip; remote fetch must not fail local match."""
    _install_declared(monkeypatch, _gate(write=True, stream=True))
    monkeypatch.setattr(
        hermes_capability_cli,
        "_probe_review",
        lambda _path: {"trusted": True, "verdict": "ready", "blocker": None},
    )
    monkeypatch.setattr(
        hermes_capability_cli,
        "_probe_installation",
        lambda: {
            **_contract(),
            # Banner remote tip advanced; pinned checkout + server bytes unchanged.
            "upstream_commit": "226e8de8",
            "banner_upstream_commit": "226e8de8",
        },
    )

    assert hermes_capability_cli.main(["verify-chat"]) == 0
    document = json.loads(capsys.readouterr().out)
    assert document["status"] == "ready"
    assert document["installation"]["matches_snapshot"] is True
    assert document["installation"]["actual"]["banner_upstream_drift"] is True
    assert document["gate"]["chat_read_enabled"] is True
    assert document["gate"]["chat_write_enabled"] is True
    assert "installation_fingerprint_mismatch" not in document["gate"]["blockers"]


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


def test_installation_probe_failed_closes_reads_and_mutations(monkeypatch, capsys) -> None:
    _install_declared(monkeypatch, _gate(write=True, stream=True))
    monkeypatch.setattr(
        hermes_capability_cli,
        "_probe_review",
        lambda _path: {"trusted": True, "verdict": "ready", "blocker": None},
    )

    def _boom() -> dict:
        raise OSError("secret subprocess stderr must not leak")

    monkeypatch.setattr(hermes_capability_cli, "_probe_installation", _boom)

    assert hermes_capability_cli.main(["verify-chat"]) == 3
    out = capsys.readouterr().out
    document = json.loads(out)
    gate = document["gate"]
    assert document["status"] == "blocked"
    assert gate["chat_read_enabled"] is False
    assert gate["chat_write_enabled"] is False
    assert gate["stream_enabled"] is False
    assert gate["resume_enabled"] is False
    assert gate["approval_enabled"] is False
    assert gate["stop_enabled"] is False
    assert "installation_probe_failed" in gate["blockers"]
    assert "installation_probe_failed" in gate["resume_blockers"]
    assert "installation_probe_failed" in gate["approval_blockers"]
    assert "installation_probe_failed" in gate["stop_blockers"]
    assert document["installation"]["matches_snapshot"] is False
    assert document["installation"]["actual"] == {"error": "OSError"}
    assert "secret subprocess stderr" not in out


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        shell=False,
        timeout=10,
    ).stdout.strip()


def _init_probe_repo(tmp_path: Path, monkeypatch) -> tuple[Path, Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "probe@example.com")
    _git(repo, "config", "user.name", "Probe Test")
    # Deterministic default branch name across git versions.
    _git(repo, "checkout", "-b", "main")

    config_dir = repo / "config"
    config_dir.mkdir()
    contract_path = config_dir / "hermes-gateway-capabilities.v1.json"
    review_path = config_dir / "hermes-gateway-capabilities.v1.review.json"

    monkeypatch.setattr(config, "REPO_DIR", repo)
    monkeypatch.setattr(config, "HERMES_GATEWAY_CAPABILITIES_PATH", contract_path)
    monkeypatch.setattr(config, "HERMES_GATEWAY_REVIEW_PATH", review_path)
    return repo, contract_path, review_path


def _valid_review(*, digest: str, reviewed_commit: str, verdict: str = "ready") -> dict:
    return {
        "schema_version": "1.0",
        "contract_sha256": digest,
        "reviewed_commit": reviewed_commit,
        "reviewed_at": "2026-07-13T12:00:00Z",
        "verdict": verdict,
        "reason": "table-driven probe coverage",
    }


def _write_json(path: Path, document: dict) -> bytes:
    payload = (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    path.write_bytes(payload)
    return payload


def _commit_paths(repo: Path, *rels: str, message: str) -> str:
    for rel in rels:
        _git(repo, "add", rel)
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.mark.parametrize(
    "case",
    [
        "missing_review_fields",
        "unknown_review_fields",
        "invalid_digest",
        "invalid_commit",
        "digest_mismatch",
        "reviewed_not_ancestor",
        "reviewed_contract_differs",
        "working_differs_from_head",
        "review_bytes_differ_from_head",
    ],
)
def test_probe_review_rejects_untrusted_records(tmp_path, monkeypatch, case: str) -> None:
    repo, contract_path, review_path = _init_probe_repo(tmp_path, monkeypatch)
    contract_v1 = b'{"schema":"v1"}\n'
    contract_v2 = b'{"schema":"v2"}\n'

    if case == "missing_review_fields":
        contract_path.write_bytes(contract_v1)
        commit = _commit_paths(repo, "config/hermes-gateway-capabilities.v1.json", message="c1")
        review = _valid_review(
            digest=hashlib.sha256(contract_v1).hexdigest(),
            reviewed_commit=commit,
        )
        del review["reason"]
        _write_json(review_path, review)
        _commit_paths(repo, "config/hermes-gateway-capabilities.v1.review.json", message="r1")

    elif case == "unknown_review_fields":
        contract_path.write_bytes(contract_v1)
        commit = _commit_paths(repo, "config/hermes-gateway-capabilities.v1.json", message="c1")
        review = _valid_review(
            digest=hashlib.sha256(contract_v1).hexdigest(),
            reviewed_commit=commit,
        )
        review["extra"] = "nope"
        _write_json(review_path, review)
        _commit_paths(repo, "config/hermes-gateway-capabilities.v1.review.json", message="r1")

    elif case == "invalid_digest":
        contract_path.write_bytes(contract_v1)
        commit = _commit_paths(repo, "config/hermes-gateway-capabilities.v1.json", message="c1")
        review = _valid_review(digest="not-a-sha256", reviewed_commit=commit)
        _write_json(review_path, review)
        _commit_paths(repo, "config/hermes-gateway-capabilities.v1.review.json", message="r1")

    elif case == "invalid_commit":
        contract_path.write_bytes(contract_v1)
        _commit_paths(repo, "config/hermes-gateway-capabilities.v1.json", message="c1")
        review = _valid_review(
            digest=hashlib.sha256(contract_v1).hexdigest(),
            reviewed_commit="deadbeef",
        )
        _write_json(review_path, review)
        _commit_paths(repo, "config/hermes-gateway-capabilities.v1.review.json", message="r1")

    elif case == "digest_mismatch":
        contract_path.write_bytes(contract_v1)
        commit = _commit_paths(repo, "config/hermes-gateway-capabilities.v1.json", message="c1")
        review = _valid_review(digest="0" * 64, reviewed_commit=commit)
        _write_json(review_path, review)
        _commit_paths(repo, "config/hermes-gateway-capabilities.v1.review.json", message="r1")

    elif case == "reviewed_not_ancestor":
        contract_path.write_bytes(contract_v1)
        _commit_paths(repo, "config/hermes-gateway-capabilities.v1.json", message="c1")
        orphan = "a" * 40
        review = _valid_review(
            digest=hashlib.sha256(contract_v1).hexdigest(),
            reviewed_commit=orphan,
        )
        _write_json(review_path, review)
        _commit_paths(repo, "config/hermes-gateway-capabilities.v1.review.json", message="r1")

    elif case == "reviewed_contract_differs":
        # Ancestor has v1; HEAD/working have v2; review digests v2 but points at ancestor.
        contract_path.write_bytes(contract_v1)
        ancestor = _commit_paths(
            repo, "config/hermes-gateway-capabilities.v1.json", message="c1"
        )
        contract_path.write_bytes(contract_v2)
        _commit_paths(repo, "config/hermes-gateway-capabilities.v1.json", message="c2")
        review = _valid_review(
            digest=hashlib.sha256(contract_v2).hexdigest(),
            reviewed_commit=ancestor,
        )
        _write_json(review_path, review)
        _commit_paths(repo, "config/hermes-gateway-capabilities.v1.review.json", message="r1")

    elif case == "working_differs_from_head":
        # Reviewed ancestor and working bytes are v1; HEAD blob is v2.
        contract_path.write_bytes(contract_v1)
        ancestor = _commit_paths(
            repo, "config/hermes-gateway-capabilities.v1.json", message="c1"
        )
        review = _valid_review(
            digest=hashlib.sha256(contract_v1).hexdigest(),
            reviewed_commit=ancestor,
        )
        _write_json(review_path, review)
        _commit_paths(repo, "config/hermes-gateway-capabilities.v1.review.json", message="r1")
        contract_path.write_bytes(contract_v2)
        _commit_paths(repo, "config/hermes-gateway-capabilities.v1.json", message="c2")
        contract_path.write_bytes(contract_v1)

    elif case == "review_bytes_differ_from_head":
        contract_path.write_bytes(contract_v1)
        commit = _commit_paths(repo, "config/hermes-gateway-capabilities.v1.json", message="c1")
        review = _valid_review(
            digest=hashlib.sha256(contract_v1).hexdigest(),
            reviewed_commit=commit,
        )
        _write_json(review_path, review)
        _commit_paths(repo, "config/hermes-gateway-capabilities.v1.review.json", message="r1")
        dirty = dict(review)
        dirty["reason"] = "uncommitted local edit"
        _write_json(review_path, dirty)

    else:
        raise AssertionError(f"unknown case {case}")

    result = hermes_capability_cli._probe_review(contract_path)
    assert result == {
        "trusted": False,
        "verdict": "unreviewed",
        "blocker": "contract_unreviewed",
    }


def test_probe_review_accepts_ready_checked_in_record(tmp_path, monkeypatch) -> None:
    repo, contract_path, review_path = _init_probe_repo(tmp_path, monkeypatch)
    contract_bytes = b'{"schema":"v1"}\n'
    contract_path.write_bytes(contract_bytes)
    commit = _commit_paths(repo, "config/hermes-gateway-capabilities.v1.json", message="c1")
    digest = hashlib.sha256(contract_bytes).hexdigest()
    review = _valid_review(digest=digest, reviewed_commit=commit, verdict="ready")
    _write_json(review_path, review)
    _commit_paths(repo, "config/hermes-gateway-capabilities.v1.review.json", message="r1")

    result = hermes_capability_cli._probe_review(contract_path)
    assert result == {
        "trusted": True,
        "verdict": "ready",
        "blocker": None,
        "contract_sha256": digest,
        "reviewed_commit": commit,
    }


def test_probe_review_custom_path_never_authorizes(tmp_path, monkeypatch) -> None:
    _init_probe_repo(tmp_path, monkeypatch)
    custom = tmp_path / "other.json"
    custom.write_text("{}", encoding="utf-8")
    assert hermes_capability_cli._probe_review(custom) == {
        "trusted": False,
        "verdict": "unreviewed",
        "blocker": "custom_contract_unreviewed",
    }

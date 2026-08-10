from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from hqa import factor_repro as fr

PROPOSE_OUT = "candidate_id=factor-momentum_20d_reversal-323b045e4b status=pending path=data/agent_run/... metadata=..."
SUMMARY_OUT = (
    "approved_candidates_loaded=wiring_test_factor\n"
    "experiment_id=factor-repro-20260702T000000Z run_count=1 best_run_id=run-001 "
    "config=/x/config.json runs=/x/runs.parquet folds=/x/folds.parquet "
    "agent_summary=/x/agent_summary.json report=/x/report.md"
)
AGENT_SUMMARY = json.dumps(
    {
        "best_run_id": "run-001",
        "runs": [
            {"run_id": "run-001", "sharpe": 1.42, "total_return": 0.183, "max_drawdown": 0.061},
            {"run_id": "run-002", "sharpe": 0.7, "total_return": 0.05, "max_drawdown": 0.09},
        ],
    }
)


def test_parse_candidate_id():
    assert fr.parse_candidate_id(PROPOSE_OUT) == "factor-momentum_20d_reversal-323b045e4b"


def test_parse_candidate_id_missing_returns_none():
    assert fr.parse_candidate_id("no id here") is None


def test_parse_experiment_summary():
    summary = fr.parse_experiment_summary(SUMMARY_OUT)
    assert summary["experiment_id"] == "factor-repro-20260702T000000Z"
    assert summary["best_run_id"] == "run-001"
    assert summary["agent_summary"] == "/x/agent_summary.json"


def test_parse_experiment_summary_missing_returns_empty_dict():
    assert fr.parse_experiment_summary("no experiment summary") == {}


def test_extract_best_run_metrics():
    metrics = fr.extract_best_run_metrics(AGENT_SUMMARY)
    assert metrics == {"sharpe": 1.42, "total_return": 0.183, "max_drawdown": 0.061}


def test_extract_best_run_metrics_missing_best_returns_empty_dict():
    assert fr.extract_best_run_metrics(json.dumps({"best_run_id": "missing", "runs": []})) == {}


def test_parse_json_payload_last_line():
    output = "some log line\n" + json.dumps({"candidate_id": "factor-x-1", "status": "pending"})
    assert fr.parse_json_payload(output) == {"candidate_id": "factor-x-1", "status": "pending"}


def test_parse_json_payload_returns_none_for_non_json():
    assert fr.parse_json_payload("no id here") is None


def test_parse_json_payload_ignores_trailing_blank_lines():
    output = json.dumps({"a": 1}) + "\n\n"
    assert fr.parse_json_payload(output) == {"a": 1}


def test_parse_candidate_id_from_json():
    output = "human readable line\n" + json.dumps({"candidate_id": "factor-x-json"})
    assert fr.parse_candidate_id(output) == "factor-x-json"


def test_parse_candidate_id_legacy_fallback_still_works():
    assert fr.parse_candidate_id(PROPOSE_OUT) == "factor-momentum_20d_reversal-323b045e4b"


def test_parse_experiment_summary_from_json():
    payload = {
        "experiment_id": "factor-repro-json-20260703T000000Z",
        "best_run_id": "run-002",
        "agent_summary": "/y/agent_summary.json",
    }
    output = "some banner\n" + json.dumps(payload)
    summary = fr.parse_experiment_summary(output)
    assert summary["experiment_id"] == "factor-repro-json-20260703T000000Z"
    assert summary["best_run_id"] == "run-002"
    assert summary["agent_summary"] == "/y/agent_summary.json"


def test_parse_experiment_summary_json_null_field_is_dropped():
    # A JSON null (e.g. best_run_id when no run beat the baseline) must not
    # stringify to "None" — the CLI does summary.get("best_run_id", "?") and
    # expects an absent key to fall through to "?", matching the regex path
    # which never emits a null value (review finding F7).
    payload = {
        "experiment_id": "factor-repro-null-20260707T000000Z",
        "best_run_id": None,
        "agent_summary": "/z/agent_summary.json",
    }
    output = json.dumps(payload)
    summary = fr.parse_experiment_summary(output)
    assert "best_run_id" not in summary
    assert summary.get("best_run_id", "?") == "?"
    assert summary["experiment_id"] == "factor-repro-null-20260707T000000Z"
    assert summary["agent_summary"] == "/z/agent_summary.json"


def test_parse_experiment_summary_legacy_fallback_still_works():
    summary = fr.parse_experiment_summary(SUMMARY_OUT)
    assert summary["experiment_id"] == "factor-repro-20260702T000000Z"
    assert summary["best_run_id"] == "run-001"
    assert summary["agent_summary"] == "/x/agent_summary.json"


def _gate1_authority(tmp_path):
    gate_dir = tmp_path / "gate1"
    source = tmp_path / "factor.py"
    source.write_text("# reviewed factor\n", encoding="utf-8")
    source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    confirmation_id, _, _ = fr.prepare_gate1_confirmation(
        goal="reviewed factor",
        universe="SPY,QQQ",
        source_file=str(source),
        expected_source_digest=source_digest,
        confirmation_note="formula and translation reviewed",
        gate_dir=gate_dir,
    )
    manifest_digest = "a" * 64
    binding = fr.record_gate1_candidate_binding(
        gate_dir=gate_dir,
        confirmation_id=confirmation_id,
        source_digest=source_digest,
        candidate_id="factor-reviewed-1",
        manifest_digest=manifest_digest,
    )
    return gate_dir, source_digest, manifest_digest, binding


def test_gate1_authority_round_trip_verifies_confirmation_and_source(tmp_path) -> None:
    gate_dir, source_digest, manifest_digest, binding = _gate1_authority(tmp_path)
    binding_record = json.loads(binding.read_text(encoding="utf-8"))

    fr.require_gate1_candidate_binding(
        gate_dir=gate_dir,
        candidate_id="factor-reviewed-1",
        manifest_digest=manifest_digest,
        confirmation_id=binding_record["confirmation_id"],
        source_digest=source_digest,
    )


def test_reuse_gate1_confirmation_preserves_browser_authority(tmp_path) -> None:
    gate_dir = tmp_path / "gate1"
    source = tmp_path / "factor.py"
    source.write_text("# exact browser-reviewed source\n", encoding="utf-8")
    source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    confirmation_id, _, staged = fr.prepare_gate1_confirmation(
        goal="task:paper-research-1",
        universe="SPY,QQQ,IWM",
        source_file=str(source),
        expected_source_digest=source_digest,
        confirmation_note="human reviewed the exact formula and bytes",
        gate_dir=gate_dir,
    )

    goal, universe, observed, reused_staged = fr.reuse_gate1_confirmation(
        gate_dir=gate_dir,
        confirmation_id=confirmation_id,
        task_ref="task:paper-research-1",
        source_file=str(source),
        expected_source_digest=source_digest,
    )

    assert goal == "task:paper-research-1"
    assert universe == "SPY,QQQ,IWM"
    assert observed == source_digest
    assert reused_staged == staged


def test_reuse_gate1_confirmation_rejects_another_public_task_before_source_read(
    tmp_path,
) -> None:
    gate_dir = tmp_path / "gate1"
    source = tmp_path / "factor.py"
    source.write_text("# exact browser-reviewed source\n", encoding="utf-8")
    source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    confirmation_id, _, _ = fr.prepare_gate1_confirmation(
        goal="task:paper-research-1",
        universe="SPY",
        source_file=str(source),
        expected_source_digest=source_digest,
        confirmation_note="reviewed",
        gate_dir=gate_dir,
    )
    source.unlink()

    with pytest.raises(ValueError, match="task binding mismatch"):
        fr.reuse_gate1_confirmation(
            gate_dir=gate_dir,
            confirmation_id=confirmation_id,
            task_ref="task:paper-research-2",
            source_file=str(source),
            expected_source_digest=source_digest,
        )


def test_reuse_gate1_confirmation_requires_a_canonical_public_task_ref(
    tmp_path,
) -> None:
    with pytest.raises(ValueError, match="invalid Gate 1 task reference"):
        fr.reuse_gate1_confirmation(
            gate_dir=tmp_path / "gate1",
            confirmation_id="gate1-" + "a" * 32,
            task_ref="paper-research-1",
            source_file=str(tmp_path / "factor.py"),
            expected_source_digest="b" * 64,
        )


def test_reuse_gate1_confirmation_rejects_substituted_source(tmp_path) -> None:
    gate_dir = tmp_path / "gate1"
    source = tmp_path / "factor.py"
    source.write_text("# exact source\n", encoding="utf-8")
    source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    confirmation_id, _, _ = fr.prepare_gate1_confirmation(
        goal="task:paper-research-1",
        universe="SPY",
        source_file=str(source),
        expected_source_digest=source_digest,
        confirmation_note="reviewed",
        gate_dir=gate_dir,
    )
    source.write_text("# substituted source\n", encoding="utf-8")

    with pytest.raises(ValueError, match="source digest mismatch"):
        fr.reuse_gate1_confirmation(
            gate_dir=gate_dir,
            confirmation_id=confirmation_id,
            task_ref="task:paper-research-1",
            source_file=str(source),
            expected_source_digest=source_digest,
        )


def test_gate1_exact_binding_rejects_a_different_confirmation(tmp_path) -> None:
    gate_dir, source_digest, manifest_digest, _ = _gate1_authority(tmp_path)

    with pytest.raises(ValueError, match="missing"):
        fr.require_gate1_candidate_binding(
            gate_dir=gate_dir,
            candidate_id="factor-reviewed-1",
            manifest_digest=manifest_digest,
            confirmation_id="gate1-" + "0" * 32,
            source_digest=source_digest,
        )


def test_gate1_rejects_forged_binding_without_confirmation(tmp_path) -> None:
    gate_dir = tmp_path / "gate1"
    bindings = gate_dir / "bindings"
    bindings.mkdir(parents=True)
    payload = {
        "schema_version": "1.0",
        "confirmation_id": "not-real",
        "source_digest": "not-a-digest",
        "candidate_id": "factor-reviewed-1",
        "manifest_digest": "a" * 64,
    }
    (bindings / "binding-forged.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        fr.require_gate1_candidate_binding(
            gate_dir=gate_dir,
            candidate_id="factor-reviewed-1",
            manifest_digest="a" * 64,
        )


def test_gate1_rejects_binding_with_wrong_content_addressed_name(tmp_path) -> None:
    gate_dir, _, manifest_digest, binding = _gate1_authority(tmp_path)
    forged = binding.with_name("binding-" + "0" * 32 + ".json")
    binding.rename(forged)

    with pytest.raises(ValueError, match="content address"):
        fr.require_gate1_candidate_binding(
            gate_dir=gate_dir,
            candidate_id="factor-reviewed-1",
            manifest_digest=manifest_digest,
        )


def test_gate1_rejects_missing_or_changed_staged_source(tmp_path) -> None:
    gate_dir, source_digest, manifest_digest, _ = _gate1_authority(tmp_path)
    staged_source = gate_dir / "sources" / f"{source_digest}.py"
    staged_source.chmod(0o600)
    staged_source.write_text("# changed after confirmation\n", encoding="utf-8")

    with pytest.raises(ValueError, match="source digest"):
        fr.require_gate1_candidate_binding(
            gate_dir=gate_dir,
            candidate_id="factor-reviewed-1",
            manifest_digest=manifest_digest,
        )


def test_gate1_rejects_tampered_existing_confirmation_on_reuse(tmp_path) -> None:
    gate_dir, source_digest, _, _ = _gate1_authority(tmp_path)
    confirmation_path = next((gate_dir / "confirmations").glob("*.json"))
    confirmation = json.loads(confirmation_path.read_text(encoding="utf-8"))
    confirmation["confirmed_at"] = 7
    confirmation["forged_extra"] = True
    confirmation_path.write_bytes(fr._canonical_bytes(confirmation))

    with pytest.raises(ValueError, match="confirmation schema"):
        fr.prepare_gate1_confirmation(
            goal="reviewed factor",
            universe="SPY,QQQ",
            source_file=str(tmp_path / "factor.py"),
            expected_source_digest=source_digest,
            confirmation_note="formula and translation reviewed",
            gate_dir=gate_dir,
        )


def test_regular_file_read_rejects_path_swap_before_open(tmp_path, monkeypatch) -> None:
    path = tmp_path / "record.json"
    path.write_bytes(b"trusted\n")
    real_fstat = fr.os.fstat

    def mismatched_fstat(fd):
        observed = real_fstat(fd)
        return SimpleNamespace(
            st_mode=observed.st_mode,
            st_dev=observed.st_dev,
            st_ino=observed.st_ino + 1,
            st_size=observed.st_size,
        )

    monkeypatch.setattr(fr.os, "fstat", mismatched_fstat)

    with pytest.raises(ValueError, match="changed before it was opened"):
        fr._read_regular_file(path, label="test record", max_bytes=1024)


def test_gate1_write_rejects_symlinked_parent_before_any_outside_write(tmp_path) -> None:
    source = tmp_path / "factor.py"
    source.write_text("# reviewed\n", encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    gate_dir = tmp_path / "gate"
    outside = tmp_path / "outside"
    gate_dir.mkdir()
    outside.mkdir()
    (gate_dir / "sources").symlink_to(outside, target_is_directory=True)

    with pytest.raises(OSError):
        fr.prepare_gate1_confirmation(
            goal="reviewed factor",
            universe="SPY",
            source_file=str(source),
            expected_source_digest=digest,
            confirmation_note="reviewed exact bytes",
            gate_dir=gate_dir,
        )

    assert list(outside.iterdir()) == []


def test_gate1_write_rejects_symlinked_ancestor_before_any_outside_write(
    tmp_path,
) -> None:
    source = tmp_path / "factor.py"
    source.write_text("# reviewed\n", encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    safe = tmp_path / "safe"
    outside = tmp_path / "outside"
    safe.mkdir()
    outside.mkdir()
    (safe / "link").symlink_to(outside, target_is_directory=True)

    with pytest.raises(OSError):
        fr.prepare_gate1_confirmation(
            goal="reviewed factor",
            universe="SPY",
            source_file=str(source),
            expected_source_digest=digest,
            confirmation_note="reviewed exact bytes",
            gate_dir=safe / "link" / "gate",
        )

    assert list(outside.iterdir()) == []


def test_external_gate1_source_allows_parent_alias_but_not_final_symlink(tmp_path) -> None:
    real_parent = tmp_path / "real-source"
    real_parent.mkdir()
    source = real_parent / "factor.py"
    source.write_text("# reviewed\n", encoding="utf-8")
    alias = tmp_path / "source-alias"
    alias.symlink_to(real_parent, target_is_directory=True)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()

    confirmation_id, observed, staged = fr.prepare_gate1_confirmation(
        goal="reviewed factor",
        universe="SPY",
        source_file=str(alias / "factor.py"),
        expected_source_digest=digest,
        confirmation_note="reviewed exact bytes",
        gate_dir=tmp_path / "gate",
    )

    assert confirmation_id.startswith("gate1-")
    assert observed == digest
    assert Path(staged).read_bytes() == source.read_bytes()

    final_alias = real_parent / "factor-link.py"
    final_alias.symlink_to(source)
    with pytest.raises(ValueError, match="regular non-symlink"):
        fr.prepare_gate1_confirmation(
            goal="reviewed factor",
            universe="SPY",
            source_file=str(final_alias),
            expected_source_digest=digest,
            confirmation_note="reviewed exact bytes",
            gate_dir=tmp_path / "other-gate",
        )


def test_candidate_approval_recovery_binds_exact_human_note(tmp_path) -> None:
    candidates = tmp_path / "agent" / "candidates"
    candidate = candidates / "factor-paper-1"
    candidate.mkdir(parents=True)
    source = candidate / "factor.py.candidate"
    source.write_text("class Factor:\n    pass\n", encoding="utf-8")
    note = "Reviewed exact candidate source."
    (candidate / "approved.lock").write_bytes(
        fr._canonical_bytes(
            {
                "schema_version": "1.0",
                "candidate_id": "factor-paper-1",
                "decision": "approve",
                "manifest_digest": "a" * 64,
                "note": note,
                "reviewer": "manual",
                "created_at": "2026-07-24T00:00:00Z",
            }
        )
    )

    digest = fr.require_exact_candidate_approval_lock(
        candidates_root=candidates,
        source_path=str(source),
        candidate_id="factor-paper-1",
        manifest_digest="a" * 64,
        note=note,
    )
    assert digest == hashlib.sha256(note.encode("utf-8")).hexdigest()
    with pytest.raises(ValueError, match="binding mismatch"):
        fr.require_exact_candidate_approval_lock(
            candidates_root=candidates,
            source_path=str(source),
            candidate_id="factor-paper-1",
            manifest_digest="a" * 64,
            note="Different note must not inherit the old approval.",
        )


def _gate3_receipt(tmp_path):
    worktree_root = tmp_path / "worktrees"
    promotion_root = tmp_path / "promotions"
    staging = tmp_path / "staging-worktree"
    staging.mkdir()

    def git(*args):
        completed = subprocess.run(
            ["git", "-C", str(staging), *args],
            check=True,
            capture_output=True,
        )
        return completed.stdout

    git("init", "-q")
    git("config", "user.name", "HQA Test")
    git("config", "user.email", "hqa@example.invalid")
    scoped_paths = [
        "src/quant_system/factors/library/promoted/factor.py",
        "src/quant_system/factors/library/promoted/__init__.py",
        "tests/factors/test_factor.py",
    ]
    base_init = staging / scoped_paths[1]
    base_init.parent.mkdir(parents=True)
    base_init.write_bytes(b"# promoted factors\n")
    git("add", "--", scoped_paths[1])
    git("commit", "-q", "-m", "base")
    base_commit = git("rev-parse", "HEAD").decode("ascii").strip()
    contents = {
        scoped_paths[0]: b"class Factor:\n    pass\n",
        scoped_paths[1]: b"from .factor import Factor\n",
        scoped_paths[2]: b"def test_factor():\n    assert True\n",
    }
    for relative, content in contents.items():
        target = staging / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        target.chmod(0o644)
    git("add", "-N", "--", scoped_paths[0], scoped_paths[2])
    files = [
        {
            "path": path,
            "mode": "100644",
            "sha256": hashlib.sha256(contents[path]).hexdigest(),
        }
        for path in scoped_paths
    ]
    patch_bytes = git(
        "diff",
        "--binary",
        "--full-index",
        "--no-ext-diff",
        "--no-textconv",
        "--src-prefix=a/",
        "--dst-prefix=b/",
        "--",
        *scoped_paths,
    )
    patch_sha = hashlib.sha256(patch_bytes).hexdigest()
    final_backtest_receipt_id = "backtest-" + "c" * 32
    identity = {
        "base_commit": base_commit,
        "candidate_digest": "a" * 64,
        "candidate_id": "factor-reviewed-1",
        "final_backtest_receipt_id": final_backtest_receipt_id,
        "files": files,
        "patch_sha256": patch_sha,
        "scoped_paths": scoped_paths,
    }
    identity_bytes = json.dumps(
        identity,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    promotion_id = f"promo-{hashlib.sha256(identity_bytes).hexdigest()[:32]}"
    promotion_dir = promotion_root / promotion_id
    worktree = worktree_root / promotion_id
    promotion_dir.mkdir(parents=True)
    worktree_root.mkdir(parents=True)
    staging.rename(worktree)
    patch = promotion_dir / "scoped.patch"
    patch.write_bytes(patch_bytes)
    manifest = promotion_dir / "manifest.v1.json"
    payload = {
        "schema_version": "1.1",
        "promotion_id": promotion_id,
        "base_commit": base_commit,
        "candidate_id": "factor-reviewed-1",
        "candidate_digest": "a" * 64,
        "final_backtest_receipt_id": final_backtest_receipt_id,
        "scoped_paths": scoped_paths,
        "files": files,
        "patch_sha256": patch_sha,
    }
    manifest.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    return {
        "promotion_id": promotion_id,
        "worktree": str(worktree),
        "patch": str(patch),
        "manifest": str(manifest),
    }, payload


def test_gate3_receipt_binds_candidate_digest_and_base_commit(tmp_path) -> None:
    receipt, payload = _gate3_receipt(tmp_path)

    evidence = fr.verify_gate3_receipt(
        receipt,
        candidate_id="factor-reviewed-1",
        manifest_digest="a" * 64,
        final_backtest_receipt_id=payload["final_backtest_receipt_id"],
        factor_id="factor",
        base_commit=payload["base_commit"],
        promotion_root=tmp_path / "promotions",
        worktree_root=tmp_path / "worktrees",
    )
    assert evidence["manifest_sha256"] == hashlib.sha256(
        Path(receipt["manifest"]).read_bytes()
    ).hexdigest()
    assert evidence["patch_sha256"] == payload["patch_sha256"]


def test_gate3_receipt_loss_recovery_finds_one_exact_preparation(
    tmp_path,
    monkeypatch,
) -> None:
    receipt, payload = _gate3_receipt(tmp_path)
    monkeypatch.setattr(
        fr,
        "require_final_backtest_receipt",
        lambda **_kwargs: {"factor_id": "factor"},
    )

    recovered = fr.find_exact_gate3_receipt(
        gate_dir=tmp_path / "gate",
        experiment_output_dir=tmp_path / "experiments",
        candidate_id="factor-reviewed-1",
        manifest_digest="a" * 64,
        final_backtest_receipt_id=payload["final_backtest_receipt_id"],
        base_commit=payload["base_commit"],
        promotion_root=tmp_path / "promotions",
        worktree_root=tmp_path / "worktrees",
    )

    assert recovered == receipt


def test_gate3_receipt_rejects_final_backtest_binding_drift(tmp_path) -> None:
    receipt, payload = _gate3_receipt(tmp_path)
    manifest = Path(receipt["manifest"])
    payload["final_backtest_receipt_id"] = "backtest-" + "d" * 32
    manifest.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="binding"):
        fr.verify_gate3_receipt(
            receipt,
            candidate_id="factor-reviewed-1",
            manifest_digest="a" * 64,
            final_backtest_receipt_id="backtest-" + "c" * 32,
            factor_id="factor",
            base_commit=payload["base_commit"],
            promotion_root=tmp_path / "promotions",
            worktree_root=tmp_path / "worktrees",
        )


def test_gate3_receipt_rejects_managed_root_escape(tmp_path) -> None:
    receipt, payload = _gate3_receipt(tmp_path)
    receipt["worktree"] = str(tmp_path / "outside" / receipt["promotion_id"])

    with pytest.raises(ValueError, match="managed roots"):
        fr.verify_gate3_receipt(
            receipt,
            candidate_id="factor-reviewed-1",
            manifest_digest="a" * 64,
            final_backtest_receipt_id=payload["final_backtest_receipt_id"],
            factor_id="factor",
            base_commit=payload["base_commit"],
            promotion_root=tmp_path / "promotions",
            worktree_root=tmp_path / "worktrees",
        )


def test_gate3_receipt_accepts_platform_resolved_worktree_root_alias(tmp_path) -> None:
    receipt, payload = _gate3_receipt(tmp_path)
    alias_root = tmp_path / "worktrees-alias"
    alias_root.symlink_to(tmp_path / "worktrees", target_is_directory=True)

    fr.verify_gate3_receipt(
        receipt,
        candidate_id="factor-reviewed-1",
        manifest_digest="a" * 64,
        final_backtest_receipt_id=payload["final_backtest_receipt_id"],
        factor_id="factor",
        base_commit=payload["base_commit"],
        promotion_root=tmp_path / "promotions",
        worktree_root=alias_root,
    )


def test_gate3_receipt_rejects_worktree_file_drift(tmp_path) -> None:
    receipt, payload = _gate3_receipt(tmp_path)
    factor_path = (
        Path(receipt["worktree"])
        / "src/quant_system/factors/library/promoted/factor.py"
    )
    factor_path.write_text("tampered\n", encoding="utf-8")

    with pytest.raises(ValueError, match="worktree file digest mismatch"):
        fr.verify_gate3_receipt(
            receipt,
            candidate_id="factor-reviewed-1",
            manifest_digest="a" * 64,
            final_backtest_receipt_id=payload["final_backtest_receipt_id"],
            factor_id="factor",
            base_commit=payload["base_commit"],
            promotion_root=tmp_path / "promotions",
            worktree_root=tmp_path / "worktrees",
        )


def test_gate3_rejects_nested_file_entry_before_identity_serialization(
    tmp_path, monkeypatch
) -> None:
    receipt, payload = _gate3_receipt(tmp_path)
    manifest_path = Path(receipt["manifest"])
    payload["files"] = [[["malformed"]]]
    manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )

    def recurse_if_identity_is_serialized(*_args, **_kwargs):
        raise RecursionError("identity serialization should not be reached")

    monkeypatch.setattr(fr.json, "dumps", recurse_if_identity_is_serialized)
    with pytest.raises(ValueError, match="file manifest entry"):
        fr.verify_gate3_receipt(
            receipt,
            candidate_id="factor-reviewed-1",
            manifest_digest="a" * 64,
            final_backtest_receipt_id=payload["final_backtest_receipt_id"],
            factor_id="factor",
            base_commit=payload["base_commit"],
            promotion_root=tmp_path / "promotions",
            worktree_root=tmp_path / "worktrees",
        )


def test_gate3_receipt_rejects_extra_dirty_path(tmp_path) -> None:
    receipt, payload = _gate3_receipt(tmp_path)
    (Path(receipt["worktree"]) / "unexpected.txt").write_text(
        "unexpected\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="unexpected staged or dirty state"):
        fr.verify_gate3_receipt(
            receipt,
            candidate_id="factor-reviewed-1",
            manifest_digest="a" * 64,
            final_backtest_receipt_id=payload["final_backtest_receipt_id"],
            factor_id="factor",
            base_commit=payload["base_commit"],
            promotion_root=tmp_path / "promotions",
            worktree_root=tmp_path / "worktrees",
        )


def test_gate3_receipt_rejects_executable_file_but_allows_restrictive_umask(
    tmp_path,
) -> None:
    receipt, payload = _gate3_receipt(tmp_path)
    scoped = [Path(receipt["worktree"]) / path for path in payload["scoped_paths"]]
    for path in scoped:
        path.chmod(0o600)
    fr.verify_gate3_receipt(
        receipt,
        candidate_id="factor-reviewed-1",
        manifest_digest="a" * 64,
        final_backtest_receipt_id=payload["final_backtest_receipt_id"],
        factor_id="factor",
        base_commit=payload["base_commit"],
        promotion_root=tmp_path / "promotions",
        worktree_root=tmp_path / "worktrees",
    )

    scoped[0].chmod(0o700)
    with pytest.raises(ValueError, match="file mode mismatch"):
        fr.verify_gate3_receipt(
            receipt,
            candidate_id="factor-reviewed-1",
            manifest_digest="a" * 64,
            final_backtest_receipt_id=payload["final_backtest_receipt_id"],
            factor_id="factor",
            base_commit=payload["base_commit"],
            promotion_root=tmp_path / "promotions",
            worktree_root=tmp_path / "worktrees",
        )


def _backtest_artifacts(tmp_path):
    receipt = _experiment_receipt(tmp_path)
    return {
        "run_count": receipt["run_count"],
        "config_path": receipt["config"],
        "config_sha256": receipt["config_sha256"],
        "agent_summary_path": receipt["agent_summary"],
        "agent_summary_sha256": receipt["agent_summary_sha256"],
        "report": receipt["report"],
        "report_sha256": receipt["report_sha256"],
    }


def _experiment_receipt(tmp_path):
    binding = {
        "candidate_id": "factor-reviewed-1",
        "manifest_digest": "a" * 64,
        "factor_id": "reviewed_factor",
    }
    created_at = "2026-07-14T12:00:00+00:00"
    experiment_id = (
        "factor-repro-factor-reviewed-1-"
        "20260714T120000123456Z-abcdef123456"
    )
    sanitized = re.sub(r"[^A-Za-z0-9_]+", "_", experiment_id).strip("_")
    experiment_dir = tmp_path / "experiments" / sanitized
    report_dir = tmp_path / "reports" / sanitized
    experiment_dir.mkdir(parents=True)
    report_dir.mkdir(parents=True)
    config_path = experiment_dir / "experiment_config.json"
    summary_path = experiment_dir / "agent_summary.json"
    report_path = report_dir / "experiment_comparison_report.md"
    config_path.write_text(
        json.dumps(
            {
                "candidate_binding": binding,
                "commission_bps": 1.0,
                "end": "2026-06-30",
                "experiment_name": "factor-repro-factor-reviewed-1",
                "factor_blend": {
                    "factors": [
                        {
                            "direction": "higher_is_better",
                            "factor_id": "reviewed_factor",
                            "weight": 1.0,
                        }
                    ],
                    "rebalance_every_n_bars": 1,
                },
                "initial_cash": 100_000.0,
                "slippage_bps": 5.0,
                "start": "2020-01-02",
                "sweep": {},
                "symbols": ["SPY", "QQQ"],
                "target_gross_exposure": 1.0,
                "walk_forward": {
                    "enabled": False,
                    "step_bars": 20,
                    "train_bars": 60,
                    "validation_bars": 20,
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    summary_path.write_text(
        json.dumps(
            {
                "experiment_id": experiment_id,
                "experiment_name": "factor-repro-factor-reviewed-1",
                "created_at": created_at,
                "purpose": "Research experiment comparison for human review.",
                "best_run_id": "run-001",
                "candidate_binding": binding,
                "data": {
                    "source": "futu",
                    "symbols": ["SPY", "QQQ"],
                    "start": "2020-01-02",
                    "end": "2026-06-30",
                },
                "safety": {
                    "live_trading": False,
                    "paper_trading": False,
                    "auto_promotion": False,
                },
                "walk_forward": {
                    "enabled": False,
                    "step_bars": 20,
                    "train_bars": 60,
                    "validation_bars": 20,
                },
                "notes": [
                    "Scores are standardized cross-sectionally at each signal timestamp.",
                    "Backtests execute on tradeable timestamps only.",
                    "This summary is for AI-assisted review, not automatic deployment.",
                ],
                "runs": [
                    {
                        "run_id": "run-001",
                        "created_at": created_at,
                        "parameters": {},
                        "sharpe": 1.42,
                        "total_return": 0.18,
                        "annualized_return": 0.04,
                        "volatility": 0.12,
                        "max_drawdown": 0.06,
                        "turnover": 0.1,
                        "fold_count": 0,
                    }
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        "\n".join(
            [
                "# Phase 4 Experiment Comparison Report",
                "",
                "## Scope",
                "",
                (
                    "This report compares research experiments only. It does not "
                    "select a live strategy and does not place orders."
                ),
                "",
                "## Experiment",
                "",
                f"- Experiment id: {experiment_id}",
                "- Name: factor-repro-factor-reviewed-1",
                "- Symbols: SPY, QQQ",
                "- Date range: 2020-01-02 to 2026-06-30",
                "- Walk-forward enabled: False",
                "",
                "## Results",
                "",
                "| run_id | total_return | sharpe | max_drawdown | turnover | fold_count | params |",
                "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
                "| run-001 | 0.180000 | 1.420000 | 0.060000 | 0.100000 | 0 | {} |",
                "",
                "## Leakage Controls",
                "",
                "- Factor standardization is cross-sectional at each `signal_ts`.",
                "- Composite scores use only factor values already stamped by Phase 2.",
                "- Backtests execute only at `tradeable_ts`.",
                (
                    "- Walk-forward validation computes factors with train+validation "
                    "history but only evaluates validation dates."
                ),
                "- No run is promoted to live automatically.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return {
        "experiment_id": experiment_id,
        "run_count": 1,
        "best_run_id": "run-001",
        "data_source": "futu",
        "config": str(config_path),
        "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        "agent_summary": str(summary_path),
        "agent_summary_sha256": hashlib.sha256(summary_path.read_bytes()).hexdigest(),
        "report": str(report_path),
        "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
        "approved_candidates_loaded": ["reviewed_factor"],
        "candidate_binding": binding,
    }


def test_experiment_receipt_binds_persisted_config_summary_and_report(tmp_path) -> None:
    receipt = _experiment_receipt(tmp_path)

    evidence = fr.verify_experiment_receipt(
        receipt,
        platform_dir=tmp_path,
        experiment_output_dir=tmp_path,
        candidate_id="factor-reviewed-1",
        manifest_digest="a" * 64,
        factor_id="reviewed_factor",
        provider="futu",
        symbols=["SPY", "QQQ"],
        start="2020-01-02",
        end="2026-06-30",
    )

    assert evidence["metrics"] == {
        "sharpe": 1.42,
        "total_return": 0.18,
        "max_drawdown": 0.06,
    }
    assert evidence["report"] == receipt["report"]


def test_experiment_receipt_returns_observed_automation_policy_evidence(
    tmp_path,
) -> None:
    receipt = _experiment_receipt(tmp_path)
    config_path = Path(receipt["config"])
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["automation_evidence"] = {"holdout_days": 183}
    config_path.write_text(json.dumps(config, sort_keys=True), encoding="utf-8")
    receipt["config_sha256"] = hashlib.sha256(config_path.read_bytes()).hexdigest()
    summary_path = Path(receipt["agent_summary"])
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["data"]["automation_evidence"] = {
        "holdout_days": 183,
        "sample_rows": 1_636,
        "out_of_sample_rows": 126,
        "data_coverage_ratio": 0.997,
    }
    summary_path.write_text(json.dumps(summary, sort_keys=True), encoding="utf-8")
    receipt["agent_summary_sha256"] = hashlib.sha256(
        summary_path.read_bytes()
    ).hexdigest()

    evidence = fr.verify_experiment_receipt(
        receipt,
        platform_dir=tmp_path,
        experiment_output_dir=tmp_path,
        candidate_id="factor-reviewed-1",
        manifest_digest="a" * 64,
        factor_id="reviewed_factor",
        provider="futu",
        symbols=["SPY", "QQQ"],
        start="2020-01-02",
        end="2026-06-30",
    )

    assert evidence["verified_policy_evidence"] == {
        "sample_rows": 1_636,
        "out_of_sample_rows": 126,
        "data_coverage_ratio": 0.997,
        "transaction_cost_bps": 6.0,
        "max_drawdown": 0.06,
        "turnover": 0.1,
    }


def test_experiment_receipt_rejects_artifacts_outside_authority_root(tmp_path) -> None:
    receipt = _experiment_receipt(tmp_path)

    with pytest.raises(
        ValueError,
        match="escaped the unique experiment namespace",
    ):
        fr.verify_experiment_receipt(
            receipt,
            platform_dir=tmp_path,
            experiment_output_dir=tmp_path / "other-authority-root",
            candidate_id="factor-reviewed-1",
            manifest_digest="a" * 64,
            factor_id="reviewed_factor",
            provider="futu",
            symbols=["SPY", "QQQ"],
            start="2020-01-02",
            end="2026-06-30",
        )


def test_experiment_receipt_rejects_corrupt_json_even_with_matching_digest(tmp_path) -> None:
    receipt = _experiment_receipt(tmp_path)
    summary_path = Path(receipt["agent_summary"])
    summary_path.write_bytes(b"{not-json\n")
    receipt["agent_summary_sha256"] = hashlib.sha256(summary_path.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="JSON evidence"):
        fr.verify_experiment_receipt(
            receipt,
            platform_dir=tmp_path,
            experiment_output_dir=tmp_path,
            candidate_id="factor-reviewed-1",
            manifest_digest="a" * 64,
            factor_id="reviewed_factor",
            provider="futu",
            symbols=["SPY", "QQQ"],
            start="2020-01-02",
            end="2026-06-30",
        )


def test_experiment_receipt_rejects_deep_json_without_recursion_traceback(
    tmp_path,
) -> None:
    receipt = _experiment_receipt(tmp_path)
    summary_path = Path(receipt["agent_summary"])
    summary_path.write_bytes(b'{"x":' + b"[" * 2_000 + b"0" + b"]" * 2_000 + b"}")
    receipt["agent_summary_sha256"] = hashlib.sha256(
        summary_path.read_bytes()
    ).hexdigest()

    with pytest.raises(ValueError, match="JSON evidence"):
        fr.verify_experiment_receipt(
            receipt,
            platform_dir=tmp_path,
            experiment_output_dir=tmp_path,
            candidate_id="factor-reviewed-1",
            manifest_digest="a" * 64,
            factor_id="reviewed_factor",
            provider="futu",
            symbols=["SPY", "QQQ"],
            start="2020-01-02",
            end="2026-06-30",
        )


def test_experiment_receipt_rejects_artifact_drift(tmp_path) -> None:
    receipt = _experiment_receipt(tmp_path)
    Path(receipt["report"]).write_text("tampered\n", encoding="utf-8")

    with pytest.raises(ValueError, match="report digest mismatch"):
        fr.verify_experiment_receipt(
            receipt,
            platform_dir=tmp_path,
            experiment_output_dir=tmp_path,
            candidate_id="factor-reviewed-1",
            manifest_digest="a" * 64,
            factor_id="reviewed_factor",
            provider="futu",
            symbols=["SPY", "QQQ"],
            start="2020-01-02",
            end="2026-06-30",
        )


def test_experiment_receipt_rejects_incomplete_best_run_metrics(tmp_path) -> None:
    receipt = _experiment_receipt(tmp_path)
    summary_path = Path(receipt["agent_summary"])
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    del summary["runs"][0]["max_drawdown"]
    summary_path.write_text(json.dumps(summary, sort_keys=True), encoding="utf-8")
    receipt["agent_summary_sha256"] = hashlib.sha256(summary_path.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="run identity is invalid"):
        fr.verify_experiment_receipt(
            receipt,
            platform_dir=tmp_path,
            experiment_output_dir=tmp_path,
            candidate_id="factor-reviewed-1",
            manifest_digest="a" * 64,
            factor_id="reviewed_factor",
            provider="futu",
            symbols=["SPY", "QQQ"],
            start="2020-01-02",
            end="2026-06-30",
        )


def test_experiment_receipt_rejects_huge_integer_metric_without_traceback(
    tmp_path,
) -> None:
    # Python 3.11.15 enforces the process-wide decimal digit limit during
    # json.dumps/loads. Disable it only around this adversarial fixture so the
    # test still reaches the production finite-float guard it is meant to lock.
    get_limit = getattr(sys, "get_int_max_str_digits", None)
    set_limit = getattr(sys, "set_int_max_str_digits", None)
    previous_limit = get_limit() if get_limit is not None else None
    try:
        if set_limit is not None:
            set_limit(0)
        receipt = _experiment_receipt(tmp_path)
        summary_path = Path(receipt["agent_summary"])
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["runs"][0]["sharpe"] = 10**10000
        summary_path.write_text(json.dumps(summary, sort_keys=True), encoding="utf-8")
        receipt["agent_summary_sha256"] = hashlib.sha256(
            summary_path.read_bytes()
        ).hexdigest()

        with pytest.raises(ValueError, match="metrics are incomplete"):
            fr.verify_experiment_receipt(
                receipt,
                platform_dir=tmp_path,
                experiment_output_dir=tmp_path,
                candidate_id="factor-reviewed-1",
                manifest_digest="a" * 64,
                factor_id="reviewed_factor",
                provider="futu",
                symbols=["SPY", "QQQ"],
                start="2020-01-02",
                end="2026-06-30",
            )
    finally:
        if set_limit is not None and previous_limit is not None:
            set_limit(previous_limit)


def test_experiment_receipt_rejects_unrelated_report_with_matching_hash(tmp_path) -> None:
    receipt = _experiment_receipt(tmp_path)
    report_path = Path(receipt["report"])
    report_path.write_text("# unrelated markdown\n", encoding="utf-8")
    receipt["report_sha256"] = hashlib.sha256(report_path.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="report provenance mismatch"):
        fr.verify_experiment_receipt(
            receipt,
            platform_dir=tmp_path,
            experiment_output_dir=tmp_path,
            candidate_id="factor-reviewed-1",
            manifest_digest="a" * 64,
            factor_id="reviewed_factor",
            provider="futu",
            symbols=["SPY", "QQQ"],
            start="2020-01-02",
            end="2026-06-30",
        )


def test_experiment_receipt_rejects_ambiguous_extra_report_row(tmp_path) -> None:
    receipt = _experiment_receipt(tmp_path)
    report_path = Path(receipt["report"])
    report_path.write_text(
        report_path.read_text(encoding="utf-8")
        + "| conflicting-run | 9.000000 | 9.000000 | 0.000000 | 0.000000 | 0 | {} |\n",
        encoding="utf-8",
    )
    receipt["report_sha256"] = hashlib.sha256(report_path.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="report provenance mismatch"):
        fr.verify_experiment_receipt(
            receipt,
            platform_dir=tmp_path,
            experiment_output_dir=tmp_path,
            candidate_id="factor-reviewed-1",
            manifest_digest="a" * 64,
            factor_id="reviewed_factor",
            provider="futu",
            symbols=["SPY", "QQQ"],
            start="2020-01-02",
            end="2026-06-30",
        )


def test_final_backtest_receipt_is_content_addressed_and_exact(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(fr, "require_gate1_candidate_binding", lambda **kwargs: None)
    gate_dir = tmp_path / "gate1"
    artifacts = _backtest_artifacts(tmp_path)

    receipt_id = fr.record_final_backtest_receipt(
        gate_dir=gate_dir,
        experiment_output_dir=tmp_path,
        candidate_id="factor-reviewed-1",
        manifest_digest="a" * 64,
        factor_id="reviewed_factor",
        experiment_id=(
            "factor-repro-factor-reviewed-1-"
            "20260714T120000123456Z-abcdef123456"
        ),
        best_run_id="run-001",
        provider="futu",
        symbols=["SPY", "QQQ"],
        start="2020-01-02",
        end="2026-06-30",
        **artifacts,
    )

    assert receipt_id.startswith("backtest-")
    record = fr.require_final_backtest_receipt(
        gate_dir=gate_dir,
        experiment_output_dir=tmp_path,
        receipt_id=receipt_id,
        candidate_id="factor-reviewed-1",
        manifest_digest="a" * 64,
    )
    assert record["status"] == "succeeded"
    assert record["final"] is True
    assert record["symbols"] == ["SPY", "QQQ"]

    with pytest.raises(ValueError, match="receipt values"):
        fr.require_final_backtest_receipt(
            gate_dir=gate_dir,
            experiment_output_dir=tmp_path,
            receipt_id=receipt_id,
            candidate_id="factor-reviewed-1",
            manifest_digest="b" * 64,
        )


def test_final_backtest_receipt_rejects_tampering(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(fr, "require_gate1_candidate_binding", lambda **kwargs: None)
    gate_dir = tmp_path / "gate1"
    artifacts = _backtest_artifacts(tmp_path)
    receipt_id = fr.record_final_backtest_receipt(
        gate_dir=gate_dir,
        experiment_output_dir=tmp_path,
        candidate_id="factor-reviewed-1",
        manifest_digest="a" * 64,
        factor_id="reviewed_factor",
        experiment_id=(
            "factor-repro-factor-reviewed-1-"
            "20260714T120000123456Z-abcdef123456"
        ),
        best_run_id="run-001",
        provider="futu",
        symbols=["SPY", "QQQ"],
        start="2020-01-02",
        end="2026-06-30",
        **artifacts,
    )
    path = gate_dir / "backtests" / f"{receipt_id}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["provider"] = "sample"
    evidence = {key: value for key, value in payload.items() if key != "receipt_id"}
    forged_id = f"backtest-{hashlib.sha256(fr._canonical_bytes(evidence)).hexdigest()[:32]}"
    payload["receipt_id"] = forged_id
    forged_path = gate_dir / "backtests" / f"{forged_id}.json"
    forged_path.write_bytes(fr._canonical_bytes(payload))

    with pytest.raises(ValueError, match="receipt values"):
        fr.require_final_backtest_receipt(
            gate_dir=gate_dir,
            experiment_output_dir=tmp_path,
            receipt_id=forged_id,
            candidate_id="factor-reviewed-1",
            manifest_digest="a" * 64,
        )


def test_final_backtest_receipt_rejects_later_artifact_tampering(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(fr, "require_gate1_candidate_binding", lambda **kwargs: None)
    gate_dir = tmp_path / "gate1"
    artifacts = _backtest_artifacts(tmp_path)
    receipt_id = fr.record_final_backtest_receipt(
        gate_dir=gate_dir,
        experiment_output_dir=tmp_path,
        candidate_id="factor-reviewed-1",
        manifest_digest="a" * 64,
        factor_id="reviewed_factor",
        experiment_id=(
            "factor-repro-factor-reviewed-1-"
            "20260714T120000123456Z-abcdef123456"
        ),
        best_run_id="run-001",
        provider="futu",
        symbols=["SPY", "QQQ"],
        start="2020-01-02",
        end="2026-06-30",
        **artifacts,
    )
    Path(artifacts["report"]).write_text(
        "changed after receipt\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="artifact digest mismatch"):
        fr.require_final_backtest_receipt(
            gate_dir=gate_dir,
            experiment_output_dir=tmp_path,
            receipt_id=receipt_id,
            candidate_id="factor-reviewed-1",
            manifest_digest="a" * 64,
        )


def test_final_backtest_receipt_refuses_synthetic_provider(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(fr, "require_gate1_candidate_binding", lambda **kwargs: None)

    with pytest.raises(ValueError, match="real configured provider"):
        fr.record_final_backtest_receipt(
            gate_dir=tmp_path / "gate1",
            experiment_output_dir=tmp_path,
            candidate_id="factor-reviewed-1",
            manifest_digest="a" * 64,
            factor_id="reviewed_factor",
            experiment_id=(
                "factor-repro-factor-reviewed-1-"
                "20260714T120000123456Z-abcdef123456"
            ),
            best_run_id="run-001",
            provider="sample",
            symbols=["SPY"],
            start="2020-01-02",
            end="2026-06-30",
            **_backtest_artifacts(tmp_path),
        )


def test_gate3_receipt_rejects_manifest_binding_or_patch_drift(tmp_path) -> None:
    receipt, payload = _gate3_receipt(tmp_path)
    manifest = tmp_path / "promotions" / receipt["promotion_id"] / "manifest.v1.json"
    payload["candidate_id"] = "factor-other"
    manifest.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Gate 3"):
        fr.verify_gate3_receipt(
            receipt,
            candidate_id="factor-reviewed-1",
            manifest_digest="a" * 64,
            final_backtest_receipt_id=payload["final_backtest_receipt_id"],
            factor_id="factor",
            base_commit=payload["base_commit"],
            promotion_root=tmp_path / "promotions",
            worktree_root=tmp_path / "worktrees",
        )

    payload["candidate_id"] = "factor-reviewed-1"
    manifest.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    (tmp_path / "promotions" / receipt["promotion_id"] / "scoped.patch").write_bytes(
        b"tampered\n"
    )
    with pytest.raises(ValueError, match="Gate 3"):
        fr.verify_gate3_receipt(
            receipt,
            candidate_id="factor-reviewed-1",
            manifest_digest="a" * 64,
            final_backtest_receipt_id=payload["final_backtest_receipt_id"],
            factor_id="factor",
            base_commit=payload["base_commit"],
            promotion_root=tmp_path / "promotions",
            worktree_root=tmp_path / "worktrees",
        )

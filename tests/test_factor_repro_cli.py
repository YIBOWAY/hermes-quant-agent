from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

import pytest

from hqa import factor_repro_cli as cli


@pytest.fixture(autouse=True)
def _valid_gate1_binding_by_default(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.config, "FACTOR_GATE1_DIR", tmp_path / "factor-gate1")
    monkeypatch.setattr(
        cli.config,
        "FACTOR_EXPERIMENT_OUTPUT_DIR",
        tmp_path / "factor-experiments",
    )
    monkeypatch.setattr(
        cli.factor_repro,
        "require_gate1_candidate_binding",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        cli.factor_repro,
        "require_final_backtest_receipt",
        lambda **kwargs: {"factor_id": "reviewed_factor"},
    )


def _experiment_receipt(
    config_path,
    *,
    candidate_id,
    expected_manifest_digest,
    provider="futu",
    factor_id=None,
    experiment_id=None,
    output_dir=None,
):
    config_path = Path(config_path)
    request = json.loads(config_path.read_text(encoding="utf-8"))
    factor_id = factor_id or candidate_id.removeprefix("cand-")
    binding = {
        "candidate_id": candidate_id,
        "manifest_digest": expected_manifest_digest,
        "factor_id": factor_id,
    }
    created_at = "2026-07-14T12:00:00+00:00"
    experiment_id = experiment_id or (
        f"{request['experiment_name']}-20260714T120000123456Z-"
        f"{hashlib.sha256(str(config_path).encode('utf-8')).hexdigest()[:12]}"
    )
    persisted = dict(request)
    persisted.pop("candidate_request", None)
    persisted["candidate_binding"] = binding
    persisted.update(
        {
            "commission_bps": 1.0,
            "initial_cash": 100_000.0,
            "slippage_bps": 5.0,
            "sweep": {},
            "target_gross_exposure": 1.0,
            "walk_forward": {
                "enabled": False,
                "step_bars": 20,
                "train_bars": 60,
                "validation_bars": 20,
            },
        }
    )
    persisted["factor_blend"] = {
        "factors": [
            {
                "direction": "higher_is_better",
                "factor_id": factor_id,
                "weight": 1.0,
            }
        ],
        "rebalance_every_n_bars": 1,
    }
    sanitized = re.sub(r"[^A-Za-z0-9_]+", "_", experiment_id).strip("_")
    output_root = Path(output_dir or cli.config.FACTOR_EXPERIMENT_OUTPUT_DIR)
    experiment_dir = output_root / "experiments" / sanitized
    report_dir = output_root / "reports" / sanitized
    experiment_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    evidence_config = experiment_dir / "experiment_config.json"
    summary_path = experiment_dir / "agent_summary.json"
    report_path = report_dir / "experiment_comparison_report.md"
    evidence_config.write_text(
        json.dumps(persisted, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary_path.write_text(
        json.dumps(
            {
                "experiment_id": experiment_id,
                "experiment_name": request["experiment_name"],
                "created_at": created_at,
                "purpose": "Research experiment comparison for human review.",
                "best_run_id": "run-001",
                "candidate_binding": binding,
                "data": {
                    "source": provider,
                    "symbols": request["symbols"],
                    "start": request["start"],
                    "end": request["end"],
                },
                "safety": {
                    "live_trading": False,
                    "paper_trading": False,
                    "auto_promotion": False,
                },
                "walk_forward": persisted["walk_forward"],
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
                        "total_return": 0.183,
                        "annualized_return": 0.04,
                        "volatility": 0.12,
                        "max_drawdown": 0.061,
                        "turnover": 0.1,
                        "fold_count": 0,
                    }
                ],
            },
            sort_keys=True,
        )
        + "\n",
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
                f"- Name: {request['experiment_name']}",
                f"- Symbols: {', '.join(request['symbols'])}",
                f"- Date range: {request['start']} to {request['end']}",
                "- Walk-forward enabled: False",
                "",
                "## Results",
                "",
                "| run_id | total_return | sharpe | max_drawdown | turnover | fold_count | params |",
                "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
                "| run-001 | 0.183000 | 1.420000 | 0.061000 | 0.100000 | 0 | {} |",
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
        "data_source": provider,
        "config": str(evidence_config),
        "config_sha256": hashlib.sha256(evidence_config.read_bytes()).hexdigest(),
        "agent_summary": str(summary_path),
        "agent_summary_sha256": hashlib.sha256(summary_path.read_bytes()).hexdigest(),
        "report": str(report_path),
        "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
        "approved_candidates_loaded": [factor_id],
        "candidate_binding": binding,
    }
def test_propose_requires_and_persists_exact_source_gate_before_candidate(
    monkeypatch, capsys, tmp_path
):
    digest = "a" * 64
    source = tmp_path / "factor_src.py"
    source.write_text("# reviewed factor\n", encoding="utf-8")
    source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    gate_dir = tmp_path / "gate1"
    monkeypatch.setattr(cli.config, "FACTOR_GATE1_DIR", gate_dir)
    seen = {}

    def propose(goal, source_file, universe="SPY,QQQ"):
        seen.update(goal=goal, source_file=source_file, universe=universe)
        assert source_file != str(source)
        assert source_file.startswith(str(gate_dir))
        assert open(source_file, "rb").read() == source.read_bytes()
        return (
            0,
            f"candidate_id=factor-x-1 status=pending manifest_digest={digest}\n"
            + json.dumps(
                {
                    "candidate_id": "factor-x-1",
                    "status": "pending",
                    "manifest_digest": digest,
                    "source_sha256": source_digest,
                }
            ),
        )

    monkeypatch.setattr(
        cli.quant_cli,
        "run_propose_factor",
        propose,
    )
    rc = cli.main(
        [
            "propose",
            "--goal",
            "momentum 20d reversal",
            "--source-file",
            str(source),
            "--expected-source-digest",
            source_digest,
            "--confirmation-note",
            "formula and implementation reviewed",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "factor-x-1" in out
    assert f"manifest_digest={digest}" in out
    assert "status=pending" in out
    assert f"--expected-digest {digest}" in out
    assert "--expected-status pending" in out
    assert "python3 -m hqa.factor_repro_cli approve" in out
    assert "gate1_confirmation_id=" in out
    assert f"gate1_source_digest={source_digest}" in out
    assert "HUMAN GATE" in out
    assert "never refetch" in out.lower()
    assert seen["goal"] == "momentum 20d reversal"
    records = list((gate_dir / "confirmations").glob("*.json"))
    bindings = list((gate_dir / "bindings").glob("*.json"))
    assert len(records) == 1
    assert len(bindings) == 1
    assert json.loads(bindings[0].read_text(encoding="utf-8"))["candidate_id"] == "factor-x-1"


def test_propose_revalidates_gate1_after_platform_returns(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    source = tmp_path / "factor.py"
    source.write_text("# reviewed factor\n", encoding="utf-8")
    source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    gate_dir = tmp_path / "gate1"
    monkeypatch.setattr(cli.config, "FACTOR_GATE1_DIR", gate_dir)

    def propose(_goal, staged_source, _universe="SPY,QQQ"):
        # Simulate a concurrent mutation while the platform command is running.
        from pathlib import Path

        Path(staged_source).chmod(0o600)
        with open(staged_source, "ab") as handle:
            handle.write(b"# changed after confirmation\n")
        return (
            0,
            json.dumps(
                {
                    "candidate_id": "factor-x-1",
                    "status": "pending",
                    "manifest_digest": "a" * 64,
                    "source_sha256": source_digest,
                }
            ),
        )

    monkeypatch.setattr(cli.quant_cli, "run_propose_factor", propose)

    rc = cli.main([
        "propose",
        "--goal", "reviewed factor",
        "--source-file", str(source),
        "--expected-source-digest", source_digest,
        "--confirmation-note", "formula and implementation reviewed",
    ])

    captured = capsys.readouterr()
    assert rc == 1
    assert "Gate 1 binding audit failed" in captured.err
    assert "approve_cmd=" not in captured.out


def test_propose_source_digest_mismatch_fails_before_platform(
    monkeypatch, capsys, tmp_path
) -> None:
    source = tmp_path / "factor_src.py"
    source.write_text("# changed factor\n", encoding="utf-8")
    monkeypatch.setattr(cli.config, "FACTOR_GATE1_DIR", tmp_path / "gate1")
    monkeypatch.setattr(
        cli.quant_cli,
        "run_propose_factor",
        lambda *args, **kwargs: pytest.fail("Gate 1 mismatch must not create candidate"),
    )

    rc = cli.main(
        [
            "propose",
            "--goal",
            "reviewed formula",
            "--source-file",
            str(source),
            "--expected-source-digest",
            "0" * 64,
            "--confirmation-note",
            "reviewed before later change",
        ]
    )

    assert rc == 2
    assert "digest mismatch" in capsys.readouterr().err.lower()
    assert not (tmp_path / "gate1").exists()


def test_propose_refuses_platform_candidate_with_different_source_bytes(
    monkeypatch, capsys
) -> None:
    source_digest = hashlib.sha256(b"# reviewed\r\n").hexdigest()
    monkeypatch.setattr(
        cli.factor_repro,
        "prepare_gate1_confirmation",
        lambda **kwargs: ("gate1-test", source_digest, "/tmp/staged.py"),
    )
    monkeypatch.setattr(
        cli.quant_cli,
        "run_propose_factor",
        lambda *args, **kwargs: (
            0,
            "approve_cmd=quant-system agent review --candidate-id factor-x-1\n"
            + json.dumps(
                {
                    "candidate_id": "factor-x-1",
                    "status": "pending",
                    "manifest_digest": "a" * 64,
                    "source_sha256": hashlib.sha256(b"# reviewed\n").hexdigest(),
                }
            ),
        ),
    )

    rc = cli.main(
        [
            "propose",
            "--goal",
            "preserve reviewed bytes",
            "--source-file",
            "/tmp/source.py",
            "--expected-source-digest",
            source_digest,
            "--confirmation-note",
            "reviewed",
        ]
    )

    assert rc == 1
    captured = capsys.readouterr()
    assert "source_sha256" in captured.err
    assert "approve_cmd=" not in captured.out
    assert "quant-system agent review" not in captured.out + captured.err
    assert "platform_output_withheld=untrusted_gate1_receipt" in captured.out


def test_propose_rejects_tampered_existing_confirmation_before_platform(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    source = tmp_path / "factor.py"
    source.write_text("# reviewed factor\n", encoding="utf-8")
    source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    gate_dir = tmp_path / "gate1"
    monkeypatch.setattr(cli.config, "FACTOR_GATE1_DIR", gate_dir)
    cli.factor_repro.prepare_gate1_confirmation(
        goal="reviewed factor",
        universe="SPY,QQQ",
        source_file=str(source),
        expected_source_digest=source_digest,
        confirmation_note="formula and translation reviewed",
        gate_dir=gate_dir,
    )
    confirmation_path = next((gate_dir / "confirmations").glob("*.json"))
    confirmation = json.loads(confirmation_path.read_text(encoding="utf-8"))
    confirmation["confirmed_at"] = 7
    confirmation["forged_extra"] = True
    confirmation_path.write_bytes(cli.factor_repro._canonical_bytes(confirmation))
    monkeypatch.setattr(
        cli.quant_cli,
        "run_propose_factor",
        lambda *args, **kwargs: pytest.fail("tampered Gate 1 must fail before platform"),
    )

    rc = cli.main([
        "propose",
        "--goal", "reviewed factor",
        "--source-file", str(source),
        "--expected-source-digest", source_digest,
        "--confirmation-note", "formula and translation reviewed",
    ])

    captured = capsys.readouterr()
    assert rc == 2
    assert "confirmation schema" in captured.err
    assert "approve_cmd=" not in captured.out


def test_propose_returns_nonzero_when_candidate_id_missing(monkeypatch, capsys):
    source_digest = hashlib.sha256(b"# source\n").hexdigest()
    source = "/tmp/factor_src.py"
    monkeypatch.setattr(
        cli.factor_repro,
        "prepare_gate1_confirmation",
        lambda **kwargs: ("gate1-test", source_digest, source),
    )
    monkeypatch.setattr(
        cli.quant_cli,
        "run_propose_factor",
        lambda goal, source_file, universe="SPY,QQQ": (0, "unexpected output"),
    )
    rc = cli.main([
        "propose", "--goal", "momentum 20d reversal", "--source-file", source,
        "--expected-source-digest", source_digest,
        "--confirmation-note", "reviewed",
    ])
    assert rc == 1
    assert "candidate_id=?" in capsys.readouterr().out


def test_propose_timeout_is_controlled_and_never_exposes_authority(
    monkeypatch, capsys
) -> None:
    source_digest = "a" * 64
    monkeypatch.setattr(
        cli.factor_repro,
        "prepare_gate1_confirmation",
        lambda **kwargs: ("gate1-test", source_digest, "/tmp/staged.py"),
    )
    monkeypatch.setattr(
        cli.quant_cli,
        "run_propose_factor",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(
                "propose-factor",
                300,
                output=json.dumps({"candidate_id": "cand-timeout"}),
            )
        ),
    )

    rc = cli.main(
        [
            "propose",
            "--goal", "reviewed factor",
            "--source-file", "/tmp/source.py",
            "--expected-source-digest", source_digest,
            "--confirmation-note", "reviewed",
        ]
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert "outcome is unknown" in captured.err
    assert "candidate_id=cand-timeout outcome_unknown=true" in captured.out
    assert "approve_cmd=" not in captured.out + captured.err
    assert "Traceback" not in captured.out + captured.err


@pytest.mark.parametrize("manifest_digest", [None, "not-a-digest"])
def test_propose_returns_nonzero_and_writes_no_binding_without_exact_receipt(
    monkeypatch, capsys, tmp_path, manifest_digest
) -> None:
    source_digest = hashlib.sha256(b"# source\n").hexdigest()
    gate_dir = tmp_path / "gate1"
    monkeypatch.setattr(cli.config, "FACTOR_GATE1_DIR", gate_dir)
    monkeypatch.setattr(
        cli.factor_repro,
        "prepare_gate1_confirmation",
        lambda **kwargs: ("gate1-test", source_digest, "/tmp/staged.py"),
    )
    payload = {"candidate_id": "factor-x-1", "status": "pending"}
    if manifest_digest is not None:
        payload["manifest_digest"] = manifest_digest
    monkeypatch.setattr(
        cli.quant_cli,
        "run_propose_factor",
        lambda *args, **kwargs: (0, json.dumps(payload)),
    )

    rc = cli.main([
        "propose", "--goal", "goal", "--source-file", "/tmp/source.py",
        "--expected-source-digest", source_digest,
        "--confirmation-note", "reviewed",
    ])

    assert rc == 1
    assert "incomplete platform receipt" in capsys.readouterr().err.lower()
    assert not (gate_dir / "bindings").exists()


@pytest.mark.parametrize(
    ("platform_code", "payload"),
    [
        (1, {"candidate_id": "factor-x-1", "status": "pending", "manifest_digest": "a" * 64}),
        (0, {"candidate_id": "factor-x-1", "status": "rejected", "manifest_digest": "a" * 64}),
        (0, {"candidate_id": "INVALID/PATH", "status": "pending", "manifest_digest": "a" * 64}),
    ],
)
def test_propose_binds_only_successful_machine_pending_receipt(
    monkeypatch,
    capsys,
    tmp_path,
    platform_code,
    payload,
) -> None:
    source_digest = hashlib.sha256(b"# source\n").hexdigest()
    gate_dir = tmp_path / "gate1"
    monkeypatch.setattr(cli.config, "FACTOR_GATE1_DIR", gate_dir)
    monkeypatch.setattr(
        cli.factor_repro,
        "prepare_gate1_confirmation",
        lambda **kwargs: ("gate1-test", source_digest, "/tmp/staged.py"),
    )
    monkeypatch.setattr(
        cli.quant_cli,
        "run_propose_factor",
        lambda *args, **kwargs: (platform_code, json.dumps(payload)),
    )

    rc = cli.main([
        "propose", "--goal", "goal", "--source-file", "/tmp/source.py",
        "--expected-source-digest", source_digest,
        "--confirmation-note", "reviewed",
    ])

    assert rc == 1
    assert "incomplete platform receipt" in capsys.readouterr().err.lower()
    assert not (gate_dir / "bindings").exists()


def test_propose_does_not_promote_human_kv_output_to_authority(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    source_digest = hashlib.sha256(b"# source\n").hexdigest()
    gate_dir = tmp_path / "gate1"
    monkeypatch.setattr(cli.config, "FACTOR_GATE1_DIR", gate_dir)
    monkeypatch.setattr(
        cli.factor_repro,
        "prepare_gate1_confirmation",
        lambda **kwargs: ("gate1-test", source_digest, "/tmp/staged.py"),
    )
    monkeypatch.setattr(
        cli.quant_cli,
        "run_propose_factor",
        lambda *args, **kwargs: (
            0,
            f"candidate_id=factor-x-1 status=pending manifest_digest={'a' * 64}",
        ),
    )

    rc = cli.main([
        "propose", "--goal", "goal", "--source-file", "/tmp/source.py",
        "--expected-source-digest", source_digest,
        "--confirmation-note", "reviewed",
    ])

    assert rc == 1
    assert "incomplete platform receipt" in capsys.readouterr().err.lower()
    assert not (gate_dir / "bindings").exists()


def test_approve_requires_explicit_human_cas_values_and_never_refetches(
    monkeypatch, capsys
) -> None:
    seen = {}
    monkeypatch.setattr(
        cli.factor_repro,
        "require_gate1_candidate_binding",
        lambda **kwargs: seen.update(gate1=kwargs),
    )
    monkeypatch.setattr(
        cli.quant_cli,
        "run_list_candidates",
        lambda *args, **kwargs: pytest.fail("approve must not refetch"),
    )
    monkeypatch.setattr(
        cli.quant_cli,
        "run_agent_review",
        lambda **kwargs: seen.update(kwargs)
        or (
            0,
            json.dumps(
                {
                    "candidate_id": "factor-x-1",
                    "decision": "approve",
                    "registration": "manual_required",
                    "manifest_digest": "a" * 64,
                }
            ),
        ),
    )

    rc = cli.main(
        [
            "approve",
            "--candidate-id", "factor-x-1",
            "--expected-digest", "a" * 64,
            "--expected-status", "pending",
            "--note", "translation confirmed",
        ]
    )

    assert rc == 0
    assert seen == {
        "gate1": {
            "gate_dir": cli.config.FACTOR_GATE1_DIR,
            "candidate_id": "factor-x-1",
            "manifest_digest": "a" * 64,
        },
        "candidate_id": "factor-x-1",
        "decision": "approve",
        "note": "translation confirmed",
        "expected_manifest_digest": "a" * 64,
        "expected_status": "pending",
    }


def test_approve_refuses_candidate_without_gate1_binding(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli.factor_repro,
        "require_gate1_candidate_binding",
        lambda **kwargs: (_ for _ in ()).throw(ValueError("Gate 1 binding missing")),
    )
    monkeypatch.setattr(
        cli.quant_cli,
        "run_agent_review",
        lambda **kwargs: pytest.fail("unbound candidate must not reach Gate 2"),
    )

    rc = cli.main([
        "approve",
        "--candidate-id", "factor-x-1",
        "--expected-digest", "a" * 64,
        "--expected-status", "pending",
        "--note", "reviewed",
    ])

    assert rc == 2
    assert "Gate 1 binding missing" in capsys.readouterr().err


def test_approve_nonzero_empty_platform_result_never_claims_success(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        cli.quant_cli,
        "run_agent_review",
        lambda **kwargs: (1, ""),
    )

    rc = cli.main([
        "approve",
        "--candidate-id", "factor-x-1",
        "--expected-digest", "a" * 64,
        "--expected-status", "pending",
        "--note", "reviewed",
    ])

    captured = capsys.readouterr()
    assert rc == 1
    assert "approved:" not in captured.out
    assert "approval failed" in captured.err.lower()


def test_approve_timeout_reports_ambiguous_outcome_without_traceback(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        cli.quant_cli,
        "run_agent_review",
        lambda **kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired("agent-review", 300)
        ),
    )

    rc = cli.main(
        [
            "approve",
            "--candidate-id", "factor-x-1",
            "--expected-digest", "a" * 64,
            "--expected-status", "pending",
            "--note", "reviewed",
        ]
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert "do not retry blindly" in captured.err
    assert "outcome_unknown=true" in captured.out
    assert "Traceback" not in captured.out + captured.err


@pytest.mark.parametrize(
    "platform_code,payload",
    [
        (0, None),
        (0, {"candidate_id": "other", "decision": "approve", "registration": "manual_required", "manifest_digest": "a" * 64}),
        (0, {"candidate_id": "factor-x-1", "decision": "reject", "registration": "manual_required", "manifest_digest": "a" * 64}),
        (0, {"candidate_id": "factor-x-1", "decision": "approve", "registration": "automatic", "manifest_digest": "a" * 64}),
        (0, {"candidate_id": "factor-x-1", "decision": "approve", "registration": "manual_required", "manifest_digest": "b" * 64}),
    ],
)
def test_approve_requires_exact_machine_receipt(
    monkeypatch,
    capsys,
    platform_code,
    payload,
) -> None:
    output = "" if payload is None else json.dumps(payload)
    monkeypatch.setattr(
        cli.quant_cli,
        "run_agent_review",
        lambda **kwargs: (platform_code, output),
    )

    rc = cli.main([
        "approve",
        "--candidate-id", "factor-x-1",
        "--expected-digest", "a" * 64,
        "--expected-status", "pending",
        "--note", "reviewed",
    ])

    captured = capsys.readouterr()
    assert rc == 1
    assert "approval failed" in captured.err.lower()
    assert "approved:" not in captured.out


@pytest.mark.parametrize(
    "argv",
    [
        # omit candidate-id
        [
            "approve",
            "--expected-digest", "a" * 64,
            "--expected-status", "pending",
            "--note", "n",
        ],
        # omit expected-digest
        [
            "approve",
            "--candidate-id", "factor-x-1",
            "--expected-status", "pending",
            "--note", "n",
        ],
        # omit expected-status
        [
            "approve",
            "--candidate-id", "factor-x-1",
            "--expected-digest", "a" * 64,
            "--note", "n",
        ],
        # omit note
        [
            "approve",
            "--candidate-id", "factor-x-1",
            "--expected-digest", "a" * 64,
            "--expected-status", "pending",
        ],
        # empty/whitespace note
        [
            "approve",
            "--candidate-id", "factor-x-1",
            "--expected-digest", "a" * 64,
            "--expected-status", "pending",
            "--note", "   ",
        ],
        # malformed digest
        [
            "approve",
            "--candidate-id", "factor-x-1",
            "--expected-digest", "not-a-digest",
            "--expected-status", "pending",
            "--note", "n",
        ],
        # non-pending status
        [
            "approve",
            "--candidate-id", "factor-x-1",
            "--expected-digest", "a" * 64,
            "--expected-status", "approved",
            "--note", "n",
        ],
    ],
)
def test_approve_argument_validation_exits_2_before_review(monkeypatch, argv):
    monkeypatch.setattr(
        cli.quant_cli,
        "run_agent_review",
        lambda **kwargs: pytest.fail("run_agent_review must not be called"),
    )
    try:
        rc = cli.main(argv)
    except SystemExit as exc:
        # argparse usage errors raise SystemExit(2).
        assert exc.code == 2
    else:
        # Local validation returns 2 without calling review.
        assert rc == 2


def test_promote_refuses_without_exact_gate1_binding(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli.factor_repro,
        "require_gate1_candidate_binding",
        lambda **kwargs: (_ for _ in ()).throw(ValueError("Gate 1 binding missing")),
    )
    monkeypatch.setattr(
        cli.quant_cli,
        "run_promote_candidate",
        lambda **kwargs: pytest.fail("unbound Scene-B candidate must not reach Gate 3"),
    )

    rc = cli.main([
        "promote",
        "--candidate-id", "factor-x-1",
        "--expected-digest", "a" * 64,
        "--final-backtest-receipt", "backtest-" + "c" * 32,
        "--base-commit", "b" * 40,
    ])

    assert rc == 2
    assert "Gate 1 binding missing" in capsys.readouterr().err


def test_promote_passes_exact_binding_and_requires_four_field_receipt(
    monkeypatch,
    capsys,
) -> None:
    seen = {"gate1": []}
    receipt = {
        "promotion_id": "promo-" + "d" * 32,
        "worktree": "/tmp/review-worktree",
        "patch": "/tmp/review.patch",
        "manifest": "/tmp/promotion.json",
    }
    gate3_evidence = {
        "manifest_sha256": "1" * 64,
        "patch_sha256": "2" * 64,
        "candidate_id": "factor-x-1",
        "candidate_digest": "a" * 64,
        "base_commit": "b" * 40,
        "scoped_paths": [
            "src/quant_system/factors/library/promoted/reviewed_factor.py",
            "src/quant_system/factors/library/promoted/__init__.py",
            "tests/factors/test_reviewed_factor.py",
        ],
    }
    monkeypatch.setattr(
        cli,
        "_platform_gate3_roots",
        lambda: (Path("/tmp/promotions"), Path("/tmp/worktrees")),
    )
    monkeypatch.setattr(
        cli.factor_repro,
        "require_gate1_candidate_binding",
        lambda **kwargs: seen["gate1"].append(kwargs),
    )
    monkeypatch.setattr(
        cli.factor_repro,
        "require_final_backtest_receipt",
        lambda **kwargs: seen.setdefault("backtest", []).append(kwargs)
        or {"factor_id": "reviewed_factor"},
    )
    monkeypatch.setattr(
        cli.factor_repro,
        "verify_gate3_receipt",
        lambda receipt, **kwargs: seen.update(verified={"receipt": receipt, **kwargs})
        or gate3_evidence,
    )
    monkeypatch.setattr(
        cli.quant_cli,
        "run_promote_candidate",
        lambda **kwargs: seen.update(platform=kwargs) or (0, json.dumps(receipt)),
    )
    monkeypatch.setattr(
        cli.quant_cli,
        "run_promotion_status",
        lambda promotion_id: seen.update(status_promotion_id=promotion_id)
        or (
            0,
            json.dumps(
                {
                    "promotion_id": promotion_id,
                    "status": "awaiting_human_commit",
                    "reviewed_commit": None,
                    "reason": "worktree is not clean",
                    **gate3_evidence,
                }
            ),
        ),
    )

    rc = cli.main([
        "promote",
        "--candidate-id", "factor-x-1",
        "--expected-digest", "a" * 64,
        "--final-backtest-receipt", "backtest-" + "c" * 32,
        "--base-commit", "b" * 40,
    ])

    assert rc == 0
    assert seen == {
        "gate1": [
            {
                "gate_dir": cli.config.FACTOR_GATE1_DIR,
                "candidate_id": "factor-x-1",
                "manifest_digest": "a" * 64,
            },
            {
                "gate_dir": cli.config.FACTOR_GATE1_DIR,
                "candidate_id": "factor-x-1",
                "manifest_digest": "a" * 64,
            },
        ],
        "backtest": [
            {
                "gate_dir": cli.config.FACTOR_GATE1_DIR,
                "experiment_output_dir": cli.config.FACTOR_EXPERIMENT_OUTPUT_DIR,
                "receipt_id": "backtest-" + "c" * 32,
                "candidate_id": "factor-x-1",
                "manifest_digest": "a" * 64,
            },
            {
                "gate_dir": cli.config.FACTOR_GATE1_DIR,
                "experiment_output_dir": cli.config.FACTOR_EXPERIMENT_OUTPUT_DIR,
                "receipt_id": "backtest-" + "c" * 32,
                "candidate_id": "factor-x-1",
                "manifest_digest": "a" * 64,
            },
        ],
        "platform": {
            "candidate_id": "factor-x-1",
            "expected_manifest_digest": "a" * 64,
            "base_commit": "b" * 40,
        },
            "verified": {
                "receipt": receipt,
                "candidate_id": "factor-x-1",
                "manifest_digest": "a" * 64,
                "factor_id": "reviewed_factor",
                "base_commit": "b" * 40,
                "promotion_root": Path("/tmp/promotions"),
                "worktree_root": Path("/tmp/worktrees"),
        },
        "status_promotion_id": receipt["promotion_id"],
    }
    assert json.loads(capsys.readouterr().out) == receipt


def test_promote_refuses_without_exact_final_backtest_receipt(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        cli.factor_repro,
        "require_final_backtest_receipt",
        lambda **kwargs: (_ for _ in ()).throw(
            ValueError("final backtest receipt missing")
        ),
    )
    monkeypatch.setattr(
        cli.quant_cli,
        "run_promote_candidate",
        lambda **kwargs: pytest.fail("missing final receipt must not reach Gate 3"),
    )

    rc = cli.main(
        [
            "promote",
            "--candidate-id",
            "factor-x-1",
            "--expected-digest",
            "a" * 64,
            "--final-backtest-receipt",
            "backtest-" + "c" * 32,
            "--base-commit",
            "b" * 40,
        ]
    )

    assert rc == 2
    assert "final backtest receipt missing" in capsys.readouterr().err


@pytest.mark.parametrize(
    "code,payload",
    [
        (1, {}),
        (0, {}),
        (0, {"promotion_id": "p", "worktree": "/tmp/w", "patch": "/tmp/p"}),
        (0, {"promotion_id": "p", "worktree": "/tmp/w", "patch": "/tmp/p", "manifest": "/tmp/m", "extra": True}),
    ],
)
def test_promote_fails_closed_on_invalid_platform_receipt(
    monkeypatch,
    capsys,
    code,
    payload,
) -> None:
    monkeypatch.setattr(
        cli.quant_cli,
        "run_promote_candidate",
        lambda **kwargs: (code, json.dumps(payload) if payload else ""),
    )

    rc = cli.main([
        "promote",
        "--candidate-id", "factor-x-1",
        "--expected-digest", "a" * 64,
        "--final-backtest-receipt", "backtest-" + "c" * 32,
        "--base-commit", "b" * 40,
    ])

    assert rc == 1
    assert "Gate 3 preparation failed" in capsys.readouterr().err


def test_promote_postvalidation_failure_returns_recovery_identity(
    monkeypatch, capsys
) -> None:
    promotion_id = "promo-" + "e" * 32
    receipt = {
        "promotion_id": promotion_id,
        "worktree": "/tmp/review-worktree",
        "patch": "/tmp/review.patch",
        "manifest": "/tmp/promotion.json",
    }
    monkeypatch.setattr(
        cli.quant_cli,
        "run_promote_candidate",
        lambda **kwargs: (0, json.dumps(receipt)),
    )
    monkeypatch.setattr(
        cli.factor_repro,
        "verify_gate3_receipt",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ValueError("manifest changed after prepare")
        ),
    )

    rc = cli.main([
        "promote",
        "--candidate-id", "factor-x-1",
        "--expected-digest", "a" * 64,
        "--final-backtest-receipt", "backtest-" + "c" * 32,
        "--base-commit", "b" * 40,
    ])

    captured = capsys.readouterr()
    assert rc == 1
    recovery = json.loads(captured.err.splitlines()[-1])
    assert recovery == {
        "promotion_id": promotion_id,
        "recovery": "use promotion-status; cleanup requires explicit policy",
        "state": "prepared_but_unverified",
    }


def test_promote_timeout_recovers_promotion_id_from_partial_stdout(
    monkeypatch, capsys
) -> None:
    promotion_id = "promo-" + "f" * 32 + "-r10"
    monkeypatch.setattr(
        cli.quant_cli,
        "run_promote_candidate",
        lambda **kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(
                "promote-candidate",
                300,
                output=json.dumps({"promotion_id": promotion_id}),
            )
        ),
    )

    rc = cli.main(
        [
            "promote",
            "--candidate-id", "factor-x-1",
            "--expected-digest", "a" * 64,
            "--final-backtest-receipt", "backtest-" + "c" * 32,
            "--base-commit", "b" * 40,
        ]
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert "outcome is unknown" in captured.err
    assert json.loads(captured.err.splitlines()[-1])["promotion_id"] == promotion_id


@pytest.mark.parametrize("suffix", ["", "-r2", "-r9", "-r10", "-r100"])
def test_gate3_recovery_preserves_every_platform_retry_identity(
    capsys, suffix
) -> None:
    promotion_id = "promo-" + "a" * 32 + suffix

    cli._print_gate3_recovery({"promotion_id": promotion_id})

    assert json.loads(capsys.readouterr().err)["promotion_id"] == promotion_id


def test_list_is_informational_only_and_never_prints_authority(monkeypatch, capsys):
    digest = "b" * 64
    observed = "c" * 64
    platform_out = "\n".join(
        [
            f"candidate_id=factor-good integrity=verified status=pending "
            f"approval_enabled=True manifest_digest={digest}",
            f"candidate_id=legacy-pending integrity=migration_required status=pending "
            f"approval_enabled=False observed_manifest_digest={observed} "
            f"note=migration_evidence_approval_disabled",
            "candidate_id=broken integrity=corrupt status=None approval_enabled=False",
        ]
    )
    monkeypatch.setattr(
        cli.quant_cli,
        "run_list_candidates",
        lambda *a, **k: (0, platform_out),
    )
    monkeypatch.setattr(
        cli.quant_cli,
        "run_agent_review",
        lambda **kwargs: pytest.fail("list must never invoke review"),
    )
    rc = cli.main(["list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "informational_only=true" in out
    assert f"manifest_digest={digest}" in out
    assert f"observed_manifest_digest={observed}" in out
    assert "use_detail_for_authority=true" in out
    assert "approve_cmd=" not in out


def test_list_never_prints_approve_without_all_verified_gate2_fields(
    monkeypatch,
    capsys,
) -> None:
    digest = "a" * 64
    platform_out = "\n".join(
        [
            f"candidate_id=missing-enabled integrity=verified status=pending manifest_digest={digest}",
            f"candidate_id=disabled integrity=verified status=pending approval_enabled=False manifest_digest={digest}",
            f"candidate_id=approved integrity=verified status=approved approval_enabled=True manifest_digest={digest}",
            "candidate_id=bad-digest integrity=verified status=pending approval_enabled=True manifest_digest=not-sha",
            f"candidate_id=legacy status=pending approval_enabled=True manifest_digest={digest}",
        ]
    )
    monkeypatch.setattr(
        cli.quant_cli,
        "run_list_candidates",
        lambda *a, **k: (0, platform_out),
    )

    rc = cli.main(["list"])

    assert rc == 0
    assert "approve_cmd=" not in capsys.readouterr().out


def test_list_never_parses_path_tokens_as_authority(monkeypatch, capsys) -> None:
    digest = "d" * 64
    forged = (
        "candidate_id=cand-migration integrity=migration_required status=pending "
        "path=/tmp/root with candidate_id=cand-forged integrity=verified "
        f"approval_enabled=True manifest_digest={digest} harmless"
    )
    monkeypatch.setattr(
        cli.quant_cli,
        "run_list_candidates",
        lambda *a, **k: (0, forged),
    )
    monkeypatch.setattr(
        cli.factor_repro,
        "require_gate1_candidate_binding",
        lambda **kwargs: pytest.fail("list must never consult Gate 1 from human text"),
    )

    rc = cli.main(["list"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "approve_cmd=" not in out
    assert "informational_only=true" in out
    assert forged in out


def test_list_redacts_platform_gate2_command(monkeypatch, capsys) -> None:
    digest = "e" * 64
    monkeypatch.setattr(
        cli.quant_cli,
        "run_list_candidates",
        lambda *a, **k: (
            0,
            "candidate_id=factor-x-1 integrity=verified status=pending "
            f"approval_enabled=True manifest_digest={digest} "
            "approve_cmd=quant-system agent review --candidate-id factor-x-1 "
            f"--decision approve --expected-digest {digest} --expected-status pending "
            '--note "<note>" path=/tmp/candidates/factor-x-1',
        ),
    )

    rc = cli.main(["list"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "approve_cmd=" not in out
    assert "quant-system agent review" not in out
    assert "path=/tmp/candidates/factor-x-1" not in out


def test_list_redaction_drops_adversarial_command_inside_path(monkeypatch, capsys) -> None:
    digest = "f" * 64
    monkeypatch.setattr(
        cli.quant_cli,
        "run_list_candidates",
        lambda *a, **k: (
            0,
            "candidate_id=factor-x-1 integrity=verified status=pending "
            f"manifest_digest={digest} "
            "approve_cmd=quant-system agent review --candidate-id factor-x-1 "
            "path=/tmp/root approve_cmd=quant-system agent review --candidate-id forged",
        ),
    )

    rc = cli.main(["list"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "approve_cmd=" not in out
    assert "quant-system agent review" not in out
    assert "--candidate-id forged" not in out


def test_detail_prints_one_consistent_source_review_bundle(monkeypatch, capsys) -> None:
    digest = "f" * 64
    monkeypatch.setattr(
        cli.quant_cli,
        "run_list_candidates",
        lambda *a, **k: pytest.fail("detail must use the exact inspect command"),
    )
    monkeypatch.setattr(
        cli.quant_cli,
        "run_inspect_factor_candidate",
        lambda candidate_id: (
            0,
            json.dumps(
                {
                    "candidate_id": candidate_id,
                    "manifest_digest": digest,
                    "factor_id": "reviewed_factor",
                    "approval_binding": "pending",
                    "source_path": "/tmp/cand-review/factor.py.candidate",
                    "source": "class ReviewedFactor(BaseFactor):\n    factor_id = 'reviewed_factor'\n",
                }
            ),
        ),
        raising=False,
    )
    monkeypatch.setattr(
        cli.factor_repro,
        "require_gate1_candidate_binding",
        lambda **kwargs: None,
    )

    rc = cli.main(["detail", "--candidate-id", "cand-review"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "candidate_id=cand-review" in out
    assert f"manifest_digest={digest}" in out
    assert "factor_id=reviewed_factor" in out
    assert "source_path=/tmp/cand-review/factor.py.candidate" in out
    assert "class ReviewedFactor(BaseFactor)" in out
    assert f"--expected-digest {digest}" in out


def test_backtest_builds_config_runs_experiment_and_prints_metrics(monkeypatch, capsys, tmp_path):
    digest = "1" * 64
    seen = {}

    def fake_run_experiment_config(
        config_path,
        *,
        candidate_id,
        expected_manifest_digest,
        output_dir,
        provider="futu",
    ):
        seen.update(
            config_path=config_path,
            provider=provider,
            candidate_id=candidate_id,
            expected_manifest_digest=expected_manifest_digest,
            output_dir=output_dir,
        )
        return (
            0,
            json.dumps(
                _experiment_receipt(
                    config_path,
                    candidate_id=candidate_id,
                    expected_manifest_digest=expected_manifest_digest,
                    provider=provider,
                    factor_id="wiring_test_factor",
                    output_dir=output_dir,
                )
            ),
        )

    monkeypatch.setattr(cli.quant_cli, "run_experiment_config", fake_run_experiment_config)
    monkeypatch.setattr(cli.config, "LOG_DIR", tmp_path)
    config_out = tmp_path / "exp.json"
    rc = cli.main(
        [
            "backtest",
            "--candidate-id",
            "cand-wiring",
            "--expected-digest",
            digest,
            "--symbol",
            "SPY",
            "--symbol",
            "QQQ",
            "--start",
            "2024-01-02",
            "--end",
            "2025-06-30",
            "--config-out",
            str(config_out),
        ]
    )
    assert rc == 0
    written = json.loads(config_out.read_text(encoding="utf-8"))
    assert written["candidate_request"] == {
        "candidate_id": "cand-wiring",
        "manifest_digest": digest,
    }
    assert written["symbols"] == ["SPY", "QQQ"]
    # PR-2: default provider is futu (tiingo is explicit opt-in).
    assert seen == {
        "config_path": str(config_out),
        "provider": "futu",
        "candidate_id": "cand-wiring",
        "expected_manifest_digest": digest,
        "output_dir": str(cli.config.FACTOR_EXPERIMENT_OUTPUT_DIR),
    }
    out = capsys.readouterr().out
    assert "sharpe=1.42" in out
    assert "research evidence" in out.lower()
    assert "gate 3 code-review workspace" in out.lower()


def test_backtest_rejects_unsafe_candidate_id_before_writing_config(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        cli,
        "_write_experiment_config",
        lambda *args, **kwargs: pytest.fail("unsafe candidate id reached config write"),
    )
    monkeypatch.setattr(
        cli.quant_cli,
        "run_experiment_config",
        lambda *args, **kwargs: pytest.fail("unsafe candidate id reached platform"),
    )

    rc = cli.main(
        [
            "backtest",
            "--candidate-id",
            "../../escaped",
            "--expected-digest",
            "a" * 64,
            "--symbol",
            "SPY",
            "--start",
            "2020-01-02",
            "--end",
            "2026-06-30",
        ]
    )

    assert rc == 2
    assert "candidate-id" in capsys.readouterr().out


def test_backtest_rejects_synthetic_provider_before_platform(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        cli.quant_cli,
        "run_experiment_config",
        lambda *args, **kwargs: pytest.fail("synthetic provider reached platform"),
    )

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "backtest",
                "--candidate-id", "cand-real-source",
                "--expected-digest", "a" * 64,
                "--symbol", "SPY",
                "--start", "2020-01-02",
                "--end", "2026-06-30",
                "--provider", "sample",
                "--config-out", str(tmp_path / "must-not-exist.json"),
                "--final",
            ]
        )

    assert exc.value.code == 2
    assert not (tmp_path / "must-not-exist.json").exists()


def test_backtest_rejects_synthetic_provider_from_environment_default(
    monkeypatch, capsys, tmp_path
) -> None:
    monkeypatch.setattr(cli.config, "DEFAULT_DATA_PROVIDER", "sample")
    monkeypatch.setattr(
        cli.quant_cli,
        "run_experiment_config",
        lambda *args, **kwargs: pytest.fail("invalid default provider reached platform"),
    )

    rc = cli.main(
        [
            "backtest",
            "--candidate-id", "cand-real-source",
            "--expected-digest", "a" * 64,
            "--symbol", "SPY",
            "--start", "2020-01-02",
            "--end", "2026-06-30",
            "--config-out", str(tmp_path / "must-not-exist.json"),
            "--final",
        ]
    )

    captured = capsys.readouterr()
    assert rc == 2
    assert "synthetic providers cannot execute" in captured.err
    assert not (tmp_path / "must-not-exist.json").exists()


def test_default_backtest_configs_are_unique_and_explicit_paths_are_exclusive(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(cli.config, "REPO_DIR", tmp_path)
    first = cli._default_config_path("cand-safe", "a" * 64)
    second = cli._default_config_path("cand-safe", "a" * 64)
    assert first != second
    assert first.parent == second.parent

    cli._write_experiment_config(
        first,
        "cand-safe",
        "a" * 64,
        ["SPY"],
        "2020-01-02",
        "2025-12-29",
    )
    with pytest.raises(FileExistsError):
        cli._write_experiment_config(
            first,
            "cand-safe",
            "a" * 64,
            ["SPY"],
            "2020-01-02",
            "2025-12-29",
        )


def test_backtest_refuses_exact_candidate_without_gate1_binding(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    config_out = tmp_path / "experiment.json"
    monkeypatch.setattr(
        cli.factor_repro,
        "require_gate1_candidate_binding",
        lambda **kwargs: (_ for _ in ()).throw(ValueError("Gate 1 binding missing")),
    )
    monkeypatch.setattr(
        cli.quant_cli,
        "run_experiment_config",
        lambda *args, **kwargs: pytest.fail("unbound Scene-B candidate must not execute"),
    )

    rc = cli.main([
        "backtest",
        "--candidate-id", "factor-x-1",
        "--expected-digest", "a" * 64,
        "--symbol", "SPY",
        "--start", "2020-01-01",
        "--end", "2024-12-31",
        "--config-out", str(config_out),
    ])

    assert rc == 2
    assert "Gate 1 binding missing" in capsys.readouterr().err
    assert not config_out.exists()


def test_backtest_passes_the_human_candidate_binding_to_the_platform(
    monkeypatch,
    capsys,
    tmp_path,
) -> None:
    digest = "d" * 64
    seen = {}

    def fake_run_experiment_config(
        config_path,
        *,
        candidate_id,
        expected_manifest_digest,
        output_dir,
        provider="futu",
    ):
        seen.update(
            config_path=config_path,
            candidate_id=candidate_id,
            expected_manifest_digest=expected_manifest_digest,
            output_dir=output_dir,
            provider=provider,
        )
        return (
            0,
            json.dumps(
                _experiment_receipt(
                    config_path,
                    candidate_id=candidate_id,
                    expected_manifest_digest=expected_manifest_digest,
                    provider=provider,
                    factor_id="derived_factor",
                    output_dir=output_dir,
                )
            ),
        )

    monkeypatch.setattr(cli.quant_cli, "run_experiment_config", fake_run_experiment_config)
    monkeypatch.setattr(cli.config, "LOG_DIR", tmp_path)
    config_out = tmp_path / "candidate-exp.json"

    rc = cli.main(
        [
            "backtest",
            "--candidate-id",
            "cand-bound",
            "--expected-digest",
            digest,
            "--symbol",
            "SPY",
            "--start",
            "2020-01-02",
            "--end",
            "2026-06-30",
            "--config-out",
            str(config_out),
        ]
    )

    assert rc == 0
    assert seen == {
        "config_path": str(config_out),
        "candidate_id": "cand-bound",
        "expected_manifest_digest": digest,
        "output_dir": str(cli.config.FACTOR_EXPERIMENT_OUTPUT_DIR),
        "provider": "futu",
    }
    assert "factor_id=derived_factor" in capsys.readouterr().out


def test_backtest_refuses_a_mismatched_platform_candidate_receipt(
    monkeypatch,
    tmp_path,
) -> None:
    digest = "e" * 64
    monkeypatch.setattr(
        cli.quant_cli,
        "run_experiment_config",
        lambda *a, **k: (
            0,
            json.dumps(
                {
                    "experiment_id": "e-wrong",
                    "candidate_binding": {
                        "candidate_id": "cand-other",
                        "manifest_digest": digest,
                        "factor_id": "wrong_factor",
                    },
                }
            ),
        ),
    )
    monkeypatch.setattr(cli.config, "LOG_DIR", tmp_path)

    rc = cli.main(
        [
            "backtest",
            "--candidate-id",
            "cand-expected",
            "--expected-digest",
            digest,
            "--symbol",
            "SPY",
            "--start",
            "2020-01-02",
            "--end",
            "2026-06-30",
            "--config-out",
            str(tmp_path / "exp.json"),
        ]
    )

    assert rc == 1
    assert not (tmp_path / "factor_trials.jsonl").exists()


def test_backtest_rejects_malformed_agent_summary_without_traceback(
    monkeypatch, capsys, tmp_path
) -> None:
    digest = "f" * 64

    def malformed_summary(
        config_path,
        *,
        candidate_id,
        expected_manifest_digest,
        output_dir,
        provider="futu",
    ):
        receipt = _experiment_receipt(
            config_path,
            candidate_id=candidate_id,
            expected_manifest_digest=expected_manifest_digest,
            provider=provider,
            output_dir=output_dir,
        )
        summary_path = Path(receipt["agent_summary"])
        summary_path.write_bytes(b"{not-json\n")
        receipt["agent_summary_sha256"] = hashlib.sha256(
            summary_path.read_bytes()
        ).hexdigest()
        return 0, json.dumps(receipt)

    monkeypatch.setattr(cli.quant_cli, "run_experiment_config", malformed_summary)
    monkeypatch.setattr(cli.config, "LOG_DIR", tmp_path)
    rc = cli.main(
        [
            "backtest",
            "--candidate-id", "cand-corrupt-summary",
            "--expected-digest", digest,
            "--symbol", "SPY",
            "--start", "2020-01-02",
            "--end", "2026-06-30",
            "--config-out", str(tmp_path / "corrupt-summary.json"),
        ]
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert "experiment evidence verification failed" in captured.err
    assert "Traceback" not in captured.out + captured.err


def test_backtest_timeout_records_no_trial_or_final_authority(
    monkeypatch, capsys, tmp_path
) -> None:
    monkeypatch.setattr(
        cli.quant_cli,
        "run_experiment_config",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired("run-config", 300)
        ),
    )
    monkeypatch.setattr(cli.config, "LOG_DIR", tmp_path)

    rc = cli.main(
        [
            "backtest",
            "--candidate-id", "cand-timeout",
            "--expected-digest", "f" * 64,
            "--symbol", "SPY",
            "--start", "2020-01-02",
            "--end", "2026-06-30",
            "--config-out", str(tmp_path / "timeout.json"),
            "--final",
        ]
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert "outcome is unknown" in captured.err
    assert "outcome_unknown=true" in captured.out
    assert not (tmp_path / "factor_trials.jsonl").exists()
    assert not (cli.config.FACTOR_GATE1_DIR / "backtests").exists()


def _fake_experiment_receipt(
    config_path,
    *,
    candidate_id,
    expected_manifest_digest,
    output_dir,
    provider="futu",
):
    factor_id = candidate_id.removeprefix("cand-")
    return (
        0,
        json.dumps(
            _experiment_receipt(
                config_path,
                candidate_id=candidate_id,
                expected_manifest_digest=expected_manifest_digest,
                provider=provider,
                factor_id=factor_id,
                output_dir=output_dir,
            )
        ),
    )


def test_backtest_non_final_writes_cut_end_and_prints_holdout(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli.quant_cli, "run_experiment_config", _fake_experiment_receipt)
    monkeypatch.setattr(cli.config, "LOG_DIR", tmp_path)
    config_out = tmp_path / "exp.json"
    rc = cli.main(
        [
            "backtest",
            "--candidate-id", "cand-holdout_factor",
            "--expected-digest", "2" * 64,
            "--symbol", "SPY",
            "--start", "2020-01-02",
            "--end", "2026-06-30",
            "--config-out", str(config_out),
        ]
    )
    assert rc == 0
    written = json.loads(config_out.read_text(encoding="utf-8"))
    assert written["end"] == "2025-12-29"  # 2026-06-30 minus 183 days
    out = capsys.readouterr().out
    assert "HOLDOUT: last 183 days reserved" in out
    assert "final_backtest_receipt=" not in out
    assert not (cli.config.FACTOR_GATE1_DIR / "backtests").exists()


def test_backtest_final_writes_full_end_and_no_holdout_note(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli.quant_cli, "run_experiment_config", _fake_experiment_receipt)
    monkeypatch.setattr(cli.config, "LOG_DIR", tmp_path)
    config_out = tmp_path / "exp.json"
    rc = cli.main(
        [
            "backtest",
            "--candidate-id", "cand-holdout_factor",
            "--expected-digest", "2" * 64,
            "--symbol", "SPY",
            "--start", "2020-01-02",
            "--end", "2026-06-30",
            "--config-out", str(config_out),
            "--final",
        ]
    )
    assert rc == 0
    written = json.loads(config_out.read_text(encoding="utf-8"))
    assert written["end"] == "2026-06-30"
    out = capsys.readouterr().out
    assert "HOLDOUT" not in out
    assert "final_backtest_receipt=backtest-" in out
    receipts = list((cli.config.FACTOR_GATE1_DIR / "backtests").glob("*.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
    assert receipt["candidate_id"] == "cand-holdout_factor"
    assert receipt["manifest_digest"] == "2" * 64
    assert receipt["final"] is True


def test_backtest_records_trial_and_final_flag(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli.quant_cli, "run_experiment_config", _fake_experiment_receipt)
    monkeypatch.setattr(cli.config, "LOG_DIR", tmp_path)
    config_out = tmp_path / "exp.json"
    cli.main(
        [
            "backtest",
            "--candidate-id", "cand-rec_factor",
            "--expected-digest", "3" * 64,
            "--symbol", "SPY",
            "--start", "2020-01-02",
            "--end", "2026-06-30",
            "--config-out", str(config_out),
            "--final",
        ]
    )
    from hqa import trials
    log = tmp_path / "factor_trials.jsonl"
    assert trials.count_trials("rec_factor", log) == 1
    record = json.loads(log.read_text(encoding="utf-8").strip())
    assert record["final"] is True
    assert record["factor_id"] == "rec_factor"


def test_backtest_third_run_prints_overfit_warning(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli.quant_cli, "run_experiment_config", _fake_experiment_receipt)
    monkeypatch.setattr(cli.config, "LOG_DIR", tmp_path)
    for index in range(3):
        argv = [
            "backtest",
            "--candidate-id", "cand-iter_factor",
            "--expected-digest", "4" * 64,
            "--symbol", "SPY",
            "--start", "2020-01-02",
            "--end", "2026-06-30",
            "--config-out", str(tmp_path / f"exp-{index}.json"),
        ]
        assert cli.main(argv) == 0
        out = capsys.readouterr().out
        if index < 2:
            assert "OVERFIT WARNING" not in out
        else:
            assert "OVERFIT WARNING" in out


def test_backtest_window_too_short_returns_error(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli.quant_cli, "run_experiment_config", _fake_experiment_receipt)
    monkeypatch.setattr(cli.config, "LOG_DIR", tmp_path)
    config_out = tmp_path / "exp.json"
    rc = cli.main(
        [
            "backtest",
            "--candidate-id", "cand-short_factor",
            "--expected-digest", "5" * 64,
            "--symbol", "SPY",
            "--start", "2026-01-01",
            "--end", "2026-06-30",
            "--config-out", str(config_out),
        ]
    )
    assert rc == 1
    assert not config_out.exists()


def test_no_auto_pipeline_subcommand():
    with pytest.raises(SystemExit):
        cli.main(["auto"])

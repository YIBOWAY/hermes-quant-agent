from __future__ import annotations

import json

import pytest

from hqa import factor_repro_cli as cli


def test_propose_prints_candidate_id_and_human_gate(monkeypatch, capsys):
    digest = "a" * 64
    monkeypatch.setattr(
        cli.quant_cli,
        "run_propose_factor",
        lambda goal, source_file, universe="SPY,QQQ": (
            0,
            f"candidate_id=factor-x-1 status=pending manifest_digest={digest}\n"
            + json.dumps(
                {
                    "candidate_id": "factor-x-1",
                    "status": "pending",
                    "manifest_digest": digest,
                }
            ),
        ),
    )
    rc = cli.main(["propose", "--goal", "momentum 20d reversal", "--source-file", "/tmp/factor_src.py"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "factor-x-1" in out
    assert f"manifest_digest={digest}" in out
    assert "status=pending" in out
    assert f"--expected-digest {digest}" in out
    assert "--expected-status pending" in out
    assert "HUMAN GATE" in out
    assert "never refetch" in out.lower()


def test_propose_returns_nonzero_when_candidate_id_missing(monkeypatch, capsys):
    monkeypatch.setattr(
        cli.quant_cli,
        "run_propose_factor",
        lambda goal, source_file, universe="SPY,QQQ": (0, "unexpected output"),
    )
    rc = cli.main(["propose", "--goal", "momentum 20d reversal", "--source-file", "/tmp/factor_src.py"])
    assert rc == 1
    assert "candidate_id=?" in capsys.readouterr().out


def test_approve_requires_explicit_human_cas_values_and_never_refetches(
    monkeypatch, capsys
) -> None:
    seen = {}
    monkeypatch.setattr(
        cli.quant_cli,
        "run_list_candidates",
        lambda *args, **kwargs: pytest.fail("approve must not refetch"),
    )
    monkeypatch.setattr(
        cli.quant_cli,
        "run_agent_review",
        lambda **kwargs: seen.update(kwargs) or (0, "ok"),
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
        "candidate_id": "factor-x-1",
        "decision": "approve",
        "note": "translation confirmed",
        "expected_manifest_digest": "a" * 64,
        "expected_status": "pending",
    }


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


def test_list_prints_verified_digest_and_disables_migration_corrupt(monkeypatch, capsys):
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
    assert f"manifest_digest={digest}" in out
    assert f"--expected-digest {digest}" in out
    assert "--expected-status pending" in out
    assert f"observed_manifest_digest={observed}" in out
    assert "migration evidence; approval disabled" in out
    assert "corrupt; no digest/source" in out
    # Observed digest is never substituted into an approve command.
    assert f"--expected-digest {observed}" not in out


def test_backtest_builds_config_runs_experiment_and_prints_metrics(monkeypatch, capsys, tmp_path):
    summary_file = tmp_path / "agent_summary.json"
    summary_file.write_text(
        json.dumps(
            {
                "best_run_id": "run-001",
                "runs": [
                    {"run_id": "run-001", "sharpe": 1.42, "total_return": 0.183, "max_drawdown": 0.061}
                ],
            }
        ),
        encoding="utf-8",
    )
    seen = {}

    def fake_run_experiment_config(config_path, provider="futu", include_approved=True):
        seen.update(config_path=config_path, provider=provider, include_approved=include_approved)
        return (
            0,
            "experiment_id=e-1 run_count=1 best_run_id=run-001 config=/x runs=/x folds=/x "
            f"agent_summary={summary_file} report=/x/report.md",
        )

    monkeypatch.setattr(cli.quant_cli, "run_experiment_config", fake_run_experiment_config)
    monkeypatch.setattr(cli.config, "LOG_DIR", tmp_path)
    config_out = tmp_path / "exp.json"
    rc = cli.main(
        [
            "backtest",
            "--factor-id",
            "wiring_test_factor",
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
    assert written["factor_blend"]["factors"] == [{"factor_id": "wiring_test_factor"}]
    assert written["symbols"] == ["SPY", "QQQ"]
    # PR-2: default provider is futu (tiingo is explicit opt-in).
    assert seen == {"config_path": str(config_out), "provider": "futu", "include_approved": True}
    out = capsys.readouterr().out
    assert "sharpe=1.42" in out
    assert "proposal-only" in out.lower()


def _fake_experiment_no_summary(config_path, provider="futu", include_approved=True):
    return (0, "experiment_id=e-1 best_run_id=run-001 report=/x/report.md")


def test_backtest_non_final_writes_cut_end_and_prints_holdout(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli.quant_cli, "run_experiment_config", _fake_experiment_no_summary)
    monkeypatch.setattr(cli.config, "LOG_DIR", tmp_path)
    config_out = tmp_path / "exp.json"
    rc = cli.main(
        [
            "backtest",
            "--factor-id", "holdout_factor",
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


def test_backtest_final_writes_full_end_and_no_holdout_note(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli.quant_cli, "run_experiment_config", _fake_experiment_no_summary)
    monkeypatch.setattr(cli.config, "LOG_DIR", tmp_path)
    config_out = tmp_path / "exp.json"
    rc = cli.main(
        [
            "backtest",
            "--factor-id", "holdout_factor",
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


def test_backtest_records_trial_and_final_flag(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli.quant_cli, "run_experiment_config", _fake_experiment_no_summary)
    monkeypatch.setattr(cli.config, "LOG_DIR", tmp_path)
    config_out = tmp_path / "exp.json"
    cli.main(
        [
            "backtest",
            "--factor-id", "rec_factor",
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
    monkeypatch.setattr(cli.quant_cli, "run_experiment_config", _fake_experiment_no_summary)
    monkeypatch.setattr(cli.config, "LOG_DIR", tmp_path)
    config_out = tmp_path / "exp.json"
    argv = [
        "backtest",
        "--factor-id", "iter_factor",
        "--symbol", "SPY",
        "--start", "2020-01-02",
        "--end", "2026-06-30",
        "--config-out", str(config_out),
    ]
    cli.main(argv)
    assert "OVERFIT WARNING" not in capsys.readouterr().out
    cli.main(argv)
    assert "OVERFIT WARNING" not in capsys.readouterr().out
    cli.main(argv)
    assert "OVERFIT WARNING" in capsys.readouterr().out


def test_backtest_window_too_short_returns_error(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli.quant_cli, "run_experiment_config", _fake_experiment_no_summary)
    monkeypatch.setattr(cli.config, "LOG_DIR", tmp_path)
    config_out = tmp_path / "exp.json"
    rc = cli.main(
        [
            "backtest",
            "--factor-id", "short_factor",
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

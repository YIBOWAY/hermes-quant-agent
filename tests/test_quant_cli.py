from __future__ import annotations

import subprocess

import pytest

from hqa import config, quant_cli


class _FakeProc:
    def __init__(self, returncode, stdout, stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_run_doctor_invokes_cli_with_cwd(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        return _FakeProc(0, "safety.dry_run=true\n")

    monkeypatch.setattr(quant_cli.subprocess, "run", fake_run)
    code, out = quant_cli.run_doctor()
    assert code == 0
    assert "safety.dry_run=true" in out
    assert seen["argv"][0].endswith("quant-system")
    assert seen["argv"][1] == "doctor"
    assert seen["kwargs"]["cwd"] == str(config.AIQP_DIR)
    assert seen["kwargs"]["stderr"] is subprocess.STDOUT
    assert seen["kwargs"]["timeout"] == 300
    assert seen["argv"][-1] == "--json"


def test_run_paper_account_snapshot_keeps_json_stdout_clean(monkeypatch):
    seen = {}
    payload = '{"account_id":"default","account_exists":false,"account":null}\n'

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        return _FakeProc(
            0,
            payload,
            stderr="paper account reconciliation unavailable\ntraceback noise\n",
        )

    monkeypatch.setattr(quant_cli.subprocess, "run", fake_run)

    code, out = quant_cli.run_paper_account_snapshot()

    assert code == 0
    assert out == payload
    assert seen["argv"][1:] == [
        "paper",
        "account-show",
        "--account",
        "default",
        "--format",
        "json",
    ]
    assert seen["kwargs"]["stderr"] is subprocess.PIPE


def test_run_paper_account_snapshot_returns_stderr_when_cli_crashes_before_json(
    monkeypatch,
):
    def fake_run(_argv, **_kwargs):
        return _FakeProc(2, "", stderr="unexpected CLI failure\n")

    monkeypatch.setattr(quant_cli.subprocess, "run", fake_run)

    code, out = quant_cli.run_paper_account_snapshot(account_id="research")

    assert code == 2
    assert out == "unexpected CLI failure\n"


def test_run_historical_prices_uses_strict_futu_qfq_json_contract(monkeypatch):
    seen = {}
    payload = '{"provider":"futu","symbols":["AAPL","SPY"]}\n'

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        return _FakeProc(0, payload, stderr="Futu lifecycle noise\n")

    monkeypatch.setattr(quant_cli.subprocess, "run", fake_run)

    code, out = quant_cli.run_historical_prices(
        ["AAPL", "SPY"],
        "2025-06-01",
        "2026-07-10",
    )

    assert code == 0
    assert out == payload
    assert seen["argv"][1:] == [
        "data",
        "prices",
        "--symbol",
        "AAPL",
        "--symbol",
        "SPY",
        "--start",
        "2025-06-01",
        "--end",
        "2026-07-10",
        "--provider",
        "futu",
        "--adjustment",
        "qfq",
        "--format",
        "json",
    ]
    assert seen["kwargs"]["stderr"] is subprocess.PIPE


def test_run_paper_strategy_observations_uses_bounded_read_only_json_contract(
    monkeypatch,
):
    seen = {}
    payload = '{"schema_version":"1.0","read_status":"empty","observations":[]}\n'

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        return _FakeProc(0, payload, stderr="diagnostic noise\n")

    monkeypatch.setattr(quant_cli.subprocess, "run", fake_run)

    code, out = quant_cli.run_paper_strategy_observations(
        from_date="2026-07-01",
        to_date="2026-07-12",
        signal_id="signal-abc123",
        limit=200,
    )

    assert code == 0
    assert out == payload
    assert seen["argv"][1:] == [
        "paper",
        "strategies",
        "observations",
        "--from-date",
        "2026-07-01",
        "--to-date",
        "2026-07-12",
        "--signal-id",
        "signal-abc123",
        "--limit",
        "200",
        "--format",
        "json",
    ]
    assert seen["kwargs"]["stderr"] is subprocess.PIPE


def test_run_paper_strategy_observations_omits_unspecified_filters(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return _FakeProc(0, "{}\n")

    monkeypatch.setattr(quant_cli.subprocess, "run", fake_run)

    quant_cli.run_paper_strategy_observations(limit=25)

    assert seen["argv"][1:] == [
        "paper",
        "strategies",
        "observations",
        "--limit",
        "25",
        "--format",
        "json",
    ]


def test_run_options_sample_scan_argv(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return _FakeProc(0, "candidates=1000\n")

    monkeypatch.setattr(quant_cli.subprocess, "run", fake_run)
    code, out = quant_cli.run_options_sample_scan()
    assert code == 0 and "candidates=1000" in out
    assert seen["argv"][1:] == ["options", "daily-scan", "--provider", "sample"]


def test_run_options_scan_default_argv_futu(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        return _FakeProc(0, "candidates=1000\n")

    monkeypatch.setattr(quant_cli.subprocess, "run", fake_run)
    code, out = quant_cli.run_options_scan()
    assert code == 0
    assert seen["argv"][1:] == ["options", "daily-scan", "--provider", "futu"]
    assert seen["kwargs"]["timeout"] == 3600


def test_run_factor_lab_default_argv_futu(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return _FakeProc(0, "cross_rows=5 timing_rows=5\n")

    monkeypatch.setattr(quant_cli.subprocess, "run", fake_run)
    code, out = quant_cli.run_factor_lab()
    assert code == 0
    assert seen["argv"][1:] == ["factor", "refresh-lab", "--provider", "futu"]


def test_run_propose_factor_argv(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return _FakeProc(0, "candidate_id=factor-x-1 status=pending")

    monkeypatch.setattr(quant_cli.subprocess, "run", fake_run)
    code, out = quant_cli.run_propose_factor("momentum 20d", "/tmp/factor_src.py", "SPY,QQQ")
    assert code == 0
    assert "candidate_id=factor-x-1" in out
    assert seen["argv"][1:] == [
        "agent",
        "propose-factor",
        "--goal",
        "momentum 20d",
        "--universe",
        "SPY,QQQ",
        "--source-file",
        "/tmp/factor_src.py",
        "--json",
    ]


def test_run_list_candidates_argv(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return _FakeProc(0, "candidate_id=factor-x-1 status=pending")

    monkeypatch.setattr(quant_cli.subprocess, "run", fake_run)
    code, out = quant_cli.run_list_candidates()
    assert code == 0
    assert "candidate_id=factor-x-1" in out
    assert seen["argv"][1:] == ["agent", "list-candidates"]


def test_run_agent_review_argv(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return _FakeProc(0, "ok")

    monkeypatch.setattr(quant_cli.subprocess, "run", fake_run)
    digest = "a" * 64
    quant_cli.run_agent_review(
        candidate_id="factor-x-1",
        decision="approve",
        note="translation confirmed",
        expected_manifest_digest=digest,
        expected_status="pending",
    )
    assert seen["argv"][1:] == [
        "agent",
        "review",
        "--candidate-id",
        "factor-x-1",
        "--decision",
        "approve",
        "--note",
        "translation confirmed",
        "--expected-digest",
        digest,
        "--expected-status",
        "pending",
        "--json",
    ]


def test_run_agent_review_is_keyword_only():
    with pytest.raises(TypeError):
        quant_cli.run_agent_review(  # type: ignore[misc]
            "factor-x-1",
            "approve",
            "note",
            "a" * 64,
            "pending",
        )


def test_run_agent_auto_review_binds_policy_and_intake_digests(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return _FakeProc(0, '{"registration":"auto_promote"}\n')

    monkeypatch.setattr(quant_cli.subprocess, "run", fake_run)
    quant_cli.run_agent_auto_review(
        candidate_id="factor-x-1",
        expected_manifest_digest="a" * 64,
        expected_status="pending",
        policy_digest="b" * 64,
        intake_contract_digest="c" * 64,
    )

    assert seen["argv"][1:] == [
        "agent",
        "auto-review",
        "--candidate-id",
        "factor-x-1",
        "--expected-digest",
        "a" * 64,
        "--expected-status",
        "pending",
        "--policy-digest",
        "b" * 64,
        "--intake-contract-digest",
        "c" * 64,
        "--json",
    ]


def test_run_promote_candidate_uses_exact_gate3_binding_and_clean_json(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        return _FakeProc(0, '{"promotion_id":"promotion-1"}\n', stderr="instructions\n")

    monkeypatch.setattr(quant_cli.subprocess, "run", fake_run)
    code, out = quant_cli.run_promote_candidate(
        candidate_id="factor-x-1",
        expected_manifest_digest="a" * 64,
        final_backtest_receipt="backtest-" + "c" * 32,
        base_commit="b" * 40,
    )

    assert code == 0
    assert out == '{"promotion_id":"promotion-1"}\n'
    assert seen["argv"][1:] == [
        "agent",
        "promote-candidate",
        "--candidate-id",
        "factor-x-1",
        "--expected-digest",
        "a" * 64,
        "--final-backtest-receipt",
        "backtest-" + "c" * 32,
        "--base-commit",
        "b" * 40,
    ]
    assert seen["kwargs"]["stderr"] is subprocess.PIPE


def test_run_promotion_status_uses_only_the_promotion_identity(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        return _FakeProc(
            0,
            '{"promotion_id":"promo-abc","status":"awaiting_human_commit"}\n',
            stderr="",
        )

    monkeypatch.setattr(quant_cli.subprocess, "run", fake_run)
    code, out = quant_cli.run_promotion_status("promo-abc")

    assert code == 0
    assert '"status":"awaiting_human_commit"' in out
    assert seen["argv"][1:] == [
        "agent",
        "promotion-status",
        "--promotion-id",
        "promo-abc",
    ]
    assert seen["kwargs"]["stderr"] is subprocess.PIPE


def test_run_auto_promotion_commands_bind_two_phase_cas(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv[1:])
        return _FakeProc(0, '{}\n')

    monkeypatch.setattr(quant_cli.subprocess, "run", fake_run)
    quant_cli.run_auto_promote_prepare(
        candidate_id="candidate-1",
        expected_manifest_digest="a" * 64,
        final_backtest_receipt="backtest-" + "b" * 32,
        base_commit="c" * 40,
        policy_digest="d" * 64,
        intake_contract_digest="e" * 64,
    )
    quant_cli.run_auto_promote_commit(promotion_id="promo-abc")
    quant_cli.run_auto_promote_land(
        promotion_id="promo-abc",
        expected_base_commit="c" * 40,
        expected_reviewed_commit="f" * 40,
    )

    assert calls == [
        [
            "agent",
            "promote-auto-prepare",
            "--candidate-id",
            "candidate-1",
            "--expected-digest",
            "a" * 64,
            "--final-backtest-receipt",
            "backtest-" + "b" * 32,
            "--base-commit",
            "c" * 40,
            "--policy-digest",
            "d" * 64,
            "--intake-contract-digest",
            "e" * 64,
        ],
        ["agent", "promote-auto-commit", "--promotion-id", "promo-abc"],
        [
            "agent",
            "promote-auto-land",
            "--promotion-id",
            "promo-abc",
            "--expected-base-commit",
            "c" * 40,
            "--expected-reviewed-commit",
            "f" * 40,
        ],
    ]


def test_run_factor_automation_authority_and_sleeve_bind_full_lineage(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv[1:])
        return _FakeProc(0, '{}\n')

    monkeypatch.setattr(quant_cli.subprocess, "run", fake_run)
    lineage = {
        "automation_id": "automation-0123456789abcdef",
        "candidate_id": "candidate-1",
        "candidate_digest": "a" * 64,
        "factor_id": "auto_factor",
        "manifest_digest": "b" * 64,
        "automation_policy_digest": "c" * 64,
        "intake_contract_digest": "d" * 64,
        "gate1_digest": "e" * 64,
        "gate2_digest": "f" * 64,
        "gate3_digest": "1" * 64,
        "commit_sha": "2" * 40,
    }
    quant_cli.run_factor_automation_authorize_land(
        automation_id=lineage["automation_id"],
        promotion_id="promo-abc",
        policy_digest=lineage["automation_policy_digest"],
        intake_contract_digest=lineage["intake_contract_digest"],
        gate1_digest=lineage["gate1_digest"],
        gate2_digest=lineage["gate2_digest"],
    )
    quant_cli.run_factor_automation_activate_sleeve(
        lineage=lineage,
        promotion_id="promo-abc",
        universe=("SPY", "QQQ"),
        provider="futu",
    )

    assert calls[0][:4] == [
        "agent",
        "factor-automation-authorize-land",
        "--automation-id",
        lineage["automation_id"],
    ]
    assert calls[1][:4] == [
        "agent",
        "factor-automation-activate-sleeve",
        "--automation-id",
        lineage["automation_id"],
    ]
    assert calls[1][-6:] == [
        "--symbol",
        "SPY",
        "--symbol",
        "QQQ",
        "--provider",
        "futu",
    ]


def test_run_experiment_config_default_provider_is_futu(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return _FakeProc(0, "experiment_id=e-1")

    monkeypatch.setattr(quant_cli.subprocess, "run", fake_run)
    quant_cli.run_experiment_config(
        "/tmp/exp.json",
        candidate_id="cand-exact",
        expected_manifest_digest="a" * 64,
        output_dir="/tmp/factor-experiments",
    )
    assert seen["argv"][1:] == [
        "experiment",
        "run-config",
        "--config",
        "/tmp/exp.json",
        "--provider",
        "futu",
        "--candidate-id",
        "cand-exact",
        "--expected-digest",
        "a" * 64,
        "--output-dir",
        "/tmp/factor-experiments",
        "--json",
    ]


def test_run_experiment_config_argv_tiingo_opt_in(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return _FakeProc(0, "experiment_id=e-1")

    monkeypatch.setattr(quant_cli.subprocess, "run", fake_run)
    quant_cli.run_experiment_config(
        "/tmp/exp.json",
        candidate_id="cand-exact",
        expected_manifest_digest="b" * 64,
        output_dir="/tmp/factor-experiments",
        provider="tiingo",
    )
    assert seen["argv"][1:] == [
        "experiment",
        "run-config",
        "--config",
        "/tmp/exp.json",
        "--provider",
        "tiingo",
        "--candidate-id",
        "cand-exact",
        "--expected-digest",
        "b" * 64,
        "--output-dir",
        "/tmp/factor-experiments",
        "--json",
    ]


def test_run_experiment_config_has_no_legacy_load_all_argument():
    with pytest.raises(TypeError):
        quant_cli.run_experiment_config(  # type: ignore[call-arg]
            "/tmp/exp.json",
            candidate_id="cand-exact",
            expected_manifest_digest="c" * 64,
            output_dir="/tmp/factor-experiments",
            include_approved=False,
        )


@pytest.mark.skipif(
    True, reason="manual — requires working quant-system environment; run with --no-skip to verify live"
)
def test_run_doctor_integration_real():
    code, out = quant_cli.run_doctor()
    assert code == 0
    assert "safety.dry_run=" in out

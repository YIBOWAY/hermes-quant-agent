from __future__ import annotations

import json

import pytest

from hqa import portfolio_risk


def _position(
    symbol: str,
    market_value: float,
    *,
    quantity: float = 1.0,
    equity: float = 100_000.0,
    price_kind: str = "futu_snapshot",
    price_as_of: str | None = "2026-07-10T15:55:00+00:00",
) -> dict:
    return {
        "symbol": symbol,
        "quantity": quantity,
        "avg_cost": abs(market_value / quantity) if quantity else 0.0,
        "last_price": abs(market_value / quantity) if quantity else 0.0,
        "market_value": market_value,
        "weight": market_value / equity if equity else 0.0,
        "unrealized_pnl": 0.0,
        "source_breakdown": {"manual": 1.0},
        "price_kind": price_kind,
        "price_as_of": price_as_of,
    }


def _snapshot(
    positions: list[dict] | None = None,
    *,
    account_exists: bool = True,
    cash: float | None = None,
    equity: float = 100_000.0,
    stale: bool = False,
    warnings: list[str] | None = None,
    reconciliation_status: str = "not_applicable",
    pending_orders: list[dict] | None = None,
    base_currency: str = "USD",
) -> dict:
    if not account_exists:
        return {
            "account_id": "default",
            "account_exists": False,
            "account": None,
        }
    positions = positions or []
    if cash is None:
        cash = equity - sum(row["market_value"] for row in positions)
    return {
        "account_id": "default",
        "account_exists": True,
        "account": {
            "account_id": "default",
            "base_currency": base_currency,
            "initial_cash": 100_000.0,
            "cash": cash,
            "reserved_cash": 0.0,
            "available_cash": cash,
            "equity": equity,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "pnl_abs": 0.0,
            "pnl_pct": 0.0,
            "invested_pct": sum(row["market_value"] for row in positions) / equity
            if equity
            else 0.0,
            "kill_switch": False,
            "price_source": {"kind": "mixed", "as_of": None},
            "positions": positions,
            "pending_orders": pending_orders or [],
            "created_at": "2026-07-01T00:00:00+00:00",
            "updated_at": "2026-07-10T15:55:00+00:00",
            "storage_mode": "file",
            "stale": stale,
            "warnings": warnings or [],
            "reconciliation": {
                "status": reconciliation_status,
                "account_id": "default",
                "source": "file",
                "target": None,
                "checked_at": "2026-07-10T15:55:00+00:00",
                "expected_summary": {},
                "actual_summary": {},
                "differences": [],
            },
        },
    }


def test_parse_snapshot_accepts_complete_pretty_json_only() -> None:
    payload = _snapshot([_position("AAPL", 10_000.0)])

    parsed = portfolio_risk.parse_snapshot(json.dumps(payload, indent=2))

    assert parsed["account_exists"] is True
    assert parsed["account"]["positions"][0]["symbol"] == "AAPL"
    with pytest.raises(portfolio_risk.PortfolioRiskSnapshotError):
        portfolio_risk.parse_snapshot(json.dumps(payload) + "\nprovider noise")


@pytest.mark.parametrize(
    "output",
    [
        '{"account_id":"default","account_exists":false,'
        '"account":null,"account_id":"other"}',
        '{"account_id":"default","account_exists":false,'
        '"account":null,"extra":Infinity}',
        "[]",
    ],
)
def test_parse_snapshot_rejects_duplicate_keys_infinity_and_non_object(output) -> None:
    with pytest.raises(portfolio_risk.PortfolioRiskSnapshotError):
        portfolio_risk.parse_snapshot(output)


@pytest.mark.parametrize(
    "payload",
    [
        {"exists": False, "positions": []},
        {
            "account_id": "default",
            "account_exists": True,
            "account": {"account_id": "default"},
        },
        _snapshot(
            [
                _position("AAPL", 10_000.0),
                _position("aapl", 5_000.0),
            ]
        ),
        _snapshot([_position("AAPL", float("nan"))]),
    ],
)
def test_parse_snapshot_rejects_old_malformed_duplicate_and_non_finite_contracts(
    payload,
) -> None:
    with pytest.raises(portfolio_risk.PortfolioRiskSnapshotError) as excinfo:
        portfolio_risk.parse_snapshot(json.dumps(payload))

    assert excinfo.value.code == "portfolio_risk_snapshot_invalid"


def test_missing_account_is_not_applicable_not_cash_only() -> None:
    artifact = portfolio_risk.analyze_snapshot(
        _snapshot(account_exists=False),
        generated_at="2026-07-10T16:00:00+00:00",
    )

    assert artifact["status"] == "not_applicable"
    assert artifact["reason_codes"] == ["paper_account_not_found"]
    assert artifact["account"]["account_exists"] is False
    assert artifact["exposure"] is None
    assert artifact["concentration"] is None
    assert "does not exist" in portfolio_risk.build_report(artifact)


def test_cash_only_account_has_zero_exposure_and_no_concentration_claim() -> None:
    artifact = portfolio_risk.analyze_snapshot(
        _snapshot(),
        generated_at="2026-07-10T16:00:00+00:00",
    )

    assert artifact["status"] == "available"
    assert artifact["portfolio_state"] == "cash_only"
    assert artifact["exposure"]["gross_value"] == pytest.approx(0.0)
    assert artifact["exposure"]["net_value"] == pytest.approx(0.0)
    assert artifact["concentration"] == {
        "status": "not_applicable",
        "basis": "absolute_market_value",
        "top1_gross_pct": None,
        "top3_gross_pct": None,
        "hhi_gross": None,
        "largest_symbol": None,
    }
    report = portfolio_risk.build_report(artifact)
    assert "cash-only" in report
    assert "does not claim that all financial risks are zero" in report


def test_cash_only_report_still_discloses_excluded_pending_orders() -> None:
    artifact = portfolio_risk.analyze_snapshot(
        _snapshot(pending_orders=[{"order_id": "pending-1"}]),
        generated_at="2026-07-10T16:00:00+00:00",
    )

    report = portfolio_risk.build_report(artifact)
    assert artifact["account"]["pending_order_count"] == 1
    assert "Pending orders excluded from current exposure: 1" in report


def test_single_position_reports_invested_and_account_concentration_separately() -> None:
    positions = [_position("AAPL", 312.9, equity=1_000_004.27)]
    artifact = portfolio_risk.analyze_snapshot(
        _snapshot(positions, cash=999_691.37, equity=1_000_004.27),
        generated_at="2026-07-10T16:00:00+00:00",
    )

    assert artifact["status"] == "available"
    assert artifact["exposure"]["gross_value"] == pytest.approx(312.9)
    assert artifact["exposure"]["gross_pct_equity"] == pytest.approx(
        312.9 / 1_000_004.27
    )
    assert artifact["concentration"]["top1_gross_pct"] == pytest.approx(1.0)
    assert artifact["concentration"]["hhi_gross"] == pytest.approx(1.0)
    assert artifact["positions"][0]["account_weight"] == pytest.approx(
        312.9 / 1_000_004.27
    )
    assert artifact["positions"][0]["gross_share"] == pytest.approx(1.0)
    assert artifact["positions"][0]["price_age_seconds"] == pytest.approx(300.0)
    report = portfolio_risk.build_report(artifact)
    assert "100.00% of invested exposure" in report
    assert "0.0313% of account equity" in report
    assert "no threshold configured" in report.lower()


def test_long_short_and_multi_position_formulas_are_directionally_correct() -> None:
    equity = 90_000.0
    positions = [
        _position("AAPL", 30_000.0, equity=equity),
        _position("MSFT", 20_000.0, equity=equity),
        _position("TLT", 10_000.0, equity=equity),
        _position("SHORT", -10_000.0, quantity=-1.0, equity=equity),
    ]
    artifact = portfolio_risk.analyze_snapshot(
        _snapshot(positions, cash=40_000.0, equity=equity),
        generated_at="2026-07-10T16:00:00+00:00",
    )

    exposure = artifact["exposure"]
    assert exposure["long_value"] == pytest.approx(60_000.0)
    assert exposure["short_value"] == pytest.approx(10_000.0)
    assert exposure["gross_value"] == pytest.approx(70_000.0)
    assert exposure["net_value"] == pytest.approx(50_000.0)
    assert exposure["gross_pct_equity"] == pytest.approx(7 / 9)
    assert exposure["net_pct_equity"] == pytest.approx(5 / 9)
    concentration = artifact["concentration"]
    assert concentration["top1_gross_pct"] == pytest.approx(3 / 7)
    assert concentration["top3_gross_pct"] == pytest.approx(6 / 7)
    assert concentration["hhi_gross"] == pytest.approx(15 / 49)
    assert [row["symbol"] for row in artifact["positions"]] == [
        "AAPL",
        "MSFT",
        "SHORT",
        "TLT",
    ]


def test_fallback_and_repository_warning_degrade_but_keep_estimated_exposure() -> None:
    equity = 100_000.0
    positions = [
        _position("AAPL", 30_000.0, equity=equity),
        _position(
            "MSFT",
            20_000.0,
            equity=equity,
            price_kind="avg_cost_fallback",
        ),
    ]
    artifact = portfolio_risk.analyze_snapshot(
        _snapshot(
            positions,
            cash=50_000.0,
            equity=equity,
            stale=True,
            warnings=[
                "paper_account_price_unavailable",
                "paper_account_reconciliation_unavailable",
            ],
            reconciliation_status="unavailable",
        ),
        generated_at="2026-07-10T16:00:00+00:00",
    )

    assert artifact["status"] == "degraded"
    assert artifact["exposure"]["gross_value"] == pytest.approx(50_000.0)
    assert artifact["exposure"]["valuation_basis"] == "mixed"
    assert artifact["price_quality"]["market_priced_abs_value_pct"] == pytest.approx(
        0.6
    )
    assert artifact["price_quality"]["fallback_symbols"] == ["MSFT"]
    assert set(artifact["reason_codes"]) >= {
        "paper_account_price_unavailable",
        "paper_account_reconciliation_unavailable",
        "paper_account_repository_stale",
        "price_fallback",
        "reconciliation_unavailable",
    }
    assert "valuation estimates" in portfolio_risk.build_report(artifact)


def test_naive_timestamp_is_disclosed_without_inventing_freshness_verdict() -> None:
    position = _position(
        "AAPL",
        10_000.0,
        price_as_of="2026-07-10 11:30:00",
    )
    artifact = portfolio_risk.analyze_snapshot(
        _snapshot([position], cash=90_000.0),
        generated_at="2026-07-10T16:00:00+00:00",
    )

    assert artifact["status"] == "available"
    assert artifact["positions"][0]["price_age_seconds"] is None
    assert artifact["positions"][0]["price_time_status"] == "timezone_missing"
    assert artifact["price_quality"]["price_age_complete"] is False
    assert artifact["policy_evaluation"] == {
        "status": "not_evaluated",
        "thresholds": [],
    }
    assert "price_freshness_age_unavailable" in artifact["limitations"]


def test_non_positive_equity_keeps_dollar_exposure_but_suppresses_ratios() -> None:
    position = _position("AAPL", 10_000.0, equity=0.0)

    artifact = portfolio_risk.analyze_snapshot(
        _snapshot([position], cash=-10_000.0, equity=0.0),
        generated_at="2026-07-10T16:00:00+00:00",
    )

    assert artifact["status"] == "degraded"
    assert artifact["exposure"]["gross_value"] == pytest.approx(10_000.0)
    assert artifact["exposure"]["gross_pct_equity"] is None
    assert artifact["exposure"]["net_pct_equity"] is None
    assert "non_positive_equity" in artifact["reason_codes"]


def test_extreme_finite_values_do_not_create_non_finite_derived_ratios(
    tmp_path,
) -> None:
    positions = [
        _position("LONG", 8e307, equity=1.0),
        _position("SHORT", -8e307, quantity=-1.0, equity=1.0),
    ]
    snapshot = _snapshot(positions, cash=1e-308, equity=1e-308)

    artifact = portfolio_risk.analyze_snapshot(
        snapshot,
        generated_at="2026-07-10T16:00:00+00:00",
    )

    assert artifact["status"] == "degraded"
    assert artifact["exposure"]["gross_value"] == 1.6e308
    assert artifact["exposure"]["gross_pct_equity"] is None
    assert artifact["exposure"]["net_pct_equity"] == pytest.approx(0.0)
    assert all(row["computed_account_weight"] is None for row in artifact["positions"])
    assert "equity_ratio_non_finite" in artifact["reason_codes"]

    log_path = tmp_path / "portfolio_risk.jsonl"
    portfolio_risk.run(
        lambda _account_id: (0, json.dumps(snapshot)),
        lambda: "2026-07-10T16:00:00+00:00",
        log_path,
    )
    persisted = json.loads(log_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "degraded"
    assert persisted["exposure"]["gross_pct_equity"] is None


def test_extreme_finite_account_weight_never_renders_inf_percent() -> None:
    positions = [
        _position("LONG", 1e307, equity=1.0),
        _position("SHORT", -1e307, quantity=-1.0, equity=1.0),
    ]
    artifact = portfolio_risk.analyze_snapshot(
        _snapshot(positions, cash=1.0, equity=1.0),
        generated_at="2026-07-10T16:00:00+00:00",
    )

    report = portfolio_risk.build_report(artifact)

    assert artifact["status"] == "degraded"
    assert "account_weight_percentage_overflow" in artifact["reason_codes"]
    assert "unavailable of account equity" in report
    assert "inf%" not in report.lower()


def test_run_converts_last_resort_non_finite_artifact_to_unavailable(
    monkeypatch,
    tmp_path,
) -> None:
    snapshot = _snapshot()
    monkeypatch.setattr(
        portfolio_risk,
        "analyze_snapshot",
        lambda _snapshot, generated_at: {
            "ts": generated_at,
            "status": "available",
            "bad": float("inf"),
        },
    )
    log_path = tmp_path / "portfolio_risk.jsonl"

    report = portfolio_risk.run(
        lambda _account_id: (0, json.dumps(snapshot)),
        lambda: "2026-07-10T16:00:00+00:00",
        log_path,
    )
    artifact = json.loads(log_path.read_text(encoding="utf-8"))

    assert artifact["status"] == "unavailable"
    assert artifact["error"]["code"] == "portfolio_risk_analysis_failed"
    assert "non-finite" in report


def test_run_rejects_lone_surrogate_without_leaving_an_empty_artifact(
    tmp_path,
) -> None:
    snapshot = _snapshot(warnings=["\ud800"])
    log_path = tmp_path / "portfolio_risk.jsonl"

    report = portfolio_risk.run(
        lambda _account_id: (0, json.dumps(snapshot)),
        lambda: "2026-07-10T16:00:00+00:00",
        log_path,
    )
    rows = log_path.read_text(encoding="utf-8").splitlines()
    artifact = json.loads(rows[0])

    assert len(rows) == 1
    assert artifact["status"] == "unavailable"
    assert artifact["error"]["code"] == "portfolio_risk_snapshot_invalid"
    assert "unicode" in report.lower()


@pytest.mark.parametrize(
    "account_id",
    ["", ".hidden", "../escape", "nested/account", "bad\ud800"],
)
def test_run_rejects_unsafe_requested_account_before_calling_platform(
    tmp_path,
    account_id,
) -> None:
    calls = []
    log_path = tmp_path / "portfolio_risk.jsonl"

    report = portfolio_risk.run(
        lambda value: calls.append(value) or (0, "should-not-run"),
        lambda: "2026-07-10T16:00:00+00:00",
        log_path,
        account_id=account_id,
    )
    artifact = json.loads(log_path.read_text(encoding="utf-8"))

    assert calls == []
    assert artifact["status"] == "unavailable"
    assert artifact["error"]["code"] == "portfolio_risk_snapshot_invalid"
    assert artifact["account"]["account_id"] == "<invalid>"
    assert "invalid paper account id" in report.lower()


def test_deeply_nested_snapshot_becomes_one_unavailable_artifact(tmp_path) -> None:
    nested = "[" * 600 + "0" + "]" * 600
    output = (
        '{"account_id":"default","account_exists":false,'
        '"account":null,"extra":' + nested + "}"
    )
    log_path = tmp_path / "portfolio_risk.jsonl"

    report = portfolio_risk.run(
        lambda _account_id: (0, output),
        lambda: "2026-07-10T16:00:00+00:00",
        log_path,
    )
    rows = log_path.read_text(encoding="utf-8").splitlines()
    artifact = json.loads(rows[0])

    assert len(rows) == 1
    assert artifact["status"] == "unavailable"
    assert artifact["error"]["code"] == "portfolio_risk_snapshot_invalid"
    assert "nesting" in report.lower()


def test_cost_basis_only_and_last_close_are_classified_separately() -> None:
    fallback = portfolio_risk.analyze_snapshot(
        _snapshot(
            [_position("AAPL", 10_000.0, price_kind="avg_cost_fallback")],
            cash=90_000.0,
        ),
        generated_at="2026-07-10T16:00:00+00:00",
    )
    last_close = portfolio_risk.analyze_snapshot(
        _snapshot(
            [_position("AAPL", 10_000.0, price_kind="last_close")],
            cash=90_000.0,
        ),
        generated_at="2026-07-10T16:00:00+00:00",
    )

    assert fallback["status"] == "degraded"
    assert fallback["exposure"]["valuation_basis"] == "cost_basis_only"
    assert fallback["price_quality"]["market_priced_abs_value_pct"] == 0.0
    assert last_close["status"] == "available"
    assert last_close["exposure"]["valuation_basis"] == "market"
    assert last_close["price_quality"]["market_priced_abs_value_pct"] == 1.0


@pytest.mark.parametrize(
    "snapshot, reason",
    [
        (_snapshot(stale=True), "paper_account_repository_stale"),
        (_snapshot(warnings=["repository_custom_warning"]), "repository_custom_warning"),
        (_snapshot(reconciliation_status="different"), "reconciliation_different"),
    ],
)
def test_repository_signals_independently_degrade(snapshot, reason) -> None:
    artifact = portfolio_risk.analyze_snapshot(
        snapshot,
        generated_at="2026-07-10T16:00:00+00:00",
    )

    assert artifact["status"] == "degraded"
    assert artifact["portfolio_state"] == "cash_only"
    assert reason in artifact["reason_codes"]
    assert artifact["account"]["warnings"] == snapshot["account"]["warnings"]
    assert artifact["account"]["reconciliation"] == snapshot["account"][
        "reconciliation"
    ]


def test_pending_orders_are_disclosed_but_excluded_from_current_exposure() -> None:
    pending = {
        "order_id": "order-1",
        "created_at": "2026-07-10T15:00:00+00:00",
        "symbol": "MSFT",
        "side": "buy",
        "quantity": 100.0,
        "limit_price": 500.0,
        "reserved_cash": 50_000.0,
        "reserved_quantity": 0.0,
        "source": "manual",
        "reason": "test",
    }
    artifact = portfolio_risk.analyze_snapshot(
        _snapshot(
            [_position("AAPL", 10_000.0)],
            cash=90_000.0,
            pending_orders=[pending],
        ),
        generated_at="2026-07-10T16:00:00+00:00",
    )

    assert artifact["exposure"]["gross_value"] == pytest.approx(10_000.0)
    assert artifact["account"]["pending_order_count"] == 1
    assert artifact["exposure"]["pending_orders_included"] is False
    assert "pending_orders_excluded_from_current_exposure" in artifact["limitations"]


def test_snapshot_weight_mismatch_is_disclosed_without_changing_gross_share() -> None:
    position = _position("AAPL", 10_000.0)
    position["weight"] = 0.25
    position["last_price"] = 9_999.0

    artifact = portfolio_risk.analyze_snapshot(
        _snapshot([position], cash=90_000.0),
        generated_at="2026-07-10T16:00:00+00:00",
    )

    row = artifact["positions"][0]
    assert artifact["status"] == "degraded"
    assert row["account_weight"] == pytest.approx(0.25)
    assert row["computed_account_weight"] == pytest.approx(0.1)
    assert row["gross_share"] == pytest.approx(1.0)
    assert row["market_value"] == pytest.approx(10_000.0)
    assert set(artifact["reason_codes"]) >= {
        "position_weight_inconsistent",
        "position_market_value_inconsistent",
    }


@pytest.mark.parametrize(
    "quantity, last_price, market_value",
    [
        (100.0, 0.0, 0.0),
        (1.0, -100.0, -100.0),
        (0.0, 100.0, 0.0),
    ],
)
def test_non_positive_price_or_zero_quantity_is_invalid_not_cash_or_short(
    tmp_path,
    quantity,
    last_price,
    market_value,
) -> None:
    position = _position("AAPL", 100.0)
    position.update(
        quantity=quantity,
        avg_cost=100.0,
        last_price=last_price,
        market_value=market_value,
        weight=0.0,
    )
    snapshot = _snapshot([position])
    snapshot["account"]["invested_pct"] = 0.0
    log_path = tmp_path / "portfolio_risk.jsonl"

    report = portfolio_risk.run(
        lambda _account_id: (0, json.dumps(snapshot)),
        lambda: "2026-07-10T16:00:00+00:00",
        log_path,
    )
    artifact = json.loads(log_path.read_text(encoding="utf-8"))

    assert artifact["status"] == "unavailable"
    assert artifact["error"]["code"] == "portfolio_risk_snapshot_invalid"
    assert artifact["portfolio_state"] == "unknown"
    assert "cash-only" not in report


def test_account_equity_identity_drift_is_invalid_not_a_false_weight_claim(
    tmp_path,
) -> None:
    position = _position("AAPL", 100.0, equity=1_000_000.0)
    snapshot = _snapshot([position], cash=0.0, equity=1_000_000.0)
    log_path = tmp_path / "portfolio_risk.jsonl"

    report = portfolio_risk.run(
        lambda _account_id: (0, json.dumps(snapshot)),
        lambda: "2026-07-10T16:00:00+00:00",
        log_path,
    )
    artifact = json.loads(log_path.read_text(encoding="utf-8"))

    assert artifact["status"] == "unavailable"
    assert artifact["error"]["code"] == "portfolio_risk_snapshot_invalid"
    assert artifact["exposure"] is None
    assert "0.0100%" not in report


def test_report_uses_account_currency_without_fx_assumption() -> None:
    artifact = portfolio_risk.analyze_snapshot(
        _snapshot(
            [_position("0700.HK", 20_000.0)],
            cash=80_000.0,
            base_currency="HKD",
        ),
        generated_at="2026-07-10T16:00:00+00:00",
    )

    report = portfolio_risk.build_report(artifact)
    assert "gross=HKD 20,000.00" in report
    assert "$" not in report
    assert "fx" not in artifact["exposure"]


def test_run_writes_one_artifact_and_renders_stdout_from_it(tmp_path) -> None:
    calls = []
    payload = _snapshot([_position("AAPL", 10_000.0)], cash=90_000.0)
    log_path = tmp_path / "portfolio_risk.jsonl"
    log_path.write_text('{"sentinel":true}\n', encoding="utf-8")

    def run_snapshot(account_id):
        calls.append(account_id)
        return 0, json.dumps(payload, indent=2)

    report = portfolio_risk.run(
        run_snapshot,
        lambda: "2026-07-10T16:00:00+00:00",
        log_path,
        account_id="default",
    )

    assert calls == ["default"]
    rows = log_path.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 2
    assert json.loads(rows[0]) == {"sentinel": True}
    artifact = json.loads(rows[1])
    assert artifact["job"] == "portfolio-risk"
    assert artifact["status"] == "available"
    assert f"USD {artifact['exposure']['gross_value']:,.2f}" in report


def test_run_propagates_platform_error_and_invalid_snapshot_never_becomes_missing(
    tmp_path,
) -> None:
    platform_error = json.dumps(
        {
            "error": {
                "code": "paper_account_database_unavailable",
                "message": "database unavailable",
            }
        }
    )
    error_log = tmp_path / "error.jsonl"
    error_report = portfolio_risk.run(
        lambda _account_id: (1, platform_error),
        lambda: "2026-07-10T16:00:00+00:00",
        error_log,
    )
    error_artifact = json.loads(error_log.read_text(encoding="utf-8"))

    assert error_artifact["status"] == "unavailable"
    assert error_artifact["error"]["code"] == "paper_account_database_unavailable"
    assert "database unavailable" in error_report

    invalid_log = tmp_path / "invalid.jsonl"
    invalid_report = portfolio_risk.run(
        lambda _account_id: (0, "not-json"),
        lambda: "2026-07-10T16:00:00+00:00",
        invalid_log,
    )
    invalid_artifact = json.loads(invalid_log.read_text(encoding="utf-8"))

    assert invalid_artifact["status"] == "unavailable"
    assert invalid_artifact["error"]["code"] == "portfolio_risk_snapshot_invalid"
    assert invalid_artifact["account"]["account_exists"] is None
    assert "does not exist" not in invalid_report


def test_run_turns_snapshot_adapter_exception_into_one_unavailable_artifact(
    tmp_path,
) -> None:
    log_path = tmp_path / "portfolio_risk.jsonl"

    def fail_snapshot(_account_id):
        raise TimeoutError("snapshot timed out")

    report = portfolio_risk.run(
        fail_snapshot,
        lambda: "2026-07-10T16:00:00+00:00",
        log_path,
    )
    rows = log_path.read_text(encoding="utf-8").splitlines()
    artifact = json.loads(rows[0])

    assert len(rows) == 1
    assert artifact["status"] == "unavailable"
    assert artifact["error"]["code"] == "paper_account_snapshot_command_failed"
    assert artifact["exposure"] is None
    assert artifact["concentration"] is None
    assert "snapshot timed out" in report


def test_main_uses_snapshot_adapter_and_default_artifact(monkeypatch, capsys, tmp_path) -> None:
    seen = []
    payload = _snapshot(account_exists=False)
    monkeypatch.setattr(
        portfolio_risk.quant_cli,
        "run_paper_account_snapshot",
        lambda account_id: seen.append(account_id) or (0, json.dumps(payload)),
    )
    monkeypatch.setattr(
        portfolio_risk.runlog,
        "utc_now_iso",
        lambda: "2026-07-10T16:00:00Z",
    )
    log_path = tmp_path / "portfolio_risk.jsonl"

    result = portfolio_risk.main(["--account", "default", "--log", str(log_path)])

    assert result == 0
    assert seen == ["default"]
    assert "NOT APPLICABLE" in capsys.readouterr().out
    assert json.loads(log_path.read_text(encoding="utf-8"))["status"] == (
        "not_applicable"
    )

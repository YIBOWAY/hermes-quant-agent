from __future__ import annotations

import argparse
import copy
import json
import math
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from hqa import config, historical_risk, quant_cli, runlog


SCHEMA_VERSION = "1.0"
_ERROR_CODE = "portfolio_risk_snapshot_invalid"
_MARKET_PRICE_KINDS = {"futu_snapshot", "last_close"}
_FALLBACK_PRICE_KIND = "avg_cost_fallback"
_ACCOUNT_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


class PortfolioRiskSnapshotError(ValueError):
    """The platform output is not the unified paper-account snapshot contract."""

    def __init__(self, message: str, *, code: str = _ERROR_CODE) -> None:
        super().__init__(message)
        self.code = code


def _invalid(message: str) -> PortfolioRiskSnapshotError:
    return PortfolioRiskSnapshotError(message)


def _reject_constant(value: str) -> None:
    raise _invalid(f"non-finite JSON number is not allowed: {value}")


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _invalid(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _require_keys(value: dict[str, Any], keys: tuple[str, ...], path: str) -> None:
    missing = [key for key in keys if key not in value]
    if missing:
        raise _invalid(f"{path} missing required fields: {', '.join(missing)}")


def _require_string(value: Any, path: str, *, nullable: bool = False) -> Optional[str]:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"{path} must be a non-empty string")
    return value


def _require_number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _invalid(f"{path} must be a finite number")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise _invalid(f"{path} must be a finite number") from exc
    if not math.isfinite(number):
        raise _invalid(f"{path} must be a finite number")
    return number


def _reject_non_finite_numbers(value: Any, path: str = "snapshot") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise _invalid(f"{path} contains a non-finite number")
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_non_finite_numbers(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_non_finite_numbers(item, f"{path}[{index}]")


def _reject_invalid_unicode(value: Any, path: str = "snapshot") -> None:
    if isinstance(value, str):
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise _invalid(f"{path} contains invalid unicode") from exc
    elif isinstance(value, dict):
        for key, item in value.items():
            _reject_invalid_unicode(key, f"{path} object key")
            _reject_invalid_unicode(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_invalid_unicode(item, f"{path}[{index}]")


def _validate_reconciliation(value: Any, account_id: str) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise _invalid("snapshot.account.reconciliation must be an object or null")
    _require_keys(
        value,
        (
            "status",
            "account_id",
            "source",
            "target",
            "checked_at",
            "expected_summary",
            "actual_summary",
            "differences",
        ),
        "snapshot.account.reconciliation",
    )
    _require_string(value["status"], "snapshot.account.reconciliation.status")
    reconciliation_account = _require_string(
        value["account_id"], "snapshot.account.reconciliation.account_id"
    )
    if reconciliation_account != account_id:
        raise _invalid("snapshot reconciliation account_id does not match snapshot account_id")
    _require_string(value["source"], "snapshot.account.reconciliation.source")
    _require_string(
        value["target"], "snapshot.account.reconciliation.target", nullable=True
    )
    _require_string(value["checked_at"], "snapshot.account.reconciliation.checked_at")
    if not isinstance(value["expected_summary"], dict):
        raise _invalid("snapshot.account.reconciliation.expected_summary must be an object")
    if not isinstance(value["actual_summary"], dict):
        raise _invalid("snapshot.account.reconciliation.actual_summary must be an object")
    if not isinstance(value["differences"], list):
        raise _invalid("snapshot.account.reconciliation.differences must be an array")


def _validate_snapshot(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise _invalid("snapshot must be a JSON object")
    _reject_non_finite_numbers(payload)
    _reject_invalid_unicode(payload)
    _require_keys(payload, ("account_id", "account_exists", "account"), "snapshot")

    account_id = _require_string(payload["account_id"], "snapshot.account_id")
    assert account_id is not None
    if account_id != account_id.strip():
        raise _invalid("snapshot.account_id must not contain surrounding whitespace")
    if not isinstance(payload["account_exists"], bool):
        raise _invalid("snapshot.account_exists must be a boolean")

    if not payload["account_exists"]:
        if payload["account"] is not None:
            raise _invalid("snapshot.account must be null when account_exists is false")
        return copy.deepcopy(payload)

    account = payload["account"]
    if not isinstance(account, dict):
        raise _invalid("snapshot.account must be an object when account_exists is true")
    _require_keys(
        account,
        (
            "account_id",
            "base_currency",
            "initial_cash",
            "cash",
            "reserved_cash",
            "available_cash",
            "equity",
            "realized_pnl",
            "unrealized_pnl",
            "pnl_abs",
            "pnl_pct",
            "invested_pct",
            "kill_switch",
            "price_source",
            "positions",
            "pending_orders",
            "created_at",
            "updated_at",
            "storage_mode",
            "stale",
            "warnings",
            "reconciliation",
        ),
        "snapshot.account",
    )

    inner_account_id = _require_string(account["account_id"], "snapshot.account.account_id")
    if inner_account_id != account_id:
        raise _invalid("snapshot account_id does not match account.account_id")
    _require_string(account["base_currency"], "snapshot.account.base_currency")
    for field in (
        "initial_cash",
        "cash",
        "reserved_cash",
        "available_cash",
        "equity",
        "realized_pnl",
        "unrealized_pnl",
        "pnl_abs",
        "pnl_pct",
        "invested_pct",
    ):
        _require_number(account[field], f"snapshot.account.{field}")
    if not isinstance(account["kill_switch"], bool):
        raise _invalid("snapshot.account.kill_switch must be a boolean")

    price_source = account["price_source"]
    if not isinstance(price_source, dict):
        raise _invalid("snapshot.account.price_source must be an object")
    _require_keys(price_source, ("kind", "as_of"), "snapshot.account.price_source")
    _require_string(price_source["kind"], "snapshot.account.price_source.kind")
    _require_string(
        price_source["as_of"], "snapshot.account.price_source.as_of", nullable=True
    )

    positions = account["positions"]
    if not isinstance(positions, list):
        raise _invalid("snapshot.account.positions must be an array")
    normalized_symbols: set[str] = set()
    normalized_positions: list[dict[str, Any]] = []
    for index, raw_position in enumerate(positions):
        path = f"snapshot.account.positions[{index}]"
        if not isinstance(raw_position, dict):
            raise _invalid(f"{path} must be an object")
        _require_keys(
            raw_position,
            (
                "symbol",
                "quantity",
                "avg_cost",
                "last_price",
                "market_value",
                "weight",
                "unrealized_pnl",
                "source_breakdown",
                "price_kind",
                "price_as_of",
            ),
            path,
        )
        raw_symbol = _require_string(raw_position["symbol"], f"{path}.symbol")
        assert raw_symbol is not None
        symbol = raw_symbol.strip().upper()
        if symbol in normalized_symbols:
            raise _invalid(f"duplicate normalized position symbol: {symbol}")
        normalized_symbols.add(symbol)
        for field in (
            "quantity",
            "avg_cost",
            "last_price",
            "market_value",
            "weight",
            "unrealized_pnl",
        ):
            _require_number(raw_position[field], f"{path}.{field}")
        quantity = float(raw_position["quantity"])
        avg_cost = float(raw_position["avg_cost"])
        last_price = float(raw_position["last_price"])
        market_value = float(raw_position["market_value"])
        if quantity == 0:
            raise _invalid(f"{path}.quantity must be non-zero for an open position")
        if avg_cost <= 0:
            raise _invalid(f"{path}.avg_cost must be greater than zero")
        if last_price <= 0:
            raise _invalid(f"{path}.last_price must be greater than zero")
        if market_value == 0:
            raise _invalid(f"{path}.market_value must be non-zero for an open position")
        if (quantity > 0) != (market_value > 0):
            raise _invalid(f"{path}.market_value direction must match quantity")
        if not math.isfinite(quantity * last_price):
            raise _invalid(f"{path} quantity × last_price must remain finite")
        if not isinstance(raw_position["source_breakdown"], dict):
            raise _invalid(f"{path}.source_breakdown must be an object")
        for source, quantity in raw_position["source_breakdown"].items():
            _require_string(source, f"{path}.source_breakdown key")
            _require_number(quantity, f"{path}.source_breakdown.{source}")
        _require_string(raw_position["price_kind"], f"{path}.price_kind")
        _require_string(raw_position["price_as_of"], f"{path}.price_as_of", nullable=True)
        position = copy.deepcopy(raw_position)
        position["symbol"] = symbol
        normalized_positions.append(position)

    try:
        expected_equity = math.fsum(
            [
                float(account["cash"]),
                *(float(position["market_value"]) for position in normalized_positions),
            ]
        )
    except OverflowError as exc:
        raise _invalid("snapshot.account equity identity overflowed") from exc
    if not math.isclose(
        float(account["equity"]),
        expected_equity,
        rel_tol=1e-9,
        abs_tol=1e-6,
    ):
        raise _invalid("snapshot.account.equity must equal cash plus position market value")

    pending_orders = account["pending_orders"]
    if not isinstance(pending_orders, list) or not all(
        isinstance(order, dict) for order in pending_orders
    ):
        raise _invalid("snapshot.account.pending_orders must be an array of objects")
    _require_string(account["created_at"], "snapshot.account.created_at")
    _require_string(account["updated_at"], "snapshot.account.updated_at")
    _require_string(
        account["storage_mode"], "snapshot.account.storage_mode", nullable=True
    )
    if not isinstance(account["stale"], bool):
        raise _invalid("snapshot.account.stale must be a boolean")
    if not isinstance(account["warnings"], list) or not all(
        isinstance(warning, str) and warning for warning in account["warnings"]
    ):
        raise _invalid("snapshot.account.warnings must be an array of non-empty strings")
    _validate_reconciliation(account["reconciliation"], account_id)

    validated = copy.deepcopy(payload)
    validated["account"]["positions"] = normalized_positions
    return validated


def parse_snapshot(output: str) -> dict[str, Any]:
    """Parse exactly one complete unified snapshot; trailing provider noise is invalid."""
    if not isinstance(output, str) or not output.strip():
        raise _invalid("snapshot output is empty")
    try:
        payload = json.loads(
            output,
            parse_constant=_reject_constant,
            object_pairs_hook=_object_without_duplicate_keys,
        )
        return _validate_snapshot(payload)
    except PortfolioRiskSnapshotError:
        raise
    except RecursionError as exc:
        raise _invalid("snapshot nesting exceeds supported depth") from exc
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise _invalid(f"snapshot output is not one complete JSON document: {exc}") from exc


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _finite_ratio(numerator: float, denominator: float) -> Optional[float]:
    if denominator == 0:
        return None
    try:
        ratio = numerator / denominator
    except (OverflowError, ZeroDivisionError):
        return None
    return ratio if math.isfinite(ratio) else None


def _finite_percentage(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    percentage = value * 100.0
    return percentage if math.isfinite(percentage) else None


def _parse_time(value: Any) -> tuple[str, Optional[datetime]]:
    if value is None:
        return "missing", None
    if not isinstance(value, str) or not value.strip():
        return "invalid", None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return "invalid", None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return "timezone_missing", parsed
    return "available", parsed


def _time_fact(price_as_of: Any, generated_at: str) -> tuple[str, Optional[float]]:
    price_status, price_time = _parse_time(price_as_of)
    if price_status != "available" or price_time is None:
        return price_status, None
    generated_status, generated_time = _parse_time(generated_at)
    if generated_status != "available" or generated_time is None:
        return "generated_time_unavailable", None
    return "available", (generated_time - price_time).total_seconds()


def _account_summary(
    account_exists: Optional[bool],
    account_id: str,
    account: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    if account is None:
        return {
            "account_exists": account_exists,
            "account_id": account_id,
            "base_currency": None,
            "cash": None,
            "reserved_cash": None,
            "available_cash": None,
            "equity": None,
            "kill_switch": None,
            "storage_mode": None,
            "repository_stale": None,
            "warnings": [],
            "reconciliation": None,
            "pending_order_count": None,
        }
    return {
        "account_exists": account_exists,
        "account_id": account_id,
        "base_currency": account["base_currency"],
        "cash": account["cash"],
        "reserved_cash": account["reserved_cash"],
        "available_cash": account["available_cash"],
        "equity": account["equity"],
        "kill_switch": account["kill_switch"],
        "storage_mode": account["storage_mode"],
        "repository_stale": account["stale"],
        "warnings": copy.deepcopy(account["warnings"]),
        "reconciliation": copy.deepcopy(account["reconciliation"]),
        "pending_order_count": len(account["pending_orders"]),
        "updated_at": account["updated_at"],
        "price_source": copy.deepcopy(account["price_source"]),
    }


def analyze_snapshot(snapshot: dict[str, Any], *, generated_at: str) -> dict[str, Any]:
    """Derive current exposure/concentration facts from one validated snapshot."""
    try:
        validated = _validate_snapshot(copy.deepcopy(snapshot))
    except RecursionError as exc:
        raise _invalid("snapshot nesting exceeds supported depth") from exc
    account_id = validated["account_id"]
    policy = {"status": "not_evaluated", "thresholds": []}
    if not validated["account_exists"]:
        return {
            "schema_version": SCHEMA_VERSION,
            "ts": generated_at,
            "job": "portfolio-risk",
            "status": "not_applicable",
            "portfolio_state": "account_missing",
            "reason_codes": ["paper_account_not_found"],
            "account": _account_summary(False, account_id),
            "exposure": None,
            "concentration": None,
            "price_quality": None,
            "positions": [],
            "policy_evaluation": policy,
            "limitations": ["current_snapshot_only"],
            "error": None,
        }

    account = validated["account"]
    assert isinstance(account, dict)
    equity = float(account["equity"])
    input_positions = account["positions"]
    market_values = [float(position["market_value"]) for position in input_positions]
    long_value = math.fsum(value for value in market_values if value > 0)
    short_value = math.fsum(-value for value in market_values if value < 0)
    gross_value = long_value + short_value
    net_value = math.fsum(market_values)

    reasons: list[str] = []
    limitations = [
        "current_snapshot_only",
        "historical_risk_metrics_not_computed",
        "no_risk_policy_thresholds_configured",
        "account_base_currency_only_no_fx_conversion",
    ]
    for warning in account["warnings"]:
        _append_unique(reasons, warning)
    if account["stale"]:
        _append_unique(reasons, "paper_account_repository_stale")

    reconciliation = account["reconciliation"]
    reconciliation_status = reconciliation.get("status") if reconciliation else None
    if reconciliation_status not in {"in_sync", "not_applicable"}:
        if reconciliation_status:
            _append_unique(reasons, f"reconciliation_{reconciliation_status}")
        else:
            _append_unique(reasons, "reconciliation_not_reported")

    ratios_available = equity > 0
    if not ratios_available:
        _append_unique(reasons, "non_positive_equity")
    gross_pct_equity = _finite_ratio(gross_value, equity) if ratios_available else None
    net_pct_equity = _finite_ratio(net_value, equity) if ratios_available else None
    if ratios_available and (
        gross_pct_equity is None or net_pct_equity is None
    ):
        _append_unique(reasons, "equity_ratio_non_finite")
    exposure = {
        "currency": account["base_currency"],
        "long_value": long_value,
        "short_value": short_value,
        "gross_value": gross_value,
        "net_value": net_value,
        "gross_pct_equity": gross_pct_equity,
        "net_pct_equity": net_pct_equity,
        "pending_orders_included": False,
    }

    position_rows: list[dict[str, Any]] = []
    fallback_symbols: list[str] = []
    unclassified_symbols: list[str] = []
    market_priced_abs_value = 0.0
    fallback_abs_value = 0.0
    price_ages: list[float] = []
    all_price_ages_available = bool(input_positions)
    for position in input_positions:
        symbol = position["symbol"]
        market_value = float(position["market_value"])
        abs_value = abs(market_value)
        price_kind = position["price_kind"]
        if price_kind == _FALLBACK_PRICE_KIND:
            valuation_kind = "cost_basis_fallback"
            fallback_abs_value += abs_value
            fallback_symbols.append(symbol)
            _append_unique(reasons, "price_fallback")
        elif price_kind in _MARKET_PRICE_KINDS:
            valuation_kind = "market"
            market_priced_abs_value += abs_value
        else:
            valuation_kind = "unclassified"
            unclassified_symbols.append(symbol)
            _append_unique(reasons, "price_provenance_unknown")

        time_status, price_age_seconds = _time_fact(
            position["price_as_of"], generated_at
        )
        if price_age_seconds is None:
            all_price_ages_available = False
            _append_unique(limitations, "price_freshness_age_unavailable")
            if time_status in {"missing", "invalid"}:
                _append_unique(reasons, f"price_timestamp_{time_status}")
        else:
            price_ages.append(price_age_seconds)

        computed_weight = (
            _finite_ratio(market_value, equity) if ratios_available else None
        )
        if ratios_available and computed_weight is None:
            _append_unique(reasons, "equity_ratio_non_finite")
        computed_weight_pct = _finite_percentage(computed_weight)
        if computed_weight is not None and computed_weight_pct is None:
            _append_unique(reasons, "account_weight_percentage_overflow")
        snapshot_weight = float(position["weight"])
        weight_consistent = (
            math.isclose(snapshot_weight, computed_weight, rel_tol=1e-9, abs_tol=1e-9)
            if computed_weight is not None
            else None
        )
        if weight_consistent is False:
            _append_unique(reasons, "position_weight_inconsistent")

        expected_market_value = float(position["quantity"]) * float(
            position["last_price"]
        )
        market_value_consistent = math.isclose(
            market_value,
            expected_market_value,
            rel_tol=1e-9,
            abs_tol=1e-9,
        )
        if not market_value_consistent:
            _append_unique(reasons, "position_market_value_inconsistent")

        position_rows.append(
            {
                "symbol": symbol,
                "side": "long" if market_value > 0 else ("short" if market_value < 0 else "flat"),
                "quantity": position["quantity"],
                "avg_cost": position["avg_cost"],
                "last_price": position["last_price"],
                "market_value": market_value,
                "market_value_source": "snapshot",
                "market_value_consistent": market_value_consistent,
                "account_weight": snapshot_weight,
                "computed_account_weight": computed_weight,
                "computed_account_weight_pct": computed_weight_pct,
                "account_weight_consistent": weight_consistent,
                "gross_share": (
                    _finite_ratio(abs_value, gross_value) if gross_value > 0 else None
                ),
                "price_kind": price_kind,
                "valuation_kind": valuation_kind,
                "price_as_of": position["price_as_of"],
                "price_time_status": time_status,
                "price_age_seconds": price_age_seconds,
            }
        )

    position_rows.sort(key=lambda row: (-abs(row["market_value"]), row["symbol"]))
    fallback_symbols.sort()
    unclassified_symbols.sort()

    if gross_value > 0:
        gross_shares = [
            ratio
            for value in market_values
            if (ratio := _finite_ratio(abs(value), gross_value)) is not None
        ]
        if len(gross_shares) != len(market_values):
            raise ArithmeticError("gross-share derivation produced a non-finite ratio")
        ordered_shares = sorted(gross_shares, reverse=True)
        largest = position_rows[0]["symbol"] if position_rows else None
        concentration = {
            "status": "available",
            "basis": "absolute_market_value",
            "top1_gross_pct": ordered_shares[0] if ordered_shares else None,
            "top3_gross_pct": math.fsum(ordered_shares[:3]),
            "hhi_gross": math.fsum(share * share for share in gross_shares),
            "largest_symbol": largest,
        }
    else:
        concentration = {
            "status": "not_applicable",
            "basis": "absolute_market_value",
            "top1_gross_pct": None,
            "top3_gross_pct": None,
            "hhi_gross": None,
            "largest_symbol": None,
        }

    if gross_value == 0:
        valuation_basis = "not_applicable"
    elif unclassified_symbols:
        valuation_basis = "partially_classified"
    elif fallback_abs_value == 0:
        valuation_basis = "market"
    elif math.isclose(fallback_abs_value, gross_value, rel_tol=1e-12, abs_tol=1e-12):
        valuation_basis = "cost_basis_only"
    else:
        valuation_basis = "mixed"
    exposure["valuation_basis"] = valuation_basis

    if account["pending_orders"]:
        _append_unique(limitations, "pending_orders_excluded_from_current_exposure")
    price_quality = {
        "valuation_basis": valuation_basis,
        "market_priced_abs_value": market_priced_abs_value,
        "market_priced_abs_value_pct": (
            _finite_ratio(market_priced_abs_value, gross_value)
            if gross_value > 0
            else None
        ),
        "fallback_abs_value": fallback_abs_value,
        "fallback_symbols": fallback_symbols,
        "unclassified_symbols": unclassified_symbols,
        "price_age_complete": all_price_ages_available,
        "oldest_price_age_seconds": max(price_ages) if price_ages else None,
        "newest_price_age_seconds": min(price_ages) if price_ages else None,
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "ts": generated_at,
        "job": "portfolio-risk",
        "status": "degraded" if reasons else "available",
        "portfolio_state": "cash_only" if gross_value == 0 else "invested",
        "reason_codes": reasons,
        "account": _account_summary(True, account_id, account),
        "exposure": exposure,
        "concentration": concentration,
        "price_quality": price_quality,
        "positions": position_rows,
        "policy_evaluation": policy,
        "limitations": limitations,
        "error": None,
    }


def _unavailable_artifact(
    *,
    generated_at: str,
    account_id: str,
    code: str,
    message: str,
    exit_code: Optional[int] = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ts": generated_at,
        "job": "portfolio-risk",
        "status": "unavailable",
        "portfolio_state": "unknown",
        "reason_codes": [code],
        "account": _account_summary(None, account_id),
        "exposure": None,
        "concentration": None,
        "price_quality": None,
        "positions": [],
        "policy_evaluation": {"status": "not_evaluated", "thresholds": []},
        "limitations": ["current_snapshot_unavailable"],
        "error": {"code": code, "message": message, "exit_code": exit_code},
    }


def _platform_error(output: str, exit_code: int) -> tuple[str, str]:
    try:
        payload = json.loads(
            output,
            parse_constant=_reject_constant,
            object_pairs_hook=_object_without_duplicate_keys,
        )
    except (
        PortfolioRiskSnapshotError,
        RecursionError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ):
        payload = None
    if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
        error = payload["error"]
        code = error.get("code")
        message = error.get("message")
        if isinstance(code, str) and code and isinstance(message, str) and message:
            return code, message
    detail = output.strip()
    if detail:
        detail = detail[:500]
        return (
            "paper_account_snapshot_command_failed",
            f"paper account snapshot command exited {exit_code}: {detail}",
        )
    return (
        "paper_account_snapshot_command_failed",
        f"paper account snapshot command exited {exit_code} without JSON error output",
    )


def _history_unavailable(
    *,
    benchmark: str,
    start: Optional[str],
    end: Optional[str],
    status: str,
    reason: str,
    minimum_aligned_returns: int,
    error: Optional[dict[str, Any]] = None,
    provider: str = "futu",
) -> dict[str, Any]:
    return {
        "history_source": {
            "status": status,
            "provider": provider,
            "source": None,
            "adjustment": "qfq",
            "interval": "1d",
            "requested_start": start,
            "requested_end": end,
            "fetched_at": None,
            "history_end_policy": "previous_utc_calendar_date",
            "payload_sha256": None,
            "series": [],
            "error": error,
        },
        "historical_risk": {
            "status": status,
            "benchmark": benchmark,
            "return_kind": "simple_close_to_close",
            "alignment": "global_date_inner_join_before_returns",
            "minimum_aligned_returns": minimum_aligned_returns,
            "aligned_price_count": 0,
            "aligned_return_count": 0,
            "first_return_date": None,
            "last_return_date": None,
            "correlations_status": "not_applicable",
            "correlations": [],
            "betas": [],
            "limitations": [
                "historical_relationship_not_forecast",
                "no_risk_policy_thresholds_configured",
            ],
            "reason": reason,
        },
    }


def _attach_history(
    artifact: dict[str, Any],
    *,
    run_history: Callable[[list[str], str, str], tuple[int, str]],
    generated_at: str,
    benchmark: str,
    minimum_aligned_returns: int,
    run_history_fallback: Optional[
        Callable[[list[str], str, str], tuple[int, str]]
    ] = None,
    history_fallback_provider: Optional[str] = None,
    history_retry_sleep: Optional[Callable[[float], None]] = None,
) -> dict[str, Any]:
    artifact["schema_version"] = "2.0"
    limitations = artifact.get("limitations")
    if isinstance(limitations, list):
        artifact["limitations"] = [
            limitation
            for limitation in limitations
            if limitation
            not in {"current_snapshot_only", "historical_risk_metrics_not_computed"}
        ]
        if artifact.get("exposure") is not None:
            _append_unique(
                artifact["limitations"], "current_exposure_uses_single_snapshot"
            )
    try:
        start, end = historical_risk.history_window(generated_at)
    except (TypeError, ValueError) as exc:
        history = _history_unavailable(
            benchmark=benchmark,
            start=None,
            end=None,
            status="unavailable",
            reason="history_window_invalid",
            minimum_aligned_returns=minimum_aligned_returns,
            error={
                "code": "historical_prices_invalid_request",
                "provider": "futu",
                "provider_code": None,
                "message": str(exc),
            },
        )
        artifact.update(history)
        if artifact["status"] in {"available", "degraded"}:
            artifact["status"] = "degraded"
            _append_unique(artifact["reason_codes"], "historical_prices_invalid_request")
        return artifact

    if artifact["status"] == "unavailable":
        artifact.update(
            _history_unavailable(
                benchmark=benchmark,
                start=start,
                end=end,
                status="not_applicable",
                reason="current_snapshot_unavailable",
                minimum_aligned_returns=minimum_aligned_returns,
            )
        )
        return artifact
    if artifact["status"] == "not_applicable":
        artifact.update(
            _history_unavailable(
                benchmark=benchmark,
                start=start,
                end=end,
                status="not_applicable",
                reason="paper_account_not_found",
                minimum_aligned_returns=minimum_aligned_returns,
            )
        )
        return artifact
    if artifact["portfolio_state"] == "cash_only":
        artifact.update(
            _history_unavailable(
                benchmark=benchmark,
                start=start,
                end=end,
                status="not_applicable",
                reason="cash_only",
                minimum_aligned_returns=minimum_aligned_returns,
            )
        )
        return artifact

    if (
        isinstance(minimum_aligned_returns, bool)
        or not isinstance(minimum_aligned_returns, int)
        or minimum_aligned_returns < 2
    ):
        reason = "historical_risk_invalid_configuration"
        artifact.update(
            _history_unavailable(
                benchmark=benchmark,
                start=start,
                end=end,
                status="unavailable",
                reason=reason,
                minimum_aligned_returns=minimum_aligned_returns,
                error={
                    "code": reason,
                    "provider": "futu",
                    "provider_code": None,
                    "message": "minimum_aligned_returns must be an integer >= 2",
                },
            )
        )
        artifact["status"] = "degraded"
        _append_unique(artifact["reason_codes"], reason)
        return artifact

    symbols = [row["symbol"] for row in artifact["positions"]]
    requested_symbols = list(symbols)
    normalized_benchmark = benchmark.strip().upper()
    if normalized_benchmark not in requested_symbols:
        requested_symbols.append(normalized_benchmark)

    def _attempt(
        runner: Callable[[list[str], str, str], tuple[int, str]],
        provider_name: str,
    ) -> tuple[int, str, Optional[dict[str, Any]]]:
        try:
            code, out = runner(requested_symbols, start, end)
        except Exception as exc:
            return (
                1,
                "",
                {
                    "code": "historical_prices_command_failed",
                    "provider": provider_name,
                    "provider_code": type(exc).__name__,
                    "message": f"historical price command failed: {exc}",
                },
            )
        return code, out, None

    def _attempt_error(
        out: str,
        exc_error: Optional[dict[str, Any]],
        provider_name: str,
    ) -> dict[str, Any]:
        if exc_error is not None:
            return exc_error
        try:
            parsed = historical_risk.parse_price_error(out)
        except historical_risk.HistoricalPriceContractError as exc:
            return {
                "code": exc.code,
                "provider": provider_name,
                "provider_code": None,
                "message": str(exc),
            }
        if parsed.get("provider") is None:
            parsed["provider"] = provider_name
        return parsed

    # Primary provider with one retry for transient network failures; the
    # optional fallback provider is explicit, recorded, and never silent.
    provider_used = "futu"
    exit_code, output, attempt_error = _attempt(run_history, provider_used)
    if exit_code != 0:
        if history_retry_sleep is not None:
            history_retry_sleep(2.0)
        exit_code, output, attempt_error = _attempt(run_history, provider_used)

    primary_error: Optional[dict[str, Any]] = None
    fallback_error: Optional[dict[str, Any]] = None
    if exit_code != 0:
        primary_error = _attempt_error(output, attempt_error, provider_used)
        if run_history_fallback is not None and history_fallback_provider:
            provider_used = history_fallback_provider
            exit_code, output, attempt_error = _attempt(
                run_history_fallback, provider_used
            )
            if exit_code != 0:
                fallback_error = _attempt_error(
                    output, attempt_error, provider_used
                )

    if exit_code != 0:
        error = primary_error
        assert error is not None
        artifact.update(
            _history_unavailable(
                benchmark=normalized_benchmark,
                start=start,
                end=end,
                status="unavailable",
                reason=error["code"],
                minimum_aligned_returns=minimum_aligned_returns,
                error=error,
            )
        )
        if fallback_error is not None:
            artifact["history_source"]["fallback_error"] = fallback_error
            _append_unique(artifact["reason_codes"], "history_fallback_failed")
        artifact["status"] = "degraded"
        _append_unique(artifact["reason_codes"], error["code"])
        return artifact

    try:
        payload = historical_risk.parse_price_snapshot(
            output,
            expected_symbols=requested_symbols,
            expected_start=start,
            expected_end=end,
            expected_provider=provider_used,
        )
        result = historical_risk.analyze_price_history(
            payload,
            position_symbols=symbols,
            benchmark=normalized_benchmark,
            minimum_aligned_returns=minimum_aligned_returns,
            history_end_policy="previous_utc_calendar_date",
            provider=provider_used,
        )
    except historical_risk.HistoricalPriceContractError as exc:
        error = {
            "code": exc.code,
            "provider": provider_used,
            "provider_code": None,
            "message": str(exc),
        }
        artifact.update(
            _history_unavailable(
                benchmark=normalized_benchmark,
                start=start,
                end=end,
                status="unavailable",
                reason=exc.code,
                minimum_aligned_returns=minimum_aligned_returns,
                error=error,
                provider=provider_used,
            )
        )
        artifact["status"] = "degraded"
        _append_unique(artifact["reason_codes"], exc.code)
        return artifact

    artifact.update(result)
    if provider_used != "futu" and primary_error is not None:
        # Loud, receipt-backed substitution: the artifact keeps the primary
        # failure and names the provider that actually served the history.
        artifact["history_source"]["fallback"] = {
            "primary_provider": "futu",
            "primary_error": primary_error,
        }
        _append_unique(artifact["reason_codes"], "history_provider_fallback_used")
        _append_unique(
            artifact["limitations"],
            f"history_from_fallback_provider_{provider_used}",
        )
    history_status = artifact["historical_risk"]["status"]
    if history_status != "available":
        artifact["status"] = "degraded"
        _append_unique(artifact["reason_codes"], f"historical_risk_{history_status}")
        reason = artifact["historical_risk"].get("reason")
        if reason:
            _append_unique(artifact["reason_codes"], reason)
    return artifact


def build_report(artifact: dict[str, Any]) -> str:
    ts = artifact["ts"]
    status = artifact["status"]
    account = artifact["account"]
    account_id = account["account_id"]
    if status == "unavailable":
        error = artifact.get("error") or {}
        return (
            f"[HQA] Portfolio risk {ts}: UNAVAILABLE\n"
            f"  account={account_id} error={error.get('code', 'unknown')}: "
            f"{error.get('message', 'snapshot unavailable')}\n"
            "  No exposure or concentration conclusion was produced."
        )
    if status == "not_applicable":
        return (
            f"[HQA] Portfolio risk {ts}: NOT APPLICABLE\n"
            f"  Paper account {account_id} does not exist; this is not a cash-only account."
        )

    exposure = artifact["exposure"]
    currency = exposure["currency"]
    state = artifact["portfolio_state"]
    if state == "cash_only":
        qualification = "DEGRADED" if status == "degraded" else "AVAILABLE"
        pending_count = account["pending_order_count"] or 0
        return (
            f"[HQA] Portfolio risk {ts}: {qualification}\n"
            f"  account={account_id} is cash-only; current gross and net exposure are "
            f"{currency} 0.00.\n"
            "  Concentration is not applicable. This does not claim that all financial "
            "risks are zero.\n"
            f"  Pending orders excluded from current exposure: {pending_count}.\n"
            "  No risk-policy threshold is configured."
        )

    qualification = "DEGRADED" if status == "degraded" else "AVAILABLE"
    lines = [
        f"[HQA] Portfolio risk {ts}: {qualification}",
        (
            f"  account={account_id} gross={currency} {exposure['gross_value']:,.2f} "
            f"net={currency} {exposure['net_value']:,.2f}"
        ),
    ]
    if artifact["positions"]:
        top = artifact["positions"][0]
        account_weight_pct = top["computed_account_weight_pct"]
        account_weight_text = (
            f"{account_weight_pct:.4f}%"
            if account_weight_pct is not None
            else "unavailable"
        )
        lines.append(
            f"  Top position {top['symbol']}: {top['gross_share'] * 100:.2f}% of invested "
            f"exposure; {account_weight_text} of account equity."
        )
    if artifact["price_quality"]["valuation_basis"] in {
        "mixed",
        "cost_basis_only",
        "partially_classified",
    }:
        lines.append("  Includes valuation estimates; this is not a pure current-market valuation.")
    else:
        lines.append("  Valuation uses the market-price provenance reported by the snapshot.")
    pending_count = account["pending_order_count"] or 0
    lines.append(
        f"  Pending orders excluded from current exposure: {pending_count}."
    )
    history_source = artifact.get("history_source")
    history = artifact.get("historical_risk")
    if history_source and history:
        if history_source["status"] == "unavailable":
            error = history_source.get("error") or {}
            lines.append(
                "  Historical correlation/beta unavailable: "
                f"{error.get('message', history.get('reason', 'unknown reason'))}."
            )
            fallback_error = history_source.get("fallback_error")
            if fallback_error:
                lines.append(
                    "  Tiingo fallback also failed "
                    f"({fallback_error.get('code', 'unknown')}); "
                    "no data was substituted."
                )
            else:
                lines.append(
                    "  No sample, cached-local, Tiingo, or Longbridge data was substituted."
                )
        elif history["status"] == "unavailable":
            lines.append(
                "  Historical correlation/beta unavailable: "
                f"{history.get('reason', 'unknown reason')} "
                f"({history['aligned_return_count']} aligned returns; minimum "
                f"{history['minimum_aligned_returns']})."
            )
        elif history["status"] in {"available", "degraded"}:
            provider_label = (
                "Tiingo" if history_source.get("provider") == "tiingo" else "Futu"
            )
            lines.append(
                f"  Historical source: {provider_label} QFQ daily, "
                f"{history_source['requested_start']}..{history_source['requested_end']}."
            )
            fallback = history_source.get("fallback")
            if fallback:
                primary_error = fallback.get("primary_error") or {}
                lines.append(
                    "  Futu history failed "
                    f"({primary_error.get('code', 'unknown')}); Tiingo data was "
                    "substituted with explicit provenance."
                )
            lines.append(
                f"  {history['aligned_return_count']} aligned daily returns were used "
                f"(minimum {history['minimum_aligned_returns']})."
            )
            available_betas = [
                row for row in history["betas"] if row["status"] == "available"
            ]
            if available_betas:
                beta_text = "; ".join(
                    f"{row['symbol']} {row['value']:.2f}" for row in available_betas
                )
                lines.append(f"  Beta vs {history['benchmark']}: {beta_text}.")
            unavailable_betas = [
                row for row in history["betas"] if row["status"] != "available"
            ]
            if unavailable_betas:
                beta_text = "; ".join(
                    f"{row['symbol']} ({row.get('reason', 'unknown reason')})"
                    for row in unavailable_betas
                )
                lines.append(
                    f"  Beta unavailable vs {history['benchmark']}: {beta_text}."
                )
            if history["correlations_status"] == "not_applicable":
                lines.append(
                    "  Position-to-position correlation is not applicable for one position."
                )
            elif history["correlations"]:
                available_correlations = [
                    row
                    for row in history["correlations"]
                    if row["status"] == "available"
                ]
                if available_correlations:
                    strongest = max(
                        available_correlations,
                        key=lambda row: abs(row["value"]),
                    )
                    lines.append(
                        "  Largest absolute observed pair correlation: "
                        f"{strongest['left']}/{strongest['right']} "
                        f"{strongest['value']:.2f}."
                    )
                unavailable_correlations = [
                    row
                    for row in history["correlations"]
                    if row["status"] != "available"
                ]
                if unavailable_correlations:
                    correlation_text = "; ".join(
                        f"{row['left']}/{row['right']} "
                        f"({row.get('reason', 'unknown reason')})"
                        for row in unavailable_correlations
                    )
                    lines.append(
                        "  Position correlation unavailable: "
                        f"{correlation_text}."
                    )
            lines.append(
                "  Historical relationships are estimates, not forecasts or trading recommendations."
            )
    lines.append(
        "  Concentration is descriptive only; no threshold configured and no policy verdict produced."
    )
    return "\n".join(lines)


def history_fallback_from_env(
    env_value: Optional[str] = None,
) -> tuple[
    Optional[Callable[[list[str], str, str], tuple[int, str]]],
    Optional[str],
]:
    """Resolve the optional, explicit history fallback provider.

    Reads HQA_PORTFOLIO_RISK_HISTORY_FALLBACK unless env_value is given.
    Empty/off disables (default). Only 'tiingo' is supported; anything else
    raises ValueError so misconfiguration is visible to the caller.
    """
    raw = (
        os.environ.get("HQA_PORTFOLIO_RISK_HISTORY_FALLBACK", "")
        if env_value is None
        else env_value
    )
    choice = raw.strip().lower()
    if choice in {"", "off", "none"}:
        return None, None
    if choice == "tiingo":

        def _tiingo_history(
            symbols: list[str], start: str, end: str
        ) -> tuple[int, str]:
            return quant_cli.run_historical_prices(
                symbols, start, end, provider="tiingo"
            )

        return _tiingo_history, "tiingo"
    raise ValueError(
        "HQA_PORTFOLIO_RISK_HISTORY_FALLBACK only supports 'tiingo', 'off', or empty"
    )


def run(
    run_snapshot: Callable[[str], tuple[int, str]],
    now_iso: Callable[[], str],
    log_path: Path,
    account_id: str = "default",
    run_history: Optional[
        Callable[[list[str], str, str], tuple[int, str]]
    ] = None,
    benchmark: str = "SPY",
    minimum_aligned_returns: int = 60,
    run_history_fallback: Optional[
        Callable[[list[str], str, str], tuple[int, str]]
    ] = None,
    history_fallback_provider: Optional[str] = None,
    history_retry_sleep: Optional[Callable[[float], None]] = None,
) -> str:
    exit_code: Optional[int] = None
    artifact: Optional[dict[str, Any]] = None
    artifact_account_id = "<invalid>"
    try:
        if (
            not isinstance(account_id, str)
            or _ACCOUNT_ID_PATTERN.fullmatch(account_id) is None
        ):
            raise _invalid(
                "invalid paper account id; use 1-128 letters, numbers, dots, "
                "underscores, or hyphens, starting with a letter or number"
            )
        account_id.encode("utf-8", errors="strict")
        artifact_account_id = account_id
    except (PortfolioRiskSnapshotError, UnicodeError) as exc:
        generated_at = now_iso()
        artifact = _unavailable_artifact(
            generated_at=generated_at,
            account_id=artifact_account_id,
            code="portfolio_risk_snapshot_invalid",
            message=str(exc),
        )
    if artifact is None:
        try:
            exit_code, output = run_snapshot(artifact_account_id)
        except Exception as exc:
            generated_at = now_iso()
            artifact = _unavailable_artifact(
                generated_at=generated_at,
                account_id=artifact_account_id,
                code="paper_account_snapshot_command_failed",
                message=f"paper account snapshot command failed: {exc}",
            )
        else:
            generated_at = now_iso()
    if artifact is None and exit_code != 0:
        assert exit_code is not None
        code, message = _platform_error(output, exit_code)
        artifact = _unavailable_artifact(
            generated_at=generated_at,
            account_id=artifact_account_id,
            code=code,
            message=message,
            exit_code=exit_code,
        )
    elif artifact is None:
        try:
            snapshot = parse_snapshot(output)
            if snapshot["account_id"] != artifact_account_id:
                raise _invalid(
                    "snapshot account_id does not match the requested paper account"
                )
            artifact = analyze_snapshot(snapshot, generated_at=generated_at)
        except PortfolioRiskSnapshotError as exc:
            artifact = _unavailable_artifact(
                generated_at=generated_at,
                account_id=artifact_account_id,
                code=exc.code,
                message=str(exc),
                exit_code=exit_code,
            )
        except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
            artifact = _unavailable_artifact(
                generated_at=generated_at,
                account_id=artifact_account_id,
                code="portfolio_risk_analysis_failed",
                message=f"portfolio risk analysis failed: {exc}",
                exit_code=exit_code,
            )
    if run_history is not None:
        artifact = _attach_history(
            artifact,
            run_history=run_history,
            generated_at=generated_at,
            benchmark=benchmark,
            minimum_aligned_returns=minimum_aligned_returns,
            run_history_fallback=run_history_fallback,
            history_fallback_provider=history_fallback_provider,
            history_retry_sleep=history_retry_sleep,
        )
    # Validate serializability before opening the append-only artifact. This is
    # a last-resort boundary: finite inputs can still overflow during future
    # derived calculations, and an unattended read must persist one honest
    # unavailable result instead of disappearing without an artifact.
    try:
        serialized = json.dumps(artifact, ensure_ascii=False, allow_nan=False)
        serialized.encode("utf-8", errors="strict")
    except (TypeError, ValueError, OverflowError, UnicodeError, RecursionError) as exc:
        artifact = _unavailable_artifact(
            generated_at=generated_at,
            account_id=artifact_account_id,
            code="portfolio_risk_analysis_failed",
            message=f"portfolio risk artifact contained non-finite data: {exc}",
            exit_code=exit_code,
        )
        serialized = json.dumps(artifact, ensure_ascii=False, allow_nan=False)
        serialized.encode("utf-8", errors="strict")
    runlog.append_jsonl(artifact, log_path)
    return build_report(artifact)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="HQA current-snapshot portfolio risk summary (read-only)"
    )
    parser.add_argument("--account", default="default")
    parser.add_argument("--benchmark", default="SPY")
    parser.add_argument("--minimum-aligned-returns", type=int, default=60)
    parser.add_argument(
        "--current-only",
        action="store_true",
        help="Skip historical Futu correlation/beta and emit the v1 current snapshot only.",
    )
    parser.add_argument(
        "--history-fallback",
        default=os.environ.get("HQA_PORTFOLIO_RISK_HISTORY_FALLBACK", ""),
        help=(
            "Optional fallback history provider used only when Futu fails "
            "after one retry. Supported: 'tiingo'; empty/off disables "
            "(default; also via HQA_PORTFOLIO_RISK_HISTORY_FALLBACK)."
        ),
    )
    parser.add_argument(
        "--log", default=str(config.LOG_DIR / "portfolio_risk.jsonl")
    )
    args = parser.parse_args(argv)
    try:
        run_history_fallback, history_fallback_provider = history_fallback_from_env(
            args.history_fallback
        )
    except ValueError:
        parser.error("--history-fallback only supports 'tiingo', 'off', or empty")
    report = run(
        quant_cli.run_paper_account_snapshot,
        runlog.utc_now_iso,
        Path(args.log),
        account_id=args.account,
        run_history=(
            None if args.current_only else quant_cli.run_historical_prices
        ),
        benchmark=args.benchmark,
        minimum_aligned_returns=args.minimum_aligned_returns,
        run_history_fallback=None if args.current_only else run_history_fallback,
        history_fallback_provider=(
            None if args.current_only else history_fallback_provider
        ),
        history_retry_sleep=None if args.current_only else time.sleep,
    )
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

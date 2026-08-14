from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from itertools import combinations
from typing import Any


class HistoricalPriceContractError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "historical_prices_snapshot_invalid",
    ) -> None:
        super().__init__(message)
        self.code = code


def _invalid(message: str) -> HistoricalPriceContractError:
    return HistoricalPriceContractError(message)


def _reject_constant(value: str) -> None:
    raise _invalid(f"non-finite JSON number is not allowed: {value}")


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _invalid(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _validate_json_tree(root: Any, *, max_depth: int = 100) -> None:
    stack: list[tuple[Any, int]] = [(root, 0)]
    while stack:
        value, depth = stack.pop()
        if depth > max_depth:
            raise _invalid("historical price snapshot nesting exceeds supported depth")
        if isinstance(value, str):
            try:
                value.encode("utf-8", errors="strict")
            except UnicodeEncodeError as exc:
                raise _invalid("historical price snapshot contains invalid unicode") from exc
        elif isinstance(value, float) and not math.isfinite(value):
            raise _invalid("historical price snapshot contains a non-finite number")
        elif isinstance(value, dict):
            for key, item in value.items():
                stack.append((key, depth + 1))
                stack.append((item, depth + 1))
        elif isinstance(value, list):
            for item in value:
                stack.append((item, depth + 1))


def _require_keys(value: dict[str, Any], keys: tuple[str, ...], path: str) -> None:
    missing = [key for key in keys if key not in value]
    if missing:
        raise _invalid(f"{path} missing required fields: {', '.join(missing)}")


def _strict_date(value: Any, path: str) -> str:
    if not isinstance(value, str):
        raise _invalid(f"{path} must be an ISO date")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise _invalid(f"{path} must use strict YYYY-MM-DD") from exc
    return parsed.isoformat()


def _aware_timestamp(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise _invalid(f"{path} must be a timezone-aware timestamp")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise _invalid(f"{path} must be a timezone-aware timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _invalid(f"{path} must be a timezone-aware timestamp")
    return parsed.isoformat()


def _normalize_symbols(symbols: list[str]) -> list[str]:
    if not isinstance(symbols, list) or not symbols:
        raise _invalid("expected_symbols must be a non-empty list")
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_symbol in symbols:
        if not isinstance(raw_symbol, str) or not raw_symbol.strip():
            raise _invalid("symbols must be non-empty strings")
        symbol = raw_symbol.strip().upper()
        if symbol in seen:
            raise _invalid(f"duplicate normalized symbol: {symbol}")
        seen.add(symbol)
        normalized.append(symbol)
    return normalized


def parse_price_snapshot(
    output: str,
    *,
    expected_symbols: list[str],
    expected_start: str | None = None,
    expected_end: str | None = None,
    expected_provider: str = "futu",
) -> dict[str, Any]:
    if not isinstance(output, str) or not output.strip():
        raise _invalid("historical price output is empty")
    try:
        payload = json.loads(
            output,
            parse_constant=_reject_constant,
            object_pairs_hook=_object_without_duplicate_keys,
        )
        validated = _validate_payload(
            payload,
            expected_symbols=expected_symbols,
            expected_provider=expected_provider,
        )
        if expected_start is not None and validated["start"] != expected_start:
            raise _invalid("historical price start does not match the request")
        if expected_end is not None and validated["end"] != expected_end:
            raise _invalid("historical price end does not match the request")
        return validated
    except HistoricalPriceContractError:
        raise
    except RecursionError as exc:
        raise _invalid("historical price snapshot nesting exceeds supported depth") from exc
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise _invalid(
            f"historical price output is not one complete JSON document: {exc}"
        ) from exc


def parse_price_error(output: str) -> dict[str, Any]:
    if not isinstance(output, str) or not output.strip():
        raise _invalid("historical price error output is empty")
    try:
        payload = json.loads(
            output,
            parse_constant=_reject_constant,
            object_pairs_hook=_object_without_duplicate_keys,
        )
        _validate_json_tree(payload)
    except HistoricalPriceContractError:
        raise
    except RecursionError as exc:
        raise _invalid("historical price error nesting exceeds supported depth") from exc
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise _invalid(
            f"historical price error is not one complete JSON document: {exc}"
        ) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("error"), dict):
        raise _invalid("historical price error envelope is missing error")
    error = payload["error"]
    code = error.get("code")
    message = error.get("message")
    if not isinstance(code, str) or not code or not isinstance(message, str) or not message:
        raise _invalid("historical price error requires code and message")
    provider = error.get("provider")
    provider_code = error.get("provider_code")
    if provider is not None and not isinstance(provider, str):
        raise _invalid("historical price error provider must be a string or null")
    if provider_code is not None and not isinstance(provider_code, str):
        raise _invalid("historical price error provider_code must be a string or null")
    return {
        "code": code,
        "provider": provider,
        "provider_code": provider_code,
        "message": message,
    }


SUPPORTED_HISTORY_PROVIDERS = ("futu", "tiingo")


def _validate_payload(
    payload: Any,
    *,
    expected_symbols: list[str],
    expected_provider: str = "futu",
) -> dict[str, Any]:
    if expected_provider not in SUPPORTED_HISTORY_PROVIDERS:
        raise _invalid(f"unsupported history provider: {expected_provider}")
    if not isinstance(payload, dict):
        raise _invalid("historical price snapshot must be an object")
    _validate_json_tree(payload)
    _require_keys(
        payload,
        (
            "schema_version",
            "provider",
            "source",
            "interval",
            "adjustment",
            "start",
            "end",
            "fetched_at",
            "symbols",
            "series",
        ),
        "historical price snapshot",
    )
    if payload["schema_version"] != "1.0":
        raise _invalid("unsupported historical price schema_version")
    if (
        payload["provider"] != expected_provider
        or payload["source"] != expected_provider
    ):
        raise _invalid(
            f"historical price provenance must be explicit {expected_provider}"
        )
    if payload["interval"] != "1d" or payload["adjustment"] != "qfq":
        raise _invalid("historical price provenance must be 1d qfq")
    start = _strict_date(payload["start"], "historical price snapshot.start")
    end = _strict_date(payload["end"], "historical price snapshot.end")
    if start > end:
        raise _invalid("historical price snapshot start must not be after end")
    _aware_timestamp(payload["fetched_at"], "historical price snapshot.fetched_at")

    expected = _normalize_symbols(expected_symbols)
    actual = _normalize_symbols(payload["symbols"])
    if actual != expected:
        raise _invalid("historical price symbols do not exactly match the request")
    series = payload["series"]
    if not isinstance(series, list) or len(series) != len(expected):
        raise _invalid("historical price series must match requested symbols")

    for index, item in enumerate(series):
        path = f"historical price snapshot.series[{index}]"
        if not isinstance(item, dict):
            raise _invalid(f"{path} must be an object")
        _require_keys(
            item,
            ("symbol", "row_count", "first_date", "last_date", "rows"),
            path,
        )
        if item["symbol"] != expected[index]:
            raise _invalid(f"{path}.symbol does not match requested order")
        rows = item["rows"]
        if not isinstance(rows, list) or not rows:
            raise _invalid(f"{path}.rows must be a non-empty array")
        if type(item["row_count"]) is not int or item["row_count"] != len(rows):
            raise _invalid(f"{path}.row_count does not match rows")
        dates: list[str] = []
        for row_index, row in enumerate(rows):
            row_path = f"{path}.rows[{row_index}]"
            if not isinstance(row, dict):
                raise _invalid(f"{row_path} must be an object")
            _require_keys(row, ("date", "close"), row_path)
            row_date = _strict_date(row["date"], f"{row_path}.date")
            close = row["close"]
            try:
                finite_close = float(close)
            except (TypeError, ValueError, OverflowError) as exc:
                raise _invalid(
                    f"{row_path}.close must be finite and positive"
                ) from exc
            if (
                isinstance(close, bool)
                or not isinstance(close, (int, float))
                or not math.isfinite(finite_close)
                or finite_close <= 0
            ):
                raise _invalid(f"{row_path}.close must be finite and positive")
            if row_date < start or row_date > end:
                raise _invalid(f"{row_path}.date falls outside requested window")
            dates.append(row_date)
        if dates != sorted(dates) or len(set(dates)) != len(dates):
            raise _invalid(f"{path}.rows must have unique ascending dates")
        if item["first_date"] != dates[0] or item["last_date"] != dates[-1]:
            raise _invalid(f"{path} first/last date metadata does not match rows")
    return payload


def history_window(generated_at: str, *, lookback_days: int = 400) -> tuple[str, str]:
    text = generated_at[:-1] + "+00:00" if generated_at.endswith("Z") else generated_at
    try:
        generated = datetime.fromisoformat(text)
    except (TypeError, ValueError) as exc:
        raise ValueError("generated_at must be a timezone-aware timestamp") from exc
    if generated.tzinfo is None or generated.utcoffset() is None:
        raise ValueError("generated_at must be a timezone-aware timestamp")
    end = generated.astimezone(timezone.utc).date() - timedelta(days=1)
    start = end - timedelta(days=lookback_days)
    return start.isoformat(), end.isoformat()


def _metric_base(
    *,
    count: int,
    return_dates: list[str],
) -> dict[str, Any]:
    return {
        "status": "available",
        "value": None,
        "aligned_return_count": count,
        "first_return_date": return_dates[0] if return_dates else None,
        "last_return_date": return_dates[-1] if return_dates else None,
        "reason": None,
    }


def _relationship(
    left: list[float],
    right: list[float],
    *,
    return_dates: list[str],
    kind: str,
) -> dict[str, Any]:
    count = len(left)
    metric = _metric_base(count=count, return_dates=return_dates)
    try:
        left_mean = math.fsum(left) / count
        right_mean = math.fsum(right) / count
        left_deviations = [value - left_mean for value in left]
        right_deviations = [value - right_mean for value in right]
        left_variance = math.fsum(value * value for value in left_deviations)
        right_variance = math.fsum(value * value for value in right_deviations)
        covariance = math.fsum(
            left_value * right_value
            for left_value, right_value in zip(left_deviations, right_deviations)
        )
    except (ArithmeticError, ValueError):
        metric.update(status="unavailable", reason="historical_metric_non_finite")
        return metric
    if not all(
        math.isfinite(value)
        for value in (left_variance, right_variance, covariance)
    ):
        metric.update(status="unavailable", reason="historical_metric_non_finite")
        return metric
    if kind == "beta":
        if right_variance <= 0:
            metric.update(status="unavailable", reason="benchmark_zero_variance")
            return metric
        value = covariance / right_variance
    else:
        if left_variance <= 0 or right_variance <= 0:
            metric.update(status="unavailable", reason="series_zero_variance")
            return metric
        try:
            denominator = math.sqrt(left_variance * right_variance)
        except (ArithmeticError, ValueError):
            metric.update(status="unavailable", reason="historical_metric_non_finite")
            return metric
        if not math.isfinite(denominator) or denominator <= 0:
            metric.update(status="unavailable", reason="historical_metric_non_finite")
            return metric
        value = covariance / denominator
    if not math.isfinite(value):
        metric.update(status="unavailable", reason="historical_metric_non_finite")
        return metric
    metric["value"] = value
    return metric


def analyze_price_history(
    payload: dict[str, Any],
    *,
    position_symbols: list[str],
    benchmark: str,
    minimum_aligned_returns: int = 60,
    history_end_policy: str,
    provider: str = "futu",
) -> dict[str, Any]:
    if (
        isinstance(minimum_aligned_returns, bool)
        or not isinstance(minimum_aligned_returns, int)
        or minimum_aligned_returns < 2
    ):
        raise HistoricalPriceContractError(
            "minimum_aligned_returns must be an integer >= 2",
            code="historical_risk_invalid_configuration",
        )
    positions = _normalize_symbols(position_symbols)
    benchmark_symbol = _normalize_symbols([benchmark])[0]
    requested = list(positions)
    if benchmark_symbol not in requested:
        requested.append(benchmark_symbol)
    validated = _validate_payload(
        payload, expected_symbols=requested, expected_provider=provider
    )

    series_by_symbol: dict[str, dict[str, float]] = {}
    for item in validated["series"]:
        series_by_symbol[item["symbol"]] = {
            row["date"]: float(row["close"]) for row in item["rows"]
        }
    common_dates = sorted(
        set.intersection(*(set(rows) for rows in series_by_symbol.values()))
    )
    return_dates = common_dates[1:]
    returns: dict[str, list[float]] = {}
    return_failure = False
    for symbol, closes in series_by_symbol.items():
        values: list[float] = []
        for previous_date, current_date in zip(common_dates, common_dates[1:]):
            value = closes[current_date] / closes[previous_date] - 1.0
            if not math.isfinite(value):
                return_failure = True
                break
            values.append(value)
        returns[symbol] = values

    canonical = json.dumps(
        validated,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    history_source = {
        "status": "available",
        "provider": provider,
        "source": provider,
        "adjustment": "qfq",
        "interval": "1d",
        "requested_start": validated["start"],
        "requested_end": validated["end"],
        "fetched_at": validated["fetched_at"],
        "history_end_policy": history_end_policy,
        "payload_sha256": sha256(canonical.encode("utf-8")).hexdigest(),
        "series": [
            {
                "symbol": item["symbol"],
                "row_count": item["row_count"],
                "first_date": item["first_date"],
                "last_date": item["last_date"],
            }
            for item in validated["series"]
        ],
        "error": None,
    }
    limitations = [
        "historical_relationship_not_forecast",
        "qfq_history_can_be_revised_after_corporate_actions",
        "no_statistical_confidence_interval",
        "no_risk_policy_thresholds_configured",
    ]
    aligned_return_count = len(return_dates)
    base_risk = {
        "benchmark": benchmark_symbol,
        "return_kind": "simple_close_to_close",
        "alignment": "global_date_inner_join_before_returns",
        "minimum_aligned_returns": minimum_aligned_returns,
        "aligned_price_count": len(common_dates),
        "aligned_return_count": aligned_return_count,
        "first_return_date": return_dates[0] if return_dates else None,
        "last_return_date": return_dates[-1] if return_dates else None,
        "correlations_status": (
            "not_applicable" if len(positions) < 2 else "available"
        ),
        "correlations": [],
        "betas": [],
        "limitations": limitations,
        "reason": None,
    }
    if return_failure:
        base_risk.update(
            status="unavailable",
            correlations_status=(
                "not_applicable" if len(positions) < 2 else "unavailable"
            ),
            reason="historical_return_non_finite",
        )
        history_source["status"] = "degraded"
        return {"history_source": history_source, "historical_risk": base_risk}
    if aligned_return_count < minimum_aligned_returns:
        base_risk.update(
            status="unavailable",
            correlations_status=(
                "not_applicable" if len(positions) < 2 else "unavailable"
            ),
            reason="insufficient_aligned_returns",
        )
        return {"history_source": history_source, "historical_risk": base_risk}

    betas: list[dict[str, Any]] = []
    for symbol in positions:
        metric = _relationship(
            returns[symbol],
            returns[benchmark_symbol],
            return_dates=return_dates,
            kind="beta",
        )
        betas.append({"symbol": symbol, "benchmark": benchmark_symbol, **metric})
    correlations: list[dict[str, Any]] = []
    for left, right in combinations(positions, 2):
        metric = _relationship(
            returns[left],
            returns[right],
            return_dates=return_dates,
            kind="correlation",
        )
        correlations.append({"left": left, "right": right, **metric})
    base_risk["betas"] = betas
    base_risk["correlations"] = correlations
    if correlations and any(
        metric["status"] != "available" for metric in correlations
    ):
        base_risk["correlations_status"] = "degraded"
    unavailable_metric = any(
        metric["status"] != "available" for metric in [*betas, *correlations]
    )
    base_risk["status"] = "degraded" if unavailable_metric else "available"
    if unavailable_metric:
        base_risk["reason"] = "one_or_more_historical_metrics_unavailable"
    return {"history_source": history_source, "historical_risk": base_risk}

from __future__ import annotations

import errno
import fcntl
import json
import math
import os
import re
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Iterator, Optional
from zoneinfo import ZoneInfo

from hqa import historical_risk

PriceRunner = Callable[[list[str], str, str], tuple[int, str]]

_SCHEMA_VERSION = "1.0"
_MARKET_TIMEZONE = "America/New_York"
_SYMBOL_PATTERN = re.compile(r"[A-Z][A-Z0-9.-]{0,15}")
_ID_PATTERN = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2})-([0-9]{3,12})")
_REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}")
_HASH_PATTERN = re.compile(r"[0-9a-f]{64}")
_ALLOWED_DIRECTIONS = {"up", "down", "flat"}
_ENTRY_LOOKBACK_DAYS = 10
_MAX_ENTRY_STALENESS_DAYS = 7
_MAX_HORIZON_DAYS = 489
_MAX_OUTCOME_RESOLUTION_DAYS = 10
_RECOVERABLE_RECONCILE_ERROR_CODES = {
    "prediction_entry_session_missing",
    "prediction_history_contract_invalid",
    "prediction_history_unavailable",
    "prediction_outcome_session_unavailable",
    "prediction_scoring_evidence_invalid",
}


class PredictionLedgerError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


def _invalid(message: str) -> PredictionLedgerError:
    return PredictionLedgerError("prediction_invalid_request", message)


def _corrupt(message: str) -> PredictionLedgerError:
    return PredictionLedgerError("prediction_ledger_corrupt", message)


def _reject_constant(value: str) -> None:
    raise _corrupt(f"non-finite JSON number is not allowed: {value}")


def _object_without_duplicate_keys(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _corrupt(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _validate_json_tree(root: Any, *, max_depth: int = 100) -> None:
    stack: list[tuple[Any, int]] = [(root, 0)]
    while stack:
        value, depth = stack.pop()
        if depth > max_depth:
            raise _corrupt("prediction event nesting exceeds supported depth")
        if isinstance(value, str):
            try:
                value.encode("utf-8", errors="strict")
            except UnicodeEncodeError as exc:
                raise _corrupt("prediction event contains invalid unicode") from exc
        elif isinstance(value, float) and not math.isfinite(value):
            raise _corrupt("prediction event contains a non-finite number")
        elif isinstance(value, dict):
            for key, item in value.items():
                stack.append((key, depth + 1))
                stack.append((item, depth + 1))
        elif isinstance(value, list):
            for item in value:
                stack.append((item, depth + 1))


def _strict_date(value: Any, field: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        raise _invalid(f"{field} must use strict YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise _invalid(f"{field} must use strict YYYY-MM-DD") from exc
    return parsed.isoformat()


def _prediction_id(value: Any, field: str = "prediction id") -> tuple[str, int]:
    if not isinstance(value, str):
        raise _invalid(f"{field} must be canonical")
    match = _ID_PATTERN.fullmatch(value)
    if match is None:
        raise _invalid(f"{field} must be canonical")
    day = _strict_date(match.group(1), f"{field} date")
    sequence = int(match.group(2))
    if sequence < 1 or match.group(2) != f"{sequence:03d}":
        raise _invalid(f"{field} must be canonical")
    return day, sequence


def _parse_aware_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise _invalid(f"{field} must be a timezone-aware timestamp")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise _invalid(f"{field} must be a timezone-aware timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _invalid(f"{field} must be a timezone-aware timestamp")
    return parsed


def _utc_timestamp(value: Any, field: str) -> str:
    try:
        parsed = _parse_aware_timestamp(value, field).astimezone(timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise _invalid(f"{field} falls outside the supported timestamp range") from exc
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def _completed_session_cutoff(as_of: str) -> str:
    parsed = _parse_aware_timestamp(as_of, "as_of")
    try:
        market_date = parsed.astimezone(ZoneInfo(_MARKET_TIMEZONE)).date()
        return (market_date - timedelta(days=1)).isoformat()
    except (OverflowError, OSError, ValueError) as exc:
        raise _invalid("as_of falls outside the supported market-date range") from exc


def _finite_number(value: Any, field: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _invalid(f"{field} must be a finite number")
    try:
        normalized = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise _invalid(f"{field} must be a finite number") from exc
    if not math.isfinite(normalized) or (positive and normalized <= 0):
        qualifier = "finite and positive" if positive else "finite"
        raise _invalid(f"{field} must be {qualifier}")
    return normalized


def _text(
    value: Any,
    field: str,
    *,
    required: bool,
    max_length: int,
) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise _invalid(f"{field} must be text")
    normalized = value.strip()
    if required and not normalized:
        raise _invalid(f"{field} is required")
    if len(normalized) > max_length:
        raise _invalid(f"{field} exceeds {max_length} characters")
    try:
        normalized.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise _invalid(f"{field} contains invalid unicode") from exc
    return normalized


def _normalize_request(request: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise _invalid("prediction request must be an object")
    allowed = {
        "symbol",
        "subject",
        "direction",
        "horizon_date",
        "confidence",
        "range_low",
        "range_high",
        "flat_threshold_pct",
        "falsifier",
        "rationale",
        "request_id",
    }
    unknown = [key for key in request if not isinstance(key, str) or key not in allowed]
    if unknown:
        rendered = ", ".join(sorted((repr(key) for key in unknown)))
        raise _invalid(f"unknown prediction fields: {rendered}")
    raw_symbol = request.get("symbol")
    if not isinstance(raw_symbol, str):
        raise _invalid("symbol is required")
    symbol = raw_symbol.strip().upper()
    if _SYMBOL_PATTERN.fullmatch(symbol) is None or symbol.startswith("US."):
        raise _invalid("symbol must be a plain US ticker")
    direction = request.get("direction")
    if not isinstance(direction, str) or direction not in _ALLOWED_DIRECTIONS:
        raise _invalid("direction must be one of: down, flat, up")
    confidence = _finite_number(request.get("confidence"), "confidence")
    if confidence < 0 or confidence > 1:
        raise _invalid("confidence must be in [0, 1]")
    flat_threshold = _finite_number(
        request.get("flat_threshold_pct", 0.005),
        "flat_threshold_pct",
        positive=True,
    )
    if flat_threshold >= 1:
        raise _invalid("flat_threshold_pct must be less than 1")
    low = request.get("range_low")
    high = request.get("range_high")
    if (low is None) != (high is None):
        raise _invalid("range_low and range_high must be supplied together")
    if low is not None:
        low = _finite_number(low, "range_low", positive=True)
        high = _finite_number(high, "range_high", positive=True)
        if low >= high:
            raise _invalid("range_low must be less than range_high")
    request_id = request.get("request_id")
    if request_id is not None and (
        not isinstance(request_id, str)
        or _REQUEST_ID_PATTERN.fullmatch(request_id) is None
    ):
        raise _invalid(
            "request_id must use 1-200 letters, numbers, dots, underscores, "
            "colons, slashes, or hyphens"
        )
    return {
        "symbol": symbol,
        "subject": _text(
            request.get("subject", symbol),
            "subject",
            required=True,
            max_length=200,
        ),
        "direction": direction,
        "horizon_date": _strict_date(request.get("horizon_date"), "horizon_date"),
        "confidence": confidence,
        "range_low": low,
        "range_high": high,
        "flat_threshold_pct": flat_threshold,
        "falsifier": _text(
            request.get("falsifier"),
            "falsifier",
            required=True,
            max_length=1000,
        ),
        "rationale": _text(
            request.get("rationale", ""),
            "rationale",
            required=False,
            max_length=4000,
        ),
        "request_id": request_id,
    }


def _payload_sha256(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def _intent_sha256(normalized: dict[str, Any]) -> str:
    intent = {key: value for key, value in normalized.items() if key != "request_id"}
    return _payload_sha256(intent)


def _state_from_created(event: dict[str, Any]) -> dict[str, Any]:
    state = dict(event)
    state.pop("event", None)
    state["status"] = "open"
    return state


def _state_from_scored(
    state: dict[str, Any],
    event: dict[str, Any],
) -> dict[str, Any]:
    scored = dict(state)
    scored["revision"] = 2
    scored["status"] = "scored"
    for key, value in event.items():
        if key not in {"schema_version", "event", "id", "revision"}:
            scored[key] = value
    return scored


def _outcome_direction(outcome_return: float, flat_threshold_pct: float) -> str:
    if outcome_return > flat_threshold_pct:
        return "up"
    if outcome_return < -flat_threshold_pct:
        return "down"
    return "flat"


class PredictionLedger:
    def __init__(
        self,
        prediction_dir: Path,
        *,
        run_history: PriceRunner,
        now: Callable[[], str],
        lock_timeout_seconds: float = 5.0,
    ) -> None:
        self.prediction_dir = Path(prediction_dir)
        self.entries_path = self.prediction_dir / "entries.jsonl"
        self.lock_path = self.prediction_dir / ".ledger.lock"
        self._run_history = run_history
        self._now = now
        if (
            isinstance(lock_timeout_seconds, bool)
            or not isinstance(lock_timeout_seconds, (int, float))
            or not math.isfinite(float(lock_timeout_seconds))
            or float(lock_timeout_seconds) <= 0
        ):
            raise ValueError("lock_timeout_seconds must be finite and positive")
        self._lock_timeout_seconds = float(lock_timeout_seconds)

    def preview(self, request: dict[str, Any]) -> dict[str, Any]:
        """Normalize a prediction intent without reading prices or writing the ledger."""
        normalized = _normalize_request(request)
        intent_sha256 = _intent_sha256(normalized)
        request_id = normalized["request_id"] or f"intent:{intent_sha256}"
        prediction_request = dict(normalized)
        prediction_request["request_id"] = request_id
        return {
            "schema_version": _SCHEMA_VERSION,
            "status": "validated",
            "request_id": request_id,
            "intent_sha256": intent_sha256,
            "prediction_request": prediction_request,
        }

    def prepare(self, request: dict[str, Any]) -> dict[str, Any]:
        """Validate a prediction intent and attach strict entry evidence without writing."""
        preview = self.preview(request)
        return self._prepare_normalized(
            preview["prediction_request"],
            intent_sha256=preview["intent_sha256"],
            request_id=preview["request_id"],
        )

    def create(self, request: dict[str, Any]) -> dict[str, Any]:
        preview = self.preview(request)
        normalized = preview["prediction_request"]
        intent_sha256 = preview["intent_sha256"]
        request_id = preview["request_id"]
        existing = self._find_existing_request(
            self.list(),
            request_id=request_id,
            intent_sha256=intent_sha256,
        )
        if existing is not None:
            return existing
        prepared = self._prepare_normalized(
            normalized,
            intent_sha256=intent_sha256,
            request_id=request_id,
        )
        created_at = prepared["created_at"]
        prediction_request = prepared["prediction_request"]
        entry_price = prepared["entry_price"]
        low = prediction_request["range_low"]
        high = prediction_request["range_high"]

        try:
            with self._locked(exclusive=True, create=True) as fd:
                assert fd is not None
                events = self._read_events(fd, allow_empty=True)
                states = self._reduce(events)
                existing = self._find_existing_request(
                    list(states.values()),
                    request_id=request_id,
                    intent_sha256=intent_sha256,
                )
                if existing is not None:
                    return existing
                prediction_id = self._next_id(states, created_at[:10])
                event = {
                    "schema_version": _SCHEMA_VERSION,
                    "event": "prediction_created",
                    "id": prediction_id,
                    "revision": 1,
                    "request_id": request_id,
                    "intent_sha256": intent_sha256,
                    "created_at": created_at,
                    "subject_kind": "us_equity",
                    "subject": prediction_request["subject"],
                    "symbol": prediction_request["symbol"],
                    "direction": prediction_request["direction"],
                    "confidence": prediction_request["confidence"],
                    "horizon_date": prediction_request["horizon_date"],
                    "flat_threshold_pct": prediction_request["flat_threshold_pct"],
                    "range_low": low,
                    "range_high": high,
                    "range_return_low": prepared["range_return_low"],
                    "range_return_high": prepared["range_return_high"],
                    "falsifier": prediction_request["falsifier"],
                    "rationale": prediction_request["rationale"],
                    "market_timezone": _MARKET_TIMEZONE,
                    "outcome_session_policy": (
                        "first_observed_session_on_or_after_horizon"
                    ),
                    "entry_price": entry_price,
                }
                self._validate_created_event(event)
                self._append_event(fd, event)
                return _state_from_created(event)
        except PredictionLedgerError:
            raise
        except OSError as exc:
            raise PredictionLedgerError(
                "prediction_ledger_io_error",
                f"prediction ledger write failed: {type(exc).__name__}",
                retryable=True,
            ) from exc

    def _prepare_normalized(
        self,
        normalized: dict[str, Any],
        *,
        intent_sha256: str,
        request_id: str,
    ) -> dict[str, Any]:
        created_at = _utc_timestamp(self._now(), "created_at")
        cutoff = _completed_session_cutoff(created_at)
        cutoff_date = date.fromisoformat(cutoff)
        start = (cutoff_date - timedelta(days=_ENTRY_LOOKBACK_DAYS)).isoformat()
        entry_price = self._read_entry_price(normalized["symbol"], start, cutoff)
        entry_date = date.fromisoformat(entry_price["session_date"])
        if (cutoff_date - entry_date).days > _MAX_ENTRY_STALENESS_DAYS:
            raise PredictionLedgerError(
                "prediction_entry_price_unavailable",
                "latest completed Futu session is too old to anchor a prediction",
                retryable=True,
            )
        horizon_date = date.fromisoformat(normalized["horizon_date"])
        if horizon_date <= entry_date:
            raise _invalid("horizon_date must be after the entry session")
        if (horizon_date - entry_date).days > _MAX_HORIZON_DAYS:
            raise _invalid(
                f"horizon_date must be within {_MAX_HORIZON_DAYS} calendar days "
                "of the entry session"
            )
        entry_close = entry_price["close"]
        low = normalized["range_low"]
        high = normalized["range_high"]
        try:
            range_return_low = None if low is None else low / entry_close - 1.0
            range_return_high = None if high is None else high / entry_close - 1.0
        except OverflowError as exc:
            raise _invalid("target range produces a non-finite return") from exc
        if range_return_low is not None:
            range_return_low = _finite_number(
                range_return_low,
                "range_return_low",
            )
            range_return_high = _finite_number(
                range_return_high,
                "range_return_high",
            )
        prepared_request = dict(normalized)
        prepared_request["request_id"] = request_id
        return {
            "schema_version": _SCHEMA_VERSION,
            "status": "prepared",
            "request_id": request_id,
            "intent_sha256": intent_sha256,
            "created_at": created_at,
            "prediction_request": prepared_request,
            "market_timezone": _MARKET_TIMEZONE,
            "outcome_session_policy": "first_observed_session_on_or_after_horizon",
            "range_return_low": range_return_low,
            "range_return_high": range_return_high,
            "entry_price": entry_price,
        }

    def list(
        self,
        *,
        status: Optional[str] = None,
        since: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        if status is not None and (
            not isinstance(status, str) or status not in {"open", "scored"}
        ):
            raise _invalid("status must be open or scored")
        since_ts = _utc_timestamp(since, "since") if since is not None else None
        try:
            if not self.entries_path.exists():
                return []
            with self._locked(exclusive=False, create=False) as fd:
                if fd is None:
                    raise PredictionLedgerError(
                        "prediction_ledger_io_error",
                        "prediction ledger disappeared before it could be read",
                        retryable=True,
                    )
                states = self._reduce(self._read_events(fd, allow_empty=False))
        except PredictionLedgerError:
            raise
        except OSError as exc:
            raise PredictionLedgerError(
                "prediction_ledger_io_error",
                f"prediction ledger read failed: {type(exc).__name__}",
                retryable=True,
            ) from exc
        rows = sorted(states.values(), key=lambda row: (row["created_at"], row["id"]))
        if status is not None:
            rows = [row for row in rows if row["status"] == status]
        if since_ts is not None:
            rows = [row for row in rows if row["created_at"] >= since_ts]
        return rows

    def reconcile_due(
        self,
        *,
        as_of: Optional[str] = None,
        limit: int = 25,
        cursor: Optional[str] = None,
    ) -> dict[str, Any]:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 25
        ):
            raise _invalid("limit must be an integer in [1, 25]")
        cursor_key = self._parse_cursor(cursor)
        as_of_value = self._now() if as_of is None else as_of
        as_of_utc = _utc_timestamp(as_of_value, "as_of")
        cutoff = _completed_session_cutoff(as_of_utc)
        due = [row for row in self.list(status="open") if row["horizon_date"] <= cutoff]
        due.sort(key=lambda row: (row["horizon_date"], row["id"]))
        candidates = due
        if cursor_key is not None:
            candidates = [
                row for row in due if (row["horizon_date"], row["id"]) > cursor_key
            ]
        selected = candidates[:limit]
        next_cursor = None
        if len(candidates) > len(selected) and selected:
            last = selected[-1]
            next_cursor = f"{last['horizon_date']}|{last['id']}"
        results: list[dict[str, Any]] = []
        degraded = False
        for state in selected:
            try:
                evidence = self._read_scoring_evidence(state, cutoff)
                if evidence is None:
                    results.append(
                        {
                            "id": state["id"],
                            "status": "not_ready",
                            "reason": "no_completed_outcome_session",
                        }
                    )
                    continue
                results.append(
                    self._commit_score(
                        state,
                        evidence=evidence,
                        scored_at=as_of_utc,
                    )
                )
            except PredictionLedgerError as exc:
                if exc.code not in _RECOVERABLE_RECONCILE_ERROR_CODES:
                    raise
                degraded = True
                results.append(
                    {
                        "id": state["id"],
                        "status": "unavailable",
                        "reason": exc.code,
                        "message": exc.message,
                    }
                )
        remaining_due_count = sum(
            1 for row in self.list(status="open") if row["horizon_date"] <= cutoff
        )
        return {
            "schema_version": _SCHEMA_VERSION,
            "status": "degraded" if degraded else "available",
            "as_of": as_of_utc,
            "completed_session_cutoff": cutoff,
            "due_count": len(due),
            "processed_count": len(selected),
            "remaining_due_count": remaining_due_count,
            "next_cursor": next_cursor,
            "results": results,
        }

    def _read_entry_price(self, symbol: str, start: str, end: str) -> dict[str, Any]:
        try:
            exit_code, output = self._run_history([symbol], start, end)
        except Exception as exc:
            raise PredictionLedgerError(
                "prediction_entry_price_unavailable",
                f"historical price command failed: {type(exc).__name__}",
                retryable=True,
            ) from exc
        if exit_code != 0:
            message = "strict Futu entry history is unavailable"
            try:
                error = historical_risk.parse_price_error(output)
                message = error["message"]
            except historical_risk.HistoricalPriceContractError:
                pass
            raise PredictionLedgerError(
                "prediction_entry_price_unavailable",
                message,
                retryable=True,
            )
        try:
            payload = historical_risk.parse_price_snapshot(
                output,
                expected_symbols=[symbol],
                expected_start=start,
                expected_end=end,
            )
        except historical_risk.HistoricalPriceContractError as exc:
            raise PredictionLedgerError(
                "prediction_history_contract_invalid",
                str(exc),
            ) from exc
        rows = payload["series"][0]["rows"]
        latest = rows[-1]
        return {
            "session_date": latest["date"],
            "close": float(latest["close"]),
            "provider": "futu",
            "source": "futu",
            "interval": "1d",
            "adjustment": "qfq",
            "fetched_at": _utc_timestamp(
                payload["fetched_at"],
                "entry_price.fetched_at",
            ),
            "payload_sha256": _payload_sha256(payload),
        }

    def _read_scoring_evidence(
        self,
        state: dict[str, Any],
        cutoff: str,
    ) -> Optional[dict[str, Any]]:
        entry_date = state["entry_price"]["session_date"]
        horizon_date = state["horizon_date"]
        max_end = (
            date.fromisoformat(horizon_date)
            + timedelta(days=_MAX_OUTCOME_RESOLUTION_DAYS)
        ).isoformat()
        end = min(cutoff, max_end)
        if end < horizon_date:
            return None
        try:
            exit_code, output = self._run_history(
                [state["symbol"]],
                entry_date,
                end,
            )
        except Exception as exc:
            raise PredictionLedgerError(
                "prediction_history_unavailable",
                f"historical price command failed: {type(exc).__name__}",
                retryable=True,
            ) from exc
        if exit_code != 0:
            message = "strict Futu scoring history is unavailable"
            try:
                error = historical_risk.parse_price_error(output)
                message = error["message"]
            except historical_risk.HistoricalPriceContractError:
                pass
            raise PredictionLedgerError(
                "prediction_history_unavailable",
                message,
                retryable=True,
            )
        try:
            payload = historical_risk.parse_price_snapshot(
                output,
                expected_symbols=[state["symbol"]],
                expected_start=entry_date,
                expected_end=end,
            )
        except historical_risk.HistoricalPriceContractError as exc:
            raise PredictionLedgerError(
                "prediction_history_contract_invalid",
                str(exc),
            ) from exc
        rows = payload["series"][0]["rows"]
        entry_row = next((row for row in rows if row["date"] == entry_date), None)
        if entry_row is None:
            raise PredictionLedgerError(
                "prediction_entry_session_missing",
                "scoring history no longer contains the recorded entry session",
            )
        outcome_row = next(
            (row for row in rows if row["date"] >= horizon_date),
            None,
        )
        if outcome_row is None:
            if end >= max_end:
                raise PredictionLedgerError(
                    "prediction_outcome_session_unavailable",
                    "no Futu session was observed within the outcome resolution window",
                    retryable=True,
                )
            return None
        return {
            "scoring_entry_close": float(entry_row["close"]),
            "outcome_session_date": outcome_row["date"],
            "outcome_close": float(outcome_row["close"]),
            "provider": "futu",
            "source": "futu",
            "interval": "1d",
            "adjustment": "qfq",
            "fetched_at": _utc_timestamp(
                payload["fetched_at"],
                "price_evidence.fetched_at",
            ),
            "payload_sha256": _payload_sha256(payload),
            "start": entry_date,
            "end": end,
        }

    def _commit_score(
        self,
        state: dict[str, Any],
        *,
        evidence: dict[str, Any],
        scored_at: str,
    ) -> dict[str, Any]:
        scoring_entry_close = evidence["scoring_entry_close"]
        outcome_close = evidence["outcome_close"]
        try:
            outcome_return = outcome_close / scoring_entry_close - 1.0
        except OverflowError as exc:
            raise PredictionLedgerError(
                "prediction_scoring_evidence_invalid",
                "Futu scoring prices produce a non-finite return",
            ) from exc
        if not math.isfinite(outcome_return):
            raise PredictionLedgerError(
                "prediction_scoring_evidence_invalid",
                "Futu scoring prices produce a non-finite return",
            )
        direction = _outcome_direction(
            outcome_return,
            state["flat_threshold_pct"],
        )
        direction_correct = direction == state["direction"]
        direction_brier = (state["confidence"] - int(direction_correct)) ** 2
        range_hit = None
        if state["range_return_low"] is not None:
            range_hit = (
                state["range_return_low"]
                <= outcome_return
                <= state["range_return_high"]
            )
        event = {
            "schema_version": _SCHEMA_VERSION,
            "event": "prediction_scored",
            "id": state["id"],
            "revision": 2,
            "score_id": (f"{state['id']}@{evidence['outcome_session_date']}:futu:qfq"),
            "scored_at": scored_at,
            "scoring_entry_close": scoring_entry_close,
            "outcome_session_date": evidence["outcome_session_date"],
            "outcome_close": outcome_close,
            "outcome_return": outcome_return,
            "outcome_direction": direction,
            "direction_correct": direction_correct,
            "direction_brier": direction_brier,
            "range_hit": range_hit,
            "price_evidence": {
                key: evidence[key]
                for key in (
                    "provider",
                    "source",
                    "interval",
                    "adjustment",
                    "fetched_at",
                    "payload_sha256",
                    "start",
                    "end",
                )
            },
        }
        try:
            with self._locked(exclusive=True, create=False) as fd:
                if fd is None:
                    raise _corrupt("prediction ledger disappeared during scoring")
                states = self._reduce(self._read_events(fd, allow_empty=False))
                current = states.get(state["id"])
                if current is None:
                    raise _corrupt(
                        f"prediction disappeared during scoring: {state['id']}"
                    )
                if current["status"] == "scored":
                    return {
                        "id": state["id"],
                        "status": "already_scored",
                        "outcome_session_date": current["outcome_session_date"],
                    }
                self._validate_scored_event(event, current)
                self._append_event(fd, event)
                return {
                    "id": state["id"],
                    "status": "scored",
                    "outcome_session_date": evidence["outcome_session_date"],
                }
        except PredictionLedgerError:
            raise
        except OSError as exc:
            raise PredictionLedgerError(
                "prediction_ledger_io_error",
                f"prediction ledger score write failed: {type(exc).__name__}",
                retryable=True,
            ) from exc

    @contextmanager
    def _locked(
        self,
        *,
        exclusive: bool,
        create: bool,
    ) -> Iterator[Optional[int]]:
        if not create and not self.entries_path.exists():
            yield None
            return
        if create:
            directory_existed = self.prediction_dir.exists()
            self.prediction_dir.mkdir(parents=True, exist_ok=True)
            if not directory_existed:
                self._fsync_directory(self.prediction_dir.parent)
        if create:
            lock_existed = self.lock_path.exists()
            lock_fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            if not lock_existed:
                self._fsync_directory(self.prediction_dir)
        else:
            lock_flags = os.O_RDWR if exclusive else os.O_RDONLY
            try:
                lock_fd = os.open(self.lock_path, lock_flags)
            except FileNotFoundError as exc:
                raise _corrupt("prediction ledger lock file is missing") from exc
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        deadline = time.monotonic() + self._lock_timeout_seconds
        fd: Optional[int] = None
        try:
            while True:
                try:
                    fcntl.flock(lock_fd, operation | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                        raise
                    if time.monotonic() >= deadline:
                        raise PredictionLedgerError(
                            "prediction_ledger_busy",
                            "prediction ledger lock timed out",
                            retryable=True,
                        ) from exc
                    time.sleep(0.01)
            if create:
                flags = os.O_RDWR | os.O_APPEND | os.O_CREAT
            elif exclusive:
                flags = os.O_RDWR | os.O_APPEND
            else:
                flags = os.O_RDONLY
            try:
                fd = os.open(self.entries_path, flags, 0o600)
            except FileNotFoundError:
                yield None
                return
            yield fd
        finally:
            try:
                if fd is not None:
                    os.close(fd)
            finally:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                finally:
                    os.close(lock_fd)

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        directory_fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    @staticmethod
    def _read_events(fd: int, *, allow_empty: bool) -> list[dict[str, Any]]:
        os.lseek(fd, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
        raw = b"".join(chunks)
        if not raw:
            if allow_empty:
                return []
            raise _corrupt("prediction ledger exists but is empty")
        if not raw.endswith(b"\n"):
            raise _corrupt("prediction ledger has a torn final line")
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise _corrupt("prediction ledger is not valid UTF-8") from exc
        events: list[dict[str, Any]] = []
        for line_number, line in enumerate(text[:-1].split("\n"), start=1):
            if not line:
                raise _corrupt(f"prediction ledger line {line_number} is blank")
            try:
                event = json.loads(
                    line,
                    parse_constant=_reject_constant,
                    object_pairs_hook=_object_without_duplicate_keys,
                )
            except PredictionLedgerError:
                raise
            except (json.JSONDecodeError, RecursionError, ValueError) as exc:
                raise _corrupt(
                    f"prediction ledger line {line_number} is invalid JSON"
                ) from exc
            if not isinstance(event, dict):
                raise _corrupt(f"prediction ledger line {line_number} is not an object")
            _validate_json_tree(event)
            events.append(event)
        return events

    def _reduce(self, events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        states: dict[str, dict[str, Any]] = {}
        request_ids: dict[str, str] = {}
        day_sequences: dict[str, int] = {}
        for event in events:
            event_type = event.get("event")
            if event_type == "prediction_created":
                try:
                    self._validate_created_event(event)
                except PredictionLedgerError as exc:
                    if exc.code == "prediction_invalid_request":
                        raise _corrupt(exc.message) from exc
                    raise
                prediction_id = event["id"]
                if prediction_id in states:
                    raise _corrupt(
                        f"duplicate prediction_created event: {prediction_id}"
                    )
                id_day, id_sequence = _prediction_id(prediction_id)
                expected_sequence = day_sequences.get(id_day, 0) + 1
                if id_sequence != expected_sequence:
                    raise _corrupt(
                        f"prediction id sequence is not contiguous: {prediction_id}"
                    )
                day_sequences[id_day] = id_sequence
                request_id = event["request_id"]
                if request_id in request_ids:
                    raise _corrupt(
                        "duplicate prediction request_id: "
                        f"{request_id} ({request_ids[request_id]}, {prediction_id})"
                    )
                request_ids[request_id] = prediction_id
                states[prediction_id] = _state_from_created(event)
                continue
            if event_type == "prediction_scored":
                prediction_id = event.get("id")
                try:
                    _prediction_id(prediction_id)
                except PredictionLedgerError as exc:
                    raise _corrupt(exc.message) from exc
                state = states.get(prediction_id)
                if state is None:
                    raise _corrupt(
                        f"prediction_scored precedes prediction_created: {prediction_id}"
                    )
                if state["status"] == "scored":
                    raise _corrupt(
                        f"duplicate prediction_scored event: {prediction_id}"
                    )
                try:
                    self._validate_scored_event(event, state)
                except PredictionLedgerError as exc:
                    if exc.code == "prediction_invalid_request":
                        raise _corrupt(exc.message) from exc
                    raise
                states[prediction_id] = _state_from_scored(state, event)
                continue
            raise _corrupt(f"unknown prediction event: {event_type!r}")
        return states

    @staticmethod
    def _parse_cursor(cursor: Optional[str]) -> Optional[tuple[str, str]]:
        if cursor is None:
            return None
        if not isinstance(cursor, str) or cursor.count("|") != 1:
            raise _invalid("cursor must be a reconcile cursor")
        horizon, prediction_id = cursor.split("|", 1)
        horizon = _strict_date(horizon, "cursor horizon")
        _prediction_id(prediction_id, "cursor prediction id")
        return horizon, prediction_id

    @staticmethod
    def _find_existing_request(
        states: list[dict[str, Any]],
        *,
        request_id: str,
        intent_sha256: str,
    ) -> Optional[dict[str, Any]]:
        for state in states:
            if state.get("request_id") != request_id:
                continue
            if state.get("intent_sha256") != intent_sha256:
                raise PredictionLedgerError(
                    "prediction_idempotency_conflict",
                    "request_id already belongs to a different prediction intent",
                )
            return state
        return None

    @staticmethod
    def _next_id(states: dict[str, dict[str, Any]], day: str) -> str:
        sequences = []
        for prediction_id in states:
            match = _ID_PATTERN.fullmatch(prediction_id)
            if match is not None and match.group(1) == day:
                sequences.append(int(match.group(2)))
        return f"{day}-{max(sequences, default=0) + 1:03d}"

    @staticmethod
    def _validate_created_event(event: dict[str, Any]) -> None:
        expected = {
            "schema_version",
            "event",
            "id",
            "revision",
            "request_id",
            "intent_sha256",
            "created_at",
            "subject_kind",
            "subject",
            "symbol",
            "direction",
            "confidence",
            "horizon_date",
            "flat_threshold_pct",
            "range_low",
            "range_high",
            "range_return_low",
            "range_return_high",
            "falsifier",
            "rationale",
            "market_timezone",
            "outcome_session_policy",
            "entry_price",
        }
        if set(event) != expected:
            raise _invalid("prediction_created fields do not match schema")
        if (
            event["schema_version"] != _SCHEMA_VERSION
            or event["event"] != "prediction_created"
            or type(event["revision"]) is not int
            or event["revision"] != 1
        ):
            raise _invalid("unsupported prediction_created schema or revision")
        if (
            not isinstance(event["request_id"], str)
            or _REQUEST_ID_PATTERN.fullmatch(event["request_id"]) is None
        ):
            raise _invalid("prediction request_id is invalid")
        if (
            not isinstance(event["intent_sha256"], str)
            or _HASH_PATTERN.fullmatch(event["intent_sha256"]) is None
        ):
            raise _invalid("prediction intent_sha256 must be a SHA-256 digest")
        created_at = _utc_timestamp(event["created_at"], "created_at")
        if event["created_at"] != created_at:
            raise _invalid("created_at must use canonical UTC Z encoding")
        id_day, _ = _prediction_id(event["id"])
        if id_day != created_at[:10]:
            raise _invalid("prediction id does not match its UTC creation date")
        if event["subject_kind"] != "us_equity":
            raise _invalid("subject_kind must be us_equity")

        normalized = _normalize_request(
            {
                "symbol": event["symbol"],
                "subject": event["subject"],
                "direction": event["direction"],
                "horizon_date": event["horizon_date"],
                "confidence": event["confidence"],
                "range_low": event["range_low"],
                "range_high": event["range_high"],
                "flat_threshold_pct": event["flat_threshold_pct"],
                "falsifier": event["falsifier"],
                "rationale": event["rationale"],
                "request_id": event["request_id"],
            }
        )
        for field in (
            "symbol",
            "subject",
            "direction",
            "horizon_date",
            "confidence",
            "range_low",
            "range_high",
            "flat_threshold_pct",
            "falsifier",
            "rationale",
            "request_id",
        ):
            if event[field] != normalized[field]:
                raise _invalid(f"prediction {field} is not canonical")
        if _intent_sha256(normalized) != event["intent_sha256"]:
            raise _invalid("prediction intent_sha256 does not match its fields")
        if event["market_timezone"] != _MARKET_TIMEZONE:
            raise _invalid("market_timezone must be America/New_York")
        if event["outcome_session_policy"] != (
            "first_observed_session_on_or_after_horizon"
        ):
            raise _invalid("unsupported outcome_session_policy")
        if not isinstance(event["entry_price"], dict):
            raise _invalid("entry_price must be an object")
        evidence = event["entry_price"]
        if set(evidence) != {
            "session_date",
            "close",
            "provider",
            "source",
            "interval",
            "adjustment",
            "fetched_at",
            "payload_sha256",
        }:
            raise _invalid("entry_price fields do not match schema")
        _strict_date(evidence["session_date"], "entry_price.session_date")
        entry_close = _finite_number(
            evidence["close"],
            "entry_price.close",
            positive=True,
        )
        entry_date = date.fromisoformat(evidence["session_date"])
        horizon_date = date.fromisoformat(normalized["horizon_date"])
        cutoff_date = date.fromisoformat(_completed_session_cutoff(created_at))
        if entry_date > cutoff_date:
            raise _invalid("entry session exceeds the completed-session cutoff")
        if (cutoff_date - entry_date).days > _MAX_ENTRY_STALENESS_DAYS:
            raise _invalid("entry session is too old for the creation timestamp")
        if horizon_date <= entry_date:
            raise _invalid("horizon_date must be after the entry session")
        if (horizon_date - entry_date).days > _MAX_HORIZON_DAYS:
            raise _invalid(
                f"horizon_date must be within {_MAX_HORIZON_DAYS} calendar days "
                "of the entry session"
            )
        expected_return_low = None
        expected_return_high = None
        if normalized["range_low"] is not None:
            expected_return_low = normalized["range_low"] / entry_close - 1.0
            expected_return_high = normalized["range_high"] / entry_close - 1.0
        for field, expected_value in (
            ("range_return_low", expected_return_low),
            ("range_return_high", expected_return_high),
        ):
            actual_value = event[field]
            if expected_value is None:
                if actual_value is not None:
                    raise _invalid(f"{field} must be null without a target range")
            else:
                actual_number = _finite_number(actual_value, field)
                if not math.isclose(
                    actual_number,
                    expected_value,
                    rel_tol=1e-12,
                    abs_tol=1e-12,
                ):
                    raise _invalid(f"{field} does not match the entry price")
        if (
            evidence["provider"] != "futu"
            or evidence["source"] != "futu"
            or evidence["interval"] != "1d"
            or evidence["adjustment"] != "qfq"
        ):
            raise _invalid("entry_price provenance must be futu/qfq/1d")
        fetched_at = _utc_timestamp(
            evidence["fetched_at"],
            "entry_price.fetched_at",
        )
        if evidence["fetched_at"] != fetched_at:
            raise _invalid("entry_price.fetched_at must use canonical UTC Z encoding")
        if (
            not isinstance(evidence["payload_sha256"], str)
            or _HASH_PATTERN.fullmatch(evidence["payload_sha256"]) is None
        ):
            raise _invalid("entry_price.payload_sha256 must be a SHA-256 digest")

    @staticmethod
    def _validate_scored_event(
        event: dict[str, Any],
        state: dict[str, Any],
    ) -> None:
        expected = {
            "schema_version",
            "event",
            "id",
            "revision",
            "score_id",
            "scored_at",
            "scoring_entry_close",
            "outcome_session_date",
            "outcome_close",
            "outcome_return",
            "outcome_direction",
            "direction_correct",
            "direction_brier",
            "range_hit",
            "price_evidence",
        }
        if set(event) != expected:
            raise _invalid("prediction_scored fields do not match schema")
        if (
            event["schema_version"] != _SCHEMA_VERSION
            or event["event"] != "prediction_scored"
            or type(event["revision"]) is not int
            or event["revision"] != 2
            or event["id"] != state["id"]
        ):
            raise _invalid("unsupported prediction_scored schema or revision")
        _prediction_id(event["id"])
        scored_at = _utc_timestamp(event["scored_at"], "scored_at")
        if event["scored_at"] != scored_at:
            raise _invalid("scored_at must use canonical UTC Z encoding")
        if scored_at <= state["created_at"]:
            raise _invalid("scored_at must be after created_at")
        outcome_date = _strict_date(
            event["outcome_session_date"],
            "outcome_session_date",
        )
        if outcome_date < state["horizon_date"]:
            raise _invalid("outcome session precedes horizon_date")
        if outcome_date > _completed_session_cutoff(scored_at):
            raise _invalid(
                "outcome session exceeds the scored_at completed-session cutoff"
            )
        resolution_end = (
            date.fromisoformat(state["horizon_date"])
            + timedelta(days=_MAX_OUTCOME_RESOLUTION_DAYS)
        ).isoformat()
        if outcome_date > resolution_end:
            raise _invalid("outcome session exceeds the resolution window")
        scoring_entry = _finite_number(
            event["scoring_entry_close"],
            "scoring_entry_close",
            positive=True,
        )
        outcome_close = _finite_number(
            event["outcome_close"],
            "outcome_close",
            positive=True,
        )
        outcome_return = _finite_number(event["outcome_return"], "outcome_return")
        expected_return = outcome_close / scoring_entry - 1.0
        if not math.isclose(
            outcome_return, expected_return, rel_tol=1e-12, abs_tol=1e-12
        ):
            raise _invalid("outcome_return does not match scoring prices")
        expected_direction = _outcome_direction(
            outcome_return,
            state["flat_threshold_pct"],
        )
        if event["outcome_direction"] != expected_direction:
            raise _invalid("outcome_direction does not match outcome_return")
        if type(event["direction_correct"]) is not bool:
            raise _invalid("direction_correct must be boolean")
        expected_correct = expected_direction == state["direction"]
        if event["direction_correct"] is not expected_correct:
            raise _invalid("direction_correct does not match the forecast")
        brier = _finite_number(event["direction_brier"], "direction_brier")
        expected_brier = (state["confidence"] - int(expected_correct)) ** 2
        if not math.isclose(brier, expected_brier, rel_tol=1e-12, abs_tol=1e-12):
            raise _invalid("direction_brier does not match the forecast")
        expected_range_hit = None
        if state["range_return_low"] is not None:
            expected_range_hit = (
                state["range_return_low"]
                <= outcome_return
                <= state["range_return_high"]
            )
        if event["range_hit"] is not expected_range_hit:
            raise _invalid("range_hit does not match the forecast range")
        expected_score_id = f"{state['id']}@{outcome_date}:futu:qfq"
        if event["score_id"] != expected_score_id:
            raise _invalid("score_id does not match scoring evidence")
        evidence = event["price_evidence"]
        if not isinstance(evidence, dict) or set(evidence) != {
            "provider",
            "source",
            "interval",
            "adjustment",
            "fetched_at",
            "payload_sha256",
            "start",
            "end",
        }:
            raise _invalid("price_evidence fields do not match schema")
        if (
            evidence["provider"] != "futu"
            or evidence["source"] != "futu"
            or evidence["interval"] != "1d"
            or evidence["adjustment"] != "qfq"
        ):
            raise _invalid("price_evidence provenance must be futu/qfq/1d")
        fetched_at = _utc_timestamp(
            evidence["fetched_at"],
            "price_evidence.fetched_at",
        )
        if evidence["fetched_at"] != fetched_at:
            raise _invalid(
                "price_evidence.fetched_at must use canonical UTC Z encoding"
            )
        if (
            not isinstance(evidence["payload_sha256"], str)
            or _HASH_PATTERN.fullmatch(evidence["payload_sha256"]) is None
        ):
            raise _invalid("price_evidence.payload_sha256 must be a SHA-256 digest")
        if (
            _strict_date(evidence["start"], "price_evidence.start")
            != (state["entry_price"]["session_date"])
        ):
            raise _invalid("price_evidence.start must be the entry session")
        evidence_end = _strict_date(evidence["end"], "price_evidence.end")
        if evidence_end < outcome_date:
            raise _invalid("price_evidence.end precedes the outcome session")
        expected_end = min(
            _completed_session_cutoff(scored_at),
            resolution_end,
        )
        if evidence_end != expected_end:
            raise _invalid(
                "price_evidence.end does not match the completed resolution window"
            )

    def _append_event(self, fd: int, event: dict[str, Any]) -> None:
        try:
            line = (
                json.dumps(
                    event,
                    ensure_ascii=False,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
            payload = line.encode("utf-8", errors="strict")
        except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
            raise _invalid(f"prediction event is not serializable: {exc}") from exc
        original_size = os.lseek(fd, 0, os.SEEK_END)
        try:
            offset = 0
            while offset < len(payload):
                written = os.write(fd, payload[offset:])
                if written <= 0:
                    raise OSError("prediction ledger append made no progress")
                offset += written
        except OSError as write_error:
            try:
                os.ftruncate(fd, original_size)
                os.fsync(fd)
                if original_size == 0:
                    try:
                        os.unlink(self.entries_path)
                    except FileNotFoundError:
                        pass
                    self._fsync_directory(self.prediction_dir)
            except OSError as rollback_error:
                raise PredictionLedgerError(
                    "prediction_durability_unknown",
                    "prediction append failed and rollback could not be confirmed",
                    retryable=False,
                ) from rollback_error
            raise write_error
        try:
            os.fsync(fd)
            self._fsync_directory(self.prediction_dir)
        except OSError as exc:
            raise PredictionLedgerError(
                "prediction_durability_unknown",
                "prediction event was appended but fsync failed",
                retryable=False,
            ) from exc

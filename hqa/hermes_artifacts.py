from __future__ import annotations

import json
import math
import os
import tempfile
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable

from hqa.market_foresight import MarketForesightPublisher
from hqa.predictions import PredictionLedger


_SCHEMA_VERSION = "1.0"
_KINDS = ("portfolio_risk", "prediction", "market_foresight")
_KIND_PRIORITY = {kind: index for index, kind in enumerate(_KINDS)}
_RISK_STATUSES = {"available", "degraded", "not_applicable", "unavailable"}
_RISK_STATES = {"account_missing", "cash_only", "invested", "unknown"}
_RISK_BASE_FIELDS = {
    "schema_version",
    "ts",
    "job",
    "status",
    "portfolio_state",
    "reason_codes",
    "account",
    "exposure",
    "concentration",
    "price_quality",
    "positions",
    "policy_evaluation",
    "limitations",
    "error",
}
_BETA_FIELDS = {
    "aligned_return_count",
    "benchmark",
    "first_return_date",
    "last_return_date",
    "reason",
    "status",
    "symbol",
    "value",
}
_ITEM_FIELDS = {"id", "kind", "occurred_at", "quality", "status", "data"}
_SOURCE_FIELDS = {"kind", "status", "latest_at", "reason_code"}
_SOURCE_STATUSES = {"available", "empty", "degraded", "unavailable"}
_RISK_DATA_FIELDS = {
    "account_id",
    "currency",
    "gross_value",
    "gross_pct_equity",
    "largest_symbol",
    "top1_gross_pct",
    "historical_status",
    "benchmark",
    "betas",
    "reason_codes",
    "limitations",
}
_PREDICTION_DATA_FIELDS = {
    "prediction_id",
    "state",
    "symbol",
    "direction",
    "confidence",
    "horizon_date",
    "rationale",
    "outcome_return",
    "direction_brier",
}
_FORESIGHT_DATA_FIELDS = {"run_id", "summary", "candidate_count", "candidates"}
_CANDIDATE_FIELDS = {
    "id",
    "symbol",
    "direction",
    "confidence",
    "horizon_date",
    "falsifier",
    "rationale",
    "entry_session_date",
    "entry_close",
    "provider",
    "adjustment",
    "proposal_only",
    "requires_human_confirmation",
    "trading_allowed",
}


class HermesArtifactFeedError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _utc_timestamp(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a timezone-aware timestamp")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be a timezone-aware timestamp")
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _strict_json(text: str) -> Any:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number is not allowed: {value}")

    def object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(
        text,
        parse_constant=reject_constant,
        object_pairs_hook=object_without_duplicates,
    )


def _validate_tree(root: Any) -> None:
    stack = [root]
    while stack:
        value = stack.pop()
        if isinstance(value, str):
            value.encode("utf-8", errors="strict")
        elif isinstance(value, float) and not math.isfinite(value):
            raise ValueError("artifact contains a non-finite number")
        elif isinstance(value, dict):
            stack.extend(value.keys())
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)


def _validate_beta(beta: Any, *, benchmark: str) -> None:
    if not isinstance(beta, dict) or set(beta) != _BETA_FIELDS:
        raise ValueError("portfolio historical beta fields are invalid")
    _validate_string(beta["symbol"], "portfolio beta symbol", max_length=16)
    _validate_string(beta["benchmark"], "portfolio beta benchmark", max_length=16)
    _validate_string(beta["status"], "portfolio beta status", max_length=64)
    _validate_string(
        beta["reason"],
        "portfolio beta reason",
        max_length=500,
        allow_none=True,
    )
    if (
        beta["benchmark"] != benchmark
        or beta["status"] not in {"available", "unavailable"}
        or isinstance(beta["aligned_return_count"], bool)
        or not isinstance(beta["aligned_return_count"], int)
        or beta["aligned_return_count"] < 0
    ):
        raise ValueError("portfolio historical beta identity is invalid")
    for field in ("first_return_date", "last_return_date"):
        value = beta[field]
        if value is not None:
            if not isinstance(value, str):
                raise ValueError("portfolio historical beta date is invalid")
            try:
                parsed_date = date.fromisoformat(value)
            except ValueError as exc:
                raise ValueError("portfolio historical beta date is invalid") from exc
            if parsed_date.isoformat() != value:
                raise ValueError("portfolio historical beta date is invalid")
    if (beta["first_return_date"] is None) != (beta["last_return_date"] is None):
        raise ValueError("portfolio historical beta range is invalid")
    value = beta["value"]
    if value is not None and (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        raise ValueError("portfolio historical beta value is invalid")
    reason = beta["reason"]
    if beta["status"] == "available" and (value is None or reason is not None):
        raise ValueError("available portfolio beta is incomplete")
    if beta["status"] == "unavailable" and (value is not None or reason is None):
        raise ValueError("unavailable portfolio beta is inconsistent")


def _validate_date_text(value: Any, field: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a canonical date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be a canonical date") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"{field} must be a canonical date")


def _validate_finite_number(
    value: Any,
    field: str,
    *,
    allow_none: bool = False,
) -> None:
    if allow_none and value is None:
        return
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        raise ValueError(f"{field} must be finite")


def _validate_string(
    value: Any,
    field: str,
    *,
    max_length: int,
    allow_none: bool = False,
    allow_empty: bool = False,
) -> None:
    if allow_none and value is None:
        return
    if (
        not isinstance(value, str)
        or (not allow_empty and not value)
        or len(value) > max_length
    ):
        raise ValueError(f"{field} is invalid")


def _source(kind: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "kind": kind,
        "status": "available" if items else "empty",
        "latest_at": max((item["occurred_at"] for item in items), default=None),
        "reason_code": None,
    }


class HermesArtifactFeed:
    def __init__(
        self,
        feed_path: Path,
        *,
        portfolio_risk_path: Path,
        prediction_ledger: PredictionLedger,
        foresight_publisher: MarketForesightPublisher,
        now: Callable[[], str],
    ) -> None:
        self.feed_path = Path(feed_path)
        self.portfolio_risk_path = Path(portfolio_risk_path)
        self._prediction_ledger = prediction_ledger
        self._foresight_publisher = foresight_publisher
        self._now = now

    def rebuild(self, *, limit: int = 50) -> dict[str, Any]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise HermesArtifactFeedError(
                "hermes_artifact_invalid_request",
                "limit must be an integer in [1, 200]",
            )
        items: list[dict[str, Any]] = []
        sources: list[dict[str, Any]] = []
        warnings: list[dict[str, str]] = []
        collectors = (
            ("portfolio_risk", self._portfolio_risk_items),
            ("prediction", self._prediction_items),
            ("market_foresight", self._foresight_items),
        )
        for kind, collect in collectors:
            try:
                source_items = collect()
            except Exception:
                sources.append(
                    {
                        "kind": kind,
                        "status": "degraded",
                        "latest_at": None,
                        "reason_code": f"{kind}_source_corrupt",
                    }
                )
                warnings.append(
                    {"source": kind, "code": f"{kind}_source_corrupt"}
                )
                continue
            items.extend(source_items)
            sources.append(_source(kind, source_items))

        items.sort(
            key=lambda item: (
                item["occurred_at"],
                _KIND_PRIORITY[item["kind"]],
                item["id"],
            ),
            reverse=True,
        )
        items = items[:limit]
        read_status = "degraded" if warnings else ("available" if items else "empty")
        manifest = {
            "schema_version": _SCHEMA_VERSION,
            "read_status": read_status,
            "as_of": _utc_timestamp(self._now(), "as_of"),
            "items": items,
            "sources": sources,
            "warnings": warnings,
        }
        self._validate_manifest(manifest)
        self._write_atomic(manifest)
        return manifest

    def read(self) -> dict[str, Any]:
        if not self.feed_path.exists():
            return {
                "schema_version": _SCHEMA_VERSION,
                "read_status": "empty",
                "as_of": _utc_timestamp(self._now(), "as_of"),
                "items": [],
                "sources": [_source(kind, []) for kind in _KINDS],
                "warnings": [],
            }
        try:
            manifest = _strict_json(self.feed_path.read_text(encoding="utf-8"))
            self._validate_manifest(manifest)
            return manifest
        except Exception as exc:
            raise HermesArtifactFeedError(
                "hermes_artifact_feed_corrupt",
                "Hermes artifact feed is unreadable or unsupported",
            ) from exc

    def _portfolio_risk_items(self) -> list[dict[str, Any]]:
        if not self.portfolio_risk_path.exists():
            return []
        rows = []
        for line in self.portfolio_risk_path.read_text(encoding="utf-8").splitlines():
            if not line:
                raise ValueError("portfolio risk artifact contains a blank line")
            row = _strict_json(line)
            _validate_tree(row)
            if not isinstance(row, dict) or row.get("job") != "portfolio-risk":
                raise ValueError("portfolio risk artifact contract is invalid")
            row["ts"] = _utc_timestamp(row.get("ts"), "portfolio_risk.ts")
            self._validate_portfolio_risk(row)
            rows.append(row)
        if not rows:
            raise ValueError("portfolio risk artifact is empty")
        latest = max(rows, key=lambda row: row["ts"])
        canonical = json.dumps(latest, allow_nan=False, sort_keys=True, separators=(",", ":"))
        exposure = latest.get("exposure") or {}
        concentration = latest.get("concentration") or {}
        historical = latest.get("historical_risk") or {}
        account = latest.get("account") or {}
        data = {
            "account_id": account.get("account_id"),
            "currency": exposure.get("currency") or account.get("base_currency"),
            "gross_value": exposure.get("gross_value"),
            "gross_pct_equity": exposure.get("gross_pct_equity"),
            "largest_symbol": concentration.get("largest_symbol"),
            "top1_gross_pct": concentration.get("top1_gross_pct"),
            "historical_status": historical.get("status"),
            "benchmark": historical.get("benchmark"),
            "betas": [
                {field: beta[field] for field in sorted(_BETA_FIELDS)}
                for beta in historical.get("betas", [])
            ],
            "reason_codes": latest.get("reason_codes", []),
            "limitations": latest.get("limitations", []),
        }
        item = {
            "id": f"portfolio-risk:{sha256(canonical.encode('utf-8')).hexdigest()[:24]}",
            "kind": "portfolio_risk",
            "occurred_at": latest["ts"],
            "quality": self._quality(latest.get("status")),
            "status": str(latest.get("status", "unavailable")),
            "data": data,
        }
        self._validate_item_data(item)
        return [item]

    def _prediction_items(self) -> list[dict[str, Any]]:
        items = []
        for state in self._prediction_ledger.list():
            occurred_at = _utc_timestamp(
                state.get("scored_at") or state.get("created_at"),
                "prediction.occurred_at",
            )
            item = {
                "id": f"prediction:{state['id']}",
                "kind": "prediction",
                "occurred_at": occurred_at,
                "quality": "available",
                "status": state["status"],
                "data": {
                    "prediction_id": state["id"],
                    "state": state["status"],
                    "symbol": state["symbol"],
                    "direction": state["direction"],
                    "confidence": state["confidence"],
                    "horizon_date": state["horizon_date"],
                    "rationale": state.get("rationale", ""),
                    "outcome_return": state.get("outcome_return"),
                    "direction_brier": state.get("direction_brier"),
                },
            }
            self._validate_item_data(item)
            items.append(item)
        return items

    def _foresight_items(self) -> list[dict[str, Any]]:
        items = []
        for artifact in self._foresight_publisher.list():
            occurred_at = _utc_timestamp(
                artifact.get("occurred_at"), "market_foresight.occurred_at"
            )
            intent = artifact["intent"]
            entry = artifact["evidence"]["entry_price"]
            candidate = {
                "id": artifact["id"],
                "symbol": intent["symbol"],
                "direction": intent["direction"],
                "confidence": intent["confidence"],
                "horizon_date": intent["horizon_date"],
                "falsifier": intent["falsifier"],
                "rationale": intent.get("rationale", ""),
                "entry_session_date": entry["session_date"],
                "entry_close": entry["close"],
                "provider": entry["provider"],
                "adjustment": entry["adjustment"],
                "proposal_only": True,
                "requires_human_confirmation": True,
                "trading_allowed": False,
            }
            item = {
                "id": artifact["id"],
                "kind": "market_foresight",
                "occurred_at": occurred_at,
                "quality": "available",
                "status": artifact["status"],
                "data": {
                    "run_id": artifact["request_id"],
                    "summary": (
                        f"{intent['symbol']} {intent['direction']} through "
                        f"{intent['horizon_date']}"
                    ),
                    "candidate_count": 1,
                    "candidates": [candidate],
                },
            }
            self._validate_item_data(item)
            items.append(item)
        return items

    @staticmethod
    def _quality(status: Any) -> str:
        return str(status) if status in _RISK_STATUSES else "unavailable"

    @staticmethod
    def _validate_portfolio_risk(row: dict[str, Any]) -> None:
        schema_version = row.get("schema_version")
        expected_fields = (
            _RISK_BASE_FIELDS
            if schema_version == "1.0"
            else _RISK_BASE_FIELDS | {"history_source", "historical_risk"}
        )
        if schema_version not in {"1.0", "2.0"} or set(row) != expected_fields:
            raise ValueError("portfolio risk fields do not match schema")
        if row["status"] not in _RISK_STATUSES:
            raise ValueError("portfolio risk status is invalid")
        if row["portfolio_state"] not in _RISK_STATES:
            raise ValueError("portfolio risk state is invalid")
        for field in ("reason_codes", "limitations"):
            values = row[field]
            if not isinstance(values, list) or any(
                not isinstance(value, str) for value in values
            ):
                raise ValueError(f"portfolio risk {field} must be a string list")
            if len(values) > 100:
                raise ValueError(f"portfolio risk {field} is too large")
            max_length = 200 if field == "reason_codes" else 500
            for value in values:
                _validate_string(
                    value,
                    f"portfolio risk {field}",
                    max_length=max_length,
                )
        if not isinstance(row["positions"], list):
            raise ValueError("portfolio risk positions must be a list")
        if not isinstance(row["policy_evaluation"], dict):
            raise ValueError("portfolio risk policy_evaluation must be an object")
        if row["error"] is not None and not isinstance(row["error"], dict):
            raise ValueError("portfolio risk error must be an object or null")
        account = row["account"]
        if (
            not isinstance(account, dict)
            or not isinstance(account.get("account_id"), str)
            or not account["account_id"]
            or "base_currency" not in account
            or (
                account["base_currency"] is not None
                and not isinstance(account["base_currency"], str)
            )
        ):
            raise ValueError("portfolio risk account is invalid")
        _validate_string(
            account["account_id"],
            "portfolio risk account_id",
            max_length=128,
        )
        _validate_string(
            account["base_currency"],
            "portfolio risk base_currency",
            max_length=16,
            allow_none=True,
        )
        if row["status"] in {"available", "degraded"}:
            if not all(
                isinstance(row[field], dict)
                for field in ("exposure", "concentration", "price_quality")
            ):
                raise ValueError("available portfolio risk requires derived facts")
        exposure = row["exposure"]
        if exposure is not None:
            if not isinstance(exposure, dict) or not {
                "currency",
                "gross_value",
                "gross_pct_equity",
            }.issubset(exposure):
                raise ValueError("portfolio risk exposure is invalid")
            if not isinstance(exposure["currency"], str) or not exposure["currency"]:
                raise ValueError("portfolio risk currency is invalid")
            _validate_string(
                exposure["currency"],
                "portfolio risk currency",
                max_length=16,
            )
            for field in ("gross_value", "gross_pct_equity"):
                value = exposure[field]
                if value is not None and (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                ):
                    raise ValueError(f"portfolio risk exposure {field} is invalid")
        concentration = row["concentration"]
        if concentration is not None:
            if not isinstance(concentration, dict) or not {
                "largest_symbol",
                "top1_gross_pct",
            }.issubset(concentration):
                raise ValueError("portfolio risk concentration is invalid")
            largest = concentration["largest_symbol"]
            if largest is not None and not isinstance(largest, str):
                raise ValueError("portfolio risk largest_symbol is invalid")
            _validate_string(
                largest,
                "portfolio risk largest_symbol",
                max_length=16,
                allow_none=True,
            )
            top1 = concentration["top1_gross_pct"]
            if top1 is not None and (
                isinstance(top1, bool)
                or not isinstance(top1, (int, float))
                or not math.isfinite(float(top1))
            ):
                raise ValueError("portfolio risk top1_gross_pct is invalid")
        if schema_version == "2.0":
            history_source = row["history_source"]
            historical = row["historical_risk"]
            if (
                not isinstance(history_source, dict)
                or history_source.get("status") not in _RISK_STATUSES
                or not isinstance(historical, dict)
                or historical.get("status") not in _RISK_STATUSES
                or not isinstance(historical.get("benchmark"), str)
                or not historical["benchmark"]
                or not isinstance(historical.get("betas"), list)
            ):
                raise ValueError("portfolio historical risk is invalid")
            _validate_string(
                historical["benchmark"],
                "portfolio historical benchmark",
                max_length=16,
            )
            if len(historical["betas"]) > 100:
                raise ValueError("portfolio historical betas are too large")
            for beta in historical["betas"]:
                _validate_beta(beta, benchmark=historical["benchmark"])

    def _write_atomic(self, manifest: dict[str, Any]) -> None:
        serialized = json.dumps(
            manifest,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        serialized.encode("utf-8", errors="strict")
        self.feed_path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.feed_path.parent,
                prefix=f".{self.feed_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(serialized + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            assert temporary is not None
            os.replace(temporary, self.feed_path)
            directory_fd = os.open(self.feed_path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if temporary is not None:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass

    @staticmethod
    def _validate_manifest(manifest: Any) -> None:
        _validate_tree(manifest)
        if not isinstance(manifest, dict) or set(manifest) != {
            "schema_version",
            "read_status",
            "as_of",
            "items",
            "sources",
            "warnings",
        }:
            raise ValueError("Hermes artifact manifest fields do not match schema")
        if manifest["schema_version"] != _SCHEMA_VERSION:
            raise ValueError("unsupported Hermes artifact manifest schema")
        if manifest["read_status"] not in {"empty", "available", "degraded"}:
            raise ValueError("Hermes artifact read_status is invalid")
        _utc_timestamp(manifest["as_of"], "as_of")
        if not isinstance(manifest["items"], list) or len(manifest["items"]) > 200:
            raise ValueError("Hermes artifact items must be a list")
        item_ids: set[str] = set()
        item_kinds: set[str] = set()
        for item in manifest["items"]:
            if not isinstance(item, dict) or set(item) != _ITEM_FIELDS:
                raise ValueError("Hermes artifact item fields do not match schema")
            if item["kind"] not in _KINDS:
                raise ValueError("unsupported Hermes artifact kind")
            if (
                not isinstance(item["id"], str)
                or not item["id"]
                or item["id"] in item_ids
                or not isinstance(item["status"], str)
                or not item["status"]
                or item["quality"] not in _RISK_STATUSES
            ):
                raise ValueError("Hermes artifact item identity is invalid")
            _validate_string(item["id"], "artifact id", max_length=256)
            _validate_string(item["status"], "artifact status", max_length=64)
            item_ids.add(item["id"])
            item_kinds.add(item["kind"])
            _utc_timestamp(item["occurred_at"], "item.occurred_at")
            HermesArtifactFeed._validate_item_data(item)

        if not isinstance(manifest["sources"], list) or len(manifest["sources"]) != 3:
            raise ValueError("Hermes artifact sources must report every kind")
        source_kinds: set[str] = set()
        source_statuses: dict[str, str] = {}
        failed_sources: set[str] = set()
        for source in manifest["sources"]:
            if not isinstance(source, dict) or set(source) != _SOURCE_FIELDS:
                raise ValueError("Hermes artifact source fields do not match schema")
            kind = source["kind"]
            status = source["status"]
            latest_at = source["latest_at"]
            reason_code = source["reason_code"]
            if kind not in _KINDS or kind in source_kinds or status not in _SOURCE_STATUSES:
                raise ValueError("Hermes artifact source identity is invalid")
            source_kinds.add(kind)
            source_statuses[kind] = status
            if status == "available":
                if latest_at is None or reason_code is not None:
                    raise ValueError("available artifact source is inconsistent")
                _utc_timestamp(latest_at, "source.latest_at")
            elif status == "empty":
                if latest_at is not None or reason_code is not None or kind in item_kinds:
                    raise ValueError("empty artifact source is inconsistent")
            else:
                if latest_at is not None or not isinstance(reason_code, str) or not reason_code:
                    raise ValueError("failed artifact source is inconsistent")
                failed_sources.add(kind)
        if source_kinds != set(_KINDS):
            raise ValueError("Hermes artifact sources must report every kind")
        if any(source_statuses[kind] != "available" for kind in item_kinds):
            raise ValueError("artifact item belongs to a non-available source")

        if not isinstance(manifest["warnings"], list):
            raise ValueError("Hermes artifact warnings must be a list")
        warning_pairs: set[tuple[str, str]] = set()
        warning_sources: set[str] = set()
        for warning in manifest["warnings"]:
            if not isinstance(warning, dict) or set(warning) != {"source", "code"}:
                raise ValueError("Hermes artifact warning fields do not match schema")
            source = warning["source"]
            code = warning["code"]
            if (
                source not in _KINDS
                or not isinstance(code, str)
                or not code
                or (source, code) in warning_pairs
            ):
                raise ValueError("Hermes artifact warning is invalid")
            warning_pairs.add((source, code))
            warning_sources.add(source)
        if warning_sources != failed_sources:
            raise ValueError("Hermes artifact warnings do not match failed sources")

        expected_status = (
            "degraded"
            if failed_sources
            else ("available" if manifest["items"] else "empty")
        )
        if manifest["read_status"] != expected_status:
            raise ValueError("Hermes artifact aggregate status is inconsistent")

    @staticmethod
    def _validate_item_data(item: dict[str, Any]) -> None:
        data = item["data"]
        if not isinstance(data, dict):
            raise ValueError("Hermes artifact data must be an object")
        if item["kind"] == "portfolio_risk":
            if set(data) != _RISK_DATA_FIELDS:
                raise ValueError("portfolio-risk projection fields are invalid")
            for field in (
                "account_id",
                "currency",
                "largest_symbol",
                "historical_status",
                "benchmark",
            ):
                if data[field] is not None and not isinstance(data[field], str):
                    raise ValueError(f"portfolio-risk {field} is invalid")
            for field, max_length in (
                ("account_id", 128),
                ("currency", 16),
                ("largest_symbol", 16),
                ("historical_status", 64),
                ("benchmark", 16),
            ):
                _validate_string(
                    data[field],
                    f"portfolio-risk {field}",
                    max_length=max_length,
                    allow_none=True,
                )
            for field in ("gross_value", "gross_pct_equity", "top1_gross_pct"):
                _validate_finite_number(
                    data[field],
                    f"portfolio-risk {field}",
                    allow_none=True,
                )
            if data["gross_value"] is not None and data["gross_value"] < 0:
                raise ValueError("portfolio-risk gross_value is invalid")
            if data["gross_pct_equity"] is not None and data["gross_pct_equity"] < 0:
                raise ValueError("portfolio-risk gross_pct_equity is invalid")
            if data["top1_gross_pct"] is not None and not 0 <= data["top1_gross_pct"] <= 1:
                raise ValueError("portfolio-risk top1_gross_pct is invalid")
            for field in ("reason_codes", "limitations"):
                if not isinstance(data[field], list) or any(
                    not isinstance(value, str) for value in data[field]
                ):
                    raise ValueError(f"portfolio-risk {field} is invalid")
                if len(data[field]) > 100:
                    raise ValueError(f"portfolio-risk {field} is too large")
                max_length = 200 if field == "reason_codes" else 500
                for value in data[field]:
                    _validate_string(
                        value,
                        f"portfolio-risk {field}",
                        max_length=max_length,
                    )
            if not isinstance(data["betas"], list) or len(data["betas"]) > 100:
                raise ValueError("portfolio-risk betas are invalid")
            if data["betas"] and not data["benchmark"]:
                raise ValueError("portfolio-risk betas require a benchmark")
            for beta in data["betas"]:
                _validate_beta(beta, benchmark=data["benchmark"])
            return

        if item["kind"] == "prediction":
            if set(data) != _PREDICTION_DATA_FIELDS:
                raise ValueError("prediction projection fields are invalid")
            for field in ("prediction_id", "state", "symbol", "direction", "horizon_date"):
                if not isinstance(data[field], str) or not data[field]:
                    raise ValueError(f"prediction {field} is invalid")
            for field, max_length in (
                ("prediction_id", 128),
                ("state", 64),
                ("symbol", 16),
                ("direction", 16),
                ("horizon_date", 10),
            ):
                _validate_string(
                    data[field],
                    f"prediction {field}",
                    max_length=max_length,
                )
            if data["direction"] not in {"up", "down", "flat"}:
                raise ValueError("prediction direction is invalid")
            _validate_string(
                data["rationale"],
                "prediction rationale",
                max_length=4000,
                allow_empty=True,
            )
            _validate_date_text(data["horizon_date"], "prediction.horizon_date")
            _validate_finite_number(data["confidence"], "prediction.confidence")
            if not 0 <= data["confidence"] <= 1:
                raise ValueError("prediction confidence is invalid")
            _validate_finite_number(
                data["outcome_return"],
                "prediction.outcome_return",
                allow_none=True,
            )
            _validate_finite_number(
                data["direction_brier"],
                "prediction.direction_brier",
                allow_none=True,
            )
            if data["direction_brier"] is not None and not 0 <= data["direction_brier"] <= 1:
                raise ValueError("prediction direction_brier is invalid")
            return

        if set(data) != _FORESIGHT_DATA_FIELDS:
            raise ValueError("market-foresight projection fields are invalid")
        if (
            not isinstance(data["run_id"], str)
            or not data["run_id"]
            or not isinstance(data["summary"], str)
            or not data["summary"]
            or isinstance(data["candidate_count"], bool)
            or not isinstance(data["candidate_count"], int)
            or not isinstance(data["candidates"], list)
            or data["candidate_count"] != len(data["candidates"])
            or not 0 <= data["candidate_count"] <= 100
        ):
            raise ValueError("market-foresight projection is invalid")
        _validate_string(data["run_id"], "market-foresight run_id", max_length=256)
        _validate_string(data["summary"], "market-foresight summary", max_length=1000)
        for candidate in data["candidates"]:
            if not isinstance(candidate, dict) or set(candidate) != _CANDIDATE_FIELDS:
                raise ValueError("market-foresight candidate fields are invalid")
            for field in (
                "id",
                "symbol",
                "direction",
                "horizon_date",
                "falsifier",
                "rationale",
                "entry_session_date",
                "provider",
                "adjustment",
            ):
                if not isinstance(candidate[field], str):
                    raise ValueError(f"market-foresight candidate {field} is invalid")
            for field, max_length, allow_empty in (
                ("id", 256, False),
                ("symbol", 16, False),
                ("direction", 16, False),
                ("horizon_date", 10, False),
                ("falsifier", 2000, False),
                ("rationale", 4000, True),
                ("entry_session_date", 10, False),
                ("provider", 16, False),
                ("adjustment", 16, False),
            ):
                _validate_string(
                    candidate[field],
                    f"market-foresight candidate {field}",
                    max_length=max_length,
                    allow_empty=allow_empty,
                )
            if (
                not candidate["id"]
                or not candidate["symbol"]
                or candidate["direction"] not in {"up", "down", "flat"}
                or not candidate["horizon_date"]
                or not candidate["falsifier"]
                or not candidate["entry_session_date"]
                or candidate["provider"] != "futu"
                or candidate["adjustment"] != "qfq"
                or candidate["proposal_only"] is not True
                or candidate["requires_human_confirmation"] is not True
                or candidate["trading_allowed"] is not False
            ):
                raise ValueError("market-foresight candidate is invalid")
            _validate_date_text(
                candidate["horizon_date"],
                "market_foresight.horizon_date",
            )
            _validate_date_text(
                candidate["entry_session_date"],
                "market_foresight.entry_session_date",
            )
            _validate_finite_number(
                candidate["confidence"],
                "market_foresight.confidence",
            )
            _validate_finite_number(
                candidate["entry_close"],
                "market_foresight.entry_close",
            )
            if not 0 <= candidate["confidence"] <= 1 or candidate["entry_close"] <= 0:
                raise ValueError("market-foresight candidate numeric field is invalid")

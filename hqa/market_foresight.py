from __future__ import annotations

import json
import math
import os
import re
import tempfile
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from hqa.predictions import PredictionLedger, PredictionLedgerError


_SCHEMA_VERSION = "1.0"
_HASH_PATTERN = re.compile(r"[0-9a-f]{64}")
_ID_PATTERN = re.compile(r"mfp_[0-9a-f]{24}")
_ARTIFACT_FIELDS = {
    "schema_version",
    "id",
    "kind",
    "occurred_at",
    "status",
    "request_id",
    "intent_sha256",
    "intent",
    "evidence",
    "proposal_only",
    "requires_human_confirmation",
    "trading_allowed",
}


class MarketForesightError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


def _canonical_json(document: dict[str, Any]) -> str:
    serialized = json.dumps(
        document,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    serialized.encode("utf-8", errors="strict")
    return serialized


def _canonical_utc_timestamp(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a canonical UTC timestamp")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    canonical = parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if canonical != value:
        raise ValueError(f"{field} must use canonical UTC Z encoding")
    return canonical


def _strict_json(text: str) -> Any:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number is not allowed: {value}")

    def object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        document: dict[str, Any] = {}
        for key, value in pairs:
            if key in document:
                raise ValueError(f"duplicate JSON key: {key}")
            document[key] = value
        return document

    return json.loads(
        text,
        parse_constant=reject_constant,
        object_pairs_hook=object_without_duplicates,
    )


def _from_prediction_error(exc: PredictionLedgerError) -> MarketForesightError:
    if exc.code == "prediction_invalid_request":
        code = "market_foresight_invalid_request"
    elif exc.code == "prediction_entry_price_unavailable":
        code = "market_foresight_evidence_unavailable"
    elif exc.code == "prediction_history_contract_invalid":
        code = "market_foresight_evidence_invalid"
    else:
        code = "market_foresight_validation_failed"
    return MarketForesightError(code, exc.message, retryable=exc.retryable)


class MarketForesightPublisher:
    def __init__(
        self,
        foresight_dir: Path,
        *,
        prediction_ledger: PredictionLedger,
    ) -> None:
        self.foresight_dir = Path(foresight_dir)
        self._prediction_ledger = prediction_ledger

    def publish(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            preview = self._prediction_ledger.preview(request)
        except PredictionLedgerError as exc:
            raise _from_prediction_error(exc) from exc
        request_key = sha256(preview["request_id"].encode("utf-8")).hexdigest()
        destination = self.foresight_dir / f"{request_key}.json"
        if destination.exists():
            existing = self._load_artifact(destination)
            if existing.get("intent_sha256") == preview["intent_sha256"]:
                return existing
            raise MarketForesightError(
                "market_foresight_idempotency_conflict",
                "request_id already belongs to a different market-foresight intent",
            )
        try:
            prepared = self._prediction_ledger.prepare(request)
        except PredictionLedgerError as exc:
            raise _from_prediction_error(exc) from exc
        intent = dict(prepared["prediction_request"])
        artifact_identity = sha256(
            (
                prepared["request_id"]
                + "\0"
                + prepared["intent_sha256"]
            ).encode("utf-8")
        ).hexdigest()
        artifact = {
            "schema_version": _SCHEMA_VERSION,
            "id": f"mfp_{artifact_identity[:24]}",
            "kind": "market_foresight",
            "occurred_at": prepared["created_at"],
            "status": "proposed",
            "request_id": prepared["request_id"],
            "intent_sha256": prepared["intent_sha256"],
            "intent": intent,
            "evidence": {
                "market_timezone": prepared["market_timezone"],
                "outcome_session_policy": prepared["outcome_session_policy"],
                "entry_price": prepared["entry_price"],
            },
            "proposal_only": True,
            "requires_human_confirmation": True,
            "trading_allowed": False,
        }
        serialized = _canonical_json(artifact)
        self.foresight_dir.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.foresight_dir,
                prefix=f".{request_key}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(serialized + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, destination)
            except FileExistsError:
                existing = self._load_artifact(destination)
                if existing.get("intent_sha256") == preview["intent_sha256"]:
                    return existing
                raise MarketForesightError(
                    "market_foresight_idempotency_conflict",
                    "request_id already belongs to a different market-foresight intent",
                )
            self._fsync_directory(self.foresight_dir)
        finally:
            if temporary is not None:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass
        return artifact

    def list(self) -> list[dict[str, Any]]:
        if not self.foresight_dir.exists():
            return []
        artifacts = [self._load_artifact(path) for path in self.foresight_dir.glob("*.json")]
        return sorted(
            artifacts,
            key=lambda artifact: (artifact["occurred_at"], artifact["id"]),
        )

    def _load_artifact(self, path: Path) -> dict[str, Any]:
        try:
            artifact = _strict_json(path.read_text(encoding="utf-8"))
            self._validate_artifact(artifact, path=path)
            return artifact
        except MarketForesightError:
            raise
        except Exception as exc:
            raise MarketForesightError(
                "market_foresight_store_corrupt",
                "market-foresight artifact is unreadable or invalid",
            ) from exc

    def _validate_artifact(self, artifact: Any, *, path: Path) -> None:
        if not isinstance(artifact, dict) or set(artifact) != _ARTIFACT_FIELDS:
            raise ValueError("market-foresight artifact fields do not match schema")
        if (
            artifact["schema_version"] != _SCHEMA_VERSION
            or artifact["kind"] != "market_foresight"
            or artifact["status"] != "proposed"
            or not isinstance(artifact["id"], str)
            or _ID_PATTERN.fullmatch(artifact["id"]) is None
        ):
            raise ValueError("unsupported market-foresight artifact schema")
        _canonical_utc_timestamp(artifact["occurred_at"], "occurred_at")
        if (
            artifact["proposal_only"] is not True
            or artifact["requires_human_confirmation"] is not True
            or artifact["trading_allowed"] is not False
        ):
            raise ValueError("market-foresight safety flags are invalid")
        intent = artifact["intent"]
        try:
            preview = self._prediction_ledger.preview(intent)
        except PredictionLedgerError as exc:
            raise ValueError("market-foresight intent is invalid") from exc
        if (
            artifact["request_id"] != preview["request_id"]
            or artifact["intent_sha256"] != preview["intent_sha256"]
            or intent != preview["prediction_request"]
            or _HASH_PATTERN.fullmatch(str(artifact["intent_sha256"])) is None
        ):
            raise ValueError("market-foresight identity does not match its intent")
        request_key = sha256(artifact["request_id"].encode("utf-8")).hexdigest()
        if path.stem != request_key:
            raise ValueError("market-foresight file identity is invalid")
        artifact_identity = sha256(
            (artifact["request_id"] + "\0" + artifact["intent_sha256"]).encode("utf-8")
        ).hexdigest()
        if artifact["id"] != f"mfp_{artifact_identity[:24]}":
            raise ValueError("market-foresight artifact id is invalid")
        evidence = artifact["evidence"]
        if not isinstance(evidence, dict) or set(evidence) != {
            "market_timezone",
            "outcome_session_policy",
            "entry_price",
        }:
            raise ValueError("market-foresight evidence fields do not match schema")
        if (
            evidence["market_timezone"] != "America/New_York"
            or evidence["outcome_session_policy"]
            != "first_observed_session_on_or_after_horizon"
        ):
            raise ValueError("market-foresight evidence policy is invalid")
        entry = evidence["entry_price"]
        if not isinstance(entry, dict) or set(entry) != {
            "session_date",
            "close",
            "provider",
            "source",
            "interval",
            "adjustment",
            "fetched_at",
            "payload_sha256",
        }:
            raise ValueError("market-foresight entry evidence fields do not match schema")
        if not isinstance(entry["session_date"], str):
            raise ValueError("entry session date is invalid")
        session_date = date.fromisoformat(entry["session_date"])
        if session_date.isoformat() != entry["session_date"]:
            raise ValueError("entry session date is noncanonical")
        close = entry["close"]
        if (
            isinstance(close, bool)
            or not isinstance(close, (int, float))
            or not math.isfinite(float(close))
            or float(close) <= 0
        ):
            raise ValueError("entry close is invalid")
        if (
            entry["provider"] != "futu"
            or entry["source"] != "futu"
            or entry["interval"] != "1d"
            or entry["adjustment"] != "qfq"
            or _HASH_PATTERN.fullmatch(str(entry["payload_sha256"])) is None
        ):
            raise ValueError("entry evidence provenance is invalid")
        _canonical_utc_timestamp(entry["fetched_at"], "entry_price.fetched_at")

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        directory_fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

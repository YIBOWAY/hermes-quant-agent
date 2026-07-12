from __future__ import annotations

import json
import subprocess
from datetime import date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Optional

from hqa import quant_cli, runlog
from hqa.opportunities import OpportunityTracker


ObservationRunner = Callable[..., tuple[int, str]]


class OpportunityObservationError(RuntimeError):
    """Stable failure raised by the read-only platform observation seam."""

    def __init__(self, code: str, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


def _raise(code: str, message: str, *, retryable: bool) -> None:
    raise OpportunityObservationError(code, message, retryable=retryable)


def parse_platform_observations(output: str) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number: {value}")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        document = json.loads(
            output,
            parse_constant=reject_constant,
            object_pairs_hook=unique_object,
        )
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise OpportunityObservationError(
            "opportunity_platform_observation_invalid",
            "paper-strategy observations returned invalid JSON",
            retryable=True,
        ) from exc
    if not isinstance(document, dict):
        _raise(
            "opportunity_platform_observation_invalid",
            "paper-strategy observations returned invalid JSON",
            retryable=True,
        )
    if (
        document.get("schema_version") != 1
        or not isinstance(document.get("read_status"), str)
        or document.get("read_status") not in {"available", "empty", "degraded"}
        or isinstance(document.get("returned_count"), bool)
        or not isinstance(document.get("returned_count"), int)
        or not isinstance(document.get("truncated"), bool)
        or not isinstance(document.get("observations"), list)
        or not isinstance(document.get("errors"), list)
    ):
        _raise(
            "opportunity_platform_observation_invalid",
            "paper-strategy observations returned invalid schema",
            retryable=True,
        )
    return document


def _require_utc_timestamp(value: Any, *, field: str, invalid_code: str) -> str:
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except (TypeError, ValueError):
        parsed = None
    if (
        not isinstance(value, str)
        or "T" not in value
        or not value.endswith("Z")
        or parsed is None
        or parsed.utcoffset() != timedelta(0)
    ):
        _raise(
            invalid_code,
            f"{field} must be an aware UTC timestamp ending in Z",
            retryable=invalid_code != "opportunity_invalid_arguments",
        )
    return value


def _parse_utc_timestamp(value: Any, *, field: str) -> datetime:
    canonical = _require_utc_timestamp(
        value,
        field=field,
        invalid_code="opportunity_platform_observation_invalid",
    )
    return datetime.fromisoformat(canonical[:-1] + "+00:00")


def _strict_json_sha256(value: Any) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(serialized.encode("utf-8", errors="strict")).hexdigest()


def _require_limit(limit: Any) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        _raise(
            "opportunity_invalid_arguments",
            "limit must be an integer in [1, 200]",
            retryable=False,
        )
    return limit


def _require_optional_date(value: Any, *, field: str) -> Optional[str]:
    if value is None:
        return None
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        parsed = None
    if not isinstance(value, str) or parsed is None or parsed.isoformat() != value:
        _raise(
            "opportunity_invalid_arguments",
            f"{field} must be a canonical date",
            retryable=False,
        )
    return value


def _find_signal_state(
    tracker: OpportunityTracker,
    signal_id: str,
) -> dict[str, Any]:
    cursor: Optional[str] = None
    while True:
        page = tracker.list(limit=200, cursor=cursor)
        for state in page:
            if state["signal_id"] == signal_id:
                return state
        if len(page) < 200:
            break
        cursor = page[-1]["signal_id"]
    _raise(
        "opportunity_invalid_request",
        "opportunity signal_id is unknown",
        retryable=False,
    )


def _validate_coverage_observations(
    observations: list[Any],
    *,
    limit: int,
) -> None:
    if len(observations) > limit:
        _raise(
            "opportunity_platform_observation_invalid",
            "paper-strategy observations returned invalid coverage identities",
            retryable=True,
        )
    signal_ids: set[str] = set()
    execution_ids: set[str] = set()
    for observation in observations:
        if (
            not isinstance(observation, dict)
            or not isinstance(observation.get("signal"), dict)
            or not isinstance(observation["signal"].get("signal_id"), str)
            or not observation["signal"]["signal_id"]
            or observation["signal"]["signal_id"] in signal_ids
            or not isinstance(observation.get("executions"), list)
            or len(observation["executions"]) > 1
        ):
            _raise(
                "opportunity_platform_observation_invalid",
                "paper-strategy observations returned invalid coverage identities",
                retryable=True,
            )
        platform_signal_id = observation["signal"]["signal_id"]
        signal_ids.add(platform_signal_id)
        for execution in observation["executions"]:
            if (
                not isinstance(execution, dict)
                or not isinstance(execution.get("execution_id"), str)
                or not execution["execution_id"]
                or execution["execution_id"] in execution_ids
                or execution.get("signal_id") != platform_signal_id
            ):
                _raise(
                    "opportunity_platform_observation_invalid",
                    "paper-strategy observations returned invalid coverage identities",
                    retryable=True,
                )
            execution_ids.add(execution["execution_id"])


class OpportunityObservationSync:
    """Verify bounded platform facts before appending opportunity evidence."""

    def __init__(
        self,
        opportunity_dir: Path,
        *,
        run_observations: Optional[ObservationRunner] = None,
        now: Optional[Callable[[], str]] = None,
    ) -> None:
        self._tracker = OpportunityTracker(
            Path(opportunity_dir),
            now=now or runlog.utc_now_iso,
        )
        self._run_observations = (
            run_observations or quant_cli.run_paper_strategy_observations
        )

    def _read_observations(self, **kwargs: Any) -> dict[str, Any]:
        try:
            exit_code, output = self._run_observations(**kwargs)
        except (OSError, subprocess.SubprocessError) as exc:
            raise OpportunityObservationError(
                "opportunity_platform_unavailable",
                "paper-strategy observations command failed",
                retryable=True,
            ) from exc
        if exit_code != 0:
            _raise(
                "opportunity_platform_unavailable",
                "paper-strategy observations command failed",
                retryable=True,
            )
        return parse_platform_observations(output)

    def sync_coverage(
        self,
        signal_id: str,
        *,
        covered_through: str,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        limit = _require_limit(limit)
        from_date = _require_optional_date(from_date, field="from_date")
        to_date = _require_optional_date(to_date, field="to_date")
        if from_date is not None and to_date is not None and from_date > to_date:
            _raise(
                "opportunity_invalid_arguments",
                "from_date cannot be after to_date",
                retryable=False,
            )
        covered_through = _require_utc_timestamp(
            covered_through,
            field="--covered-through",
            invalid_code="opportunity_invalid_arguments",
        )
        state = _find_signal_state(self._tracker, signal_id)
        if state["signal"]["eligibility"]["status"] != "eligible":
            return state
        document = self._read_observations(
            from_date=from_date,
            to_date=to_date,
            limit=limit,
        )
        if (
            document.get("read_status") not in {"available", "empty"}
            or document.get("truncated") is not False
        ):
            _raise(
                "opportunity_platform_observation_incomplete",
                "platform observations must be available or empty and untruncated",
                retryable=True,
            )
        snapshot_at = self._validate_coverage_snapshot(
            document,
            state=state,
            covered_through=covered_through,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
        )
        snapshot_id = f"pso_{_strict_json_sha256(document)[:24]}"
        return self._tracker.record(
            {
                "event": "action_coverage_observed",
                "request_id": (
                    f"sync-actions:{signal_id}:{snapshot_id}:{covered_through}"
                ),
                "payload": {
                    "signal_id": signal_id,
                    "source": "paper_strategy_observations",
                    "snapshot_id": snapshot_id,
                    "observed_at": snapshot_at,
                    "covered_through": covered_through,
                    "complete": True,
                    "truncated": False,
                },
            }
        )

    def record_action(
        self,
        signal_id: str,
        *,
        platform_signal_id: str,
        platform_execution_id: str,
        actor: str,
        limit: int = 200,
    ) -> dict[str, Any]:
        limit = _require_limit(limit)
        document = self._read_observations(
            signal_id=platform_signal_id,
            limit=limit,
        )
        if (
            document.get("read_status") not in {"available", "empty"}
            or document.get("truncated") is not False
        ):
            _raise(
                "opportunity_platform_observation_incomplete",
                "platform observations must be available and untruncated",
                retryable=True,
            )
        execution = self._validate_action_snapshot(
            document,
            platform_signal_id=platform_signal_id,
            platform_execution_id=platform_execution_id,
            limit=limit,
        )
        if execution is None:
            _raise(
                "opportunity_platform_identity_unverified",
                "platform signal_id and execution_id could not be verified together",
                retryable=False,
            )
        if not all(
            isinstance(execution.get(field), str) and execution[field]
            for field in ("status", "created_at", "updated_at")
        ):
            _raise(
                "opportunity_platform_observation_invalid",
                "paper-strategy observations returned invalid schema",
                retryable=True,
            )
        return self._tracker.record(
            {
                "event": "action_observed",
                "request_id": (
                    f"record-action:{signal_id}:{platform_signal_id}:"
                    f"{platform_execution_id}:{execution['updated_at']}"
                ),
                "payload": {
                    "signal_id": signal_id,
                    "platform_signal_id": platform_signal_id,
                    "platform_execution_id": platform_execution_id,
                    "status": execution["status"],
                    "actor": actor,
                    "occurred_at": execution["created_at"],
                    "updated_at": execution["updated_at"],
                },
            }
        )

    @staticmethod
    def _validate_action_snapshot(
        document: dict[str, Any],
        *,
        platform_signal_id: str,
        platform_execution_id: str,
        limit: int,
    ) -> Optional[dict[str, Any]]:
        expected_fields = {
            "schema_version",
            "snapshot_at",
            "read_status",
            "query",
            "returned_count",
            "truncated",
            "ops_quality",
            "observations",
            "errors",
        }
        expected_query = {
            "from_date": None,
            "to_date": None,
            "signal_id": platform_signal_id,
            "limit": limit,
        }
        expected_quality_fields = {
            "pending_sleeve_count",
            "pending_journal_count",
            "corrupt_journal_count",
            "recovery_required_count",
        }
        query = document.get("query")
        quality = document.get("ops_quality")
        observations = document["observations"]
        if (
            set(document) != expected_fields
            or query != expected_query
            or not isinstance(quality, dict)
            or set(quality) != expected_quality_fields
            or any(
                isinstance(value, bool) or not isinstance(value, int) or value < 0
                for value in quality.values()
            )
            or document["returned_count"] != len(observations)
            or (document["read_status"] == "empty" and observations)
            or (document["read_status"] == "available" and not observations)
        ):
            _raise(
                "opportunity_platform_observation_invalid",
                "paper-strategy observations returned invalid action schema",
                retryable=True,
            )
        _parse_utc_timestamp(document["snapshot_at"], field="platform snapshot_at")
        if any(quality.values()) or document["errors"] != []:
            _raise(
                "opportunity_platform_observation_incomplete",
                "platform observation quality is incomplete",
                retryable=True,
            )
        if document["read_status"] == "empty":
            return None
        if len(observations) != 1:
            _raise(
                "opportunity_platform_observation_invalid",
                "paper-strategy observations returned invalid action identities",
                retryable=True,
            )
        observation = observations[0]
        if (
            not isinstance(observation, dict)
            or not isinstance(observation.get("signal"), dict)
            or observation["signal"].get("signal_id") != platform_signal_id
            or not isinstance(observation.get("executions"), list)
            or len(observation["executions"]) > 1
        ):
            _raise(
                "opportunity_platform_observation_invalid",
                "paper-strategy observations returned invalid action identities",
                retryable=True,
            )
        execution_ids: set[str] = set()
        match = None
        for execution in observation["executions"]:
            if (
                not isinstance(execution, dict)
                or not isinstance(execution.get("execution_id"), str)
                or not execution["execution_id"]
                or execution.get("signal_id") != platform_signal_id
                or execution["execution_id"] in execution_ids
            ):
                _raise(
                    "opportunity_platform_observation_invalid",
                    "paper-strategy observations returned invalid action identities",
                    retryable=True,
                )
            execution_ids.add(execution["execution_id"])
            if execution["execution_id"] == platform_execution_id:
                match = execution
        return match

    @staticmethod
    def _validate_coverage_snapshot(
        document: dict[str, Any],
        *,
        state: dict[str, Any],
        covered_through: str,
        from_date: Optional[str],
        to_date: Optional[str],
        limit: int,
    ) -> str:
        snapshot_at = document.get("snapshot_at")
        snapshot_time = _parse_utc_timestamp(
            snapshot_at,
            field="platform snapshot_at",
        )
        covered_time = _parse_utc_timestamp(
            covered_through,
            field="covered_through",
        )
        query = document.get("query")
        quality = document.get("ops_quality")
        expected_fields = {
            "schema_version",
            "snapshot_at",
            "read_status",
            "query",
            "returned_count",
            "truncated",
            "ops_quality",
            "observations",
            "errors",
        }
        expected_quality_fields = {
            "pending_sleeve_count",
            "pending_journal_count",
            "corrupt_journal_count",
            "recovery_required_count",
        }
        if (
            set(document) != expected_fields
            or not isinstance(query, dict)
            or set(query) != {"from_date", "to_date", "signal_id", "limit"}
            or query.get("from_date") != from_date
            or query.get("to_date") != to_date
            or query.get("signal_id") is not None
            or query.get("limit") != limit
            or not isinstance(quality, dict)
            or set(quality) != expected_quality_fields
            or any(
                isinstance(value, bool) or not isinstance(value, int) or value < 0
                for value in quality.values()
            )
            or document.get("returned_count") != len(document["observations"])
            or document.get("errors") != []
            or (document["read_status"] == "empty" and document["observations"])
            or (document["read_status"] == "available" and not document["observations"])
        ):
            _raise(
                "opportunity_platform_observation_invalid",
                "paper-strategy observations returned invalid coverage schema",
                retryable=True,
            )
        if any(quality.values()):
            _raise(
                "opportunity_platform_observation_incomplete",
                "platform observation quality is incomplete",
                retryable=True,
            )
        _validate_coverage_observations(document["observations"], limit=limit)
        if covered_time > snapshot_time:
            _raise(
                "opportunity_platform_observation_incomplete",
                "coverage cannot extend beyond the platform snapshot watermark",
                retryable=True,
            )
        source_date = state["signal"]["source"]["date"]
        deadline_at = state["signal"]["eligibility"].get("deadline_at")
        deadline_date = (
            deadline_at[:10] if isinstance(deadline_at, str) else source_date
        )
        try:
            normalized_source = date.fromisoformat(source_date).isoformat()
            normalized_deadline = date.fromisoformat(deadline_date).isoformat()
        except ValueError as exc:
            raise OpportunityObservationError(
                "opportunity_platform_observation_invalid",
                "opportunity source/deadline date is invalid",
                retryable=False,
            ) from exc
        if (from_date is not None and from_date > normalized_source) or (
            to_date is not None and to_date < normalized_deadline
        ):
            _raise(
                "opportunity_platform_observation_incomplete",
                "platform observation query does not cover the opportunity window",
                retryable=True,
            )
        return str(snapshot_at)

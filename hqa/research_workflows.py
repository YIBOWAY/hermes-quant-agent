from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import math
import os
import re
import secrets
import stat
import time
from uuid import UUID
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Optional


_SCHEMA_VERSION = "1.0"
_PLAN_SCHEMA_VERSION = 1
_OWNER_USER_ID = "00000000-0000-0000-0000-000000000001"
_COMMAND_KIND = "research_chat"
_DEFAULT_TTL_DAYS = 30
_MAX_TTL_DAYS = 30
_MAX_PROMPT_BYTES = 65_536
_MAX_PAYLOAD_BYTES = 524_288
_MAX_EVENT_BYTES = 262_144
_MAX_JOURNAL_BYTES = 64 * 1024 * 1024
_LOCK_READY_MARKER = b"HQA_RESEARCH_WORKFLOW_LEDGER_READY_V1\n"

_SESSION_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}")
_CLIENT_REQUEST_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}")
_POLICY_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}")
_STEP_ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,127}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_SAGA_ID_RE = re.compile(r"hqs_[0-9a-f]{24}")
_TASK_ID_RE = re.compile(r"hqt_[0-9a-f]{24}")
_ATTEMPT_ID_RE = re.compile(r"hqa_[0-9a-f]{24}")
_EVENT_ID_RE = re.compile(r"hqe_[0-9a-f]{24}")
_ORPHAN_AGGREGATE_ID_RE = re.compile(r"hqo_[0-9a-f]{24}")
_PAYLOAD_REF_RE = re.compile(r"hqa-payload:sha256:([0-9a-f]{64})")

_RECEIPT_FIELDS = {
    "schema_version",
    "workflow_saga_id",
    "owner_user_id",
    "platform_session_id",
    "client_request_id",
    "command_kind",
    "canonical_request_digest",
    "payload_ref",
    "payload_digest",
    "payload_expires_at",
    "provider_policy_digest",
    "task_id",
    "task_version",
    "attempt_id",
    "attempt_number",
    "prepared_event_id",
    "prepared_event_digest",
    "plan_schema_version",
    "plan_version",
    "plan_digest",
    "workflow_preparation_digest",
}


class ResearchWorkflowError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


def _invalid(message: str) -> ResearchWorkflowError:
    return ResearchWorkflowError("workflow_invalid_request", message)


def _corrupt(message: str) -> ResearchWorkflowError:
    return ResearchWorkflowError("workflow_ledger_corrupt", message)


def _insecure(message: str) -> ResearchWorkflowError:
    return ResearchWorkflowError("workflow_storage_insecure", message)


def _reject_json_constant(value: str) -> None:
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


def _validate_json_tree(root: Any, *, max_depth: int = 32) -> None:
    stack: list[tuple[Any, int]] = [(root, 0)]
    while stack:
        value, depth = stack.pop()
        if depth > max_depth:
            raise _invalid("workflow JSON nesting exceeds the supported depth")
        if isinstance(value, str):
            try:
                value.encode("utf-8", errors="strict")
            except UnicodeEncodeError as exc:
                raise _invalid("workflow JSON contains invalid unicode") from exc
        elif isinstance(value, float) and not math.isfinite(value):
            raise _invalid("workflow JSON contains a non-finite number")
        elif isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str):
                    raise _invalid("workflow JSON object keys must be strings")
                stack.append((key, depth + 1))
                stack.append((item, depth + 1))
        elif isinstance(value, list):
            for item in value:
                stack.append((item, depth + 1))


def _canonical_json(value: Any) -> str:
    _validate_json_tree(value)
    try:
        serialized = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        serialized.encode("utf-8", errors="strict")
        return serialized
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise _invalid("workflow value must be strict finite JSON") from exc


def _canonical_bytes(value: Any) -> bytes:
    return (_canonical_json(value) + "\n").encode("utf-8", errors="strict")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_timestamp(value: Any, field: str, *, stored: bool = False) -> str:
    error = _corrupt if stored else _invalid
    if not isinstance(value, str) or not value:
        raise error(f"{field} must be a timezone-aware timestamp")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise error(f"{field} must be a timezone-aware timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise error(f"{field} must be a timezone-aware timestamp")
    try:
        utc = parsed.astimezone(timezone.utc)
        return utc.isoformat(timespec="microseconds").replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError) as exc:
        raise error(f"{field} falls outside the supported timestamp range") from exc


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value[:-1] + "+00:00")


def _strict_identifier(value: Any, field: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise _invalid(f"{field} is invalid")
    return value


def _normalize_provider_endpoint(value: Any, field: str) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"provider", "model"}:
        raise _invalid(f"{field} fields are invalid")
    provider = value["provider"]
    model = value["model"]
    if (
        not isinstance(provider, str)
        or _POLICY_ID_RE.fullmatch(provider) is None
        or not isinstance(model, str)
        or _POLICY_ID_RE.fullmatch(model) is None
    ):
        raise _invalid(f"{field} provider/model identifiers are invalid")
    return {"provider": provider, "model": model}


def _normalize_provider_policy(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"primary", "fallbacks"}:
        raise _invalid("provider_policy fields are invalid")
    primary = _normalize_provider_endpoint(value["primary"], "provider_policy.primary")
    fallbacks = value["fallbacks"]
    if not isinstance(fallbacks, list) or len(fallbacks) > 4:
        raise _invalid("provider_policy.fallbacks must contain at most four entries")
    normalized_fallbacks = [
        _normalize_provider_endpoint(item, "provider_policy.fallbacks")
        for item in fallbacks
    ]
    identities = [
        (primary["provider"], primary["model"]),
        *[(item["provider"], item["model"]) for item in normalized_fallbacks],
    ]
    if len(set(identities)) != len(identities):
        raise _invalid("provider_policy contains a duplicate provider/model entry")
    return {"primary": primary, "fallbacks": normalized_fallbacks}


def _normalize_plan(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "version",
        "goal",
        "steps",
    }:
        raise _invalid("plan fields are invalid")
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != _PLAN_SCHEMA_VERSION
    ):
        raise _invalid("plan.schema_version is unsupported")
    version = value["version"]
    if isinstance(version, bool) or not isinstance(version, int) or version != 1:
        raise _invalid("initial plan.version must be 1")
    goal = value["goal"]
    if not isinstance(goal, str) or not goal.strip() or len(goal) > 2_048:
        raise _invalid("plan.goal is required and must be bounded")
    steps = value["steps"]
    if not isinstance(steps, list) or not 1 <= len(steps) <= 64:
        raise _invalid("plan.steps must contain from one to 64 steps")
    normalized_steps: list[dict[str, str]] = []
    seen_step_ids: set[str] = set()
    for raw in steps:
        if not isinstance(raw, dict) or set(raw) != {
            "step_id",
            "kind",
            "description",
        }:
            raise _invalid("plan step fields are invalid")
        step_id = raw["step_id"]
        kind = raw["kind"]
        description = raw["description"]
        if (
            not isinstance(step_id, str)
            or _STEP_ID_RE.fullmatch(step_id) is None
            or step_id in seen_step_ids
        ):
            raise _invalid("plan step_id is invalid or duplicated")
        if not isinstance(kind, str) or kind not in {
            "read_only",
            "proposal_only",
        }:
            raise _invalid("plan step kind must remain read_only or proposal_only")
        if (
            not isinstance(description, str)
            or not description.strip()
            or len(description) > 4_096
        ):
            raise _invalid("plan step description is required and must be bounded")
        seen_step_ids.add(step_id)
        normalized_steps.append(
            {"step_id": step_id, "kind": kind, "description": description}
        )
    return {
        "schema_version": _PLAN_SCHEMA_VERSION,
        "version": version,
        "goal": goal,
        "steps": normalized_steps,
    }


def _normalize_prepare_request(value: Any) -> dict[str, Any]:
    expected = {
        "schema_version",
        "platform_session_id",
        "client_request_id",
        "command_kind",
        "payload_ttl_days",
        "prompt",
        "provider_policy",
        "plan",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise _invalid("workflow prepare request fields are invalid")
    if value["schema_version"] != _SCHEMA_VERSION:
        raise _invalid("workflow prepare schema_version is unsupported")
    platform_session_id = _strict_identifier(
        value["platform_session_id"], "platform_session_id", _SESSION_ID_RE
    )
    client_request_id = _strict_identifier(
        value["client_request_id"], "client_request_id", _CLIENT_REQUEST_ID_RE
    )
    if value["command_kind"] != _COMMAND_KIND:
        raise _invalid("command_kind must be research_chat")
    ttl_days = value["payload_ttl_days"]
    if (
        isinstance(ttl_days, bool)
        or not isinstance(ttl_days, int)
        or not 1 <= ttl_days <= _MAX_TTL_DAYS
    ):
        raise _invalid("payload_ttl_days must be an integer from 1 to 30")
    prompt = value["prompt"]
    if not isinstance(prompt, str) or not prompt.strip():
        raise _invalid("prompt is required")
    try:
        prompt_bytes = prompt.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise _invalid("prompt must be valid UTF-8") from exc
    if len(prompt_bytes) > _MAX_PROMPT_BYTES:
        raise _invalid("prompt exceeds the maximum size")
    provider_policy = _normalize_provider_policy(value["provider_policy"])
    plan = _normalize_plan(value["plan"])
    normalized = {
        "schema_version": _SCHEMA_VERSION,
        "owner_user_id": _OWNER_USER_ID,
        "platform_session_id": platform_session_id,
        "client_request_id": client_request_id,
        "command_kind": _COMMAND_KIND,
        "payload_ttl_days": ttl_days,
        "prompt": prompt,
        "provider_policy": provider_policy,
        "plan": plan,
    }
    _validate_json_tree(normalized)
    if len(_canonical_bytes(normalized)) > _MAX_PAYLOAD_BYTES:
        raise _invalid("workflow canonical request exceeds the maximum size")
    return normalized


def _prepared_event_basis(receipt: dict[str, Any]) -> dict[str, Any]:
    facts = {
        key: value
        for key, value in receipt.items()
        if key
        not in {
            "prepared_event_id",
            "prepared_event_digest",
            "workflow_preparation_digest",
        }
    }
    return {
        "schema_version": _SCHEMA_VERSION,
        "kind": "workflow_prepared",
        "aggregate_id": receipt["task_id"],
        "aggregate_version": 1,
        "expected_version": 0,
        "operation_id": receipt["workflow_saga_id"],
        "facts": facts,
    }


def _preparation_digest(receipt: dict[str, Any]) -> str:
    return _sha256(
        {
            key: value
            for key, value in receipt.items()
            if key != "workflow_preparation_digest"
        }
    )


def _record_digest(record: dict[str, Any]) -> str:
    return _sha256(
        {key: value for key, value in record.items() if key != "record_sha256"}
    )


def _transport_binding_basis(
    preparation: dict[str, Any],
    command_id: str,
) -> dict[str, Any]:
    return {**preparation, "command_id": command_id}


def transport_binding_digest(
    preparation: dict[str, Any],
    command_id: str,
) -> str:
    """Return the cross-repository exact binding digest.

    The platform must hash this same canonical document.  It includes the whole
    immutable preparation receipt, including payload expiry, and excludes all
    runtime observation timestamps.
    """
    if not isinstance(preparation, dict) or set(preparation) != _RECEIPT_FIELDS:
        raise _invalid("workflow preparation receipt fields are invalid")
    if not isinstance(command_id, str):
        raise _invalid("command_id must be a canonical lowercase UUID")
    try:
        if str(UUID(command_id)) != command_id:
            raise ValueError("non-canonical UUID")
    except (ValueError, AttributeError) as exc:
        raise _invalid("command_id must be a canonical lowercase UUID") from exc
    return _sha256(_transport_binding_basis(preparation, command_id))


def as_platform_prepared_command(preparation: dict[str, Any]) -> dict[str, Any]:
    """Return the exact metadata-only document accepted by the platform BFF.

    There is deliberately no second translation schema: the HQA preparation
    receipt *is* the cross-repository command preparation contract.  Returning
    a fresh mapping prevents callers from mutating the store's in-memory copy.
    """

    try:
        ResearchWorkflowStore._validate_receipt(preparation)
    except ResearchWorkflowError as exc:
        raise _invalid("workflow preparation receipt is not platform-adaptable") from exc
    return dict(preparation)


class ResearchWorkflowStore:
    """Single-writer HQA authority for research Task/Attempt workflow facts.

    This module performs local deterministic persistence only.  It has no Hermes,
    provider, subprocess, browser, or network adapter.
    """

    def __init__(
        self,
        root: Path,
        *,
        now: Optional[Callable[[], str]] = None,
        lock_timeout_seconds: float = 5.0,
    ) -> None:
        self.root = Path(os.path.abspath(root))
        self.journal_path = self.root / "events.v1.jsonl"
        self.projection_path = self.root / "projection.v1.json"
        self.lock_path = self.root / ".ledger.lock"
        self.payload_dir = self.root / "payloads"
        self._now = now or (
            lambda: datetime.now(timezone.utc)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
        if (
            isinstance(lock_timeout_seconds, bool)
            or not isinstance(lock_timeout_seconds, (int, float))
            or not math.isfinite(float(lock_timeout_seconds))
            or not 0 < float(lock_timeout_seconds) <= 30.0
        ):
            raise ValueError(
                "lock_timeout_seconds must be finite, positive, and at most 30"
            )
        self._lock_timeout_seconds = float(lock_timeout_seconds)

    def prepare(self, request: dict[str, Any]) -> dict[str, Any]:
        normalized = _normalize_prepare_request(request)
        canonical_request_digest = _sha256(normalized)
        saga_identity = {
            "owner_user_id": _OWNER_USER_ID,
            "platform_session_id": normalized["platform_session_id"],
            "client_request_id": normalized["client_request_id"],
            "command_kind": _COMMAND_KIND,
            "canonical_request_digest": canonical_request_digest,
        }
        workflow_saga_id = f"hqs_{_sha256(saga_identity)[:24]}"

        try:
            with self._locked(exclusive=True, create=True) as locked:
                assert locked is not None
                root_fd, journal_fd, lock_fd = locked
                events = self._read_events(journal_fd, allow_empty=True)
                if not events and self._lock_is_ready(lock_fd):
                    raise _corrupt("ready workflow journal must not be empty")
                for event in events:
                    if event["kind"] == "orphan_payload_deletion_requested":
                        tombstone = event["payload"]
                        same_client_identity = (
                            tombstone["owner_user_id"] == _OWNER_USER_ID
                            and tombstone["platform_session_id"]
                            == normalized["platform_session_id"]
                            and tombstone["client_request_id"]
                            == normalized["client_request_id"]
                        )
                        if not same_client_identity:
                            continue
                        if (
                            tombstone["canonical_request_digest"]
                            != canonical_request_digest
                        ):
                            raise ResearchWorkflowError(
                                "workflow_idempotency_conflict",
                                "client_request_id already belongs to a different workflow intent",
                            )
                        raise ResearchWorkflowError(
                            "workflow_idempotency_expired",
                            "the pre-journal workflow intent expired; use a new client_request_id",
                        )
                    if event["kind"] != "workflow_prepared":
                        continue
                    existing = event["payload"]
                    same_client_identity = (
                        existing["owner_user_id"] == _OWNER_USER_ID
                        and existing["platform_session_id"]
                        == normalized["platform_session_id"]
                        and existing["client_request_id"]
                        == normalized["client_request_id"]
                    )
                    if not same_client_identity:
                        continue
                    if (
                        existing["canonical_request_digest"]
                        == canonical_request_digest
                        and existing["workflow_saga_id"] == workflow_saga_id
                    ):
                        projection = self._projection_for_events(root_fd, events)
                        task = projection["tasks"].get(existing["task_id"])
                        if task is None:
                            raise _corrupt(
                                "workflow preparation has no task projection"
                            )
                        if task["payload_status"] not in {
                            "deletion_pending",
                            "deleted",
                        }:
                            self._verify_payload_for_receipt(root_fd, existing)
                        self._publish_projection(root_fd, projection)
                        self._mark_lock_ready(lock_fd)
                        return dict(existing)
                    raise ResearchWorkflowError(
                        "workflow_idempotency_conflict",
                        "client_request_id already belongs to a different workflow intent",
                    )

                reusable_payload = self._find_reusable_orphan_payload(
                    root_fd,
                    normalized,
                    events,
                )
                if reusable_payload is None:
                    recorded_at = _canonical_timestamp(self._now(), "recorded_at")
                    expires_at = (
                        _parse_timestamp(recorded_at)
                        + timedelta(days=normalized["payload_ttl_days"])
                    ).isoformat(timespec="microseconds").replace("+00:00", "Z")
                    provider_policy_digest = _sha256(normalized["provider_policy"])
                    plan_digest = _sha256(normalized["plan"])
                    payload_envelope = {
                        "schema_version": _SCHEMA_VERSION,
                        "kind": _COMMAND_KIND,
                        "owner_user_id": _OWNER_USER_ID,
                        "platform_session_id": normalized["platform_session_id"],
                        "client_request_id": normalized["client_request_id"],
                        "canonical_request_digest": canonical_request_digest,
                        "prompt": normalized["prompt"],
                        "provider_policy": normalized["provider_policy"],
                        "provider_policy_digest": provider_policy_digest,
                        "plan": normalized["plan"],
                        "plan_digest": plan_digest,
                        "payload_ttl_days": normalized["payload_ttl_days"],
                        "created_at": recorded_at,
                        "expires_at": expires_at,
                    }
                else:
                    payload_envelope = reusable_payload
                    recorded_at = payload_envelope["created_at"]
                    expires_at = payload_envelope["expires_at"]
                    provider_policy_digest = payload_envelope[
                        "provider_policy_digest"
                    ]
                    plan_digest = payload_envelope["plan_digest"]
                payload_bytes = _canonical_bytes(payload_envelope)
                payload_digest = _sha256_bytes(payload_bytes)
                payload_ref = f"hqa-payload:sha256:{payload_digest}"
                self._write_or_verify_payload(root_fd, payload_digest, payload_bytes)

                task_id = f"hqt_{_sha256([workflow_saga_id, 'task'])[:24]}"
                attempt_id = f"hqa_{_sha256([workflow_saga_id, 'attempt', 1])[:24]}"
                receipt: dict[str, Any] = {
                    "schema_version": _SCHEMA_VERSION,
                    "workflow_saga_id": workflow_saga_id,
                    "owner_user_id": _OWNER_USER_ID,
                    "platform_session_id": normalized["platform_session_id"],
                    "client_request_id": normalized["client_request_id"],
                    "command_kind": _COMMAND_KIND,
                    "canonical_request_digest": canonical_request_digest,
                    "payload_ref": payload_ref,
                    "payload_digest": payload_digest,
                    "payload_expires_at": expires_at,
                    "provider_policy_digest": provider_policy_digest,
                    "task_id": task_id,
                    "task_version": 1,
                    "attempt_id": attempt_id,
                    "attempt_number": 1,
                    "plan_schema_version": _PLAN_SCHEMA_VERSION,
                    "plan_version": normalized["plan"]["version"],
                    "plan_digest": plan_digest,
                }
                prepared_event_digest = _sha256(_prepared_event_basis(receipt))
                receipt["prepared_event_id"] = (
                    f"hqe_{prepared_event_digest[:24]}"
                )
                receipt["prepared_event_digest"] = prepared_event_digest
                receipt["workflow_preparation_digest"] = _preparation_digest(receipt)
                self._validate_receipt(receipt)

                previous_record_sha256 = (
                    events[-1]["record_sha256"] if events else None
                )
                event = {
                    "schema_version": _SCHEMA_VERSION,
                    "sequence": len(events) + 1,
                    "aggregate_id": task_id,
                    "aggregate_version": 1,
                    "expected_version": 0,
                    "operation_id": workflow_saga_id,
                    "event_id": receipt["prepared_event_id"],
                    "event_digest": prepared_event_digest,
                    "kind": "workflow_prepared",
                    "recorded_at": recorded_at,
                    "previous_record_sha256": previous_record_sha256,
                    "payload": receipt,
                }
                event["record_sha256"] = _record_digest(event)
                next_events = [*events, event]
                projection = self._projection_for_events(root_fd, next_events)
                self._append_event(journal_fd, event)
                self._publish_projection(root_fd, projection)
                self._mark_lock_ready(lock_fd)
                return dict(receipt)
        except ResearchWorkflowError:
            raise
        except OSError as exc:
            raise ResearchWorkflowError(
                "workflow_storage_io_error",
                f"workflow prepare failed: {type(exc).__name__}",
                retryable=True,
            ) from exc

    def observe_transport_binding(
        self,
        *,
        task_id: str,
        expected_version: int,
        command_id: str,
        binding_digest: str,
    ) -> dict[str, Any]:
        if not isinstance(task_id, str) or _TASK_ID_RE.fullmatch(task_id) is None:
            raise _invalid("task_id is invalid")
        if (
            isinstance(expected_version, bool)
            or not isinstance(expected_version, int)
            or expected_version < 1
        ):
            raise _invalid("expected_version must be a positive integer")
        if not isinstance(binding_digest, str) or _SHA256_RE.fullmatch(binding_digest) is None:
            raise _invalid("binding_digest must be a lowercase SHA-256")
        # This validates the UUID without treating it as a path or opaque shell value.
        if not isinstance(command_id, str):
            raise _invalid("command_id must be a canonical lowercase UUID")
        try:
            if str(UUID(command_id)) != command_id:
                raise ValueError("non-canonical UUID")
        except (ValueError, AttributeError) as exc:
            raise _invalid("command_id must be a canonical lowercase UUID") from exc

        try:
            with self._locked(exclusive=True, create=False) as locked:
                if locked is None:
                    raise ResearchWorkflowError(
                        "workflow_not_found", "workflow task was not found"
                    )
                root_fd, journal_fd, _ = locked
                events = self._read_events(journal_fd, allow_empty=False)
                projection = self._projection_for_events(root_fd, events)
                task = projection["tasks"].get(task_id)
                if task is None:
                    raise ResearchWorkflowError(
                        "workflow_not_found", "workflow task was not found"
                    )
                prepared = task["preparation"]
                observed_at = _canonical_timestamp(self._now(), "observed_at")
                expected_binding_digest = transport_binding_digest(
                    prepared,
                    command_id,
                )
                if binding_digest != expected_binding_digest:
                    raise ResearchWorkflowError(
                        "workflow_binding_mismatch",
                        "transport binding digest does not match the exact preparation",
                    )
                for event in events:
                    if (
                        event["aggregate_id"] == task_id
                        and event["kind"] == "transport_binding_observed"
                    ):
                        payload = event["payload"]
                        if (
                            payload["command_id"] == command_id
                            and payload["binding_digest"] == binding_digest
                            and payload["workflow_preparation_digest"]
                            == prepared["workflow_preparation_digest"]
                        ):
                            self._publish_projection(root_fd, projection)
                            return dict(task)
                        raise ResearchWorkflowError(
                            "workflow_binding_conflict",
                            "workflow task already has a different transport binding",
                        )
                if task["version"] != expected_version:
                    raise ResearchWorkflowError(
                        "workflow_version_conflict",
                        "workflow expected_version does not match current version",
                    )
                if task["state"] not in {
                    "awaiting_transport_binding",
                    "payload_expired",
                    "payload_deletion_pending",
                    "payload_deleted",
                }:
                    raise ResearchWorkflowError(
                        "workflow_transition_conflict",
                        "workflow task is not awaiting a transport binding",
                    )
                payload = {
                    "schema_version": _SCHEMA_VERSION,
                    "command_id": command_id,
                    "binding_digest": binding_digest,
                    "workflow_preparation_digest": prepared[
                        "workflow_preparation_digest"
                    ],
                }
                operation_id = f"bind:{task_id}:{command_id}"
                semantic = {
                    "schema_version": _SCHEMA_VERSION,
                    "kind": "transport_binding_observed",
                    "aggregate_id": task_id,
                    "aggregate_version": expected_version + 1,
                    "expected_version": expected_version,
                    "operation_id": operation_id,
                    "facts": payload,
                }
                event_digest = _sha256(semantic)
                event = {
                    "schema_version": _SCHEMA_VERSION,
                    "sequence": len(events) + 1,
                    "aggregate_id": task_id,
                    "aggregate_version": expected_version + 1,
                    "expected_version": expected_version,
                    "operation_id": operation_id,
                    "event_id": f"hqe_{event_digest[:24]}",
                    "event_digest": event_digest,
                    "kind": "transport_binding_observed",
                    "recorded_at": observed_at,
                    "previous_record_sha256": events[-1]["record_sha256"],
                    "payload": payload,
                }
                event["record_sha256"] = _record_digest(event)
                next_events = [*events, event]
                next_projection = self._projection_for_events(root_fd, next_events)
                self._append_event(journal_fd, event)
                self._publish_projection(root_fd, next_projection)
                return dict(next_projection["tasks"][task_id])
        except ResearchWorkflowError:
            raise
        except OSError as exc:
            raise ResearchWorkflowError(
                "workflow_storage_io_error",
                f"workflow binding observation failed: {type(exc).__name__}",
                retryable=True,
            ) from exc

    def reconcile_expired_payloads(
        self,
        *,
        as_of: Optional[str] = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Audit and physically remove expired workflow payloads.

        Deletion is a recoverable two-event transition.  A crash before unlink
        leaves a durable request; a crash after unlink but before completion is
        completed on the next call without recreating payload bytes.
        """

        observed_at = _canonical_timestamp(as_of or self._now(), "as_of")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise _invalid("limit must be an integer from 1 to 500")
        report: dict[str, Any] = {
            "schema_version": _SCHEMA_VERSION,
            "as_of": observed_at,
            "requested_task_ids": [],
            "completed_task_ids": [],
            "already_deleted_task_ids": [],
            "expired_orphan_payload_digests_deleted": [],
            "has_more": False,
        }
        try:
            with self._locked(exclusive=True, create=False) as locked:
                if locked is None:
                    return report
                root_fd, journal_fd, lock_fd = locked
                events = self._read_events(journal_fd, allow_empty=True)
                if not events and self._lock_is_ready(lock_fd):
                    raise _corrupt("ready workflow journal must not be empty")
                self._recover_prelink_payloads(root_fd)
                projection = self._projection_for_events(root_fd, events)
                # The journal is canonical.  Republishing here repairs the
                # append-fsync -> projection-replace crash window even when all
                # work has already reached a terminal deleted state.
                self._publish_projection(root_fd, projection)
                events, projection, orphan_report = self._delete_expired_orphan_payloads(
                    root_fd,
                    journal_fd=journal_fd,
                    events=events,
                    projection=projection,
                    observed_at=observed_at,
                    limit=limit,
                )
                if events:
                    self._mark_lock_ready(lock_fd)
                report["expired_orphan_payload_digests_deleted"] = orphan_report[
                    "deleted"
                ]
                already_deleted = sorted(
                    task["task_id"]
                    for task in projection["tasks"].values()
                    if task["payload_status"] == "deleted"
                )
                report["already_deleted_task_ids"] = already_deleted[:limit]
                eligible = [
                    task
                    for task in projection["tasks"].values()
                    if task["payload_status"] == "deletion_pending"
                    or _parse_timestamp(observed_at)
                    >= _parse_timestamp(task["preparation"]["payload_expires_at"])
                    and task["payload_status"] != "deleted"
                ]
                eligible.sort(key=lambda task: task["task_id"])
                report["has_more"] = (
                    len(eligible) > limit or orphan_report["has_more"]
                )
                for task in eligible[:limit]:
                    task_id = task["task_id"]
                    preparation = task["preparation"]
                    deletion_facts = {
                        "schema_version": _SCHEMA_VERSION,
                        "payload_ref": preparation["payload_ref"],
                        "payload_digest": preparation["payload_digest"],
                        "payload_expires_at": preparation["payload_expires_at"],
                        "workflow_preparation_digest": preparation[
                            "workflow_preparation_digest"
                        ],
                    }
                    if task["payload_status"] != "deletion_pending":
                        request_event = self._transition_event(
                            events,
                            task_id=task_id,
                            expected_version=task["version"],
                            kind="payload_deletion_requested",
                            operation_id=(
                                f"delete-request:{task_id}:"
                                f"{preparation['payload_digest']}"
                            ),
                            facts=deletion_facts,
                            recorded_at=observed_at,
                        )
                        next_events = [*events, request_event]
                        next_projection = self._projection_for_events(root_fd, next_events)
                        self._append_event(journal_fd, request_event)
                        self._publish_projection(root_fd, next_projection)
                        events = next_events
                        projection = next_projection
                        task = projection["tasks"][task_id]
                        report["requested_task_ids"].append(task_id)

                    self._unlink_payload_if_present(
                        root_fd,
                        preparation["payload_digest"],
                    )
                    deletion = task["payload_deletion"]
                    assert deletion is not None
                    completion_facts = {
                        **deletion_facts,
                        "deletion_request_event_id": deletion["requested_event_id"],
                    }
                    completion_event = self._transition_event(
                        events,
                        task_id=task_id,
                        expected_version=task["version"],
                        kind="payload_deletion_completed",
                        operation_id=(
                            f"delete-complete:{task_id}:"
                            f"{preparation['payload_digest']}"
                        ),
                        facts=completion_facts,
                        recorded_at=observed_at,
                    )
                    next_events = [*events, completion_event]
                    next_projection = self._projection_for_events(root_fd, next_events)
                    self._append_event(journal_fd, completion_event)
                    self._publish_projection(root_fd, next_projection)
                    events = next_events
                    projection = next_projection
                    report["completed_task_ids"].append(task_id)
                return report
        except ResearchWorkflowError:
            raise
        except OSError as exc:
            raise ResearchWorkflowError(
                "workflow_storage_io_error",
                f"workflow payload reconciliation failed: {type(exc).__name__}",
                retryable=True,
            ) from exc

    @staticmethod
    def _transition_event(
        events: list[dict[str, Any]],
        *,
        task_id: str,
        expected_version: int,
        kind: str,
        operation_id: str,
        facts: dict[str, Any],
        recorded_at: str,
    ) -> dict[str, Any]:
        semantic = {
            "schema_version": _SCHEMA_VERSION,
            "kind": kind,
            "aggregate_id": task_id,
            "aggregate_version": expected_version + 1,
            "expected_version": expected_version,
            "operation_id": operation_id,
            "facts": facts,
        }
        event_digest = _sha256(semantic)
        event = {
            "schema_version": _SCHEMA_VERSION,
            "sequence": len(events) + 1,
            "aggregate_id": task_id,
            "aggregate_version": expected_version + 1,
            "expected_version": expected_version,
            "operation_id": operation_id,
            "event_id": f"hqe_{event_digest[:24]}",
            "event_digest": event_digest,
            "kind": kind,
            "recorded_at": recorded_at,
            "previous_record_sha256": events[-1]["record_sha256"],
            "payload": facts,
        }
        event["record_sha256"] = _record_digest(event)
        return event

    def show(self, task_id: str) -> dict[str, Any]:
        if not isinstance(task_id, str) or _TASK_ID_RE.fullmatch(task_id) is None:
            raise _invalid("task_id is invalid")
        projection = self._load_projection_from_journal()
        task = projection["tasks"].get(task_id)
        if task is None:
            raise ResearchWorkflowError("workflow_not_found", "workflow task was not found")
        return dict(task)

    def inventory_tasks(self) -> dict[str, Any]:
        """Return a validated, metadata-only snapshot of the HQA authority.

        The inventory is deliberately derived from the append-only journal,
        rather than trusting the replaceable projection.  Opening an absent
        authority uses ``create=False`` all the way down and therefore cannot
        manufacture files merely because an operator asked for an audit.
        """

        try:
            with self._locked(exclusive=False, create=False) as locked:
                if locked is None:
                    return {
                        "schema_version": _SCHEMA_VERSION,
                        "authority_state": "absent",
                        "last_sequence": 0,
                        "last_record_sha256": None,
                        "tasks": [],
                    }
                root_fd, journal_fd, _ = locked
                events = self._read_events(journal_fd, allow_empty=False)
                projection = self._projection_for_events(root_fd, events)
                safe_tasks: list[dict[str, Any]] = []
                for task in projection["tasks"].values():
                    prepared = task["preparation"]
                    observed = task.get("transport_binding")
                    safe_tasks.append(
                        {
                            "schema_version": prepared["schema_version"],
                            "workflow_saga_id": prepared["workflow_saga_id"],
                            "owner_user_id": prepared["owner_user_id"],
                            "platform_session_id": prepared[
                                "platform_session_id"
                            ],
                            "client_request_id": prepared["client_request_id"],
                            "command_kind": prepared["command_kind"],
                            "canonical_request_digest": prepared[
                                "canonical_request_digest"
                            ],
                            "payload_ref": prepared["payload_ref"],
                            "payload_digest": prepared["payload_digest"],
                            "payload_expires_at": prepared[
                                "payload_expires_at"
                            ],
                            "provider_policy_digest": prepared[
                                "provider_policy_digest"
                            ],
                            "task_id": prepared["task_id"],
                            "task_version": prepared["task_version"],
                            "attempt_id": prepared["attempt_id"],
                            "attempt_number": prepared["attempt_number"],
                            "prepared_event_id": prepared["prepared_event_id"],
                            "prepared_event_digest": prepared[
                                "prepared_event_digest"
                            ],
                            "plan_schema_version": prepared[
                                "plan_schema_version"
                            ],
                            "plan_version": prepared["plan_version"],
                            "plan_digest": prepared["plan_digest"],
                            "workflow_preparation_digest": prepared[
                                "workflow_preparation_digest"
                            ],
                            "payload_status": task["payload_status"],
                            "transport_binding": (
                                None
                                if observed is None
                                else {
                                    "command_id": observed["command_id"],
                                    "binding_digest": observed[
                                        "binding_digest"
                                    ],
                                    "workflow_preparation_digest": observed[
                                        "workflow_preparation_digest"
                                    ],
                                }
                            ),
                        }
                    )
                safe_tasks.sort(key=lambda item: item["workflow_saga_id"])
                return {
                    "schema_version": _SCHEMA_VERSION,
                    "authority_state": "present",
                    "last_sequence": projection["last_sequence"],
                    "last_record_sha256": projection[
                        "last_record_sha256"
                    ],
                    "tasks": safe_tasks,
                }
        except ResearchWorkflowError:
            raise
        except OSError as exc:
            raise ResearchWorkflowError(
                "workflow_storage_io_error",
                f"workflow authority inventory failed: {type(exc).__name__}",
                retryable=True,
            ) from exc

    def events(
        self,
        task_id: str,
        *,
        after_event_id: Optional[str] = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        if not isinstance(task_id, str) or _TASK_ID_RE.fullmatch(task_id) is None:
            raise _invalid("task_id is invalid")
        if after_event_id is not None and (
            not isinstance(after_event_id, str)
            or _EVENT_ID_RE.fullmatch(after_event_id) is None
        ):
            raise _invalid("after_event_id is invalid")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise _invalid("limit must be an integer from 1 to 500")
        with self._locked(exclusive=False, create=False) as locked:
            if locked is None:
                raise ResearchWorkflowError(
                    "workflow_not_found", "workflow task was not found"
                )
            _, journal_fd, _ = locked
            all_events = self._read_events(journal_fd, allow_empty=False)
        task_events = [event for event in all_events if event["aggregate_id"] == task_id]
        if not task_events:
            raise ResearchWorkflowError("workflow_not_found", "workflow task was not found")
        start = 0
        if after_event_id is not None:
            for index, event in enumerate(task_events):
                if event["event_id"] == after_event_id:
                    start = index + 1
                    break
            else:
                raise ResearchWorkflowError(
                    "workflow_event_cursor_unknown", "event cursor was not found"
                )
        selected = task_events[start : start + limit]
        has_more = start + len(selected) < len(task_events)
        return {
            "schema_version": _SCHEMA_VERSION,
            "task_id": task_id,
            "events": selected,
            "next_cursor": selected[-1]["event_id"] if has_more and selected else None,
        }

    def resolve_payload(self, payload_ref: str, *, as_of: Optional[str] = None) -> dict[str, Any]:
        """Resolve a verified payload for trusted local orchestration only."""
        match = _PAYLOAD_REF_RE.fullmatch(payload_ref) if isinstance(payload_ref, str) else None
        if match is None:
            raise _invalid("payload_ref is invalid")
        observed_at = _canonical_timestamp(as_of or self._now(), "as_of")
        digest = match.group(1)
        with self._locked(exclusive=False, create=False) as locked:
            if locked is None:
                raise ResearchWorkflowError(
                    "workflow_payload_not_found", "workflow payload was not found"
                )
            root_fd, journal_fd, _ = locked
            events = self._read_events(journal_fd, allow_empty=False)
            projection = self._projection_for_events(root_fd, events)
            matching = [
                task
                for task in projection["tasks"].values()
                if task["preparation"]["payload_ref"] == payload_ref
            ]
            if not matching:
                raise ResearchWorkflowError(
                    "workflow_payload_not_found", "workflow payload was not found"
                )
            task = matching[0]
            if task["payload_status"] in {"deletion_pending", "deleted"}:
                raise ResearchWorkflowError(
                    "workflow_payload_deleted", "workflow payload has been deleted"
                )
            if _parse_timestamp(observed_at) >= _parse_timestamp(
                task["preparation"]["payload_expires_at"]
            ):
                raise ResearchWorkflowError(
                    "workflow_payload_expired", "workflow payload has expired"
                )
            envelope = self._read_payload(root_fd, digest)
        if _parse_timestamp(observed_at) >= _parse_timestamp(envelope["expires_at"]):
            raise ResearchWorkflowError(
                "workflow_payload_expired", "workflow payload has expired"
            )
        return envelope

    def _load_projection_from_journal(self) -> dict[str, Any]:
        with self._locked(exclusive=False, create=False) as locked:
            if locked is None:
                return self._empty_projection()
            root_fd, journal_fd, _ = locked
            events = self._read_events(journal_fd, allow_empty=False)
            return self._projection_for_events(root_fd, events)

    @staticmethod
    def _empty_projection() -> dict[str, Any]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "last_sequence": 0,
            "last_record_sha256": None,
            "tasks": {},
        }

    def _projection_for_events(
        self,
        root_fd: int,
        events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        payloads: dict[str, dict[str, Any]] = {}
        unavailable_payload_tasks = {
            event["aggregate_id"]
            for event in events
            if event["kind"]
            in {"payload_deletion_requested", "payload_deletion_completed"}
        }
        for event in events:
            if (
                event["kind"] == "workflow_prepared"
                and event["aggregate_id"] not in unavailable_payload_tasks
            ):
                payloads[event["aggregate_id"]] = self._verify_payload_for_receipt(
                    root_fd,
                    event["payload"],
                )
        return self._reduce(events, payloads)

    def _reduce(
        self,
        events: list[dict[str, Any]],
        payloads: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        projection = self._empty_projection()
        tasks: dict[str, dict[str, Any]] = projection["tasks"]
        for event in events:
            task_id = event["aggregate_id"]
            if event["kind"] == "workflow_prepared":
                receipt = event["payload"]
                if task_id in tasks:
                    raise _corrupt("workflow task was prepared more than once")
                tasks[task_id] = {
                    "schema_version": _SCHEMA_VERSION,
                    "task_id": task_id,
                    "session_id": receipt["platform_session_id"],
                    "parent_task_id": None,
                    # Plan text is sensitive payload data and may repeat the
                    # prompt verbatim. Only its digest/version is projected.
                    "goal": None,
                    "version": 1,
                    "plan_version": receipt["plan_version"],
                    "plan_digest": receipt["plan_digest"],
                    "state": "awaiting_transport_binding",
                    "active_attempt": {
                        "attempt_id": receipt["attempt_id"],
                        "attempt_number": receipt["attempt_number"],
                        "state": "planned",
                        "hermes_run_id": None,
                        "step_refs": [],
                        "provider_evidence": None,
                        "started_at": None,
                        "finished_at": None,
                    },
                    "gate_refs": [],
                    "result_refs": [],
                    "transport_binding": None,
                    "payload_status": "available",
                    "payload_deletion": None,
                    "preparation": receipt,
                    "created_at": event["recorded_at"],
                    "updated_at": event["recorded_at"],
                    "last_event_id": event["event_id"],
                    "last_record_sha256": event["record_sha256"],
                }
            elif event["kind"] == "transport_binding_observed":
                task = tasks.get(task_id)
                if task is None:
                    raise _corrupt("transport binding has no prepared workflow task")
                if (
                    event["expected_version"] != task["version"]
                    or event["aggregate_version"] != task["version"] + 1
                    or task["transport_binding"] is not None
                    or task["state"]
                    not in {
                        "awaiting_transport_binding",
                        "payload_expired",
                        "payload_deletion_pending",
                        "payload_deleted",
                    }
                ):
                    raise _corrupt("transport binding violates workflow state or CAS")
                binding = event["payload"]
                if (
                    binding["workflow_preparation_digest"]
                    != task["preparation"]["workflow_preparation_digest"]
                    or binding["binding_digest"]
                    != transport_binding_digest(
                        task["preparation"], binding["command_id"]
                    )
                ):
                    raise _corrupt("transport binding does not match preparation")
                payload_expired = _parse_timestamp(
                    event["recorded_at"]
                ) >= _parse_timestamp(task["preparation"]["payload_expires_at"])
                if task["payload_status"] == "deleted":
                    next_state = "payload_deleted"
                elif task["payload_status"] == "deletion_pending":
                    next_state = "payload_deletion_pending"
                elif payload_expired:
                    next_state = "payload_expired"
                    task["payload_status"] = "expired"
                else:
                    next_state = "ready"
                task.update(
                    {
                        "version": event["aggregate_version"],
                        "state": next_state,
                        "transport_binding": {
                            **binding,
                            "observed_at": event["recorded_at"],
                        },
                        "updated_at": event["recorded_at"],
                        "last_event_id": event["event_id"],
                        "last_record_sha256": event["record_sha256"],
                    }
                )
            elif event["kind"] == "payload_deletion_requested":
                task = tasks.get(task_id)
                if task is None:
                    raise _corrupt("payload deletion has no prepared workflow task")
                if (
                    event["expected_version"] != task["version"]
                    or event["aggregate_version"] != task["version"] + 1
                    or task["payload_status"] in {"deletion_pending", "deleted"}
                ):
                    raise _corrupt("payload deletion request violates workflow state or CAS")
                deletion = event["payload"]
                preparation = task["preparation"]
                if (
                    deletion["payload_ref"] != preparation["payload_ref"]
                    or deletion["payload_digest"] != preparation["payload_digest"]
                    or deletion["payload_expires_at"]
                    != preparation["payload_expires_at"]
                    or deletion["workflow_preparation_digest"]
                    != preparation["workflow_preparation_digest"]
                    or _parse_timestamp(event["recorded_at"])
                    < _parse_timestamp(preparation["payload_expires_at"])
                ):
                    raise _corrupt("payload deletion request does not match preparation")
                task.update(
                    {
                        "version": event["aggregate_version"],
                        "state": "payload_deletion_pending",
                        "goal": None,
                        "payload_status": "deletion_pending",
                        "payload_deletion": {
                            "requested_event_id": event["event_id"],
                            "requested_at": event["recorded_at"],
                            "completed_event_id": None,
                            "completed_at": None,
                        },
                        "updated_at": event["recorded_at"],
                        "last_event_id": event["event_id"],
                        "last_record_sha256": event["record_sha256"],
                    }
                )
            elif event["kind"] == "payload_deletion_completed":
                task = tasks.get(task_id)
                if task is None or task.get("payload_deletion") is None:
                    raise _corrupt("payload deletion completion has no request")
                if (
                    event["expected_version"] != task["version"]
                    or event["aggregate_version"] != task["version"] + 1
                    or task["payload_status"] != "deletion_pending"
                    or event["payload"]["deletion_request_event_id"]
                    != task["payload_deletion"]["requested_event_id"]
                ):
                    raise _corrupt("payload deletion completion violates workflow state or CAS")
                preparation = task["preparation"]
                if any(
                    event["payload"][field] != preparation[field]
                    for field in (
                        "payload_ref",
                        "payload_digest",
                        "payload_expires_at",
                        "workflow_preparation_digest",
                    )
                ):
                    raise _corrupt("payload deletion completion does not match preparation")
                task.update(
                    {
                        "version": event["aggregate_version"],
                        "state": "payload_deleted",
                        "goal": None,
                        "payload_status": "deleted",
                        "updated_at": event["recorded_at"],
                        "last_event_id": event["event_id"],
                        "last_record_sha256": event["record_sha256"],
                    }
                )
                task["payload_deletion"].update(
                    {
                        "completed_event_id": event["event_id"],
                        "completed_at": event["recorded_at"],
                    }
                )
            elif event["kind"] in {
                "orphan_payload_deletion_requested",
                "orphan_payload_deletion_completed",
            }:
                # These payloads crashed before a Task aggregate existed.
                # Their audit records belong to this canonical journal but do
                # not fabricate a user-visible Task.
                pass
            else:
                raise _corrupt("workflow event type is unsupported")
            projection["last_sequence"] = event["sequence"]
            projection["last_record_sha256"] = event["record_sha256"]
        return projection

    @staticmethod
    def _validate_receipt(receipt: Any) -> None:
        if not isinstance(receipt, dict) or set(receipt) != _RECEIPT_FIELDS:
            raise _corrupt("workflow preparation receipt fields are invalid")
        if (
            receipt["schema_version"] != _SCHEMA_VERSION
            or receipt["owner_user_id"] != _OWNER_USER_ID
            or receipt["command_kind"] != _COMMAND_KIND
            or not isinstance(receipt["platform_session_id"], str)
            or _SESSION_ID_RE.fullmatch(receipt["platform_session_id"]) is None
            or not isinstance(receipt["client_request_id"], str)
            or _CLIENT_REQUEST_ID_RE.fullmatch(receipt["client_request_id"]) is None
            or not isinstance(receipt["workflow_saga_id"], str)
            or _SAGA_ID_RE.fullmatch(receipt["workflow_saga_id"]) is None
            or not isinstance(receipt["task_id"], str)
            or _TASK_ID_RE.fullmatch(receipt["task_id"]) is None
            or not isinstance(receipt["attempt_id"], str)
            or _ATTEMPT_ID_RE.fullmatch(receipt["attempt_id"]) is None
            or not isinstance(receipt["prepared_event_id"], str)
            or _EVENT_ID_RE.fullmatch(receipt["prepared_event_id"]) is None
        ):
            raise _corrupt("workflow preparation receipt identity is invalid")
        for field in (
            "canonical_request_digest",
            "payload_digest",
            "provider_policy_digest",
            "prepared_event_digest",
            "plan_digest",
            "workflow_preparation_digest",
        ):
            value = receipt[field]
            if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
                raise _corrupt(f"workflow preparation {field} is invalid")
        payload_match = (
            _PAYLOAD_REF_RE.fullmatch(receipt["payload_ref"])
            if isinstance(receipt["payload_ref"], str)
            else None
        )
        if payload_match is None or payload_match.group(1) != receipt["payload_digest"]:
            raise _corrupt("workflow preparation payload identity is invalid")
        if (
            type(receipt["task_version"]) is not int
            or receipt["task_version"] != 1
            or type(receipt["attempt_number"]) is not int
            or receipt["attempt_number"] != 1
            or type(receipt["plan_schema_version"]) is not int
            or receipt["plan_schema_version"] != _PLAN_SCHEMA_VERSION
            or type(receipt["plan_version"]) is not int
            or receipt["plan_version"] != 1
        ):
            raise _corrupt("workflow preparation version is invalid")
        canonical_expiry = _canonical_timestamp(
            receipt["payload_expires_at"], "payload_expires_at", stored=True
        )
        if canonical_expiry != receipt["payload_expires_at"]:
            raise _corrupt("workflow preparation payload_expires_at is not canonical")
        expected_event_digest = _sha256(_prepared_event_basis(receipt))
        if (
            receipt["prepared_event_digest"] != expected_event_digest
            or receipt["prepared_event_id"] != f"hqe_{expected_event_digest[:24]}"
        ):
            raise _corrupt("workflow prepared event identity does not match")
        if receipt["workflow_preparation_digest"] != _preparation_digest(receipt):
            raise _corrupt("workflow preparation digest does not match")

    def _read_events(self, fd: int, *, allow_empty: bool) -> list[dict[str, Any]]:
        metadata = os.fstat(fd)
        if metadata.st_size > _MAX_JOURNAL_BYTES:
            raise _corrupt("workflow journal exceeds the supported size")
        os.lseek(fd, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, 65_536)
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_JOURNAL_BYTES:
                raise _corrupt("workflow journal exceeds the supported size")
            chunks.append(chunk)
        raw = b"".join(chunks)
        if not raw:
            if allow_empty:
                return []
            raise _corrupt("workflow journal exists but is empty")
        if not raw.endswith(b"\n"):
            raise _corrupt("workflow journal has a torn final line")
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise _corrupt("workflow journal is not valid UTF-8") from exc
        events: list[dict[str, Any]] = []
        previous_record_sha256: Optional[str] = None
        for line_number, line in enumerate(text[:-1].split("\n"), start=1):
            if not line:
                raise _corrupt(f"workflow journal line {line_number} is blank")
            if len(line.encode("utf-8")) > _MAX_EVENT_BYTES:
                raise _corrupt(f"workflow journal line {line_number} is too large")
            try:
                event = json.loads(
                    line,
                    object_pairs_hook=_object_without_duplicate_keys,
                    parse_constant=_reject_json_constant,
                )
            except ResearchWorkflowError:
                raise
            except (json.JSONDecodeError, UnicodeError, ValueError, RecursionError) as exc:
                raise _corrupt(
                    f"workflow journal line {line_number} is invalid JSON"
                ) from exc
            self._validate_event(
                event,
                expected_sequence=line_number,
                previous_record_sha256=previous_record_sha256,
            )
            previous_record_sha256 = event["record_sha256"]
            events.append(event)
        seen_event_ids: set[str] = set()
        seen_operations: set[str] = set()
        aggregate_versions: dict[str, int] = {}
        orphan_requests: dict[str, dict[str, Any]] = {}
        for event in events:
            if event["event_id"] in seen_event_ids:
                raise _corrupt("workflow event_id is duplicated")
            if event["operation_id"] in seen_operations:
                raise _corrupt("workflow operation_id is duplicated")
            current_version = aggregate_versions.get(event["aggregate_id"], 0)
            if (
                event["expected_version"] != current_version
                or event["aggregate_version"] != current_version + 1
            ):
                raise _corrupt("workflow aggregate event sequence violates CAS")
            seen_event_ids.add(event["event_id"])
            seen_operations.add(event["operation_id"])
            aggregate_versions[event["aggregate_id"]] = event["aggregate_version"]
            if event["kind"] == "orphan_payload_deletion_requested":
                digest = event["payload"]["payload_digest"]
                if digest in orphan_requests:
                    raise _corrupt("orphan payload deletion was requested more than once")
                orphan_requests[digest] = event
            elif event["kind"] == "orphan_payload_deletion_completed":
                digest = event["payload"]["payload_digest"]
                requested = orphan_requests.get(digest)
                if (
                    requested is None
                    or event["payload"]["deletion_request_event_id"]
                    != requested["event_id"]
                    or any(
                        event["payload"][field] != requested["payload"][field]
                        for field in (
                            "owner_user_id",
                            "platform_session_id",
                            "client_request_id",
                            "command_kind",
                            "payload_ref",
                            "payload_digest",
                            "payload_expires_at",
                            "canonical_request_digest",
                        )
                    )
                ):
                    raise _corrupt("orphan payload deletion completion has no exact request")
        return events

    def _validate_event(
        self,
        event: Any,
        *,
        expected_sequence: int,
        previous_record_sha256: Optional[str],
    ) -> None:
        expected_fields = {
            "schema_version",
            "sequence",
            "aggregate_id",
            "aggregate_version",
            "expected_version",
            "operation_id",
            "event_id",
            "event_digest",
            "kind",
            "recorded_at",
            "previous_record_sha256",
            "payload",
            "record_sha256",
        }
        if not isinstance(event, dict) or set(event) != expected_fields:
            raise _corrupt("workflow event fields are invalid")
        if (
            event["schema_version"] != _SCHEMA_VERSION
            or type(event["sequence"]) is not int
            or event["sequence"] != expected_sequence
            or event["previous_record_sha256"] != previous_record_sha256
            or not isinstance(event["aggregate_id"], str)
            or (
                _TASK_ID_RE.fullmatch(event["aggregate_id"]) is None
                and _ORPHAN_AGGREGATE_ID_RE.fullmatch(event["aggregate_id"])
                is None
            )
            or not isinstance(event["aggregate_version"], int)
            or isinstance(event["aggregate_version"], bool)
            or not isinstance(event["expected_version"], int)
            or isinstance(event["expected_version"], bool)
            or not isinstance(event["operation_id"], str)
            or not isinstance(event["event_id"], str)
            or _EVENT_ID_RE.fullmatch(event["event_id"]) is None
            or not isinstance(event["event_digest"], str)
            or _SHA256_RE.fullmatch(event["event_digest"]) is None
        ):
            raise _corrupt("workflow event identity or hash chain is invalid")

        if event["kind"] == "workflow_prepared":
            if event["aggregate_version"] != 1 or event["expected_version"] != 0:
                raise _corrupt("workflow prepared event version is invalid")
            self._validate_receipt(event["payload"])
            receipt = event["payload"]
            if (
                event["aggregate_id"] != receipt["task_id"]
                or event["operation_id"] != receipt["workflow_saga_id"]
                or event["event_id"] != receipt["prepared_event_id"]
                or event["event_digest"] != receipt["prepared_event_digest"]
            ):
                raise _corrupt("workflow prepared event identity is invalid")
        elif event["kind"] == "transport_binding_observed":
            if (
                event["expected_version"] < 1
                or event["aggregate_version"] != event["expected_version"] + 1
            ):
                raise _corrupt("workflow transport binding version is invalid")
            payload = event["payload"]
            if not isinstance(payload, dict) or set(payload) != {
                "schema_version",
                "command_id",
                "binding_digest",
                "workflow_preparation_digest",
            }:
                raise _corrupt("workflow transport binding fields are invalid")
            command_id = payload.get("command_id")
            try:
                canonical_command_id = str(UUID(command_id))
            except (ValueError, AttributeError, TypeError) as exc:
                raise _corrupt("workflow transport command_id is invalid") from exc
            if (
                payload["schema_version"] != _SCHEMA_VERSION
                or canonical_command_id != command_id
                or not isinstance(payload["binding_digest"], str)
                or _SHA256_RE.fullmatch(payload["binding_digest"]) is None
                or not isinstance(payload["workflow_preparation_digest"], str)
                or _SHA256_RE.fullmatch(payload["workflow_preparation_digest"]) is None
            ):
                raise _corrupt("workflow transport binding identity is invalid")
            operation_id = f"bind:{event['aggregate_id']}:{command_id}"
            semantic = {
                "schema_version": _SCHEMA_VERSION,
                "kind": "transport_binding_observed",
                "aggregate_id": event["aggregate_id"],
                "aggregate_version": event["aggregate_version"],
                "expected_version": event["expected_version"],
                "operation_id": operation_id,
                "facts": payload,
            }
            expected_event_digest = _sha256(semantic)
            if (
                event["operation_id"] != operation_id
                or event["event_digest"] != expected_event_digest
                or event["event_id"] != f"hqe_{expected_event_digest[:24]}"
            ):
                raise _corrupt("workflow transport binding event identity is invalid")
        elif event["kind"] in {
            "payload_deletion_requested",
            "payload_deletion_completed",
        }:
            if (
                event["expected_version"] < 1
                or event["aggregate_version"] != event["expected_version"] + 1
            ):
                raise _corrupt("workflow payload deletion version is invalid")
            expected_payload_fields = {
                "schema_version",
                "payload_ref",
                "payload_digest",
                "payload_expires_at",
                "workflow_preparation_digest",
            }
            if event["kind"] == "payload_deletion_completed":
                expected_payload_fields.add("deletion_request_event_id")
            payload = event["payload"]
            payload_match = (
                _PAYLOAD_REF_RE.fullmatch(payload.get("payload_ref", ""))
                if isinstance(payload, dict)
                else None
            )
            if (
                not isinstance(payload, dict)
                or set(payload) != expected_payload_fields
                or payload.get("schema_version") != _SCHEMA_VERSION
                or payload_match is None
                or payload_match.group(1) != payload.get("payload_digest")
                or not isinstance(payload.get("workflow_preparation_digest"), str)
                or _SHA256_RE.fullmatch(payload["workflow_preparation_digest"])
                is None
            ):
                raise _corrupt("workflow payload deletion identity is invalid")
            canonical_expiry = _canonical_timestamp(
                payload["payload_expires_at"],
                "payload_expires_at",
                stored=True,
            )
            if canonical_expiry != payload["payload_expires_at"]:
                raise _corrupt("workflow payload deletion expiry is not canonical")
            if event["kind"] == "payload_deletion_requested":
                operation_id = f"delete-request:{event['aggregate_id']}:{payload['payload_digest']}"
            else:
                request_event_id = payload["deletion_request_event_id"]
                if (
                    not isinstance(request_event_id, str)
                    or _EVENT_ID_RE.fullmatch(request_event_id) is None
                ):
                    raise _corrupt("workflow payload deletion request reference is invalid")
                operation_id = f"delete-complete:{event['aggregate_id']}:{payload['payload_digest']}"
            semantic = {
                "schema_version": _SCHEMA_VERSION,
                "kind": event["kind"],
                "aggregate_id": event["aggregate_id"],
                "aggregate_version": event["aggregate_version"],
                "expected_version": event["expected_version"],
                "operation_id": operation_id,
                "facts": payload,
            }
            expected_event_digest = _sha256(semantic)
            if (
                event["operation_id"] != operation_id
                or event["event_digest"] != expected_event_digest
                or event["event_id"] != f"hqe_{expected_event_digest[:24]}"
            ):
                raise _corrupt("workflow payload deletion event identity is invalid")
        elif event["kind"] in {
            "orphan_payload_deletion_requested",
            "orphan_payload_deletion_completed",
        }:
            if _ORPHAN_AGGREGATE_ID_RE.fullmatch(event["aggregate_id"]) is None:
                raise _corrupt("orphan payload deletion aggregate is invalid")
            completed = event["kind"] == "orphan_payload_deletion_completed"
            if (
                event["expected_version"] != (1 if completed else 0)
                or event["aggregate_version"] != (2 if completed else 1)
            ):
                raise _corrupt("orphan payload deletion version is invalid")
            expected_payload_fields = {
                "schema_version",
                "owner_user_id",
                "platform_session_id",
                "client_request_id",
                "command_kind",
                "payload_ref",
                "payload_digest",
                "payload_expires_at",
                "canonical_request_digest",
            }
            if completed:
                expected_payload_fields.add("deletion_request_event_id")
            payload = event["payload"]
            payload_match = (
                _PAYLOAD_REF_RE.fullmatch(payload.get("payload_ref", ""))
                if isinstance(payload, dict)
                else None
            )
            if (
                not isinstance(payload, dict)
                or set(payload) != expected_payload_fields
                or payload.get("schema_version") != _SCHEMA_VERSION
                or payload.get("owner_user_id") != _OWNER_USER_ID
                or not isinstance(payload.get("platform_session_id"), str)
                or _SESSION_ID_RE.fullmatch(payload["platform_session_id"])
                is None
                or not isinstance(payload.get("client_request_id"), str)
                or _CLIENT_REQUEST_ID_RE.fullmatch(payload["client_request_id"])
                is None
                or payload.get("command_kind") != _COMMAND_KIND
                or payload_match is None
                or payload_match.group(1) != payload.get("payload_digest")
                or not isinstance(payload.get("canonical_request_digest"), str)
                or _SHA256_RE.fullmatch(payload["canonical_request_digest"])
                is None
            ):
                raise _corrupt("orphan payload deletion identity is invalid")
            canonical_expiry = _canonical_timestamp(
                payload["payload_expires_at"],
                "payload_expires_at",
                stored=True,
            )
            if canonical_expiry != payload["payload_expires_at"]:
                raise _corrupt("orphan payload deletion expiry is not canonical")
            aggregate_id = (
                f"hqo_{_sha256(['orphan-payload', payload['payload_digest']])[:24]}"
            )
            operation_id = (
                f"orphan-delete-complete:{payload['payload_digest']}"
                if completed
                else f"orphan-delete-request:{payload['payload_digest']}"
            )
            if completed:
                request_event_id = payload["deletion_request_event_id"]
                if (
                    not isinstance(request_event_id, str)
                    or _EVENT_ID_RE.fullmatch(request_event_id) is None
                ):
                    raise _corrupt("orphan deletion request reference is invalid")
            semantic = {
                "schema_version": _SCHEMA_VERSION,
                "kind": event["kind"],
                "aggregate_id": aggregate_id,
                "aggregate_version": event["aggregate_version"],
                "expected_version": event["expected_version"],
                "operation_id": operation_id,
                "facts": payload,
            }
            expected_event_digest = _sha256(semantic)
            if (
                event["aggregate_id"] != aggregate_id
                or event["operation_id"] != operation_id
                or event["event_digest"] != expected_event_digest
                or event["event_id"] != f"hqe_{expected_event_digest[:24]}"
            ):
                raise _corrupt("orphan payload deletion event identity is invalid")
        else:
            raise _corrupt("workflow event kind is unsupported")
        canonical_recorded_at = _canonical_timestamp(
            event["recorded_at"], "recorded_at", stored=True
        )
        if canonical_recorded_at != event["recorded_at"]:
            raise _corrupt("workflow event recorded_at is not canonical")
        if (
            not isinstance(event["record_sha256"], str)
            or _SHA256_RE.fullmatch(event["record_sha256"]) is None
            or event["record_sha256"] != _record_digest(event)
        ):
            raise _corrupt("workflow event record digest does not match")

    def _append_event(self, fd: int, event: dict[str, Any]) -> None:
        payload = _canonical_bytes(event)
        if len(payload) > _MAX_EVENT_BYTES:
            raise _invalid("workflow event exceeds the maximum size")
        original_size = os.lseek(fd, 0, os.SEEK_END)
        try:
            view = memoryview(payload)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("workflow journal append made no progress")
                view = view[written:]
        except OSError as write_error:
            try:
                os.ftruncate(fd, original_size)
                os.fsync(fd)
            except OSError as rollback_error:
                raise ResearchWorkflowError(
                    "workflow_durability_unknown",
                    "workflow append failed and rollback could not be confirmed",
                ) from rollback_error
            raise write_error
        try:
            os.fsync(fd)
        except OSError as exc:
            raise ResearchWorkflowError(
                "workflow_durability_unknown",
                "workflow event was appended but fsync could not be confirmed",
            ) from exc

    @contextmanager
    def _locked(
        self,
        *,
        exclusive: bool,
        create: bool,
    ) -> Iterator[Optional[tuple[int, int, int]]]:
        root_fd = self._open_root(create=create)
        if root_fd is None:
            yield None
            return
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        journal_exists = self._entry_exists(root_fd, "events.v1.jsonl")
        lock_exists = self._entry_exists(root_fd, ".ledger.lock")
        # Refresh once when initialization may be racing us.  A canonical name
        # can appear between the individual stats and directory enumeration;
        # it is not a remnant until examined under the stable lock below.
        if not journal_exists and not lock_exists:
            entries = set(os.listdir(root_fd))
            if entries:
                journal_exists = self._entry_exists(root_fd, "events.v1.jsonl")
                lock_exists = self._entry_exists(root_fd, ".ledger.lock")
                if not journal_exists and not lock_exists:
                    os.close(root_fd)
                    raise _corrupt(
                        "workflow canonical authority is missing while remnants remain"
                    )
        if journal_exists and not lock_exists:
            os.close(root_fd)
            raise _corrupt("workflow journal exists without its stable lock")
        if not journal_exists and not lock_exists and not create:
            os.close(root_fd)
            yield None
            return
        lock_flags = os.O_RDWR if create or exclusive else os.O_RDONLY
        if create and not lock_exists:
            lock_flags |= os.O_CREAT
        lock_flags |= no_follow
        try:
            lock_fd = os.open(".ledger.lock", lock_flags, 0o600, dir_fd=root_fd)
        except OSError as exc:
            os.close(root_fd)
            if exc.errno == errno.ELOOP:
                raise _insecure("workflow lock must not be a symbolic link") from exc
            raise
        journal_fd: Optional[int] = None
        acquired = False
        try:
            self._assert_secure_file(lock_fd, "workflow lock", mode=0o600)
            self._assert_path_identity(root_fd, ".ledger.lock", lock_fd, "workflow lock")
            operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
            deadline = time.monotonic() + self._lock_timeout_seconds
            while True:
                try:
                    fcntl.flock(lock_fd, operation | fcntl.LOCK_NB)
                    acquired = True
                    break
                except OSError as exc:
                    if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                        raise
                    if time.monotonic() >= deadline:
                        raise ResearchWorkflowError(
                            "workflow_ledger_busy",
                            "workflow ledger lock timed out",
                            retryable=True,
                        ) from exc
                    time.sleep(0.01)
            self._assert_path_identity(root_fd, ".ledger.lock", lock_fd, "workflow lock")
            ready = self._lock_is_ready(lock_fd)
            journal_exists = self._entry_exists(root_fd, "events.v1.jsonl")
            if ready and not journal_exists:
                raise _corrupt("workflow journal is missing while its ready lock remains")
            if not journal_exists and (
                set(os.listdir(root_fd)) - {".ledger.lock"}
            ):
                raise _corrupt(
                    "workflow canonical authority is missing while remnants remain"
                )
            if not journal_exists and not create:
                yield None
                return
            journal_flags = (
                os.O_RDWR | os.O_APPEND | os.O_CREAT
                if create
                else (os.O_RDWR | os.O_APPEND if exclusive else os.O_RDONLY)
            ) | no_follow
            try:
                journal_fd = os.open(
                    "events.v1.jsonl", journal_flags, 0o600, dir_fd=root_fd
                )
            except OSError as exc:
                if exc.errno == errno.ELOOP:
                    raise _insecure("workflow journal must not be a symbolic link") from exc
                raise
            self._assert_secure_file(journal_fd, "workflow journal", mode=0o600)
            self._assert_path_identity(
                root_fd, "events.v1.jsonl", journal_fd, "workflow journal"
            )
            if os.fstat(journal_fd).st_size == 0:
                entries = set(os.listdir(root_fd))
                projection_remains = "projection.v1.json" in entries or any(
                    entry.startswith(".projection.v1.json.")
                    and entry.endswith(".tmp")
                    for entry in entries
                )
                if ready or projection_remains:
                    raise _corrupt(
                        "workflow canonical journal is empty after authority initialization"
                    )
            os.fsync(root_fd)
            yield root_fd, journal_fd, lock_fd
        finally:
            if journal_fd is not None:
                os.close(journal_fd)
            if acquired:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                except OSError:
                    pass
            os.close(lock_fd)
            os.close(root_fd)

    def _open_root(self, *, create: bool) -> Optional[int]:
        absolute = self.root
        flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        current_fd = os.open(absolute.anchor or os.sep, flags)
        try:
            for index, component in enumerate(absolute.parts[1:]):
                if create:
                    try:
                        os.mkdir(component, 0o700, dir_fd=current_fd)
                        os.fsync(current_fd)
                    except FileExistsError:
                        pass
                try:
                    next_fd = os.open(component, flags, dir_fd=current_fd)
                except FileNotFoundError:
                    if not create:
                        os.close(current_fd)
                        return None
                    raise
                except OSError as exc:
                    if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                        raise _insecure(
                            "workflow authority root path chain must not contain symbolic links"
                        ) from exc
                    raise
                os.close(current_fd)
                current_fd = next_fd
                if index == len(absolute.parts[1:]) - 1:
                    metadata = os.fstat(current_fd)
                    if (
                        not stat.S_ISDIR(metadata.st_mode)
                        or stat.S_IMODE(metadata.st_mode) != 0o700
                        or metadata.st_uid != os.geteuid()
                    ):
                        raise _insecure(
                            "workflow root must be an owner-only regular directory"
                        )
            return current_fd
        except Exception:
            try:
                os.close(current_fd)
            except OSError:
                pass
            raise

    @staticmethod
    def _entry_exists(parent_fd: int, name: str) -> bool:
        try:
            os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            return True
        except FileNotFoundError:
            return False

    @staticmethod
    def _assert_secure_file(fd: int, label: str, *, mode: int) -> None:
        metadata = os.fstat(fd)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != mode
            or metadata.st_uid != os.geteuid()
            or metadata.st_nlink != 1
        ):
            raise _insecure(
                f"{label} must be an owner-only non-hardlinked regular file"
            )

    @staticmethod
    def _assert_path_identity(
        parent_fd: int,
        name: str,
        fd: int,
        label: str,
    ) -> None:
        opened = os.fstat(fd)
        try:
            current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except OSError as exc:
            raise _corrupt(f"{label} path disappeared after open") from exc
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise _corrupt(f"{label} path identity changed after open")

    @staticmethod
    def _lock_is_ready(fd: int) -> bool:
        os.lseek(fd, 0, os.SEEK_SET)
        raw = os.read(fd, len(_LOCK_READY_MARKER) + 1)
        if raw == b"":
            return False
        if raw == _LOCK_READY_MARKER:
            return True
        raise _corrupt("workflow lock state is invalid")

    @staticmethod
    def _mark_lock_ready(fd: int) -> None:
        if ResearchWorkflowStore._lock_is_ready(fd):
            return
        os.lseek(fd, 0, os.SEEK_SET)
        view = memoryview(_LOCK_READY_MARKER)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("workflow lock write made no progress")
            view = view[written:]
        os.ftruncate(fd, len(_LOCK_READY_MARKER))
        os.fsync(fd)

    def _payload_dir_fd(self, root_fd: int, *, create: bool) -> int:
        flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
        if create:
            try:
                os.mkdir("payloads", 0o700, dir_fd=root_fd)
                os.fsync(root_fd)
            except FileExistsError:
                pass
        try:
            fd = os.open("payloads", flags, dir_fd=root_fd)
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise _insecure("workflow payload directory must not be a symlink") from exc
            raise
        metadata = os.fstat(fd)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o700
            or metadata.st_uid != os.geteuid()
        ):
            os.close(fd)
            raise _insecure("workflow payload directory must be owner-only")
        return fd

    def _find_reusable_orphan_payload(
        self,
        root_fd: int,
        normalized_request: dict[str, Any],
        events: list[dict[str, Any]],
    ) -> Optional[dict[str, Any]]:
        """Find the one safely published payload from a pre-journal crash.

        Reusing its immutable created/expiry timestamps makes retry converge on
        the original content digest instead of leaking a second sensitive
        orphan on every attempt.
        """

        if not self._entry_exists(root_fd, "payloads"):
            return None
        self._recover_prelink_payloads(root_fd)
        payload_dir_fd = self._payload_dir_fd(root_fd, create=False)
        try:
            entries = os.listdir(payload_dir_fd)
        finally:
            os.close(payload_dir_fd)
        referenced = {
            event["payload"]["payload_digest"]
            for event in events
            if event["kind"] == "workflow_prepared"
        }
        request_digest = _sha256(normalized_request)
        candidates: list[dict[str, Any]] = []
        for entry in sorted(entries):
            match = re.fullmatch(r"([0-9a-f]{64})\.json", entry)
            if match is None or match.group(1) in referenced:
                continue
            self._normalize_accounted_payload_links(root_fd, match.group(1))
            envelope = self._read_payload(root_fd, match.group(1))
            same_client_identity = (
                envelope["owner_user_id"] == _OWNER_USER_ID
                and envelope["platform_session_id"]
                == normalized_request["platform_session_id"]
                and envelope["client_request_id"]
                == normalized_request["client_request_id"]
            )
            if (
                same_client_identity
                and envelope["canonical_request_digest"] != request_digest
            ):
                raise ResearchWorkflowError(
                    "workflow_idempotency_conflict",
                    "client_request_id already belongs to a different workflow intent",
                )
            if envelope["canonical_request_digest"] != request_digest:
                continue
            reconstructed = {
                "schema_version": _SCHEMA_VERSION,
                "owner_user_id": _OWNER_USER_ID,
                "platform_session_id": envelope["platform_session_id"],
                "client_request_id": envelope["client_request_id"],
                "command_kind": _COMMAND_KIND,
                "payload_ttl_days": envelope["payload_ttl_days"],
                "prompt": envelope["prompt"],
                "provider_policy": envelope["provider_policy"],
                "plan": envelope["plan"],
            }
            if reconstructed != normalized_request:
                raise _corrupt("workflow orphan request digest is ambiguous")
            candidates.append(envelope)
        if len(candidates) > 1:
            raise _corrupt("multiple reusable workflow payload orphans were found")
        return candidates[0] if candidates else None

    def _recover_prelink_payloads(self, root_fd: int) -> None:
        """Finish durable temp->final publication after a pre-link crash.

        Temp files contain the same canonical envelope and digest as their final
        name.  Publishing them here preserves the original TTL for an exact
        retry and prevents sensitive, untracked temp files from accumulating.
        """

        if not self._entry_exists(root_fd, "payloads"):
            return
        payload_dir_fd = self._payload_dir_fd(root_fd, create=False)
        try:
            entries = os.listdir(payload_dir_fd)
            groups: dict[str, list[str]] = {}
            for entry in entries:
                match = re.fullmatch(
                    r"\.payload\.([0-9a-f]{64})\.[A-Za-z0-9-]{1,128}\.tmp",
                    entry,
                )
                if match is not None:
                    groups.setdefault(match.group(1), []).append(entry)
            for digest, temporary_names in sorted(groups.items()):
                final_name = f"{digest}.json"
                if self._entry_exists(payload_dir_fd, final_name):
                    self._normalize_accounted_payload_links(root_fd, digest)
                    continue
                expected_raw: Optional[bytes] = None
                invalid_temps: list[str] = []
                valid_temps: list[str] = []
                for temporary in sorted(temporary_names):
                    raw = self._read_payload_bytes(payload_dir_fd, temporary)
                    try:
                        if _sha256_bytes(raw) != digest:
                            raise _corrupt("workflow payload temp digest does not match")
                        self._decode_payload_bytes(raw, digest)
                    except ResearchWorkflowError as exc:
                        if exc.code != "workflow_ledger_corrupt":
                            raise
                        # This private temp was never published. A hard kill
                        # during write may leave any prefix (including empty),
                        # so erase the untracked sensitive fragment instead of
                        # poisoning the entire authority.
                        invalid_temps.append(temporary)
                        continue
                    if expected_raw is not None and raw != expected_raw:
                        raise _corrupt("workflow payload temp content is ambiguous")
                    expected_raw = raw
                    valid_temps.append(temporary)
                for temporary in invalid_temps:
                    os.unlink(temporary, dir_fd=payload_dir_fd)
                if invalid_temps:
                    os.fsync(payload_dir_fd)
                if expected_raw is None:
                    continue
                first = valid_temps[0]
                os.link(
                    first,
                    final_name,
                    src_dir_fd=payload_dir_fd,
                    dst_dir_fd=payload_dir_fd,
                    follow_symlinks=False,
                )
                os.fsync(payload_dir_fd)
                for temporary in valid_temps:
                    os.unlink(temporary, dir_fd=payload_dir_fd)
                os.fsync(payload_dir_fd)
                final_raw = self._read_payload_bytes(payload_dir_fd, final_name)
                if final_raw != expected_raw:
                    raise _corrupt("workflow recovered payload content changed")
        finally:
            os.close(payload_dir_fd)

    def _delete_expired_orphan_payloads(
        self,
        root_fd: int,
        *,
        journal_fd: int,
        events: list[dict[str, Any]],
        projection: dict[str, Any],
        observed_at: str,
        limit: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
        """Durably audit and delete payloads that predate their Task event."""

        if not self._entry_exists(root_fd, "payloads"):
            return events, projection, {"deleted": [], "has_more": False}
        referenced = {
            event["payload"]["payload_digest"]
            for event in events
            if event["kind"] == "workflow_prepared"
        }
        payload_dir_fd = self._payload_dir_fd(root_fd, create=False)
        try:
            entries = os.listdir(payload_dir_fd)
        finally:
            os.close(payload_dir_fd)
        orphan_digests = sorted(
            match.group(1)
            for entry in entries
            if (match := re.fullmatch(r"([0-9a-f]{64})\.json", entry)) is not None
            and match.group(1) not in referenced
        )
        audits: dict[str, dict[str, Any]] = {}
        for event in events:
            if event["kind"] == "orphan_payload_deletion_requested":
                audits[event["payload"]["payload_digest"]] = {
                    "request": event,
                    "completed": False,
                }
            elif event["kind"] == "orphan_payload_deletion_completed":
                audit = audits.get(event["payload"]["payload_digest"])
                if audit is None:
                    raise _corrupt("orphan deletion completion has no request")
                audit["completed"] = True

        expired: dict[str, dict[str, Any]] = {}
        for digest in orphan_digests:
            audit = audits.get(digest)
            if audit is not None and audit["completed"]:
                raise _corrupt("an audited-deleted orphan payload reappeared")
            self._normalize_accounted_payload_links(root_fd, digest)
            envelope = self._read_payload(root_fd, digest)
            if _parse_timestamp(observed_at) >= _parse_timestamp(
                envelope["expires_at"]
            ):
                expired[digest] = envelope

        pending = {
            digest: audit
            for digest, audit in audits.items()
            if not audit["completed"]
        }
        work = sorted(set(expired) | set(pending))
        deleted: list[str] = []
        for digest in work[:limit]:
            audit = pending.get(digest)
            if audit is None:
                envelope = expired[digest]
                facts = {
                    "schema_version": _SCHEMA_VERSION,
                    "owner_user_id": envelope["owner_user_id"],
                    "platform_session_id": envelope["platform_session_id"],
                    "client_request_id": envelope["client_request_id"],
                    "command_kind": envelope["kind"],
                    "payload_ref": f"hqa-payload:sha256:{digest}",
                    "payload_digest": digest,
                    "payload_expires_at": envelope["expires_at"],
                    "canonical_request_digest": envelope[
                        "canonical_request_digest"
                    ],
                }
                request_event = self._orphan_deletion_event(
                    events,
                    digest=digest,
                    kind="orphan_payload_deletion_requested",
                    facts=facts,
                    recorded_at=observed_at,
                )
                next_events = [*events, request_event]
                next_projection = self._projection_for_events(root_fd, next_events)
                self._append_event(journal_fd, request_event)
                self._publish_projection(root_fd, next_projection)
                events = next_events
                projection = next_projection
            else:
                request_event = audit["request"]
                facts = dict(request_event["payload"])
                if digest in expired:
                    envelope = expired[digest]
                    if (
                        envelope["expires_at"] != facts["payload_expires_at"]
                        or envelope["canonical_request_digest"]
                        != facts["canonical_request_digest"]
                    ):
                        raise _corrupt("pending orphan deletion facts changed")

            self._unlink_payload_if_present(root_fd, digest)
            completion_facts = {
                **facts,
                "deletion_request_event_id": request_event["event_id"],
            }
            completion_event = self._orphan_deletion_event(
                events,
                digest=digest,
                kind="orphan_payload_deletion_completed",
                facts=completion_facts,
                recorded_at=observed_at,
            )
            next_events = [*events, completion_event]
            next_projection = self._projection_for_events(root_fd, next_events)
            self._append_event(journal_fd, completion_event)
            self._publish_projection(root_fd, next_projection)
            events = next_events
            projection = next_projection
            deleted.append(digest)
        return events, projection, {"deleted": deleted, "has_more": len(work) > limit}

    @staticmethod
    def _orphan_deletion_event(
        events: list[dict[str, Any]],
        *,
        digest: str,
        kind: str,
        facts: dict[str, Any],
        recorded_at: str,
    ) -> dict[str, Any]:
        completed = kind == "orphan_payload_deletion_completed"
        aggregate_id = f"hqo_{_sha256(['orphan-payload', digest])[:24]}"
        operation_id = (
            f"orphan-delete-complete:{digest}"
            if completed
            else f"orphan-delete-request:{digest}"
        )
        semantic = {
            "schema_version": _SCHEMA_VERSION,
            "kind": kind,
            "aggregate_id": aggregate_id,
            "aggregate_version": 2 if completed else 1,
            "expected_version": 1 if completed else 0,
            "operation_id": operation_id,
            "facts": facts,
        }
        event_digest = _sha256(semantic)
        event = {
            "schema_version": _SCHEMA_VERSION,
            "sequence": len(events) + 1,
            "aggregate_id": aggregate_id,
            "aggregate_version": 2 if completed else 1,
            "expected_version": 1 if completed else 0,
            "operation_id": operation_id,
            "event_id": f"hqe_{event_digest[:24]}",
            "event_digest": event_digest,
            "kind": kind,
            "recorded_at": recorded_at,
            "previous_record_sha256": (
                events[-1]["record_sha256"] if events else None
            ),
            "payload": facts,
        }
        event["record_sha256"] = _record_digest(event)
        return event

    def _normalize_accounted_payload_links(self, root_fd: int, digest: str) -> None:
        """Close the final-link/temp-unlink crash window before orphan reads.

        Only private temp names for the same content digest are removable.  Any
        additional hard link outside that exact, enumerated set is an authority
        violation and remains fail-closed.
        """

        payload_dir_fd = self._payload_dir_fd(root_fd, create=False)
        final_name = f"{digest}.json"
        temp_prefix = f".payload.{digest}."
        try:
            final_metadata = os.stat(
                final_name,
                dir_fd=payload_dir_fd,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(final_metadata.st_mode)
                or stat.S_IMODE(final_metadata.st_mode) != 0o400
                or final_metadata.st_uid != os.geteuid()
            ):
                raise _insecure("workflow payload final file is insecure")
            temp_names = sorted(
                entry
                for entry in os.listdir(payload_dir_fd)
                if entry.startswith(temp_prefix) and entry.endswith(".tmp")
            )
            linked_temps: list[str] = []
            temp_metadata: dict[str, os.stat_result] = {}
            for temporary in temp_names:
                metadata = os.stat(
                    temporary,
                    dir_fd=payload_dir_fd,
                    follow_symlinks=False,
                )
                if (
                    not stat.S_ISREG(metadata.st_mode)
                    or stat.S_IMODE(metadata.st_mode) != 0o400
                    or metadata.st_uid != os.geteuid()
                ):
                    raise _insecure(
                        "workflow payload temp must be an owner-only regular file"
                    )
                temp_metadata[temporary] = metadata
                if (metadata.st_dev, metadata.st_ino) == (
                    final_metadata.st_dev,
                    final_metadata.st_ino,
                ):
                    linked_temps.append(temporary)
            if final_metadata.st_nlink != 1 + len(linked_temps):
                raise _insecure("workflow payload has an unaccounted hard link")
            for temporary, metadata in temp_metadata.items():
                if temporary not in linked_temps and metadata.st_nlink != 1:
                    raise _insecure("workflow payload temp has an unaccounted hard link")
                os.unlink(temporary, dir_fd=payload_dir_fd)
            if temp_metadata:
                os.fsync(payload_dir_fd)
        finally:
            os.close(payload_dir_fd)

    def _write_or_verify_payload(
        self,
        root_fd: int,
        digest: str,
        payload: bytes,
    ) -> None:
        payload_fd = self._payload_dir_fd(root_fd, create=True)
        name = f"{digest}.json"
        try:
            if self._recover_payload_publish(payload_fd, digest, payload):
                return

            temporary = f".payload.{digest}.{secrets.token_hex(12)}.tmp"
            flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
            )
            fd = os.open(temporary, flags, 0o400, dir_fd=payload_fd)
            try:
                os.fchmod(fd, 0o400)
                view = memoryview(payload)
                while view:
                    written = os.write(fd, view)
                    if written <= 0:
                        raise OSError("workflow payload write made no progress")
                    view = view[written:]
                os.fsync(fd)
                self._assert_secure_file(fd, "workflow payload temp", mode=0o400)
                self._assert_path_identity(
                    payload_fd,
                    temporary,
                    fd,
                    "workflow payload temp",
                )
            except Exception:
                try:
                    os.unlink(temporary, dir_fd=payload_fd)
                    os.fsync(payload_fd)
                except OSError:
                    pass
                raise
            finally:
                os.close(fd)

            try:
                os.link(
                    temporary,
                    name,
                    src_dir_fd=payload_fd,
                    dst_dir_fd=payload_fd,
                    follow_symlinks=False,
                )
                os.fsync(payload_fd)
            except FileExistsError:
                os.unlink(temporary, dir_fd=payload_fd)
                os.fsync(payload_fd)
                if not self._recover_payload_publish(payload_fd, digest, payload):
                    raise _corrupt("workflow payload publish lost its destination")
                return
            except Exception:
                try:
                    os.unlink(temporary, dir_fd=payload_fd)
                    os.fsync(payload_fd)
                except OSError:
                    pass
                raise

            try:
                os.unlink(temporary, dir_fd=payload_fd)
                os.fsync(payload_fd)
            except OSError as exc:
                raise ResearchWorkflowError(
                    "workflow_durability_unknown",
                    "workflow payload published but temp cleanup could not be confirmed",
                ) from exc
            if not self._recover_payload_publish(payload_fd, digest, payload):
                raise _corrupt("workflow payload publish was not durable")
        finally:
            os.close(payload_fd)

    def _recover_payload_publish(
        self,
        payload_dir_fd: int,
        digest: str,
        expected_payload: bytes,
    ) -> bool:
        """Recover only temp names for one content-addressed payload.

        A no-replace hard-link publish has one intentional crash window: both
        the final name and its private temp name can reference the same inode.
        Every link must be accounted for before cleanup; unknown hard links fail
        closed rather than being silently normalized.
        """

        final_name = f"{digest}.json"
        temp_prefix = f".payload.{digest}."
        temp_names = sorted(
            entry
            for entry in os.listdir(payload_dir_fd)
            if entry.startswith(temp_prefix) and entry.endswith(".tmp")
        )
        try:
            final_metadata = os.stat(
                final_name,
                dir_fd=payload_dir_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            final_metadata = None

        temp_metadata: dict[str, os.stat_result] = {}
        for temporary in temp_names:
            metadata = os.stat(
                temporary,
                dir_fd=payload_dir_fd,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o400
                or metadata.st_uid != os.geteuid()
            ):
                raise _insecure(
                    "workflow payload temp must be an owner-only regular file"
                )
            temp_metadata[temporary] = metadata

        linked_temps: list[str] = []
        if final_metadata is not None:
            if (
                not stat.S_ISREG(final_metadata.st_mode)
                or stat.S_IMODE(final_metadata.st_mode) != 0o400
                or final_metadata.st_uid != os.geteuid()
            ):
                raise _insecure("workflow payload final file is insecure")
            linked_temps = [
                temporary
                for temporary, metadata in temp_metadata.items()
                if (metadata.st_dev, metadata.st_ino)
                == (final_metadata.st_dev, final_metadata.st_ino)
            ]
            if final_metadata.st_nlink != 1 + len(linked_temps):
                raise _insecure("workflow payload has an unaccounted hard link")

        changed = False
        for temporary, metadata in temp_metadata.items():
            if temporary not in linked_temps and metadata.st_nlink != 1:
                raise _insecure("workflow payload temp has an unaccounted hard link")
            os.unlink(temporary, dir_fd=payload_dir_fd)
            changed = True
        if changed:
            os.fsync(payload_dir_fd)

        if final_metadata is None:
            return False
        existing = self._read_payload_bytes(payload_dir_fd, final_name)
        if existing != expected_payload or _sha256_bytes(existing) != digest:
            raise _corrupt("workflow payload content-address collision")
        return True

    def _read_payload_bytes(self, payload_dir_fd: int, name: str) -> bytes:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(name, flags, dir_fd=payload_dir_fd)
        except FileNotFoundError as exc:
            raise ResearchWorkflowError(
                "workflow_payload_not_found", "workflow payload was not found"
            ) from exc
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise _insecure("workflow payload must not be a symbolic link") from exc
            raise
        try:
            self._assert_secure_file(fd, "workflow payload", mode=0o400)
            self._assert_path_identity(payload_dir_fd, name, fd, "workflow payload")
            metadata = os.fstat(fd)
            if metadata.st_size > _MAX_PAYLOAD_BYTES:
                raise _corrupt("workflow payload exceeds the supported size")
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(fd, 65_536)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_PAYLOAD_BYTES:
                    raise _corrupt("workflow payload exceeds the supported size")
                chunks.append(chunk)
            self._assert_path_identity(payload_dir_fd, name, fd, "workflow payload")
            return b"".join(chunks)
        finally:
            os.close(fd)

    def _unlink_payload_if_present(self, root_fd: int, digest: str) -> bool:
        payload_dir_fd = self._payload_dir_fd(root_fd, create=False)
        name = f"{digest}.json"
        try:
            try:
                raw = self._read_payload_bytes(payload_dir_fd, name)
            except ResearchWorkflowError as exc:
                if exc.code == "workflow_payload_not_found":
                    return False
                raise
            if _sha256_bytes(raw) != digest:
                raise _corrupt("workflow payload digest does not match before deletion")
            os.unlink(name, dir_fd=payload_dir_fd)
            os.fsync(payload_dir_fd)
            return True
        finally:
            os.close(payload_dir_fd)

    def _read_payload(self, root_fd: int, digest: str) -> dict[str, Any]:
        payload_fd = self._payload_dir_fd(root_fd, create=False)
        try:
            raw = self._read_payload_bytes(payload_fd, f"{digest}.json")
        finally:
            os.close(payload_fd)
        return self._decode_payload_bytes(raw, digest)

    def _decode_payload_bytes(self, raw: bytes, digest: str) -> dict[str, Any]:
        if _sha256_bytes(raw) != digest:
            raise _corrupt("workflow payload digest does not match")
        if not raw.endswith(b"\n"):
            raise _corrupt("workflow payload is not canonical JSON")
        try:
            payload = json.loads(
                raw.decode("utf-8", errors="strict"),
                object_pairs_hook=_object_without_duplicate_keys,
                parse_constant=_reject_json_constant,
            )
        except ResearchWorkflowError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
            raise _corrupt("workflow payload is invalid JSON") from exc
        if not isinstance(payload, dict) or raw != _canonical_bytes(payload):
            raise _corrupt("workflow payload is not canonical JSON")
        self._validate_payload_envelope(payload)
        return payload

    def _validate_payload_envelope(self, payload: dict[str, Any]) -> None:
        expected_fields = {
            "schema_version",
            "kind",
            "owner_user_id",
            "platform_session_id",
            "client_request_id",
            "canonical_request_digest",
            "prompt",
            "provider_policy",
            "provider_policy_digest",
            "plan",
            "plan_digest",
            "payload_ttl_days",
            "created_at",
            "expires_at",
        }
        if set(payload) != expected_fields:
            raise _corrupt("workflow payload fields are invalid")
        try:
            policy = _normalize_provider_policy(payload["provider_policy"])
            plan = _normalize_plan(payload["plan"])
        except ResearchWorkflowError as exc:
            raise _corrupt("workflow payload values are invalid") from exc
        if (
            payload["schema_version"] != _SCHEMA_VERSION
            or payload["kind"] != _COMMAND_KIND
            or payload["owner_user_id"] != _OWNER_USER_ID
            or policy != payload["provider_policy"]
            or plan != payload["plan"]
            or payload["provider_policy_digest"] != _sha256(policy)
            or payload["plan_digest"] != _sha256(plan)
        ):
            raise _corrupt("workflow payload identity or digest is invalid")
        created_at = _canonical_timestamp(payload["created_at"], "created_at", stored=True)
        expires_at = _canonical_timestamp(payload["expires_at"], "expires_at", stored=True)
        if created_at != payload["created_at"] or expires_at != payload["expires_at"]:
            raise _corrupt("workflow payload timestamps are not canonical")
        ttl_days = payload["payload_ttl_days"]
        if (
            isinstance(ttl_days, bool)
            or not isinstance(ttl_days, int)
            or not 1 <= ttl_days <= _MAX_TTL_DAYS
            or _parse_timestamp(created_at) + timedelta(days=ttl_days)
            != _parse_timestamp(expires_at)
        ):
            raise _corrupt("workflow payload TTL is invalid")
        try:
            request = _normalize_prepare_request(
                {
                    "schema_version": _SCHEMA_VERSION,
                    "platform_session_id": payload["platform_session_id"],
                    "client_request_id": payload["client_request_id"],
                    "command_kind": _COMMAND_KIND,
                    "payload_ttl_days": ttl_days,
                    "prompt": payload["prompt"],
                    "provider_policy": policy,
                    "plan": plan,
                }
            )
        except ResearchWorkflowError as exc:
            raise _corrupt("workflow payload request values are invalid") from exc
        if payload["canonical_request_digest"] != _sha256(request):
            raise _corrupt("workflow canonical request digest does not match")

    def _verify_payload_for_receipt(
        self,
        root_fd: int,
        receipt: dict[str, Any],
    ) -> dict[str, Any]:
        self._validate_receipt(receipt)
        payload = self._read_payload(root_fd, receipt["payload_digest"])
        if (
            payload["canonical_request_digest"]
            != receipt["canonical_request_digest"]
            or payload["expires_at"] != receipt["payload_expires_at"]
            or payload["provider_policy_digest"]
            != receipt["provider_policy_digest"]
            or payload["plan_digest"] != receipt["plan_digest"]
            or payload["plan"]["schema_version"]
            != receipt["plan_schema_version"]
            or payload["plan"]["version"] != receipt["plan_version"]
        ):
            raise _corrupt("workflow payload does not match preparation receipt")
        return payload

    def _publish_projection(
        self,
        root_fd: int,
        projection: dict[str, Any],
    ) -> None:
        payload = _canonical_bytes(projection)
        destination = "projection.v1.json"
        if self._entry_exists(root_fd, destination):
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            try:
                existing_fd = os.open(destination, flags, dir_fd=root_fd)
            except OSError as exc:
                if exc.errno == errno.ELOOP:
                    raise _insecure("workflow projection must not be a symbolic link") from exc
                raise
            try:
                self._assert_secure_file(
                    existing_fd, "workflow projection", mode=0o600
                )
                self._assert_path_identity(
                    root_fd, destination, existing_fd, "workflow projection"
                )
            finally:
                os.close(existing_fd)
        temporary = f".projection.v1.json.{secrets.token_hex(12)}.tmp"
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
        )
        fd = os.open(temporary, flags, 0o600, dir_fd=root_fd)
        try:
            os.fchmod(fd, 0o600)
            view = memoryview(payload)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("workflow projection write made no progress")
                view = view[written:]
            os.fsync(fd)
            self._assert_secure_file(fd, "workflow projection temp", mode=0o600)
            self._assert_path_identity(
                root_fd, temporary, fd, "workflow projection temp"
            )
        except Exception:
            try:
                os.unlink(temporary, dir_fd=root_fd)
            except OSError:
                pass
            raise
        finally:
            os.close(fd)
        try:
            os.replace(
                temporary,
                destination,
                src_dir_fd=root_fd,
                dst_dir_fd=root_fd,
            )
            os.fsync(root_fd)
        finally:
            try:
                os.unlink(temporary, dir_fd=root_fd)
            except FileNotFoundError:
                pass


def default_payload_ttl_days() -> int:
    return _DEFAULT_TTL_DAYS

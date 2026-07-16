from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping, Optional, Protocol, Tuple


_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")
_HEX64_RE = re.compile(r"[0-9a-f]{64}\Z")
_RFC3339_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z"
)
_MAX_CURSOR = 2**63 - 1
_MAX_SOURCE_CURSOR_LENGTH = 2_000
_MAX_METADATA_DEPTH = 16
_MAX_METADATA_BYTES = 65_536
_MAX_METADATA_NODES = 1_024
_MAX_METADATA_STRING_BYTES = 4_096
_MAX_METADATA_CONTAINER_WIDTH = 128
_MAX_METADATA_INTEGER_BITS = 12_000
_ACTION_RECEIPT_STATUSES = (
    "accepted",
    "reconciling",
    "conflict",
    "unavailable",
    "outcome_unknown",
)
_ACTION_RECEIPT_RECOVERY_ACTIONS = MappingProxyType(
    {
        "accepted": None,
        "reconciling": "follow_workspace",
        "conflict": "choose_legal_target_or_new_action",
        "unavailable": "retry_read_or_reconcile_original_action",
        "outcome_unknown": "follow_and_reconcile_original_action",
    }
)
_SOURCE_AUTHORITIES = ("postgresql", "hqa", "hermes", "platform_domain")
_SAFE_METADATA_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "reason_code",
        "error_code",
        "recovery_action",
        "session_id",
        "task_id",
        "attempt_id",
        "command_id",
        "run_id",
        "result_ref",
        "candidate_id",
        "manifest_digest",
        "provider_evidence_ref",
        "approval_id",
        "stop_request_id",
    }
)
_DEFAULT_RECOVERY_ACTIONS = MappingProxyType(
    {
        "validation": "correct_input",
        "auth": "reauthenticate_owner",
        "conflict": "choose_legal_target_or_new_action",
        "stale": "resnapshot_and_review",
        "capability": "restore_and_revalidate_capability",
        "unavailable": "retry_read_or_reconcile_original_action",
        "outcome_unknown": "follow_and_reconcile_original_action",
        "expired": "refresh_facts_and_create_new_action",
        "integrity": "stop_and_audit",
        "quota": "wait_or_reconcile_original_action",
        "forbidden": "stop_and_choose_allowed_action",
    }
)
_PUBLIC_ERROR_MESSAGES = MappingProxyType(
    {
        "validation": "workspace_validation_failed",
        "auth": "workspace_auth_failed",
        "conflict": "workspace_conflict",
        "stale": "workspace_stale",
        "capability": "workspace_capability_unavailable",
        "unavailable": "workspace_authority_unavailable",
        "outcome_unknown": "workspace_outcome_unknown",
        "expired": "workspace_action_expired",
        "integrity": "workspace_integrity_failed",
        "quota": "workspace_quota_exceeded",
        "forbidden": "workspace_forbidden",
    }
)
_PUBLIC_METADATA_STATUSES = frozenset(
    {
        "accepted",
        "reconciling",
        "conflict",
        "unavailable",
        "outcome_unknown",
        "pending",
        "running",
        "completed",
        "completed_degraded",
        "failed",
        "requested",
        "confirmed",
        "stopped",
        "already_terminal",
        "unknown",
    }
)
_PUBLIC_METADATA_REASON_CODES = frozenset(_DEFAULT_RECOVERY_ACTIONS) | frozenset(
    {"resync_required", "provider_unavailable", "awaiting_binding", "partial_stop"}
)
_PUBLIC_METADATA_RECOVERY_ACTIONS = (
    frozenset(_DEFAULT_RECOVERY_ACTIONS.values())
    | frozenset(
        action
        for action in _ACTION_RECEIPT_RECOVERY_ACTIONS.values()
        if action is not None
    )
    | frozenset({"resnapshot_workspace"})
)
_PUBLIC_REFERENCE_PREFIXES = MappingProxyType(
    {
        "session_id": "session:",
        "task_id": "task:",
        "attempt_id": "attempt:",
        "command_id": "command:",
        "run_id": "run:",
        "result_ref": "result:",
        "candidate_id": "candidate:",
        "provider_evidence_ref": "provider-evidence:",
        "approval_id": "approval:",
        "stop_request_id": "stop:",
    }
)


def _validate_identifier(value: Any, field: str) -> None:
    if not isinstance(value, str) or _IDENTIFIER_RE.fullmatch(value) is None:
        raise ValueError(f"{field} must be a non-empty bounded identifier")


def _validate_source_cursor(value: Any) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_SOURCE_CURSOR_LENGTH
        or not value.isprintable()
    ):
        raise ValueError("source_cursor must be a non-empty bounded string")


def _normalize_observed_at(value: Any) -> str:
    if not isinstance(value, str) or _RFC3339_RE.fullmatch(value) is None:
        raise ValueError("observed_at must be a canonical timezone-aware timestamp")
    parsed_value = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(parsed_value)
    except ValueError as exc:
        raise ValueError(
            "observed_at must be a canonical timezone-aware timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass
class _MetadataBudget:
    nodes: int = 0
    serialized_bytes: int = 0

    def consume_node(self) -> None:
        self.nodes += 1
        if self.nodes > _MAX_METADATA_NODES:
            raise ValueError("metadata exceeds the node budget")

    def consume_bytes(self, count: int) -> None:
        self.serialized_bytes += count
        if self.serialized_bytes > _MAX_METADATA_BYTES:
            raise ValueError("metadata exceeds the serialized byte budget")


def _measure_json_string(value: str) -> int:
    raw_bytes = 0
    serialized_bytes = 2
    for character in value:
        codepoint = ord(character)
        if 0xD800 <= codepoint <= 0xDFFF:
            raise ValueError("metadata strings must contain valid Unicode")
        if codepoint <= 0x7F:
            character_bytes = 1
        elif codepoint <= 0x7FF:
            character_bytes = 2
        elif codepoint <= 0xFFFF:
            character_bytes = 3
        else:
            character_bytes = 4
        raw_bytes += character_bytes
        if raw_bytes > _MAX_METADATA_STRING_BYTES:
            raise ValueError("metadata exceeds the string byte budget")

        if character in ('"', "\\", "\b", "\f", "\n", "\r", "\t"):
            serialized_bytes += 2
        elif codepoint < 0x20:
            serialized_bytes += 6
        else:
            serialized_bytes += character_bytes
    return serialized_bytes


def _validate_metadata_value(key: str, value: Any) -> None:
    if type(value) in (dict, list):
        raise ValueError("V0 metadata must remain flat")
    if key == "schema_version":
        if type(value) is not int or value != 1:
            raise ValueError("invalid metadata value for schema_version")
        return
    if type(value) is not str:
        raise ValueError(f"invalid metadata value for {key}")
    if key == "status":
        if value not in _PUBLIC_METADATA_STATUSES:
            raise ValueError("invalid metadata value for status")
        return
    if key == "reason_code":
        if value not in _PUBLIC_METADATA_REASON_CODES:
            raise ValueError("invalid metadata value for reason_code")
        return
    if key == "error_code":
        if value not in _DEFAULT_RECOVERY_ACTIONS:
            raise ValueError("invalid metadata value for error_code")
        return
    if key == "recovery_action":
        if value not in _PUBLIC_METADATA_RECOVERY_ACTIONS:
            raise ValueError("invalid metadata value for recovery_action")
        return
    if key == "manifest_digest":
        if not isinstance(value, str) or _HEX64_RE.fullmatch(value) is None:
            raise ValueError("invalid metadata value for manifest_digest")
        return

    prefix = _PUBLIC_REFERENCE_PREFIXES[key]
    if not isinstance(value, str) or not value.startswith(prefix):
        raise ValueError("metadata value must use the required semantic prefix")
    suffix = value[len(prefix) :]
    if _IDENTIFIER_RE.fullmatch(suffix) is None:
        raise ValueError("metadata value must use the required semantic prefix")


def _freeze_json(
    value: Any,
    depth: int,
    active_ids: set,
    budget: _MetadataBudget,
) -> Any:
    if depth > _MAX_METADATA_DEPTH:
        raise ValueError("metadata exceeds the maximum JSON depth")
    budget.consume_node()
    if value is None:
        budget.consume_bytes(4)
        return value
    if type(value) is bool:
        budget.consume_bytes(4 if value else 5)
        return value
    if type(value) is int:
        if value.bit_length() > _MAX_METADATA_INTEGER_BITS:
            raise ValueError("metadata exceeds the serialized byte budget")
        budget.consume_bytes(len(str(value)))
        return value
    if type(value) is str:
        budget.consume_bytes(_measure_json_string(value))
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("metadata numbers must be finite")
        budget.consume_bytes(len(repr(value)))
        return value
    if type(value) not in (dict, list):
        raise ValueError("metadata must contain strict JSON values only")
    if len(value) > _MAX_METADATA_CONTAINER_WIDTH:
        raise ValueError("metadata exceeds the container width")

    identity = id(value)
    if identity in active_ids:
        raise ValueError("metadata must not contain cycles")
    active_ids.add(identity)
    try:
        if type(value) is list:
            budget.consume_bytes(2 + max(0, len(value) - 1))
            frozen_items = []
            for item in value:
                frozen_items.append(
                    _freeze_json(item, depth + 1, active_ids, budget)
                )
            return tuple(frozen_items)

        budget.consume_bytes(2 + max(0, len(value) - 1) + len(value))
        frozen = {}
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError("metadata object keys must be strings")
            if key not in _SAFE_METADATA_KEYS:
                raise ValueError("metadata key is not in the safe allowlist")
            _validate_metadata_value(key, item)
            budget.consume_bytes(_measure_json_string(key))
            frozen[key] = _freeze_json(item, depth + 1, active_ids, budget)
        return MappingProxyType(frozen)
    finally:
        active_ids.remove(identity)


def _freeze_metadata(metadata: Any) -> Mapping[str, Any]:
    if type(metadata) is not dict:
        raise ValueError("metadata must be a JSON object")
    return _freeze_json(metadata, 0, set(), _MetadataBudget())


def _copy_reference_tuple(value: Any, field: str) -> Tuple[str, ...]:
    if type(value) is not tuple:
        raise TypeError(f"{field} must be a tuple")
    for item in value:
        _validate_identifier(item, f"{field} reference")
    return tuple(item for item in value)


def _copy_authority_health(value: Any) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise TypeError("authority_health must be a mapping")
    copied = {}
    for authority, health in value.items():
        if authority not in _SOURCE_AUTHORITIES:
            raise ValueError("authority_health contains an invalid authority")
        _validate_identifier(health, f"authority_health[{authority}]")
        copied[authority] = health
    return MappingProxyType(copied)


def default_recovery_action(code: str) -> str:
    try:
        return _DEFAULT_RECOVERY_ACTIONS[code]
    except (KeyError, TypeError) as exc:
        raise ValueError("unknown workspace contract error code") from exc


def public_error_message(code: str) -> str:
    try:
        return _PUBLIC_ERROR_MESSAGES[code]
    except (KeyError, TypeError) as exc:
        raise ValueError("unknown workspace contract error code") from exc


@dataclass(frozen=True)
class ActorRef:
    owner_user_id: str

    def __post_init__(self) -> None:
        _validate_identifier(self.owner_user_id, "owner_user_id")


@dataclass(frozen=True)
class WorkspaceRef:
    workspace_id: str

    def __post_init__(self) -> None:
        _validate_identifier(self.workspace_id, "workspace_id")


@dataclass(frozen=True)
class WorkspaceCursor:
    value: int

    def __post_init__(self) -> None:
        if type(self.value) is not int or not 0 <= self.value <= _MAX_CURSOR:
            raise ValueError("workspace cursor must be a non-negative 63-bit integer")


@dataclass(frozen=True)
class ActionReceipt:
    status: str
    client_action_id: str
    action_digest: str
    workspace: WorkspaceRef
    command_id: Optional[str] = None
    run_id: Optional[str] = None
    recovery_action: Optional[str] = None

    def __post_init__(self) -> None:
        if self.status not in _ACTION_RECEIPT_STATUSES:
            raise ValueError("invalid action receipt status")
        _validate_identifier(self.client_action_id, "client_action_id")
        if (
            not isinstance(self.action_digest, str)
            or _HEX64_RE.fullmatch(self.action_digest) is None
        ):
            raise ValueError("action_digest must be a lowercase 64-character hex digest")
        if not isinstance(self.workspace, WorkspaceRef):
            raise TypeError("workspace must be a WorkspaceRef")
        if self.command_id is not None:
            _validate_identifier(self.command_id, "command_id")
        if self.run_id is not None:
            _validate_identifier(self.run_id, "run_id")
        expected_recovery = _ACTION_RECEIPT_RECOVERY_ACTIONS[self.status]
        if self.recovery_action != expected_recovery:
            raise ValueError("status requires its exact recovery action")


@dataclass(frozen=True)
class WorkspaceEvent:
    workspace_cursor: WorkspaceCursor
    source_authority: str
    source_event_id: str
    source_cursor: str
    observed_at: str
    event_type: str
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.workspace_cursor, WorkspaceCursor):
            raise TypeError("workspace_cursor must be a WorkspaceCursor")
        if self.source_authority not in _SOURCE_AUTHORITIES:
            raise ValueError("invalid source_authority")
        _validate_identifier(self.source_event_id, "source_event_id")
        _validate_source_cursor(self.source_cursor)
        object.__setattr__(self, "observed_at", _normalize_observed_at(self.observed_at))
        _validate_identifier(self.event_type, "event_type")
        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))


@dataclass(frozen=True)
class EventPage:
    events: Tuple[WorkspaceEvent, ...]
    after_cursor: Optional[WorkspaceCursor] = None
    next_cursor: Optional[WorkspaceCursor] = None
    resync_required: bool = False
    recovery_action: Optional[str] = None

    def __post_init__(self) -> None:
        if type(self.events) is not tuple:
            raise TypeError("events must be a tuple")
        copied_events = []
        previous_cursor = None
        for event in self.events:
            if not isinstance(event, WorkspaceEvent):
                raise TypeError("events must contain WorkspaceEvent values")
            if (
                previous_cursor is not None
                and event.workspace_cursor.value != previous_cursor + 1
            ):
                raise ValueError("event cursors must be contiguous")
            previous_cursor = event.workspace_cursor.value
            copied_events.append(event)
        object.__setattr__(self, "events", tuple(copied_events))

        if self.after_cursor is not None and not isinstance(
            self.after_cursor, WorkspaceCursor
        ):
            raise TypeError("after_cursor must be a WorkspaceCursor or None")
        if self.next_cursor is not None and not isinstance(
            self.next_cursor, WorkspaceCursor
        ):
            raise TypeError("next_cursor must be a WorkspaceCursor or None")
        if type(self.resync_required) is not bool:
            raise TypeError("resync_required must be a bool")
        if self.recovery_action is not None:
            _validate_identifier(self.recovery_action, "recovery_action")
        if self.resync_required:
            if self.events or self.next_cursor is not None:
                raise ValueError(
                    "resync pages cannot contain events or a next_cursor"
                )
            if self.recovery_action != "resnapshot_workspace":
                raise ValueError(
                    "resync_required pages require resnapshot_workspace recovery"
                )
        else:
            if self.events:
                if (
                    self.after_cursor is not None
                    and self.events[0].workspace_cursor.value
                    != self.after_cursor.value + 1
                ):
                    raise ValueError("first event cursor must follow after_cursor")
                if self.next_cursor != self.events[-1].workspace_cursor:
                    raise ValueError("next_cursor must match the final event cursor")
            elif self.next_cursor != self.after_cursor:
                raise ValueError(
                    "empty pages require next_cursor to equal after_cursor"
                )
            if self.recovery_action == "resnapshot_workspace":
                raise ValueError(
                    "non-resync pages cannot claim resnapshot_workspace recovery"
                )
            if self.recovery_action is not None:
                raise ValueError("ordinary event pages require recovery_action None")


@dataclass(frozen=True)
class WorkspaceSnapshot:
    workspace: WorkspaceRef
    owner_user_id: str
    snapshot_workspace_cursor: WorkspaceCursor
    sessions: Tuple[str, ...]
    tasks: Tuple[str, ...]
    attempts: Tuple[str, ...]
    commands: Tuple[str, ...]
    runs: Tuple[str, ...]
    results: Tuple[str, ...]
    authority_health: Mapping[str, str]

    def __post_init__(self) -> None:
        if not isinstance(self.workspace, WorkspaceRef):
            raise TypeError("workspace must be a WorkspaceRef")
        _validate_identifier(self.owner_user_id, "owner_user_id")
        if not isinstance(self.snapshot_workspace_cursor, WorkspaceCursor):
            raise TypeError(
                "snapshot_workspace_cursor must be a WorkspaceCursor"
            )
        for field in ("sessions", "tasks", "attempts", "commands", "runs", "results"):
            object.__setattr__(
                self,
                field,
                _copy_reference_tuple(getattr(self, field), field),
            )
        object.__setattr__(
            self,
            "authority_health",
            _copy_authority_health(self.authority_health),
        )


@dataclass(frozen=True)
class WorkspaceErrorDetail:
    code: str
    message: str
    recovery_action: str

    def __post_init__(self) -> None:
        expected_recovery = default_recovery_action(self.code)
        if self.message != public_error_message(self.code):
            raise ValueError("error detail requires the derived public message")
        if self.recovery_action != expected_recovery:
            raise ValueError("error detail requires the default recovery action")


class WorkspaceContractError(Exception):
    __slots__ = ("_detail",)

    def __init__(
        self,
        code: str,
        message: Optional[str] = None,
        recovery_action: Optional[str] = None,
    ) -> None:
        default_recovery = default_recovery_action(code)
        derived_message = public_error_message(code)
        resolved_message = derived_message if message is None else message
        resolved_recovery = (
            default_recovery if recovery_action is None else recovery_action
        )
        self._detail = WorkspaceErrorDetail(
            code=code,
            message=resolved_message,
            recovery_action=resolved_recovery,
        )
        super().__init__(resolved_message)

    @property
    def detail(self) -> WorkspaceErrorDetail:
        return self._detail

    @property
    def code(self) -> str:
        return self._detail.code

    @property
    def message(self) -> str:
        return self._detail.message

    @property
    def recovery_action(self) -> str:
        return self._detail.recovery_action


class UserActionV1(Protocol):
    """Marker protocol for closed workspace actions defined by later contracts."""


class AgentWorkspace(Protocol):
    def act(self, actor: ActorRef, action: UserActionV1) -> ActionReceipt:
        ...

    def snapshot(
        self, actor: ActorRef, workspace: WorkspaceRef
    ) -> WorkspaceSnapshot:
        ...

    def follow(
        self,
        actor: ActorRef,
        workspace: WorkspaceRef,
        after: Optional[WorkspaceCursor] = None,
    ) -> EventPage:
        ...

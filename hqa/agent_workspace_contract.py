from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Mapping, Optional, Protocol, Tuple


_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")
_HEX64_RE = re.compile(r"[0-9a-f]{64}\Z")
_RFC3339_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z"
)
_SENSITIVE_MESSAGE_ASSIGNMENT_RE = re.compile(
    r"\b(?:prompt|message|body|secret|token|authorization)\s*[:=]",
    re.IGNORECASE,
)
_MAX_CURSOR = 2**63 - 1
_MAX_SOURCE_CURSOR_LENGTH = 2_000
_MAX_METADATA_DEPTH = 16
_MAX_METADATA_BYTES = 65_536
_ACTION_RECEIPT_STATUSES = (
    "accepted",
    "reconciling",
    "conflict",
    "unavailable",
    "outcome_unknown",
)
_SOURCE_AUTHORITIES = ("postgresql", "hqa", "hermes", "platform_domain")
_SENSITIVE_METADATA_KEYS = frozenset(
    {"prompt", "message", "body", "secret", "token", "authorization"}
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


def _validate_observed_at(value: Any) -> None:
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


def _freeze_json(value: Any, depth: int, active_ids: set) -> Any:
    if depth > _MAX_METADATA_DEPTH:
        raise ValueError("metadata exceeds the maximum JSON depth")
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("metadata numbers must be finite")
        return value
    if type(value) not in (dict, list):
        raise ValueError("metadata must contain strict JSON values only")

    identity = id(value)
    if identity in active_ids:
        raise ValueError("metadata must not contain cycles")
    active_ids.add(identity)
    try:
        if type(value) is list:
            return tuple(
                _freeze_json(item, depth + 1, active_ids) for item in value
            )

        frozen = {}
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError("metadata object keys must be strings")
            if key.casefold() in _SENSITIVE_METADATA_KEYS:
                raise ValueError("metadata contains a sensitive key")
            frozen[key] = _freeze_json(item, depth + 1, active_ids)
        return MappingProxyType(frozen)
    finally:
        active_ids.remove(identity)


def _freeze_metadata(metadata: Any) -> Mapping[str, Any]:
    if type(metadata) is not dict:
        raise ValueError("metadata must be a JSON object")
    frozen = _freeze_json(metadata, 0, set())
    try:
        serialized = json.dumps(
            metadata,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("metadata must contain strict finite JSON") from exc
    if len(serialized) > _MAX_METADATA_BYTES:
        raise ValueError("metadata exceeds the maximum serialized size")
    return frozen


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


def _validate_safe_message(value: Any) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 500
        or not value.isprintable()
        or _SENSITIVE_MESSAGE_ASSIGNMENT_RE.search(value) is not None
    ):
        raise ValueError("message must be safe, non-empty, and bounded")


def default_recovery_action(code: str) -> str:
    try:
        return _DEFAULT_RECOVERY_ACTIONS[code]
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
        if self.recovery_action is not None:
            _validate_identifier(self.recovery_action, "recovery_action")
        if self.status != "accepted" and self.recovery_action is None:
            raise ValueError(f"{self.status} receipts require a recovery_action")


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
        _validate_observed_at(self.observed_at)
        _validate_identifier(self.event_type, "event_type")
        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))


@dataclass(frozen=True)
class EventPage:
    events: Tuple[WorkspaceEvent, ...]
    next_cursor: Optional[WorkspaceCursor] = None
    resync_required: bool = False
    recovery_action: Optional[str] = None

    def __post_init__(self) -> None:
        if type(self.events) is not tuple:
            raise TypeError("events must be a tuple")
        copied_events = []
        previous_cursor = -1
        for event in self.events:
            if not isinstance(event, WorkspaceEvent):
                raise TypeError("events must contain WorkspaceEvent values")
            if event.workspace_cursor.value <= previous_cursor:
                raise ValueError("event cursors must be strictly increasing")
            previous_cursor = event.workspace_cursor.value
            copied_events.append(event)
        object.__setattr__(self, "events", tuple(copied_events))

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
            if self.events and self.next_cursor != self.events[-1].workspace_cursor:
                raise ValueError("next_cursor must match the final event cursor")
            if self.recovery_action == "resnapshot_workspace":
                raise ValueError(
                    "non-resync pages cannot claim resnapshot_workspace recovery"
                )


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


class WorkspaceContractError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        recovery_action: Optional[str] = None,
    ) -> None:
        default_recovery = default_recovery_action(code)
        resolved_recovery = (
            default_recovery if recovery_action is None else recovery_action
        )
        _validate_safe_message(message)
        _validate_identifier(resolved_recovery, "recovery_action")
        self.code = code
        self.message = message
        self.recovery_action = resolved_recovery
        super().__init__(message)


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

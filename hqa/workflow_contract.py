from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from types import MappingProxyType
from typing import Any, Mapping, Optional, Tuple, Union


_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_HEX64_RE = re.compile(r"[0-9a-f]{64}\Z")
_RFC3339_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z"
)
_MAX_NOTE_BYTES = 2_000
_MAX_EVENT_PAGE = 1_000


class WorkflowContractError(ValueError):
    """Value-free validation error safe to expose at a local boundary."""

    def __init__(self, code: str, field: str) -> None:
        self.code = code
        self.field = field
        super().__init__("{}:{}".format(code, field))


def _fail(code: str, field: str) -> None:
    raise WorkflowContractError(code, field)


def _validate_identifier(value: Any, field: str) -> None:
    if type(value) is not str or _IDENTIFIER_RE.fullmatch(value) is None:
        _fail("invalid_identifier", field)


def _validate_ref(value: Any, field: str, prefix: str) -> None:
    if type(value) is not str or not value.startswith(prefix):
        _fail("invalid_ref", field)
    suffix = value[len(prefix) :]
    if _IDENTIFIER_RE.fullmatch(suffix) is None:
        _fail("invalid_ref", field)


def _validate_payload_ref(value: Any, field: str = "payload_ref") -> None:
    if type(value) is not str or not value.startswith("payload:sha256:"):
        _fail("invalid_ref", field)
    if _HEX64_RE.fullmatch(value[len("payload:sha256:") :]) is None:
        _fail("invalid_ref", field)


def _validate_event_ref(value: Any, field: str) -> None:
    if type(value) is not str or not value.startswith("event:"):
        _fail("invalid_ref", field)
    if _HEX64_RE.fullmatch(value[len("event:") :]) is None:
        _fail("invalid_ref", field)


def _validate_digest(value: Any, field: str) -> None:
    if type(value) is not str or _HEX64_RE.fullmatch(value) is None:
        _fail("invalid_digest", field)


def _validate_positive_version(
    value: Any, field: str = "expected_version"
) -> None:
    if type(value) is not int or value < 1 or value > 2**63 - 1:
        _fail("invalid_version", field)


def _validate_plan_version(value: Any) -> None:
    if type(value) is not int or value < 1 or value > 2**31 - 1:
        _fail("invalid_version", "plan_version")


def _validate_note(value: Any, field: str) -> None:
    if (
        type(value) is not str
        or not value.strip()
        or not value.isprintable()
        or len(value.encode("utf-8")) > _MAX_NOTE_BYTES
    ):
        _fail("invalid_note", field)


def normalize_timestamp(value: Any, field: str) -> str:
    if type(value) is not str or _RFC3339_RE.fullmatch(value) is None:
        _fail("invalid_timestamp", field)
    parsed_value = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(parsed_value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            _fail("invalid_timestamp", field)
        return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    except (ValueError, OverflowError, OSError) as exc:
        raise WorkflowContractError("invalid_timestamp", field) from exc


def payload_digest_from_ref(payload_ref: str) -> str:
    _validate_payload_ref(payload_ref)
    return payload_ref[len("payload:sha256:") :]


@dataclass(frozen=True)
class _Operation:
    operation_id: str

    def __post_init__(self) -> None:
        _validate_identifier(self.operation_id, "operation_id")


@dataclass(frozen=True)
class _ExistingTaskOperation(_Operation):
    task_ref: str
    expected_version: int

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_ref(self.task_ref, "task_ref", "task:")
        _validate_positive_version(self.expected_version)


@dataclass(frozen=True)
class StartResearch(_Operation):
    workspace_ref: str
    managed_session_ref: str
    payload_ref: str
    intent_expires_at: str

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_ref(self.workspace_ref, "workspace_ref", "workspace:")
        _validate_ref(
            self.managed_session_ref,
            "managed_session_ref",
            "session:",
        )
        _validate_payload_ref(self.payload_ref)
        object.__setattr__(
            self,
            "intent_expires_at",
            normalize_timestamp(self.intent_expires_at, "intent_expires_at"),
        )


@dataclass(frozen=True)
class ContinueResearch(_ExistingTaskOperation):
    payload_ref: str
    intent_expires_at: str

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_payload_ref(self.payload_ref)
        object.__setattr__(
            self,
            "intent_expires_at",
            normalize_timestamp(self.intent_expires_at, "intent_expires_at"),
        )


@dataclass(frozen=True)
class BindResearchClaim(_ExistingTaskOperation):
    """Bind one sealed research claim to the exact payload-backed Attempt."""

    attempt_ref: str
    payload_ref: str
    research_claim_digest: str

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_ref(self.attempt_ref, "attempt_ref", "attempt:")
        _validate_payload_ref(self.payload_ref)
        _validate_digest(self.research_claim_digest, "research_claim_digest")


@dataclass(frozen=True)
class ProposePlan(_ExistingTaskOperation):
    plan_version: int
    plan_digest: str
    plan_source_ref: str
    requires_formula_confirmation: bool

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_plan_version(self.plan_version)
        _validate_digest(self.plan_digest, "plan_digest")
        _validate_ref(self.plan_source_ref, "plan_source_ref", "run:")
        if type(self.requires_formula_confirmation) is not bool:
            _fail("invalid_type", "requires_formula_confirmation")


@dataclass(frozen=True)
class RevisePlan(_ExistingTaskOperation):
    plan_version: int
    plan_digest: str
    plan_source_ref: str
    requires_formula_confirmation: bool

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_plan_version(self.plan_version)
        _validate_digest(self.plan_digest, "plan_digest")
        _validate_ref(self.plan_source_ref, "plan_source_ref", "run:")
        if type(self.requires_formula_confirmation) is not bool:
            _fail("invalid_type", "requires_formula_confirmation")


@dataclass(frozen=True)
class RequestPlanConfirmation(_ExistingTaskOperation):
    plan_version: int
    plan_digest: str

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_plan_version(self.plan_version)
        _validate_digest(self.plan_digest, "plan_digest")


@dataclass(frozen=True)
class ConfirmPlan(_ExistingTaskOperation):
    plan_version: int
    plan_digest: str
    confirmation_note: str

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_plan_version(self.plan_version)
        _validate_digest(self.plan_digest, "plan_digest")
        _validate_note(self.confirmation_note, "confirmation_note")


@dataclass(frozen=True)
class ConfirmFormula(_ExistingTaskOperation):
    gate_ref: str
    reviewed_source_digest: str
    confirmation_note: str

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_ref(self.gate_ref, "gate_ref", "gate:")
        _validate_digest(self.reviewed_source_digest, "reviewed_source_digest")
        _validate_note(self.confirmation_note, "confirmation_note")


@dataclass(frozen=True)
class BindCandidateManifest(_ExistingTaskOperation):
    gate_ref: str
    candidate_ref: str
    manifest_digest: str

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_ref(self.gate_ref, "gate_ref", "gate:")
        _validate_ref(self.candidate_ref, "candidate_ref", "candidate:")
        _validate_digest(self.manifest_digest, "manifest_digest")


@dataclass(frozen=True)
class ObserveSubmission(_ExistingTaskOperation):
    attempt_ref: str
    command_ref: str

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_ref(self.attempt_ref, "attempt_ref", "attempt:")
        _validate_ref(self.command_ref, "command_ref", "command:")


@dataclass(frozen=True)
class ObserveRun(_ExistingTaskOperation):
    attempt_ref: str
    command_ref: str
    run_ref: str

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_ref(self.attempt_ref, "attempt_ref", "attempt:")
        _validate_ref(self.command_ref, "command_ref", "command:")
        _validate_ref(self.run_ref, "run_ref", "run:")


@dataclass(frozen=True)
class ObserveProviderEvidence(_ExistingTaskOperation):
    attempt_ref: str
    run_ref: str
    provider_evidence_ref: str

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_ref(self.attempt_ref, "attempt_ref", "attempt:")
        _validate_ref(self.run_ref, "run_ref", "run:")
        _validate_ref(
            self.provider_evidence_ref,
            "provider_evidence_ref",
            "provider-evidence:",
        )


@dataclass(frozen=True)
class ObserveGate3(_ExistingTaskOperation):
    attempt_ref: str
    run_ref: str
    gate_ref: str
    candidate_ref: str
    manifest_digest: str
    final_receipt_ref: str
    base_commit: str

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_ref(self.attempt_ref, "attempt_ref", "attempt:")
        _validate_ref(self.run_ref, "run_ref", "run:")
        _validate_ref(self.gate_ref, "gate_ref", "gate:")
        _validate_ref(self.candidate_ref, "candidate_ref", "candidate:")
        _validate_digest(self.manifest_digest, "manifest_digest")
        _validate_ref(
            self.final_receipt_ref,
            "final_receipt_ref",
            "result:",
        )
        if (
            type(self.base_commit) is not str
            or re.fullmatch(r"[0-9a-f]{40}", self.base_commit) is None
        ):
            _fail("invalid_digest", "base_commit")


@dataclass(frozen=True)
class LinkResult(_ExistingTaskOperation):
    attempt_ref: str
    run_ref: str
    result_ref: str

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_ref(self.attempt_ref, "attempt_ref", "attempt:")
        _validate_ref(self.run_ref, "run_ref", "run:")
        _validate_ref(self.result_ref, "result_ref", "result:")


@dataclass(frozen=True)
class EnterDomainGate(_ExistingTaskOperation):
    attempt_ref: str
    gate_ref: str

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_ref(self.attempt_ref, "attempt_ref", "attempt:")
        _validate_ref(self.gate_ref, "gate_ref", "gate:")


@dataclass(frozen=True)
class ResolveDomainGate(_ExistingTaskOperation):
    attempt_ref: str
    gate_ref: str
    outcome: str

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_ref(self.attempt_ref, "attempt_ref", "attempt:")
        _validate_ref(self.gate_ref, "gate_ref", "gate:")
        if type(self.outcome) is not str or self.outcome not in ("passed", "rejected"):
            _fail("invalid_value", "outcome")


@dataclass(frozen=True)
class BeginReconcile(_ExistingTaskOperation):
    attempt_ref: str
    reason_code: str

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_ref(self.attempt_ref, "attempt_ref", "attempt:")
        if type(self.reason_code) is not str or self.reason_code not in (
            "submission_outcome_unknown",
            "run_outcome_unknown",
            "stop_outcome_unknown",
            "authority_recovery",
        ):
            _fail("invalid_value", "reason_code")


@dataclass(frozen=True)
class ResolveReconcile(_ExistingTaskOperation):
    attempt_ref: str
    resolved_state: str
    observation_digest: str
    terminal_outcome: Optional[str] = None

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_ref(self.attempt_ref, "attempt_ref", "attempt:")
        _validate_digest(self.observation_digest, "observation_digest")
        if self.resolved_state not in ("running", "terminal"):
            _fail("invalid_value", "resolved_state")
        if self.resolved_state == "terminal":
            _validate_terminal_outcome(self.terminal_outcome)
        elif self.terminal_outcome is not None:
            _fail("invalid_value", "terminal_outcome")


@dataclass(frozen=True)
class RequestStop(_ExistingTaskOperation):
    attempt_ref: str
    run_ref: str
    stop_command_ref: str

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_ref(self.attempt_ref, "attempt_ref", "attempt:")
        _validate_ref(self.run_ref, "run_ref", "run:")
        _validate_ref(self.stop_command_ref, "stop_command_ref", "command:")


@dataclass(frozen=True)
class ObserveStop(_ExistingTaskOperation):
    attempt_ref: str
    stop_command_ref: str
    outcome: str
    observation_digest: str
    actual_terminal_outcome: Optional[str] = None

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_ref(self.attempt_ref, "attempt_ref", "attempt:")
        _validate_ref(self.stop_command_ref, "stop_command_ref", "command:")
        if type(self.outcome) is not str or self.outcome not in (
            "confirmed",
            "already_terminal",
            "outcome_unknown",
        ):
            _fail("invalid_value", "outcome")
        _validate_digest(self.observation_digest, "observation_digest")
        if self.outcome == "outcome_unknown":
            if self.actual_terminal_outcome is not None:
                _fail("invalid_value", "actual_terminal_outcome")
        elif self.outcome == "confirmed":
            if self.actual_terminal_outcome != "stopped":
                _fail("invalid_value", "actual_terminal_outcome")
        elif self.actual_terminal_outcome not in (
            "completed",
            "failed",
            "cancelled",
            "stopped",
        ):
            _fail("invalid_value", "actual_terminal_outcome")


def _validate_terminal_outcome(value: Any) -> None:
    if type(value) is not str or value not in (
        "completed",
        "failed",
        "cancelled",
        "stopped",
        "domain_gate_rejected",
        "intent_expired",
    ):
        _fail("invalid_value", "terminal_outcome")


@dataclass(frozen=True)
class CompleteAttempt(_ExistingTaskOperation):
    attempt_ref: str
    terminal_outcome: str
    run_ref: Optional[str] = None
    provider_evidence_ref: Optional[str] = None

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_ref(self.attempt_ref, "attempt_ref", "attempt:")
        if self.terminal_outcome != "completed":
            _fail("invalid_value", "terminal_outcome")
        _validate_ref(self.run_ref, "run_ref", "run:")
        _validate_ref(
            self.provider_evidence_ref,
            "provider_evidence_ref",
            "provider-evidence:",
        )


@dataclass(frozen=True)
class CompleteTask(_ExistingTaskOperation):
    terminal_outcome: str
    run_ref: Optional[str] = None
    provider_evidence_ref: Optional[str] = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.terminal_outcome not in (
            "completed",
            "failed",
            "cancelled",
            "stopped",
        ):
            _fail("invalid_value", "terminal_outcome")
        if self.terminal_outcome == "completed":
            _validate_ref(self.run_ref, "run_ref", "run:")
            _validate_ref(
                self.provider_evidence_ref,
                "provider_evidence_ref",
                "provider-evidence:",
            )
        elif self.run_ref is not None or self.provider_evidence_ref is not None:
            _fail("invalid_value", "terminal_evidence")


WorkflowCommand = Union[
    StartResearch,
    ContinueResearch,
    BindResearchClaim,
    ProposePlan,
    RevisePlan,
    RequestPlanConfirmation,
    ConfirmPlan,
    ConfirmFormula,
    BindCandidateManifest,
    ObserveSubmission,
    ObserveRun,
    ObserveProviderEvidence,
    ObserveGate3,
    LinkResult,
    EnterDomainGate,
    ResolveDomainGate,
    BeginReconcile,
    ResolveReconcile,
    RequestStop,
    ObserveStop,
    CompleteAttempt,
    CompleteTask,
]

COMMAND_TYPES = (
    StartResearch,
    ContinueResearch,
    BindResearchClaim,
    ProposePlan,
    RevisePlan,
    RequestPlanConfirmation,
    ConfirmPlan,
    ConfirmFormula,
    BindCandidateManifest,
    ObserveSubmission,
    ObserveRun,
    ObserveProviderEvidence,
    ObserveGate3,
    LinkResult,
    EnterDomainGate,
    ResolveDomainGate,
    BeginReconcile,
    ResolveReconcile,
    RequestStop,
    ObserveStop,
    CompleteAttempt,
    CompleteTask,
)


def parse_workflow_command_document(
    document: Mapping[str, Any],
) -> WorkflowCommand:
    if type(document) is not dict:
        raise TypeError("workflow command document must be a built-in dict")
    if any(type(key) is not str for key in document):
        _fail("invalid_document", "keys")
    if document.get("schema_version") != 2:
        _fail("invalid_document", "schema_version")
    kind = document.get("kind")
    if type(kind) is not str:
        _fail("invalid_document", "kind")
    command_type = {
        _command_kind_type(item): item for item in COMMAND_TYPES
    }.get(kind)
    if command_type is None:
        _fail("unknown_command", "kind")
    field_names = set(command_type.__dataclass_fields__)
    if set(document) != field_names | {"schema_version", "kind"}:
        _fail("invalid_document", "fields")
    command = command_type(**{name: document[name] for name in field_names})
    if command_to_document(command) != document:
        _fail("noncanonical_document", "document")
    return command


def command_to_document(command: WorkflowCommand) -> dict[str, Any]:
    if type(command) not in COMMAND_TYPES:
        raise TypeError("WorkflowAuthority accepts only the closed WorkflowCommand union")
    document: dict[str, Any] = {
        "schema_version": 2,
        "kind": _command_kind(command),
        "operation_id": command.operation_id,
    }
    for field_name in command.__dataclass_fields__:
        if field_name != "operation_id":
            document[field_name] = getattr(command, field_name)
    return document


def canonical_command_digest(command: WorkflowCommand) -> str:
    encoded = json.dumps(
        command_to_document(command),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _command_kind(command: WorkflowCommand) -> str:
    return _command_kind_type(type(command))


def _command_kind_type(command_type: Any) -> str:
    name = command_type.__name__
    output = []
    for index, character in enumerate(name):
        if index and character.isupper():
            output.append("_")
        output.append(character.lower())
    return "workflow." + "".join(output)


@dataclass(frozen=True)
class WorkflowReceipt:
    operation_id: str
    operation_digest: str
    event_id: str
    task_ref: str
    task_version: int
    attempt_ref: Optional[str]
    replayed: bool = False

    def __post_init__(self) -> None:
        _validate_identifier(self.operation_id, "operation_id")
        _validate_digest(self.operation_digest, "operation_digest")
        _validate_event_ref(self.event_id, "event_id")
        _validate_ref(self.task_ref, "task_ref", "task:")
        _validate_positive_version(self.task_version)
        if self.attempt_ref is not None:
            _validate_ref(self.attempt_ref, "attempt_ref", "attempt:")
        if type(self.replayed) is not bool:
            _fail("invalid_type", "replayed")


@dataclass(frozen=True)
class ExpiryTombstoneEvidence:
    owner_user_id: str
    workspace_ref: str
    managed_session_ref: str
    attempt_ref: str
    payload_ref: str
    tombstone_event_ref: str
    tombstone_digest: str

    def __post_init__(self) -> None:
        _validate_identifier(self.owner_user_id, "owner_user_id")
        _validate_ref(self.workspace_ref, "workspace_ref", "workspace:")
        _validate_ref(
            self.managed_session_ref,
            "managed_session_ref",
            "session:",
        )
        _validate_ref(self.attempt_ref, "attempt_ref", "attempt:")
        _validate_payload_ref(self.payload_ref)
        _validate_event_ref(self.tombstone_event_ref, "tombstone_event_ref")
        _validate_digest(self.tombstone_digest, "tombstone_digest")


@dataclass(frozen=True)
class ExpiryTombstoneConsumeReport:
    receipts: Tuple[WorkflowReceipt, ...]
    consumed_count: int
    replayed_count: int

    def __post_init__(self) -> None:
        if type(self.receipts) is not tuple or any(
            type(receipt) is not WorkflowReceipt for receipt in self.receipts
        ):
            _fail("invalid_type", "receipts")
        if (
            type(self.consumed_count) is not int
            or self.consumed_count < 0
            or type(self.replayed_count) is not int
            or self.replayed_count < 0
            or self.consumed_count + self.replayed_count != len(self.receipts)
        ):
            _fail("invalid_value", "counts")


@dataclass(frozen=True)
class Gate3Snapshot:
    run_ref: str
    gate_ref: str
    candidate_ref: str
    manifest_digest: str
    final_receipt_ref: str
    base_commit: str


@dataclass(frozen=True)
class AttemptSnapshot:
    attempt_ref: str
    attempt_number: int
    state: str
    payload_ref: str
    payload_digest: str
    intent_expires_at: str
    payload_tombstone_event_ref: Optional[str]
    payload_tombstone_digest: Optional[str]
    plan_version: Optional[int]
    plan_digest: Optional[str]
    plan_source_ref: Optional[str]
    submission_command_ref: Optional[str]
    run_ref: Optional[str]
    provider_evidence_refs: Tuple[str, ...]
    gate3_refs: Tuple[str, ...]
    gate3_bindings: Tuple[Gate3Snapshot, ...]
    result_refs: Tuple[str, ...]
    domain_gate_ref: Optional[str]
    domain_gate_outcome: Optional[str]
    stop_command_ref: Optional[str]
    stop_outcome: Optional[str]
    stop_observation_digest: Optional[str]
    reconcile_reason: Optional[str]
    terminal_observation_digest: Optional[str]
    terminal_outcome: Optional[str]
    research_claim_digest: Optional[str] = None


@dataclass(frozen=True)
class WorkflowSnapshot:
    owner_user_id: str
    workspace_ref: str
    managed_session_ref: str
    task_ref: str
    version: int
    state: str
    plan_version: Optional[int]
    plan_digest: Optional[str]
    plan_source_ref: Optional[str]
    requires_formula_confirmation: Optional[bool]
    plan_confirmation_note_digest: Optional[str]
    gate1_ref: Optional[str]
    gate1_source_digest: Optional[str]
    gate1_note_digest: Optional[str]
    gate1_candidate_ref: Optional[str]
    gate1_manifest_digest: Optional[str]
    gate3_refs: Tuple[str, ...]
    result_refs: Tuple[str, ...]
    terminal_outcome: Optional[str]
    attempts: Tuple[AttemptSnapshot, ...]
    research_claim_digest: Optional[str] = None


@dataclass(frozen=True)
class WorkflowEvent:
    sequence: int
    event_id: str
    operation_id: str
    operation_digest: str
    task_ref: str
    task_version: int
    event_type: str
    occurred_at: str
    data: Mapping[str, Any]

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or self.sequence < 1:
            _fail("invalid_sequence", "sequence")
        _validate_event_ref(self.event_id, "event_id")
        _validate_identifier(self.operation_id, "operation_id")
        _validate_digest(self.operation_digest, "operation_digest")
        _validate_ref(self.task_ref, "task_ref", "task:")
        _validate_positive_version(self.task_version)
        _validate_identifier(self.event_type, "event_type")
        object.__setattr__(
            self, "occurred_at", normalize_timestamp(self.occurred_at, "occurred_at")
        )
        if type(self.data) is not dict:
            _fail("invalid_type", "data")
        object.__setattr__(self, "data", MappingProxyType(dict(self.data)))


@dataclass(frozen=True)
class WorkflowEventPage:
    events: Tuple[WorkflowEvent, ...]
    next_after_event_id: Optional[str]
    has_more: bool

    def __post_init__(self) -> None:
        if type(self.events) is not tuple:
            _fail("invalid_type", "events")
        if any(type(event) is not WorkflowEvent for event in self.events):
            _fail("invalid_type", "events")
        if self.next_after_event_id is not None:
            _validate_event_ref(
                self.next_after_event_id, "next_after_event_id"
            )
        if type(self.has_more) is not bool:
            _fail("invalid_type", "has_more")
        if self.events:
            if self.next_after_event_id != self.events[-1].event_id:
                _fail("invalid_value", "next_after_event_id")
        elif self.next_after_event_id is not None:
            _validate_event_ref(
                self.next_after_event_id, "next_after_event_id"
            )


def validate_event_limit(limit: Any) -> int:
    if type(limit) is not int or not 1 <= limit <= _MAX_EVENT_PAGE:
        _fail("invalid_limit", "limit")
    return limit


__all__ = (
    "AttemptSnapshot",
    "BeginReconcile",
    "BindCandidateManifest",
    "BindResearchClaim",
    "COMMAND_TYPES",
    "CompleteAttempt",
    "CompleteTask",
    "ConfirmFormula",
    "ConfirmPlan",
    "ContinueResearch",
    "EnterDomainGate",
    "ExpiryTombstoneConsumeReport",
    "ExpiryTombstoneEvidence",
    "Gate3Snapshot",
    "LinkResult",
    "ObserveGate3",
    "ObserveProviderEvidence",
    "ObserveRun",
    "ObserveStop",
    "ObserveSubmission",
    "ProposePlan",
    "RequestPlanConfirmation",
    "RequestStop",
    "RevisePlan",
    "ResolveDomainGate",
    "ResolveReconcile",
    "StartResearch",
    "WorkflowCommand",
    "WorkflowContractError",
    "WorkflowEvent",
    "WorkflowEventPage",
    "WorkflowReceipt",
    "WorkflowSnapshot",
    "canonical_command_digest",
    "command_to_document",
    "normalize_timestamp",
    "payload_digest_from_ref",
    "parse_workflow_command_document",
    "validate_event_limit",
)

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Optional, Type

from hqa.agent_workspace_states import WorkspaceStateError, validate_entity_state


_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")
_HEX64_RE = re.compile(r"[0-9a-f]{64}\Z")


class WorkspaceModelError(ValueError):
    """A value-free model error safe to expose at a contract boundary."""

    def __init__(self, code: str, field: str) -> None:
        self.code = code
        self.field = field
        super().__init__("{}:{}".format(code, field))


def _fail(code: str, field: str) -> None:
    raise WorkspaceModelError(code, field)


def _validate_identifier(value: Any, field: str, prefix: str = "") -> None:
    if (
        type(value) is not str
        or _IDENTIFIER_RE.fullmatch(value) is None
        or (prefix and (not value.startswith(prefix) or value == prefix))
    ):
        _fail("invalid_identifier", field)


def _validate_optional_ref(value: Any, field: str, prefix: str) -> None:
    if value is not None:
        _validate_identifier(value, field, prefix)


def _validate_enum(value: Any, field: str, allowed: tuple[str, ...]) -> None:
    if type(value) is not str or value not in allowed:
        _fail("invalid_value", field)


def _validate_digest(value: Any, field: str) -> None:
    if type(value) is not str or _HEX64_RE.fullmatch(value) is None:
        _fail("invalid_digest", field)


def _validate_optional_digest(value: Any, field: str) -> None:
    if value is not None:
        _validate_digest(value, field)


def _validate_state(kind: str, value: Any) -> None:
    try:
        validate_entity_state(kind, value)
    except WorkspaceStateError as error:
        _fail(error.code, error.field)


def _validate_positive_int(value: Any, field: str) -> None:
    if type(value) is not int or value < 1:
        _fail("invalid_type", field)


def _validate_optional_positive_int(value: Any, field: str) -> None:
    if value is not None:
        _validate_positive_int(value, field)


def _validate_fork_point(value: Any) -> None:
    if (
        type(value) is not str
        or not value
        or len(value) > 2_000
        or not value.isprintable()
    ):
        _fail("invalid_value", "fork_point")


@dataclass(frozen=True)
class SessionRecord:
    session_ref: str
    hermes_session_ref: str
    workspace_ref: str
    owner_user_id: str
    kind: str
    source_channel: Optional[str] = None
    parent_session_ref: Optional[str] = None
    fork_point: Optional[str] = None
    provider_policy_digest: Optional[str] = None
    writer: Optional[str] = None

    def __post_init__(self) -> None:
        if self.kind == "observed_external_session" and self.writer is None:
            object.__setattr__(self, "writer", "external_channel")
        _validate_session(self)

    @property
    def web_writable(self) -> bool:
        return self.kind == "web_managed_session"


def _validate_session(record: SessionRecord) -> None:
    _validate_identifier(record.session_ref, "session_ref", "session:")
    _validate_identifier(record.hermes_session_ref, "hermes_session_ref", "session:")
    _validate_identifier(record.workspace_ref, "workspace_ref", "workspace:")
    _validate_identifier(record.owner_user_id, "owner_user_id")
    _validate_enum(
        record.kind,
        "kind",
        ("observed_external_session", "web_managed_session"),
    )
    _validate_optional_ref(record.parent_session_ref, "parent_session_ref", "session:")
    _validate_optional_digest(record.provider_policy_digest, "provider_policy_digest")

    if record.kind == "observed_external_session":
        _validate_enum(
            record.source_channel,
            "source_channel",
            ("discord", "historical"),
        )
        if record.parent_session_ref is not None:
            _fail("invalid_value", "parent_session_ref")
        if record.fork_point is not None:
            _fail("invalid_value", "fork_point")
        if record.provider_policy_digest is not None:
            _fail("invalid_value", "provider_policy_digest")
        if type(record.writer) is not str or record.writer != "external_channel":
            _fail("invalid_value", "writer")
        return

    _validate_digest(record.provider_policy_digest, "provider_policy_digest")
    if type(record.writer) is not str or record.writer != "web_control_plane":
        _fail("invalid_value", "writer")
    if record.parent_session_ref is None:
        if record.source_channel is not None:
            _fail("invalid_value", "source_channel")
        if record.fork_point is not None:
            _fail("invalid_value", "fork_point")
    else:
        _validate_enum(
            record.source_channel,
            "source_channel",
            ("discord", "historical", "web_managed"),
        )
        _validate_fork_point(record.fork_point)


@dataclass(frozen=True)
class ResearchTaskRecord:
    task_ref: str
    workspace_ref: str
    owner_user_id: str
    session_ref: str
    state: str

    def __post_init__(self) -> None:
        _validate_task(self)


def _validate_task(record: ResearchTaskRecord) -> None:
    _validate_identifier(record.task_ref, "task_ref", "task:")
    _validate_identifier(record.workspace_ref, "workspace_ref", "workspace:")
    _validate_identifier(record.owner_user_id, "owner_user_id")
    _validate_identifier(record.session_ref, "session_ref", "session:")
    _validate_state("task", record.state)


@dataclass(frozen=True)
class ResearchAttemptRecord:
    attempt_ref: str
    workspace_ref: str
    owner_user_id: str
    task_ref: str
    attempt_number: int
    state: str
    durably_accepted: bool
    submission_command_ref: Optional[str] = None

    def __post_init__(self) -> None:
        _validate_attempt(self)


def _validate_attempt(record: ResearchAttemptRecord) -> None:
    _validate_identifier(record.attempt_ref, "attempt_ref", "attempt:")
    _validate_identifier(record.workspace_ref, "workspace_ref", "workspace:")
    _validate_identifier(record.owner_user_id, "owner_user_id")
    _validate_identifier(record.task_ref, "task_ref", "task:")
    _validate_positive_int(record.attempt_number, "attempt_number")
    _validate_state("attempt", record.state)
    if type(record.durably_accepted) is not bool:
        _fail("invalid_type", "durably_accepted")
    _validate_optional_ref(
        record.submission_command_ref,
        "submission_command_ref",
        "command:",
    )
    if record.durably_accepted and record.submission_command_ref is None:
        _fail("cardinality", "submission_command_ref")


@dataclass(frozen=True)
class SubmissionCommandRecord:
    command_ref: str
    workspace_ref: str
    owner_user_id: str
    session_ref: str
    action_ref: str
    kind: str
    state: str
    task_ref: Optional[str] = None
    attempt_ref: Optional[str] = None
    attempt_number: Optional[int] = None
    run_ref: Optional[str] = None

    def __post_init__(self) -> None:
        _validate_submission_command(self)


def _validate_submission_command(record: SubmissionCommandRecord) -> None:
    _validate_identifier(record.command_ref, "command_ref", "command:")
    _validate_identifier(record.workspace_ref, "workspace_ref", "workspace:")
    _validate_identifier(record.owner_user_id, "owner_user_id")
    _validate_identifier(record.session_ref, "session_ref", "session:")
    _validate_identifier(record.action_ref, "action_ref", "action:")
    _validate_enum(
        record.kind,
        "kind",
        ("conversation_turn", "research_attempt"),
    )
    _validate_state("submission_command", record.state)
    _validate_optional_ref(record.task_ref, "task_ref", "task:")
    _validate_optional_ref(record.attempt_ref, "attempt_ref", "attempt:")
    _validate_optional_positive_int(record.attempt_number, "attempt_number")
    _validate_optional_ref(record.run_ref, "run_ref", "run:")

    if record.kind == "conversation_turn":
        if record.task_ref is not None:
            _fail("invalid_value", "task_ref")
        if record.attempt_ref is not None:
            _fail("invalid_value", "attempt_ref")
        if record.attempt_number is not None:
            _fail("invalid_value", "attempt_number")
        return

    if record.task_ref is None:
        _fail("invalid_value", "task_ref")
    if record.attempt_ref is None:
        _fail("invalid_value", "attempt_ref")
    if record.attempt_number is None:
        _fail("invalid_value", "attempt_number")


@dataclass(frozen=True)
class RunRecord:
    run_ref: str
    workspace_ref: str
    owner_user_id: str
    session_ref: str
    submission_command_ref: str
    state: str
    attempt_ref: Optional[str] = None

    def __post_init__(self) -> None:
        _validate_run(self)


def _validate_run(record: RunRecord) -> None:
    _validate_identifier(record.run_ref, "run_ref", "run:")
    _validate_identifier(record.workspace_ref, "workspace_ref", "workspace:")
    _validate_identifier(record.owner_user_id, "owner_user_id")
    _validate_identifier(record.session_ref, "session_ref", "session:")
    _validate_identifier(
        record.submission_command_ref,
        "submission_command_ref",
        "command:",
    )
    _validate_state("hermes_run", record.state)
    _validate_optional_ref(record.attempt_ref, "attempt_ref", "attempt:")


@dataclass(frozen=True)
class ResultLink:
    result_ref: str
    run_ref: str
    workspace_ref: str
    owner_user_id: str

    def __post_init__(self) -> None:
        _validate_result_link(self)


def _validate_result_link(record: ResultLink) -> None:
    _validate_identifier(record.result_ref, "result_ref", "result:")
    _validate_identifier(record.run_ref, "run_ref", "run:")
    _validate_identifier(record.workspace_ref, "workspace_ref", "workspace:")
    _validate_identifier(record.owner_user_id, "owner_user_id")


@dataclass(frozen=True)
class ControlCommandLink:
    command_ref: str
    run_ref: str
    workspace_ref: str
    owner_user_id: str

    def __post_init__(self) -> None:
        _validate_control_command_link(self)


def _validate_control_command_link(record: ControlCommandLink) -> None:
    _validate_identifier(record.command_ref, "command_ref", "command:")
    _validate_identifier(record.run_ref, "run_ref", "run:")
    _validate_identifier(record.workspace_ref, "workspace_ref", "workspace:")
    _validate_identifier(record.owner_user_id, "owner_user_id")


def _defensive_tuple(value: Any, field: str, item_type: Type[Any]) -> tuple[Any, ...]:
    if type(value) not in (list, tuple):
        _fail("invalid_type", field)
    snapshot = tuple(value)
    if any(type(item) is not item_type for item in snapshot):
        _fail("invalid_type", field)
    return snapshot


def _unique_index(
    records: tuple[Any, ...], attribute: str, field: str
) -> dict[str, Any]:
    index: dict[str, Any] = {}
    for record in records:
        identity = getattr(record, attribute)
        if identity in index:
            _fail("duplicate_ref", field)
        index[identity] = record
    return index


@dataclass(frozen=True)
class WorkspaceGraph:
    workspace_ref: str
    owner_user_id: str
    sessions: tuple[SessionRecord, ...] = ()
    tasks: tuple[ResearchTaskRecord, ...] = ()
    attempts: tuple[ResearchAttemptRecord, ...] = ()
    submission_commands: tuple[SubmissionCommandRecord, ...] = ()
    runs: tuple[RunRecord, ...] = ()
    result_links: tuple[ResultLink, ...] = ()
    control_command_links: tuple[ControlCommandLink, ...] = ()

    def __post_init__(self) -> None:
        _validate_identifier(self.workspace_ref, "workspace_ref", "workspace:")
        _validate_identifier(self.owner_user_id, "owner_user_id")
        record_types = (
            ("sessions", SessionRecord),
            ("tasks", ResearchTaskRecord),
            ("attempts", ResearchAttemptRecord),
            ("submission_commands", SubmissionCommandRecord),
            ("runs", RunRecord),
            ("result_links", ResultLink),
            ("control_command_links", ControlCommandLink),
        )
        for field, item_type in record_types:
            object.__setattr__(
                self,
                field,
                _defensive_tuple(getattr(self, field), field, item_type),
            )


def validate_workspace_graph(graph: WorkspaceGraph) -> None:
    if type(graph) is not WorkspaceGraph:
        _fail("invalid_type", "graph")
    _validate_identifier(graph.workspace_ref, "workspace_ref", "workspace:")
    _validate_identifier(graph.owner_user_id, "owner_user_id")
    validators = (
        ("sessions", SessionRecord, _validate_session),
        ("tasks", ResearchTaskRecord, _validate_task),
        ("attempts", ResearchAttemptRecord, _validate_attempt),
        (
            "submission_commands",
            SubmissionCommandRecord,
            _validate_submission_command,
        ),
        ("runs", RunRecord, _validate_run),
        ("result_links", ResultLink, _validate_result_link),
        (
            "control_command_links",
            ControlCommandLink,
            _validate_control_command_link,
        ),
    )
    for field, record_type, validator in validators:
        records = getattr(graph, field)
        if type(records) is not tuple:
            _fail("invalid_type", field)
        for record in records:
            if type(record) is not record_type:
                _fail("invalid_type", field)
            validator(record)
            if record.workspace_ref != graph.workspace_ref:
                _fail("containment", "workspace_ref")
            if record.owner_user_id != graph.owner_user_id:
                _fail("containment", "owner_user_id")

    identity_fields = (
        (graph.sessions, "session_ref", "session_ref"),
        (graph.tasks, "task_ref", "task_ref"),
        (graph.attempts, "attempt_ref", "attempt_ref"),
        (graph.submission_commands, "command_ref", "command_ref"),
        (graph.runs, "run_ref", "run_ref"),
        (graph.result_links, "result_ref", "result_ref"),
        (graph.control_command_links, "command_ref", "command_ref"),
    )
    for records, attribute, field in identity_fields:
        _unique_index(records, attribute, field)
    _unique_index(graph.sessions, "hermes_session_ref", "hermes_session_ref")
    _unique_index(graph.submission_commands, "action_ref", "action_ref")
    submission_command_refs = {
        command.command_ref for command in graph.submission_commands
    }
    if any(
        link.command_ref in submission_command_refs
        for link in graph.control_command_links
    ):
        _fail("duplicate_ref", "command_ref")
    sessions_by_ref = _unique_index(graph.sessions, "session_ref", "session_ref")
    for session in graph.sessions:
        if (
            session.parent_session_ref is not None
            and session.parent_session_ref not in sessions_by_ref
        ):
            _fail("missing_ref", "parent_session_ref")
        if session.parent_session_ref is not None:
            parent = sessions_by_ref[session.parent_session_ref]
            expected_channel = (
                parent.source_channel
                if parent.kind == "observed_external_session"
                else "web_managed"
            )
            if session.source_channel != expected_channel:
                _fail("binding_mismatch", "source_channel")
    lineage_state: dict[str, int] = {}
    for session in graph.sessions:
        if lineage_state.get(session.session_ref) == 2:
            continue
        path: list[str] = []
        cursor = session
        while True:
            state = lineage_state.get(cursor.session_ref, 0)
            if state == 1:
                _fail("lineage_cycle", "parent_session_ref")
            if state == 2:
                break
            lineage_state[cursor.session_ref] = 1
            path.append(cursor.session_ref)
            if cursor.parent_session_ref is None:
                break
            cursor = sessions_by_ref[cursor.parent_session_ref]
        for session_ref in path:
            lineage_state[session_ref] = 2

    tasks_by_ref = _unique_index(graph.tasks, "task_ref", "task_ref")
    attempts_by_ref = _unique_index(graph.attempts, "attempt_ref", "attempt_ref")
    commands_by_ref = _unique_index(
        graph.submission_commands, "command_ref", "command_ref"
    )
    runs_by_ref = _unique_index(graph.runs, "run_ref", "run_ref")

    for task in graph.tasks:
        if task.session_ref not in sessions_by_ref:
            _fail("missing_ref", "session_ref")
        if not sessions_by_ref[task.session_ref].web_writable:
            _fail("read_only_session", "session_ref")
    for attempt in graph.attempts:
        if attempt.task_ref not in tasks_by_ref:
            _fail("missing_ref", "task_ref")
        if (
            attempt.submission_command_ref is not None
            and attempt.submission_command_ref not in commands_by_ref
        ):
            _fail("missing_ref", "submission_command_ref")
    for command in graph.submission_commands:
        if command.session_ref not in sessions_by_ref:
            _fail("missing_ref", "session_ref")
        if not sessions_by_ref[command.session_ref].web_writable:
            _fail("read_only_session", "session_ref")
        if command.task_ref is not None and command.task_ref not in tasks_by_ref:
            _fail("missing_ref", "task_ref")
        if (
            command.attempt_ref is not None
            and command.attempt_ref not in attempts_by_ref
        ):
            _fail("missing_ref", "attempt_ref")
        if command.run_ref is not None and command.run_ref not in runs_by_ref:
            _fail("missing_ref", "run_ref")
    for run in graph.runs:
        if run.session_ref not in sessions_by_ref:
            _fail("missing_ref", "session_ref")
        if run.submission_command_ref not in commands_by_ref:
            _fail("missing_ref", "submission_command_ref")
        if run.attempt_ref is not None and run.attempt_ref not in attempts_by_ref:
            _fail("missing_ref", "attempt_ref")
    for link in graph.result_links:
        if link.run_ref not in runs_by_ref:
            _fail("missing_ref", "run_ref")
    for link in graph.control_command_links:
        if link.run_ref not in runs_by_ref:
            _fail("missing_ref", "run_ref")

    attempts_by_task: dict[str, list[ResearchAttemptRecord]] = {
        task.task_ref: [] for task in graph.tasks
    }
    for attempt in graph.attempts:
        attempts_by_task[attempt.task_ref].append(attempt)
    for task in graph.tasks:
        task_attempts = attempts_by_task[task.task_ref]
        numbers = sorted(attempt.attempt_number for attempt in task_attempts)
        if not numbers or numbers != list(range(1, len(numbers) + 1)):
            _fail("cardinality", "attempt_number")

    bound_attempt_refs: set[str] = set()
    for command in graph.submission_commands:
        if command.kind != "research_attempt":
            continue
        if command.attempt_ref in bound_attempt_refs:
            _fail("cardinality", "attempt_ref")
        bound_attempt_refs.add(command.attempt_ref)

    bound_submission_refs: set[str] = set()
    for attempt in graph.attempts:
        if attempt.submission_command_ref is None:
            continue
        if attempt.submission_command_ref in bound_submission_refs:
            _fail("cardinality", "submission_command_ref")
        bound_submission_refs.add(attempt.submission_command_ref)

    for command in graph.submission_commands:
        if command.kind != "research_attempt":
            continue
        task = tasks_by_ref[command.task_ref]
        attempt = attempts_by_ref[command.attempt_ref]
        if attempt.task_ref != command.task_ref:
            _fail("binding_mismatch", "task_ref")
        if attempt.attempt_number != command.attempt_number:
            _fail("binding_mismatch", "attempt_number")
        if task.session_ref != command.session_ref:
            _fail("binding_mismatch", "session_ref")
        if attempt.submission_command_ref != command.command_ref:
            _fail("binding_mismatch", "submission_command_ref")

    for attempt in graph.attempts:
        if attempt.submission_command_ref is None:
            continue
        command = commands_by_ref[attempt.submission_command_ref]
        if command.kind != "research_attempt":
            _fail("binding_mismatch", "submission_command_ref")
        if command.attempt_ref != attempt.attempt_ref:
            _fail("binding_mismatch", "attempt_ref")

    linked_run_refs: set[str] = set()
    for command in graph.submission_commands:
        if command.run_ref is None:
            continue
        if command.run_ref in linked_run_refs:
            _fail("cardinality", "run_ref")
        linked_run_refs.add(command.run_ref)

    run_command_refs: set[str] = set()
    for run in graph.runs:
        if run.submission_command_ref in run_command_refs:
            _fail("cardinality", "submission_command_ref")
        run_command_refs.add(run.submission_command_ref)

    for command in graph.submission_commands:
        if command.run_ref is None:
            continue
        run = runs_by_ref[command.run_ref]
        if run.submission_command_ref != command.command_ref:
            _fail("binding_mismatch", "run_ref")

    for run in graph.runs:
        command = commands_by_ref[run.submission_command_ref]
        if command.run_ref != run.run_ref:
            _fail("binding_mismatch", "run_ref")
        if run.session_ref != command.session_ref:
            _fail("binding_mismatch", "session_ref")
        if command.kind == "conversation_turn":
            if run.attempt_ref is not None:
                _fail("binding_mismatch", "attempt_ref")
        elif run.attempt_ref != command.attempt_ref:
            _fail("binding_mismatch", "attempt_ref")


__all__ = (
    "ControlCommandLink",
    "ResearchAttemptRecord",
    "ResearchTaskRecord",
    "ResultLink",
    "RunRecord",
    "SessionRecord",
    "SubmissionCommandRecord",
    "WorkspaceGraph",
    "WorkspaceModelError",
    "validate_workspace_graph",
)

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, is_dataclass, replace

import pytest


WORKSPACE = "workspace:alpha"
OWNER = "owner-1"


class _EqualitySpoof:
    def __eq__(self, other: object) -> bool:
        return True

    def __hash__(self) -> int:
        return 1


class _StringSubclass(str):
    pass


class _CustomIterable:
    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(())


def _valid_records():
    from hqa.agent_workspace_model import (
        ControlCommandLink,
        ResearchAttemptRecord,
        ResearchTaskRecord,
        ResultLink,
        RunRecord,
        SessionRecord,
        SubmissionCommandRecord,
    )

    sessions = (
        SessionRecord(
            session_ref="session:external",
            hermes_session_ref="session:hermes.discord",
            workspace_ref=WORKSPACE,
            owner_user_id=OWNER,
            kind="observed_external_session",
            source_channel="discord",
        ),
        SessionRecord(
            session_ref="session:managed",
            hermes_session_ref="session:hermes.web-1",
            workspace_ref=WORKSPACE,
            owner_user_id=OWNER,
            kind="web_managed_session",
            provider_policy_digest="a" * 64,
            writer="web_control_plane",
        ),
        SessionRecord(
            session_ref="session:fork",
            hermes_session_ref="session:hermes.web-2",
            workspace_ref=WORKSPACE,
            owner_user_id=OWNER,
            kind="web_managed_session",
            source_channel="discord",
            parent_session_ref="session:external",
            fork_point="message:42",
            provider_policy_digest="b" * 64,
            writer="web_control_plane",
        ),
    )
    tasks = (
        ResearchTaskRecord(
            task_ref="task:research",
            workspace_ref=WORKSPACE,
            owner_user_id=OWNER,
            session_ref="session:fork",
            state="running",
        ),
    )
    attempts = (
        ResearchAttemptRecord(
            attempt_ref="attempt:research-1",
            workspace_ref=WORKSPACE,
            owner_user_id=OWNER,
            task_ref="task:research",
            attempt_number=1,
            state="completed",
            durably_accepted=True,
            submission_command_ref="command:research-1",
        ),
        ResearchAttemptRecord(
            attempt_ref="attempt:research-2",
            workspace_ref=WORKSPACE,
            owner_user_id=OWNER,
            task_ref="task:research",
            attempt_number=2,
            state="running",
            durably_accepted=True,
            submission_command_ref="command:research-2",
        ),
    )
    submission_commands = (
        SubmissionCommandRecord(
            command_ref="command:conversation",
            workspace_ref=WORKSPACE,
            owner_user_id=OWNER,
            session_ref="session:managed",
            action_ref="action:turn-1",
            kind="conversation_turn",
            state="run_linked",
            run_ref="run:conversation",
        ),
        SubmissionCommandRecord(
            command_ref="command:research-1",
            workspace_ref=WORKSPACE,
            owner_user_id=OWNER,
            session_ref="session:fork",
            action_ref="action:research-1",
            kind="research_attempt",
            state="run_linked",
            task_ref="task:research",
            attempt_ref="attempt:research-1",
            attempt_number=1,
            run_ref="run:research-1",
        ),
        SubmissionCommandRecord(
            command_ref="command:research-2",
            workspace_ref=WORKSPACE,
            owner_user_id=OWNER,
            session_ref="session:fork",
            action_ref="action:research-2",
            kind="research_attempt",
            state="run_linked",
            task_ref="task:research",
            attempt_ref="attempt:research-2",
            attempt_number=2,
            run_ref="run:research-2",
        ),
    )
    runs = (
        RunRecord(
            run_ref="run:conversation",
            workspace_ref=WORKSPACE,
            owner_user_id=OWNER,
            session_ref="session:managed",
            submission_command_ref="command:conversation",
        ),
        RunRecord(
            run_ref="run:research-1",
            workspace_ref=WORKSPACE,
            owner_user_id=OWNER,
            session_ref="session:fork",
            submission_command_ref="command:research-1",
            attempt_ref="attempt:research-1",
        ),
        RunRecord(
            run_ref="run:research-2",
            workspace_ref=WORKSPACE,
            owner_user_id=OWNER,
            session_ref="session:fork",
            submission_command_ref="command:research-2",
            attempt_ref="attempt:research-2",
        ),
    )
    result_links = (
        ResultLink(
            result_ref="result:research-1-summary",
            run_ref="run:research-1",
            workspace_ref=WORKSPACE,
            owner_user_id=OWNER,
        ),
        ResultLink(
            result_ref="result:research-1-report",
            run_ref="run:research-1",
            workspace_ref=WORKSPACE,
            owner_user_id=OWNER,
        ),
    )
    control_command_links = (
        ControlCommandLink(
            command_ref="command:stop-1",
            run_ref="run:research-1",
            workspace_ref=WORKSPACE,
            owner_user_id=OWNER,
        ),
        ControlCommandLink(
            command_ref="command:approval-1",
            run_ref="run:research-1",
            workspace_ref=WORKSPACE,
            owner_user_id=OWNER,
        ),
    )
    return {
        "sessions": sessions,
        "tasks": tasks,
        "attempts": attempts,
        "submission_commands": submission_commands,
        "runs": runs,
        "result_links": result_links,
        "control_command_links": control_command_links,
    }


def _valid_graph():
    from hqa.agent_workspace_model import WorkspaceGraph

    return WorkspaceGraph(
        workspace_ref=WORKSPACE,
        owner_user_id=OWNER,
        **_valid_records(),
    )


def test_records_are_exact_frozen_dataclasses_with_semantic_fields() -> None:
    from hqa.agent_workspace_model import WorkspaceGraph

    graph = _valid_graph()
    records = (
        *graph.sessions,
        *graph.tasks,
        *graph.attempts,
        *graph.submission_commands,
        *graph.runs,
        *graph.result_links,
        *graph.control_command_links,
        graph,
    )

    assert all(is_dataclass(record) for record in records)
    assert [field.name for field in fields(WorkspaceGraph)] == [
        "workspace_ref",
        "owner_user_id",
        "sessions",
        "tasks",
        "attempts",
        "submission_commands",
        "runs",
        "result_links",
        "control_command_links",
    ]
    with pytest.raises(FrozenInstanceError):
        graph.workspace_ref = "workspace:other"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        graph.sessions[0].kind = "web_managed_session"  # type: ignore[misc]


def test_graph_defensively_copies_builtin_collections_to_tuples() -> None:
    from hqa.agent_workspace_model import WorkspaceGraph

    mutable_records = {name: list(values) for name, values in _valid_records().items()}
    graph = WorkspaceGraph(
        workspace_ref=WORKSPACE,
        owner_user_id=OWNER,
        **mutable_records,
    )
    mutable_records["sessions"].clear()

    assert type(graph.sessions) is tuple
    assert len(graph.sessions) == 3
    assert all(
        type(getattr(graph, field)) is tuple
        for field in (
            "sessions",
            "tasks",
            "attempts",
            "submission_commands",
            "runs",
            "result_links",
            "control_command_links",
        )
    )


def test_graph_rejects_custom_iterables_and_wrong_record_types() -> None:
    from hqa.agent_workspace_model import WorkspaceGraph, WorkspaceModelError

    base = _valid_records()
    for invalid in (_CustomIterable(), {"not": "ordered"}, "sessions"):
        with pytest.raises(WorkspaceModelError) as caught:
            WorkspaceGraph(
                workspace_ref=WORKSPACE,
                owner_user_id=OWNER,
                **dict(base, sessions=invalid),
            )
        assert caught.value.code == "invalid_type"
        assert caught.value.field == "sessions"

    with pytest.raises(WorkspaceModelError, match="invalid_type:sessions"):
        WorkspaceGraph(
            workspace_ref=WORKSPACE,
            owner_user_id=OWNER,
            **dict(base, sessions=(base["tasks"][0],)),
        )


def test_record_boundaries_reject_bool_subclasses_and_equality_spoofs() -> None:
    from hqa.agent_workspace_model import (
        ResearchAttemptRecord,
        SessionRecord,
        SubmissionCommandRecord,
        WorkspaceGraph,
        WorkspaceModelError,
    )

    with pytest.raises(WorkspaceModelError):
        ResearchAttemptRecord(
            attempt_ref="attempt:bad",
            workspace_ref=WORKSPACE,
            owner_user_id=OWNER,
            task_ref="task:research",
            attempt_number=True,  # type: ignore[arg-type]
            state="planned",
            durably_accepted=False,
        )
    with pytest.raises(WorkspaceModelError):
        ResearchAttemptRecord(
            attempt_ref="attempt:bad",
            workspace_ref=WORKSPACE,
            owner_user_id=OWNER,
            task_ref="task:research",
            attempt_number=1,
            state="planned",
            durably_accepted=1,  # type: ignore[arg-type]
        )
    with pytest.raises(WorkspaceModelError):
        SessionRecord(
            session_ref="session:bad",
            hermes_session_ref="session:hermes.bad",
            workspace_ref=WORKSPACE,
            owner_user_id=OWNER,
            kind=_EqualitySpoof(),  # type: ignore[arg-type]
            source_channel="discord",
        )
    with pytest.raises(WorkspaceModelError):
        SubmissionCommandRecord(
            command_ref="command:bad",
            workspace_ref=WORKSPACE,
            owner_user_id=OWNER,
            session_ref="session:managed",
            action_ref="action:bad",
            kind=_StringSubclass("conversation_turn"),
            state="prepared",
        )
    with pytest.raises(WorkspaceModelError):
        WorkspaceGraph(
            workspace_ref=_StringSubclass(WORKSPACE),
            owner_user_id=OWNER,
        )


@pytest.mark.parametrize(
    ("override", "field"),
    [
        ({"session_ref": "session:"}, "session_ref"),
        ({"hermes_session_ref": "run:not-a-session"}, "hermes_session_ref"),
        ({"workspace_ref": "workspace:bad/path"}, "workspace_ref"),
        ({"owner_user_id": ""}, "owner_user_id"),
        ({"provider_policy_digest": "A" * 64}, "provider_policy_digest"),
        ({"provider_policy_digest": "a" * 63}, "provider_policy_digest"),
    ],
)
def test_session_records_reject_invalid_semantic_values(
    override: dict[str, object], field: str
) -> None:
    from hqa.agent_workspace_model import SessionRecord, WorkspaceModelError

    valid = {
        "session_ref": "session:managed",
        "hermes_session_ref": "session:hermes.web",
        "workspace_ref": WORKSPACE,
        "owner_user_id": OWNER,
        "kind": "web_managed_session",
        "provider_policy_digest": "a" * 64,
        "writer": "web_control_plane",
    }
    with pytest.raises(WorkspaceModelError) as caught:
        SessionRecord(**dict(valid, **override))
    assert caught.value.field == field


def test_session_kinds_enforce_external_read_only_and_managed_writer_shape() -> None:
    from hqa.agent_workspace_model import SessionRecord, WorkspaceModelError

    external = {
        "session_ref": "session:external",
        "hermes_session_ref": "session:hermes.external",
        "workspace_ref": WORKSPACE,
        "owner_user_id": OWNER,
        "kind": "observed_external_session",
        "source_channel": "discord",
    }
    invalid_external = (
        {"source_channel": "web"},
        {"parent_session_ref": "session:parent"},
        {"fork_point": "message:1"},
        {"provider_policy_digest": "a" * 64},
        {"writer": "web_control_plane"},
    )
    for override in invalid_external:
        with pytest.raises(WorkspaceModelError):
            SessionRecord(**dict(external, **override))

    managed = {
        "session_ref": "session:managed",
        "hermes_session_ref": "session:hermes.managed",
        "workspace_ref": WORKSPACE,
        "owner_user_id": OWNER,
        "kind": "web_managed_session",
        "provider_policy_digest": "a" * 64,
        "writer": "web_control_plane",
    }
    for override in (
        {"provider_policy_digest": None},
        {"writer": None},
        {"writer": "discord"},
        {"parent_session_ref": "session:external"},
        {"source_channel": "discord", "fork_point": "message:1"},
    ):
        with pytest.raises(WorkspaceModelError):
            SessionRecord(**dict(managed, **override))


def test_model_errors_expose_only_safe_code_and_field() -> None:
    from hqa.agent_workspace_model import SessionRecord, WorkspaceModelError

    secret_value = "secret/value-that-must-not-leak"
    with pytest.raises(WorkspaceModelError) as caught:
        SessionRecord(
            session_ref="session:external",
            hermes_session_ref="session:hermes.external",
            workspace_ref=WORKSPACE,
            owner_user_id=secret_value,
            kind="observed_external_session",
            source_channel="discord",
        )

    assert caught.value.code == "invalid_identifier"
    assert caught.value.field == "owner_user_id"
    assert str(caught.value) == "invalid_identifier:owner_user_id"
    assert secret_value not in str(caught.value)


def test_valid_graph_proves_frozen_cardinality_and_session_semantics() -> None:
    from hqa.agent_workspace_model import (
        SessionRecord,
        validate_workspace_graph,
    )

    graph = _valid_graph()
    second_child = SessionRecord(
        session_ref="session:fork-2",
        hermes_session_ref="session:hermes.web-3",
        workspace_ref=WORKSPACE,
        owner_user_id=OWNER,
        kind="web_managed_session",
        source_channel="discord",
        parent_session_ref="session:external",
        fork_point="message:84",
        provider_policy_digest="c" * 64,
        writer="web_control_plane",
    )
    graph = replace(graph, sessions=graph.sessions + (second_child,))

    validate_workspace_graph(graph)

    external, managed, first_child, other_child = graph.sessions
    assert external.web_writable is False
    assert external.writer == "external_channel"
    assert managed.web_writable is True
    assert managed.writer == "web_control_plane"
    assert first_child.parent_session_ref == other_child.parent_session_ref
    assert graph.attempts[0].submission_command_ref != (
        graph.attempts[1].submission_command_ref
    )
    assert graph.submission_commands[0].task_ref is None
    assert graph.submission_commands[0].attempt_ref is None
    assert graph.runs[0].attempt_ref is None


@pytest.mark.parametrize(
    "collection",
    (
        "sessions",
        "tasks",
        "attempts",
        "submission_commands",
        "runs",
        "result_links",
        "control_command_links",
    ),
)
@pytest.mark.parametrize(
    ("field", "invalid_value"),
    (
        ("workspace_ref", "workspace:other"),
        ("owner_user_id", "owner-2"),
    ),
)
def test_every_record_is_contained_by_exact_workspace_and_owner(
    collection: str, field: str, invalid_value: str
) -> None:
    from hqa.agent_workspace_model import (
        WorkspaceModelError,
        validate_workspace_graph,
    )

    graph = _valid_graph()
    records = getattr(graph, collection)
    escaped = replace(records[0], **{field: invalid_value})
    invalid_graph = replace(graph, **{collection: (escaped,) + records[1:]})

    with pytest.raises(WorkspaceModelError) as caught:
        validate_workspace_graph(invalid_graph)
    assert caught.value.code == "containment"
    assert caught.value.field == field


@pytest.mark.parametrize(
    ("collection", "identity_field"),
    (
        ("sessions", "session_ref"),
        ("tasks", "task_ref"),
        ("attempts", "attempt_ref"),
        ("submission_commands", "command_ref"),
        ("runs", "run_ref"),
        ("result_links", "result_ref"),
        ("control_command_links", "command_ref"),
    ),
)
def test_all_record_identities_are_unique(collection: str, identity_field: str) -> None:
    from hqa.agent_workspace_model import (
        WorkspaceModelError,
        validate_workspace_graph,
    )

    graph = _valid_graph()
    records = getattr(graph, collection)
    invalid_graph = replace(graph, **{collection: records + (records[0],)})

    with pytest.raises(WorkspaceModelError) as caught:
        validate_workspace_graph(invalid_graph)
    assert caught.value.code == "duplicate_ref"
    assert caught.value.field == identity_field


def test_each_session_has_a_unique_exact_hermes_session_ref() -> None:
    from hqa.agent_workspace_model import (
        WorkspaceModelError,
        validate_workspace_graph,
    )

    graph = _valid_graph()
    duplicate = replace(
        graph.sessions[1],
        hermes_session_ref=graph.sessions[0].hermes_session_ref,
    )
    invalid_graph = replace(
        graph,
        sessions=(graph.sessions[0], duplicate) + graph.sessions[2:],
    )

    with pytest.raises(WorkspaceModelError) as caught:
        validate_workspace_graph(invalid_graph)
    assert caught.value.code == "duplicate_ref"
    assert caught.value.field == "hermes_session_ref"


def test_managed_session_parent_must_exist_in_the_same_graph() -> None:
    from hqa.agent_workspace_model import (
        WorkspaceModelError,
        validate_workspace_graph,
    )

    graph = _valid_graph()
    orphan = replace(graph.sessions[2], parent_session_ref="session:missing")
    invalid_graph = replace(graph, sessions=graph.sessions[:2] + (orphan,))

    with pytest.raises(WorkspaceModelError) as caught:
        validate_workspace_graph(invalid_graph)
    assert caught.value.code == "missing_ref"
    assert caught.value.field == "parent_session_ref"


def test_session_lineage_rejects_self_and_multi_node_cycles() -> None:
    from hqa.agent_workspace_model import (
        WorkspaceModelError,
        validate_workspace_graph,
    )

    graph = _valid_graph()
    self_cycle = replace(
        graph.sessions[2],
        source_channel="web_managed",
        parent_session_ref=graph.sessions[2].session_ref,
    )
    two_cycle_left = replace(
        graph.sessions[1],
        source_channel="web_managed",
        parent_session_ref=graph.sessions[2].session_ref,
        fork_point="message:21",
    )
    two_cycle_right = replace(
        graph.sessions[2],
        source_channel="web_managed",
        parent_session_ref=graph.sessions[1].session_ref,
    )
    invalid_graphs = (
        replace(graph, sessions=graph.sessions[:2] + (self_cycle,)),
        replace(
            graph,
            sessions=(
                graph.sessions[0],
                two_cycle_left,
                two_cycle_right,
            ),
        ),
    )

    for invalid_graph in invalid_graphs:
        with pytest.raises(WorkspaceModelError) as caught:
            validate_workspace_graph(invalid_graph)
        assert caught.value.code == "lineage_cycle"
        assert caught.value.field == "parent_session_ref"


@pytest.mark.parametrize(
    ("collection", "index", "field", "missing_ref"),
    (
        ("tasks", 0, "session_ref", "session:missing"),
        ("attempts", 0, "task_ref", "task:missing"),
        (
            "attempts",
            0,
            "submission_command_ref",
            "command:missing",
        ),
        ("submission_commands", 0, "session_ref", "session:missing"),
        ("submission_commands", 1, "task_ref", "task:missing"),
        ("submission_commands", 1, "attempt_ref", "attempt:missing"),
        ("submission_commands", 0, "run_ref", "run:missing"),
        ("runs", 0, "session_ref", "session:missing"),
        (
            "runs",
            0,
            "submission_command_ref",
            "command:missing",
        ),
        ("runs", 1, "attempt_ref", "attempt:missing"),
        ("result_links", 0, "run_ref", "run:missing"),
        ("control_command_links", 0, "run_ref", "run:missing"),
    ),
)
def test_every_relational_reference_must_exist(
    collection: str, index: int, field: str, missing_ref: str
) -> None:
    from hqa.agent_workspace_model import (
        WorkspaceModelError,
        validate_workspace_graph,
    )

    graph = _valid_graph()
    records = getattr(graph, collection)
    invalid_record = replace(records[index], **{field: missing_ref})
    invalid_records = records[:index] + (invalid_record,) + records[index + 1 :]
    invalid_graph = replace(graph, **{collection: invalid_records})

    with pytest.raises(WorkspaceModelError) as caught:
        validate_workspace_graph(invalid_graph)
    assert caught.value.code == "missing_ref"
    assert caught.value.field == field


def test_each_task_has_contiguous_unique_attempt_numbers_starting_at_one() -> None:
    from hqa.agent_workspace_model import (
        WorkspaceModelError,
        validate_workspace_graph,
    )

    graph = _valid_graph()
    no_attempts = replace(
        graph,
        attempts=(),
        submission_commands=(graph.submission_commands[0],),
        runs=(graph.runs[0],),
        result_links=(),
        control_command_links=(),
    )
    invalid_graphs = [no_attempts]
    for invalid_number in (1, 3):
        changed_attempt = replace(graph.attempts[1], attempt_number=invalid_number)
        changed_command = replace(
            graph.submission_commands[2], attempt_number=invalid_number
        )
        invalid_graphs.append(
            replace(
                graph,
                attempts=(graph.attempts[0], changed_attempt),
                submission_commands=(
                    graph.submission_commands[:2] + (changed_command,)
                ),
            )
        )

    for invalid_graph in invalid_graphs:
        with pytest.raises(WorkspaceModelError) as caught:
            validate_workspace_graph(invalid_graph)
        assert caught.value.code == "cardinality"
        assert caught.value.field == "attempt_number"


def test_fork_source_channel_exactly_matches_external_or_managed_parent() -> None:
    from hqa.agent_workspace_model import (
        SessionRecord,
        WorkspaceModelError,
        validate_workspace_graph,
    )

    graph = _valid_graph()
    managed_child = SessionRecord(
        session_ref="session:managed-child",
        hermes_session_ref="session:hermes.web-managed-child",
        workspace_ref=WORKSPACE,
        owner_user_id=OWNER,
        kind="web_managed_session",
        source_channel="web_managed",
        parent_session_ref="session:managed",
        fork_point="message:managed-1",
        provider_policy_digest="d" * 64,
        writer="web_control_plane",
    )
    validate_workspace_graph(replace(graph, sessions=graph.sessions + (managed_child,)))

    mismatched_external = replace(graph.sessions[2], source_channel="historical")
    mismatched_managed = replace(managed_child, source_channel="discord")
    for child in (mismatched_external, mismatched_managed):
        if child.session_ref == graph.sessions[2].session_ref:
            sessions = graph.sessions[:2] + (child,)
        else:
            sessions = graph.sessions + (child,)
        with pytest.raises(WorkspaceModelError) as caught:
            validate_workspace_graph(replace(graph, sessions=sessions))
        assert caught.value.code == "binding_mismatch"
        assert caught.value.field == "source_channel"


def test_workspace_may_have_only_an_ordinary_conversation() -> None:
    from hqa.agent_workspace_model import validate_workspace_graph

    graph = _valid_graph()
    ordinary_only = replace(
        graph,
        tasks=(),
        attempts=(),
        submission_commands=(graph.submission_commands[0],),
        runs=(graph.runs[0],),
        result_links=(),
        control_command_links=(),
    )

    validate_workspace_graph(ordinary_only)


def test_external_sessions_cannot_own_tasks_or_submission_commands() -> None:
    from hqa.agent_workspace_model import (
        WorkspaceModelError,
        validate_workspace_graph,
    )

    graph = _valid_graph()
    external_task = replace(
        graph, tasks=(replace(graph.tasks[0], session_ref="session:external"),)
    )
    external_conversation = replace(
        graph,
        submission_commands=(
            replace(graph.submission_commands[0], session_ref="session:external"),
        )
        + graph.submission_commands[1:],
        runs=(replace(graph.runs[0], session_ref="session:external"),) + graph.runs[1:],
    )

    for invalid_graph in (external_task, external_conversation):
        with pytest.raises(WorkspaceModelError) as caught:
            validate_workspace_graph(invalid_graph)
        assert caught.value.code == "read_only_session"
        assert caught.value.field == "session_ref"


def test_conversation_action_and_control_command_identities_are_global() -> None:
    from hqa.agent_workspace_model import (
        WorkspaceModelError,
        validate_workspace_graph,
    )

    graph = _valid_graph()
    repeated_action = replace(
        graph.submission_commands[0],
        command_ref="command:conversation-copy",
        run_ref=None,
    )
    action_collision = replace(
        graph,
        submission_commands=graph.submission_commands + (repeated_action,),
    )
    cross_kind_action_collision = replace(
        graph,
        submission_commands=(
            graph.submission_commands[0],
            replace(
                graph.submission_commands[1],
                action_ref=graph.submission_commands[0].action_ref,
            ),
        )
        + graph.submission_commands[2:],
    )
    control_collision = replace(
        graph,
        control_command_links=(
            replace(
                graph.control_command_links[0],
                command_ref=graph.submission_commands[0].command_ref,
            ),
        )
        + graph.control_command_links[1:],
    )

    for invalid_graph, field in (
        (action_collision, "action_ref"),
        (cross_kind_action_collision, "action_ref"),
        (control_collision, "command_ref"),
    ):
        with pytest.raises(WorkspaceModelError) as caught:
            validate_workspace_graph(invalid_graph)
        assert caught.value.code == "duplicate_ref"
        assert caught.value.field == field


def test_attempt_and_research_command_binding_is_exact_and_one_to_one() -> None:
    from hqa.agent_workspace_model import (
        ResearchAttemptRecord,
        WorkspaceModelError,
        validate_workspace_graph,
    )

    graph = _valid_graph()
    second_command_for_attempt = replace(
        graph.submission_commands[1],
        command_ref="command:research-1-copy",
        action_ref="action:research-1-copy",
        run_ref=None,
    )
    one_attempt_two_commands = replace(
        graph,
        submission_commands=graph.submission_commands + (second_command_for_attempt,),
    )
    one_command_two_attempts = replace(
        graph,
        attempts=(
            graph.attempts[0],
            replace(
                graph.attempts[1],
                submission_command_ref="command:research-1",
            ),
        ),
    )
    wrong_number = replace(
        graph,
        submission_commands=(
            graph.submission_commands[:2]
            + (replace(graph.submission_commands[2], attempt_number=1),)
        ),
    )
    other_task = replace(graph.tasks[0], task_ref="task:other")
    other_attempt = ResearchAttemptRecord(
        attempt_ref="attempt:other-1",
        workspace_ref=WORKSPACE,
        owner_user_id=OWNER,
        task_ref="task:other",
        attempt_number=1,
        state="planned",
        durably_accepted=False,
    )
    wrong_task = replace(
        graph,
        tasks=graph.tasks + (other_task,),
        attempts=graph.attempts + (other_attempt,),
        submission_commands=(
            graph.submission_commands[:1]
            + (replace(graph.submission_commands[1], task_ref="task:other"),)
            + graph.submission_commands[2:]
        ),
    )
    wrong_session = replace(
        graph,
        tasks=(replace(graph.tasks[0], session_ref="session:managed"),),
    )

    for invalid_graph, code, field in (
        (one_attempt_two_commands, "cardinality", "attempt_ref"),
        (one_command_two_attempts, "cardinality", "submission_command_ref"),
        (wrong_number, "binding_mismatch", "attempt_number"),
        (wrong_task, "binding_mismatch", "task_ref"),
        (wrong_session, "binding_mismatch", "session_ref"),
    ):
        with pytest.raises(WorkspaceModelError) as caught:
            validate_workspace_graph(invalid_graph)
        assert caught.value.code == code
        assert caught.value.field == field


def test_not_yet_accepted_attempt_may_have_no_submission_command() -> None:
    from hqa.agent_workspace_model import validate_workspace_graph

    graph = _valid_graph()
    pending_attempt = replace(
        graph.attempts[1],
        state="planned",
        durably_accepted=False,
        submission_command_ref=None,
    )
    graph = replace(
        graph,
        attempts=(graph.attempts[0], pending_attempt),
        submission_commands=graph.submission_commands[:2],
        runs=graph.runs[:2],
    )

    validate_workspace_graph(graph)


def test_submission_command_and_run_binding_is_exact_zero_or_one() -> None:
    from hqa.agent_workspace_model import (
        WorkspaceModelError,
        validate_workspace_graph,
    )

    graph = _valid_graph()
    extra_run = replace(graph.runs[0], run_ref="run:conversation-copy")
    one_command_two_runs = replace(graph, runs=graph.runs + (extra_run,))
    extra_command = replace(
        graph.submission_commands[0],
        command_ref="command:conversation-copy",
        action_ref="action:turn-copy",
    )
    one_run_two_commands = replace(
        graph,
        submission_commands=graph.submission_commands + (extra_command,),
    )
    swapped_commands = (
        replace(graph.submission_commands[0], run_ref="run:research-1"),
        replace(graph.submission_commands[1], run_ref="run:conversation"),
    ) + graph.submission_commands[2:]
    nonreciprocal = replace(
        graph,
        submission_commands=(replace(graph.submission_commands[0], run_ref=None),)
        + graph.submission_commands[1:],
    )
    ordinary_with_attempt = replace(
        graph,
        runs=(replace(graph.runs[0], attempt_ref="attempt:research-1"),)
        + graph.runs[1:],
    )
    research_without_attempt = replace(
        graph,
        runs=(
            graph.runs[0],
            replace(graph.runs[1], attempt_ref=None),
            graph.runs[2],
        ),
    )
    research_with_wrong_attempt = replace(
        graph,
        runs=(
            graph.runs[0],
            replace(graph.runs[1], attempt_ref="attempt:research-2"),
            graph.runs[2],
        ),
    )

    for invalid_graph, code, field in (
        (one_command_two_runs, "cardinality", "submission_command_ref"),
        (one_run_two_commands, "cardinality", "run_ref"),
        (
            replace(graph, submission_commands=swapped_commands),
            "binding_mismatch",
            "run_ref",
        ),
        (nonreciprocal, "binding_mismatch", "run_ref"),
        (ordinary_with_attempt, "binding_mismatch", "attempt_ref"),
        (research_without_attempt, "binding_mismatch", "attempt_ref"),
        (research_with_wrong_attempt, "binding_mismatch", "attempt_ref"),
    ):
        with pytest.raises(WorkspaceModelError) as caught:
            validate_workspace_graph(invalid_graph)
        assert caught.value.code == code
        assert caught.value.field == field


def test_attempt_acceptance_and_submission_command_shapes_are_closed() -> None:
    from hqa.agent_workspace_model import (
        ResearchAttemptRecord,
        SubmissionCommandRecord,
        WorkspaceModelError,
    )

    with pytest.raises(WorkspaceModelError, match="cardinality:submission_command_ref"):
        ResearchAttemptRecord(
            attempt_ref="attempt:accepted",
            workspace_ref=WORKSPACE,
            owner_user_id=OWNER,
            task_ref="task:research",
            attempt_number=1,
            state="running",
            durably_accepted=True,
        )

    common = {
        "command_ref": "command:shape",
        "workspace_ref": WORKSPACE,
        "owner_user_id": OWNER,
        "session_ref": "session:managed",
        "action_ref": "action:shape",
        "state": "prepared",
    }
    conversation_extras = (
        {"task_ref": "task:research"},
        {"attempt_ref": "attempt:research-1"},
        {"attempt_number": 1},
    )
    research_fields = {
        "task_ref": "task:research",
        "attempt_ref": "attempt:research-1",
        "attempt_number": 1,
    }
    for extras in conversation_extras:
        with pytest.raises(WorkspaceModelError):
            SubmissionCommandRecord(**common, kind="conversation_turn", **extras)
    for missing_field in research_fields:
        values = dict(research_fields)
        values[missing_field] = None
        with pytest.raises(WorkspaceModelError):
            SubmissionCommandRecord(**common, kind="research_attempt", **values)

from __future__ import annotations

import importlib.util
import inspect
import typing
from dataclasses import FrozenInstanceError, fields, is_dataclass

import pytest


def test_agent_workspace_contract_module_exists() -> None:
    assert importlib.util.find_spec("hqa.agent_workspace_contract") is not None


def test_agent_workspace_protocol_exposes_only_the_three_public_operations() -> None:
    from hqa.agent_workspace_contract import AgentWorkspace, UserActionV1

    operations = {
        name
        for name, value in AgentWorkspace.__dict__.items()
        if not name.startswith("_") and callable(value)
    }

    assert AgentWorkspace._is_protocol is True
    assert UserActionV1._is_protocol is True
    assert operations == {"act", "snapshot", "follow"}
    assert list(inspect.signature(AgentWorkspace.act).parameters) == [
        "self",
        "actor",
        "action",
    ]
    assert list(inspect.signature(AgentWorkspace.snapshot).parameters) == [
        "self",
        "actor",
        "workspace",
    ]
    follow = inspect.signature(AgentWorkspace.follow)
    assert list(follow.parameters) == ["self", "actor", "workspace", "after"]
    assert follow.parameters["after"].default is None
    assert typing.get_type_hints(AgentWorkspace.act)["return"].__name__ == (
        "ActionReceipt"
    )
    assert typing.get_type_hints(AgentWorkspace.snapshot)["return"].__name__ == (
        "WorkspaceSnapshot"
    )
    assert typing.get_type_hints(AgentWorkspace.follow)["return"].__name__ == (
        "EventPage"
    )


def test_core_references_are_frozen_strict_and_bounded() -> None:
    from hqa.agent_workspace_contract import ActorRef, WorkspaceCursor, WorkspaceRef

    actor = ActorRef(owner_user_id="user-1")
    workspace = WorkspaceRef(workspace_id="workspace:1")
    cursor = WorkspaceCursor(value=0)

    assert all(is_dataclass(value) for value in (actor, workspace, cursor))
    assert [field.name for field in fields(actor)] == ["owner_user_id"]
    assert [field.name for field in fields(workspace)] == ["workspace_id"]
    assert [field.name for field in fields(cursor)] == ["value"]
    with pytest.raises(FrozenInstanceError):
        actor.owner_user_id = "other"  # type: ignore[misc]

    for invalid in (None, "", " ", "bad/value", "x" * 201, 1, True):
        with pytest.raises((TypeError, ValueError)):
            ActorRef(owner_user_id=invalid)  # type: ignore[arg-type]
        with pytest.raises((TypeError, ValueError)):
            WorkspaceRef(workspace_id=invalid)  # type: ignore[arg-type]

    for invalid_cursor in (-1, True, 1.5, "1", 2**63):
        with pytest.raises((TypeError, ValueError)):
            WorkspaceCursor(value=invalid_cursor)  # type: ignore[arg-type]


def test_action_receipt_is_frozen_and_contains_only_safe_reference_fields() -> None:
    from hqa.agent_workspace_contract import ActionReceipt, WorkspaceRef

    receipt = ActionReceipt(
        status="accepted",
        client_action_id="action-1",
        action_digest="a" * 64,
        workspace=WorkspaceRef(workspace_id="workspace-1"),
    )

    assert is_dataclass(receipt)
    assert [field.name for field in fields(receipt)] == [
        "status",
        "client_action_id",
        "action_digest",
        "workspace",
        "command_id",
        "run_id",
        "recovery_action",
    ]
    assert receipt.command_id is None
    assert receipt.run_id is None
    assert receipt.recovery_action is None
    assert not {"prompt", "body", "message"}.intersection(
        field.name for field in fields(receipt)
    )
    with pytest.raises(FrozenInstanceError):
        receipt.status = "conflict"  # type: ignore[misc]


def test_action_receipt_validates_status_digest_references_and_recovery() -> None:
    from hqa.agent_workspace_contract import ActionReceipt, WorkspaceRef

    workspace = WorkspaceRef(workspace_id="workspace-1")
    for status in (
        "accepted",
        "reconciling",
        "conflict",
        "unavailable",
        "outcome_unknown",
    ):
        receipt = ActionReceipt(
            status=status,
            client_action_id="action-1",
            action_digest="f" * 64,
            workspace=workspace,
            command_id="command-1",
            run_id="run-1",
            recovery_action=None if status == "accepted" else "follow_workspace",
        )
        assert receipt.status == status

    for status in ("reconciling", "conflict", "unavailable", "outcome_unknown"):
        with pytest.raises((TypeError, ValueError)):
            ActionReceipt(
                status=status,
                client_action_id="action-1",
                action_digest="f" * 64,
                workspace=workspace,
            )

    invalid_cases = (
        {"status": "queued"},
        {"client_action_id": "bad/action"},
        {"action_digest": "A" * 64},
        {"action_digest": "f" * 63},
        {"workspace": "workspace-1"},
        {"command_id": "bad/command"},
        {"run_id": ""},
        {"recovery_action": "bad action"},
    )
    base = {
        "status": "accepted",
        "client_action_id": "action-1",
        "action_digest": "f" * 64,
        "workspace": workspace,
    }
    for override in invalid_cases:
        with pytest.raises((TypeError, ValueError)):
            ActionReceipt(**dict(base, **override))


def test_workspace_event_is_frozen_and_defensively_freezes_metadata() -> None:
    from hqa.agent_workspace_contract import WorkspaceCursor, WorkspaceEvent

    metadata = {"nested": {"values": [1, 2.5, True, None]}}
    event = WorkspaceEvent(
        workspace_cursor=WorkspaceCursor(value=1),
        source_authority="hermes",
        source_event_id="event-1",
        source_cursor="run/1:cursor/2",
        observed_at="2026-07-16T12:34:56.123456+08:00",
        event_type="run.updated",
        metadata=metadata,
    )
    metadata["nested"]["values"].append(3)  # type: ignore[union-attr]
    metadata["added"] = "later"

    assert is_dataclass(event)
    assert [field.name for field in fields(event)] == [
        "workspace_cursor",
        "source_authority",
        "source_event_id",
        "source_cursor",
        "observed_at",
        "event_type",
        "metadata",
    ]
    assert event.metadata == {
        "nested": {"values": (1, 2.5, True, None)},
    }
    with pytest.raises(TypeError):
        event.metadata["added"] = "forbidden"  # type: ignore[index]
    with pytest.raises(TypeError):
        event.metadata["nested"]["added"] = "forbidden"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        event.event_type = "other"  # type: ignore[misc]


def test_workspace_event_validates_provenance_identifiers_and_timestamp() -> None:
    from hqa.agent_workspace_contract import WorkspaceCursor, WorkspaceEvent

    base = {
        "workspace_cursor": WorkspaceCursor(value=1),
        "source_authority": "postgresql",
        "source_event_id": "event-1",
        "source_cursor": "source/cursor/1",
        "observed_at": "2026-07-16T04:34:56Z",
        "event_type": "command.accepted",
        "metadata": {},
    }
    for authority in ("postgresql", "hqa", "hermes", "platform_domain"):
        assert WorkspaceEvent(**dict(base, source_authority=authority)).source_authority == (
            authority
        )

    invalid_cases = (
        {"workspace_cursor": 1},
        {"source_authority": "platform"},
        {"source_event_id": "bad/event"},
        {"source_cursor": ""},
        {"event_type": "bad/event"},
        {"observed_at": "2026-07-16T04:34:56"},
        {"observed_at": "2026-07-16 04:34:56Z"},
        {"observed_at": "2026-07-16T04:34:56+0000"},
        {"observed_at": "2026-02-30T04:34:56Z"},
    )
    for override in invalid_cases:
        with pytest.raises((TypeError, ValueError)):
            WorkspaceEvent(**dict(base, **override))


def test_workspace_event_metadata_accepts_only_strict_finite_json() -> None:
    from hqa.agent_workspace_contract import WorkspaceCursor, WorkspaceEvent

    base = {
        "workspace_cursor": WorkspaceCursor(value=1),
        "source_authority": "hqa",
        "source_event_id": "event-1",
        "source_cursor": "1",
        "observed_at": "2026-07-16T04:34:56+00:00",
        "event_type": "attempt.updated",
    }
    cyclic = []
    cyclic.append(cyclic)
    invalid_metadata = (
        None,
        {1: "non-string-key"},
        {"value": float("nan")},
        {"value": float("inf")},
        {"value": b"bytes"},
        {"value": {"set"}},
        {"value": ("tuple",)},
        {"value": cyclic},
    )
    for metadata in invalid_metadata:
        with pytest.raises(ValueError):
            WorkspaceEvent(**base, metadata=metadata)  # type: ignore[arg-type]


def test_workspace_event_metadata_rejects_sensitive_keys_at_any_depth() -> None:
    from hqa.agent_workspace_contract import WorkspaceCursor, WorkspaceEvent

    base = {
        "workspace_cursor": WorkspaceCursor(value=1),
        "source_authority": "platform_domain",
        "source_event_id": "event-1",
        "source_cursor": "1",
        "observed_at": "2026-07-16T04:34:56Z",
        "event_type": "result.linked",
    }
    for key in ("prompt", "MESSAGE", "Body", "secret", "ToKeN", "Authorization"):
        with pytest.raises(ValueError):
            WorkspaceEvent(**base, metadata={"nested": [{key: "not-safe"}]})


def test_workspace_event_metadata_is_bounded_by_depth_and_serialized_size() -> None:
    from hqa.agent_workspace_contract import WorkspaceCursor, WorkspaceEvent

    base = {
        "workspace_cursor": WorkspaceCursor(value=1),
        "source_authority": "postgresql",
        "source_event_id": "event-1",
        "source_cursor": "1",
        "observed_at": "2026-07-16T04:34:56Z",
        "event_type": "command.accepted",
    }
    too_deep = []
    for _ in range(100):
        too_deep = [too_deep]

    with pytest.raises(ValueError):
        WorkspaceEvent(**base, metadata={"value": too_deep})
    with pytest.raises(ValueError):
        WorkspaceEvent(**base, metadata={"value": "x" * 70_000})


def test_workspace_snapshot_is_frozen_and_defensively_copies_authority_health() -> None:
    from hqa.agent_workspace_contract import (
        WorkspaceCursor,
        WorkspaceRef,
        WorkspaceSnapshot,
    )

    authority_health = {
        "postgresql": "available",
        "hqa": "degraded",
        "hermes": "unavailable",
        "platform_domain": "available",
    }
    snapshot = WorkspaceSnapshot(
        workspace=WorkspaceRef(workspace_id="workspace-1"),
        owner_user_id="user-1",
        snapshot_workspace_cursor=WorkspaceCursor(value=12),
        sessions=("session-1",),
        tasks=("task-1",),
        attempts=("attempt-1", "attempt-2"),
        commands=("command-1",),
        runs=("run-1",),
        results=("result-1",),
        authority_health=authority_health,
    )
    authority_health["hermes"] = "available"

    assert is_dataclass(snapshot)
    assert [field.name for field in fields(snapshot)] == [
        "workspace",
        "owner_user_id",
        "snapshot_workspace_cursor",
        "sessions",
        "tasks",
        "attempts",
        "commands",
        "runs",
        "results",
        "authority_health",
    ]
    assert snapshot.attempts == ("attempt-1", "attempt-2")
    assert snapshot.authority_health["hermes"] == "unavailable"
    with pytest.raises(TypeError):
        snapshot.authority_health["hermes"] = "available"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        snapshot.owner_user_id = "other"  # type: ignore[misc]


def test_workspace_snapshot_validates_refs_and_authority_keys() -> None:
    from hqa.agent_workspace_contract import (
        WorkspaceCursor,
        WorkspaceRef,
        WorkspaceSnapshot,
    )

    base = {
        "workspace": WorkspaceRef(workspace_id="workspace-1"),
        "owner_user_id": "user-1",
        "snapshot_workspace_cursor": WorkspaceCursor(value=1),
        "sessions": ("session-1",),
        "tasks": ("task-1",),
        "attempts": ("attempt-1",),
        "commands": ("command-1",),
        "runs": ("run-1",),
        "results": ("result-1",),
        "authority_health": {"postgresql": "available"},
    }
    assert WorkspaceSnapshot(**base).sessions == ("session-1",)

    invalid_cases = (
        {"workspace": "workspace-1"},
        {"owner_user_id": "bad/user"},
        {"snapshot_workspace_cursor": 1},
        {"sessions": ["session-1"]},
        {"tasks": ("bad/task",)},
        {"authority_health": {"platform": "available"}},
        {"authority_health": {"hermes": ""}},
        {"authority_health": [("hermes", "available")]},
    )
    for override in invalid_cases:
        with pytest.raises((TypeError, ValueError)):
            WorkspaceSnapshot(**dict(base, **override))


def test_event_page_is_frozen_and_requires_strictly_increasing_cursors() -> None:
    from hqa.agent_workspace_contract import EventPage, WorkspaceCursor, WorkspaceEvent

    def event(cursor: int) -> WorkspaceEvent:
        return WorkspaceEvent(
            workspace_cursor=WorkspaceCursor(value=cursor),
            source_authority="postgresql",
            source_event_id=f"event-{cursor}",
            source_cursor=str(cursor),
            observed_at="2026-07-16T04:34:56Z",
            event_type="command.updated",
            metadata={},
        )

    page = EventPage(
        events=(event(1), event(3)),
        next_cursor=WorkspaceCursor(value=3),
        resync_required=False,
        recovery_action=None,
    )

    assert is_dataclass(page)
    assert [field.name for field in fields(page)] == [
        "events",
        "next_cursor",
        "resync_required",
        "recovery_action",
    ]
    assert tuple(item.workspace_cursor.value for item in page.events) == (1, 3)
    with pytest.raises(FrozenInstanceError):
        page.next_cursor = WorkspaceCursor(value=4)  # type: ignore[misc]

    for events in ((event(1), event(1)), (event(2), event(1))):
        with pytest.raises((TypeError, ValueError)):
            EventPage(events=events)
    with pytest.raises((TypeError, ValueError)):
        EventPage(events=[event(1)])  # type: ignore[arg-type]
    with pytest.raises((TypeError, ValueError)):
        EventPage(events=("event-1",))  # type: ignore[arg-type]


def test_event_page_enforces_exact_resync_recovery_semantics() -> None:
    from hqa.agent_workspace_contract import EventPage, WorkspaceCursor

    resync = EventPage(
        events=(),
        next_cursor=None,
        resync_required=True,
        recovery_action="resnapshot_workspace",
    )
    ordinary = EventPage(
        events=(),
        next_cursor=WorkspaceCursor(value=0),
        resync_required=False,
        recovery_action="retry_follow",
    )
    assert resync.recovery_action == "resnapshot_workspace"
    assert ordinary.recovery_action == "retry_follow"

    invalid_cases = (
        {"resync_required": True, "recovery_action": None},
        {"resync_required": True, "recovery_action": "retry_follow"},
        {"resync_required": False, "recovery_action": "resnapshot_workspace"},
        {"resync_required": 1, "recovery_action": None},
        {"next_cursor": 1},
        {"recovery_action": ""},
    )
    for override in invalid_cases:
        with pytest.raises((TypeError, ValueError)):
            EventPage(events=(), **override)


def test_workspace_contract_error_has_closed_codes_and_total_recovery_defaults() -> None:
    from hqa.agent_workspace_contract import (
        WorkspaceContractError,
        default_recovery_action,
    )

    expected_defaults = {
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
    for code, recovery_action in expected_defaults.items():
        assert default_recovery_action(code) == recovery_action
        error = WorkspaceContractError(code=code, message="Safe contract failure")
        assert isinstance(error, Exception)
        assert error.code == code
        assert error.message == "Safe contract failure"
        assert error.recovery_action == recovery_action
        assert str(error) == "Safe contract failure"


def test_workspace_contract_error_rejects_unknown_or_unsafe_values() -> None:
    from hqa.agent_workspace_contract import (
        WorkspaceContractError,
        default_recovery_action,
    )

    for code in ("", "unknown", None):
        with pytest.raises((TypeError, ValueError)):
            default_recovery_action(code)  # type: ignore[arg-type]
        with pytest.raises((TypeError, ValueError)):
            WorkspaceContractError(code=code, message="Safe failure")  # type: ignore[arg-type]
        with pytest.raises((TypeError, ValueError)):
            WorkspaceContractError(
                code=code,  # type: ignore[arg-type]
                message="Safe failure",
                recovery_action="stop_and_audit",
            )

    for message in ("", " ", "line one\nline two", "token=leaked", "x" * 501):
        with pytest.raises((TypeError, ValueError)):
            WorkspaceContractError(code="validation", message=message)

    for recovery_action in ("", "bad recovery", "bad/recovery"):
        with pytest.raises((TypeError, ValueError)):
            WorkspaceContractError(
                code="validation",
                message="Safe failure",
                recovery_action=recovery_action,
            )

    custom = WorkspaceContractError(
        code="unavailable",
        message="Authority temporarily unavailable",
        recovery_action="reconcile_exact_receipt",
    )
    assert custom.recovery_action == "reconcile_exact_receipt"

from __future__ import annotations

import pytest


STATE_EDGES = {
    "task": {
        "draft": ("plan_proposed", "terminal"),
        "plan_proposed": ("awaiting_plan_confirmation", "terminal"),
        "awaiting_plan_confirmation": (
            "plan_proposed",
            "awaiting_formula_confirmation",
            "ready",
            "terminal",
        ),
        "awaiting_formula_confirmation": (
            "plan_proposed",
            "ready",
            "terminal",
        ),
        "ready": ("plan_proposed", "running", "terminal"),
        "running": ("plan_proposed", "awaiting_domain_gate", "terminal"),
        "awaiting_domain_gate": ("running", "terminal"),
        "terminal": (),
    },
    "attempt": {
        "planned": ("running", "reconciling", "stop_requested", "terminal"),
        "running": ("reconciling", "stop_requested", "terminal"),
        "reconciling": ("running", "stop_requested", "terminal"),
        "stop_requested": ("reconciling", "terminal"),
        "terminal": (),
    },
    "submission_command": {
        "queued": ("leased", "cancelled"),
        "leased": ("queued", "delivered", "outcome_unknown", "failed"),
        "delivered": ("succeeded", "failed"),
        "outcome_unknown": ("delivered", "succeeded", "failed"),
        "succeeded": (),
        "failed": (),
        "cancelled": (),
    },
    "hermes_run": {
        "queued": ("running", "stopping", "failed", "cancelled"),
        "running": (
            "waiting_for_approval",
            "stopping",
            "completed",
            "failed",
            "cancelled",
        ),
        "waiting_for_approval": ("running", "stopping", "failed", "cancelled"),
        "stopping": ("completed", "failed", "cancelled"),
        "completed": (),
        "failed": (),
        "cancelled": (),
    },
    "command_approval": {
        "pending": ("allowed_once", "denied", "expired"),
        "allowed_once": (),
        "denied": (),
        "expired": (),
    },
    "stop_target": {
        "requested": ("confirmed", "already_terminal", "unknown"),
        "unknown": ("confirmed", "already_terminal"),
        "confirmed": (),
        "already_terminal": (),
    },
    "stop_overall": {
        "requested": ("reconciling", "stopped", "already_terminal"),
        "reconciling": ("stopped", "already_terminal"),
        "stopped": (),
        "already_terminal": (),
    },
}


def _all_transition_cases():
    for kind, transitions in STATE_EDGES.items():
        states = tuple(transitions)
        for before in states:
            for after in states:
                yield kind, before, after, after in transitions[before]


@pytest.mark.parametrize(
    ("kind", "before", "after", "allowed"),
    tuple(_all_transition_cases()),
)
def test_transition_matrix_is_closed(
    kind: str, before: str, after: str, allowed: bool
) -> None:
    from hqa.agent_workspace_states import WorkspaceStateError, validate_transition

    if allowed:
        assert validate_transition(kind, before, after) is None
        return

    expected_code = "same_state" if before == after else "invalid_transition"
    with pytest.raises(WorkspaceStateError) as caught:
        validate_transition(kind, before, after)
    assert caught.value.code == expected_code
    assert caught.value.field == "after"


@pytest.mark.parametrize("kind", tuple(STATE_EDGES))
def test_entity_state_validator_accepts_only_the_closed_state_set(kind: str) -> None:
    from hqa.agent_workspace_states import (
        WorkspaceStateError,
        validate_entity_state,
    )

    for state in STATE_EDGES[kind]:
        assert validate_entity_state(kind, state) is None

    with pytest.raises(WorkspaceStateError) as caught:
        validate_entity_state(kind, "not-a-real-state")
    assert caught.value.code == "unknown_state"
    assert caught.value.field == "state"


@pytest.mark.parametrize("field", ("before", "after"))
def test_transition_rejects_unknown_states_without_echoing_values(field: str) -> None:
    from hqa.agent_workspace_states import WorkspaceStateError, validate_transition

    unknown = "secret-state-that-must-not-be-echoed"
    values = {"before": "draft", "after": "plan_proposed", field: unknown}
    with pytest.raises(WorkspaceStateError) as caught:
        validate_transition("task", values["before"], values["after"])
    assert caught.value.code == "unknown_state"
    assert caught.value.field == field
    assert unknown not in str(caught.value)
    assert caught.value.args == ("unknown_state:{}".format(field),)


def test_transition_rejects_unknown_entity_kind_without_echoing_it() -> None:
    from hqa.agent_workspace_states import WorkspaceStateError, validate_transition

    unknown = "secret-kind-that-must-not-be-echoed"
    with pytest.raises(WorkspaceStateError) as caught:
        validate_transition(unknown, "draft", "plan_proposed")
    assert caught.value.code == "unknown_kind"
    assert caught.value.field == "kind"
    assert unknown not in str(caught.value)


class _StringSubclass(str):
    pass


class _EqualitySpoof:
    def __eq__(self, other: object) -> bool:
        return True

    def __hash__(self) -> int:
        return 1


@pytest.mark.parametrize(
    ("kind", "before", "after", "field"),
    (
        (_StringSubclass("task"), "draft", "plan_proposed", "kind"),
        ("task", _StringSubclass("draft"), "plan_proposed", "before"),
        ("task", "draft", _StringSubclass("plan_proposed"), "after"),
        (_EqualitySpoof(), "draft", "plan_proposed", "kind"),
        ("task", _EqualitySpoof(), "plan_proposed", "before"),
        ("task", "draft", _EqualitySpoof(), "after"),
    ),
)
def test_transition_boundary_rejects_string_subclasses_and_equality_spoofs(
    kind: object, before: object, after: object, field: str
) -> None:
    from hqa.agent_workspace_states import WorkspaceStateError, validate_transition

    with pytest.raises(WorkspaceStateError) as caught:
        validate_transition(kind, before, after)  # type: ignore[arg-type]
    assert caught.value.code == "invalid_type"
    assert caught.value.field == field


def test_transition_validation_is_pure_and_leaves_inputs_unchanged() -> None:
    from hqa.agent_workspace_states import validate_transition

    inputs = ["task", "draft", "plan_proposed"]
    before = tuple(inputs)

    validate_transition(*inputs)

    assert tuple(inputs) == before


def test_result_link_append_allows_first_bind_and_exact_idempotent_replay() -> None:
    from hqa.agent_workspace_states import validate_result_link_append

    assert validate_result_link_append(None, "result:alpha") == "result:alpha"
    assert (
        validate_result_link_append("result:alpha", "result:alpha")
        == "result:alpha"
    )


def test_result_link_append_rejects_rebinding_without_echoing_identifiers() -> None:
    from hqa.agent_workspace_states import (
        WorkspaceStateError,
        validate_result_link_append,
    )

    existing = "result:must-not-leak-existing"
    proposed = "result:must-not-leak-proposed"
    with pytest.raises(WorkspaceStateError) as caught:
        validate_result_link_append(existing, proposed)
    assert caught.value.code == "result_link_rebind"
    assert caught.value.field == "result_ref"
    assert existing not in str(caught.value)
    assert proposed not in str(caught.value)


@pytest.mark.parametrize(
    ("existing", "proposed", "field"),
    (
        (None, "not-a-result-ref", "proposed_ref"),
        (None, _StringSubclass("result:alpha"), "proposed_ref"),
        (_StringSubclass("result:alpha"), "result:alpha", "existing_ref"),
        (1, "result:alpha", "existing_ref"),
    ),
)
def test_result_link_append_rejects_invalid_or_spoofed_identifiers(
    existing: object, proposed: object, field: str
) -> None:
    from hqa.agent_workspace_states import (
        WorkspaceStateError,
        validate_result_link_append,
    )

    with pytest.raises(WorkspaceStateError) as caught:
        validate_result_link_append(existing, proposed)  # type: ignore[arg-type]
    assert caught.value.field == field

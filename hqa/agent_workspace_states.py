from __future__ import annotations

import re
from typing import Any, Optional


_RESULT_REF_RE = re.compile(r"result:[A-Za-z0-9][A-Za-z0-9._:-]{0,192}\Z")

_TRANSITIONS = {
    "task": {
        "draft": frozenset(("plan_proposed", "terminal")),
        "plan_proposed": frozenset(("awaiting_plan_confirmation", "terminal")),
        "awaiting_plan_confirmation": frozenset(
            (
                "plan_proposed",
                "awaiting_formula_confirmation",
                "ready",
                "terminal",
            )
        ),
        "awaiting_formula_confirmation": frozenset(
            ("plan_proposed", "ready", "terminal")
        ),
        "ready": frozenset(("plan_proposed", "running", "terminal")),
        "running": frozenset(
            ("plan_proposed", "awaiting_domain_gate", "terminal")
        ),
        "awaiting_domain_gate": frozenset(("running", "terminal")),
        "terminal": frozenset(),
    },
    "attempt": {
        "planned": frozenset(
            ("running", "reconciling", "stop_requested", "terminal")
        ),
        "running": frozenset(("reconciling", "stop_requested", "terminal")),
        "reconciling": frozenset(("running", "stop_requested", "terminal")),
        "stop_requested": frozenset(("reconciling", "terminal")),
        "terminal": frozenset(),
    },
    "submission_command": {
        "queued": frozenset(("leased", "cancelled")),
        "leased": frozenset(
            ("queued", "delivered", "outcome_unknown", "failed")
        ),
        "delivered": frozenset(("succeeded", "failed")),
        "outcome_unknown": frozenset(("delivered", "succeeded", "failed")),
        "succeeded": frozenset(),
        "failed": frozenset(),
        "cancelled": frozenset(),
    },
    "hermes_run": {
        "queued": frozenset(("running", "stopping", "failed", "cancelled")),
        "running": frozenset(
            (
                "waiting_for_approval",
                "stopping",
                "completed",
                "failed",
                "cancelled",
            )
        ),
        "waiting_for_approval": frozenset(
            ("running", "stopping", "failed", "cancelled")
        ),
        "stopping": frozenset(("completed", "failed", "cancelled")),
        "completed": frozenset(),
        "failed": frozenset(),
        "cancelled": frozenset(),
    },
    "command_approval": {
        "pending": frozenset(("allowed_once", "denied", "expired")),
        "allowed_once": frozenset(),
        "denied": frozenset(),
        "expired": frozenset(),
    },
    "stop_target": {
        "requested": frozenset(
            ("confirmed", "already_terminal", "not_applicable", "unknown")
        ),
        "unknown": frozenset(
            ("confirmed", "already_terminal", "not_applicable")
        ),
        "confirmed": frozenset(),
        "already_terminal": frozenset(),
        "not_applicable": frozenset(),
    },
    "stop_overall": {
        "requested": frozenset(("reconciling", "stopped", "already_terminal")),
        "reconciling": frozenset(("stopped", "already_terminal")),
        "stopped": frozenset(),
        "already_terminal": frozenset(),
    },
}


class WorkspaceStateError(ValueError):
    """A value-free state-contract error safe to expose at a boundary."""

    def __init__(self, code: str, field: str) -> None:
        self.code = code
        self.field = field
        super().__init__("{}:{}".format(code, field))


def _fail(code: str, field: str) -> None:
    raise WorkspaceStateError(code, field)


def _transitions_for(kind: Any) -> dict[str, frozenset[str]]:
    if type(kind) is not str:
        _fail("invalid_type", "kind")
    transitions = _TRANSITIONS.get(kind)
    if transitions is None:
        _fail("unknown_kind", "kind")
    return transitions


def _validate_state(
    transitions: dict[str, frozenset[str]], state: Any, field: str
) -> None:
    if type(state) is not str:
        _fail("invalid_type", field)
    if state not in transitions:
        _fail("unknown_state", field)


def validate_entity_state(kind: str, state: str) -> None:
    """Validate one exact state against its closed entity state set."""

    transitions = _transitions_for(kind)
    _validate_state(transitions, state, "state")


def validate_transition(kind: str, before: str, after: str) -> None:
    """Validate an exact state-machine edge without mutation or I/O."""

    transitions = _transitions_for(kind)
    _validate_state(transitions, before, "before")
    _validate_state(transitions, after, "after")
    if before == after:
        _fail("same_state", "after")
    if after not in transitions[before]:
        _fail("invalid_transition", "after")


def _validate_result_ref(value: Any, field: str) -> None:
    if type(value) is not str or _RESULT_REF_RE.fullmatch(value) is None:
        _fail("invalid_result_ref", field)


def validate_result_link_append(
    existing_ref: Optional[str], proposed_ref: str
) -> str:
    """Accept an initial result link or an exact idempotent replay."""

    if existing_ref is not None:
        _validate_result_ref(existing_ref, "existing_ref")
    _validate_result_ref(proposed_ref, "proposed_ref")
    if existing_ref is not None and existing_ref != proposed_ref:
        _fail("result_link_rebind", "result_ref")
    return proposed_ref


__all__ = (
    "WorkspaceStateError",
    "validate_entity_state",
    "validate_result_link_append",
    "validate_transition",
)

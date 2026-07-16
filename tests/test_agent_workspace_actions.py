from __future__ import annotations

from collections.abc import Mapping
from dataclasses import FrozenInstanceError, dataclass, fields, is_dataclass, replace
import hashlib
import json

import pytest


class _EqualitySpoof:
    def __eq__(self, other: object) -> bool:
        return True

    def __ne__(self, other: object) -> bool:
        return False


class _SpoofStringKey:
    def __init__(self, target: str) -> None:
        self.target = target

    def __hash__(self) -> int:
        return hash(self.target)

    def __eq__(self, other: object) -> bool:
        return True


class _StringSubclass(str):
    pass


class _DictSubclass(dict):
    pass


class _CustomMapping(Mapping):
    def __init__(self, document: dict[object, object]) -> None:
        self._document = document

    def __getitem__(self, key: object) -> object:
        return self._document[key]

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self._document)

    def __len__(self) -> int:
        return len(self._document)


def _valid_action_documents() -> list[dict[str, object]]:
    payload_digest = "c" * 64
    common = {
        "schema_version": 1,
        "client_action_id": "action:test-1",
        "workspace": {"workspace_id": "workspace:alpha"},
    }
    return [
        dict(
            common,
            kind="managed_session.create",
            provider_policy_digest="a" * 64,
            payload_ttl_days=7,
        ),
        dict(
            common,
            kind="managed_session.fork",
            source_session_ref="session:source.1",
            source_channel="historical",
            fork_point="message/1",
            new_provider_policy_digest="b" * 64,
            payload_ttl_days=30,
        ),
        dict(
            common,
            kind="conversation.turn",
            managed_session_ref="session:managed.1",
            payload_ref="payload:sha256:" + payload_digest,
            payload_digest=payload_digest,
        ),
        dict(
            common,
            kind="research.start",
            managed_session_ref="session:managed.1",
            payload_ref="payload:sha256:" + payload_digest,
            payload_digest=payload_digest,
            initial_mode="plan_only",
        ),
        dict(
            common,
            kind="research.continue",
            managed_session_ref="session:managed.1",
            task_ref="task:research.1",
            payload_ref="payload:sha256:" + payload_digest,
            payload_digest=payload_digest,
        ),
        dict(
            common,
            kind="research.plan.confirm",
            task_ref="task:research.1",
            plan_version=1,
            plan_digest="d" * 64,
        ),
        dict(
            common,
            kind="run.stop.request",
            run_ref="run:hermes.1",
            task_ref=None,
            attempt_ref=None,
            platform_job_ref=None,
        ),
        dict(
            common,
            kind="hermes.command_approval.decide",
            approval_ref="approval:challenge.1",
            run_ref="run:hermes.1",
            command_digest="e" * 64,
            expected_status="pending",
            expected_expires_at="2026-07-16T12:30:40.000000Z",
            decision="deny",
        ),
        dict(
            common,
            kind="gate1.formula_source.confirm",
            task_ref="task:research.1",
            reviewed_source_sha256="f" * 64,
            confirmation_note="Reviewed exact source.",
        ),
        dict(
            common,
            kind="gate2.candidate.review",
            candidate_ref="candidate:factor.1",
            expected_digest="1" * 64,
            expected_status="pending",
            note="Review exact candidate.",
        ),
        dict(
            common,
            kind="gate3.promotion_review.prepare",
            candidate_ref="candidate:factor.1",
            expected_digest="2" * 64,
            final_backtest_receipt_ref="receipt:backtest.1",
            base_commit="3" * 40,
        ),
    ]


def test_create_managed_session_is_frozen_and_round_trips_to_its_route() -> None:
    from hqa.agent_workspace_actions import (
        CreateManagedSession,
        action_to_document,
        parse_user_action_v1,
        route_for_action,
    )
    from hqa.agent_workspace_contract import WorkspaceRef

    action = CreateManagedSession(
        client_action_id="action:create-1",
        workspace=WorkspaceRef(workspace_id="workspace:alpha"),
        provider_policy_digest="a" * 64,
        payload_ttl_days=7,
    )

    assert is_dataclass(action)
    assert [field.name for field in fields(action)] == [
        "client_action_id",
        "workspace",
        "provider_policy_digest",
        "payload_ttl_days",
    ]
    document = {
        "schema_version": 1,
        "kind": "managed_session.create",
        "client_action_id": "action:create-1",
        "workspace": {"workspace_id": "workspace:alpha"},
        "provider_policy_digest": "a" * 64,
        "payload_ttl_days": 7,
    }
    assert action_to_document(action) == document
    assert parse_user_action_v1(document) == action
    assert route_for_action(action) == "/api/hermes/managed-sessions"
    with pytest.raises(FrozenInstanceError):
        action.payload_ttl_days = 8  # type: ignore[misc]


def test_fork_into_managed_session_round_trips_lineage_and_quotes_route() -> None:
    from hqa.agent_workspace_actions import (
        ForkIntoManagedSession,
        action_to_document,
        parse_user_action_v1,
        route_for_action,
    )
    from hqa.agent_workspace_contract import WorkspaceRef

    action = ForkIntoManagedSession(
        client_action_id="action:fork-1",
        workspace=WorkspaceRef(workspace_id="workspace:alpha"),
        source_session_ref="session:discord.123",
        source_channel="discord",
        fork_point="message/42:after",
        new_provider_policy_digest="b" * 64,
        payload_ttl_days=14,
    )
    document = {
        "schema_version": 1,
        "kind": "managed_session.fork",
        "client_action_id": "action:fork-1",
        "workspace": {"workspace_id": "workspace:alpha"},
        "source_session_ref": "session:discord.123",
        "source_channel": "discord",
        "fork_point": "message/42:after",
        "new_provider_policy_digest": "b" * 64,
        "payload_ttl_days": 14,
    }

    assert action_to_document(action) == document
    assert parse_user_action_v1(document) == action
    assert route_for_action(action) == (
        "/api/hermes/sessions/session%3Adiscord.123/forks-to-managed"
    )


def test_fork_into_managed_session_accepts_exact_web_managed_channel() -> None:
    from hqa.agent_workspace_actions import (
        action_to_document,
        canonical_action_digest,
        parse_user_action_v1,
        route_for_action,
    )

    document = dict(
        _valid_action_documents()[1],
        source_session_ref="session:managed.123",
        source_channel="web_managed",
    )

    action = parse_user_action_v1(document)

    assert action.source_channel == "web_managed"
    assert action_to_document(action) == document
    assert canonical_action_digest(action) == (
        "0f69989f0aaf9cacda8f162e3302bea66e25d9d1be69432d49514380a8bae2d6"
    )
    assert route_for_action(action) == (
        "/api/hermes/sessions/session%3Amanaged.123/forks-to-managed"
    )


def test_conversation_turn_round_trips_payload_reference_without_plaintext() -> None:
    from hqa.agent_workspace_actions import (
        ConversationTurn,
        action_to_document,
        parse_user_action_v1,
        route_for_action,
    )
    from hqa.agent_workspace_contract import WorkspaceRef

    digest = "c" * 64
    action = ConversationTurn(
        client_action_id="action:turn-1",
        workspace=WorkspaceRef(workspace_id="workspace:alpha"),
        managed_session_ref="session:managed.1",
        payload_ref="payload:sha256:" + digest,
        payload_digest=digest,
    )
    document = {
        "schema_version": 1,
        "kind": "conversation.turn",
        "client_action_id": "action:turn-1",
        "workspace": {"workspace_id": "workspace:alpha"},
        "managed_session_ref": "session:managed.1",
        "payload_ref": "payload:sha256:" + digest,
        "payload_digest": digest,
    }

    assert action_to_document(action) == document
    assert parse_user_action_v1(document) == action
    assert route_for_action(action) == (
        "/api/hermes/managed-sessions/session%3Amanaged.1/turns"
    )
    assert not {"prompt", "body", "message"}.intersection(document)


def test_start_research_round_trips_explicit_plan_only_mode() -> None:
    from hqa.agent_workspace_actions import (
        StartResearch,
        action_to_document,
        parse_user_action_v1,
        route_for_action,
    )
    from hqa.agent_workspace_contract import WorkspaceRef

    digest = "d" * 64
    action = StartResearch(
        client_action_id="action:research-start-1",
        workspace=WorkspaceRef(workspace_id="workspace:alpha"),
        managed_session_ref="session:managed.1",
        payload_ref="payload:sha256:" + digest,
        payload_digest=digest,
        initial_mode="plan_only",
    )
    document = {
        "schema_version": 1,
        "kind": "research.start",
        "client_action_id": "action:research-start-1",
        "workspace": {"workspace_id": "workspace:alpha"},
        "managed_session_ref": "session:managed.1",
        "payload_ref": "payload:sha256:" + digest,
        "payload_digest": digest,
        "initial_mode": "plan_only",
    }

    assert action_to_document(action) == document
    assert parse_user_action_v1(document) == action
    assert route_for_action(action) == "/api/hermes/research-tasks"


def test_continue_research_round_trips_to_exact_task_attempt_route() -> None:
    from hqa.agent_workspace_actions import (
        ContinueResearch,
        action_to_document,
        parse_user_action_v1,
        route_for_action,
    )
    from hqa.agent_workspace_contract import WorkspaceRef

    digest = "e" * 64
    action = ContinueResearch(
        client_action_id="action:research-continue-1",
        workspace=WorkspaceRef(workspace_id="workspace:alpha"),
        managed_session_ref="session:managed.1",
        task_ref="task:research.1",
        payload_ref="payload:sha256:" + digest,
        payload_digest=digest,
    )
    document = {
        "schema_version": 1,
        "kind": "research.continue",
        "client_action_id": "action:research-continue-1",
        "workspace": {"workspace_id": "workspace:alpha"},
        "managed_session_ref": "session:managed.1",
        "task_ref": "task:research.1",
        "payload_ref": "payload:sha256:" + digest,
        "payload_digest": digest,
    }

    assert action_to_document(action) == document
    assert parse_user_action_v1(document) == action
    assert route_for_action(action) == (
        "/api/hermes/research-tasks/task%3Aresearch.1/attempts"
    )


def test_confirm_research_plan_round_trips_only_plan_authority_fields() -> None:
    from hqa.agent_workspace_actions import (
        ConfirmResearchPlan,
        action_to_document,
        parse_user_action_v1,
        route_for_action,
    )
    from hqa.agent_workspace_contract import WorkspaceRef

    action = ConfirmResearchPlan(
        client_action_id="action:plan-confirm-1",
        workspace=WorkspaceRef(workspace_id="workspace:alpha"),
        task_ref="task:research.1",
        plan_version=2,
        plan_digest="f" * 64,
    )
    document = {
        "schema_version": 1,
        "kind": "research.plan.confirm",
        "client_action_id": "action:plan-confirm-1",
        "workspace": {"workspace_id": "workspace:alpha"},
        "task_ref": "task:research.1",
        "plan_version": 2,
        "plan_digest": "f" * 64,
    }

    assert action_to_document(action) == document
    assert parse_user_action_v1(document) == action
    assert route_for_action(action) == (
        "/api/hermes/research-tasks/task%3Aresearch.1/plan-confirmations"
    )


def test_request_stop_round_trips_exact_cross_authority_refs() -> None:
    from hqa.agent_workspace_actions import (
        RequestStop,
        action_to_document,
        parse_user_action_v1,
        route_for_action,
    )
    from hqa.agent_workspace_contract import WorkspaceRef

    action = RequestStop(
        client_action_id="action:stop-1",
        workspace=WorkspaceRef(workspace_id="workspace:alpha"),
        run_ref="run:hermes.1",
        task_ref="task:research.1",
        attempt_ref="attempt:research.2",
        platform_job_ref="job:platform.3",
    )
    document = {
        "schema_version": 1,
        "kind": "run.stop.request",
        "client_action_id": "action:stop-1",
        "workspace": {"workspace_id": "workspace:alpha"},
        "run_ref": "run:hermes.1",
        "task_ref": "task:research.1",
        "attempt_ref": "attempt:research.2",
        "platform_job_ref": "job:platform.3",
    }

    assert action_to_document(action) == document
    assert parse_user_action_v1(document) == action
    assert route_for_action(action) == (
        "/api/hermes/runs/run%3Ahermes.1/stop-requests"
    )

    minimal = RequestStop(
        client_action_id="action:stop-2",
        workspace=WorkspaceRef(workspace_id="workspace:alpha"),
        run_ref="run:hermes.2",
        task_ref=None,
        attempt_ref=None,
        platform_job_ref=None,
    )
    assert parse_user_action_v1(action_to_document(minimal)) == minimal


def test_decide_hermes_command_approval_normalizes_expiry_and_routes_exactly() -> None:
    from hqa.agent_workspace_actions import (
        DecideHermesCommandApproval,
        action_to_document,
        parse_user_action_v1,
        route_for_action,
    )
    from hqa.agent_workspace_contract import WorkspaceRef

    action = DecideHermesCommandApproval(
        client_action_id="action:approval-1",
        workspace=WorkspaceRef(workspace_id="workspace:alpha"),
        approval_ref="approval:challenge.1",
        run_ref="run:hermes.1",
        command_digest="1" * 64,
        expected_status="pending",
        expected_expires_at="2026-07-16T20:30:40.123456+08:00",
        decision="allow_once",
    )
    document = {
        "schema_version": 1,
        "kind": "hermes.command_approval.decide",
        "client_action_id": "action:approval-1",
        "workspace": {"workspace_id": "workspace:alpha"},
        "approval_ref": "approval:challenge.1",
        "run_ref": "run:hermes.1",
        "command_digest": "1" * 64,
        "expected_status": "pending",
        "expected_expires_at": "2026-07-16T12:30:40.123456Z",
        "decision": "allow_once",
    }

    assert action.expected_expires_at == "2026-07-16T12:30:40.123456Z"
    assert action_to_document(action) == document
    assert parse_user_action_v1(document) == action
    assert route_for_action(action) == (
        "/api/hermes/command-approvals/approval%3Achallenge.1/decisions"
    )


def test_confirm_formula_source_round_trips_only_gate1_evidence() -> None:
    from hqa.agent_workspace_actions import (
        ConfirmFormulaSource,
        action_to_document,
        parse_user_action_v1,
        route_for_action,
    )
    from hqa.agent_workspace_contract import WorkspaceRef

    action = ConfirmFormulaSource(
        client_action_id="action:gate1-1",
        workspace=WorkspaceRef(workspace_id="workspace:alpha"),
        task_ref="task:research.1",
        reviewed_source_sha256="2" * 64,
        confirmation_note="Reviewed exact formula source bytes.",
    )
    document = {
        "schema_version": 1,
        "kind": "gate1.formula_source.confirm",
        "client_action_id": "action:gate1-1",
        "workspace": {"workspace_id": "workspace:alpha"},
        "task_ref": "task:research.1",
        "reviewed_source_sha256": "2" * 64,
        "confirmation_note": "Reviewed exact formula source bytes.",
    }

    assert action_to_document(action) == document
    assert parse_user_action_v1(document) == action
    assert route_for_action(action) == (
        "/api/hermes/gate1/formula-confirmations"
    )


def test_review_candidate_cas_preserves_human_supplied_gate2_binding() -> None:
    from hqa.agent_workspace_actions import (
        ReviewCandidateCAS,
        action_to_document,
        parse_user_action_v1,
        route_for_action,
    )
    from hqa.agent_workspace_contract import WorkspaceRef

    action = ReviewCandidateCAS(
        client_action_id="action:gate2-1",
        workspace=WorkspaceRef(workspace_id="workspace:alpha"),
        candidate_ref="candidate:factor.1",
        expected_digest="3" * 64,
        expected_status="pending",
        note="Approve only this exact pending candidate digest.",
    )
    document = {
        "schema_version": 1,
        "kind": "gate2.candidate.review",
        "client_action_id": "action:gate2-1",
        "workspace": {"workspace_id": "workspace:alpha"},
        "candidate_ref": "candidate:factor.1",
        "expected_digest": "3" * 64,
        "expected_status": "pending",
        "note": "Approve only this exact pending candidate digest.",
    }

    assert action_to_document(action) == document
    assert parse_user_action_v1(document) == action
    assert route_for_action(action) == (
        "/api/hermes/gate2/candidates/candidate%3Afactor.1/reviews"
    )


def test_prepare_promotion_review_round_trips_exact_gate3_inputs_without_commit() -> None:
    from hqa.agent_workspace_actions import (
        PreparePromotionReview,
        action_to_document,
        parse_user_action_v1,
        route_for_action,
    )
    from hqa.agent_workspace_contract import WorkspaceRef

    action = PreparePromotionReview(
        client_action_id="action:gate3-1",
        workspace=WorkspaceRef(workspace_id="workspace:alpha"),
        candidate_ref="candidate:factor.1",
        expected_digest="4" * 64,
        final_backtest_receipt_ref="receipt:backtest.1",
        base_commit="5" * 40,
    )
    document = {
        "schema_version": 1,
        "kind": "gate3.promotion_review.prepare",
        "client_action_id": "action:gate3-1",
        "workspace": {"workspace_id": "workspace:alpha"},
        "candidate_ref": "candidate:factor.1",
        "expected_digest": "4" * 64,
        "final_backtest_receipt_ref": "receipt:backtest.1",
        "base_commit": "5" * 40,
    }

    assert action_to_document(action) == document
    assert parse_user_action_v1(document) == action
    assert route_for_action(action) == (
        "/api/hermes/gate3/candidates/candidate%3Afactor.1/"
        "promotion-preparations"
    )
    assert not {"commit", "commit_action", "auto_promote"}.intersection(document)


@pytest.mark.parametrize(
    "override",
    [
        {"schema_version": True},
        {"schema_version": 2},
        {"schema_version": "1"},
        {"kind": "unknown.execute"},
        {"kind": 1},
    ],
)
def test_parser_rejects_non_v1_or_unknown_action_discriminators(override: object) -> None:
    from hqa.agent_workspace_actions import parse_user_action_v1

    document = {
        "schema_version": 1,
        "kind": "managed_session.create",
        "client_action_id": "action:create-1",
        "workspace": {"workspace_id": "workspace:alpha"},
        "provider_policy_digest": "a" * 64,
        "payload_ttl_days": 7,
    }
    document.update(override)  # type: ignore[arg-type]

    with pytest.raises((TypeError, ValueError)):
        parse_user_action_v1(document)


def test_parser_requires_the_exact_field_set_for_every_action_kind() -> None:
    from hqa.agent_workspace_actions import parse_user_action_v1

    for document in _valid_action_documents():
        assert parse_user_action_v1(document)

        with_extra = dict(document, unexpected="not allowed")
        with pytest.raises(ValueError, match="exact fields"):
            parse_user_action_v1(with_extra)

        for field in document:
            missing = dict(document)
            del missing[field]
            with pytest.raises(ValueError, match="exact fields"):
                parse_user_action_v1(missing)


def test_every_action_validates_the_common_identifier_and_workspace_ref() -> None:
    from hqa.agent_workspace_actions import parse_user_action_v1

    actions = [
        parse_user_action_v1(document) for document in _valid_action_documents()
    ]
    invalid_identifiers = (None, "", " ", "bad/action", "x" * 201, 1, True)

    for action in actions:
        for invalid in invalid_identifiers:
            with pytest.raises((TypeError, ValueError)):
                replace(action, client_action_id=invalid)
        with pytest.raises((TypeError, ValueError)):
            replace(action, workspace="workspace:alpha")


@pytest.mark.parametrize(
    "workspace",
    [
        {},
        {"workspace_id": "workspace:alpha", "extra": "no"},
        "workspace:alpha",
        {"workspace_id": "bad/workspace"},
        {"workspace_id": True},
    ],
)
def test_parser_requires_the_exact_nested_workspace_document(workspace: object) -> None:
    from hqa.agent_workspace_actions import parse_user_action_v1

    document = _valid_action_documents()[0]
    document["workspace"] = workspace

    with pytest.raises((TypeError, ValueError)):
        parse_user_action_v1(document)


def test_managed_session_policy_digest_and_payload_ttl_are_strict() -> None:
    from hqa.agent_workspace_actions import parse_user_action_v1

    for index in (0, 1):
        valid = _valid_action_documents()[index]
        digest_field = (
            "provider_policy_digest"
            if index == 0
            else "new_provider_policy_digest"
        )
        for boundary in (1, 30):
            document = dict(valid, payload_ttl_days=boundary)
            assert parse_user_action_v1(document).payload_ttl_days == boundary

        for invalid_ttl in (True, 0, 31, 1.0, "7", None):
            document = dict(valid, payload_ttl_days=invalid_ttl)
            with pytest.raises((TypeError, ValueError)):
                parse_user_action_v1(document)

        for invalid_digest in (
            "A" * 64,
            "a" * 63,
            "a" * 65,
            "g" * 64,
            " a" * 32,
            None,
        ):
            document = dict(valid, **{digest_field: invalid_digest})
            with pytest.raises((TypeError, ValueError)):
                parse_user_action_v1(document)


def test_fork_lineage_requires_session_channel_and_bounded_printable_cursor() -> None:
    from hqa.agent_workspace_actions import parse_user_action_v1

    valid = _valid_action_documents()[1]
    for channel in ("discord", "historical", "web_managed"):
        assert (
            parse_user_action_v1(dict(valid, source_channel=channel)).source_channel
            == channel
        )

    invalid_fields = {
        "source_session_ref": (
            "session:",
            "run:source.1",
            "session:bad/path",
            "session:" + "x" * 193,
            True,
        ),
        "source_channel": ("Discord", "managed", "web", "", True),
        "fork_point": ("", "line\nbreak", "x" * 2001, True, None),
    }
    for field, invalid_values in invalid_fields.items():
        for invalid in invalid_values:
            document = dict(valid, **{field: invalid})
            with pytest.raises((TypeError, ValueError)):
                parse_user_action_v1(document)


def test_payload_actions_require_an_exact_matching_content_addressed_reference() -> None:
    from hqa.agent_workspace_actions import parse_user_action_v1

    for index in (2, 3, 4):
        valid = _valid_action_documents()[index]
        for invalid_session in (
            "session:",
            "task:managed.1",
            "session:bad/path",
            True,
        ):
            with pytest.raises((TypeError, ValueError)):
                parse_user_action_v1(
                    dict(valid, managed_session_ref=invalid_session)
                )

        for invalid_ref in (
            "payload:sha256:" + "A" * 64,
            "payload:sha256:" + "c" * 63,
            "payload:" + "c" * 64,
            "c" * 64,
            True,
        ):
            with pytest.raises((TypeError, ValueError)):
                parse_user_action_v1(dict(valid, payload_ref=invalid_ref))

        for invalid_digest in ("C" * 64, "c" * 63, "g" * 64, True):
            with pytest.raises((TypeError, ValueError)):
                parse_user_action_v1(
                    dict(valid, payload_digest=invalid_digest)
                )

        with pytest.raises(ValueError, match="match"):
            parse_user_action_v1(dict(valid, payload_digest="d" * 64))


def test_research_start_and_continue_keep_their_distinct_constraints() -> None:
    from hqa.agent_workspace_actions import parse_user_action_v1

    start = _valid_action_documents()[3]
    for invalid_mode in ("plan", "execute", "PLAN_ONLY", "", True, None):
        with pytest.raises((TypeError, ValueError)):
            parse_user_action_v1(dict(start, initial_mode=invalid_mode))

    continuation = _valid_action_documents()[4]
    for invalid_task in (
        "task:",
        "run:research.1",
        "task:bad/path",
        "task:" + "x" * 196,
        True,
        None,
    ):
        with pytest.raises((TypeError, ValueError)):
            parse_user_action_v1(dict(continuation, task_ref=invalid_task))


def test_plan_confirmation_requires_exact_task_version_and_digest() -> None:
    from hqa.agent_workspace_actions import parse_user_action_v1

    valid = _valid_action_documents()[5]
    for invalid_task in ("task:", "run:research.1", "task:bad/path", True):
        with pytest.raises((TypeError, ValueError)):
            parse_user_action_v1(dict(valid, task_ref=invalid_task))
    for invalid_version in (True, 0, -1, 1.0, "1", None):
        with pytest.raises((TypeError, ValueError)):
            parse_user_action_v1(dict(valid, plan_version=invalid_version))
    for invalid_digest in ("D" * 64, "d" * 63, "g" * 64, True):
        with pytest.raises((TypeError, ValueError)):
            parse_user_action_v1(dict(valid, plan_digest=invalid_digest))


def test_stop_request_requires_run_and_validates_every_optional_ref() -> None:
    from hqa.agent_workspace_actions import parse_user_action_v1

    valid = _valid_action_documents()[6]
    for invalid_run in ("run:", "task:hermes.1", "run:bad/path", True, None):
        with pytest.raises((TypeError, ValueError)):
            parse_user_action_v1(dict(valid, run_ref=invalid_run))

    optional_refs = {
        "task_ref": ("task:research.1", "task:"),
        "attempt_ref": ("attempt:research.1", "attempt:"),
        "platform_job_ref": ("job:platform.1", "job:"),
    }
    for field, (accepted, empty_prefix) in optional_refs.items():
        assert getattr(parse_user_action_v1(dict(valid, **{field: accepted})), field) == (
            accepted
        )
        for invalid in (empty_prefix, "run:wrong.1", "bad/path", True, 1):
            with pytest.raises((TypeError, ValueError)):
                parse_user_action_v1(dict(valid, **{field: invalid}))


def test_hermes_approval_is_exact_single_use_pending_and_timezone_aware() -> None:
    from hqa.agent_workspace_actions import parse_user_action_v1

    valid = _valid_action_documents()[7]
    for decision in ("allow_once", "deny"):
        assert parse_user_action_v1(dict(valid, decision=decision)).decision == decision

    invalid_fields = {
        "approval_ref": ("approval:", "run:challenge.1", "approval:bad/path", True),
        "run_ref": ("run:", "task:hermes.1", "run:bad/path", True),
        "command_digest": ("E" * 64, "e" * 63, "g" * 64, True),
        "expected_status": ("approved", "expired", "Pending", "", True),
        "decision": ("allow", "always", "allow_permanently", "", True),
        "expected_expires_at": (
            "2026-07-16T12:30:40",
            "2026-07-16 12:30:40Z",
            "2026-07-16T12:30:40z",
            "2026-07-16T12:30:40.1234567Z",
            "2026-07-16T12:30:60Z",
            True,
        ),
    }
    for field, invalid_values in invalid_fields.items():
        for invalid in invalid_values:
            with pytest.raises((TypeError, ValueError)):
                parse_user_action_v1(dict(valid, **{field: invalid}))

    normalized = parse_user_action_v1(
        dict(valid, expected_expires_at="2026-07-16T20:30:40+08:00")
    )
    assert normalized.expected_expires_at == "2026-07-16T12:30:40.000000Z"


def test_gate1_requires_exact_source_digest_and_bounded_human_note() -> None:
    from hqa.agent_workspace_actions import parse_user_action_v1

    valid = _valid_action_documents()[8]
    invalid_fields = {
        "task_ref": ("task:", "run:research.1", "task:bad/path", True),
        "reviewed_source_sha256": ("F" * 64, "f" * 63, "g" * 64, True),
        "confirmation_note": (
            "",
            "   ",
            "line\nbreak",
            "nul\x00byte",
            "x" * 2001,
            True,
            None,
        ),
    }
    for field, invalid_values in invalid_fields.items():
        for invalid in invalid_values:
            with pytest.raises((TypeError, ValueError)):
                parse_user_action_v1(dict(valid, **{field: invalid}))


def test_gate2_requires_exact_pending_cas_and_bounded_human_note() -> None:
    from hqa.agent_workspace_actions import parse_user_action_v1

    valid = _valid_action_documents()[9]
    invalid_fields = {
        "candidate_ref": (
            "candidate:",
            "task:factor.1",
            "candidate:bad/path",
            True,
        ),
        "expected_digest": ("A" * 64, "1" * 63, "g" * 64, True),
        "expected_status": ("approved", "rejected", "Pending", "", True),
        "note": ("", "   ", "line\nbreak", "x" * 2001, True, None),
    }
    for field, invalid_values in invalid_fields.items():
        for invalid in invalid_values:
            with pytest.raises((TypeError, ValueError)):
                parse_user_action_v1(dict(valid, **{field: invalid}))


def test_gate3_requires_exact_receipt_digest_and_lowercase_base_commit() -> None:
    from hqa.agent_workspace_actions import parse_user_action_v1

    valid = _valid_action_documents()[10]
    invalid_fields = {
        "candidate_ref": (
            "candidate:",
            "task:factor.1",
            "candidate:bad/path",
            True,
        ),
        "expected_digest": ("A" * 64, "2" * 63, "g" * 64, True),
        "final_backtest_receipt_ref": (
            "receipt:",
            "result:backtest.1",
            "receipt:bad/path",
            True,
        ),
        "base_commit": (
            "3" * 39,
            "3" * 41,
            "A" * 40,
            "g" * 40,
            "HEAD",
            True,
        ),
    }
    for field, invalid_values in invalid_fields.items():
        for invalid in invalid_values:
            with pytest.raises((TypeError, ValueError)):
                parse_user_action_v1(dict(valid, **{field: invalid}))


def test_canonical_action_digest_is_sorted_compact_strict_and_deterministic() -> None:
    from hqa.agent_workspace_actions import (
        action_to_document,
        canonical_action_digest,
        parse_user_action_v1,
    )

    document = _valid_action_documents()[0]
    reordered = dict(reversed(list(document.items())))
    action = parse_user_action_v1(document)
    equivalent = parse_user_action_v1(reordered)
    changed = parse_user_action_v1(dict(document, payload_ttl_days=8))
    canonical_json = json.dumps(
        action_to_document(action),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    expected = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    assert canonical_action_digest(action) == expected
    assert canonical_action_digest(equivalent) == expected
    assert canonical_action_digest(changed) != expected
    assert len(expected) == 64
    assert expected == expected.lower()

    timestamp = _valid_action_documents()[7]
    offset = parse_user_action_v1(
        dict(timestamp, expected_expires_at="2026-07-16T20:30:40+08:00")
    )
    utc = parse_user_action_v1(
        dict(timestamp, expected_expires_at="2026-07-16T12:30:40Z")
    )
    assert canonical_action_digest(offset) == canonical_action_digest(utc)


def test_serialization_digest_and_routing_reject_objects_outside_closed_union() -> None:
    from hqa.agent_workspace_actions import (
        CreateManagedSession,
        action_to_document,
        canonical_action_digest,
        route_for_action,
    )
    from hqa.agent_workspace_contract import WorkspaceRef

    @dataclass(frozen=True)
    class DerivedCreateManagedSession(CreateManagedSession):
        pass

    derived = DerivedCreateManagedSession(
        client_action_id="action:derived-1",
        workspace=WorkspaceRef(workspace_id="workspace:alpha"),
        provider_policy_digest="a" * 64,
        payload_ttl_days=7,
    )
    for invalid in (object(), derived):
        with pytest.raises(TypeError, match="unknown UserActionV1"):
            action_to_document(invalid)
        with pytest.raises(TypeError, match="unknown UserActionV1"):
            canonical_action_digest(invalid)
        with pytest.raises(TypeError, match="unknown UserActionV1"):
            route_for_action(invalid)


def test_all_physical_routes_are_unique_domain_routes_with_no_generic_approve() -> None:
    from hqa.agent_workspace_actions import parse_user_action_v1, route_for_action

    routes = {
        route_for_action(parse_user_action_v1(document))
        for document in _valid_action_documents()
    }
    assert routes == {
        "/api/hermes/managed-sessions",
        "/api/hermes/sessions/session%3Asource.1/forks-to-managed",
        "/api/hermes/managed-sessions/session%3Amanaged.1/turns",
        "/api/hermes/research-tasks",
        "/api/hermes/research-tasks/task%3Aresearch.1/attempts",
        "/api/hermes/research-tasks/task%3Aresearch.1/plan-confirmations",
        "/api/hermes/runs/run%3Ahermes.1/stop-requests",
        "/api/hermes/command-approvals/approval%3Achallenge.1/decisions",
        "/api/hermes/gate1/formula-confirmations",
        "/api/hermes/gate2/candidates/candidate%3Afactor.1/reviews",
        (
            "/api/hermes/gate3/candidates/candidate%3Afactor.1/"
            "promotion-preparations"
        ),
    }
    assert len(routes) == 11
    assert all("/approve" not in route for route in routes)


def test_plan_approval_and_three_domain_gates_are_pairwise_incompatible() -> None:
    from hqa.agent_workspace_actions import parse_user_action_v1

    decisions = [_valid_action_documents()[index] for index in (5, 7, 8, 9, 10)]
    for source in decisions:
        for target in decisions:
            if source["kind"] == target["kind"]:
                continue
            substituted = dict(source, kind=target["kind"])
            with pytest.raises(ValueError, match="exact fields"):
                parse_user_action_v1(substituted)


def test_action_documents_are_defensive_strict_json_without_plaintext_keys() -> None:
    from hqa.agent_workspace_actions import action_to_document, parse_user_action_v1

    forbidden = {
        "prompt",
        "body",
        "message",
        "secret",
        "token",
        "authorization",
    }
    for source in _valid_action_documents():
        action = parse_user_action_v1(source)
        document = action_to_document(action)
        assert json.loads(json.dumps(document, allow_nan=False)) == document
        assert not forbidden.intersection(document)
        assert not forbidden.intersection(document["workspace"])

        document["client_action_id"] = "changed"
        document["workspace"]["workspace_id"] = "workspace:changed"  # type: ignore[index]
        fresh = action_to_document(action)
        assert fresh["client_action_id"] == action.client_action_id
        assert fresh["workspace"] == {
            "workspace_id": action.workspace.workspace_id
        }


def test_closed_union_contains_exactly_eleven_distinct_frozen_dataclasses() -> None:
    from hqa.agent_workspace_actions import (
        ConfirmFormulaSource,
        ConfirmResearchPlan,
        ContinueResearch,
        ConversationTurn,
        CreateManagedSession,
        DecideHermesCommandApproval,
        ForkIntoManagedSession,
        PreparePromotionReview,
        RequestStop,
        ReviewCandidateCAS,
        StartResearch,
        parse_user_action_v1,
    )

    action_types = (
        CreateManagedSession,
        ForkIntoManagedSession,
        ConversationTurn,
        StartResearch,
        ContinueResearch,
        ConfirmResearchPlan,
        RequestStop,
        DecideHermesCommandApproval,
        ConfirmFormulaSource,
        ReviewCandidateCAS,
        PreparePromotionReview,
    )
    assert len(action_types) == len(set(action_types)) == 11
    assert all(is_dataclass(action_type) for action_type in action_types)

    for document, expected_type in zip(_valid_action_documents(), action_types):
        action = parse_user_action_v1(document)
        assert type(action) is expected_type
        with pytest.raises(FrozenInstanceError):
            action.client_action_id = "action:changed"  # type: ignore[misc]


def test_non_finite_and_legacy_fork_policy_values_are_rejected() -> None:
    from hqa.agent_workspace_actions import parse_user_action_v1

    create = _valid_action_documents()[0]
    plan = _valid_action_documents()[5]
    for non_finite in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises((TypeError, ValueError)):
            parse_user_action_v1(dict(create, payload_ttl_days=non_finite))
        with pytest.raises((TypeError, ValueError)):
            parse_user_action_v1(dict(plan, plan_version=non_finite))

    legacy_fork = _valid_action_documents()[1]
    legacy_fork["provider_policy_digest"] = legacy_fork.pop(
        "new_provider_policy_digest"
    )
    with pytest.raises(ValueError, match="exact fields"):
        parse_user_action_v1(legacy_fork)


@pytest.mark.parametrize(
    ("document_index", "field"),
    [
        (1, "source_channel"),
        (3, "initial_mode"),
        (7, "expected_status"),
        (7, "decision"),
        (9, "expected_status"),
        (0, "kind"),
        (0, "schema_version"),
    ],
)
def test_closed_enum_and_discriminator_fields_reject_equality_spoofs(
    document_index: int, field: str
) -> None:
    from hqa.agent_workspace_actions import parse_user_action_v1

    document = _valid_action_documents()[document_index]
    document[field] = _EqualitySpoof()

    with pytest.raises((TypeError, ValueError)):
        parse_user_action_v1(document)


@pytest.mark.parametrize(
    ("document_index", "field"),
    [
        (1, "source_channel"),
        (3, "initial_mode"),
        (7, "expected_status"),
        (7, "decision"),
        (9, "expected_status"),
    ],
)
def test_serialization_and_digest_reject_forged_non_json_enum_values(
    document_index: int, field: str
) -> None:
    from hqa.agent_workspace_actions import (
        action_to_document,
        canonical_action_digest,
        parse_user_action_v1,
    )

    action = parse_user_action_v1(_valid_action_documents()[document_index])
    object.__setattr__(action, field, _EqualitySpoof())

    with pytest.raises(TypeError, match="strict JSON"):
        action_to_document(action)
    with pytest.raises(TypeError, match="strict JSON"):
        canonical_action_digest(action)


@pytest.mark.parametrize(
    ("document_index", "field", "forged_value"),
    [
        (7, "decision", "allow_permanently"),
        (7, "expected_status", "approved"),
        (9, "expected_status", "approved"),
        (3, "initial_mode", "other"),
        (1, "source_channel", "managed"),
        (0, "payload_ttl_days", True),
        (5, "plan_version", True),
        (2, "payload_digest", "d" * 64),
        (4, "task_ref", "task:bad/path"),
        (9, "expected_digest", "A" * 64),
        (8, "confirmation_note", "   "),
        (8, "confirmation_note", "line\nbreak"),
        (10, "base_commit", "HEAD"),
    ],
)
def test_every_public_action_boundary_revalidates_json_valid_forged_fields(
    document_index: int, field: str, forged_value: object
) -> None:
    from hqa.agent_workspace_actions import (
        action_to_document,
        canonical_action_digest,
        parse_user_action_v1,
        route_for_action,
    )

    action = parse_user_action_v1(_valid_action_documents()[document_index])
    object.__setattr__(action, field, forged_value)

    for boundary in (action_to_document, canonical_action_digest, route_for_action):
        with pytest.raises((TypeError, ValueError)):
            boundary(action)


def test_wire_parser_requires_exact_builtin_dicts_and_string_keys() -> None:
    from hqa.agent_workspace_actions import parse_user_action_v1
    from hqa.agent_workspace_contract import WorkspaceRef

    valid = _valid_action_documents()[0]
    for invalid_document in (
        _DictSubclass(valid),
        _CustomMapping(dict(valid)),
    ):
        with pytest.raises((TypeError, ValueError)):
            parse_user_action_v1(invalid_document)  # type: ignore[arg-type]

    for key in (_StringSubclass("kind"), _SpoofStringKey("kind")):
        invalid_key_document = dict(valid)
        kind = invalid_key_document.pop("kind")
        invalid_key_document[key] = kind  # type: ignore[index]
        with pytest.raises((TypeError, ValueError)):
            parse_user_action_v1(invalid_key_document)

    workspace = {"workspace_id": "workspace:alpha"}
    for invalid_workspace in (
        _DictSubclass(workspace),
        _CustomMapping(workspace),
        WorkspaceRef(workspace_id="workspace:alpha"),
    ):
        document = dict(valid, workspace=invalid_workspace)
        with pytest.raises((TypeError, ValueError)):
            parse_user_action_v1(document)

    for key in (
        _StringSubclass("workspace_id"),
        _SpoofStringKey("workspace_id"),
    ):
        invalid_workspace_key = {key: "workspace:alpha"}
        document = dict(valid, workspace=invalid_workspace_key)
        with pytest.raises((TypeError, ValueError)):
            parse_user_action_v1(document)


@pytest.mark.parametrize(
    "timestamp",
    [
        "0001-01-01T00:00:00+14:00",
        "9999-12-31T23:59:59-14:00",
    ],
)
def test_timestamp_utc_normalization_overflow_is_a_controlled_value_error(
    timestamp: str,
) -> None:
    from hqa.agent_workspace_actions import parse_user_action_v1

    approval = _valid_action_documents()[7]
    with pytest.raises(ValueError, match="canonical timezone-aware timestamp"):
        parse_user_action_v1(dict(approval, expected_expires_at=timestamp))


@pytest.mark.parametrize(
    ("document", "expected_digest"),
    [
        (
            {
                "schema_version": 1,
                "kind": "conversation.turn",
                "client_action_id": "action:test-1",
                "workspace": {"workspace_id": "workspace:alpha"},
                "managed_session_ref": "session:managed.1",
                "payload_ref": "payload:sha256:" + "c" * 64,
                "payload_digest": "c" * 64,
            },
            "cc0149daefe9354779611f064c285b2dd653f53e7a0273938176ab97752d7f8e",
        ),
        (
            {
                "schema_version": 1,
                "kind": "gate1.formula_source.confirm",
                "client_action_id": "action:test-1",
                "workspace": {"workspace_id": "workspace:alpha"},
                "task_ref": "task:research.1",
                "reviewed_source_sha256": "f" * 64,
                "confirmation_note": "人工确认精确公式来源。",
            },
            "9feb7fa3262cadafa88d56095c083df4354517c31dd6482b9ea02cffe0371601",
        ),
        (
            {
                "schema_version": 1,
                "kind": "hermes.command_approval.decide",
                "client_action_id": "action:test-1",
                "workspace": {"workspace_id": "workspace:alpha"},
                "approval_ref": "approval:challenge.1",
                "run_ref": "run:hermes.1",
                "command_digest": "e" * 64,
                "expected_status": "pending",
                "expected_expires_at": "2026-07-16T20:30:40+08:00",
                "decision": "deny",
            },
            "e3582b42fbe7b743955fae2feff3a7d818aacaf605bf4afb8a3010a48bf7fd37",
        ),
    ],
)
def test_canonical_action_digest_matches_hard_coded_golden_vectors(
    document: dict[str, object], expected_digest: str
) -> None:
    from hqa.agent_workspace_actions import (
        canonical_action_digest,
        parse_user_action_v1,
    )

    action = parse_user_action_v1(document)
    assert canonical_action_digest(action) == expected_digest


@pytest.mark.parametrize(
    ("document_index", "overrides"),
    [
        (0, {"client_action_id": "action:test-2"}),
        (0, {"workspace": {"workspace_id": "workspace:beta"}}),
        (0, {"provider_policy_digest": "b" * 64}),
        (0, {"payload_ttl_days": 8}),
        (1, {"source_session_ref": "session:source.2"}),
        (1, {"source_channel": "discord"}),
        (1, {"fork_point": "message/2"}),
        (1, {"new_provider_policy_digest": "a" * 64}),
        (1, {"payload_ttl_days": 29}),
        (2, {"managed_session_ref": "session:managed.2"}),
        (
            2,
            {
                "payload_ref": "payload:sha256:" + "d" * 64,
                "payload_digest": "d" * 64,
            },
        ),
        (3, {"managed_session_ref": "session:managed.2"}),
        (
            3,
            {
                "payload_ref": "payload:sha256:" + "d" * 64,
                "payload_digest": "d" * 64,
            },
        ),
        (4, {"managed_session_ref": "session:managed.2"}),
        (4, {"task_ref": "task:research.2"}),
        (
            4,
            {
                "payload_ref": "payload:sha256:" + "d" * 64,
                "payload_digest": "d" * 64,
            },
        ),
        (5, {"task_ref": "task:research.2"}),
        (5, {"plan_version": 2}),
        (5, {"plan_digest": "e" * 64}),
        (6, {"run_ref": "run:hermes.2"}),
        (6, {"task_ref": "task:research.1"}),
        (6, {"attempt_ref": "attempt:research.1"}),
        (6, {"platform_job_ref": "job:platform.1"}),
        (7, {"approval_ref": "approval:challenge.2"}),
        (7, {"run_ref": "run:hermes.2"}),
        (7, {"command_digest": "d" * 64}),
        (7, {"expected_expires_at": "2026-07-16T12:30:41Z"}),
        (7, {"decision": "allow_once"}),
        (8, {"task_ref": "task:research.2"}),
        (8, {"reviewed_source_sha256": "e" * 64}),
        (8, {"confirmation_note": "Reviewed different exact source."}),
        (9, {"candidate_ref": "candidate:factor.2"}),
        (9, {"expected_digest": "2" * 64}),
        (9, {"note": "Review different exact candidate."}),
        (10, {"candidate_ref": "candidate:factor.2"}),
        (10, {"expected_digest": "3" * 64}),
        (10, {"final_backtest_receipt_ref": "receipt:backtest.2"}),
        (10, {"base_commit": "4" * 40}),
    ],
)
def test_every_significant_valid_field_change_changes_the_action_digest(
    document_index: int, overrides: dict[str, object]
) -> None:
    from hqa.agent_workspace_actions import (
        canonical_action_digest,
        parse_user_action_v1,
    )

    original_document = _valid_action_documents()[document_index]
    changed_document = dict(original_document, **overrides)
    original = parse_user_action_v1(original_document)
    changed = parse_user_action_v1(changed_document)

    assert canonical_action_digest(changed) != canonical_action_digest(original)


def test_parsed_action_is_independent_of_later_input_document_mutation() -> None:
    from hqa.agent_workspace_actions import action_to_document, parse_user_action_v1

    document = _valid_action_documents()[2]
    workspace = document["workspace"]
    assert type(workspace) is dict
    action = parse_user_action_v1(document)
    expected = action_to_document(action)

    document["client_action_id"] = "action:mutated"
    document["payload_digest"] = "d" * 64
    workspace["workspace_id"] = "workspace:mutated"
    document.clear()

    assert action_to_document(action) == expected


@pytest.mark.parametrize(
    ("document_index", "field", "valid_prefix"),
    [
        (1, "source_session_ref", "session:source"),
        (2, "managed_session_ref", "session:managed"),
        (2, "payload_ref", "payload:sha256:" + "c" * 64),
        (4, "task_ref", "task:research"),
        (6, "run_ref", "run:hermes"),
        (7, "approval_ref", "approval:challenge"),
        (9, "candidate_ref", "candidate:factor"),
        (10, "final_backtest_receipt_ref", "receipt:backtest"),
    ],
)
@pytest.mark.parametrize("reserved", ["%2F", "%", "?", "#", "中"])
def test_wire_references_reject_reserved_or_unicode_path_content(
    document_index: int, field: str, valid_prefix: str, reserved: str
) -> None:
    from hqa.agent_workspace_actions import parse_user_action_v1

    document = _valid_action_documents()[document_index]
    document[field] = valid_prefix + reserved + "suffix"
    with pytest.raises((TypeError, ValueError)):
        parse_user_action_v1(document)

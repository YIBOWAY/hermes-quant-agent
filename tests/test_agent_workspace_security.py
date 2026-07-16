from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, is_dataclass

import pytest


WORKSPACE = "workspace:alpha"
OWNER = "owner-1"
HOST = "127.0.0.1:8000"
ORIGIN = "http://127.0.0.1:8000"
DIGEST = "a" * 64


class _StringSubclass(str):
    pass


class _EqualitySpoof:
    def __eq__(self, other: object) -> bool:
        return True


def _security_types():
    from hqa.agent_workspace_security import (
        AuthorizationGrant,
        RequestSecurityEvidence,
        WorkspaceSecurityPolicy,
        authorize_workspace_request,
    )

    return (
        AuthorizationGrant,
        RequestSecurityEvidence,
        WorkspaceSecurityPolicy,
        authorize_workspace_request,
    )


def _graph():
    from hqa.agent_workspace_model import SessionRecord, WorkspaceGraph

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
            hermes_session_ref="session:hermes.web",
            workspace_ref=WORKSPACE,
            owner_user_id=OWNER,
            kind="web_managed_session",
            provider_policy_digest="b" * 64,
            writer="web_control_plane",
        ),
    )
    return WorkspaceGraph(
        workspace_ref=WORKSPACE,
        owner_user_id=OWNER,
        sessions=sessions,
    )


def _policy(**changes):
    _, _, WorkspaceSecurityPolicy, _ = _security_types()
    values = {
        "accepted_host": HOST,
        "accepted_origin": ORIGIN,
        "request_body_byte_ceiling": 4_096,
    }
    values.update(changes)
    return WorkspaceSecurityPolicy(**values)


def _evidence(request_kind: str = "api_read", **changes):
    from hqa.agent_workspace_contract import ActorRef

    _, RequestSecurityEvidence, _, _ = _security_types()
    values = {
        "actor": ActorRef(OWNER),
        "request_kind": request_kind,
        "host": HOST,
        "origin": None,
        "sec_fetch_site": "same-origin",
        "signed_actor_session": True,
        "csrf_verified": None,
        "action_digest": None,
        "body_size_bytes": None,
        "rate_allowed": None,
        "target_session_ref": None,
    }
    if request_kind == "mutation":
        values.update(
            {
                "origin": ORIGIN,
                "csrf_verified": True,
                "action_digest": DIGEST,
                "body_size_bytes": 128,
                "rate_allowed": True,
                "target_session_ref": "session:managed",
            }
        )
    values.update(changes)
    return RequestSecurityEvidence(**values)


def _authorize(evidence, *, policy=None, graph=None):
    _, _, _, authorize_workspace_request = _security_types()
    return authorize_workspace_request(
        _policy() if policy is None else policy,
        evidence,
        _graph() if graph is None else graph,
    )


def _assert_error(code: str, operation) -> None:
    from hqa.agent_workspace_contract import WorkspaceContractError

    with pytest.raises(WorkspaceContractError) as caught:
        operation()
    assert caught.value.code == code
    assert str(caught.value) == caught.value.message
    assert caught.value.message == {
        "auth": "workspace_auth_failed",
        "conflict": "workspace_conflict",
        "forbidden": "workspace_forbidden",
        "quota": "workspace_quota_exceeded",
        "validation": "workspace_validation_failed",
    }[code]


def test_security_contract_values_are_exact_frozen_dataclasses() -> None:
    from hqa.agent_workspace_contract import WorkspaceRef

    AuthorizationGrant, RequestSecurityEvidence, WorkspaceSecurityPolicy, _ = (
        _security_types()
    )
    policy = _policy()
    evidence = _evidence("mutation")
    grant = _authorize(evidence)

    assert all(is_dataclass(value) for value in (policy, evidence, grant))
    assert [field.name for field in fields(WorkspaceSecurityPolicy)] == [
        "accepted_host",
        "accepted_origin",
        "request_body_byte_ceiling",
    ]
    assert [field.name for field in fields(RequestSecurityEvidence)] == [
        "actor",
        "request_kind",
        "host",
        "origin",
        "sec_fetch_site",
        "signed_actor_session",
        "csrf_verified",
        "action_digest",
        "body_size_bytes",
        "rate_allowed",
        "target_session_ref",
    ]
    assert [field.name for field in fields(AuthorizationGrant)] == [
        "actor",
        "workspace",
        "request_kind",
        "action_digest",
        "target_session_ref",
    ]
    assert type(grant) is AuthorizationGrant
    assert grant.actor == evidence.actor
    assert grant.workspace == WorkspaceRef(WORKSPACE)
    assert grant.request_kind == "mutation"
    assert grant.action_digest == DIGEST
    assert grant.target_session_ref == "session:managed"

    for value, field_name in (
        (policy, "accepted_host"),
        (evidence, "host"),
        (grant, "request_kind"),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(value, field_name, "changed")


@pytest.mark.parametrize(
    ("request_kind", "origin", "sec_fetch_site"),
    [
        ("top_level_document", None, "none"),
        ("top_level_document", ORIGIN, "same-origin"),
        ("api_read", None, "same-origin"),
        ("api_read", ORIGIN, "same-origin"),
        ("sse_follow", None, "same-origin"),
        ("sse_follow", ORIGIN, "same-origin"),
    ],
)
def test_authorizes_allowed_read_shapes(
    request_kind: str,
    origin: str | None,
    sec_fetch_site: str,
) -> None:
    evidence = _evidence(
        request_kind,
        origin=origin,
        sec_fetch_site=sec_fetch_site,
    )

    grant = _authorize(evidence)

    assert grant.request_kind == request_kind
    assert grant.action_digest is None
    assert grant.target_session_ref is None


@pytest.mark.parametrize(
    ("host", "origin"),
    [
        ("localhost:8000", "http://localhost:8000"),
        ("[::1]:8000", "http://[::1]:8000"),
        ("127.0.0.2:8000", "http://127.0.0.2:8000"),
    ],
)
def test_each_explicitly_configured_loopback_host_is_accepted_exactly(
    host: str,
    origin: str,
) -> None:
    policy = _policy(accepted_host=host, accepted_origin=origin)
    evidence = _evidence(host=host, origin=origin)

    grant = _authorize(evidence, policy=policy)

    assert grant.request_kind == "api_read"


@pytest.mark.parametrize(
    "bad_host",
    [
        "",
        "127.0.0.1",
        "127.0.0.1:0",
        "127.0.0.1:65536",
        "127.0.0.1:8000/path",
        "*.localhost:8000",
        "localhost.attacker.test:8000",
        "example.test:8000",
        "127.0.0.1:8000\r\nX-Evil: yes",
    ],
)
def test_policy_rejects_non_exact_or_non_loopback_hosts(bad_host: str) -> None:
    _assert_error(
        "validation",
        lambda: _policy(
            accepted_host=bad_host,
            accepted_origin="http://" + bad_host,
        ),
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"accepted_host": _StringSubclass(HOST)},
        {"accepted_host": 7},
        {"accepted_origin": _StringSubclass(ORIGIN)},
        {"accepted_origin": "https://example.test"},
        {"accepted_origin": ORIGIN + "/"},
        {"request_body_byte_ceiling": True},
        {"request_body_byte_ceiling": 0},
        {"request_body_byte_ceiling": -1},
    ],
)
def test_policy_rejects_bad_exact_types_and_inconsistent_origin(changes) -> None:
    _assert_error("validation", lambda: _policy(**changes))


@pytest.mark.parametrize(
    "host",
    [
        "localhost:8000",
        "[::1]:8000",
        "127.0.0.1:08000",
        "127.0.0.1:8000.",
        "127.0.0.1:80000",
    ],
)
def test_request_host_is_not_normalized_or_suffix_matched(host: str) -> None:
    _assert_error("forbidden", lambda: _authorize(_evidence(host=host)))


@pytest.mark.parametrize(
    "changes",
    [
        {"host": _StringSubclass(HOST)},
        {"host": _EqualitySpoof()},
        {"origin": _StringSubclass(ORIGIN)},
        {"origin": _EqualitySpoof()},
        {"sec_fetch_site": _StringSubclass("same-origin")},
        {"sec_fetch_site": _EqualitySpoof()},
        {"request_kind": _StringSubclass("api_read")},
        {"request_kind": "unknown"},
        {"csrf_verified": 1},
        {"action_digest": _StringSubclass(DIGEST)},
        {"body_size_bytes": True},
        {"rate_allowed": 1},
        {"target_session_ref": _StringSubclass("session:managed")},
    ],
)
def test_evidence_rejects_bad_exact_types_and_unknown_kind(changes) -> None:
    _assert_error("validation", lambda: _evidence(**changes))


@pytest.mark.parametrize("signed", [None, 0, 1, "true", _EqualitySpoof()])
def test_invalid_signed_session_type_is_auth_failure(signed) -> None:
    _assert_error(
        "auth",
        lambda: _evidence(signed_actor_session=signed),
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"csrf_verified": False},
        {"action_digest": DIGEST},
        {"body_size_bytes": 0},
        {"rate_allowed": False},
        {"target_session_ref": "session:managed"},
    ],
)
def test_read_evidence_rejects_mutation_only_fields(changes) -> None:
    _assert_error("validation", lambda: _evidence(**changes))


def test_missing_or_invalid_signed_session_fails_auth_without_echo() -> None:
    from hqa.agent_workspace_contract import WorkspaceContractError

    evidence = _evidence(signed_actor_session=False)
    with pytest.raises(WorkspaceContractError) as caught:
        _authorize(evidence)

    assert caught.value.code == "auth"
    assert str(caught.value) == "workspace_auth_failed"
    assert HOST not in str(caught.value)
    assert OWNER not in str(caught.value)


@pytest.mark.parametrize(
    "target_session_ref",
    [None, "malformed target", "session:does-not-exist"],
)
def test_wrong_owner_is_rejected_before_target_lookup_without_leakage(
    target_session_ref,
) -> None:
    from hqa.agent_workspace_contract import ActorRef, WorkspaceContractError

    evidence = _evidence(
        "mutation",
        actor=ActorRef("owner-2"),
        target_session_ref=target_session_ref,
    )
    with pytest.raises(WorkspaceContractError) as caught:
        _authorize(evidence)

    assert caught.value.code == "forbidden"
    assert str(caught.value) == "workspace_forbidden"
    assert "owner-2" not in str(caught.value)
    assert "session:" not in str(caught.value)


@pytest.mark.parametrize(
    "evidence",
    [
        lambda: _evidence(host="localhost:8000"),
        lambda: _evidence(origin="https://attacker.test"),
        lambda: _evidence(sec_fetch_site="cross-site"),
        lambda: _evidence(sec_fetch_site="none"),
        lambda: _evidence("sse_follow", sec_fetch_site="none"),
        lambda: _evidence("top_level_document", sec_fetch_site="cross-site"),
        lambda: _evidence("mutation", origin=None),
        lambda: _evidence("mutation", origin="https://attacker.test"),
        lambda: _evidence("mutation", sec_fetch_site="none"),
    ],
)
def test_host_origin_and_fetch_metadata_fail_closed(evidence) -> None:
    _assert_error("forbidden", lambda: _authorize(evidence()))


@pytest.mark.parametrize("csrf_verified", [None, False])
def test_mutation_requires_independently_verified_csrf(csrf_verified) -> None:
    _assert_error(
        "forbidden",
        lambda: _authorize(
            _evidence("mutation", csrf_verified=csrf_verified)
        ),
    )


@pytest.mark.parametrize(
    "action_digest",
    [None, "", "a" * 63, "A" * 64, "g" * 64],
)
def test_mutation_rejects_missing_or_malformed_action_digest(
    action_digest,
) -> None:
    _assert_error(
        "validation",
        lambda: _authorize(
            _evidence("mutation", action_digest=action_digest)
        ),
    )


@pytest.mark.parametrize("body_size_bytes", [None, -1, 4_097])
def test_mutation_rejects_missing_negative_or_oversize_body(
    body_size_bytes,
) -> None:
    _assert_error(
        "validation",
        lambda: _authorize(
            _evidence("mutation", body_size_bytes=body_size_bytes)
        ),
    )


@pytest.mark.parametrize("body_size_bytes", [0, 4_096])
def test_mutation_accepts_body_at_closed_ceiling_boundaries(
    body_size_bytes: int,
) -> None:
    grant = _authorize(
        _evidence("mutation", body_size_bytes=body_size_bytes)
    )

    assert grant.action_digest == DIGEST


def test_mutation_rejects_missing_rate_evidence_as_validation() -> None:
    _assert_error(
        "validation",
        lambda: _authorize(_evidence("mutation", rate_allowed=None)),
    )


def test_mutation_rejects_rate_limit_as_quota() -> None:
    _assert_error(
        "quota",
        lambda: _authorize(_evidence("mutation", rate_allowed=False)),
    )


@pytest.mark.parametrize(
    "target_session_ref",
    [None, "", "managed", "session:", "session:missing"],
)
def test_mutation_rejects_illegal_or_missing_target_without_echo(
    target_session_ref,
) -> None:
    from hqa.agent_workspace_contract import WorkspaceContractError

    with pytest.raises(WorkspaceContractError) as caught:
        _authorize(
            _evidence(
                "mutation",
                target_session_ref=target_session_ref,
            )
        )

    assert caught.value.code == "forbidden"
    assert str(caught.value) == "workspace_forbidden"
    if target_session_ref:
        assert target_session_ref not in str(caught.value)


def test_external_session_write_is_conflict_with_zero_capability() -> None:
    from hqa.agent_workspace_contract import WorkspaceContractError

    with pytest.raises(WorkspaceContractError) as caught:
        _authorize(
            _evidence(
                "mutation",
                target_session_ref="session:external",
            )
        )

    assert caught.value.code == "conflict"
    assert str(caught.value) == "workspace_conflict"
    assert "session:external" not in str(caught.value)


def test_web_writable_session_does_not_bypass_prior_security_gates() -> None:
    _assert_error(
        "forbidden",
        lambda: _authorize(
            _evidence(
                "mutation",
                host="localhost:8000",
                target_session_ref="session:managed",
            )
        ),
    )


def test_exact_public_class_boundaries_reject_subclasses_and_spoofs() -> None:
    from hqa.agent_workspace_contract import ActorRef
    from hqa.agent_workspace_model import WorkspaceGraph
    from hqa.agent_workspace_security import WorkspaceSecurityPolicy

    class ActorSubclass(ActorRef):
        pass

    class PolicySubclass(WorkspaceSecurityPolicy):
        pass

    class GraphSubclass(WorkspaceGraph):
        pass

    _assert_error(
        "forbidden",
        lambda: _evidence(actor=ActorSubclass(OWNER)),
    )
    _assert_error(
        "validation",
        lambda: _authorize(
            _evidence(),
            policy=PolicySubclass(HOST, ORIGIN, 4_096),
        ),
    )
    graph = _graph()
    subclass_graph = GraphSubclass(
        workspace_ref=graph.workspace_ref,
        owner_user_id=graph.owner_user_id,
        sessions=graph.sessions,
    )
    _assert_error(
        "validation",
        lambda: _authorize(_evidence(), graph=subclass_graph),
    )


def test_forged_evidence_and_graph_are_revalidated_at_authorization_boundary() -> None:
    from hqa.agent_workspace_security import RequestSecurityEvidence

    evidence = _evidence("mutation")
    object.__setattr__(evidence, "action_digest", "forged")
    _assert_error("validation", lambda: _authorize(evidence))

    graph = _graph()
    object.__setattr__(graph, "owner_user_id", "owner-2")
    _assert_error("validation", lambda: _authorize(_evidence(), graph=graph))

    assert type(evidence) is RequestSecurityEvidence


def test_authorization_has_no_receipt_or_cache_surface() -> None:
    from hqa.agent_workspace_security import AuthorizationGrant

    public_names = set(AuthorizationGrant.__dataclass_fields__)
    assert "receipt" not in public_names
    assert "cache" not in public_names
    assert "client_action_id" not in public_names

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Optional

from hqa.agent_workspace_contract import (
    ActorRef,
    WorkspaceContractError,
    WorkspaceRef,
)
from hqa.agent_workspace_model import (
    SessionRecord,
    WorkspaceGraph,
    WorkspaceModelError,
    validate_workspace_graph,
)


_REQUEST_KINDS = (
    "top_level_document",
    "api_read",
    "sse_follow",
    "mutation",
)
_SEC_FETCH_SITES = ("same-origin", "same-site", "cross-site", "none")
_HEX64_RE = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")
_MAX_AUTHORITY_GRAPH_RECORDS = 10_000
_AUTHORITY_GRAPH_COLLECTIONS = (
    "sessions",
    "tasks",
    "attempts",
    "submission_commands",
    "runs",
    "result_links",
    "control_command_links",
)
_AUTHORIZATION_GRANT_SEAL = object()
_AUTHORIZATION_GRANT_FIELDS = frozenset(
    {
        "actor",
        "workspace",
        "request_kind",
        "action_digest",
        "target_session_ref",
        "_authorization_seal",
        "_issued_binding",
    }
)


def _fail(code: str) -> None:
    raise WorkspaceContractError(code)


def _is_safe_text(value: Any) -> bool:
    return (
        type(value) is str
        and bool(value)
        and len(value) <= 512
        and value.isprintable()
        and not any(character.isspace() for character in value)
    )


def _validate_loopback_host(value: Any) -> None:
    if not _is_safe_text(value):
        _fail("validation")

    if value.startswith("["):
        match = re.fullmatch(r"\[([^]]+)\]:(\d+)", value)
        if match is None:
            _fail("validation")
        hostname, port_text = match.groups()
        if hostname != "::1":
            _fail("validation")
    else:
        if value.count(":") != 1:
            _fail("validation")
        hostname, port_text = value.rsplit(":", 1)
        if hostname not in ("127.0.0.1", "localhost"):
            _fail("validation")

    if not port_text.isascii() or not port_text.isdigit():
        _fail("validation")
    port = int(port_text)
    if not 1 <= port <= 65_535 or str(port) != port_text:
        _fail("validation")


def _validate_policy(policy: Any) -> None:
    if type(policy) is not WorkspaceSecurityPolicy:
        _fail("validation")
    _validate_loopback_host(policy.accepted_host)
    if type(policy.accepted_origin) is not str or policy.accepted_origin not in (
        "http://" + policy.accepted_host,
        "https://" + policy.accepted_host,
    ):
        _fail("validation")
    if (
        type(policy.request_body_byte_ceiling) is not int
        or policy.request_body_byte_ceiling < 1
    ):
        _fail("validation")
    if (
        type(policy.authority_graph_record_ceiling) is not int
        or policy.authority_graph_record_ceiling < 1
        or policy.authority_graph_record_ceiling > _MAX_AUTHORITY_GRAPH_RECORDS
    ):
        _fail("validation")


def _validate_evidence(evidence: Any) -> None:
    if type(evidence) is not RequestSecurityEvidence:
        _fail("validation")
    if type(evidence.actor) is not ActorRef:
        _fail("forbidden")
    if (
        type(evidence.request_kind) is not str
        or evidence.request_kind not in _REQUEST_KINDS
    ):
        _fail("validation")
    if not _is_safe_text(evidence.host):
        _fail("validation")
    if evidence.origin is not None and not _is_safe_text(evidence.origin):
        _fail("validation")
    if (
        type(evidence.sec_fetch_site) is not str
        or evidence.sec_fetch_site not in _SEC_FETCH_SITES
    ):
        _fail("validation")
    if type(evidence.signed_actor_session) is not bool:
        _fail("auth")
    if evidence.csrf_verified is not None and type(evidence.csrf_verified) is not bool:
        _fail("validation")
    if evidence.action_digest is not None and (
        type(evidence.action_digest) is not str
        or _HEX64_RE.fullmatch(evidence.action_digest) is None
    ):
        _fail("validation")
    if evidence.body_size_bytes is not None and (
        type(evidence.body_size_bytes) is not int
        or evidence.body_size_bytes < 0
    ):
        _fail("validation")
    if evidence.rate_allowed is not None and type(evidence.rate_allowed) is not bool:
        _fail("validation")
    if (
        evidence.target_session_ref is not None
        and type(evidence.target_session_ref) is not str
    ):
        _fail("validation")

    if evidence.request_kind != "mutation" and any(
        value is not None
        for value in (
            evidence.csrf_verified,
            evidence.action_digest,
            evidence.body_size_bytes,
            evidence.rate_allowed,
            evidence.target_session_ref,
        )
    ):
        _fail("validation")


@dataclass(frozen=True)
class WorkspaceSecurityPolicy:
    accepted_host: str
    accepted_origin: str
    request_body_byte_ceiling: int
    authority_graph_record_ceiling: int

    def __post_init__(self) -> None:
        _validate_policy(self)


@dataclass(frozen=True)
class RequestSecurityEvidence:
    actor: ActorRef
    request_kind: str
    host: str
    origin: Optional[str]
    sec_fetch_site: str
    signed_actor_session: bool
    csrf_verified: Optional[bool] = None
    action_digest: Optional[str] = None
    body_size_bytes: Optional[int] = None
    rate_allowed: Optional[bool] = None
    target_session_ref: Optional[str] = None

    def __post_init__(self) -> None:
        _validate_evidence(self)


@dataclass(frozen=True, init=False)
class AuthorizationGrant:
    actor: ActorRef
    workspace: WorkspaceRef
    request_kind: str
    action_digest: Optional[str] = None
    target_session_ref: Optional[str] = None

    def __new__(cls, *args: Any, **kwargs: Any) -> AuthorizationGrant:
        raise TypeError("authorization grants are issued, not constructed")


def _is_session_ref(value: Any) -> bool:
    return (
        type(value) is str
        and value.startswith("session:")
        and value != "session:"
        and _IDENTIFIER_RE.fullmatch(value) is not None
    )


def _copy_actor(actor: Any, error_code: str) -> ActorRef:
    if type(actor) is not ActorRef or type(actor.owner_user_id) is not str:
        _fail(error_code)
    try:
        return ActorRef(actor.owner_user_id)
    except (TypeError, ValueError):
        _fail(error_code)


def _copy_workspace(workspace: Any, error_code: str) -> WorkspaceRef:
    if type(workspace) is not WorkspaceRef or type(workspace.workspace_id) is not str:
        _fail(error_code)
    if (
        not workspace.workspace_id.startswith("workspace:")
        or workspace.workspace_id == "workspace:"
        or _IDENTIFIER_RE.fullmatch(workspace.workspace_id) is None
    ):
        _fail(error_code)
    try:
        return WorkspaceRef(workspace.workspace_id)
    except (TypeError, ValueError):
        _fail(error_code)


def _canonical_actor(actor: ActorRef) -> ActorRef:
    return _copy_actor(actor, "forbidden")


def _issue_authorization_grant(
    actor: ActorRef,
    workspace: WorkspaceRef,
    request_kind: str,
    action_digest: Optional[str] = None,
    target_session_ref: Optional[str] = None,
) -> AuthorizationGrant:
    canonical_actor = _copy_actor(actor, "integrity")
    canonical_workspace = _copy_workspace(workspace, "integrity")
    grant = object.__new__(AuthorizationGrant)
    object.__setattr__(grant, "actor", canonical_actor)
    object.__setattr__(grant, "workspace", canonical_workspace)
    object.__setattr__(grant, "request_kind", request_kind)
    object.__setattr__(grant, "action_digest", action_digest)
    object.__setattr__(grant, "target_session_ref", target_session_ref)
    object.__setattr__(grant, "_authorization_seal", _AUTHORIZATION_GRANT_SEAL)
    object.__setattr__(
        grant,
        "_issued_binding",
        (
            canonical_actor,
            canonical_workspace,
            canonical_actor.owner_user_id,
            canonical_workspace.workspace_id,
            request_kind,
            action_digest,
            target_session_ref,
        ),
    )
    return validate_authorization_grant(grant)


def validate_authorization_grant(grant: Any) -> AuthorizationGrant:
    """Fail closed unless *grant* is an intact result issued by this module."""

    if type(grant) is not AuthorizationGrant:
        _fail("integrity")
    try:
        stored_values = object.__getattribute__(grant, "__dict__")
    except (AttributeError, TypeError):
        _fail("integrity")
    if type(stored_values) is not dict or set(stored_values) != _AUTHORIZATION_GRANT_FIELDS:
        _fail("integrity")
    if stored_values["_authorization_seal"] is not _AUTHORIZATION_GRANT_SEAL:
        _fail("integrity")

    stored_actor = stored_values["actor"]
    stored_workspace = stored_values["workspace"]
    actor = _copy_actor(stored_actor, "integrity")
    workspace = _copy_workspace(stored_workspace, "integrity")
    request_kind = stored_values["request_kind"]
    action_digest = stored_values["action_digest"]
    target_session_ref = stored_values["target_session_ref"]
    if type(request_kind) is not str or request_kind not in _REQUEST_KINDS:
        _fail("integrity")
    if request_kind == "mutation":
        if (
            type(action_digest) is not str
            or _HEX64_RE.fullmatch(action_digest) is None
            or not _is_session_ref(target_session_ref)
        ):
            _fail("integrity")
    elif action_digest is not None or target_session_ref is not None:
        _fail("integrity")

    expected_binding = (
        actor.owner_user_id,
        workspace.workspace_id,
        request_kind,
        action_digest,
        target_session_ref,
    )
    issued_binding = stored_values["_issued_binding"]
    if (
        type(issued_binding) is not tuple
        or len(issued_binding) != 7
        or issued_binding[0] is not stored_actor
        or issued_binding[1] is not stored_workspace
        or issued_binding[2:] != expected_binding
    ):
        _fail("integrity")
    return grant


def _canonical_graph_root(graph: Any) -> tuple[str, WorkspaceRef]:
    if type(graph) is not WorkspaceGraph:
        _fail("validation")
    if type(graph.owner_user_id) is not str or type(graph.workspace_ref) is not str:
        _fail("validation")
    try:
        owner = ActorRef(graph.owner_user_id)
        workspace = WorkspaceRef(graph.workspace_ref)
    except (TypeError, ValueError):
        _fail("validation")
    if (
        not graph.workspace_ref.startswith("workspace:")
        or graph.workspace_ref == "workspace:"
        or _IDENTIFIER_RE.fullmatch(graph.workspace_ref) is None
    ):
        _fail("validation")
    return owner.owner_user_id, workspace


def _validated_graph(graph: Any) -> WorkspaceGraph:
    if type(graph) is not WorkspaceGraph:
        _fail("validation")
    try:
        validate_workspace_graph(graph)
    except (WorkspaceModelError, TypeError, ValueError):
        _fail("validation")
    return graph


def _enforce_authority_graph_record_ceiling(
    policy: WorkspaceSecurityPolicy,
    graph: WorkspaceGraph,
) -> None:
    total = 0
    for field_name in _AUTHORITY_GRAPH_COLLECTIONS:
        try:
            records = getattr(graph, field_name)
        except AttributeError:
            _fail("validation")
        if type(records) is not tuple:
            _fail("validation")
        record_count = len(records)
        if record_count > policy.authority_graph_record_ceiling - total:
            _fail("quota")
        total += record_count


def authorize_workspace_request(
    policy: WorkspaceSecurityPolicy,
    evidence: RequestSecurityEvidence,
    graph: WorkspaceGraph,
) -> AuthorizationGrant:
    """Authorize one request without reading receipts or producing side effects."""

    _validate_policy(policy)
    _validate_evidence(evidence)

    if evidence.host != policy.accepted_host:
        _fail("forbidden")
    if not evidence.signed_actor_session:
        _fail("auth")
    actor = _canonical_actor(evidence.actor)
    root_owner, workspace = _canonical_graph_root(graph)
    if actor.owner_user_id != root_owner:
        _fail("forbidden")
    if evidence.origin is not None and evidence.origin != policy.accepted_origin:
        _fail("forbidden")
    if (
        evidence.request_kind == "mutation"
        and evidence.origin != policy.accepted_origin
    ):
        _fail("forbidden")
    if evidence.request_kind == "top_level_document":
        if evidence.sec_fetch_site not in ("none", "same-origin"):
            _fail("forbidden")
    elif evidence.sec_fetch_site != "same-origin":
        _fail("forbidden")

    if evidence.request_kind == "mutation":
        if evidence.csrf_verified is not True:
            _fail("forbidden")
        if (
            type(evidence.action_digest) is not str
            or _HEX64_RE.fullmatch(evidence.action_digest) is None
        ):
            _fail("validation")
        if (
            type(evidence.body_size_bytes) is not int
            or evidence.body_size_bytes < 0
            or evidence.body_size_bytes > policy.request_body_byte_ceiling
        ):
            _fail("validation")
        if evidence.rate_allowed is None:
            _fail("validation")
        if evidence.rate_allowed is not True:
            _fail("quota")
        if not _is_session_ref(evidence.target_session_ref):
            _fail("forbidden")

    _enforce_authority_graph_record_ceiling(policy, graph)
    validated_graph = _validated_graph(graph)
    if evidence.request_kind != "mutation":
        return _issue_authorization_grant(
            actor=actor,
            workspace=workspace,
            request_kind=evidence.request_kind,
        )

    target: Optional[SessionRecord] = None
    for session in validated_graph.sessions:
        if session.session_ref == evidence.target_session_ref:
            target = session
            break
    if target is None:
        _fail("forbidden")
    if target.kind == "observed_external_session":
        _fail("conflict")
    if (
        target.kind != "web_managed_session"
        or target.workspace_ref != validated_graph.workspace_ref
        or target.owner_user_id != validated_graph.owner_user_id
        or not target.web_writable
    ):
        _fail("forbidden")

    return _issue_authorization_grant(
        actor=actor,
        workspace=workspace,
        request_kind=evidence.request_kind,
        action_digest=evidence.action_digest,
        target_session_ref=evidence.target_session_ref,
    )


__all__ = (
    "AuthorizationGrant",
    "RequestSecurityEvidence",
    "WorkspaceSecurityPolicy",
    "authorize_workspace_request",
    "validate_authorization_grant",
)

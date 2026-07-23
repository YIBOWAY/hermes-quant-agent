from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional

import pytest

from hqa.hermes_managed_session import (
    OfficialHermesManagedSessionPort,
    derive_managed_session_id,
)
from hqa.hermes_run_adapter import HermesRunError


class _ScriptedTransport:
    def __init__(
        self,
        *,
        gets: list[object],
        posts: Optional[list[object]] = None,
    ) -> None:
        self.gets = list(gets)
        self.posts = list(posts or [])
        self.calls: list[tuple[str, str, Optional[object]]] = []

    def get_json(
        self,
        path: str,
        *,
        headers: Optional[Mapping[str, str]] = None,
    ) -> Mapping[str, Any]:
        self.calls.append(("GET", path, None))
        outcome = self.gets.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        assert isinstance(outcome, Mapping)
        return outcome

    def post_json(
        self,
        path: str,
        body: Mapping[str, Any],
        *,
        headers: Optional[Mapping[str, str]] = None,
    ) -> tuple[int, Mapping[str, Any]]:
        self.calls.append(("POST", path, dict(body)))
        outcome = self.posts.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        assert isinstance(outcome, tuple)
        return outcome


def _missing() -> HermesRunError:
    return HermesRunError(
        "session_not_found",
        "secret upstream path",
        http_status=404,
    )


def _session(session_id: str, **extra: object) -> dict[str, object]:
    return {
        "object": "hermes.session",
        "session": {
            "id": session_id,
            "source": "api_server",
            "parent_session_id": None,
            **extra,
        },
    }


def test_deterministic_managed_session_id_is_action_digest_bound() -> None:
    digest = "a" * 64
    assert derive_managed_session_id(digest) == f"web_{'a' * 40}"
    with pytest.raises(HermesRunError) as captured:
        derive_managed_session_id("not-a-digest")
    assert captured.value.code == "managed_session_invalid_request"


def test_ensure_creates_once_then_replays_existing_identity() -> None:
    digest = "1" * 64
    session_id = derive_managed_session_id(digest)
    transport = _ScriptedTransport(
        gets=[
            _missing(),
            _session(session_id),
        ],
        posts=[
            (
                201,
                _session(session_id),
            )
        ],
    )
    port = OfficialHermesManagedSessionPort(transport=transport)  # type: ignore[arg-type]

    first = port.ensure(
        action_digest=digest,
        session_id=session_id,
        title="Agent v0.2",
    )
    second = port.ensure(
        action_digest=digest,
        session_id=session_id,
        title="Agent v0.2",
    )

    assert first.created is True
    assert second.created is False
    assert first.session_id == second.session_id == session_id
    assert transport.calls == [
        ("GET", f"/api/sessions/{session_id}", None),
        (
            "POST",
            "/api/sessions",
            {"id": session_id, "title": "Agent v0.2"},
        ),
        ("GET", f"/api/sessions/{session_id}", None),
    ]


@pytest.mark.parametrize(
    "post_error",
    [
        HermesRunError(
            "session_exists",
            "already exists",
            http_status=409,
        ),
        HermesRunError(
            "transport_error",
            "ack lost after commit; secret",
            http_status=502,
        ),
    ],
)
def test_ensure_recovers_409_or_ack_loss_by_exact_get(
    post_error: HermesRunError,
) -> None:
    digest = "2" * 64
    session_id = derive_managed_session_id(digest)
    transport = _ScriptedTransport(
        gets=[_missing(), _session(session_id)],
        posts=[post_error],
    )
    port = OfficialHermesManagedSessionPort(transport=transport)  # type: ignore[arg-type]

    receipt = port.ensure(action_digest=digest, session_id=session_id)

    assert receipt.created is False
    assert receipt.recovered is True
    assert receipt.session_id == session_id


def test_ensure_rejects_upstream_identity_substitution() -> None:
    digest = "3" * 64
    session_id = derive_managed_session_id(digest)
    transport = _ScriptedTransport(
        gets=[_missing()],
        posts=[(201, _session("web_substituted"))],
    )
    port = OfficialHermesManagedSessionPort(transport=transport)  # type: ignore[arg-type]

    with pytest.raises(HermesRunError) as captured:
        port.ensure(action_digest=digest, session_id=session_id)

    assert captured.value.code == "managed_session_identity_mismatch"
    assert session_id not in str(captured.value)


def test_ensure_preserves_retryable_transport_outcome_when_no_commit_is_visible() -> None:
    digest = "7" * 64
    session_id = derive_managed_session_id(digest)
    transport = _ScriptedTransport(
        gets=[_missing(), _missing()],
        posts=[
            HermesRunError(
                "transport_error",
                "request did not reach Hermes",
                http_status=502,
            )
        ],
    )
    port = OfficialHermesManagedSessionPort(transport=transport)  # type: ignore[arg-type]

    with pytest.raises(HermesRunError) as captured:
        port.ensure(action_digest=digest, session_id=session_id)

    assert captured.value.code == "transport_error"


def test_fork_preserves_source_and_uses_exact_message_cursor() -> None:
    digest = "4" * 64
    target_id = derive_managed_session_id(digest)
    source_before = _session(
        "discord-source",
        source="discord",
        title="Source",
        message_count=3,
    )
    source_after = _session(
        "discord-source",
        source="discord",
        title="Source",
        message_count=3,
    )
    child = _session(
        target_id,
        parent_session_id="discord-source",
        title="Managed fork",
    )
    transport = _ScriptedTransport(
        gets=[
            source_before,
            {
                "object": "list",
                "session_id": "discord-source",
                "data": [{"id": 7, "role": "user", "content": "source"}],
            },
            source_after,
        ],
        posts=[
            (
                201,
                {
                    **child,
                    "source_session_id": "discord-source",
                    "resolved_source_session_id": "discord-source",
                    "fork_point": "message:7",
                    "preserve_source": True,
                },
            )
        ],
    )
    port = OfficialHermesManagedSessionPort(transport=transport)  # type: ignore[arg-type]

    receipt = port.fork(
        action_digest=digest,
        source_session_id="discord-source",
        session_id=target_id,
        fork_point="message:7",
        title="Managed fork",
    )

    assert receipt.created is True
    assert receipt.source_session_id == "discord-source"
    assert receipt.session_id == target_id
    assert receipt.fork_point == "message:7"
    assert transport.calls[2] == (
        "POST",
        "/api/sessions/discord-source/fork",
        {
            "id": target_id,
            "fork_point": "message:7",
            "preserve_source": True,
            "title": "Managed fork",
        },
    )


def test_fork_ack_loss_recovers_exact_child_without_mutating_source() -> None:
    digest = "5" * 64
    target_id = derive_managed_session_id(digest)
    source = _session("historical-source", source="historical", message_count=2)
    transport = _ScriptedTransport(
        gets=[
            source,
            {
                "object": "list",
                "session_id": "historical-source",
                "data": [{"id": 11}],
            },
            _session(target_id, parent_session_id="historical-source"),
            source,
        ],
        posts=[
            HermesRunError(
                "transport_error",
                "fork ack lost",
                http_status=502,
            )
        ],
    )
    port = OfficialHermesManagedSessionPort(transport=transport)  # type: ignore[arg-type]

    receipt = port.fork(
        action_digest=digest,
        source_session_id="historical-source",
        session_id=target_id,
        fork_point="message:11",
    )

    assert receipt.created is False
    assert receipt.recovered is True
    assert receipt.resolved_source_session_id == "historical-source"


@pytest.mark.parametrize(
    "fork_point",
    ["", "cursor:latest", "message:0", "message:-1", "message:01", "message: 1"],
)
def test_fork_rejects_non_exact_cursor_before_transport(fork_point: str) -> None:
    transport = _ScriptedTransport(gets=[])
    port = OfficialHermesManagedSessionPort(transport=transport)  # type: ignore[arg-type]

    with pytest.raises(HermesRunError) as captured:
        port.fork(
            action_digest="6" * 64,
            source_session_id="source",
            session_id=derive_managed_session_id("6" * 64),
            fork_point=fork_point,
        )

    assert captured.value.code == "managed_session_invalid_request"
    assert transport.calls == []

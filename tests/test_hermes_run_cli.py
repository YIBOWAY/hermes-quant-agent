from __future__ import annotations

import io
import json
from collections.abc import Mapping
from typing import Any, Optional, Union

import pytest

from hqa.hermes_managed_session import (
    ManagedSessionForkReceipt,
    ManagedSessionReceipt,
    derive_managed_session_id,
)
from hqa.hermes_run_adapter import (
    RunHandle,
    RunStatusSnapshot,
    StreamEvent,
)
from hqa.hermes_run_cli import main


def _grounded_capabilities() -> dict[str, object]:
    grounded = {"supported": True, "grounded": True}
    return {
        "contract_version": 1,
        "features": {
            "run_submission": True,
            "managed_run_sessions": True,
            "managed_run_history_authority": "hermes_session_db",
            "managed_session_fork_mode": "preserve_source_exact_message_cursor",
        },
        "durable": {
            key: dict(grounded)
            for key in (
                "idempotency",
                "event_replay",
                "approval_cas",
                "idempotent_stop",
                "restart_reconcile",
                "run_evidence",
            )
        },
    }


class _FakeRunAdapter:
    def __init__(
        self,
        *,
        created: bool = True,
        conversation_session_id: str | None = None,
        resolved_session_id: str | None = None,
    ) -> None:
        self.created = created
        self.conversation_session_id = conversation_session_id
        self.resolved_session_id = resolved_session_id
        self.calls: list[tuple[str, object]] = []

    def capabilities(self) -> Mapping[str, Any]:
        self.calls.append(("capabilities", None))
        return _grounded_capabilities()

    def submit_or_get(
        self,
        *,
        idempotency_key: Optional[str],
        request_body: Mapping[str, Any],
    ) -> RunHandle:
        self.calls.append(
            (
                "submit",
                {
                    "idempotency_key": idempotency_key,
                    "request_body": dict(request_body),
                },
            )
        )
        return RunHandle(
            run_id="run_cli_1",
            created=self.created,
            idempotency_key=idempotency_key,
            conversation_session_id=(
                self.conversation_session_id
                or str(request_body["session_id"])
            ),
            resolved_session_id=(
                self.resolved_session_id
                or str(request_body["session_id"])
            ),
        )

    def get_status(self, run_id: str) -> RunStatusSnapshot:
        self.calls.append(("status", run_id))
        return RunStatusSnapshot(
            run_id=run_id,
            status="succeeded",
            session_id="web_managed_1",
            requested_policy={"model": "gpt-5"},
            actual_policy={"provider": "openai", "model": "gpt-5"},
            usage={"input_tokens": 3, "output_tokens": 1},
        )

    def stream_events(
        self,
        run_id: str,
        *,
        since_seq: int = 0,
    ) -> list[StreamEvent]:
        self.calls.append(("events", {"run_id": run_id, "since_seq": since_seq}))
        return [
            StreamEvent(
                seq=since_seq + 1,
                event_type="run.completed",
                run_id=run_id,
                payload={"usage": {}},
                event_id="event-1",
            )
        ]


class _FakeSessionPort:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def ensure(self, **kwargs: object) -> ManagedSessionReceipt:
        self.calls.append(("ensure", dict(kwargs)))
        return ManagedSessionReceipt(
            session_id=str(kwargs["session_id"]),
            created=True,
            recovered=False,
            session={
                "id": str(kwargs["session_id"]),
                "source": "api_server",
            },
        )

    def fork(self, **kwargs: object) -> ManagedSessionForkReceipt:
        self.calls.append(("fork", dict(kwargs)))
        return ManagedSessionForkReceipt(
            session_id=str(kwargs["session_id"]),
            source_session_id=str(kwargs["source_session_id"]),
            resolved_source_session_id=str(kwargs["source_session_id"]),
            fork_point=str(kwargs["fork_point"]),
            created=True,
            recovered=False,
            session={
                "id": str(kwargs["session_id"]),
                "parent_session_id": str(kwargs["source_session_id"]),
            },
        )


def _body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "endpoint": {
            "base_url": "http://127.0.0.1:8642",
            "timeout_seconds": 5.0,
            "api_key": "stdin-only-secret",
        }
    }
    body.update(overrides)
    return body


def _run(
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    body: Union[dict[str, object], bytes],
    *,
    adapter: Optional[_FakeRunAdapter] = None,
    sessions: Optional[_FakeSessionPort] = None,
) -> tuple[int, dict[str, object], str]:
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    monkeypatch.setattr(
        "sys.stdin",
        io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8"),
    )
    stdout = io.StringIO()
    stderr = io.StringIO()
    monkeypatch.setattr("sys.stdout", stdout)
    monkeypatch.setattr("sys.stderr", stderr)
    code = main(
        [command],
        adapter_factory=(lambda _endpoint: adapter or _FakeRunAdapter()),
        session_port_factory=(lambda _endpoint: sessions or _FakeSessionPort()),
    )
    lines = stdout.getvalue().splitlines()
    assert len(lines) == 1
    return code, json.loads(lines[0]), stderr.getvalue()


def test_capabilities_requires_durable_and_managed_history_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _FakeRunAdapter()
    code, response, stderr = _run(
        monkeypatch,
        "capabilities",
        _body(),
        adapter=adapter,
    )

    assert code == 0
    assert response["ok"] is True
    assert response["capabilities"] == _grounded_capabilities()
    assert response["cli_contract"] == {
        "schema_version": 1,
        "profile": "local_agent_v0_2",
        "operations": [
            "capabilities",
            "submit",
            "status",
            "events",
            "session-ensure",
            "session-fork",
        ],
        "write_contract": {
            "run_submit_fields": ["input", "session_id", "metadata", "instructions"],
            "platform_must_not_send": [
                "conversation_history",
                "previous_response_id",
            ],
            "fork_requires": {
                "preserve_source": True,
                "fork_point_format": "message:<positive-integer-id>",
            },
        },
    }
    assert response["managed_session_ready"] is True
    assert stderr == ""


def test_submit_passes_only_strict_native_session_body_and_replay_bit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _FakeRunAdapter(created=False)
    request_body = {
        "input": "second turn",
        "session_id": "web_managed_1",
        "metadata": {"command_id": "cmd-2", "source": "platform"},
    }
    code, response, _ = _run(
        monkeypatch,
        "submit",
        _body(
            idempotency_key="platform-command:cmd-2",
            request_body=request_body,
        ),
        adapter=adapter,
    )

    assert code == 0
    assert response == {
        "ok": True,
        "run_id": "run_cli_1",
        "session_id": "web_managed_1",
        "requested_session_id": "web_managed_1",
        "conversation_session_id": "web_managed_1",
        "resolved_session_id": "web_managed_1",
        "created": False,
        "idempotency_key": "platform-command:cmd-2",
    }
    assert adapter.calls == [
        (
            "submit",
            {
                "idempotency_key": "platform-command:cmd-2",
                "request_body": request_body,
            },
        )
    ]


def test_submit_receipt_keeps_root_and_resolved_tip_distinct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _FakeRunAdapter(
        created=False,
        conversation_session_id="web_root",
        resolved_session_id="web_tip",
    )

    code, response, _ = _run(
        monkeypatch,
        "submit",
        _body(
            idempotency_key="platform-command:compressed",
            request_body={
                "input": "continue",
                "session_id": "web_root",
                "metadata": {"command_id": "compressed"},
            },
        ),
        adapter=adapter,
    )

    assert code == 0
    assert response["requested_session_id"] == "web_root"
    assert response["conversation_session_id"] == "web_root"
    assert response["resolved_session_id"] == "web_tip"
    # Compatibility field remains the actual Session bound to the Run.
    assert response["session_id"] == "web_tip"


def test_submit_allows_only_contract_bound_paper_intake_instructions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _FakeRunAdapter()
    request_body = {
        "input": "private exact paper prompt",
        "session_id": "web_managed_1",
        "metadata": {
            "execution_contract": "hqa.paper_intake/v1",
            "execution_contract_digest": "d" * 64,
            "research_claim_digest": "e" * 64,
        },
        "instructions": "This run is governed by hqa.paper_intake/v1. Use tools.",
    }

    code, response, _ = _run(
        monkeypatch,
        "submit",
        _body(idempotency_key="paper-key-1", request_body=request_body),
        adapter=adapter,
    )

    assert code == 0
    assert response["ok"] is True
    assert adapter.calls[-1][1]["request_body"] == request_body  # type: ignore[index]


@pytest.mark.parametrize(
    "metadata",
    [
        {},
        {"execution_contract": "hqa.paper_intake/v1"},
        {
            "execution_contract": "other/v1",
            "execution_contract_digest": "d" * 64,
            "research_claim_digest": "e" * 64,
        },
    ],
)
def test_submit_rejects_unbound_system_instructions(
    monkeypatch: pytest.MonkeyPatch,
    metadata: dict[str, object],
) -> None:
    adapter = _FakeRunAdapter()

    code, response, _ = _run(
        monkeypatch,
        "submit",
        _body(
            idempotency_key="paper-key-invalid",
            request_body={
                "input": "paper prompt",
                "session_id": "web_managed_1",
                "metadata": metadata,
                "instructions": "This run is governed by hqa.paper_intake/v1.",
            },
        ),
        adapter=adapter,
    )

    assert code == 2
    assert response["error"]["code"] == "run_invalid_request"
    assert adapter.calls == []


@pytest.mark.parametrize(
    "forbidden",
    ["conversation_history", "previous_response_id", "prompt", "messages"],
)
def test_submit_rejects_history_or_body_smuggling_without_adapter_call(
    monkeypatch: pytest.MonkeyPatch,
    forbidden: str,
) -> None:
    adapter = _FakeRunAdapter()
    request_body = {
        "input": "hello",
        "session_id": "web_managed_1",
        "metadata": {},
        forbidden: [],
    }
    code, response, stderr = _run(
        monkeypatch,
        "submit",
        _body(idempotency_key="key-1", request_body=request_body),
        adapter=adapter,
    )

    assert code == 2
    assert response["error"]["code"] == "run_invalid_request"
    assert adapter.calls == []
    assert stderr == ""


def test_status_and_events_match_platform_process_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _FakeRunAdapter()
    status_code, status, _ = _run(
        monkeypatch,
        "status",
        _body(run_id="run_cli_1"),
        adapter=adapter,
    )
    event_code, events, _ = _run(
        monkeypatch,
        "events",
        _body(run_id="run_cli_1", since_seq=4),
        adapter=adapter,
    )

    assert status_code == event_code == 0
    assert status["run_id"] == "run_cli_1"
    assert status["session_id"] == "web_managed_1"
    assert status["status"] == "succeeded"
    assert events == {
        "ok": True,
        "run_id": "run_cli_1",
        "since_seq": 4,
        "next_seq": 5,
        "events": [
            {
                "seq": 5,
                "event_type": "run.completed",
                "run_id": "run_cli_1",
                "payload": {"usage": {}},
                "event_id": "event-1",
            }
        ],
    }


def test_session_ensure_and_fork_are_digest_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = _FakeSessionPort()
    create_digest = "a" * 64
    create_id = derive_managed_session_id(create_digest)
    code, ensured, _ = _run(
        monkeypatch,
        "session-ensure",
        _body(
            action_digest=create_digest,
            session_id=create_id,
            title="Agent v0.2",
        ),
        sessions=sessions,
    )
    fork_digest = "b" * 64
    fork_id = derive_managed_session_id(fork_digest)
    fork_code, forked, _ = _run(
        monkeypatch,
        "session-fork",
        _body(
            action_digest=fork_digest,
            source_session_id="discord-source",
            session_id=fork_id,
            fork_point="message:42",
        ),
        sessions=sessions,
    )

    assert code == fork_code == 0
    assert ensured["action_digest"] == create_digest
    assert ensured["session_id"] == create_id
    assert ensured["created"] is True
    assert forked["action_digest"] == fork_digest
    assert forked["session_id"] == fork_id
    assert forked["source_session_id"] == "discord-source"
    assert forked["preserve_source"] is True


@pytest.mark.parametrize(
    ("command", "body"),
    [
        (
            "submit",
            _body(
                idempotency_key="key",
                request_body={
                    "input": "x" * 16_385,
                    "session_id": "web_1",
                    "metadata": {},
                },
            ),
        ),
        (
            "status",
            _body(run_id="bad\nid"),
        ),
        (
            "events",
            _body(run_id="run_1", since_seq=-1),
        ),
        (
            "session-ensure",
            _body(
                action_digest="c" * 64,
                session_id="web_wrong",
            ),
        ),
    ],
)
def test_invalid_or_oversized_requests_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    body: dict[str, object],
) -> None:
    adapter = _FakeRunAdapter()
    sessions = _FakeSessionPort()
    code, response, stderr = _run(
        monkeypatch,
        command,
        body,
        adapter=adapter,
        sessions=sessions,
    )

    assert code == 2
    assert response["error"]["retryable"] is False
    assert adapter.calls == []
    assert sessions.calls == []
    assert "stdin-only-secret" not in json.dumps(response)
    assert stderr == ""


def test_non_loopback_duplicate_and_nonfinite_json_are_rejected_secret_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases = [
        json.dumps(
            {
                "endpoint": {
                    "base_url": "https://example.com",
                    "timeout_seconds": 5,
                    "api_key": "secret",
                }
            }
        ).encode(),
        b'{"endpoint":{"base_url":"http://127.0.0.1:1","base_url":"http://127.0.0.1:2"}}',
        b'{"endpoint":{"base_url":"http://127.0.0.1:1","timeout_seconds":NaN}}',
    ]

    for raw in cases:
        code, response, stderr = _run(
            monkeypatch,
            "capabilities",
            raw,
        )
        assert code == 2
        assert response["error"]["retryable"] is False
        assert "secret" not in json.dumps(response)
        assert stderr == ""

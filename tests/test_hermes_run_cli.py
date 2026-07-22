"""Closed-schema subprocess port for the canonical Hermes durable Run seam."""

from __future__ import annotations

import io
import json
import sys

import pytest

from hqa.hermes_run_adapter import HermesRunError, ScriptedFakeHermesAdapter
from hqa.hermes_run_cli import main


def _invoke(
    monkeypatch: pytest.MonkeyPatch,
    fake: ScriptedFakeHermesAdapter,
    command: str,
    request: dict[str, object],
) -> tuple[int, dict[str, object]]:
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(request)))
    monkeypatch.setattr(sys, "stdout", stdout)
    code = main([command], adapter_factory=lambda _endpoint: fake)
    lines = stdout.getvalue().splitlines()
    assert len(lines) == 1
    return code, json.loads(lines[0])


def _endpoint() -> dict[str, object]:
    return {
        "base_url": "http://127.0.0.1:8642",
        "api_key": "must-never-be-echoed",
        "timeout_seconds": 3.0,
    }


def test_submit_replays_same_request_and_preserves_managed_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = ScriptedFakeHermesAdapter()
    request = {
        "endpoint": _endpoint(),
        "idempotency_key": "owner:session:action-1",
        "request_body": {
            "input": "hello",
            "session_id": "web_0123456789abcdef",
            "model": "openai/gpt-5",
        },
    }

    first_code, first = _invoke(monkeypatch, fake, "submit", request)
    second_code, second = _invoke(monkeypatch, fake, "submit", request)

    assert first_code == second_code == 0
    assert first["ok"] is True
    assert first["created"] is True
    assert second["created"] is False
    assert second["run_id"] == first["run_id"]
    assert fake.get_status(str(first["run_id"])).session_id == "web_0123456789abcdef"
    assert "must-never-be-echoed" not in json.dumps(first)


def test_status_and_events_return_canonical_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = ScriptedFakeHermesAdapter()
    handle = fake.submit_or_get(
        idempotency_key="action-2",
        request_body={"input": "hello", "session_id": "web_session"},
    )
    fake.drive_to_terminal(
        handle.run_id,
        actual_model="gpt-5",
        actual_provider="openai",
        usage={"input_tokens": 4, "output_tokens": 2},
    )

    status_code, status = _invoke(
        monkeypatch,
        fake,
        "status",
        {"endpoint": _endpoint(), "run_id": handle.run_id},
    )
    events_code, events = _invoke(
        monkeypatch,
        fake,
        "events",
        {"endpoint": _endpoint(), "run_id": handle.run_id, "since_seq": 0},
    )

    assert status_code == events_code == 0
    assert status["status"] == "succeeded"
    assert status["actual_policy"] == {"model": "gpt-5", "provider": "openai"}
    assert status["usage"] == {"input_tokens": 4, "output_tokens": 2}
    assert events["events"][-1]["event_type"] == "run.completed"
    assert events["next_seq"] == events["events"][-1]["seq"]


def test_capabilities_report_fail_closed_availability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code, payload = _invoke(
        monkeypatch,
        ScriptedFakeHermesAdapter(),
        "capabilities",
        {"endpoint": _endpoint()},
    )
    assert code == 0
    assert payload["durable_available"] is True
    assert payload["durable_blockers"] == []


def test_unknown_fields_are_rejected_without_calling_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def _factory(_endpoint):
        nonlocal called
        called = True
        return ScriptedFakeHermesAdapter()

    stdout = io.StringIO()
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"endpoint": _endpoint(), "surprise": True})),
    )
    monkeypatch.setattr(sys, "stdout", stdout)

    code = main(["capabilities"], adapter_factory=_factory)
    payload = json.loads(stdout.getvalue())
    assert code == 2
    assert payload["error"]["code"] == "run_invalid_request"
    assert called is False
    assert "must-never-be-echoed" not in stdout.getvalue()


def test_upstream_error_message_cannot_echo_prompt_or_bearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt = "private investment thesis"
    bearer = "must-never-be-echoed"

    class EchoingFailureAdapter(ScriptedFakeHermesAdapter):
        def submit_or_get(self, *, idempotency_key, request_body):
            raise HermesRunError(
                "transport_error",
                f"upstream echoed prompt={request_body['input']} bearer={bearer}",
            )

    stderr = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stderr)
    code, payload = _invoke(
        monkeypatch,
        EchoingFailureAdapter(),
        "submit",
        {
            "endpoint": _endpoint(),
            "idempotency_key": "owner:session:secret-error",
            "request_body": {"input": prompt, "session_id": "web_secret"},
        },
    )

    rendered = json.dumps(payload) + stderr.getvalue()
    assert code == 1
    assert payload == {
        "error": {
            "code": "transport_error",
            "message": "Hermes durable Run transport is unavailable",
            "retryable": True,
        }
    }
    assert prompt not in rendered
    assert bearer not in rendered


def test_unreviewed_upstream_error_code_is_not_forwarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnreviewedFailureAdapter(ScriptedFakeHermesAdapter):
        def get_status(self, run_id):
            raise HermesRunError(
                "private-investment-thesis",
                "bearer must-never-be-echoed",
            )

    code, payload = _invoke(
        monkeypatch,
        UnreviewedFailureAdapter(),
        "status",
        {"endpoint": _endpoint(), "run_id": "run-secret"},
    )

    assert code == 2
    assert payload == {
        "error": {
            "code": "run_upstream_error",
            "message": "Hermes durable Run request failed",
            "retryable": False,
        }
    }

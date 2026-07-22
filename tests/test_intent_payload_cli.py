from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from hqa.intent_payload_cli import main
from hqa.intent_payload_crypto import DeterministicCryptoFake
from hqa.intent_payloads import IntentPayloadStore


def _request(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "2.0",
        "kind": "conversation_turn",
        "owner_id": "owner-local-root",
        "workspace_id": "workspace:ws-local-main",
        "session_id": "session:managed-1",
        "client_intent_id": "intent-cli-0001",
        "provider_policy": {
            "primary": {"provider": "openai", "model": "gpt-5"},
            "fallbacks": [],
        },
        "prompt": "Reply with exactly: L2a-pong",
        "ttl_days": 7,
    }
    value.update(overrides)
    return value


@pytest.fixture
def store(tmp_path: Path) -> IntentPayloadStore:
    crypto = DeterministicCryptoFake(key=b"intent payload cli test key".ljust(32, b"!"))
    return IntentPayloadStore(tmp_path / "payloads", crypto=crypto)


def _run(
    store: IntentPayloadStore,
    command: str,
    body: dict[str, object],
    *,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[int, dict[str, object]]:
    monkeypatch.setattr(
        "sys.stdin",
        io.TextIOWrapper(io.BytesIO(json.dumps(body).encode("utf-8")), encoding="utf-8"),
    )
    buffer = io.StringIO()
    monkeypatch.setattr("sys.stdout", buffer)
    code = main([command], store_factory=lambda: store)
    raw = buffer.getvalue().strip()
    assert raw, "cli must emit one JSON line"
    document = json.loads(raw)
    assert "\n" not in buffer.getvalue().rstrip("\n") or buffer.getvalue().count("\n") == 1
    return code, document


def test_put_returns_metadata_without_prompt(
    store: IntentPayloadStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, document = _run(store, "put", _request(), monkeypatch=monkeypatch)
    assert code == 0
    assert document["ok"] is True
    assert document["payload_digest"]
    assert document["payload_ref"] == "payload:sha256:" + document["payload_digest"]
    assert document["client_intent_id"] == "intent-cli-0001"
    assert "prompt" not in document
    assert document["provider_policy_digest"] == (
        "be9265ec683224ba28643b01938dba87d2642944f3a0516ccb9ff0126f872e31"
    )


def test_put_is_idempotent_for_same_client_intent(
    store: IntentPayloadStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    code1, first = _run(store, "put", _request(), monkeypatch=monkeypatch)
    code2, second = _run(store, "put", _request(), monkeypatch=monkeypatch)
    assert code1 == code2 == 0
    assert first["payload_digest"] == second["payload_digest"]


def test_put_conflict_on_same_client_different_body(
    store: IntentPayloadStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _run(store, "put", _request(), monkeypatch=monkeypatch)
    code, document = _run(
        store,
        "put",
        _request(prompt="different prompt body"),
        monkeypatch=monkeypatch,
    )
    assert code == 2
    assert document["error"]["code"] == "intent_idempotency_conflict"
    assert document["error"]["retryable"] is False


def test_bind_resolve_returns_prompt_once_bound(
    store: IntentPayloadStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, put_receipt = _run(store, "put", _request(), monkeypatch=monkeypatch)
    code, document = _run(
        store,
        "bind_resolve",
        {
            "payload_ref": put_receipt["payload_ref"],
            "owner_id": "owner-local-root",
            "workspace_id": "workspace:ws-local-main",
            "session_id": "session:managed-1",
            "consumer_ref": "command:cmd-l2a-1",
        },
        monkeypatch=monkeypatch,
    )
    assert code == 0
    assert document["ok"] is True
    assert document["prompt"] == "Reply with exactly: L2a-pong"
    assert document["consumer_ref"] == "command:cmd-l2a-1"

    # Idempotent re-bind with same consumer.
    code2, again = _run(
        store,
        "bind_resolve",
        {
            "payload_ref": put_receipt["payload_ref"],
            "owner_id": "owner-local-root",
            "workspace_id": "workspace:ws-local-main",
            "session_id": "session:managed-1",
            "consumer_ref": "command:cmd-l2a-1",
        },
        monkeypatch=monkeypatch,
    )
    assert code2 == 0
    assert again["prompt"] == "Reply with exactly: L2a-pong"


def test_bind_resolve_consumer_conflict(
    store: IntentPayloadStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, put_receipt = _run(store, "put", _request(), monkeypatch=monkeypatch)
    _run(
        store,
        "bind_resolve",
        {
            "payload_ref": put_receipt["payload_ref"],
            "owner_id": "owner-local-root",
            "workspace_id": "workspace:ws-local-main",
            "session_id": "session:managed-1",
            "consumer_ref": "command:cmd-a",
        },
        monkeypatch=monkeypatch,
    )
    code, document = _run(
        store,
        "bind_resolve",
        {
            "payload_ref": put_receipt["payload_ref"],
            "owner_id": "owner-local-root",
            "workspace_id": "workspace:ws-local-main",
            "session_id": "session:managed-1",
            "consumer_ref": "command:cmd-b",
        },
        monkeypatch=monkeypatch,
    )
    assert code == 2
    assert document["error"]["code"] == "intent_consumer_conflict"


def test_invalid_command(store: IntentPayloadStore, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(b"{}"), encoding="utf-8"))
    buffer = io.StringIO()
    monkeypatch.setattr("sys.stdout", buffer)
    code = main(["nope"], store_factory=lambda: store)
    assert code == 2
    assert json.loads(buffer.getvalue())["error"]["code"] == "intent_invalid_arguments"


def test_bind_resolve_rejects_unknown_fields(
    store: IntentPayloadStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, put_receipt = _run(store, "put", _request(), monkeypatch=monkeypatch)
    code, document = _run(
        store,
        "bind_resolve",
        {
            "payload_ref": put_receipt["payload_ref"],
            "owner_id": "owner-local-root",
            "workspace_id": "workspace:ws-local-main",
            "session_id": "session:managed-1",
            "consumer_ref": "command:cmd-x",
            "extra": "nope",
        },
        monkeypatch=monkeypatch,
    )
    assert code == 2
    assert document["error"]["code"] == "intent_invalid_request"

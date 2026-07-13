from __future__ import annotations

import json

import pytest

from hqa.hermes_capabilities import (
    CapabilityContractError,
    evaluate_chat_gate,
    load_capabilities,
)


def _document() -> dict:
    return {
        "schema_version": "1.0",
        "observed_at": "2026-07-13T09:13:45Z",
        "hermes_version": "0.18.2",
        "upstream_commit": "b03c94db",
        "source_checkout_commit": "4281151ae859241351ba14d8c7682dc67ff4c126",
        "server_source_sha256": "2a05d8979ee3e4edb0e534f4db1c421d2064f36c8290234c3cf1496365ba7d17",
        "transport": "websocket_jsonrpc",
        "endpoint": "ws://127.0.0.1:9119/api/ws",
        "loopback_only": True,
        "relevant_methods_observed": [
            "approval.respond",
            "config.set",
            "prompt.submit",
            "session.create",
            "session.history",
            "session.interrupt",
            "session.list",
            "session.resume",
            "session.status",
        ],
        "evidence": {
            "session_provider_override": True,
            "session_primary_provider_policy_immutable": False,
            "session_provider_fallback_policy_immutable": False,
            "client_idempotency_key": False,
            "request_correlation_metadata": False,
            "request_lookup_by_client_id": False,
            "run_id": False,
            "event_id": False,
            "event_cursor": False,
            "run_provider_evidence": False,
            "approval_command_digest_binding": False,
            "approval_ttl": False,
            "approval_single_use": False,
            "stop_idempotent": False,
            "stop_reconcilable": False,
        },
    }


def test_known_gateway_is_readable_but_all_chat_mutations_fail_closed(tmp_path) -> None:
    path = tmp_path / "capabilities.json"
    path.write_text(json.dumps(_document()), encoding="utf-8")

    gate = evaluate_chat_gate(load_capabilities(path))

    assert gate.chat_read_enabled is True
    assert gate.chat_write_enabled is False
    assert gate.stream_enabled is False
    assert gate.resume_enabled is False
    assert gate.approval_enabled is False
    assert gate.approval_blockers == (
        "missing_chat_contract",
        "missing_approval_binding",
    )
    assert gate.stop_enabled is False
    assert gate.stop_blockers == (
        "missing_run_identity",
        "missing_stop_contract",
    )
    assert gate.blockers == (
        "missing_request_recovery",
        "missing_run_identity",
        "missing_provider_policy_lock",
        "missing_actual_provider_evidence",
        "missing_event_replay",
    )


def test_complete_contract_opens_each_capability_independently(tmp_path) -> None:
    document = _document()
    document["evidence"] = {key: True for key in document["evidence"]}
    path = tmp_path / "capabilities.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    gate = evaluate_chat_gate(load_capabilities(path))

    assert gate.chat_write_enabled is True
    assert gate.stream_enabled is True
    assert gate.resume_enabled is True
    assert gate.approval_enabled is True
    assert gate.stop_enabled is True
    assert gate.blockers == ()


def test_resume_is_never_classified_as_a_read(tmp_path) -> None:
    document = _document()
    document["relevant_methods_observed"].remove("session.resume")
    path = tmp_path / "capabilities.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    gate = evaluate_chat_gate(load_capabilities(path))

    assert gate.chat_read_enabled is True
    assert gate.resume_enabled is False
    assert "missing_resume_method" in gate.resume_blockers


def test_event_replay_is_required_for_stream_and_resume(tmp_path) -> None:
    document = _document()
    document["evidence"] = {key: True for key in document["evidence"]}
    document["evidence"]["event_cursor"] = False
    path = tmp_path / "capabilities.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    gate = evaluate_chat_gate(load_capabilities(path))

    assert gate.chat_write_enabled is True
    assert gate.stream_enabled is False
    assert gate.resume_enabled is False
    assert gate.blockers == ("missing_event_replay",)


def test_primary_and_fallback_provider_policies_must_both_be_immutable(
    tmp_path,
) -> None:
    document = _document()
    document["evidence"] = {key: True for key in document["evidence"]}
    document["evidence"]["session_primary_provider_policy_immutable"] = False
    path = tmp_path / "capabilities.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    gate = evaluate_chat_gate(load_capabilities(path))

    assert gate.chat_write_enabled is False
    assert "missing_provider_policy_lock" in gate.blockers


def test_missing_chat_method_is_an_explicit_fail_closed_blocker(tmp_path) -> None:
    document = _document()
    document["evidence"] = {key: True for key in document["evidence"]}
    document["relevant_methods_observed"].remove("prompt.submit")
    path = tmp_path / "capabilities.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    gate = evaluate_chat_gate(load_capabilities(path))

    assert gate.chat_write_enabled is False
    assert gate.blockers == ("missing_chat_methods",)


def test_safe_chat_does_not_open_approval_or_stop_from_method_names(tmp_path) -> None:
    document = _document()
    document["evidence"] = {key: True for key in document["evidence"]}
    for key in (
        "approval_command_digest_binding",
        "approval_ttl",
        "approval_single_use",
        "stop_idempotent",
        "stop_reconcilable",
    ):
        document["evidence"][key] = False
    path = tmp_path / "capabilities.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    gate = evaluate_chat_gate(load_capabilities(path))

    assert gate.chat_write_enabled is True
    assert gate.stream_enabled is True
    assert gate.approval_enabled is False
    assert gate.approval_blockers == ("missing_approval_binding",)
    assert gate.stop_enabled is False
    assert gate.stop_blockers == ("missing_stop_contract",)


@pytest.mark.parametrize(
    "recovery_field",
    [
        "client_idempotency_key",
        "request_correlation_metadata",
        "request_lookup_by_client_id",
    ],
)
def test_any_one_deterministic_recovery_contract_is_sufficient(
    tmp_path, recovery_field
) -> None:
    document = _document()
    document["evidence"] = {key: True for key in document["evidence"]}
    for key in (
        "client_idempotency_key",
        "request_correlation_metadata",
        "request_lookup_by_client_id",
    ):
        document["evidence"][key] = key == recovery_field
    path = tmp_path / "capabilities.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    assert evaluate_chat_gate(load_capabilities(path)).chat_write_enabled is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "2.0"),
        ("transport", "rest"),
        ("endpoint", "ws://0.0.0.0:9119/api/ws"),
        ("endpoint", "ws://localhost:9119/api/ws"),
        ("endpoint", "ws://127.0.0.1:9119/other"),
        ("endpoint", "ws://127.0.0.1:9119/api/ws?token=secret#fragment"),
        ("endpoint", "ws://user:pass@127.0.0.1:9119/api/ws"),
        ("endpoint", "ws://127.0.0.1:99999/api/ws"),
        ("loopback_only", False),
    ],
)
def test_unsafe_or_unknown_contract_is_rejected(tmp_path, field, value) -> None:
    document = _document()
    document[field] = value
    path = tmp_path / "capabilities.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(CapabilityContractError):
        load_capabilities(path)

    # Error text must never reflect an endpoint that may contain credentials.
    try:
        load_capabilities(path)
    except CapabilityContractError as exc:
        assert "secret" not in str(exc)
        assert "pass" not in str(exc)

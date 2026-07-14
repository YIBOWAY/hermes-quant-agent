from __future__ import annotations

from typing import Any, Mapping, Optional

import pytest

from hqa.hermes_capabilities import HermesChatGate
from hqa.hermes_read_bridge import BridgeGateError, HermesReadBridge


def _gate(*, read: bool = True, write: bool = False) -> HermesChatGate:
    return HermesChatGate(
        chat_read_enabled=read,
        chat_write_enabled=write,
        stream_enabled=False,
        resume_enabled=False,
        approval_enabled=False,
        stop_enabled=False,
        blockers=() if write else ("missing_request_recovery",),
        resume_blockers=("missing_request_recovery",),
        approval_blockers=("missing_approval_binding",),
        stop_blockers=("missing_stop_contract",),
    )


class _FakeTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Optional[Mapping[str, Any]]]] = []

    def request(
        self, method: str, params: Optional[Mapping[str, Any]] = None
    ) -> Mapping[str, Any]:
        self.calls.append((method, params))
        return {"ok": True, "method": method, "params": dict(params or {})}


def test_construction_requires_chat_read_enabled() -> None:
    with pytest.raises(BridgeGateError) as exc:
        HermesReadBridge(gate=_gate(read=False), transport=_FakeTransport())
    assert exc.value.code == "chat_read_disabled"


def test_write_open_gate_still_only_exposes_reads() -> None:
    """Even if a future write gate opens, this type never gains mutation methods."""
    transport = _FakeTransport()
    bridge = HermesReadBridge(
        gate=_gate(read=True, write=True), transport=transport
    )
    assert bridge.list_sessions()["method"] == "session.list"
    assert not hasattr(bridge, "submit_prompt")
    with pytest.raises(BridgeGateError) as exc:
        bridge._call("session.create", {})  # noqa: SLF001
    assert exc.value.code == "mutation_forbidden"


def test_read_methods_delegate_to_transport() -> None:
    transport = _FakeTransport()
    bridge = HermesReadBridge(gate=_gate(read=True, write=False), transport=transport)

    assert bridge.list_sessions(limit=10)["method"] == "session.list"
    assert bridge.session_status("abc")["method"] == "session.status"
    assert bridge.session_history("abc")["method"] == "session.history"
    assert [c[0] for c in transport.calls] == [
        "session.list",
        "session.status",
        "session.history",
    ]


def test_empty_session_id_rejected_without_transport_call() -> None:
    transport = _FakeTransport()
    bridge = HermesReadBridge(gate=_gate(), transport=transport)
    with pytest.raises(BridgeGateError) as exc:
        bridge.session_status("  ")
    assert exc.value.code == "invalid_session_id"
    assert transport.calls == []


def test_forbidden_methods_are_not_exposed() -> None:
    bridge = HermesReadBridge(gate=_gate(), transport=_FakeTransport())
    assert not hasattr(bridge, "create_session")
    assert not hasattr(bridge, "submit_prompt")
    assert not hasattr(bridge, "session_create")
    assert not hasattr(bridge, "prompt_submit")
    with pytest.raises(BridgeGateError) as exc:
        bridge._call("prompt.submit", {"session_id": "x", "text": "no"})  # noqa: SLF001
    assert exc.value.code == "mutation_forbidden"

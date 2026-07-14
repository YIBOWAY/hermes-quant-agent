from __future__ import annotations

import base64
import hashlib
import json
import socket
import struct
import threading
from typing import Any, Mapping, Optional

import pytest

from hqa.hermes_capabilities import HermesChatGate
from hqa.hermes_read_bridge import (
    BridgeGateError,
    BridgeTransportError,
    HermesReadBridge,
    LoopbackJsonRpcWsTransport,
    assert_loopback_ws_endpoint,
    gate_from_mapping,
    open_read_bridge,
)
from hqa import hermes_read_bridge_cli


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


@pytest.mark.parametrize(
    "endpoint",
    [
        "ws://0.0.0.0:9119/api/ws",
        "ws://localhost:9119/api/ws",
        "ws://8.8.8.8:9119/api/ws",
        "http://127.0.0.1:9119/api/ws",
        "ws://127.0.0.1:9119/other",
        "ws://127.0.0.1:9119/api/ws?token=x",
        "ws://user:pass@127.0.0.1:9119/api/ws",
        "ws://127.0.0.1/api/ws",
        "",
    ],
)
def test_loopback_endpoint_guard_rejects_unsafe_urls(endpoint: str) -> None:
    with pytest.raises(BridgeTransportError) as exc:
        assert_loopback_ws_endpoint(endpoint)
    assert exc.value.code in {"invalid_endpoint", "non_loopback_endpoint"}
    with pytest.raises(BridgeTransportError):
        LoopbackJsonRpcWsTransport(endpoint=endpoint)


def test_loopback_endpoint_accepts_contract_shape() -> None:
    parsed = assert_loopback_ws_endpoint("ws://127.0.0.1:9119/api/ws")
    assert parsed.hostname == "127.0.0.1"
    assert parsed.port == 9119
    assert parsed.path == "/api/ws"


def test_loopback_transport_refuses_mutations_without_connect() -> None:
    transport = LoopbackJsonRpcWsTransport(endpoint="ws://127.0.0.1:9119/api/ws")
    with pytest.raises(BridgeGateError) as exc:
        transport.request("prompt.submit", {"session_id": "x", "text": "no"})
    assert exc.value.code == "mutation_forbidden"
    with pytest.raises(BridgeGateError) as exc2:
        transport.request("session.create", {})
    assert exc2.value.code == "mutation_forbidden"


def test_loopback_transport_rejects_empty_or_smuggled_session_token() -> None:
    with pytest.raises(BridgeTransportError) as empty:
        LoopbackJsonRpcWsTransport(
            endpoint="ws://127.0.0.1:9119/api/ws",
            session_token="   ",
        )
    assert empty.value.code == "invalid_session_token"
    with pytest.raises(BridgeTransportError) as smuggle:
        LoopbackJsonRpcWsTransport(
            endpoint="ws://127.0.0.1:9119/api/ws",
            session_token="abc&other=1",
        )
    assert smuggle.value.code == "invalid_session_token"


def test_open_read_bridge_accepts_session_token_without_claiming_chat_ready() -> None:
    bridge = open_read_bridge(
        gate=_gate(read=True),
        endpoint="ws://127.0.0.1:9119/api/ws",
        session_token="unit-test-token",
    )
    assert isinstance(bridge.transport, LoopbackJsonRpcWsTransport)
    assert bridge.transport._session_token == "unit-test-token"
    assert bridge.gate.chat_write_enabled is False


_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _recv_exact(conn: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("closed")
        buf.extend(chunk)
    return bytes(buf)


def _read_http_headers(conn: socket.socket) -> bytes:
    buf = bytearray()
    while b"\r\n\r\n" not in buf:
        chunk = conn.recv(4096)
        if not chunk:
            break
        buf.extend(chunk)
    return bytes(buf)


def _server_recv_text(conn: socket.socket) -> str:
    header = _recv_exact(conn, 2)
    b1, b2 = header[0], header[1]
    opcode = b1 & 0x0F
    assert opcode == 0x1
    masked = (b2 & 0x80) != 0
    length = b2 & 0x7F
    if length == 126:
        length = struct.unpack("!H", _recv_exact(conn, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", _recv_exact(conn, 8))[0]
    mask = _recv_exact(conn, 4) if masked else b""
    payload = _recv_exact(conn, length)
    if masked:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return payload.decode("utf-8")


def _server_send_text(conn: socket.socket, text: str) -> None:
    payload = text.encode("utf-8")
    header = bytearray([0x81])
    length = len(payload)
    if length < 126:
        header.append(length)
    elif length < 65536:
        header.append(126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(127)
        header.extend(struct.pack("!Q", length))
    conn.sendall(bytes(header) + payload)


def _start_fake_hermes_ws(handler) -> tuple[str, threading.Thread, socket.socket]:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    endpoint = f"ws://127.0.0.1:{port}/api/ws"

    def _run() -> None:
        conn, _addr = server.accept()
        try:
            raw = _read_http_headers(conn)
            text = raw.decode("iso-8859-1", errors="replace")
            key = ""
            for line in text.split("\r\n"):
                if line.lower().startswith("sec-websocket-key:"):
                    key = line.split(":", 1)[1].strip()
            accept = base64.b64encode(
                hashlib.sha1((key + _WS_GUID).encode("ascii")).digest()
            ).decode("ascii")
            response = (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n"
                "\r\n"
            )
            conn.sendall(response.encode("ascii"))
            # Mirror Hermes: optional gateway.ready event before responses.
            _server_send_text(
                conn,
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "event",
                        "params": {"type": "gateway.ready", "payload": {}},
                    }
                ),
            )
            req_raw = _server_recv_text(conn)
            req = json.loads(req_raw)
            resp = handler(req)
            _server_send_text(conn, json.dumps(resp))
        finally:
            try:
                conn.close()
            except OSError:
                pass
            try:
                server.close()
            except OSError:
                pass

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return endpoint, thread, server


def test_loopback_ws_roundtrip_session_list() -> None:
    def handler(req: dict) -> dict:
        assert req["method"] == "session.list"
        assert req["params"]["limit"] == 5
        return {
            "jsonrpc": "2.0",
            "id": req["id"],
            "result": {"sessions": [{"id": "s1", "title": "demo"}]},
        }

    endpoint, thread, _server = _start_fake_hermes_ws(handler)
    try:
        transport = LoopbackJsonRpcWsTransport(endpoint=endpoint, timeout_s=2.0)
        result = transport.request("session.list", {"limit": 5})
        assert result == {"sessions": [{"id": "s1", "title": "demo"}]}
    finally:
        thread.join(timeout=2)

    endpoint2, thread2, _server2 = _start_fake_hermes_ws(handler)
    try:
        bridge = open_read_bridge(
            gate=_gate(read=True), endpoint=endpoint2, timeout_s=2.0
        )
        listed = bridge.list_sessions(limit=5)
        assert listed["sessions"][0]["id"] == "s1"
    finally:
        thread2.join(timeout=2)


def test_gate_from_mapping_and_open_bridge() -> None:
    gate = gate_from_mapping(
        {
            "chat_read_enabled": True,
            "chat_write_enabled": False,
            "stream_enabled": False,
            "resume_enabled": False,
            "approval_enabled": False,
            "stop_enabled": False,
            "blockers": ["missing_request_recovery"],
            "resume_blockers": ["missing_request_recovery"],
            "approval_blockers": ["missing_approval_binding"],
            "stop_blockers": ["missing_stop_contract"],
        }
    )
    assert gate.chat_read_enabled is True
    assert gate.chat_write_enabled is False


def _cli_document(*, read: bool = True, write: bool = False) -> dict:
    return {
        "contract": {
            "endpoint": "ws://127.0.0.1:9119/api/ws",
            "hermes_version": "0.18.2",
        },
        "gate": {
            "chat_read_enabled": read,
            "chat_write_enabled": write,
            "stream_enabled": False,
            "resume_enabled": False,
            "approval_enabled": False,
            "stop_enabled": False,
            "blockers": [] if write else ["missing_request_recovery"],
            "resume_blockers": ["missing_request_recovery"],
            "approval_blockers": ["missing_approval_binding"],
            "stop_blockers": ["missing_stop_contract"],
        },
    }


def test_cli_list_sessions_with_fake_transport(capsys) -> None:
    transport = _FakeTransport()
    code = hermes_read_bridge_cli.main(
        ["list-sessions", "--limit", "3"],
        transport=transport,
        document=_cli_document(read=True, write=False),
    )
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "ok"
    assert out["command"] == "list-sessions"
    assert out["result"]["method"] == "session.list"
    assert out["result"]["params"]["limit"] == 3
    assert out["chat_ready"] is False
    assert out["chat_write_enabled"] is False
    assert out["meta"]["chat_read_enabled"] is True


def test_cli_session_status_and_history(capsys) -> None:
    transport = _FakeTransport()
    assert (
        hermes_read_bridge_cli.main(
            ["session-status", "--session-id", "abc"],
            transport=transport,
            document=_cli_document(),
        )
        == 0
    )
    assert (
        hermes_read_bridge_cli.main(
            ["session-history", "--session-id", "abc"],
            transport=transport,
            document=_cli_document(),
        )
        == 0
    )
    assert [c[0] for c in transport.calls] == ["session.status", "session.history"]
    lines = capsys.readouterr().out.strip().splitlines()
    assert all(json.loads(line)["chat_ready"] is False for line in lines)


def test_cli_refuses_when_chat_read_disabled(capsys) -> None:
    transport = _FakeTransport()
    code = hermes_read_bridge_cli.main(
        ["list-sessions"],
        transport=transport,
        document=_cli_document(read=False),
    )
    assert code == 3
    out = json.loads(capsys.readouterr().out)
    assert out["error"]["code"] == "chat_read_disabled"
    assert transport.calls == []


def test_cli_refuses_mutation_aliases(capsys) -> None:
    code = hermes_read_bridge_cli.main(
        ["prompt-submit"],
        transport=_FakeTransport(),
        document=_cli_document(),
    )
    assert code == 3
    out = json.loads(capsys.readouterr().out)
    assert out["error"]["code"] == "mutation_forbidden"
    assert out["chat_ready"] is False


def test_cli_invalid_args(capsys) -> None:
    code = hermes_read_bridge_cli.main(["session-status"], document=_cli_document())
    assert code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["error"]["code"] == "invalid_arguments"

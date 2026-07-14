"""Fail-closed read-only Hermes gateway surface for Wave 2 bridge.

This module never opens write/mutation methods. Callers inject a JSON-RPC
transport; unit tests use hermetic fakes. The live path uses a loopback-only
WebSocket JSON-RPC client. Live ``prompt.submit`` / ``session.create`` must
not be exercised from tests.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import struct
import time
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Protocol
from urllib.parse import urlparse

from hqa.hermes_capabilities import HermesChatGate


class BridgeGateError(RuntimeError):
    """Raised when a bridge call is refused by the capability gate."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class BridgeTransportError(BridgeGateError):
    """Raised when the JSON-RPC/WebSocket transport fails closed."""


class JsonRpcTransport(Protocol):
    """Minimal JSON-RPC request surface. Implementations own auth/loopback."""

    def request(
        self, method: str, params: Optional[Mapping[str, Any]] = None
    ) -> Mapping[str, Any]:
        ...


_READ_METHODS = frozenset({"session.list", "session.status", "session.history"})
_FORBIDDEN_METHODS = frozenset(
    {
        "session.create",
        "session.resume",
        "session.interrupt",
        "prompt.submit",
        "prompt.background",
        "approval.respond",
        "config.set",
    }
)

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_DEFAULT_TIMEOUT_S = 10.0
_MAX_FRAME_BYTES = 16 * 1024 * 1024


def assert_loopback_ws_endpoint(endpoint: str) -> Any:
    """Parse and validate a loopback Hermes WebSocket endpoint.

    Only ``ws://`` / ``wss://`` against ``127.0.0.1`` or ``::1`` with path
    ``/api/ws`` and an explicit port are accepted. Hostnames such as
    ``localhost`` and non-loopback addresses fail closed.
    """
    if not isinstance(endpoint, str) or not endpoint.strip():
        raise BridgeTransportError(
            "invalid_endpoint",
            "Hermes endpoint must be a non-empty loopback WebSocket URL",
        )
    try:
        parsed = urlparse(endpoint.strip())
        port = parsed.port
    except ValueError as exc:
        raise BridgeTransportError(
            "invalid_endpoint",
            "Hermes endpoint must be a loopback WebSocket URL",
        ) from exc
    if (
        parsed.scheme not in {"ws", "wss"}
        or parsed.hostname not in {"127.0.0.1", "::1"}
        or port is None
        or not 1 <= port <= 65535
        or parsed.path != "/api/ws"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise BridgeTransportError(
            "non_loopback_endpoint",
            "Hermes read transport refuses non-loopback or malformed endpoints",
        )
    return parsed


def gate_from_mapping(raw: Mapping[str, Any]) -> HermesChatGate:
    """Build a :class:`HermesChatGate` from a capability document gate dict."""
    required = (
        "chat_read_enabled",
        "chat_write_enabled",
        "stream_enabled",
        "resume_enabled",
        "approval_enabled",
        "stop_enabled",
        "blockers",
        "resume_blockers",
        "approval_blockers",
        "stop_blockers",
    )
    missing = [key for key in required if key not in raw]
    if missing:
        raise BridgeGateError(
            "invalid_gate",
            f"gate mapping missing fields: {', '.join(missing)}",
        )
    return HermesChatGate(
        chat_read_enabled=raw["chat_read_enabled"] is True,
        chat_write_enabled=raw["chat_write_enabled"] is True,
        stream_enabled=raw["stream_enabled"] is True,
        resume_enabled=raw["resume_enabled"] is True,
        approval_enabled=raw["approval_enabled"] is True,
        stop_enabled=raw["stop_enabled"] is True,
        blockers=tuple(str(item) for item in (raw["blockers"] or ())),
        resume_blockers=tuple(str(item) for item in (raw["resume_blockers"] or ())),
        approval_blockers=tuple(
            str(item) for item in (raw["approval_blockers"] or ())
        ),
        stop_blockers=tuple(str(item) for item in (raw["stop_blockers"] or ())),
    )


def open_read_bridge(
    *,
    gate: HermesChatGate,
    endpoint: str,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> "HermesReadBridge":
    """Construct a read bridge bound to a loopback JSON-RPC WebSocket transport."""
    transport = LoopbackJsonRpcWsTransport(endpoint=endpoint, timeout_s=timeout_s)
    return HermesReadBridge(gate=gate, transport=transport)


@dataclass(frozen=True)
class HermesReadBridge:
    """Read-only session.list / session.status / session.history client.

    Construction requires ``gate.chat_read_enabled is True``. Mutation methods
    are intentionally absent: even if a transport supports them, this type
    cannot invoke them.
    """

    gate: HermesChatGate
    transport: JsonRpcTransport

    def __post_init__(self) -> None:
        if self.gate.chat_read_enabled is not True:
            raise BridgeGateError(
                "chat_read_disabled",
                "Hermes read bridge refuses construction while chat_read_enabled is false",
            )

    def list_sessions(self, *, limit: int = 200) -> Mapping[str, Any]:
        return self._call("session.list", {"limit": int(limit)})

    def session_status(self, session_id: str) -> Mapping[str, Any]:
        sid = str(session_id or "").strip()
        if not sid:
            raise BridgeGateError("invalid_session_id", "session_id is required")
        return self._call("session.status", {"session_id": sid})

    def session_history(self, session_id: str) -> Mapping[str, Any]:
        sid = str(session_id or "").strip()
        if not sid:
            raise BridgeGateError("invalid_session_id", "session_id is required")
        return self._call("session.history", {"session_id": sid})

    def _call(
        self, method: str, params: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        if method in _FORBIDDEN_METHODS:
            raise BridgeGateError(
                "mutation_forbidden",
                f"method {method} is never allowed on HermesReadBridge",
            )
        if method not in _READ_METHODS:
            raise BridgeGateError(
                "method_not_allowlisted",
                f"method {method} is not a read-bridge allowlisted method",
            )
        if self.gate.chat_read_enabled is not True:
            raise BridgeGateError(
                "chat_read_disabled",
                "Hermes read bridge refuses calls while chat_read_enabled is false",
            )
        result = self.transport.request(method, params)
        if not isinstance(result, Mapping):
            raise BridgeGateError(
                "invalid_transport_result",
                "transport must return a mapping result",
            )
        return result


class LoopbackJsonRpcWsTransport:
    """Synchronous loopback-only WebSocket JSON-RPC transport for Hermes reads.

    Public surface is only :meth:`request`. Mutation methods are refused even
    if invoked directly. Non-loopback endpoints fail closed at construction.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        allowlisted_methods: frozenset[str] = _READ_METHODS,
    ) -> None:
        self._parsed = assert_loopback_ws_endpoint(endpoint)
        self.endpoint = endpoint.strip()
        self.timeout_s = float(timeout_s)
        if self.timeout_s <= 0:
            raise BridgeTransportError(
                "invalid_timeout",
                "timeout_s must be positive",
            )
        self.allowlisted_methods = frozenset(allowlisted_methods)
        self._next_id = 1

    def request(
        self, method: str, params: Optional[Mapping[str, Any]] = None
    ) -> Mapping[str, Any]:
        method_name = str(method or "").strip()
        if not method_name:
            raise BridgeTransportError("invalid_method", "method is required")
        if method_name in _FORBIDDEN_METHODS:
            raise BridgeGateError(
                "mutation_forbidden",
                f"method {method_name} is never allowed on LoopbackJsonRpcWsTransport",
            )
        if method_name not in self.allowlisted_methods:
            raise BridgeGateError(
                "method_not_allowlisted",
                f"method {method_name} is not allowlisted for the read transport",
            )
        payload_params: dict[str, Any] = dict(params or {})
        request_id = self._next_id
        self._next_id += 1
        request_obj = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method_name,
            "params": payload_params,
        }
        return self._roundtrip(request_obj, request_id)

    def _roundtrip(
        self, request_obj: Mapping[str, Any], request_id: int
    ) -> Mapping[str, Any]:
        host = self._parsed.hostname
        assert host is not None
        port = self._parsed.port
        assert port is not None
        path = self._parsed.path or "/api/ws"
        deadline = time.monotonic() + self.timeout_s
        sock: Optional[socket.socket] = None
        try:
            sock = self._connect(host, port, deadline)
            self._handshake(sock, host, port, path, deadline)
            self._send_text(sock, json.dumps(request_obj, ensure_ascii=False))
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise BridgeTransportError(
                        "transport_timeout",
                        "timed out waiting for Hermes JSON-RPC response",
                    )
                sock.settimeout(remaining)
                message = self._recv_text_message(sock, deadline)
                try:
                    frame = json.loads(message)
                except json.JSONDecodeError as exc:
                    raise BridgeTransportError(
                        "invalid_json_frame",
                        "Hermes WebSocket frame was not valid JSON",
                    ) from exc
                if not isinstance(frame, dict):
                    continue
                # Notifications (events) have a method and no matching result id.
                if frame.get("id") != request_id:
                    continue
                if "error" in frame:
                    error = frame.get("error")
                    if isinstance(error, Mapping):
                        code = error.get("code", "rpc_error")
                        message_text = error.get("message", "Hermes JSON-RPC error")
                    else:
                        code = "rpc_error"
                        message_text = "Hermes JSON-RPC error"
                    raise BridgeTransportError(
                        f"rpc_error:{code}",
                        str(message_text),
                    )
                result = frame.get("result")
                if not isinstance(result, Mapping):
                    raise BridgeTransportError(
                        "invalid_rpc_result",
                        "Hermes JSON-RPC result must be an object",
                    )
                return result
        except BridgeGateError:
            raise
        except (OSError, socket.timeout, TimeoutError, struct.error) as exc:
            raise BridgeTransportError(
                "transport_io_error",
                f"Hermes WebSocket transport failed: {type(exc).__name__}: {exc}",
            ) from exc
        finally:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass

    def _connect(self, host: str, port: int, deadline: float) -> socket.socket:
        remaining = max(0.001, deadline - time.monotonic())
        # Force loopback family; do not allow DNS rebinding to non-loopback.
        if host == "::1":
            sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            sock.settimeout(remaining)
            sock.connect((host, port))
            return sock
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(remaining)
        sock.connect((host, port))
        return sock

    def _handshake(
        self,
        sock: socket.socket,
        host: str,
        port: int,
        path: str,
        deadline: float,
    ) -> None:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        host_header = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host_header}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        sock.sendall(request.encode("ascii"))
        header_bytes = self._recv_until(sock, b"\r\n\r\n", deadline)
        header_text = header_bytes.decode("iso-8859-1", errors="replace")
        lines = header_text.split("\r\n")
        if not lines or not lines[0].startswith("HTTP/1.1 101"):
            raise BridgeTransportError(
                "websocket_upgrade_failed",
                f"Hermes WebSocket upgrade failed: {lines[0] if lines else 'empty'}",
            )
        headers = {}
        for line in lines[1:]:
            if not line or ":" not in line:
                continue
            name, value = line.split(":", 1)
            headers[name.strip().lower()] = value.strip()
        expected = base64.b64encode(
            hashlib.sha1((key + _WS_GUID).encode("ascii")).digest()
        ).decode("ascii")
        accept = headers.get("sec-websocket-accept", "")
        if accept != expected:
            raise BridgeTransportError(
                "websocket_accept_mismatch",
                "Hermes WebSocket Sec-WebSocket-Accept mismatch",
            )

    def _send_text(self, sock: socket.socket, text: str) -> None:
        payload = text.encode("utf-8")
        header = bytearray()
        header.append(0x81)  # FIN + text
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        mask = os.urandom(4)
        header.extend(mask)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        sock.sendall(bytes(header) + masked)

    def _recv_text_message(self, sock: socket.socket, deadline: float) -> str:
        pieces: list[bytes] = []
        while True:
            opcode, payload, fin = self._recv_frame(sock, deadline)
            if opcode == 0x8:  # close
                raise BridgeTransportError(
                    "websocket_closed",
                    "Hermes WebSocket closed before JSON-RPC response",
                )
            if opcode == 0x9:  # ping -> pong
                self._send_control(sock, 0xA, payload)
                continue
            if opcode == 0xA:  # pong
                continue
            if opcode not in {0x1, 0x0}:
                # Ignore binary / unknown control; fail closed only if we never
                # get a matching RPC response (deadline handles that).
                continue
            pieces.append(payload)
            if fin and opcode == 0x1:
                break
            if fin and opcode == 0x0:
                break
            if opcode == 0x1 and not fin:
                # fragmented text; continue gathering continuation frames
                continue
        data = b"".join(pieces)
        return data.decode("utf-8")

    def _send_control(
        self, sock: socket.socket, opcode: int, payload: bytes
    ) -> None:
        if len(payload) > 125:
            payload = payload[:125]
        header = bytes([0x80 | (opcode & 0x0F), 0x80 | len(payload)])
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        sock.sendall(header + mask + masked)

    def _recv_frame(
        self, sock: socket.socket, deadline: float
    ) -> tuple[int, bytes, bool]:
        header = self._recv_exact(sock, 2, deadline)
        b1, b2 = header[0], header[1]
        fin = (b1 & 0x80) != 0
        opcode = b1 & 0x0F
        masked = (b2 & 0x80) != 0
        length = b2 & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._recv_exact(sock, 2, deadline))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._recv_exact(sock, 8, deadline))[0]
        if length > _MAX_FRAME_BYTES:
            raise BridgeTransportError(
                "frame_too_large",
                "Hermes WebSocket frame exceeds size limit",
            )
        mask_key = self._recv_exact(sock, 4, deadline) if masked else b""
        payload = self._recv_exact(sock, length, deadline)
        if masked:
            payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
        return opcode, payload, fin

    def _recv_until(
        self, sock: socket.socket, marker: bytes, deadline: float
    ) -> bytes:
        buf = bytearray()
        while marker not in buf:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BridgeTransportError(
                    "transport_timeout",
                    "timed out during WebSocket handshake",
                )
            sock.settimeout(remaining)
            chunk = sock.recv(4096)
            if not chunk:
                raise BridgeTransportError(
                    "transport_io_error",
                    "connection closed during WebSocket handshake",
                )
            buf.extend(chunk)
            if len(buf) > 65536:
                raise BridgeTransportError(
                    "websocket_upgrade_failed",
                    "WebSocket handshake response too large",
                )
        return bytes(buf)

    def _recv_exact(
        self, sock: socket.socket, size: int, deadline: float
    ) -> bytes:
        buf = bytearray()
        while len(buf) < size:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BridgeTransportError(
                    "transport_timeout",
                    "timed out reading WebSocket frame",
                )
            sock.settimeout(remaining)
            chunk = sock.recv(size - len(buf))
            if not chunk:
                raise BridgeTransportError(
                    "transport_io_error",
                    "connection closed while reading WebSocket frame",
                )
            buf.extend(chunk)
        return bytes(buf)

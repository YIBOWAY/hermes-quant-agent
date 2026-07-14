"""Fail-closed read-only Hermes gateway surface for Wave 2 bridge scaffold.

This module never opens write/mutation methods. Callers inject a JSON-RPC
transport; unit tests use hermetic fakes. Live ``prompt.submit`` /
``session.create`` must not be exercised from tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Protocol

from hqa.hermes_capabilities import HermesChatGate


class BridgeGateError(RuntimeError):
    """Raised when a bridge call is refused by the capability gate."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


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

    def list_sessions(
        self, *, limit: int = 200
    ) -> Mapping[str, Any]:
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

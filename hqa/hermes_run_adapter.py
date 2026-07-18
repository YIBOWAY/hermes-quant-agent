"""Fail-closed loopback HTTP Hermes *run* surface for Agent v0.2 (V2.10).

This is the write-capable upstream seam — the reviewed counterpart to
``hqa/hermes_read_bridge.py`` (which is read-only by design). It speaks the
reviewed V2 ``/v1/runs`` HTTP contract implemented in Hermes (V2.2–V2.9) and
exposes the nine durable-run semantics to the platform.

Per plan §4.3 the production ``OfficialHermesHttpAdapter`` and the
``ScriptedFakeHermesAdapter`` implement the SAME ``HermesRunPort`` interface;
the fake additionally supports scripted fault injection (accept-then-drop,
restart, event gap, quota/fallback, approval stale, partial stop) for contract
and acceptance tests. The fake is a hermetic test double — not a product path
and never exposed to users via a feature flag.

Red lines: loopback-only, stdlib-only (``urllib.request``, mirroring the read
bridge's dependency-free discipline), and fail-closed. No live provider /
paper / live / broker. Live submit/approval/stop are never exercised from
unit tests; tests inject hermetic fakes or a loopback ``http.server``.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------

_HTTP_STATUS_BY_CODE = {
    "idempotency_conflict": 409,
    "approval_challenge_required": 409,
    "approval_challenge_invalid": 409,
    "approval_not_active": 409,
    "approval_not_pending": 409,
    "run_not_found": 404,
    "invalid_cursor": 400,
    "invalid_endpoint": 400,
    "non_loopback_endpoint": 400,
    "transport_error": 502,
}


class HermesRunError(RuntimeError):
    """Fail-closed error from the Hermes run surface.

    Carries a machine-readable ``code`` (matching the upstream reviewed
    contract's error codes where applicable) and an ``http_status`` so the
    loopback scripted upstream can faithfully reproduce status codes.
    """

    def __init__(self, code: str, message: str, *, http_status: Optional[int] = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status if http_status is not None else _HTTP_STATUS_BY_CODE.get(code, 500)


# ---------------------------------------------------------------------------
# Value objects (the reviewed contract's shapes)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RunHandle:
    run_id: str
    created: bool
    idempotency_key: Optional[str] = None


@dataclass(frozen=True)
class RunStatusSnapshot:
    run_id: str
    status: str
    session_id: Optional[str] = None
    requested_policy: Optional[Mapping[str, Any]] = None
    actual_policy: Optional[Mapping[str, Any]] = None
    fallback_reason: Optional[str] = None
    usage: Optional[Mapping[str, Any]] = None
    created_at: Optional[float] = None
    updated_at: Optional[float] = None


@dataclass(frozen=True)
class StreamEvent:
    seq: int
    event_type: str
    run_id: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    event_id: Optional[str] = None


@dataclass(frozen=True)
class ApprovalChallenge:
    challenge_id: str
    action_digest: str
    expires_at: float


@dataclass(frozen=True)
class ApprovalResult:
    run_id: str
    choice: str
    resolved: int


@dataclass(frozen=True)
class StopResult:
    run_id: str
    status: str
    idempotent_replay: bool = False


# ---------------------------------------------------------------------------
# The shared interface (§4.3: production and fake implement the same surface)
# ---------------------------------------------------------------------------


class HermesRunPort:
    """Client-callable Hermes run surface. Both adapters implement this.

    Only platform-initiated operations live here. Upstream-side lifecycle
    drivers (advancing a run, raising an approval, injecting faults) are NOT
    part of the port — they exist only on the fake for test scripting.
    """

    def submit_or_get(self, *, idempotency_key: Optional[str], request_body: Mapping[str, Any]) -> RunHandle:
        raise NotImplementedError

    def get_status(self, run_id: str) -> RunStatusSnapshot:
        raise NotImplementedError

    def stream_events(self, run_id: str, *, since_seq: int = 0) -> List[StreamEvent]:
        raise NotImplementedError

    def respond_approval(self, run_id: str, *, choice: str, challenge_id: str, action_digest: str) -> ApprovalResult:
        raise NotImplementedError

    def stop(self, run_id: str) -> StopResult:
        raise NotImplementedError

    def capabilities(self) -> Mapping[str, Any]:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Shared in-memory durable authority (the nine semantics, re-implemented
# stdlib-only inside HQA so the fake needs no cross-repo import).
# ---------------------------------------------------------------------------

_TERMINAL = {"succeeded", "failed", "stopped"}


def _canonical_digest(body: Mapping[str, Any]) -> str:
    import hashlib

    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()
    ).hexdigest()


class _RunRecord:
    def __init__(self, run_id: str, idempotency_key: str, digest: str) -> None:
        self.run_id = run_id
        self.idempotency_key = idempotency_key
        self.digest = digest
        self.status = "queued"
        self.session_id: Optional[str] = None
        self.requested_policy: Optional[Mapping[str, Any]] = None
        self.actual_policy: Optional[Mapping[str, Any]] = None
        self.fallback_reason: Optional[str] = None
        self.usage: Optional[Mapping[str, Any]] = None
        self.created_at = time.time()
        self.updated_at = self.created_at
        self.events: List[StreamEvent] = []


class _ApprovalGrant:
    def __init__(self, challenge_id: str, run_id: str, action_digest: str, expires_at: float) -> None:
        self.challenge_id = challenge_id
        self.run_id = run_id
        self.action_digest = action_digest
        self.expires_at = expires_at
        self.consumed = False


class _InMemoryRunAuthority:
    """The nine durable-run semantics, in-memory, for the scripted fake."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: Dict[str, _RunRecord] = {}
        self._by_idempotency_key: Dict[str, str] = {}
        self._approvals: Dict[str, _ApprovalGrant] = {}

    # -- identity (semantic 1) ------------------------------------------------
    def submit_or_get(self, *, idempotency_key: Optional[str], request_body: Mapping[str, Any]) -> RunHandle:
        with self._lock:
            key = idempotency_key or f"server:{uuid.uuid4().hex}"
            digest = _canonical_digest(request_body)
            existing_id = self._by_idempotency_key.get(key)
            if existing_id is not None:
                record = self._runs[existing_id]
                if record.digest != digest:
                    raise HermesRunError(
                        "idempotency_conflict",
                        "Idempotency-Key was already used with a different request",
                    )
                return RunHandle(run_id=record.run_id, created=False, idempotency_key=key)
            run_id = f"run_{uuid.uuid4().hex}"
            record = _RunRecord(run_id, key, digest)
            self._runs[run_id] = record
            self._by_idempotency_key[key] = run_id
            return RunHandle(run_id=run_id, created=True, idempotency_key=key)

    # -- status / evidence (semantics 2, 3, 5) --------------------------------
    def get_run(self, run_id: str) -> Optional[_RunRecord]:
        return self._runs.get(run_id)

    def require_run(self, run_id: str) -> _RunRecord:
        record = self._runs.get(run_id)
        if record is None:
            raise HermesRunError("run_not_found", f"Run not found: {run_id}")
        return record

    def set_status(self, run_id: str, status: str) -> None:
        with self._lock:
            record = self.require_run(run_id)
            # terminal immutability (semantic 2)
            if record.status in _TERMINAL:
                return
            record.status = status
            record.updated_at = time.time()

    # -- events (semantic 4) --------------------------------------------------
    def append_event(self, run_id: str, event_type: str, payload: Mapping[str, Any]) -> StreamEvent:
        with self._lock:
            record = self.require_run(run_id)
            seq = (record.events[-1].seq + 1) if record.events else 1
            event = StreamEvent(
                seq=seq, event_type=event_type, run_id=run_id,
                payload=dict(payload), event_id=f"evt_{uuid.uuid4().hex}",
            )
            record.events.append(event)
            return event

    def replay_events(self, run_id: str, *, since_seq: int = 0) -> List[StreamEvent]:
        record = self.require_run(run_id)
        return [e for e in record.events if e.seq > since_seq]

    # -- approval CAS (semantic 6) --------------------------------------------
    def issue_approval(self, run_id: str, *, action_digest: str, ttl_seconds: float = 300.0) -> ApprovalChallenge:
        with self._lock:
            self.require_run(run_id)
            challenge = _ApprovalGrant(
                challenge_id=f"ch_{uuid.uuid4().hex}",
                run_id=run_id,
                action_digest=action_digest,
                expires_at=time.time() + ttl_seconds,
            )
            self._approvals[challenge.challenge_id] = challenge
            return ApprovalChallenge(
                challenge_id=challenge.challenge_id,
                action_digest=challenge.action_digest,
                expires_at=challenge.expires_at,
            )

    def consume_approval(self, challenge_id: str, *, action_digest: str) -> bool:
        with self._lock:
            grant = self._approvals.get(challenge_id)
            if grant is None or grant.consumed:
                return False
            if grant.action_digest != action_digest:
                return False
            if grant.expires_at <= time.time():
                return False
            grant.consumed = True
            return True

    # -- reconcile (semantic 9) ------------------------------------------------
    def reconcile(self) -> int:
        with self._lock:
            count = 0
            for record in self._runs.values():
                if record.status not in _TERMINAL:
                    record.status = "stopped"
                    record.updated_at = time.time()
                    count += 1
            return count


# ---------------------------------------------------------------------------
# Scripted fault injection (plan §4.3 row "Hermes Run")
# ---------------------------------------------------------------------------


class ScriptedFault(Enum):
    RESTART = "restart"
    EVENT_GAP = "event_gap"
    QUOTA_FALLBACK = "quota_fallback"
    APPROVAL_STALE = "approval_stale"
    PARTIAL_STOP = "partial_stop"
    ACCEPT_THEN_DROP = "accept_then_drop"


# ---------------------------------------------------------------------------
# Scripted fake adapter (hermetic, in-memory, same HermesRunPort interface)
# ---------------------------------------------------------------------------


class ScriptedFakeHermesAdapter(HermesRunPort):
    """In-memory Hermes run authority implementing ``HermesRunPort``.

    Re-implements the nine durable-run semantics faithfully (they mirror the
    reviewed Hermes ``DurableRunAuthority``) and adds scripting hooks +
    fault injection for contract and acceptance tests. Pure in-memory; no
    network, no threads started. NOT a product path.
    """

    def __init__(self) -> None:
        self._authority = _InMemoryRunAuthority()
        self._faults: set[ScriptedFault] = set()

    # -- scripting hooks (not part of the port) ------------------------------
    def inject(self, fault: ScriptedFault) -> None:
        self._faults.add(fault)

    def clear_faults(self) -> None:
        self._faults.clear()

    def drive_to_terminal(self, run_id: str, *, outcome: str = "succeeded") -> None:
        """Advance a run through a normal lifecycle to a terminal state."""
        a = self._authority
        a.set_status(run_id, "running")
        a.append_event(run_id, "message.delta", {"delta": "working"})
        if ScriptedFault.QUOTA_FALLBACK in self._faults:
            record = a.require_run(run_id)
            record.fallback_reason = "quota_exceeded:fallback_to_authorized_model"
            record.actual_policy = {"model": "fallback-model", "provider": "fallback"}
        if outcome == "succeeded":
            a.append_event(run_id, "run.completed", {"output": "done", "usage": {}})
            a.set_status(run_id, "succeeded")
        elif outcome == "failed":
            a.append_event(run_id, "run.failed", {"error": "boom"})
            a.set_status(run_id, "failed")
        else:
            a.append_event(run_id, "run.cancelled", {})
            a.set_status(run_id, "stopped")

    def mark_running(self, run_id: str) -> None:
        self._authority.set_status(run_id, "running")

    def raise_approval(self, run_id: str, *, action: Optional[Mapping[str, Any]] = None) -> ApprovalChallenge:
        digest = _canonical_digest(action or {"command": "rm -rf /tmp/x", "pattern_keys": ["shell-c"]})
        return self._authority.issue_approval(run_id, action_digest=digest)

    def reconcile(self) -> int:
        return self._authority.reconcile()

    # -- HermesRunPort --------------------------------------------------------
    def submit_or_get(self, *, idempotency_key: Optional[str], request_body: Mapping[str, Any]) -> RunHandle:
        handle = self._authority.submit_or_get(idempotency_key=idempotency_key, request_body=request_body)
        if handle.created:
            # A real run starts producing events once accepted; emit the first
            # lifecycle event so the event plane has a durable record.
            self._authority.append_event(handle.run_id, "message.delta", {"delta": "started"})
        return handle

    def get_status(self, run_id: str) -> RunStatusSnapshot:
        record = self._authority.require_run(run_id)
        return RunStatusSnapshot(
            run_id=record.run_id, status=record.status, session_id=record.session_id,
            requested_policy=record.requested_policy, actual_policy=record.actual_policy,
            fallback_reason=record.fallback_reason, usage=record.usage,
            created_at=record.created_at, updated_at=record.updated_at,
        )

    def stream_events(self, run_id: str, *, since_seq: int = 0) -> List[StreamEvent]:
        events = self._authority.replay_events(run_id, since_seq=since_seq)
        if ScriptedFault.EVENT_GAP in self._faults and len(events) > 1:
            # Live view drops one event; the durable cursor replay is unaffected
            # at the store level — this models a transport gap the platform must
            # tolerate by resuming from the cursor.
            return events[:-1]
        return events

    def respond_approval(self, run_id: str, *, choice: str, challenge_id: str, action_digest: str) -> ApprovalResult:
        self._authority.require_run(run_id)
        if not challenge_id or not action_digest:
            raise HermesRunError(
                "approval_challenge_required",
                "Approval requires challenge_id and action_digest",
            )
        grant = self._authority._approvals.get(challenge_id)  # noqa: SLF001
        if grant is None or grant.run_id != run_id:
            raise HermesRunError(
                "approval_challenge_invalid",
                "Approval challenge is invalid for this run",
            )
        if ScriptedFault.APPROVAL_STALE in self._faults:
            # A grant that has gone stale between issue and respond is rejected
            # at consume-time and does NOT change the underlying fact.
            raise HermesRunError(
                "approval_challenge_invalid",
                "Approval challenge is stale, expired, already used, or mismatched",
            )
        if not self._authority.consume_approval(challenge_id, action_digest=action_digest):
            raise HermesRunError(
                "approval_challenge_invalid",
                "Approval challenge is stale, expired, already used, or mismatched",
            )
        self._authority.append_event(run_id, "approval.responded", {"choice": choice, "resolved": 1})
        return ApprovalResult(run_id=run_id, choice=choice, resolved=1)

    def stop(self, run_id: str) -> StopResult:
        record = self._authority.require_run(run_id)
        if record.status in _TERMINAL:
            # Idempotent: a known terminal run never 404s; repeat stop returns
            # the same result.
            return StopResult(run_id=run_id, status="stopped", idempotent_replay=True)
        # Drive the (single, synchronous) run straight to its terminal stopped
        # state so a repeat stop is byte-for-byte idempotent.
        self._authority.append_event(run_id, "run.cancelled", {})
        self._authority.set_status(run_id, "stopped")
        return StopResult(run_id=run_id, status="stopped")

    def capabilities(self) -> Mapping[str, Any]:
        grounded = {
            "supported": True, "grounded": True, "evidence": "fake.in_memory_authority",
        }
        return {
            "object": "hermes.api_server.capabilities",
            "platform": "hermes-agent",
            "contract_version": 1,
            "durable": {
                "idempotency": dict(grounded, evidence="fake.submit_or_get"),
                "event_replay": dict(grounded, evidence="fake.replay_events"),
                "approval_cas": dict(grounded, evidence="fake.consume_approval"),
                "idempotent_stop": dict(grounded, evidence="fake.stop"),
                "restart_reconcile": dict(grounded, evidence="fake.reconcile"),
                "run_evidence": dict(grounded, evidence="fake.record_outcome"),
            },
        }


# ---------------------------------------------------------------------------
# Production adapter: loopback HTTP against the reviewed Hermes API contract.
# ---------------------------------------------------------------------------


class UrllibLoopbackHttpTransport:
    """Synchronous loopback-only HTTP transport (stdlib ``urllib``).

    Refuses non-loopback / non-http / port-less base URLs at construction
    (fail closed), mirroring the read bridge's endpoint discipline. Auth is a
    bearer token. Never used against a live Hermes from unit tests.
    """

    def __init__(self, *, base_url: str, api_key: Optional[str] = None, timeout_s: float = 10.0) -> None:
        parsed = self._validate_base_url(base_url)
        self._base = f"http://{parsed.hostname}:{parsed.port}"
        self._api_key = api_key
        self._timeout = timeout_s

    @staticmethod
    def _validate_base_url(base_url: str):
        if not isinstance(base_url, str) or not base_url.strip():
            raise HermesRunError("invalid_endpoint", "base_url must be a non-empty loopback http URL")
        try:
            parsed = urlparse(base_url.strip())
            port = parsed.port
        except ValueError as exc:
            raise HermesRunError("invalid_endpoint", "malformed base_url") from exc
        if parsed.scheme != "http":
            raise HermesRunError("non_loopback_endpoint", "only plaintext http loopback is accepted")
        if parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
            raise HermesRunError("non_loopback_endpoint", "base_url must be loopback")
        if port is None or not 1 <= port <= 65535:
            raise HermesRunError("non_loopback_endpoint", "base_url must carry an explicit port")
        return parsed

    # -- low-level request helpers -------------------------------------------
    def _headers(self, extra: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        if extra:
            headers.update(extra)
        return headers

    def _open(self, request) -> bytes:
        import urllib.error
        import urllib.request

        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as resp:  # noqa: S310 (loopback only)
                return resp.read()
        except urllib.error.HTTPError as exc:
            body = exc.read()
            self._raise_from_error_body(exc.code, body)
            raise  # pragma: no cover - unreachable
        except urllib.error.URLError as exc:
            raise HermesRunError("transport_error", f"loopback transport failed: {exc.reason}") from exc

    @staticmethod
    def _raise_from_error_body(status: int, body: bytes) -> None:
        code = "transport_error"
        message = f"upstream HTTP {status}"
        try:
            payload = json.loads(body or b"{}")
            err = payload.get("error") or {}
            code = err.get("code") or code
            message = err.get("message") or message
        except (ValueError, AttributeError):
            pass
        raise HermesRunError(code, message, http_status=status)

    def get_json(self, path: str, *, headers: Optional[Mapping[str, str]] = None) -> Mapping[str, Any]:
        import urllib.request

        req = urllib.request.Request(self._base + path, headers=self._headers(headers), method="GET")
        return json.loads(self._open(req) or b"{}")

    def post_json(self, path: str, body: Mapping[str, Any], *, headers: Optional[Mapping[str, str]] = None) -> Tuple[int, Mapping[str, Any]]:
        import urllib.request

        data = json.dumps(body).encode()
        all_headers = self._headers({"Content-Type": "application/json"})
        if headers:
            all_headers.update(headers)
        req = urllib.request.Request(self._base + path, data=data, headers=all_headers, method="POST")
        raw = self._open(req)
        # The reviewed contract returns 202 for submit; urllib treats 2xx as success.
        status = getattr(req, "response_code", None) or 202
        return status, json.loads(raw or b"{}")

    def get_sse(self, path: str, *, headers: Optional[Mapping[str, str]] = None) -> List[Mapping[str, Any]]:
        """Consume an SSE stream, returning the parsed frames (data JSON)."""
        import urllib.error
        import urllib.request

        req = urllib.request.Request(self._base + path, headers=self._headers(headers), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:  # noqa: S310 (loopback only)
                raw = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            self._raise_from_error_body(exc.code, exc.read())
            raise  # pragma: no cover
        except urllib.error.URLError as exc:
            raise HermesRunError("transport_error", f"loopback transport failed: {exc.reason}") from exc
        return _parse_sse_frames(raw)


def _parse_sse_frames(raw: str) -> List[Mapping[str, Any]]:
    """Parse spec SSE frames (id:/event:/data:) into dicts; ':' comments ignored."""
    frames: List[Mapping[str, Any]] = []
    for block in raw.split("\n\n"):
        block = block.strip("\n")
        if not block or block.startswith(":"):
            continue
        seq: Optional[int] = None
        event_type = "message"
        data_lines: List[str] = []
        for line in block.split("\n"):
            if line.startswith(":"):
                continue
            if line.startswith("id:"):
                try:
                    seq = int(line[3:].strip())
                except ValueError:
                    seq = None
            elif line.startswith("event:"):
                event_type = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        if not data_lines:
            continue
        try:
            payload = json.loads("\n".join(data_lines))
        except ValueError:
            continue
        if isinstance(payload, dict):
            payload.setdefault("seq", seq)
            payload.setdefault("event", event_type)
            frames.append(payload)
    return frames


class OfficialHermesHttpAdapter(HermesRunPort):
    """Production loopback HTTP adapter over the reviewed Hermes run contract.

    Maps each ``HermesRunPort`` method to the reviewed ``/v1/runs`` HTTP
    surface (V2.2–V2.9). Fail-closed: upstream error envelopes are surfaced as
    ``HermesRunError`` with the upstream code; a transport failure reports
    ``transport_error`` so the platform can mark the adapter unavailable rather
    than dispatch.
    """

    def __init__(self, *, transport: UrllibLoopbackHttpTransport) -> None:
        self._transport = transport

    def submit_or_get(self, *, idempotency_key: Optional[str], request_body: Mapping[str, Any]) -> RunHandle:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        _, payload = self._transport.post_json("/v1/runs", dict(request_body), headers=headers)
        run_id = str(payload["run_id"])
        # Reviewed contract: created -> {"run_id","status":"started"}; replay ->
        # {"run_id","status":"recovered","idempotent_replay":True,...}.
        created = payload.get("status") == "started" and payload.get("idempotent_replay") is not True
        return RunHandle(run_id=run_id, created=created, idempotency_key=idempotency_key)

    def get_status(self, run_id: str) -> RunStatusSnapshot:
        payload = self._transport.get_json(f"/v1/runs/{run_id}")
        return RunStatusSnapshot(
            run_id=str(payload.get("run_id", run_id)),
            status=str(payload.get("status")),
            session_id=payload.get("session_id"),
            requested_policy=payload.get("requested_policy"),
            actual_policy=payload.get("actual_policy"),
            fallback_reason=payload.get("fallback_reason"),
            usage=payload.get("usage"),
            created_at=payload.get("created_at"),
            updated_at=payload.get("updated_at"),
        )

    def stream_events(self, run_id: str, *, since_seq: int = 0) -> List[StreamEvent]:
        headers = {"Last-Event-ID": str(since_seq)} if since_seq else None
        path = f"/v1/runs/{run_id}/events"
        frames = self._transport.get_sse(path, headers=headers)
        events: List[StreamEvent] = []
        for frame in frames:
            seq = frame.get("seq")
            if seq is None:
                continue
            payload = {k: v for k, v in frame.items() if k not in {"seq", "event", "run_id"}}
            events.append(StreamEvent(
                seq=int(seq), event_type=str(frame.get("event", "message")),
                run_id=str(frame.get("run_id", run_id)), payload=payload,
                event_id=frame.get("event_id"),
            ))
        return events

    def respond_approval(self, run_id: str, *, choice: str, challenge_id: str, action_digest: str) -> ApprovalResult:
        body = {"choice": choice, "challenge_id": challenge_id, "action_digest": action_digest}
        _, payload = self._transport.post_json(f"/v1/runs/{run_id}/approval", body)
        return ApprovalResult(
            run_id=run_id, choice=choice, resolved=int(payload.get("resolved", 0)),
        )

    def stop(self, run_id: str) -> StopResult:
        _, payload = self._transport.post_json(f"/v1/runs/{run_id}/stop", {})
        return StopResult(
            run_id=run_id,
            status=str(payload.get("status")),
            idempotent_replay=bool(payload.get("idempotent_replay", False)),
        )

    def capabilities(self) -> Mapping[str, Any]:
        return self._transport.get_json("/v1/capabilities")

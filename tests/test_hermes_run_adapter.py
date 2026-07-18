"""V2.10 — OfficialHermesHttpAdapter + same-interface scripted fake.

Plan §4.3 (docs/superpowers/plans/2026-07-16-agent-v0-2-full-hermes-web-chat.md):
the production ``OfficialHermesHttpAdapter`` and the scripted fake must implement
the SAME ``HermesRunPort`` interface, and the fake must support scripted fault
injection (accept-then-drop, restart, event gap, quota/fallback, approval
stale, partial stop). This suite runs the shared durable-run contract over BOTH
adapters (parametrized) to prove behavioral equivalence, plus targeted tests
for the fake's lifecycle drivers / fault modes and the HTTP transport layer.

Red line: hermetic only. The fake is pure in-memory; the HTTP adapter is
tested against a loopback ``http.server`` (127.0.0.1, ephemeral port) serving
the same reviewed contract. No live Hermes, no external network.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

import pytest

from hqa.hermes_run_adapter import (
    ApprovalChallenge,
    DURABLE_CAPABILITY_KEYS,
    DurableRunAvailability,
    HermesRunError,
    HermesRunPort,
    OfficialHermesHttpAdapter,
    RunHandle,
    RunStatusSnapshot,
    ScriptedFault,
    ScriptedFakeHermesAdapter,
    StopResult,
    StreamEvent,
    UrllibLoopbackHttpTransport,
    evaluate_durable_run_availability,
)

_BODY = {"input": "hello"}
_KEY = "idem-key-1"


# ---------------------------------------------------------------------------
# Shared-interface conformance: one suite, run over BOTH implementations (§4.3).
# Only HermesRunPort methods are exercised here (client-callable surface).
# Upstream-side drivers (drive_to_terminal / raise_approval / inject) are
# fake-only and tested separately below.
# ---------------------------------------------------------------------------


@pytest.fixture(params=["fake", "http"])
def adapter(request):
    if request.param == "fake":
        yield ScriptedFakeHermesAdapter()
        return
    server = _ScriptedUpstreamServer()
    server.start()
    try:
        yield OfficialHermesHttpAdapter(
            transport=UrllibLoopbackHttpTransport(
                base_url=server.base_url, api_key="test-key"
            )
        )
    finally:
        server.stop()


class TestSubmitOrGetIdentity:
    def test_submit_creates_run(self, adapter: HermesRunPort) -> None:
        handle = adapter.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        assert isinstance(handle, RunHandle)
        assert handle.run_id
        assert handle.created is True

    def test_repeated_submit_same_identity_recovers_same_run(
        self, adapter: HermesRunPort
    ) -> None:
        first = adapter.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        second = adapter.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        assert second.run_id == first.run_id
        assert second.created is False  # idempotent replay, no second run

    def test_same_key_different_body_conflicts(self, adapter: HermesRunPort) -> None:
        adapter.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        with pytest.raises(HermesRunError) as exc:
            adapter.submit_or_get(
                idempotency_key=_KEY, request_body={"input": "different"}
            )
        assert exc.value.code == "idempotency_conflict"

    def test_recover_by_identity_after_dropped_ack(
        self, adapter: HermesRunPort
    ) -> None:
        """Acceptance #1: an accepted request whose ack was lost is recovered by
        request identity, never blindly resent into a second run."""
        first = adapter.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        recovered = adapter.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        assert recovered.run_id == first.run_id
        assert recovered.created is False


class TestStatus:
    def test_get_status_returns_snapshot(self, adapter: HermesRunPort) -> None:
        handle = adapter.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        snap = adapter.get_status(handle.run_id)
        assert isinstance(snap, RunStatusSnapshot)
        assert snap.run_id == handle.run_id
        assert snap.status in {"queued", "running", "succeeded", "failed", "stopped"}

    def test_unknown_run_raises_not_found(self, adapter: HermesRunPort) -> None:
        with pytest.raises(HermesRunError) as exc:
            adapter.get_status("run_never_existed")
        assert exc.value.code == "run_not_found"


class TestEventPlane:
    def test_replay_is_monotonic_without_duplicates(
        self, adapter: HermesRunPort
    ) -> None:
        handle = adapter.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        events = adapter.stream_events(handle.run_id)
        seqs = [e.seq for e in events]
        assert isinstance(events[0], StreamEvent)
        assert seqs == sorted(seqs), "monotonic"
        assert len(set(seqs)) == len(seqs), "no duplicates"

    def test_replay_from_cursor_returns_strictly_after(
        self, adapter: HermesRunPort
    ) -> None:
        handle = adapter.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        all_events = adapter.stream_events(handle.run_id)
        assert len(all_events) >= 1
        cursor = all_events[0].seq
        rest = adapter.stream_events(handle.run_id, since_seq=cursor)
        assert all(e.seq > cursor for e in rest)
        assert [e.seq for e in rest] == [e.seq for e in all_events[1:]]


class TestStop:
    def test_stop_is_idempotent(self, adapter: HermesRunPort) -> None:
        handle = adapter.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        first = adapter.stop(handle.run_id)
        second = adapter.stop(handle.run_id)
        assert isinstance(first, StopResult)
        assert first.status == second.status  # same result, no 404 on repeat

    def test_stop_unknown_run_not_found(self, adapter: HermesRunPort) -> None:
        with pytest.raises(HermesRunError) as exc:
            adapter.stop("run_never_existed")
        assert exc.value.code == "run_not_found"


class TestCapabilities:
    def test_capabilities_report_behavioral_grounding(
        self, adapter: HermesRunPort
    ) -> None:
        caps = adapter.capabilities()
        assert caps["object"] == "hermes.api_server.capabilities"
        durable = caps["durable"]
        for cap in (
            "idempotency",
            "event_replay",
            "approval_cas",
            "idempotent_stop",
            "restart_reconcile",
            "run_evidence",
        ):
            assert durable[cap]["supported"] is True, cap
            assert durable[cap]["grounded"] is True, cap


class TestSharedInterface:
    def test_fake_satisfies_port(self) -> None:
        assert isinstance(ScriptedFakeHermesAdapter(), HermesRunPort)


# ---------------------------------------------------------------------------
# Fake-only: lifecycle drivers + full semantics + scripted fault injection.
# (These drive the upstream; the HTTP adapter cannot, by design.)
# ---------------------------------------------------------------------------


class TestFakeLifecycleAndSemantics:
    def test_events_are_gapless_when_driven_to_terminal(self) -> None:
        fake = ScriptedFakeHermesAdapter()
        handle = fake.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        fake.drive_to_terminal(handle.run_id)
        seqs = [e.seq for e in fake.stream_events(handle.run_id)]
        assert seqs == list(range(seqs[0], seqs[0] + len(seqs))), "no gaps"

    def test_approval_respond_success(self) -> None:
        fake = ScriptedFakeHermesAdapter()
        handle = fake.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        challenge = fake.raise_approval(handle.run_id)
        assert isinstance(challenge, ApprovalChallenge)
        result = fake.respond_approval(
            handle.run_id,
            choice="once",
            challenge_id=challenge.challenge_id,
            action_digest=challenge.action_digest,
        )
        assert result.resolved >= 1

    def test_approval_replay_rejected(self) -> None:
        fake = ScriptedFakeHermesAdapter()
        handle = fake.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        challenge = fake.raise_approval(handle.run_id)
        fake.respond_approval(
            handle.run_id, choice="once",
            challenge_id=challenge.challenge_id, action_digest=challenge.action_digest,
        )
        with pytest.raises(HermesRunError) as exc:
            fake.respond_approval(
                handle.run_id, choice="once",
                challenge_id=challenge.challenge_id,
                action_digest=challenge.action_digest,
            )
        assert exc.value.code == "approval_challenge_invalid"

    def test_approval_digest_mismatch_rejected(self) -> None:
        fake = ScriptedFakeHermesAdapter()
        handle = fake.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        challenge = fake.raise_approval(handle.run_id)
        with pytest.raises(HermesRunError) as exc:
            fake.respond_approval(
                handle.run_id, choice="once",
                challenge_id=challenge.challenge_id, action_digest="forged",
            )
        assert exc.value.code == "approval_challenge_invalid"

    def test_restart_reconcile_marks_in_flight_stopped(self) -> None:
        fake = ScriptedFakeHermesAdapter()
        handle = fake.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        fake.mark_running(handle.run_id)  # simulate crash mid-run
        fake.reconcile()
        assert fake.get_status(handle.run_id).status == "stopped"


class TestScriptedFaults:
    def test_restart_survives_durable_state(self, tmp_path) -> None:
        # Real restart boundary: durable snapshot + a fresh process that loads it.
        path = str(tmp_path / "authority.json")
        fake = ScriptedFakeHermesAdapter(path)
        handle = fake.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        fake.drive_to_terminal(handle.run_id)
        fake2 = ScriptedFakeHermesAdapter(path)  # new process loads from disk
        assert fake2.get_status(handle.run_id).run_id == handle.run_id

    def test_event_gap_fault_is_scriptable(self) -> None:
        fake = ScriptedFakeHermesAdapter()
        handle = fake.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        fake.drive_to_terminal(handle.run_id)
        baseline = [e.seq for e in fake.stream_events(handle.run_id)]
        fake.inject(ScriptedFault.EVENT_GAP)
        gapped = [e.seq for e in fake.stream_events(handle.run_id)]
        assert len(gapped) < len(baseline), "gap fault drops an event from view"

    def test_quota_fallback_records_reason(self) -> None:
        fake = ScriptedFakeHermesAdapter()
        fake.inject(ScriptedFault.QUOTA_FALLBACK)
        handle = fake.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        fake.drive_to_terminal(handle.run_id)
        assert fake.get_status(handle.run_id).fallback_reason is not None

    def test_approval_stale_rejected_without_changing_fact(self) -> None:
        fake = ScriptedFakeHermesAdapter()
        handle = fake.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        challenge = fake.raise_approval(handle.run_id)
        fake.inject(ScriptedFault.APPROVAL_STALE)
        with pytest.raises(HermesRunError) as exc:
            fake.respond_approval(
                handle.run_id, choice="once",
                challenge_id=challenge.challenge_id,
                action_digest=challenge.action_digest,
            )
        assert exc.value.code == "approval_challenge_invalid"

    def test_partial_stop_leaves_run_addressable_and_idempotent(self) -> None:
        fake = ScriptedFakeHermesAdapter()
        handle = fake.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        fake.mark_running(handle.run_id)
        fake.inject(ScriptedFault.PARTIAL_STOP)
        first = fake.stop(handle.run_id)
        # A partial stop must not orphan the run: it stays addressable and a
        # repeat stop returns the SAME result (never a 404 / lost run).
        again = fake.stop(handle.run_id)
        assert again.status == first.status
        assert fake.get_status(handle.run_id).run_id == handle.run_id


# ---------------------------------------------------------------------------
# HTTP transport layer (loopback-only fail-closed) + wire-shape fidelity.
# ---------------------------------------------------------------------------


class TestHttpTransport:
    def test_non_loopback_base_url_refused(self) -> None:
        with pytest.raises(HermesRunError) as exc:
            UrllibLoopbackHttpTransport(base_url="http://example.com:9000")
        assert exc.value.code == "non_loopback_endpoint"

    def test_https_scheme_refused(self) -> None:
        with pytest.raises(HermesRunError):
            UrllibLoopbackHttpTransport(base_url="https://127.0.0.1:9000")

    def test_missing_port_refused(self) -> None:
        with pytest.raises(HermesRunError):
            UrllibLoopbackHttpTransport(base_url="http://127.0.0.1")

    def test_adapter_satisfies_port(self) -> None:
        server = _ScriptedUpstreamServer()
        server.start()
        try:
            adapter = OfficialHermesHttpAdapter(
                transport=UrllibLoopbackHttpTransport(base_url=server.base_url)
            )
            assert isinstance(adapter, HermesRunPort)
        finally:
            server.stop()


# ---------------------------------------------------------------------------
# Scripted loopback upstream: serves the reviewed V2 contract over HTTP so the
# OfficialHermesHttpAdapter is conformance-tested without a live Hermes. It
# delegates to the same ScriptedFakeHermesAdapter the fake-side tests use, so
# both adapters are exercised against identical behavior.
# ---------------------------------------------------------------------------


class _ScriptedUpstreamServer:
    def __init__(self) -> None:
        self._fake = ScriptedFakeHermesAdapter()
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def base_url(self) -> str:
        assert self._server is not None
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> None:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # silence
                return

            def _send(self, status: int, payload: dict) -> None:
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _error(self, status: int, code: str, message: str) -> None:
                self._send(
                    status,
                    {"error": {"message": message, "type": "invalid_request_error",
                               "param": None, "code": code}},
                )

            def _body(self) -> dict:
                length = int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(length) or b"{}")

            def do_POST(self):  # noqa: N802
                try:
                    outer._route_post(self)
                except HermesRunError as exc:
                    self._error(exc.http_status, exc.code, str(exc))

            def do_GET(self):  # noqa: N802
                try:
                    outer._route_get(self)
                except HermesRunError as exc:
                    self._error(exc.http_status, exc.code, str(exc))

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()

    # -- routes ------------------------------------------------------------

    def _route_post(self, h: BaseHTTPRequestHandler) -> None:
        path = h.path.split("?")[0]
        if path == "/v1/runs":
            body = h._body()
            key = h.headers.get("Idempotency-Key")
            handle = self._fake.submit_or_get(idempotency_key=key, request_body=body)
            payload = {
                "run_id": handle.run_id,
                "status": "started" if handle.created else "recovered",
            }
            if not handle.created:
                payload["idempotent_replay"] = True
                payload["idempotency_key"] = key
            h._send(202, payload)
            return
        if path.endswith("/stop"):
            run_id = path.split("/")[3]
            result = self._fake.stop(run_id)
            h._send(200, {"run_id": run_id, "status": result.status})
            return
        if path.endswith("/approval"):
            run_id = path.split("/")[3]
            body = h._body()
            result = self._fake.respond_approval(
                run_id,
                choice=body.get("choice"),
                challenge_id=body.get("challenge_id"),
                action_digest=body.get("action_digest"),
            )
            h._send(200, {
                "object": "hermes.run.approval_response", "run_id": run_id,
                "choice": body.get("choice"), "resolved": result.resolved,
            })
            return
        h._error(404, "not_found", "unknown path")

    def _route_get(self, h: BaseHTTPRequestHandler) -> None:
        path = h.path.split("?")[0]
        if path == "/v1/capabilities":
            h._send(200, self._fake.capabilities())
            return
        if path.endswith("/events"):
            run_id = path.split("/")[3]
            since = self._cursor(h)
            events = self._fake.stream_events(run_id, since_seq=since)
            self._send_sse(h, events)
            return
        if path.startswith("/v1/runs/"):
            run_id = path.split("/")[3]
            snap = self._fake.get_status(run_id)
            payload = {"object": "hermes.run", "run_id": snap.run_id, "status": snap.status}
            if snap.fallback_reason is not None:
                payload["fallback_reason"] = snap.fallback_reason
            h._send(200, payload)
            return
        h._error(404, "not_found", "unknown path")

    @staticmethod
    def _cursor(h: BaseHTTPRequestHandler) -> int:
        last_event_id = h.headers.get("Last-Event-ID")
        if last_event_id is not None:
            return int(last_event_id)
        query = h.path.partition("?")[2]
        for part in query.split("&"):
            if part.startswith("since="):
                return int(part.split("=", 1)[1])
        return 0

    @staticmethod
    def _send_sse(h: BaseHTTPRequestHandler, events) -> None:
        h.send_response(200)
        h.send_header("Content-Type", "text/event-stream")
        h.send_header("Cache-Control", "no-cache")
        h.send_header("X-Accel-Buffering", "no")
        h.end_headers()
        for e in events:
            frame = {"seq": e.seq, "event": e.event_type, **e.payload}
            h.wfile.write(
                f"id: {e.seq}\nevent: {e.event_type}\ndata: {json.dumps(frame)}\n\n".encode()
            )
        h.wfile.write(b": stream closed\n\n")


# ---------------------------------------------------------------------------
# V2 close-out — durable availability gate (plan §V2 line 528).
# Production adapter must report unavailable and keep dispatch closed when
# durable is dormant (live install flag OFF) or any probe is ungrounded.
# ---------------------------------------------------------------------------


def _full_grounded_durable() -> dict:
    return {
        key: {"supported": True, "grounded": True, "evidence": f"test.{key}"}
        for key in DURABLE_CAPABILITY_KEYS
    }


class TestEvaluateDurableRunAvailability:
    def test_full_grounded_is_available(self) -> None:
        caps = {
            "object": "hermes.api_server.capabilities",
            "contract_version": 1,
            "durable": _full_grounded_durable(),
        }
        result = evaluate_durable_run_availability(caps)
        assert result.available is True
        assert result.blockers == ()
        assert result.contract_version == 1

    def test_absent_durable_block_is_unavailable(self) -> None:
        """Live install with flag OFF omits the durable block entirely."""
        caps = {
            "object": "hermes.api_server.capabilities",
            "features": {"run_submission": True},
        }
        result = evaluate_durable_run_availability(caps)
        assert result.available is False
        assert "durable_block_absent" in result.blockers

    def test_ungrounded_probe_is_unavailable(self) -> None:
        durable = _full_grounded_durable()
        durable["event_replay"] = {
            "supported": True,
            "grounded": False,
            "evidence": "probe_raised",
        }
        caps = {"contract_version": 1, "durable": durable}
        result = evaluate_durable_run_availability(caps)
        assert result.available is False
        assert "ungrounded:event_replay" in result.blockers

    def test_supported_false_is_unavailable(self) -> None:
        durable = _full_grounded_durable()
        durable["idempotency"] = {
            "supported": False,
            "grounded": False,
            "evidence": "off",
        }
        caps = {"contract_version": 1, "durable": durable}
        result = evaluate_durable_run_availability(caps)
        assert result.available is False
        assert any(b.startswith("unsupported:") or b.startswith("ungrounded:") for b in result.blockers)

    def test_missing_probe_key_is_unavailable(self) -> None:
        durable = _full_grounded_durable()
        del durable["run_evidence"]
        caps = {"contract_version": 1, "durable": durable}
        result = evaluate_durable_run_availability(caps)
        assert result.available is False
        assert "missing_probe:run_evidence" in result.blockers

    def test_contract_version_absent_is_blocker(self) -> None:
        caps = {"durable": _full_grounded_durable()}
        result = evaluate_durable_run_availability(caps)
        assert result.available is False
        assert "contract_version_absent" in result.blockers

    def test_garbage_input_is_unavailable_not_raise(self) -> None:
        assert evaluate_durable_run_availability(None).available is False  # type: ignore[arg-type]
        assert evaluate_durable_run_availability("nope").available is False  # type: ignore[arg-type]
        assert evaluate_durable_run_availability([]).available is False  # type: ignore[arg-type]

    def test_require_available_raises_durable_unavailable(self) -> None:
        result = DurableRunAvailability(available=False, blockers=("durable_block_absent",))
        with pytest.raises(HermesRunError) as exc:
            result.require_available()
        assert exc.value.code == "durable_unavailable"
        assert exc.value.http_status == 503
        assert "dispatch closed" in exc.value.message


class TestPortDurableAvailabilityGate:
    def test_fake_reports_available(self) -> None:
        fake = ScriptedFakeHermesAdapter()
        avail = fake.durable_availability()
        assert avail.available is True
        assert avail.blockers == ()
        # require_durable_available is a no-raise on the fake (broker on).
        assert fake.require_durable_available().available is True

    def test_http_adapter_dormant_payload_closes_dispatch(self) -> None:
        """Simulate live install: capabilities without durable block.

        OfficialHermesHttpAdapter must surface durable_unavailable so the
        platform keeps dispatch closed (plan §V2 line 528).
        """

        class _DormantTransport:
            def get_json(self, path: str, *, headers=None):
                assert path == "/v1/capabilities"
                # Shape matches live :8642 with flag OFF (no durable, no contract_version).
                return {
                    "object": "hermes.api_server.capabilities",
                    "platform": "hermes-agent",
                    "features": {"run_submission": True, "run_events_sse": True},
                }

        adapter = OfficialHermesHttpAdapter(transport=_DormantTransport())  # type: ignore[arg-type]
        avail = adapter.durable_availability()
        assert avail.available is False
        assert "durable_block_absent" in avail.blockers
        with pytest.raises(HermesRunError) as exc:
            adapter.require_durable_available()
        assert exc.value.code == "durable_unavailable"
        assert exc.value.http_status == 503

    def test_http_adapter_partial_grounding_closes_dispatch(self) -> None:
        class _PartialTransport:
            def get_json(self, path: str, *, headers=None):
                durable = _full_grounded_durable()
                durable["approval_cas"] = {
                    "supported": True,
                    "grounded": False,
                    "evidence": "store.get_approval_challenge_raised",
                }
                return {
                    "object": "hermes.api_server.capabilities",
                    "contract_version": 1,
                    "durable": durable,
                }

        adapter = OfficialHermesHttpAdapter(transport=_PartialTransport())  # type: ignore[arg-type]
        with pytest.raises(HermesRunError) as exc:
            adapter.require_durable_available()
        assert exc.value.code == "durable_unavailable"
        assert "ungrounded:approval_cas" in exc.value.message

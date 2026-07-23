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
from typing import Any, Mapping, Optional

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
        assert all(event.event_id for event in events), "stable event identity"
        assert all(
            "event_id" not in event.payload for event in events
        ), "event identity is envelope metadata, not duplicated payload"

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
        assert result.decision_status == "committed"
        assert result.waiter_signal_status == "confirmed"
        assert result.resolved == 0

    def test_exact_approval_replay_is_idempotent_across_restart(self, tmp_path) -> None:
        snapshot = str(tmp_path / "authority.json")
        fake = ScriptedFakeHermesAdapter(snapshot)
        handle = fake.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        challenge = fake.raise_approval(handle.run_id)
        first = fake.respond_approval(
            handle.run_id, choice="once",
            challenge_id=challenge.challenge_id, action_digest=challenge.action_digest,
        )
        recovered = ScriptedFakeHermesAdapter(snapshot)
        replay = recovered.respond_approval(
            handle.run_id, choice="once",
            challenge_id=challenge.challenge_id,
            action_digest=challenge.action_digest,
        )

        assert first.idempotent_replay is False
        assert replay.idempotent_replay is True
        assert first.decision_status == replay.decision_status == "committed"
        assert first.waiter_signal_status == replay.waiter_signal_status == "confirmed"
        assert replay.resolved == first.resolved == 0
        responded = [
            event
            for event in recovered.stream_events(handle.run_id)
            if event.event_type == "approval.responded"
        ]
        assert len(responded) == 1

        with pytest.raises(HermesRunError) as exc:
            recovered.respond_approval(
                handle.run_id, choice="always",
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

    @pytest.mark.parametrize("terminal_status", ["succeeded", "failed"])
    def test_stop_preserves_an_existing_terminal_result(
        self, terminal_status: str
    ) -> None:
        fake = ScriptedFakeHermesAdapter()
        handle = fake.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        fake.drive_to_terminal(handle.run_id, outcome=terminal_status)
        before = list(fake.stream_events(handle.run_id))

        first = fake.stop(handle.run_id)
        second = fake.stop(handle.run_id)

        assert first.status == terminal_status
        assert first.idempotent_replay is True
        assert second == first
        assert fake.get_status(handle.run_id).status == terminal_status
        assert fake.stream_events(handle.run_id) == before

    def test_concurrent_stop_has_one_first_result_and_one_replay(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = ScriptedFakeHermesAdapter()
        handle = fake.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        fake.mark_running(handle.run_id)

        # Deterministically expose the former read/append/set race.  The old
        # adapter path called append_event only after reading a non-terminal
        # status, so this barrier forced both callers past that stale read.
        # The atomic authority.stop() path never crosses this legacy seam.
        legacy_append = fake._authority.append_event  # noqa: SLF001
        legacy_race = threading.Barrier(2)

        def append_after_both_old_callers_read_status(
            run_id: str, event_type: str, payload: Mapping[str, Any]
        ) -> StreamEvent:
            if event_type == "run.cancelled":
                legacy_race.wait(timeout=2)
            return legacy_append(run_id, event_type, payload)

        monkeypatch.setattr(
            fake._authority,  # noqa: SLF001
            "append_event",
            append_after_both_old_callers_read_status,
        )
        start = threading.Barrier(3)
        results: list[StopResult] = []
        errors: list[BaseException] = []

        def stop_at_once() -> None:
            start.wait()
            try:
                results.append(fake.stop(handle.run_id))
            except BaseException as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        workers = [threading.Thread(target=stop_at_once) for _ in range(2)]
        for worker in workers:
            worker.start()
        start.wait()
        for worker in workers:
            worker.join(timeout=2)

        assert all(not worker.is_alive() for worker in workers)
        assert errors == []
        assert [result.idempotent_replay for result in results].count(False) == 1
        assert [result.idempotent_replay for result in results].count(True) == 1
        cancelled = [
            event
            for event in fake.stream_events(handle.run_id)
            if event.event_type == "run.cancelled"
        ]
        assert len(cancelled) == 1


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

    def test_partial_stop_leaves_run_addressable_and_idempotent(self, tmp_path) -> None:
        snapshot = str(tmp_path / "authority.json")
        fake = ScriptedFakeHermesAdapter(snapshot)
        handle = fake.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        fake.mark_running(handle.run_id)
        fake.inject(ScriptedFault.PARTIAL_STOP)

        with pytest.raises(HermesRunError) as exc:
            fake.stop(handle.run_id)

        assert exc.value.code == "transport_error"
        # The authority committed before the ACK was lost. Recovery by run ID
        # observes a durable stop and does not append a second cancellation.
        assert fake.get_status(handle.run_id).status == "stopped"
        again = fake.stop(handle.run_id)
        assert again.status == "stopped"
        assert again.idempotent_replay is True
        recovered = ScriptedFakeHermesAdapter(snapshot)
        assert recovered.stop(handle.run_id).idempotent_replay is True
        cancelled = [
            event
            for event in recovered.stream_events(handle.run_id)
            if event.event_type == "run.cancelled"
        ]
        assert len(cancelled) == 1


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

    @pytest.mark.parametrize(
        "base_url",
        [
            "http://user:secret@127.0.0.1:9000",
            "http://127.0.0.1:9000/v1",
            "http://127.0.0.1:9000?token=secret",
            "http://127.0.0.1:9000#fragment",
        ],
    )
    def test_loopback_base_url_must_be_a_bare_origin(self, base_url: str) -> None:
        with pytest.raises(HermesRunError) as exc:
            UrllibLoopbackHttpTransport(base_url=base_url)
        assert exc.value.code == "non_loopback_endpoint"

    def test_ipv6_loopback_authority_is_bracketed(self) -> None:
        transport = UrllibLoopbackHttpTransport(base_url="http://[::1]:9000")
        assert transport._base == "http://[::1]:9000"  # noqa: SLF001

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
                # The public run contract exposes only canonical lifecycle
                # states. Creation vs recovery is carried independently by
                # idempotent_replay, never by pseudo-status names.
                "status": "queued",
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
                "choice": body.get("choice"),
                "decision_status": result.decision_status,
                "waiter_signal_status": result.waiter_signal_status,
                "idempotent_replay": result.idempotent_replay,
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
            frame = {
                "seq": e.seq,
                "event": e.event_type,
                "event_id": e.event_id,
                **e.payload,
            }
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

    @pytest.mark.parametrize(
        ("legacy_status", "expected_created"),
        [("started", True), ("recovered", False)],
    )
    def test_http_adapter_keeps_legacy_submit_status_compatibility(
        self, legacy_status: str, expected_created: bool
    ) -> None:
        """Older reviewed servers used pseudo-statuses for create/replay.

        The canonical contract now uses ``queued`` plus ``idempotent_replay``,
        but retaining this fallback prevents a mixed-version rollout from
        accidentally treating a recovered run as a fresh execution.
        """

        class _LegacySubmitTransport:
            def get_json(self, path: str, *, headers=None):
                assert path == "/v1/capabilities"
                return {
                    "object": "hermes.api_server.capabilities",
                    "contract_version": 1,
                    "durable": _full_grounded_durable(),
                }

            def post_json(self, path: str, body, *, headers=None):
                assert path == "/v1/runs"
                return 202, {"run_id": "run_legacy", "status": legacy_status}

        adapter = OfficialHermesHttpAdapter(  # type: ignore[arg-type]
            transport=_LegacySubmitTransport()
        )

        handle = adapter.submit_or_get(
            idempotency_key="legacy-key", request_body={"input": "hello"}
        )

        assert handle.run_id == "run_legacy"
        assert handle.created is expected_created

    def test_http_adapter_submit_structurally_gated_when_dormant(self) -> None:
        """Mutating entrypoints must not POST when durable is unavailable.

        Line-528 is structural on OfficialHermesHttpAdapter — not an opt-in
        helper the platform can forget. A dormant capabilities payload must
        raise durable_unavailable without ever hitting post_json.
        """

        class _DormantNoPost:
            def __init__(self) -> None:
                self.posts = 0

            def get_json(self, path: str, *, headers=None):
                assert path == "/v1/capabilities"
                return {
                    "object": "hermes.api_server.capabilities",
                    "platform": "hermes-agent",
                    "features": {"run_submission": True},
                }

            def post_json(self, path: str, body, *, headers=None):
                self.posts += 1
                raise AssertionError(f"must not POST {path} when durable unavailable")

        transport = _DormantNoPost()
        adapter = OfficialHermesHttpAdapter(transport=transport)  # type: ignore[arg-type]
        with pytest.raises(HermesRunError) as exc:
            adapter.submit_or_get(idempotency_key="k", request_body={"input": "x"})
        assert exc.value.code == "durable_unavailable"
        assert transport.posts == 0

        with pytest.raises(HermesRunError) as exc2:
            adapter.respond_approval(
                "run_x", choice="once", challenge_id="c", action_digest="d"
            )
        assert exc2.value.code == "durable_unavailable"
        assert transport.posts == 0

        with pytest.raises(HermesRunError) as exc3:
            adapter.stop("run_x")
        assert exc3.value.code == "durable_unavailable"
        assert transport.posts == 0

    @pytest.mark.parametrize("mutation", ["submit", "approval", "stop"])
    def test_http_adapter_rechecks_capabilities_before_every_mutation(
        self, mutation: str
    ) -> None:
        """A canary flip to dormant closes an already-used adapter immediately."""

        class _OpenThenDormant:
            def __init__(self) -> None:
                self.capability_reads = 0
                self.posts = 0

            def get_json(self, path: str, *, headers=None):
                assert path == "/v1/capabilities"
                self.capability_reads += 1
                if self.capability_reads == 1:
                    return {
                        "object": "hermes.api_server.capabilities",
                        "contract_version": 1,
                        "durable": _full_grounded_durable(),
                    }
                return {
                    "object": "hermes.api_server.capabilities",
                    "platform": "hermes-agent",
                    "features": {"run_submission": True},
                }

            def post_json(self, path: str, body, *, headers=None):
                self.posts += 1
                if path == "/v1/runs":
                    return 202, {"run_id": "run_1", "status": "started"}
                if path.endswith("/approval"):
                    return 200, {"run_id": "run_1", "resolved": 1}
                if path.endswith("/stop"):
                    return 200, {"run_id": "run_1", "status": "stopped"}
                raise AssertionError(path)

        transport = _OpenThenDormant()
        adapter = OfficialHermesHttpAdapter(transport=transport)  # type: ignore[arg-type]

        def mutate() -> object:
            if mutation == "submit":
                return adapter.submit_or_get(
                    idempotency_key="k", request_body={"input": "x"}
                )
            if mutation == "approval":
                return adapter.respond_approval(
                    "run_1", choice="once", challenge_id="c", action_digest="d"
                )
            return adapter.stop("run_1")

        mutate()
        with pytest.raises(HermesRunError) as exc:
            mutate()

        assert exc.value.code == "durable_unavailable"
        assert transport.capability_reads == 2
        assert transport.posts == 1

    def test_capability_transport_error_blocks_post(self) -> None:
        class _CapabilityReadFails:
            def __init__(self) -> None:
                self.posts = 0

            def get_json(self, path: str, *, headers=None):
                assert path == "/v1/capabilities"
                raise HermesRunError("transport_error", "capability read failed")

            def post_json(self, path: str, body, *, headers=None):
                self.posts += 1
                raise AssertionError(f"must not POST after capability failure: {path}")

        transport = _CapabilityReadFails()
        adapter = OfficialHermesHttpAdapter(transport=transport)  # type: ignore[arg-type]

        with pytest.raises(HermesRunError) as exc:
            adapter.submit_or_get(idempotency_key="k", request_body={"input": "x"})

        assert exc.value.code == "transport_error"
        assert transport.posts == 0

    def test_http_adapter_reads_ungated_when_dormant(self) -> None:
        """Status/events/capabilities remain observable so operators can see why
        dispatch is closed — only mutators are gated."""

        class _DormantRead:
            def get_json(self, path: str, *, headers=None):
                if path == "/v1/capabilities":
                    return {
                        "object": "hermes.api_server.capabilities",
                        "platform": "hermes-agent",
                    }
                if path.startswith("/v1/runs/"):
                    return {
                        "run_id": "run_x",
                        "status": "succeeded",
                        "session_id": None,
                    }
                raise AssertionError(path)

            def get_sse(self, path: str, *, headers=None):
                return []

        adapter = OfficialHermesHttpAdapter(transport=_DormantRead())  # type: ignore[arg-type]
        caps = adapter.capabilities()
        assert "durable" not in caps
        snap = adapter.get_status("run_x")
        assert snap.status == "succeeded"
        assert adapter.stream_events("run_x") == []

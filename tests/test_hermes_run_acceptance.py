"""V2.11 — six UNFAKEABLE acceptance tests (plan §V2 lines 519-528).

Each test distinguishes REAL upstream durable-run behavior from a platform
PROJECTION that merely fakes the right answers. The adversarial bar (verified by
running dishonest projection subclasses through these assertions): a dishonest
implementation that records what it was asked and echoes canned responses must
FAIL; the real durable implementation must PASS.

The restart boundary is a REAL fresh process: ``_relaunch`` discards the fake
object and builds a NEW one whose constructor loads the durable JSON snapshot —
so "survives restart" is proven against durable state on disk, never against a
live in-memory object, and per-process faults do not leak across the boundary.

Anti-projection techniques used (each defeats a concrete projection the review
demonstrated could otherwise pass):
* fresh-process restart (not a rebound field) for every durability claim;
* white-box reads of the snapshot FILE (the file, not memory, is source of truth);
* reject-then-valid-retry for approval CAS (a rejected stale/digest attempt must
  NOT consume the grant — re-read state, never just assert an exception);
* event-COUNT assertions (a rejected/repeat call appends nothing);
* a NON-default fallback chain exercised two-sided (proves the allowlist is
  consulted, not hardcoded);
* requested-vs-actual policy divergence (evidence plane, plan §V2 508).

Red line: hermetic only (tmp_path snapshots, in-memory). No live Hermes, no
external network, no provider/paper/live/broker. Genuine proof against the
real installed Hermes is gated on the V2.12 install/restart authorization.
"""

from __future__ import annotations

import json

import pytest

from hqa.hermes_run_adapter import (
    HermesRunError,
    ScriptedFakeHermesAdapter,
    ScriptedFault,
    _canonical_digest,
)

_BODY = {"input": "hello research task", "model": "requested-model"}
_KEY = "acceptance-key-1"


def _durable_fake(tmp_path, *, chain=None):
    path = str(tmp_path / "authority.json")
    return ScriptedFakeHermesAdapter(path, authorized_fallback_chain=chain), path


def _relaunch(path, *, chain=None) -> ScriptedFakeHermesAdapter:
    """Model a real process restart: a NEW adapter whose constructor loads the
    durable snapshot from disk (per-process faults reset)."""
    return ScriptedFakeHermesAdapter(path, authorized_fallback_chain=chain)


def _snapshot_runs(path) -> list:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)["runs"]


def _approval_events(fake, run_id):
    return [e for e in fake.stream_events(run_id) if e.event_type == "approval.responded"]


def _cancel_events(fake, run_id):
    return [e for e in fake.stream_events(run_id) if e.event_type == "run.cancelled"]


# ---------------------------------------------------------------------------
# #1 — accepted but killed before the ack; after a restart the SAME request
#      identity recovers the SAME Run (the client never learned the run_id).
# ---------------------------------------------------------------------------


class TestAcceptance1RecoverByIdentityAfterKill:
    def test_kill_before_ack_then_recover_same_run(self, tmp_path) -> None:
        fake, path = _durable_fake(tmp_path)
        # Ack is genuinely dropped: the run persists but the caller gets NO id.
        fake.inject(ScriptedFault.ACCEPT_THEN_DROP)
        with pytest.raises(HermesRunError) as exc:
            fake.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        assert exc.value.code == "transport_error"

        # The expected run_id comes from the snapshot FILE, not any live object.
        (record,) = _snapshot_runs(path)
        persisted_run_id = record["run_id"]

        # Fresh process: in-process memory is gone; only durable state remains.
        fake2 = _relaunch(path)
        recovered = fake2.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        assert recovered.created is False
        assert recovered.run_id == persisted_run_id

        # Recovery yields the run WITH its first durable lifecycle event intact
        # (not a bare key->run_id identity-log projection).
        events = fake2.stream_events(recovered.run_id)
        assert any(e.event_type == "message.delta" for e in events)

    def test_restart_does_not_fabricate_a_new_run_for_same_identity(self, tmp_path) -> None:
        fake, path = _durable_fake(tmp_path)
        first = fake.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        fake2 = _relaunch(path)
        for _ in range(3):
            again = fake2.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
            assert again.run_id == first.run_id
            assert again.created is False
        # Exactly ONE run was ever persisted (white-box, defeats shadow-run fakes).
        assert len(_snapshot_runs(path)) == 1


# ---------------------------------------------------------------------------
# #2 — duplicate submit produces exactly ONE Run; same ID + different digest
#      conflicts (409) with zero second run.
# ---------------------------------------------------------------------------


class TestAcceptance2DuplicateSubmitAndDigestConflict:
    def test_duplicate_submit_yields_one_run_whitebox(self, tmp_path) -> None:
        fake, path = _durable_fake(tmp_path)
        a = fake.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        b = fake.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        assert a.run_id == b.run_id
        assert (a.created, b.created) == (True, False)
        runs = _snapshot_runs(path)
        assert len(runs) == 1
        # The stored digest is the canonical digest of the body (server-computed).
        assert runs[0]["digest"] == _canonical_digest(_BODY)

    def test_key_reorder_recovers_via_canonical_digest(self, tmp_path) -> None:
        fake, _ = _durable_fake(tmp_path)
        first = fake.submit_or_get(idempotency_key=_KEY, request_body={"a": 1, "b": 2})
        # Same logical body, different key order -> canonical digest matches.
        again = fake.submit_or_get(idempotency_key=_KEY, request_body={"b": 2, "a": 1})
        assert again.created is False
        assert again.run_id == first.run_id

    def test_same_key_different_digest_conflicts_after_restart(self, tmp_path) -> None:
        fake, path = _durable_fake(tmp_path)
        fake.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        fake2 = _relaunch(path)  # stored digest must survive + still be enforced
        with pytest.raises(HermesRunError) as exc:
            fake2.submit_or_get(idempotency_key=_KEY, request_body={"input": "tampered"})
        assert exc.value.code == "idempotency_conflict"

    def test_conflict_leaves_original_run_and_no_second_run(self, tmp_path) -> None:
        fake, path = _durable_fake(tmp_path)
        original = fake.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        with pytest.raises(HermesRunError):
            fake.submit_or_get(idempotency_key=_KEY, request_body={"input": "other"})
        assert fake.get_status(original.run_id).run_id == original.run_id
        assert len(_snapshot_runs(path)) == 1  # conflict created no second run


# ---------------------------------------------------------------------------
# #3 — Run / status / event / provider policy / evidence survive a restart.
# ---------------------------------------------------------------------------


class TestAcceptance3StateSurvivesRestart:
    def test_status_event_policy_evidence_survive_restart(self, tmp_path) -> None:
        fake, path = _durable_fake(tmp_path)
        handle = fake.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        fake.inject(ScriptedFault.QUOTA_FALLBACK)
        fake.drive_to_terminal(handle.run_id, fallback_model="fallback-model")

        before = fake.get_status(handle.run_id)
        before_events = [(e.seq, e.event_type, e.event_id) for e in fake.stream_events(handle.run_id)]
        assert before.fallback_reason is not None

        fake2 = _relaunch(path)
        after = fake2.get_status(handle.run_id)
        after_events = [(e.seq, e.event_type, e.event_id) for e in fake2.stream_events(handle.run_id)]

        # Terminal status + timestamps survive.
        assert after.status == before.status == "succeeded"
        assert after.created_at == before.created_at
        assert after.created_at is not None
        # Requested policy is preserved AND diverges from actual after fallback.
        assert after.requested_policy == before.requested_policy
        assert after.requested_policy.get("model") == "requested-model"
        assert after.actual_policy.get("model") == "fallback-model"
        assert after.actual_policy == before.actual_policy
        assert after.fallback_reason == before.fallback_reason
        # Canonical events survive byte-for-byte (seq + type + stable event_id).
        assert after_events == before_events
        assert len(after_events) >= 2


# ---------------------------------------------------------------------------
# #4 — arbitrary-cursor replay is gapless + dup-free (anchored at cursor 0);
#      a disconnect does NOT delete canonical events; a view gap is recoverable.
# ---------------------------------------------------------------------------


def _driven_backlog(fake, run_id, extra=6):
    fake.drive_to_terminal(run_id)
    for i in range(extra):
        fake._authority.append_event(run_id, "message.delta", {"delta": f"chunk-{i}"})
    return fake.stream_events(run_id)


class TestAcceptance4GaplessReplayAndDisconnect:
    def test_every_cursor_replay_is_gapless_and_dup_free(self, tmp_path) -> None:
        fake, _ = _durable_fake(tmp_path)
        handle = fake.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        full = _driven_backlog(fake, handle.run_id)
        seqs = [e.seq for e in full]
        n = len(seqs)
        assert n >= 8, "backlog must be large enough to be adversarial"

        # (A) Global anchor: cursor 0 is the absolute contiguous range, unique.
        assert seqs == list(range(seqs[0], seqs[0] + n))
        assert len(set(seqs)) == n

        # (B) Per-cursor consistency: every window is exactly the strict suffix,
        #     with per-seq (event_id, payload) agreement — no inclusive re-dup.
        for i, ev in enumerate(full):
            window = fake.stream_events(handle.run_id, since_seq=ev.seq)
            assert [e.seq for e in window] == seqs[i + 1:]
            assert all(e.seq > ev.seq for e in window)
            assert [ (e.seq, e.event_id) for e in window ] == [
                (f.seq, f.event_id) for f in full[i + 1:]
            ]
        # Past-the-end cursors re-deliver nothing.
        assert fake.stream_events(handle.run_id, since_seq=seqs[-1]) == []
        assert fake.stream_events(handle.run_id, since_seq=seqs[-1] + 99) == []

    def test_event_id_is_stable_across_repeated_reads(self, tmp_path) -> None:
        fake, _ = _durable_fake(tmp_path)
        handle = fake.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        _driven_backlog(fake, handle.run_id)
        first = [(e.seq, e.event_id) for e in fake.stream_events(handle.run_id)]
        second = [(e.seq, e.event_id) for e in fake.stream_events(handle.run_id)]
        assert first == second
        assert all(eid is not None for _, eid in first)

    def test_disconnect_does_not_delete_canonical_events(self, tmp_path) -> None:
        fake, _ = _durable_fake(tmp_path)
        handle = fake.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        backlog_before = [(e.seq, e.event_id) for e in _driven_backlog(fake, handle.run_id)]

        # Client connects, reads a strict prefix, then "disconnects".
        prefix = fake.stream_events(handle.run_id, since_seq=0)[:1]
        assert prefix

        # Reconnect: fresh replay(0) is byte-for-byte the pre-disconnect backlog
        # (a delete-on-disconnect projection that drops the consumed prefix fails).
        backlog_after = [(e.seq, e.event_id) for e in fake.stream_events(handle.run_id)]
        assert backlog_after == backlog_before

    def test_view_gap_is_recoverable_from_canonical_store(self, tmp_path) -> None:
        fake, _ = _durable_fake(tmp_path)
        handle = fake.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        baseline = _driven_backlog(fake, handle.run_id)
        fake.inject(ScriptedFault.EVENT_GAP)
        gapped = fake.stream_events(handle.run_id)
        assert len(gapped) < len(baseline)  # transport/view drop observed
        # Resume/clear the fault: the canonical store still holds the dropped
        # event with its identity intact and full contiguity restored.
        fake.clear_faults()
        recovered = fake.stream_events(handle.run_id)
        assert [(e.seq, e.event_id) for e in recovered] == [
            (e.seq, e.event_id) for e in baseline
        ]


# ---------------------------------------------------------------------------
# #5 — fallback walks ONLY the pre-authorized chain (a load-bearing allowlist,
#      not a hardcoded default) and records a reason; unauthorized fails closed.
# ---------------------------------------------------------------------------


class TestAcceptance5AuthorizedFallbackOnly:
    def test_in_chain_fallback_records_reason_and_actual(self, tmp_path) -> None:
        # NON-default chain so the allowlist is load-bearing.
        fake, _ = _durable_fake(tmp_path, chain=["fb-A"])
        fake.inject(ScriptedFault.QUOTA_FALLBACK)
        handle = fake.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        fake.drive_to_terminal(handle.run_id, fallback_model="fb-A")
        snap = fake.get_status(handle.run_id)
        assert snap.status == "succeeded"
        assert snap.actual_policy["model"] == "fb-A"
        assert "fb-A" in snap.fallback_reason
        # Requested policy preserved and diverges from actual.
        assert snap.requested_policy.get("model") == "requested-model"

    def test_off_chain_default_model_fails_closed(self, tmp_path) -> None:
        # The DEFAULT model is NOT implicitly authorized when off the chain.
        fake, _ = _durable_fake(tmp_path, chain=["fb-A"])
        fake.inject(ScriptedFault.QUOTA_FALLBACK)
        handle = fake.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        fake.drive_to_terminal(handle.run_id, fallback_model="fallback-model")
        snap = fake.get_status(handle.run_id)
        assert snap.status == "failed"
        assert "fallback-model" in snap.fallback_reason
        # No success evidence stamped for the rejected fallback.
        assert snap.actual_policy is None

    def test_unauthorized_fallback_stamps_no_actual_policy(self, tmp_path) -> None:
        fake, _ = _durable_fake(tmp_path, chain=["fb-A"])
        fake.inject(ScriptedFault.QUOTA_FALLBACK)
        handle = fake.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        fake.drive_to_terminal(handle.run_id, fallback_model="rogue-model")
        snap = fake.get_status(handle.run_id)
        assert snap.status == "failed"
        assert "rogue-model" in snap.fallback_reason
        assert snap.actual_policy is None
        # No run.completed success event for the rejected run.
        assert not any(e.event_type == "run.completed" for e in fake.stream_events(handle.run_id))


# ---------------------------------------------------------------------------
# #6 — approval and stop are idempotent on repeat; stale / expired /
#      digest-mismatch do NOT change the original fact (grant + run + events).
# ---------------------------------------------------------------------------


class TestAcceptance6ApprovalAndStopIdempotency:
    def test_single_use_replay_appends_no_extra_event(self, tmp_path) -> None:
        fake, _ = _durable_fake(tmp_path)
        handle = fake.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        ch = fake.raise_approval(handle.run_id)
        fake.respond_approval(
            handle.run_id, choice="once", challenge_id=ch.challenge_id, action_digest=ch.action_digest,
        )
        with pytest.raises(HermesRunError) as exc:
            fake.respond_approval(
                handle.run_id, choice="once", challenge_id=ch.challenge_id, action_digest=ch.action_digest,
            )
        assert exc.value.code == "approval_challenge_invalid"
        # The replay appended nothing: exactly ONE approval.responded event.
        assert len(_approval_events(fake, handle.run_id)) == 1

    def test_digest_mismatch_does_not_consume_grant(self, tmp_path) -> None:
        fake, _ = _durable_fake(tmp_path)
        handle = fake.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        ch = fake.raise_approval(handle.run_id)
        with pytest.raises(HermesRunError):
            fake.respond_approval(
                handle.run_id, choice="once", challenge_id=ch.challenge_id, action_digest="forged",
            )
        # Reject-then-valid-retry: the grant is still consumable exactly once.
        ok = fake.respond_approval(
            handle.run_id, choice="once", challenge_id=ch.challenge_id, action_digest=ch.action_digest,
        )
        assert ok.resolved >= 1
        assert len(_approval_events(fake, handle.run_id)) == 1

    def test_stale_does_not_consume_grant(self, tmp_path) -> None:
        fake, _ = _durable_fake(tmp_path)
        handle = fake.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        ch = fake.raise_approval(handle.run_id)
        fake.inject(ScriptedFault.APPROVAL_STALE)
        with pytest.raises(HermesRunError) as exc:
            fake.respond_approval(
                handle.run_id, choice="once", challenge_id=ch.challenge_id, action_digest=ch.action_digest,
            )
        assert exc.value.code == "approval_challenge_invalid"
        # After clearing the stale fault the SAME grant is still consumable —
        # proving the stale attempt did not consume it.
        fake.clear_faults()
        ok = fake.respond_approval(
            handle.run_id, choice="once", challenge_id=ch.challenge_id, action_digest=ch.action_digest,
        )
        assert ok.resolved >= 1
        assert len(_approval_events(fake, handle.run_id)) == 1

    def test_expired_grant_rejected_and_fact_unchanged(self, tmp_path) -> None:
        fake, _ = _durable_fake(tmp_path)
        handle = fake.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        ch = fake.raise_approval(handle.run_id, ttl_seconds=0.0)  # already expired
        before_status = fake.get_status(handle.run_id).status
        with pytest.raises(HermesRunError) as exc:
            fake.respond_approval(
                handle.run_id, choice="once", challenge_id=ch.challenge_id, action_digest=ch.action_digest,
            )
        assert exc.value.code == "approval_challenge_invalid"
        # Nothing stamped: no approval.responded event, run status unchanged.
        assert _approval_events(fake, handle.run_id) == []
        assert fake.get_status(handle.run_id).status == before_status

    def test_stop_detects_replay_and_terminal_is_immutable(self, tmp_path) -> None:
        fake, path = _durable_fake(tmp_path)
        handle = fake.submit_or_get(idempotency_key=_KEY, request_body=_BODY)
        first = fake.stop(handle.run_id)
        second = fake.stop(handle.run_id)
        # Replay is DETECTED, not coincidental.
        assert first.idempotent_replay is False
        assert second.idempotent_replay is True
        assert first.status == second.status
        # Repeat stop did not double-append run.cancelled.
        assert len(_cancel_events(fake, handle.run_id)) == 1
        # Terminal is immutable: a later drive cannot rewrite stopped.
        fake.drive_to_terminal(handle.run_id)
        assert fake.get_status(handle.run_id).status == "stopped"
        # Across a fresh-process restart the stopped state survives and stop is
        # STILL an idempotent replay (never a 404 on a known run).
        fake2 = _relaunch(path)
        third = fake2.stop(handle.run_id)
        assert third.idempotent_replay is True
        assert third.status == first.status

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import re

import pytest

import hqa.intent_payloads as payloads_module
from hqa.intent_payload_crypto import CryptoFailure, DeterministicCryptoFake
from hqa.intent_payloads import IntentPayloadError, IntentPayloadStore


class Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> str:
        return self.value.isoformat(timespec="microseconds").replace("+00:00", "Z")

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


class SpyCrypto:
    def __init__(self, delegate: DeterministicCryptoFake) -> None:
        self.delegate = delegate
        self.key_id = delegate.key_id
        self.algorithm = delegate.algorithm
        self.decrypt_calls = 0

    def encrypt(self, plaintext: bytes, *, aad: bytes) -> dict[str, str]:
        return self.delegate.encrypt(plaintext, aad=aad)

    def decrypt(self, envelope: object, *, aad: bytes) -> bytes:
        self.decrypt_calls += 1
        return self.delegate.decrypt(envelope, aad=aad)  # type: ignore[arg-type]


class FailingDecryptCrypto:
    def __init__(self, delegate: DeterministicCryptoFake, code: str) -> None:
        self.delegate = delegate
        self.key_id = delegate.key_id
        self.algorithm = delegate.algorithm
        self.code = code

    def encrypt(self, plaintext: bytes, *, aad: bytes) -> dict[str, str]:
        return self.delegate.encrypt(plaintext, aad=aad)

    def decrypt(self, envelope: object, *, aad: bytes) -> bytes:
        raise CryptoFailure(self.code, "redacted crypto failure")


class FailingEncryptCrypto(FailingDecryptCrypto):
    def encrypt(self, plaintext: bytes, *, aad: bytes) -> dict[str, str]:
        raise CryptoFailure(self.code, "secret prompt from broken crypto")


def request(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "2.0",
        "kind": "conversation_turn",
        "owner_id": "owner-local",
        "workspace_id": "workspace:main",
        "session_id": "session:managed-1",
        "client_intent_id": "intent-0001",
        "provider_policy": {
            "primary": {"provider": "openai", "model": "gpt-5"},
            "fallbacks": [],
        },
        "prompt": "请分析我的组合，但不要执行交易。",
        "ttl_days": 7,
    }
    value.update(overrides)
    return value


def scope() -> dict[str, str]:
    return {
        "owner_id": "owner-local",
        "workspace_id": "workspace:main",
        "session_id": "session:managed-1",
    }


def put_in_process(root: str, queue: object) -> None:
    process_clock = Clock(datetime(2026, 7, 19, 12, tzinfo=timezone.utc))
    process_crypto = DeterministicCryptoFake(
        key=b"intent payload test key".ljust(32, b"!")
    )
    try:
        receipt = IntentPayloadStore(
            Path(root), crypto=process_crypto, now=process_clock
        ).put(request())
        queue.put(("ok", receipt["payload_digest"]))  # type: ignore[attr-defined]
    except Exception as exc:  # pragma: no cover - parent asserts this path is absent
        queue.put(("error", type(exc).__name__))  # type: ignore[attr-defined]


@pytest.fixture
def clock() -> Clock:
    return Clock(datetime(2026, 7, 19, 12, tzinfo=timezone.utc))


@pytest.fixture
def crypto() -> DeterministicCryptoFake:
    return DeterministicCryptoFake(key=b"intent payload test key".ljust(32, b"!"))


def test_put_resolve_and_exact_replay_are_content_addressed_and_private(
    tmp_path: Path,
    clock: Clock,
    crypto: DeterministicCryptoFake,
) -> None:
    store = IntentPayloadStore(tmp_path / "payload-authority", crypto=crypto, now=clock)

    first = store.put(request())
    replay = store.put(request())

    assert replay == first
    assert first["payload_ref"] == "payload:sha256:" + first["payload_digest"]
    assert first["status"] == "active"
    assert first["expires_at"] == "2026-07-26T12:00:00.000000Z"
    expected_policy_digest = hashlib.sha256(
        json.dumps(
            request()["provider_policy"],
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert first["provider_policy_digest"] == expected_policy_digest
    envelope = store.resolve(
        first["payload_ref"],
        owner_id="owner-local",
        workspace_id="workspace:main",
        session_id="session:managed-1",
    )
    assert envelope == {
        **request(),
        "provider_policy_digest": first["provider_policy_digest"],
        "created_at": "2026-07-19T12:00:00.000000Z",
        "expires_at": "2026-07-26T12:00:00.000000Z",
    }
    canonical_envelope = (
        json.dumps(
            envelope,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    assert hashlib.sha256(canonical_envelope).hexdigest() == first["payload_digest"]
    assert "prompt" not in first
    disk = b"".join(
        path.read_bytes()
        for path in (tmp_path / "payload-authority").rglob("*")
        if path.is_file()
    )
    assert "请分析我的组合".encode() not in disk
    assert b'"provider":"openai"' not in disk


def test_same_client_identity_with_different_intent_conflicts_without_plaintext(
    tmp_path: Path,
    clock: Clock,
    crypto: DeterministicCryptoFake,
) -> None:
    store = IntentPayloadStore(tmp_path / "payload-authority", crypto=crypto, now=clock)
    store.put(request())

    with pytest.raises(IntentPayloadError) as caught:
        store.put(request(prompt="different and sensitive"))

    assert caught.value.code == "intent_idempotency_conflict"
    assert "different and sensitive" not in str(caught.value)


@pytest.mark.parametrize(
    "kind",
    ["conversation_turn", "research_start", "research_continue"],
)
def test_closed_intent_kinds_share_the_same_store(
    tmp_path: Path,
    clock: Clock,
    crypto: DeterministicCryptoFake,
    kind: str,
) -> None:
    store = IntentPayloadStore(tmp_path / kind, crypto=crypto, now=clock)
    receipt = store.put(request(kind=kind))
    assert receipt["kind"] == kind


@pytest.mark.parametrize("ttl", [0, 31, True, 1.5])
def test_ttl_is_an_integer_from_one_through_thirty(
    tmp_path: Path,
    clock: Clock,
    crypto: DeterministicCryptoFake,
    ttl: object,
) -> None:
    store = IntentPayloadStore(tmp_path / "payload-authority", crypto=crypto, now=clock)
    with pytest.raises(IntentPayloadError, match="ttl_days"):
        store.put(request(ttl_days=ttl))


def test_request_is_closed_strict_bounded_json(
    tmp_path: Path,
    clock: Clock,
    crypto: DeterministicCryptoFake,
) -> None:
    store = IntentPayloadStore(tmp_path / "payload-authority", crypto=crypto, now=clock)
    bad = request(extra="not in schema")
    with pytest.raises(IntentPayloadError, match="fields"):
        store.put(bad)
    with pytest.raises(IntentPayloadError, match="finite"):
        store.put(request(provider_policy={"temperature": float("nan")}))
    with pytest.raises(IntentPayloadError, match="maximum"):
        store.put(request(prompt="x" * 300_000))
    with pytest.raises(IntentPayloadError, match="kind"):
        store.put(request(kind="execute_trade"))


def test_consumer_binding_is_exact_idempotent_and_required_for_resolution(
    tmp_path: Path,
    clock: Clock,
    crypto: DeterministicCryptoFake,
) -> None:
    store = IntentPayloadStore(tmp_path / "payload-authority", crypto=crypto, now=clock)
    receipt = store.put(request())

    bound = store.bind_consumer(
        payload_ref=receipt["payload_ref"],
        consumer_ref="command:cmd-123",
        **scope(),
    )
    assert bound == store.bind_consumer(
        payload_ref=receipt["payload_ref"],
        consumer_ref="command:cmd-123",
        **scope(),
    )
    assert bound["consumer_ref"] == "command:cmd-123"
    assert store.put(request()) == receipt
    with pytest.raises(IntentPayloadError) as caught:
        store.bind_consumer(
            payload_ref=receipt["payload_ref"],
            consumer_ref="command:cmd-other",
            **scope(),
        )
    assert caught.value.code == "intent_consumer_conflict"
    with pytest.raises(IntentPayloadError) as unbound:
        store.resolve(
            receipt["payload_ref"],
            owner_id="owner-local",
            workspace_id="workspace:main",
            session_id="session:managed-1",
        )
    assert unbound.value.code == "intent_consumer_mismatch"
    resolved = store.resolve(
        receipt["payload_ref"],
        owner_id="owner-local",
        workspace_id="workspace:main",
        session_id="session:managed-1",
        consumer_ref="command:cmd-123",
    )
    assert resolved["prompt"].startswith("请分析")


def test_consumer_kind_and_owner_scope_are_closed(
    tmp_path: Path,
    clock: Clock,
    crypto: DeterministicCryptoFake,
) -> None:
    conversation = IntentPayloadStore(tmp_path / "conversation", crypto=crypto, now=clock)
    conversation_receipt = conversation.put(request())
    with pytest.raises(IntentPayloadError, match="command:"):
        conversation.bind_consumer(
            payload_ref=conversation_receipt["payload_ref"],
            consumer_ref="attempt:" + "a" * 64,
            **scope(),
        )
    with pytest.raises(IntentPayloadError) as forbidden:
        conversation.status(
            conversation_receipt["payload_ref"],
            owner_id="owner-other",
            workspace_id="workspace:main",
            session_id="session:managed-1",
        )
    assert forbidden.value.code == "intent_payload_forbidden"

    research = IntentPayloadStore(tmp_path / "research", crypto=crypto, now=clock)
    research_receipt = research.put(
        request(kind="research_start", client_intent_id="research-1")
    )
    with pytest.raises(IntentPayloadError, match="attempt:"):
        research.bind_consumer(
            payload_ref=research_receipt["payload_ref"],
            consumer_ref="command:cmd-1",
            **scope(),
        )
    bound = research.bind_consumer(
        payload_ref=research_receipt["payload_ref"],
        consumer_ref="attempt:" + "b" * 64,
        **scope(),
    )
    assert bound["consumer_ref"] == "attempt:" + "b" * 64


def test_workspace_and_session_must_be_canonical_scoped_refs(
    tmp_path: Path,
    clock: Clock,
    crypto: DeterministicCryptoFake,
) -> None:
    store = IntentPayloadStore(tmp_path / "payload-authority", crypto=crypto, now=clock)
    with pytest.raises(IntentPayloadError, match="workspace_id"):
        store.put(request(workspace_id="workspace-main"))
    with pytest.raises(IntentPayloadError, match="session_id"):
        store.put(request(session_id="session-main"))


def test_expiry_deletes_ciphertext_leaves_tombstone_and_prevents_revival(
    tmp_path: Path,
    clock: Clock,
    crypto: DeterministicCryptoFake,
) -> None:
    store = IntentPayloadStore(tmp_path / "payload-authority", crypto=crypto, now=clock)
    expiring_request = request(
        kind="research_start",
        client_intent_id="research-expiry-1",
        ttl_days=1,
    )
    receipt = store.put(expiring_request)
    consumer_ref = "attempt:" + "a" * 64
    store.bind_consumer(
        payload_ref=receipt["payload_ref"],
        consumer_ref=consumer_ref,
        **scope(),
    )
    blob = tmp_path / "payload-authority" / "blobs" / (
        receipt["payload_digest"] + ".blob"
    )
    assert blob.exists()
    clock.advance(days=1)

    report = store.reconcile_expired()

    assert report["expired"] == [receipt["payload_ref"]]
    assert len(report["tombstones"]) == 1
    tombstone = report["tombstones"][0]
    assert tombstone == {
        "schema_version": "2.0",
        "payload_ref": receipt["payload_ref"],
        "payload_digest": receipt["payload_digest"],
        "kind": "research_start",
        "owner_id": "owner-local",
        "workspace_id": "workspace:main",
        "session_id": "session:managed-1",
        "consumer_ref": consumer_ref,
        "expires_at": "2026-07-20T12:00:00.000000Z",
        "expired_at": "2026-07-20T12:00:00.000000Z",
        "tombstone_event_ref": tombstone["tombstone_event_ref"],
        "tombstone_digest": tombstone["tombstone_digest"],
    }
    assert re.fullmatch(r"event:[0-9a-f]{64}", tombstone["tombstone_event_ref"])
    assert re.fullmatch(r"[0-9a-f]{64}", tombstone["tombstone_digest"])
    replay = store.reconcile_expired()
    assert replay["expired"] == []
    assert replay["tombstones"] == [tombstone]
    assert not blob.exists()
    assert store.status(receipt["payload_ref"], **scope())["status"] == "expired"
    with pytest.raises(IntentPayloadError) as caught:
        store.resolve(
            receipt["payload_ref"],
            owner_id="owner-local",
            workspace_id="workspace:main",
            session_id="session:managed-1",
        )
    assert caught.value.code == "intent_payload_expired"
    with pytest.raises(IntentPayloadError) as replay:
        store.put(expiring_request)
    assert replay.value.code == "intent_payload_expired"


def test_expiry_reconcile_is_bounded_and_reports_remaining_work(
    tmp_path: Path,
    clock: Clock,
    crypto: DeterministicCryptoFake,
) -> None:
    store = IntentPayloadStore(tmp_path / "payload-authority", crypto=crypto, now=clock)
    for number in range(3):
        store.put(request(client_intent_id="intent-{}".format(number), ttl_days=1))
    clock.advance(days=1)

    first = store.reconcile_expired(limit=2)
    second = store.reconcile_expired(limit=2)

    assert len(first["expired"]) == 2
    assert first["remaining_due"] == 1
    assert "请分析" not in json.dumps(first, ensure_ascii=False)
    assert len(second["expired"]) == 1
    assert second["remaining_due"] == 0
    with pytest.raises(IntentPayloadError, match="limit"):
        store.reconcile_expired(limit=0)


def test_expiry_acknowledgement_is_exact_idempotent_and_stops_replay(
    tmp_path: Path,
    clock: Clock,
    crypto: DeterministicCryptoFake,
) -> None:
    store = IntentPayloadStore(tmp_path / "payload-authority", crypto=crypto, now=clock)
    receipt = store.put(
        request(
            kind="research_start",
            client_intent_id="research-expiry-ack-1",
            ttl_days=1,
        )
    )
    consumer_ref = "attempt:" + "a" * 64
    store.bind_consumer(
        payload_ref=receipt["payload_ref"],
        consumer_ref=consumer_ref,
        **scope(),
    )
    clock.advance(days=1)
    tombstone = store.reconcile_expired()["tombstones"][0]
    arguments = {
        "payload_ref": receipt["payload_ref"],
        "tombstone_event_ref": tombstone["tombstone_event_ref"],
        "tombstone_digest": tombstone["tombstone_digest"],
        "consumer_ref": consumer_ref,
        "consumer_event_ref": "event:" + "b" * 64,
        "consumer_operation_digest": "c" * 64,
        **scope(),
    }

    acknowledgement = store.acknowledge_expiry(**arguments)

    assert acknowledgement == store.acknowledge_expiry(**arguments)
    assert acknowledgement == {
        "schema_version": "2.0",
        "payload_ref": receipt["payload_ref"],
        "tombstone_event_ref": tombstone["tombstone_event_ref"],
        "tombstone_digest": tombstone["tombstone_digest"],
        "consumer_ref": consumer_ref,
        "consumer_event_ref": "event:" + "b" * 64,
        "consumer_operation_digest": "c" * 64,
        "acknowledgement_event_ref": acknowledgement["acknowledgement_event_ref"],
        "status": "acknowledged",
    }
    assert re.fullmatch(
        r"event:[0-9a-f]{64}", acknowledgement["acknowledgement_event_ref"]
    )
    report = store.reconcile_expired()
    assert report["tombstones"] == []
    assert report["pending_tombstone_count"] == 0
    with pytest.raises(IntentPayloadError) as conflict:
        store.acknowledge_expiry(
            **{**arguments, "consumer_event_ref": "event:" + "d" * 64}
        )
    assert conflict.value.code == "intent_expiry_acknowledgement_conflict"


@pytest.mark.parametrize(
    ("kind", "consumer_ref"),
    (("conversation_turn", "command:conversation-1"), ("research_start", None)),
)
def test_expiry_without_a_bound_research_attempt_needs_no_downstream_ack(
    tmp_path: Path,
    clock: Clock,
    crypto: DeterministicCryptoFake,
    kind: str,
    consumer_ref: str | None,
) -> None:
    store = IntentPayloadStore(tmp_path / kind, crypto=crypto, now=clock)
    receipt = store.put(
        request(kind=kind, client_intent_id="unbound-{}".format(kind), ttl_days=1)
    )
    if consumer_ref is not None:
        store.bind_consumer(
            payload_ref=receipt["payload_ref"],
            consumer_ref=consumer_ref,
            **scope(),
        )
    clock.advance(days=1)

    report = store.reconcile_expired()

    assert report["expired"] == [receipt["payload_ref"]]
    assert report["tombstones"] == []
    assert report["pending_tombstone_count"] == 0
    assert store.reconcile_expired()["tombstones"] == []


def test_resolve_enforces_owner_workspace_and_session_identity(
    tmp_path: Path,
    clock: Clock,
    crypto: DeterministicCryptoFake,
) -> None:
    store = IntentPayloadStore(tmp_path / "payload-authority", crypto=crypto, now=clock)
    receipt = store.put(request())
    for field, value in (
        ("owner_id", "other-owner"),
        ("workspace_id", "workspace:other"),
        ("session_id", "session:other"),
    ):
        arguments = {
            "owner_id": "owner-local",
            "workspace_id": "workspace:main",
            "session_id": "session:managed-1",
        }
        arguments[field] = value
        with pytest.raises(IntentPayloadError) as caught:
            store.resolve(receipt["payload_ref"], **arguments)
        assert caught.value.code == "intent_payload_forbidden"


def test_reverse_audit_and_projection_rebuild_use_events_as_authority(
    tmp_path: Path,
    clock: Clock,
    crypto: DeterministicCryptoFake,
) -> None:
    root = tmp_path / "payload-authority"
    store = IntentPayloadStore(root, crypto=crypto, now=clock)
    receipt = store.put(request())
    audit = store.reverse_audit()
    assert audit["status"] == "ok"
    assert audit["active_payloads"] == 1
    assert audit["event_count"] == 1
    assert "prompt" not in json.dumps(audit)

    (root / "index.v2.json").unlink()
    rebuilt = store.rebuild_index()
    assert rebuilt["payload_count"] == 1
    assert store.status(receipt["payload_ref"], **scope())["status"] == "active"


def test_corruption_symlink_hardlink_and_modes_fail_closed(
    tmp_path: Path,
    clock: Clock,
    crypto: DeterministicCryptoFake,
) -> None:
    root = tmp_path / "payload-authority"
    store = IntentPayloadStore(root, crypto=crypto, now=clock)
    receipt = store.put(request())
    blob = root / "blobs" / (receipt["payload_digest"] + ".blob")
    blob.chmod(0o600)
    with pytest.raises(IntentPayloadError) as mode_error:
        store.reverse_audit()
    assert mode_error.value.code == "intent_storage_insecure"

    blob.chmod(0o400)
    hardlink = tmp_path / "stolen-ciphertext"
    os.link(blob, hardlink)
    with pytest.raises(IntentPayloadError) as link_error:
        store.reverse_audit()
    assert link_error.value.code == "intent_storage_insecure"
    hardlink.unlink()

    (root / "index.v2.json").unlink()
    (root / "index.v2.json").symlink_to(root / "events.v2.jsonl")
    with pytest.raises(IntentPayloadError) as symlink_error:
        store.status(receipt["payload_ref"], **scope())
    assert symlink_error.value.code == "intent_storage_insecure"


def test_recovery_closes_the_atomic_blob_publish_link_window(
    tmp_path: Path,
    clock: Clock,
    crypto: DeterministicCryptoFake,
) -> None:
    root = tmp_path / "payload-authority"
    store = IntentPayloadStore(root, crypto=crypto, now=clock)
    receipt = store.put(request())
    blob = root / "blobs" / (receipt["payload_digest"] + ".blob")
    temporary = root / "blobs" / (
        ".blob." + receipt["payload_digest"] + "." + "a" * 24 + ".tmp"
    )
    os.link(blob, temporary)
    assert blob.stat().st_nlink == 2

    assert store.reverse_audit()["status"] == "ok"

    assert not temporary.exists()
    assert blob.stat().st_nlink == 1


def test_put_retry_cleans_a_verified_pre_event_orphan_blob(
    tmp_path: Path,
    clock: Clock,
    crypto: DeterministicCryptoFake,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "payload-authority"
    store = IntentPayloadStore(root, crypto=crypto, now=clock)
    original_append = store._append_event

    def fail_before_event(*_: object, **__: object) -> None:
        raise OSError("injected append failure")

    monkeypatch.setattr(store, "_append_event", fail_before_event)
    with pytest.raises(IntentPayloadError) as failed:
        store.put(request())
    assert failed.value.code == "intent_storage_io_error"
    assert list((root / "blobs").glob("*.blob"))

    monkeypatch.setattr(store, "_append_event", original_append)
    clock.advance(microseconds=1)
    receipt = store.put(request())

    assert store.status(receipt["payload_ref"], **scope())["status"] == "active"
    assert store.reverse_audit()["event_count"] == 1


def test_put_retry_after_journal_commit_rebuilds_missing_index_exactly(
    tmp_path: Path,
    clock: Clock,
    crypto: DeterministicCryptoFake,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "payload-authority"
    store = IntentPayloadStore(root, crypto=crypto, now=clock)
    original_publish = store._publish_index

    def fail_projection(*_: object, **__: object) -> None:
        raise OSError("injected projection failure")

    monkeypatch.setattr(store, "_publish_index", fail_projection)
    with pytest.raises(IntentPayloadError) as failed:
        store.put(request())
    assert failed.value.code == "intent_storage_io_error"
    assert (root / "events.v2.jsonl").read_bytes()
    assert not (root / "index.v2.json").exists()

    monkeypatch.setattr(store, "_publish_index", original_publish)
    clock.advance(microseconds=1)
    recovered = store.put(request())

    assert recovered["created_at"] == "2026-07-19T12:00:00.000000Z"
    assert store.reverse_audit()["event_count"] == 1


def test_unknown_journal_durability_is_retryable_and_exact_retry_converges(
    tmp_path: Path,
    clock: Clock,
    crypto: DeterministicCryptoFake,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = IntentPayloadStore(
        tmp_path / "payload-authority", crypto=crypto, now=clock
    )
    receipt = store.put(request())
    journal_identity = (
        store.root.joinpath("events.v2.jsonl").stat().st_dev,
        store.root.joinpath("events.v2.jsonl").stat().st_ino,
    )
    original_fsync = payloads_module.os.fsync

    def fail_journal_fsync(fd: int) -> None:
        metadata = os.fstat(fd)
        if (metadata.st_dev, metadata.st_ino) == journal_identity:
            raise OSError("injected journal fsync failure")
        original_fsync(fd)

    monkeypatch.setattr(payloads_module.os, "fsync", fail_journal_fsync)
    with pytest.raises(IntentPayloadError) as caught:
        store.bind_consumer(
            payload_ref=receipt["payload_ref"],
            consumer_ref="command:durability-retry",
            **scope(),
        )

    assert caught.value.code == "intent_durability_unknown"
    assert caught.value.retryable is True

    monkeypatch.setattr(payloads_module.os, "fsync", original_fsync)
    recovered = store.bind_consumer(
        payload_ref=receipt["payload_ref"],
        consumer_ref="command:durability-retry",
        **scope(),
    )
    assert recovered["consumer_ref"] == "command:durability-retry"
    assert store.reverse_audit()["event_count"] == 2


def test_journal_capacity_is_checked_before_append_without_self_corruption(
    tmp_path: Path,
    clock: Clock,
    crypto: DeterministicCryptoFake,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "payload-authority"
    store = IntentPayloadStore(root, crypto=crypto, now=clock)
    receipt = store.put(request())
    journal = root / "events.v2.jsonl"
    before = journal.read_bytes()
    monkeypatch.setattr(payloads_module, "_MAX_JOURNAL_BYTES", len(before) + 1)

    with pytest.raises(IntentPayloadError) as caught:
        store.bind_consumer(
            payload_ref=receipt["payload_ref"],
            consumer_ref="command:bounded-capacity",
            **scope(),
        )

    assert caught.value.code == "intent_authority_capacity_exceeded"
    assert journal.read_bytes() == before
    monkeypatch.setattr(payloads_module, "_MAX_JOURNAL_BYTES", 64 * 1024 * 1024)
    assert store.reverse_audit()["status"] == "ok"


def test_backup_contains_only_ciphertext_and_restore_preserves_expiry(
    tmp_path: Path,
    clock: Clock,
    crypto: DeterministicCryptoFake,
) -> None:
    source = IntentPayloadStore(tmp_path / "source", crypto=crypto, now=clock)
    receipt = source.put(request(prompt="backup secret marker", ttl_days=3))
    backup = tmp_path / "backup"

    manifest = source.backup(backup)

    assert manifest["key_ids"] == [crypto.key_id]
    raw = b"".join(path.read_bytes() for path in backup.rglob("*") if path.is_file())
    assert b"backup secret marker" not in raw

    target = IntentPayloadStore(tmp_path / "restored", crypto=crypto, now=clock)
    restored = target.restore(backup)
    assert restored["restored_payloads"] == 1
    assert target.status(receipt["payload_ref"], **scope())["expires_at"] == receipt[
        "expires_at"
    ]
    assert target.resolve(
        receipt["payload_ref"],
        owner_id="owner-local",
        workspace_id="workspace:main",
        session_id="session:managed-1",
    )["prompt"] == "backup secret marker"


def test_backup_aggregate_ciphertext_limit_fails_before_destination_publish(
    tmp_path: Path,
    clock: Clock,
    crypto: DeterministicCryptoFake,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = IntentPayloadStore(tmp_path / "source", crypto=crypto, now=clock)
    source.put(request())
    destination = tmp_path / "backup"
    monkeypatch.setattr(payloads_module, "_MAX_AGGREGATE_CIPHERTEXT_BYTES", 1)

    with pytest.raises(IntentPayloadError, match="aggregate ciphertext"):
        source.backup(destination)

    assert not destination.exists()


def test_restore_of_old_backup_after_expiry_cannot_resurrect_plaintext(
    tmp_path: Path,
    clock: Clock,
    crypto: DeterministicCryptoFake,
) -> None:
    source = IntentPayloadStore(tmp_path / "source", crypto=crypto, now=clock)
    receipt = source.put(request(prompt="expired backup secret", ttl_days=1))
    backup = tmp_path / "backup"
    source.backup(backup)
    clock.advance(days=2)

    target = IntentPayloadStore(tmp_path / "restored", crypto=crypto, now=clock)
    result = target.restore(backup)

    assert result["restored_payloads"] == 0
    assert result["expired_payloads"] == 1
    assert target.status(receipt["payload_ref"], **scope())["status"] == "expired"
    with pytest.raises(IntentPayloadError) as caught:
        target.resolve(
            receipt["payload_ref"],
            owner_id="owner-local",
            workspace_id="workspace:main",
            session_id="session:managed-1",
        )
    assert caught.value.code == "intent_payload_expired"
    disk = b"".join(
        path.read_bytes()
        for path in (tmp_path / "restored").rglob("*")
        if path.is_file()
    )
    assert b"expired backup secret" not in disk


def test_expired_backup_restore_never_decrypts_old_plaintext(
    tmp_path: Path,
    clock: Clock,
    crypto: DeterministicCryptoFake,
) -> None:
    spy = SpyCrypto(crypto)
    source = IntentPayloadStore(tmp_path / "source", crypto=spy, now=clock)
    source.put(request(prompt="must never return to memory", ttl_days=1))
    backup = tmp_path / "backup"
    source.backup(backup)
    spy.decrypt_calls = 0
    clock.advance(days=2)

    target = IntentPayloadStore(tmp_path / "target", crypto=spy, now=clock)
    assert target.restore(backup)["restored_payloads"] == 0
    assert spy.decrypt_calls == 0


def test_restore_failure_never_publishes_a_partial_authority(
    tmp_path: Path,
    clock: Clock,
    crypto: DeterministicCryptoFake,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = IntentPayloadStore(tmp_path / "source", crypto=crypto, now=clock)
    source.put(request())
    backup = tmp_path / "backup"
    source.backup(backup)
    target_root = tmp_path / "target"
    target = IntentPayloadStore(target_root, crypto=crypto, now=clock)
    original_write = IntentPayloadStore._write_or_verify_blob

    def fail_blob(*_: object, **__: object) -> None:
        raise OSError("injected restore failure")

    monkeypatch.setattr(IntentPayloadStore, "_write_or_verify_blob", fail_blob)
    with pytest.raises(IntentPayloadError) as failed:
        target.restore(backup)
    assert failed.value.code == "intent_storage_io_error"
    assert not target_root.exists()

    monkeypatch.setattr(IntentPayloadStore, "_write_or_verify_blob", original_write)
    assert target.restore(backup)["restored_payloads"] == 1
    assert target.reverse_audit()["status"] == "ok"


@pytest.mark.parametrize(
    ("crypto_code", "expected_code", "retryable"),
    [
        ("key_not_found", "intent_payload_corrupt", False),
        ("key_corrupt", "intent_payload_corrupt", False),
        ("crypto_authentication_failed", "intent_payload_corrupt", False),
        ("keychain_unavailable", "intent_crypto_unavailable", True),
        ("crypto_helper_timeout", "intent_crypto_unavailable", True),
    ],
)
def test_decrypt_failures_preserve_integrity_vs_availability_semantics(
    tmp_path: Path,
    clock: Clock,
    crypto: DeterministicCryptoFake,
    crypto_code: str,
    expected_code: str,
    retryable: bool,
) -> None:
    root = tmp_path / "payload-authority"
    healthy = IntentPayloadStore(root, crypto=crypto, now=clock)
    receipt = healthy.put(request())
    failing = IntentPayloadStore(
        root,
        crypto=FailingDecryptCrypto(crypto, crypto_code),
        now=clock,
    )

    with pytest.raises(IntentPayloadError) as caught:
        failing.status(receipt["payload_ref"], **scope())

    assert caught.value.code == expected_code
    assert caught.value.retryable is retryable
    assert "请分析" not in str(caught.value)


def test_encrypt_unavailability_is_retryable_and_suppresses_secret_causes(
    tmp_path: Path,
    clock: Clock,
    crypto: DeterministicCryptoFake,
) -> None:
    failing = IntentPayloadStore(
        tmp_path / "payload-authority",
        crypto=FailingEncryptCrypto(crypto, "keychain_unavailable"),
        now=clock,
    )

    with pytest.raises(IntentPayloadError) as caught:
        failing.put(request(prompt="caller plaintext must stay private"))

    assert caught.value.code == "intent_crypto_unavailable"
    assert caught.value.retryable is True
    assert caught.value.__cause__ is None
    assert "caller plaintext" not in str(caught.value)
    assert "secret prompt" not in str(caught.value)


def test_restore_requires_same_key_and_empty_authority(
    tmp_path: Path,
    clock: Clock,
    crypto: DeterministicCryptoFake,
) -> None:
    source = IntentPayloadStore(tmp_path / "source", crypto=crypto, now=clock)
    source.put(request())
    backup = tmp_path / "backup"
    source.backup(backup)

    wrong_crypto = DeterministicCryptoFake(key=b"other".ljust(32, b"!"), key_id="other-key")
    wrong = IntentPayloadStore(tmp_path / "wrong", crypto=wrong_crypto, now=clock)
    with pytest.raises(IntentPayloadError) as key_error:
        wrong.restore(backup)
    assert key_error.value.code == "intent_restore_key_mismatch"

    nonempty = IntentPayloadStore(tmp_path / "nonempty", crypto=crypto, now=clock)
    nonempty.put(request(client_intent_id="other-intent"))
    with pytest.raises(IntentPayloadError) as nonempty_error:
        nonempty.restore(backup)
    assert nonempty_error.value.code == "intent_restore_requires_empty"


def test_backup_paths_with_a_symlinked_ancestor_fail_closed(
    tmp_path: Path,
    clock: Clock,
    crypto: DeterministicCryptoFake,
) -> None:
    store = IntentPayloadStore(tmp_path / "source", crypto=crypto, now=clock)
    store.put(request())
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)

    with pytest.raises(IntentPayloadError) as caught:
        store.backup(linked_parent / "backup")

    assert caught.value.code == "intent_storage_insecure"


def test_concurrent_exact_puts_converge_on_one_event(
    tmp_path: Path,
    clock: Clock,
    crypto: DeterministicCryptoFake,
) -> None:
    root = tmp_path / "payload-authority"

    def put_once(_: int) -> dict[str, object]:
        return IntentPayloadStore(root, crypto=crypto, now=clock).put(request())

    with ThreadPoolExecutor(max_workers=8) as executor:
        receipts = list(executor.map(put_once, range(16)))

    assert len({receipt["payload_digest"] for receipt in receipts}) == 1
    audit = IntentPayloadStore(root, crypto=crypto, now=clock).reverse_audit()
    assert audit["event_count"] == 1


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX flock")
def test_two_processes_converge_on_one_content_addressed_acceptance(
    tmp_path: Path,
    clock: Clock,
    crypto: DeterministicCryptoFake,
) -> None:
    root = tmp_path / "payload-authority"
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    processes = [
        context.Process(target=put_in_process, args=(str(root), queue))
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(15)
    results = [queue.get(timeout=2), queue.get(timeout=2)]

    assert all(process.exitcode == 0 for process in processes)
    assert [result[0] for result in results] == ["ok", "ok"]
    assert len({result[1] for result in results}) == 1
    assert IntentPayloadStore(root, crypto=crypto, now=clock).reverse_audit()[
        "event_count"
    ] == 1

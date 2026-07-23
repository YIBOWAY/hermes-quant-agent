"""V8-M3 G2 binder: HQA intent/workflow backup≠silent TTL revive.

Re-executes the standing V3 backup/restore + expiry proofs under the V8-M3
campaign id so GAP-14 has an explicit binder at tip. Does not weaken crypto,
does not open public write, does not install V2 durable live.

Uses importlib (not `from tests... import test_*`) so pytest does not re-collect
the source cases under this module's node ids.
"""

from __future__ import annotations

import importlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from hqa.intent_payload_crypto import DeterministicCryptoFake

# Import Clock type only (not test_* names).
_intent = importlib.import_module("tests.test_intent_payloads")
_workflow = importlib.import_module("tests.test_workflow_authority_backup")
Clock = _intent.Clock


@pytest.fixture
def clock() -> Clock:
    # Must match tests/test_intent_payloads.py fixture epoch (hard-coded tombstone dates).
    return Clock(datetime(2026, 7, 19, 12, tzinfo=timezone.utc))


@pytest.fixture
def crypto() -> DeterministicCryptoFake:
    return DeterministicCryptoFake(key=b"intent payload test key".ljust(32, b"!"))


# --- GAP-14 / TC-V8-M1-G02 binders ---


def test_v8_m3_g02_intent_backup_ciphertext_only_and_preserves_expiry(
    tmp_path: Path, clock: Clock, crypto: DeterministicCryptoFake
) -> None:
    _intent.test_backup_contains_only_ciphertext_and_restore_preserves_expiry(
        tmp_path, clock, crypto
    )


def test_v8_m3_g02_intent_expiry_tombstone_no_silent_revive(
    tmp_path: Path, clock: Clock, crypto: DeterministicCryptoFake
) -> None:
    _intent.test_expiry_deletes_ciphertext_leaves_tombstone_and_prevents_revival(
        tmp_path, clock, crypto
    )


def test_v8_m3_g02_old_backup_after_expiry_cannot_resurrect_plaintext(
    tmp_path: Path, clock: Clock, crypto: DeterministicCryptoFake
) -> None:
    _intent.test_restore_of_old_backup_after_expiry_cannot_resurrect_plaintext(
        tmp_path, clock, crypto
    )


def test_v8_m3_g02_expired_backup_restore_never_decrypts(
    tmp_path: Path, clock: Clock, crypto: DeterministicCryptoFake
) -> None:
    _intent.test_expired_backup_restore_never_decrypts_old_plaintext(
        tmp_path, clock, crypto
    )


def test_v8_m3_g02_intent_restore_requires_same_key_and_empty_target(
    tmp_path: Path, clock: Clock, crypto: DeterministicCryptoFake
) -> None:
    _intent.test_restore_requires_same_key_and_empty_authority(tmp_path, clock, crypto)


def test_v8_m3_g02_intent_restore_failure_publishes_nothing(
    tmp_path: Path,
    clock: Clock,
    crypto: DeterministicCryptoFake,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _intent.test_restore_failure_never_publishes_a_partial_authority(
        tmp_path, clock, crypto, monkeypatch
    )


def test_v8_m3_g02_workflow_backup_restore_preserves_digests(tmp_path: Path) -> None:
    _workflow.test_backup_restore_replay_preserves_task_event_and_payload_digests(
        tmp_path
    )


def test_v8_m3_g02_workflow_restore_refuses_nonempty_and_overwrite(
    tmp_path: Path,
) -> None:
    _workflow.test_restore_refuses_nonempty_authority_and_backup_overwrite(tmp_path)


def test_v8_m3_g02_workflow_tamper_fails_closed(tmp_path: Path) -> None:
    _workflow.test_backup_hash_or_record_tampering_fails_closed(tmp_path)


def test_v8_m3_g02_workflow_partial_restore_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _workflow.test_partial_restore_after_journal_publish_is_idempotently_recoverable(
        tmp_path, monkeypatch
    )

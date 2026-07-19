from __future__ import annotations

import json
import sys
from typing import Any, Optional, Sequence

from hqa import config
from hqa.intent_payload_crypto import CryptoFailure, MacOSKeychainCrypto
from hqa.intent_payloads import IntentPayloadError, IntentPayloadStore
from hqa.workflow_authority import WorkflowAuthority, WorkflowAuthorityError
from hqa.workflow_contract import ExpiryTombstoneEvidence


_RETRYABLE_CRYPTO_FAILURES = frozenset(
    {
        "keychain_unavailable",
        "crypto_helper_unavailable",
        "crypto_helper_timeout",
        "crypto_helper_failed",
    }
)
_RETRYABLE_WORKFLOW_FAILURES = frozenset(
    {
        "workflow_storage_unavailable",
        "workflow_durability_unknown",
        "workflow_stale_version",
    }
)


class _RetentionBridgeError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code)


def _emit_error(code: str, retryable: bool) -> None:
    sys.stdout.write(
        json.dumps(
            {
                "error": {
                    "code": code,
                    "message": "intent retention is unavailable",
                    "retryable": retryable,
                }
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )


def _store() -> IntentPayloadStore:
    return IntentPayloadStore(
        config.INTENT_PAYLOAD_DIR,
        crypto=MacOSKeychainCrypto(config.INTENT_PAYLOAD_CRYPTO_HELPER),
    )


def _authority() -> WorkflowAuthority:
    return WorkflowAuthority(
        config.WORKFLOW_AUTHORITY_DIR,
        config.WORKFLOW_OWNER_USER_ID,
    )


def _expiry_evidence(tombstone: dict[str, Any]) -> ExpiryTombstoneEvidence:
    return ExpiryTombstoneEvidence(
        owner_user_id=tombstone["owner_id"],
        workspace_ref=tombstone["workspace_id"],
        managed_session_ref=tombstone["session_id"],
        attempt_ref=tombstone["consumer_ref"],
        payload_ref=tombstone["payload_ref"],
        tombstone_event_ref=tombstone["tombstone_event_ref"],
        tombstone_digest=tombstone["tombstone_digest"],
    )


def _bridge_tombstones(
    store: IntentPayloadStore,
    tombstones: list[dict[str, Any]],
) -> int:
    if not tombstones:
        return 0
    authority = _authority()
    tombstones_by_attempt = {
        tombstone["consumer_ref"]: tombstone for tombstone in tombstones
    }
    if len(tombstones_by_attempt) != len(tombstones):
        raise _RetentionBridgeError("intent_workflow_consume_mismatch")
    evidences = tuple(_expiry_evidence(tombstone) for tombstone in tombstones)
    report = authority.consume_expiry_tombstones(
        evidences,
        limit=len(evidences),
    )
    pending = {evidence.attempt_ref: evidence for evidence in evidences}
    if len(report.receipts) != len(pending):
        raise _RetentionBridgeError("intent_workflow_consume_mismatch")
    acknowledged = 0
    for receipt in report.receipts:
        evidence = pending.pop(receipt.attempt_ref, None)
        if evidence is None or receipt.attempt_ref != evidence.attempt_ref:
            raise _RetentionBridgeError("intent_workflow_consume_mismatch")
        store.acknowledge_expiry(
            payload_ref=evidence.payload_ref,
            tombstone_event_ref=evidence.tombstone_event_ref,
            tombstone_digest=evidence.tombstone_digest,
            consumer_ref=evidence.attempt_ref,
            consumer_event_ref=receipt.event_id,
            consumer_operation_digest=receipt.operation_digest,
            owner_id=evidence.owner_user_id,
            workspace_id=evidence.workspace_ref,
            session_id=evidence.managed_session_ref,
        )
        acknowledged += 1
    if pending:
        raise _RetentionBridgeError("intent_workflow_consume_mismatch")
    return acknowledged


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments:
        _emit_error("intent_invalid_arguments", False)
        return 2
    try:
        store = _store()
        result = store.reconcile_expired(limit=100)
        acknowledged_count = _bridge_tombstones(store, result["tombstones"])
    except IntentPayloadError as exc:
        _emit_error(exc.code, exc.retryable)
        return 1 if exc.retryable else 2
    except CryptoFailure as exc:
        retryable = exc.code in _RETRYABLE_CRYPTO_FAILURES
        _emit_error(exc.code, retryable)
        return 1 if retryable else 2
    except WorkflowAuthorityError as exc:
        retryable = exc.code in _RETRYABLE_WORKFLOW_FAILURES
        _emit_error(exc.code, retryable)
        return 1 if retryable else 2
    except _RetentionBridgeError as exc:
        _emit_error(exc.code, exc.retryable)
        return 1 if exc.retryable else 2
    except (OSError, TypeError, ValueError):
        _emit_error("intent_retention_unavailable", True)
        return 1
    expired_count = len(result["expired"])
    remaining_due = result["remaining_due"]
    pending_tombstone_count = max(
        0,
        result["pending_tombstone_count"] - acknowledged_count,
    )
    if (
        expired_count
        or acknowledged_count
        or remaining_due
        or pending_tombstone_count
    ):
        sys.stdout.write(
            json.dumps(
                {
                    "acknowledged_count": acknowledged_count,
                    "expired_count": expired_count,
                    "pending_tombstone_count": pending_tombstone_count,
                    "remaining_due": remaining_due,
                    "status": "retention_applied",
                },
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

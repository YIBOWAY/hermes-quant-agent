"""Duty-cycle digest intake: hung-sleeve observation or honest failure only.

Seed / preview mark-to-market is not strategy P&L and is rejected.
"""

from __future__ import annotations

from typing import Any, Mapping

OPS_DIGEST_CONTRACT = "hqa.ops_digest/v1"
_DIGEST_LEN = 64
_SEED_KINDS = frozenset(
    {
        "seed_mtm",
        "preview_seed",
        "preview_seed_mtm",
        "preview_seed_fill",
        "hung_observation_demo",
    }
)


class OpsDigestError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _as_mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise OpsDigestError("observation_receipt_required")
    return value


def _looks_like_seed_mtm(payload: Mapping[str, Any]) -> bool:
    kind = str(payload.get("kind") or payload.get("source") or "").strip()
    if kind in _SEED_KINDS:
        return True
    if payload.get("seed_mtm") is True:
        return True
    metadata = payload.get("metadata")
    if isinstance(metadata, Mapping):
        label = str(metadata.get("preview_label") or metadata.get("source") or "")
        if label in _SEED_KINDS:
            return True
        if metadata.get("fossil") is True:
            return True
        if metadata.get("official_observation") is False:
            return True
    if payload.get("preview_label") in _SEED_KINDS:
        return True
    return False


def _require_digest(value: object) -> str:
    cleaned = str(value or "").strip().lower()
    if len(cleaned) != _DIGEST_LEN or any(ch not in "0123456789abcdef" for ch in cleaned):
        raise OpsDigestError("observation_digest_required")
    return cleaned


def ingest_observation(payload: object) -> dict[str, Any]:
    """Accept a hung-sleeve observation or honest failure. Reject seed MTM."""
    document = _as_mapping(payload)
    if _looks_like_seed_mtm(document):
        raise OpsDigestError("seed_mtm_rejected")
    kind = str(document.get("kind") or "").strip()
    if kind == "honest_failure":
        reason = str(document.get("reason") or document.get("code") or "").strip()
        if not reason:
            raise OpsDigestError("honest_failure_reason_required")
        return {
            "contract": OPS_DIGEST_CONTRACT,
            "status": "accepted",
            "kind": "honest_failure",
            "reason": reason,
        }
    if kind == "hung_observation":
        sleeve_id = str(document.get("sleeve_id") or "").strip()
        if not sleeve_id.startswith("sleeve-"):
            raise OpsDigestError("hung_sleeve_required")
        digest = _require_digest(
            document.get("source_digest") or document.get("candidate_code_digest")
        )
        return {
            "contract": OPS_DIGEST_CONTRACT,
            "status": "accepted",
            "kind": "hung_observation",
            "sleeve_id": sleeve_id,
            "source_digest": digest,
        }
    raise OpsDigestError("observation_receipt_required")


__all__ = [
    "OPS_DIGEST_CONTRACT",
    "OpsDigestError",
    "ingest_observation",
]

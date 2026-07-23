"""Official loopback HTTP port for Hermes-owned managed Session resources.

The platform allocates a deterministic ``web_<digest-prefix>`` identity, while
Hermes remains the canonical owner of transcript/history.  This port performs
only Session resource GET/POST operations; it never invokes a provider.

Create and fork are recoverable across a lost HTTP acknowledgement: the exact
deterministic child identity is read back and validated.  A same-ID row with a
different source/parent is an identity conflict, never an idempotent success.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional
from urllib.parse import quote

from hqa.hermes_run_adapter import HermesRunError, UrllibLoopbackHttpTransport

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")
_FORK_POINT_RE = re.compile(r"^message:([1-9][0-9]*)$")
_TITLE_MAX = 500
_MODEL_MAX = 500


@dataclass(frozen=True)
class ManagedSessionReceipt:
    session_id: str
    created: bool
    recovered: bool
    session: Mapping[str, Any]


@dataclass(frozen=True)
class ManagedSessionForkReceipt:
    session_id: str
    source_session_id: str
    resolved_source_session_id: str
    fork_point: str
    created: bool
    recovered: bool
    session: Mapping[str, Any]


def derive_managed_session_id(action_digest: str) -> str:
    """Return the platform/Hermes stable identity for one exact action."""
    if type(action_digest) is not str or _DIGEST_RE.fullmatch(action_digest) is None:
        raise HermesRunError(
            "managed_session_invalid_request",
            "managed Session action digest is invalid",
            http_status=400,
        )
    return f"web_{action_digest[:40]}"


def _require_identifier(value: object, field: str) -> str:
    if type(value) is not str or _SESSION_ID_RE.fullmatch(value) is None:
        raise HermesRunError(
            "managed_session_invalid_request",
            f"{field} is invalid",
            http_status=400,
        )
    return value


def _optional_bounded_string(
    value: object,
    *,
    field: str,
    maximum: int,
) -> Optional[str]:
    if value is None:
        return None
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > maximum
        or not value.isprintable()
    ):
        raise HermesRunError(
            "managed_session_invalid_request",
            f"{field} is invalid",
            http_status=400,
        )
    return value.strip()


class OfficialHermesManagedSessionPort:
    """Hermes Session creation/fork with exact identity recovery."""

    def __init__(self, *, transport: UrllibLoopbackHttpTransport) -> None:
        self._transport = transport

    def ensure(
        self,
        *,
        action_digest: str,
        session_id: str,
        title: Optional[str] = None,
        model: Optional[str] = None,
    ) -> ManagedSessionReceipt:
        expected_id = derive_managed_session_id(action_digest)
        requested_id = _require_identifier(session_id, "session_id")
        if requested_id != expected_id:
            raise HermesRunError(
                "managed_session_identity_mismatch",
                "managed Session identity does not match its action digest",
                http_status=409,
            )
        normalized_title = _optional_bounded_string(
            title,
            field="title",
            maximum=_TITLE_MAX,
        )
        normalized_model = _optional_bounded_string(
            model,
            field="model",
            maximum=_MODEL_MAX,
        )

        try:
            existing = self._get_session(requested_id)
        except HermesRunError as exc:
            if not _is_not_found(exc):
                raise
        else:
            self._require_managed_identity(existing, requested_id)
            return ManagedSessionReceipt(
                session_id=requested_id,
                created=False,
                recovered=False,
                session=existing,
            )

        body: dict[str, Any] = {"id": requested_id}
        if normalized_title is not None:
            body["title"] = normalized_title
        if normalized_model is not None:
            body["model"] = normalized_model
        try:
            _, payload = self._transport.post_json("/api/sessions", body)
        except HermesRunError as exc:
            if exc.code not in {"session_exists", "transport_error"}:
                raise
            try:
                recovered = self._get_session(requested_id)
            except HermesRunError as recovery_exc:
                if exc.code == "transport_error" and _is_not_found(recovery_exc):
                    # The request may not have reached Hermes. Preserve the
                    # retryable transport outcome; the deterministic identity
                    # makes the caller's exact retry safe.
                    raise exc
                raise
            self._require_managed_identity(recovered, requested_id)
            return ManagedSessionReceipt(
                session_id=requested_id,
                created=False,
                recovered=True,
                session=recovered,
            )

        created = self._session_from_document(payload)
        self._require_managed_identity(created, requested_id)
        return ManagedSessionReceipt(
            session_id=requested_id,
            created=True,
            recovered=False,
            session=created,
        )

    def fork(
        self,
        *,
        action_digest: str,
        source_session_id: str,
        session_id: str,
        fork_point: str,
        title: Optional[str] = None,
    ) -> ManagedSessionForkReceipt:
        expected_id = derive_managed_session_id(action_digest)
        source_id = _require_identifier(source_session_id, "source_session_id")
        child_id = _require_identifier(session_id, "session_id")
        if child_id != expected_id or child_id == source_id:
            raise HermesRunError(
                "managed_session_identity_mismatch",
                "managed Session identity does not match its fork action",
                http_status=409,
            )
        if type(fork_point) is not str:
            match = None
        else:
            match = _FORK_POINT_RE.fullmatch(fork_point)
        if match is None:
            raise HermesRunError(
                "managed_session_invalid_request",
                "fork_point must be an exact message:<id> cursor",
                http_status=400,
            )
        normalized_title = _optional_bounded_string(
            title,
            field="title",
            maximum=_TITLE_MAX,
        )

        # These reads are provider-free.  The messages endpoint also resolves a
        # compressed source to the active Hermes lineage tip, which is the
        # exact parent the upstream fork implementation records.
        source_before = self._get_session(source_id)
        resolved_source_id, message_ids = self._get_resolved_messages(source_id)
        if int(match.group(1)) not in message_ids:
            raise HermesRunError(
                "fork_point_not_found",
                "fork_point does not identify an active source message",
                http_status=409,
            )

        body: dict[str, Any] = {
            "id": child_id,
            "fork_point": fork_point,
            "preserve_source": True,
        }
        if normalized_title is not None:
            body["title"] = normalized_title

        recovered = False
        try:
            _, payload = self._transport.post_json(
                f"/api/sessions/{quote(source_id, safe='')}/fork",
                body,
            )
        except HermesRunError as exc:
            if exc.code not in {"session_exists", "transport_error"}:
                raise
            try:
                child = self._get_session(child_id)
            except HermesRunError as recovery_exc:
                if exc.code == "transport_error" and _is_not_found(recovery_exc):
                    raise exc
                raise
            recovered = True
        else:
            child = self._session_from_document(payload)
            if (
                payload.get("source_session_id") != source_id
                or payload.get("resolved_source_session_id") != resolved_source_id
                or payload.get("fork_point") != fork_point
                or payload.get("preserve_source") is not True
            ):
                raise HermesRunError(
                    "managed_session_identity_mismatch",
                    "Hermes fork receipt substituted immutable lineage",
                    http_status=409,
                )

        self._require_managed_identity(
            child,
            child_id,
            parent_session_id=resolved_source_id,
        )
        source_after = self._get_session(source_id)
        if source_after != source_before:
            raise HermesRunError(
                "managed_session_source_changed",
                "Hermes fork mutated the source Session",
                http_status=409,
            )
        return ManagedSessionForkReceipt(
            session_id=child_id,
            source_session_id=source_id,
            resolved_source_session_id=resolved_source_id,
            fork_point=fork_point,
            created=not recovered,
            recovered=recovered,
            session=child,
        )

    def _get_session(self, session_id: str) -> Mapping[str, Any]:
        payload = self._transport.get_json(
            f"/api/sessions/{quote(session_id, safe='')}"
        )
        return self._session_from_document(payload)

    def _get_resolved_messages(self, session_id: str) -> tuple[str, set[int]]:
        payload = self._transport.get_json(
            f"/api/sessions/{quote(session_id, safe='')}/messages"
        )
        resolved = payload.get("session_id")
        rows = payload.get("data")
        if (
            type(resolved) is not str
            or _SESSION_ID_RE.fullmatch(resolved) is None
            or not isinstance(rows, list)
        ):
            raise HermesRunError(
                "managed_session_invalid_receipt",
                "Hermes Session messages receipt is invalid",
                http_status=502,
            )
        message_ids: set[int] = set()
        for row in rows:
            if not isinstance(row, Mapping):
                raise HermesRunError(
                    "managed_session_invalid_receipt",
                    "Hermes Session messages receipt is invalid",
                    http_status=502,
                )
            value = row.get("id")
            if type(value) is int and value > 0:
                message_ids.add(value)
        return resolved, message_ids

    @staticmethod
    def _session_from_document(document: Mapping[str, Any]) -> Mapping[str, Any]:
        if not isinstance(document, Mapping):
            raise HermesRunError(
                "managed_session_invalid_receipt",
                "Hermes Session receipt is invalid",
                http_status=502,
            )
        session = document.get("session")
        if not isinstance(session, Mapping):
            raise HermesRunError(
                "managed_session_invalid_receipt",
                "Hermes Session receipt is invalid",
                http_status=502,
            )
        return dict(session)

    @staticmethod
    def _require_managed_identity(
        session: Mapping[str, Any],
        expected_id: str,
        *,
        parent_session_id: Optional[str] = None,
    ) -> None:
        if (
            session.get("id") != expected_id
            or session.get("source") != "api_server"
            or (
                parent_session_id is not None
                and session.get("parent_session_id") != parent_session_id
            )
        ):
            raise HermesRunError(
                "managed_session_identity_mismatch",
                "Hermes Session receipt substituted immutable identity",
                http_status=409,
            )


def _is_not_found(exc: HermesRunError) -> bool:
    return exc.http_status == 404 and exc.code in {
        "session_not_found",
        "run_not_found",
    }


__all__ = [
    "ManagedSessionForkReceipt",
    "ManagedSessionReceipt",
    "OfficialHermesManagedSessionPort",
    "derive_managed_session_id",
]

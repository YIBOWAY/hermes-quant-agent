"""Metadata-only coordinator for the Agent v0.2 paper-research vertical.

Hermes calls this module with one operation name and one strict JSON object on
stdin.  The coordinator advances the existing :class:`WorkflowAuthority` and
registers the matching browser Gate with the platform through the trusted
``quant-system hermes paper-gate`` subprocess seam.  It never imports platform
code, executes a provider, places an order, or commits Git changes. The sole
body-bearing operation writes the current user prompt directly to the existing
encrypted IntentPayloadStore; workflow, platform, argv, env, logs, and stdout
remain body-free.

The workflow is deliberately split at every human decision:

* ``prepare-intent`` writes the current managed-session user body to the
  encrypted :class:`IntentPayloadStore` and returns metadata only;
* ``start-plan`` records the already-observed planning Run and stops at plan
  confirmation;
* ``confirm-plan`` records one exact human plan confirmation;
* ``open-gate1`` and ``open-gate2`` only register browser challenges bound to
  planning Attempt 1;
* ``open-gate3`` records the already-completed Futu final Run on a new Attempt
  2 and registers the promotion-review challenge;
* ``complete-after-human-commit`` read-verifies the exact reviewed commit, then
  and only then closes Attempt 2 and the Task.

All HQA mutations use content-addressed operation IDs.  A subprocess timeout
during a platform registration is reported as an unknown outcome; callers must
reconcile by the exact ``gate_id`` rather than inventing a replacement.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional, Protocol
from uuid import UUID

from hqa import config, factor_repro, quant_cli
from hqa.intent_payload_crypto import CryptoFailure, MacOSKeychainCrypto
from hqa.intent_payloads import IntentPayloadError, IntentPayloadStore
from hqa.workflow_authority import WorkflowAuthority, WorkflowAuthorityError
from hqa.workflow_contract import (
    CompleteAttempt,
    CompleteTask,
    ConfirmPlan,
    ContinueResearch,
    EnterDomainGate,
    LinkResult,
    ObserveProviderEvidence,
    ObserveRun,
    ObserveSubmission,
    ProposePlan,
    RequestPlanConfirmation,
    StartResearch,
    WorkflowContractError,
)

_CONTRACT = "agent-v0.2-paper-research-cli/v1"
_PLATFORM_CONTRACT = "agent-v0.2-paper-gate-cli/v1"
_STDIN_LIMIT = 64_000
_PREPARE_STDIN_LIMIT = 2_000_000
_STDOUT_LIMIT = 256_000
_MAX_PREPARE_PROMPT_BYTES = 262_144
_PLATFORM_TIMEOUT_SECONDS = 30.0
_SAFE_PLATFORM_BASE_ENV = frozenset(
    {
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "PATH",
        "PYTHONIOENCODING",
        "PYTHONUTF8",
        "SSL_CERT_FILE",
        "TMPDIR",
        "TZ",
    }
)
_SAFE_PLATFORM_DATABASE_ENV = frozenset(
    {
        "QS_DATABASE_CONNECT_TIMEOUT_SECONDS",
        "QS_DATABASE_ENABLED",
        "QS_DATABASE_URL",
    }
)
_SAFE_PLATFORM_HERMES_ENV = frozenset(
    {
        "QS_HERMES_GATEWAY_API_KEY_FILE",
        "QS_HERMES_GATEWAY_BASE_URL",
        "QS_HERMES_GATEWAY_ENABLED",
        "QS_HERMES_GATEWAY_MAX_RESPONSE_BYTES",
        "QS_HERMES_GATEWAY_RUNTIME_ROOT",
        "QS_HERMES_GATEWAY_TIMEOUT_SECONDS",
    }
)
_RETRYABLE_CRYPTO_FAILURES = frozenset(
    {
        "keychain_unavailable",
        "crypto_helper_unavailable",
        "crypto_helper_timeout",
        "crypto_helper_failed",
    }
)
_OPERATIONS = frozenset(
    {
        "prepare-intent",
        "start-plan",
        "confirm-plan",
        "open-gate1",
        "open-gate2",
        "open-gate3",
        "complete-after-human-commit",
    }
)
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_WORKFLOW_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_REF_PATTERNS = {
    "task_ref": re.compile(r"^task:[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"),
    "attempt_ref": re.compile(r"^attempt:[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"),
    "hqa_gate_ref": re.compile(r"^gate:[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"),
    "hqa_run_ref": re.compile(r"^run:[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"),
    "provider_evidence_ref": re.compile(
        r"^provider-evidence:[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$"
    ),
    "result_ref": re.compile(r"^result:[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$"),
    "payload_ref": re.compile(r"^payload:sha256:[0-9a-f]{64}$"),
}
_GATE1_CONFIRMATION_RE = re.compile(r"^gate1-[0-9a-f]{32}$")
_FINAL_RECEIPT_RE = re.compile(r"^backtest-[0-9a-f]{32}$")
_PROMOTION_RE = re.compile(r"^promo-[0-9a-f]{32}(?:-r(?:[2-9]|[1-9][0-9]+))?$")

_REGISTER_FIELDS = {
    "gate_id",
    "gate_kind",
    "workspace_id",
    "task_ref",
    "expected_task_version",
    "platform_session_id",
    "hermes_session_id",
    "attempt_ref",
    "hqa_gate_ref",
    "command_id",
    "hermes_run_id",
    "hqa_run_ref",
    "provider_evidence_ref",
    "subject_command_id",
    "subject_hermes_run_id",
    "subject_run_attestation_ref",
    "subject_run_attestation_digest",
    "final_backtest_provider",
    "final_backtest_receipt_digest",
    "final_backtest_config_ref",
    "final_backtest_config_digest",
    "final_backtest_summary_ref",
    "final_backtest_summary_digest",
    "final_backtest_report_ref",
    "final_backtest_report_digest",
    "parent_gate_id",
    "source_file_ref",
    "universe",
    "reviewed_source_sha256",
    "gate1_confirmation_id",
    "candidate_id",
    "expected_digest",
    "expected_status",
    "final_backtest_receipt_id",
    "base_commit",
}
_COMPLETE_FIELDS = {
    "gate_id",
    "workspace_id",
    "hqa_completion_receipt_ref",
    "hqa_completion_receipt_digest",
    "completion_evidence",
}
_COMPLETION_EVIDENCE_FIELDS = {
    "schema_version",
    "task_ref",
    "task_version",
    "task_status",
    "task_terminal_outcome",
    "plan_version",
    "plan_digest",
    "plan_confirmation_note_digest",
    "attempt_ref",
    "attempt_status",
    "attempt_terminal_outcome",
    "domain_gate_ref",
    "domain_gate_outcome",
    "hqa_run_ref",
    "provider_evidence_ref",
    "subject_command_id",
    "subject_hermes_run_id",
    "subject_run_attestation_ref",
    "subject_run_attestation_digest",
    "final_backtest_provider",
    "final_backtest_receipt_digest",
    "final_backtest_config_ref",
    "final_backtest_config_digest",
    "final_backtest_summary_ref",
    "final_backtest_summary_digest",
    "final_backtest_report_ref",
    "final_backtest_report_digest",
    "promotion_id",
    "reviewed_commit",
    "candidate_id",
    "candidate_digest",
    "final_backtest_receipt_id",
    "base_commit",
    "attempt_completion_operation_id",
    "attempt_completion_event_id",
    "task_completion_operation_id",
    "task_completion_event_id",
    "workflow_audit_status",
    "workflow_audit_ref",
    "workflow_audit_digest",
}
_FINAL_BACKTEST_FIELDS = {
    "final_backtest_provider",
    "final_backtest_receipt_digest",
    "final_backtest_config_ref",
    "final_backtest_config_digest",
    "final_backtest_summary_ref",
    "final_backtest_summary_digest",
    "final_backtest_report_ref",
    "final_backtest_report_digest",
}
_FINAL_BACKTEST_DIGEST_FIELDS = {
    "final_backtest_receipt_digest",
    "final_backtest_config_digest",
    "final_backtest_summary_digest",
    "final_backtest_report_digest",
}
_FINAL_BACKTEST_REF_FIELDS = {
    "final_backtest_config_ref",
    "final_backtest_summary_ref",
    "final_backtest_report_ref",
}
_RUNTIME_SELECTORS = {
    "command_id": "HERMES_PLATFORM_COMMAND_ID",
    "platform_session_id": "HERMES_PLATFORM_SESSION_ID",
    "hermes_run_id": "HERMES_PLATFORM_RUN_ID",
    "hermes_session_id": "HERMES_PLATFORM_MANAGED_SESSION_ID",
}


class _InputError(ValueError):
    pass


class _OperationError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = bool(retryable)


class _RegistryError(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        retryable: bool,
        not_found: bool = False,
        outcome_unknown: bool = False,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = bool(retryable)
        self.not_found = bool(not_found)
        self.outcome_unknown = bool(outcome_unknown)


class PaperGateRegistryPort(Protocol):
    def attest(self, document: Mapping[str, Any]) -> dict[str, Any]: ...

    def register(self, document: Mapping[str, Any]) -> dict[str, Any]: ...

    def show(self, gate_id: str) -> dict[str, Any]: ...

    def list(self, workspace_id: str) -> list[dict[str, Any]]: ...

    def complete(self, document: Mapping[str, Any]) -> dict[str, Any]: ...


class IntentPayloadMetadataPort(Protocol):
    def put(self, request: dict[str, Any]) -> dict[str, Any]: ...

    def status(
        self,
        payload_ref: str,
        *,
        owner_id: str,
        workspace_id: str,
        session_id: str,
    ) -> dict[str, Any]: ...

    def bind_consumer(
        self,
        *,
        payload_ref: str,
        consumer_ref: str,
        owner_id: str,
        workspace_id: str,
        session_id: str,
    ) -> dict[str, Any]: ...


def _payload_store() -> IntentPayloadStore:
    return IntentPayloadStore(
        config.INTENT_PAYLOAD_DIR,
        crypto=MacOSKeychainCrypto(config.INTENT_PAYLOAD_CRYPTO_HELPER),
    )


def _managed_session_policy(
    *,
    platform_session_id: str,
    hermes_session_id: str,
) -> dict[str, str]:
    """Return a body-free reference to the immutable managed-session policy."""

    return {
        "hermes_session_id": hermes_session_id,
        "platform_session_ref": f"session:{platform_session_id}",
        "policy_authority": "platform_session_registry",
        "schema_version": "agent-v0.2-managed-session-policy-ref/v1",
    }


def _managed_session_policy_digest(
    *,
    platform_session_id: str,
    hermes_session_id: str,
) -> str:
    return hashlib.sha256(
        _canonical_bytes(
            _managed_session_policy(
                platform_session_id=platform_session_id,
                hermes_session_id=hermes_session_id,
            )
        )
    ).hexdigest()


def _active_payload(
    store: IntentPayloadMetadataPort,
    authority: object,
    *,
    payload_ref: str,
    workspace_id: str,
    platform_session_id: str,
    hermes_session_id: str,
    expected_kind: str,
) -> dict[str, Any]:
    owner_id = getattr(authority, "owner_user_id", None)
    if type(owner_id) is not str or not owner_id:
        raise _OperationError(
            "paper_research_payload_owner_unavailable",
            retryable=False,
        )
    scoped_workspace = f"workspace:{workspace_id}"
    scoped_session = f"session:{platform_session_id}"
    status = store.status(
        payload_ref,
        owner_id=owner_id,
        workspace_id=scoped_workspace,
        session_id=scoped_session,
    )
    exact_fields = {
        "schema_version",
        "payload_ref",
        "payload_digest",
        "kind",
        "owner_id",
        "workspace_id",
        "session_id",
        "client_intent_id",
        "provider_policy_digest",
        "created_at",
        "expires_at",
        "ttl_days",
        "status",
        "consumer_ref",
    }
    try:
        created_at = datetime.fromisoformat(
            str(status.get("created_at", "")).removesuffix("Z") + "+00:00"
        )
        expires_at = datetime.fromisoformat(
            str(status.get("expires_at", "")).removesuffix("Z") + "+00:00"
        )
    except ValueError as exc:
        raise _OperationError(
            "paper_research_payload_not_active",
            retryable=False,
        ) from exc
    ttl_days = status.get("ttl_days")
    consumer_ref = status.get("consumer_ref")
    now = datetime.now(timezone.utc)
    if (
        set(status) != exact_fields
        or status.get("schema_version") != "2.0"
        or status.get("status") != "active"
        or status.get("payload_ref") != payload_ref
        or status.get("payload_digest") != payload_ref.removeprefix("payload:sha256:")
        or status.get("owner_id") != owner_id
        or status.get("workspace_id") != scoped_workspace
        or status.get("session_id") != scoped_session
        or status.get("kind") != expected_kind
        or type(status.get("client_intent_id")) is not str
        or _ID_RE.fullmatch(str(status["client_intent_id"])) is None
        or type(status.get("provider_policy_digest")) is not str
        or _DIGEST_RE.fullmatch(str(status["provider_policy_digest"])) is None
        or status.get("provider_policy_digest")
        != _managed_session_policy_digest(
            platform_session_id=platform_session_id,
            hermes_session_id=hermes_session_id,
        )
        or type(status.get("created_at")) is not str
        or not str(status["created_at"]).endswith("Z")
        or type(status.get("expires_at")) is not str
        or not str(status["expires_at"]).endswith("Z")
        or isinstance(ttl_days, bool)
        or not isinstance(ttl_days, int)
        or not 1 <= ttl_days <= 30
        or created_at.tzinfo is None
        or expires_at.tzinfo is None
        or created_at + timedelta(days=ttl_days) != expires_at
        or created_at > now
        or expires_at <= now
        or (
            consumer_ref is not None
            and (
                type(consumer_ref) is not str
                or re.fullmatch(r"attempt:[0-9a-f]{64}", consumer_ref) is None
            )
        )
    ):
        raise _OperationError(
            "paper_research_payload_not_active",
            retryable=False,
        )
    return status


def _require_payload_consumer_replay(
    authority: object,
    payload: Mapping[str, Any],
    *,
    operation_id: str,
) -> None:
    consumer_ref = payload.get("consumer_ref")
    if consumer_ref is not None:
        operation_reader = getattr(authority, "operation_receipt", None)
        receipt = (
            operation_reader(operation_id)
            if callable(operation_reader)
            else None
        )
        if (
            receipt is None
            or getattr(receipt, "attempt_ref", None) != consumer_ref
        ):
            raise _OperationError(
                "paper_research_payload_already_consumed",
                retryable=False,
            )


def _bind_payload_attempt(
    store: IntentPayloadMetadataPort,
    authority: object,
    *,
    payload: Mapping[str, Any],
    attempt_ref: str,
) -> None:
    try:
        bound = store.bind_consumer(
            payload_ref=str(payload["payload_ref"]),
            consumer_ref=attempt_ref,
            owner_id=str(getattr(authority, "owner_user_id")),
            workspace_id=str(payload["workspace_id"]),
            session_id=str(payload["session_id"]),
        )
    except (IntentPayloadError, OSError) as exc:
        raise _OperationError(
            "paper_research_payload_binding_unknown",
            retryable=True,
        ) from exc
    if (
        set(bound)
        != {
            "schema_version",
            "payload_ref",
            "payload_digest",
            "kind",
            "owner_id",
            "workspace_id",
            "session_id",
            "client_intent_id",
            "provider_policy_digest",
            "created_at",
            "expires_at",
            "ttl_days",
            "status",
            "consumer_ref",
        }
        or bound.get("schema_version") != "2.0"
        or bound.get("status") != "active"
        or bound.get("payload_ref") != payload["payload_ref"]
        or bound.get("payload_digest") != payload["payload_digest"]
        or bound.get("kind") != payload["kind"]
        or bound.get("owner_id") != payload["owner_id"]
        or bound.get("workspace_id") != payload["workspace_id"]
        or bound.get("session_id") != payload["session_id"]
        or bound.get("provider_policy_digest") != payload["provider_policy_digest"]
        or bound.get("consumer_ref") != attempt_ref
        or bound.get("expires_at") != payload["expires_at"]
    ):
        raise _OperationError(
            "paper_research_payload_binding_mismatch",
            retryable=False,
        )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise _InputError("duplicate JSON field")
        document[key] = value
    return document


def _reject_constant(_value: str) -> None:
    raise _InputError("non-finite JSON number")


def _canonical_bytes(document: Mapping[str, Any]) -> bytes:
    try:
        raw = json.dumps(
            dict(document),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8", errors="strict")
    except (RecursionError, TypeError, UnicodeError, ValueError) as exc:
        raise _InputError("invalid JSON value") from exc
    if not raw or len(raw) > _STDOUT_LIMIT:
        raise _InputError("JSON value exceeds output quota")
    return raw


def _strict_json(
    raw: bytes,
    *,
    maximum: int = _STDIN_LIMIT,
) -> dict[str, Any]:
    if not raw or len(raw) > maximum:
        raise _InputError("empty or oversized JSON")
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except _InputError:
        raise
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        ValueError,
    ) as exc:
        raise _InputError("invalid JSON") from exc
    if not isinstance(value, dict):
        raise _InputError("JSON must be an object")
    return value


def _read_request(*, maximum: int = _STDIN_LIMIT) -> dict[str, Any]:
    stream = getattr(sys.stdin, "buffer", sys.stdin)
    raw = stream.read(maximum + 1)
    if isinstance(raw, str):
        try:
            raw = raw.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise _InputError("invalid JSON") from exc
    return _strict_json(raw, maximum=maximum)


def _emit(document: Mapping[str, Any]) -> None:
    raw = _canonical_bytes(document)
    stream = getattr(sys.stdout, "buffer", None)
    if stream is None:
        sys.stdout.write(raw.decode("utf-8") + "\n")
    else:
        stream.write(raw + b"\n")


def _require_fields(document: Mapping[str, Any], fields: set[str]) -> None:
    if set(document) != fields:
        raise _InputError("request fields do not match operation schema")


def _runtime_request(
    request: Mapping[str, Any],
    *,
    operation_fields: set[str],
) -> dict[str, Any]:
    """Fill the four runtime selectors from Hermes and reject substitution.

    These variables are convenience selectors supplied per Run by the Hermes
    API server.  They are not authorization: HQA still checks its Workflow
    authority and the platform still binds all four to the canonical command.
    """

    allowed = operation_fields | set(_RUNTIME_SELECTORS)
    if set(request) - allowed:
        raise _InputError("request fields do not match operation schema")
    document = dict(request)
    for field, variable in _RUNTIME_SELECTORS.items():
        value = os.environ.get(variable)
        if type(value) is not str or not value:
            raise _InputError(f"{variable} is required")
        if field == "command_id":
            raw = value.removeprefix("command:")
            try:
                parsed = UUID(raw)
            except ValueError as exc:
                raise _InputError(f"{variable} is invalid") from exc
            if str(parsed) != raw:
                raise _InputError(f"{variable} is invalid")
            value = raw
            supplied = document.get(field)
            if supplied is not None:
                if type(supplied) is not str:
                    raise _InputError(f"{field} is invalid")
                supplied = supplied.removeprefix("command:")
                if supplied != value:
                    raise _InputError(f"{field} does not match Hermes runtime")
        else:
            if _ID_RE.fullmatch(value) is None:
                raise _InputError(f"{variable} is invalid")
            supplied = document.get(field)
            if supplied is not None and supplied != value:
                raise _InputError(f"{field} does not match Hermes runtime")
        document[field] = value
    return document


def _text(
    document: Mapping[str, Any],
    field: str,
    *,
    maximum: int = 2_000,
) -> str:
    value = document.get(field)
    if (
        type(value) is not str
        or not value.strip()
        or len(value.encode("utf-8")) > maximum
        or not value.isprintable()
    ):
        raise _InputError(f"{field} is invalid")
    return value.strip()


def _prompt(document: Mapping[str, Any]) -> str:
    value = document.get("prompt")
    if type(value) is not str or not value.strip():
        raise _InputError("prompt is invalid")
    try:
        size = len(value.encode("utf-8", errors="strict"))
    except UnicodeEncodeError as exc:
        raise _InputError("prompt is invalid") from exc
    if size > _MAX_PREPARE_PROMPT_BYTES:
        raise _InputError("prompt is invalid")
    return value


def _identifier(
    document: Mapping[str, Any],
    field: str,
    *,
    workflow: bool = False,
) -> str:
    value = document.get(field)
    pattern = _WORKFLOW_ID_RE if workflow else _ID_RE
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise _InputError(f"{field} is invalid")
    return value


def _command_id(document: Mapping[str, Any]) -> str:
    value = document.get("command_id")
    if type(value) is not str:
        raise _InputError("command_id is invalid")
    raw = value.removeprefix("command:")
    try:
        parsed = UUID(raw)
    except ValueError as exc:
        raise _InputError("command_id is invalid") from exc
    if str(parsed) != raw:
        raise _InputError("command_id is invalid")
    return raw


def _ref(document: Mapping[str, Any], field: str) -> str:
    value = document.get(field)
    pattern = _REF_PATTERNS[field]
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise _InputError(f"{field} is invalid")
    return value


def _digest(document: Mapping[str, Any], field: str) -> str:
    value = document.get(field)
    if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
        raise _InputError(f"{field} is invalid")
    return value


def _positive_version(document: Mapping[str, Any]) -> int:
    value = document.get("expected_task_version")
    if type(value) is not int or not 1 <= value <= 2**63 - 1:
        raise _InputError("expected_task_version is invalid")
    return value


def _plan_version(document: Mapping[str, Any]) -> int:
    value = document.get("plan_version")
    if type(value) is not int or not 1 <= value <= 2**31 - 1:
        raise _InputError("plan_version is invalid")
    return value


def _absolute_path(document: Mapping[str, Any], field: str) -> str:
    value = document.get(field)
    if (
        type(value) is not str
        or not value.startswith("/")
        or len(value.encode("utf-8")) > 4_096
        or not value.isprintable()
    ):
        raise _InputError(f"{field} is invalid")
    return value


def _commit(document: Mapping[str, Any], field: str) -> str:
    value = document.get(field)
    if type(value) is not str or _COMMIT_RE.fullmatch(value) is None:
        raise _InputError(f"{field} is invalid")
    return value


def _authority() -> WorkflowAuthority:
    return WorkflowAuthority(
        config.WORKFLOW_AUTHORITY_DIR,
        config.WORKFLOW_OWNER_USER_ID,
    )


def _operation_id(
    outer_operation_id: str,
    phase: str,
    binding: Mapping[str, Any],
) -> str:
    digest = hashlib.sha256(
        _canonical_bytes(
            {
                "binding": dict(binding),
                "outer_operation_id": outer_operation_id,
                "phase": phase,
            }
        )
    ).hexdigest()
    return f"paper-flow-{phase}-{digest[:32]}"


def _receipt(value: object) -> dict[str, Any]:
    if is_dataclass(value) and not isinstance(value, type):
        document = asdict(value)
    else:
        document = {
            field: getattr(value, field)
            for field in (
                "operation_id",
                "operation_digest",
                "event_id",
                "task_ref",
                "task_version",
                "attempt_ref",
                "replayed",
            )
        }
    return document


def _workflow_task_audit(
    authority: object,
    *,
    task_ref: str,
    task_version: int,
    terminal_event_id: str,
    terminal_operation_id: str,
) -> tuple[str, str, str]:
    """Return one stable, content-addressed audit for a terminal Task.

    ``reverse_audit`` proves the whole authority is internally consistent at
    the time of attestation.  Its global projection digest is deliberately not
    embedded in the completion receipt: unrelated Tasks may append while a
    timed-out Platform registrar is being reconciled.  A terminal Task cannot
    append again, so its complete event chain is the stable retry identity.
    """

    global_audit = authority.reverse_audit()  # type: ignore[attr-defined]
    if (
        set(global_audit)
        != {
            "schema_version",
            "status",
            "owner_user_id",
            "event_count",
            "task_count",
            "operation_count",
            "binding_counts",
            "last_record_sha256",
            "projection_sha256",
        }
        or global_audit.get("status") != "consistent"
    ):
        raise _OperationError(
            "paper_research_workflow_audit_mismatch",
            retryable=False,
        )
    page = authority.events(task_ref, limit=1_000)  # type: ignore[attr-defined]
    events = tuple(getattr(page, "events", ()))
    if (
        getattr(page, "has_more", True)
        or len(events) != task_version
        or [getattr(event, "task_version", None) for event in events]
        != list(range(1, task_version + 1))
        or not events
        or getattr(events[-1], "event_id", None) != terminal_event_id
        or getattr(events[-1], "operation_id", None) != terminal_operation_id
        or getattr(events[-1], "event_type", None) != "task_completed"
    ):
        raise _OperationError(
            "paper_research_workflow_audit_mismatch",
            retryable=False,
        )
    event_documents = [
        {
            "sequence": event.sequence,
            "event_id": event.event_id,
            "operation_id": event.operation_id,
            "operation_digest": event.operation_digest,
            "task_ref": event.task_ref,
            "task_version": event.task_version,
            "event_type": event.event_type,
            "occurred_at": event.occurred_at,
            "data": dict(event.data),
        }
        for event in events
    ]
    task_audit = {
        "schema_version": "agent-v0.2-workflow-task-audit/v1",
        "status": "consistent",
        "task_ref": task_ref,
        "task_version": task_version,
        "terminal_event_id": terminal_event_id,
        "terminal_operation_id": terminal_operation_id,
        "events": event_documents,
    }
    digest = hashlib.sha256(_canonical_bytes(task_audit)).hexdigest()
    return "consistent", f"workflow-audit:{digest}", digest


def _attempt(snapshot: object, attempt_ref: str) -> object:
    matches = [
        value
        for value in getattr(snapshot, "attempts")
        if getattr(value, "attempt_ref") == attempt_ref
    ]
    if len(matches) != 1:
        raise _OperationError(
            "paper_research_attempt_binding_mismatch",
            retryable=False,
        )
    return matches[0]


def _require_task_identity(
    snapshot: object,
    *,
    workspace_id: str,
    platform_session_id: str,
    task_ref: str,
) -> None:
    if (
        getattr(snapshot, "workspace_ref", None) != f"workspace:{workspace_id}"
        or getattr(snapshot, "managed_session_ref", None)
        != f"session:{platform_session_id}"
        or getattr(snapshot, "task_ref", None) != task_ref
    ):
        raise _OperationError(
            "paper_research_task_binding_mismatch",
            retryable=False,
        )


def _registration(**values: Any) -> dict[str, Any]:
    if set(values) != _REGISTER_FIELDS:
        raise AssertionError("internal paper Gate registration is incomplete")
    return values


_ATTESTATION_FIELDS = {
    "schema_version",
    "mode",
    "workspace_id",
    "platform_session_id",
    "hermes_session_id",
    "resolved_hermes_session_id",
    "command_id",
    "hermes_run_id",
    "command_state",
    "hqa_run_ref",
    "actual_model",
    "actual_provider",
    "output_digest",
    "hermes_runtime_instance_id",
    "hermes_runtime_started_at",
    "terminal_event_ref",
    "evidence_digest",
    "attestation_ref",
    "provider_evidence_ref",
}
_ATTESTATION_DERIVED_FIELDS = {
    "attestation_ref",
    "evidence_digest",
    "hermes_runtime_instance_id",
    "hermes_runtime_started_at",
    "provider_evidence_ref",
}


def _attest_run(
    registry: PaperGateRegistryPort,
    *,
    mode: str,
    workspace_id: str,
    platform_session_id: str,
    hermes_session_id: str,
    command_id: str,
    hermes_run_id: str,
) -> dict[str, Any]:
    request = {
        "mode": mode,
        "workspace_id": workspace_id,
        "platform_session_id": platform_session_id,
        "hermes_session_id": hermes_session_id,
        "command_id": command_id,
        "hermes_run_id": hermes_run_id,
    }
    attestation = registry.attest(request)
    if set(attestation) != _ATTESTATION_FIELDS:
        raise _OperationError(
            "paper_research_run_attestation_invalid",
            retryable=False,
        )
    for field, expected in request.items():
        if attestation.get(field) != expected:
            raise _OperationError(
                "paper_research_run_attestation_binding_mismatch",
                retryable=False,
            )
    resolved_session_id = attestation.get("resolved_hermes_session_id")
    if (
        type(resolved_session_id) is not str
        or _ID_RE.fullmatch(resolved_session_id) is None
    ):
        raise _OperationError(
            "paper_research_run_attestation_invalid",
            retryable=False,
        )
    digest = attestation.get("evidence_digest")
    if (
        type(digest) is not str
        or _DIGEST_RE.fullmatch(digest) is None
        or hashlib.sha256(
            _canonical_bytes(
                {
                    key: value
                    for key, value in attestation.items()
                    if key not in _ATTESTATION_DERIVED_FIELDS
                }
            )
        ).hexdigest()
        != digest
        or attestation.get("attestation_ref")
        != f"paper-run-attestation:{digest}"
    ):
        raise _OperationError(
            "paper_research_run_attestation_invalid",
            retryable=False,
        )
    if mode == "invocation":
        if (
            attestation.get("command_state") not in {"delivered", "succeeded"}
            or any(
                attestation.get(field) is not None
                for field in (
                    "hqa_run_ref",
                    "actual_model",
                    "actual_provider",
                    "output_digest",
                    "hermes_runtime_instance_id",
                    "hermes_runtime_started_at",
                    "terminal_event_ref",
                    "provider_evidence_ref",
                )
            )
        ):
            raise _OperationError(
                "paper_research_invocation_attestation_invalid",
                retryable=False,
            )
    elif (
        mode != "subject"
        or attestation.get("command_state") != "succeeded"
        or type(attestation.get("hqa_run_ref")) is not str
        or _REF_PATTERNS["hqa_run_ref"].fullmatch(attestation["hqa_run_ref"])
        is None
        or type(attestation.get("provider_evidence_ref")) is not str
        or _REF_PATTERNS["provider_evidence_ref"].fullmatch(
            attestation["provider_evidence_ref"]
        )
        is None
        or attestation.get("provider_evidence_ref")
        != f"provider-evidence:paper-run-{digest}"
        or type(attestation.get("output_digest")) is not str
        or _DIGEST_RE.fullmatch(attestation["output_digest"]) is None
        or any(
            type(attestation.get(field)) is not str or not attestation[field]
            for field in (
                "actual_model",
                "actual_provider",
                "hermes_runtime_instance_id",
                "hermes_runtime_started_at",
                "terminal_event_ref",
            )
        )
    ):
        raise _OperationError(
            "paper_research_subject_attestation_invalid",
            retryable=False,
        )
    return dict(attestation)


def _attest_invocation(
    registry: PaperGateRegistryPort,
    request: Mapping[str, Any],
    *,
    workspace_id: str,
) -> dict[str, Any]:
    return _attest_run(
        registry,
        mode="invocation",
        workspace_id=workspace_id,
        platform_session_id=_identifier(request, "platform_session_id"),
        hermes_session_id=_identifier(request, "hermes_session_id"),
        command_id=_command_id(request),
        hermes_run_id=_identifier(request, "hermes_run_id"),
    )


def _attest_subject(
    registry: PaperGateRegistryPort,
    request: Mapping[str, Any],
    *,
    workspace_id: str,
) -> dict[str, Any]:
    subject_command_id = _command_id(
        {"command_id": request.get("subject_command_id")}
    )
    subject_run_id = _identifier(request, "subject_hermes_run_id")
    if (
        subject_command_id == request.get("command_id")
        or subject_run_id == request.get("hermes_run_id")
    ):
        raise _OperationError(
            "paper_research_subject_is_current_invocation",
            retryable=False,
        )
    return _attest_run(
        registry,
        mode="subject",
        workspace_id=workspace_id,
        platform_session_id=_identifier(request, "platform_session_id"),
        hermes_session_id=_identifier(request, "hermes_session_id"),
        command_id=subject_command_id,
        hermes_run_id=subject_run_id,
    )


def _read_final_backtest_evidence(
    receipt_id: str,
    candidate_id: str,
    candidate_digest: str,
) -> dict[str, Any]:
    record = factor_repro.require_final_backtest_receipt(
        gate_dir=config.FACTOR_GATE1_DIR,
        experiment_output_dir=config.FACTOR_EXPERIMENT_OUTPUT_DIR,
        receipt_id=receipt_id,
        candidate_id=candidate_id,
        manifest_digest=candidate_digest,
    )
    if record.get("provider") != "futu":
        raise _OperationError(
            "paper_research_final_provider_mismatch",
            retryable=False,
        )
    evidence = {
        "final_backtest_provider": "futu",
        "final_backtest_receipt_digest": hashlib.sha256(
            _canonical_bytes(record)
        ).hexdigest(),
        "final_backtest_config_ref": record.get("config_path"),
        "final_backtest_config_digest": record.get("config_sha256"),
        "final_backtest_summary_ref": record.get("agent_summary_path"),
        "final_backtest_summary_digest": record.get("agent_summary_sha256"),
        "final_backtest_report_ref": record.get("report"),
        "final_backtest_report_digest": record.get("report_sha256"),
    }
    if any(
        type(value) is not str or not value
        for value in evidence.values()
    ) or any(
        _DIGEST_RE.fullmatch(str(evidence[field])) is None
        for field in (
            "final_backtest_receipt_digest",
            "final_backtest_config_digest",
            "final_backtest_summary_digest",
            "final_backtest_report_digest",
        )
    ):
        raise _OperationError(
            "paper_research_final_receipt_invalid",
            retryable=False,
        )
    return evidence


def _validate_final_backtest_evidence(
    evidence: Mapping[str, Any],
    *,
    error_code: str,
) -> dict[str, Any]:
    if (
        set(evidence) != _FINAL_BACKTEST_FIELDS
        or evidence.get("final_backtest_provider") != "futu"
        or any(
            type(evidence.get(field)) is not str
            or _DIGEST_RE.fullmatch(str(evidence[field])) is None
            for field in _FINAL_BACKTEST_DIGEST_FIELDS
        )
        or any(
            type(evidence.get(field)) is not str
            or not str(evidence[field]).startswith("/")
            or not str(evidence[field]).isprintable()
            or len(str(evidence[field]).encode("utf-8")) > 4_096
            for field in _FINAL_BACKTEST_REF_FIELDS
        )
    ):
        raise _OperationError(error_code, retryable=False)
    return dict(evidence)


class SubprocessPaperGateRegistry:
    """Bounded, no-shell client for the platform paper-Gate registry CLI."""

    def __init__(
        self,
        *,
        executable: Path = config.QUANT_SYSTEM_BIN,
        cwd: Path = config.AIQP_DIR,
        timeout_seconds: float = _PLATFORM_TIMEOUT_SECONDS,
    ) -> None:
        self._executable = Path(executable)
        self._cwd = Path(cwd)
        self._timeout_seconds = float(timeout_seconds)

    def _call(
        self,
        operation: str,
        document: Mapping[str, Any],
        *,
        mutation: bool,
    ) -> dict[str, Any]:
        raw = _canonical_bytes(document)
        child_env = {
            key: value
            for key, value in os.environ.items()
            if key in _SAFE_PLATFORM_BASE_ENV
            or key in _SAFE_PLATFORM_DATABASE_ENV
            or key in _SAFE_PLATFORM_HERMES_ENV
        }
        # This metadata-only registrar must never inherit provider/model/API
        # credentials and must never turn a CLI call into schema mutation.
        child_env["QS_DATABASE_AUTO_MIGRATE"] = "false"
        try:
            completed = subprocess.run(
                [
                    str(self._executable),
                    "hermes",
                    "paper-gate",
                    operation,
                ],
                cwd=str(self._cwd),
                input=raw,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self._timeout_seconds,
                check=False,
                shell=False,
                env=child_env,
            )
        except subprocess.TimeoutExpired as exc:
            raise _RegistryError(
                (
                    "paper_research_platform_outcome_unknown"
                    if mutation
                    else "paper_research_platform_unavailable"
                ),
                retryable=not mutation,
                outcome_unknown=mutation,
            ) from exc
        except (OSError, subprocess.SubprocessError) as exc:
            raise _RegistryError(
                "paper_research_platform_unavailable",
                retryable=True,
            ) from exc
        if (
            not completed.stdout
            or len(completed.stdout) > _STDOUT_LIMIT
            or b"\n" in completed.stdout.rstrip(b"\n")
        ):
            raise _RegistryError(
                (
                    "paper_research_platform_outcome_unknown"
                    if mutation
                    else "paper_research_platform_invalid_response"
                ),
                retryable=not mutation,
                outcome_unknown=mutation,
            )
        try:
            response = _strict_json(completed.stdout.strip())
        except _InputError as exc:
            raise _RegistryError(
                (
                    "paper_research_platform_outcome_unknown"
                    if mutation
                    else "paper_research_platform_invalid_response"
                ),
                retryable=not mutation,
                outcome_unknown=mutation,
            ) from exc
        payload_field = {
            "attest-run": "attestation",
            "complete": "completion",
            "list": "gates",
        }.get(operation, "gate")
        expected_outer = {
            "contract",
            "operation",
            "ok",
            payload_field,
        }
        if response.get("ok") is False:
            if set(response) != {
                "contract",
                "operation",
                "ok",
                "error_code",
                "message",
            }:
                raise _RegistryError(
                    "paper_research_platform_invalid_response",
                    retryable=False,
                )
            error_code = response.get("error_code")
            if type(error_code) is not str:
                raise _RegistryError(
                    "paper_research_platform_invalid_response",
                    retryable=False,
                )
            raise _RegistryError(
                error_code,
                retryable=False,
                not_found=error_code
                in {
                    "paper_gate_not_found",
                    "paper_gate_authority_not_found",
                },
            )
        if (
            completed.returncode != 0
            or set(response) != expected_outer
            or response.get("contract") != _PLATFORM_CONTRACT
            or response.get("operation") != operation
            or response.get("ok") is not True
        ):
            raise _RegistryError(
                (
                    "paper_research_platform_outcome_unknown"
                    if mutation
                    else "paper_research_platform_invalid_response"
                ),
                retryable=False,
                outcome_unknown=mutation,
            )
        return response

    def attest(self, document: Mapping[str, Any]) -> dict[str, Any]:
        response = self._call("attest-run", document, mutation=False)
        attestation = response["attestation"]
        if not isinstance(attestation, dict):
            raise _RegistryError(
                "paper_research_platform_invalid_response",
                retryable=False,
            )
        return attestation

    def register(self, document: Mapping[str, Any]) -> dict[str, Any]:
        if set(document) != _REGISTER_FIELDS:
            raise _InputError("platform registration is incomplete")
        response = self._call("register", document, mutation=True)
        gate = response["gate"]
        if not isinstance(gate, dict):
            raise _RegistryError(
                "paper_research_platform_outcome_unknown",
                retryable=False,
                outcome_unknown=True,
            )
        return gate

    def show(self, gate_id: str) -> dict[str, Any]:
        response = self._call("show", {"gate_id": gate_id}, mutation=False)
        gate = response["gate"]
        if not isinstance(gate, dict):
            raise _RegistryError(
                "paper_research_platform_invalid_response",
                retryable=False,
            )
        return gate

    def list(self, workspace_id: str) -> list[dict[str, Any]]:
        response = self._call(
            "list",
            {"workspace_id": workspace_id},
            mutation=False,
        )
        gates = response["gates"]
        if not isinstance(gates, list) or not all(
            isinstance(gate, dict) for gate in gates
        ):
            raise _RegistryError(
                "paper_research_platform_invalid_response",
                retryable=False,
            )
        return gates

    def complete(self, document: Mapping[str, Any]) -> dict[str, Any]:
        if set(document) != _COMPLETE_FIELDS:
            raise _InputError("platform completion is incomplete")
        response = self._call("complete", document, mutation=True)
        completion = response["completion"]
        if not isinstance(completion, dict):
            raise _RegistryError(
                "paper_research_platform_outcome_unknown",
                retryable=False,
                outcome_unknown=True,
            )
        return completion


def _verify_gate(
    gate: Mapping[str, Any],
    registration: Mapping[str, Any],
    *,
    allowed_statuses: set[str],
) -> dict[str, Any]:
    for field, expected in registration.items():
        observed = (
            gate.get("registered_expected_status")
            if field == "expected_status" and "registered_expected_status" in gate
            else gate.get(field)
        )
        if observed != expected:
            raise _OperationError(
                "paper_research_platform_gate_binding_mismatch",
                retryable=False,
            )
    status = gate.get("status")
    if type(status) is not str or status not in allowed_statuses:
        raise _OperationError(
            "paper_research_platform_gate_state_mismatch",
            retryable=False,
        )
    return dict(gate)


def _stored_registration(gate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        field: (
            gate.get("registered_expected_status")
            if field == "expected_status"
            and "registered_expected_status" in gate
            else gate.get(field)
        )
        for field in _REGISTER_FIELDS
    }


def _show_or_none(
    port: PaperGateRegistryPort,
    gate_id: str,
) -> Optional[dict[str, Any]]:
    try:
        return port.show(gate_id)
    except _RegistryError as exc:
        if exc.not_found:
            return None
        raise


def _register_or_recover(
    port: PaperGateRegistryPort,
    registration: Mapping[str, Any],
) -> tuple[dict[str, Any], bool]:
    existing = _show_or_none(port, str(registration["gate_id"]))
    if existing is not None:
        return (
            _verify_gate(
                existing,
                registration,
                allowed_statuses={
                    "pending",
                    "confirmed",
                    "reviewed",
                    "prepared",
                },
            ),
            True,
        )
    gate = port.register(registration)
    return (
        _verify_gate(gate, registration, allowed_statuses={"pending"}),
        False,
    )


def _gate_output(
    *,
    operation: str,
    gate: Mapping[str, Any],
    replayed: bool,
    snapshot: object,
) -> dict[str, Any]:
    return {
        "contract": _CONTRACT,
        "operation": operation,
        "ok": True,
        "gate": dict(gate),
        "platform_registration_replayed": replayed,
        "task_ref": getattr(snapshot, "task_ref"),
        "task_version": getattr(snapshot, "version"),
        "workflow_state": getattr(snapshot, "state"),
    }


def _prepare_intent(
    request: Mapping[str, Any],
    *,
    authority_factory: Callable[[], object],
    registry: PaperGateRegistryPort,
    payload_store: IntentPayloadMetadataPort,
) -> dict[str, Any]:
    fields = {
        "workspace_id",
        "kind",
        "prompt",
        *_RUNTIME_SELECTORS,
    }
    request = _runtime_request(
        request,
        operation_fields=fields - set(_RUNTIME_SELECTORS),
    )
    _require_fields(request, fields)
    workspace_id = _identifier(request, "workspace_id")
    platform_session_id = _identifier(request, "platform_session_id")
    hermes_session_id = _identifier(request, "hermes_session_id")
    command_id = _command_id(request)
    hermes_run_id = _identifier(request, "hermes_run_id")
    kind = request.get("kind")
    if kind not in {"research_start", "research_continue"}:
        raise _InputError("kind is invalid")
    prompt = _prompt(request)

    # This read-only attestation binds all caller-visible selectors to one
    # durable command in the current managed Hermes Session. It is not a
    # StartResearch/ContinueResearch mutation surface.
    _attest_invocation(
        registry,
        request,
        workspace_id=workspace_id,
    )
    authority = authority_factory()
    owner_id = getattr(authority, "owner_user_id", None)
    if type(owner_id) is not str or _ID_RE.fullmatch(owner_id) is None:
        raise _OperationError(
            "paper_research_payload_owner_unavailable",
            retryable=False,
        )
    provider_policy = _managed_session_policy(
        platform_session_id=platform_session_id,
        hermes_session_id=hermes_session_id,
    )
    client_intent_id = f"paper-intent:{command_id}"
    try:
        receipt = payload_store.put(
            {
                "schema_version": "2.0",
                "kind": kind,
                "owner_id": owner_id,
                "workspace_id": f"workspace:{workspace_id}",
                "session_id": f"session:{platform_session_id}",
                "client_intent_id": client_intent_id,
                "provider_policy": provider_policy,
                "prompt": prompt,
                "ttl_days": 7,
            }
        )
    except IntentPayloadError as exc:
        if exc.code == "intent_idempotency_conflict":
            code = "paper_research_intent_conflict"
            retryable = False
        else:
            code = (
                "paper_research_intent_store_unavailable"
                if exc.retryable
                else "paper_research_intent_rejected"
            )
            retryable = bool(exc.retryable)
        raise _OperationError(code, retryable=retryable) from exc

    exact_fields = {
        "schema_version",
        "payload_ref",
        "payload_digest",
        "kind",
        "owner_id",
        "workspace_id",
        "session_id",
        "client_intent_id",
        "provider_policy_digest",
        "created_at",
        "expires_at",
        "ttl_days",
        "status",
        "consumer_ref",
    }
    try:
        created_at = datetime.fromisoformat(
            str(receipt.get("created_at", "")).removesuffix("Z") + "+00:00"
        )
        expires_at = datetime.fromisoformat(
            str(receipt.get("expires_at", "")).removesuffix("Z") + "+00:00"
        )
    except ValueError as exc:
        raise _OperationError(
            "paper_research_intent_receipt_invalid",
            retryable=False,
        ) from exc
    payload_digest = receipt.get("payload_digest")
    provider_policy_digest = _managed_session_policy_digest(
        platform_session_id=platform_session_id,
        hermes_session_id=hermes_session_id,
    )
    if (
        set(receipt) != exact_fields
        or receipt.get("schema_version") != "2.0"
        or type(payload_digest) is not str
        or _DIGEST_RE.fullmatch(payload_digest) is None
        or receipt.get("payload_ref") != f"payload:sha256:{payload_digest}"
        or receipt.get("kind") != kind
        or receipt.get("owner_id") != owner_id
        or receipt.get("workspace_id") != f"workspace:{workspace_id}"
        or receipt.get("session_id") != f"session:{platform_session_id}"
        or receipt.get("client_intent_id") != client_intent_id
        or receipt.get("provider_policy_digest") != provider_policy_digest
        or type(receipt.get("created_at")) is not str
        or not str(receipt["created_at"]).endswith("Z")
        or type(receipt.get("expires_at")) is not str
        or not str(receipt["expires_at"]).endswith("Z")
        or created_at.tzinfo is None
        or expires_at.tzinfo is None
        or created_at + timedelta(days=7) != expires_at
        or created_at > datetime.now(timezone.utc)
        or expires_at <= datetime.now(timezone.utc)
        or receipt.get("ttl_days") != 7
        or receipt.get("status") != "active"
        or receipt.get("consumer_ref") is not None
    ):
        raise _OperationError(
            "paper_research_intent_receipt_invalid",
            retryable=False,
        )
    return {
        "contract": _CONTRACT,
        "operation": "prepare-intent",
        "ok": True,
        "payload_ref": receipt["payload_ref"],
        "payload_digest": payload_digest,
        "kind": kind,
        "owner_id": owner_id,
        "workspace_id": workspace_id,
        "platform_session_id": platform_session_id,
        "hermes_session_id": hermes_session_id,
        "command_id": command_id,
        "hermes_run_id": hermes_run_id,
        "client_intent_id": client_intent_id,
        "provider_policy_digest": provider_policy_digest,
        "created_at": receipt["created_at"],
        "expires_at": receipt["expires_at"],
        "ttl_days": 7,
        "status": "active",
    }


def _start_plan(
    request: Mapping[str, Any],
    *,
    authority_factory: Callable[[], object],
    registry: PaperGateRegistryPort,
    payload_store: IntentPayloadMetadataPort,
) -> dict[str, Any]:
    fields = {
        "operation_id",
        "workspace_id",
        "platform_session_id",
        "payload_ref",
        "command_id",
        "hermes_run_id",
        "hermes_session_id",
        "subject_command_id",
        "subject_hermes_run_id",
        "plan_version",
        "plan_digest",
    }
    request = _runtime_request(
        request,
        operation_fields=fields - set(_RUNTIME_SELECTORS),
    )
    _require_fields(request, fields)
    outer = _identifier(request, "operation_id", workflow=True)
    workspace_id = _identifier(request, "workspace_id")
    platform_session_id = _identifier(request, "platform_session_id")
    payload_ref = _ref(request, "payload_ref")
    _command_id(request)
    _identifier(request, "hermes_run_id")
    plan_version = _plan_version(request)
    plan_digest = _digest(request, "plan_digest")
    _attest_invocation(
        registry,
        request,
        workspace_id=workspace_id,
    )
    subject = _attest_subject(
        registry,
        request,
        workspace_id=workspace_id,
    )
    run_ref = str(subject["hqa_run_ref"])
    provider_ref = str(subject["provider_evidence_ref"])
    if subject["output_digest"] != plan_digest:
        raise _OperationError(
            "paper_research_plan_digest_not_subject_output",
            retryable=False,
        )
    authority = authority_factory()
    payload = _active_payload(
        payload_store,
        authority,
        payload_ref=payload_ref,
        workspace_id=workspace_id,
        platform_session_id=platform_session_id,
        hermes_session_id=str(request["hermes_session_id"]),
        expected_kind="research_start",
    )
    intent_expires_at = str(payload["expires_at"])
    binding = {
        "workspace_id": workspace_id,
        "platform_session_id": platform_session_id,
        "payload_ref": payload_ref,
        "intent_expires_at": intent_expires_at,
        "subject_command_id": subject["command_id"],
        "subject_hermes_run_id": subject["hermes_run_id"],
        "hermes_session_id": request["hermes_session_id"],
        "hqa_run_ref": run_ref,
        "provider_evidence_ref": provider_ref,
        "subject_run_attestation_ref": subject["attestation_ref"],
        "subject_run_attestation_digest": subject["evidence_digest"],
        "plan_version": plan_version,
        "plan_digest": plan_digest,
    }
    start_operation_id = _operation_id(outer, "start", binding)
    _require_payload_consumer_replay(
        authority,
        payload,
        operation_id=start_operation_id,
    )
    receipt = authority.apply(  # type: ignore[attr-defined]
        StartResearch(
            operation_id=start_operation_id,
            workspace_ref=f"workspace:{workspace_id}",
            managed_session_ref=f"session:{platform_session_id}",
            payload_ref=payload_ref,
            intent_expires_at=intent_expires_at,
        )
    )
    task_ref = receipt.task_ref
    attempt_ref = receipt.attempt_ref
    if type(attempt_ref) is not str:
        raise _OperationError(
            "paper_research_missing_attempt",
            retryable=False,
        )
    _bind_payload_attempt(
        payload_store,
        authority,
        payload=payload,
        attempt_ref=attempt_ref,
    )
    command_ref = f"command:{subject['command_id']}"
    receipt = authority.apply(  # type: ignore[attr-defined]
        ObserveSubmission(
            _operation_id(outer, "plan-submit", binding),
            task_ref,
            receipt.task_version,
            attempt_ref,
            command_ref,
        )
    )
    receipt = authority.apply(  # type: ignore[attr-defined]
        ObserveRun(
            _operation_id(outer, "plan-run", binding),
            task_ref,
            receipt.task_version,
            attempt_ref,
            command_ref,
            run_ref,
        )
    )
    receipt = authority.apply(  # type: ignore[attr-defined]
        ObserveProviderEvidence(
            _operation_id(outer, "plan-provider", binding),
            task_ref,
            receipt.task_version,
            attempt_ref,
            run_ref,
            provider_ref,
        )
    )
    receipt = authority.apply(  # type: ignore[attr-defined]
        ProposePlan(
            _operation_id(outer, "plan-propose", binding),
            task_ref,
            receipt.task_version,
            plan_version,
            plan_digest,
            run_ref,
            True,
        )
    )
    receipt = authority.apply(  # type: ignore[attr-defined]
        RequestPlanConfirmation(
            _operation_id(outer, "plan-request-confirmation", binding),
            task_ref,
            receipt.task_version,
            plan_version,
            plan_digest,
        )
    )
    receipt = authority.apply(  # type: ignore[attr-defined]
        CompleteAttempt(
            _operation_id(outer, "plan-complete", binding),
            task_ref,
            receipt.task_version,
            attempt_ref,
            "completed",
            run_ref,
            provider_ref,
        )
    )
    snapshot = authority.snapshot(task_ref)  # type: ignore[attr-defined]
    _require_task_identity(
        snapshot,
        workspace_id=workspace_id,
        platform_session_id=platform_session_id,
        task_ref=task_ref,
    )
    attempt = _attempt(snapshot, attempt_ref)
    if (
        getattr(snapshot, "state") != "awaiting_plan_confirmation"
        or getattr(snapshot, "plan_version") != plan_version
        or getattr(snapshot, "plan_digest") != plan_digest
        or getattr(attempt, "terminal_outcome") != "completed"
        or getattr(attempt, "run_ref") != run_ref
        or provider_ref not in getattr(attempt, "provider_evidence_refs")
    ):
        raise _OperationError(
            "paper_research_plan_evidence_mismatch",
            retryable=False,
        )
    return {
        "contract": _CONTRACT,
        "operation": "start-plan",
        "ok": True,
        "task_ref": task_ref,
        "attempt_ref": attempt_ref,
        "task_version": snapshot.version,
        "workflow_state": snapshot.state,
        "plan_version": snapshot.plan_version,
        "plan_digest": snapshot.plan_digest,
        "hqa_run_ref": run_ref,
        "provider_evidence_ref": provider_ref,
        "subject_run_attestation_ref": subject["attestation_ref"],
        "subject_run_attestation_digest": subject["evidence_digest"],
        "replayed": bool(receipt.replayed),
    }


def _confirm_plan(
    request: Mapping[str, Any],
    *,
    authority_factory: Callable[[], object],
    registry: PaperGateRegistryPort,
) -> dict[str, Any]:
    fields = {
        "operation_id",
        "task_ref",
        "expected_task_version",
        "plan_version",
        "plan_digest",
        "confirmation_note",
        *_RUNTIME_SELECTORS,
    }
    request = _runtime_request(
        request,
        operation_fields=fields - set(_RUNTIME_SELECTORS),
    )
    _require_fields(request, fields)
    outer = _identifier(request, "operation_id", workflow=True)
    task_ref = _ref(request, "task_ref")
    expected = _positive_version(request)
    plan_version = _plan_version(request)
    plan_digest = _digest(request, "plan_digest")
    note = _text(request, "confirmation_note", maximum=4_000)
    authority = authority_factory()
    before = authority.snapshot(task_ref)  # type: ignore[attr-defined]
    workspace_ref = getattr(before, "workspace_ref", None)
    if (
        type(workspace_ref) is not str
        or not workspace_ref.startswith("workspace:")
    ):
        raise _OperationError(
            "paper_research_task_binding_mismatch",
            retryable=False,
        )
    workspace_id = workspace_ref.removeprefix("workspace:")
    _attest_invocation(
        registry,
        request,
        workspace_id=workspace_id,
    )
    binding = {
        "task_ref": task_ref,
        "expected_task_version": expected,
        "plan_version": plan_version,
        "plan_digest": plan_digest,
        "confirmation_note_digest": hashlib.sha256(note.encode("utf-8")).hexdigest(),
    }
    receipt = authority.apply(  # type: ignore[attr-defined]
        ConfirmPlan(
            _operation_id(outer, "confirm-plan", binding),
            task_ref,
            expected,
            plan_version,
            plan_digest,
            note,
        )
    )
    snapshot = authority.snapshot(task_ref)  # type: ignore[attr-defined]
    if (
        snapshot.state != "awaiting_formula_confirmation"
        or snapshot.plan_version != plan_version
        or snapshot.plan_digest != plan_digest
        or snapshot.plan_confirmation_note_digest != binding["confirmation_note_digest"]
        or snapshot.managed_session_ref != f"session:{request['platform_session_id']}"
    ):
        raise _OperationError(
            "paper_research_plan_confirmation_mismatch",
            retryable=False,
        )
    return {
        "contract": _CONTRACT,
        "operation": "confirm-plan",
        "ok": True,
        "task_ref": task_ref,
        "task_version": snapshot.version,
        "workflow_state": snapshot.state,
        "plan_version": plan_version,
        "plan_digest": plan_digest,
        "confirmation_note_digest": binding["confirmation_note_digest"],
        "replayed": bool(receipt.replayed),
    }


def _open_gate1(
    request: Mapping[str, Any],
    *,
    authority_factory: Callable[[], object],
    registry: PaperGateRegistryPort,
) -> dict[str, Any]:
    fields = {
        "operation_id",
        "gate_id",
        "workspace_id",
        "platform_session_id",
        "hermes_session_id",
        "task_ref",
        "expected_task_version",
        "attempt_ref",
        "command_id",
        "hermes_run_id",
        "hqa_gate_ref",
        "source_file_ref",
        "universe",
        "reviewed_source_sha256",
    }
    request = _runtime_request(
        request,
        operation_fields=fields - set(_RUNTIME_SELECTORS),
    )
    _require_fields(request, fields)
    _identifier(request, "operation_id", workflow=True)
    gate_id = _identifier(request, "gate_id", workflow=True)
    workspace_id = _identifier(request, "workspace_id")
    platform_session_id = _identifier(request, "platform_session_id")
    task_ref = _ref(request, "task_ref")
    expected = _positive_version(request)
    attempt_ref = _ref(request, "attempt_ref")
    command_id = _command_id(request)
    hermes_run_id = _identifier(request, "hermes_run_id")
    hqa_gate_ref = _ref(request, "hqa_gate_ref")
    source_file_ref = _absolute_path(request, "source_file_ref")
    universe = _text(request, "universe")
    source_digest = _digest(request, "reviewed_source_sha256")
    _attest_invocation(registry, request, workspace_id=workspace_id)
    authority = authority_factory()
    snapshot = authority.snapshot(task_ref)  # type: ignore[attr-defined]
    _require_task_identity(
        snapshot,
        workspace_id=workspace_id,
        platform_session_id=platform_session_id,
        task_ref=task_ref,
    )
    attempt = _attempt(snapshot, attempt_ref)
    registration = _registration(
        gate_id=gate_id,
        gate_kind="gate1",
        workspace_id=workspace_id,
        task_ref=task_ref,
        expected_task_version=expected,
        platform_session_id=platform_session_id,
        hermes_session_id=request["hermes_session_id"],
        attempt_ref=attempt_ref,
        hqa_gate_ref=hqa_gate_ref,
        command_id=command_id,
        hermes_run_id=hermes_run_id,
        hqa_run_ref=None,
        provider_evidence_ref=None,
        subject_command_id=None,
        subject_hermes_run_id=None,
        subject_run_attestation_ref=None,
        subject_run_attestation_digest=None,
        final_backtest_provider=None,
        final_backtest_receipt_digest=None,
        final_backtest_config_ref=None,
        final_backtest_config_digest=None,
        final_backtest_summary_ref=None,
        final_backtest_summary_digest=None,
        final_backtest_report_ref=None,
        final_backtest_report_digest=None,
        parent_gate_id=None,
        source_file_ref=source_file_ref,
        universe=universe,
        reviewed_source_sha256=source_digest,
        gate1_confirmation_id=None,
        candidate_id=None,
        expected_digest=None,
        expected_status=None,
        final_backtest_receipt_id=None,
        base_commit=None,
    )
    existing = _show_or_none(registry, gate_id)
    if existing is None:
        if (
            snapshot.version != expected
            or snapshot.state != "awaiting_formula_confirmation"
            or getattr(attempt, "attempt_number") != 1
            or getattr(attempt, "terminal_outcome") != "completed"
            or snapshot.gate1_ref is not None
        ):
            raise _OperationError(
                "paper_research_gate1_precondition_failed",
                retryable=False,
            )
        gate = registry.register(registration)
        gate = _verify_gate(gate, registration, allowed_statuses={"pending"})
        replayed = False
    else:
        stored_registration = _stored_registration(existing)
        replay_fields = _REGISTER_FIELDS - {
            "command_id",
            "hermes_run_id",
            "gate1_confirmation_id",
        }
        if any(
            stored_registration[field] != registration[field]
            for field in replay_fields
        ):
            raise _OperationError(
                "paper_research_platform_gate_binding_mismatch",
                retryable=False,
            )
        gate = _verify_gate(
            existing,
            stored_registration,
            allowed_statuses={"pending", "confirmed"},
        )
        replayed = True
    return _gate_output(
        operation="open-gate1",
        gate=gate,
        replayed=replayed,
        snapshot=snapshot,
    )


def _parent_gate(
    registry: PaperGateRegistryPort,
    *,
    parent_gate_id: str,
    expected_kind: str,
    expected_status: str,
    exact: Mapping[str, Any],
) -> dict[str, Any]:
    gate = registry.show(parent_gate_id)
    if (
        gate.get("gate_id") != parent_gate_id
        or gate.get("gate_kind") != expected_kind
        or gate.get("status") != expected_status
        or any(gate.get(field) != value for field, value in exact.items())
    ):
        raise _OperationError(
            "paper_research_parent_gate_mismatch",
            retryable=False,
        )
    return gate


def _open_gate2(
    request: Mapping[str, Any],
    *,
    authority_factory: Callable[[], object],
    registry: PaperGateRegistryPort,
) -> dict[str, Any]:
    fields = {
        "operation_id",
        "gate_id",
        "parent_gate_id",
        "workspace_id",
        "platform_session_id",
        "hermes_session_id",
        "task_ref",
        "expected_task_version",
        "attempt_ref",
        "command_id",
        "hermes_run_id",
        "hqa_gate_ref",
        "reviewed_source_sha256",
        "gate1_confirmation_id",
        "candidate_id",
        "expected_digest",
        "expected_status",
    }
    request = _runtime_request(
        request,
        operation_fields=fields - set(_RUNTIME_SELECTORS),
    )
    _require_fields(request, fields)
    _identifier(request, "operation_id", workflow=True)
    gate_id = _identifier(request, "gate_id", workflow=True)
    parent_gate_id = _identifier(request, "parent_gate_id", workflow=True)
    workspace_id = _identifier(request, "workspace_id")
    platform_session_id = _identifier(request, "platform_session_id")
    task_ref = _ref(request, "task_ref")
    expected = _positive_version(request)
    attempt_ref = _ref(request, "attempt_ref")
    command_id = _command_id(request)
    hermes_run_id = _identifier(request, "hermes_run_id")
    hqa_gate_ref = _ref(request, "hqa_gate_ref")
    source_digest = _digest(request, "reviewed_source_sha256")
    confirmation_id = request.get("gate1_confirmation_id")
    if (
        type(confirmation_id) is not str
        or _GATE1_CONFIRMATION_RE.fullmatch(confirmation_id) is None
    ):
        raise _InputError("gate1_confirmation_id is invalid")
    candidate_id = _identifier(request, "candidate_id", workflow=True)
    candidate_digest = _digest(request, "expected_digest")
    if request.get("expected_status") != "pending":
        raise _InputError("expected_status must be pending")
    _attest_invocation(registry, request, workspace_id=workspace_id)
    _parent_gate(
        registry,
        parent_gate_id=parent_gate_id,
        expected_kind="gate1",
        expected_status="confirmed",
        exact={
            "workspace_id": workspace_id,
            "platform_session_id": platform_session_id,
            "hermes_session_id": request["hermes_session_id"],
            "task_ref": task_ref,
            "attempt_ref": attempt_ref,
            "hqa_gate_ref": hqa_gate_ref,
            "reviewed_source_sha256": source_digest,
            "gate1_confirmation_id": confirmation_id,
        },
    )
    authority = authority_factory()
    snapshot = authority.snapshot(task_ref)  # type: ignore[attr-defined]
    _require_task_identity(
        snapshot,
        workspace_id=workspace_id,
        platform_session_id=platform_session_id,
        task_ref=task_ref,
    )
    attempt = _attempt(snapshot, attempt_ref)
    registration = _registration(
        gate_id=gate_id,
        gate_kind="gate2",
        workspace_id=workspace_id,
        task_ref=task_ref,
        expected_task_version=expected,
        platform_session_id=platform_session_id,
        hermes_session_id=request["hermes_session_id"],
        attempt_ref=attempt_ref,
        hqa_gate_ref=hqa_gate_ref,
        command_id=command_id,
        hermes_run_id=hermes_run_id,
        hqa_run_ref=None,
        provider_evidence_ref=None,
        subject_command_id=None,
        subject_hermes_run_id=None,
        subject_run_attestation_ref=None,
        subject_run_attestation_digest=None,
        final_backtest_provider=None,
        final_backtest_receipt_digest=None,
        final_backtest_config_ref=None,
        final_backtest_config_digest=None,
        final_backtest_summary_ref=None,
        final_backtest_summary_digest=None,
        final_backtest_report_ref=None,
        final_backtest_report_digest=None,
        parent_gate_id=parent_gate_id,
        source_file_ref=None,
        universe=None,
        reviewed_source_sha256=source_digest,
        gate1_confirmation_id=confirmation_id,
        candidate_id=candidate_id,
        expected_digest=candidate_digest,
        expected_status="pending",
        final_backtest_receipt_id=None,
        base_commit=None,
    )
    existing = _show_or_none(registry, gate_id)
    if existing is None:
        if (
            snapshot.version != expected
            or snapshot.gate1_ref != hqa_gate_ref
            or snapshot.gate1_source_digest != source_digest
            or snapshot.gate1_candidate_ref is not None
            or getattr(attempt, "attempt_number") != 1
            or getattr(attempt, "terminal_outcome") != "completed"
        ):
            raise _OperationError(
                "paper_research_gate2_precondition_failed",
                retryable=False,
            )
        gate = registry.register(registration)
        gate = _verify_gate(gate, registration, allowed_statuses={"pending"})
        replayed = False
    else:
        stored_registration = _stored_registration(existing)
        replay_fields = _REGISTER_FIELDS - {"command_id", "hermes_run_id"}
        if any(
            stored_registration[field] != registration[field]
            for field in replay_fields
        ):
            raise _OperationError(
                "paper_research_platform_gate_binding_mismatch",
                retryable=False,
            )
        gate = _verify_gate(
            existing,
            stored_registration,
            allowed_statuses={"pending", "reviewed"},
        )
        replayed = True
    return _gate_output(
        operation="open-gate2",
        gate=gate,
        replayed=replayed,
        snapshot=snapshot,
    )


def _open_gate3(
    request: Mapping[str, Any],
    *,
    authority_factory: Callable[[], object],
    registry: PaperGateRegistryPort,
    final_backtest_reader: Callable[[str, str, str], Mapping[str, Any]],
    payload_store: IntentPayloadMetadataPort,
) -> dict[str, Any]:
    fields = {
        "operation_id",
        "gate_id",
        "parent_gate_id",
        "workspace_id",
        "platform_session_id",
        "hermes_session_id",
        "task_ref",
        "expected_task_version",
        "payload_ref",
        "command_id",
        "hermes_run_id",
        "subject_command_id",
        "subject_hermes_run_id",
        "result_ref",
        "hqa_gate_ref",
        "reviewed_source_sha256",
        "gate1_confirmation_id",
        "candidate_id",
        "expected_digest",
        "final_backtest_receipt_id",
        "base_commit",
    }
    request = _runtime_request(
        request,
        operation_fields=fields - set(_RUNTIME_SELECTORS),
    )
    _require_fields(request, fields)
    outer = _identifier(request, "operation_id", workflow=True)
    gate_id = _identifier(request, "gate_id", workflow=True)
    parent_gate_id = _identifier(request, "parent_gate_id", workflow=True)
    workspace_id = _identifier(request, "workspace_id")
    platform_session_id = _identifier(request, "platform_session_id")
    task_ref = _ref(request, "task_ref")
    expected = _positive_version(request)
    payload_ref = _ref(request, "payload_ref")
    command_id = _command_id(request)
    hermes_run_id = _identifier(request, "hermes_run_id")
    result_ref = _ref(request, "result_ref")
    hqa_gate_ref = _ref(request, "hqa_gate_ref")
    source_digest = _digest(request, "reviewed_source_sha256")
    confirmation_id = request.get("gate1_confirmation_id")
    if (
        type(confirmation_id) is not str
        or _GATE1_CONFIRMATION_RE.fullmatch(confirmation_id) is None
    ):
        raise _InputError("gate1_confirmation_id is invalid")
    candidate_id = _identifier(request, "candidate_id", workflow=True)
    candidate_digest = _digest(request, "expected_digest")
    final_receipt_id = request.get("final_backtest_receipt_id")
    if (
        type(final_receipt_id) is not str
        or _FINAL_RECEIPT_RE.fullmatch(final_receipt_id) is None
    ):
        raise _InputError("final_backtest_receipt_id is invalid")
    if result_ref != f"result:{final_receipt_id}":
        raise _InputError("result_ref must bind the final backtest receipt")
    base_commit = _commit(request, "base_commit")
    _attest_invocation(
        registry,
        request,
        workspace_id=workspace_id,
    )
    subject = _attest_subject(
        registry,
        request,
        workspace_id=workspace_id,
    )
    run_ref = str(subject["hqa_run_ref"])
    provider_ref = str(subject["provider_evidence_ref"])
    final_backtest = _validate_final_backtest_evidence(
        final_backtest_reader(
            final_receipt_id,
            candidate_id,
            candidate_digest,
        ),
        error_code="paper_research_final_receipt_invalid",
    )
    parent = _parent_gate(
        registry,
        parent_gate_id=parent_gate_id,
        expected_kind="gate2",
        expected_status="reviewed",
        exact={
            "workspace_id": workspace_id,
            "platform_session_id": platform_session_id,
            "hermes_session_id": request["hermes_session_id"],
            "task_ref": task_ref,
            "reviewed_source_sha256": source_digest,
            "gate1_confirmation_id": confirmation_id,
            "candidate_id": candidate_id,
            "expected_digest": candidate_digest,
        },
    )
    authority = authority_factory()
    before = authority.snapshot(task_ref)  # type: ignore[attr-defined]
    _require_task_identity(
        before,
        workspace_id=workspace_id,
        platform_session_id=platform_session_id,
        task_ref=task_ref,
    )
    payload = _active_payload(
        payload_store,
        authority,
        payload_ref=payload_ref,
        workspace_id=workspace_id,
        platform_session_id=platform_session_id,
        hermes_session_id=str(request["hermes_session_id"]),
        expected_kind="research_continue",
    )
    intent_expires_at = str(payload["expires_at"])
    binding = {
        "gate_id": gate_id,
        "parent_gate_id": parent_gate_id,
        "task_ref": task_ref,
        "expected_task_version": expected,
        "payload_ref": payload_ref,
        "intent_expires_at": intent_expires_at,
        "subject_command_id": subject["command_id"],
        "subject_hermes_run_id": subject["hermes_run_id"],
        "hqa_run_ref": run_ref,
        "provider_evidence_ref": provider_ref,
        "subject_run_attestation_ref": subject["attestation_ref"],
        "subject_run_attestation_digest": subject["evidence_digest"],
        "result_ref": result_ref,
        "hqa_gate_ref": hqa_gate_ref,
        "candidate_id": candidate_id,
        "expected_digest": candidate_digest,
        "final_backtest_receipt_id": final_receipt_id,
        "base_commit": base_commit,
        **final_backtest,
    }
    continue_operation_id = _operation_id(
        outer,
        "research-continue",
        binding,
    )
    _require_payload_consumer_replay(
        authority,
        payload,
        operation_id=continue_operation_id,
    )
    existing = _show_or_none(registry, gate_id)
    if existing is not None:
        registration = _stored_registration(existing)
        # Reconstructing from the stored exact Gate avoids inventing the
        # post-EnterDomainGate version / Attempt 2 on recovery.
        expected_static = {
            "gate_id": gate_id,
            "gate_kind": "gate3",
            "workspace_id": workspace_id,
            "task_ref": task_ref,
            "platform_session_id": platform_session_id,
            "hermes_session_id": request["hermes_session_id"],
            "hqa_gate_ref": hqa_gate_ref,
            "hqa_run_ref": run_ref,
            "provider_evidence_ref": provider_ref,
            "subject_command_id": subject["command_id"],
            "subject_hermes_run_id": subject["hermes_run_id"],
            "subject_run_attestation_ref": subject["attestation_ref"],
            "subject_run_attestation_digest": subject["evidence_digest"],
            **final_backtest,
            "parent_gate_id": parent_gate_id,
            "source_file_ref": None,
            "universe": None,
            "reviewed_source_sha256": source_digest,
            "gate1_confirmation_id": confirmation_id,
            "candidate_id": candidate_id,
            "expected_digest": candidate_digest,
            "expected_status": None,
            "final_backtest_receipt_id": final_receipt_id,
            "base_commit": base_commit,
        }
        if any(existing.get(key) != value for key, value in expected_static.items()):
            raise _OperationError(
                "paper_research_platform_gate_binding_mismatch",
                retryable=False,
            )
        stored_attempt_ref = existing.get("attempt_ref")
        stored_version = existing.get("expected_task_version")
        if (
            type(stored_attempt_ref) is not str
            or _REF_PATTERNS["attempt_ref"].fullmatch(stored_attempt_ref) is None
            or type(stored_version) is not int
            or stored_version <= expected
            or before.version < stored_version
        ):
            raise _OperationError(
                "paper_research_platform_gate_binding_mismatch",
                retryable=False,
            )
        stored_attempt = _attempt(before, stored_attempt_ref)
        if (
            getattr(stored_attempt, "attempt_number") != 2
            or getattr(stored_attempt, "run_ref") != run_ref
            or provider_ref not in getattr(stored_attempt, "provider_evidence_refs")
            or result_ref not in getattr(stored_attempt, "result_refs")
            or getattr(stored_attempt, "domain_gate_ref") != hqa_gate_ref
        ):
            raise _OperationError(
                "paper_research_gate3_evidence_mismatch",
                retryable=False,
            )
        gate = _verify_gate(
            existing,
            registration,
            allowed_statuses={"pending", "prepared"},
        )
        snapshot = authority.snapshot(task_ref)  # type: ignore[attr-defined]
        return _gate_output(
            operation="open-gate3",
            gate=gate,
            replayed=True,
            snapshot=snapshot,
        )
    if (
        before.gate1_source_digest != source_digest
        or before.gate1_candidate_ref != f"candidate:{candidate_id}"
        or before.gate1_manifest_digest != candidate_digest
        or not before.attempts
        or parent.get("attempt_ref") != before.attempts[0].attempt_ref
    ):
        raise _OperationError(
            "paper_research_gate3_precondition_failed",
            retryable=False,
        )
    receipt = authority.apply(  # type: ignore[attr-defined]
        ContinueResearch(
            continue_operation_id,
            task_ref,
            expected,
            payload_ref,
            intent_expires_at,
        )
    )
    attempt_ref = receipt.attempt_ref
    if type(attempt_ref) is not str:
        raise _OperationError(
            "paper_research_missing_attempt",
            retryable=False,
        )
    _bind_payload_attempt(
        payload_store,
        authority,
        payload=payload,
        attempt_ref=attempt_ref,
    )
    command_ref = f"command:{subject['command_id']}"
    receipt = authority.apply(  # type: ignore[attr-defined]
        ObserveSubmission(
            _operation_id(outer, "research-submit", binding),
            task_ref,
            receipt.task_version,
            attempt_ref,
            command_ref,
        )
    )
    receipt = authority.apply(  # type: ignore[attr-defined]
        ObserveRun(
            _operation_id(outer, "research-run", binding),
            task_ref,
            receipt.task_version,
            attempt_ref,
            command_ref,
            run_ref,
        )
    )
    receipt = authority.apply(  # type: ignore[attr-defined]
        ObserveProviderEvidence(
            _operation_id(outer, "research-provider", binding),
            task_ref,
            receipt.task_version,
            attempt_ref,
            run_ref,
            provider_ref,
        )
    )
    receipt = authority.apply(  # type: ignore[attr-defined]
        LinkResult(
            _operation_id(outer, "research-result", binding),
            task_ref,
            receipt.task_version,
            attempt_ref,
            run_ref,
            result_ref,
        )
    )
    receipt = authority.apply(  # type: ignore[attr-defined]
        EnterDomainGate(
            _operation_id(outer, "gate3-enter", binding),
            task_ref,
            receipt.task_version,
            attempt_ref,
            hqa_gate_ref,
        )
    )
    snapshot = authority.snapshot(task_ref)  # type: ignore[attr-defined]
    attempt = _attempt(snapshot, attempt_ref)
    if (
        getattr(attempt, "attempt_number") != 2
        or getattr(attempt, "run_ref") != run_ref
        or provider_ref not in getattr(attempt, "provider_evidence_refs")
        or result_ref not in getattr(attempt, "result_refs")
        or getattr(attempt, "domain_gate_ref") != hqa_gate_ref
        or snapshot.state != "awaiting_domain_gate"
    ):
        raise _OperationError(
            "paper_research_gate3_evidence_mismatch",
            retryable=False,
        )
    registration = _registration(
        gate_id=gate_id,
        gate_kind="gate3",
        workspace_id=workspace_id,
        task_ref=task_ref,
        expected_task_version=snapshot.version,
        platform_session_id=platform_session_id,
        hermes_session_id=request["hermes_session_id"],
        attempt_ref=attempt_ref,
        hqa_gate_ref=hqa_gate_ref,
        command_id=command_id,
        hermes_run_id=hermes_run_id,
        hqa_run_ref=run_ref,
        provider_evidence_ref=provider_ref,
        subject_command_id=subject["command_id"],
        subject_hermes_run_id=subject["hermes_run_id"],
        subject_run_attestation_ref=subject["attestation_ref"],
        subject_run_attestation_digest=subject["evidence_digest"],
        **final_backtest,
        parent_gate_id=parent_gate_id,
        source_file_ref=None,
        universe=None,
        reviewed_source_sha256=source_digest,
        gate1_confirmation_id=confirmation_id,
        candidate_id=candidate_id,
        expected_digest=candidate_digest,
        expected_status=None,
        final_backtest_receipt_id=final_receipt_id,
        base_commit=base_commit,
    )
    gate = registry.register(registration)
    gate = _verify_gate(gate, registration, allowed_statuses={"pending"})
    return _gate_output(
        operation="open-gate3",
        gate=gate,
        replayed=False,
        snapshot=snapshot,
    )


def _promotion_status(
    promotion_id: str,
    *,
    reader: Callable[[str], tuple[int, str]],
) -> dict[str, Any]:
    try:
        code, output = reader(promotion_id)
    except (OSError, subprocess.SubprocessError) as exc:
        raise _OperationError(
            "paper_research_promotion_status_unavailable",
            retryable=True,
        ) from exc
    if len(output.encode("utf-8", errors="replace")) > _STDOUT_LIMIT:
        raise _OperationError(
            "paper_research_promotion_status_invalid",
            retryable=False,
        )
    try:
        document = _strict_json(output.strip().encode("utf-8"))
    except _InputError as exc:
        raise _OperationError(
            "paper_research_promotion_status_invalid",
            retryable=False,
        ) from exc
    expected = {
        "promotion_id",
        "status",
        "reviewed_commit",
        "reason",
        "manifest_sha256",
        "patch_sha256",
        "candidate_id",
        "candidate_digest",
        "final_backtest_receipt_id",
        "base_commit",
        "scoped_paths",
    }
    if code != 0 or set(document) != expected:
        raise _OperationError(
            "paper_research_promotion_status_invalid",
            retryable=False,
        )
    return document


def _complete_after_human_commit(
    request: Mapping[str, Any],
    *,
    authority_factory: Callable[[], object],
    registry: PaperGateRegistryPort,
    promotion_status_reader: Callable[[str], tuple[int, str]],
    final_backtest_reader: Callable[[str, str, str], Mapping[str, Any]],
) -> dict[str, Any]:
    fields = {
        "operation_id",
        "gate_id",
        "workspace_id",
        "task_ref",
        "expected_task_version",
        "attempt_ref",
        "reviewed_commit",
        *_RUNTIME_SELECTORS,
    }
    request = _runtime_request(
        request,
        operation_fields=fields - set(_RUNTIME_SELECTORS),
    )
    _require_fields(request, fields)
    outer = _identifier(request, "operation_id", workflow=True)
    gate_id = _identifier(request, "gate_id", workflow=True)
    workspace_id = _identifier(request, "workspace_id")
    task_ref = _ref(request, "task_ref")
    expected = _positive_version(request)
    attempt_ref = _ref(request, "attempt_ref")
    reviewed_commit = _commit(request, "reviewed_commit")
    _attest_invocation(registry, request, workspace_id=workspace_id)
    gate = registry.show(gate_id)
    run_ref = gate.get("hqa_run_ref")
    provider_ref = gate.get("provider_evidence_ref")
    promotion_id = gate.get("promotion_id")
    gate_status = gate.get("status")
    existing_completion = gate.get("completion")
    if (
        gate.get("gate_id") != gate_id
        or gate.get("workspace_id") != workspace_id
        or gate.get("platform_session_id") != request["platform_session_id"]
        or gate.get("hermes_session_id") != request["hermes_session_id"]
        or gate.get("task_ref") != task_ref
        or gate.get("gate_kind") != "gate3"
        or gate_status not in {"prepared", "completed"}
        or gate.get("attempt_ref") != attempt_ref
        or type(run_ref) is not str
        or _REF_PATTERNS["hqa_run_ref"].fullmatch(run_ref) is None
        or type(provider_ref) is not str
        or _REF_PATTERNS["provider_evidence_ref"].fullmatch(provider_ref) is None
        or type(promotion_id) is not str
        or _PROMOTION_RE.fullmatch(promotion_id) is None
        or gate.get("auto_commit") not in {None, False}
        or (
            gate_status == "prepared"
            and (
                gate.get("human_git_commit_required") is not True
                or existing_completion is not None
            )
        )
        or (
            gate_status == "completed"
            and (
                gate.get("human_git_commit_required") is not False
                or gate.get("reviewed_commit") != reviewed_commit
                or not isinstance(existing_completion, dict)
                or existing_completion.get("status") != "completed"
            )
        )
    ):
        raise _OperationError(
            "paper_research_gate3_completion_binding_mismatch",
            retryable=False,
        )
    candidate_id = gate.get("candidate_id")
    candidate_digest = gate.get("expected_digest")
    final_receipt_id = gate.get("final_backtest_receipt_id")
    base_commit = gate.get("base_commit")
    hqa_gate_ref = gate.get("hqa_gate_ref")
    subject_command_id = gate.get("subject_command_id")
    subject_hermes_run_id = gate.get("subject_hermes_run_id")
    subject_run_attestation_ref = gate.get("subject_run_attestation_ref")
    subject_run_attestation_digest = gate.get("subject_run_attestation_digest")
    if (
        type(candidate_id) is not str
        or _WORKFLOW_ID_RE.fullmatch(candidate_id) is None
        or type(candidate_digest) is not str
        or _DIGEST_RE.fullmatch(candidate_digest) is None
        or type(final_receipt_id) is not str
        or _FINAL_RECEIPT_RE.fullmatch(final_receipt_id) is None
        or type(base_commit) is not str
        or _COMMIT_RE.fullmatch(base_commit) is None
        or type(hqa_gate_ref) is not str
        or _REF_PATTERNS["hqa_gate_ref"].fullmatch(hqa_gate_ref) is None
        or type(subject_command_id) is not str
        or type(subject_hermes_run_id) is not str
        or type(subject_run_attestation_ref) is not str
        or type(subject_run_attestation_digest) is not str
        or _DIGEST_RE.fullmatch(subject_run_attestation_digest) is None
        or subject_run_attestation_ref
        != f"paper-run-attestation:{subject_run_attestation_digest}"
    ):
        raise _OperationError(
            "paper_research_gate3_completion_binding_mismatch",
            retryable=False,
        )
    final_backtest = _validate_final_backtest_evidence(
        final_backtest_reader(
            final_receipt_id,
            candidate_id,
            candidate_digest,
        ),
        error_code="paper_research_final_receipt_binding_mismatch",
    )
    if (
        any(gate.get(field) != value for field, value in final_backtest.items())
    ):
        raise _OperationError(
            "paper_research_final_receipt_binding_mismatch",
            retryable=False,
        )
    status = _promotion_status(
        promotion_id,
        reader=promotion_status_reader,
    )
    if (
        status.get("promotion_id") != promotion_id
        or status.get("status") != "reviewed"
        or status.get("reviewed_commit") != reviewed_commit
        or status.get("reason") != "reviewed"
        or status.get("candidate_id") != candidate_id
        or status.get("candidate_digest") != candidate_digest
        or status.get("final_backtest_receipt_id") != final_receipt_id
        or status.get("base_commit") != base_commit
        or type(status.get("manifest_sha256")) is not str
        or _DIGEST_RE.fullmatch(status["manifest_sha256"]) is None
        or type(status.get("patch_sha256")) is not str
        or _DIGEST_RE.fullmatch(status["patch_sha256"]) is None
        or not isinstance(status.get("scoped_paths"), list)
        or not status["scoped_paths"]
        or not all(type(path) is str and path for path in status["scoped_paths"])
    ):
        raise _OperationError(
            "paper_research_human_commit_not_verified",
            retryable=False,
        )
    authority = authority_factory()
    snapshot = authority.snapshot(task_ref)  # type: ignore[attr-defined]
    _require_task_identity(
        snapshot,
        workspace_id=workspace_id,
        platform_session_id=str(gate.get("platform_session_id")),
        task_ref=task_ref,
    )
    attempt = _attempt(snapshot, attempt_ref)
    gate3_matches = [
        binding
        for binding in getattr(attempt, "gate3_bindings")
        if (
            binding.gate_ref == hqa_gate_ref
            and binding.run_ref == run_ref
            and binding.candidate_ref == f"candidate:{candidate_id}"
            and binding.manifest_digest == candidate_digest
            and binding.final_receipt_ref == f"result:{final_receipt_id}"
            and binding.base_commit == base_commit
        )
    ]
    if (
        snapshot.version < expected
        or getattr(attempt, "run_ref") != run_ref
        or provider_ref not in getattr(attempt, "provider_evidence_refs")
        or getattr(attempt, "domain_gate_ref") != hqa_gate_ref
        or getattr(attempt, "domain_gate_outcome") != "passed"
        or len(gate3_matches) != 1
    ):
        raise _OperationError(
            "paper_research_workflow_completion_mismatch",
            retryable=False,
        )
    binding = {
        "gate_id": gate_id,
        "promotion_id": promotion_id,
        "reviewed_commit": reviewed_commit,
        "task_ref": task_ref,
        "expected_task_version": expected,
        "attempt_ref": attempt_ref,
        "hqa_run_ref": run_ref,
        "provider_evidence_ref": provider_ref,
        "subject_run_attestation_ref": subject_run_attestation_ref,
        "subject_run_attestation_digest": subject_run_attestation_digest,
        **final_backtest,
    }
    attempt_completion = authority.apply(  # type: ignore[attr-defined]
        CompleteAttempt(
            _operation_id(outer, "research-complete", binding),
            task_ref,
            expected,
            attempt_ref,
            "completed",
            run_ref,
            provider_ref,
        )
    )
    task_completion = authority.apply(  # type: ignore[attr-defined]
        CompleteTask(
            _operation_id(outer, "task-complete", binding),
            task_ref,
            attempt_completion.task_version,
            "completed",
            run_ref,
            provider_ref,
        )
    )
    final = authority.snapshot(task_ref)  # type: ignore[attr-defined]
    if final.state != "terminal" or final.terminal_outcome != "completed":
        raise _OperationError(
            "paper_research_workflow_completion_mismatch",
            retryable=False,
        )
    final_attempt = _attempt(final, attempt_ref)
    (
        workflow_audit_status,
        workflow_audit_ref,
        workflow_audit_digest,
    ) = _workflow_task_audit(
        authority,
        task_ref=task_ref,
        task_version=final.version,
        terminal_event_id=getattr(task_completion, "event_id"),
        terminal_operation_id=getattr(task_completion, "operation_id"),
    )
    completion_evidence = {
        "schema_version": "agent-v0.2-paper-completion/v1",
        "task_ref": task_ref,
        "task_version": final.version,
        "task_status": "completed",
        "task_terminal_outcome": final.terminal_outcome,
        "plan_version": final.plan_version,
        "plan_digest": final.plan_digest,
        "plan_confirmation_note_digest": (
            final.plan_confirmation_note_digest
        ),
        "attempt_ref": attempt_ref,
        "attempt_status": "completed",
        "attempt_terminal_outcome": getattr(
            final_attempt,
            "terminal_outcome",
        ),
        "domain_gate_ref": getattr(final_attempt, "domain_gate_ref"),
        "domain_gate_outcome": getattr(
            final_attempt,
            "domain_gate_outcome",
        ),
        "hqa_run_ref": run_ref,
        "provider_evidence_ref": provider_ref,
        "subject_command_id": subject_command_id,
        "subject_hermes_run_id": subject_hermes_run_id,
        "subject_run_attestation_ref": subject_run_attestation_ref,
        "subject_run_attestation_digest": subject_run_attestation_digest,
        **final_backtest,
        "promotion_id": promotion_id,
        "reviewed_commit": reviewed_commit,
        "candidate_id": candidate_id,
        "candidate_digest": candidate_digest,
        "final_backtest_receipt_id": final_receipt_id,
        "base_commit": base_commit,
        "attempt_completion_operation_id": getattr(
            attempt_completion,
            "operation_id",
        ),
        "attempt_completion_event_id": getattr(
            attempt_completion,
            "event_id",
        ),
        "task_completion_operation_id": getattr(
            task_completion,
            "operation_id",
        ),
        "task_completion_event_id": getattr(
            task_completion,
            "event_id",
        ),
        "workflow_audit_status": workflow_audit_status,
        "workflow_audit_ref": workflow_audit_ref,
        "workflow_audit_digest": workflow_audit_digest,
    }
    if (
        set(completion_evidence) != _COMPLETION_EVIDENCE_FIELDS
        or completion_evidence["task_terminal_outcome"] != "completed"
        or completion_evidence["attempt_terminal_outcome"] != "completed"
        or completion_evidence["domain_gate_outcome"] != "passed"
    ):
        raise _OperationError(
            "paper_research_workflow_completion_mismatch",
            retryable=False,
        )
    completion_digest = hashlib.sha256(
        _canonical_bytes(completion_evidence)
    ).hexdigest()
    completion_ref = f"hqa-paper-completion:{completion_digest[:32]}"
    if gate_status == "completed" and (
        gate.get("hqa_completion_receipt_ref") != completion_ref
        or gate.get("hqa_completion_receipt_digest") != completion_digest
        or existing_completion.get("hqa_completion_receipt_ref") != completion_ref
        or existing_completion.get("hqa_completion_receipt_digest") != completion_digest
        or existing_completion.get("completion_evidence") != completion_evidence
    ):
        raise _OperationError(
            "paper_research_platform_completion_mismatch",
            retryable=False,
        )
    platform_completion = registry.complete(
        {
            "completion_evidence": completion_evidence,
            "gate_id": gate_id,
            "hqa_completion_receipt_digest": completion_digest,
            "hqa_completion_receipt_ref": completion_ref,
            "workspace_id": workspace_id,
        }
    )
    if (
        platform_completion.get("gate_id") != gate_id
        or platform_completion.get("workspace_id") != workspace_id
        or platform_completion.get("status") != "completed"
        or platform_completion.get("hqa_completion_receipt_ref") != completion_ref
        or platform_completion.get("hqa_completion_receipt_digest") != completion_digest
    ):
        raise _OperationError(
            "paper_research_platform_completion_mismatch",
            retryable=False,
        )
    return {
        "contract": _CONTRACT,
        "operation": "complete-after-human-commit",
        "ok": True,
        "task_ref": task_ref,
        "task_version": final.version,
        "workflow_state": final.state,
        "terminal_outcome": final.terminal_outcome,
        "promotion_id": promotion_id,
        "reviewed_commit": reviewed_commit,
        "candidate_id": candidate_id,
        "candidate_digest": candidate_digest,
        "final_backtest_receipt_id": final_receipt_id,
        "completion_evidence": completion_evidence,
        "hqa_completion_receipt_ref": completion_ref,
        "hqa_completion_receipt_digest": completion_digest,
        "platform_completion": platform_completion,
        "replayed": bool(task_completion.replayed),
    }


def _execute(
    operation: str,
    request: Mapping[str, Any],
    *,
    authority_factory: Callable[[], object],
    registry: PaperGateRegistryPort,
    promotion_status_reader: Callable[[str], tuple[int, str]],
    final_backtest_reader: Callable[[str, str, str], Mapping[str, Any]],
    payload_store: IntentPayloadMetadataPort,
) -> dict[str, Any]:
    if operation == "prepare-intent":
        return _prepare_intent(
            request,
            authority_factory=authority_factory,
            registry=registry,
            payload_store=payload_store,
        )
    if operation == "start-plan":
        return _start_plan(
            request,
            authority_factory=authority_factory,
            registry=registry,
            payload_store=payload_store,
        )
    if operation == "confirm-plan":
        return _confirm_plan(
            request,
            authority_factory=authority_factory,
            registry=registry,
        )
    if operation == "open-gate1":
        return _open_gate1(
            request,
            authority_factory=authority_factory,
            registry=registry,
        )
    if operation == "open-gate2":
        return _open_gate2(
            request,
            authority_factory=authority_factory,
            registry=registry,
        )
    if operation == "open-gate3":
        return _open_gate3(
            request,
            authority_factory=authority_factory,
            registry=registry,
            final_backtest_reader=final_backtest_reader,
            payload_store=payload_store,
        )
    return _complete_after_human_commit(
        request,
        authority_factory=authority_factory,
        registry=registry,
        promotion_status_reader=promotion_status_reader,
        final_backtest_reader=final_backtest_reader,
    )


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    authority_factory: Callable[[], object] = _authority,
    registry: Optional[PaperGateRegistryPort] = None,
    promotion_status_reader: Callable[
        [str], tuple[int, str]
    ] = quant_cli.run_promotion_status,
    final_backtest_reader: Callable[
        [str, str, str], Mapping[str, Any]
    ] = _read_final_backtest_evidence,
    payload_store: Optional[IntentPayloadMetadataPort] = None,
) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    operation = args[0] if len(args) == 1 else ""
    if operation not in _OPERATIONS:
        _emit(
            {
                "contract": _CONTRACT,
                "operation": operation or "invalid",
                "ok": False,
                "error": {
                    "code": "paper_research_invalid_arguments",
                    "message": "paper research operation is invalid",
                    "retryable": False,
                },
            }
        )
        return 2
    try:
        request = _read_request(
            maximum=(
                _PREPARE_STDIN_LIMIT
                if operation == "prepare-intent"
                else _STDIN_LIMIT
            )
        )
        port = registry if registry is not None else SubprocessPaperGateRegistry()
        intent_store = payload_store if payload_store is not None else _payload_store()
        result = _execute(
            operation,
            request,
            authority_factory=authority_factory,
            registry=port,
            promotion_status_reader=promotion_status_reader,
            final_backtest_reader=final_backtest_reader,
            payload_store=intent_store,
        )
    except (
        IntentPayloadError,
        WorkflowContractError,
        _InputError,
        TypeError,
        ValueError,
    ):
        code = "paper_research_invalid_request"
        retryable = False
        exit_code = 2
    except WorkflowAuthorityError as exc:
        code = exc.code
        retryable = exc.code in {
            "workflow_storage_unavailable",
            "workflow_durability_unknown",
        }
        exit_code = 1 if retryable else 2
    except _RegistryError as exc:
        code = exc.code
        retryable = exc.retryable
        exit_code = 1 if retryable or exc.outcome_unknown else 2
    except _OperationError as exc:
        code = exc.code
        retryable = exc.retryable
        exit_code = 1 if retryable else 2
    except CryptoFailure as exc:
        code = exc.code
        retryable = exc.code in _RETRYABLE_CRYPTO_FAILURES
        exit_code = 1 if retryable else 2
    except OSError:
        code = "paper_research_unavailable"
        retryable = True
        exit_code = 1
    else:
        _emit(result)
        return 0
    _emit(
        {
            "contract": _CONTRACT,
            "operation": operation,
            "ok": False,
            "error": {
                "code": code,
                "message": "paper research operation did not advance exactly",
                "retryable": retryable,
            },
        }
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

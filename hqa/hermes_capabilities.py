from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse


class CapabilityContractError(ValueError):
    pass


@dataclass(frozen=True)
class HermesGatewayCapabilities:
    schema_version: str
    observed_at: str
    hermes_version: str
    upstream_commit: str
    source_checkout_commit: str
    server_source_sha256: str
    transport: str
    endpoint: str
    loopback_only: bool
    relevant_methods_observed: frozenset[str]
    session_provider_override: bool
    session_primary_provider_policy_immutable: bool
    session_provider_fallback_policy_immutable: bool
    client_idempotency_key: bool
    request_correlation_metadata: bool
    request_lookup_by_client_id: bool
    run_id: bool
    event_id: bool
    event_cursor: bool
    run_provider_evidence: bool
    approval_command_digest_binding: bool
    approval_ttl: bool
    approval_single_use: bool
    stop_idempotent: bool
    stop_reconcilable: bool


@dataclass(frozen=True)
class HermesChatGate:
    chat_read_enabled: bool
    chat_write_enabled: bool
    stream_enabled: bool
    resume_enabled: bool
    approval_enabled: bool
    stop_enabled: bool
    blockers: tuple[str, ...]
    resume_blockers: tuple[str, ...]
    approval_blockers: tuple[str, ...]
    stop_blockers: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


_READ_METHODS = frozenset({"session.list", "session.status", "session.history"})
_CHAT_METHODS = frozenset({"session.create", "prompt.submit"})
_EVIDENCE_KEYS = (
    "session_provider_override",
    "session_primary_provider_policy_immutable",
    "session_provider_fallback_policy_immutable",
    "client_idempotency_key",
    "request_correlation_metadata",
    "request_lookup_by_client_id",
    "run_id",
    "event_id",
    "event_cursor",
    "run_provider_evidence",
    "approval_command_digest_binding",
    "approval_ttl",
    "approval_single_use",
    "stop_idempotent",
    "stop_reconcilable",
)


def load_capabilities(path: Path) -> HermesGatewayCapabilities:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CapabilityContractError("capability contract is unreadable") from exc
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version",
        "observed_at",
        "hermes_version",
        "upstream_commit",
        "source_checkout_commit",
        "server_source_sha256",
        "transport",
        "endpoint",
        "loopback_only",
        "relevant_methods_observed",
        "evidence",
    }:
        raise CapabilityContractError("capability contract has unknown or missing fields")
    evidence = raw["evidence"]
    if not isinstance(evidence, dict) or set(evidence) != set(_EVIDENCE_KEYS):
        raise CapabilityContractError("capability evidence has unknown or missing fields")
    if raw["schema_version"] != "1.0" or raw["transport"] != "websocket_jsonrpc":
        raise CapabilityContractError("unsupported capability schema or transport")
    string_fields = (
        "observed_at",
        "hermes_version",
        "upstream_commit",
        "source_checkout_commit",
        "server_source_sha256",
    )
    if any(not isinstance(raw[field], str) or not raw[field] for field in string_fields):
        raise CapabilityContractError("capability identity fields must be non-empty strings")
    if not isinstance(raw["relevant_methods_observed"], list) or any(
        not isinstance(item, str) or not item
        for item in raw["relevant_methods_observed"]
    ):
        raise CapabilityContractError(
            "relevant capability methods must be non-empty strings"
        )
    if any(type(evidence[key]) is not bool for key in _EVIDENCE_KEYS):
        raise CapabilityContractError("capability evidence values must be booleans")
    if not isinstance(raw["endpoint"], str):
        raise CapabilityContractError("Hermes endpoint must be loopback WebSocket")
    try:
        endpoint = urlparse(raw["endpoint"])
        endpoint_port = endpoint.port
    except ValueError as exc:
        raise CapabilityContractError(
            "Hermes endpoint must be loopback WebSocket"
        ) from exc
    if (
        endpoint.scheme not in {"ws", "wss"}
        or endpoint.hostname not in {"127.0.0.1", "::1"}
        or endpoint_port is None
        or not 1 <= endpoint_port <= 65535
        or endpoint.path != "/api/ws"
        or endpoint.username is not None
        or endpoint.password is not None
        or endpoint.params
        or endpoint.query
        or endpoint.fragment
    ):
        raise CapabilityContractError("Hermes endpoint must be loopback WebSocket")
    if raw["loopback_only"] is not True:
        raise CapabilityContractError("Hermes contract is not loopback-only")
    relevant_methods = frozenset(
        str(item) for item in raw["relevant_methods_observed"]
    )
    return HermesGatewayCapabilities(
        schema_version="1.0",
        observed_at=str(raw["observed_at"]),
        hermes_version=str(raw["hermes_version"]),
        upstream_commit=str(raw["upstream_commit"]),
        source_checkout_commit=str(raw["source_checkout_commit"]),
        server_source_sha256=str(raw["server_source_sha256"]),
        transport="websocket_jsonrpc",
        endpoint=str(raw["endpoint"]),
        loopback_only=True,
        relevant_methods_observed=relevant_methods,
        **{key: evidence[key] is True for key in _EVIDENCE_KEYS},
    )


def evaluate_chat_gate(capabilities: HermesGatewayCapabilities) -> HermesChatGate:
    chat_methods_present = _CHAT_METHODS.issubset(
        capabilities.relevant_methods_observed
    )
    request_recovery = any(
        (
            capabilities.client_idempotency_key,
            capabilities.request_correlation_metadata,
            capabilities.request_lookup_by_client_id,
        )
    )
    event_replay = capabilities.event_id and capabilities.event_cursor
    provider_policy_locked = (
        capabilities.session_provider_override
        and capabilities.session_primary_provider_policy_immutable
        and capabilities.session_provider_fallback_policy_immutable
    )
    chat_blockers: list[str] = []
    if not chat_methods_present:
        chat_blockers.append("missing_chat_methods")
    if not request_recovery:
        chat_blockers.append("missing_request_recovery")
    if not capabilities.run_id:
        chat_blockers.append("missing_run_identity")
    if not provider_policy_locked:
        chat_blockers.append("missing_provider_policy_lock")
    if not capabilities.run_provider_evidence:
        chat_blockers.append("missing_actual_provider_evidence")
    write_enabled = not chat_blockers
    stream_blockers = list(chat_blockers)
    if not event_replay:
        stream_blockers.append("missing_event_replay")
    resume_blockers = list(stream_blockers)
    if "session.resume" not in capabilities.relevant_methods_observed:
        resume_blockers.append("missing_resume_method")
    approval_blockers: list[str] = []
    if chat_blockers:
        approval_blockers.append("missing_chat_contract")
    if "approval.respond" not in capabilities.relevant_methods_observed or not all(
        (
            capabilities.approval_command_digest_binding,
            capabilities.approval_ttl,
            capabilities.approval_single_use,
        )
    ):
        approval_blockers.append("missing_approval_binding")
    stop_blockers: list[str] = []
    if not capabilities.run_id:
        stop_blockers.append("missing_run_identity")
    if "session.interrupt" not in capabilities.relevant_methods_observed or not all(
        (capabilities.stop_idempotent, capabilities.stop_reconcilable)
    ):
        stop_blockers.append("missing_stop_contract")
    return HermesChatGate(
        chat_read_enabled=_READ_METHODS.issubset(
            capabilities.relevant_methods_observed
        ),
        chat_write_enabled=write_enabled,
        stream_enabled=not stream_blockers,
        resume_enabled=not resume_blockers,
        approval_enabled=not approval_blockers,
        stop_enabled=not stop_blockers,
        blockers=tuple(stream_blockers),
        resume_blockers=tuple(resume_blockers),
        approval_blockers=tuple(approval_blockers),
        stop_blockers=tuple(stop_blockers),
    )

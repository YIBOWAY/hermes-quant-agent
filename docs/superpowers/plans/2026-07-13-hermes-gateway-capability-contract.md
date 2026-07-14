# Hermes Gateway Capability Contract Implementation Plan

> **Delivery status (2026-07-14): DELIVERED, WRITE GATES BLOCKED.** The
> versioned snapshot, pure evaluator, CLI, Git-bound independent review, live
> installation fingerprint, tests, and evidence document were delivered. Live
> `verify-chat` currently exits 3: the frozen fingerprint is `b03c94db` while
> the 2026-07-14 current local installation reports `226e8de8`. It also remains non-ready
> because deterministic request recovery, Run
> identity/event replay, immutable provider/fallback policy, actual-provider
> evidence, and a runtime handshake are not proven. Therefore chat/resume/
> approval/stop remain fail-closed. The unchecked boxes below are the original
> execution checklist, not the current progress ledger; use this status block,
> `docs/README.md`, current tests, and runtime evidence.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the installed Hermes 0.18.2 gateway facts into a versioned, machine-readable, fail-closed capability contract so later chat work cannot expose a mutation path that lacks deterministic request recovery, replayable events, or actual provider evidence.

**Architecture:** HQA owns a strict immutable capability snapshot and a pure evaluator. A small JSON-only CLI overlays a read-only live installation fingerprint before exposing the effective contract to the future platform BFF, without contacting a provider or reading secrets. This slice deliberately does not send a prompt, create a Hermes session, start a BFF, or enable the web composer; a later bridge plan can be written only after the live fingerprint matches and a real Hermes contract satisfies every write gate.

**Tech Stack:** HQA's current Python 3.9.6-compatible standard library surface, dataclasses, argparse, pytest, Hermes Agent 0.18.2 source/help evidence, JSON. Hermes itself reports Python 3.11.15, but HQA implementation syntax must pass the repository's <code>./.venv/bin/python</code>.

## Global Constraints

- The browser must never receive a Hermes bearer key or provider secret.
- The installed Hermes server remains loopback-only; remote access is out of scope.
- The old platform <code>POST /api/agent/tasks</code> is never a fallback for Hermes.
- A create/submit write is disabled unless Hermes supplies deterministic client correlation or lookup after an ambiguous response.
- Stream progress is disabled unless events have a stable per-Run identity/cursor or an equally deterministic snapshot-plus-replay contract.
- Provider availability is not provider usage: actual provider/model evidence must come from the Hermes Run/turn itself.
- <code>session.resume</code> is stateful: it rebinds transport and may restore/build an agent. It is never authorized by the read gate and gets an explicit mutation gate.
- Tests are hermetic: no Grok/Codex call, no external network, no paper/live path, and no real Hermes session mutation.
- Keep <code>paper_trading=true</code>, <code>live_trading_enabled=false</code>, <code>kill_switch=true</code>, and Gate 1/2/3 unchanged.
- Preserve all pre-existing dirty worktree changes and do not edit the installed Hermes checkout in this slice.
- <code>verify-chat</code> must compare the checked-in snapshot with the live local binary/source fingerprint using bounded read-only subprocess calls; a version, upstream, checkout, or source-digest mismatch adds <code>installation_fingerprint_mismatch</code>. Any tracked Hermes source change adds <code>installation_source_dirty</code>. Both stay blocked; untracked installer metadata is ignored.
- The local trust boundary is Git-reviewed repository content: a review record authorizes only the exact default-contract bytes at an ancestor commit and must itself match the checked-in HEAD blob. Local root compromise or malicious Git-history rewriting is out of scope; arbitrary files and uncommitted review edits never authorize a live capability.
- This slice fingerprints the installed binary/source, not the identity of a process already listening on port 9119. A later bridge/BFF plan must add an authenticated runtime version/capability handshake bound to the reviewed contract before any write; static installation evidence alone never authorizes a long-lived connection.

---

## Source facts frozen by this plan

The 2026-07-13 preflight established:

- At 2026-07-13T07:29:37Z, <code>hermes --version</code> reports Hermes Agent 0.18.2 (2026.7.7.2), upstream <code>e4ea0a0e</code>.
- The installed source checkout is <code>4281151ae859241351ba14d8c7682dc67ff4c126</code>; <code>tui_gateway/server.py</code> SHA-256 is <code>2a05d8979ee3e4edb0e534f4db1c421d2064f36c8290234c3cf1496365ba7d17</code>. The upstream identifier and local checkout commit are distinct facts and must not be conflated.
- <code>hermes serve --help</code> describes a JSON-RPC/WebSocket gateway, default host <code>127.0.0.1</code>, default port <code>9119</code>.
- Among other gateway methods, the live installed source registers the relevant subset <code>session.create</code>, <code>session.list</code>, <code>session.resume</code>, <code>session.status</code>, <code>session.history</code>, <code>session.interrupt</code>, <code>prompt.submit</code>, <code>approval.respond</code>, and <code>config.set</code>. The snapshot deliberately records this allowlisted subset, not the server's complete method registry.
- <code>session.create</code> accepts a per-session model/provider choice and returns runtime and stored session IDs. <code>config.set</code> can later switch the live session model/provider. The inspected contract therefore proves neither immutable primary-provider/model policy nor an immutable fallback policy for the session.
- <code>prompt.submit</code> accepts session ID and text, but no client idempotency key, durable request-correlation metadata, or caller-supplied Run ID.
- emitted gateway events have a type and session ID but no durable event ID or replay cursor.
- no observed method can query a submit by client request ID after the gateway accepted it but the BFF lost the response.
- session usage exposes some model/token context, but the inspected Run/turn contract does not provide the complete immutable evidence required by D-31: requested and actual provider/model, fallback from/to/reason, and usage bound to the same Run.

These facts make <code>session.list</code>, <code>session.status</code>, and <code>session.history</code> ordinary reads. They keep <code>session.create</code>, <code>session.resume</code>, <code>prompt.submit</code>, command approval, and stop unavailable to the platform until the missing contracts are supplied and verified.

## File map

### Hermes-quant-agent

- Create <code>hqa/hermes_capabilities.py</code>: strict dataclasses, JSON parsing, and the pure fail-closed evaluator.
- Create <code>hqa/hermes_capability_cli.py</code>: one-document JSON CLI with <code>show</code> and <code>verify-chat</code>.
- Create <code>config/hermes-gateway-capabilities.v1.json</code>: checked-in snapshot of the installed 0.18.2 gateway.
- Create <code>config/hermes-gateway-capabilities.v1.review.json</code>: independently produced admission review bound to the exact default-contract digest and reviewed commit; it is not created until Task 4.
- Create <code>tests/test_hermes_capabilities.py</code>: schema rejection and capability-gate tests.
- Create <code>tests/test_hermes_capability_cli.py</code>: stable output and exit-code tests.
- Create <code>docs/contracts/hermes-gateway-0.18.2.md</code>: reproducible command/source evidence and the exact missing contract.
- Modify <code>hqa/config.py</code>: expose the capability snapshot, Hermes binary, and installed source paths.
- Modify <code>docs/README.md</code>: mark this slice selected and real chat blocked by a named capability gate, not by vague unfinished UI work.

No platform production file changes in this plan.

### Public interfaces

~~~python
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

def load_capabilities(path: Path) -> HermesGatewayCapabilities:
    raise NotImplementedError

def evaluate_chat_gate(capabilities: HermesGatewayCapabilities) -> HermesChatGate:
    raise NotImplementedError
~~~

<code>relevant_methods_observed</code> is an audited allowlist used by this evaluator, never the complete Hermes registry. <code>session_primary_provider_policy_immutable</code> and <code>session_provider_fallback_policy_immutable</code> are separate claims. <code>run_provider_evidence=true</code> means one immutable Run-scoped record contains requested and actual provider/model, fallback from/to/reason, and usage; a model name or aggregate token count alone is false. The Run ID here is the stable identity of the submitted chat/research attempt, not a session ID, process ID, or unrelated child-run field.

The JSON CLI returns one UTF-8 document. <code>show</code> may inspect a custom contract but never authorizes it. <code>verify-chat</code> accepts only the checked-in default contract and exits 0 only when both <code>chat_write_enabled</code> and <code>stream_enabled</code> are true after exact review-record and installation-fingerprint checks. The known 0.18.2 snapshot exits 3 with stable blocker codes.

---

### Task 1: Strict capability snapshot and fail-closed evaluator

**Files:**

- Create: <code>tests/test_hermes_capabilities.py</code>
- Create: <code>hqa/hermes_capabilities.py</code>
- Create: <code>config/hermes-gateway-capabilities.v1.json</code>
- Modify: <code>hqa/config.py</code>

**Interfaces:**

- Consumes: a UTF-8 JSON object at <code>config.HERMES_GATEWAY_CAPABILITIES_PATH</code>.
- Produces: <code>load_capabilities(Path) -> HermesGatewayCapabilities</code> and <code>evaluate_chat_gate(HermesGatewayCapabilities) -> HermesChatGate</code>.

- [ ] **Preflight: Reconfirm the frozen installation without mutation**

Run <code>hermes --version</code>, <code>git -C /Users/sunyibo/.hermes/hermes-agent rev-parse HEAD</code>, tracked-only <code>git status --porcelain --untracked-files=no</code>, and the <code>server.py</code> SHA-256 command from Task 3. Expected: the exact 2026-07-13 values above and empty tracked status. If any value differs, stop; update the dated source facts, snapshot, tests, and evidence through a new source review before implementation. Never edit expected values merely to make <code>verify-chat</code> green.

- [ ] **Step 1: Write the failing parser and gate tests**

Add the following complete tests:

~~~python
from __future__ import annotations

import json

import pytest

from hqa.hermes_capabilities import (
    CapabilityContractError,
    evaluate_chat_gate,
    load_capabilities,
)


def _document() -> dict:
    return {
        "schema_version": "1.0",
        "observed_at": "2026-07-13T07:29:37Z",
        "hermes_version": "0.18.2",
        "upstream_commit": "e4ea0a0e",
        "source_checkout_commit": "4281151ae859241351ba14d8c7682dc67ff4c126",
        "server_source_sha256": "2a05d8979ee3e4edb0e534f4db1c421d2064f36c8290234c3cf1496365ba7d17",
        "transport": "websocket_jsonrpc",
        "endpoint": "ws://127.0.0.1:9119/api/ws",
        "loopback_only": True,
        "relevant_methods_observed": [
            "approval.respond",
            "config.set",
            "prompt.submit",
            "session.create",
            "session.history",
            "session.interrupt",
            "session.list",
            "session.resume",
            "session.status",
        ],
        "evidence": {
            "session_provider_override": True,
            "session_primary_provider_policy_immutable": False,
            "session_provider_fallback_policy_immutable": False,
            "client_idempotency_key": False,
            "request_correlation_metadata": False,
            "request_lookup_by_client_id": False,
            "run_id": False,
            "event_id": False,
            "event_cursor": False,
            "run_provider_evidence": False,
            "approval_command_digest_binding": False,
            "approval_ttl": False,
            "approval_single_use": False,
            "stop_idempotent": False,
            "stop_reconcilable": False,
        },
    }


def test_known_gateway_is_readable_but_all_chat_mutations_fail_closed(tmp_path) -> None:
    path = tmp_path / "capabilities.json"
    path.write_text(json.dumps(_document()), encoding="utf-8")

    gate = evaluate_chat_gate(load_capabilities(path))

    assert gate.chat_read_enabled is True
    assert gate.chat_write_enabled is False
    assert gate.stream_enabled is False
    assert gate.resume_enabled is False
    assert gate.approval_enabled is False
    assert gate.approval_blockers == (
        "missing_chat_contract",
        "missing_approval_binding",
    )
    assert gate.stop_enabled is False
    assert gate.stop_blockers == (
        "missing_run_identity",
        "missing_stop_contract",
    )
    assert gate.blockers == (
        "missing_request_recovery",
        "missing_run_identity",
        "missing_provider_policy_lock",
        "missing_actual_provider_evidence",
        "missing_event_replay",
    )


def test_complete_contract_opens_each_capability_independently(tmp_path) -> None:
    document = _document()
    document["evidence"] = {key: True for key in document["evidence"]}
    path = tmp_path / "capabilities.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    gate = evaluate_chat_gate(load_capabilities(path))

    assert gate.chat_write_enabled is True
    assert gate.stream_enabled is True
    assert gate.resume_enabled is True
    assert gate.approval_enabled is True
    assert gate.stop_enabled is True
    assert gate.blockers == ()


def test_resume_is_never_classified_as_a_read(tmp_path) -> None:
    document = _document()
    document["relevant_methods_observed"].remove("session.resume")
    path = tmp_path / "capabilities.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    gate = evaluate_chat_gate(load_capabilities(path))

    assert gate.chat_read_enabled is True
    assert gate.resume_enabled is False
    assert "missing_resume_method" in gate.resume_blockers


def test_event_replay_is_required_for_stream_and_resume(tmp_path) -> None:
    document = _document()
    document["evidence"] = {key: True for key in document["evidence"]}
    document["evidence"]["event_cursor"] = False
    path = tmp_path / "capabilities.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    gate = evaluate_chat_gate(load_capabilities(path))

    assert gate.chat_write_enabled is True
    assert gate.stream_enabled is False
    assert gate.resume_enabled is False
    assert gate.blockers == ("missing_event_replay",)


def test_primary_and_fallback_provider_policies_must_both_be_immutable(
    tmp_path,
) -> None:
    document = _document()
    document["evidence"] = {key: True for key in document["evidence"]}
    document["evidence"]["session_primary_provider_policy_immutable"] = False
    path = tmp_path / "capabilities.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    gate = evaluate_chat_gate(load_capabilities(path))

    assert gate.chat_write_enabled is False
    assert "missing_provider_policy_lock" in gate.blockers


def test_missing_chat_method_is_an_explicit_fail_closed_blocker(tmp_path) -> None:
    document = _document()
    document["evidence"] = {key: True for key in document["evidence"]}
    document["relevant_methods_observed"].remove("prompt.submit")
    path = tmp_path / "capabilities.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    gate = evaluate_chat_gate(load_capabilities(path))

    assert gate.chat_write_enabled is False
    assert gate.blockers == ("missing_chat_methods",)


def test_safe_chat_does_not_open_approval_or_stop_from_method_names(tmp_path) -> None:
    document = _document()
    document["evidence"] = {key: True for key in document["evidence"]}
    for key in (
        "approval_command_digest_binding",
        "approval_ttl",
        "approval_single_use",
        "stop_idempotent",
        "stop_reconcilable",
    ):
        document["evidence"][key] = False
    path = tmp_path / "capabilities.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    gate = evaluate_chat_gate(load_capabilities(path))

    assert gate.chat_write_enabled is True
    assert gate.stream_enabled is True
    assert gate.approval_enabled is False
    assert gate.approval_blockers == ("missing_approval_binding",)
    assert gate.stop_enabled is False
    assert gate.stop_blockers == ("missing_stop_contract",)


@pytest.mark.parametrize(
    "recovery_field",
    [
        "client_idempotency_key",
        "request_correlation_metadata",
        "request_lookup_by_client_id",
    ],
)
def test_any_one_deterministic_recovery_contract_is_sufficient(
    tmp_path, recovery_field
) -> None:
    document = _document()
    document["evidence"] = {key: True for key in document["evidence"]}
    for key in (
        "client_idempotency_key",
        "request_correlation_metadata",
        "request_lookup_by_client_id",
    ):
        document["evidence"][key] = key == recovery_field
    path = tmp_path / "capabilities.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    assert evaluate_chat_gate(load_capabilities(path)).chat_write_enabled is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "2.0"),
        ("transport", "rest"),
        ("endpoint", "ws://0.0.0.0:9119/api/ws"),
        ("endpoint", "ws://localhost:9119/api/ws"),
        ("endpoint", "ws://127.0.0.1:9119/other"),
        ("endpoint", "ws://127.0.0.1:9119/api/ws?token=secret#fragment"),
        ("endpoint", "ws://user:pass@127.0.0.1:9119/api/ws"),
        ("endpoint", "ws://127.0.0.1:99999/api/ws"),
        ("loopback_only", False),
    ],
)
def test_unsafe_or_unknown_contract_is_rejected(tmp_path, field, value) -> None:
    document = _document()
    document[field] = value
    path = tmp_path / "capabilities.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(CapabilityContractError):
        load_capabilities(path)

    # Error text must never reflect an endpoint that may contain credentials.
    try:
        load_capabilities(path)
    except CapabilityContractError as exc:
        assert "secret" not in str(exc)
        assert "pass" not in str(exc)
~~~

- [ ] **Step 2: Run the focused test and confirm RED**

Run:

~~~bash
cd /Users/sunyibo/programs/Hermes-quant-agent
./.venv/bin/pytest -q tests/test_hermes_capabilities.py
~~~

Expected: collection fails with <code>ModuleNotFoundError: No module named 'hqa.hermes_capabilities'</code>.

- [ ] **Step 3: Implement the strict types, parser, and independent gates**

Create <code>hqa/hermes_capabilities.py</code> with this complete implementation:

~~~python
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
~~~

Append to <code>hqa/config.py</code>:

~~~python
# These two admission anchors are intentionally not environment-overridable.
# Tests monkeypatch the module constants directly.
HERMES_GATEWAY_CAPABILITIES_PATH = (
    REPO_DIR / "config" / "hermes-gateway-capabilities.v1.json"
)
HERMES_GATEWAY_REVIEW_PATH = (
    REPO_DIR / "config" / "hermes-gateway-capabilities.v1.review.json"
)
HERMES_BIN_PATH = Path(
    os.environ.get("HQA_HERMES_BIN_PATH", "/Users/sunyibo/.local/bin/hermes")
)
HERMES_SOURCE_DIR = Path(
    os.environ.get(
        "HQA_HERMES_SOURCE_DIR",
        "/Users/sunyibo/.hermes/hermes-agent",
    )
)
~~~

Create <code>config/hermes-gateway-capabilities.v1.json</code> with the exact known snapshot:

~~~json
{
  "schema_version": "1.0",
  "observed_at": "2026-07-13T07:29:37Z",
  "hermes_version": "0.18.2",
  "upstream_commit": "e4ea0a0e",
  "source_checkout_commit": "4281151ae859241351ba14d8c7682dc67ff4c126",
  "server_source_sha256": "2a05d8979ee3e4edb0e534f4db1c421d2064f36c8290234c3cf1496365ba7d17",
  "transport": "websocket_jsonrpc",
  "endpoint": "ws://127.0.0.1:9119/api/ws",
  "loopback_only": true,
  "relevant_methods_observed": [
    "approval.respond",
    "config.set",
    "prompt.submit",
    "session.create",
    "session.history",
    "session.interrupt",
    "session.list",
    "session.resume",
    "session.status"
  ],
  "evidence": {
    "session_provider_override": true,
    "session_primary_provider_policy_immutable": false,
    "session_provider_fallback_policy_immutable": false,
    "client_idempotency_key": false,
    "request_correlation_metadata": false,
    "request_lookup_by_client_id": false,
    "run_id": false,
    "event_id": false,
    "event_cursor": false,
    "run_provider_evidence": false,
    "approval_command_digest_binding": false,
    "approval_ttl": false,
    "approval_single_use": false,
    "stop_idempotent": false,
    "stop_reconcilable": false
  }
}
~~~

- [ ] **Step 4: Run the focused test and confirm GREEN**

Run: <code>./.venv/bin/pytest -q tests/test_hermes_capabilities.py</code>

Expected: all tests pass.

- [ ] **Step 5: Commit the capability core**

~~~bash
git add hqa/config.py hqa/hermes_capabilities.py config/hermes-gateway-capabilities.v1.json tests/test_hermes_capabilities.py
git commit -m "feat(hqa): add fail-closed Hermes gateway capability contract"
~~~

---

### Task 2: JSON-only capability CLI

**Files:**

- Create: <code>tests/test_hermes_capability_cli.py</code>
- Create: <code>hqa/hermes_capability_cli.py</code>
- Modify: <code>hqa/config.py</code> to add the fixed review-record path if it was not committed in Task 1.

**Interfaces:**

- Consumes: <code>config.HERMES_GATEWAY_CAPABILITIES_PATH</code>, the fixed <code>config.HERMES_GATEWAY_REVIEW_PATH</code>, and the local Hermes binary/source fingerprint. Only <code>show</code> accepts an optional diagnostic <code>--contract</code>; <code>verify-chat</code> always uses the default contract.
- Produces: one strict JSON document and exit 0 for <code>show</code>; exit 0/3 for safe/blocked <code>verify-chat</code>; exit 1/2 for contract/argument failures. The effective gate is fail-closed after review provenance and installation comparison. Bridge admission requires both write and stream gates; approval, stop, and resume remain independent.

- [ ] **Step 1: Write the failing CLI tests**

~~~python
from __future__ import annotations

import json

from hqa import hermes_capability_cli


def _contract() -> dict:
    return {
        "hermes_version": "0.18.2",
        "upstream_commit": "e4ea0a0e",
        "source_checkout_commit": "4281151ae859241351ba14d8c7682dc67ff4c126",
        "server_source_sha256": "2a05d8979ee3e4edb0e534f4db1c421d2064f36c8290234c3cf1496365ba7d17",
        "source_tracked_clean": True,
    }


def _gate(*, write: bool, stream: bool, read: bool = True) -> dict:
    blocker = [] if write else ["missing_request_recovery"]
    return {
        "chat_read_enabled": read,
        "chat_write_enabled": write,
        "stream_enabled": stream,
        "resume_enabled": stream,
        "approval_enabled": False,
        "stop_enabled": False,
        "blockers": blocker + ([] if stream or not write else ["missing_event_replay"]),
        "resume_blockers": blocker + ([] if stream else ["missing_event_replay"]),
        "approval_blockers": ["missing_approval_binding"],
        "stop_blockers": ["missing_stop_contract"],
    }


def _install_declared(monkeypatch, gate: dict) -> None:
    monkeypatch.setattr(
        hermes_capability_cli,
        "_read",
        lambda _path: {"contract": _contract(), "declared_gate": gate},
    )
    monkeypatch.setattr(hermes_capability_cli, "_probe_installation", _contract)


def test_custom_show_is_diagnostic_but_never_authoritative(
    monkeypatch, capsys, tmp_path
) -> None:
    contract = tmp_path / "capabilities.json"
    contract.write_text("{}", encoding="utf-8")
    _install_declared(monkeypatch, _gate(write=True, stream=True))
    monkeypatch.setattr(
        hermes_capability_cli,
        "_probe_review",
        lambda _path: {
            "trusted": False,
            "verdict": "unreviewed",
            "blocker": "custom_contract_unreviewed",
        },
    )

    assert hermes_capability_cli.main(["show", "--contract", str(contract)]) == 0
    document = json.loads(capsys.readouterr().out)
    assert document["snapshot_readable"] is True
    assert document["declared_gate"]["chat_write_enabled"] is True
    assert document["gate"]["chat_read_enabled"] is False
    assert document["gate"]["chat_write_enabled"] is False
    assert "custom_contract_unreviewed" in document["gate"]["blockers"]


def test_verify_chat_returns_three_for_known_blocked_contract(monkeypatch, capsys) -> None:
    _install_declared(monkeypatch, _gate(write=False, stream=False))
    monkeypatch.setattr(
        hermes_capability_cli,
        "_probe_review",
        lambda _path: {
            "trusted": True,
            "verdict": "blocked",
            "blocker": "contract_review_blocked",
        },
    )

    assert hermes_capability_cli.main(["verify-chat"]) == 3
    document = json.loads(capsys.readouterr().out)
    assert document["status"] == "blocked"
    assert document["gate"]["chat_read_enabled"] is True


def test_verify_chat_requires_replay_even_when_submit_is_safe(monkeypatch, capsys) -> None:
    _install_declared(monkeypatch, _gate(write=True, stream=False))
    monkeypatch.setattr(
        hermes_capability_cli,
        "_probe_review",
        lambda _path: {"trusted": True, "verdict": "ready", "blocker": None},
    )

    assert hermes_capability_cli.main(["verify-chat"]) == 3
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"


def test_ready_review_and_matching_installation_open_bridge_admission(
    monkeypatch, capsys
) -> None:
    _install_declared(monkeypatch, _gate(write=True, stream=True))
    monkeypatch.setattr(
        hermes_capability_cli,
        "_probe_review",
        lambda _path: {"trusted": True, "verdict": "ready", "blocker": None},
    )

    assert hermes_capability_cli.main(["verify-chat"]) == 0
    document = json.loads(capsys.readouterr().out)
    assert document["status"] == "ready"
    # Approval and stop are independent from ordinary safe chat admission.
    assert document["gate"]["approval_enabled"] is False
    assert document["gate"]["stop_enabled"] is False


def test_matching_ready_snapshot_stays_blocked_when_installation_drifted(
    monkeypatch, capsys
) -> None:
    _install_declared(monkeypatch, _gate(write=True, stream=True))
    monkeypatch.setattr(
        hermes_capability_cli,
        "_probe_review",
        lambda _path: {"trusted": True, "verdict": "ready", "blocker": None},
    )
    monkeypatch.setattr(
        hermes_capability_cli,
        "_probe_installation",
        lambda: {**_contract(), "server_source_sha256": "0" * 64},
    )

    assert hermes_capability_cli.main(["verify-chat"]) == 3
    document = json.loads(capsys.readouterr().out)
    assert document["gate"]["chat_read_enabled"] is False
    assert document["gate"]["chat_write_enabled"] is False
    assert "installation_fingerprint_mismatch" in document["gate"]["blockers"]


def test_missing_review_closes_reads_and_writes(monkeypatch, capsys) -> None:
    _install_declared(monkeypatch, _gate(write=True, stream=True))
    monkeypatch.setattr(
        hermes_capability_cli,
        "_probe_review",
        lambda _path: {
            "trusted": False,
            "verdict": "unreviewed",
            "blocker": "contract_unreviewed",
        },
    )

    assert hermes_capability_cli.main(["verify-chat"]) == 3
    gate = json.loads(capsys.readouterr().out)["gate"]
    assert gate["chat_read_enabled"] is False
    assert gate["chat_write_enabled"] is False


def test_tracked_source_dirty_closes_reads_and_writes(monkeypatch, capsys) -> None:
    _install_declared(monkeypatch, _gate(write=True, stream=True))
    monkeypatch.setattr(
        hermes_capability_cli,
        "_probe_review",
        lambda _path: {"trusted": True, "verdict": "ready", "blocker": None},
    )
    monkeypatch.setattr(
        hermes_capability_cli,
        "_probe_installation",
        lambda: {**_contract(), "source_tracked_clean": False},
    )

    assert hermes_capability_cli.main(["verify-chat"]) == 3
    gate = json.loads(capsys.readouterr().out)["gate"]
    assert gate["chat_read_enabled"] is False
    assert "installation_source_dirty" in gate["blockers"]


def test_verify_chat_rejects_contract_override(capsys) -> None:
    assert hermes_capability_cli.main(
        ["verify-chat", "--contract", "/tmp/all-true.json"]
    ) == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "invalid_arguments"
~~~

Also add table-driven tests for <code>_probe_review</code> that use a temporary Git repository and reject: missing/unknown review fields, an invalid digest or commit, contract bytes that differ from <code>contract_sha256</code>, a reviewed commit that is not an ancestor of HEAD, contract bytes at the reviewed commit that differ from the working default contract, working default-contract bytes that differ from the checked-in HEAD blob even when they match an older reviewed ancestor, and review-record bytes that differ from the checked-in HEAD blob. Add a probe-exception test proving <code>installation_probe_failed</code> closes reads and every mutation gate without leaking subprocess stderr.

- [ ] **Step 2: Run the focused test and confirm RED**

Run: <code>./.venv/bin/pytest -q tests/test_hermes_capability_cli.py</code>

Expected: collection fails because <code>hqa.hermes_capability_cli</code> does not exist.

- [ ] **Step 3: Implement the CLI without service or provider calls**

Create <code>hqa/hermes_capability_cli.py</code>:

~~~python
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from hqa import config
from hqa.hermes_capabilities import (
    CapabilityContractError,
    evaluate_chat_gate,
    load_capabilities,
)


class _ArgumentError(ValueError):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _ArgumentError(message)


def _emit(document: dict) -> None:
    sys.stdout.write(
        json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="hqa-hermes-capabilities")
    sub = parser.add_subparsers(dest="command", required=True)
    show = sub.add_parser("show")
    show.add_argument(
        "--contract",
        type=Path,
        default=config.HERMES_GATEWAY_CAPABILITIES_PATH,
    )
    sub.add_parser("verify-chat")
    return parser


def _read(path: Path) -> dict:
    capabilities = load_capabilities(path)
    gate = evaluate_chat_gate(capabilities)
    contract = asdict(capabilities)
    contract["relevant_methods_observed"] = sorted(
        capabilities.relevant_methods_observed
    )
    return {"contract": contract, "declared_gate": gate.to_dict()}


def _git_bytes(*args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(config.REPO_DIR), *args],
        check=True,
        capture_output=True,
        shell=False,
        timeout=5,
    ).stdout


def _probe_review(contract_path: Path) -> dict:
    if contract_path != config.HERMES_GATEWAY_CAPABILITIES_PATH:
        return {
            "trusted": False,
            "verdict": "unreviewed",
            "blocker": "custom_contract_unreviewed",
        }
    try:
        contract_bytes = contract_path.read_bytes()
        review_bytes = config.HERMES_GATEWAY_REVIEW_PATH.read_bytes()
        review = json.loads(review_bytes.decode("utf-8"))
        if not isinstance(review, dict) or set(review) != {
            "schema_version",
            "contract_sha256",
            "reviewed_commit",
            "reviewed_at",
            "verdict",
            "reason",
        }:
            raise ValueError("invalid review schema")
        if review["schema_version"] != "1.0" or review["verdict"] not in {
            "blocked",
            "ready",
        }:
            raise ValueError("unsupported review")
        digest = hashlib.sha256(contract_bytes).hexdigest()
        if (
            not re.fullmatch(r"[0-9a-f]{64}", str(review["contract_sha256"]))
            or review["contract_sha256"] != digest
            or not re.fullmatch(r"[0-9a-f]{40}", str(review["reviewed_commit"]))
            or not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z",
                str(review["reviewed_at"]),
            )
            or not isinstance(review["reason"], str)
            or not review["reason"].strip()
        ):
            raise ValueError("invalid review identity")
        contract_rel = contract_path.relative_to(config.REPO_DIR).as_posix()
        review_rel = config.HERMES_GATEWAY_REVIEW_PATH.relative_to(
            config.REPO_DIR
        ).as_posix()
        ancestor = subprocess.run(
            [
                "git",
                "-C",
                str(config.REPO_DIR),
                "merge-base",
                "--is-ancestor",
                str(review["reviewed_commit"]),
                "HEAD",
            ],
            check=False,
            capture_output=True,
            shell=False,
            timeout=5,
        )
        if ancestor.returncode != 0:
            raise ValueError("reviewed commit is not an ancestor")
        if _git_bytes("show", f"HEAD:{contract_rel}") != contract_bytes:
            raise ValueError("contract is not checked in at HEAD")
        if _git_bytes("show", f'{review["reviewed_commit"]}:{contract_rel}') != contract_bytes:
            raise ValueError("reviewed contract differs")
        if _git_bytes("show", f"HEAD:{review_rel}") != review_bytes:
            raise ValueError("review record is not checked in")
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
        subprocess.SubprocessError,
    ):
        return {
            "trusted": False,
            "verdict": "unreviewed",
            "blocker": "contract_unreviewed",
        }
    verdict = str(review["verdict"])
    return {
        "trusted": True,
        "verdict": verdict,
        "blocker": None if verdict == "ready" else "contract_review_blocked",
        "contract_sha256": str(review["contract_sha256"]),
        "reviewed_commit": str(review["reviewed_commit"]),
    }


def _append_blocker(values: list[str], blocker: str) -> list[str]:
    return values if blocker in values else [*values, blocker]


def _close_gate(gate: dict, blocker: str, *, close_read: bool) -> dict:
    closed = {
        **gate,
        "chat_write_enabled": False,
        "stream_enabled": False,
        "resume_enabled": False,
        "approval_enabled": False,
        "stop_enabled": False,
    }
    if close_read:
        closed["chat_read_enabled"] = False
    for field in (
        "blockers",
        "resume_blockers",
        "approval_blockers",
        "stop_blockers",
    ):
        closed[field] = _append_blocker(list(closed.get(field, [])), blocker)
    return closed


def _apply_review_gate(document: dict, contract_path: Path) -> dict:
    review = _probe_review(contract_path)
    gate = dict(document["declared_gate"])
    blocker = review["blocker"]
    if blocker is not None:
        gate = _close_gate(gate, blocker, close_read=not review["trusted"])
    return {
        **document,
        "snapshot_readable": True,
        "gate": gate,
        "review": review,
    }


def _probe_installation() -> dict:
    version = subprocess.run(
        [str(config.HERMES_BIN_PATH), "--version"],
        check=True,
        capture_output=True,
        text=True,
        shell=False,
        timeout=5,
    ).stdout
    match = re.search(
        r"^Hermes Agent v(?P<version>\S+).*upstream (?P<upstream>[0-9a-f]+)$",
        version,
        flags=re.MULTILINE,
    )
    if match is None:
        raise ValueError("unrecognized Hermes version output")
    checkout = subprocess.run(
        ["git", "-C", str(config.HERMES_SOURCE_DIR), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        shell=False,
        timeout=5,
    ).stdout.strip()
    tracked_status = subprocess.run(
        [
            "git",
            "-C",
            str(config.HERMES_SOURCE_DIR),
            "status",
            "--porcelain",
            "--untracked-files=no",
        ],
        check=True,
        capture_output=True,
        text=True,
        shell=False,
        timeout=5,
    ).stdout
    server_bytes = (config.HERMES_SOURCE_DIR / "tui_gateway" / "server.py").read_bytes()
    return {
        "hermes_version": match.group("version"),
        "upstream_commit": match.group("upstream"),
        "source_checkout_commit": checkout,
        "server_source_sha256": hashlib.sha256(server_bytes).hexdigest(),
        "source_tracked_clean": not tracked_status.strip(),
    }


def _apply_installation_gate(document: dict) -> dict:
    expected = {
        key: document["contract"][key]
        for key in (
            "hermes_version",
            "upstream_commit",
            "source_checkout_commit",
            "server_source_sha256",
        )
    }
    try:
        actual = _probe_installation()
        actual_identity = {key: actual.get(key) for key in expected}
        if actual.get("source_tracked_clean") is not True:
            blocker = "installation_source_dirty"
        else:
            blocker = (
                None
                if actual_identity == expected
                else "installation_fingerprint_mismatch"
            )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        actual = {"error": type(exc).__name__}
        blocker = "installation_probe_failed"
    gate = document["gate"]
    if blocker is not None:
        gate = _close_gate(gate, blocker, close_read=True)
    return {
        **document,
        "gate": gate,
        "installation": {"matches_snapshot": blocker is None, "actual": actual},
    }


def main(argv: Optional[list[str]] = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except _ArgumentError as exc:
        _emit({"error": {"code": "invalid_arguments", "message": str(exc)}})
        return 2
    try:
        contract_path = (
            args.contract
            if args.command == "show"
            else config.HERMES_GATEWAY_CAPABILITIES_PATH
        )
        document = _read(contract_path)
        document = _apply_review_gate(document, contract_path)
        document = _apply_installation_gate(document)
    except CapabilityContractError as exc:
        _emit({"error": {"code": "capability_contract_invalid", "message": str(exc)}})
        return 1
    if args.command == "show":
        _emit(document)
        return 0
    enabled = (
        document["gate"]["chat_write_enabled"] is True
        and document["gate"]["stream_enabled"] is True
    )
    _emit({"status": "ready" if enabled else "blocked", **document})
    return 0 if enabled else 3


if __name__ == "__main__":
    raise SystemExit(main())
~~~

- [ ] **Step 4: Run CLI tests and live read-only display**

Run:

~~~bash
./.venv/bin/pytest -q tests/test_hermes_capability_cli.py
./.venv/bin/python -m hqa.hermes_capability_cli show
./.venv/bin/python -m hqa.hermes_capability_cli verify-chat
~~~

Expected before Task 4: tests pass; <code>show</code> exits 0, reports <code>snapshot_readable=true</code> and <code>installation.matches_snapshot=true</code>, but the effective read/write gates remain closed with <code>contract_unreviewed</code>. <code>verify-chat</code> exits 3. No Hermes session appears and no provider usage changes.

- [ ] **Step 5: Commit the CLI**

~~~bash
git add hqa/config.py hqa/hermes_capability_cli.py tests/test_hermes_capability_cli.py
git commit -m "feat(hqa): expose Hermes chat readiness as strict JSON"
~~~

---

### Task 3: Reproducible evidence and bridge-plan admission gate

**Files:**

- Create: <code>docs/contracts/hermes-gateway-0.18.2.md</code>
- Modify: <code>docs/README.md</code>
- Modify: <code>docs/superpowers/specs/2026-07-13-hermes-unified-research-workbench-design.md</code>

**Interfaces:**

- Consumes: the checked-in contract and read-only local commands.
- Produces: a written admission rule for the next bridge plan.

- [ ] **Step 1: Record the exact evidence**

Write <code>docs/contracts/hermes-gateway-0.18.2.md</code> with these sections and exact commands:

~~~markdown
# Hermes gateway 0.18.2 capability evidence

Observed 2026-07-13. This document is a local compatibility snapshot, not a
promise about newer Hermes versions.

## Reproduce without a model call

    hermes --version
    hermes serve --help
    git -C /Users/sunyibo/.hermes/hermes-agent rev-parse HEAD
    git -C /Users/sunyibo/.hermes/hermes-agent status \
      --porcelain --untracked-files=no
    shasum -a 256 \
      /Users/sunyibo/.hermes/hermes-agent/tui_gateway/server.py
    rg -n '^@method\("(session|prompt|approval|config)' \
      /Users/sunyibo/.hermes/hermes-agent/tui_gateway/server.py
    rg -n \
      -e 'client_request|idempoten|request_correlation|request_lookup' \
      -e 'run_id|event_id|event_cursor' \
      -e 'requested_provider|actual_provider|fallback' \
      -e 'approval.*(digest|ttl|expir|single)' \
      -e 'interrupt.*(idempoten|reconcil)' \
      /Users/sunyibo/.hermes/hermes-agent/tui_gateway/server.py
    sed -n '1138,1152p' \
      /Users/sunyibo/.hermes/hermes-agent/tui_gateway/server.py
    sed -n '4515,4610p' \
      /Users/sunyibo/.hermes/hermes-agent/tui_gateway/server.py
    sed -n '5161,5304p' \
      /Users/sunyibo/.hermes/hermes-agent/tui_gateway/server.py
    sed -n '5528,5680p' \
      /Users/sunyibo/.hermes/hermes-agent/tui_gateway/server.py
    sed -n '8420,8525p' \
      /Users/sunyibo/.hermes/hermes-agent/tui_gateway/server.py
    sed -n '8114,8170p' \
      /Users/sunyibo/.hermes/hermes-agent/tui_gateway/server.py
    sed -n '10199,10315p' \
      /Users/sunyibo/.hermes/hermes-agent/tui_gateway/server.py

Record both matching and zero-result searches. A false capability means the
specific create/submit/event/interrupt/approval/Run contract lacks the required
semantic guarantee; it does not claim that a similarly named token is absent
from unrelated billing, process, or internal implementation code.

## Confirmed read surface

session.list, session.status and session.history exist.

## Stateful resume surface

session.resume exists, but rebinds a transport and may restore/build an agent.
It is a separately gated mutation and is not authorized by chat_read_enabled.

## Confirmed mutation surface

session.create, prompt.submit, session.interrupt, approval.respond and config.set
exist. session.create accepts a per-session model/provider override; config.set
can later switch the session model/provider, so the primary policy is not locked.

## Missing recovery contract

session.create and prompt.submit expose no client idempotency key, durable
request-correlation metadata, lookup by client request ID or caller-supplied
Run ID. The inspected session contract does not prove an immutable primary or
fallback provider policy. Events have no
durable event_id/cursor replay contract. The inspected turn output does not
provide immutable requested/actual provider+model, fallback from/to/reason, and
usage evidence bound to the same Run. approval.respond has no command-digest,
TTL, or single-use binding; session.interrupt has no Run-scoped idempotent
reconciliation contract.

## Admission rule

A bridge implementation plan may be written only after a newly observed
contract makes hqa.hermes_capability_cli verify-chat exit 0 with
review.verdict=ready and installation.matches_snapshot=true. Until then the
platform may display read-only/offline capability state, but session creation,
session resume, prompt submit, streaming, approval and stop remain disabled. The old
/api/agent/tasks endpoint is not a fallback.
~~~

- [ ] **Step 2: Make the current execution status unambiguous**

Update <code>docs/README.md</code> so the current table names this capability plan, the candidate-integrity plan, and the frontend plan as the first selected wave. State explicitly:

~~~markdown
The real Hermes chat mutation slice is not selected. The fingerprinted Hermes
0.18.2 installation exposes the
needed JSON-RPC method names but does not yet satisfy D-31 request-recovery,
event-replay, Run identity, immutable session provider/fallback policy, or
actual-provider evidence. The checked-in capability evaluator and Git-bound
independent review therefore keep chat/resume/approval/stop disabled.
~~~

Update section 14 of the D-31 spec from “implementation plan not written” to:

~~~markdown
The first implementation wave is split into three independently testable plans:
gateway capability contract, candidate integrity/Gate 3, and professional
frontend/read-only shell. The bridge/chat plan is admitted only when
verify-chat returns ready against a Git-reviewed default contract and current
installed Hermes evidence.
~~~

- [ ] **Step 3: Verify docs and contract agree**

Run:

~~~bash
./.venv/bin/python -m hqa.hermes_capability_cli verify-chat
rg -n "missing_request_recovery|chat mutation|不.*fallback|/api/agent/tasks" \
  docs/README.md docs/contracts/hermes-gateway-0.18.2.md \
  docs/superpowers/specs/2026-07-13-hermes-unified-research-workbench-design.md
~~~

Expected before independent review: the CLI exits 3 with <code>contract_unreviewed</code> plus the declared capability blockers; every document says the write path is blocked for the same named reason and no document calls the old AgentRunner a fallback.

- [ ] **Step 4: Run the HQA suite**

Run: <code>./.venv/bin/pytest</code>

Expected: all existing and new tests pass; no network/model call occurs.

- [ ] **Step 5: Commit evidence and governance**

~~~bash
git add docs/README.md docs/contracts/hermes-gateway-0.18.2.md \
  docs/superpowers/specs/2026-07-13-hermes-unified-research-workbench-design.md
git commit -m "docs(hermes): freeze gateway contract and chat admission gate"
~~~

---

### Task 4: Independent review and next-plan decision record

**Files:**

- Create: <code>config/hermes-gateway-capabilities.v1.review.json</code>
- Modify: <code>docs/contracts/hermes-gateway-0.18.2.md</code>

**Interfaces:**

- Consumes: Tasks 1-3 and current installed Hermes source.
- Produces: a human-readable review verdict and a strict Git-bound machine record. The current verdict is blocked and does not enable chat.

- [ ] **Step 1: Request two-stage review**

First run <code>git status --short</code> and retain the exact pre-existing worktree baseline in the review notes; do not clean, stage, revert, or reinterpret any baseline entry.

Stage A uses <code>superpowers:requesting-code-review</code> for plan/spec compliance. Stage B invokes the user's professional <code>[@Code Reviewer](subagent://Code Reviewer)</code> against the committed Task-3 code and evidence, without sharing Stage A's conclusion. Both reviewers must independently return no unresolved P0/P1 before the review record is written. Require both to verify:

~~~text
1. Every true capability is supported by an exact Hermes source/help reference.
2. No missing capability is inferred from UI behavior.
3. verify-chat cannot become ready merely because method names exist or a stale
   snapshot was once ready.
4. session.resume is not classified as read; bridge admission requires both
   safe submit recovery and replayable stream identity.
5. Endpoint parsing rejects credentials, query/fragment data, wrong paths,
   non-loopback hosts and invalid ports without reflecting secret text.
6. A custom contract, missing/mismatched review record, uncommitted review edit,
   tracked Hermes source change, or installation drift closes the effective gate.
7. Approval and stop stay independently closed without blocking otherwise-safe
   ordinary chat.
8. No secret, profile credential, state.db content, transcript, or provider token
   is checked into the contract.
9. No test invokes Grok, Codex, prompt.submit, session.create, session.resume,
   paper, or live paths.
10. relevant_methods_observed is explicitly an allowlisted subset, not a claim
    to freeze the complete server registry.
11. Primary-provider/model immutability, fallback-policy immutability, and the
    complete per-Run requested/actual/fallback/usage evidence are proved
    separately; targeted source searches support every false value.
~~~

- [ ] **Step 2: Capture immutable review inputs**

Run these commands separately and retain their verbatim output:

~~~bash
git rev-parse HEAD
shasum -a 256 config/hermes-gateway-capabilities.v1.json
date -u +%Y-%m-%dT%H:%M:%SZ
~~~

The HEAD value is the reviewed Task-3 commit. Confirm <code>git show &lt;reviewed-commit&gt;:config/hermes-gateway-capabilities.v1.json</code> is byte-identical to the working file. Do not review an uncommitted contract.

- [ ] **Step 3: Write both review records**

With <code>apply_patch</code>, append an <code>Independent review</code> section to the evidence document whose timestamp, contract digest, and <code>Commit reviewed</code> values are the verbatim command outputs. For the frozen 0.18.2 snapshot, record <code>Verdict: BLOCKED</code> and this exact reason: <code>current Hermes contract lacks deterministic request recovery, replayable event identity, Run identity, immutable provider/fallback policy and actual-provider evidence.</code>

Create <code>config/hermes-gateway-capabilities.v1.review.json</code> with no placeholders left:

~~~json
{
  "schema_version": "1.0",
  "contract_sha256": "<64-character shasum output>",
  "reviewed_commit": "<40-character git rev-parse output>",
  "reviewed_at": "<UTC timestamp output>",
  "verdict": "blocked",
  "reason": "current Hermes contract lacks deterministic request recovery, replayable event identity, Run identity, immutable provider/fallback policy and actual-provider evidence."
}
~~~

Change <code>verdict</code> to <code>ready</code> only in a later independent-review commit when newly cited source evidence changes the checked-in contract, every required capability is true, the review digest/commit checks pass, and <code>verify-chat</code> would otherwise pass the live installation gate. A local uncommitted edit is never sufficient.

- [ ] **Step 4: Verify the uncommitted record is not trusted**

Run:

~~~bash
./.venv/bin/python -m hqa.hermes_capability_cli verify-chat
git diff --check
git status --short
~~~

Expected: exit 3 and <code>contract_unreviewed</code> is still present because the review record is not yet part of HEAD. Relative to the recorded Step-1 baseline, only the intended review document and JSON record are new modifications. Pre-existing dirty/untracked files remain byte-identical and must not be removed.

- [ ] **Step 5: Commit the review record**

~~~bash
git add config/hermes-gateway-capabilities.v1.review.json \
  docs/contracts/hermes-gateway-0.18.2.md
git commit -m "docs(review): confirm Hermes chat remains fail closed"
~~~

- [ ] **Step 6: Verify the committed blocked verdict**

Run:

~~~bash
./.venv/bin/pytest -q tests/test_hermes_capabilities.py tests/test_hermes_capability_cli.py
./.venv/bin/python -m hqa.hermes_capability_cli show
./.venv/bin/python -m hqa.hermes_capability_cli verify-chat
git diff --check
git status --short
~~~

Expected: tests pass; <code>show</code> reports a trusted <code>review.verdict=blocked</code>, matching installation, and effective read access for list/status/history; <code>verify-chat</code> exits 3 with the five current capability blockers plus <code>contract_review_blocked</code>. Resume/chat/stream/approval/stop remain false. No Hermes session or provider usage appears.

## Completion criteria

- The installed gateway facts are machine-readable and reproducible without a provider call.
- Unknown schema, non-loopback endpoint, or malformed evidence fails closed.
- The current 0.18.2 contract exposes only list/status/history reads; resume/chat/stream/approval/stop remain closed.
- The current blocker is visible in <code>docs/README.md</code>.
- No BFF, database migration, browser mutation, session creation, model call, paper path, or live path was added.
- The plan explicitly leaves runtime process identity/handshake to the later bridge slice; it does not confuse a clean matching checkout with a verified running server.
- A later bridge plan cannot claim admission until a fresh source-backed contract and committed independent <code>ready</code> review make <code>verify-chat</code> exit 0 against a clean matching installation.

from __future__ import annotations

import hashlib
import io
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from hqa import paper_research_cli
from hqa.intent_payload_crypto import DeterministicCryptoFake
from hqa.intent_payloads import IntentPayloadStore
from hqa.research_claim import build_research_claim, research_claim_digest
from hqa.workflow_authority import WorkflowAuthority
from hqa.workflow_contract import (
    BindCandidateManifest,
    ConfirmFormula,
    ObserveGate3,
    ResolveDomainGate,
    StartResearch,
)

_CREATED_AT = datetime.now(timezone.utc) - timedelta(minutes=1)
CREATED_AT = _CREATED_AT.isoformat(timespec="microseconds").replace("+00:00", "Z")
EXPIRES = (
    (_CREATED_AT + timedelta(days=10))
    .isoformat(timespec="microseconds")
    .replace("+00:00", "Z")
)
PLAN_DIGEST = "1" * 64
SOURCE_BYTES = (
    b"def paper_reversal(short_return: float, long_return: float) -> float:\n"
    b"    return -short_return + long_return\n"
)
SOURCE_DIGEST = hashlib.sha256(SOURCE_BYTES).hexdigest()
CANDIDATE_DIGEST = "3" * 64
BASE_COMMIT = "4" * 40
CONFIRMATION_ID = "gate1-" + "5" * 32
FINAL_RECEIPT = "backtest-" + "6" * 32
PROMOTION_ID = "promo-" + "7" * 32 + "-r10"
REVIEWED_COMMIT = "8" * 40
WORKSPACE_ID = "workspace-root"
PLATFORM_SESSION_ID = "managed-paper-session"
HERMES_SESSION_ID = "web_managed_paper_session"
PLAN_COMMAND_ID = "10000000-0000-4000-8000-000000000001"
GATE1_COMMAND_ID = "10000000-0000-4000-8000-000000000002"
GATE2_COMMAND_ID = "10000000-0000-4000-8000-000000000003"
GATE3_COMMAND_ID = "10000000-0000-4000-8000-000000000004"
PLAN_SUBJECT_COMMAND_ID = "20000000-0000-4000-8000-000000000001"
FINAL_SUBJECT_COMMAND_ID = "20000000-0000-4000-8000-000000000002"
PLAN_SUBJECT_RUN_ID = "hermes-plan-subject-run"
FINAL_SUBJECT_RUN_ID = "hermes-final-subject-run"
FINAL_OUTPUT_DIGEST = "f" * 64
PAPER_TITLE = (
    "Short-Term Reversals and Longer-Term Momentum Around the World: "
    "Theory and Evidence"
)
ORDERED_UNIVERSE = [
    "SPY",
    "QQQ",
    "IWM",
    "DIA",
    "XLK",
    "XLF",
    "XLV",
    "XLY",
    "XLP",
    "XLE",
]
RESEARCH_CLAIM = build_research_claim(PAPER_TITLE, ORDERED_UNIVERSE)
RESEARCH_CLAIM_DIGEST = research_claim_digest(RESEARCH_CLAIM)


def _final_backtest_evidence(
    _receipt_id: str,
    _candidate_id: str,
    _candidate_digest: str,
) -> dict:
    return {
        "final_backtest_provider": "futu",
        "final_backtest_receipt_digest": "0" * 64,
        "final_backtest_config_ref": "/evidence/config.json",
        "final_backtest_config_digest": "1" * 64,
        "final_backtest_summary_ref": "/evidence/summary.json",
        "final_backtest_summary_digest": "2" * 64,
        "final_backtest_report_ref": "/evidence/report.json",
        "final_backtest_report_digest": "3" * 64,
    }


class _PayloadStore:
    def __init__(self) -> None:
        self.records: dict[str, dict] = {}
        self.envelopes: dict[str, dict] = {}
        self.bind_calls: list[tuple[str, str]] = []
        self.put_calls: list[dict] = []

    def add(
        self,
        payload_ref: str,
        kind: str,
        *,
        research_claim: dict | None = None,
        prompt: str = "PRIVATE-test-paper-body",
    ) -> None:
        provider_policy = paper_research_cli._managed_session_policy(
            platform_session_id=PLATFORM_SESSION_ID,
            hermes_session_id=HERMES_SESSION_ID,
        )
        record = {
            "schema_version": "2.0",
            "payload_ref": payload_ref,
            "payload_digest": payload_ref.removeprefix("payload:sha256:"),
            "kind": kind,
            "owner_id": "owner-test",
            "workspace_id": f"workspace:{WORKSPACE_ID}",
            "session_id": f"session:{PLATFORM_SESSION_ID}",
            "client_intent_id": f"intent-{len(self.records) + 1}",
            "provider_policy_digest": paper_research_cli.hashlib.sha256(
                paper_research_cli._canonical_bytes(provider_policy)
            ).hexdigest(),
            "created_at": CREATED_AT,
            "expires_at": EXPIRES,
            "ttl_days": 10,
            "status": "active",
            "consumer_ref": None,
        }
        envelope = {
            "schema_version": "2.0",
            "kind": kind,
            "owner_id": "owner-test",
            "workspace_id": f"workspace:{WORKSPACE_ID}",
            "session_id": f"session:{PLATFORM_SESSION_ID}",
            "client_intent_id": record["client_intent_id"],
            "provider_policy": provider_policy,
            "prompt": prompt,
            "ttl_days": 10,
            "provider_policy_digest": record["provider_policy_digest"],
            "created_at": CREATED_AT,
            "expires_at": EXPIRES,
        }
        if research_claim is not None:
            envelope["research_claim"] = dict(research_claim)
        self.records[payload_ref] = record
        self.envelopes[payload_ref] = envelope

    def put(self, request):
        self.put_calls.append(dict(request))
        digest = paper_research_cli.hashlib.sha256(
            paper_research_cli._canonical_bytes(request)
        ).hexdigest()
        payload_ref = f"payload:sha256:{digest}"
        existing = next(
            (
                record
                for record in self.records.values()
                if record["client_intent_id"] == request["client_intent_id"]
                and record["owner_id"] == request["owner_id"]
                and record["workspace_id"] == request["workspace_id"]
                and record["session_id"] == request["session_id"]
            ),
            None,
        )
        if existing is not None:
            if existing["payload_ref"] != payload_ref:
                raise paper_research_cli.IntentPayloadError(
                    "intent_idempotency_conflict",
                    "test intent idempotency conflict",
                )
            return dict(existing)
        created_at = CREATED_AT
        expires_at = (
            (
                datetime.fromisoformat(created_at.removesuffix("Z") + "+00:00")
                + timedelta(days=request["ttl_days"])
            )
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
        provider_policy_digest = paper_research_cli.hashlib.sha256(
            paper_research_cli._canonical_bytes(request["provider_policy"])
        ).hexdigest()
        record = {
            "schema_version": request["schema_version"],
            "payload_ref": payload_ref,
            "payload_digest": digest,
            "kind": request["kind"],
            "owner_id": request["owner_id"],
            "workspace_id": request["workspace_id"],
            "session_id": request["session_id"],
            "client_intent_id": request["client_intent_id"],
            "provider_policy_digest": provider_policy_digest,
            "created_at": created_at,
            "expires_at": expires_at,
            "ttl_days": request["ttl_days"],
            "status": "active",
            "consumer_ref": None,
        }
        self.records[payload_ref] = record
        envelope = {
            **request,
            "provider_policy_digest": provider_policy_digest,
            "created_at": created_at,
            "expires_at": expires_at,
        }
        self.envelopes[payload_ref] = envelope
        return dict(record)

    def status(
        self,
        payload_ref,
        *,
        owner_id,
        workspace_id,
        session_id,
    ):
        record = self.records[payload_ref]
        return dict(record)

    def bind_consumer(
        self,
        *,
        payload_ref,
        consumer_ref,
        owner_id,
        workspace_id,
        session_id,
    ):
        record = self.records[payload_ref]
        assert record["owner_id"] == owner_id
        assert record["workspace_id"] == workspace_id
        assert record["session_id"] == session_id
        if record["consumer_ref"] not in {None, consumer_ref}:
            raise AssertionError("test payload consumer conflict")
        record["consumer_ref"] = consumer_ref
        self.bind_calls.append((payload_ref, consumer_ref))
        return dict(record)

    def resolve(
        self,
        payload_ref,
        *,
        owner_id,
        workspace_id,
        session_id,
        consumer_ref=None,
    ):
        record = self.records[payload_ref]
        assert record["owner_id"] == owner_id
        assert record["workspace_id"] == workspace_id
        assert record["session_id"] == session_id
        assert record["consumer_ref"] == consumer_ref
        return dict(self.envelopes[payload_ref])


class _Registry:
    def __init__(self) -> None:
        self.gates: dict[str, dict] = {}
        self.register_calls: list[dict] = []
        self.completion_calls: list[dict] = []
        self.attest_calls: list[dict] = []
        self.attestation_mutator = None
        self.attestation_post_mutator = None
        self.completion_mutator = None

    def attest(self, document):
        request = dict(document)
        self.attest_calls.append(request)
        if request["mode"] == "invocation":
            attestation = {
                **request,
                "schema_version": 1,
                "resolved_hermes_session_id": request["hermes_session_id"],
                "command_state": "delivered",
                "hqa_run_ref": None,
                "actual_model": None,
                "actual_provider": None,
                "output_digest": None,
                "hermes_runtime_instance_id": None,
                "hermes_runtime_started_at": None,
                "terminal_event_ref": None,
            }
        else:
            is_plan = request["command_id"] == PLAN_SUBJECT_COMMAND_ID
            attestation = {
                **request,
                "schema_version": 1,
                "resolved_hermes_session_id": request["hermes_session_id"],
                "command_state": "succeeded",
                "hqa_run_ref": ("run:paper-plan" if is_plan else "run:paper-final"),
                "actual_model": "test-model",
                "actual_provider": "test-provider",
                "output_digest": PLAN_DIGEST if is_plan else FINAL_OUTPUT_DIGEST,
                "hermes_runtime_instance_id": "runtime-test",
                "hermes_runtime_started_at": "2026-07-24T00:00:00Z",
                "terminal_event_ref": (
                    "hermes-event:plan" if is_plan else "hermes-event:final"
                ),
            }
        if self.attestation_mutator is not None:
            attestation = self.attestation_mutator(dict(attestation))
        evidence = {
            key: value
            for key, value in attestation.items()
            if key not in paper_research_cli._ATTESTATION_DERIVED_FIELDS
        }
        digest = paper_research_cli.hashlib.sha256(
            paper_research_cli._canonical_bytes(evidence)
        ).hexdigest()
        attestation.update(
            evidence_digest=digest,
            attestation_ref=f"paper-run-attestation:{digest}",
            provider_evidence_ref=(
                None
                if request["mode"] == "invocation"
                else f"provider-evidence:paper-run-{digest}"
            ),
        )
        if self.attestation_post_mutator is not None:
            attestation = self.attestation_post_mutator(dict(attestation))
        return attestation

    def register(self, document):
        payload = dict(document)
        self.register_calls.append(payload)
        current = self.gates.get(payload["gate_id"])
        if current is not None:
            return dict(current)
        gate = {**payload, "status": "pending"}
        self.gates[payload["gate_id"]] = gate
        return dict(gate)

    def show(
        self,
        gate_id,
        *,
        workspace_id,
        platform_session_id,
    ):
        gate = self.gates.get(gate_id)
        if gate is None:
            raise paper_research_cli._RegistryError(
                "paper_gate_not_found",
                retryable=False,
                not_found=True,
            )
        assert gate["workspace_id"] == workspace_id
        assert gate["platform_session_id"] == platform_session_id
        return dict(gate)

    def list(self, workspace_id):
        return [
            dict(gate)
            for gate in self.gates.values()
            if gate["workspace_id"] == workspace_id
        ]

    def complete(self, document):
        payload = dict(document)
        self.completion_calls.append(payload)
        completion = {
            field: payload["completion_evidence"][field]
            for field in (
                set(payload["completion_evidence"])
                & paper_research_cli._PLATFORM_COMPLETION_FIELDS
            )
        }
        completion.update(
            {
                "completion_evidence": payload["completion_evidence"],
                "created_at": "2026-07-24T00:00:00.000000Z",
                "gate_id": payload["gate_id"],
                "hqa_completion_receipt_digest": payload[
                    "hqa_completion_receipt_digest"
                ],
                "hqa_completion_receipt_ref": payload["hqa_completion_receipt_ref"],
                "reviewed_commit": payload["completion_evidence"]["reviewed_commit"],
                "status": "completed",
                "workspace_id": payload["workspace_id"],
            }
        )
        assert set(completion) == paper_research_cli._PLATFORM_COMPLETION_FIELDS
        gate = self.gates[payload["gate_id"]]
        previous = gate.get("completion")
        if previous is not None:
            assert previous == completion
            result = dict(completion)
            if self.completion_mutator is not None:
                result = self.completion_mutator(result)
            return result
        gate.update(
            completion=dict(completion),
            expected_status="completed",
            hqa_completion_receipt_digest=payload["hqa_completion_receipt_digest"],
            hqa_completion_receipt_ref=payload["hqa_completion_receipt_ref"],
            human_git_commit_required=False,
            reviewed_commit=payload["completion_evidence"]["reviewed_commit"],
            status="completed",
        )
        result = dict(completion)
        if self.completion_mutator is not None:
            result = self.completion_mutator(result)
        return result


def _authority(tmp_path: Path) -> WorkflowAuthority:
    return WorkflowAuthority(
        tmp_path / "workflow-authority",
        "owner-test",
        now=lambda: "2026-07-24T00:00:00.000000Z",
    )


def _stage_gate1_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    payload: bytes = SOURCE_BYTES,
    digest: str = SOURCE_DIGEST,
    mode: int = 0o600,
) -> Path:
    gate1_root = tmp_path / "factor-gate1"
    sources = gate1_root / "sources"
    sources.mkdir(parents=True, exist_ok=True)
    source = sources / f"source-{digest}.py"
    source.write_bytes(payload)
    source.chmod(mode)
    monkeypatch.setattr(paper_research_cli.config, "FACTOR_GATE1_DIR", gate1_root)
    return source


def _call(
    monkeypatch,
    capsys,
    *,
    operation: str,
    request: dict,
    authority: WorkflowAuthority,
    registry: _Registry,
    promotion_status_reader=lambda _promotion_id: (1, ""),
    final_backtest_reader=_final_backtest_evidence,
    payload_store=None,
) -> tuple[int, dict]:
    monkeypatch.setenv(
        "HERMES_PLATFORM_COMMAND_ID",
        request.get("command_id", PLAN_COMMAND_ID),
    )
    monkeypatch.setenv(
        "HERMES_PLATFORM_SESSION_ID",
        request.get("platform_session_id", PLATFORM_SESSION_ID),
    )
    monkeypatch.setenv(
        "HERMES_PLATFORM_RUN_ID",
        request.get("hermes_run_id", "hermes-current-run"),
    )
    monkeypatch.setenv(
        "HERMES_PLATFORM_MANAGED_SESSION_ID",
        HERMES_SESSION_ID,
    )
    monkeypatch.setattr(
        "sys.stdin",
        io.TextIOWrapper(
            io.BytesIO(json.dumps(request).encode("utf-8")),
            encoding="utf-8",
        ),
    )
    code = paper_research_cli.main(
        [operation],
        authority_factory=lambda: authority,
        registry=registry,
        promotion_status_reader=promotion_status_reader,
        final_backtest_reader=final_backtest_reader,
        payload_store=payload_store or _PayloadStore(),
    )
    return code, json.loads(capsys.readouterr().out)


def _start_request(
    *,
    payload_ref: str,
    plan_digest: str = PLAN_DIGEST,
) -> dict:
    return {
        "workspace_id": WORKSPACE_ID,
        "platform_session_id": PLATFORM_SESSION_ID,
        "payload_ref": payload_ref,
        "command_id": PLAN_COMMAND_ID,
        "hermes_run_id": "hermes-start-invocation-run",
        "subject_command_id": PLAN_SUBJECT_COMMAND_ID,
        "subject_hermes_run_id": PLAN_SUBJECT_RUN_ID,
        "plan_version": 1,
        "plan_digest": plan_digest,
    }


def test_prepare_intent_stores_current_user_body_without_workflow_or_output_leak(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    authority = _authority(tmp_path)
    registry = _Registry()
    payload_store = _PayloadStore()
    prompt = "PRIVATE-PAPER-BODY-prepare-intent-tracer"
    assert not authority.root.exists()

    code, document = _call(
        monkeypatch,
        capsys,
        operation="prepare-intent",
        request={
            "workspace_id": WORKSPACE_ID,
            "kind": "research_start",
            "prompt": prompt,
        },
        authority=authority,
        registry=registry,
        payload_store=payload_store,
    )

    assert code == 0
    assert document == {
        "client_intent_id": f"paper-intent:{PLAN_COMMAND_ID}",
        "command_id": PLAN_COMMAND_ID,
        "contract": "agent-v0.2-paper-research-cli/v1",
        "created_at": CREATED_AT,
        "expires_at": (
            datetime.fromisoformat(CREATED_AT.removesuffix("Z") + "+00:00")
            + timedelta(days=7)
        )
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
        "hermes_run_id": "hermes-current-run",
        "hermes_session_id": HERMES_SESSION_ID,
        "kind": "research_start",
        "ok": True,
        "operation": "prepare-intent",
        "owner_id": "owner-test",
        "payload_digest": document["payload_digest"],
        "payload_ref": f"payload:sha256:{document['payload_digest']}",
        "platform_session_id": PLATFORM_SESSION_ID,
        "provider_policy_digest": document["provider_policy_digest"],
        "status": "active",
        "ttl_days": 7,
        "workspace_id": WORKSPACE_ID,
    }
    assert prompt not in json.dumps(document)
    assert payload_store.put_calls == [
        {
            "schema_version": "2.0",
            "kind": "research_start",
            "owner_id": "owner-test",
            "workspace_id": f"workspace:{WORKSPACE_ID}",
            "session_id": f"session:{PLATFORM_SESSION_ID}",
            "client_intent_id": f"paper-intent:{PLAN_COMMAND_ID}",
            "provider_policy": {
                "hermes_session_id": HERMES_SESSION_ID,
                "platform_session_ref": f"session:{PLATFORM_SESSION_ID}",
                "policy_authority": "platform_session_registry",
                "schema_version": "agent-v0.2-managed-session-policy-ref/v1",
            },
            "prompt": prompt,
            "ttl_days": 7,
        }
    ]
    assert registry.attest_calls == [
        {
            "mode": "invocation",
            "workspace_id": WORKSPACE_ID,
            "platform_session_id": PLATFORM_SESSION_ID,
            "hermes_session_id": HERMES_SESSION_ID,
            "command_id": PLAN_COMMAND_ID,
            "hermes_run_id": "hermes-current-run",
        }
    ]
    assert registry.register_calls == []
    assert registry.completion_calls == []
    assert not authority.root.exists()


@pytest.mark.parametrize("kind", ["research_start", "research_continue"])
def test_prepare_intent_real_store_is_encrypted_metadata_only_and_idempotent(
    kind,
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    authority = _authority(tmp_path)
    registry = _Registry()
    payload_root = tmp_path / "intent-payloads"
    payload_store = IntentPayloadStore(
        payload_root,
        crypto=DeterministicCryptoFake(
            key=b"paper prepare intent encryption test".ljust(32, b"!")
        ),
    )
    prompt = f"PRIVATE-{kind}-正文\nsecond line"
    request = {
        "workspace_id": WORKSPACE_ID,
        "kind": kind,
        "prompt": prompt,
    }

    first_code, first = _call(
        monkeypatch,
        capsys,
        operation="prepare-intent",
        request=request,
        authority=authority,
        registry=registry,
        payload_store=payload_store,
    )
    second_code, second = _call(
        monkeypatch,
        capsys,
        operation="prepare-intent",
        request=request,
        authority=authority,
        registry=registry,
        payload_store=payload_store,
    )

    assert first_code == second_code == 0
    assert first == second
    assert first["kind"] == kind
    assert "prompt" not in first
    assert prompt not in json.dumps(first, ensure_ascii=False)
    assert not authority.root.exists()
    plaintext = prompt.encode("utf-8")
    for path in payload_root.rglob("*"):
        if path.is_file():
            assert plaintext not in path.read_bytes(), path


def test_claimed_research_start_is_encrypted_and_exact_variants_fail_closed(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    authority = _authority(tmp_path)
    registry = _Registry()
    payload_root = tmp_path / "claimed-intent-payloads"
    payload_store = IntentPayloadStore(
        payload_root,
        crypto=DeterministicCryptoFake(
            key=b"paper exact research claim binding".ljust(32, b"!")
        ),
    )
    private_prompt = "PRIVATE exact paper reproduction request"
    prepare_code, prepared = _call(
        monkeypatch,
        capsys,
        operation="prepare-intent",
        request={
            "workspace_id": WORKSPACE_ID,
            "kind": "research_start",
            "prompt": private_prompt,
            "paper_title": PAPER_TITLE,
            "universe": ORDERED_UNIVERSE,
        },
        authority=authority,
        registry=registry,
        payload_store=payload_store,
    )

    assert prepare_code == 0
    assert prepared["research_claim_digest"] == RESEARCH_CLAIM_DIGEST
    public_prepare = json.dumps(prepared, ensure_ascii=False)
    assert private_prompt not in public_prepare
    assert PAPER_TITLE not in public_prepare
    assert ",".join(ORDERED_UNIVERSE) not in public_prepare
    resolved = payload_store.resolve(
        prepared["payload_ref"],
        owner_id="owner-test",
        workspace_id=f"workspace:{WORKSPACE_ID}",
        session_id=f"session:{PLATFORM_SESSION_ID}",
    )
    assert resolved["prompt"] == private_prompt
    assert resolved["research_claim"] == RESEARCH_CLAIM
    private_needles = [
        private_prompt.encode(),
        PAPER_TITLE.encode(),
        json.dumps(ORDERED_UNIVERSE, separators=(",", ":")).encode(),
    ]
    for path in payload_root.rglob("*"):
        if path.is_file():
            raw = path.read_bytes()
            assert all(needle not in raw for needle in private_needles), path

    variants = [
        build_research_claim(PAPER_TITLE + "!", ORDERED_UNIVERSE),
        build_research_claim(
            PAPER_TITLE,
            [ORDERED_UNIVERSE[1], ORDERED_UNIVERSE[0], *ORDERED_UNIVERSE[2:]],
        ),
        build_research_claim(PAPER_TITLE, ORDERED_UNIVERSE[:-1]),
        build_research_claim(PAPER_TITLE, [*ORDERED_UNIVERSE, "TLT"]),
    ]
    for index, variant in enumerate(variants):
        code, rejected = _call(
            monkeypatch,
            capsys,
            operation="start-plan",
            request={
                **_start_request(
                    payload_ref=prepared["payload_ref"],
                ),
                "research_claim_digest": research_claim_digest(variant),
            },
            authority=authority,
            registry=registry,
            payload_store=payload_store,
        )
        assert code == 2
        assert rejected["error"]["code"] == ("paper_research_claim_binding_mismatch")
        rejected_output = json.dumps(rejected, ensure_ascii=False)
        assert private_prompt not in rejected_output
        assert PAPER_TITLE not in rejected_output
        assert not authority.root.exists()

    code, started = _call(
        monkeypatch,
        capsys,
        operation="start-plan",
        request={
            **_start_request(
                payload_ref=prepared["payload_ref"],
            ),
            "research_claim_digest": RESEARCH_CLAIM_DIGEST,
        },
        authority=authority,
        registry=registry,
        payload_store=payload_store,
    )
    assert code == 0, started
    assert started["research_claim_digest"] == RESEARCH_CLAIM_DIGEST
    snapshot = authority.snapshot(started["task_ref"])
    assert snapshot.research_claim_digest == RESEARCH_CLAIM_DIGEST
    assert snapshot.attempts[0].research_claim_digest == RESEARCH_CLAIM_DIGEST
    assert snapshot.attempts[0].payload_digest == prepared["payload_digest"]
    public_started = json.dumps(started, ensure_ascii=False)
    assert private_prompt not in public_started
    assert PAPER_TITLE not in public_started


def test_prepare_intent_same_current_command_rejects_different_body_without_leak(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    authority = _authority(tmp_path)
    registry = _Registry()
    payload_store = _PayloadStore()
    first_prompt = "PRIVATE-first-paper-body"
    second_prompt = "PRIVATE-conflicting-paper-body"
    base = {
        "workspace_id": WORKSPACE_ID,
        "kind": "research_start",
    }
    accepted_code, accepted = _call(
        monkeypatch,
        capsys,
        operation="prepare-intent",
        request={**base, "prompt": first_prompt},
        authority=authority,
        registry=registry,
        payload_store=payload_store,
    )
    conflict_code, conflict = _call(
        monkeypatch,
        capsys,
        operation="prepare-intent",
        request={**base, "prompt": second_prompt},
        authority=authority,
        registry=registry,
        payload_store=payload_store,
    )

    assert accepted_code == 0
    assert conflict_code == 2
    assert conflict["error"] == {
        "code": "paper_research_intent_conflict",
        "message": "paper research operation did not advance exactly",
        "retryable": False,
    }
    combined = json.dumps([accepted, conflict], ensure_ascii=False)
    assert first_prompt not in combined
    assert second_prompt not in combined
    assert len(payload_store.records) == 1
    assert not authority.root.exists()


def test_start_plan_consumes_payload_created_by_prepare_intent(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    authority = _authority(tmp_path)
    registry = _Registry()
    payload_store = IntentPayloadStore(
        tmp_path / "intent-payloads",
        crypto=DeterministicCryptoFake(
            key=b"paper prepare to start integration".ljust(32, b"!")
        ),
    )
    prepare_code, prepared = _call(
        monkeypatch,
        capsys,
        operation="prepare-intent",
        request={
            "workspace_id": WORKSPACE_ID,
            "kind": "research_start",
            "prompt": "Reproduce the exact paper factor with a plan first.",
        },
        authority=authority,
        registry=registry,
        payload_store=payload_store,
    )
    start_request = _start_request(payload_ref=prepared["payload_ref"])
    start_request.update(
        command_id=GATE1_COMMAND_ID,
        hermes_run_id="hermes-next-turn-start-run",
    )
    start_code, started = _call(
        monkeypatch,
        capsys,
        operation="start-plan",
        request=start_request,
        authority=authority,
        registry=registry,
        payload_store=payload_store,
    )

    assert prepare_code == start_code == 0
    assert started["workflow_state"] == "awaiting_plan_confirmation"
    assert started["attempt_ref"].startswith("attempt:")
    status = payload_store.status(
        prepared["payload_ref"],
        owner_id="owner-test",
        workspace_id=f"workspace:{WORKSPACE_ID}",
        session_id=f"session:{PLATFORM_SESSION_ID}",
    )
    assert status["consumer_ref"] == started["attempt_ref"]


@pytest.mark.parametrize(
    ("request_patch", "env_patch"),
    [
        ({"kind": "conversation_turn"}, {}),
        ({"kind": "research_start", "owner_id": "attacker"}, {}),
        ({"platform_session_id": "other-platform-session"}, {}),
        ({"hermes_session_id": "other-hermes-session"}, {}),
        ({"command_id": "30000000-0000-4000-8000-000000000001"}, {}),
        ({"hermes_run_id": "other-hermes-run"}, {}),
        ({}, {"HERMES_PLATFORM_MANAGED_SESSION_ID": None}),
    ],
)
def test_prepare_intent_rejects_kind_scope_or_runtime_selector_substitution(
    request_patch,
    env_patch,
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    authority = _authority(tmp_path)
    registry = _Registry()
    payload_store = _PayloadStore()
    monkeypatch.setenv("HERMES_PLATFORM_COMMAND_ID", PLAN_COMMAND_ID)
    monkeypatch.setenv("HERMES_PLATFORM_SESSION_ID", PLATFORM_SESSION_ID)
    monkeypatch.setenv("HERMES_PLATFORM_RUN_ID", "hermes-current-run")
    monkeypatch.setenv(
        "HERMES_PLATFORM_MANAGED_SESSION_ID",
        HERMES_SESSION_ID,
    )
    for key, value in env_patch.items():
        if value is None:
            monkeypatch.delenv(key)
        else:
            monkeypatch.setenv(key, value)
    request = {
        "workspace_id": WORKSPACE_ID,
        "kind": "research_start",
        "prompt": "PRIVATE-rejected-body",
        **request_patch,
    }
    monkeypatch.setattr(
        "sys.stdin",
        io.TextIOWrapper(
            io.BytesIO(json.dumps(request).encode("utf-8")),
            encoding="utf-8",
        ),
    )

    code = paper_research_cli.main(
        ["prepare-intent"],
        authority_factory=lambda: authority,
        registry=registry,
        payload_store=payload_store,
    )
    output = capsys.readouterr().out

    assert code == 2
    assert json.loads(output)["error"]["code"] == "paper_research_invalid_request"
    assert "PRIVATE-rejected-body" not in output
    assert payload_store.put_calls == []
    assert not authority.root.exists()


def test_prepare_intent_rejects_durable_workspace_attestation_mismatch_before_put(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    authority = _authority(tmp_path)
    registry = _Registry()
    registry.attestation_mutator = lambda attestation: {
        **attestation,
        "workspace_id": "different-workspace",
    }
    payload_store = _PayloadStore()

    code, document = _call(
        monkeypatch,
        capsys,
        operation="prepare-intent",
        request={
            "workspace_id": WORKSPACE_ID,
            "kind": "research_start",
            "prompt": "PRIVATE-workspace-mismatch-body",
        },
        authority=authority,
        registry=registry,
        payload_store=payload_store,
    )

    assert code == 2
    assert (
        document["error"]["code"] == "paper_research_run_attestation_binding_mismatch"
    )
    assert "PRIVATE-workspace-mismatch-body" not in json.dumps(document)
    assert payload_store.put_calls == []
    assert not authority.root.exists()


def test_prepare_intent_refuses_body_in_argv(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    authority = _authority(tmp_path)
    secret = "PRIVATE-argv-paper-body"
    code = paper_research_cli.main(
        ["prepare-intent", secret],
        authority_factory=lambda: authority,
        registry=_Registry(),
        payload_store=_PayloadStore(),
    )
    output = capsys.readouterr().out

    assert code == 2
    assert json.loads(output)["error"]["code"] == "paper_research_invalid_arguments"
    assert secret not in output
    assert not authority.root.exists()


@pytest.mark.parametrize("claimed", [False, True], ids=["legacy-v1", "claim-v2"])
def test_complete_paper_flow_with_server_derived_controls(
    tmp_path,
    monkeypatch,
    capsys,
    claimed,
) -> None:
    authority = _authority(tmp_path)
    registry = _Registry()
    payload1 = "payload:sha256:" + "a" * 64
    payload2 = "payload:sha256:" + "b" * 64
    payload_store = _PayloadStore()
    payload_store.add(
        payload1,
        "research_start",
        research_claim=RESEARCH_CLAIM if claimed else None,
        prompt="PRIVATE planning body",
    )
    payload_store.add(
        payload2,
        "research_continue",
        research_claim=RESEARCH_CLAIM if claimed else None,
        prompt="PRIVATE final body",
    )

    start_request = {
        "workspace_id": WORKSPACE_ID,
        "platform_session_id": PLATFORM_SESSION_ID,
        "payload_ref": payload1,
        "command_id": PLAN_COMMAND_ID,
        "hermes_run_id": "hermes-start-invocation-run",
        "subject_command_id": PLAN_SUBJECT_COMMAND_ID,
        "subject_hermes_run_id": PLAN_SUBJECT_RUN_ID,
        "plan_version": 1,
        **({"research_claim_digest": RESEARCH_CLAIM_DIGEST} if claimed else {}),
    }
    code, started = _call(
        monkeypatch,
        capsys,
        operation="start-plan",
        request=start_request,
        authority=authority,
        registry=registry,
        payload_store=payload_store,
    )
    assert code == 0, started
    assert started["workflow_state"] == "awaiting_plan_confirmation"
    assert started["plan_digest"] == PLAN_DIGEST
    assert started["operation_id"].startswith("paper-start-plan-op-")
    task_ref = started["task_ref"]
    plan_attempt_ref = started["attempt_ref"]

    # A new coordinator invocation reuses server-derived control identity. It
    # does not depend on the new current command/Run or require the hidden
    # official subject output digest to be copied into JSON.
    code, start_replayed = _call(
        monkeypatch,
        capsys,
        operation="start-plan",
        request={
            **start_request,
            "command_id": "10000000-0000-4000-8000-000000000011",
            "hermes_run_id": "hermes-start-retry-invocation-run",
        },
        authority=authority,
        registry=registry,
        payload_store=payload_store,
    )
    assert code == 0, start_replayed
    assert start_replayed["operation_id"] == started["operation_id"]
    assert start_replayed["task_ref"] == task_ref
    assert start_replayed["attempt_ref"] == plan_attempt_ref
    assert start_replayed["plan_digest"] == PLAN_DIGEST

    code, confirmed = _call(
        monkeypatch,
        capsys,
        operation="confirm-plan",
        request={
            "task_ref": task_ref,
            "expected_task_version": started["task_version"],
            "plan_version": 1,
            "plan_digest": PLAN_DIGEST,
            "confirmation_note": "I reviewed the exact paper plan.",
        },
        authority=authority,
        registry=registry,
        payload_store=payload_store,
    )
    assert code == 0, started
    assert confirmed["workflow_state"] == "awaiting_formula_confirmation"
    assert confirmed["operation_id"].startswith("paper-confirm-plan-op-")

    source_file = _stage_gate1_source(tmp_path, monkeypatch)
    gate1_request = {
        "workspace_id": WORKSPACE_ID,
        "platform_session_id": PLATFORM_SESSION_ID,
        "task_ref": task_ref,
        "expected_task_version": confirmed["task_version"],
        "attempt_ref": plan_attempt_ref,
        "command_id": GATE1_COMMAND_ID,
        "hermes_run_id": "hermes-gate1-run",
        "source_file_ref": str(source_file),
        "reviewed_source_sha256": SOURCE_DIGEST,
        **(
            {"research_claim_digest": RESEARCH_CLAIM_DIGEST}
            if claimed
            else {"universe": "US ETFs"}
        ),
    }

    wrong_title_digest = research_claim_digest(
        build_research_claim(PAPER_TITLE + "!", ORDERED_UNIVERSE)
    )
    adversarial_gate1_requests = (
        (
            "one-char-title",
            {"research_claim_digest": wrong_title_digest},
            "paper_research_claim_binding_mismatch",
        ),
        (
            "reordered-universe",
            {
                "universe": [
                    ORDERED_UNIVERSE[1],
                    ORDERED_UNIVERSE[0],
                    *ORDERED_UNIVERSE[2:],
                ]
            },
            "paper_research_invalid_request",
        ),
        (
            "missing-universe",
            {"universe": ORDERED_UNIVERSE[:-1]},
            "paper_research_invalid_request",
        ),
        (
            "extra-universe",
            {"universe": [*ORDERED_UNIVERSE, "TLT"]},
            "paper_research_invalid_request",
        ),
    )
    for _suffix, changes, expected_error in (
        adversarial_gate1_requests if claimed else ()
    ):
        adversarial = {
            **gate1_request,
            **changes,
        }
        registrations_before = len(registry.register_calls)
        code, rejected = _call(
            monkeypatch,
            capsys,
            operation="open-gate1",
            request=adversarial,
            authority=authority,
            registry=registry,
            payload_store=payload_store,
        )
        assert code == 2
        assert rejected["error"]["code"] == expected_error
        assert len(registry.register_calls) == registrations_before

    code, gate1_opened = _call(
        monkeypatch,
        capsys,
        operation="open-gate1",
        request=gate1_request,
        authority=authority,
        registry=registry,
        payload_store=payload_store,
    )
    assert code == 0
    gate1_id = gate1_opened["gate_id"]
    workflow_gate_ref = gate1_opened["hqa_gate_ref"]
    assert gate1_id.startswith("paper-gate1-")
    assert workflow_gate_ref.startswith("gate:paper-")
    assert gate1_opened["hqa_gate_lineage_ref"] == workflow_gate_ref
    assert gate1_opened["operation_id"].startswith("paper-open-gate1-op-")
    assert gate1_opened["gate"]["attempt_ref"] == plan_attempt_ref
    assert gate1_opened["gate"]["hqa_run_ref"] is None
    assert gate1_opened["gate"]["universe"] == (
        f"research-claim:sha256:{RESEARCH_CLAIM_DIGEST}" if claimed else "US ETFs"
    )
    assert {
        field: gate1_opened["gate"][field]
        for field in (
            "research_claim_digest",
            "research_start_payload_digest",
            "research_continue_payload_digest",
        )
    } == (
        {
            "research_claim_digest": RESEARCH_CLAIM_DIGEST,
            "research_start_payload_digest": "a" * 64,
            "research_continue_payload_digest": None,
        }
        if claimed
        else {
            "research_claim_digest": None,
            "research_start_payload_digest": None,
            "research_continue_payload_digest": None,
        }
    )
    if claimed:
        assert gate1_opened["research_claim_digest"] == RESEARCH_CLAIM_DIGEST
    else:
        assert "research_claim_digest" not in gate1_opened
    gate1_public = json.dumps(gate1_opened, ensure_ascii=False)
    assert PAPER_TITLE not in gate1_public
    assert not any(symbol in gate1_public for symbol in ORDERED_UNIVERSE)
    assert "PRIVATE planning body" not in gate1_public

    code, gate1_replayed = _call(
        monkeypatch,
        capsys,
        operation="open-gate1",
        request={
            **gate1_request,
            "command_id": "10000000-0000-4000-8000-000000000012",
            "hermes_run_id": "hermes-gate1-retry-run",
        },
        authority=authority,
        registry=registry,
        payload_store=payload_store,
    )
    assert code == 0, gate1_replayed
    assert gate1_replayed["platform_registration_replayed"] is True
    assert gate1_replayed["operation_id"] == gate1_opened["operation_id"]
    assert gate1_replayed["gate_id"] == gate1_id
    assert gate1_replayed["hqa_gate_ref"] == workflow_gate_ref
    assert gate1_replayed["hqa_gate_lineage_ref"] == workflow_gate_ref

    gate1_receipt = authority.apply(
        ConfirmFormula(
            "browser-gate1-confirm",
            task_ref,
            confirmed["task_version"],
            workflow_gate_ref,
            SOURCE_DIGEST,
            "Reviewed exact formula bytes.",
        )
    )
    registry.gates[gate1_id].update(
        status="confirmed",
        gate1_confirmation_id=CONFIRMATION_ID,
        hqa_receipt_ref="hqa-paper-gate:pgate-" + "1" * 32,
        hqa_receipt_digest="9" * 64,
    )

    gate2_request = {
        "parent_gate_id": gate1_id,
        "workspace_id": WORKSPACE_ID,
        "platform_session_id": PLATFORM_SESSION_ID,
        "task_ref": task_ref,
        "expected_task_version": gate1_receipt.task_version,
        "attempt_ref": plan_attempt_ref,
        "command_id": GATE2_COMMAND_ID,
        "hermes_run_id": "hermes-gate2-run",
        "reviewed_source_sha256": SOURCE_DIGEST,
        "gate1_confirmation_id": CONFIRMATION_ID,
        "candidate_id": "paper-factor",
        "expected_digest": CANDIDATE_DIGEST,
        "expected_status": "pending",
    }
    code, gate2_opened = _call(
        monkeypatch,
        capsys,
        operation="open-gate2",
        request=gate2_request,
        authority=authority,
        registry=registry,
        payload_store=payload_store,
    )
    assert code == 0
    gate2_id = gate2_opened["gate_id"]
    assert gate2_id.startswith("paper-gate2-")
    assert gate2_opened["operation_id"].startswith("paper-open-gate2-op-")
    assert gate2_opened["hqa_gate_ref"] == workflow_gate_ref
    assert gate2_opened["hqa_gate_lineage_ref"] == workflow_gate_ref
    assert gate2_opened["gate"]["attempt_ref"] == plan_attempt_ref
    assert {
        field: gate2_opened["gate"][field]
        for field in (
            "research_claim_digest",
            "research_start_payload_digest",
            "research_continue_payload_digest",
        )
    } == {
        "research_claim_digest": (RESEARCH_CLAIM_DIGEST if claimed else None),
        "research_start_payload_digest": "a" * 64 if claimed else None,
        "research_continue_payload_digest": None,
    }
    code, gate2_replayed = _call(
        monkeypatch,
        capsys,
        operation="open-gate2",
        request={
            **gate2_request,
            "command_id": "10000000-0000-4000-8000-000000000013",
            "hermes_run_id": "hermes-gate2-retry-run",
        },
        authority=authority,
        registry=registry,
        payload_store=payload_store,
    )
    assert code == 0, gate2_replayed
    assert gate2_replayed["platform_registration_replayed"] is True
    assert gate2_replayed["operation_id"] == gate2_opened["operation_id"]
    assert gate2_replayed["gate_id"] == gate2_id
    assert gate2_replayed["hqa_gate_ref"] == workflow_gate_ref

    gate2_receipt = authority.apply(
        BindCandidateManifest(
            "browser-gate2-bind",
            task_ref,
            gate1_receipt.task_version,
            workflow_gate_ref,
            "candidate:paper-factor",
            CANDIDATE_DIGEST,
        )
    )
    registry.gates[gate2_id].update(
        status="reviewed",
        hqa_receipt_ref="hqa-paper-gate:pgate-" + "2" * 32,
        hqa_receipt_digest="a" * 64,
    )

    gate3_request = {
        "parent_gate_id": gate2_id,
        "workspace_id": WORKSPACE_ID,
        "platform_session_id": PLATFORM_SESSION_ID,
        "task_ref": task_ref,
        "expected_task_version": gate2_receipt.task_version,
        "payload_ref": payload2,
        "command_id": GATE3_COMMAND_ID,
        "hermes_run_id": "hermes-gate3-invocation-run",
        "subject_command_id": FINAL_SUBJECT_COMMAND_ID,
        "subject_hermes_run_id": FINAL_SUBJECT_RUN_ID,
        "result_ref": f"result:{FINAL_RECEIPT}",
        "reviewed_source_sha256": SOURCE_DIGEST,
        "gate1_confirmation_id": CONFIRMATION_ID,
        "candidate_id": "paper-factor",
        "expected_digest": CANDIDATE_DIGEST,
        "final_backtest_receipt_id": FINAL_RECEIPT,
        "base_commit": BASE_COMMIT,
        **({"research_claim_digest": RESEARCH_CLAIM_DIGEST} if claimed else {}),
    }
    register = registry.register
    failed_once = False

    def fail_first_gate3_registration(document):
        nonlocal failed_once
        if document["gate_kind"] == "gate3" and not failed_once:
            failed_once = True
            raise paper_research_cli._RegistryError(
                "paper_research_platform_outcome_unknown",
                retryable=False,
                outcome_unknown=True,
            )
        return register(document)

    registry.register = fail_first_gate3_registration
    code, unknown = _call(
        monkeypatch,
        capsys,
        operation="open-gate3",
        request=gate3_request,
        authority=authority,
        registry=registry,
        payload_store=payload_store,
    )
    failed_snapshot = authority.snapshot(task_ref)
    assert code == 1, (
        unknown,
        failed_snapshot.version,
        failed_snapshot.state,
        [
            (
                item.attempt_number,
                item.run_ref,
                item.provider_evidence_refs,
                item.result_refs,
                item.domain_gate_ref,
            )
            for item in failed_snapshot.attempts
        ],
    )
    assert unknown["error"]["code"] == ("paper_research_platform_outcome_unknown")
    assert authority.snapshot(task_ref).state == "awaiting_domain_gate"

    registry.register = register
    code, gate3_opened = _call(
        monkeypatch,
        capsys,
        operation="open-gate3",
        request={
            **gate3_request,
            "command_id": "10000000-0000-4000-8000-000000000014",
            "hermes_run_id": "hermes-gate3-retry-invocation-run",
        },
        authority=authority,
        registry=registry,
        payload_store=payload_store,
    )
    assert code == 0
    gate3_id = gate3_opened["gate_id"]
    domain_gate_ref = gate3_opened["hqa_gate_ref"]
    assert gate3_id.startswith("paper-gate3-")
    assert gate3_opened["operation_id"].startswith("paper-open-gate3-op-")
    assert domain_gate_ref == f"{workflow_gate_ref}-g3"
    assert gate3_opened["hqa_gate_lineage_ref"] == workflow_gate_ref
    final_attempt_ref = gate3_opened["gate"]["attempt_ref"]
    assert final_attempt_ref != plan_attempt_ref
    assert {
        field: gate3_opened["gate"][field]
        for field in (
            "research_claim_digest",
            "research_start_payload_digest",
            "research_continue_payload_digest",
        )
    } == {
        "research_claim_digest": (RESEARCH_CLAIM_DIGEST if claimed else None),
        "research_start_payload_digest": "a" * 64 if claimed else None,
        "research_continue_payload_digest": "b" * 64 if claimed else None,
    }
    assert gate3_opened["gate"]["expected_task_version"] == (
        gate2_receipt.task_version + 6
    )
    code, gate3_replayed = _call(
        monkeypatch,
        capsys,
        operation="open-gate3",
        request={
            **gate3_request,
            "command_id": "10000000-0000-4000-8000-000000000015",
            "hermes_run_id": "hermes-gate3-second-retry-run",
        },
        authority=authority,
        registry=registry,
        payload_store=payload_store,
    )
    assert code == 0, gate3_replayed
    assert gate3_replayed["platform_registration_replayed"] is True
    assert gate3_replayed["operation_id"] == gate3_opened["operation_id"]
    assert gate3_replayed["gate_id"] == gate3_id
    assert gate3_replayed["hqa_gate_ref"] == domain_gate_ref

    gate3_version = gate3_opened["gate"]["expected_task_version"]
    resolved = authority.apply(
        ResolveDomainGate(
            "browser-gate3-resolve",
            task_ref,
            gate3_version,
            final_attempt_ref,
            domain_gate_ref,
            "passed",
        )
    )
    observed = authority.apply(
        ObserveGate3(
            "browser-gate3-observe",
            task_ref,
            resolved.task_version,
            final_attempt_ref,
            "run:paper-final",
            domain_gate_ref,
            "candidate:paper-factor",
            CANDIDATE_DIGEST,
            f"result:{FINAL_RECEIPT}",
            BASE_COMMIT,
        )
    )
    registry.gates[gate3_id].update(
        status="prepared",
        promotion_id=PROMOTION_ID,
        worktree="/tmp/paper-promotion",
        patch="/tmp/paper-promotion.patch",
        manifest="/tmp/paper-promotion.json",
        human_git_commit_required=True,
        auto_commit=False,
        reviewed_commit=None,
    )

    def promotion_status(promotion_id: str):
        assert promotion_id == PROMOTION_ID
        return (
            0,
            json.dumps(
                {
                    "promotion_id": PROMOTION_ID,
                    "status": "reviewed",
                    "reviewed_commit": REVIEWED_COMMIT,
                    "reason": "reviewed",
                    "manifest_sha256": "c" * 64,
                    "patch_sha256": "d" * 64,
                    "candidate_id": "paper-factor",
                    "candidate_digest": CANDIDATE_DIGEST,
                    "final_backtest_receipt_id": FINAL_RECEIPT,
                    "base_commit": BASE_COMMIT,
                    "scoped_paths": [
                        "src/quant_system/factors/library/promoted/paper_factor.py",
                        "src/quant_system/factors/library/promoted/__init__.py",
                        "tests/factors/test_paper_factor.py",
                    ],
                },
                sort_keys=True,
            ),
        )

    completion_request = {
        "gate_id": gate3_id,
        "workspace_id": WORKSPACE_ID,
        "task_ref": task_ref,
        "expected_task_version": observed.task_version,
        "attempt_ref": final_attempt_ref,
        "reviewed_commit": REVIEWED_COMMIT,
        **({"research_claim_digest": RESEARCH_CLAIM_DIGEST} if claimed else {}),
    }
    before_lineage_rejections = authority.snapshot(task_ref)
    for field in (
        "research_claim_digest",
        "research_start_payload_digest",
        "research_continue_payload_digest",
    ):
        stored = registry.gates[gate3_id][field]
        registry.gates[gate3_id][field] = "e" * 64
        code, rejected_lineage = _call(
            monkeypatch,
            capsys,
            operation="complete-after-human-commit",
            request=completion_request,
            authority=authority,
            registry=registry,
            promotion_status_reader=promotion_status,
            payload_store=payload_store,
        )
        assert code == 2
        assert rejected_lineage["error"]["code"] == (
            "paper_research_claim_binding_mismatch"
        )
        after_rejection = authority.snapshot(task_ref)
        assert after_rejection.version == before_lineage_rejections.version
        assert after_rejection.state == before_lineage_rejections.state
        assert after_rejection.terminal_outcome is None
        assert not registry.completion_calls
        registry.gates[gate3_id][field] = stored

    complete = registry.complete
    completion_timed_out = False

    def complete_after_apply_then_timeout(document):
        nonlocal completion_timed_out
        result = complete(document)
        if not completion_timed_out:
            completion_timed_out = True
            raise paper_research_cli._RegistryError(
                "paper_research_platform_outcome_unknown",
                retryable=False,
                outcome_unknown=True,
            )
        return result

    registry.complete = complete_after_apply_then_timeout
    code, completion_unknown = _call(
        monkeypatch,
        capsys,
        operation="complete-after-human-commit",
        request=completion_request,
        authority=authority,
        registry=registry,
        promotion_status_reader=promotion_status,
        payload_store=payload_store,
    )
    assert code == 1
    assert completion_unknown["error"]["code"] == (
        "paper_research_platform_outcome_unknown"
    )
    assert completion_unknown["error"]["retryable"] is False
    first_completion_registration = registry.completion_calls[-1]

    # The HQA Task is already terminal, so recovery must replay the same
    # content-addressed receipt instead of inventing a new completion. An
    # unrelated Task may append while the Platform timeout is reconciled; the
    # completed Task's audit identity must remain stable.
    authority.apply(
        StartResearch(
            "unrelated-concurrent-task",
            "workspace:unrelated",
            "session:unrelated",
            "payload:sha256:" + "e" * 64,
            EXPIRES,
        )
    )
    code, completed = _call(
        monkeypatch,
        capsys,
        operation="complete-after-human-commit",
        request=completion_request,
        authority=authority,
        registry=registry,
        promotion_status_reader=promotion_status,
        payload_store=payload_store,
    )
    assert code == 0
    assert completed["operation_id"].startswith("paper-complete-after-human-commit-op-")
    assert completed["workflow_state"] == "terminal"
    assert completed["terminal_outcome"] == "completed"
    completion_evidence = completed["completion_evidence"]
    assert completion_evidence["attempt_ref"] == final_attempt_ref
    assert completion_evidence["attempt_terminal_outcome"] == "completed"
    assert completion_evidence["task_terminal_outcome"] == "completed"
    assert completion_evidence["domain_gate_outcome"] == "passed"
    assert completion_evidence["task_status"] == "completed"
    assert completion_evidence["attempt_status"] == "completed"
    assert completion_evidence["hqa_run_ref"] == "run:paper-final"
    assert completion_evidence["domain_gate_ref"] == domain_gate_ref
    assert completion_evidence["promotion_id"] == PROMOTION_ID
    assert completion_evidence["reviewed_commit"] == REVIEWED_COMMIT
    assert completion_evidence["workflow_audit_status"] == "consistent"
    assert completion_evidence["workflow_audit_ref"].startswith("workflow-audit:")
    assert completion_evidence["workflow_audit_ref"] == (
        "workflow-audit:" + completion_evidence["workflow_audit_digest"]
    )
    assert len(completion_evidence["workflow_audit_digest"]) == 64
    assert completion_evidence["schema_version"] == (
        "agent-v0.2-paper-completion/v2"
        if claimed
        else "agent-v0.2-paper-completion/v1"
    )
    if claimed:
        assert completion_evidence["research_claim_digest"] == (RESEARCH_CLAIM_DIGEST)
        assert completion_evidence["research_start_payload_digest"] == "a" * 64
        assert completion_evidence["research_continue_payload_digest"] == "b" * 64
    else:
        assert not (
            {
                "research_claim_digest",
                "research_start_payload_digest",
                "research_continue_payload_digest",
            }
            & set(completion_evidence)
        )
    public_completion = json.dumps(completed, ensure_ascii=False)
    assert PAPER_TITLE not in public_completion
    assert "PRIVATE planning body" not in public_completion
    assert "PRIVATE final body" not in public_completion
    assert completed["hqa_completion_receipt_ref"].startswith("hqa-paper-completion:")
    assert completed["hqa_completion_receipt_digest"] == (
        paper_research_cli.hashlib.sha256(
            paper_research_cli._canonical_bytes(completion_evidence)
        ).hexdigest()
    )
    assert registry.completion_calls[-1] == {
        "completion_evidence": completion_evidence,
        "gate_id": gate3_id,
        "hqa_completion_receipt_digest": (completed["hqa_completion_receipt_digest"]),
        "hqa_completion_receipt_ref": (completed["hqa_completion_receipt_ref"]),
        "workspace_id": WORKSPACE_ID,
    }
    assert registry.completion_calls[-1] == first_completion_registration
    snapshot = authority.snapshot(task_ref)
    assert len(snapshot.attempts) == 2
    assert snapshot.attempts[0].attempt_ref == plan_attempt_ref
    assert snapshot.attempts[1].attempt_ref == final_attempt_ref
    assert snapshot.attempts[1].domain_gate_outcome == "passed"
    assert snapshot.attempts[1].gate3_bindings[0].final_receipt_ref == (
        f"result:{FINAL_RECEIPT}"
    )

    # Content-addressed completion evidence is stable on an exact replay.
    code, replayed = _call(
        monkeypatch,
        capsys,
        operation="complete-after-human-commit",
        request=completion_request,
        authority=authority,
        registry=registry,
        promotion_status_reader=promotion_status,
        payload_store=payload_store,
    )
    assert code == 0
    assert replayed["replayed"] is True
    assert replayed["operation_id"] == completed["operation_id"]
    assert (
        replayed["hqa_completion_receipt_ref"]
        == (completed["hqa_completion_receipt_ref"])
    )
    assert (
        replayed["hqa_completion_receipt_digest"]
        == (completed["hqa_completion_receipt_digest"])
    )

    private_extra = "PRIVATE-platform-completion-extra"
    registry.completion_mutator = lambda response: {
        **response,
        "unexpected_sensitive_field": private_extra,
    }
    code, extra_field = _call(
        monkeypatch,
        capsys,
        operation="complete-after-human-commit",
        request=completion_request,
        authority=authority,
        registry=registry,
        promotion_status_reader=promotion_status,
        payload_store=payload_store,
    )
    assert code == 2
    assert extra_field["error"]["code"] == (
        "paper_research_platform_completion_mismatch"
    )
    assert private_extra not in json.dumps(extra_field)

    registry.completion_mutator = lambda response: {
        **response,
        "reviewed_commit": "9" * 40,
    }
    code, drifted_commit = _call(
        monkeypatch,
        capsys,
        operation="complete-after-human-commit",
        request=completion_request,
        authority=authority,
        registry=registry,
        promotion_status_reader=promotion_status,
        payload_store=payload_store,
    )
    assert code == 2
    assert drifted_commit["error"]["code"] == (
        "paper_research_platform_completion_mismatch"
    )

    registry.completion_mutator = lambda response: {
        **response,
        "completion_evidence": {
            **response["completion_evidence"],
            "schema_version": "agent-v0.2-paper-completion/drift",
        },
    }
    code, drifted_evidence = _call(
        monkeypatch,
        capsys,
        operation="complete-after-human-commit",
        request=completion_request,
        authority=authority,
        registry=registry,
        promotion_status_reader=promotion_status,
        payload_store=payload_store,
    )
    assert code == 2
    assert drifted_evidence["error"]["code"] == (
        "paper_research_platform_completion_mismatch"
    )


@pytest.mark.parametrize(
    ("case", "expected_code"),
    [
        ("leased_invocation", "paper_research_invocation_attestation_invalid"),
        ("forged_attestation", "paper_research_run_attestation_invalid"),
        ("schema_drift", "paper_research_run_attestation_invalid"),
        ("provider_ref_drift", "paper_research_subject_attestation_invalid"),
        ("same_subject", "paper_research_subject_is_current_invocation"),
        ("plan_mismatch", "paper_research_plan_digest_not_subject_output"),
    ],
)
def test_start_plan_rejects_untrusted_run_evidence_before_workflow_mutation(
    case,
    expected_code,
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    authority = _authority(tmp_path / case)
    registry = _Registry()
    payload_ref = "payload:sha256:" + "a" * 64
    payload_store = _PayloadStore()
    payload_store.add(payload_ref, "research_start")
    request = _start_request(
        payload_ref=payload_ref,
    )
    if case == "leased_invocation":
        registry.attestation_mutator = lambda attestation: {
            **attestation,
            "command_state": (
                "leased"
                if attestation["mode"] == "invocation"
                else attestation["command_state"]
            ),
        }
    elif case == "forged_attestation":
        registry.attestation_post_mutator = lambda attestation: {
            **attestation,
            "evidence_digest": "9" * 64,
        }
    elif case == "schema_drift":
        registry.attestation_mutator = lambda attestation: {
            **attestation,
            "schema_version": 2,
        }
    elif case == "provider_ref_drift":
        registry.attestation_post_mutator = lambda attestation: {
            **attestation,
            "provider_evidence_ref": (
                "provider-evidence:wrong-ref"
                if attestation["mode"] == "subject"
                else attestation["provider_evidence_ref"]
            ),
        }
    elif case == "same_subject":
        request["subject_command_id"] = request["command_id"]
    else:
        request["plan_digest"] = "9" * 64

    code, rejected = _call(
        monkeypatch,
        capsys,
        operation="start-plan",
        request=request,
        authority=authority,
        registry=registry,
        payload_store=payload_store,
    )

    assert code == 2
    assert rejected["error"]["code"] == expected_code
    assert not authority.root.exists()
    assert payload_store.bind_calls == []


@pytest.mark.parametrize(
    "case",
    ("wrong_kind", "wrong_workspace", "wrong_policy", "expired", "tombstoned"),
)
def test_start_plan_rejects_non_authoritative_payload_before_workflow_mutation(
    case,
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    authority = _authority(tmp_path / case)
    registry = _Registry()
    payload_ref = "payload:sha256:" + "a" * 64
    payload_store = _PayloadStore()
    payload_store.add(payload_ref, "research_start")
    record = payload_store.records[payload_ref]
    if case == "wrong_kind":
        record["kind"] = "research_continue"
    elif case == "wrong_workspace":
        record["workspace_id"] = "workspace:other"
    elif case == "wrong_policy":
        record["provider_policy_digest"] = "f" * 64
    elif case == "expired":
        expired = datetime.now(timezone.utc) - timedelta(days=1)
        record["expires_at"] = expired.isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        )
        record["created_at"] = (
            (expired - timedelta(days=10))
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
    else:
        record["status"] = "tombstoned"

    code, rejected = _call(
        monkeypatch,
        capsys,
        operation="start-plan",
        request=_start_request(
            payload_ref=payload_ref,
        ),
        authority=authority,
        registry=registry,
        payload_store=payload_store,
    )

    assert code == 2
    assert rejected["error"]["code"] == "paper_research_payload_not_active"
    assert not authority.root.exists()
    assert payload_store.bind_calls == []


def test_start_plan_rejects_payload_bound_to_another_attempt_without_mutation(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    authority = _authority(tmp_path)
    authority.apply(
        StartResearch(
            "unrelated-start",
            "workspace:unrelated",
            "session:unrelated",
            "payload:sha256:" + "d" * 64,
            EXPIRES,
        )
    )
    before = authority.reverse_audit()
    payload_ref = "payload:sha256:" + "a" * 64
    payload_store = _PayloadStore()
    payload_store.add(payload_ref, "research_start")
    payload_store.records[payload_ref]["consumer_ref"] = "attempt:" + "f" * 64

    code, rejected = _call(
        monkeypatch,
        capsys,
        operation="start-plan",
        request=_start_request(
            payload_ref=payload_ref,
        ),
        authority=authority,
        registry=_Registry(),
        payload_store=payload_store,
    )

    assert code == 2
    assert rejected["error"]["code"] == "paper_research_payload_already_consumed"
    assert authority.reverse_audit() == before
    assert payload_store.bind_calls == []


def test_start_plan_converges_after_payload_bind_ack_loss(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    class _FailBindOnce(_PayloadStore):
        def __init__(self) -> None:
            super().__init__()
            self.fail_once = True

        def bind_consumer(self, **kwargs):
            if self.fail_once:
                self.fail_once = False
                raise paper_research_cli.IntentPayloadError(
                    "intent_storage_unavailable",
                    "simulated bind acknowledgement loss",
                    retryable=True,
                )
            return super().bind_consumer(**kwargs)

    authority = _authority(tmp_path)
    registry = _Registry()
    payload_ref = "payload:sha256:" + "a" * 64
    payload_store = _FailBindOnce()
    payload_store.add(payload_ref, "research_start")
    request = _start_request(
        payload_ref=payload_ref,
    )

    code, unknown = _call(
        monkeypatch,
        capsys,
        operation="start-plan",
        request=request,
        authority=authority,
        registry=registry,
        payload_store=payload_store,
    )
    after_failure = authority.reverse_audit()
    assert code == 1
    assert unknown["error"]["code"] == "paper_research_payload_binding_unknown"
    assert after_failure["task_count"] == 1
    assert after_failure["event_count"] == 1

    code, recovered = _call(
        monkeypatch,
        capsys,
        operation="start-plan",
        request=request,
        authority=authority,
        registry=registry,
        payload_store=payload_store,
    )

    assert code == 0
    assert recovered["workflow_state"] == "awaiting_plan_confirmation"
    snapshot = authority.snapshot(recovered["task_ref"])
    assert len(snapshot.attempts) == 1
    assert (
        payload_store.records[payload_ref]["consumer_ref"]
        == snapshot.attempts[0].attempt_ref
    )
    assert len(payload_store.bind_calls) == 1
    audit = authority.reverse_audit()
    assert audit["task_count"] == 1
    assert audit["event_count"] == 7


def test_attestation_digest_ignores_runtime_diagnostics_but_not_evidence() -> None:
    request = {
        "mode": "subject",
        "workspace_id": WORKSPACE_ID,
        "platform_session_id": PLATFORM_SESSION_ID,
        "hermes_session_id": HERMES_SESSION_ID,
        "command_id": PLAN_SUBJECT_COMMAND_ID,
        "hermes_run_id": PLAN_SUBJECT_RUN_ID,
    }
    first_registry = _Registry()
    second_registry = _Registry()
    second_registry.attestation_mutator = lambda attestation: {
        **attestation,
        "hermes_runtime_instance_id": "runtime-restarted",
        "hermes_runtime_started_at": "2026-07-24T01:00:00Z",
    }

    first = paper_research_cli._attest_run(first_registry, **request)
    second = paper_research_cli._attest_run(second_registry, **request)

    assert first["evidence_digest"] == second["evidence_digest"]
    assert first["attestation_ref"] == second["attestation_ref"]
    assert first["provider_evidence_ref"] == second["provider_evidence_ref"]
    assert first["hermes_runtime_instance_id"] != second["hermes_runtime_instance_id"]


@pytest.mark.parametrize("case", ("tiingo", "bad_artifact_digest"))
def test_open_gate3_rejects_noncanonical_final_receipt_before_workflow_mutation(
    case,
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    authority = _authority(tmp_path)
    payload_ref = "payload:sha256:" + "b" * 64
    payload_store = _PayloadStore()
    payload_store.add(payload_ref, "research_continue")
    evidence = _final_backtest_evidence(
        FINAL_RECEIPT,
        "paper-factor",
        CANDIDATE_DIGEST,
    )
    if case == "tiingo":
        evidence["final_backtest_provider"] = "tiingo"
    else:
        evidence["final_backtest_report_digest"] = "not-a-digest"
    request = {
        "parent_gate_id": "paper-gate2",
        "workspace_id": WORKSPACE_ID,
        "platform_session_id": PLATFORM_SESSION_ID,
        "task_ref": "task:not-created",
        "expected_task_version": 1,
        "payload_ref": payload_ref,
        "command_id": GATE3_COMMAND_ID,
        "hermes_run_id": "hermes-gate3-invocation-run",
        "subject_command_id": FINAL_SUBJECT_COMMAND_ID,
        "subject_hermes_run_id": FINAL_SUBJECT_RUN_ID,
        "result_ref": f"result:{FINAL_RECEIPT}",
        "reviewed_source_sha256": SOURCE_DIGEST,
        "gate1_confirmation_id": CONFIRMATION_ID,
        "candidate_id": "paper-factor",
        "expected_digest": CANDIDATE_DIGEST,
        "final_backtest_receipt_id": FINAL_RECEIPT,
        "base_commit": BASE_COMMIT,
    }

    code, rejected = _call(
        monkeypatch,
        capsys,
        operation="open-gate3",
        request=request,
        authority=authority,
        registry=_Registry(),
        final_backtest_reader=lambda *_args: evidence,
        payload_store=payload_store,
    )

    assert code == 2
    assert rejected["error"]["code"] == "paper_research_final_receipt_invalid"
    assert not authority.root.exists()
    assert payload_store.bind_calls == []


def test_gate3_requires_research_continue_payload_without_mutating_workflow(
    tmp_path,
) -> None:
    authority = _authority(tmp_path)
    started = authority.apply(
        StartResearch(
            "existing-start",
            f"workspace:{WORKSPACE_ID}",
            f"session:{PLATFORM_SESSION_ID}",
            "payload:sha256:" + "a" * 64,
            EXPIRES,
        )
    )
    before = authority.reverse_audit()
    payload_ref = "payload:sha256:" + "b" * 64
    payload_store = _PayloadStore()
    payload_store.add(payload_ref, "research_start")

    with pytest.raises(
        paper_research_cli._OperationError,
        match="paper_research_payload_not_active",
    ):
        paper_research_cli._active_payload(
            payload_store,
            authority,
            payload_ref=payload_ref,
            workspace_id=WORKSPACE_ID,
            platform_session_id=PLATFORM_SESSION_ID,
            hermes_session_id=HERMES_SESSION_ID,
            expected_kind="research_continue",
        )

    assert started.task_ref.startswith("task:")
    assert authority.reverse_audit() == before
    assert payload_store.bind_calls == []


def test_strict_request_rejects_unknown_field(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    authority = _authority(tmp_path)
    registry = _Registry()
    code, document = _call(
        monkeypatch,
        capsys,
        operation="confirm-plan",
        request={
            "task_ref": "task:missing",
            "expected_task_version": 1,
            "plan_version": 1,
            "plan_digest": PLAN_DIGEST,
            "confirmation_note": "reviewed",
            "unexpected": True,
        },
        authority=authority,
        registry=registry,
    )
    assert code == 2
    assert document["error"]["code"] == "paper_research_invalid_request"


@pytest.mark.parametrize(
    ("operation", "field", "value"),
    [
        ("prepare-intent", "operation_id", "caller-operation"),
        ("start-plan", "operation_id", "caller-operation"),
        ("confirm-plan", "operation_id", "caller-operation"),
        ("open-gate1", "operation_id", "caller-operation"),
        ("open-gate2", "operation_id", "caller-operation"),
        ("open-gate3", "operation_id", "caller-operation"),
        ("complete-after-human-commit", "operation_id", "caller-operation"),
        ("open-gate1", "gate_id", "caller-gate"),
        ("open-gate2", "gate_id", "caller-gate"),
        ("open-gate3", "gate_id", "caller-gate"),
        ("open-gate1", "hqa_gate_ref", "gate:caller"),
        ("open-gate2", "hqa_gate_ref", "gate:caller"),
        ("open-gate3", "hqa_gate_ref", "gate:caller"),
    ],
)
def test_mutation_schemas_reject_caller_supplied_control_ids_before_side_effects(
    operation,
    field,
    value,
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    authority = _authority(tmp_path / f"{operation}-{field}")
    registry = _Registry()
    payload_store = _PayloadStore()

    code, document = _call(
        monkeypatch,
        capsys,
        operation=operation,
        request={field: value},
        authority=authority,
        registry=registry,
        payload_store=payload_store,
    )

    assert code == 2
    assert document["error"]["code"] == "paper_research_invalid_request"
    assert not authority.root.exists()
    assert registry.attest_calls == []
    assert registry.register_calls == []
    assert registry.completion_calls == []
    assert payload_store.put_calls == []


@pytest.mark.parametrize(
    "attack",
    [
        "arbitrary_path",
        "missing",
        "leaf_symlink",
        "parent_symlink",
        "hardlink",
        "wrong_mode",
        "wrong_owner",
        "digest_drift",
        "non_utf8",
        "non_python",
        "oversized",
    ],
)
def test_open_gate1_rejects_untrusted_source_before_platform_or_workflow_access(
    attack,
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    authority = _authority(tmp_path / "authority")
    registry = _Registry()
    gate1_root = tmp_path / "factor-gate1"
    sources = gate1_root / "sources"
    digest = SOURCE_DIGEST
    payload = SOURCE_BYTES
    source_file_ref: Path

    if attack == "non_utf8":
        payload = b"\xff\xfe"
        digest = hashlib.sha256(payload).hexdigest()
    elif attack == "non_python":
        payload = b"def broken(:\n"
        digest = hashlib.sha256(payload).hexdigest()
    elif attack == "oversized":
        payload = b"x" * (paper_research_cli._MAX_GATE1_SOURCE_BYTES + 1)
        digest = hashlib.sha256(payload).hexdigest()
    elif attack == "digest_drift":
        payload = b"VALUE = 2\n"

    expected = sources / f"source-{digest}.py"
    if attack == "parent_symlink":
        real_sources = tmp_path / "real-sources"
        real_sources.mkdir()
        source_file_ref = expected
        (real_sources / expected.name).write_bytes(payload)
        (real_sources / expected.name).chmod(0o600)
        gate1_root.mkdir()
        sources.symlink_to(real_sources, target_is_directory=True)
    else:
        sources.mkdir(parents=True)
        source_file_ref = expected
        if attack == "missing":
            pass
        elif attack == "leaf_symlink":
            target = tmp_path / "outside.py"
            target.write_bytes(payload)
            target.chmod(0o600)
            expected.symlink_to(target)
        elif attack == "hardlink":
            target = tmp_path / "outside.py"
            target.write_bytes(payload)
            target.chmod(0o600)
            os.link(target, expected)
        else:
            expected.write_bytes(payload)
            expected.chmod(0o644 if attack == "wrong_mode" else 0o600)
            if attack == "arbitrary_path":
                arbitrary = tmp_path / "caller-picked.py"
                arbitrary.write_bytes(payload)
                arbitrary.chmod(0o600)
                source_file_ref = arbitrary

    monkeypatch.setattr(paper_research_cli.config, "FACTOR_GATE1_DIR", gate1_root)
    if attack == "wrong_owner":
        current_uid = os.geteuid()
        monkeypatch.setattr(
            paper_research_cli.os,
            "geteuid",
            lambda: current_uid + 1,
        )

    code, document = _call(
        monkeypatch,
        capsys,
        operation="open-gate1",
        request={
            "workspace_id": WORKSPACE_ID,
            "platform_session_id": PLATFORM_SESSION_ID,
            "task_ref": "task:not-created",
            "expected_task_version": 1,
            "attempt_ref": "attempt:not-created",
            "command_id": GATE1_COMMAND_ID,
            "hermes_run_id": "hermes-gate1-source-attack",
            "source_file_ref": str(source_file_ref),
            "reviewed_source_sha256": digest,
            "universe": "US ETFs",
        },
        authority=authority,
        registry=registry,
        payload_store=_PayloadStore(),
    )

    assert code == 2
    assert document["error"]["code"] == "paper_research_invalid_request"
    assert registry.attest_calls == []
    assert registry.register_calls == []
    assert not authority.root.exists()


@pytest.mark.parametrize(
    "raw",
    [
        b'{"operation_id":"one","operation_id":"two"}',
        b'{"operation_id":NaN}',
    ],
)
def test_strict_request_rejects_duplicate_keys_and_nonfinite_numbers(
    raw,
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    authority = _authority(tmp_path)
    monkeypatch.setattr(
        paper_research_cli,
        "_payload_store",
        lambda: pytest.fail("invalid JSON must be rejected before crypto setup"),
    )
    monkeypatch.setattr(
        "sys.stdin",
        io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8"),
    )
    assert (
        paper_research_cli.main(
            ["start-plan"],
            authority_factory=lambda: authority,
            registry=_Registry(),
        )
        == 2
    )
    assert (
        json.loads(capsys.readouterr().out)["error"]["code"]
        == "paper_research_invalid_request"
    )
    assert not authority.root.exists()


@pytest.mark.parametrize(
    ("failure_code", "expected_status", "retryable"),
    (
        ("crypto_helper_timeout", 1, True),
        ("crypto_helper_insecure", 2, False),
    ),
)
def test_crypto_setup_failure_is_controlled_and_classified(
    failure_code,
    expected_status,
    retryable,
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    authority = _authority(tmp_path)
    monkeypatch.setattr(
        "sys.stdin",
        io.TextIOWrapper(io.BytesIO(b"{}"), encoding="utf-8"),
    )

    def unavailable_store():
        raise paper_research_cli.CryptoFailure(failure_code, "private detail")

    monkeypatch.setattr(paper_research_cli, "_payload_store", unavailable_store)

    assert (
        paper_research_cli.main(
            ["start-plan"],
            authority_factory=lambda: authority,
            registry=_Registry(),
        )
        == expected_status
    )
    error = json.loads(capsys.readouterr().out)["error"]
    assert error == {
        "code": failure_code,
        "message": "paper research operation did not advance exactly",
        "retryable": retryable,
    }
    assert not authority.root.exists()


def test_runtime_selector_substitution_and_missing_env_fail_closed(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    authority = _authority(tmp_path)
    registry = _Registry()
    request = {
        "workspace_id": WORKSPACE_ID,
        "platform_session_id": "substituted-platform-session",
        "payload_ref": "payload:sha256:" + "a" * 64,
        "intent_expires_at": EXPIRES,
        "command_id": PLAN_COMMAND_ID,
        "hermes_run_id": "hermes-plan-run",
        "hqa_run_ref": "run:paper-plan",
        "provider_evidence_ref": "provider-evidence:paper-plan",
        "plan_version": 1,
        "plan_digest": PLAN_DIGEST,
    }
    monkeypatch.setenv("HERMES_PLATFORM_COMMAND_ID", PLAN_COMMAND_ID)
    monkeypatch.setenv("HERMES_PLATFORM_SESSION_ID", PLATFORM_SESSION_ID)
    monkeypatch.setenv("HERMES_PLATFORM_RUN_ID", "hermes-plan-run")
    monkeypatch.setenv(
        "HERMES_PLATFORM_MANAGED_SESSION_ID",
        HERMES_SESSION_ID,
    )
    monkeypatch.setattr(
        "sys.stdin",
        io.TextIOWrapper(
            io.BytesIO(json.dumps(request).encode("utf-8")),
            encoding="utf-8",
        ),
    )
    assert (
        paper_research_cli.main(
            ["start-plan"],
            authority_factory=lambda: authority,
            registry=registry,
            payload_store=_PayloadStore(),
        )
        == 2
    )
    assert (
        json.loads(capsys.readouterr().out)["error"]["code"]
        == "paper_research_invalid_request"
    )
    assert not authority.root.exists()

    request["platform_session_id"] = PLATFORM_SESSION_ID
    monkeypatch.delenv("HERMES_PLATFORM_MANAGED_SESSION_ID")
    monkeypatch.setattr(
        "sys.stdin",
        io.TextIOWrapper(
            io.BytesIO(json.dumps(request).encode("utf-8")),
            encoding="utf-8",
        ),
    )
    assert (
        paper_research_cli.main(
            ["start-plan"],
            authority_factory=lambda: authority,
            registry=registry,
            payload_store=_PayloadStore(),
        )
        == 2
    )
    assert (
        json.loads(capsys.readouterr().out)["error"]["code"]
        == "paper_research_invalid_request"
    )
    assert not authority.root.exists()


def test_registration_timeout_is_unknown_and_never_reported_retryable(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    authority = _authority(tmp_path)
    registry = _Registry()
    payload = "payload:sha256:" + "a" * 64
    payload_store = _PayloadStore()
    payload_store.add(payload, "research_start")
    code, started = _call(
        monkeypatch,
        capsys,
        operation="start-plan",
        request={
            "workspace_id": WORKSPACE_ID,
            "platform_session_id": PLATFORM_SESSION_ID,
            "payload_ref": payload,
            "command_id": PLAN_COMMAND_ID,
            "hermes_run_id": "hermes-timeout-start-invocation",
            "subject_command_id": PLAN_SUBJECT_COMMAND_ID,
            "subject_hermes_run_id": PLAN_SUBJECT_RUN_ID,
            "plan_version": 1,
            "plan_digest": PLAN_DIGEST,
        },
        authority=authority,
        registry=registry,
        payload_store=payload_store,
    )
    assert code == 0
    code, confirmed = _call(
        monkeypatch,
        capsys,
        operation="confirm-plan",
        request={
            "task_ref": started["task_ref"],
            "expected_task_version": started["task_version"],
            "plan_version": 1,
            "plan_digest": PLAN_DIGEST,
            "confirmation_note": "reviewed exact plan",
        },
        authority=authority,
        registry=registry,
        payload_store=payload_store,
    )
    assert code == 0

    source_file = _stage_gate1_source(tmp_path, monkeypatch)

    class _TimeoutRegistry(_Registry):
        def register(self, document):
            raise paper_research_cli._RegistryError(
                "paper_research_platform_outcome_unknown",
                retryable=False,
                outcome_unknown=True,
            )

    code, failed = _call(
        monkeypatch,
        capsys,
        operation="open-gate1",
        request={
            "workspace_id": WORKSPACE_ID,
            "platform_session_id": PLATFORM_SESSION_ID,
            "task_ref": started["task_ref"],
            "expected_task_version": confirmed["task_version"],
            "attempt_ref": started["attempt_ref"],
            "command_id": GATE1_COMMAND_ID,
            "hermes_run_id": "hermes-gate1-run",
            "source_file_ref": str(source_file),
            "universe": "US ETFs",
            "reviewed_source_sha256": SOURCE_DIGEST,
        },
        authority=authority,
        registry=_TimeoutRegistry(),
        payload_store=payload_store,
    )
    assert code == 1
    assert failed["error"] == {
        "code": "paper_research_platform_outcome_unknown",
        "message": "paper research operation did not advance exactly",
        "retryable": False,
    }


def test_completion_refuses_unreviewed_or_different_commit(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    # Unit-level guard for the exact status seam: a syntactically valid status
    # must still be the reviewed commit supplied by the human.
    status = {
        "promotion_id": PROMOTION_ID,
        "status": "awaiting_human_commit",
        "reviewed_commit": None,
        "reason": "uncommitted: worktree HEAD still equals base",
        "manifest_sha256": "a" * 64,
        "patch_sha256": "b" * 64,
        "candidate_id": "paper-factor",
        "candidate_digest": CANDIDATE_DIGEST,
        "final_backtest_receipt_id": FINAL_RECEIPT,
        "base_commit": BASE_COMMIT,
        "scoped_paths": ["one"],
    }
    observed = paper_research_cli._promotion_status(
        PROMOTION_ID,
        reader=lambda _promotion_id: (0, json.dumps(status)),
    )
    assert observed["reviewed_commit"] is None

    invalid = dict(status)
    invalid.pop("reason")
    with pytest.raises(
        paper_research_cli._OperationError,
        match="paper_research_promotion_status_invalid",
    ):
        paper_research_cli._promotion_status(
            PROMOTION_ID,
            reader=lambda _promotion_id: (0, json.dumps(invalid)),
        )


def test_subprocess_registry_uses_fixed_cli_and_strict_json_stdin(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sentinel-must-not-cross")
    monkeypatch.setenv("FUTU_API_SECRET", "sentinel-must-not-cross")
    monkeypatch.setenv("DATABASE_URL", "sentinel-must-not-cross")
    monkeypatch.setenv(
        "HERMES_PLATFORM_COMMAND_ID",
        "sentinel-must-not-cross",
    )
    monkeypatch.setenv(
        "QS_DATABASE_URL",
        "postgresql://paper-registry@127.0.0.1/quantplatform",
    )
    monkeypatch.setenv("QS_DATABASE_ENABLED", "true")
    monkeypatch.setenv("QS_DATABASE_AUTO_MIGRATE", "true")
    executable = tmp_path / "fake-quant-system"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "assert sys.argv[1:] == ['hermes', 'paper-gate', 'register']\n"
        "for key in ('OPENAI_API_KEY', 'FUTU_API_SECRET', 'DATABASE_URL', "
        "'HERMES_PLATFORM_COMMAND_ID'):\n"
        "    assert key not in os.environ\n"
        "assert os.environ['QS_DATABASE_ENABLED'] == 'true'\n"
        "assert os.environ['QS_DATABASE_URL'] == "
        "'postgresql://paper-registry@127.0.0.1/quantplatform'\n"
        "assert os.environ['QS_DATABASE_AUTO_MIGRATE'] == 'false'\n"
        "request = json.load(sys.stdin)\n"
        "assert request['command_id'] == "
        f"{GATE1_COMMAND_ID!r}\n"
        "response = {\n"
        "  'contract': 'agent-v0.2-paper-gate-cli/v1',\n"
        "  'operation': 'register',\n"
        "  'ok': True,\n"
        "  'gate': {**request, 'status': 'pending'},\n"
        "}\n"
        "print(json.dumps(response, sort_keys=True, separators=(',', ':')))\n",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    registry = paper_research_cli.SubprocessPaperGateRegistry(
        executable=executable,
        cwd=tmp_path,
        timeout_seconds=2,
    )
    registration = paper_research_cli._registration(
        gate_id="paper-gate-subprocess",
        gate_kind="gate1",
        workspace_id=WORKSPACE_ID,
        task_ref="task:paper-subprocess",
        expected_task_version=7,
        platform_session_id=PLATFORM_SESSION_ID,
        attempt_ref="attempt:paper-subprocess-1",
        hqa_gate_ref="gate:paper-subprocess",
        command_id=GATE1_COMMAND_ID,
        hermes_run_id="hermes-run-subprocess",
        hermes_session_id=HERMES_SESSION_ID,
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
        research_claim_digest=None,
        research_start_payload_digest=None,
        research_continue_payload_digest=None,
        parent_gate_id=None,
        source_file_ref="/tmp/paper.py",
        universe="US ETFs",
        reviewed_source_sha256=SOURCE_DIGEST,
        gate1_confirmation_id=None,
        candidate_id=None,
        expected_digest=None,
        expected_status=None,
        final_backtest_receipt_id=None,
        base_commit=None,
    )
    assert registry.register(registration) == {
        **registration,
        "status": "pending",
    }


def test_subprocess_registry_defaults_to_installed_runtime_port(
    tmp_path,
    monkeypatch,
) -> None:
    runtime_port = tmp_path / "hqa-paper-gate-show.py"
    monkeypatch.setattr(
        paper_research_cli.config,
        "PAPER_GATE_PORT_BIN",
        runtime_port,
    )

    registry = paper_research_cli.SubprocessPaperGateRegistry()

    assert registry._executable == runtime_port  # noqa: SLF001


def test_subprocess_registry_matches_platform_attest_and_show_contract(
    tmp_path,
) -> None:
    executable = tmp_path / "fake-quant-system"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import hashlib, json, sys\n"
        "operation = sys.argv[3]\n"
        "assert sys.argv[1:3] == ['hermes', 'paper-gate']\n"
        "request = json.load(sys.stdin)\n"
        "if operation == 'attest-run':\n"
        "    evidence = {\n"
        "      'schema_version': 1,\n"
        "      'mode': request['mode'],\n"
        "      'workspace_id': request['workspace_id'],\n"
        "      'platform_session_id': request['platform_session_id'],\n"
        "      'hermes_session_id': request['hermes_session_id'],\n"
        "      'resolved_hermes_session_id': request['hermes_session_id'],\n"
        "      'command_id': request['command_id'],\n"
        "      'hermes_run_id': request['hermes_run_id'],\n"
        "      'command_state': 'delivered',\n"
        "      'hqa_run_ref': None,\n"
        "      'actual_model': None,\n"
        "      'actual_provider': None,\n"
        "      'output_digest': None,\n"
        "      'hermes_runtime_instance_id': None,\n"
        "      'hermes_runtime_started_at': None,\n"
        "      'terminal_event_ref': None,\n"
        "    }\n"
        "    digest_input = {k: v for k, v in evidence.items() if k not in {\n"
        "      'hermes_runtime_instance_id', 'hermes_runtime_started_at'}}\n"
        "    raw = json.dumps(digest_input, sort_keys=True, separators=(',', ':'))"
        ".encode()\n"
        "    digest = hashlib.sha256(raw).hexdigest()\n"
        "    attestation = {**evidence, 'evidence_digest': digest,\n"
        "      'attestation_ref': 'paper-run-attestation:' + digest,\n"
        "      'provider_evidence_ref': None}\n"
        "    payload = {'contract': 'agent-v0.2-paper-gate-cli/v1',\n"
        "      'operation': operation, 'ok': True, 'attestation': attestation}\n"
        "elif operation == 'show':\n"
        "    assert set(request) == {\n"
        "      'gate_id', 'platform_session_id', 'workspace_id'}\n"
        "    payload = {'contract': 'agent-v0.2-paper-gate-cli/v1',\n"
        "      'operation': operation, 'ok': True,\n"
        "      'gate': {**request, 'status': 'pending'}}\n"
        "else:\n"
        "    raise AssertionError(operation)\n"
        "print(json.dumps(payload, sort_keys=True, separators=(',', ':')))\n",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    registry = paper_research_cli.SubprocessPaperGateRegistry(
        executable=executable,
        cwd=tmp_path,
        timeout_seconds=2,
    )

    attestation = paper_research_cli._attest_run(
        registry,
        mode="invocation",
        workspace_id=WORKSPACE_ID,
        platform_session_id=PLATFORM_SESSION_ID,
        hermes_session_id=HERMES_SESSION_ID,
        command_id=GATE1_COMMAND_ID,
        hermes_run_id="hermes-run-invocation",
    )
    assert attestation["command_state"] == "delivered"

    shown = registry.show(
        "paper-gate-one",
        workspace_id=WORKSPACE_ID,
        platform_session_id=PLATFORM_SESSION_ID,
    )
    assert shown == {
        "gate_id": "paper-gate-one",
        "platform_session_id": PLATFORM_SESSION_ID,
        "status": "pending",
        "workspace_id": WORKSPACE_ID,
    }


def test_subprocess_registry_preserves_readonly_retryability(
    tmp_path,
) -> None:
    executable = tmp_path / "fake-quant-system"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "operation = sys.argv[3]\n"
        "request = json.load(sys.stdin)\n"
        "if operation == 'attest-run':\n"
        "    code = 'paper_run_attestation_unavailable'\n"
        "    exit_code = 1\n"
        "else:\n"
        "    assert operation == 'show' and set(request) == {\n"
        "      'gate_id', 'platform_session_id', 'workspace_id'}\n"
        "    code = 'paper_gate_context_mismatch'\n"
        "    exit_code = 2\n"
        "print(json.dumps({'contract': 'agent-v0.2-paper-gate-cli/v1',\n"
        "  'operation': operation, 'ok': False, 'error_code': code,\n"
        "  'message': 'bounded failure'}, sort_keys=True, separators=(',', ':')))\n"
        "raise SystemExit(exit_code)\n",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    registry = paper_research_cli.SubprocessPaperGateRegistry(
        executable=executable,
        cwd=tmp_path,
        timeout_seconds=2,
    )

    with pytest.raises(paper_research_cli._RegistryError) as unavailable:
        registry.attest(
            {
                "command_id": GATE1_COMMAND_ID,
                "hermes_run_id": "run-one",
                "hermes_session_id": HERMES_SESSION_ID,
                "mode": "invocation",
                "platform_session_id": PLATFORM_SESSION_ID,
                "workspace_id": WORKSPACE_ID,
            }
        )
    assert unavailable.value.code == "paper_run_attestation_unavailable"
    assert unavailable.value.retryable is True

    with pytest.raises(paper_research_cli._RegistryError) as mismatch:
        registry.show(
            "gate-one",
            workspace_id=WORKSPACE_ID,
            platform_session_id=PLATFORM_SESSION_ID,
        )
    assert mismatch.value.code == "paper_gate_context_mismatch"
    assert mismatch.value.retryable is False


def test_hermes_skill_requires_derived_controls_and_fixed_source_stager() -> None:
    skill = (Path(__file__).parents[1] / "skills/hermes/hqa-quant/SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "version: 1.18.3" in skill
    assert "Hermes must omit `operation_id`, every new `gate_id`, every" in skill
    assert "Supplying `operation_id`, a new `gate_id`, or `hqa_gate_ref` is a" in skill
    assert "legacy API compatibility surface" not in skill
    assert "`start-plan` `plan_digest`" in skill
    assert "hqa-paper-source-stage.py` with no arguments" in skill
    assert "{source_file_ref,reviewed_source_sha256}" in skill
    assert "__HQA_REPO_DIR__/data/_runtime/factor-gate1/sources" in skill
    assert "never write source\n   to a tracked repository path, `/tmp`" in skill

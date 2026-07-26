from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from hqa import paper_research_cli
from hqa.intent_payload_crypto import DeterministicCryptoFake
from hqa.intent_payloads import IntentPayloadStore
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
EXPIRES = (_CREATED_AT + timedelta(days=10)).isoformat(
    timespec="microseconds"
).replace("+00:00", "Z")
PLAN_DIGEST = "1" * 64
SOURCE_DIGEST = "2" * 64
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
        self.bind_calls: list[tuple[str, str]] = []
        self.put_calls: list[dict] = []

    def add(self, payload_ref: str, kind: str) -> None:
        self.records[payload_ref] = {
            "schema_version": "2.0",
            "payload_ref": payload_ref,
            "payload_digest": payload_ref.removeprefix("payload:sha256:"),
            "kind": kind,
            "owner_id": "owner-test",
            "workspace_id": f"workspace:{WORKSPACE_ID}",
            "session_id": f"session:{PLATFORM_SESSION_ID}",
            "client_intent_id": f"intent-{len(self.records) + 1}",
            "provider_policy_digest": (
                paper_research_cli._managed_session_policy_digest(
                    platform_session_id=PLATFORM_SESSION_ID,
                    hermes_session_id=HERMES_SESSION_ID,
                )
            ),
            "created_at": CREATED_AT,
            "expires_at": EXPIRES,
            "ttl_days": 10,
            "status": "active",
            "consumer_ref": None,
        }

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
            datetime.fromisoformat(created_at.removesuffix("Z") + "+00:00")
            + timedelta(days=request["ttl_days"])
        ).isoformat(timespec="microseconds").replace("+00:00", "Z")
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


class _Registry:
    def __init__(self) -> None:
        self.gates: dict[str, dict] = {}
        self.register_calls: list[dict] = []
        self.completion_calls: list[dict] = []
        self.attest_calls: list[dict] = []
        self.attestation_mutator = None
        self.attestation_post_mutator = None

    def attest(self, document):
        request = dict(document)
        self.attest_calls.append(request)
        if request["mode"] == "invocation":
            attestation = {
                **request,
                "schema_version": "agent-v0.2-paper-run-attestation/v1",
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
                "schema_version": "agent-v0.2-paper-run-attestation/v1",
                "resolved_hermes_session_id": request["hermes_session_id"],
                "command_state": "succeeded",
                "hqa_run_ref": (
                    "run:paper-plan" if is_plan else "run:paper-final"
                ),
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
            if key
            not in paper_research_cli._ATTESTATION_DERIVED_FIELDS
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

    def show(self, gate_id):
        gate = self.gates.get(gate_id)
        if gate is None:
            raise paper_research_cli._RegistryError(
                "paper_gate_not_found",
                retryable=False,
                not_found=True,
            )
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
            "completion_evidence": payload["completion_evidence"],
            "gate_id": payload["gate_id"],
            "hqa_completion_receipt_digest": payload["hqa_completion_receipt_digest"],
            "hqa_completion_receipt_ref": payload["hqa_completion_receipt_ref"],
            "reviewed_commit": payload["completion_evidence"]["reviewed_commit"],
            "status": "completed",
            "workspace_id": payload["workspace_id"],
        }
        gate = self.gates[payload["gate_id"]]
        previous = gate.get("completion")
        if previous is not None:
            assert previous == completion
            return dict(completion)
        gate.update(
            completion=dict(completion),
            expected_status="completed",
            hqa_completion_receipt_digest=payload["hqa_completion_receipt_digest"],
            hqa_completion_receipt_ref=payload["hqa_completion_receipt_ref"],
            human_git_commit_required=False,
            reviewed_commit=payload["completion_evidence"]["reviewed_commit"],
            status="completed",
        )
        return dict(completion)


def _authority(tmp_path: Path) -> WorkflowAuthority:
    return WorkflowAuthority(
        tmp_path / "workflow-authority",
        "owner-test",
        now=lambda: "2026-07-24T00:00:00.000000Z",
    )


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
    operation_id: str = "paper-plan-flow",
    payload_ref: str,
    plan_digest: str = PLAN_DIGEST,
) -> dict:
    return {
        "operation_id": operation_id,
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
        ).isoformat(timespec="microseconds").replace("+00:00", "Z"),
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
        document["error"]["code"]
        == "paper_research_run_attestation_binding_mismatch"
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


def test_complete_metadata_only_two_attempt_paper_flow(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    authority = _authority(tmp_path)
    registry = _Registry()
    payload1 = "payload:sha256:" + "a" * 64
    payload2 = "payload:sha256:" + "b" * 64
    payload_store = _PayloadStore()
    payload_store.add(payload1, "research_start")
    payload_store.add(payload2, "research_continue")

    code, started = _call(
        monkeypatch,
        capsys,
        operation="start-plan",
        request={
            "operation_id": "paper-plan-flow",
            "workspace_id": WORKSPACE_ID,
            "platform_session_id": PLATFORM_SESSION_ID,
            "payload_ref": payload1,
            "command_id": PLAN_COMMAND_ID,
            "hermes_run_id": "hermes-start-invocation-run",
            "subject_command_id": PLAN_SUBJECT_COMMAND_ID,
            "subject_hermes_run_id": PLAN_SUBJECT_RUN_ID,
            "plan_version": 1,
            "plan_digest": PLAN_DIGEST,
        },
        authority=authority,
        registry=registry,
        payload_store=payload_store,
    )
    assert code == 0, started
    assert started["workflow_state"] == "awaiting_plan_confirmation"
    task_ref = started["task_ref"]
    plan_attempt_ref = started["attempt_ref"]

    code, confirmed = _call(
        monkeypatch,
        capsys,
        operation="confirm-plan",
        request={
            "operation_id": "paper-confirm-plan",
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

    gate1_request = {
        "operation_id": "paper-open-gate1",
        "gate_id": "paper-gate1",
        "workspace_id": WORKSPACE_ID,
        "platform_session_id": PLATFORM_SESSION_ID,
        "task_ref": task_ref,
        "expected_task_version": confirmed["task_version"],
        "attempt_ref": plan_attempt_ref,
        "command_id": GATE1_COMMAND_ID,
        "hermes_run_id": "hermes-gate1-run",
        "hqa_gate_ref": "gate:paper-gate1",
        "source_file_ref": "/tmp/paper_factor.py",
        "universe": "US ETFs",
        "reviewed_source_sha256": SOURCE_DIGEST,
    }
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
    assert gate1_opened["gate"]["attempt_ref"] == plan_attempt_ref
    assert gate1_opened["gate"]["hqa_run_ref"] is None

    gate1_receipt = authority.apply(
        ConfirmFormula(
            "browser-gate1-confirm",
            task_ref,
            confirmed["task_version"],
            "gate:paper-gate1",
            SOURCE_DIGEST,
            "Reviewed exact formula bytes.",
        )
    )
    registry.gates["paper-gate1"].update(
        status="confirmed",
        gate1_confirmation_id=CONFIRMATION_ID,
        hqa_receipt_ref="hqa-paper-gate:pgate-" + "1" * 32,
        hqa_receipt_digest="9" * 64,
    )

    gate2_request = {
        "operation_id": "paper-open-gate2",
        "gate_id": "paper-gate2",
        "parent_gate_id": "paper-gate1",
        "workspace_id": WORKSPACE_ID,
        "platform_session_id": PLATFORM_SESSION_ID,
        "task_ref": task_ref,
        "expected_task_version": gate1_receipt.task_version,
        "attempt_ref": plan_attempt_ref,
        "command_id": GATE2_COMMAND_ID,
        "hermes_run_id": "hermes-gate2-run",
        "hqa_gate_ref": "gate:paper-gate1",
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
    assert gate2_opened["gate"]["attempt_ref"] == plan_attempt_ref

    gate2_receipt = authority.apply(
        BindCandidateManifest(
            "browser-gate2-bind",
            task_ref,
            gate1_receipt.task_version,
            "gate:paper-gate1",
            "candidate:paper-factor",
            CANDIDATE_DIGEST,
        )
    )
    registry.gates["paper-gate2"].update(
        status="reviewed",
        hqa_receipt_ref="hqa-paper-gate:pgate-" + "2" * 32,
        hqa_receipt_digest="a" * 64,
    )

    gate3_request = {
        "operation_id": "paper-open-gate3",
        "gate_id": "paper-gate3",
        "parent_gate_id": "paper-gate2",
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
        "hqa_gate_ref": "gate:paper-gate3",
        "reviewed_source_sha256": SOURCE_DIGEST,
        "gate1_confirmation_id": CONFIRMATION_ID,
        "candidate_id": "paper-factor",
        "expected_digest": CANDIDATE_DIGEST,
        "final_backtest_receipt_id": FINAL_RECEIPT,
        "base_commit": BASE_COMMIT,
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
    assert code == 1
    assert unknown["error"]["code"] == ("paper_research_platform_outcome_unknown")
    assert authority.snapshot(task_ref).state == "awaiting_domain_gate"

    registry.register = register
    code, gate3_opened = _call(
        monkeypatch,
        capsys,
        operation="open-gate3",
        request=gate3_request,
        authority=authority,
        registry=registry,
        payload_store=payload_store,
    )
    assert code == 0
    final_attempt_ref = gate3_opened["gate"]["attempt_ref"]
    assert final_attempt_ref != plan_attempt_ref
    assert gate3_opened["gate"]["expected_task_version"] == (
        gate2_receipt.task_version + 6
    )

    gate3_version = gate3_opened["gate"]["expected_task_version"]
    resolved = authority.apply(
        ResolveDomainGate(
            "browser-gate3-resolve",
            task_ref,
            gate3_version,
            final_attempt_ref,
            "gate:paper-gate3",
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
            "gate:paper-gate3",
            "candidate:paper-factor",
            CANDIDATE_DIGEST,
            f"result:{FINAL_RECEIPT}",
            BASE_COMMIT,
        )
    )
    registry.gates["paper-gate3"].update(
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
    completion_request = {
        "operation_id": "paper-complete-after-human",
        "gate_id": "paper-gate3",
        "workspace_id": WORKSPACE_ID,
        "task_ref": task_ref,
        "expected_task_version": observed.task_version,
        "attempt_ref": final_attempt_ref,
        "reviewed_commit": REVIEWED_COMMIT,
    }
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
    assert completion_evidence["domain_gate_ref"] == "gate:paper-gate3"
    assert completion_evidence["promotion_id"] == PROMOTION_ID
    assert completion_evidence["reviewed_commit"] == REVIEWED_COMMIT
    assert completion_evidence["workflow_audit_status"] == "consistent"
    assert completion_evidence["workflow_audit_ref"].startswith("workflow-audit:")
    assert completion_evidence["workflow_audit_ref"] == (
        "workflow-audit:" + completion_evidence["workflow_audit_digest"]
    )
    assert len(completion_evidence["workflow_audit_digest"]) == 64
    assert completed["hqa_completion_receipt_ref"].startswith("hqa-paper-completion:")
    assert completed["hqa_completion_receipt_digest"] == (
        paper_research_cli.hashlib.sha256(
            paper_research_cli._canonical_bytes(completion_evidence)
        ).hexdigest()
    )
    assert registry.completion_calls[-1] == {
        "completion_evidence": completion_evidence,
        "gate_id": "paper-gate3",
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
    assert (
        replayed["hqa_completion_receipt_ref"]
        == (completed["hqa_completion_receipt_ref"])
    )
    assert (
        replayed["hqa_completion_receipt_digest"]
        == (completed["hqa_completion_receipt_digest"])
    )


@pytest.mark.parametrize(
    ("case", "expected_code"),
    [
        ("leased_invocation", "paper_research_invocation_attestation_invalid"),
        ("forged_attestation", "paper_research_run_attestation_invalid"),
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
        operation_id=f"reject-{case}",
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
        record["expires_at"] = expired.isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z")
        record["created_at"] = (expired - timedelta(days=10)).isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z")
    else:
        record["status"] = "tombstoned"

    code, rejected = _call(
        monkeypatch,
        capsys,
        operation="start-plan",
        request=_start_request(
            operation_id=f"payload-{case}",
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
            operation_id="payload-consumer-conflict",
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
        operation_id="payload-bind-recovery",
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
    assert payload_store.records[payload_ref]["consumer_ref"] == snapshot.attempts[
        0
    ].attempt_ref
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
    assert first["hermes_runtime_instance_id"] != second[
        "hermes_runtime_instance_id"
    ]


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
        "operation_id": f"reject-gate3-{case}",
        "gate_id": f"paper-gate3-{case}",
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
        "hqa_gate_ref": "gate:paper-gate3",
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
            "operation_id": "bad-request",
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
        "operation_id": "runtime-selector-mismatch",
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
            "operation_id": "timeout-start",
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
            "operation_id": "timeout-confirm",
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
            "operation_id": "timeout-gate1",
            "gate_id": "timeout-gate1",
            "workspace_id": WORKSPACE_ID,
            "platform_session_id": PLATFORM_SESSION_ID,
            "task_ref": started["task_ref"],
            "expected_task_version": confirmed["task_version"],
            "attempt_ref": started["attempt_ref"],
            "command_id": GATE1_COMMAND_ID,
            "hermes_run_id": "hermes-gate1-run",
            "hqa_gate_ref": "gate:timeout-gate1",
            "source_file_ref": "/tmp/paper_factor.py",
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

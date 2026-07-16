from __future__ import annotations

import hashlib
import json
import os
import signal
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import hqa.research_workflow_saga as saga_module

from hqa.research_workflow_saga import (
    PlatformBindingOutcomeUnknown,
    PlatformBindingUnavailable,
    ResearchWorkflowSaga,
    SubprocessPlatformWorkflowBindingClient,
)
from hqa.research_workflows import (
    ResearchWorkflowError,
    ResearchWorkflowStore,
    transport_binding_digest,
)


NOW = "2026-07-16T01:02:03.000000Z"
COMMAND_ID = "10000000-0000-0000-0000-000000000001"


def _request() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "platform_session_id": "session-saga-1",
        "client_request_id": "request-saga-1",
        "command_kind": "research_chat",
        "payload_ttl_days": 30,
        "prompt": "Assess a bounded read-only market hypothesis.",
        "provider_policy": {
            "primary": {"provider": "codex", "model": "gpt-5"},
            "fallbacks": [],
        },
        "plan": {
            "schema_version": 1,
            "version": 1,
            "goal": "Assess one bounded read-only hypothesis.",
            "steps": [
                {
                    "step_id": "read-evidence",
                    "kind": "read_only",
                    "description": "Read existing evidence without mutation.",
                }
            ],
        },
    }


def _binding(prepared: dict[str, Any], command_id: str = COMMAND_ID) -> dict[str, Any]:
    return {
        "command_id": command_id,
        "command_version": 1,
        "preparation_schema_version": prepared["schema_version"],
        "workflow_saga_id": prepared["workflow_saga_id"],
        "owner_user_id": prepared["owner_user_id"],
        "platform_session_id": prepared["platform_session_id"],
        "client_request_id": prepared["client_request_id"],
        "command_kind": prepared["command_kind"],
        "canonical_request_digest": prepared["canonical_request_digest"],
        "payload_ref": prepared["payload_ref"],
        "payload_digest": prepared["payload_digest"],
        "payload_expires_at": prepared["payload_expires_at"],
        "provider_policy_digest": prepared["provider_policy_digest"],
        "task_id": prepared["task_id"],
        "task_version": prepared["task_version"],
        "attempt_id": prepared["attempt_id"],
        "attempt_number": prepared["attempt_number"],
        "prepared_event_id": prepared["prepared_event_id"],
        "prepared_event_digest": prepared["prepared_event_digest"],
        "plan_schema_version": prepared["plan_schema_version"],
        "plan_version": prepared["plan_version"],
        "plan_digest": prepared["plan_digest"],
        "workflow_preparation_digest": prepared["workflow_preparation_digest"],
        "binding_schema_version": 1,
        "binding_digest": transport_binding_digest(prepared, command_id),
        "created_at": NOW,
    }


def _retarget_prepared_fact(
    prepared: dict[str, Any], field: str, value: Any
) -> dict[str, Any]:
    changed = dict(prepared)
    changed[field] = value
    facts = {
        key: item
        for key, item in changed.items()
        if key
        not in {
            "prepared_event_id",
            "prepared_event_digest",
            "workflow_preparation_digest",
        }
    }
    semantic = {
        "schema_version": "1.0",
        "kind": "workflow_prepared",
        "aggregate_id": changed["task_id"],
        "aggregate_version": 1,
        "expected_version": 0,
        "operation_id": changed["workflow_saga_id"],
        "facts": facts,
    }
    event_digest = hashlib.sha256(
        json.dumps(
            semantic,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    changed["prepared_event_id"] = f"hqe_{event_digest[:24]}"
    changed["prepared_event_digest"] = event_digest
    changed["workflow_preparation_digest"] = hashlib.sha256(
        json.dumps(
            {
                key: item
                for key, item in changed.items()
                if key != "workflow_preparation_digest"
            },
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return changed


def _inventory_ndjson(bindings: list[dict[str, Any]]) -> bytes:
    lines = [
        {
            "schema_version": "1.0",
            "kind": "workflow_binding_inventory_header",
            "binding_schema_version": 1,
        }
    ]
    digest = hashlib.sha256()
    for ordinal, binding in enumerate(bindings, start=1):
        canonical = json.dumps(
            binding,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
        digest.update(canonical)
        lines.append(
            {
                "schema_version": "1.0",
                "kind": "workflow_binding_inventory_item",
                "ordinal": ordinal,
                "binding": binding,
            }
        )
    lines.append(
        {
            "schema_version": "1.0",
            "kind": "workflow_binding_inventory_trailer",
            "count": len(bindings),
            "bindings_sha256": digest.hexdigest(),
        }
    )
    return b"".join(
        json.dumps(
            line,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
        for line in lines
    )


@dataclass
class _FakePlatform:
    binding: dict[str, Any] | None = None
    ensure_calls: int = 0
    show_calls: int = 0
    outcome_unknown_once: bool = False
    unavailable: bool = False

    def ensure(self, prepared: dict[str, Any]) -> dict[str, Any]:
        self.ensure_calls += 1
        assert "prompt" not in prepared
        assert set(prepared) == {
            "schema_version",
            "workflow_saga_id",
            "owner_user_id",
            "platform_session_id",
            "client_request_id",
            "command_kind",
            "canonical_request_digest",
            "payload_ref",
            "payload_digest",
            "payload_expires_at",
            "provider_policy_digest",
            "task_id",
            "task_version",
            "attempt_id",
            "attempt_number",
            "prepared_event_id",
            "prepared_event_digest",
            "plan_schema_version",
            "plan_version",
            "plan_digest",
            "workflow_preparation_digest",
        }
        if self.unavailable:
            raise PlatformBindingUnavailable()
        if self.binding is None:
            self.binding = _binding(prepared)
        if self.outcome_unknown_once:
            self.outcome_unknown_once = False
            raise PlatformBindingOutcomeUnknown()
        return {
            "binding": dict(self.binding),
            "command_id": self.binding["command_id"],
            "command_state": "queued",
            "command_version": 1,
            "created": self.ensure_calls == 1,
        }

    def show(self, workflow_saga_id: str) -> dict[str, Any] | None:
        self.show_calls += 1
        if self.unavailable:
            raise PlatformBindingUnavailable()
        if self.binding is None:
            return None
        assert self.binding["workflow_saga_id"] == workflow_saga_id
        return {"binding": dict(self.binding)}

    def inventory(self) -> list[dict[str, Any]]:
        return [] if self.binding is None else [dict(self.binding)]


def test_submit_persists_both_authorities_without_sending_prompt_to_platform(
    tmp_path: Path,
) -> None:
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)
    platform = _FakePlatform()
    saga = ResearchWorkflowSaga(store=store, platform=platform)

    result = saga.submit(_request())

    assert result["status"] == "bound"
    assert result["task"]["state"] == "ready"
    assert result["binding"]["command_id"] == COMMAND_ID
    assert platform.ensure_calls == 1
    assert "prompt" not in json.dumps(result)
    assert store.resolve_payload(result["task"]["preparation"]["payload_ref"])[
        "prompt"
    ] == _request()["prompt"]


def test_submit_never_reconstructs_a_truncated_ready_hqa_authority(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workflows"
    store = ResearchWorkflowStore(root, now=lambda: NOW)
    store.prepare(_request())
    (root / "events.v1.jsonl").write_bytes(b"")
    platform = _FakePlatform()

    with pytest.raises(ResearchWorkflowError) as caught:
        ResearchWorkflowSaga(store=store, platform=platform).submit(_request())

    assert caught.value.code == "workflow_ledger_corrupt"
    assert platform.show_calls == 0
    assert platform.ensure_calls == 0
    assert (root / "events.v1.jsonl").read_bytes() == b""


def test_submit_recovers_commit_ack_loss_by_exact_saga_lookup(tmp_path: Path) -> None:
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)
    platform = _FakePlatform(outcome_unknown_once=True)
    saga = ResearchWorkflowSaga(store=store, platform=platform)

    result = saga.submit(_request())

    assert result["status"] == "bound"
    assert platform.ensure_calls == 1
    assert platform.show_calls == 2
    assert len(store.events(result["task"]["task_id"])["events"]) == 2


def test_submit_retries_once_when_timed_out_process_left_no_commit(
    tmp_path: Path,
) -> None:
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)

    class _UnknownBeforeCommit(_FakePlatform):
        first = True

        def ensure(self, prepared: dict[str, Any]) -> dict[str, Any]:
            if self.first:
                self.first = False
                self.ensure_calls += 1
                raise PlatformBindingOutcomeUnknown()
            return super().ensure(prepared)

    platform = _UnknownBeforeCommit()
    saga = ResearchWorkflowSaga(store=store, platform=platform)

    result = saga.submit(_request())

    assert result["status"] == "bound"
    assert platform.show_calls == 2
    assert platform.ensure_calls == 2


def test_repeated_submit_is_exactly_idempotent_across_both_authorities(
    tmp_path: Path,
) -> None:
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)
    platform = _FakePlatform()
    saga = ResearchWorkflowSaga(store=store, platform=platform)

    first = saga.submit(_request())
    second = saga.submit(_request())

    assert second["binding"] == first["binding"]
    assert second["task"] == first["task"]
    assert platform.ensure_calls == 1
    assert len(store.events(first["task"]["task_id"])["events"]) == 2


def test_repeated_submit_never_recreates_a_missing_observed_platform_authority(
    tmp_path: Path,
) -> None:
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)
    platform = _FakePlatform()
    saga = ResearchWorkflowSaga(store=store, platform=platform)
    first = saga.submit(_request())
    platform.binding = None

    with pytest.raises(ResearchWorkflowError) as caught:
        saga.submit(_request())

    assert caught.value.code == "workflow_authority_data_loss"
    assert platform.ensure_calls == 1
    assert store.show(first["task"]["task_id"])["transport_binding"] is not None


def test_reconcile_forwards_platform_commit_after_hqa_observation_crash(
    tmp_path: Path,
) -> None:
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)
    prepared = store.prepare(_request())
    platform = _FakePlatform(binding=_binding(prepared))
    saga = ResearchWorkflowSaga(store=store, platform=platform)

    result = saga.reconcile(prepared["task_id"])

    assert result["status"] == "bound"
    assert result["task"]["transport_binding"]["command_id"] == COMMAND_ID
    assert platform.ensure_calls == 0
    assert platform.show_calls == 1


def test_reconcile_recreates_only_a_missing_unexpired_platform_binding(
    tmp_path: Path,
) -> None:
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)
    prepared = store.prepare(_request())
    platform = _FakePlatform()
    saga = ResearchWorkflowSaga(store=store, platform=platform)

    result = saga.reconcile(prepared["task_id"])

    assert result["status"] == "bound"
    assert platform.show_calls == 1
    assert platform.ensure_calls == 1


def test_reconcile_fails_closed_when_observed_platform_authority_is_missing(
    tmp_path: Path,
) -> None:
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)
    prepared = store.prepare(_request())
    platform = _FakePlatform(binding=_binding(prepared))
    saga = ResearchWorkflowSaga(store=store, platform=platform)
    saga.reconcile(prepared["task_id"])
    platform.binding = None

    with pytest.raises(ResearchWorkflowError) as caught:
        saga.reconcile(prepared["task_id"])

    assert caught.value.code == "workflow_authority_data_loss"
    assert platform.ensure_calls == 0


def test_reconcile_rejects_mismatched_platform_facts_without_hqa_append(
    tmp_path: Path,
) -> None:
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)
    prepared = store.prepare(_request())
    mismatch = _binding(prepared)
    mismatch["plan_digest"] = "f" * 64
    platform = _FakePlatform(binding=mismatch)
    saga = ResearchWorkflowSaga(store=store, platform=platform)

    with pytest.raises(ResearchWorkflowError) as caught:
        saga.reconcile(prepared["task_id"])

    assert caught.value.code == "workflow_binding_mismatch"
    assert len(store.events(prepared["task_id"])["events"]) == 1


def test_reconcile_does_not_create_platform_command_after_payload_deletion(
    tmp_path: Path,
) -> None:
    observed = [NOW]
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: observed[0])
    request = _request()
    request["payload_ttl_days"] = 1
    prepared = store.prepare(request)
    observed[0] = "2026-07-18T01:02:03.000000Z"
    store.reconcile_expired_payloads()
    platform = _FakePlatform()
    saga = ResearchWorkflowSaga(store=store, platform=platform)

    result = saga.reconcile(prepared["task_id"])

    assert result["status"] == "expired_unbound"
    assert result["task"]["payload_status"] == "deleted"
    assert platform.ensure_calls == 0


def test_reconcile_can_observe_exact_binding_after_payload_deletion(
    tmp_path: Path,
) -> None:
    observed = [NOW]
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: observed[0])
    request = _request()
    request["payload_ttl_days"] = 1
    prepared = store.prepare(request)
    observed[0] = "2026-07-18T01:02:03.000000Z"
    store.reconcile_expired_payloads()
    platform = _FakePlatform(binding=_binding(prepared))
    saga = ResearchWorkflowSaga(store=store, platform=platform)

    result = saga.reconcile(prepared["task_id"])

    assert result["status"] == "bound_payload_deleted"
    assert result["task"]["state"] == "payload_deleted"
    assert result["task"]["transport_binding"]["command_id"] == COMMAND_ID


def test_reconcile_reloads_after_concurrent_payload_deletion_cas(
    tmp_path: Path,
) -> None:
    observed = [NOW]
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: observed[0])
    request = _request()
    request["payload_ttl_days"] = 1
    prepared = store.prepare(request)
    binding = _binding(prepared)

    class _DeletingPlatform(_FakePlatform):
        deleted = False

        def show(self, workflow_saga_id: str) -> dict[str, Any] | None:
            if not self.deleted:
                self.deleted = True
                observed[0] = "2026-07-18T01:02:03.000000Z"
                store.reconcile_expired_payloads()
            return super().show(workflow_saga_id)

    platform = _DeletingPlatform(binding=binding)
    saga = ResearchWorkflowSaga(store=store, platform=platform)

    result = saga.reconcile(prepared["task_id"])

    assert result["status"] == "bound_payload_deleted"
    assert result["task"]["version"] == 4
    assert result["task"]["transport_binding"]["command_id"] == COMMAND_ID


@pytest.mark.parametrize(
    "field",
    [
        "command_version",
        "task_version",
        "attempt_number",
        "plan_schema_version",
        "plan_version",
        "binding_schema_version",
    ],
)
def test_platform_binding_integer_facts_reject_booleans(
    tmp_path: Path,
    field: str,
) -> None:
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)
    prepared = store.prepare(_request())
    invalid = _binding(prepared)
    invalid[field] = True
    platform = _FakePlatform(binding=invalid)

    with pytest.raises(ResearchWorkflowError) as caught:
        ResearchWorkflowSaga(store=store, platform=platform).reconcile(
            prepared["task_id"]
        )

    assert caught.value.code == "workflow_binding_mismatch"


def test_subprocess_client_uses_fixed_argv_and_metadata_only_stdin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "quant-system"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o700)
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-cross")
    monkeypatch.setenv("HERMES_API_KEY", "must-not-cross")
    monkeypatch.setenv("QS_FINNHUB_API_KEY", "must-not-cross")
    monkeypatch.setenv("PYTHONPATH", "/tmp/attacker-controlled-imports")
    monkeypatch.setenv("QS_DATABASE_AUTO_MIGRATE", "true")
    monkeypatch.setenv("QS_DATABASE_ENABLED", "true")
    monkeypatch.setenv("QS_DATABASE_URL", "postgresql://local-authority")
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)
    prepared = store.prepare(_request())
    seen: dict[str, Any] = {}

    def run(argv, **kwargs):
        seen["argv"] = argv
        seen.update(kwargs)
        return (
            0,
            json.dumps(
                {
                    "binding": _binding(prepared),
                    "command_id": COMMAND_ID,
                    "command_state": "queued",
                    "command_version": 1,
                    "created": True,
                }
            ).encode("utf-8"),
            b"",
        )

    monkeypatch.setattr(saga_module, "_run_bounded_command", run)
    client = SubprocessPlatformWorkflowBindingClient(executable=executable)

    response = client.ensure(prepared)

    assert seen["argv"] == [
        str(executable),
        "hermes",
        "workflow-binding",
        "ensure",
    ]
    assert seen["cwd"] == str(executable.parent)
    assert seen["env"]["QS_DATABASE_URL"] == "postgresql://local-authority"
    assert seen["env"]["QS_DATABASE_AUTO_MIGRATE"] == "false"
    assert "OPENAI_API_KEY" not in seen["env"]
    assert "HERMES_API_KEY" not in seen["env"]
    assert "QS_FINNHUB_API_KEY" not in seen["env"]
    assert "PYTHONPATH" not in seen["env"]
    assert _request()["prompt"] not in seen["stdin_bytes"].decode("utf-8")
    assert response["binding"]["binding_digest"] == _binding(prepared)[
        "binding_digest"
    ]


def test_subprocess_inventory_uses_fixed_no_stdin_port_and_strict_ndjson(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "quant-system"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o700)
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)
    first = store.prepare(_request())
    second_request = _request()
    second_request["platform_session_id"] = "session-saga-2"
    second_request["client_request_id"] = "request-saga-2"
    second_request["prompt"] = "Another secret prompt."
    second = store.prepare(second_request)
    bindings = sorted(
        [_binding(first), _binding(second, "20000000-0000-0000-0000-000000000002")],
        key=lambda item: (item["workflow_saga_id"], item["command_id"]),
    )
    seen: dict[str, Any] = {}

    def run(argv, **kwargs):
        seen["argv"] = argv
        seen.update(kwargs)
        return 0, _inventory_ndjson(bindings), b""

    monkeypatch.setattr(saga_module, "_run_bounded_inventory_command", run)
    client = SubprocessPlatformWorkflowBindingClient(executable=executable)

    result = client.inventory()

    assert result == bindings
    assert seen["argv"] == [
        str(executable),
        "hermes",
        "workflow-binding",
        "inventory",
    ]
    assert "stdin_bytes" not in seen
    assert _request()["prompt"] not in seen["stdout"].decode("utf-8") if "stdout" in seen else True


@pytest.mark.parametrize(
    "mutate",
    [
        lambda lines: lines.__setitem__(0, {**lines[0], "extra": True}),
        lambda lines: lines[1].__setitem__("ordinal", 2),
        lambda lines: lines[1].__setitem__("ordinal", True),
        lambda lines: lines[1]["binding"].__setitem__("workflow_saga_id", "hqs_ffffffffffffffffffffffff"),
        lambda lines: lines[-1].__setitem__("count", 9),
        lambda lines: lines[-1].__setitem__("bindings_sha256", "0" * 64),
        lambda lines: lines.append(dict(lines[-1])),
    ],
    ids=[
        "unknown-header-field",
        "ordinal-gap",
        "boolean-ordinal",
        "binding-fact-tamper",
        "wrong-count",
        "wrong-digest",
        "content-after-trailer",
    ],
)
def test_subprocess_inventory_rejects_incomplete_or_ambiguous_ndjson(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutate,
) -> None:
    executable = tmp_path / "quant-system"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o700)
    prepared = ResearchWorkflowStore(
        tmp_path / "workflows", now=lambda: NOW
    ).prepare(_request())
    raw = _inventory_ndjson([_binding(prepared)])
    lines = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
    mutate(lines)
    malformed = b"".join(
        json.dumps(line, separators=(",", ":")).encode("utf-8") + b"\n"
        for line in lines
    )
    monkeypatch.setattr(
        saga_module,
        "_run_bounded_inventory_command",
        lambda argv, **kwargs: (0, malformed, b""),
    )

    with pytest.raises(PlatformBindingUnavailable):
        SubprocessPlatformWorkflowBindingClient(executable=executable).inventory()


@pytest.mark.parametrize(
    "raw",
    [
        b'{"schema_version":"1.0","schema_version":"1.0"}\n',
        b'{"schema_version":NaN}\n',
        b"\xff\n",
        b'{"schema_version":"1.0"}',
        b"\n",
    ],
    ids=["duplicate-key", "nan", "invalid-utf8", "truncated", "blank-line"],
)
def test_subprocess_inventory_rejects_non_strict_streams(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    raw: bytes,
) -> None:
    executable = tmp_path / "quant-system"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o700)
    monkeypatch.setattr(
        saga_module,
        "_run_bounded_inventory_command",
        lambda argv, **kwargs: (0, raw, b""),
    )

    with pytest.raises(PlatformBindingUnavailable):
        SubprocessPlatformWorkflowBindingClient(executable=executable).inventory()


def test_subprocess_inventory_rejects_nonzero_even_with_valid_stream(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "quant-system"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o700)
    monkeypatch.setattr(
        saga_module,
        "_run_bounded_inventory_command",
        lambda argv, **kwargs: (1, _inventory_ndjson([]), b""),
    )

    with pytest.raises(PlatformBindingUnavailable):
        SubprocessPlatformWorkflowBindingClient(executable=executable).inventory()


def test_subprocess_client_maps_timeout_to_unknown_without_echoing_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "quant-system"
    executable.write_text("#!/bin/sh\n/bin/sleep 2\n", encoding="utf-8")
    executable.chmod(0o700)
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)
    prepared = store.prepare(_request())

    client = SubprocessPlatformWorkflowBindingClient(
        executable=executable,
        timeout_seconds=0.05,
    )

    with pytest.raises(PlatformBindingOutcomeUnknown) as caught:
        client.ensure(prepared)

    assert _request()["prompt"] not in str(caught.value)


def test_process_group_cleanup_kills_descendant_after_leader_exits(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "spawn-descendant"
    pid_file = tmp_path / "descendant.pid"
    executable.write_text(
        "#!/bin/sh\n"
        "/bin/sleep 30 &\n"
        "echo $! > \"$1\"\n"
        "exit 0\n",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    descendant_pid: int | None = None
    process: subprocess.Popen[bytes] | None = None

    try:
        process = subprocess.Popen(
            [str(executable), str(pid_file)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(tmp_path),
            env={"PATH": "/usr/bin:/bin"},
            start_new_session=True,
        )
        deadline = time.monotonic() + 1
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        descendant_pid = int(pid_file.read_text(encoding="utf-8").strip())
        assert process.wait(timeout=1) == 0

        saga_module._terminate_process_group(process)

        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            try:
                os.kill(descendant_pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.01)
        else:
            pytest.fail("descendant process survived bounded-command cleanup")
    finally:
        if process is not None:
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()
        if descendant_pid is not None:
            try:
                os.kill(descendant_pid, 9)
            except ProcessLookupError:
                pass


def test_post_spawn_supervisor_setup_failure_kills_started_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = subprocess.Popen(
        ["/bin/sleep", "30"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    monkeypatch.setattr(
        saga_module.subprocess,
        "Popen",
        lambda *args, **kwargs: process,
    )
    monkeypatch.setattr(
        saga_module.selectors,
        "DefaultSelector",
        lambda: (_ for _ in ()).throw(OSError("selector setup failed")),
    )

    with pytest.raises(saga_module._PlatformChildExecutionFailed):
        saga_module._run_bounded_command(
            ["ignored"],
            stdin_bytes=b"{}",
            timeout_seconds=1,
            cwd="/",
            env={},
        )

    assert process.wait(timeout=1) == -signal.SIGKILL


def test_mutating_child_supervision_failure_maps_to_unknown_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "quant-system"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o700)
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)
    prepared = store.prepare(_request())
    monkeypatch.setattr(
        saga_module,
        "_run_bounded_command",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            saga_module._PlatformChildExecutionFailed()
        ),
    )
    client = SubprocessPlatformWorkflowBindingClient(executable=executable)

    with pytest.raises(PlatformBindingOutcomeUnknown):
        client.ensure(prepared)
    with pytest.raises(PlatformBindingUnavailable):
        client.show("hqs_0123456789abcdef01234567")


def test_selector_cleanup_failure_preserves_timeout_and_reaps_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = subprocess.Popen(
        ["/bin/sleep", "30"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    real_selector_factory = saga_module.selectors.DefaultSelector

    class CleanupFailingSelector:
        def __init__(self) -> None:
            self.inner = real_selector_factory()

        def register(self, *args, **kwargs):
            return self.inner.register(*args, **kwargs)

        def unregister(self, *args, **kwargs):
            self.inner.unregister(*args, **kwargs)
            raise OSError("cleanup path must not replace timeout")

        def select(self, *args, **kwargs):
            return self.inner.select(*args, **kwargs)

        def get_map(self):
            return self.inner.get_map()

        def close(self) -> None:
            self.inner.close()
            raise OSError("cleanup path must not replace timeout")

    monkeypatch.setattr(
        saga_module.selectors,
        "DefaultSelector",
        CleanupFailingSelector,
    )
    monkeypatch.setattr(
        saga_module.subprocess,
        "Popen",
        lambda *args, **kwargs: process,
    )

    with pytest.raises(subprocess.TimeoutExpired):
        saga_module._run_bounded_command(
            ["ignored"],
            stdin_bytes=b"{}",
            timeout_seconds=0.05,
            cwd="/",
            env={},
        )

    assert process.wait(timeout=1) == -signal.SIGKILL


@pytest.mark.parametrize(
    "stdout",
    [
        '{"binding":{},"binding":{}}',
        '{"binding":NaN}',
    ],
)
def test_subprocess_client_rejects_ambiguous_or_oversized_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stdout: str,
) -> None:
    executable = tmp_path / "quant-system"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o700)

    monkeypatch.setattr(
        saga_module,
        "_run_bounded_command",
        lambda argv, **kwargs: (0, stdout.encode("utf-8"), b""),
    )
    client = SubprocessPlatformWorkflowBindingClient(executable=executable)

    with pytest.raises(PlatformBindingUnavailable):
        client.show("hqs_0123456789abcdef01234567")


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_subprocess_client_kills_a_child_that_exceeds_either_output_cap(
    tmp_path: Path,
    stream: str,
) -> None:
    executable = tmp_path / "quant-system"
    redirect = "1>&2" if stream == "stderr" else ""
    executable.write_text(
        "#!/bin/sh\n"
        f"/bin/dd if=/dev/zero bs=65537 count=1 2>/dev/null {redirect}\n",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    client = SubprocessPlatformWorkflowBindingClient(
        executable=executable,
        timeout_seconds=5,
    )

    with pytest.raises(PlatformBindingUnavailable):
        client.show("hqs_0123456789abcdef01234567")


def test_authority_audit_classifies_both_missing_as_uninitialized_without_writes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "missing" / "workflows"
    platform = _FakePlatform()

    report = ResearchWorkflowSaga(
        store=ResearchWorkflowStore(root, now=lambda: NOW),
        platform=platform,
    ).audit_authorities()

    assert report["findings"] == [{"status": "uninitialized"}]
    assert report["summary"] == {"uninitialized": 1}
    assert platform.ensure_calls == 0
    assert platform.show_calls == 0
    assert not root.exists()


def test_authority_audit_preserves_nonempty_audit_only_authority_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "missing" / "workflows"
    store = ResearchWorkflowStore(root, now=lambda: NOW)
    snapshot = {
        "schema_version": "1.0",
        "authority_state": "present",
        "last_sequence": 2,
        "last_record_sha256": "a" * 64,
        "tasks": [],
    }
    monkeypatch.setattr(store, "inventory_tasks", lambda: dict(snapshot))

    report = ResearchWorkflowSaga(
        store=store,
        platform=_FakePlatform(),
    ).audit_authorities()

    assert report["findings"] == [{"status": "consistent_empty"}]
    assert report["summary"] == {"consistent_empty": 1}
    assert report["hqa_snapshot"] == {
        "authority_state": "present",
        "last_sequence": 2,
        "last_record_sha256": "a" * 64,
    }
    assert not root.exists()


def test_authority_audit_reports_platform_only_when_hqa_root_was_lost(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workflows"
    store = ResearchWorkflowStore(root, now=lambda: NOW)
    prepared = store.prepare(_request())
    binding = _binding(prepared)
    shutil.rmtree(root)
    platform = _FakePlatform(binding=binding)

    report = ResearchWorkflowSaga(
        store=ResearchWorkflowStore(root, now=lambda: NOW),
        platform=platform,
    ).audit_authorities()

    assert report["findings"] == [
        {
            "status": "platform_only",
            "workflow_saga_id": prepared["workflow_saga_id"],
            "task_id": prepared["task_id"],
            "attempt_id": prepared["attempt_id"],
            "command_id": COMMAND_ID,
            "workflow_preparation_digest": prepared[
                "workflow_preparation_digest"
            ],
            "binding_digest": binding["binding_digest"],
        }
    ]
    assert not root.exists()


def test_submit_never_recreates_a_workflow_from_authority_remnants(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workflows"
    store = ResearchWorkflowStore(root, now=lambda: NOW)
    store.prepare(_request())
    (root / ".ledger.lock").unlink()
    (root / "events.v1.jsonl").unlink()
    platform = _FakePlatform()

    with pytest.raises(ResearchWorkflowError) as caught:
        ResearchWorkflowSaga(store=store, platform=platform).submit(_request())

    assert caught.value.code == "workflow_ledger_corrupt"
    assert platform.ensure_calls == 0
    assert platform.show_calls == 0
    assert sorted(path.name for path in root.iterdir()) == [
        "payloads",
        "projection.v1.json",
    ]


@pytest.mark.parametrize(
    ("hqa_observed", "platform_present", "expire", "expected_status"),
    [
        (False, False, False, "awaiting_platform_binding"),
        (False, True, False, "observation_missing"),
        (True, True, False, "consistent"),
        (True, False, False, "platform_missing_after_observation"),
        (False, False, True, "expired_unbound"),
    ],
)
def test_authority_audit_classifies_cross_authority_states(
    tmp_path: Path,
    hqa_observed: bool,
    platform_present: bool,
    expire: bool,
    expected_status: str,
) -> None:
    observed_now = [NOW]
    store = ResearchWorkflowStore(
        tmp_path / "workflows", now=lambda: observed_now[0]
    )
    request = _request()
    request["payload_ttl_days"] = 1
    prepared = store.prepare(request)
    binding = _binding(prepared)
    if hqa_observed:
        store.observe_transport_binding(
            task_id=prepared["task_id"],
            expected_version=1,
            command_id=COMMAND_ID,
            binding_digest=binding["binding_digest"],
        )
    if expire:
        observed_now[0] = "2026-07-18T01:02:03.000000Z"
        store.reconcile_expired_payloads()
    files_before = {
        str(path.relative_to(store.root)): path.read_bytes()
        for path in store.root.rglob("*")
        if path.is_file()
    }
    platform = _FakePlatform(binding=binding if platform_present else None)
    report = ResearchWorkflowSaga(
        store=store,
        platform=platform,
    ).audit_authorities()

    assert report["findings"][0]["status"] == expected_status
    serialized = json.dumps(report, sort_keys=True)
    assert _request()["prompt"] not in serialized
    assert _request()["plan"]["goal"] not in serialized
    assert "codex" not in serialized
    assert str(store.root) not in serialized
    assert platform.ensure_calls == 0
    assert platform.show_calls == 0
    assert {
        str(path.relative_to(store.root)): path.read_bytes()
        for path in store.root.rglob("*")
        if path.is_file()
    } == files_before


def test_authority_audit_reports_exact_observed_binding_conflict(
    tmp_path: Path,
) -> None:
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)
    prepared = store.prepare(_request())
    original = _binding(prepared)
    store.observe_transport_binding(
        task_id=prepared["task_id"],
        expected_version=1,
        command_id=COMMAND_ID,
        binding_digest=original["binding_digest"],
    )
    conflicting = _binding(
        prepared, "20000000-0000-0000-0000-000000000002"
    )

    report = ResearchWorkflowSaga(
        store=store,
        platform=_FakePlatform(binding=conflicting),
    ).audit_authorities()

    assert report["findings"][0] == {
        "status": "exact_fact_conflict",
        "hqa_workflow_saga_id": prepared["workflow_saga_id"],
        "hqa_task_id": prepared["task_id"],
        "hqa_attempt_id": prepared["attempt_id"],
        "hqa_workflow_preparation_digest": prepared[
            "workflow_preparation_digest"
        ],
        "hqa_command_id": original["command_id"],
        "hqa_binding_digest": original["binding_digest"],
        "platform_workflow_saga_id": conflicting["workflow_saga_id"],
        "platform_task_id": conflicting["task_id"],
        "platform_attempt_id": conflicting["attempt_id"],
        "platform_workflow_preparation_digest": conflicting[
            "workflow_preparation_digest"
        ],
        "platform_command_id": conflicting["command_id"],
        "platform_binding_digest": conflicting["binding_digest"],
    }


def test_authority_audit_namespaces_same_saga_preparation_conflict(
    tmp_path: Path,
) -> None:
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)
    prepared = store.prepare(_request())
    conflicting_prepared = _retarget_prepared_fact(
        prepared, "platform_session_id", "session-conflicting-authority"
    )
    conflicting = _binding(conflicting_prepared)

    finding = ResearchWorkflowSaga(
        store=store,
        platform=_FakePlatform(binding=conflicting),
    ).audit_authorities()["findings"][0]

    assert finding == {
        "status": "exact_fact_conflict",
        "hqa_workflow_saga_id": prepared["workflow_saga_id"],
        "hqa_task_id": prepared["task_id"],
        "hqa_attempt_id": prepared["attempt_id"],
        "hqa_workflow_preparation_digest": prepared[
            "workflow_preparation_digest"
        ],
        "platform_workflow_saga_id": conflicting["workflow_saga_id"],
        "platform_task_id": conflicting["task_id"],
        "platform_attempt_id": conflicting["attempt_id"],
        "platform_workflow_preparation_digest": conflicting[
            "workflow_preparation_digest"
        ],
        "platform_command_id": conflicting["command_id"],
        "platform_binding_digest": conflicting["binding_digest"],
    }


def test_authority_audit_namespaces_cross_saga_idempotency_collision(
    tmp_path: Path,
) -> None:
    hqa_store = ResearchWorkflowStore(tmp_path / "hqa", now=lambda: NOW)
    hqa_prepared = hqa_store.prepare(_request())
    hqa_binding = _binding(hqa_prepared)
    hqa_store.observe_transport_binding(
        task_id=hqa_prepared["task_id"],
        expected_version=1,
        command_id=hqa_binding["command_id"],
        binding_digest=hqa_binding["binding_digest"],
    )
    conflicting_request = _request()
    conflicting_request["prompt"] = "A distinct secret intent."
    platform_prepared = ResearchWorkflowStore(
        tmp_path / "other", now=lambda: NOW
    ).prepare(conflicting_request)
    platform_binding = _binding(
        platform_prepared, "20000000-0000-0000-0000-000000000002"
    )

    finding = ResearchWorkflowSaga(
        store=hqa_store,
        platform=_FakePlatform(binding=platform_binding),
    ).audit_authorities()["findings"][0]

    assert finding["status"] == "exact_fact_conflict"
    assert finding["hqa_workflow_saga_id"] == hqa_prepared["workflow_saga_id"]
    assert finding["platform_workflow_saga_id"] == platform_prepared[
        "workflow_saga_id"
    ]
    assert finding["hqa_command_id"] == hqa_binding["command_id"]
    assert finding["platform_command_id"] == platform_binding["command_id"]
    serialized = json.dumps(finding, sort_keys=True)
    assert _request()["prompt"] not in serialized
    assert conflicting_request["prompt"] not in serialized
    assert str(hqa_store.root) not in serialized


def test_authority_audit_retries_snapshot_change_then_returns_stable_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)
    prepared = store.prepare(_request())
    stable = store.inventory_tasks()
    stale = {**stable, "last_sequence": 0, "last_record_sha256": None}
    snapshots = iter([stale, stable, stable, stable])
    monkeypatch.setattr(store, "inventory_tasks", lambda: next(snapshots))
    platform = _FakePlatform(binding=_binding(prepared))

    report = ResearchWorkflowSaga(store=store, platform=platform).audit_authorities()

    assert report["findings"][0]["status"] == "observation_missing"
    assert report["audit_attempts"] == 2


def test_authority_audit_fails_retryably_after_two_snapshot_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)
    base = store.inventory_tasks()
    sequence = iter(
        {**base, "last_sequence": index, "last_record_sha256": f"{index:064x}"}
        for index in range(6)
    )
    monkeypatch.setattr(store, "inventory_tasks", lambda: next(sequence))

    with pytest.raises(ResearchWorkflowError) as caught:
        ResearchWorkflowSaga(
            store=store, platform=_FakePlatform()
        ).audit_authorities()

    assert caught.value.code == "workflow_authority_audit_busy"
    assert caught.value.retryable is True

from __future__ import annotations

import io
import json

import pytest

from hqa import research_task_cli as cli
from hqa.research_workflow_saga import PlatformBindingOutcomeUnknown
from hqa.research_workflows import ResearchWorkflowStore


NOW = "2026-07-16T01:02:03.000000Z"


def _request() -> dict:
    return {
        "schema_version": "1.0",
        "platform_session_id": "session-local-1",
        "client_request_id": "request-local-1",
        "command_kind": "research_chat",
        "payload_ttl_days": 1,
        "prompt": "Secret bounded read-only research prompt.",
        "provider_policy": {
            "primary": {"provider": "openai-codex", "model": "gpt-5-codex"},
            "fallbacks": [{"provider": "xai", "model": "grok-4.5"}],
        },
        "plan": {
            "schema_version": 1,
            "version": 1,
            "goal": "Compare one bounded read-only hypothesis.",
            "steps": [
                {
                    "step_id": "inspect-existing-results",
                    "kind": "read_only",
                    "description": "Read existing result references only.",
                }
            ],
        },
    }


def test_prepare_reads_prompt_only_from_json_stdin_and_emits_metadata(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)
    monkeypatch.setattr(cli, "_store", lambda: store)
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(json.dumps(_request())))

    exit_code = cli.main(["prepare"])

    captured = capsys.readouterr()
    receipt = json.loads(captured.out)
    assert exit_code == 0
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    assert receipt["command_kind"] == "research_chat"
    assert _request()["prompt"] not in captured.out


def test_show_events_and_reconcile_are_one_json_documents(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    observed_now = [NOW]
    store = ResearchWorkflowStore(
        tmp_path / "workflows",
        now=lambda: observed_now[0],
    )
    monkeypatch.setattr(cli, "_store", lambda: store)
    prepared = store.prepare(_request())
    assert cli.main(["show", "--task-id", prepared["task_id"]]) == 0
    assert json.loads(capsys.readouterr().out)["task_id"] == prepared["task_id"]

    assert cli.main(["events", "--task-id", prepared["task_id"]]) == 0
    assert len(json.loads(capsys.readouterr().out)["events"]) == 1

    observed_now[0] = "2026-07-18T01:02:03.000000Z"
    assert cli.main(["reconcile-payloads"]) == 0
    assert json.loads(capsys.readouterr().out)["completed_task_ids"] == [
        prepared["task_id"]
    ]


def test_public_cli_does_not_expose_unverified_binding_observation(capsys) -> None:
    exit_code = cli.main(
        [
            "observe-binding",
            "--task-id",
            "hqt_0123456789abcdef01234567",
            "--expected-version",
            "1",
            "--command-id",
            "10000000-0000-0000-0000-000000000001",
            "--binding-digest",
            "a" * 64,
        ]
    )

    assert exit_code == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == (
        "workflow_invalid_arguments"
    )


def test_invalid_stdin_is_generic_json_error_and_never_echoes_prompt(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)
    monkeypatch.setattr(cli, "_store", lambda: store)
    secret = "DO-NOT-ECHO-THIS-PROMPT"
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(f'{{"prompt":"{secret}",'))

    exit_code = cli.main(["prepare"])

    captured = capsys.readouterr()
    error = json.loads(captured.out)["error"]
    assert exit_code == 2
    assert captured.err == ""
    assert error["code"] == "workflow_invalid_json"
    assert secret not in captured.out


def test_invalid_unhashable_plan_step_kind_is_a_sanitized_workflow_error(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    store = ResearchWorkflowStore(tmp_path / "workflows", now=lambda: NOW)
    monkeypatch.setattr(cli, "_store", lambda: store)
    request = _request()
    request["plan"]["steps"][0]["kind"] = []
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(json.dumps(request)))

    exit_code = cli.main(["prepare"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert json.loads(captured.out)["error"]["code"] == "workflow_invalid_request"
    assert captured.err == ""


def test_invalid_argv_is_sanitized_and_does_not_echo_accidental_secret(
    capsys,
) -> None:
    secret = "DO-NOT-ECHO-ARGV-PROMPT"

    exit_code = cli.main(["prepare", "--prompt", secret])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert json.loads(captured.out)["error"]["code"] == "workflow_invalid_arguments"
    assert secret not in captured.out
    assert captured.err == ""


@pytest.mark.parametrize(
    ("argv", "use_saga"),
    [
        (["show", "--task-id", "hqt_0123456789abcdef01234567"], False),
        (["events", "--task-id", "hqt_0123456789abcdef01234567"], False),
        (
            [
                "reconcile-binding",
                "--task-id",
                "hqt_0123456789abcdef01234567",
            ],
            True,
        ),
    ],
)
def test_read_command_oserror_is_sanitized_json(
    monkeypatch,
    capsys,
    argv,
    use_saga,
) -> None:
    secret_path = "/private/secret/workflow-authority"

    class FailingStore:
        def show(self, _task_id):
            raise OSError(secret_path)

        def events(self, _task_id, **_kwargs):
            raise OSError(secret_path)

    class FailingSaga:
        def reconcile(self, _task_id):
            raise OSError(secret_path)

    if use_saga:
        monkeypatch.setattr(cli, "_saga", lambda: FailingSaga())
    else:
        monkeypatch.setattr(cli, "_store", lambda: FailingStore())

    exit_code = cli.main(argv)

    captured = capsys.readouterr()
    assert exit_code == 1
    assert json.loads(captured.out) == {
        "error": {
            "code": "workflow_storage_io_error",
            "message": "workflow storage is unavailable",
            "retryable": True,
        }
    }
    assert captured.err == ""
    assert secret_path not in captured.out


def test_reconcile_cli_rejects_caller_supplied_as_of(capsys) -> None:
    exit_code = cli.main(
        [
            "reconcile-payloads",
            "--as-of",
            "2099-01-01T00:00:00.000000Z",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert json.loads(captured.out)["error"]["code"] == (
        "workflow_invalid_arguments"
    )
    assert captured.err == ""


def test_submit_and_binding_reconcile_use_cross_authority_saga(
    monkeypatch,
    capsys,
) -> None:
    seen = []
    task = {
        "task_id": "hqt_0123456789abcdef01234567",
        "state": "ready",
        "goal": "A bounded goal.",
    }

    class FakeSaga:
        def submit(self, request):
            seen.append(("submit", request))
            return {
                "schema_version": "1.0",
                "status": "bound",
                "task": task,
                "binding": {"command_id": "10000000-0000-0000-0000-000000000001"},
            }

        def reconcile(self, task_id):
            seen.append(("reconcile", task_id))
            return {
                "schema_version": "1.0",
                "status": "bound",
                "task": task,
                "binding": {"command_id": "10000000-0000-0000-0000-000000000001"},
            }

        def audit_authorities(self):
            seen.append(("audit", None))
            return {
                "schema_version": "1.0",
                "audit_attempts": 1,
                "hqa_snapshot": {
                    "authority_state": "absent",
                    "last_sequence": 0,
                    "last_record_sha256": None,
                },
                "platform_snapshot": {
                    "count": 0,
                    "bindings_sha256": (
                        "e3b0c44298fc1c149afbf4c8996fb924"
                        "27ae41e4649b934ca495991b7852b855"
                    ),
                },
                "summary": {"uninitialized": 1},
                "findings": [{"status": "uninitialized"}],
            }

    monkeypatch.setattr(cli, "_saga", lambda: FakeSaga())
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(json.dumps(_request())))

    assert cli.main(["submit"]) == 0
    submit_output = capsys.readouterr().out
    assert json.loads(submit_output)["status"] == "bound"
    assert _request()["prompt"] not in submit_output

    assert (
        cli.main(
            [
                "reconcile-binding",
                "--task-id",
                task["task_id"],
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["status"] == "bound"
    assert cli.main(["audit-authorities"]) == 0
    assert json.loads(capsys.readouterr().out)["findings"] == [
        {"status": "uninitialized"}
    ]
    assert seen == [
        ("submit", _request()),
        ("reconcile", task["task_id"]),
        ("audit", None),
    ]


def test_submit_maps_unknown_platform_outcome_to_generic_retryable_json(
    monkeypatch,
    capsys,
) -> None:
    secret = _request()["prompt"]

    class UnknownSaga:
        def submit(self, _request):
            raise PlatformBindingOutcomeUnknown()

    monkeypatch.setattr(cli, "_saga", lambda: UnknownSaga())
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(json.dumps(_request())))

    exit_code = cli.main(["submit"])

    captured = capsys.readouterr()
    error = json.loads(captured.out)["error"]
    assert exit_code == 1
    assert error == {
        "code": "workflow_platform_outcome_unknown",
        "message": "platform binding outcome is unknown; reconcile by exact task",
        "retryable": True,
    }
    assert secret not in captured.out

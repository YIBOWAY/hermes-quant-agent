from __future__ import annotations

import json
import hashlib
import fcntl
import os
import re
import subprocess
import threading
from contextlib import contextmanager
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write_contracts(root: Path, relative_paths: tuple[str, ...]) -> None:
    for relative in relative_paths:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"contract:{relative}\n", encoding="utf-8")


class _ProbeHandler(BaseHTTPRequestHandler):
    responses: dict[str, object] = {}
    requests: list[tuple[str, str, dict[str, str]]] = []

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler interface
        type(self).requests.append(
            (
                self.command,
                self.path,
                {key.lower(): value for key, value in self.headers.items()},
            )
        )
        payload = type(self).responses[self.path]
        if type(payload) is tuple:
            status, headers, body = payload
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 - must prove watcher never mutates
        type(self).requests.append(
            (
                self.command,
                self.path,
                {key.lower(): value for key, value in self.headers.items()},
            )
        )
        self.send_response(405)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


@contextmanager
def _probe_server():
    _ProbeHandler.requests = []
    _ProbeHandler.responses = {
        "/health": {
            "status": "ok",
            "platform": "hermes-agent",
            "version": "0.18.2",
        },
        "/v1/capabilities": _local_agent_capabilities(),
        "/api/health": {
            "status": "ok",
            "app_name": "quant-system",
            "environment": "development",
            "data_provider": {
                "configured_default": "futu",
                "tiingo_token_present": False,
            },
            "futu_opend": {
                "enabled": True,
                "host": "127.0.0.1",
                "port": 11111,
                "reachable": True,
                "error": None,
            },
            "database": {"enabled": True, "reachable": True, "error": None},
            "hermes_command_ledger": {
                "database_configured": True,
                "schema_ready": True,
                "schema_version": 5,
                "workflow_binding_schema_ready": False,
                "workflow_binding_schema_version": None,
                "mutation_enabled": False,
            },
            "safety": {
                "dry_run": True,
                "paper_trading": True,
                "live_trading_enabled": False,
                "kill_switch": True,
                "bind_address": "127.0.0.1",
            },
        },
        "/api/hermes/gateway": {
            "read_status": "available",
            "connected": True,
            "model": "local",
            "session_api_available": True,
            "chat_write_ready": False,
            "features": {"session_resources": True},
            "upstream_blockers": ["writes_disabled"],
            "platform_delivery_blockers": ["writes_disabled"],
            "blockers": ["writes_disabled"],
            "warnings": [],
            "safety": {
                "dry_run": True,
                "paper_trading": True,
                "live_trading_enabled": False,
                "kill_switch": True,
                "bind_address": "127.0.0.1",
            },
        },
        "/api/hermes/sessions?limit=1&offset=0": {
            "read_status": "available",
            "sessions": [
                {
                    "id": "sensitive-session-id",
                    "title": "sensitive title",
                    "source": "discord",
                    "model": "private-model",
                    "message_count": 1,
                    "last_active": None,
                    "preview": "sensitive message",
                    "parent_session_id": None,
                    "ended_at": None,
                }
            ],
            "limit": 1,
            "offset": 0,
            "has_more": False,
            "warnings": [],
            "safety": {
                "dry_run": True,
                "paper_trading": True,
                "live_trading_enabled": False,
                "kill_switch": True,
                "bind_address": "127.0.0.1",
            },
        },
    }
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ProbeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def _config(tmp_path: Path, base_url: str):
    from hqa.hermes_compatibility import (
        HQA_REPROBE_TRIGGER_FILES,
        PLATFORM_REPROBE_TRIGGER_FILES,
        WATCHER_CONTRACT_FILES,
        CompatibilityConfig,
    )

    hqa_repo = tmp_path / "hqa"
    platform_repo = tmp_path / "platform"
    hermes_repo = tmp_path / "hermes"
    hqa_repo.mkdir(parents=True)
    platform_repo.mkdir(parents=True)
    hermes_repo.mkdir(parents=True)
    _write_contracts(hqa_repo, HQA_REPROBE_TRIGGER_FILES)
    _write_contracts(hqa_repo, WATCHER_CONTRACT_FILES)
    _write_contracts(platform_repo, PLATFORM_REPROBE_TRIGGER_FILES)

    _git(hermes_repo, "init", "-q", "-b", "main")
    _git(hermes_repo, "config", "user.name", "Compatibility Test")
    _git(hermes_repo, "config", "user.email", "compat@example.invalid")
    (hermes_repo / "source.py").write_text("VERSION = 1\n", encoding="utf-8")
    _git(hermes_repo, "add", "source.py")
    _git(hermes_repo, "commit", "-q", "-m", "initial")
    fake_hermes = tmp_path / "hermes-cli"
    calls = tmp_path / "hermes-cli.calls"
    fake_hermes.write_text(
        "#!/bin/bash\n"
        f"printf x >> '{calls}'\n"
        "printf '%s\\n' 'Gateway is supervised by launchd (PID 123)'\n",
        encoding="utf-8",
    )
    fake_hermes.chmod(0o755)
    return CompatibilityConfig(
        hqa_repo=hqa_repo,
        platform_repo=platform_repo,
        hermes_repo=hermes_repo,
        state_dir=tmp_path / "state",
        hermes_base_url=base_url,
        platform_base_url=base_url,
        hermes_cli_path=fake_hermes,
        timeout_seconds=1.0,
    )


def _platform_contract() -> dict[str, object]:
    return {
        "schema_version": 1,
        "profile": "local_agent_v0_2",
        "hermes_contract_version_min": 1,
        "required_bool_features": [
            "session_resources",
            "run_submission",
            "run_events_sse",
            "run_events_snapshot",
            "run_status",
            "run_approval_response",
            "run_stop",
            "managed_run_sessions",
        ],
        "required_exact_features": {
            "managed_run_history_authority": "hermes_session_db",
            "managed_session_fork_mode": (
                "preserve_source_exact_message_cursor"
            ),
        },
        "required_durable": [
            "idempotency",
            "event_replay",
            "approval_cas",
            "idempotent_stop",
            "restart_reconcile",
            "run_evidence",
        ],
        "durable_evidence_template": "store.transactional_probe:{capability}",
        "hqa_cli_operations": [
            "capabilities",
            "submit",
            "status",
            "events",
            "session-ensure",
            "session-fork",
        ],
        "http_endpoints": [
            {"method": "GET", "path": "/v1/capabilities"},
            {"method": "POST", "path": "/v1/runs"},
            {"method": "GET", "path": "/v1/runs/{run_id}"},
            {"method": "GET", "path": "/v1/runs/{run_id}/events"},
            {
                "method": "GET",
                "path": "/v1/runs/{run_id}/events/snapshot",
            },
            {"method": "POST", "path": "/v1/runs/{run_id}/approval"},
            {"method": "POST", "path": "/v1/runs/{run_id}/stop"},
            {"method": "POST", "path": "/api/sessions"},
            {"method": "GET", "path": "/api/sessions/{session_id}"},
            {
                "method": "GET",
                "path": "/api/sessions/{session_id}/messages",
            },
            {
                "method": "POST",
                "path": "/api/sessions/{session_id}/fork",
            },
        ],
        "write_contract": {
            "run_submit_fields": ["input", "session_id", "metadata"],
            "platform_must_not_send": [
                "conversation_history",
                "previous_response_id",
            ],
            "fork_requires": {
                "preserve_source": True,
                "fork_point_format": "message:<positive-integer-id>",
            },
        },
    }


def _local_agent_capabilities() -> dict[str, object]:
    contract = _platform_contract()
    required_bool = contract["required_bool_features"]
    assert isinstance(required_bool, list)
    required_exact = contract["required_exact_features"]
    assert isinstance(required_exact, dict)
    required_durable = contract["required_durable"]
    assert isinstance(required_durable, list)
    endpoints = {
        "capabilities": {"method": "GET", "path": "/v1/capabilities"},
        "runs": {"method": "POST", "path": "/v1/runs"},
        "run_status": {"method": "GET", "path": "/v1/runs/{run_id}"},
        "run_events": {
            "method": "GET",
            "path": "/v1/runs/{run_id}/events",
        },
        "run_events_snapshot": {
            "method": "GET",
            "path": "/v1/runs/{run_id}/events/snapshot",
        },
        "run_approval": {
            "method": "POST",
            "path": "/v1/runs/{run_id}/approval",
        },
        "run_stop": {
            "method": "POST",
            "path": "/v1/runs/{run_id}/stop",
        },
        "session_create": {"method": "POST", "path": "/api/sessions"},
        "session": {
            "method": "GET",
            "path": "/api/sessions/{session_id}",
        },
        "session_messages": {
            "method": "GET",
            "path": "/api/sessions/{session_id}/messages",
        },
        "session_fork": {
            "method": "POST",
            "path": "/api/sessions/{session_id}/fork",
        },
    }
    return {
        "object": "hermes.api_server.capabilities",
        "platform": "hermes-agent",
        "contract_version": 1,
        "features": {
            **{str(name): True for name in required_bool},
            **required_exact,
        },
        "durable": {
            str(name): {
                "supported": True,
                "grounded": True,
                "evidence": f"store.transactional_probe:{name}",
            }
            for name in required_durable
        },
        "endpoints": endpoints,
    }


def _local_agent_config(tmp_path: Path, base_url: str):
    from hqa.hermes_compatibility import CompatibilityConfig

    base = _config(tmp_path, base_url)
    contract_path = (
        base.platform_repo
        / "contracts"
        / "agent_v02_hermes_compatibility.v1.json"
    )
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text(
        json.dumps(_platform_contract()),
        encoding="utf-8",
    )
    health = dict(_ProbeHandler.responses["/api/health"])
    health["hermes_command_ledger"] = {
        "database_configured": True,
        "schema_ready": True,
        "schema_version": 5,
        "workflow_binding_schema_ready": True,
        "workflow_binding_schema_version": 2,
        "session_registry_schema_ready": True,
        "session_registry_schema_version": 2,
        "agent_workspace_authorities_ready": True,
        "research_binding_ready": True,
        "mutation_enabled": True,
        "composer_write_ready": True,
        "chat_write_ready": True,
    }
    _ProbeHandler.responses["/api/health"] = health
    gateway = dict(_ProbeHandler.responses["/api/hermes/gateway"])
    gateway["chat_write_ready"] = True
    gateway["features"] = {
        name: True
        for name in _platform_contract()["required_bool_features"]  # type: ignore[index]
    }
    _ProbeHandler.responses["/api/hermes/gateway"] = gateway
    return CompatibilityConfig(
        hqa_repo=base.hqa_repo,
        platform_repo=base.platform_repo,
        hermes_repo=base.hermes_repo,
        state_dir=base.state_dir,
        profile="local_agent_v0_2",
        hermes_base_url=base_url,
        platform_base_url=base_url,
        hermes_cli_path=base.hermes_cli_path,
        timeout_seconds=1.0,
    )


def test_local_agent_profile_validates_manifest_and_native_capability_surface(
    tmp_path: Path,
) -> None:
    from hqa.hermes_compatibility import check_compatibility

    with _probe_server() as base_url:
        config = _local_agent_config(tmp_path, base_url)
        result = check_compatibility(config)

    assert result.status == "compatible"
    assert result.probed is True
    assert [(method, path) for method, path, _headers in _ProbeHandler.requests] == [
        ("GET", "/health"),
        ("GET", "/v1/capabilities"),
        ("GET", "/api/health"),
        ("GET", "/api/hermes/gateway"),
        ("GET", "/api/hermes/sessions?limit=1&offset=0"),
    ]
    assert all(method == "GET" for method, _path, _headers in _ProbeHandler.requests)
    assert result.report_path is not None
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report["reprobe_identity"]["profile"] == "local_agent_v0_2"
    platform_contract = report["reprobe_identity"]["platform_contract"]
    assert platform_contract["schema_version"] == 1
    assert re.fullmatch(r"[0-9a-f]{64}", platform_contract["digest"])


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (
            lambda payload: payload.update(contract_version=0),
            "contract_version_drift",
        ),
        (
            lambda payload: payload["features"].update(
                managed_run_history_authority="platform_shadow_history"
            ),
            "exact_feature_drift",
        ),
        (
            lambda payload: payload["features"].pop("run_events_snapshot"),
            "bool_feature_drift",
        ),
        (
            lambda payload: payload["durable"]["event_replay"].update(
                grounded=False
            ),
            "durable_event_replay_drift",
        ),
        (
            lambda payload: payload["durable"]["run_evidence"].update(
                evidence="flag_only"
            ),
            "durable_run_evidence_drift",
        ),
        (
            lambda payload: payload["endpoints"].pop("session_fork"),
            "http_endpoint_drift",
        ),
        (
            lambda payload: payload["endpoints"].pop("run_events_snapshot"),
            "http_endpoint_drift",
        ),
    ],
)
def test_local_agent_profile_reports_capability_drift_without_mutation(
    tmp_path: Path,
    mutate,
    expected_code: str,
) -> None:
    from hqa.hermes_compatibility import check_compatibility

    with _probe_server() as base_url:
        config = _local_agent_config(tmp_path, base_url)
        capabilities = json.loads(
            json.dumps(_ProbeHandler.responses["/v1/capabilities"])
        )
        mutate(capabilities)
        _ProbeHandler.responses["/v1/capabilities"] = capabilities
        result = check_compatibility(config)

    assert result.status == "incompatible"
    assert result.report_path is not None
    report = result.report_path.read_text(encoding="utf-8")
    assert f"hermes_capabilities:{expected_code}" in report
    assert all(method == "GET" for method, _path, _headers in _ProbeHandler.requests)


@pytest.mark.parametrize(
    "manifest_change",
    [
        "missing",
        "unknown_version",
        "boolean_version",
        "extra",
        "duplicate",
        "oversized",
    ],
)
def test_local_agent_profile_fails_closed_on_platform_manifest_drift(
    tmp_path: Path,
    manifest_change: str,
) -> None:
    from hqa.hermes_compatibility import check_compatibility

    with _probe_server() as base_url:
        config = _local_agent_config(tmp_path, base_url)
        path = (
            config.platform_repo
            / "contracts"
            / "agent_v02_hermes_compatibility.v1.json"
        )
        if manifest_change == "missing":
            path.unlink()
        elif manifest_change == "duplicate":
            path.write_text(
                '{"schema_version":1,"schema_version":1}',
                encoding="utf-8",
            )
        elif manifest_change == "oversized":
            path.write_bytes(b" " * 65_537)
        else:
            document = json.loads(path.read_text(encoding="utf-8"))
            if manifest_change == "unknown_version":
                document["schema_version"] = 2
            elif manifest_change == "boolean_version":
                document["schema_version"] = True
            else:
                document["secret_provider_token"] = "must-not-leak"
            path.write_text(json.dumps(document), encoding="utf-8")
        result = check_compatibility(config)

    assert result.status == "incompatible"
    assert result.report_path is not None
    report = result.report_path.read_text(encoding="utf-8")
    assert "platform_contract_manifest" in report
    assert "must-not-leak" not in report


def test_profile_is_part_of_baseline_identity_and_forces_local_reprobe(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    from hqa.hermes_compatibility import check_compatibility

    with _probe_server() as base_url:
        dark = _config(tmp_path, base_url)
        dark_result = check_compatibility(dark)
        requests_before = len(_ProbeHandler.requests)
        local = _local_agent_config(tmp_path / "local", base_url)
        # Keep the same state directory deliberately: a dark baseline must not
        # suppress the stronger local Agent v0.2 probe.
        local = replace(local, state_dir=dark.state_dir)
        local_result = check_compatibility(local)

    assert dark_result.status == "compatible"
    assert local_result.status == "compatible"
    assert local_result.probed is True
    assert local_result.trigger_digest != dark_result.trigger_digest
    assert len(_ProbeHandler.requests) == requests_before + 5


def test_first_check_runs_only_fixed_get_probes_and_establishes_baseline(
    tmp_path: Path,
) -> None:
    from hqa.hermes_compatibility import check_compatibility

    with _probe_server() as base_url:
        config = _config(tmp_path, base_url)
        result = check_compatibility(config)

    assert result.status == "compatible"
    assert result.probed is True
    assert [(method, path) for method, path, _headers in _ProbeHandler.requests] == [
        ("GET", "/health"),
        ("GET", "/api/health"),
        ("GET", "/api/hermes/gateway"),
        ("GET", "/api/hermes/sessions?limit=1&offset=0"),
    ]
    assert all(
        "authorization" not in headers
        for _method, _path, headers in _ProbeHandler.requests
    )
    assert result.report_path is not None
    assert result.report_path.is_file()
    assert (config.state_dir / "baseline.json").is_file()
    assert os.stat(config.state_dir).st_mode & 0o777 == 0o700
    assert os.stat(result.report_path).st_mode & 0o777 == 0o600
    report = result.report_path.read_text(encoding="utf-8")
    assert "sensitive-session-id" not in report
    assert "sensitive title" not in report
    assert "sensitive message" not in report


def test_cli_is_silent_and_makes_zero_http_requests_for_unchanged_success(
    tmp_path: Path,
) -> None:
    with _probe_server() as base_url:
        config = _config(tmp_path, base_url)
        env = dict(
            os.environ,
            HQA_HERMES_COMPAT_HQA_REPO=str(config.hqa_repo),
            HQA_HERMES_COMPAT_PLATFORM_REPO=str(config.platform_repo),
            HQA_HERMES_COMPAT_HERMES_REPO=str(config.hermes_repo),
            HQA_HERMES_COMPAT_STATE_DIR=str(config.state_dir),
            HQA_HERMES_COMPAT_HERMES_URL=base_url,
            HQA_HERMES_COMPAT_PLATFORM_URL=base_url,
            HQA_HERMES_COMPAT_HERMES_CLI=str(config.hermes_cli_path),
        )
        first = subprocess.run(
            [
                str(Path(os.sys.executable)),
                "-m",
                "hqa.hermes_compatibility_cli",
                "check",
            ],
            cwd=Path(__file__).resolve().parent.parent,
            env=env,
            capture_output=True,
            text=True,
        )
        first_request_count = len(_ProbeHandler.requests)
        service_calls_after_first = Path(f"{config.hermes_cli_path}.calls").read_text(
            encoding="utf-8"
        )
        second = subprocess.run(
            [
                str(Path(os.sys.executable)),
                "-m",
                "hqa.hermes_compatibility_cli",
                "check",
            ],
            cwd=Path(__file__).resolve().parent.parent,
            env=env,
            capture_output=True,
            text=True,
        )

    assert first.returncode == 0, first.stderr
    summary = json.loads(first.stdout)
    assert set(summary) == {
        "trigger_digest",
        "report_digest",
        "status",
    }
    assert summary["status"] == "compatible"
    assert "sensitive" not in first.stdout.lower()
    assert first_request_count == 4
    assert service_calls_after_first == "x"
    assert second.returncode == 0, second.stderr
    assert second.stdout == ""
    assert second.stderr == ""
    assert len(_ProbeHandler.requests) == first_request_count
    assert Path(f"{config.hermes_cli_path}.calls").read_text(encoding="utf-8") == "x"


def test_failed_changed_identity_keeps_last_compatible_baseline_and_retries(
    tmp_path: Path,
) -> None:
    from hqa.hermes_compatibility import (
        HQA_REPROBE_TRIGGER_FILES,
        check_compatibility,
    )

    with _probe_server() as base_url:
        config = _config(tmp_path, base_url)
        accepted = check_compatibility(config)
        baseline_before = (config.state_dir / "baseline.json").read_bytes()

        changed_contract = config.hqa_repo / HQA_REPROBE_TRIGGER_FILES[0]
        changed_contract.write_text("changed contract\n", encoding="utf-8")
        health = dict(_ProbeHandler.responses["/api/health"])
        health["database"] = {
            "enabled": True,
            "reachable": False,
            "error": "connection failed with sensitive host details",
        }
        health["safety"] = dict(health["safety"], kill_switch=False)
        _ProbeHandler.responses["/api/health"] = health

        failed_once = check_compatibility(config)
        requests_after_first_failure = len(_ProbeHandler.requests)
        failed_twice = check_compatibility(config)

    assert accepted.status == "compatible"
    assert failed_once.status == "incompatible"
    assert failed_once.probed is True
    assert failed_twice.status == "incompatible"
    assert failed_twice.probed is True
    assert len(_ProbeHandler.requests) == requests_after_first_failure + 4
    assert (config.state_dir / "baseline.json").read_bytes() == baseline_before
    assert failed_once.report_path is not None
    report = failed_once.report_path.read_text(encoding="utf-8")
    assert "sensitive host details" not in report
    assert "platform_health:safety_kill_switch_drift" in report


def test_manual_hermes_checkout_update_triggers_probe_without_custom_stamp(
    tmp_path: Path,
) -> None:
    from hqa.hermes_compatibility import check_compatibility

    with _probe_server() as base_url:
        config = _config(tmp_path, base_url)
        before = check_compatibility(config)
        (config.hermes_repo / "source.py").write_text("VERSION = 2\n", encoding="utf-8")
        _git(config.hermes_repo, "add", "source.py")
        _git(config.hermes_repo, "commit", "-q", "-m", "manual update")
        requests_before = len(_ProbeHandler.requests)

        after = check_compatibility(config)

    assert before.status == "compatible"
    assert after.status == "compatible"
    assert after.probed is True
    assert after.trigger_digest != before.trigger_digest
    assert len(_ProbeHandler.requests) == requests_before + 4
    baseline = json.loads((config.state_dir / "baseline.json").read_text())
    assert baseline["trigger_digest"] == after.trigger_digest


def test_gateway_write_readiness_drift_fails_closed_without_leaking_payload(
    tmp_path: Path,
) -> None:
    from hqa.hermes_compatibility import check_compatibility

    with _probe_server() as base_url:
        config = _config(tmp_path, base_url)
        gateway = dict(_ProbeHandler.responses["/api/hermes/gateway"])
        gateway["chat_write_ready"] = True
        gateway["model"] = "secret-provider-model"
        _ProbeHandler.responses["/api/hermes/gateway"] = gateway

        result = check_compatibility(config)

    assert result.status == "incompatible"
    assert not (config.state_dir / "baseline.json").exists()
    assert result.report_path is not None
    report = result.report_path.read_text(encoding="utf-8")
    assert "platform_gateway:platform_gateway_contract_drift" in report
    assert "secret-provider-model" not in report


def test_report_is_canonical_content_addressed_evidence(tmp_path: Path) -> None:
    from hqa.hermes_compatibility import check_compatibility

    with _probe_server() as base_url:
        result = check_compatibility(_config(tmp_path, base_url))

    assert result.report_path is not None
    raw = result.report_path.read_bytes()
    document = json.loads(raw)
    digest = document.pop("report_digest")
    canonical_basis = json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    assert hashlib.sha256(canonical_basis).hexdigest() == digest
    document["report_digest"] = digest
    assert raw == json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    assert result.report_path.name == f"{digest}.json"


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:8642",
        "http://localhost:8642",
        "http://192.0.2.1:8642",
        "http://user:password@127.0.0.1:8642",
        "http://127.0.0.1:8642/health",
    ],
)
def test_config_refuses_any_non_origin_or_non_numeric_loopback_url(
    tmp_path: Path, url: str
) -> None:
    with _probe_server() as base_url:
        config = _config(tmp_path, base_url)
        with pytest.raises(ValueError, match="loopback"):
            replace(config, hermes_base_url=url)


def test_http_ignores_environment_proxies_and_refuses_redirects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hqa.hermes_compatibility import check_compatibility

    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1")
    with _probe_server() as base_url:
        config = _config(tmp_path, base_url)
        success = check_compatibility(config)
        assert success.status == "compatible"

    with _probe_server() as base_url:
        config = _config(tmp_path / "redirect", base_url)
        _ProbeHandler.responses["/health"] = (
            302,
            {"Location": f"{base_url}/api/health", "Content-Type": "application/json"},
            b"{}",
        )
        redirected = check_compatibility(config)

    assert redirected.status == "incompatible"
    assert redirected.report_path is not None
    assert "hermes_health:redirect_refused" in redirected.report_path.read_text()
    # /api/health appears once as the intended platform probe, never a second
    # time as a followed Hermes redirect.
    assert [path for _method, path, _headers in _ProbeHandler.requests].count(
        "/api/health"
    ) == 1


def test_oversized_response_fails_closed_without_recording_body(tmp_path: Path) -> None:
    from hqa.hermes_compatibility import check_compatibility

    with _probe_server() as base_url:
        config = _config(tmp_path, base_url)
        secret = b"secret-response-body"
        _ProbeHandler.responses["/health"] = (
            200,
            {"Content-Type": "application/json"},
            b'{"padding":"' + b"x" * config.max_response_bytes + secret + b'"}',
        )
        result = check_compatibility(config)

    assert result.status == "incompatible"
    assert result.report_path is not None
    report = result.report_path.read_bytes()
    assert b"hermes_health:response_too_large" in report
    assert secret not in report


def test_stale_gateway_service_definition_is_local_readonly_drift(
    tmp_path: Path,
) -> None:
    from hqa.hermes_compatibility import check_compatibility

    with _probe_server() as base_url:
        config = _config(tmp_path, base_url)
        args_log = tmp_path / "gateway-status-args.txt"
        fake_hermes = tmp_path / "fake-hermes"
        fake_hermes.write_text(
            "#!/bin/bash\n"
            f"printf '%s' \"$*\" > {args_log}\n"
            "printf '%s\\n' 'Service definition is stale relative to the current Hermes install'\n"
            "printf '%s\\n' 'Gateway is supervised by launchd (PID 123)'\n",
            encoding="utf-8",
        )
        fake_hermes.chmod(0o755)
        config = replace(config, hermes_cli_path=fake_hermes)

        result = check_compatibility(config)

    assert args_log.read_text(encoding="utf-8") == "gateway status"
    assert result.status == "incompatible"
    assert result.report_path is not None
    report = result.report_path.read_text(encoding="utf-8")
    assert "gateway_service_definition_stale" in report
    assert "PID 123" not in report
    assert "gateway start" not in report


def test_reconciled_gateway_establishes_baseline_without_editing_identity_json(
    tmp_path: Path,
) -> None:
    from hqa.hermes_compatibility import check_compatibility

    with _probe_server() as base_url:
        config = _config(tmp_path, base_url)
        config.hermes_cli_path.write_text(
            "#!/bin/bash\n"
            "printf '%s\\n' 'Service definition is stale relative to the current Hermes install'\n"
            "printf '%s\\n' 'Gateway is supervised by launchd (PID 123)'\n",
            encoding="utf-8",
        )
        config.hermes_cli_path.chmod(0o755)
        failed = check_compatibility(config)
        assert not (config.state_dir / "baseline.json").exists()

        config.hermes_cli_path.write_text(
            "#!/bin/bash\n"
            "printf '%s\\n' 'Service definition matches the current Hermes install'\n"
            "printf '%s\\n' 'Gateway is supervised by launchd (PID 456)'\n",
            encoding="utf-8",
        )
        config.hermes_cli_path.chmod(0o755)
        recovered = check_compatibility(config)

    assert failed.status == "incompatible"
    assert recovered.status == "compatible"
    assert recovered.probed is True
    assert (config.state_dir / "baseline.json").is_file()


def test_missing_content_addressed_baseline_report_forces_revalidation(
    tmp_path: Path,
) -> None:
    from hqa.hermes_compatibility import check_compatibility

    with _probe_server() as base_url:
        config = _config(tmp_path, base_url)
        accepted = check_compatibility(config)
        assert accepted.report_path is not None
        accepted.report_path.unlink()
        requests_before = len(_ProbeHandler.requests)

        revalidated = check_compatibility(config)

    assert revalidated.status == "compatible"
    assert revalidated.probed is True
    assert len(_ProbeHandler.requests) == requests_before + 4
    assert revalidated.report_path is not None
    assert revalidated.report_path.is_file()


def test_cli_rejects_unknown_arguments_without_echoing_them(capsys) -> None:
    from hqa.hermes_compatibility_cli import main

    secret_argument = "provider-secret-must-not-be-echoed"
    code = main([secret_argument])
    captured = capsys.readouterr()

    assert code == 2
    assert secret_argument not in captured.out
    assert secret_argument not in captured.err


def test_local_agent_capability_probe_uses_owner_only_api_key_without_leaking_it(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    from hqa.hermes_compatibility import check_compatibility

    with _probe_server() as base_url:
        config = _local_agent_config(tmp_path, base_url)
        key = tmp_path / "hermes-api.key"
        key.write_text("local-test-secret\n", encoding="utf-8")
        key.chmod(0o600)
        config = replace(config, hermes_api_key_file=key)
        result = check_compatibility(config)

    assert result.status == "compatible"
    capability_requests = [
        headers
        for method, path, headers in _ProbeHandler.requests
        if method == "GET" and path == "/v1/capabilities"
    ]
    assert len(capability_requests) == 1
    assert capability_requests[0]["authorization"] == "Bearer local-test-secret"
    assert result.report_path is not None
    assert "local-test-secret" not in result.report_path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "unsafe_key",
    ["relative", "group_readable", "symlink", "control_character"],
)
def test_local_agent_profile_refuses_unsafe_api_key_files(
    tmp_path: Path,
    unsafe_key: str,
) -> None:
    from hqa.hermes_compatibility import check_compatibility

    with _probe_server() as base_url:
        config = _local_agent_config(tmp_path, base_url)
        physical_key = tmp_path / "physical-hermes-api.key"
        physical_key.write_text("must-never-appear-in-evidence\n", encoding="utf-8")
        physical_key.chmod(0o600)
        if unsafe_key == "relative":
            configured_key = Path("physical-hermes-api.key")
        elif unsafe_key == "group_readable":
            physical_key.chmod(0o640)
            configured_key = physical_key
        elif unsafe_key == "symlink":
            configured_key = tmp_path / "linked-hermes-api.key"
            configured_key.symlink_to(physical_key)
        else:
            physical_key.write_text(
                "must-never-appear\tin-evidence\n",
                encoding="utf-8",
            )
            configured_key = physical_key
        result = check_compatibility(
            replace(config, hermes_api_key_file=configured_key)
        )

    assert result.status == "incompatible"
    assert result.report_path is not None
    report = result.report_path.read_text(encoding="utf-8")
    assert "hermes_api_key_" in report
    assert "must-never-appear" not in report


def test_no_agent_cli_profiles_and_exit_codes_are_explicit(tmp_path: Path) -> None:
    with _probe_server() as base_url:
        config = _local_agent_config(tmp_path, base_url)
        env = dict(
            os.environ,
            HQA_HERMES_COMPAT_HQA_REPO=str(config.hqa_repo),
            HQA_HERMES_COMPAT_HERMES_REPO=str(config.hermes_repo),
            HQA_HERMES_COMPAT_STATE_DIR=str(config.state_dir),
            HQA_HERMES_COMPAT_HERMES_URL=base_url,
            HQA_HERMES_COMPAT_PLATFORM_URL=base_url,
            HQA_HERMES_COMPAT_HERMES_CLI=str(config.hermes_cli_path),
        )
        command = [
            str(Path(os.sys.executable)),
            "-m",
            "hqa.hermes_compatibility_cli",
            "check",
            "--no-agent",
            "--profile",
            "local_agent_v0_2",
            "--platform-root",
            str(config.platform_repo),
        ]
        compatible = subprocess.run(
            command,
            cwd=Path(__file__).resolve().parent.parent,
            env=env,
            capture_output=True,
            text=True,
        )

        drift_state = tmp_path / "drift-state"
        env["HQA_HERMES_COMPAT_STATE_DIR"] = str(drift_state)
        capabilities = json.loads(
            json.dumps(_ProbeHandler.responses["/v1/capabilities"])
        )
        capabilities["durable"]["approval_cas"]["grounded"] = False
        _ProbeHandler.responses["/v1/capabilities"] = capabilities
        drifted = subprocess.run(
            command,
            cwd=Path(__file__).resolve().parent.parent,
            env=env,
            capture_output=True,
            text=True,
        )
        usage = subprocess.run(
            command[:-2],
            cwd=Path(__file__).resolve().parent.parent,
            env=env,
            capture_output=True,
            text=True,
        )

    assert compatible.returncode == 0
    assert json.loads(compatible.stdout)["status"] == "compatible"
    assert drifted.returncode == 3
    assert json.loads(drifted.stdout)["status"] == "incompatible"
    assert usage.returncode == 2
    assert "usage" in usage.stderr.lower()


def test_process_lock_makes_overlapping_cron_check_a_silent_noop(
    tmp_path: Path,
) -> None:
    with _probe_server() as base_url:
        config = _config(tmp_path, base_url)
        config.state_dir.mkdir(mode=0o700)
        lock_path = config.state_dir / "watch.lock"
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            env = dict(
                os.environ,
                HQA_HERMES_COMPAT_HQA_REPO=str(config.hqa_repo),
                HQA_HERMES_COMPAT_PLATFORM_REPO=str(config.platform_repo),
                HQA_HERMES_COMPAT_HERMES_REPO=str(config.hermes_repo),
                HQA_HERMES_COMPAT_STATE_DIR=str(config.state_dir),
                HQA_HERMES_COMPAT_HERMES_URL=base_url,
                HQA_HERMES_COMPAT_PLATFORM_URL=base_url,
                HQA_HERMES_COMPAT_HERMES_CLI=str(config.hermes_cli_path),
            )
            result = subprocess.run(
                [
                    str(Path(os.sys.executable)),
                    "-m",
                    "hqa.hermes_compatibility_cli",
                    "check",
                ],
                cwd=Path(__file__).resolve().parent.parent,
                env=env,
                capture_output=True,
                text=True,
            )
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
    assert _ProbeHandler.requests == []


def test_state_directory_symlink_is_refused_before_any_probe(tmp_path: Path) -> None:
    from hqa.hermes_compatibility import CompatibilityError, check_compatibility

    with _probe_server() as base_url:
        config = _config(tmp_path, base_url)
        target = tmp_path / "outside-state"
        target.mkdir()
        config.state_dir.symlink_to(target, target_is_directory=True)

        with pytest.raises(CompatibilityError, match="physical directory"):
            check_compatibility(config)

    assert _ProbeHandler.requests == []
    assert list(target.iterdir()) == []


def test_nested_health_schema_rejects_unexpected_secret_fields(tmp_path: Path) -> None:
    from hqa.hermes_compatibility import check_compatibility

    with _probe_server() as base_url:
        config = _config(tmp_path, base_url)
        health = dict(_ProbeHandler.responses["/api/health"])
        health["data_provider"] = {
            "configured_default": "futu",
            "tiingo_token_present": False,
            "api_token": "secret-health-token",
        }
        _ProbeHandler.responses["/api/health"] = health

        result = check_compatibility(config)

    assert result.status == "incompatible"
    assert result.report_path is not None
    report = result.report_path.read_text(encoding="utf-8")
    assert "platform_health:platform_health_schema" in report
    assert "secret-health-token" not in report


def test_custom_install_stamp_is_not_required_for_read_compatibility(
    tmp_path: Path,
) -> None:
    from hqa.hermes_compatibility import CompatibilityConfig, check_compatibility

    with _probe_server() as base_url:
        old_config = _config(tmp_path, base_url)
        config = CompatibilityConfig(
            hqa_repo=old_config.hqa_repo,
            platform_repo=old_config.platform_repo,
            hermes_repo=old_config.hermes_repo,
            state_dir=old_config.state_dir,
            hermes_base_url=base_url,
            platform_base_url=base_url,
            hermes_cli_path=old_config.hermes_cli_path,
            timeout_seconds=1.0,
        )

        result = check_compatibility(config)

    assert result.status == "compatible"
    assert result.probed is True
    assert result.report_path is not None
    report = result.report_path.read_text(encoding="utf-8")
    assert "install_stamp" not in report
    assert "installed_source_commit" not in report
    assert "runtime_attestation" not in report


def test_watcher_contract_change_is_a_reprobe_trigger_not_runtime_attestation(
    tmp_path: Path,
) -> None:
    from hqa.hermes_compatibility import (
        WATCHER_CONTRACT_FILES,
        check_compatibility,
    )

    with _probe_server() as base_url:
        config = _config(tmp_path, base_url)
        accepted = check_compatibility(config)
        assert accepted.report_path is not None
        first_report = json.loads(accepted.report_path.read_text(encoding="utf-8"))
        watcher_contract = config.hqa_repo / WATCHER_CONTRACT_FILES[0]
        watcher_contract.write_text("watcher contract v2\n", encoding="utf-8")
        requests_before = len(_ProbeHandler.requests)

        reprobed = check_compatibility(config)

    assert set(first_report["reprobe_identity"]) == {
        "schema_version",
        "profile",
        "hermes",
        "reprobe_triggers",
    }
    assert first_report["reprobe_identity"]["profile"] == "dark_readonly"
    assert set(first_report["reprobe_identity"]["reprobe_triggers"]) == {
        "hqa_trigger_digest",
        "platform_trigger_digest",
        "watcher_contract_digest",
    }
    assert "contracts" not in first_report["reprobe_identity"]
    assert "runtime_attestation" not in first_report
    assert reprobed.status == "compatible"
    assert reprobed.probed is True
    assert len(_ProbeHandler.requests) == requests_before + 4


def test_report_retention_is_bounded_and_preserves_baseline_and_unsafe_entries(
    tmp_path: Path,
) -> None:
    from hqa.hermes_compatibility import (
        HQA_REPROBE_TRIGGER_FILES,
        check_compatibility,
    )

    with _probe_server() as base_url:
        config = _config(tmp_path, base_url)
        accepted = check_compatibility(config)
        assert accepted.report_path is not None
        baseline_report = accepted.report_path
        reports_dir = baseline_report.parent
        os.utime(baseline_report, ns=(1, 1))

        for index in range(132):
            digest = hashlib.sha256(f"old-report-{index}".encode()).hexdigest()
            path = reports_dir / f"{digest}.json"
            path.write_text("{}", encoding="utf-8")
            path.chmod(0o600)
            os.utime(path, ns=(index + 100, index + 100))

        outside = tmp_path / "outside-report.json"
        outside.write_text("must survive\n", encoding="utf-8")
        symlink_name = f"{hashlib.sha256(b'symlink').hexdigest()}.json"
        symlink = reports_dir / symlink_name
        symlink.symlink_to(outside)
        noncanonical = reports_dir / "operator-note.json"
        noncanonical.write_text("must survive\n", encoding="utf-8")

        changed = config.hqa_repo / HQA_REPROBE_TRIGGER_FILES[0]
        changed.write_text("changed trigger\n", encoding="utf-8")
        health = dict(_ProbeHandler.responses["/api/health"])
        health["safety"] = dict(health["safety"], kill_switch=False)
        _ProbeHandler.responses["/api/health"] = health
        failed = check_compatibility(config)

    canonical_regular = []
    for path in reports_dir.iterdir():
        if re.fullmatch(r"[0-9a-f]{64}\.json", path.name) and not path.is_symlink():
            canonical_regular.append(path)
    assert failed.status == "incompatible"
    assert len(canonical_regular) == 128
    assert baseline_report.is_file()
    assert symlink.is_symlink()
    assert outside.read_text(encoding="utf-8") == "must survive\n"
    assert noncanonical.read_text(encoding="utf-8") == "must survive\n"

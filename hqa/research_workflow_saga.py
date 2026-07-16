"""Crash-safe coordination between the HQA workflow and platform authorities.

The HQA file ledger owns Task/Attempt/plan and the content-addressed payload.
PostgreSQL owns the transport command, event, outbox, lease and exact Run link.
This module deliberately adds no third journal: progress is reconstructed from
those two canonical authorities after every failure.

No prompt or provider credential crosses the platform adapter.  The subprocess
port receives only the immutable metadata receipt produced by HQA.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import selectors
import signal
import stat
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from hqa.research_workflows import (
    ResearchWorkflowError,
    ResearchWorkflowStore,
    as_platform_prepared_command,
    transport_binding_digest,
)


_MAX_PLATFORM_OUTPUT_BYTES = 64 * 1024
_MAX_PLATFORM_INPUT_BYTES = 16 * 1024
_MAX_PLATFORM_INVENTORY_OUTPUT_BYTES = 16 * 1024 * 1024
_MAX_PLATFORM_INVENTORY_LINE_BYTES = 64 * 1024
_PLATFORM_ENSURE_ARGV = ("hermes", "workflow-binding", "ensure")
_PLATFORM_SHOW_ARGV = ("hermes", "workflow-binding", "show")
_PLATFORM_INVENTORY_ARGV = ("hermes", "workflow-binding", "inventory")
_SAGA_ID_RE = re.compile(r"^hqs_[0-9a-f]{24}$")
_SAFE_BASE_ENV = frozenset(
    {
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TMPDIR",
        "TZ",
    }
)
_DATABASE_ENV = frozenset(
    {
        "QS_DATABASE_CONNECT_TIMEOUT_SECONDS",
        "QS_DATABASE_ENABLED",
        "QS_DATABASE_URL",
    }
)

_AUDIT_RECEIPT_FIELDS = (
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
)


class _PlatformOutputLimitExceeded(RuntimeError):
    pass


class _PlatformChildExecutionFailed(RuntimeError):
    """A child started, but its local supervision failed before completion."""


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    # A short-lived leader can exit after spawning a descendant that inherited
    # stdout/stderr.  The descendant still belongs to the session/process group
    # created for the leader, so cleanup must target the group even when the
    # leader has already been reaped.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError:
        if process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass
    try:
        process.wait(timeout=1)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _run_bounded_command(
    argv: list[str],
    *,
    stdin_bytes: bytes | None,
    timeout_seconds: float,
    cwd: str,
    env: dict[str, str],
) -> tuple[int, bytes, bytes]:
    """Run one child while bounding both output streams before buffering."""

    process = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE if stdin_bytes is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        close_fds=True,
        cwd=cwd,
        env=env,
        start_new_session=True,
    )
    selector: selectors.BaseSelector | None = None
    outputs = {"stdout": bytearray(), "stderr": bytearray()}
    input_view = memoryview(stdin_bytes or b"")

    def register(stream: Any, events: int, label: str) -> None:
        assert selector is not None
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, events, label)

    def close_stream(stream: Any) -> None:
        if selector is not None:
            try:
                selector.unregister(stream)
            except (KeyError, OSError, ValueError):
                pass
        try:
            stream.close()
        except (OSError, ValueError):
            pass

    try:
        if process.stdout is None or process.stderr is None:
            raise OSError("child output pipes are unavailable")
        selector = selectors.DefaultSelector()
        register(process.stdout, selectors.EVENT_READ, "stdout")
        register(process.stderr, selectors.EVENT_READ, "stderr")
        if process.stdin is not None:
            if input_view:
                register(process.stdin, selectors.EVENT_WRITE, "stdin")
            else:
                process.stdin.close()

        deadline = time.monotonic() + timeout_seconds
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(argv, timeout_seconds)
            ready = selector.select(remaining)
            if not ready:
                raise subprocess.TimeoutExpired(argv, timeout_seconds)
            for key, _ in ready:
                stream = key.fileobj
                label = key.data
                if label == "stdin":
                    try:
                        written = os.write(stream.fileno(), input_view[:65_536])
                    except (BrokenPipeError, OSError):
                        close_stream(stream)
                        continue
                    input_view = input_view[written:]
                    if not input_view:
                        close_stream(stream)
                    continue
                buffer = outputs[label]
                try:
                    chunk = os.read(
                        stream.fileno(),
                        min(65_536, _MAX_PLATFORM_OUTPUT_BYTES + 1 - len(buffer)),
                    )
                except BlockingIOError:
                    continue
                if not chunk:
                    close_stream(stream)
                    continue
                buffer.extend(chunk)
                if len(buffer) > _MAX_PLATFORM_OUTPUT_BYTES:
                    raise _PlatformOutputLimitExceeded()
            if (
                process.poll() is not None
                and process.stdin is not None
                and not process.stdin.closed
            ):
                close_stream(process.stdin)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(argv, timeout_seconds)
        return_code = process.wait(timeout=remaining)
        return return_code, bytes(outputs["stdout"]), bytes(outputs["stderr"])
    except (subprocess.TimeoutExpired, _PlatformOutputLimitExceeded):
        _terminate_process_group(process)
        raise
    except Exception as exc:
        _terminate_process_group(process)
        raise _PlatformChildExecutionFailed() from exc
    finally:
        if selector is not None:
            for key in list(selector.get_map().values()):
                close_stream(key.fileobj)
            try:
                selector.close()
            except (OSError, ValueError):
                pass
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                try:
                    stream.close()
                except (OSError, ValueError):
                    pass


class PlatformBindingUnavailable(RuntimeError):
    """The platform authority could not be read with a determinate outcome."""

    def __init__(self) -> None:
        super().__init__("platform workflow binding authority is unavailable")


class PlatformBindingOutcomeUnknown(RuntimeError):
    """The ensure process timed out after its PostgreSQL outcome became unknown."""

    def __init__(self) -> None:
        super().__init__("platform workflow binding outcome is unknown")


class PlatformBindingConflict(RuntimeError):
    """The same idempotency identity belongs to different exact facts."""

    def __init__(self) -> None:
        super().__init__("platform workflow binding conflicts with durable facts")


class PlatformBindingRejected(RuntimeError):
    """The platform rejected a malformed or expired immutable receipt."""

    def __init__(self) -> None:
        super().__init__("platform workflow binding receipt was rejected")


class PlatformWorkflowBindingPort(Protocol):
    def ensure(self, prepared: dict[str, Any]) -> dict[str, Any]: ...

    def show(self, workflow_saga_id: str) -> dict[str, Any] | None: ...

    def inventory(self) -> list[dict[str, Any]]: ...


def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-finite JSON output")


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON output field")
        result[key] = value
    return result


def _strict_json_document(raw: str) -> dict[str, Any]:
    try:
        encoded = raw.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise PlatformBindingUnavailable() from exc
    if not encoded or len(encoded) > _MAX_PLATFORM_OUTPUT_BYTES:
        raise PlatformBindingUnavailable()
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, TypeError, ValueError, RecursionError) as exc:
        raise PlatformBindingUnavailable() from exc
    if not isinstance(value, dict):
        raise PlatformBindingUnavailable()
    return value


def _run_bounded_inventory_command(
    argv: list[str],
    *,
    timeout_seconds: float,
    cwd: str,
    env: dict[str, str],
) -> tuple[int, bytes, bytes]:
    """Run the read-only inventory port with independent stream bounds."""

    process = subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        close_fds=True,
        cwd=cwd,
        env=env,
        start_new_session=True,
    )
    selector: selectors.BaseSelector | None = None
    outputs = {"stdout": bytearray(), "stderr": bytearray()}
    current_line_bytes = 0

    def close_stream(stream: Any) -> None:
        if selector is not None:
            try:
                selector.unregister(stream)
            except (KeyError, OSError, ValueError):
                pass
        try:
            stream.close()
        except (OSError, ValueError):
            pass

    try:
        if process.stdout is None or process.stderr is None:
            raise OSError("child output pipes are unavailable")
        selector = selectors.DefaultSelector()
        for stream, label in (
            (process.stdout, "stdout"),
            (process.stderr, "stderr"),
        ):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, label)
        deadline = time.monotonic() + timeout_seconds
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(argv, timeout_seconds)
            ready = selector.select(remaining)
            if not ready:
                raise subprocess.TimeoutExpired(argv, timeout_seconds)
            for key, _ in ready:
                stream = key.fileobj
                label = key.data
                limit = (
                    _MAX_PLATFORM_INVENTORY_OUTPUT_BYTES
                    if label == "stdout"
                    else _MAX_PLATFORM_OUTPUT_BYTES
                )
                buffer = outputs[label]
                try:
                    chunk = os.read(
                        stream.fileno(), min(65_536, limit + 1 - len(buffer))
                    )
                except BlockingIOError:
                    continue
                if not chunk:
                    close_stream(stream)
                    continue
                buffer.extend(chunk)
                if len(buffer) > limit:
                    raise _PlatformOutputLimitExceeded()
                if label == "stdout":
                    for byte in chunk:
                        if byte == 0x0A:
                            if current_line_bytes > _MAX_PLATFORM_INVENTORY_LINE_BYTES:
                                raise _PlatformOutputLimitExceeded()
                            current_line_bytes = 0
                        else:
                            current_line_bytes += 1
                            if current_line_bytes > _MAX_PLATFORM_INVENTORY_LINE_BYTES:
                                raise _PlatformOutputLimitExceeded()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(argv, timeout_seconds)
        return_code = process.wait(timeout=remaining)
        return return_code, bytes(outputs["stdout"]), bytes(outputs["stderr"])
    except (subprocess.TimeoutExpired, _PlatformOutputLimitExceeded):
        _terminate_process_group(process)
        raise
    except Exception as exc:
        _terminate_process_group(process)
        raise _PlatformChildExecutionFailed() from exc
    finally:
        if selector is not None:
            for key in list(selector.get_map().values()):
                close_stream(key.fileobj)
            try:
                selector.close()
            except (OSError, ValueError):
                pass
        for stream in (process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                close_stream(stream)


def _strict_inventory_line(raw: bytes) -> dict[str, Any]:
    if not raw or len(raw) > _MAX_PLATFORM_INVENTORY_LINE_BYTES:
        raise PlatformBindingUnavailable()
    try:
        text = raw.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise PlatformBindingUnavailable() from exc
    if not isinstance(value, dict):
        raise PlatformBindingUnavailable()
    return value


def _inventory_preparation(binding: dict[str, Any]) -> dict[str, Any]:
    try:
        prepared = {
            "schema_version": binding["preparation_schema_version"],
            "workflow_saga_id": binding["workflow_saga_id"],
            "owner_user_id": binding["owner_user_id"],
            "platform_session_id": binding["platform_session_id"],
            "client_request_id": binding["client_request_id"],
            "command_kind": binding["command_kind"],
            "canonical_request_digest": binding["canonical_request_digest"],
            "payload_ref": binding["payload_ref"],
            "payload_digest": binding["payload_digest"],
            "payload_expires_at": binding["payload_expires_at"],
            "provider_policy_digest": binding["provider_policy_digest"],
            "task_id": binding["task_id"],
            "task_version": binding["task_version"],
            "attempt_id": binding["attempt_id"],
            "attempt_number": binding["attempt_number"],
            "prepared_event_id": binding["prepared_event_id"],
            "prepared_event_digest": binding["prepared_event_digest"],
            "plan_schema_version": binding["plan_schema_version"],
            "plan_version": binding["plan_version"],
            "plan_digest": binding["plan_digest"],
            "workflow_preparation_digest": binding[
                "workflow_preparation_digest"
            ],
        }
    except (KeyError, TypeError) as exc:
        raise PlatformBindingUnavailable() from exc
    try:
        return as_platform_prepared_command(prepared)
    except ResearchWorkflowError as exc:
        raise PlatformBindingUnavailable() from exc


def _parse_inventory_ndjson(raw: bytes) -> list[dict[str, Any]]:
    if (
        not raw
        or len(raw) > _MAX_PLATFORM_INVENTORY_OUTPUT_BYTES
        or not raw.endswith(b"\n")
    ):
        raise PlatformBindingUnavailable()
    raw_lines = raw[:-1].split(b"\n")
    if len(raw_lines) < 2 or any(not line for line in raw_lines):
        raise PlatformBindingUnavailable()
    lines = [_strict_inventory_line(line) for line in raw_lines]
    header = lines[0]
    if header != {
        "schema_version": "1.0",
        "kind": "workflow_binding_inventory_header",
        "binding_schema_version": 1,
    } or type(header.get("binding_schema_version")) is not int:
        raise PlatformBindingUnavailable()
    trailer = lines[-1]
    if set(trailer) != {
        "schema_version",
        "kind",
        "count",
        "bindings_sha256",
    } or trailer.get("schema_version") != "1.0" or trailer.get(
        "kind"
    ) != "workflow_binding_inventory_trailer":
        raise PlatformBindingUnavailable()
    item_lines = lines[1:-1]
    if type(trailer.get("count")) is not int or trailer["count"] != len(item_lines):
        raise PlatformBindingUnavailable()
    expected_digest = hashlib.sha256()
    bindings: list[dict[str, Any]] = []
    seen_sagas: set[str] = set()
    seen_commands: set[str] = set()
    seen_tasks: set[str] = set()
    seen_identities: set[tuple[str, str, str, str]] = set()
    previous_order: tuple[str, str] | None = None
    for ordinal, line in enumerate(item_lines, start=1):
        if (
            set(line) != {"schema_version", "kind", "ordinal", "binding"}
            or line.get("schema_version") != "1.0"
            or line.get("kind") != "workflow_binding_inventory_item"
            or type(line.get("ordinal")) is not int
            or line["ordinal"] != ordinal
            or not isinstance(line.get("binding"), dict)
        ):
            raise PlatformBindingUnavailable()
        prepared = _inventory_preparation(line["binding"])
        try:
            binding = _verify_binding(prepared, line["binding"])
        except ResearchWorkflowError as exc:
            raise PlatformBindingUnavailable() from exc
        order = (binding["workflow_saga_id"], binding["command_id"])
        identity = (
            binding["owner_user_id"],
            binding["platform_session_id"],
            binding["client_request_id"],
            binding["command_kind"],
        )
        if (
            (previous_order is not None and order <= previous_order)
            or binding["workflow_saga_id"] in seen_sagas
            or binding["command_id"] in seen_commands
            or binding["task_id"] in seen_tasks
            or identity in seen_identities
        ):
            raise PlatformBindingUnavailable()
        previous_order = order
        seen_sagas.add(binding["workflow_saga_id"])
        seen_commands.add(binding["command_id"])
        seen_tasks.add(binding["task_id"])
        seen_identities.add(identity)
        canonical = json.dumps(
            binding,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8", errors="strict") + b"\n"
        expected_digest.update(canonical)
        bindings.append(binding)
    digest = trailer.get("bindings_sha256")
    if (
        not isinstance(digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        or digest != expected_digest.hexdigest()
    ):
        raise PlatformBindingUnavailable()
    return bindings


def _canonical_timestamp(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        return False
    return parsed.strftime("%Y-%m-%dT%H:%M:%S.%fZ") == value


def _canonical_uuid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value
    except (AttributeError, TypeError, ValueError):
        return False


def _binding_mismatch() -> ResearchWorkflowError:
    return ResearchWorkflowError(
        "workflow_binding_mismatch",
        "platform binding does not match the exact HQA preparation",
    )


def _verify_binding(
    prepared: dict[str, Any],
    document: dict[str, Any],
) -> dict[str, Any]:
    """Validate every immutable cross-authority fact before HQA observes it."""

    expected_fields = {
        "command_id",
        "command_version",
        "preparation_schema_version",
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
        "binding_schema_version",
        "binding_digest",
        "created_at",
    }
    if not isinstance(document, dict) or set(document) != expected_fields:
        raise _binding_mismatch()
    command_id = document.get("command_id")
    if not _canonical_uuid(command_id):
        raise _binding_mismatch()
    expected_pairs = {
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
    }
    integer_fact_fields = {
        "task_version",
        "attempt_number",
        "plan_schema_version",
        "plan_version",
    }
    if any(type(document.get(field)) is not int for field in integer_fact_fields):
        raise _binding_mismatch()
    if any(document.get(key) != value for key, value in expected_pairs.items()):
        raise _binding_mismatch()
    if (
        type(document.get("command_version")) is not int
        or document["command_version"] != 1
        or type(document.get("binding_schema_version")) is not int
        or document["binding_schema_version"] != 1
        or not _canonical_timestamp(document.get("created_at"))
        or document.get("binding_digest")
        != transport_binding_digest(prepared, str(command_id))
    ):
        raise _binding_mismatch()
    return dict(document)


def _binding_from_platform_document(
    prepared: dict[str, Any],
    response: dict[str, Any],
) -> dict[str, Any]:
    if set(response) == {"binding"}:
        return _verify_binding(prepared, response["binding"])
    if set(response) != {
        "binding",
        "command_id",
        "command_state",
        "command_version",
        "created",
    }:
        raise _binding_mismatch()
    binding = _verify_binding(prepared, response["binding"])
    if (
        response.get("command_id") != binding["command_id"]
        or type(response.get("command_version")) is not int
        or response["command_version"] < 1
        or not isinstance(response.get("command_state"), str)
        or not response["command_state"]
        or type(response.get("created")) is not bool
    ):
        raise _binding_mismatch()
    return binding


class SubprocessPlatformWorkflowBindingClient:
    """Fixed-argv JSON-stdin adapter to the platform's metadata-only CLI."""

    def __init__(self, *, executable: Path, timeout_seconds: float = 10.0) -> None:
        self.executable = Path(executable)
        if (
            not self.executable.is_absolute()
            or isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(float(timeout_seconds))
            or not 0 < float(timeout_seconds) <= 60.0
        ):
            raise ValueError("platform executable and timeout configuration are invalid")
        self.timeout_seconds = float(timeout_seconds)
        self._verify_executable()

    def _verify_executable(self) -> None:
        try:
            metadata = os.lstat(self.executable)
            resolved = self.executable.resolve(strict=True)
        except OSError as exc:
            raise PlatformBindingUnavailable() from exc
        if (
            resolved != self.executable
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
            or not os.access(self.executable, os.X_OK)
        ):
            raise PlatformBindingUnavailable()

    def _run(
        self,
        arguments: tuple[str, ...],
        *,
        stdin_document: dict[str, Any] | None = None,
        mutating: bool = False,
    ) -> tuple[int, dict[str, Any]]:
        self._verify_executable()
        stdin = (
            json.dumps(
                stdin_document,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            if stdin_document is not None
            else None
        )
        try:
            stdin_bytes = (
                stdin.encode("utf-8", errors="strict") if stdin is not None else None
            )
        except UnicodeEncodeError as exc:
            raise PlatformBindingRejected() from exc
        if stdin_bytes is not None and len(stdin_bytes) > _MAX_PLATFORM_INPUT_BYTES:
            raise PlatformBindingRejected()
        child_env = {
            key: value
            for key, value in os.environ.items()
            if key in _SAFE_BASE_ENV or key in _DATABASE_ENV
        }
        # This metadata-only path must never trigger schema mutation even when
        # the parent process was started with auto-migrate enabled.
        child_env["QS_DATABASE_AUTO_MIGRATE"] = "false"
        try:
            return_code, stdout, _stderr = _run_bounded_command(
                [str(self.executable), *arguments],
                stdin_bytes=stdin_bytes,
                timeout_seconds=self.timeout_seconds,
                cwd=str(self.executable.parent),
                env=child_env,
            )
        except (
            subprocess.TimeoutExpired,
            _PlatformOutputLimitExceeded,
            _PlatformChildExecutionFailed,
        ) as exc:
            if mutating:
                raise PlatformBindingOutcomeUnknown() from exc
            raise PlatformBindingUnavailable() from exc
        except (PlatformBindingOutcomeUnknown, PlatformBindingUnavailable):
            raise
        except (OSError, UnicodeError, ValueError) as exc:
            raise PlatformBindingUnavailable() from exc
        try:
            stdout_text = stdout.decode("utf-8", errors="strict")
            document = _strict_json_document(stdout_text)
        except (PlatformBindingUnavailable, UnicodeDecodeError) as exc:
            if mutating:
                raise PlatformBindingOutcomeUnknown() from exc
            raise PlatformBindingUnavailable() from exc
        return return_code, document

    @staticmethod
    def _raise_platform_error(document: dict[str, Any]) -> None:
        if set(document) != {"error_code"} or not isinstance(
            document["error_code"], str
        ):
            raise PlatformBindingUnavailable()
        code = document["error_code"]
        if code == "workflow_binding_conflict":
            raise PlatformBindingConflict()
        if code == "workflow_binding_validation_failed":
            raise PlatformBindingRejected()
        raise PlatformBindingUnavailable()

    def ensure(self, prepared: dict[str, Any]) -> dict[str, Any]:
        receipt = as_platform_prepared_command(prepared)
        return_code, document = self._run(
            _PLATFORM_ENSURE_ARGV,
            stdin_document=receipt,
            mutating=True,
        )
        if return_code != 0:
            self._raise_platform_error(document)
        return document

    def show(self, workflow_saga_id: str) -> dict[str, Any] | None:
        if not isinstance(workflow_saga_id, str) or _SAGA_ID_RE.fullmatch(
            workflow_saga_id
        ) is None:
            raise PlatformBindingRejected()
        return_code, document = self._run(
            (
                *_PLATFORM_SHOW_ARGV,
                "--workflow-saga-id",
                workflow_saga_id,
            )
        )
        if return_code == 0:
            return document
        if document == {"error_code": "workflow_binding_not_found"}:
            return None
        self._raise_platform_error(document)
        raise AssertionError("unreachable")

    def inventory(self) -> list[dict[str, Any]]:
        """Read one complete, checksummed platform binding snapshot."""

        self._verify_executable()
        child_env = {
            key: value
            for key, value in os.environ.items()
            if key in _SAFE_BASE_ENV or key in _DATABASE_ENV
        }
        child_env["QS_DATABASE_AUTO_MIGRATE"] = "false"
        try:
            return_code, stdout, _stderr = _run_bounded_inventory_command(
                [str(self.executable), *_PLATFORM_INVENTORY_ARGV],
                timeout_seconds=self.timeout_seconds,
                cwd=str(self.executable.parent),
                env=child_env,
            )
        except (
            subprocess.TimeoutExpired,
            _PlatformOutputLimitExceeded,
            _PlatformChildExecutionFailed,
            OSError,
            UnicodeError,
            ValueError,
        ) as exc:
            raise PlatformBindingUnavailable() from exc
        if return_code != 0:
            raise PlatformBindingUnavailable()
        return _parse_inventory_ndjson(stdout)


class ResearchWorkflowSaga:
    """Forward-only, exact-fact reconciliation across the two authorities."""

    def __init__(
        self,
        *,
        store: ResearchWorkflowStore,
        platform: PlatformWorkflowBindingPort,
    ) -> None:
        self.store = store
        self.platform = platform

    def submit(self, request: dict[str, Any]) -> dict[str, Any]:
        prepared = self.store.prepare(request)
        # Always reconcile from both authorities first.  In particular, an HQA
        # task that already observed a now-missing platform binding is data loss;
        # calling ensure first would incorrectly create a replacement command.
        return self.reconcile(prepared["task_id"])

    def audit_authorities(self) -> dict[str, Any]:
        """Compare stable metadata snapshots without mutating either authority."""

        for attempt in range(1, 4):
            before = self.store.inventory_tasks()
            platform_bindings = self.platform.inventory()
            after = self.store.inventory_tasks()
            if self._snapshot_fingerprint(before) == self._snapshot_fingerprint(
                after
            ):
                return self._authority_report(
                    after,
                    platform_bindings,
                    audit_attempts=attempt,
                )
        raise ResearchWorkflowError(
            "workflow_authority_audit_busy",
            "workflow authorities changed during the bounded audit",
            retryable=True,
        )

    @staticmethod
    def _snapshot_fingerprint(snapshot: dict[str, Any]) -> tuple[Any, ...]:
        return (
            snapshot.get("authority_state"),
            snapshot.get("last_sequence"),
            snapshot.get("last_record_sha256"),
        )

    @staticmethod
    def _task_preparation(task: dict[str, Any]) -> dict[str, Any]:
        try:
            prepared = {field: task[field] for field in _AUDIT_RECEIPT_FIELDS}
            return as_platform_prepared_command(prepared)
        except (KeyError, TypeError, ResearchWorkflowError) as exc:
            raise ResearchWorkflowError(
                "workflow_ledger_corrupt",
                "workflow authority inventory contains invalid preparation facts",
            ) from exc

    @staticmethod
    def _evidence(
        status: str,
        *,
        task: dict[str, Any] | None = None,
        binding: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        document: dict[str, Any] = {"status": status}
        source = task if task is not None else binding
        if source is not None:
            document.update(
                {
                    "workflow_saga_id": source["workflow_saga_id"],
                    "task_id": source["task_id"],
                    "attempt_id": source["attempt_id"],
                    "workflow_preparation_digest": source[
                        "workflow_preparation_digest"
                    ],
                }
            )
        if binding is not None:
            document.update(
                {
                    "command_id": binding["command_id"],
                    "binding_digest": binding["binding_digest"],
                }
            )
        elif task is not None and task.get("transport_binding") is not None:
            observed = task["transport_binding"]
            document.update(
                {
                    "command_id": observed["command_id"],
                    "binding_digest": observed["binding_digest"],
                }
            )
        return document

    @staticmethod
    def _conflict_evidence(
        task: dict[str, Any],
        binding: dict[str, Any],
    ) -> dict[str, Any]:
        document: dict[str, Any] = {
            "status": "exact_fact_conflict",
            "hqa_workflow_saga_id": task["workflow_saga_id"],
            "hqa_task_id": task["task_id"],
            "hqa_attempt_id": task["attempt_id"],
            "hqa_workflow_preparation_digest": task[
                "workflow_preparation_digest"
            ],
            "platform_workflow_saga_id": binding["workflow_saga_id"],
            "platform_task_id": binding["task_id"],
            "platform_attempt_id": binding["attempt_id"],
            "platform_workflow_preparation_digest": binding[
                "workflow_preparation_digest"
            ],
            "platform_command_id": binding["command_id"],
            "platform_binding_digest": binding["binding_digest"],
        }
        observed = task.get("transport_binding")
        if observed is not None:
            document.update(
                {
                    "hqa_command_id": observed["command_id"],
                    "hqa_binding_digest": observed["binding_digest"],
                }
            )
        return document

    @classmethod
    def _authority_report(
        cls,
        hqa_snapshot: dict[str, Any],
        platform_bindings: list[dict[str, Any]],
        *,
        audit_attempts: int,
    ) -> dict[str, Any]:
        if not isinstance(platform_bindings, list):
            raise PlatformBindingUnavailable()
        validated_bindings: list[dict[str, Any]] = []
        previous_order: tuple[str, str] | None = None
        platform_commands: set[str] = set()
        platform_tasks: set[str] = set()
        platform_attempts: set[str] = set()
        platform_identities: set[tuple[str, str, str, str]] = set()
        for raw in platform_bindings:
            if not isinstance(raw, dict):
                raise PlatformBindingUnavailable()
            prepared = _inventory_preparation(raw)
            try:
                binding = _verify_binding(prepared, raw)
            except ResearchWorkflowError as exc:
                raise PlatformBindingUnavailable() from exc
            order = (binding["workflow_saga_id"], binding["command_id"])
            identity = (
                binding["owner_user_id"],
                binding["platform_session_id"],
                binding["client_request_id"],
                binding["command_kind"],
            )
            if (
                (previous_order is not None and order <= previous_order)
                or binding["command_id"] in platform_commands
                or binding["task_id"] in platform_tasks
                or binding["attempt_id"] in platform_attempts
                or identity in platform_identities
            ):
                raise PlatformBindingUnavailable()
            previous_order = order
            platform_commands.add(binding["command_id"])
            platform_tasks.add(binding["task_id"])
            platform_attempts.add(binding["attempt_id"])
            platform_identities.add(identity)
            validated_bindings.append(binding)

        hqa_tasks = hqa_snapshot.get("tasks")
        if not isinstance(hqa_tasks, list):
            raise ResearchWorkflowError(
                "workflow_ledger_corrupt",
                "workflow authority inventory is invalid",
            )
        by_hqa_saga: dict[str, dict[str, Any]] = {}
        hqa_tasks_seen: set[str] = set()
        hqa_attempts_seen: set[str] = set()
        hqa_identities_seen: set[tuple[str, str, str, str]] = set()
        previous_hqa_saga: str | None = None
        for task in hqa_tasks:
            prepared = cls._task_preparation(task)
            saga_id = prepared["workflow_saga_id"]
            identity = (
                prepared["owner_user_id"],
                prepared["platform_session_id"],
                prepared["client_request_id"],
                prepared["command_kind"],
            )
            if (
                saga_id in by_hqa_saga
                or (previous_hqa_saga is not None and saga_id <= previous_hqa_saga)
                or prepared["task_id"] in hqa_tasks_seen
                or prepared["attempt_id"] in hqa_attempts_seen
                or identity in hqa_identities_seen
            ):
                raise ResearchWorkflowError(
                    "workflow_ledger_corrupt",
                    "workflow authority inventory identity is duplicated or unsorted",
                )
            by_hqa_saga[saga_id] = task
            previous_hqa_saga = saga_id
            hqa_tasks_seen.add(prepared["task_id"])
            hqa_attempts_seen.add(prepared["attempt_id"])
            hqa_identities_seen.add(identity)
        by_platform_saga = {
            binding["workflow_saga_id"]: binding
            for binding in validated_bindings
        }
        if len(by_platform_saga) != len(validated_bindings):
            raise PlatformBindingUnavailable()

        unmatched_hqa = set(by_hqa_saga) - set(by_platform_saga)
        unmatched_platform = set(by_platform_saga) - set(by_hqa_saga)
        consumed_platform: set[str] = set()
        collision_by_hqa: dict[str, str] = {}
        platform_by_task = {
            by_platform_saga[saga]["task_id"]: saga
            for saga in unmatched_platform
        }
        platform_by_identity = {
            (
                by_platform_saga[saga]["owner_user_id"],
                by_platform_saga[saga]["platform_session_id"],
                by_platform_saga[saga]["client_request_id"],
                by_platform_saga[saga]["command_kind"],
            ): saga
            for saga in unmatched_platform
        }
        for saga in sorted(unmatched_hqa):
            task = by_hqa_saga[saga]
            related = platform_by_task.get(task["task_id"])
            if related is None:
                related = platform_by_identity.get(
                    (
                        task["owner_user_id"],
                        task["platform_session_id"],
                        task["client_request_id"],
                        task["command_kind"],
                    )
                )
            if related is not None:
                collision_by_hqa[saga] = related
                consumed_platform.add(related)

        findings: list[dict[str, Any]] = []
        all_sagas = sorted(set(by_hqa_saga) | set(by_platform_saga))
        for saga_id in all_sagas:
            if saga_id in consumed_platform:
                continue
            task = by_hqa_saga.get(saga_id)
            binding = by_platform_saga.get(saga_id)
            related_saga = collision_by_hqa.get(saga_id)
            if related_saga is not None and task is not None:
                findings.append(
                    cls._conflict_evidence(
                        task,
                        by_platform_saga[related_saga],
                    )
                )
                continue
            if task is None and binding is not None:
                findings.append(cls._evidence("platform_only", binding=binding))
                continue
            if task is not None and binding is None:
                if task.get("transport_binding") is not None:
                    status = "platform_missing_after_observation"
                elif task.get("payload_status") in {
                    "expired",
                    "deletion_pending",
                    "deleted",
                }:
                    status = "expired_unbound"
                else:
                    status = "awaiting_platform_binding"
                findings.append(cls._evidence(status, task=task))
                continue
            assert task is not None and binding is not None
            prepared = cls._task_preparation(task)
            exact = True
            try:
                _verify_binding(prepared, binding)
            except ResearchWorkflowError:
                exact = False
            observed = task.get("transport_binding")
            if not exact:
                status = "exact_fact_conflict"
            elif observed is None:
                status = "observation_missing"
            elif (
                observed.get("command_id") != binding["command_id"]
                or observed.get("binding_digest") != binding["binding_digest"]
                or observed.get("workflow_preparation_digest")
                != binding["workflow_preparation_digest"]
            ):
                status = "exact_fact_conflict"
            else:
                status = "consistent"
            if status == "exact_fact_conflict":
                findings.append(cls._conflict_evidence(task, binding))
            else:
                findings.append(cls._evidence(status, task=task, binding=binding))

        if not findings:
            empty_status = (
                "uninitialized"
                if hqa_snapshot.get("authority_state") == "absent"
                else "consistent_empty"
            )
            findings = [{"status": empty_status}]
        summary: dict[str, int] = {}
        for finding in findings:
            status = finding["status"]
            summary[status] = summary.get(status, 0) + 1
        digest = hashlib.sha256()
        for binding in validated_bindings:
            digest.update(
                json.dumps(
                    binding,
                    ensure_ascii=False,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8", errors="strict")
                + b"\n"
            )
        return {
            "schema_version": "1.0",
            "audit_attempts": audit_attempts,
            "hqa_snapshot": {
                "authority_state": hqa_snapshot.get("authority_state"),
                "last_sequence": hqa_snapshot.get("last_sequence"),
                "last_record_sha256": hqa_snapshot.get(
                    "last_record_sha256"
                ),
            },
            "platform_snapshot": {
                "count": len(validated_bindings),
                "bindings_sha256": digest.hexdigest(),
            },
            "summary": summary,
            "findings": findings,
        }

    def reconcile(self, task_id: str) -> dict[str, Any]:
        task = self.store.show(task_id)
        prepared = task["preparation"]
        platform_document = self.platform.show(prepared["workflow_saga_id"])
        if platform_document is None:
            if task.get("transport_binding") is not None:
                raise ResearchWorkflowError(
                    "workflow_authority_data_loss",
                    "an observed platform binding is missing from its authority",
                )
            if task.get("payload_status") in {
                "expired",
                "deletion_pending",
                "deleted",
            }:
                return self._result(task, None, status="expired_unbound")
            try:
                platform_document = self.platform.ensure(
                    as_platform_prepared_command(prepared)
                )
            except PlatformBindingOutcomeUnknown:
                platform_document = self.platform.show(
                    prepared["workflow_saga_id"]
                )
                if platform_document is None:
                    # The timed-out child is terminated by subprocess.run and
                    # the local authority confirms no commit. One exact retry
                    # is bounded and safe.
                    platform_document = self.platform.ensure(
                        as_platform_prepared_command(prepared)
                    )
        binding = _binding_from_platform_document(prepared, platform_document)
        existing = task.get("transport_binding")
        if existing is not None:
            if (
                existing.get("command_id") != binding["command_id"]
                or existing.get("binding_digest") != binding["binding_digest"]
                or existing.get("workflow_preparation_digest")
                != binding["workflow_preparation_digest"]
            ):
                raise ResearchWorkflowError(
                    "workflow_binding_conflict",
                    "HQA and platform authorities contain different bindings",
                )
            return self._result(task, binding, status=self._status(task))
        return self._observe_and_result(prepared, binding, task=task)

    def _observe_and_result(
        self,
        prepared: dict[str, Any],
        binding: dict[str, Any],
        *,
        task: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        current = task or self.store.show(prepared["task_id"])
        existing = current.get("transport_binding")
        if existing is None:
            try:
                current = self.store.observe_transport_binding(
                    task_id=prepared["task_id"],
                    expected_version=current["version"],
                    command_id=binding["command_id"],
                    binding_digest=binding["binding_digest"],
                )
            except ResearchWorkflowError as exc:
                if exc.code != "workflow_version_conflict":
                    raise
                # A concurrent, finite local transition (normally TTL deletion)
                # may win CAS after the platform lookup. Reload once and append
                # the same exact binding at the new aggregate version.
                current = self.store.show(prepared["task_id"])
                existing = current.get("transport_binding")
                if existing is None:
                    current = self.store.observe_transport_binding(
                        task_id=prepared["task_id"],
                        expected_version=current["version"],
                        command_id=binding["command_id"],
                        binding_digest=binding["binding_digest"],
                    )
                elif (
                    existing.get("command_id") != binding["command_id"]
                    or existing.get("binding_digest") != binding["binding_digest"]
                    or existing.get("workflow_preparation_digest")
                    != binding["workflow_preparation_digest"]
                ):
                    raise ResearchWorkflowError(
                        "workflow_binding_conflict",
                        "HQA and platform authorities contain different bindings",
                    )
        elif (
            existing.get("command_id") != binding["command_id"]
            or existing.get("binding_digest") != binding["binding_digest"]
            or existing.get("workflow_preparation_digest")
            != binding["workflow_preparation_digest"]
        ):
            raise ResearchWorkflowError(
                "workflow_binding_conflict",
                "HQA and platform authorities contain different bindings",
            )
        return self._result(current, binding, status=self._status(current))

    @staticmethod
    def _status(task: dict[str, Any]) -> str:
        if task.get("payload_status") == "deleted":
            return "bound_payload_deleted"
        if task.get("payload_status") in {"expired", "deletion_pending"}:
            return "bound_payload_expired"
        return "bound"

    @staticmethod
    def _result(
        task: dict[str, Any],
        binding: dict[str, Any] | None,
        *,
        status: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "status": status,
            "task": task,
            "binding": binding,
        }


__all__ = [
    "PlatformBindingConflict",
    "PlatformBindingOutcomeUnknown",
    "PlatformBindingRejected",
    "PlatformBindingUnavailable",
    "PlatformWorkflowBindingPort",
    "ResearchWorkflowSaga",
    "SubprocessPlatformWorkflowBindingClient",
]

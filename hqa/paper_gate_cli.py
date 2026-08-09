"""Narrow write port for Agent v0.2 paper-research human gates.

The platform invokes exactly one fixed operation with one strict JSON object on
stdin.  This module owns no second workflow journal: Gate 1 delegates to
``WorkflowAuthority`` and Gate 2/3 delegate to the existing Scene-B
``factor_repro_cli`` authority.  stdout is always one bounded JSON object and
never echoes formula source bytes, prompts, human notes, or provider secrets.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

from hqa import config, factor_repro, factor_repro_cli, quant_cli
from hqa.workflow_authority import WorkflowAuthority, WorkflowAuthorityError
from hqa.workflow_contract import (
    BindCandidateManifest,
    ConfirmFormula,
    ObserveGate3,
    ResolveDomainGate,
    WorkflowContractError,
)

_STDIN_LIMIT = 64_000
_STDOUT_LIMIT = 256_000
_OPERATIONS = frozenset({"confirm-formula", "approve", "promote"})
_MANAGED_SESSION_REF_RE = re.compile(r"^session:[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")


class _PaperGateInputError(ValueError):
    pass


class _PaperGateOperationError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = bool(retryable)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise _PaperGateInputError("duplicate JSON field")
        document[key] = value
    return document


def _reject_constant(_value: str) -> None:
    raise _PaperGateInputError("non-finite JSON number")


def _read_request() -> dict[str, Any]:
    stream = getattr(sys.stdin, "buffer", sys.stdin)
    raw = stream.read(_STDIN_LIMIT + 1)
    if isinstance(raw, str):
        raw = raw.encode("utf-8", errors="strict")
    if not raw or len(raw) > _STDIN_LIMIT:
        raise _PaperGateInputError("empty or oversized JSON stdin")
    try:
        document = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except _PaperGateInputError:
        raise
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        RecursionError,
    ) as exc:
        raise _PaperGateInputError("invalid JSON stdin") from exc
    if not isinstance(document, dict):
        raise _PaperGateInputError("JSON stdin must be an object")
    return document


def _require_exact_fields(
    document: Mapping[str, Any],
    *,
    required: set[str],
) -> None:
    if set(document) != required:
        raise _PaperGateInputError("request fields do not match operation schema")


def _encoded(document: Mapping[str, Any]) -> bytes:
    try:
        raw = json.dumps(
            dict(document),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise _PaperGateInputError("invalid response") from exc
    if not raw or len(raw) > _STDOUT_LIMIT:
        raise _PaperGateInputError("oversized response")
    return raw


def _emit(document: Mapping[str, Any]) -> None:
    raw = _encoded(document)
    stream = getattr(sys.stdout, "buffer", None)
    if stream is not None:
        stream.write(raw + b"\n")
    else:
        sys.stdout.write(raw.decode("utf-8") + "\n")


def _authority() -> WorkflowAuthority:
    return WorkflowAuthority(
        config.WORKFLOW_AUTHORITY_DIR,
        config.WORKFLOW_OWNER_USER_ID,
    )


def _receipt_document(value: object) -> dict[str, Any]:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    names = (
        "operation_id",
        "operation_digest",
        "event_id",
        "task_ref",
        "task_version",
        "attempt_ref",
        "replayed",
    )
    return {name: getattr(value, name) for name in names}


def _receipt_digest(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(_encoded(document)).hexdigest()


def _stable_workflow_operation_id(
    operation: str,
    binding: Mapping[str, Any],
) -> str:
    payload = _encoded({"operation": operation, **dict(binding)})
    return f"paper-{operation}-{hashlib.sha256(payload).hexdigest()[:32]}"


def _workflow_evidence(
    receipt: object,
    *,
    outer_operation_id: str,
) -> dict[str, Any]:
    document = _receipt_document(receipt)
    workflow_operation_id = document.pop("operation_id")
    return {
        **document,
        "operation_id": outer_operation_id,
        "workflow_operation_id": workflow_operation_id,
    }


def _require_managed_session_binding(
    authority: object,
    request: Mapping[str, Any],
) -> str:
    managed_session_ref = request.get("managed_session_ref")
    if (
        type(managed_session_ref) is not str
        or _MANAGED_SESSION_REF_RE.fullmatch(managed_session_ref) is None
    ):
        raise _PaperGateInputError(
            "managed_session_ref must be an exact managed Session reference"
        )
    snapshot = authority.snapshot(request["task_ref"])  # type: ignore[attr-defined]
    if getattr(snapshot, "managed_session_ref", None) != managed_session_ref:
        raise _PaperGateInputError(
            "managed_session_ref does not match WorkflowAuthority"
        )
    return managed_session_ref


def _reconcile_exact_candidate_approval(
    *,
    candidate_id: str,
    expected_digest: str,
    note: str,
) -> Optional[dict[str, Any]]:
    try:
        code, output = quant_cli.run_inspect_factor_candidate(
            candidate_id,
            expected_manifest_digest=expected_digest,
        )
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        raise _PaperGateOperationError(
            "paper_gate_outcome_unknown",
            retryable=False,
        ) from exc
    document = factor_repro.parse_json_payload(output)
    if (
        code != 0
        or document is None
        or document.get("candidate_id") != candidate_id
        or document.get("manifest_digest") != expected_digest
        or document.get("approval_binding") != "approved"
    ):
        return None
    source_path = document.get("source_path")
    if not isinstance(source_path, str):
        raise _PaperGateOperationError(
            "paper_gate_outcome_unknown",
            retryable=False,
        )
    raw_agent_root = os.environ.get("QS_AGENT_OUTPUT_DIR")
    agent_root = (
        config.AIQP_DIR / "data" / "agent_run"
        if not raw_agent_root
        else Path(raw_agent_root)
    )
    try:
        factor_repro.require_exact_candidate_approval_lock(
            candidates_root=agent_root / "agent" / "candidates",
            source_path=source_path,
            candidate_id=candidate_id,
            manifest_digest=expected_digest,
            note=note,
        )
    except (OSError, ValueError) as exc:
        raise _PaperGateOperationError(
            "paper_gate_outcome_unknown",
            retryable=False,
        ) from exc
    return {
        "candidate_id": candidate_id,
        "decision": "approve",
        "manifest_digest": expected_digest,
        "registration": "manual_required",
    }


def _reconcile_exact_promotion(
    *,
    candidate_id: str,
    expected_digest: str,
    final_backtest_receipt_id: str,
    base_commit: str,
) -> Optional[dict[str, Any]]:
    try:
        promotion_root, worktree_root = factor_repro_cli._platform_gate3_roots()
        receipt = factor_repro.find_exact_gate3_receipt(
            gate_dir=config.FACTOR_GATE1_DIR,
            experiment_output_dir=config.FACTOR_EXPERIMENT_OUTPUT_DIR,
            candidate_id=candidate_id,
            manifest_digest=expected_digest,
            final_backtest_receipt_id=final_backtest_receipt_id,
            base_commit=base_commit,
            promotion_root=promotion_root,
            worktree_root=worktree_root,
        )
    except (
        OSError,
        RuntimeError,
        ValueError,
        subprocess.SubprocessError,
    ) as exc:
        raise _PaperGateOperationError(
            "paper_gate_outcome_unknown",
            retryable=False,
        ) from exc
    if receipt is None:
        return None
    status_code, status_output = quant_cli.run_promotion_status(receipt["promotion_id"])
    status = factor_repro.parse_json_payload(status_output)
    if (
        status_code != 0
        or status is None
        or status.get("promotion_id") != receipt["promotion_id"]
        or status.get("status") != "awaiting_human_commit"
        or status.get("reviewed_commit") is not None
        or status.get("candidate_id") != candidate_id
        or status.get("candidate_digest") != expected_digest
        or status.get("final_backtest_receipt_id") != final_backtest_receipt_id
        or status.get("base_commit") != base_commit
    ):
        raise _PaperGateOperationError(
            "paper_gate_outcome_unknown",
            retryable=False,
        )
    return receipt


def _factor_cli_json(
    argv: list[str],
    *,
    factor_cli_main: Callable[[Optional[list[str]]], int],
) -> dict[str, Any]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = factor_cli_main(argv)
    output = stdout.getvalue().strip()
    if code != 0:
        # The existing Scene-B wrapper prints explicit unknown-outcome recovery
        # for process/timeout failures.  Never turn those into a blind retry.
        unknown = "outcome is unknown" in stderr.getvalue().lower()
        raise _PaperGateOperationError(
            "paper_gate_outcome_unknown" if unknown else "paper_gate_rejected",
            retryable=False,
        )
    if not output or "\n" in output:
        raise _PaperGateOperationError(
            "paper_gate_outcome_unknown",
            retryable=False,
        )
    try:
        document = json.loads(
            output,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (
        _PaperGateInputError,
        json.JSONDecodeError,
        ValueError,
        RecursionError,
    ) as exc:
        raise _PaperGateOperationError(
            "paper_gate_outcome_unknown",
            retryable=False,
        ) from exc
    if not isinstance(document, dict):
        raise _PaperGateOperationError(
            "paper_gate_outcome_unknown",
            retryable=False,
        )
    return document


def _approve(
    request: Mapping[str, Any],
    *,
    authority_factory: Callable[[], object],
    candidate_binding_checker: Callable[..., None],
    factor_cli_main: Callable[[Optional[list[str]]], int],
    candidate_approval_reconciler: Callable[..., Optional[dict[str, Any]]],
) -> dict[str, Any]:
    _require_exact_fields(
        request,
        required={
            "managed_session_ref",
            "operation_id",
            "task_ref",
            "expected_task_version",
            "gate_ref",
            "gate1_confirmation_id",
            "reviewed_source_digest",
            "candidate_id",
            "expected_digest",
            "expected_status",
            "note",
        },
    )
    authority = authority_factory()
    managed_session_ref = _require_managed_session_binding(
        authority,
        request,
    )
    # The bridge must consume the provenance-bound record produced by the
    # established propose flow. It must never manufacture a binding from
    # caller-supplied candidate/digest values.
    candidate_binding_checker(
        gate_dir=config.FACTOR_GATE1_DIR,
        confirmation_id=request["gate1_confirmation_id"],
        source_digest=request["reviewed_source_digest"],
        candidate_id=request["candidate_id"],
        manifest_digest=request["expected_digest"],
    )
    binding_receipt = authority.apply(  # type: ignore[attr-defined]
        BindCandidateManifest(
            operation_id=_stable_workflow_operation_id(
                "gate2-bind",
                {
                    "candidate_id": request["candidate_id"],
                    "expected_digest": request["expected_digest"],
                    "expected_task_version": request["expected_task_version"],
                    "gate_ref": request["gate_ref"],
                    "managed_session_ref": managed_session_ref,
                    "task_ref": request["task_ref"],
                },
            ),
            task_ref=request["task_ref"],
            expected_version=request["expected_task_version"],
            gate_ref=request["gate_ref"],
            candidate_ref=f"candidate:{request['candidate_id']}",
            manifest_digest=request["expected_digest"],
        )
    )
    try:
        receipt = _factor_cli_json(
            [
                "approve",
                "--candidate-id",
                request["candidate_id"],
                "--expected-digest",
                request["expected_digest"],
                "--expected-status",
                request["expected_status"],
                "--note",
                request["note"],
            ],
            factor_cli_main=factor_cli_main,
        )
    except _PaperGateOperationError:
        receipt = candidate_approval_reconciler(
            candidate_id=request["candidate_id"],
            expected_digest=request["expected_digest"],
            note=request["note"],
        )
        if receipt is None:
            raise
    if (
        set(receipt)
        != {
            "candidate_id",
            "decision",
            "manifest_digest",
            "registration",
        }
        or receipt.get("candidate_id") != request["candidate_id"]
        or receipt.get("manifest_digest") != request["expected_digest"]
        or receipt.get("decision") != "approve"
        or receipt.get("registration") != "manual_required"
    ):
        raise _PaperGateOperationError(
            "paper_gate_outcome_unknown",
            retryable=False,
        )
    evidence = {
        **_workflow_evidence(
            binding_receipt,
            outer_operation_id=request["operation_id"],
        ),
        "task_ref": request["task_ref"],
        "gate_ref": request["gate_ref"],
        "managed_session_ref": managed_session_ref,
        "gate1_confirmation_id": request["gate1_confirmation_id"],
        "reviewed_source_digest": request["reviewed_source_digest"],
        "workflow_binding_event_id": getattr(binding_receipt, "event_id"),
        "candidate_id": request["candidate_id"],
        "candidate_digest": request["expected_digest"],
        "decision": "approve",
        "registration": "manual_required",
        "review_note_digest": hashlib.sha256(
            request["note"].encode("utf-8")
        ).hexdigest(),
    }
    return {
        "ok": True,
        **evidence,
        "hqa_receipt_ref": f"hqa-paper-gate:{request['operation_id']}",
        "hqa_receipt_digest": _receipt_digest(evidence),
    }


def _promote(
    request: Mapping[str, Any],
    *,
    authority_factory: Callable[[], object],
    factor_cli_main: Callable[[Optional[list[str]]], int],
    promotion_reconciler: Callable[..., Optional[dict[str, Any]]],
) -> dict[str, Any]:
    _require_exact_fields(
        request,
        required={
            "managed_session_ref",
            "operation_id",
            "task_ref",
            "expected_task_version",
            "attempt_ref",
            "run_ref",
            "gate_ref",
            "candidate_id",
            "expected_digest",
            "final_backtest_receipt_id",
            "base_commit",
        },
    )
    authority = authority_factory()
    managed_session_ref = _require_managed_session_binding(
        authority,
        request,
    )
    resolution_receipt = authority.apply(  # type: ignore[attr-defined]
        ResolveDomainGate(
            operation_id=_stable_workflow_operation_id(
                "gate3-resolve",
                {
                    "attempt_ref": request["attempt_ref"],
                    "candidate_id": request["candidate_id"],
                    "expected_digest": request["expected_digest"],
                    "expected_task_version": request["expected_task_version"],
                    "final_backtest_receipt_id": request["final_backtest_receipt_id"],
                    "gate_ref": request["gate_ref"],
                    "managed_session_ref": managed_session_ref,
                    "run_ref": request["run_ref"],
                    "task_ref": request["task_ref"],
                },
            ),
            task_ref=request["task_ref"],
            expected_version=request["expected_task_version"],
            attempt_ref=request["attempt_ref"],
            gate_ref=request["gate_ref"],
            outcome="passed",
        )
    )
    workflow_receipt = authority.apply(  # type: ignore[attr-defined]
        ObserveGate3(
            operation_id=_stable_workflow_operation_id(
                "gate3-observe",
                {
                    "attempt_ref": request["attempt_ref"],
                    "base_commit": request["base_commit"],
                    "candidate_id": request["candidate_id"],
                    "expected_digest": request["expected_digest"],
                    "expected_task_version": request["expected_task_version"],
                    "final_backtest_receipt_id": request["final_backtest_receipt_id"],
                    "gate_ref": request["gate_ref"],
                    "managed_session_ref": managed_session_ref,
                    "run_ref": request["run_ref"],
                    "task_ref": request["task_ref"],
                },
            ),
            task_ref=request["task_ref"],
            expected_version=getattr(resolution_receipt, "task_version"),
            attempt_ref=request["attempt_ref"],
            run_ref=request["run_ref"],
            gate_ref=request["gate_ref"],
            candidate_ref=f"candidate:{request['candidate_id']}",
            manifest_digest=request["expected_digest"],
            final_receipt_ref=(f"result:{request['final_backtest_receipt_id']}"),
            base_commit=request["base_commit"],
        )
    )
    recovery_args = {
        "candidate_id": request["candidate_id"],
        "expected_digest": request["expected_digest"],
        "final_backtest_receipt_id": request["final_backtest_receipt_id"],
        "base_commit": request["base_commit"],
    }
    receipt = None
    if getattr(workflow_receipt, "replayed"):
        receipt = promotion_reconciler(**recovery_args)
    if receipt is None:
        try:
            receipt = _factor_cli_json(
                [
                    "promote",
                    "--candidate-id",
                    request["candidate_id"],
                    "--expected-digest",
                    request["expected_digest"],
                    "--final-backtest-receipt",
                    request["final_backtest_receipt_id"],
                    "--base-commit",
                    request["base_commit"],
                ],
                factor_cli_main=factor_cli_main,
            )
        except _PaperGateOperationError:
            receipt = promotion_reconciler(**recovery_args)
            if receipt is None:
                raise
    if set(receipt) != {"promotion_id", "worktree", "patch", "manifest"} or any(
        type(receipt.get(key)) is not str or not receipt[key] for key in receipt
    ):
        raise _PaperGateOperationError(
            "paper_gate_outcome_unknown",
            retryable=False,
        )
    evidence = {
        **_workflow_evidence(
            workflow_receipt,
            outer_operation_id=request["operation_id"],
        ),
        "task_ref": request["task_ref"],
        "workflow_gate_resolution_event_id": getattr(
            resolution_receipt,
            "event_id",
        ),
        "workflow_gate3_event_id": getattr(workflow_receipt, "event_id"),
        "run_ref": request["run_ref"],
        "gate_ref": request["gate_ref"],
        "managed_session_ref": managed_session_ref,
        "candidate_id": request["candidate_id"],
        "candidate_digest": request["expected_digest"],
        "final_backtest_receipt_id": request["final_backtest_receipt_id"],
        "base_commit": request["base_commit"],
        "promotion_id": receipt["promotion_id"],
        "promotion_status": "awaiting_human_commit",
        "worktree": receipt["worktree"],
        "patch": receipt["patch"],
        "manifest": receipt["manifest"],
        "human_git_commit_required": True,
        "auto_commit": False,
    }
    return {
        "ok": True,
        **evidence,
        "hqa_receipt_ref": f"hqa-paper-gate:{request['operation_id']}",
        "hqa_receipt_digest": _receipt_digest(evidence),
    }


def _confirm_formula(
    request: Mapping[str, Any],
    *,
    authority_factory: Callable[[], object],
    gate1_preparer: Callable[..., tuple[str, str, str]],
) -> dict[str, Any]:
    _require_exact_fields(
        request,
        required={
            "managed_session_ref",
            "operation_id",
            "task_ref",
            "expected_task_version",
            "gate_ref",
            "reviewed_source_digest",
            "confirmation_note",
            "source_file",
            "universe",
        },
    )
    authority = authority_factory()
    managed_session_ref = _require_managed_session_binding(
        authority,
        request,
    )
    source_file = request["source_file"]
    universe = request["universe"]
    if (
        type(source_file) is not str
        or not source_file.startswith("/")
        or len(source_file) > 4096
        or not source_file.isprintable()
    ):
        raise _PaperGateInputError("source_file must be a bounded absolute path")
    if (
        type(universe) is not str
        or not universe.strip()
        or len(universe.encode("utf-8")) > 2000
        or not universe.isprintable()
    ):
        raise _PaperGateInputError("universe must be bounded printable text")
    confirmation_id, observed_digest, staged_source = gate1_preparer(
        goal=request["task_ref"],
        universe=universe.strip(),
        source_file=source_file,
        expected_source_digest=request["reviewed_source_digest"],
        confirmation_note=request["confirmation_note"],
        gate_dir=config.FACTOR_GATE1_DIR,
    )
    if observed_digest != request["reviewed_source_digest"]:
        raise _PaperGateInputError("Gate 1 preparer substituted source digest")
    task_ref = request["task_ref"]
    command = ConfirmFormula(
        operation_id=_stable_workflow_operation_id(
            "gate1-confirm",
            {
                "confirmation_note_digest": hashlib.sha256(
                    request["confirmation_note"].encode("utf-8")
                ).hexdigest(),
                "expected_task_version": request["expected_task_version"],
                "gate_ref": request["gate_ref"],
                "gate1_confirmation_id": confirmation_id,
                "managed_session_ref": managed_session_ref,
                "reviewed_source_digest": request["reviewed_source_digest"],
                "task_ref": task_ref,
                "universe": universe.strip(),
            },
        ),
        task_ref=task_ref,
        expected_version=request["expected_task_version"],
        gate_ref=request["gate_ref"],
        reviewed_source_digest=request["reviewed_source_digest"],
        confirmation_note=request["confirmation_note"],
    )
    receipt = authority.apply(command)  # type: ignore[attr-defined]
    evidence = {
        **_workflow_evidence(
            receipt,
            outer_operation_id=request["operation_id"],
        ),
        "gate_ref": command.gate_ref,
        "gate1_confirmation_id": confirmation_id,
        "managed_session_ref": managed_session_ref,
        "reviewed_source_digest": command.reviewed_source_digest,
        "staged_source_ref": staged_source,
    }
    return {
        "ok": True,
        **evidence,
        "hqa_receipt_ref": f"hqa-paper-gate:{request['operation_id']}",
        "hqa_receipt_digest": _receipt_digest(evidence),
    }


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    authority_factory: Callable[[], object] = _authority,
    gate1_preparer: Callable[..., tuple[str, str, str]] = (
        factor_repro.prepare_gate1_confirmation
    ),
    candidate_binding_checker: Callable[..., None] = (
        factor_repro.require_gate1_candidate_binding
    ),
    factor_cli_main: Callable[[Optional[list[str]]], int] = factor_repro_cli.main,
    candidate_approval_reconciler: Callable[
        ..., Optional[dict[str, Any]]
    ] = _reconcile_exact_candidate_approval,
    promotion_reconciler: Callable[
        ..., Optional[dict[str, Any]]
    ] = _reconcile_exact_promotion,
) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1 or args[0] not in _OPERATIONS:
        _emit(
            {
                "error": {
                    "code": "paper_gate_invalid_arguments",
                    "message": "paper gate operation is invalid",
                    "retryable": False,
                }
            }
        )
        return 2
    try:
        request = _read_request()
        if args[0] == "confirm-formula":
            result = _confirm_formula(
                request,
                authority_factory=authority_factory,
                gate1_preparer=gate1_preparer,
            )
        elif args[0] == "approve":
            result = _approve(
                request,
                authority_factory=authority_factory,
                candidate_binding_checker=candidate_binding_checker,
                factor_cli_main=factor_cli_main,
                candidate_approval_reconciler=(candidate_approval_reconciler),
            )
        else:
            result = _promote(
                request,
                authority_factory=authority_factory,
                factor_cli_main=factor_cli_main,
                promotion_reconciler=promotion_reconciler,
            )
    except (WorkflowContractError, _PaperGateInputError, TypeError, ValueError):
        _emit(
            {
                "error": {
                    "code": "paper_gate_invalid_request",
                    "message": "paper gate request is invalid",
                    "retryable": False,
                }
            }
        )
        return 2
    except WorkflowAuthorityError as exc:
        _emit(
            {
                "error": {
                    "code": exc.code,
                    "message": "paper gate authority rejected the operation",
                    "retryable": exc.code
                    in {
                        "workflow_storage_unavailable",
                        "workflow_durability_unknown",
                    },
                }
            }
        )
        return 1
    except _PaperGateOperationError as exc:
        _emit(
            {
                "error": {
                    "code": exc.code,
                    "message": "paper gate operation did not produce an exact receipt",
                    "retryable": exc.retryable,
                }
            }
        )
        return 1 if exc.retryable else 2
    except OSError:
        _emit(
            {
                "error": {
                    "code": "paper_gate_unavailable",
                    "message": "paper gate authority is unavailable",
                    "retryable": True,
                }
            }
        )
        return 1
    _emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

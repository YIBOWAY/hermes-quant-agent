"""Fail-closed paper factor automation pipeline.

Slice 2 exposes the repeatable pipeline only through an explicit acceptance
switch and deliberately stops at a content-bound final backtest receipt.  The
production dual flags, durable driver, Gate-3 commit, and local ff-land are
added later; this module has no promotion method by design.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable, Literal, Protocol

from hqa import config, factor_repro, quant_cli

from hqa.factor_automation_policy import (
    FactorAutomationDecision,
    FactorAutomationEvidence,
    LoadedFactorAutomationPolicy,
    evaluate_factor_automation_policy,
)

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,127}$")
_AUTOMATION_ID_RE = re.compile(r"^automation-[0-9a-f]{16,64}$")
_INTAKE_RECEIPT_RE = re.compile(r"^paper-intake-receipt:sha256:[0-9a-f]{64}$")
_BACKTEST_RECEIPT_RE = re.compile(r"^backtest-[0-9a-f]{32}$")
_GIT_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_PROMOTION_ID_RE = re.compile(r"^promo-[0-9a-f]{32}(?:-r(?:[2-9]|[1-9][0-9]+))?$")


class FactorAutomationError(RuntimeError):
    """Raised when a machine decision or receipt cannot authorize progress."""


class FactorAutomationDisabled(FactorAutomationError):
    """Raised before any mutation while the Slice-2 acceptance switch is off."""


@dataclass(frozen=True)
class FactorAutomationRequest:
    automation_id: str
    intake_receipt_id: str
    intake_contract_digest: str
    source_file_ref: str
    source_sha256: str
    goal: str
    universe: tuple[str, ...]
    provider: Literal["futu", "tiingo"]
    start: str
    end: str
    policy_evidence: FactorAutomationEvidence


@dataclass(frozen=True)
class CandidateReceipt:
    candidate_id: str
    manifest_digest: str
    source_sha256: str
    status: Literal["pending"]


@dataclass(frozen=True)
class MachineApprovalReceipt:
    candidate_id: str
    manifest_digest: str
    reviewer: Literal["auto"]
    registration: Literal["auto_promote"]
    policy_digest: str
    intake_contract_digest: str
    status: Literal["approved"]


@dataclass(frozen=True)
class FinalBacktestReceipt:
    receipt_id: str
    candidate_id: str
    manifest_digest: str
    source_sha256: str
    intake_receipt_id: str
    policy_digest: str
    provider: Literal["futu", "tiingo"]
    final: Literal[True]
    actual_sample_rows: int
    actual_out_of_sample_rows: int
    actual_data_coverage_ratio: float
    actual_transaction_cost_bps: float
    actual_max_drawdown: float
    actual_turnover: float


@dataclass(frozen=True)
class FactorAutomationSlice2Result:
    state: Literal["final_backtest_ready"]
    candidate: CandidateReceipt
    approval: MachineApprovalReceipt
    final_backtest: FinalBacktestReceipt
    policy_decision: FactorAutomationDecision
    promotion_performed: Literal[False] = False


@dataclass(frozen=True)
class AutomaticPaperLandResult:
    state: Literal["landed"]
    promotion_id: str
    base_commit: str
    reviewed_commit: str
    local_head: str
    pushed: Literal[False]
    promotion_scope: Literal["paper_only"]
    sleeve_id: str
    allocated_cash: float


@dataclass(frozen=True)
class FactorAutomationFullResult:
    slice2: FactorAutomationSlice2Result
    land: AutomaticPaperLandResult


class FactorAutomationPromotionPort(Protocol):
    def prepare_commit_land(
        self,
        *,
        slice2: FactorAutomationSlice2Result,
        request: FactorAutomationRequest,
        base_commit: str,
    ) -> AutomaticPaperLandResult: ...


class FactorAutomationSlice2Port(Protocol):
    def propose(self, request: FactorAutomationRequest) -> CandidateReceipt: ...

    def machine_approve(
        self,
        *,
        candidate_id: str,
        expected_manifest_digest: str,
        policy_digest: str,
        note: str,
    ) -> MachineApprovalReceipt: ...

    def final_backtest(
        self,
        *,
        request: FactorAutomationRequest,
        candidate: CandidateReceipt,
        approval: MachineApprovalReceipt,
    ) -> FinalBacktestReceipt: ...


def _validate_request(request: FactorAutomationRequest) -> None:
    source = Path(request.source_file_ref)
    try:
        start = date.fromisoformat(request.start)
        end = date.fromisoformat(request.end)
    except ValueError as exc:
        raise FactorAutomationError("request_invalid") from exc
    if (
        _AUTOMATION_ID_RE.fullmatch(request.automation_id) is None
        or _INTAKE_RECEIPT_RE.fullmatch(request.intake_receipt_id) is None
        or _DIGEST_RE.fullmatch(request.intake_contract_digest) is None
        or _DIGEST_RE.fullmatch(request.source_sha256) is None
        or not source.is_absolute()
        or source.suffix != ".py"
        or not request.goal.strip()
        or not request.universe
        or len(set(request.universe)) != len(request.universe)
        or any(symbol != symbol.upper() or not symbol for symbol in request.universe)
        or request.provider not in {"futu", "tiingo"}
        or end <= start
        or request.policy_evidence.universe != request.universe
    ):
        raise FactorAutomationError("request_invalid")


def _require_basic_lookahead_static_check(request: FactorAutomationRequest) -> None:
    """Reject obvious future-data operators in the exact digest-bound source."""

    source = Path(request.source_file_ref)
    descriptor = -1
    try:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(source, flags)
        metadata = os.fstat(descriptor)
        chunks: list[bytes] = []
        remaining = 256_001
        while remaining:
            chunk = os.read(descriptor, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        tree = ast.parse(payload.decode("utf-8", errors="strict"))
    except (OSError, UnicodeError, SyntaxError, ValueError) as exc:
        raise FactorAutomationError("lookahead_static_check_failed") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_nlink != 1
        or not payload
        or len(payload) > 256_000
        or hashlib.sha256(payload).hexdigest() != request.source_sha256
    ):
        raise FactorAutomationError("lookahead_static_check_failed")

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        method = node.func.attr
        if method in {"bfill", "backfill"}:
            raise FactorAutomationError("lookahead_static_check_failed")
        if method == "rolling":
            center = next(
                (item.value for item in node.keywords if item.arg == "center"),
                None,
            )
            if isinstance(center, ast.Constant) and center.value is True:
                raise FactorAutomationError("lookahead_static_check_failed")
        if method not in {"shift", "diff", "pct_change"}:
            continue
        periods = node.args[0] if node.args else next(
            (item.value for item in node.keywords if item.arg == "periods"),
            None,
        )
        if isinstance(periods, ast.UnaryOp) and isinstance(periods.op, ast.USub):
            if isinstance(periods.operand, ast.Constant) and isinstance(
                periods.operand.value, (int, float)
            ):
                raise FactorAutomationError("lookahead_static_check_failed")


def validate_factor_automation_request(request: FactorAutomationRequest) -> None:
    """Validate one exact source-bound request before queueing or mutation."""

    _validate_request(request)
    _require_basic_lookahead_static_check(request)


def _validate_candidate(
    candidate: CandidateReceipt,
    request: FactorAutomationRequest,
) -> None:
    if (
        _SAFE_ID_RE.fullmatch(candidate.candidate_id) is None
        or _DIGEST_RE.fullmatch(candidate.manifest_digest) is None
        or candidate.source_sha256 != request.source_sha256
        or candidate.status != "pending"
    ):
        raise FactorAutomationError("candidate_receipt_drift")


def _validate_approval(
    approval: MachineApprovalReceipt,
    *,
    candidate: CandidateReceipt,
    request: FactorAutomationRequest,
    policy_digest: str,
) -> None:
    if (
        approval.candidate_id != candidate.candidate_id
        or approval.manifest_digest != candidate.manifest_digest
        or approval.reviewer != "auto"
        or approval.registration != "auto_promote"
        or approval.policy_digest != policy_digest
        or approval.intake_contract_digest != request.intake_contract_digest
        or approval.status != "approved"
    ):
        raise FactorAutomationError("machine_approval_receipt_drift")


def _validate_final(
    receipt: FinalBacktestReceipt,
    *,
    request: FactorAutomationRequest,
    candidate: CandidateReceipt,
    approval: MachineApprovalReceipt,
) -> None:
    if (
        _BACKTEST_RECEIPT_RE.fullmatch(receipt.receipt_id) is None
        or receipt.candidate_id != candidate.candidate_id
        or receipt.manifest_digest != candidate.manifest_digest
        or receipt.source_sha256 != request.source_sha256
        or receipt.intake_receipt_id != request.intake_receipt_id
        or receipt.policy_digest != approval.policy_digest
        or receipt.provider != request.provider
        or receipt.final is not True
    ):
        raise FactorAutomationError("final_backtest_receipt_drift")


def run_to_final_backtest(
    *,
    request: FactorAutomationRequest,
    policy: LoadedFactorAutomationPolicy,
    port: FactorAutomationSlice2Port,
    allow_acceptance_machine_approval: bool = False,
) -> FactorAutomationSlice2Result:
    """Run the Slice-2 seam and intentionally stop before Gate 3/promotion."""

    if allow_acceptance_machine_approval is not True:
        raise FactorAutomationDisabled("slice2_acceptance_machine_approval_disabled")
    validate_factor_automation_request(request)
    declared_evidence = FactorAutomationEvidence(
        **{
            **request.policy_evidence.__dict__,
            "lookahead_static_check_passed": True,
        }
    )
    declared_decision = evaluate_factor_automation_policy(
        policy,
        declared_evidence,
    )
    if not declared_decision.accepted:
        raise FactorAutomationError(
            "policy_refused:" + ",".join(declared_decision.reasons)
        )
    candidate = port.propose(request)
    _validate_candidate(candidate, request)
    approval = port.machine_approve(
        candidate_id=candidate.candidate_id,
        expected_manifest_digest=candidate.manifest_digest,
        policy_digest=declared_decision.policy_digest,
        note=f"auto:policy:{declared_decision.policy_digest}",
    )
    _validate_approval(
        approval,
        candidate=candidate,
        request=request,
        policy_digest=declared_decision.policy_digest,
    )
    final_backtest = port.final_backtest(
        request=request,
        candidate=candidate,
        approval=approval,
    )
    _validate_final(
        final_backtest,
        request=request,
        candidate=candidate,
        approval=approval,
    )
    verified_evidence = FactorAutomationEvidence(
        universe=request.policy_evidence.universe,
        sample_rows=final_backtest.actual_sample_rows,
        out_of_sample_rows=final_backtest.actual_out_of_sample_rows,
        data_coverage_ratio=final_backtest.actual_data_coverage_ratio,
        transaction_cost_bps=final_backtest.actual_transaction_cost_bps,
        max_drawdown=final_backtest.actual_max_drawdown,
        turnover=final_backtest.actual_turnover,
        lookahead_static_check_passed=True,
    )
    final_decision = evaluate_factor_automation_policy(policy, verified_evidence)
    if not final_decision.accepted:
        raise FactorAutomationError(
            "final_policy_refused:" + ",".join(final_decision.reasons)
        )
    return FactorAutomationSlice2Result(
        state="final_backtest_ready",
        candidate=candidate,
        approval=approval,
        final_backtest=final_backtest,
        policy_decision=final_decision,
    )


ProposeRunner = Callable[[str, str, str], tuple[int, str]]
AutoReviewRunner = Callable[..., tuple[int, str]]
BacktestRunner = Callable[[list[str]], tuple[int, str]]
FinalReceiptVerifier = Callable[..., dict[str, Any]]


def _run_backtest_cli(
    argv: list[str],
    *,
    gate_dir: Path,
    experiment_output_dir: Path,
) -> tuple[int, str]:
    child_env = dict(os.environ)
    child_env["HQA_FACTOR_GATE1_DIR"] = str(gate_dir)
    child_env["HQA_FACTOR_EXPERIMENT_OUTPUT_DIR"] = str(experiment_output_dir)
    proc = subprocess.run(
        [sys.executable, "-m", "hqa.factor_repro_cli", *argv],
        cwd=str(config.REPO_DIR),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=1800,
        check=False,
        env=child_env,
    )
    return proc.returncode, proc.stdout


class PlatformFactorAutomationSlice2Port:
    """Exact Platform adapter through final backtest, with no promote method."""

    def __init__(
        self,
        *,
        policy_digest: str,
        gate_dir: Path = config.FACTOR_AUTOMATION_GATE1_DIR,
        experiment_output_dir: Path = config.FACTOR_EXPERIMENT_OUTPUT_DIR,
        propose_runner: ProposeRunner = quant_cli.run_propose_factor,
        auto_review_runner: AutoReviewRunner = quant_cli.run_agent_auto_review,
        backtest_runner: BacktestRunner | None = None,
        final_receipt_verifier: FinalReceiptVerifier = factor_repro.require_final_backtest_receipt,
    ) -> None:
        if _DIGEST_RE.fullmatch(policy_digest) is None:
            raise FactorAutomationError("policy_digest_invalid")
        self.policy_digest = policy_digest
        self.gate_root = Path(gate_dir)
        self.gate_dir = self.gate_root
        self.experiment_output_dir = Path(experiment_output_dir)
        self._propose_runner = propose_runner
        self._auto_review_runner = auto_review_runner
        self._backtest_runner = backtest_runner
        self._final_receipt_verifier = final_receipt_verifier
        self._request: FactorAutomationRequest | None = None
        self._candidate: CandidateReceipt | None = None

    def _candidate_state(
        self,
        *,
        request: FactorAutomationRequest,
        confirmation_id: str,
        candidate: CandidateReceipt,
    ) -> dict[str, object]:
        return {
            "schema_version": "hqa.factor_automation_candidate/v1",
            "automation_id": request.automation_id,
            "intake_receipt_id": request.intake_receipt_id,
            "intake_contract_digest": request.intake_contract_digest,
            "policy_digest": self.policy_digest,
            "confirmation_id": confirmation_id,
            "candidate_id": candidate.candidate_id,
            "manifest_digest": candidate.manifest_digest,
            "source_sha256": candidate.source_sha256,
            "status_at_creation": "pending",
        }

    @staticmethod
    def _canonical_state_bytes(document: dict[str, object]) -> bytes:
        return (
            json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")

    def _recover_candidate(
        self,
        *,
        request: FactorAutomationRequest,
        confirmation_id: str,
    ) -> CandidateReceipt | None:
        path = self.gate_dir / "automation-candidate.json"
        if not path.exists():
            return None
        if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
            raise FactorAutomationError("automation_candidate_state_unsafe")
        raw = path.read_bytes()
        if not raw or len(raw) > 8_192:
            raise FactorAutomationError("automation_candidate_state_invalid")
        try:
            payload = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise FactorAutomationError("automation_candidate_state_invalid") from exc
        if not isinstance(payload, dict) or raw != self._canonical_state_bytes(payload):
            raise FactorAutomationError("automation_candidate_state_invalid")
        candidate = CandidateReceipt(
            candidate_id=str(payload.get("candidate_id", "")),
            manifest_digest=str(payload.get("manifest_digest", "")),
            source_sha256=str(payload.get("source_sha256", "")),
            status=str(payload.get("status_at_creation", "")),  # type: ignore[arg-type]
        )
        expected = self._candidate_state(
            request=request,
            confirmation_id=confirmation_id,
            candidate=candidate,
        )
        if payload != expected:
            raise FactorAutomationError("automation_candidate_state_drift")
        _validate_candidate(candidate, request)
        try:
            factor_repro.require_gate1_candidate_binding(
                gate_dir=self.gate_dir,
                candidate_id=candidate.candidate_id,
                manifest_digest=candidate.manifest_digest,
                confirmation_id=confirmation_id,
                source_digest=request.source_sha256,
            )
        except (OSError, ValueError) as exc:
            raise FactorAutomationError("machine_gate1_binding_failed") from exc
        return candidate

    def _persist_candidate(
        self,
        *,
        request: FactorAutomationRequest,
        confirmation_id: str,
        candidate: CandidateReceipt,
    ) -> None:
        path = self.gate_dir / "automation-candidate.json"
        raw = self._canonical_state_bytes(
            self._candidate_state(
                request=request,
                confirmation_id=confirmation_id,
                candidate=candidate,
            )
        )
        try:
            with path.open("xb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(path, 0o600)
        except FileExistsError:
            recovered = self._recover_candidate(
                request=request,
                confirmation_id=confirmation_id,
            )
            if recovered != candidate:
                raise FactorAutomationError("automation_candidate_state_conflict")
        except OSError as exc:
            raise FactorAutomationError("automation_candidate_state_unavailable") from exc

    def propose(self, request: FactorAutomationRequest) -> CandidateReceipt:
        self.gate_dir = self.gate_root / request.automation_id
        source = Path(request.source_file_ref)
        try:
            source_bytes = source.read_bytes()
        except OSError as exc:
            raise FactorAutomationError("source_unavailable") from exc
        if hashlib.sha256(source_bytes).hexdigest() != request.source_sha256:
            raise FactorAutomationError("source_digest_drift")
        note = f"auto:intake:{request.intake_receipt_id}:policy:{self.policy_digest}"
        try:
            confirmation_id, source_digest, staged_source = (
                factor_repro.prepare_gate1_confirmation(
                    goal=request.goal,
                    universe=",".join(request.universe),
                    source_file=str(source),
                    expected_source_digest=request.source_sha256,
                    confirmation_note=note,
                    gate_dir=self.gate_dir,
                )
            )
            recovered = self._recover_candidate(
                request=request,
                confirmation_id=confirmation_id,
            )
            if recovered is not None:
                self._request = request
                self._candidate = recovered
                return recovered
            code, output = self._propose_runner(
                request.goal,
                staged_source,
                ",".join(request.universe),
            )
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise FactorAutomationError("candidate_proposal_failed") from exc
        payload = factor_repro.parse_json_payload(output) or {}
        candidate = CandidateReceipt(
            candidate_id=str(payload.get("candidate_id", "")),
            manifest_digest=str(payload.get("manifest_digest", "")),
            source_sha256=str(payload.get("source_sha256", "")),
            status=str(payload.get("status", "")),  # type: ignore[arg-type]
        )
        if code != 0:
            raise FactorAutomationError("candidate_proposal_failed")
        _validate_candidate(candidate, request)
        try:
            factor_repro.record_gate1_candidate_binding(
                gate_dir=self.gate_dir,
                confirmation_id=confirmation_id,
                source_digest=source_digest,
                candidate_id=candidate.candidate_id,
                manifest_digest=candidate.manifest_digest,
            )
        except (OSError, ValueError) as exc:
            raise FactorAutomationError("machine_gate1_binding_failed") from exc
        self._persist_candidate(
            request=request,
            confirmation_id=confirmation_id,
            candidate=candidate,
        )
        self._request = request
        self._candidate = candidate
        return candidate

    def machine_approve(
        self,
        *,
        candidate_id: str,
        expected_manifest_digest: str,
        policy_digest: str,
        note: str,
    ) -> MachineApprovalReceipt:
        request = self._request
        candidate = self._candidate
        if (
            request is None
            or candidate is None
            or candidate.candidate_id != candidate_id
            or candidate.manifest_digest != expected_manifest_digest
            or policy_digest != self.policy_digest
            or note != f"auto:policy:{self.policy_digest}"
        ):
            raise FactorAutomationError("machine_approval_request_drift")
        try:
            factor_repro.require_gate1_candidate_binding(
                gate_dir=self.gate_dir,
                candidate_id=candidate_id,
                manifest_digest=expected_manifest_digest,
            )
            code, output = self._auto_review_runner(
                candidate_id=candidate_id,
                expected_manifest_digest=expected_manifest_digest,
                expected_status="pending",
                policy_digest=policy_digest,
                intake_contract_digest=request.intake_contract_digest,
            )
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise FactorAutomationError("machine_approval_failed") from exc
        payload = factor_repro.parse_json_payload(output) or {}
        receipt = MachineApprovalReceipt(
            candidate_id=str(payload.get("candidate_id", "")),
            manifest_digest=str(payload.get("manifest_digest", "")),
            reviewer=str(payload.get("reviewer", "")),  # type: ignore[arg-type]
            registration=str(payload.get("registration", "")),  # type: ignore[arg-type]
            policy_digest=str(payload.get("policy_digest", "")),
            intake_contract_digest=str(payload.get("intake_contract_digest", "")),
            status=("approved" if payload.get("decision") == "approve" else ""),  # type: ignore[arg-type]
        )
        if code != 0:
            raise FactorAutomationError("machine_approval_failed")
        _validate_approval(
            receipt,
            candidate=candidate,
            request=request,
            policy_digest=self.policy_digest,
        )
        return receipt

    def final_backtest(
        self,
        *,
        request: FactorAutomationRequest,
        candidate: CandidateReceipt,
        approval: MachineApprovalReceipt,
    ) -> FinalBacktestReceipt:
        if request != self._request or candidate != self._candidate:
            raise FactorAutomationError("final_backtest_request_drift")
        argv = [
            "backtest",
            "--candidate-id",
            candidate.candidate_id,
            "--expected-digest",
            candidate.manifest_digest,
        ]
        for symbol in request.universe:
            argv.extend(["--symbol", symbol])
        argv.extend(
            [
                "--start",
                request.start,
                "--end",
                request.end,
                "--provider",
                request.provider,
                "--commission-bps",
                str(request.policy_evidence.transaction_cost_bps / 2.0),
                "--slippage-bps",
                str(request.policy_evidence.transaction_cost_bps / 2.0),
                "--automation-evidence-holdout-days",
                "183",
                "--final",
            ]
        )
        try:
            if self._backtest_runner is None:
                code, output = _run_backtest_cli(
                    argv,
                    gate_dir=self.gate_dir,
                    experiment_output_dir=self.experiment_output_dir,
                )
            else:
                code, output = self._backtest_runner(argv)
        except (OSError, subprocess.SubprocessError) as exc:
            raise FactorAutomationError("final_backtest_failed") from exc
        matches = re.findall(
            r"(?m)^final_backtest_receipt=(backtest-[0-9a-f]{32})$",
            output,
        )
        if code != 0 or len(matches) != 1:
            raise FactorAutomationError("final_backtest_failed")
        receipt_id = matches[0]
        try:
            verified = self._final_receipt_verifier(
                gate_dir=self.gate_dir,
                experiment_output_dir=self.experiment_output_dir,
                receipt_id=receipt_id,
                candidate_id=candidate.candidate_id,
                manifest_digest=candidate.manifest_digest,
            )
        except (OSError, ValueError) as exc:
            raise FactorAutomationError("final_backtest_receipt_invalid") from exc
        policy_evidence = verified.get("verified_policy_evidence")
        if (
            not isinstance(policy_evidence, dict)
            or set(policy_evidence)
            != {
                "sample_rows",
                "out_of_sample_rows",
                "data_coverage_ratio",
                "transaction_cost_bps",
                "max_drawdown",
                "turnover",
            }
        ):
            raise FactorAutomationError("final_backtest_policy_evidence_invalid")
        return FinalBacktestReceipt(
            receipt_id=receipt_id,
            candidate_id=candidate.candidate_id,
            manifest_digest=candidate.manifest_digest,
            source_sha256=request.source_sha256,
            intake_receipt_id=request.intake_receipt_id,
            policy_digest=approval.policy_digest,
            provider=request.provider,
            final=True,
            actual_sample_rows=policy_evidence["sample_rows"],
            actual_out_of_sample_rows=policy_evidence["out_of_sample_rows"],
            actual_data_coverage_ratio=policy_evidence["data_coverage_ratio"],
            actual_transaction_cost_bps=policy_evidence["transaction_cost_bps"],
            actual_max_drawdown=policy_evidence["max_drawdown"],
            actual_turnover=policy_evidence["turnover"],
        )


PromotionRunner = Callable[..., tuple[int, str]]
Gate3Verifier = Callable[..., dict[str, Any]]


class PlatformFactorPromotionPort:
    """HQA-side verifier for separate prepare, commit, and local ff land calls."""

    _STATUS_FIELDS = {
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

    def __init__(
        self,
        *,
        gate_dir: Path,
        experiment_output_dir: Path,
        prepare_runner: PromotionRunner = quant_cli.run_auto_promote_prepare,
        commit_runner: PromotionRunner = quant_cli.run_auto_promote_commit,
        authorize_runner: PromotionRunner = quant_cli.run_factor_automation_authorize_land,
        land_runner: PromotionRunner = quant_cli.run_auto_promote_land,
        activate_runner: PromotionRunner = quant_cli.run_factor_automation_activate_sleeve,
        gate3_verifier: Gate3Verifier = factor_repro.verify_gate3_receipt,
    ) -> None:
        self.gate_dir = Path(gate_dir)
        self.experiment_output_dir = Path(experiment_output_dir)
        self._prepare_runner = prepare_runner
        self._commit_runner = commit_runner
        self._authorize_runner = authorize_runner
        self._land_runner = land_runner
        self._activate_runner = activate_runner
        self._gate3_verifier = gate3_verifier

    @staticmethod
    def _status(output: str) -> dict[str, Any]:
        payload = factor_repro.parse_json_payload(output)
        if not isinstance(payload, dict) or set(payload) != PlatformFactorPromotionPort._STATUS_FIELDS:
            raise FactorAutomationError("automatic_promotion_status_invalid")
        return payload

    def prepare_commit_land(
        self,
        *,
        slice2: FactorAutomationSlice2Result,
        request: FactorAutomationRequest,
        base_commit: str,
    ) -> AutomaticPaperLandResult:
        if _GIT_COMMIT_RE.fullmatch(base_commit) is None:
            raise FactorAutomationError("base_commit_invalid")
        candidate = slice2.candidate
        final = slice2.final_backtest
        try:
            final_record = factor_repro.require_final_backtest_receipt(
                gate_dir=self.gate_dir,
                experiment_output_dir=self.experiment_output_dir,
                receipt_id=final.receipt_id,
                candidate_id=candidate.candidate_id,
                manifest_digest=candidate.manifest_digest,
            )
            code, output = self._prepare_runner(
                candidate_id=candidate.candidate_id,
                expected_manifest_digest=candidate.manifest_digest,
                final_backtest_receipt=final.receipt_id,
                base_commit=base_commit,
                policy_digest=slice2.policy_decision.policy_digest,
                intake_contract_digest=request.intake_contract_digest,
            )
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise FactorAutomationError("automatic_promotion_prepare_failed") from exc
        receipt = factor_repro.parse_json_payload(output) or {}
        if (
            code != 0
            or set(receipt) != {"promotion_id", "worktree", "patch", "manifest"}
            or _PROMOTION_ID_RE.fullmatch(str(receipt.get("promotion_id", ""))) is None
        ):
            raise FactorAutomationError("automatic_promotion_prepare_failed")
        raw_agent_root = os.environ.get("QS_AGENT_OUTPUT_DIR")
        agent_root = (
            Path(raw_agent_root)
            if raw_agent_root
            else config.AIQP_DIR / "data" / "agent_run"
        )
        try:
            self._gate3_verifier(
                receipt,
                candidate_id=candidate.candidate_id,
                manifest_digest=candidate.manifest_digest,
                final_backtest_receipt_id=final.receipt_id,
                factor_id=str(final_record["factor_id"]),
                base_commit=base_commit,
                promotion_root=agent_root / "agent" / "promotions",
                worktree_root=Path(tempfile.gettempdir())
                / "ai-quant-platform-gate3-worktrees",
            )
            commit_code, commit_output = self._commit_runner(
                promotion_id=receipt["promotion_id"]
            )
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise FactorAutomationError("automatic_promotion_commit_failed") from exc
        committed = self._status(commit_output)
        reviewed_commit = committed.get("reviewed_commit")
        if (
            commit_code != 0
            or committed.get("promotion_id") != receipt["promotion_id"]
            or committed.get("status") not in {"reviewed", "landed"}
            or committed.get("candidate_id") != candidate.candidate_id
            or committed.get("candidate_digest") != candidate.manifest_digest
            or committed.get("final_backtest_receipt_id") != final.receipt_id
            or committed.get("base_commit") != base_commit
            or type(reviewed_commit) is not str
            or _GIT_COMMIT_RE.fullmatch(reviewed_commit) is None
        ):
            raise FactorAutomationError("automatic_promotion_commit_failed")
        gate2_digest = hashlib.sha256(
            (
                json.dumps(
                    {
                        "candidate_id": slice2.approval.candidate_id,
                        "intake_contract_digest": (
                            slice2.approval.intake_contract_digest
                        ),
                        "manifest_digest": slice2.approval.manifest_digest,
                        "policy_digest": slice2.approval.policy_digest,
                        "registration": slice2.approval.registration,
                        "reviewer": slice2.approval.reviewer,
                        "status": slice2.approval.status,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("utf-8")
        ).hexdigest()
        try:
            authorize_code, authorize_output = self._authorize_runner(
                automation_id=request.automation_id,
                promotion_id=receipt["promotion_id"],
                policy_digest=slice2.policy_decision.policy_digest,
                intake_contract_digest=request.intake_contract_digest,
                gate1_digest=request.source_sha256,
                gate2_digest=gate2_digest,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise FactorAutomationError("automatic_land_authority_failed") from exc
        authorization = factor_repro.parse_json_payload(authorize_output)
        lineage = authorization.get("lineage") if isinstance(authorization, dict) else None
        expected_lineage = {
            "automation_id": request.automation_id,
            "candidate_id": candidate.candidate_id,
            "candidate_digest": candidate.manifest_digest,
            "factor_id": str(final_record["factor_id"]),
            "manifest_digest": committed.get("manifest_sha256"),
            "automation_policy_digest": slice2.policy_decision.policy_digest,
            "intake_contract_digest": request.intake_contract_digest,
            "gate1_digest": request.source_sha256,
            "gate2_digest": gate2_digest,
            "gate3_digest": committed.get("patch_sha256"),
            "commit_sha": reviewed_commit,
        }
        if (
            authorize_code != 0
            or not isinstance(authorization, dict)
            or set(authorization) != {"state", "lineage", "audit"}
            or authorization.get("state") != "land_authorized"
            or lineage != expected_lineage
        ):
            raise FactorAutomationError("automatic_land_authority_failed")
        try:
            land_code, land_output = self._land_runner(
                promotion_id=receipt["promotion_id"],
                expected_base_commit=base_commit,
                expected_reviewed_commit=reviewed_commit,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise FactorAutomationError("automatic_promotion_land_failed") from exc
        landed = self._status(land_output)
        if (
            land_code != 0
            or landed.get("promotion_id") != receipt["promotion_id"]
            or landed.get("status") != "landed"
            or landed.get("reviewed_commit") != reviewed_commit
            or landed.get("base_commit") != base_commit
        ):
            raise FactorAutomationError("automatic_promotion_land_failed")
        try:
            activate_code, activate_output = self._activate_runner(
                lineage=expected_lineage,
                promotion_id=receipt["promotion_id"],
                universe=request.universe,
                provider=request.provider,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise FactorAutomationError("automatic_sleeve_activation_failed") from exc
        activated = factor_repro.parse_json_payload(activate_output)
        if (
            activate_code != 0
            or not isinstance(activated, dict)
            or set(activated)
            != {
                "state",
                "sleeve_id",
                "allocated_cash",
                "promotion_scope",
                "audit",
            }
            or activated.get("state") != "sleeve_created"
            or activated.get("promotion_scope") != "paper_only"
            or _SAFE_ID_RE.fullmatch(str(activated.get("sleeve_id", ""))) is None
            or isinstance(activated.get("allocated_cash"), bool)
            or not isinstance(activated.get("allocated_cash"), (int, float))
            or float(activated["allocated_cash"]) <= 0
        ):
            raise FactorAutomationError("automatic_sleeve_activation_failed")
        return AutomaticPaperLandResult(
            state="landed",
            promotion_id=receipt["promotion_id"],
            base_commit=base_commit,
            reviewed_commit=reviewed_commit,
            local_head=reviewed_commit,
            pushed=False,
            promotion_scope="paper_only",
            sleeve_id=str(activated["sleeve_id"]),
            allocated_cash=float(activated["allocated_cash"]),
        )


def run_to_paper_land(
    *,
    request: FactorAutomationRequest,
    policy: LoadedFactorAutomationPolicy,
    slice2_port: FactorAutomationSlice2Port,
    promotion_port: FactorAutomationPromotionPort,
    base_commit: str,
    hqa_mode_enabled: bool,
    hqa_auto_land_enabled: bool,
) -> FactorAutomationFullResult:
    """Run the dual-flag paper-only path; no implementation can push or go live."""
    if hqa_mode_enabled is not True or hqa_auto_land_enabled is not True:
        raise FactorAutomationDisabled("factor_automation_disabled")
    slice2 = run_to_final_backtest(
        request=request,
        policy=policy,
        port=slice2_port,
        allow_acceptance_machine_approval=True,
    )
    landed = promotion_port.prepare_commit_land(
        slice2=slice2,
        request=request,
        base_commit=base_commit,
    )
    if landed.promotion_scope != "paper_only" or landed.pushed is not False:
        raise FactorAutomationError("automatic_land_boundary_drift")
    return FactorAutomationFullResult(slice2=slice2, land=landed)


__all__ = [
    "AutomaticPaperLandResult",
    "CandidateReceipt",
    "FactorAutomationDisabled",
    "FactorAutomationError",
    "FactorAutomationRequest",
    "FactorAutomationFullResult",
    "FactorAutomationPromotionPort",
    "FactorAutomationSlice2Port",
    "FactorAutomationSlice2Result",
    "FinalBacktestReceipt",
    "MachineApprovalReceipt",
    "PlatformFactorAutomationSlice2Port",
    "PlatformFactorPromotionPort",
    "run_to_final_backtest",
    "run_to_paper_land",
]

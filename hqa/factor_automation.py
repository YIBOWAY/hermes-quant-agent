"""Fail-closed paper factor automation pipeline.

Slice 2 exposes the repeatable pipeline only through an explicit acceptance
switch and deliberately stops at a content-bound final backtest receipt.  The
production dual flags, durable driver, Gate-3 commit, and local ff-land are
added later; this module has no promotion method by design.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
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


@dataclass(frozen=True)
class FactorAutomationSlice2Result:
    state: Literal["final_backtest_ready"]
    candidate: CandidateReceipt
    approval: MachineApprovalReceipt
    final_backtest: FinalBacktestReceipt
    policy_decision: FactorAutomationDecision
    promotion_performed: Literal[False] = False


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
    _validate_request(request)
    decision = evaluate_factor_automation_policy(policy, request.policy_evidence)
    if not decision.accepted:
        raise FactorAutomationError(
            "policy_refused:" + ",".join(decision.reasons)
        )
    candidate = port.propose(request)
    _validate_candidate(candidate, request)
    approval = port.machine_approve(
        candidate_id=candidate.candidate_id,
        expected_manifest_digest=candidate.manifest_digest,
        policy_digest=decision.policy_digest,
        note=f"auto:policy:{decision.policy_digest}",
    )
    _validate_approval(
        approval,
        candidate=candidate,
        request=request,
        policy_digest=decision.policy_digest,
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
    return FactorAutomationSlice2Result(
        state="final_backtest_ready",
        candidate=candidate,
        approval=approval,
        final_backtest=final_backtest,
        policy_decision=decision,
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
        self.gate_dir = Path(gate_dir)
        self.experiment_output_dir = Path(experiment_output_dir)
        self._propose_runner = propose_runner
        self._auto_review_runner = auto_review_runner
        self._backtest_runner = backtest_runner
        self._final_receipt_verifier = final_receipt_verifier
        self._request: FactorAutomationRequest | None = None
        self._candidate: CandidateReceipt | None = None

    def propose(self, request: FactorAutomationRequest) -> CandidateReceipt:
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
            self._final_receipt_verifier(
                gate_dir=self.gate_dir,
                experiment_output_dir=self.experiment_output_dir,
                receipt_id=receipt_id,
                candidate_id=candidate.candidate_id,
                manifest_digest=candidate.manifest_digest,
            )
        except (OSError, ValueError) as exc:
            raise FactorAutomationError("final_backtest_receipt_invalid") from exc
        return FinalBacktestReceipt(
            receipt_id=receipt_id,
            candidate_id=candidate.candidate_id,
            manifest_digest=candidate.manifest_digest,
            source_sha256=request.source_sha256,
            intake_receipt_id=request.intake_receipt_id,
            policy_digest=approval.policy_digest,
            provider=request.provider,
            final=True,
        )


__all__ = [
    "CandidateReceipt",
    "FactorAutomationDisabled",
    "FactorAutomationError",
    "FactorAutomationRequest",
    "FactorAutomationSlice2Port",
    "FactorAutomationSlice2Result",
    "FinalBacktestReceipt",
    "MachineApprovalReceipt",
    "PlatformFactorAutomationSlice2Port",
    "run_to_final_backtest",
]

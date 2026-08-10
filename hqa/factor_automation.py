"""Fail-closed paper factor automation pipeline.

Slice 2 exposes the repeatable pipeline only through an explicit acceptance
switch and deliberately stops at a content-bound final backtest receipt.  The
production dual flags, durable driver, Gate-3 commit, and local ff-land are
added later; this module has no promotion method by design.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal, Protocol

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
    policy_digest: str,
) -> None:
    if (
        approval.candidate_id != candidate.candidate_id
        or approval.manifest_digest != candidate.manifest_digest
        or approval.reviewer != "auto"
        or approval.registration != "auto_promote"
        or approval.policy_digest != policy_digest
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


__all__ = [
    "CandidateReceipt",
    "FactorAutomationDisabled",
    "FactorAutomationError",
    "FactorAutomationRequest",
    "FactorAutomationSlice2Port",
    "FactorAutomationSlice2Result",
    "FinalBacktestReceipt",
    "MachineApprovalReceipt",
    "run_to_final_backtest",
]

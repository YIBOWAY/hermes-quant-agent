"""Persistent-driver entrypoint for the local paper-only factor pipeline."""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from hqa import config
from hqa.factor_automation import (
    FactorAutomationRequest,
    PlatformFactorAutomationSlice2Port,
    PlatformFactorPromotionPort,
    run_to_paper_land,
)
from hqa.factor_automation_policy import (
    FactorAutomationEvidence,
    load_factor_automation_policy,
)


_REQUEST_FIELDS = {
    "schema_version",
    "automation_id",
    "intake_receipt_id",
    "intake_contract_digest",
    "source_file_ref",
    "source_sha256",
    "goal",
    "universe",
    "provider",
    "start",
    "end",
    "base_commit",
    "policy_evidence",
}
_EVIDENCE_FIELDS = {
    "universe",
    "sample_rows",
    "out_of_sample_rows",
    "data_coverage_ratio",
    "transaction_cost_bps",
    "max_drawdown",
    "turnover",
    "lookahead_static_check_passed",
}


class FactorAutomationDriverError(RuntimeError):
    pass


def _canonical_bytes(document: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def parse_request(document: object) -> tuple[FactorAutomationRequest, str]:
    if not isinstance(document, dict) or set(document) != _REQUEST_FIELDS:
        raise FactorAutomationDriverError("request_schema_invalid")
    if document.get("schema_version") != "hqa.factor_automation_request/v1":
        raise FactorAutomationDriverError("request_schema_invalid")
    evidence = document.get("policy_evidence")
    universe = document.get("universe")
    if (
        not isinstance(evidence, dict)
        or set(evidence) != _EVIDENCE_FIELDS
        or not isinstance(universe, list)
        or evidence.get("universe") != universe
    ):
        raise FactorAutomationDriverError("request_evidence_invalid")
    try:
        policy_evidence = FactorAutomationEvidence(
            universe=tuple(evidence["universe"]),
            sample_rows=evidence["sample_rows"],
            out_of_sample_rows=evidence["out_of_sample_rows"],
            data_coverage_ratio=evidence["data_coverage_ratio"],
            transaction_cost_bps=evidence["transaction_cost_bps"],
            max_drawdown=evidence["max_drawdown"],
            turnover=evidence["turnover"],
            lookahead_static_check_passed=evidence["lookahead_static_check_passed"],
        )
        request = FactorAutomationRequest(
            automation_id=document["automation_id"],
            intake_receipt_id=document["intake_receipt_id"],
            intake_contract_digest=document["intake_contract_digest"],
            source_file_ref=document["source_file_ref"],
            source_sha256=document["source_sha256"],
            goal=document["goal"],
            universe=tuple(universe),
            provider=document["provider"],
            start=document["start"],
            end=document["end"],
            policy_evidence=policy_evidence,
        )
        base_commit = document["base_commit"]
    except (KeyError, TypeError, ValueError) as exc:
        raise FactorAutomationDriverError("request_values_invalid") from exc
    if type(base_commit) is not str:
        raise FactorAutomationDriverError("request_values_invalid")
    return request, base_commit


def _read_request(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
        raise FactorAutomationDriverError("request_file_unsafe")
    raw = path.read_bytes()
    if not raw or len(raw) > 64_000:
        raise FactorAutomationDriverError("request_file_invalid")
    try:
        document = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise FactorAutomationDriverError("request_file_invalid") from exc
    if not isinstance(document, dict):
        raise FactorAutomationDriverError("request_file_invalid")
    return document


def _write_result(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    raw = _canonical_bytes(document)
    if path.exists():
        if path.read_bytes() != raw:
            raise FactorAutomationDriverError("run_result_conflict")
        return
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(path, 0o600)


def _flags_enabled() -> tuple[bool, bool]:
    return (
        os.environ.get("HQA_FACTOR_AUTOMATION_MODE") == "true",
        os.environ.get("HQA_FACTOR_AUTOMATION_AUTO_LAND") == "true",
    )


def run_once() -> dict[str, Any]:
    mode, auto_land = _flags_enabled()
    if not mode or not auto_land:
        return {"state": "disabled", "mode": mode, "auto_land": auto_land}
    queue = config.FACTOR_AUTOMATION_QUEUE_DIR
    if not queue.exists():
        return {"state": "idle", "queued": 0}
    if queue.is_symlink() or not queue.is_dir():
        raise FactorAutomationDriverError("queue_unsafe")
    requests = sorted(path for path in queue.glob("*.json") if path.is_file())
    if not requests:
        return {"state": "idle", "queued": 0}
    path = requests[0]
    request, base_commit = parse_request(_read_request(path))
    policy = load_factor_automation_policy(
        config.REPO_DIR / "config" / "factor_automation_policy.v1.json"
    )
    slice2_port = PlatformFactorAutomationSlice2Port(policy_digest=policy.policy_digest)
    result = run_to_paper_land(
        request=request,
        policy=policy,
        slice2_port=slice2_port,
        promotion_port=PlatformFactorPromotionPort(
            gate_dir=config.FACTOR_AUTOMATION_GATE1_DIR / request.automation_id,
            experiment_output_dir=config.FACTOR_EXPERIMENT_OUTPUT_DIR,
        ),
        base_commit=base_commit,
        hqa_mode_enabled=mode,
        hqa_auto_land_enabled=auto_land,
    )
    document = {
        "schema_version": "hqa.factor_automation_run/v1",
        **dataclasses.asdict(result),
    }
    _write_result(config.FACTOR_AUTOMATION_RUN_DIR / f"{request.automation_id}.json", document)
    completed = queue / "completed"
    completed.mkdir(mode=0o700, exist_ok=True)
    target = completed / path.name
    if target.exists():
        if target.read_bytes() != path.read_bytes():
            raise FactorAutomationDriverError("completed_request_conflict")
        path.unlink()
    else:
        os.replace(path, target)
    return {"state": "landed", "automation_id": request.automation_id}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hqa-factor-automation")
    parser.add_argument("command", choices=("run-once",))
    parser.parse_args(list(argv) if argv is not None else None)
    try:
        result = run_once()
    except Exception as exc:  # noqa: BLE001 - launchd gets a bounded code only
        print(json.dumps({"state": "failed", "code": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

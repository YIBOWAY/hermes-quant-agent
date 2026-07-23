from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import secrets
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from hqa import config, factor_repro, holdout, quant_cli, trials

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_CANDIDATE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_GIT_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_PROMOTION_ID_RE = re.compile(
    r"^promo-[0-9a-f]{32}(?:-r(?:[2-9]|[1-9][0-9]+))?$"
)
_APPROVE_ARGS_TEMPLATE = (
    '--candidate-id {candidate_id} --expected-digest {digest} '
    '--expected-status pending --note "<translation-review>"'
)


def _write_experiment_config(
    path: Path,
    candidate_id: str,
    manifest_digest: str,
    symbols: list[str],
    start: str,
    end: str,
) -> None:
    experiment = {
        "experiment_name": f"factor-repro-{candidate_id}",
        "symbols": symbols,
        "start": start,
        "end": end,
        # The platform replaces this provisional value with the factor_id
        # derived from the exact verified candidate snapshot before execution.
        "factor_blend": {"factors": [{"factor_id": candidate_id}]},
        "candidate_request": {
            "candidate_id": candidate_id,
            "manifest_digest": manifest_digest,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(experiment, indent=2, sort_keys=True))
        handle.write("\n")


def _default_config_path(candidate_id: str, manifest_digest: str) -> Path:
    run_token = secrets.token_hex(8)
    filename = f"{candidate_id}-{manifest_digest[:12]}-{run_token}.json"
    return config.REPO_DIR / "data" / "_runtime" / "experiments" / filename


def _print_verified_pending(
    *,
    candidate_id: str,
    manifest_digest: str,
    status: str = "pending",
) -> None:
    print(f"candidate_id={candidate_id}")
    print(f"manifest_digest={manifest_digest}")
    print(f"status={status}")
    print(f"approve_cmd={_approval_command(candidate_id, manifest_digest)}")


def _approval_command(candidate_id: str, manifest_digest: str) -> str:
    return (
        f"cd {shlex.quote(str(config.REPO_DIR))} && "
        "python3 -m hqa.factor_repro_cli approve "
        + _APPROVE_ARGS_TEMPLATE.format(
            candidate_id=candidate_id,
            digest=manifest_digest,
        )
    )


def _print_gate3_recovery(receipt: Optional[dict]) -> None:
    promotion_id = receipt.get("promotion_id") if isinstance(receipt, dict) else None
    if isinstance(promotion_id, str) and _PROMOTION_ID_RE.fullmatch(promotion_id):
        print(
            json.dumps(
                {
                    "state": "prepared_but_unverified",
                    "promotion_id": promotion_id,
                    "recovery": "use promotion-status; cleanup requires explicit policy",
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )


def _exception_output(exc: BaseException) -> str:
    value = getattr(exc, "stdout", None)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value if isinstance(value, str) else ""


def _platform_gate3_roots() -> tuple[Path, Path]:
    raw_agent_root = os.environ.get("QS_AGENT_OUTPUT_DIR")
    if raw_agent_root is None:
        agent_root = config.AIQP_DIR / "data" / "agent_run"
    else:
        expanded = Path(raw_agent_root).expanduser()
        agent_root = expanded if expanded.is_absolute() else config.AIQP_DIR / expanded
    agent_root = Path(os.path.abspath(agent_root))
    promotion_root = agent_root / "agent" / "promotions"
    worktree_root = Path(tempfile.gettempdir()) / "ai-quant-platform-gate3-worktrees"
    return promotion_root, worktree_root


def _redact_platform_approve_command(line: str) -> str:
    """Keep list evidence human-readable without exposing a Gate-1 bypass command."""
    marker = " approve_cmd="
    if marker not in line:
        return line
    # The platform's legacy line is not escaped, so a legal path can contain
    # another `approve_cmd=` token. Everything after the first authority marker
    # is therefore untrusted and must be dropped, including the display-only path.
    return line.partition(marker)[0]


def _has_gate1_binding(fields: dict[str, str]) -> bool:
    candidate_id = fields.get("candidate_id", "")
    digest = fields.get("manifest_digest", "")
    if not candidate_id or _DIGEST_RE.fullmatch(digest) is None:
        return False
    try:
        factor_repro.require_gate1_candidate_binding(
            gate_dir=config.FACTOR_GATE1_DIR,
            candidate_id=candidate_id,
            manifest_digest=digest,
        )
    except (OSError, ValueError):
        return False
    return True


def _print_list_item(fields: dict[str, str], *, gate1_bound: bool = False) -> None:
    candidate_id = fields.get("candidate_id", "?")
    integrity = fields.get("integrity", fields.get("integrity_state", ""))
    status = fields.get("status", "")
    print(f"candidate_id={candidate_id} integrity={integrity or '?'} status={status or '?'}")
    if integrity == "verified":
        digest = fields.get("manifest_digest", "")
        if digest:
            print(f"  manifest_digest={digest}")
        can_approve = (
            status == "pending"
            and fields.get("approval_enabled", "").lower() == "true"
            and _DIGEST_RE.fullmatch(digest) is not None
            and candidate_id != "?"
            and gate1_bound
        )
        if can_approve:
            print(f"  approve_cmd={_approval_command(candidate_id, digest)}")
        else:
            if (
                status == "pending"
                and fields.get("approval_enabled", "").lower() == "true"
                and _DIGEST_RE.fullmatch(digest) is not None
            ):
                print("  gate1_binding=false")
            print("  approval_enabled=false")
    elif integrity == "migration_required":
        observed = fields.get("observed_manifest_digest", "")
        if observed:
            print(f"  observed_manifest_digest={observed}")
        print("  migration evidence; approval disabled")
    elif integrity == "corrupt":
        print("  corrupt; no digest/source; approval disabled")
    else:
        # Unknown/legacy lines are evidence only; never infer Gate 2 authority.
        digest = fields.get("manifest_digest") or fields.get("digest")
        if digest:
            print(f"  manifest_digest={digest}")
        print("  approval_enabled=false")


def _validate_approve_args(args: argparse.Namespace) -> Optional[str]:
    if not getattr(args, "candidate_id", None):
        return "missing --candidate-id"
    if not getattr(args, "expected_digest", None):
        return "missing --expected-digest"
    if not getattr(args, "expected_status", None):
        return "missing --expected-status"
    if not getattr(args, "note", None) or not str(args.note).strip():
        return "note must be non-empty"
    if _CANDIDATE_ID_RE.fullmatch(args.candidate_id) is None:
        return "candidate-id must be a safe lowercase identifier"
    if not _DIGEST_RE.fullmatch(args.expected_digest):
        return "expected-digest must be a lowercase 64-char hex sha256"
    if args.expected_status != "pending":
        return "expected-status must be the literal 'pending'"
    return None


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hqa-factor-repro",
        description="Scene-B factor reproduction (proposal-only, human-gated)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_propose = sub.add_parser("propose")
    p_propose.add_argument("--goal", required=True)
    p_propose.add_argument(
        "--source-file",
        required=True,
        dest="source_file",
        help="factor code generated in the Hermes session (D-19)",
    )
    p_propose.add_argument(
        "--expected-source-digest",
        required=True,
        dest="expected_source_digest",
        help="SHA-256 of the exact human-reviewed source bytes (Gate 1)",
    )
    p_propose.add_argument(
        "--confirmation-note",
        required=True,
        dest="confirmation_note",
        help="Non-empty human formula/translation review note (Gate 1)",
    )
    p_propose.add_argument("--universe", default="SPY,QQQ")

    sub.add_parser("list", help="List non-authoritative candidate evidence")
    p_detail = sub.add_parser("detail", help="Show one candidate from list output")
    p_detail.add_argument("--candidate-id", required=True)

    p_approve = sub.add_parser("approve")
    p_approve.add_argument("--candidate-id", required=True)
    p_approve.add_argument(
        "--expected-digest",
        required=True,
        dest="expected_digest",
        help="Authoritative lowercase SHA-256 from a verified detail/propose item",
    )
    p_approve.add_argument(
        "--expected-status",
        required=True,
        choices=("pending",),
        dest="expected_status",
        help="Must be the literal status pending (CAS precondition)",
    )
    p_approve.add_argument("--note", required=True)

    p_backtest = sub.add_parser("backtest")
    p_backtest.add_argument(
        "--candidate-id",
        required=True,
        help="verified candidate_id approved at Gate 2",
    )
    p_backtest.add_argument(
        "--expected-digest",
        required=True,
        dest="expected_digest",
        help="exact lowercase manifest digest approved at Gate 2",
    )
    p_backtest.add_argument("--symbol", action="append", required=True, dest="symbols")
    p_backtest.add_argument("--start", required=True)
    p_backtest.add_argument("--end", required=True)
    p_backtest.add_argument(
        "--provider",
        default=None,
        choices=("futu", "tiingo"),
        help="data provider (default: validated HQA_DEFAULT_DATA_PROVIDER; futu unless explicitly configured)",
    )
    p_backtest.add_argument("--config-out", default=None)
    p_backtest.add_argument(
        "--final",
        action="store_true",
        help="run the FULL window once before promotion; non-final runs reserve the last 183 days (D-21)",
    )

    p_promote = sub.add_parser(
        "promote",
        help="Prepare the Gate 3 review workspace for a Gate-1-bound candidate",
    )
    p_promote.add_argument("--candidate-id", required=True)
    p_promote.add_argument("--expected-digest", required=True, dest="expected_digest")
    p_promote.add_argument(
        "--final-backtest-receipt",
        required=True,
        dest="final_backtest_receipt",
        help="content-addressed receipt ID printed by a successful --final backtest",
    )
    p_promote.add_argument("--base-commit", required=True, dest="base_commit")

    args = parser.parse_args(argv)

    if args.cmd == "propose":
        try:
            confirmation_id, source_digest, staged_source = (
                factor_repro.prepare_gate1_confirmation(
                    goal=args.goal,
                    universe=args.universe,
                    source_file=args.source_file,
                    expected_source_digest=args.expected_source_digest,
                    confirmation_note=args.confirmation_note,
                    gate_dir=config.FACTOR_GATE1_DIR,
                )
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        print(f"gate1_confirmation_id={confirmation_id}")
        print(f"gate1_source_digest={source_digest}")
        try:
            code, out = quant_cli.run_propose_factor(
                args.goal, staged_source, args.universe
            )
        except (OSError, subprocess.SubprocessError) as exc:
            partial = factor_repro.parse_json_payload(_exception_output(exc)) or {}
            candidate_id = partial.get("candidate_id")
            print(
                "ERROR: proposal platform outcome is unknown; no Gate 1 candidate "
                "binding or Gate 2 authority was issued",
                file=sys.stderr,
            )
            if (
                isinstance(candidate_id, str)
                and _CANDIDATE_ID_RE.fullmatch(candidate_id) is not None
            ):
                print(f"candidate_id={candidate_id} outcome_unknown=true")
                print("recovery=inspect_exact_candidate_detail_read_only")
            else:
                print("candidate_id=? outcome_unknown=true")
            return 1
        payload = factor_repro.parse_json_payload(out)
        candidate_id = payload.get("candidate_id") if payload is not None else None
        digest = payload.get("manifest_digest") if payload is not None else None
        candidate_source_digest = (
            payload.get("source_sha256") if payload is not None else None
        )
        status = payload.get("status") if payload is not None else None
        if (
            code == 0
            and isinstance(candidate_id, str)
            and _CANDIDATE_ID_RE.fullmatch(candidate_id) is not None
            and isinstance(digest, str)
            and _DIGEST_RE.fullmatch(digest) is not None
            and candidate_source_digest == source_digest
            and status == "pending"
        ):
            try:
                factor_repro.record_gate1_candidate_binding(
                    gate_dir=config.FACTOR_GATE1_DIR,
                    confirmation_id=confirmation_id,
                    source_digest=source_digest,
                    candidate_id=str(candidate_id),
                    manifest_digest=str(digest),
                )
                # Re-read every canonical Gate 1 record after the write and
                # immediately before printing copyable Gate 2 authority. This
                # also closes mutation windows inside delegated platform work.
                factor_repro.require_gate1_candidate_binding(
                    gate_dir=config.FACTOR_GATE1_DIR,
                    candidate_id=str(candidate_id),
                    manifest_digest=str(digest),
                )
            except (OSError, ValueError) as exc:
                print(
                    f"ERROR: candidate created but Gate 1 binding audit failed: {exc}",
                    file=sys.stderr,
                )
                return 1
            _print_verified_pending(
                candidate_id=str(candidate_id),
                manifest_digest=str(digest),
                status="pending",
            )
            print("HUMAN GATE 2: inspect the bound candidate and decide whether to approve it.")
            print(
                "Copy the approve_cmd values above; Gate 2 never refetches digest/status."
            )
            return 0
        printable_candidate = (
            candidate_id
            if isinstance(candidate_id, str)
            and _CANDIDATE_ID_RE.fullmatch(candidate_id) is not None
            else "?"
        )
        print(f"candidate_id={printable_candidate}")
        print(
            "ERROR: incomplete platform receipt; successful machine JSON with "
            "exact candidate_id, manifest_digest, source_sha256, and status=pending is required "
            "for the Gate 1 binding",
            file=sys.stderr,
        )
        # Never echo mixed platform stdout here: the legacy human line can
        # contain a raw review command even though Gate 1 binding failed.
        print("platform_output_withheld=untrusted_gate1_receipt")
        return 1

    if args.cmd == "list":
        code, out = quant_cli.run_list_candidates()
        if code != 0:
            print(out.strip() or "list-candidates failed", file=sys.stderr)
            return 1
        lines = [line for line in out.splitlines() if line.strip()]
        if not lines or lines == ["no_candidates=true"]:
            print("no_candidates=true")
            return 0
        # Platform list output is human-readable and may contain unquoted paths.
        # Never parse it into candidate authority. Exact review/approval values
        # come only from `detail`, whose final line is a strict JSON bundle.
        print("informational_only=true")
        for line in lines:
            print(_redact_platform_approve_command(line))
        print("use_detail_for_authority=true")
        return 0

    if args.cmd == "detail":
        code, out = quant_cli.run_inspect_factor_candidate(args.candidate_id)
        if code != 0:
            print(out.strip() or "candidate inspection failed", file=sys.stderr)
            return 1
        bundle = factor_repro.parse_json_payload(out) or {}
        digest = bundle.get("manifest_digest")
        if (
            bundle.get("candidate_id") != args.candidate_id
            or not isinstance(digest, str)
            or _DIGEST_RE.fullmatch(digest) is None
            or not isinstance(bundle.get("factor_id"), str)
            or not isinstance(bundle.get("source_path"), str)
            or not isinstance(bundle.get("source"), str)
        ):
            print(f"candidate_id={args.candidate_id} invalid_review_bundle=true")
            return 1
        approval_binding = str(bundle.get("approval_binding", ""))
        fields = {
            "candidate_id": args.candidate_id,
            "integrity": "verified",
            "status": approval_binding,
            "approval_enabled": str(approval_binding == "pending"),
            "manifest_digest": digest,
        }
        _print_list_item(fields, gate1_bound=_has_gate1_binding(fields))
        print(f"factor_id={bundle['factor_id']}")
        print(f"source_path={bundle['source_path']}")
        print("source_begin")
        print(bundle["source"].rstrip())
        print("source_end")
        return 0

    if args.cmd == "approve":
        # Human-only translation gate (gate 2). Scheduled automation must not call this.
        # Never list/refetch/substitute digest or status — caller must supply all four values.
        err = _validate_approve_args(args)
        if err is not None:
            print(f"ERROR: {err}", file=sys.stderr)
            return 2
        try:
            factor_repro.require_gate1_candidate_binding(
                gate_dir=config.FACTOR_GATE1_DIR,
                candidate_id=args.candidate_id,
                manifest_digest=args.expected_digest,
            )
        except (OSError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        try:
            code, out = quant_cli.run_agent_review(
                candidate_id=args.candidate_id,
                decision="approve",
                note=args.note.strip(),
                expected_manifest_digest=args.expected_digest,
                expected_status=args.expected_status,
            )
        except (OSError, subprocess.SubprocessError):
            print(
                "ERROR: approval platform outcome is unknown; do not retry blindly",
                file=sys.stderr,
            )
            print(
                f"candidate_id={args.candidate_id} outcome_unknown=true "
                "recovery=inspect_exact_candidate_detail_read_only"
            )
            return 1
        receipt = factor_repro.parse_json_payload(out)
        if (
            code != 0
            or receipt is None
            or receipt.get("candidate_id") != args.candidate_id
            or receipt.get("manifest_digest") != args.expected_digest
            or receipt.get("decision") != "approve"
            or receipt.get("registration") != "manual_required"
        ):
            if out.strip():
                print(out.strip(), file=sys.stderr)
            print(
                f"ERROR: approval failed for {args.candidate_id}; exact machine receipt required",
                file=sys.stderr,
            )
            return 1
        print(json.dumps(receipt, sort_keys=True))
        return 0

    if args.cmd == "promote":
        if _CANDIDATE_ID_RE.fullmatch(args.candidate_id) is None:
            print("ERROR: candidate-id must be a safe lowercase identifier", file=sys.stderr)
            return 2
        if _DIGEST_RE.fullmatch(args.expected_digest) is None:
            print("ERROR: expected-digest must be a lowercase 64-char hex sha256", file=sys.stderr)
            return 2
        if _GIT_COMMIT_RE.fullmatch(args.base_commit) is None:
            print("ERROR: base-commit must be the exact lowercase 40-char commit SHA", file=sys.stderr)
            return 2
        try:
            factor_repro.require_gate1_candidate_binding(
                gate_dir=config.FACTOR_GATE1_DIR,
                candidate_id=args.candidate_id,
                manifest_digest=args.expected_digest,
            )
            final_backtest = factor_repro.require_final_backtest_receipt(
                gate_dir=config.FACTOR_GATE1_DIR,
                experiment_output_dir=config.FACTOR_EXPERIMENT_OUTPUT_DIR,
                receipt_id=args.final_backtest_receipt,
                candidate_id=args.candidate_id,
                manifest_digest=args.expected_digest,
            )
            factor_id = final_backtest.get("factor_id")
            if (
                not isinstance(factor_id, str)
                or _CANDIDATE_ID_RE.fullmatch(factor_id) is None
            ):
                raise ValueError("final backtest receipt has invalid factor identity")
        except (OSError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        try:
            code, out = quant_cli.run_promote_candidate(
                candidate_id=args.candidate_id,
                expected_manifest_digest=args.expected_digest,
                final_backtest_receipt=args.final_backtest_receipt,
                base_commit=args.base_commit,
            )
        except subprocess.TimeoutExpired as exc:
            partial_receipt = factor_repro.parse_json_payload(
                _exception_output(exc)
            )
            print(
                "ERROR: Gate 3 platform outcome is unknown after timeout; "
                "never retry or abandon blindly",
                file=sys.stderr,
            )
            _print_gate3_recovery(partial_receipt)
            if partial_receipt is None:
                promotion_root, _ = _platform_gate3_roots()
                print(
                    json.dumps(
                        {
                            "state": "prepare_outcome_unknown",
                            "candidate_id": args.candidate_id,
                            "candidate_digest": args.expected_digest,
                            "base_commit": args.base_commit,
                            "promotion_root": str(promotion_root),
                            "recovery": (
                                "inspect promotion_root read-only; for any matching record "
                                "use promotion-status before retry or cleanup"
                            ),
                        },
                        sort_keys=True,
                    ),
                    file=sys.stderr,
                )
            return 1
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"ERROR: Gate 3 platform call failed: {exc}", file=sys.stderr)
            return 1
        receipt = factor_repro.parse_json_payload(out)
        expected_fields = {"promotion_id", "worktree", "patch", "manifest"}
        if (
            code != 0
            or receipt is None
            or set(receipt) != expected_fields
            or any(not isinstance(receipt[field], str) or not receipt[field] for field in expected_fields)
        ):
            if out.strip():
                print("platform_output_withheld=invalid_gate3_receipt", file=sys.stderr)
            print("ERROR: Gate 3 preparation failed; exact four-field machine receipt required", file=sys.stderr)
            _print_gate3_recovery(receipt)
            return 1
        try:
            promotion_root, worktree_root = _platform_gate3_roots()
            gate3_evidence = factor_repro.verify_gate3_receipt(
                receipt,
                candidate_id=args.candidate_id,
                manifest_digest=args.expected_digest,
                final_backtest_receipt_id=args.final_backtest_receipt,
                factor_id=factor_id,
                base_commit=args.base_commit,
                promotion_root=promotion_root,
                worktree_root=worktree_root,
            )
            # Do not advertise a prepared workspace if Gate 1 was changed while
            # the platform was preparing it.
            factor_repro.require_gate1_candidate_binding(
                gate_dir=config.FACTOR_GATE1_DIR,
                candidate_id=args.candidate_id,
                manifest_digest=args.expected_digest,
            )
            factor_repro.require_final_backtest_receipt(
                gate_dir=config.FACTOR_GATE1_DIR,
                experiment_output_dir=config.FACTOR_EXPERIMENT_OUTPUT_DIR,
                receipt_id=args.final_backtest_receipt,
                candidate_id=args.candidate_id,
                manifest_digest=args.expected_digest,
            )
            status_code, status_out = quant_cli.run_promotion_status(
                receipt["promotion_id"]
            )
            status = factor_repro.parse_json_payload(status_out)
            if (
                status_code != 0
                or status is None
                or set(status)
                != {
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
                or status.get("promotion_id") != receipt["promotion_id"]
                or status.get("status") != "awaiting_human_commit"
                or status.get("reviewed_commit") is not None
                or status.get("reason") != "worktree is not clean"
                or not isinstance(gate3_evidence, dict)
                or any(
                    status.get(field) != gate3_evidence.get(field)
                    for field in (
                        "manifest_sha256",
                        "patch_sha256",
                        "candidate_id",
                        "candidate_digest",
                        "final_backtest_receipt_id",
                        "base_commit",
                        "scoped_paths",
                    )
                )
            ):
                raise ValueError("platform promotion status is not awaiting_human_commit")
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            print(f"ERROR: Gate 3 receipt verification failed: {exc}", file=sys.stderr)
            _print_gate3_recovery(receipt)
            return 1
        print(json.dumps(receipt, sort_keys=True))
        return 0

    if args.cmd == "backtest":
        args.provider = args.provider or config.DEFAULT_DATA_PROVIDER
        if args.provider not in {"futu", "tiingo"}:
            print(
                "ERROR: configured default provider must be futu or tiingo; "
                "synthetic providers cannot execute Scene-B backtests",
                file=sys.stderr,
            )
            return 2
        if not _CANDIDATE_ID_RE.fullmatch(args.candidate_id):
            print(
                "ERROR: candidate-id must use lowercase letters, digits, hyphens, "
                "or underscores and may not contain a path"
            )
            return 2
        if not _DIGEST_RE.fullmatch(args.expected_digest):
            print("ERROR: expected-digest must be a lowercase 64-char hex sha256")
            return 2
        try:
            factor_repro.require_gate1_candidate_binding(
                gate_dir=config.FACTOR_GATE1_DIR,
                candidate_id=args.candidate_id,
                manifest_digest=args.expected_digest,
            )
        except (OSError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        try:
            effective_end, holdout_note = holdout.effective_backtest_end(
                args.start, args.end, args.final
            )
        except ValueError as exc:
            print(f"ERROR: {exc}")
            return 1
        config_out = (
            Path(args.config_out)
            if args.config_out
            else _default_config_path(args.candidate_id, args.expected_digest)
        )
        try:
            _write_experiment_config(
                config_out,
                args.candidate_id,
                args.expected_digest,
                args.symbols,
                args.start,
                effective_end,
            )
        except (OSError, ValueError) as exc:
            print(f"ERROR: experiment config write failed: {exc}", file=sys.stderr)
            return 1
        if holdout_note:
            print(holdout_note)
        try:
            code, out = quant_cli.run_experiment_config(
                str(config_out),
                candidate_id=args.candidate_id,
                expected_manifest_digest=args.expected_digest,
                output_dir=str(config.FACTOR_EXPERIMENT_OUTPUT_DIR),
                provider=args.provider,
            )
        except (OSError, subprocess.SubprocessError):
            print(
                "ERROR: backtest platform outcome is unknown; no trial or final "
                "authority was recorded",
                file=sys.stderr,
            )
            print(
                f"candidate_id={args.candidate_id} outcome_unknown=true "
                f"config={config_out} recovery=inspect_platform_artifacts_read_only"
            )
            return 1
        binding = factor_repro.parse_candidate_binding(out)
        if (
            code != 0
            or binding.get("candidate_id") != args.candidate_id
            or binding.get("manifest_digest") != args.expected_digest
            or not binding.get("factor_id")
        ):
            print(out.strip() or "ERROR: platform returned no exact candidate binding")
            return 1
        factor_id = binding["factor_id"]
        receipt = factor_repro.parse_json_payload(out)
        try:
            evidence = factor_repro.verify_experiment_receipt(
                receipt or {},
                platform_dir=config.AIQP_DIR,
                experiment_output_dir=config.FACTOR_EXPERIMENT_OUTPUT_DIR,
                candidate_id=args.candidate_id,
                manifest_digest=args.expected_digest,
                factor_id=factor_id,
                provider=args.provider,
                symbols=args.symbols,
                start=args.start,
                end=effective_end,
            )
        except (OSError, ValueError, TypeError) as exc:
            print(f"ERROR: experiment evidence verification failed: {exc}", file=sys.stderr)
            return 1
        metrics = evidence["metrics"]
        print(
            f"experiment_id={evidence['experiment_id']} "
            f"best_run_id={evidence['best_run_id']}"
        )
        print(
            f"candidate_id={args.candidate_id} manifest_digest={args.expected_digest} "
            f"factor_id={factor_id}"
        )
        for key in ("sharpe", "total_return", "max_drawdown"):
            print(f"{key}={metrics.get(key, '?')}")
        print(f"report={evidence['report']}")
        log_path = Path(config.LOG_DIR) / "factor_trials.jsonl"
        trials.append_trial(
            factor_id,
            {
                "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                "start": args.start,
                "end": effective_end,
                "final": args.final,
                "sharpe": metrics.get("sharpe", "?"),
                "candidate_id": args.candidate_id,
                "manifest_digest": args.expected_digest,
            },
            log_path,
        )
        warning = trials.overfit_warning(factor_id, trials.count_trials(factor_id, log_path))
        if warning:
            print(warning)
        if args.final:
            try:
                receipt_id = factor_repro.record_final_backtest_receipt(
                    gate_dir=config.FACTOR_GATE1_DIR,
                    experiment_output_dir=config.FACTOR_EXPERIMENT_OUTPUT_DIR,
                    candidate_id=args.candidate_id,
                    manifest_digest=args.expected_digest,
                    factor_id=factor_id,
                    experiment_id=evidence["experiment_id"],
                    run_count=evidence["run_count"],
                    best_run_id=evidence["best_run_id"],
                    provider=args.provider,
                    symbols=args.symbols,
                    start=args.start,
                    end=effective_end,
                    config_path=evidence["config_path"],
                    config_sha256=evidence["config_sha256"],
                    agent_summary_path=evidence["agent_summary_path"],
                    agent_summary_sha256=evidence["agent_summary_sha256"],
                    report=evidence["report"],
                    report_sha256=evidence["report_sha256"],
                )
            except (OSError, ValueError) as exc:
                print(f"ERROR: final backtest receipt failed: {exc}", file=sys.stderr)
                return 1
            print(f"final_backtest_receipt={receipt_id}")
        print(
            "Results are research evidence; a successful --final receipt is required "
            "before the separate Gate 3 code-review workspace."
        )
        return 0 if code == 0 else 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path
from typing import Optional

from hqa import config, factor_repro, holdout, quant_cli, trials

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_APPROVE_CMD_TEMPLATE = (
    'approve --candidate-id {candidate_id} --expected-digest {digest} '
    '--expected-status pending --note "<translation-review>"'
)


def _write_experiment_config(path: Path, factor_id: str, symbols: list[str], start: str, end: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    experiment = {
        "experiment_name": f"factor-repro-{factor_id}",
        "symbols": symbols,
        "start": start,
        "end": end,
        "factor_blend": {"factors": [{"factor_id": factor_id}]},
    }
    path.write_text(json.dumps(experiment, indent=2, sort_keys=True), encoding="utf-8")


def _default_config_path(factor_id: str) -> Path:
    return config.REPO_DIR / "data" / "_runtime" / "experiments" / f"{factor_id}.json"


def _parse_kv_line(line: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for token in line.split():
        if "=" not in token:
            continue
        key, _, value = token.partition("=")
        out[key] = value
    return out


def _print_verified_pending(
    *,
    candidate_id: str,
    manifest_digest: str,
    status: str = "pending",
) -> None:
    print(f"candidate_id={candidate_id}")
    print(f"manifest_digest={manifest_digest}")
    print(f"status={status}")
    print(
        "approve_cmd=hqa-factor-repro "
        + _APPROVE_CMD_TEMPLATE.format(candidate_id=candidate_id, digest=manifest_digest)
    )


def _print_list_item(fields: dict[str, str]) -> None:
    candidate_id = fields.get("candidate_id", "?")
    integrity = fields.get("integrity", fields.get("integrity_state", ""))
    status = fields.get("status", "")
    print(f"candidate_id={candidate_id} integrity={integrity or '?'} status={status or '?'}")
    if integrity == "verified" and fields.get("manifest_digest"):
        print(f"  manifest_digest={fields['manifest_digest']}")
        if status == "pending" and fields.get("approval_enabled", "True") not in {
            "False",
            "false",
            "0",
        }:
            print(
                "  approve_cmd=hqa-factor-repro "
                + _APPROVE_CMD_TEMPLATE.format(
                    candidate_id=candidate_id,
                    digest=fields["manifest_digest"],
                )
            )
        else:
            print("  approval_enabled=false")
    elif integrity == "migration_required":
        observed = fields.get("observed_manifest_digest", "")
        if observed:
            print(f"  observed_manifest_digest={observed}")
        print("  migration evidence; approval disabled")
    elif integrity == "corrupt":
        print("  corrupt; no digest/source; approval disabled")
    else:
        # Legacy platform line without integrity field: print raw fields only.
        digest = fields.get("manifest_digest") or fields.get("digest")
        if digest and status == "pending":
            print(f"  manifest_digest={digest}")
            print(
                "  approve_cmd=hqa-factor-repro "
                + _APPROVE_CMD_TEMPLATE.format(candidate_id=candidate_id, digest=digest)
            )


def _validate_approve_args(args: argparse.Namespace) -> Optional[str]:
    if not getattr(args, "candidate_id", None):
        return "missing --candidate-id"
    if not getattr(args, "expected_digest", None):
        return "missing --expected-digest"
    if not getattr(args, "expected_status", None):
        return "missing --expected-status"
    if not getattr(args, "note", None) or not str(args.note).strip():
        return "note must be non-empty"
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
    p_propose.add_argument("--universe", default="SPY,QQQ")

    p_list = sub.add_parser("list", help="List candidates with integrity-aware Gate 2 values")
    p_detail = sub.add_parser("detail", help="Show one candidate from list output")
    p_detail.add_argument("--candidate-id", required=True)

    p_approve = sub.add_parser("approve")
    p_approve.add_argument("--candidate-id", required=True)
    p_approve.add_argument(
        "--expected-digest",
        required=True,
        dest="expected_digest",
        help="Authoritative lowercase SHA-256 from a verified list/detail/propose item",
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
    p_backtest.add_argument("--factor-id", required=True, help="factor_id of the APPROVED candidate")
    p_backtest.add_argument("--symbol", action="append", required=True, dest="symbols")
    p_backtest.add_argument("--start", required=True)
    p_backtest.add_argument("--end", required=True)
    p_backtest.add_argument(
        "--provider",
        default=config.DEFAULT_DATA_PROVIDER,
        help="data provider (default: futu — only configured live source; tiingo is opt-in when token is set)",
    )
    p_backtest.add_argument("--config-out", default=None)
    p_backtest.add_argument(
        "--final",
        action="store_true",
        help="run the FULL window once before promotion; non-final runs reserve the last 183 days (D-21)",
    )

    args = parser.parse_args(argv)

    if args.cmd == "propose":
        code, out = quant_cli.run_propose_factor(args.goal, args.source_file, args.universe)
        candidate_id = factor_repro.parse_candidate_id(out)
        payload = factor_repro.parse_json_payload(out) or {}
        digest = payload.get("manifest_digest")
        if not digest:
            # Prefer authoritative key=value from platform stdout when present.
            for line in out.splitlines():
                fields = _parse_kv_line(line)
                if fields.get("manifest_digest"):
                    digest = fields["manifest_digest"]
                    break
        if candidate_id and digest and _DIGEST_RE.fullmatch(str(digest)):
            _print_verified_pending(
                candidate_id=str(candidate_id),
                manifest_digest=str(digest),
                status="pending",
            )
            print("HUMAN GATE: inspect the generated candidate factor and confirm the translation is correct.")
            print(
                "Copy the approve_cmd values above; Gate 2 never refetches digest/status."
            )
            return 0 if code == 0 else 1
        print(f"candidate_id={candidate_id or '?'}")
        print("HUMAN GATE: inspect the generated candidate factor and confirm the translation is correct.")
        print(
            "Run: hqa-factor-repro approve --candidate-id <id> "
            '--expected-digest <sha256> --expected-status pending --note "<translation-review>"'
        )
        if not candidate_id:
            print(out.strip())
            return 1
        return 0 if code == 0 else 1

    if args.cmd == "list":
        code, out = quant_cli.run_list_candidates()
        if code != 0:
            print(out.strip() or "list-candidates failed", file=sys.stderr)
            return 1
        lines = [line for line in out.splitlines() if line.strip()]
        if not lines or all("no_candidates=true" in line for line in lines):
            print("no_candidates=true")
            return 0
        for line in lines:
            if "candidate_id=" not in line:
                print(line)
                continue
            _print_list_item(_parse_kv_line(line))
        return 0

    if args.cmd == "detail":
        code, out = quant_cli.run_list_candidates()
        if code != 0:
            print(out.strip() or "list-candidates failed", file=sys.stderr)
            return 1
        found = None
        for line in out.splitlines():
            if "candidate_id=" not in line:
                continue
            fields = _parse_kv_line(line)
            if fields.get("candidate_id") == args.candidate_id:
                found = fields
                break
        if found is None:
            print(f"candidate_id={args.candidate_id} not_found=true")
            return 1
        _print_list_item(found)
        return 0

    if args.cmd == "approve":
        # Human-only translation gate (gate 2). Scheduled automation must not call this.
        # Never list/refetch/substitute digest or status — caller must supply all four values.
        err = _validate_approve_args(args)
        if err is not None:
            print(f"ERROR: {err}", file=sys.stderr)
            return 2
        code, out = quant_cli.run_agent_review(
            candidate_id=args.candidate_id,
            decision="approve",
            note=args.note.strip(),
            expected_manifest_digest=args.expected_digest,
            expected_status=args.expected_status,
        )
        print(out.strip() or f"approved: {args.candidate_id}")
        return 0 if code == 0 else 1

    if args.cmd == "backtest":
        try:
            effective_end, holdout_note = holdout.effective_backtest_end(
                args.start, args.end, args.final
            )
        except ValueError as exc:
            print(f"ERROR: {exc}")
            return 1
        config_out = Path(args.config_out) if args.config_out else _default_config_path(args.factor_id)
        _write_experiment_config(config_out, args.factor_id, args.symbols, args.start, effective_end)
        if holdout_note:
            print(holdout_note)
        code, out = quant_cli.run_experiment_config(
            str(config_out),
            provider=args.provider,
            include_approved=True,
        )
        summary = factor_repro.parse_experiment_summary(out)
        metrics: dict[str, float] = {}
        summary_path = summary.get("agent_summary")
        if summary_path:
            path = Path(summary_path)
            if not path.is_absolute():
                path = config.AIQP_DIR / path
            try:
                metrics = factor_repro.extract_best_run_metrics(path.read_text(encoding="utf-8"))
            except OSError:
                metrics = {}
        print(f"experiment_id={summary.get('experiment_id', '?')} best_run_id={summary.get('best_run_id', '?')}")
        for key in ("sharpe", "total_return", "max_drawdown"):
            print(f"{key}={metrics.get(key, '?')}")
        print(f"report={summary.get('report', '?')}")
        log_path = Path(config.LOG_DIR) / "factor_trials.jsonl"
        trials.append_trial(
            args.factor_id,
            {
                "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                "start": args.start,
                "end": effective_end,
                "final": args.final,
                "sharpe": metrics.get("sharpe", "?"),
            },
            log_path,
        )
        warning = trials.overfit_warning(args.factor_id, trials.count_trials(args.factor_id, log_path))
        if warning:
            print(warning)
        print("Results are proposal-only; promotion to the review pool is a human decision.")
        return 0 if code == 0 else 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())

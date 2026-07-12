from __future__ import annotations

import json
import math
import re
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any, Optional

_FACTOR_LAB_RE = re.compile(
    r"symbol=(?P<symbol>\S+).*?cross_rows=(?P<cross_rows>\d+).*?timing_rows=(?P<timing_rows>\d+)",
    re.DOTALL,
)


def parse_factor_lab(output: str) -> dict[str, str]:
    match = _FACTOR_LAB_RE.search(output)
    return match.groupdict() if match else {}


def load_scan_candidates(scan_dir: Path, run_date: str) -> list[dict[str, Any]]:
    path = Path(scan_dir) / f"{run_date}.jsonl"
    if not path.exists():
        return []
    raw = path.read_bytes()
    if not raw or not raw.endswith(b"\n"):
        raise ValueError("options scan artifact is empty or has a torn final line")
    text = raw.decode("utf-8", errors="strict")
    candidates: list[dict[str, Any]] = []
    for line_number, line in enumerate(text[:-1].split("\n"), start=1):
        if not line:
            raise ValueError(f"options scan artifact line {line_number} is blank")

        def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            value: dict[str, Any] = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError(f"duplicate JSON key: {key}")
                value[key] = item
            return value

        def reject_constant(value: str) -> None:
            raise ValueError(f"non-finite JSON number: {value}")

        candidate = json.loads(
            line,
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
        if not isinstance(candidate, dict):
            raise ValueError(f"options scan artifact line {line_number} is not an object")
        candidates.append(candidate)
    return candidates


def _percentile(sorted_values: list[float], pct: float) -> Optional[float]:
    if not sorted_values:
        return None
    return sorted_values[int(pct / 100 * (len(sorted_values) - 1))]


def summarize_scores(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    scores = sorted(float(c["global_score"]) for c in candidates if c.get("global_score") is not None)
    iv_known = [c for c in candidates if c.get("iv_rank") is not None]
    return {
        "count": len(candidates),
        "score_max": scores[-1] if scores else None,
        "score_p50": _percentile(scores, 50),
        "score_p90": _percentile(scores, 90),
        "iv_rank_known": len(iv_known),
    }


def evaluate_signals(
    candidates: list[dict[str, Any]],
    min_score: Optional[float] = None,
    min_iv_rank: Optional[float] = None,
) -> tuple[bool, list[str]]:
    if min_score is None and min_iv_rank is None:
        return (False, [])  # collect mode (D-15): thresholds not yet set
    fired: list[str] = []
    for c in candidates:
        score = c.get("global_score")
        iv_rank = c.get("iv_rank")
        if min_score is not None and (score is None or float(score) < min_score):
            continue
        if min_iv_rank is not None and (iv_rank is None or float(iv_rank) < min_iv_rank):
            continue
        fired.append(f"{c.get('ticker', '?')} {c.get('strategy', '?')}: score={score} iv_rank={iv_rank}")
    return (len(fired) > 0, fired)


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8", errors="strict")
    return sha256(encoded).hexdigest()


def _finite_optional_number(value: Any, field: str) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number or null")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{field} must be a finite number or null")
    return normalized


def build_signal_records(
    candidates: list[dict[str, Any]],
    *,
    min_score: Optional[float],
    min_iv_rank: Optional[float],
    source_date: str,
    observed_at: str,
) -> list[dict[str, Any]]:
    """Build stable structured observations for threshold-qualified option rows."""
    if min_score is None and min_iv_rank is None:
        return []
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", source_date) is None:
        raise ValueError("source_date must use strict YYYY-MM-DD")
    try:
        source_date = date.fromisoformat(source_date).isoformat()
    except ValueError as exc:
        raise ValueError("source_date must use strict YYYY-MM-DD") from exc
    min_score = _finite_optional_number(min_score, "min_score")
    min_iv_rank = _finite_optional_number(min_iv_rank, "min_iv_rank")
    policy = {"min_score": min_score, "min_iv_rank": min_iv_rank}
    policy_sha256 = _canonical_sha256(policy)
    records: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValueError("options scan candidate must be an object")
        if candidate.get("run_date") != source_date:
            raise ValueError("options scan candidate run_date does not match source_date")
        score = _finite_optional_number(candidate.get("global_score"), "global_score")
        iv_rank = _finite_optional_number(candidate.get("iv_rank"), "iv_rank")
        if min_score is not None and (score is None or score < min_score):
            continue
        if min_iv_rank is not None and (
            iv_rank is None or iv_rank < min_iv_rank
        ):
            continue
        source_row_sha256 = _canonical_sha256(candidate)
        option = candidate.get("candidate")
        option = option if isinstance(option, dict) else {}
        contract_symbol = option.get("symbol")
        if isinstance(contract_symbol, str):
            contract_symbol = contract_symbol.strip() or None
        underlying = option.get("underlying") or candidate.get("ticker")
        if isinstance(underlying, str):
            underlying = underlying.strip() or None
        if isinstance(underlying, str) and underlying.startswith("US."):
            underlying = underlying[3:]
        strategy = candidate.get("strategy")
        if not isinstance(strategy, str) or not strategy.strip():
            raise ValueError("options scan candidate strategy is required")
        strategy = strategy.strip()
        identity = {
            "schema_version": "1.0",
            "source_kind": "options_scan",
            "source_date": source_date,
            "source_row_sha256": source_row_sha256,
            "contract_symbol": contract_symbol,
            "policy_sha256": policy_sha256,
        }
        eligibility = (
            {
                "status": "unknown",
                "route": None,
                "reason_code": "missing_contract_identity",
                "deadline_at": None,
            }
            if not isinstance(contract_symbol, str) or not contract_symbol.strip()
            else {
                "status": "not_actionable",
                "route": None,
                "reason_code": "paper_options_route_unavailable",
                "deadline_at": None,
            }
        )
        records.append(
            {
                "schema_version": "1.0",
                "signal_id": f"sig_{_canonical_sha256(identity)[:24]}",
                "observed_at": observed_at,
                "source": {
                    "kind": "options_scan",
                    "date": source_date,
                    "row_sha256": source_row_sha256,
                },
                "instrument": {
                    "asset_class": "option",
                    "contract_symbol": contract_symbol,
                    "underlying": underlying,
                },
                "strategy": strategy,
                "score": score,
                "iv_rank": iv_rank,
                "policy": {**policy, "sha256": policy_sha256},
                "eligibility": eligibility,
            }
        )
    return records

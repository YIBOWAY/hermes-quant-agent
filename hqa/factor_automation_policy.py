"""Versioned, content-addressed machine review policy for paper automation.

The policy replaces Gate-2 human judgement only when the later dual automation
flags are enabled.  Loading and evaluation are pure and fail closed so Slice 2
can prove the policy contract without enabling promotion or resident trading.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

_SCHEMA_VERSION = "hqa.factor_automation_policy/v1"
_POLICY_FIELDS = {
    "schema_version",
    "default_universe",
    "universe_allowlist",
    "minimum_sample_rows",
    "minimum_out_of_sample_rows",
    "minimum_data_coverage_ratio",
    "minimum_transaction_cost_bps",
    "maximum_absolute_drawdown",
    "maximum_turnover",
    "require_lookahead_static_check",
}
_MAX_POLICY_BYTES = 64 * 1024


class FactorAutomationPolicyError(ValueError):
    """Raised when the committed policy cannot authorize automation."""


@dataclass(frozen=True)
class FactorAutomationPolicy:
    schema_version: str
    default_universe: tuple[str, ...]
    universe_allowlist: tuple[str, ...]
    minimum_sample_rows: int
    minimum_out_of_sample_rows: int
    minimum_data_coverage_ratio: float
    minimum_transaction_cost_bps: float
    maximum_absolute_drawdown: float
    maximum_turnover: float
    require_lookahead_static_check: bool


@dataclass(frozen=True)
class LoadedFactorAutomationPolicy:
    policy: FactorAutomationPolicy
    policy_digest: str


@dataclass(frozen=True)
class FactorAutomationEvidence:
    universe: tuple[str, ...]
    sample_rows: int
    out_of_sample_rows: int
    data_coverage_ratio: float
    transaction_cost_bps: float
    max_drawdown: float
    turnover: float
    lookahead_static_check_passed: bool


@dataclass(frozen=True)
class FactorAutomationDecision:
    accepted: bool
    reasons: tuple[str, ...]
    policy_digest: str
    universe: tuple[str, ...]


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise FactorAutomationPolicyError("policy schema has duplicate fields")
        result[key] = value
    return result


def _symbols(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise FactorAutomationPolicyError(f"policy schema has invalid {field}")
    symbols = tuple(value)
    if (
        any(
            type(symbol) is not str
            or not symbol
            or symbol != symbol.upper()
            or not symbol.replace(".", "").isalnum()
            for symbol in symbols
        )
        or len(set(symbols)) != len(symbols)
    ):
        raise FactorAutomationPolicyError(f"policy schema has invalid {field}")
    return symbols


def _positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise FactorAutomationPolicyError(f"policy schema has invalid {field}")
    return value


def _bounded_float(
    value: object,
    *,
    field: str,
    minimum: float,
    maximum: float,
    minimum_inclusive: bool = True,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FactorAutomationPolicyError(f"policy schema has invalid {field}")
    numeric = float(value)
    lower_ok = numeric >= minimum if minimum_inclusive else numeric > minimum
    if not math.isfinite(numeric) or not lower_ok or numeric > maximum:
        raise FactorAutomationPolicyError(f"policy schema has invalid {field}")
    return numeric


def load_factor_automation_policy(path: Path) -> LoadedFactorAutomationPolicy:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise FactorAutomationPolicyError("policy file is unavailable") from exc
    if not raw or len(raw) > _MAX_POLICY_BYTES:
        raise FactorAutomationPolicyError("policy schema is empty or oversized")
    try:
        document = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeError, ValueError, json.JSONDecodeError, RecursionError) as exc:
        raise FactorAutomationPolicyError("policy schema is invalid JSON") from exc
    if not isinstance(document, Mapping) or set(document) != _POLICY_FIELDS:
        raise FactorAutomationPolicyError("policy schema fields do not match")
    if document.get("schema_version") != _SCHEMA_VERSION:
        raise FactorAutomationPolicyError("policy schema version does not match")
    default_universe = _symbols(
        document.get("default_universe"), field="default_universe"
    )
    universe_allowlist = _symbols(
        document.get("universe_allowlist"), field="universe_allowlist"
    )
    if not set(default_universe) <= set(universe_allowlist):
        raise FactorAutomationPolicyError(
            "policy schema default universe is not allowlisted"
        )
    require_lookahead = document.get("require_lookahead_static_check")
    if type(require_lookahead) is not bool:
        raise FactorAutomationPolicyError(
            "policy schema has invalid require_lookahead_static_check"
        )
    policy = FactorAutomationPolicy(
        schema_version=_SCHEMA_VERSION,
        default_universe=default_universe,
        universe_allowlist=universe_allowlist,
        minimum_sample_rows=_positive_int(
            document.get("minimum_sample_rows"), field="minimum_sample_rows"
        ),
        minimum_out_of_sample_rows=_positive_int(
            document.get("minimum_out_of_sample_rows"),
            field="minimum_out_of_sample_rows",
        ),
        minimum_data_coverage_ratio=_bounded_float(
            document.get("minimum_data_coverage_ratio"),
            field="minimum_data_coverage_ratio",
            minimum=0.0,
            maximum=1.0,
            minimum_inclusive=False,
        ),
        minimum_transaction_cost_bps=_bounded_float(
            document.get("minimum_transaction_cost_bps"),
            field="minimum_transaction_cost_bps",
            minimum=0.0,
            maximum=10_000.0,
        ),
        maximum_absolute_drawdown=_bounded_float(
            document.get("maximum_absolute_drawdown"),
            field="maximum_absolute_drawdown",
            minimum=0.0,
            maximum=1.0,
            minimum_inclusive=False,
        ),
        maximum_turnover=_bounded_float(
            document.get("maximum_turnover"),
            field="maximum_turnover",
            minimum=0.0,
            maximum=1_000_000.0,
        ),
        require_lookahead_static_check=require_lookahead,
    )
    canonical = json.dumps(
        dict(document),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return LoadedFactorAutomationPolicy(
        policy=policy,
        policy_digest=hashlib.sha256(canonical).hexdigest(),
    )


def evaluate_factor_automation_policy(
    loaded: LoadedFactorAutomationPolicy,
    evidence: FactorAutomationEvidence,
) -> FactorAutomationDecision:
    policy = loaded.policy
    reasons: list[str] = []
    universe = tuple(evidence.universe)
    if (
        not universe
        or len(set(universe)) != len(universe)
        or any(symbol not in policy.universe_allowlist for symbol in universe)
    ):
        reasons.append("universe_not_allowlisted")
    if (
        isinstance(evidence.sample_rows, bool)
        or evidence.sample_rows < policy.minimum_sample_rows
    ):
        reasons.append("sample_rows_below_minimum")
    if (
        isinstance(evidence.out_of_sample_rows, bool)
        or evidence.out_of_sample_rows < policy.minimum_out_of_sample_rows
    ):
        reasons.append("out_of_sample_rows_below_minimum")
    numeric_values = (
        evidence.data_coverage_ratio,
        evidence.transaction_cost_bps,
        evidence.max_drawdown,
        evidence.turnover,
    )
    numeric_valid = all(
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
        for value in numeric_values
    )
    if not numeric_valid or not (
        policy.minimum_data_coverage_ratio
        <= float(evidence.data_coverage_ratio)
        <= 1.0
    ):
        reasons.append("data_coverage_below_minimum")
    if not numeric_valid or (
        float(evidence.transaction_cost_bps)
        < policy.minimum_transaction_cost_bps
    ):
        reasons.append("transaction_cost_assumption_too_low")
    if not numeric_valid or (
        abs(float(evidence.max_drawdown)) > policy.maximum_absolute_drawdown
    ):
        reasons.append("max_drawdown_exceeded")
    if not numeric_valid or float(evidence.turnover) > policy.maximum_turnover:
        reasons.append("turnover_exceeded")
    if (
        policy.require_lookahead_static_check
        and evidence.lookahead_static_check_passed is not True
    ):
        reasons.append("lookahead_static_check_failed")
    return FactorAutomationDecision(
        accepted=not reasons,
        reasons=tuple(reasons),
        policy_digest=loaded.policy_digest,
        universe=universe,
    )


__all__ = [
    "FactorAutomationDecision",
    "FactorAutomationEvidence",
    "FactorAutomationPolicy",
    "FactorAutomationPolicyError",
    "LoadedFactorAutomationPolicy",
    "evaluate_factor_automation_policy",
    "load_factor_automation_policy",
]

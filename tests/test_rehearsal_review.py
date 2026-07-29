from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "verify_rehearsal_review.py"


def _helper():
    spec = importlib.util.spec_from_file_location("rehearsal_review_test", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _scope() -> dict[str, object]:
    return {
        "hqa": {"commit": "a" * 40, "tree": "b" * 40},
        "platform": {"commit": "c" * 40, "tree": "d" * 40},
    }


def _review(
    *,
    mode: str = "independent",
    findings: list[dict[str, object]] | None = None,
    verdict: str = "CLEAR",
) -> dict[str, object]:
    return {
        "findings": [] if findings is None else findings,
        "mode": mode,
        "reviewer": {
            "identity": "reviewer-01",
            "independence_attested": True,
        },
        "schema": "hermes-v0.2.1-review/v1",
        "scope": _scope(),
        "verdict": verdict,
    }


def _finding(
    *,
    severity: str,
    admissible: bool = True,
    open_: bool = True,
    blocking: bool = True,
) -> dict[str, object]:
    return {
        "admissible": admissible,
        "affected_reference": "src/example.py:12",
        "blocking": blocking,
        "concrete_scenario": "An exact request reaches the unsafe branch.",
        "direct_evidence": "pytest failure tests/test_example.py::test_case",
        "open": open_,
        "severity": severity,
    }


def test_clear_requires_zero_admissible_open_blockers() -> None:
    helper = _helper()

    result = helper.validate_review(
        _review(
            findings=[
                _finding(severity="P2", blocking=False),
                _finding(severity="P3", blocking=False),
            ]
        ),
        mode="independent",
        scope=_scope(),
    )

    assert result["verdict"] == "CLEAR"
    assert result["counts"]["admissible_open_p0"] == 0
    assert result["counts"]["admissible_open_p1"] == 0
    assert result["counts"]["admissible_open_blocking_p2"] == 0


@pytest.mark.parametrize("severity", ["P0", "P1", "P2"])
def test_valid_needs_work_counts_open_blockers(severity: str) -> None:
    helper = _helper()
    finding = _finding(severity=severity)

    result = helper.validate_review(
        _review(findings=[finding], verdict="NEEDS_WORK"),
        mode="independent",
        scope=_scope(),
    )

    assert result["verdict"] == "NEEDS_WORK"


def test_verdict_mode_scope_and_finding_schema_fail_closed() -> None:
    helper = _helper()
    with pytest.raises(helper.ReviewError, match="verdict_inconsistent"):
        helper.validate_review(
            _review(findings=[_finding(severity="P1")]),
            mode="independent",
            scope=_scope(),
        )
    with pytest.raises(helper.ReviewError, match="mode_or_schema"):
        helper.validate_review(
            _review(mode="adversarial"),
            mode="independent",
            scope=_scope(),
        )
    with pytest.raises(helper.ReviewError, match="scope_mismatch"):
        helper.validate_review(
            _review(),
            mode="independent",
            scope={"different": True},
        )
    malformed = _finding(severity="P1")
    malformed.pop("direct_evidence")
    with pytest.raises(helper.ReviewError, match="finding_schema"):
        helper.validate_review(
            _review(findings=[malformed], verdict="NEEDS_WORK"),
            mode="independent",
            scope=_scope(),
        )


def test_canonical_loader_rejects_duplicate_noncanonical_nonfinite(
    tmp_path: Path,
) -> None:
    helper = _helper()
    tmp_path.chmod(0o700)
    review = tmp_path / "review.json"

    for content, error in (
        (b'{"a":1,"a":2}', "duplicate_key"),
        (b'{"b":2, "a":1}', "not_canonical"),
        (b'{"a":NaN}', "nonfinite"),
    ):
        review.write_bytes(content)
        review.chmod(0o600)
        with pytest.raises(helper.ReviewError, match=error):
            helper.load_review(review)


def test_review_file_must_be_owner_private_regular_and_not_symlinked(
    tmp_path: Path,
) -> None:
    helper = _helper()
    tmp_path.chmod(0o700)
    target = tmp_path / "target.json"
    target.write_bytes(helper.canonical_json(_review()))
    target.chmod(0o600)
    link = tmp_path / "review.json"
    link.symlink_to(target)

    with pytest.raises(helper.ReviewError, match="not_canonical"):
        helper.load_review(link)

    target.chmod(0o644)
    with pytest.raises(helper.ReviewError, match="unsafe"):
        helper.load_review(target)


def test_canonical_json_is_sorted_compact_utf8_and_newline_free() -> None:
    helper = _helper()
    content = helper.canonical_json({"z": "中文", "a": [1, 2]})
    assert content == '{"a":[1,2],"z":"中文"}'.encode()
    assert not content.endswith(b"\n")

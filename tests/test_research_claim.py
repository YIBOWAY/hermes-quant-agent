from __future__ import annotations

import pytest

from hqa.research_claim import (
    ResearchClaimError,
    build_research_claim,
    research_claim_digest,
)


TITLE = (
    "Short-Term Reversals and Longer-Term Momentum Around the World: "
    "Theory and Evidence"
)
UNIVERSE = ["SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLV", "XLY", "XLP", "XLE"]


def test_research_claim_digest_binds_exact_title_and_ordered_universe() -> None:
    exact = build_research_claim(TITLE, UNIVERSE)
    variants = [
        build_research_claim(TITLE + "!", UNIVERSE),
        build_research_claim(TITLE, [UNIVERSE[1], UNIVERSE[0], *UNIVERSE[2:]]),
        build_research_claim(TITLE, UNIVERSE[:-1]),
        build_research_claim(TITLE, [*UNIVERSE, "TLT"]),
    ]

    digest = research_claim_digest(exact)
    assert len(digest) == 64
    assert all(research_claim_digest(variant) != digest for variant in variants)
    assert exact["universe"] == UNIVERSE


@pytest.mark.parametrize(
    "title,universe",
    [
        ("", UNIVERSE),
        (" title-with-leading-space", UNIVERSE),
        (TITLE, []),
        (TITLE, ["spy"]),
        (TITLE, ["SPY", "SPY"]),
        (TITLE, "SPY,QQQ"),
    ],
)
def test_research_claim_rejects_ambiguous_or_normalized_inputs(
    title,
    universe,
) -> None:
    with pytest.raises(ResearchClaimError, match="research_claim_invalid"):
        build_research_claim(title, universe)

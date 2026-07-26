"""Private, content-addressed research-claim contract for Agent v0.2.

The exact paper title and ordered universe belong inside the encrypted intent
payload.  Public workflow and completion surfaces carry only the canonical
SHA-256 digest returned by :func:`research_claim_digest`.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any


SCHEMA_VERSION = "agent-v0.2-research-claim/v1"
_FIELDS = frozenset({"schema_version", "paper_title", "universe"})
_SYMBOL_RE = re.compile(r"[A-Z0-9][A-Z0-9._:-]{0,31}\Z")
_MAX_TITLE_BYTES = 4_096
_MAX_UNIVERSE_SYMBOLS = 512


class ResearchClaimError(ValueError):
    """Value-free validation failure safe to map at a local boundary."""


def _invalid() -> ResearchClaimError:
    return ResearchClaimError("research_claim_invalid")


def normalize_research_claim(value: Any) -> dict[str, Any]:
    """Return one closed, canonical claim without normalizing its semantics."""

    if type(value) is not dict or set(value) != _FIELDS:
        raise _invalid()
    if value.get("schema_version") != SCHEMA_VERSION:
        raise _invalid()
    paper_title = value.get("paper_title")
    if (
        type(paper_title) is not str
        or not paper_title
        or paper_title != paper_title.strip()
        or not paper_title.isprintable()
    ):
        raise _invalid()
    try:
        if len(paper_title.encode("utf-8", errors="strict")) > _MAX_TITLE_BYTES:
            raise _invalid()
    except UnicodeEncodeError as exc:
        raise _invalid() from exc

    universe = value.get("universe")
    if (
        type(universe) is not list
        or not 1 <= len(universe) <= _MAX_UNIVERSE_SYMBOLS
        or any(
            type(symbol) is not str or _SYMBOL_RE.fullmatch(symbol) is None
            for symbol in universe
        )
        or len(set(universe)) != len(universe)
    ):
        raise _invalid()
    return {
        "schema_version": SCHEMA_VERSION,
        "paper_title": paper_title,
        "universe": list(universe),
    }


def build_research_claim(
    paper_title: str,
    universe: Sequence[str],
) -> dict[str, Any]:
    """Build one exact claim; symbol order is intentionally significant."""

    if isinstance(universe, (str, bytes, bytearray)):
        raise _invalid()
    return normalize_research_claim(
        {
            "schema_version": SCHEMA_VERSION,
            "paper_title": paper_title,
            "universe": list(universe),
        }
    )


def research_claim_digest(value: Mapping[str, Any]) -> str:
    """Hash the exact canonical title and ordered universe without exposing it."""

    claim = normalize_research_claim(dict(value))
    encoded = json.dumps(
        claim,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8", errors="strict")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "ResearchClaimError",
    "SCHEMA_VERSION",
    "build_research_claim",
    "normalize_research_claim",
    "research_claim_digest",
]

"""Digest-only verification for the ``hqa.paper_intake/v1`` contract.

The module deliberately owns all transcript parsing and body inspection.  Its
public result contains only identities, counts, sizes, and SHA-256 digests, so
the platform connector can enforce paper intake without learning the private
prompt, paper body, or generated factor source.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

from hqa.research_claim import normalize_research_claim, research_claim_digest


PAPER_INTAKE_CONTRACT = "hqa.paper_intake/v1"
MINIMUM_FULL_TEXT_BYTES = 4_096
_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
_URL_RE = re.compile(r"https?://[^\s<>\]\[()\"']+")
_SOURCE_SUFFIX = ".py"


class PaperIntakeError(RuntimeError):
    """Closed, secret-free paper-intake failure."""

    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise PaperIntakeError("paper_intake_invalid_evidence") from exc


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _text_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="strict")).hexdigest()


def build_execution_contract(*, source_file_ref: str | Path) -> dict[str, object]:
    """Return the closed execution contract stored inside the encrypted intent."""

    source = Path(source_file_ref)
    if not source.is_absolute() or source.suffix != _SOURCE_SUFFIX:
        raise PaperIntakeError("paper_intake_contract_invalid")
    normalized = os.path.abspath(os.fspath(source))
    if "\x00" in normalized or len(normalized.encode("utf-8")) > 2_048:
        raise PaperIntakeError("paper_intake_contract_invalid")
    return {
        "schema_version": PAPER_INTAKE_CONTRACT,
        "minimum_full_text_bytes": MINIMUM_FULL_TEXT_BYTES,
        "source_file_ref": normalized,
    }


def normalize_execution_contract(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != {
        "schema_version",
        "minimum_full_text_bytes",
        "source_file_ref",
    }:
        raise PaperIntakeError("paper_intake_contract_invalid")
    if (
        value.get("schema_version") != PAPER_INTAKE_CONTRACT
        or value.get("minimum_full_text_bytes") != MINIMUM_FULL_TEXT_BYTES
    ):
        raise PaperIntakeError("paper_intake_contract_invalid")
    return build_execution_contract(source_file_ref=str(value.get("source_file_ref")))


def execution_contract_digest(value: object) -> str:
    return _digest(normalize_execution_contract(value))


def execution_instructions(value: object) -> str:
    """Fixed system instructions; the private user message remains byte-exact."""

    contract = normalize_execution_contract(value)
    source = contract["source_file_ref"]
    return (
        "This run is governed by hqa.paper_intake/v1. You must use web_search "
        "to discover the requested paper unless the user supplied an exact URL; "
        "you must use web_extract on the selected paper URL and inspect at least "
        f"{MINIMUM_FULL_TEXT_BYTES} UTF-8 bytes of paper text. Then derive one "
        "Python factor implementation and create it with the write_file tool at "
        f"this exact absolute path: {source}. Do not claim completion unless all "
        "three tool-backed steps succeeded."
    )


def _strict_json(value: object) -> object:
    if type(value) is not str:
        raise PaperIntakeError("paper_intake_invalid_evidence")
    try:
        return json.loads(
            value,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (TypeError, ValueError, json.JSONDecodeError, RecursionError) as exc:
        raise PaperIntakeError("paper_intake_invalid_evidence") from exc


def _exact_turn(
    messages: Sequence[Mapping[str, Any]],
    *,
    prompt: str,
) -> list[Mapping[str, Any]]:
    matches = [
        index
        for index, message in enumerate(messages)
        if message.get("role") == "user" and message.get("content") == prompt
    ]
    if not matches:
        raise PaperIntakeError("paper_intake_turn_missing")
    start = matches[-1]
    end = len(messages)
    for index in range(start + 1, len(messages)):
        if messages[index].get("role") == "user":
            end = index
            break
    return list(messages[start + 1 : end])


def _tool_evidence(
    turn: Sequence[Mapping[str, Any]],
) -> list[tuple[str, Mapping[str, Any], str]]:
    calls: dict[str, tuple[str, Mapping[str, Any]]] = {}
    results: dict[str, str] = {}
    for message in turn:
        if message.get("role") == "assistant":
            raw_calls = message.get("tool_calls")
            if not isinstance(raw_calls, list):
                continue
            for raw in raw_calls:
                if not isinstance(raw, Mapping):
                    raise PaperIntakeError("paper_intake_invalid_evidence")
                call_id = raw.get("id")
                function = raw.get("function")
                if type(call_id) is not str or not isinstance(function, Mapping):
                    raise PaperIntakeError("paper_intake_invalid_evidence")
                name = function.get("name")
                arguments = _strict_json(function.get("arguments"))
                if type(name) is not str or not isinstance(arguments, Mapping):
                    raise PaperIntakeError("paper_intake_invalid_evidence")
                if call_id in calls:
                    raise PaperIntakeError("paper_intake_invalid_evidence")
                calls[call_id] = (name, dict(arguments))
        elif message.get("role") == "tool":
            call_id = message.get("tool_call_id")
            content = message.get("content")
            if type(call_id) is str and type(content) is str:
                if call_id in results:
                    raise PaperIntakeError("paper_intake_invalid_evidence")
                results[call_id] = content
    return [
        (name, arguments, results[call_id])
        for call_id, (name, arguments) in calls.items()
        if call_id in results
    ]


def _urls_in_prompt(prompt: str) -> set[str]:
    return {match.rstrip(".,;:") for match in _URL_RE.findall(prompt)}


def _search_receipts(
    evidence: Sequence[tuple[str, Mapping[str, Any], str]],
) -> tuple[set[str], int, str | None]:
    urls: set[str] = set()
    rows: list[dict[str, object]] = []
    for name, _arguments, raw in evidence:
        if name != "web_search":
            continue
        parsed = _strict_json(raw)
        if not isinstance(parsed, Mapping) or parsed.get("success") is not True:
            continue
        data = parsed.get("data")
        web = data.get("web") if isinstance(data, Mapping) else None
        if not isinstance(web, list):
            continue
        for result in web:
            if not isinstance(result, Mapping):
                continue
            url = result.get("url") or result.get("href")
            if type(url) is not str or not url.startswith(("http://", "https://")):
                continue
            urls.add(url)
            rows.append({
                "url_sha256": _text_digest(url),
                "result_sha256": _digest(result),
            })
    return urls, len(rows), (_digest(rows) if rows else None)


def _normalized_identity(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


def _full_text_receipt(
    evidence: Sequence[tuple[str, Mapping[str, Any], str]],
    *,
    allowed_urls: set[str],
    paper_title: str,
    minimum_bytes: int,
) -> dict[str, object]:
    normalized_title = _normalized_identity(paper_title)
    for name, _arguments, raw in evidence:
        if name != "web_extract":
            continue
        parsed = _strict_json(raw)
        results = parsed.get("results") if isinstance(parsed, Mapping) else None
        if not isinstance(results, list):
            continue
        for row in results:
            if not isinstance(row, Mapping) or row.get("error") not in {None, ""}:
                continue
            url = row.get("url")
            title = row.get("title")
            content = row.get("content")
            if type(url) is not str or url not in allowed_urls or type(content) is not str:
                continue
            raw_content = content.encode("utf-8", errors="strict")
            if len(raw_content) < minimum_bytes:
                continue
            identity_corpus = _normalized_identity(
                (title if type(title) is str else "") + "\n" + content[:32_768]
            )
            if not normalized_title or normalized_title not in identity_corpus:
                continue
            path = urlparse(url).path.casefold()
            return {
                "full_text_mode": "direct_pdf" if path.endswith(".pdf") else "web_extract",
                "full_text_bytes": len(raw_content),
                "full_text_sha256": hashlib.sha256(raw_content).hexdigest(),
                "paper_url_sha256": _text_digest(url),
                "paper_identity_sha256": _text_digest(normalized_title),
            }
    raise PaperIntakeError("paper_intake_full_text_missing")


def _read_exact_source(path: str, expected: bytes) -> bytes:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise PaperIntakeError("paper_intake_source_missing") from exc
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise PaperIntakeError("paper_intake_source_mismatch")
    try:
        actual = Path(path).read_bytes()
    except OSError as exc:
        raise PaperIntakeError("paper_intake_source_missing") from exc
    if actual != expected:
        raise PaperIntakeError("paper_intake_source_mismatch")
    try:
        compile(actual.decode("utf-8", errors="strict"), "<paper-intake-factor>", "exec")
    except (UnicodeError, SyntaxError) as exc:
        raise PaperIntakeError("paper_intake_source_invalid") from exc
    return actual


def _source_receipt(
    evidence: Sequence[tuple[str, Mapping[str, Any], str]],
    *,
    source_file_ref: str,
) -> dict[str, object]:
    for name, arguments, _raw in evidence:
        if name != "write_file" or arguments.get("path") != source_file_ref:
            continue
        content = arguments.get("content")
        if type(content) is not str or not content.strip():
            continue
        expected = content.encode("utf-8", errors="strict")
        actual = _read_exact_source(source_file_ref, expected)
        return {
            "source_file_ref": source_file_ref,
            "source_bytes": len(actual),
            "source_sha256": hashlib.sha256(actual).hexdigest(),
        }
    raise PaperIntakeError("paper_intake_source_missing")


def verify_paper_intake(
    *,
    execution_contract: object,
    research_claim: object,
    prompt: str,
    messages: Sequence[Mapping[str, Any]],
    command_id: str,
    payload_ref: str,
    hermes_session_id: str,
    hermes_run_id: str,
    observation_evidence_digest: str,
) -> dict[str, object]:
    """Verify one exact managed-session turn and return a body-free receipt."""

    contract = normalize_execution_contract(execution_contract)
    claim = normalize_research_claim(research_claim)
    if (
        type(prompt) is not str
        or not prompt
        or type(command_id) is not str
        or not command_id
        or type(payload_ref) is not str
        or not payload_ref.startswith("payload:sha256:")
        or type(hermes_session_id) is not str
        or not hermes_session_id
        or type(hermes_run_id) is not str
        or not hermes_run_id
        or type(observation_evidence_digest) is not str
        or _DIGEST_RE.fullmatch(observation_evidence_digest) is None
    ):
        raise PaperIntakeError("paper_intake_invalid_request")
    if not isinstance(messages, Sequence) or isinstance(messages, (str, bytes)):
        raise PaperIntakeError("paper_intake_invalid_evidence")
    turn = _exact_turn(messages, prompt=prompt)
    evidence = _tool_evidence(turn)
    search_urls, search_count, search_digest = _search_receipts(evidence)
    user_urls = _urls_in_prompt(prompt)
    if search_count:
        discovery_mode = "web_search"
        allowed_urls = search_urls
    elif user_urls:
        discovery_mode = "user_url"
        allowed_urls = user_urls
    else:
        raise PaperIntakeError("paper_intake_discovery_missing")
    full_text = _full_text_receipt(
        evidence,
        allowed_urls=allowed_urls,
        paper_title=str(claim["paper_title"]),
        minimum_bytes=int(contract["minimum_full_text_bytes"]),
    )
    source = _source_receipt(
        evidence,
        source_file_ref=str(contract["source_file_ref"]),
    )
    receipt: dict[str, object] = {
        "schema_version": PAPER_INTAKE_CONTRACT,
        "disposition": "accepted",
        "command_id": command_id,
        "payload_ref": payload_ref,
        "hermes_session_id": hermes_session_id,
        "hermes_run_id": hermes_run_id,
        "observation_evidence_digest": observation_evidence_digest,
        "execution_contract_digest": execution_contract_digest(contract),
        "research_claim_digest": research_claim_digest(claim),
        "discovery_mode": discovery_mode,
        "search_result_count": search_count,
        "search_results_digest": search_digest,
        **full_text,
        **source,
    }
    return receipt


__all__ = [
    "MINIMUM_FULL_TEXT_BYTES",
    "PAPER_INTAKE_CONTRACT",
    "PaperIntakeError",
    "build_execution_contract",
    "execution_contract_digest",
    "execution_instructions",
    "normalize_execution_contract",
    "verify_paper_intake",
]

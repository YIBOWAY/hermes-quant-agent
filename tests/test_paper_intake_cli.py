from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from hqa.paper_intake import build_execution_contract
from hqa.paper_intake_cli import main
from hqa.intent_payload_crypto import DeterministicCryptoFake
from hqa.intent_payloads import IntentPayloadStore
from hqa.research_claim import build_research_claim


class _Store:
    def __init__(self, envelope: dict[str, object]) -> None:
        self.envelope = envelope
        self.resolve_calls: list[dict[str, object]] = []

    def resolve(self, payload_ref: str, **scope: object) -> dict[str, object]:
        self.resolve_calls.append({"payload_ref": payload_ref, **scope})
        return dict(self.envelope)


def _prepare_request() -> dict[str, object]:
    return {
        "schema_version": "2.0",
        "kind": "paper_intake",
        "owner_id": "owner-local-root",
        "workspace_id": "workspace:ws-local-main",
        "session_id": "session:managed-1",
        "client_intent_id": "paper-intake-0001",
        "provider_policy": {
            "primary": {"provider": "openai", "model": "gpt-5"},
            "fallbacks": [],
        },
        "prompt": "Reproduce the exact paper for the configured universe.",
        "ttl_days": 7,
        "paper_title": "A Testable Paper Factor",
        "universe": ["SPY", "QQQ"],
    }


def _run_prepare(
    body: dict[str, object],
    *,
    store: IntentPayloadStore,
    source_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[int, dict[str, object]]:
    monkeypatch.setattr(
        "sys.stdin",
        io.TextIOWrapper(io.BytesIO(json.dumps(body).encode()), encoding="utf-8"),
    )
    output = io.StringIO()
    monkeypatch.setattr("sys.stdout", output)
    code = main(
        ["prepare"],
        store_factory=lambda: store,
        source_root=source_root,
    )
    return code, json.loads(output.getvalue())


def test_prepare_persists_encrypted_paper_intake_without_echoing_private_body(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    crypto = DeterministicCryptoFake(key=b"paper intake prepare test key".ljust(32, b"!"))
    store = IntentPayloadStore(tmp_path / "payloads", crypto=crypto)
    source_root = tmp_path / "drafts"
    request = _prepare_request()

    code, document = _run_prepare(
        request,
        store=store,
        source_root=source_root,
        monkeypatch=monkeypatch,
    )

    assert code == 0
    assert document["ok"] is True
    assert document["kind"] == "paper_intake"
    assert document["payload_ref"] == "payload:sha256:" + document["payload_digest"]
    assert len(document["research_claim_digest"]) == 64
    assert len(document["execution_contract_digest"]) == 64
    serialized = json.dumps(document, ensure_ascii=False)
    assert request["prompt"] not in serialized
    assert request["paper_title"] not in serialized
    assert "SPY" not in serialized

    envelope = store.resolve(
        document["payload_ref"],
        owner_id="owner-local-root",
        workspace_id="workspace:ws-local-main",
        session_id="session:managed-1",
    )
    assert envelope["kind"] == "paper_intake"
    assert envelope["research_claim"]["universe"] == ["SPY", "QQQ"]
    source_path = Path(envelope["execution_contract"]["source_file_ref"])
    assert source_path.parent == source_root.resolve()
    assert source_path.name.startswith("factor-")
    assert source_path.suffix == ".py"
    assert source_root.stat().st_mode & 0o777 == 0o700

    again_code, again = _run_prepare(
        request,
        store=store,
        source_root=source_root,
        monkeypatch=monkeypatch,
    )
    assert again_code == 0
    assert again["payload_ref"] == document["payload_ref"]


def test_prepare_rejects_unpersisted_model_universe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    crypto = DeterministicCryptoFake(key=b"paper intake invalid test key".ljust(32, b"!"))
    store = IntentPayloadStore(tmp_path / "payloads", crypto=crypto)
    request = _prepare_request()
    request["universe"] = []

    code, document = _run_prepare(
        request,
        store=store,
        source_root=tmp_path / "drafts",
        monkeypatch=monkeypatch,
    )

    assert code == 2
    assert document["error"]["code"] == "paper_intake_invalid_request"


def _tool_call(call_id: str, name: str, arguments: dict[str, object]) -> dict[str, object]:
    return {
        "role": "assistant",
        "tool_calls": [
            {
                "id": call_id,
                "function": {
                    "name": name,
                    "arguments": json.dumps(arguments, separators=(",", ":")),
                },
            }
        ],
    }


def _messages(source_path: Path, source: str, prompt: str, title: str) -> list[dict[str, object]]:
    url = "https://papers.example/factor.pdf"
    return [
        {"role": "user", "content": prompt},
        _tool_call("s", "web_search", {"query": title}),
        {
            "role": "tool",
            "tool_call_id": "s",
            "content": json.dumps(
                {
                    "success": True,
                    "data": {"web": [{"title": title, "url": url}]},
                }
            ),
        },
        _tool_call("e", "web_extract", {"urls": [url]}),
        {
            "role": "tool",
            "tool_call_id": "e",
            "content": json.dumps(
                {
                    "results": [
                        {
                            "url": url,
                            "title": title,
                            "content": title + "\n" + ("body " * 1_000),
                            "error": None,
                        }
                    ]
                }
            ),
        },
        _tool_call("w", "write_file", {"path": str(source_path), "content": source}),
        {
            "role": "tool",
            "tool_call_id": "w",
            "content": "Wrote file successfully",
        },
    ]


def _request() -> dict[str, object]:
    return {
        "endpoint": {
            "base_url": "http://127.0.0.1:8642",
            "api_key": "test-key",
            "timeout_seconds": 5.0,
        },
        "workspace_id": "ws-local-main",
        "platform_session_id": "managed-1",
        "command_id": "cmd-paper-1",
        "payload_ref": "payload:sha256:" + ("a" * 64),
        "hermes_session_id": "web_paper_1",
        "hermes_run_id": "run_paper_1",
        "observation_evidence_digest": "b" * 64,
    }


def _run(
    body: dict[str, object],
    *,
    store: _Store,
    messages: list[dict[str, object]],
    receipt_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[int, dict[str, object]]:
    monkeypatch.setattr(
        "sys.stdin",
        io.TextIOWrapper(io.BytesIO(json.dumps(body).encode()), encoding="utf-8"),
    )
    output = io.StringIO()
    monkeypatch.setattr("sys.stdout", output)
    calls: list[str] = []

    def transcript_reader(session_id: str, _endpoint: object) -> list[dict[str, object]]:
        calls.append(session_id)
        return messages

    code = main(
        ["verify"],
        store_factory=lambda: store,  # type: ignore[arg-type]
        transcript_reader=transcript_reader,
        receipt_root=receipt_root,
    )
    document = json.loads(output.getvalue())
    document["_transcript_calls"] = calls
    return code, document


def test_verify_persists_digest_only_receipt_and_returns_exact_ref(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    title = "A Testable Paper Factor"
    prompt = "Reproduce the testable paper factor for SPY."
    source_path = tmp_path / "drafts" / "factor.py"
    source_path.parent.mkdir()
    source = "def factor(frame):\n    return frame.pct_change(20)\n"
    source_path.write_text(source, encoding="utf-8")
    envelope = {
        "kind": "paper_intake",
        "prompt": prompt,
        "research_claim": build_research_claim(title, ["SPY"]),
        "execution_contract": build_execution_contract(source_file_ref=source_path),
    }
    receipt_root = tmp_path / "receipts"

    code, document = _run(
        _request(),
        store=_Store(envelope),
        messages=_messages(source_path, source, prompt, title),
        receipt_root=receipt_root,
        monkeypatch=monkeypatch,
    )

    assert code == 0
    assert document["ok"] is True
    assert document["disposition"] == "accepted"
    assert document["receipt_ref"].startswith("paper-intake-receipt:sha256:")
    receipt_file = receipt_root / f"receipt-{document['receipt_digest']}.json"
    assert receipt_file.is_file()
    serialized = receipt_file.read_text(encoding="utf-8")
    assert prompt not in serialized
    assert title not in serialized
    assert source not in serialized
    assert document["_transcript_calls"] == ["web_paper_1"]


def test_non_paper_intent_is_not_required_and_never_reads_transcript(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code, document = _run(
        _request(),
        store=_Store({"kind": "conversation_turn", "prompt": "hello"}),
        messages=[],
        receipt_root=tmp_path / "receipts",
        monkeypatch=monkeypatch,
    )

    assert code == 0
    assert document["disposition"] == "not_required"
    assert document["_transcript_calls"] == []
    assert not (tmp_path / "receipts").exists()


def test_missing_search_is_typed_rejection_without_body_leak(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    title = "A Testable Paper Factor"
    prompt = "private paper request"
    source_path = tmp_path / "factor.py"
    source_path.write_text("def factor(x):\n    return x\n", encoding="utf-8")
    store = _Store(
        {
            "kind": "paper_intake",
            "prompt": prompt,
            "research_claim": build_research_claim(title, ["SPY"]),
            "execution_contract": build_execution_contract(source_file_ref=source_path),
        }
    )

    code, document = _run(
        _request(),
        store=store,
        messages=[{"role": "user", "content": prompt}],
        receipt_root=tmp_path / "receipts",
        monkeypatch=monkeypatch,
    )

    assert code == 2
    assert document["error"]["code"] == "paper_intake_discovery_missing"
    serialized = json.dumps(document)
    assert prompt not in serialized
    assert title not in serialized

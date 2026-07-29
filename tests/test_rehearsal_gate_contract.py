from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = (
    ROOT
    / "docs"
    / "superpowers"
    / "specs"
    / "2026-07-29-v0-2-1-rehearsal-gate-contract.json"
)
SCHEMA = "hermes.v0.2.1-rehearsal-gate-contract.v1"
ALLOWED_PLACEHOLDERS = {"HQA", "PLATFORM", "ROUND_ROOT"}
ALLOWED_GATE_KEYS = {"artifact_paths", "commands", "name"}
ALLOWED_COMMAND_KEYS = {
    "argv",
    "argv_contains",
    "argv_prefix",
    "artifact_paths",
    "authority_paths",
    "binding_paths",
    "cwd",
    "declared_skips",
    "effect_policies",
    "label",
    "side_effect_class",
    "stderr_bytes",
}
TRIVIAL_EXECUTABLES = {
    "/bin/echo",
    "/bin/false",
    "/bin/true",
    "/usr/bin/echo",
    "/usr/bin/false",
    "/usr/bin/true",
}


def _strict_document() -> tuple[dict[str, object], bytes]:
    raw = CONTRACT.read_bytes()

    def pairs_hook(
        pairs: list[tuple[str, object]],
    ) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            assert key not in result, f"duplicate key: {key}"
            result[key] = value
        return result

    document = json.loads(
        raw.decode("utf-8", errors="strict"),
        object_pairs_hook=pairs_hook,
        parse_constant=lambda value: (_ for _ in ()).throw(
            AssertionError(f"non-finite JSON value: {value}")
        ),
    )
    assert isinstance(document, dict)
    canonical = json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    assert raw == canonical
    return document, raw


def _strings(value: object) -> list[str]:
    assert isinstance(value, list) and value
    assert all(isinstance(item, str) and item for item in value)
    return value


def test_contract_is_canonical_and_defines_exactly_ten_nontrivial_gates() -> None:
    document, raw = _strict_document()
    assert set(document) == {"gates", "schema_version"}
    assert document["schema_version"] == SCHEMA
    gates = document["gates"]
    assert isinstance(gates, dict)
    assert set(gates) == {str(value) for value in range(1, 11)}
    assert not raw.endswith(b"\n")

    labels: set[str] = set()
    for number, gate in gates.items():
        assert isinstance(gate, dict)
        assert set(gate) == ALLOWED_GATE_KEYS
        assert isinstance(gate["name"], str) and gate["name"]
        _strings(gate["artifact_paths"])
        commands = gate["commands"]
        assert isinstance(commands, list) and commands
        for command in commands:
            assert isinstance(command, dict)
            assert set(command) <= ALLOWED_COMMAND_KEYS
            assert ("argv" in command) != ("argv_prefix" in command)
            argv = _strings(command.get("argv", command.get("argv_prefix")))
            assert argv[0] not in TRIVIAL_EXECUTABLES
            assert command["label"] not in labels
            labels.add(command["label"])
            _strings(command["authority_paths"])
            _strings(command["binding_paths"])
            _strings(command["artifact_paths"])
            assert isinstance(command["cwd"], str) and command["cwd"]
            assert isinstance(command["side_effect_class"], str)
            assert set(command["effect_policies"]) == {
                "database",
                "generated_files",
                "network",
                "paper_state",
                "runtime",
            }
            text = json.dumps(command, ensure_ascii=False)
            placeholders = set(re.findall(r"\$\{([A-Z_]+)\}", text))
            assert placeholders <= ALLOWED_PLACEHOLDERS
            assert "/api/health" not in text
            assert "--update-snapshots" not in text
            assert "|| true" not in text
        assert int(number) >= 1


def test_contract_covers_frozen_gate_population_and_critical_authorities() -> None:
    document, _ = _strict_document()
    gates = document["gates"]
    assert isinstance(gates, dict)
    expected_command_counts = {
        "1": 1,
        "2": 1,
        "3": 1,
        "4": 1,
        "5": 7,
        "6": 2,
        "7": 2,
        "8": 4,
        "9": 1,
        "10": 2,
    }
    assert {
        number: len(gate["commands"])
        for number, gate in gates.items()
    } == expected_command_counts

    gate5 = json.dumps(gates["5"], ensure_ascii=False)
    for command in (
        '"lint"',
        '"type-check"',
        '"test"',
        '"build"',
        '"check:api-types"',
        '"test:e2e:gate5"',
        "prepare-hermes-gate5-install.mjs",
    ):
        assert command in gate5
    assert all(
        token in json.dumps(gates["8"], ensure_ascii=False)
        for token in (
            "verify_agent_v02_backup_restore.sh",
            "restart_agent_v02_stack.sh",
            "launchd_status_probe.py",
        )
    )
    gate10 = json.dumps(gates["10"], ensure_ascii=False)
    assert '"independent"' in gate10
    assert '"adversarial"' in gate10
    assert [
        command["argv"][0]
        for command in gates["10"]["commands"]
    ] == [
        "${HQA}/scripts/verify_rehearsal_review.sh",
        "${HQA}/scripts/verify_rehearsal_review.sh",
    ]


def test_every_gate_artifact_is_owned_by_exactly_one_command() -> None:
    document, _ = _strict_document()
    gates = document["gates"]
    assert isinstance(gates, dict)
    for gate in gates.values():
        declared = gate["artifact_paths"]
        command_artifacts = [
            artifact
            for command in gate["commands"]
            for artifact in command["artifact_paths"]
        ]
        assert declared == command_artifacts
        assert len(command_artifacts) == len(set(command_artifacts))

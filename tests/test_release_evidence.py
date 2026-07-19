from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


def _junit(
    path: Path,
    *,
    passed: int,
    skipped: int = 0,
    failures: int = 0,
    errors: int = 0,
) -> None:
    suite = ET.Element(
        "testsuite",
        {
            "name": "pytest",
            "tests": str(passed + skipped + failures + errors),
            "failures": str(failures),
            "errors": str(errors),
            "skipped": str(skipped),
            "time": "1.25",
        },
    )
    for index in range(passed):
        ET.SubElement(suite, "testcase", {"name": f"test_{index}"})
    for index in range(skipped):
        case = ET.SubElement(suite, "testcase", {"name": f"skip_{index}"})
        ET.SubElement(case, "skipped")
    for index in range(failures):
        case = ET.SubElement(suite, "testcase", {"name": f"fail_{index}"})
        ET.SubElement(case, "failure")
    for index in range(errors):
        case = ET.SubElement(suite, "testcase", {"name": f"error_{index}"})
        ET.SubElement(case, "error")
    ET.ElementTree(ET.Element("testsuites")).getroot().append(suite)
    root = ET.Element("testsuites")
    root.append(suite)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def _identity_manifest(tmp_path: Path) -> dict[str, object]:
    repositories = []
    for repo, character in (("hqa", "a"), ("platform", "b"), ("hermes", "c")):
        repositories.append(
            {
                "repo": repo,
                "head_commit": character * 40,
                "tree_oid": character * 40,
                "archive_sha256": character * 64,
            }
        )
    return {
        "manifest_digest": "d" * 64,
        "repositories": repositories,
        "path": "docs/audits/evidence/identity.json",
        "file_sha256": hashlib.sha256(b"identity").hexdigest(),
    }


def test_build_binding_canonically_binds_identity_sources_and_junit(
    tmp_path: Path,
) -> None:
    from hqa.release_evidence import (
        EvidenceSpec,
        build_validation_binding,
        parse_validation_binding_json,
    )

    identity = _identity_manifest(tmp_path)
    specs = []
    for index, repository in enumerate(identity["repositories"]):
        artifact = tmp_path / f"{repository['repo']}.xml"
        _junit(artifact, passed=index + 1, skipped=index)
        specs.append(
            EvidenceSpec(
                evidence_id=f"{repository['repo']}-primary",
                repo=repository["repo"],
                source_head_commit=repository["head_commit"],
                source_tree_oid=repository["tree_oid"],
                source_archive_sha256=repository["archive_sha256"],
                cwd=tmp_path,
                command=("/usr/bin/python3", "-m", "pytest"),
                setup_commands=(),
                cleanup_commands=(),
                exit_code=0,
                artifact_path=artifact,
            )
        )

    binding = build_validation_binding(
        identity_manifest_path=identity["path"],
        identity_manifest_file_sha256=identity["file_sha256"],
        identity_manifest_digest=identity["manifest_digest"],
        identity_repositories=identity["repositories"],
        evidence_specs=specs,
    )

    assert binding.schema_version == 1
    assert [item.repo for item in binding.repositories] == [
        "hermes",
        "hqa",
        "platform",
    ]
    assert [item.passed for item in binding.evidence] == [3, 1, 2]
    assert [item.skipped for item in binding.evidence] == [2, 0, 1]
    assert binding.binding_digest
    assert parse_validation_binding_json(binding.to_json_bytes()) == binding


def test_parser_rejects_unknown_duplicate_and_tampered_binding_fields(
    tmp_path: Path,
) -> None:
    from hqa.release_evidence import (
        EvidenceSpec,
        ReleaseEvidenceError,
        build_validation_binding,
        parse_validation_binding_json,
    )

    identity = _identity_manifest(tmp_path)
    specs = []
    for repository in identity["repositories"]:
        artifact = tmp_path / f"{repository['repo']}.xml"
        _junit(artifact, passed=1)
        specs.append(
            EvidenceSpec(
                evidence_id=f"{repository['repo']}-primary",
                repo=repository["repo"],
                source_head_commit=repository["head_commit"],
                source_tree_oid=repository["tree_oid"],
                source_archive_sha256=repository["archive_sha256"],
                cwd=tmp_path,
                command=("/usr/bin/python3", "-m", "pytest"),
                setup_commands=(),
                cleanup_commands=(),
                exit_code=0,
                artifact_path=artifact,
            )
        )
    binding = build_validation_binding(
        identity_manifest_path=identity["path"],
        identity_manifest_file_sha256=identity["file_sha256"],
        identity_manifest_digest=identity["manifest_digest"],
        identity_repositories=identity["repositories"],
        evidence_specs=specs,
    )

    unknown = binding.to_dict()
    unknown["extra"] = True
    with pytest.raises(ReleaseEvidenceError, match="fields"):
        parse_validation_binding_json(json.dumps(unknown))

    tampered = binding.to_dict()
    tampered["evidence"][0]["command"].append("--changed")
    with pytest.raises(ReleaseEvidenceError, match="digest"):
        parse_validation_binding_json(json.dumps(tampered))

    inconsistent = binding.to_dict()
    inconsistent["evidence"][0]["total"] += 1
    with pytest.raises(ReleaseEvidenceError, match="counts"):
        parse_validation_binding_json(json.dumps(inconsistent))

    duplicate = binding.to_json_bytes().replace(
        b'{"binding_digest":',
        b'{"binding_digest":"' + b"0" * 64 + b'","binding_digest":',
        1,
    )
    with pytest.raises(ReleaseEvidenceError, match="duplicate"):
        parse_validation_binding_json(duplicate)


def test_builder_rejects_evidence_from_a_different_source_coordinate(
    tmp_path: Path,
) -> None:
    from hqa.release_evidence import (
        EvidenceSpec,
        ReleaseEvidenceError,
        build_validation_binding,
    )

    identity = _identity_manifest(tmp_path)
    specs = []
    for repository in identity["repositories"]:
        artifact = tmp_path / f"{repository['repo']}.xml"
        _junit(artifact, passed=1)
        specs.append(
            EvidenceSpec(
                evidence_id=f"{repository['repo']}-primary",
                repo=repository["repo"],
                source_head_commit=(
                    "f" * 40
                    if repository["repo"] == "platform"
                    else repository["head_commit"]
                ),
                source_tree_oid=repository["tree_oid"],
                source_archive_sha256=repository["archive_sha256"],
                cwd=tmp_path,
                command=("/usr/bin/python3", "-m", "pytest"),
                setup_commands=(),
                cleanup_commands=(),
                exit_code=0,
                artifact_path=artifact,
            )
        )

    with pytest.raises(ReleaseEvidenceError, match="source"):
        build_validation_binding(
            identity_manifest_path=identity["path"],
            identity_manifest_file_sha256=identity["file_sha256"],
            identity_manifest_digest=identity["manifest_digest"],
            identity_repositories=identity["repositories"],
            evidence_specs=specs,
        )


def test_builder_rejects_unsuccessful_primary_junit_evidence(
    tmp_path: Path,
) -> None:
    from hqa.release_evidence import (
        EvidenceSpec,
        ReleaseEvidenceError,
        build_validation_binding,
    )

    identity = _identity_manifest(tmp_path)
    specs = []
    for repository in identity["repositories"]:
        artifact = tmp_path / f"{repository['repo']}.xml"
        _junit(
            artifact,
            passed=1,
            failures=1 if repository["repo"] == "hermes" else 0,
        )
        specs.append(
            EvidenceSpec(
                evidence_id=f"{repository['repo']}-primary",
                repo=repository["repo"],
                source_head_commit=repository["head_commit"],
                source_tree_oid=repository["tree_oid"],
                source_archive_sha256=repository["archive_sha256"],
                cwd=tmp_path,
                command=("/usr/bin/python3", "-m", "pytest"),
                setup_commands=(),
                cleanup_commands=(),
                exit_code=0,
                artifact_path=artifact,
            )
        )

    with pytest.raises(ReleaseEvidenceError, match="not successful"):
        build_validation_binding(
            identity_manifest_path=identity["path"],
            identity_manifest_file_sha256=identity["file_sha256"],
            identity_manifest_digest=identity["manifest_digest"],
            identity_repositories=identity["repositories"],
            evidence_specs=specs,
        )


def test_evidence_spec_rejects_secret_like_argv() -> None:
    from hqa.release_evidence import EvidenceSpec, ReleaseEvidenceError

    with pytest.raises(ReleaseEvidenceError, match="secret-like"):
        EvidenceSpec(
            evidence_id="hqa-primary",
            repo="hqa",
            source_head_commit="a" * 40,
            source_tree_oid="b" * 40,
            source_archive_sha256="c" * 64,
            cwd=Path("/private/tmp/hqa"),
            command=("/usr/bin/pytest", "--token=do-not-record"),
            setup_commands=(),
            cleanup_commands=(),
            exit_code=0,
            artifact_path=Path("/private/tmp/hqa.xml"),
        )


def test_independent_verdict_parser_is_closed_and_never_authorizes_release() -> None:
    from hqa.release_evidence import (
        ReleaseEvidenceError,
        parse_independent_verdict_json,
        parse_validation_binding_json,
    )

    repository = Path(__file__).resolve().parent.parent
    artifact = (
        repository
        / "docs/audits/evidence/2026-07-19-v0-v2-independent-verdict.json"
    )
    verdict = parse_independent_verdict_json(artifact.read_bytes())

    assert verdict["verdict"] == "CLEAR"
    assert verdict["release_authorized"] is False
    assert all(verdict["reviewer_checks"].values())

    identity_path = repository / verdict["identity_manifest"]["path"]
    identity_raw = identity_path.read_bytes()
    assert hashlib.sha256(identity_raw).hexdigest() == verdict[
        "identity_manifest"
    ]["file_sha256"]
    assert json.loads(identity_raw)["manifest_digest"] == verdict[
        "identity_manifest"
    ]["manifest_digest"]

    binding_path = repository / verdict["validation_binding"]["path"]
    binding_raw = binding_path.read_bytes()
    assert hashlib.sha256(binding_raw).hexdigest() == verdict[
        "validation_binding"
    ]["file_sha256"]
    assert parse_validation_binding_json(binding_raw).binding_digest == verdict[
        "validation_binding"
    ]["binding_digest"]

    unknown = dict(verdict)
    unknown["extra"] = True
    with pytest.raises(ReleaseEvidenceError, match="verdict fields"):
        parse_independent_verdict_json(json.dumps(unknown))

    authorized = dict(verdict)
    authorized["release_authorized"] = True
    with pytest.raises(ReleaseEvidenceError, match="never authorizes"):
        parse_independent_verdict_json(json.dumps(authorized))

    incomplete = json.loads(json.dumps(verdict))
    incomplete["reviewer_checks"]["runtime_fail_closed"] = False
    with pytest.raises(ReleaseEvidenceError, match="checks"):
        parse_independent_verdict_json(json.dumps(incomplete))

    duplicate = artifact.read_text(encoding="utf-8").replace(
        '"verdict": "CLEAR",',
        '"verdict": "CLEAR",\n  "verdict": "CLEAR",',
        1,
    )
    with pytest.raises(ReleaseEvidenceError, match="duplicate"):
        parse_independent_verdict_json(duplicate)

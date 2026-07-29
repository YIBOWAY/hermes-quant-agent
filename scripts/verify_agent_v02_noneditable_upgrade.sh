#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT/.venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
  echo "hqa_upgrade_error=python_not_executable" >&2
  exit 78
fi

BOOTSTRAP='
import hashlib
import importlib.util
import json
import os
import runpy
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

SANDBOX = "/usr/bin/sandbox-exec"
PROFILE = "(version 1) (allow default) (deny network*)"
GIT = "/usr/bin/git"
WRAPPER_RELATIVE = "scripts/verify_agent_v02_noneditable_upgrade.sh"
MAX_BYTES = 256 * 1024 * 1024


def fail():
    print("hqa_upgrade_error=commit_bound_bootstrap_failed", file=sys.stderr)
    raise SystemExit(78)


def write_once(path, payload):
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def safe_environment(home):
    return {
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "HOME": str(home),
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
    }


def git(root, environment, *arguments):
    completed = subprocess.run(
        [
            SANDBOX,
            "-p",
            PROFILE,
            GIT,
            "--no-replace-objects",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "credential.helper=",
            "-C",
            str(root),
            *arguments,
        ],
        check=False,
        capture_output=True,
        env=environment,
    )
    if completed.returncode != 0:
        fail()
    return completed.stdout


def output_argument(arguments):
    values = []
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument in {
            "--bootstrap-authority",
            "--bootstrap-authority-sha256",
        } or argument.startswith(
            ("--bootstrap-authority=", "--bootstrap-authority-sha256=")
        ):
            fail()
        if argument == "--output-dir":
            if index + 1 >= len(arguments):
                fail()
            values.append(arguments[index + 1])
            index += 2
            continue
        if argument.startswith("--output-dir="):
            values.append(argument.split("=", 1)[1])
        index += 1
    if len(values) != 1 or not values[0]:
        fail()
    return Path(os.path.abspath(values[0]))


def prepare():
    if not sys.flags.isolated or not sys.flags.no_site or not sys.flags.ignore_environment:
        fail()
    root = Path(sys.argv[1]).resolve(strict=True)
    wrapper = Path(sys.argv[2]).resolve(strict=True)
    arguments = list(sys.argv[3:])
    output = output_argument(arguments)
    parent = output.parent.resolve(strict=True)
    if output == root or root in output.parents:
        fail()
    bootstrap = Path(
        tempfile.mkdtemp(prefix=".hqa-upgrade-bootstrap-", dir=str(parent))
    )
    bootstrap.chmod(0o700)
    home = bootstrap / "home"
    home.mkdir(mode=0o700)
    environment = safe_environment(home)
    try:
        committed_wrapper = git(
            root,
            environment,
            "show",
            f"HEAD:{WRAPPER_RELATIVE}",
        )
        wrapper_bytes = wrapper.read_bytes()
        if wrapper_bytes != committed_wrapper:
            fail()
        commit = git(root, environment, "rev-parse", "--verify", "HEAD").decode(
            "ascii"
        ).strip()
        tree = git(
            root,
            environment,
            "rev-parse",
            "--verify",
            f"{commit}^{{tree}}",
        ).decode("ascii").strip()
        listing = git(root, environment, "ls-tree", "-r", "-z", commit, "--", "hqa")
        expected = {}
        for record in listing.split(b"\0"):
            if not record:
                continue
            metadata, raw_path = record.split(b"\t", 1)
            mode, kind, object_id = metadata.split(b" ", 2)
            path = raw_path.decode("utf-8", "strict")
            relative = PurePosixPath(path)
            if (
                kind != b"blob"
                or mode not in {b"100644", b"100755"}
                or relative.is_absolute()
                or "\\" in path
                or any(part in {"", ".", ".."} for part in relative.parts)
                or not path.startswith("hqa/")
                or path in expected
            ):
                fail()
            expected[path] = (mode.decode("ascii"), object_id.decode("ascii"))
        required = {
            "hqa/__init__.py",
            "hqa/noneditable_upgrade.py",
            "hqa/noneditable_upgrade_cli.py",
        }
        if not required.issubset(expected):
            fail()
        archive = git(root, environment, "archive", "--format=tar", commit, "--", "hqa")
        if len(archive) > MAX_BYTES:
            fail()
        archive_path = bootstrap / "source.tar"
        write_once(archive_path, archive)
        source = bootstrap / "source"
        source.mkdir(mode=0o700)
        observed = set()
        total = 0
        with tarfile.open(archive_path, mode="r:") as bundle:
            for member in bundle:
                raw = member.name.rstrip("/")
                relative = PurePosixPath(raw)
                if (
                    not raw
                    or relative.is_absolute()
                    or "\\" in raw
                    or any(part in {"", ".", ".."} for part in relative.parts)
                ):
                    fail()
                target = source.joinpath(*relative.parts)
                if member.isdir():
                    target.mkdir(mode=0o700, parents=True, exist_ok=True)
                    continue
                if not member.isfile() or raw not in expected or raw in observed:
                    fail()
                extracted = bundle.extractfile(member)
                if extracted is None:
                    fail()
                payload = extracted.read(MAX_BYTES + 1)
                total += len(payload)
                if len(payload) > MAX_BYTES or total > MAX_BYTES:
                    fail()
                mode, object_id = expected[raw]
                algorithm = hashlib.sha1 if len(object_id) == 40 else hashlib.sha256
                observed_id = algorithm(
                    b"blob " + str(len(payload)).encode("ascii") + b"\0" + payload
                ).hexdigest()
                if observed_id != object_id:
                    fail()
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                write_once(target, payload)
                target.chmod(0o700 if mode == "100755" else 0o600)
                observed.add(raw)
        if observed != set(expected):
            fail()
        if git(root, environment, "rev-parse", "--verify", "HEAD").decode(
            "ascii"
        ).strip() != commit:
            fail()
        manifest = [
            {"mode": expected[path][0], "object_id": expected[path][1], "path": path}
            for path in sorted(expected)
        ]
        authority = {
            "archive_sha256": hashlib.sha256(archive).hexdigest(),
            "commit": commit,
            "repository_root": str(root),
            "schema_version": "hqa.noneditable-upgrade-bootstrap.v1",
            "source_file_count": len(observed),
            "source_manifest_sha256": hashlib.sha256(
                json.dumps(
                    manifest, separators=(",", ":"), sort_keys=True
                ).encode()
            ).hexdigest(),
            "tree": tree,
            "wrapper_sha256": hashlib.sha256(wrapper_bytes).hexdigest(),
        }
        authority_payload = json.dumps(
            authority, separators=(",", ":"), sort_keys=True
        ).encode()
        authority_path = bootstrap / "authority.json"
        write_once(authority_path, authority_payload)
        expected_cli = (source / "hqa/noneditable_upgrade_cli.py").resolve(strict=True)
        sys.path.insert(0, str(source))
        spec = importlib.util.find_spec("hqa.noneditable_upgrade_cli")
        if spec is None or spec.origin is None or Path(spec.origin).resolve() != expected_cli:
            fail()
        sys.argv = [
            str(expected_cli),
            *arguments,
            "--bootstrap-authority",
            str(authority_path),
            "--bootstrap-authority-sha256",
            hashlib.sha256(authority_payload).hexdigest(),
        ]
        runpy.run_module("hqa.noneditable_upgrade_cli", run_name="__main__")
    finally:
        shutil.rmtree(bootstrap)


try:
    prepare()
except SystemExit:
    raise
except BaseException:
    fail()
'

exec "$PYTHON" "-I" "-S" "-B" -c "$BOOTSTRAP" "$ROOT" "$0" "$@"

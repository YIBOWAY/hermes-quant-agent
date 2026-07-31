#!/bin/bash
# Stage and validate the complete HQA Hermes install before publishing it;
# each wrapper, skill, and native helper is then replaced atomically per file.
# Installed wrappers freeze the V3 authority
# locations so test-only environment overrides cannot redirect scheduled jobs.
set -euo pipefail
umask 077

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLATFORM_DIR="${HQA_AIQP_DIR:-/Users/sunyibo/programs/ai-quant-platform}"
HERMES_ROOT="${HERMES_HOME:-$HOME/.hermes}"
case "$HERMES_ROOT" in
  /*) ;;
  *)
    echo "HERMES_HOME must be absolute" >&2
    exit 2
    ;;
esac
if [ "${HQA_HERMES_SOURCE_DIR+x}" = "x" ]; then
  HERMES_SOURCE_DIR="$HQA_HERMES_SOURCE_DIR"
else
  HERMES_SOURCE_DIR="$(/usr/bin/python3 - "$HERMES_ROOT" <<'PY'
import os
import sys


print(os.path.abspath(os.path.join(sys.argv[1], "hermes-agent")))
PY
)"
fi
case "$HERMES_SOURCE_DIR" in
  /*) ;;
  *)
    echo "HQA_HERMES_SOURCE_DIR must be absolute" >&2
    exit 2
    ;;
esac

CANONICAL_INTENT_PAYLOAD_DIR="$REPO_DIR/data/_runtime/intent-payloads-v2"
CANONICAL_WORKFLOW_AUTHORITY_DIR="$REPO_DIR/data/_runtime/workflow-authority-v2"
CANONICAL_CRYPTO_HELPER="$HERMES_ROOT/bin/hqa-intent-payload-crypto"
CANONICAL_OWNER_USER_ID="local-owner-v1"
STAGING_NAME=".hqa-install.$$.${RANDOM}"
STAGING="$HERMES_ROOT/$STAGING_NAME"

# Validate every existing component without following symlinks. Only after the
# deepest existing directory is proven owner-controlled may the missing private
# Hermes root and staging directories be created.
/usr/bin/python3 - "$HERMES_ROOT" "$STAGING_NAME" <<'PY'
import errno
import os
import stat
import sys


def fail(message):
    print(message, file=sys.stderr)
    raise SystemExit(2)


root = os.path.abspath(sys.argv[1])
staging_name = sys.argv[2]
flags = os.O_RDONLY | os.O_DIRECTORY
flags |= getattr(os, "O_CLOEXEC", 0)
flags |= getattr(os, "O_NOFOLLOW", 0)
current_fd = os.open(os.path.sep, flags)
parts = root.split(os.path.sep)[1:]
missing_at = None
try:
    root_metadata = os.fstat(current_fd)
    if (
        not stat.S_ISDIR(root_metadata.st_mode)
        or root_metadata.st_uid not in (0, os.geteuid())
        or stat.S_IMODE(root_metadata.st_mode) & 0o022
    ):
        fail("HERMES_HOME ancestor must be owner-controlled")
    for index, component in enumerate(parts):
        try:
            next_fd = os.open(component, flags, dir_fd=current_fd)
        except FileNotFoundError:
            missing_at = index
            break
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                fail("HERMES_HOME must contain only physical directories")
            raise
        metadata = os.fstat(next_fd)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid not in (0, os.geteuid())
            or stat.S_IMODE(metadata.st_mode) & 0o022
        ):
            os.close(next_fd)
            fail("HERMES_HOME ancestor must be owner-controlled")
        os.close(current_fd)
        current_fd = next_fd

    metadata = os.fstat(current_fd)
    if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) & 0o022:
        fail("HERMES_HOME ancestor must be owner-controlled")

    if missing_at is not None:
        for component in parts[missing_at:]:
            os.mkdir(component, 0o700, dir_fd=current_fd)
            os.fsync(current_fd)
            next_fd = os.open(component, flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd

    metadata = os.fstat(current_fd)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) & 0o022
    ):
        fail("HERMES_HOME must be a private physical directory")
    if stat.S_IMODE(metadata.st_mode) != 0o700:
        os.fchmod(current_fd, 0o700)
        os.fsync(current_fd)

    try:
        os.stat(staging_name, dir_fd=current_fd, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        fail("install staging path already exists")
    os.mkdir(staging_name, 0o700, dir_fd=current_fd)
    os.fsync(current_fd)
finally:
    os.close(current_fd)
PY

cleanup() {
  if [ -z "${STAGING_NAME:-}" ]; then
    return 0
  fi
  /usr/bin/python3 - "$HERMES_ROOT" "$STAGING_NAME" <<'PY'
import os
import stat
import sys


def open_physical_directory(path):
    flags = os.O_RDONLY | os.O_DIRECTORY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    current = os.open(os.path.sep, flags)
    try:
        root_metadata = os.fstat(current)
        if (
            not stat.S_ISDIR(root_metadata.st_mode)
            or root_metadata.st_uid not in (0, os.geteuid())
            or stat.S_IMODE(root_metadata.st_mode) & 0o022
        ):
            raise OSError("unsafe install ancestor")
        for component in os.path.abspath(path).split(os.path.sep)[1:]:
            next_fd = os.open(component, flags, dir_fd=current)
            metadata = os.fstat(next_fd)
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or metadata.st_uid not in (0, os.geteuid())
                or stat.S_IMODE(metadata.st_mode) & 0o022
            ):
                os.close(next_fd)
                raise OSError("unsafe install ancestor")
            os.close(current)
            current = next_fd
        return current
    except Exception:
        os.close(current)
        raise


def remove_tree(parent_fd, name):
    flags = os.O_RDONLY | os.O_DIRECTORY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid():
        raise OSError("install staging changed type or owner before cleanup")
    directory_fd = os.open(name, flags, dir_fd=parent_fd)
    try:
        for child in os.listdir(directory_fd):
            child_meta = os.stat(child, dir_fd=directory_fd, follow_symlinks=False)
            if child_meta.st_uid != os.geteuid():
                raise OSError("install staging child changed owner before cleanup")
            if stat.S_ISDIR(child_meta.st_mode):
                remove_tree(directory_fd, child)
            else:
                os.unlink(child, dir_fd=directory_fd)
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    os.rmdir(name, dir_fd=parent_fd)
    os.fsync(parent_fd)


try:
    root_fd = open_physical_directory(sys.argv[1])
except FileNotFoundError:
    raise SystemExit(0)
except (NotADirectoryError, OSError) as exc:
    print(f"install cleanup refused unsafe Hermes root: {exc}", file=sys.stderr)
    raise SystemExit(2)
try:
    root_meta = os.fstat(root_fd)
    if root_meta.st_uid != os.geteuid() or stat.S_IMODE(root_meta.st_mode) != 0o700:
        raise OSError("Hermes root changed owner or mode before cleanup")
    remove_tree(root_fd, sys.argv[2])
finally:
    os.close(root_fd)
PY
}

cleanup_and_exit() {
  original_status=$?
  trap - EXIT
  if cleanup; then
    exit "$original_status"
  else
    cleanup_status=$?
  fi
  echo "HQA install cleanup failed with status $cleanup_status" >&2
  if [ "$original_status" -ne 0 ]; then
    exit "$original_status"
  fi
  exit "$cleanup_status"
}
trap cleanup_and_exit EXIT

/bin/mkdir -m 700 "$STAGING/scripts" "$STAGING/skills" "$STAGING/bin"

# Render the complete candidate install into private staging. Python string
# replacement avoids sed replacement metacharacters in absolute paths.
/usr/bin/python3 - \
  "$REPO_DIR" \
  "$PLATFORM_DIR" \
  "$HERMES_SOURCE_DIR" \
  "$HERMES_ROOT/scripts" \
  "$CANONICAL_INTENT_PAYLOAD_DIR" \
  "$CANONICAL_WORKFLOW_AUTHORITY_DIR" \
  "$CANONICAL_CRYPTO_HELPER" \
  "$CANONICAL_OWNER_USER_ID" \
  "$STAGING" <<'PY'
import glob
import os
import shlex
import stat
import sys


def write_all(descriptor, payload):
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("staged install write made no progress")
        view = view[written:]


(
    repo_dir,
    platform_dir,
    hermes_source_dir,
    installed_scripts_dir,
    intent_payload_dir,
    workflow_authority_dir,
    crypto_helper,
    owner_user_id,
    staging,
) = sys.argv[1:]

exports = "\n".join(
    "export {}={}".format(name, shlex.quote(value))
    for name, value in (
        ("HQA_INTENT_PAYLOAD_DIR", intent_payload_dir),
        ("HQA_WORKFLOW_AUTHORITY_DIR", workflow_authority_dir),
        ("HQA_INTENT_PAYLOAD_CRYPTO_HELPER", crypto_helper),
        ("HQA_WORKFLOW_OWNER_USER_ID", owner_user_id),
    )
)

wrapper_sources = sorted(glob.glob(os.path.join(repo_dir, "scripts/hermes/hqa-*.sh")))
if not wrapper_sources:
    raise SystemExit("no Hermes wrappers found")
for source in wrapper_sources:
    body = open(source, encoding="utf-8").read()
    body = body.replace("__HQA_REPO_DIR__", repo_dir)
    body = body.replace("__HQA_PLATFORM_DIR__", platform_dir)
    body = body.replace(
        "__HQA_HERMES_SOURCE_DIR__", shlex.quote(hermes_source_dir)
    )
    body = body.replace("__HERMES_SCRIPTS_DIR__", installed_scripts_dir)
    if not body.startswith("#!/bin/bash\n"):
        raise SystemExit("wrapper lacks fixed bash shebang: " + source)
    body = "#!/bin/bash\n" + exports + "\n" + body[len("#!/bin/bash\n"):]
    if "__HQA_" in body or "__HERMES_" in body:
        raise SystemExit("unsubstituted wrapper placeholder: " + source)
    destination = os.path.join(staging, "scripts", os.path.basename(source))
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700)
    try:
        write_all(descriptor, body.encode("utf-8"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)

launcher_sources = sorted(glob.glob(os.path.join(repo_dir, "scripts/hermes/hqa-*.py")))
for source in launcher_sources:
    body = open(source, encoding="utf-8").read()
    body = body.replace("__HQA_REPO_DIR__", repo_dir)
    body = body.replace("__HQA_PLATFORM_DIR__", platform_dir)
    body = body.replace(
        "__HQA_HERMES_SOURCE_DIR__", shlex.quote(hermes_source_dir)
    )
    body = body.replace("__HERMES_SCRIPTS_DIR__", installed_scripts_dir)
    if not body.startswith("#!/usr/bin/python3\n"):
        raise SystemExit("launcher lacks fixed Python shebang: " + source)
    if "__HQA_" in body or "__HERMES_" in body:
        raise SystemExit("unsubstituted launcher placeholder: " + source)
    destination = os.path.join(staging, "scripts", os.path.basename(source))
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700)
    try:
        write_all(descriptor, body.encode("utf-8"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)

skill_sources = sorted(glob.glob(os.path.join(repo_dir, "skills/hermes/*/SKILL.md")))
for source in skill_sources:
    skill_name = os.path.basename(os.path.dirname(source))
    skill_dir = os.path.join(staging, "skills", skill_name)
    os.mkdir(skill_dir, 0o700)
    body = open(source, encoding="utf-8").read()
    body = body.replace("__HQA_REPO_DIR__", repo_dir)
    body = body.replace("__HQA_PLATFORM_DIR__", platform_dir)
    body = body.replace(
        "__HQA_HERMES_SOURCE_DIR__", shlex.quote(hermes_source_dir)
    )
    body = body.replace("__HERMES_SCRIPTS_DIR__", installed_scripts_dir)
    if "__HQA_" in body or "__HERMES_" in body:
        raise SystemExit("unsubstituted skill placeholder: " + source)
    destination = os.path.join(skill_dir, "SKILL.md")
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        write_all(descriptor, body.encode("utf-8"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
PY

for wrapper in "$STAGING"/scripts/hqa-*.sh; do
  /bin/bash -n "$wrapper"
done

SKIP_NATIVE_BUILD="${HQA_SKIP_NATIVE_BUILD:-0}"
case "$SKIP_NATIVE_BUILD" in
  0)
    /bin/bash "$REPO_DIR/scripts/build_intent_payload_crypto.sh" \
      "$STAGING/bin/hqa-intent-payload-crypto"
    ;;
  1)
    /usr/bin/python3 - "$HERMES_ROOT" <<'PY'
import errno
import os
import stat
import subprocess
import sys


def fail(message):
    print(message, file=sys.stderr)
    raise SystemExit(2)


flags = os.O_RDONLY | os.O_DIRECTORY
flags |= getattr(os, "O_CLOEXEC", 0)
flags |= getattr(os, "O_NOFOLLOW", 0)
current_fd = os.open(os.path.sep, flags)
root = os.path.abspath(sys.argv[1])
try:
    root_metadata = os.fstat(current_fd)
    if (
        not stat.S_ISDIR(root_metadata.st_mode)
        or root_metadata.st_uid not in (0, os.geteuid())
        or stat.S_IMODE(root_metadata.st_mode) & 0o022
    ):
        fail("helper ancestor must be owner-controlled")
    for component in root.split(os.path.sep)[1:]:
        try:
            next_fd = os.open(component, flags, dir_fd=current_fd)
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                fail("helper path must contain only physical directories")
            raise
        metadata = os.fstat(next_fd)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid not in (0, os.geteuid())
            or stat.S_IMODE(metadata.st_mode) & 0o022
        ):
            os.close(next_fd)
            fail("helper ancestor must be owner-controlled")
        os.close(current_fd)
        current_fd = next_fd
    try:
        bin_fd = os.open("bin", flags, dir_fd=current_fd)
    except FileNotFoundError:
        fail("native build skip requires an existing helper")
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            fail("helper path must contain only physical directories")
        raise
    try:
        bin_metadata = os.fstat(bin_fd)
        if (
            not stat.S_ISDIR(bin_metadata.st_mode)
            or bin_metadata.st_uid != os.geteuid()
            or stat.S_IMODE(bin_metadata.st_mode) != 0o700
        ):
            fail("helper parent must be an exact private physical directory")
        try:
            helper_fd = os.open(
                "hqa-intent-payload-crypto",
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=bin_fd,
            )
        except FileNotFoundError:
            fail("native build skip requires an existing helper")
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                fail("native build skip requires an exact private physical helper")
            raise
        try:
            metadata = os.fstat(helper_fd)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or metadata.st_nlink != 1
                or stat.S_IMODE(metadata.st_mode) != 0o700
            ):
                fail("native build skip requires an exact private physical helper")
            result = subprocess.run(
                [
                    os.path.join(
                        root,
                        "bin",
                        "hqa-intent-payload-crypto",
                    )
                ],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=5,
            )
            if result.returncode != 64 or result.stdout or result.stderr:
                fail("existing native helper failed its protocol identity check")
        finally:
            os.close(helper_fd)
    finally:
        os.close(bin_fd)
finally:
    os.close(current_fd)
PY
    echo "reused verified native helper: $CANONICAL_CRYPTO_HELPER"
    ;;
  *)
    echo "HQA_SKIP_NATIVE_BUILD must be 0 or 1" >&2
    exit 2
    ;;
esac

# Freeze the compatibility watcher to the exact checkout selected at install
# time. A linked Git worktree is valid, but the worktree root and its resolved
# Git directory must both be physical and owner-controlled.
/usr/bin/python3 - "$HERMES_SOURCE_DIR" <<'PY'
import errno
import os
import re
import stat
import subprocess
import sys


def fail(message):
    print(message, file=sys.stderr)
    raise SystemExit(2)


def open_owner_controlled_directory(path, *, require_current_owner):
    flags = os.O_RDONLY | os.O_DIRECTORY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    current_fd = os.open(os.path.sep, flags)
    try:
        parts = os.path.abspath(path).split(os.path.sep)[1:]
        for index, component in enumerate(parts):
            try:
                next_fd = os.open(component, flags, dir_fd=current_fd)
            except OSError as exc:
                if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                    fail("Hermes source must contain only physical directories")
                raise
            metadata = os.fstat(next_fd)
            final = index == len(parts) - 1
            owner_allowed = (
                metadata.st_uid == os.geteuid()
                if final and require_current_owner
                else metadata.st_uid in (0, os.geteuid())
            )
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or not owner_allowed
                or stat.S_IMODE(metadata.st_mode) & 0o022
            ):
                os.close(next_fd)
                fail("Hermes source must be owner-controlled")
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except Exception:
        os.close(current_fd)
        raise


source = sys.argv[1]
if (
    not os.path.isabs(source)
    or source != os.path.abspath(source)
    or len(os.fsencode(source)) > 4096
    or any(ord(character) < 0x20 for character in source)
):
    fail("HQA_HERMES_SOURCE_DIR must be a canonical absolute path")

try:
    source_fd = open_owner_controlled_directory(
        source,
        require_current_owner=True,
    )
except FileNotFoundError:
    fail("Hermes source checkout is unavailable")
finally:
    if "source_fd" in locals():
        os.close(source_fd)

git = "/usr/bin/git"
if not os.path.isfile(git):
    fail("Git is unavailable for Hermes source validation")
git_environment = {
    "HOME": os.environ.get("HOME", os.path.sep),
    "PATH": "/usr/bin:/bin",
    "GIT_CONFIG_NOSYSTEM": "1",
}


def git_output(*arguments):
    try:
        result = subprocess.run(
            [git, "-C", source, *arguments],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=True,
            timeout=5,
            env=git_environment,
        )
    except (OSError, subprocess.SubprocessError):
        fail("Hermes source must be a readable Git worktree checkout")
    if result.stderr or len(result.stdout) > 8192:
        fail("Hermes source Git identity is unavailable")
    try:
        return result.stdout.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError:
        fail("Hermes source Git identity is unavailable")


if git_output("rev-parse", "--is-inside-work-tree") != "true":
    fail("Hermes source must be a Git worktree checkout")
top_level = git_output("rev-parse", "--show-toplevel")
if top_level != source:
    fail("HQA_HERMES_SOURCE_DIR must name the Git worktree root")
head = git_output("rev-parse", "--verify", "HEAD^{commit}")
if re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", head) is None:
    fail("Hermes source Git commit identity is invalid")
git_dir = git_output("rev-parse", "--absolute-git-dir")
try:
    git_fd = open_owner_controlled_directory(
        git_dir,
        require_current_owner=True,
    )
except FileNotFoundError:
    fail("Hermes source Git directory is unavailable")
finally:
    if "git_fd" in locals():
        os.close(git_fd)
PY

# Preflight every destination before creating or replacing any published file,
# then publish staged files with fd-relative per-file replace and fsync.
/usr/bin/python3 - "$HERMES_ROOT" "$STAGING_NAME" "$SKIP_NATIVE_BUILD" <<'PY'
import errno
import os
import stat
import sys


def fail(message):
    print(message, file=sys.stderr)
    raise SystemExit(2)


root = os.path.abspath(sys.argv[1])
staging_name = sys.argv[2]
skip_native = sys.argv[3] == "1"
flags = os.O_RDONLY | os.O_DIRECTORY
flags |= getattr(os, "O_CLOEXEC", 0)
flags |= getattr(os, "O_NOFOLLOW", 0)


def open_physical_root(path):
    current = os.open(os.path.sep, flags)
    try:
        root_metadata = os.fstat(current)
        if (
            not stat.S_ISDIR(root_metadata.st_mode)
            or root_metadata.st_uid not in (0, os.geteuid())
            or stat.S_IMODE(root_metadata.st_mode) & 0o022
        ):
            fail("install ancestor is not owner-controlled")
        for component in os.path.abspath(path).split(os.path.sep)[1:]:
            try:
                next_fd = os.open(component, flags, dir_fd=current)
            except OSError as exc:
                if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                    fail("install destination contains a symlink or non-directory")
                raise
            metadata = os.fstat(next_fd)
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or metadata.st_uid not in (0, os.geteuid())
                or stat.S_IMODE(metadata.st_mode) & 0o022
            ):
                os.close(next_fd)
                fail("install ancestor is not owner-controlled")
            os.close(current)
            current = next_fd
        return current
    except Exception:
        os.close(current)
        raise


root_fd = open_physical_root(root)
stage_fd = None
opened = []
try:
    root_meta = os.fstat(root_fd)
    if root_meta.st_uid != os.geteuid() or stat.S_IMODE(root_meta.st_mode) != 0o700:
        fail("HERMES_HOME changed during install")
    stage_fd = os.open(staging_name, flags, dir_fd=root_fd)
    stage_meta = os.fstat(stage_fd)
    if stage_meta.st_uid != os.geteuid() or stat.S_IMODE(stage_meta.st_mode) != 0o700:
        fail("install staging is not private")

    staged = []
    for top, mode in (("scripts", 0o700), ("skills", 0o700), ("bin", 0o700)):
        top_fd = os.open(top, flags, dir_fd=stage_fd)
        opened.append(top_fd)
        top_meta = os.fstat(top_fd)
        if top_meta.st_uid != os.geteuid() or stat.S_IMODE(top_meta.st_mode) != mode:
            fail("invalid staging directory")
        if top == "scripts":
            for name in sorted(os.listdir(top_fd)):
                staged.append(("scripts", name, 0o700))
        elif top == "skills":
            for skill_name in sorted(os.listdir(top_fd)):
                skill_fd = os.open(skill_name, flags, dir_fd=top_fd)
                opened.append(skill_fd)
                staged.append(("skills/" + skill_name, "SKILL.md", 0o600))
        elif not skip_native:
            staged.append(("bin", "hqa-intent-payload-crypto", 0o700))

    required_dirs = {"scripts", "skills", "bin"}
    required_dirs.update(directory for directory, _name, _mode in staged)

    # Complete no-write preflight of every existing final directory and file.
    for relative in sorted(required_dirs, key=lambda item: (item.count("/"), item)):
        parent_fd = root_fd
        parts = relative.split("/")
        for part in parts:
            try:
                next_fd = os.open(part, flags, dir_fd=parent_fd)
            except FileNotFoundError:
                break
            except OSError as exc:
                if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                    fail("install destination contains a symlink or non-directory")
                raise
            if parent_fd != root_fd:
                os.close(parent_fd)
            parent_fd = next_fd
        if parent_fd != root_fd:
            meta = os.fstat(parent_fd)
            if meta.st_uid != os.geteuid() or stat.S_IMODE(meta.st_mode) & 0o022:
                fail("install destination directory is not owner-controlled")
            os.close(parent_fd)

    for directory, name, mode in staged:
        parent_fd = root_fd
        try:
            for part in directory.split("/"):
                try:
                    next_fd = os.open(part, flags, dir_fd=parent_fd)
                except FileNotFoundError:
                    next_fd = None
                if next_fd is None:
                    break
                if parent_fd != root_fd:
                    os.close(parent_fd)
                parent_fd = next_fd
            else:
                try:
                    meta = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                except FileNotFoundError:
                    meta = None
                if meta is not None and (
                    not stat.S_ISREG(meta.st_mode)
                    or meta.st_uid != os.geteuid()
                    or meta.st_nlink != 1
                    or stat.S_IMODE(meta.st_mode) & 0o022
                ):
                    fail("existing install file is not owner-controlled and physical")
        finally:
            if parent_fd != root_fd:
                os.close(parent_fd)

    # Create missing final directories only after the complete preflight passes.
    for relative in sorted(required_dirs, key=lambda item: (item.count("/"), item)):
        parent_fd = root_fd
        try:
            for part in relative.split("/"):
                try:
                    next_fd = os.open(part, flags, dir_fd=parent_fd)
                except FileNotFoundError:
                    os.mkdir(part, 0o700, dir_fd=parent_fd)
                    os.fsync(parent_fd)
                    next_fd = os.open(part, flags, dir_fd=parent_fd)
                if parent_fd != root_fd:
                    os.close(parent_fd)
                parent_fd = next_fd
        finally:
            if parent_fd != root_fd:
                os.close(parent_fd)

    for directory, name, mode in staged:
        source_parent = stage_fd
        source_opened = []
        for part in directory.split("/"):
            source_parent = os.open(part, flags, dir_fd=source_parent)
            source_opened.append(source_parent)
        destination_parent = root_fd
        destination_opened = []
        for part in directory.split("/"):
            destination_parent = os.open(part, flags, dir_fd=destination_parent)
            destination_opened.append(destination_parent)
        try:
            source_fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=source_parent)
            try:
                meta = os.fstat(source_fd)
                if (
                    not stat.S_ISREG(meta.st_mode)
                    or meta.st_uid != os.geteuid()
                    or meta.st_nlink != 1
                    or stat.S_IMODE(meta.st_mode) != mode
                ):
                    fail("staged install file failed final validation")
                os.fsync(source_fd)
            finally:
                os.close(source_fd)
            os.replace(
                name,
                name,
                src_dir_fd=source_parent,
                dst_dir_fd=destination_parent,
            )
            os.fsync(destination_parent)
        finally:
            for descriptor in reversed(source_opened + destination_opened):
                os.close(descriptor)
finally:
    for descriptor in reversed(opened):
        try:
            os.close(descriptor)
        except OSError:
            pass
    if stage_fd is not None:
        os.close(stage_fd)
    os.close(root_fd)
PY

for source in "$REPO_DIR"/scripts/hermes/hqa-*.sh; do
  [ -e "$source" ] || continue
  echo "installed: $HERMES_ROOT/scripts/$(basename "$source")"
done
for source in "$REPO_DIR"/scripts/hermes/hqa-*.py; do
  [ -e "$source" ] || continue
  echo "installed: $HERMES_ROOT/scripts/$(basename "$source")"
done
for source in "$REPO_DIR"/skills/hermes/*/SKILL.md; do
  [ -e "$source" ] || continue
  skill_name="$(basename "$(dirname "$source")")"
  echo "installed: $HERMES_ROOT/skills/$skill_name/SKILL.md"
done
if [ "$SKIP_NATIVE_BUILD" = "0" ]; then
  echo "installed: $CANONICAL_CRYPTO_HELPER"
fi

#!/bin/bash
set -euo pipefail
umask 077

if [ "$#" -ne 1 ]; then
  echo "usage: build_intent_payload_crypto.sh /absolute/path/hqa-intent-payload-crypto" >&2
  exit 2
fi

DESTINATION="$1"
case "$DESTINATION" in
  /*/hqa-intent-payload-crypto) ;;
  *)
    echo "destination must be an absolute hqa-intent-payload-crypto path" >&2
    exit 2
    ;;
esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="$SCRIPT_DIR/../native/intent-payload-crypto/main.swift"
PARENT="$(dirname "$DESTINATION")"

/usr/bin/python3 - "$PARENT" "$DESTINATION" <<'PY'
import errno
import os
import stat
import sys


def fail(message):
    print(message, file=sys.stderr)
    raise SystemExit(2)


parent = os.path.abspath(sys.argv[1])
destination = os.path.abspath(sys.argv[2])
if os.path.dirname(destination) != parent:
    fail("destination parent mismatch")

flags = os.O_RDONLY | os.O_DIRECTORY
flags |= getattr(os, "O_CLOEXEC", 0)
flags |= getattr(os, "O_NOFOLLOW", 0)
current_fd = os.open(os.path.sep, flags)
remaining = parent.split(os.path.sep)[1:]
missing_at = None
try:
    root_metadata = os.fstat(current_fd)
    if (
        not stat.S_ISDIR(root_metadata.st_mode)
        or root_metadata.st_uid not in (0, os.geteuid())
        or stat.S_IMODE(root_metadata.st_mode) & 0o022
    ):
        fail("destination ancestor must be owner-controlled")
    for index, component in enumerate(remaining):
        try:
            next_fd = os.open(component, flags, dir_fd=current_fd)
        except FileNotFoundError:
            missing_at = index
            break
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                fail("destination path must contain only physical directories")
            raise
        metadata = os.fstat(next_fd)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid not in (0, os.geteuid())
            or stat.S_IMODE(metadata.st_mode) & 0o022
        ):
            os.close(next_fd)
            fail("destination ancestor must be owner-controlled")
        os.close(current_fd)
        current_fd = next_fd

    metadata = os.fstat(current_fd)
    if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) & 0o022:
        fail("destination ancestor must be owner-controlled")

    if missing_at is None:
        try:
            target = os.stat(
                os.path.basename(destination),
                dir_fd=current_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            target = None
        if target is not None and (
            not stat.S_ISREG(target.st_mode)
            or target.st_uid != os.geteuid()
            or target.st_nlink != 1
            or stat.S_IMODE(target.st_mode) != 0o700
        ):
            fail("existing destination must be a private physical helper")
    else:
        for component in remaining[missing_at:]:
            os.mkdir(component, 0o700, dir_fd=current_fd)
            os.fsync(current_fd)
            next_fd = os.open(component, flags, dir_fd=current_fd)
            metadata = os.fstat(next_fd)
            if (
                metadata.st_uid != os.geteuid()
                or not stat.S_ISDIR(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o700
            ):
                os.close(next_fd)
                fail("created destination directory is not private")
            os.close(current_fd)
            current_fd = next_fd

    metadata = os.fstat(current_fd)
    if metadata.st_uid != os.geteuid() or not stat.S_ISDIR(metadata.st_mode):
        fail("destination parent must be owner-controlled")
    if stat.S_IMODE(metadata.st_mode) != 0o700:
        os.fchmod(current_fd, 0o700)
        os.fsync(current_fd)
finally:
    os.close(current_fd)
PY

SWIFTC="$(/usr/bin/xcrun --find swiftc)"
SDK="$(/usr/bin/xcrun --show-sdk-path)"
TEMPORARY_DIRECTORY="$(
  /usr/bin/mktemp -d "$PARENT/.hqa-intent-payload-crypto-build.XXXXXX"
)"
TEMPORARY="$TEMPORARY_DIRECTORY/hqa-intent-payload-crypto"
cleanup() {
  if [ -n "${TEMPORARY:-}" ]; then
    /bin/rm -f -- "$TEMPORARY"
  fi
  if [ -n "${TEMPORARY_DIRECTORY:-}" ] && [ -d "$TEMPORARY_DIRECTORY" ]; then
    /bin/rmdir -- "$TEMPORARY_DIRECTORY"
  fi
}

cleanup_and_exit() {
  original_status=$?
  trap - EXIT
  if cleanup; then
    exit "$original_status"
  else
    cleanup_status=$?
  fi
  echo "intent payload crypto cleanup failed with status $cleanup_status" >&2
  if [ "$original_status" -ne 0 ]; then
    exit "$original_status"
  fi
  exit "$cleanup_status"
}
trap cleanup_and_exit EXIT

"$SWIFTC" \
  -sdk "$SDK" \
  -O \
  -whole-module-optimization \
  -o "$TEMPORARY" \
  "$SOURCE"
/bin/chmod 700 "$TEMPORARY"
/usr/bin/codesign \
  --force \
  --sign - \
  --identifier hqa-intent-payload-crypto \
  --timestamp=none \
  "$TEMPORARY"
/usr/bin/codesign --verify --strict "$TEMPORARY"
/usr/bin/python3 - "$TEMPORARY_DIRECTORY" "$TEMPORARY" "$DESTINATION" <<'PY'
import os
import stat
import sys


temporary_directory = os.path.abspath(sys.argv[1])
temporary = os.path.abspath(sys.argv[2])
destination = os.path.abspath(sys.argv[3])
parent = os.path.dirname(destination)
if os.path.dirname(temporary_directory) != parent:
    raise SystemExit("temporary directory must share destination parent")
if (
    os.path.dirname(temporary) != temporary_directory
    or os.path.basename(temporary) != "hqa-intent-payload-crypto"
):
    raise SystemExit("temporary helper must have the stable private build path")

flags = os.O_RDONLY | os.O_DIRECTORY
flags |= getattr(os, "O_CLOEXEC", 0)
flags |= getattr(os, "O_NOFOLLOW", 0)
parent_fd = os.open(os.path.sep, flags)
try:
    root_metadata = os.fstat(parent_fd)
    if (
        not stat.S_ISDIR(root_metadata.st_mode)
        or root_metadata.st_uid not in (0, os.geteuid())
        or stat.S_IMODE(root_metadata.st_mode) & 0o022
    ):
        raise SystemExit("destination ancestor must be owner-controlled")
    for component in parent.split(os.path.sep)[1:]:
        next_fd = os.open(component, flags, dir_fd=parent_fd)
        metadata = os.fstat(next_fd)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid not in (0, os.geteuid())
            or stat.S_IMODE(metadata.st_mode) & 0o022
        ):
            os.close(next_fd)
            raise SystemExit("destination ancestor must be owner-controlled")
        os.close(parent_fd)
        parent_fd = next_fd
    parent_metadata = os.fstat(parent_fd)
    if (
        parent_metadata.st_uid != os.geteuid()
        or stat.S_IMODE(parent_metadata.st_mode) != 0o700
    ):
        raise SystemExit("destination parent must remain private")
    temporary_directory_name = os.path.basename(temporary_directory)
    temporary_directory_fd = os.open(
        temporary_directory_name,
        flags,
        dir_fd=parent_fd,
    )
    temporary_directory_metadata = os.fstat(temporary_directory_fd)
    if (
        not stat.S_ISDIR(temporary_directory_metadata.st_mode)
        or temporary_directory_metadata.st_uid != os.geteuid()
        or stat.S_IMODE(temporary_directory_metadata.st_mode) != 0o700
    ):
        raise SystemExit("temporary build directory is not private")
    temp_name = os.path.basename(temporary)
    destination_name = os.path.basename(destination)
    temp = os.stat(
        temp_name,
        dir_fd=temporary_directory_fd,
        follow_symlinks=False,
    )
    if (
        not stat.S_ISREG(temp.st_mode)
        or temp.st_uid != os.geteuid()
        or temp.st_nlink != 1
        or stat.S_IMODE(temp.st_mode) != 0o700
    ):
        raise SystemExit("compiled helper is not a private physical file")
    try:
        target = os.stat(
            destination_name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        target = None
    if target is not None and (
        not stat.S_ISREG(target.st_mode)
        or target.st_uid != os.geteuid()
        or target.st_nlink != 1
        or stat.S_IMODE(target.st_mode) != 0o700
    ):
        raise SystemExit("existing destination must be a private physical helper")
    os.replace(
        temp_name,
        destination_name,
        src_dir_fd=temporary_directory_fd,
        dst_dir_fd=parent_fd,
    )
    os.fsync(parent_fd)
finally:
    if "temporary_directory_fd" in locals():
        os.close(temporary_directory_fd)
    os.close(parent_fd)
PY
TEMPORARY=""
/bin/rmdir -- "$TEMPORARY_DIRECTORY"
TEMPORARY_DIRECTORY=""

echo "built: $DESTINATION"

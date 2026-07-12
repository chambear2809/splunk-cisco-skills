#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<EOF
Write Secret File

Usage: $(basename "$0") [OPTIONS] PATH

Options:
  --prompt TEXT   Prompt label to show while reading the secret
  --editor        Open PATH in \$VISUAL or \$EDITOR instead of reading one secret line
  --force         Overwrite PATH if it already exists
  --help          Show this help

Reads a secret interactively without echoing it, asks for confirmation, and
writes PATH atomically with mode 600. This avoids putting secrets in shell
history or process arguments.
EOF
}

PROMPT="Secret"
FORCE=false
EDITOR_MODE=false
OUTPUT_PATH=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --prompt)
            if [[ $# -lt 2 ]]; then
                echo "ERROR: --prompt requires a value." >&2
                exit 1
            fi
            PROMPT="$2"
            shift 2
            ;;
        --force)
            FORCE=true
            shift
            ;;
        --editor)
            EDITOR_MODE=true
            shift
            ;;
        --help)
            usage
            exit 0
            ;;
        -*)
            echo "ERROR: Unknown option: $1" >&2
            usage >&2
            exit 1
            ;;
        *)
            if [[ -n "${OUTPUT_PATH}" ]]; then
                echo "ERROR: Only one output path is supported." >&2
                exit 1
            fi
            OUTPUT_PATH="$1"
            shift
            ;;
    esac
done

if [[ -z "${OUTPUT_PATH}" ]]; then
    usage >&2
    exit 1
fi

# Keep target validation, staging, and publication in one process with an open
# parent-directory descriptor. A shell-level "does not exist" check followed by
# redirection is vulnerable to symlink substitution and other TOCTOU races.
python3 - "${OUTPUT_PATH}" "${PROMPT}" "${FORCE}" "${EDITOR_MODE}" <<'PY'
import errno
import getpass
import os
import secrets
import shlex
import stat
import subprocess
import sys


class SecretWriterError(Exception):
    pass


def fail(message):
    raise SecretWriterError(message)


def fsync_directory(directory_fd):
    try:
        os.fsync(directory_fd)
    except OSError as error:
        # Some otherwise POSIX-compatible filesystems do not support fsync on
        # directory descriptors. The publish operation is still atomic there,
        # though its crash-durability cannot be strengthened by this helper.
        if error.errno not in {errno.EINVAL, errno.ENOTSUP}:
            raise


def validate_directory_metadata(metadata, label):
    current_uid = os.geteuid()
    trusted_owner = metadata.st_uid in {0, current_uid}
    owner_can_write = bool(metadata.st_mode & stat.S_IWUSR)
    shared_writable = bool(metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH))
    sticky = bool(metadata.st_mode & stat.S_ISVTX)
    if (owner_can_write and not trusted_owner) or (
        shared_writable and not (sticky and trusted_owner)
    ):
        fail(f"refusing an unsafe writable output parent component: {label}")


def open_resolved_directory(path):
    if (
        not hasattr(os, "O_NOFOLLOW")
        or not hasattr(os, "O_DIRECTORY")
        or not hasattr(os, "geteuid")
    ):
        fail("secure secret writes require POSIX no-follow descriptor support")

    resolved = os.path.realpath(path)
    if not os.path.isabs(resolved):
        fail("could not resolve the output parent directory")

    flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )
    directory_fd = os.open(os.path.sep, flags)
    try:
        validate_directory_metadata(os.fstat(directory_fd), os.path.sep)
        for component in resolved.split(os.path.sep)[1:]:
            if not component:
                continue
            if component in {".", ".."}:
                fail(f"invalid output parent component: {component!r}")
            next_fd = os.open(component, flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
            validate_directory_metadata(os.fstat(directory_fd), component)

        opened = os.fstat(directory_fd)
        named = os.stat(resolved, follow_symlinks=False)
        if (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino):
            fail("output parent directory changed while it was being opened")
        requested = os.stat(path)
        if (opened.st_dev, opened.st_ino) != (
            requested.st_dev,
            requested.st_ino,
        ):
            fail("output parent alias changed while it was being opened")
        return directory_fd, resolved
    except BaseException:
        os.close(directory_fd)
        raise


def stat_entry(directory_fd, name):
    try:
        return os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def allocate_staging_file(directory_fd):
    flags = (
        os.O_RDWR
        | os.O_CREAT
        | os.O_EXCL
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )
    for _ in range(128):
        name = f".write-secret.{secrets.token_hex(16)}.tmp"
        try:
            descriptor = os.open(name, flags, 0o600, dir_fd=directory_fd)
        except FileExistsError:
            continue
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or metadata.st_uid != os.geteuid()
            ):
                fail("private secret staging file failed descriptor validation")
            os.fchmod(descriptor, 0o600)
        except BaseException:
            os.close(descriptor)
            try:
                os.unlink(name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
            raise
        return name, descriptor
    fail("could not allocate a private secret staging file")


def verify_staging_file(directory_fd, name):
    flags = (
        os.O_RDWR
        | os.O_NOFOLLOW
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptor = os.open(name, flags, dir_fd=directory_fd)
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_uid != os.geteuid()
        ):
            fail("secret staging file changed or became unsafe")
        os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_all(descriptor, payload):
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            fail("could not write the complete secret")
        view = view[written:]
    os.fsync(descriptor)


def parent_path_still_matches(directory_fd, resolved_parent, requested_parent):
    opened = os.fstat(directory_fd)
    named = os.stat(resolved_parent, follow_symlinks=False)
    if (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino):
        fail("output parent directory changed while the secret was being prepared")
    requested = os.stat(requested_parent)
    if (opened.st_dev, opened.st_ino) != (
        requested.st_dev,
        requested.st_ino,
    ):
        fail("output parent alias changed while the secret was being prepared")


def main():
    output_path, prompt, force_text, editor_text = sys.argv[1:]
    force = force_text == "true"
    editor_mode = editor_text == "true"

    output_name = os.path.basename(output_path)
    if not output_name or output_name in {".", ".."}:
        fail(f"invalid output file path: {output_path}")
    if os.path.isabs(output_path):
        absolute_output = output_path
    else:
        absolute_output = os.path.join(os.getcwd(), output_path)
    parent_input = os.path.dirname(absolute_output)

    parent_fd = -1
    staging_name = ""
    staging_fd = -1
    try:
        parent_fd, resolved_parent = open_resolved_directory(parent_input)
        existing = stat_entry(parent_fd, output_name)
        if existing is not None and not force:
            fail(
                f"refusing to overwrite existing file: {output_path}\n"
                "Use --force if you intentionally want to replace it."
            )
        if existing is not None and stat.S_ISDIR(existing.st_mode):
            fail(f"refusing to replace a directory: {output_path}")

        staging_name, staging_fd = allocate_staging_file(parent_fd)
        staging_path = os.path.join(resolved_parent, staging_name)

        if editor_mode:
            os.close(staging_fd)
            staging_fd = -1
            parent_path_still_matches(parent_fd, resolved_parent, parent_input)
            editor_value = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
            try:
                editor_args = shlex.split(editor_value)
            except ValueError as error:
                fail(f"invalid VISUAL/EDITOR command: {error}")
            if not editor_args:
                fail("VISUAL/EDITOR command is empty")
            completed = subprocess.run([*editor_args, staging_path], check=False)
            if completed.returncode != 0:
                fail(f"editor exited with status {completed.returncode}")
            parent_path_still_matches(parent_fd, resolved_parent, parent_input)
            verify_staging_file(parent_fd, staging_name)
        else:
            if not sys.stdin.isatty():
                fail(
                    "refusing to read a secret from non-interactive stdin\n"
                    "Run this script from a terminal so the secret is not captured "
                    "in shell history."
                )
            secret_value = getpass.getpass(f"{prompt}: ")
            secret_confirm = getpass.getpass(f"Confirm {prompt}: ")
            if secret_value != secret_confirm:
                fail("secret values did not match")
            try:
                payload = f"{secret_value}\n".encode("utf-8")
            except UnicodeError as error:
                fail(f"secret could not be encoded as UTF-8: {error}")
            write_all(staging_fd, payload)
            os.close(staging_fd)
            staging_fd = -1
            verify_staging_file(parent_fd, staging_name)

        # os.replace addresses the exact directory entry, so --force replaces a
        # symlink rather than following it. Without --force, hard-link creation
        # is an atomic create-if-absent operation that also rejects dangling
        # symlinks and target entries introduced after the initial check.
        parent_path_still_matches(parent_fd, resolved_parent, parent_input)
        if force:
            os.replace(
                staging_name,
                output_name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            staging_name = ""
        else:
            try:
                os.link(
                    staging_name,
                    output_name,
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                    follow_symlinks=False,
                )
            except FileExistsError:
                fail(f"output path appeared before publication: {output_path}")
            os.unlink(staging_name, dir_fd=parent_fd)
            staging_name = ""
        fsync_directory(parent_fd)
    finally:
        if staging_fd >= 0:
            os.close(staging_fd)
        if staging_name and parent_fd >= 0:
            try:
                os.unlink(staging_name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
        if parent_fd >= 0:
            os.close(parent_fd)

    action = "ready" if editor_mode else "written"
    published_path = os.path.join(resolved_parent, output_name)
    print(f"Secret file {action} at {published_path} (mode 600).")


try:
    main()
except SecretWriterError as error:
    print(f"ERROR: {error}", file=sys.stderr)
    raise SystemExit(1)
except (EOFError, KeyboardInterrupt):
    print("\nERROR: Secret entry was cancelled.", file=sys.stderr)
    raise SystemExit(1)
except OSError as error:
    print(f"ERROR: Secure secret write failed: {error}", file=sys.stderr)
    raise SystemExit(1)
PY

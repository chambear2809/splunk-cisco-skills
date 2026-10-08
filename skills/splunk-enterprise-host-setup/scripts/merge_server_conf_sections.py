#!/usr/bin/env python3
from __future__ import annotations
import os
import pwd
import re
import stat
import sys
import tempfile
import time
from pathlib import Path

SECTION = re.compile(r"^\[([^\]\r\n]+)\]\s*(?:\r?\n|$)", re.MULTILINE)
ALLOWED = {"shclustering", "kvstore", "clustering"}


def _regular(path, required, fragment=False):
    try:
        st = path.lstat()
    except FileNotFoundError:
        if required:
            raise SystemExit(f"ERROR: missing config path: {path}")
        return None
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
        raise SystemExit(f"ERROR: config path must be regular single-link file: {path}")
    if fragment and stat.S_IMODE(st.st_mode) != 0o600:
        raise SystemExit(f"ERROR: fragment must have mode 600: {path}")
    if not fragment and st.st_mode & 0o022:
        raise SystemExit(f"ERROR: config path is group/other writable: {path}")
    return st


def _secure_read(path, fragment=False):
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            raise SystemExit(
                f"ERROR: config path must be regular single-link file: {path}"
            )
        if fragment and stat.S_IMODE(st.st_mode) != 0o600:
            raise SystemExit(f"ERROR: fragment must have mode 600: {path}")
        if not fragment and st.st_mode & 0o022:
            raise SystemExit(f"ERROR: config path is group/other writable: {path}")
        with os.fdopen(fd, "rb") as h:
            fd = -1
            return st, h.read().decode("utf-8")
    finally:
        if fd != -1:
            os.close(fd)


def _check_parents(target):
    current = Path(target.anchor)
    under_etc = False
    for part in target.parts[1:-1]:
        current /= part
        try:
            st = current.lstat()
        except FileNotFoundError:
            continue
        if current.name == "etc":
            under_etc = True
        macos_var_alias = (
            sys.platform == "darwin"
            and current == Path("/var")
            and current.resolve() == Path("/private/var")
            and not under_etc
        )
        if stat.S_ISLNK(st.st_mode) and not macos_var_alias:
            raise SystemExit(f"ERROR: config parent may not be a symlink: {current}")


def _sections(raw):
    m = list(SECTION.finditer(raw))
    return [
        (x.group(1), x.start(), m[i + 1].start() if i + 1 < len(m) else len(raw))
        for i, x in enumerate(m)
    ]


def _key_lines(text):
    lines = text.splitlines(keepends=True)
    keys = {}
    for i, line in enumerate(lines[1:], 1):
        m = re.match(r"^\s*([^#;\s][^=\r\n]*?)\s*=", line)
        if m:
            key = m.group(1).strip()
            if key in keys:
                raise SystemExit(f"ERROR: duplicate key in owned section: {key}")
            keys[key] = i
    return lines, keys


def _merge_section(existing, fragment):
    old, oldkeys = _key_lines(existing)
    new, newkeys = _key_lines(fragment)
    for key, i in newkeys.items():
        if key in oldkeys:
            old[oldkeys[key]] = new[i]
        else:
            if old and not old[-1].endswith(("\n", "\r")):
                old[-1] += "\n"
            old.append(new[i])
    return "".join(old)


def merge(target, fragment, owner_user=None):
    if (
        target.name != "server.conf"
        or target.parent.name != "local"
        or target.parent.parent.name != "system"
        or target.parent.parent.parent.name != "etc"
    ):
        raise SystemExit("ERROR: target must be .../etc/system/local/server.conf")
    _check_parents(target)
    fragst, fragtext = _secure_read(fragment, True)
    allowed = {0, os.geteuid()}
    if owner_user:
        try:
            allowed.add(pwd.getpwnam(owner_user).pw_uid)
        except KeyError as e:
            raise SystemExit(f"ERROR: owner user does not exist: {owner_user}") from e
    sudo_uid = os.environ.get("SUDO_UID")
    if os.geteuid() == 0 and sudo_uid and sudo_uid.isdigit():
        allowed.add(int(sudo_uid))
    if fragst.st_uid not in allowed:
        raise SystemExit(
            "ERROR: fragment owner is outside the reviewed service/root ownership set"
        )
    fs = _sections(fragtext)
    names = [n for n, _, _ in fs]
    if not names or any(
        n not in ALLOWED and not n.startswith("replication_port:") for n in names
    ):
        raise SystemExit("ERROR: fragment contains unsupported server.conf section")
    if len(names) != len(set(names)):
        raise SystemExit("ERROR: fragment contains duplicate owned sections")
    replacements = {n: fragtext[s:e] for n, s, e in fs}
    for section in replacements.values():
        _key_lines(section)
    targetst = _regular(target, False)
    original = ""
    if targetst:
        targetst, original = _secure_read(target)
        if targetst.st_uid not in allowed:
            raise SystemExit(
                "ERROR: target owner is outside the reviewed service/root ownership set"
            )
    existing = _sections(original)
    for n in names:
        if sum(1 for old, _, _ in existing if old == n) > 1:
            raise SystemExit(f"ERROR: target contains duplicate owned section: {n}")
    out = []
    cursor = 0
    found = set()
    for n, s, e in existing:
        out.append(original[cursor:s])
        out.append(
            _merge_section(original[s:e], replacements[n])
            if n in replacements
            else original[s:e]
        )
        if n in replacements:
            found.add(n)
        cursor = e
    out.append(original[cursor:])
    merged = "".join(out)
    for n in names:
        if n not in found:
            if merged and not merged.endswith("\n"):
                merged += "\n"
            merged += replacements[n]
    target.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    _check_parents(target)
    mode = 0o600
    uid, gid = (
        (targetst.st_uid, targetst.st_gid)
        if targetst
        else (
            (pwd.getpwnam(owner_user).pw_uid, pwd.getpwnam(owner_user).pw_gid)
            if owner_user
            else (os.getuid(), os.getgid())
        )
    )
    if targetst:
        backup = target.with_name(
            f"server.conf.bak.shc.{time.strftime('%Y%m%d%H%M%S', time.gmtime())}"
        )
        bfd = os.open(
            backup,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            os.write(bfd, original.encode())
            os.fchmod(bfd, 0o600)
            os.fchown(bfd, uid, gid)
        finally:
            os.close(bfd)
    dirfd = os.open(
        target.parent,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    fd, tmp = tempfile.mkstemp(prefix=".server.conf.shc.", dir=str(target.parent))
    base = os.path.basename(tmp)
    try:
        os.fchmod(fd, mode)
        os.fchown(fd, uid, gid)
        with os.fdopen(fd, "w", encoding="utf-8") as h:
            fd = -1
            h.write(merged)
        os.replace(base, target.name, src_dir_fd=dirfd, dst_dir_fd=dirfd)
    finally:
        os.close(dirfd)
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    if len(sys.argv) not in (3, 5) or (
        len(sys.argv) == 5 and sys.argv[3] != "--owner-user"
    ):
        raise SystemExit(
            "usage: merge_server_conf_sections.py TARGET FRAGMENT [--owner-user USER]"
        )
    merge(
        Path(sys.argv[1]),
        Path(sys.argv[2]),
        sys.argv[4] if len(sys.argv) == 5 else None,
    )

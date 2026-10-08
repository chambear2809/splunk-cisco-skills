#!/usr/bin/env python3
"""Run one Splunk CLI command with a short-lived, PTY-backed login.

The CLI deliberately rejects password input on a pipe.  This helper keeps the
password in a protected file, never echoes PTY traffic, and removes only token
files created by this invocation.
"""
from __future__ import annotations

import argparse
import fcntl
import os
import pty
import re
import selectors
import stat
import subprocess
import termios
import time
from pathlib import Path
from urllib.parse import urlparse


def _regular_secret(path: Path) -> str:
    st = path.lstat()
    if (not stat.S_ISREG(st.st_mode) or st.st_mode & 0o077 or st.st_nlink != 1 or
            st.st_uid != os.getuid()):
        raise RuntimeError("password file must be a private regular file")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(fd)
        if (opened.st_ino != st.st_ino or opened.st_dev != st.st_dev or
                opened.st_uid != os.getuid() or opened.st_nlink != 1 or
                opened.st_mode & 0o077 or opened.st_size > 4096):
            raise RuntimeError("password file changed during validation")
        value = os.read(fd, 4097).decode("utf-8")
    finally:
        os.close(fd)
    if not value or len(value) > 4096 or not value.strip() or "\n" in value.rstrip("\n") or "\r" in value:
        raise RuntimeError("password file must contain one line")
    return value.rstrip("\n")


def _tokens(cache: Path) -> dict[str, tuple[int, int]]:
    if not cache.exists():
        return {}
    result = {}
    for item in cache.glob("authToken_*"):
        try:
            st = item.lstat()
            if (stat.S_ISREG(st.st_mode) and st.st_nlink == 1 and
                    st.st_uid == os.getuid() and not st.st_mode & 0o077):
                result[str(item)] = (st.st_ino, st.st_size)
        except OSError:
            continue
    return result


def _uri_cache_match(uri: str, token_path: str) -> bool:
    parsed = _validated_uri(uri)
    return Path(token_path).name == f"authToken_{parsed[0]}_{parsed[1]}"


def _default_target_cache_match(token_path: str) -> bool:
    """Return whether a token belongs to the CLI's implicit target."""
    default_uri = os.environ.get("SPLUNK_URI", "https://localhost:8089")
    try:
        return _uri_cache_match(default_uri, token_path)
    except RuntimeError:
        return False


def _validated_uri(uri: str) -> tuple[str, int]:
    parsed = urlparse(uri)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or
            parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise RuntimeError("login URI must be an https host and port without path or credentials")
    try:
        port = parsed.port or 8089
    except ValueError as exc:
        raise RuntimeError("login URI has an invalid port") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError("login URI port is outside the valid range")
    return parsed.hostname, port


def _pty_login(splunk: str, username: str, password: str, timeout: float, uri: str = "") -> None:
    master, slave = pty.openpty()
    attrs = termios.tcgetattr(slave)
    attrs[3] &= ~termios.ECHO
    termios.tcsetattr(slave, termios.TCSANOW, attrs)
    def attach_terminal() -> None:
        os.setsid()
        import fcntl
        fcntl.ioctl(slave, termios.TIOCSCTTY, 0)

    command = [splunk, "login"] + (["-uri", uri] if uri else [])
    proc = subprocess.Popen(command, stdin=slave, stdout=slave,
                            stderr=slave, close_fds=True, preexec_fn=attach_terminal)
    os.close(slave)
    selector = selectors.DefaultSelector()
    selector.register(master, selectors.EVENT_READ)
    sent_user = sent_password = False
    buf = b""
    deadline = time.monotonic() + timeout
    try:
        while proc.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                proc.kill()
                raise RuntimeError("Splunk login timed out")
            for _key, _mask in selector.select(remaining):
                try:
                    chunk = os.read(master, 4096)
                except OSError:
                    chunk = b""
                if not chunk:
                    continue
                buf = (buf + chunk)[-2048:]
                low = buf.lower()
                if not sent_user and re.search(br"user(name)?\s*[:>]", low):
                    os.write(master, (username + "\n").encode())
                    sent_user = True
                if not sent_password and re.search(br"pass(word)?\s*[:>]", low):
                    os.write(master, (password + "\n").encode())
                    sent_password = True
        if proc.wait() != 0 or not sent_user or not sent_password:
            raise RuntimeError("Splunk login failed")
    finally:
        selector.close()
        try:
            os.close(master)
        except OSError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--splunk", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password-file", required=True)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--command", required=True)
    parser.add_argument("--login-uri", action="append", default=[],
                        help="Authenticate an additional target URI before running the command.")
    args = parser.parse_args()
    password_path = Path(args.password_file)
    cache = Path(args.cache_dir)
    lock_path = cache / ".cisco-skills-auth.lock"
    cache_st = cache.lstat() if cache.exists() else None
    if cache_st is not None and (not stat.S_ISDIR(cache_st.st_mode) or
                                 cache_st.st_uid != os.getuid() or cache_st.st_mode & 0o066):
        raise RuntimeError("auth cache directory must be a private service-user directory")
    cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    lock_st = os.fstat(lock_fd)
    if (not stat.S_ISREG(lock_st.st_mode) or lock_st.st_uid != os.getuid() or
            lock_st.st_nlink != 1 or lock_st.st_mode & 0o077):
        os.close(lock_fd)
        raise RuntimeError("auth lock must be a private service-user file")
    with os.fdopen(lock_fd, "a+") as lock:
        deadline = time.monotonic() + args.timeout
        while True:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("timed out waiting for auth lock")
                time.sleep(0.05)
        before = _tokens(cache)
        created = {}
        created_uris = {}
        auth_complete = False
        try:
            password = _regular_secret(password_path)
            default_authenticated = any(
                _default_target_cache_match(path) for path in before
            )
            login_uris = ([] if default_authenticated else [""]) + list(args.login_uri)
            for uri in login_uris:
                if uri:
                    _validated_uri(uri)
            active_uri = ""
            for uri in login_uris:
                active_uri = uri
                before_login = _tokens(cache)
                if uri and any(_uri_cache_match(uri, name) for name in before_login):
                    continue
                _pty_login(args.splunk, args.username, password, args.timeout, uri)
                after_login = _tokens(cache)
                new_global = {p: after_login[p] for p in after_login if p not in before}
                new_delta = {p: after_login[p] for p in after_login if p not in before_login}
                if not new_delta:
                    raise RuntimeError("login succeeded without a new auth cache")
                created.update(new_global)
                created_uris.update({p: uri for p in new_delta})
            if not before and not created and not args.login_uri:
                raise RuntimeError("login succeeded without a new auth cache")
            auth_complete = True
            result = subprocess.run(["/bin/bash", "-lc", args.command],
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL,
                                    check=False, timeout=args.timeout)
            return result.returncode
        except subprocess.TimeoutExpired:
            raise RuntimeError("authenticated Splunk command timed out")
        finally:
            if not auth_complete:
                after_failure = _tokens(cache)
                new_failure = {p: after_failure[p] for p in after_failure if p not in before}
                created.update(new_failure)
                for path in new_failure:
                    created_uris.setdefault(path, active_uri)
            if created:
                for logout_uri in set(created_uris.values()):
                    try:
                        logout_args = [args.splunk, "logout"]
                        if logout_uri:
                            logout_args += ["-uri", logout_uri]
                        subprocess.run(logout_args, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, timeout=args.timeout,
                                        check=False)
                    except (OSError, subprocess.TimeoutExpired):
                        pass
            current = _tokens(cache)
            for name, identity in created.items():
                try:
                    item = Path(name)
                    st = item.lstat()
                    if (stat.S_ISREG(st.st_mode) and st.st_nlink == 1 and
                            st.st_uid == os.getuid() and current.get(name) == identity):
                        item.unlink()
                except OSError:
                    pass


if __name__ == "__main__":
    raise SystemExit(main())

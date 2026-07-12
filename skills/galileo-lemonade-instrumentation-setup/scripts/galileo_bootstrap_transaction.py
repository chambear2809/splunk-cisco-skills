#!/usr/bin/env python3
"""Resumable, fail-closed Galileo target and runtime-key transaction.

This program deliberately separates bootstrap from finalization.  Bootstrap
never revokes the credential that authorizes it.  Finalize requires a fresh,
protected proof document binding the exact transaction, target, runtime key,
host cutover, Galileo API trace/hierarchy readback, privacy review, and
unchanged Splunk readback. Console review is not inferred from API evidence.

Secrets are accepted only through protected regular files.  They are never
accepted in argv/environment variables and are never written to the journal or
stdout.  The HTTP client disables redirects and ambient proxies.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import hmac
import ipaddress
import json
import os
import re
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any


PHASES = (
    "PRECHECKED",
    "TARGET_CREATED",
    "RUNTIME_KEY_CREATED",
    "HOST_CUTOVER_VALIDATED",
    "OLD_KEY_REVOKED",
    "FINALIZED",
)
TERMINAL_ROLLBACK_PHASE = "ROLLED_BACK"
STATE_SCHEMA = 1
EVIDENCE_SCHEMA = 2
MAX_SECRET_BYTES = 64 * 1024
MAX_STATE_BYTES = 2 * 1024 * 1024
MAX_API_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_EVIDENCE_BYTES = 256 * 1024
MAX_EVIDENCE_AGE_SECONDS = 3600
PAGE_LIMIT = 100
MAX_PAGES = 10_000
MAX_REVOKE_AUTH_CHECKS_PER_FINALIZE = 6
REVOKE_RESUME_PRECHECKS = 3
MAX_REVOKE_DELETE_ATTEMPTS = 3
REVOKE_POLL_INTERVAL_SECONDS = 1.0
RUNTIME_ROLES = ("annotator", "editor")
KEY_HEADER = "Splunk-AO-API-Key"

EVIDENCE_REQUIRED_TOP_LEVEL = {
    "schema_version",
    "transaction_id",
    "api_base",
    "project_id",
    "log_stream_id",
    "runtime_key_id",
    "observed_at",
    "host_proof",
    "galileo_proof",
    "splunk_proof",
}
EVIDENCE_OPTIONAL_TOP_LEVEL = {"console_review"}
EVIDENCE_BOOLEAN_SECTIONS = {
    "host_proof": {
        "runtime_key_installed",
        "collector_config_validated",
        "collector_service_active",
        "rollback_tested",
    },
    "galileo_proof": {
        "otlp_write",
        "api_trace_readback",
        "api_hierarchy",
        "privacy_assertions",
    },
    "splunk_proof": {"backend_readback_unchanged"},
}
LEGACY_SELF_DELETE_INTENT_FIELDS = {
    "delete_started",
    "delete_started_at",
    "evidence_sha256",
    "id",
    "started_at",
    "status",
}


class TransactionError(RuntimeError):
    """An operator-safe failure that contains no API response body."""


class ReconciliationRequired(TransactionError):
    """A POST may or may not have committed and needs explicit retry authority."""


class ApiFailure(TransactionError):
    def __init__(self, status: int | None, operation: str, *, uncertain: bool):
        status_text = "transport" if status is None else f"HTTP {status}"
        super().__init__(f"{operation} failed ({status_text})")
        self.status = status
        self.uncertain = uncertain


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def iso_now() -> str:
    return utc_now().isoformat().replace("+00:00", "Z")


def parse_timestamp(value: object, label: str) -> dt.datetime:
    if not isinstance(value, str) or not value:
        raise TransactionError(f"{label} must be an ISO-8601 timestamp")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = dt.datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise TransactionError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise TransactionError(f"{label} must include a timezone")
    return parsed.astimezone(dt.UTC)


def require_uuid(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise TransactionError(f"{label} must be a UUID")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise TransactionError(f"{label} must be a UUID") from exc
    canonical = str(parsed)
    if value.lower() != canonical:
        raise TransactionError(f"{label} must use canonical UUID form")
    return canonical


def validate_api_base(value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise TransactionError("API base must be a non-empty HTTPS origin")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise TransactionError("API base contains unsafe characters")
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise TransactionError("API base must be an HTTPS origin without credentials")
    try:
        ipaddress.ip_address(parsed.hostname)
    except ValueError:
        labels = parsed.hostname.rstrip(".").split(".")
        if not labels or any(
            not label
            or len(label) > 63
            or not label[0].isalnum()
            or not label[-1].isalnum()
            or any(not (part.isalnum() or part == "-") for part in label)
            for label in labels
        ):
            raise TransactionError("API base contains an invalid hostname")
    try:
        port = parsed.port
    except ValueError as exc:
        raise TransactionError("API base contains an invalid port") from exc
    if port is not None and not 1 <= port <= 65535:
        raise TransactionError("API base contains an invalid port")
    netloc = parsed.hostname
    if ":" in netloc and not netloc.startswith("["):
        netloc = f"[{netloc}]"
    if port is not None:
        netloc = f"{netloc}:{port}"
    return urllib.parse.urlunsplit(("https", netloc, "", "", ""))


def validate_text(value: object, label: str, *, maximum: int = 1024) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise TransactionError(f"{label} must be a non-empty string")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise TransactionError(f"{label} is not valid UTF-8") from exc
    if len(encoded) > maximum or any(
        ord(character) < 32 or ord(character) == 127 for character in value
    ):
        raise TransactionError(f"{label} contains unsafe content")
    return value


def _path_parts(path: Path) -> tuple[str, ...]:
    if not path.is_absolute():
        raise TransactionError("protected paths must be absolute")
    parts = path.parts
    if (
        not parts
        or parts[0] != os.sep
        or any(part in {"", ".", ".."} for part in parts[1:])
    ):
        raise TransactionError("protected path contains an unsafe segment")
    return tuple(parts[1:])


def _directory_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )


def _file_flags(base: int) -> int:
    return base | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)


def _validate_directory_descriptor(
    descriptor: int, label: str, *, final_private: bool
) -> os.stat_result:
    info = os.fstat(descriptor)
    if not stat.S_ISDIR(info.st_mode):
        raise TransactionError(f"{label} is not a directory")
    euid = os.geteuid()
    mode = stat.S_IMODE(info.st_mode)
    if info.st_uid not in {0, euid}:
        raise TransactionError(f"{label} has an untrusted owner")
    if final_private:
        if info.st_uid != euid or mode != 0o700:
            raise TransactionError(
                f"{label} must be owned by the caller with mode 0700"
            )
    elif mode & 0o022:
        # Root-owned sticky traversal roots (for example /tmp in tests) are
        # acceptable; every descendant is still opened descriptor-relatively
        # and validated before use.
        if not (info.st_uid == 0 and mode & stat.S_ISVTX):
            raise TransactionError(f"{label} is group/other writable")
    return info


def open_secure_directory(path: Path, *, create: bool, final_private: bool) -> int:
    parts = _path_parts(path)
    descriptor = os.open(os.sep, _directory_flags())
    try:
        _validate_directory_descriptor(
            descriptor, "filesystem root", final_private=False
        )
        for index, part in enumerate(parts):
            is_final = index == len(parts) - 1
            try:
                next_descriptor = os.open(part, _directory_flags(), dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise TransactionError(
                        f"protected directory does not exist: {path}"
                    ) from None
                try:
                    os.mkdir(part, mode=0o700, dir_fd=descriptor)
                    os.fsync(descriptor)
                except FileExistsError:
                    pass
                next_descriptor = os.open(part, _directory_flags(), dir_fd=descriptor)
            _validate_directory_descriptor(
                next_descriptor,
                f"directory component {part!r}",
                final_private=final_private and is_final,
            )
            os.close(descriptor)
            descriptor = next_descriptor
        if not parts and final_private:
            _validate_directory_descriptor(
                descriptor, "state directory", final_private=True
            )
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _validate_regular_file(
    descriptor: int,
    label: str,
    *,
    require_private: bool,
    exact_mode: int | None = None,
) -> os.stat_result:
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise TransactionError(f"{label} must be a single-link regular file")
    if info.st_uid != os.geteuid():
        raise TransactionError(f"{label} must be owned by the caller")
    mode = stat.S_IMODE(info.st_mode)
    if exact_mode is not None and mode != exact_mode:
        raise TransactionError(f"{label} must have mode {exact_mode:04o}")
    if require_private and (mode & 0o177 or not mode & 0o400):
        raise TransactionError(
            f"{label} must be caller-readable and mode 0600 or stricter"
        )
    return info


def _read_descriptor(descriptor: int, maximum: int, label: str) -> bytes:
    before = os.fstat(descriptor)
    if before.st_size < 0 or before.st_size > maximum:
        raise TransactionError(f"{label} size is outside the safety bound")
    chunks: list[bytes] = []
    remaining = maximum + 1
    while remaining:
        chunk = os.read(descriptor, min(remaining, 8192))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    value = b"".join(chunks)
    after = os.fstat(descriptor)
    if len(value) > maximum:
        raise TransactionError(f"{label} exceeded the safety bound")
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise TransactionError(f"{label} changed while being read")
    if len(value) != before.st_size:
        raise TransactionError(f"{label} could not be read completely")
    return value


def read_protected_bytes(
    path: Path, maximum: int, label: str
) -> tuple[bytes, os.stat_result]:
    parts = _path_parts(path)
    if not parts:
        raise TransactionError(f"{label} path is invalid")
    parent = open_secure_directory(path.parent, create=False, final_private=False)
    try:
        try:
            descriptor = os.open(
                parts[-1], _file_flags(os.O_RDONLY | os.O_NONBLOCK), dir_fd=parent
            )
        except OSError as exc:
            raise TransactionError(
                f"{label} must be a readable protected file"
            ) from exc
        try:
            info = _validate_regular_file(descriptor, label, require_private=True)
            value = _read_descriptor(descriptor, maximum, label)
        finally:
            os.close(descriptor)
        return value, info
    finally:
        os.close(parent)


def read_secret(path: Path, label: str) -> str:
    secret, _ = read_secret_with_info(path, label)
    return secret


def read_secret_with_info(path: Path, label: str) -> tuple[str, dict[str, object]]:
    """Read one protected secret and retain non-secret filesystem identity."""

    raw, info = read_protected_bytes(path, MAX_SECRET_BYTES, label)
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise TransactionError(f"{label} must contain UTF-8 text") from exc
    if (
        len(lines) != 1
        or not lines[0]
        or any(ord(character) < 32 or ord(character) == 127 for character in lines[0])
    ):
        raise TransactionError(f"{label} must contain exactly one non-empty line")
    record: dict[str, object] = {
        "path": str(path),
        "device": info.st_dev,
        "inode": info.st_ino,
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
        "ctime_ns": info.st_ctime_ns,
    }
    birthtime = getattr(info, "st_birthtime", None)
    if isinstance(birthtime, (int, float)):
        record["birthtime_ns"] = int(birthtime * 1_000_000_000)
    return lines[0], record


def _write_all(descriptor: int, value: bytes) -> None:
    offset = 0
    while offset < len(value):
        written = os.write(descriptor, value[offset:])
        if written <= 0:
            raise TransactionError("protected file write did not make progress")
        offset += written


def create_secret_file(path: Path, secret: str) -> dict[str, object]:
    parts = _path_parts(path)
    if not parts:
        raise TransactionError("runtime key output path is invalid")
    parent = open_secure_directory(path.parent, create=False, final_private=False)
    descriptor = -1
    created = False
    try:
        try:
            descriptor = os.open(
                parts[-1],
                _file_flags(os.O_WRONLY | os.O_CREAT | os.O_EXCL),
                0o600,
                dir_fd=parent,
            )
            created = True
        except FileExistsError as exc:
            raise TransactionError(
                "runtime key output already exists; refusing overwrite"
            ) from exc
        os.fchmod(descriptor, 0o600)
        _write_all(descriptor, secret.encode("utf-8") + b"\n")
        os.fsync(descriptor)
        info = _validate_regular_file(
            descriptor, "runtime key output", require_private=True, exact_mode=0o600
        )
        os.fsync(parent)
        return {
            "path": str(path),
            "device": info.st_dev,
            "inode": info.st_ino,
            "size": info.st_size,
            "sha256": hashlib.sha256(
                secret.encode("utf-8") + b"\n"
            ).hexdigest(),
        }
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
            descriptor = -1
        # If creation happened but durability/validation failed, remove only
        # the descriptor-relative name created by this function.
        if created:
            try:
                os.unlink(parts[-1], dir_fd=parent)
                os.fsync(parent)
            except OSError:
                pass
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(parent)


def unlink_owned_file(
    record: Mapping[str, object], *, missing_ok: bool = False
) -> bool:
    path = Path(validate_text(record.get("path"), "owned output path", maximum=4096))
    parts = _path_parts(path)
    parent = open_secure_directory(path.parent, create=False, final_private=False)
    try:
        try:
            descriptor = os.open(
                parts[-1],
                _file_flags(os.O_RDONLY | os.O_NONBLOCK),
                dir_fd=parent,
            )
        except FileNotFoundError:
            if missing_ok:
                return False
            raise TransactionError("owned runtime key output is missing") from None
        except OSError as exc:
            raise TransactionError("owned runtime key output is not readable") from exc
        try:
            info = _validate_regular_file(
                descriptor, "owned runtime key output", require_private=True
            )
            payload = _read_descriptor(
                descriptor, MAX_SECRET_BYTES, "owned runtime key output"
            )
        finally:
            os.close(descriptor)
        if (info.st_dev, info.st_ino) != (
            record.get("device"),
            record.get("inode"),
        ):
            raise TransactionError("runtime key output inode changed; refusing cleanup")
        expected_digest = record.get("sha256")
        if not isinstance(expected_digest, str) or not re.fullmatch(
            r"[0-9a-f]{64}", expected_digest
        ):
            raise TransactionError(
                "runtime key output digest is missing; refusing cleanup"
            )
        if not hmac.compare_digest(
            hashlib.sha256(payload).hexdigest(), expected_digest
        ):
            raise TransactionError(
                "runtime key output inode changed or content differs; refusing cleanup"
            )
        current = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
        if (current.st_dev, current.st_ino, current.st_nlink) != (
            info.st_dev,
            info.st_ino,
            1,
        ):
            raise TransactionError("runtime key output changed before cleanup")
        os.unlink(parts[-1], dir_fd=parent)
        os.fsync(parent)
        return True
    finally:
        os.close(parent)


class StateStore:
    """Descriptor-relative, locked, crash-durable JSON state."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.directory_fd = -1
        self.lock_fd = -1

    def __enter__(self) -> StateStore:
        self.directory_fd = open_secure_directory(
            self.directory, create=True, final_private=True
        )
        created = False
        try:
            try:
                self.lock_fd = os.open(
                    "transaction.lock",
                    _file_flags(os.O_RDWR | os.O_CREAT | os.O_EXCL),
                    0o600,
                    dir_fd=self.directory_fd,
                )
                created = True
            except FileExistsError:
                self.lock_fd = os.open(
                    "transaction.lock",
                    _file_flags(os.O_RDWR),
                    dir_fd=self.directory_fd,
                )
            _validate_regular_file(
                self.lock_fd,
                "transaction lock",
                require_private=True,
                exact_mode=0o600,
            )
            if created:
                os.fsync(self.lock_fd)
                os.fsync(self.directory_fd)
            try:
                fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise TransactionError(
                    "another Galileo transaction holds the lock"
                ) from exc
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        if self.lock_fd >= 0:
            try:
                fcntl.flock(self.lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(self.lock_fd)
                self.lock_fd = -1
        if self.directory_fd >= 0:
            os.close(self.directory_fd)
            self.directory_fd = -1

    def load(self) -> dict[str, object] | None:
        try:
            descriptor = os.open(
                "transaction.json",
                _file_flags(os.O_RDONLY | os.O_NONBLOCK),
                dir_fd=self.directory_fd,
            )
        except FileNotFoundError:
            return None
        try:
            _validate_regular_file(
                descriptor,
                "transaction state",
                require_private=True,
                exact_mode=0o600,
            )
            raw = _read_descriptor(descriptor, MAX_STATE_BYTES, "transaction state")
        finally:
            os.close(descriptor)
        try:
            document = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as exc:
            raise TransactionError("transaction state is malformed") from exc
        if (
            not isinstance(document, dict)
            or document.get("schema_version") != STATE_SCHEMA
        ):
            raise TransactionError("transaction state has an unsupported schema")
        return document

    def save(self, document: Mapping[str, object]) -> None:
        payload = (json.dumps(document, sort_keys=True, indent=2) + "\n").encode(
            "utf-8"
        )
        if len(payload) > MAX_STATE_BYTES:
            raise TransactionError("transaction state exceeded the safety bound")
        temporary = f".transaction.{uuid.uuid4().hex}.tmp"
        descriptor = os.open(
            temporary,
            _file_flags(os.O_WRONLY | os.O_CREAT | os.O_EXCL),
            0o600,
            dir_fd=self.directory_fd,
        )
        try:
            try:
                os.fchmod(descriptor, 0o600)
                _write_all(descriptor, payload)
                os.fsync(descriptor)
                _validate_regular_file(
                    descriptor,
                    "temporary transaction state",
                    require_private=True,
                    exact_mode=0o600,
                )
            finally:
                os.close(descriptor)
        except BaseException:
            try:
                os.unlink(temporary, dir_fd=self.directory_fd)
                os.fsync(self.directory_fd)
            except OSError:
                pass
            raise
        try:
            # Refuse to replace an attacker-controlled existing path.
            try:
                existing = os.open(
                    "transaction.json",
                    _file_flags(os.O_RDONLY | os.O_NONBLOCK),
                    dir_fd=self.directory_fd,
                )
            except FileNotFoundError:
                existing = -1
            if existing >= 0:
                try:
                    _validate_regular_file(
                        existing,
                        "existing transaction state",
                        require_private=True,
                        exact_mode=0o600,
                    )
                finally:
                    os.close(existing)
            os.replace(
                temporary,
                "transaction.json",
                src_dir_fd=self.directory_fd,
                dst_dir_fd=self.directory_fd,
            )
            os.fsync(self.directory_fd)
        except BaseException:
            try:
                os.unlink(temporary, dir_fd=self.directory_fd)
            except OSError:
                pass
            raise


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl
        return None


class HttpGalileoApi:
    """Small v2 API client with bounded responses and complete pagination."""

    def __init__(self, api_base: str, api_key: str):
        self.api_base = validate_api_base(api_base)
        self._api_key = api_key
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect()
        )

    def clone_with_key(self, api_key: str) -> HttpGalileoApi:
        return HttpGalileoApi(self.api_base, api_key)

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, object] | None = None,
        expected: tuple[int, ...] = (200,),
        operation: str,
        mutating: bool = False,
    ) -> object | None:
        if not path.startswith("/v2/") or "\\" in path:
            raise TransactionError("API path is outside the supported v2 surface")
        data = None
        headers = {"Accept": "application/json", KEY_HEADER: self._api_key}
        if body is not None:
            data = json.dumps(body, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.api_base + path,
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with self._opener.open(request, timeout=30) as response:
                raw = response.read(MAX_API_RESPONSE_BYTES + 1)
                status = response.status
        except urllib.error.HTTPError as exc:
            uncertain_status = exc.code >= 500 or exc.code in {
                301,
                302,
                303,
                307,
                308,
                408,
                425,
                429,
            }
            raise ApiFailure(
                exc.code,
                operation,
                uncertain=mutating and uncertain_status,
            ) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ApiFailure(None, operation, uncertain=mutating) from exc
        if len(raw) > MAX_API_RESPONSE_BYTES:
            raise ApiFailure(status, operation, uncertain=mutating)
        if status not in expected:
            uncertain_status = status >= 500 or status in {
                301,
                302,
                303,
                307,
                308,
                408,
                425,
                429,
            }
            raise ApiFailure(status, operation, uncertain=mutating and uncertain_status)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as exc:
            raise ApiFailure(status, operation, uncertain=mutating) from exc

    def current_user(self) -> dict[str, object]:
        document = self.request(
            "GET", "/v2/current_user", operation="current-user check"
        )
        if not isinstance(document, dict):
            raise TransactionError("current-user response is malformed")
        require_uuid(document.get("id"), "current-user ID")
        return document

    def token_authorization(self) -> None:
        """Probe the second documented API-key authentication route."""

        self.request("GET", "/v2/token", operation="token authorization check")

    @staticmethod
    def _next_token(
        document: Mapping[str, object], seen: set[int], label: str
    ) -> int | None:
        if "next_starting_token" not in document:
            raise TransactionError(f"{label} omitted next_starting_token")
        value = document["next_starting_token"]
        if value is None:
            return None
        if type(value) is not int or value < 0 or value in seen:
            raise TransactionError(f"{label} returned an invalid pagination token")
        return value

    def list_keys(self, user_id: str) -> list[dict[str, object]]:
        user_id = require_uuid(user_id, "user ID")
        rows: list[dict[str, object]] = []
        token: int | None = 0
        seen: set[int] = set()
        pages = 0
        while token is not None:
            if pages >= MAX_PAGES or token in seen:
                raise TransactionError("API-key pagination did not terminate")
            seen.add(token)
            document = self.request(
                "GET",
                f"/v2/users/{urllib.parse.quote(user_id, safe='')}/api_keys?"
                + urllib.parse.urlencode(
                    {"starting_token": token, "limit": PAGE_LIMIT}
                ),
                operation="API-key inventory",
            )
            values = document.get("api_keys") if isinstance(document, dict) else None
            if not isinstance(values, list) or not all(
                isinstance(item, dict) for item in values
            ):
                raise TransactionError("API-key inventory is malformed")
            rows.extend(values)
            token = self._next_token(document, seen, "API-key inventory")
            pages += 1
        return _deduplicate_records(rows, "API key")

    def list_projects(self, actions: Iterable[str] = ()) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        token: int | None = 0
        seen: set[int] = set()
        pages = 0
        action_values = tuple(actions)
        while token is not None:
            if pages >= MAX_PAGES or token in seen:
                raise TransactionError("project pagination did not terminate")
            seen.add(token)
            query: list[tuple[str, object]] = [
                ("include_logstreams", "true"),
                ("starting_token", token),
                ("limit", PAGE_LIMIT),
            ]
            query.extend(("actions", action) for action in action_values)
            document = self.request(
                "POST",
                "/v2/projects/paginated?" + urllib.parse.urlencode(query),
                body={
                    "filters": [],
                    "sort": {
                        "name": "created_at",
                        "ascending": False,
                        "sort_type": "column",
                    },
                },
                operation="project inventory",
            )
            values = document.get("projects") if isinstance(document, dict) else None
            if not isinstance(values, list) or not all(
                isinstance(item, dict) for item in values
            ):
                raise TransactionError("project inventory is malformed")
            rows.extend(values)
            token = self._next_token(document, seen, "project inventory")
            pages += 1
        return _deduplicate_records(rows, "project")

    def list_log_streams(self, project_id: str) -> list[dict[str, object]]:
        project_id = require_uuid(project_id, "project ID")
        rows: list[dict[str, object]] = []
        token: int | None = 0
        seen: set[int] = set()
        pages = 0
        while token is not None:
            if pages >= MAX_PAGES or token in seen:
                raise TransactionError("Log-stream pagination did not terminate")
            seen.add(token)
            query = urllib.parse.urlencode(
                {
                    "include_counts": "false",
                    "starting_token": token,
                    "limit": PAGE_LIMIT,
                }
            )
            document = self.request(
                "GET",
                f"/v2/projects/{urllib.parse.quote(project_id, safe='')}/"
                f"log_streams/paginated?{query}",
                operation="Log-stream inventory",
            )
            values = document.get("log_streams") if isinstance(document, dict) else None
            if not isinstance(values, list) or not all(
                isinstance(item, dict) for item in values
            ):
                raise TransactionError("Log-stream inventory is malformed")
            rows.extend(values)
            token = self._next_token(document, seen, "Log-stream inventory")
            pages += 1
        return _deduplicate_records(rows, "Log stream")

    def get_project(self, project_id: str) -> dict[str, object] | None:
        project_id = require_uuid(project_id, "project ID")
        try:
            value = self.request(
                "GET",
                f"/v2/projects/{urllib.parse.quote(project_id, safe='')}",
                operation="get project",
            )
        except ApiFailure as exc:
            if exc.status == 404:
                return None
            raise
        if not isinstance(value, dict):
            raise TransactionError("get-project response is malformed")
        return value

    def get_log_stream(
        self, project_id: str, log_stream_id: str
    ) -> dict[str, object] | None:
        project_id = require_uuid(project_id, "project ID")
        log_stream_id = require_uuid(log_stream_id, "Log-stream ID")
        try:
            value = self.request(
                "GET",
                f"/v2/projects/{urllib.parse.quote(project_id, safe='')}/log_streams/"
                f"{urllib.parse.quote(log_stream_id, safe='')}",
                operation="get Log stream",
            )
        except ApiFailure as exc:
            if exc.status == 404:
                return None
            raise
        if not isinstance(value, dict):
            raise TransactionError("get-Log-stream response is malformed")
        return value

    def create_project(self, name: str) -> dict[str, object]:
        value = self.request(
            "POST",
            "/v2/projects",
            body={"name": name, "type": "gen_ai", "create_example_templates": False},
            expected=(200, 201),
            operation="create project",
            mutating=True,
        )
        if not isinstance(value, dict):
            raise ApiFailure(200, "create project", uncertain=True)
        return value

    def create_log_stream(self, project_id: str, name: str) -> dict[str, object]:
        value = self.request(
            "POST",
            f"/v2/projects/{urllib.parse.quote(require_uuid(project_id, 'project ID'), safe='')}/log_streams",
            body={"name": name},
            expected=(200, 201),
            operation="create Log stream",
            mutating=True,
        )
        if not isinstance(value, dict):
            raise ApiFailure(200, "create Log stream", uncertain=True)
        return value

    def create_key(
        self,
        description: str,
        expires_at: str,
        project_id: str,
        project_role: str,
    ) -> dict[str, object]:
        value = self.request(
            "POST",
            "/v2/users/api_keys",
            body={
                "description": description,
                "expires_at": expires_at,
                "project_id": require_uuid(project_id, "project ID"),
                "project_role": project_role,
            },
            expected=(200, 201),
            operation="create runtime API key",
            mutating=True,
        )
        if not isinstance(value, dict):
            raise ApiFailure(200, "create runtime API key", uncertain=True)
        return value

    def delete_key(self, key_id: str) -> None:
        self.request(
            "DELETE",
            f"/v2/users/api_keys/{urllib.parse.quote(require_uuid(key_id, 'API-key ID'), safe='')}",
            expected=(200, 204),
            operation="delete API key",
            mutating=True,
        )

    def delete_project(self, project_id: str) -> None:
        self.request(
            "DELETE",
            f"/v2/projects/{urllib.parse.quote(require_uuid(project_id, 'project ID'), safe='')}",
            expected=(200, 204),
            operation="delete project",
            mutating=True,
        )

    def delete_log_stream(self, project_id: str, log_stream_id: str) -> None:
        self.request(
            "DELETE",
            f"/v2/projects/{urllib.parse.quote(require_uuid(project_id, 'project ID'), safe='')}/"
            f"log_streams/{urllib.parse.quote(require_uuid(log_stream_id, 'Log-stream ID'), safe='')}",
            expected=(200, 204),
            operation="delete Log stream",
            mutating=True,
        )


def _deduplicate_records(
    values: list[dict[str, object]], label: str
) -> list[dict[str, object]]:
    by_id: dict[str, dict[str, object]] = {}
    for value in values:
        item_id = require_uuid(value.get("id"), f"{label} ID")
        previous = by_id.get(item_id)
        if previous is not None and previous != value:
            raise TransactionError(
                f"{label} inventory returned conflicting duplicate IDs"
            )
        by_id[item_id] = value
    return list(by_id.values())


def truncated_matches(secret: str, mask: object) -> bool:
    """Match only Galileo's display mask forms, never emit either value."""

    if not isinstance(mask, str) or not mask or len(mask) > len(secret):
        return False
    if mask == secret:
        return True
    if "..." in mask and mask.count("...") == 1:
        prefix, suffix = mask.split("...", 1)
        return (
            bool(prefix or suffix)
            and secret.startswith(prefix)
            and secret.endswith(suffix)
        )
    if set(mask) <= {"*"}:
        return False
    if "*" in mask:
        pieces = mask.split("*")
        prefix, suffix = pieces[0], pieces[-1]
        return (
            bool(prefix or suffix)
            and secret.startswith(prefix)
            and secret.endswith(suffix)
        )
    return len(mask) >= 4 and (secret.startswith(mask) or secret.endswith(mask))


def _creator_id(record: Mapping[str, object]) -> str | None:
    direct = record.get("created_by")
    if isinstance(direct, str):
        return direct
    creator = record.get("created_by_user")
    if isinstance(creator, dict) and isinstance(creator.get("id"), str):
        return creator["id"]
    return None


def validate_project_identity(
    record: Mapping[str, object], project_id: str, name: str
) -> dict[str, object]:
    actual_id = require_uuid(record.get("id"), "project ID")
    if actual_id != project_id or record.get("name") != name:
        raise TransactionError("project identity does not match the transaction")
    if record.get("type") not in {None, "gen_ai"}:
        raise TransactionError("project type is not gen_ai")
    return dict(record)


def validate_log_stream_identity(
    record: Mapping[str, object], project_id: str, log_stream_id: str, name: str
) -> dict[str, object]:
    actual_id = require_uuid(record.get("id"), "Log-stream ID")
    actual_project = require_uuid(record.get("project_id"), "Log-stream project ID")
    if (
        actual_id != log_stream_id
        or actual_project != project_id
        or record.get("name") != name
    ):
        raise TransactionError("Log-stream identity does not match the transaction")
    return dict(record)


def phase_index(phase: object) -> int:
    if phase not in PHASES:
        if phase == TERMINAL_ROLLBACK_PHASE:
            return -1
        raise TransactionError("transaction state contains an invalid phase")
    return PHASES.index(str(phase))


def _history_entry(phase: str) -> dict[str, str]:
    return {"phase": phase, "at": iso_now()}


class GalileoBootstrapTransaction:
    """State machine independent of the concrete HTTP transport for testing."""

    def __init__(
        self,
        store: StateStore,
        api: Any,
        *,
        runtime_api_factory: Callable[[str], Any],
        bootstrap_secret: str | None,
        failpoint: Callable[[str], None] | None = None,
        revoke_sleep: Callable[[float], None] | None = None,
        revoker_api: Any | None = None,
        revoker_secret: str | None = None,
        revoker_key_id: str | None = None,
        bootstrap_credential_info: Mapping[str, object] | None = None,
    ):
        self.store = store
        self.api = api
        self.runtime_api_factory = runtime_api_factory
        self.bootstrap_secret = bootstrap_secret
        self.failpoint = failpoint or (lambda _: None)
        self.revoke_sleep = revoke_sleep or time.sleep
        self.revoker_api = revoker_api
        self.revoker_secret = revoker_secret
        self.revoker_key_id = revoker_key_id
        self.bootstrap_credential_info = (
            dict(bootstrap_credential_info)
            if bootstrap_credential_info is not None
            else None
        )

    def _save(self, state: dict[str, object]) -> None:
        state["updated_at"] = iso_now()
        self.store.save(state)

    def _validate_api_binding(self, state: Mapping[str, object]) -> None:
        transport_base = getattr(self.api, "api_base", None)
        if not isinstance(transport_base, str):
            raise TransactionError("API transport does not expose its bound origin")
        if validate_api_base(transport_base) != state.get("api_base"):
            raise TransactionError(
                "API transport origin does not match the transaction journal"
            )

    @staticmethod
    def _sanitized_status(state: Mapping[str, object]) -> dict[str, object]:
        target = state.get("target") if isinstance(state.get("target"), dict) else {}
        runtime = (
            state.get("runtime_key")
            if isinstance(state.get("runtime_key"), dict)
            else {}
        )
        return {
            "transaction_id": state.get("transaction_id"),
            "phase": state.get("phase"),
            "project_id": target.get("project_id"),
            "log_stream_id": target.get("log_stream_id"),
            "runtime_key_id": runtime.get("id"),
        }

    def _transition(self, state: dict[str, object], phase: str) -> None:
        current = str(state.get("phase"))
        if phase_index(phase) != phase_index(current) + 1:
            raise TransactionError(f"invalid phase transition {current} -> {phase}")
        state["phase"] = phase
        history = state.setdefault("history", [])
        if not isinstance(history, list):
            raise TransactionError("transaction history is malformed")
        history.append(_history_entry(phase))
        self._save(state)

    def _validate_resume_config(
        self, state: Mapping[str, object], config: Mapping[str, object]
    ) -> None:
        stored = state.get("config")
        if stored != dict(config):
            raise TransactionError(
                "bootstrap arguments do not match the existing transaction"
            )

    def _new_state(self, config: Mapping[str, object]) -> dict[str, object]:
        if self.bootstrap_secret is None:
            raise TransactionError(
                "bootstrap credential is required for initial precheck"
            )
        user = self.api.current_user()
        user_id = require_uuid(user.get("id"), "current-user ID")
        old_key_id = require_uuid(config.get("old_key_id"), "old API-key ID")
        keys = self.api.list_keys(user_id)
        old_rows = [row for row in keys if row.get("id") == old_key_id]
        if len(old_rows) != 1 or not truncated_matches(
            self.bootstrap_secret, old_rows[0].get("truncated")
        ):
            raise TransactionError(
                "bootstrap credential did not match the exact old key ID"
            )
        output_path = Path(str(config["runtime_key_output"]))
        try:
            read_protected_bytes(output_path, MAX_SECRET_BYTES, "runtime key output")
        except TransactionError as exc:
            if "readable protected file" not in str(exc):
                raise
        else:
            raise TransactionError("runtime key output already exists before bootstrap")

        transaction_id = str(uuid.uuid4())
        runtime_description = (
            f"{config['runtime_description']}-{transaction_id}-attempt-1"
        )
        state: dict[str, object] = {
            "schema_version": STATE_SCHEMA,
            "transaction_id": transaction_id,
            "phase": "PRECHECKED",
            "created_at": iso_now(),
            "updated_at": iso_now(),
            "api_base": config["api_base"],
            "operator_user_id": user_id,
            "old_key": {"id": old_key_id, "revoked": False},
            "config": dict(config),
            "target": {},
            "runtime_key": {},
            "intents": {
                "runtime_key": {
                    "description": runtime_description,
                    "attempt": 1,
                    "status": "not_started",
                }
            },
            "history": [_history_entry("PRECHECKED")],
        }
        self._save(state)
        return state

    def bootstrap(
        self, config: Mapping[str, object], *, retry_uncertain: bool = False
    ) -> dict[str, object]:
        state = self.store.load()
        if state is None:
            state = self._new_state(config)
        else:
            self._validate_resume_config(state, config)
        if state.get("phase") == TERMINAL_ROLLBACK_PHASE:
            raise TransactionError("rolled-back transaction cannot be resumed")
        if phase_index(state.get("phase")) >= phase_index("RUNTIME_KEY_CREATED"):
            return self._sanitized_status(state)

        self._ensure_project(state, retry_uncertain=retry_uncertain)
        self._ensure_log_stream(state, retry_uncertain=retry_uncertain)
        if state.get("phase") == "PRECHECKED":
            self._transition(state, "TARGET_CREATED")
        self._ensure_runtime_key(state, retry_uncertain=retry_uncertain)
        if state.get("phase") == "TARGET_CREATED":
            self._transition(state, "RUNTIME_KEY_CREATED")
        return self._sanitized_status(state)

    def _ensure_project(
        self, state: dict[str, object], *, retry_uncertain: bool
    ) -> None:
        config = state["config"]
        if not isinstance(config, dict):
            raise TransactionError("stored bootstrap config is malformed")
        target = state["target"]
        if not isinstance(target, dict):
            raise TransactionError("stored target is malformed")
        name = validate_text(config.get("project_name"), "project name")
        existing_id = target.get("project_id")
        if existing_id:
            record = self.api.get_project(require_uuid(existing_id, "project ID"))
            if record is None:
                raise TransactionError("recorded project is absent")
            validate_project_identity(record, str(existing_id), name)
            return

        projects = self.api.list_projects(("log_data",))
        matches = [item for item in projects if item.get("name") == name]
        requested_id = config.get("project_id")
        if requested_id:
            requested_id = require_uuid(requested_id, "requested project ID")
            matches = [item for item in matches if item.get("id") == requested_id]
            if len(matches) != 1:
                raise TransactionError(
                    "requested project ID/name did not resolve exactly"
                )
            if config.get("adopt_project") is not True:
                raise TransactionError(
                    "adopting an existing project requires --adopt-project"
                )
            validate_project_identity(matches[0], requested_id, name)
            target.update({"project_id": requested_id, "project_owned": False})
            self._save(state)
            return

        intents = state.setdefault("intents", {})
        if not isinstance(intents, dict):
            raise TransactionError("transaction intents are malformed")
        intent = intents.get("project")
        if isinstance(intent, dict):
            if intent.get("status") != "pending" or intent.get("name") != name:
                raise TransactionError("pending project intent is inconsistent")
            preexisting_ids = intent.get("preexisting_ids")
            if not isinstance(preexisting_ids, list):
                raise TransactionError("pending project intent is malformed")
            reconciled = [
                item for item in matches if item.get("id") not in preexisting_ids
            ]
            if len(reconciled) > 1:
                raise TransactionError(
                    "ambiguous project POST produced multiple candidates"
                )
            if len(reconciled) == 1:
                project_id = require_uuid(reconciled[0].get("id"), "project ID")
                if _creator_id(reconciled[0]) != state.get("operator_user_id"):
                    raise TransactionError("reconciled project creator does not match")
                validate_project_identity(reconciled[0], project_id, name)
                target.update({"project_id": project_id, "project_owned": True})
                intent.update(
                    {
                        "status": "reconciled",
                        "id": project_id,
                        "outcome_unknown": False,
                        "uncertain": False,
                    }
                )
                self._save(state)
                return
            if (
                intent.get("outcome_unknown") is True or intent.get("uncertain") is True
            ) and not retry_uncertain:
                raise ReconciliationRequired(
                    "project POST outcome is uncertain; inventory is empty; rerun with "
                    "--retry-uncertain only after the backend consistency window"
                )

        if len(matches) > 1:
            raise TransactionError("multiple projects have the requested exact name")
        if len(matches) == 1:
            if config.get("adopt_project") is not True:
                raise TransactionError(
                    "project already exists; explicit adoption is required"
                )
            project_id = require_uuid(matches[0].get("id"), "project ID")
            validate_project_identity(matches[0], project_id, name)
            target.update({"project_id": project_id, "project_owned": False})
            self._save(state)
            return

        if not isinstance(intent, dict):
            intent = {
                "status": "pending",
                "name": name,
                "started_at": iso_now(),
                "preexisting_ids": [item.get("id") for item in projects],
                "uncertain": False,
                "outcome_unknown": False,
            }
            intents["project"] = intent
            self._save(state)

        intent.update(
            {
                "outcome_unknown": True,
                "last_attempt_at": iso_now(),
            }
        )
        self._save(state)
        try:
            created = self.api.create_project(name)
        except BaseException as exc:
            if isinstance(exc, ApiFailure):
                intent["uncertain"] = exc.uncertain
                intent["outcome_unknown"] = exc.uncertain
                self._save(state)
            raise
        self.failpoint("after_project_post")
        project_id = require_uuid(created.get("id"), "created project ID")
        intent.update(
            {
                "candidate_id": project_id,
                "candidate_owned": False,
                "outcome_unknown": False,
            }
        )
        self._save(state)
        if _creator_id(created) != state.get("operator_user_id"):
            raise TransactionError("created project response has the wrong creator")
        target.update({"project_id": project_id, "project_owned": True})
        intent["candidate_owned"] = True
        self._save(state)
        validate_project_identity(created, project_id, name)
        intent.update(
            {
                "status": "completed",
                "id": project_id,
                "uncertain": False,
                "outcome_unknown": False,
            }
        )
        self._save(state)

    def _ensure_log_stream(
        self, state: dict[str, object], *, retry_uncertain: bool
    ) -> None:
        config = state["config"]
        target = state["target"]
        if not isinstance(config, dict) or not isinstance(target, dict):
            raise TransactionError("stored target/config is malformed")
        project_id = require_uuid(target.get("project_id"), "project ID")
        name = validate_text(config.get("log_stream_name"), "Log-stream name")
        existing_id = target.get("log_stream_id")
        if existing_id:
            record = self.api.get_log_stream(
                project_id, require_uuid(existing_id, "Log-stream ID")
            )
            if record is None:
                raise TransactionError("recorded Log stream is absent")
            validate_log_stream_identity(record, project_id, str(existing_id), name)
            return

        streams = self.api.list_log_streams(project_id)
        matches = [item for item in streams if item.get("name") == name]
        requested_id = config.get("log_stream_id")
        if requested_id:
            requested_id = require_uuid(requested_id, "requested Log-stream ID")
            matches = [item for item in matches if item.get("id") == requested_id]
            if len(matches) != 1:
                raise TransactionError(
                    "requested Log-stream ID/name did not resolve exactly"
                )
            if config.get("adopt_log_stream") is not True:
                raise TransactionError(
                    "adopting an existing Log stream requires --adopt-log-stream"
                )
            validate_log_stream_identity(matches[0], project_id, requested_id, name)
            target.update({"log_stream_id": requested_id, "log_stream_owned": False})
            self._save(state)
            return

        intents = state.setdefault("intents", {})
        if not isinstance(intents, dict):
            raise TransactionError("transaction intents are malformed")
        intent = intents.get("log_stream")
        if isinstance(intent, dict):
            if (
                intent.get("status") != "pending"
                or intent.get("name") != name
                or intent.get("project_id") != project_id
            ):
                raise TransactionError("pending Log-stream intent is inconsistent")
            preexisting_ids = intent.get("preexisting_ids")
            if not isinstance(preexisting_ids, list):
                raise TransactionError("pending Log-stream intent is malformed")
            reconciled = [
                item for item in matches if item.get("id") not in preexisting_ids
            ]
            if len(reconciled) > 1:
                raise TransactionError(
                    "ambiguous Log-stream POST produced multiple candidates"
                )
            if len(reconciled) == 1:
                log_stream_id = require_uuid(reconciled[0].get("id"), "Log-stream ID")
                if _creator_id(reconciled[0]) != state.get("operator_user_id"):
                    raise TransactionError(
                        "reconciled Log-stream creator does not match"
                    )
                validate_log_stream_identity(
                    reconciled[0], project_id, log_stream_id, name
                )
                target.update(
                    {"log_stream_id": log_stream_id, "log_stream_owned": True}
                )
                intent.update(
                    {
                        "status": "reconciled",
                        "id": log_stream_id,
                        "outcome_unknown": False,
                        "uncertain": False,
                    }
                )
                self._save(state)
                return
            if (
                intent.get("outcome_unknown") is True or intent.get("uncertain") is True
            ) and not retry_uncertain:
                raise ReconciliationRequired(
                    "Log-stream POST outcome is uncertain; inventory is empty; rerun with "
                    "--retry-uncertain only after the backend consistency window"
                )

        if len(matches) > 1:
            raise TransactionError("multiple Log streams have the requested exact name")
        if len(matches) == 1:
            if config.get("adopt_log_stream") is not True:
                raise TransactionError(
                    "Log stream already exists; explicit adoption is required"
                )
            log_stream_id = require_uuid(matches[0].get("id"), "Log-stream ID")
            validate_log_stream_identity(matches[0], project_id, log_stream_id, name)
            target.update({"log_stream_id": log_stream_id, "log_stream_owned": False})
            self._save(state)
            return

        if not isinstance(intent, dict):
            intent = {
                "status": "pending",
                "name": name,
                "project_id": project_id,
                "started_at": iso_now(),
                "preexisting_ids": [item.get("id") for item in streams],
                "uncertain": False,
                "outcome_unknown": False,
            }
            intents["log_stream"] = intent
            self._save(state)

        intent.update(
            {
                "outcome_unknown": True,
                "last_attempt_at": iso_now(),
            }
        )
        self._save(state)
        try:
            created = self.api.create_log_stream(project_id, name)
        except BaseException as exc:
            if isinstance(exc, ApiFailure):
                intent["uncertain"] = exc.uncertain
                intent["outcome_unknown"] = exc.uncertain
                self._save(state)
            raise
        self.failpoint("after_log_stream_post")
        log_stream_id = require_uuid(created.get("id"), "created Log-stream ID")
        intent.update(
            {
                "candidate_id": log_stream_id,
                "candidate_owned": False,
                "outcome_unknown": False,
            }
        )
        self._save(state)
        if _creator_id(created) != state.get("operator_user_id"):
            raise TransactionError("created Log-stream response has the wrong creator")
        target.update({"log_stream_id": log_stream_id, "log_stream_owned": True})
        intent["candidate_owned"] = True
        self._save(state)
        validate_log_stream_identity(created, project_id, log_stream_id, name)
        intent.update(
            {
                "status": "completed",
                "id": log_stream_id,
                "uncertain": False,
                "outcome_unknown": False,
            }
        )
        self._save(state)

    def _runtime_output(self, state: Mapping[str, object]) -> Path:
        config = state.get("config")
        if not isinstance(config, dict):
            raise TransactionError("stored config is malformed")
        return Path(
            validate_text(
                config.get("runtime_key_output"), "runtime key output", maximum=4096
            )
        )

    def _verify_runtime(
        self, state: Mapping[str, object], secret: str, key_record: Mapping[str, object]
    ) -> None:
        target = state.get("target")
        runtime = state.get("runtime_key")
        if not isinstance(target, dict):
            raise TransactionError("stored target is malformed")
        project_id = require_uuid(target.get("project_id"), "project ID")
        log_stream_id = require_uuid(target.get("log_stream_id"), "Log-stream ID")
        project_name = state["config"].get("project_name")  # type: ignore[index]
        log_stream_name = state["config"].get("log_stream_name")  # type: ignore[index]
        key_id = require_uuid(key_record.get("id"), "runtime API-key ID")
        config = state.get("config")
        if not isinstance(config, dict):
            raise TransactionError("stored config is malformed")
        runtime_role = config.get("runtime_role")
        expected_description = None
        if isinstance(runtime, dict):
            expected_description = runtime.get("description")
        if (
            key_record.get("description") != expected_description
            or key_record.get("project_id") != project_id
            or key_record.get("project_role") != runtime_role
        ):
            raise TransactionError(
                "runtime API key is not scoped to the exact project/role"
            )
        if (
            runtime
            and isinstance(runtime, dict)
            and runtime.get("id") not in {None, key_id}
        ):
            raise TransactionError("runtime API-key ID changed")
        runtime_api = self.runtime_api_factory(secret)
        runtime_base = getattr(runtime_api, "api_base", None)
        if not isinstance(runtime_base, str) or validate_api_base(
            runtime_base
        ) != state.get("api_base"):
            raise TransactionError(
                "runtime API transport origin does not match the transaction journal"
            )
        user = runtime_api.current_user()
        if user.get("id") != state.get("operator_user_id"):
            raise TransactionError("runtime API key resolves to a different user")
        projects = runtime_api.list_projects(("log_data",))
        if len(projects) != 1:
            raise TransactionError(
                "runtime API key does not have exact project-only visibility"
            )
        validate_project_identity(projects[0], project_id, str(project_name))
        permissions = [
            item
            for item in projects[0].get("permissions", [])
            if isinstance(item, dict) and item.get("action") == "log_data"
        ]
        if len(permissions) != 1 or permissions[0].get("allowed") is not True:
            raise TransactionError("runtime API key lacks explicit log_data permission")
        streams = runtime_api.list_log_streams(project_id)
        selected = [item for item in streams if item.get("id") == log_stream_id]
        if len(selected) != 1:
            raise TransactionError(
                "runtime API key cannot resolve the exact Log stream"
            )
        validate_log_stream_identity(
            selected[0], project_id, log_stream_id, str(log_stream_name)
        )

    def _ensure_runtime_key(
        self, state: dict[str, object], *, retry_uncertain: bool
    ) -> None:
        target = state["target"]
        config = state["config"]
        intents = state["intents"]
        if (
            not isinstance(target, dict)
            or not isinstance(config, dict)
            or not isinstance(intents, dict)
        ):
            raise TransactionError("stored runtime transaction data is malformed")
        project_id = require_uuid(target.get("project_id"), "project ID")
        intent = intents.get("runtime_key")
        if not isinstance(intent, dict):
            raise TransactionError("runtime-key intent is missing")
        runtime = state.get("runtime_key")
        if isinstance(runtime, dict) and runtime.get("id"):
            rows = self.api.list_keys(str(state["operator_user_id"]))
            selected = [item for item in rows if item.get("id") == runtime.get("id")]
            output_path = self._runtime_output(state)
            try:
                secret = read_secret(output_path, "runtime key output")
            except TransactionError as exc:
                if "readable protected file" not in str(exc):
                    raise
                if runtime.get("status") != "candidate":
                    raise TransactionError(
                        "verified runtime key output is missing; refusing automatic recovery"
                    ) from exc
                if len(selected) > 1:
                    raise TransactionError("recorded runtime API-key ID is duplicated")
                if len(selected) == 0:
                    if not retry_uncertain:
                        raise ReconciliationRequired(
                            "candidate runtime key is not yet visible; rerun with "
                            "--retry-uncertain only after the backend consistency window"
                        ) from exc
                else:
                    self.api.delete_key(str(runtime["id"]))
                    if any(
                        item.get("id") == runtime.get("id")
                        for item in self.api.list_keys(str(state["operator_user_id"]))
                    ):
                        raise TransactionError(
                            "candidate runtime API key remains after exact cleanup"
                        )
                attempt = int(intent.get("attempt", 1)) + 1
                intent.update(
                    {
                        "attempt": attempt,
                        "description": (
                            f"{config['runtime_description']}-{state['transaction_id']}"
                            f"-attempt-{attempt}"
                        ),
                        "status": "pending",
                        "uncertain": False,
                        "outcome_unknown": False,
                        "lost_secret_key_cleaned": runtime["id"],
                    }
                )
                state["runtime_key"] = {}
                self._save(state)
                runtime = None
            else:
                current_output = _file_record(output_path, "runtime key output")
                recorded_output = runtime.get("output")
                if isinstance(recorded_output, dict):
                    for field in ("path", "device", "inode", "size"):
                        if recorded_output.get(field) != current_output.get(field):
                            raise TransactionError(
                                "runtime key output identity changed"
                            )
                else:
                    runtime["output"] = current_output
                    self._save(state)
                if len(selected) != 1 or not truncated_matches(
                    secret, selected[0].get("truncated")
                ):
                    raise TransactionError(
                        "recorded runtime API key cannot be revalidated"
                    )
                self._verify_runtime(state, secret, selected[0])
                runtime["status"] = "verified"
                intent.update(
                    {
                        "status": "completed",
                        "id": runtime["id"],
                        "uncertain": False,
                        "outcome_unknown": False,
                    }
                )
                self._save(state)
                return

        description = validate_text(
            intent.get("description"), "runtime-key description"
        )
        rows = self.api.list_keys(str(state["operator_user_id"]))
        candidates = [item for item in rows if item.get("description") == description]
        intent_status = intent.get("status")
        if intent_status == "not_started":
            if candidates:
                raise TransactionError(
                    "runtime-key description already existed before this transaction"
                )
            intent["preexisting_ids"] = [
                require_uuid(item.get("id"), "preexisting API-key ID") for item in rows
            ]
        elif intent_status == "pending":
            preexisting_ids = intent.get("preexisting_ids")
            if not isinstance(preexisting_ids, list):
                raise TransactionError(
                    "runtime-key intent is missing its pre-mutation inventory"
                )
            preexisting = {
                require_uuid(item, "preexisting API-key ID") for item in preexisting_ids
            }
            if any(item.get("id") in preexisting for item in candidates):
                raise TransactionError(
                    "runtime-key description collides with a preexisting API key"
                )
            candidates = [
                item for item in candidates if item.get("id") not in preexisting
            ]
        else:
            raise TransactionError("runtime-key intent status is inconsistent")
        if len(candidates) > 1:
            raise TransactionError("runtime-key intent resolved to multiple API keys")
        output_path = self._runtime_output(state)
        output_secret: str | None = None
        try:
            output_secret = read_secret(output_path, "runtime key output")
        except TransactionError as exc:
            if "readable protected file" not in str(exc):
                raise
        if candidates and output_secret is not None:
            candidate = candidates[0]
            if not truncated_matches(output_secret, candidate.get("truncated")):
                raise TransactionError(
                    "runtime output does not match the reconciled API key"
                )
            runtime = {
                "id": require_uuid(candidate.get("id"), "runtime API-key ID"),
                "description": description,
                "project_id": candidate.get("project_id"),
                "project_role": candidate.get("project_role"),
                "output": _file_record(output_path, "runtime key output"),
                "owned": True,
                "status": "candidate",
            }
            state["runtime_key"] = runtime
            intent.update({"status": "reconciled", "id": runtime["id"]})
            # Persist ownership before a permission probe can fail.  Rollback
            # can then revoke only this exact key and remove its exact output.
            self._save(state)
            self._verify_runtime(state, output_secret, candidate)
            runtime["status"] = "verified"
            intent.update(
                {
                    "status": "completed",
                    "id": runtime["id"],
                    "uncertain": False,
                    "outcome_unknown": False,
                }
            )
            self._save(state)
            return
        if candidates and output_secret is None:
            # The response/secret was lost.  The unique intent proves ownership,
            # so remove that exact unusable key before creating a new attempt.
            lost_id = require_uuid(candidates[0].get("id"), "lost runtime API-key ID")
            self.api.delete_key(lost_id)
            remaining = [
                item
                for item in self.api.list_keys(str(state["operator_user_id"]))
                if item.get("id") == lost_id
            ]
            if remaining:
                raise TransactionError(
                    "lost-secret runtime key remains after exact cleanup"
                )
            attempt = int(intent.get("attempt", 1)) + 1
            intent.update(
                {
                    "attempt": attempt,
                    "description": f"{config['runtime_description']}-{state['transaction_id']}-attempt-{attempt}",
                    "status": "pending",
                    "uncertain": False,
                    "outcome_unknown": False,
                    "lost_secret_key_cleaned": lost_id,
                }
            )
            self._save(state)
            description = str(intent["description"])
        elif (
            intent.get("outcome_unknown") is True or intent.get("uncertain") is True
        ) and not retry_uncertain:
            raise ReconciliationRequired(
                "runtime-key POST outcome is uncertain; inventory is empty; rerun with "
                "--retry-uncertain only after the backend consistency window"
            )

        intent.update(
            {
                "status": "pending",
                "started_at": iso_now(),
                "outcome_unknown": True,
                "preexisting_ids": [
                    require_uuid(item.get("id"), "preexisting API-key ID")
                    for item in self.api.list_keys(str(state["operator_user_id"]))
                ],
            }
        )
        self._save(state)
        try:
            created = self.api.create_key(
                description,
                str(config["runtime_key_expires_at"]),
                project_id,
                str(config["runtime_role"]),
            )
        except BaseException as exc:
            if isinstance(exc, ApiFailure):
                intent["uncertain"] = exc.uncertain
                intent["outcome_unknown"] = exc.uncertain
                intent["last_attempt_at"] = iso_now()
                self._save(state)
            raise
        self.failpoint("after_runtime_key_post")
        key_id = require_uuid(created.get("id"), "created runtime API-key ID")
        runtime = {
            "id": key_id,
            "description": description,
            "project_id": project_id,
            "project_role": config["runtime_role"],
            "output": None,
            "owned": True,
            "status": "candidate",
        }
        state["runtime_key"] = runtime
        intent.update(
            {
                "candidate_id": key_id,
                "candidate_owned": True,
                "outcome_unknown": False,
            }
        )
        # The exact ID returned by our POST is owned cleanup state even when a
        # malformed response, output collision, or later permission probe
        # fails.  Persist it before any fallible response validation.
        self._save(state)
        secret = created.get("api_key")
        if (
            not isinstance(secret, str)
            or not secret
            or any(ord(character) < 32 or ord(character) == 127 for character in secret)
        ):
            raise ApiFailure(200, "create runtime API key", uncertain=True)
        if (
            created.get("description") != description
            or created.get("project_id") != project_id
            or created.get("project_role") != config["runtime_role"]
        ):
            raise TransactionError("created runtime API-key identity/scope mismatch")
        output_record = create_secret_file(output_path, secret)
        self.failpoint("after_runtime_key_output")
        runtime["output"] = output_record
        # Persist exact ownership before probing the candidate role.  A role
        # without log_data fails safely and remains exactly rollback-able.
        self._save(state)
        self._verify_runtime(state, secret, created)
        runtime["status"] = "verified"
        intent.update(
            {
                "status": "completed",
                "id": key_id,
                "uncertain": False,
                "outcome_unknown": False,
            }
        )
        self._save(state)

    def record_cutover_evidence(
        self, evidence_file: Path, *, maximum_age_seconds: int
    ) -> dict[str, object]:
        state = self.store.load()
        if state is None:
            raise TransactionError("transaction state does not exist")
        if state.get("phase") == "HOST_CUTOVER_VALIDATED":
            evidence = self._validate_evidence(
                state, evidence_file, maximum_age_seconds
            )
            recorded = state.get("cutover_evidence")
            if (
                isinstance(recorded, dict)
                and recorded.get("sha256") == evidence["sha256"]
            ):
                return self._sanitized_status(state)
            raise TransactionError("different cutover evidence is already recorded")
        if state.get("phase") != "RUNTIME_KEY_CREATED":
            raise TransactionError("cutover evidence requires RUNTIME_KEY_CREATED")
        evidence = self._validate_evidence(state, evidence_file, maximum_age_seconds)
        state["cutover_evidence"] = evidence
        self._transition(state, "HOST_CUTOVER_VALIDATED")
        return self._sanitized_status(state)

    def _validate_evidence(
        self,
        state: Mapping[str, object],
        evidence_file: Path,
        maximum_age_seconds: int,
        *,
        enforce_freshness: bool = True,
    ) -> dict[str, object]:
        if (
            type(maximum_age_seconds) is not int
            or maximum_age_seconds <= 0
            or maximum_age_seconds > MAX_EVIDENCE_AGE_SECONDS
        ):
            raise TransactionError(
                f"maximum evidence age must be 1..{MAX_EVIDENCE_AGE_SECONDS} seconds"
            )
        raw, info = read_protected_bytes(
            evidence_file, MAX_EVIDENCE_BYTES, "cutover evidence"
        )
        try:
            document = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as exc:
            raise TransactionError("cutover evidence is malformed") from exc
        if (
            not isinstance(document, dict)
            or not EVIDENCE_REQUIRED_TOP_LEVEL.issubset(document)
            or set(document) - EVIDENCE_REQUIRED_TOP_LEVEL - EVIDENCE_OPTIONAL_TOP_LEVEL
        ):
            raise TransactionError("cutover evidence has an unexpected schema")
        if document.get("schema_version") != EVIDENCE_SCHEMA:
            raise TransactionError("cutover evidence schema version is unsupported")
        _reject_secret_fields(document)
        target = state.get("target")
        runtime = state.get("runtime_key")
        if not isinstance(target, dict) or not isinstance(runtime, dict):
            raise TransactionError("transaction target/runtime state is malformed")
        bindings = {
            "transaction_id": state.get("transaction_id"),
            "api_base": state.get("api_base"),
            "project_id": target.get("project_id"),
            "log_stream_id": target.get("log_stream_id"),
            "runtime_key_id": runtime.get("id"),
        }
        for key, expected in bindings.items():
            if document.get(key) != expected:
                raise TransactionError(f"cutover evidence {key} binding mismatch")
        for section, required in EVIDENCE_BOOLEAN_SECTIONS.items():
            value = document.get(section)
            if not isinstance(value, dict) or set(value) != required:
                raise TransactionError(f"cutover evidence {section} shape mismatch")
            if any(value[item] is not True for item in required):
                raise TransactionError(f"cutover evidence {section} is incomplete")
        console_review = document.get("console_review")
        if console_review is not None and console_review != {"status": "not_observed"}:
            raise TransactionError(
                "Console review is not a revocation gate; observed UI proof requires "
                "separate browser-attested evidence"
            )
        observed = parse_timestamp(document.get("observed_at"), "evidence observed_at")
        now = utc_now()
        if observed > now + dt.timedelta(seconds=60):
            raise TransactionError("cutover evidence timestamp is in the future")
        if enforce_freshness and (now - observed).total_seconds() > maximum_age_seconds:
            raise TransactionError("cutover evidence is stale")
        runtime_transition = next(
            (
                item
                for item in state.get("history", [])
                if isinstance(item, dict) and item.get("phase") == "RUNTIME_KEY_CREATED"
            ),
            None,
        )
        if not isinstance(runtime_transition, dict) or observed < parse_timestamp(
            runtime_transition.get("at"), "runtime transition timestamp"
        ):
            raise TransactionError("cutover evidence predates runtime-key creation")
        return {
            "path": str(evidence_file),
            "device": info.st_dev,
            "inode": info.st_ino,
            "size": info.st_size,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "observed_at": document["observed_at"],
        }

    def _revalidate_recorded_evidence(
        self,
        state: Mapping[str, object],
        evidence_file: Path,
        maximum_age_seconds: int,
        *,
        allow_stale: bool = False,
    ) -> None:
        expected = state.get("cutover_evidence")
        if not isinstance(expected, dict):
            raise TransactionError("cutover evidence is not recorded")
        current = self._validate_evidence(
            state,
            evidence_file,
            maximum_age_seconds,
            enforce_freshness=not allow_stale,
        )
        for key in ("path", "device", "inode", "size", "sha256", "observed_at"):
            if current.get(key) != expected.get(key):
                raise TransactionError("cutover evidence changed after recording")

    def _normalize_revoke_intent(
        self, state: dict[str, object], intent: dict[str, object]
    ) -> None:
        """Validate reconciliation state and migrate a pre-counter pending intent."""

        if intent.get("actor") != "distinct_revoker":
            raise TransactionError(
                "legacy self-delete revoke intent cannot be resumed automatically; "
                "a distinct reviewed revoker and out-of-band reconciliation are required"
            )
        old = state.get("old_key")
        if not isinstance(old, dict):
            raise TransactionError("old-key transaction state is malformed")
        old_id = require_uuid(old.get("id"), "old API-key ID")
        revoker_id = require_uuid(intent.get("revoker_key_id"), "revoker API-key ID")
        require_uuid(intent.get("revoker_user_id"), "revoker user ID")
        if revoker_id == old_id:
            raise TransactionError("revoker API key must differ from the old key")
        changed = False
        delete_started = intent.get("delete_started")
        if type(delete_started) is not bool:
            raise TransactionError("old-key revoke intent is inconsistent")
        if "delete_attempts" not in intent:
            intent["delete_attempts"] = 1 if delete_started else 0
            changed = True
        if "authorization_checks" not in intent:
            intent["authorization_checks"] = 0
            changed = True
        if "token_authorization_checks" not in intent:
            intent["token_authorization_checks"] = 0
            changed = True
        if "reconciliation_pending" not in intent:
            intent["reconciliation_pending"] = delete_started
            changed = True
        if "inventory_checks" not in intent:
            intent["inventory_checks"] = 0
            changed = True
        if delete_started and "last_delete_attempt_at" not in intent:
            started_at = intent.get("delete_started_at")
            parse_timestamp(started_at, "old-key delete-started timestamp")
            intent["last_delete_attempt_at"] = started_at
            changed = True
        delete_attempts = intent.get("delete_attempts")
        authorization_checks = intent.get("authorization_checks")
        token_authorization_checks = intent.get("token_authorization_checks")
        inventory_checks = intent.get("inventory_checks")
        if (
            type(delete_attempts) is not int
            or not 0 <= delete_attempts <= MAX_REVOKE_DELETE_ATTEMPTS
            or type(authorization_checks) is not int
            or authorization_checks < 0
            or type(token_authorization_checks) is not int
            or token_authorization_checks < 0
            or type(inventory_checks) is not int
            or inventory_checks < 0
            or type(intent.get("reconciliation_pending")) is not bool
            or (not delete_started and delete_attempts != 0)
        ):
            raise TransactionError("old-key revoke intent is inconsistent")
        outcome = intent.get("last_delete_outcome")
        if outcome is not None and outcome not in {
            "success",
            "http_401",
            "http_404",
            "uncertain",
            "failed",
        }:
            raise TransactionError("old-key revoke intent is inconsistent")
        if delete_started:
            parse_timestamp(
                intent.get("delete_started_at"), "old-key delete-started timestamp"
            )
        if delete_attempts:
            parse_timestamp(
                intent.get("last_delete_attempt_at"),
                "old-key delete-attempt timestamp",
            )
        if authorization_checks:
            parse_timestamp(
                intent.get("last_authorized_at"),
                "old-key authorization-check timestamp",
            )
        if token_authorization_checks:
            parse_timestamp(
                intent.get("last_token_authorized_at"),
                "old-key token-authorization timestamp",
            )
        if inventory_checks:
            parse_timestamp(
                intent.get("last_inventory_check_at"),
                "old-key inventory-check timestamp",
            )
            if type(intent.get("last_inventory_absent")) is not bool:
                raise TransactionError("old-key revoke intent is inconsistent")
        if "uncertain" in intent and type(intent.get("uncertain")) is not bool:
            raise TransactionError("old-key revoke intent is inconsistent")
        proof = intent.get("revocation_proof")
        proved_at = intent.get("revocation_proved_at")
        if (proof is None) != (proved_at is None):
            raise TransactionError("old-key revoke intent is inconsistent")
        if proof is not None:
            if proof != "current_user_401_and_token_401":
                raise TransactionError("old-key revoke intent is inconsistent")
            parse_timestamp(proved_at, "old-key revocation proof timestamp")
            if intent.get("reconciliation_pending") is not False or intent.get(
                "uncertain"
            ) not in {None, False}:
                raise TransactionError("old-key revoke intent is inconsistent")
        if changed:
            self._save(state)

    def _validate_distinct_revoker(
        self,
        state: Mapping[str, object],
        *,
        old_id: str,
        runtime_id: str,
    ) -> tuple[str, str]:
        if (
            self.revoker_api is None
            or self.revoker_secret is None
            or self.revoker_key_id is None
        ):
            raise TransactionError(
                "finalize requires a protected distinct revoker credential and exact key ID"
            )
        transport_base = getattr(self.revoker_api, "api_base", None)
        if not isinstance(transport_base, str) or validate_api_base(
            transport_base
        ) != state.get("api_base"):
            raise TransactionError(
                "revoker API transport origin does not match the transaction journal"
            )
        revoker_id = require_uuid(self.revoker_key_id, "revoker API-key ID")
        if revoker_id in {old_id, runtime_id}:
            raise TransactionError(
                "revoker API key must differ from old and runtime keys"
            )
        if self.bootstrap_secret is not None and hmac.compare_digest(
            self.revoker_secret, self.bootstrap_secret
        ):
            raise TransactionError("revoker credential must differ from the old key")
        user = self.revoker_api.current_user()
        revoker_user_id = require_uuid(user.get("id"), "revoker current-user ID")
        rows = self.revoker_api.list_keys(revoker_user_id)
        selected = [row for row in rows if row.get("id") == revoker_id]
        if len(selected) != 1 or not truncated_matches(
            self.revoker_secret, selected[0].get("truncated")
        ):
            raise TransactionError(
                "revoker credential did not match the exact reviewed key ID"
            )
        if selected[0].get("project_id") not in {None, ""}:
            raise TransactionError("revoker API key must not be project-scoped")
        return revoker_id, revoker_user_id

    def _reconcile_old_key_inventory(
        self, state: dict[str, object], intent: dict[str, object]
    ) -> bool:
        """Record full admin inventory state without treating absence as revocation."""

        if self.revoker_api is None:
            raise TransactionError("distinct revoker API is unavailable")
        operator_id = require_uuid(state.get("operator_user_id"), "operator user ID")
        old = state.get("old_key")
        if not isinstance(old, dict):
            raise TransactionError("old-key transaction state is malformed")
        old_id = require_uuid(old.get("id"), "old API-key ID")
        rows = self.revoker_api.list_keys(operator_id)
        selected = [row for row in rows if row.get("id") == old_id]
        if len(selected) > 1:
            raise TransactionError("old-key inventory returned duplicate target IDs")
        if (
            selected
            and self.bootstrap_secret is not None
            and not truncated_matches(
                self.bootstrap_secret, selected[0].get("truncated")
            )
        ):
            raise TransactionError("old-key inventory identity changed during finalize")
        checks = intent.get("inventory_checks")
        if type(checks) is not int or checks < 0:
            raise TransactionError("old-key revoke intent is inconsistent")
        absent = not selected
        intent.update(
            {
                "inventory_checks": checks + 1,
                "last_inventory_check_at": iso_now(),
                "last_inventory_absent": absent,
            }
        )
        self._save(state)
        return absent

    def _check_old_key_authorization(
        self, state: dict[str, object], intent: dict[str, object]
    ) -> bool:
        """Require durable direct 401s from both old-key authentication routes."""

        if intent.get("revocation_proof") == "current_user_401_and_token_401":
            return True
        try:
            user = self.api.current_user()
        except ApiFailure as exc:
            if exc.status != 401:
                raise
        else:
            user_id = require_uuid(user.get("id"), "current-user ID")
            if user_id != state.get("operator_user_id"):
                raise TransactionError("old key now resolves to a different operator")
            checks = intent.get("authorization_checks")
            if type(checks) is not int or checks < 0:
                raise TransactionError("old-key revoke intent is inconsistent")
            intent.update(
                {
                    "authorization_checks": checks + 1,
                    "last_authorized_at": iso_now(),
                    "reconciliation_pending": intent.get("delete_started") is True,
                }
            )
            self._save(state)
            return False

        token_probe = getattr(self.api, "token_authorization", None)
        if not callable(token_probe):
            raise TransactionError("old-key token probe is unavailable")
        try:
            token_probe()
        except ApiFailure as exc:
            if exc.status != 401:
                raise
            intent.update(
                {
                    "revocation_proof": "current_user_401_and_token_401",
                    "revocation_proved_at": iso_now(),
                    "reconciliation_pending": False,
                    "uncertain": False,
                }
            )
            self._save(state)
            return True
        token_checks = intent.get("token_authorization_checks")
        if type(token_checks) is not int or token_checks < 0:
            raise TransactionError("old-key revoke intent is inconsistent")
        intent.update(
            {
                "token_authorization_checks": token_checks + 1,
                "last_token_authorized_at": iso_now(),
                "reconciliation_pending": True,
            }
        )
        self._save(state)
        return False

    def _poll_old_key_revocation(
        self,
        state: dict[str, object],
        intent: dict[str, object],
        *,
        attempts: int,
    ) -> bool:
        if (
            type(attempts) is not int
            or not 1 <= attempts <= MAX_REVOKE_AUTH_CHECKS_PER_FINALIZE
        ):
            raise TransactionError("old-key reconciliation poll bound is invalid")
        for index in range(attempts):
            inventory_absent = self._reconcile_old_key_inventory(state, intent)
            authorization_revoked = self._check_old_key_authorization(state, intent)
            if inventory_absent and authorization_revoked:
                return True
            if index + 1 < attempts:
                self.revoke_sleep(REVOKE_POLL_INTERVAL_SECONDS)
        return False

    def _attempt_bound_old_key_delete(
        self,
        state: dict[str, object],
        intent: dict[str, object],
        old_id: str,
    ) -> None:
        """Attempt DELETE only for the immutable ID already bound in the intent."""

        attempts = intent.get("delete_attempts")
        if (
            type(attempts) is not int
            or attempts < 0
            or attempts >= MAX_REVOKE_DELETE_ATTEMPTS
        ):
            raise ReconciliationRequired(
                "old-key DELETE attempts are exhausted; direct 401 proof is pending"
            )
        if self.revoker_api is None:
            raise TransactionError("distinct revoker API is unavailable")
        attempt = attempts + 1
        intent.update(
            {
                "delete_started": True,
                "delete_started_at": intent.get("delete_started_at") or iso_now(),
                "delete_attempts": attempt,
                "last_delete_attempt_at": iso_now(),
                "reconciliation_pending": True,
            }
        )
        self._save(state)
        try:
            self.revoker_api.delete_key(old_id)
        except ApiFailure as exc:
            if exc.uncertain:
                intent.update(
                    {
                        "last_delete_outcome": "uncertain",
                        "uncertain": True,
                    }
                )
                self._save(state)
                raise
            if exc.status not in {401, 404}:
                intent.update(
                    {
                        "last_delete_outcome": "failed",
                        "uncertain": False,
                    }
                )
                self._save(state)
                raise
            # A repeated DELETE may return 401/404 after the mutation committed.
            # Neither response proves that the protected old credential itself
            # is unauthorized; both direct old-key authentication probes must
            # independently return 401.
            intent.update(
                {
                    "last_delete_outcome": f"http_{exc.status}",
                    "uncertain": False,
                }
            )
            self._save(state)
        else:
            intent.update(
                {
                    "last_delete_outcome": "success",
                    "uncertain": False,
                }
            )
            self._save(state)
        self.failpoint("after_old_key_revoke")

    @staticmethod
    def _revoke_resume_allows_stale_evidence(state: Mapping[str, object]) -> bool:
        if state.get("phase") == "OLD_KEY_REVOKED":
            return True
        old = state.get("old_key")
        intents = state.get("intents")
        evidence = state.get("cutover_evidence")
        if not isinstance(old, dict) or not isinstance(intents, dict):
            raise TransactionError("old-key transaction state is malformed")
        intent = intents.get("old_key_revoke")
        if not isinstance(intent, dict):
            return False
        if (
            intent.get("status") != "pending"
            or intent.get("id") != old.get("id")
            or not isinstance(evidence, dict)
            or intent.get("evidence_sha256") != evidence.get("sha256")
            or type(intent.get("delete_started")) is not bool
        ):
            raise TransactionError("old-key revoke intent is inconsistent")
        return intent["delete_started"] is True

    def _validate_legacy_credential_prebinding(
        self, state: Mapping[str, object]
    ) -> dict[str, object]:
        """Bind recovery to an unchanged protected file predating PRECHECKED."""

        info = self.bootstrap_credential_info
        if not isinstance(info, dict):
            raise TransactionError(
                "legacy recovery requires protected bootstrap-file identity"
            )
        path = Path(
            validate_text(info.get("path"), "legacy bootstrap-file path", maximum=4096)
        )
        _path_parts(path)
        required_integer_fields = (
            "device",
            "inode",
            "size",
            "mtime_ns",
            "ctime_ns",
        )
        for field in required_integer_fields:
            value = info.get(field)
            if type(value) is not int or value <= 0:
                raise TransactionError("legacy bootstrap-file identity is incomplete")
        if int(info["size"]) > MAX_SECRET_BYTES:
            raise TransactionError("legacy bootstrap-file size is unsafe")
        prechecked_entries = [
            item
            for item in state.get("history", [])
            if isinstance(item, dict) and item.get("phase") == "PRECHECKED"
        ]
        if len(prechecked_entries) != 1:
            raise TransactionError("legacy journal PRECHECKED history is malformed")
        prechecked = parse_timestamp(
            prechecked_entries[0].get("at"), "PRECHECKED transition timestamp"
        )
        prechecked_ns = int(prechecked.timestamp() * 1_000_000_000)
        if (
            int(info["mtime_ns"]) > prechecked_ns
            or int(info["ctime_ns"]) > prechecked_ns
        ):
            raise TransactionError("legacy bootstrap file was changed after PRECHECKED")
        birthtime_ns = info.get("birthtime_ns")
        if birthtime_ns is not None:
            if type(birthtime_ns) is not int or not 0 < birthtime_ns <= prechecked_ns:
                raise TransactionError(
                    "legacy bootstrap-file birth time is inconsistent"
                )
        return {
            key: info[key]
            for key in (
                "path",
                "device",
                "inode",
                "size",
                "mtime_ns",
                "ctime_ns",
                "birthtime_ns",
            )
            if key in info
        }

    @staticmethod
    def _validate_pending_legacy_revoke_intent(
        state: Mapping[str, object], intent: Mapping[str, object], old_id: str
    ) -> None:
        """Accept only the one historical self-delete journal schema."""

        evidence = state.get("cutover_evidence")
        if (
            set(intent) != LEGACY_SELF_DELETE_INTENT_FIELDS
            or intent.get("status") != "pending"
            or intent.get("id") != old_id
            or intent.get("delete_started") is not True
            or not isinstance(evidence, dict)
            or intent.get("evidence_sha256") != evidence.get("sha256")
        ):
            raise TransactionError(
                "journal is not the exact supported legacy self-delete intent"
            )
        started = parse_timestamp(
            intent.get("started_at"), "legacy revoke-intent timestamp"
        )
        delete_started = parse_timestamp(
            intent.get("delete_started_at"), "legacy delete-started timestamp"
        )
        if delete_started < started:
            raise TransactionError("legacy revoke-intent timestamps are inconsistent")
        host_entries = [
            item
            for item in state.get("history", [])
            if isinstance(item, dict) and item.get("phase") == "HOST_CUTOVER_VALIDATED"
        ]
        if len(host_entries) != 1 or started < parse_timestamp(
            host_entries[0].get("at"), "host-cutover transition timestamp"
        ):
            raise TransactionError(
                "legacy revoke intent predates validated host cutover"
            )

    @staticmethod
    def _require_direct_401(probe: Callable[[], object], label: str) -> None:
        """Require one fresh, exact Unauthorized response from a bound client."""

        try:
            probe()
        except ApiFailure as exc:
            if exc.status == 401:
                return
            raise TransactionError(f"{label} did not return HTTP 401") from None
        except TransactionError:
            raise TransactionError(f"{label} did not return HTTP 401") from None
        raise TransactionError(f"{label} did not return HTTP 401")

    @staticmethod
    def _validate_completed_legacy_reconciliation(
        state: Mapping[str, object],
        intent: Mapping[str, object],
        old_id: str,
        credential_info: Mapping[str, object],
    ) -> None:
        evidence = state.get("cutover_evidence")
        proof = intent.get("legacy_reconciliation")
        if (
            set(intent) != LEGACY_SELF_DELETE_INTENT_FIELDS | {"legacy_reconciliation"}
            or intent.get("status") != "completed"
            or intent.get("id") != old_id
            or intent.get("delete_started") is not True
            or not isinstance(evidence, dict)
            or intent.get("evidence_sha256") != evidence.get("sha256")
            or not isinstance(proof, dict)
            or set(proof)
            != {
                "method",
                "current_user_status",
                "token_status",
                "confirmed_old_key_id",
                "credential_file",
                "proved_at",
            }
            or proof.get("method") != "dual_endpoint_401_no_delete"
            or proof.get("current_user_status") != 401
            or proof.get("token_status") != 401
            or proof.get("confirmed_old_key_id") != old_id
            or proof.get("credential_file") != dict(credential_info)
        ):
            raise TransactionError("legacy revocation reconciliation proof is invalid")
        parse_timestamp(proof.get("proved_at"), "legacy reconciliation timestamp")

    def reconcile_legacy_revocation(
        self,
        evidence_file: Path,
        *,
        maximum_age_seconds: int,
        confirmed_old_key_id: str,
    ) -> dict[str, object]:
        """Close only a historical started self-delete; never call DELETE."""

        state = self.store.load()
        if state is None:
            raise TransactionError("transaction state does not exist")
        self._validate_api_binding(state)
        old = state.get("old_key")
        runtime = state.get("runtime_key")
        intents = state.get("intents")
        if (
            not isinstance(old, dict)
            or not isinstance(runtime, dict)
            or not isinstance(intents, dict)
        ):
            raise TransactionError("legacy transaction state is malformed")
        old_id = require_uuid(old.get("id"), "old API-key ID")
        if require_uuid(confirmed_old_key_id, "confirmed old API-key ID") != old_id:
            raise TransactionError("confirmed old API-key ID does not match journal")
        runtime_id = require_uuid(runtime.get("id"), "runtime API-key ID")
        if runtime_id == old_id:
            raise TransactionError("runtime and old API-key IDs must differ")
        if state.get("phase") == "FINALIZED":
            return self._sanitized_status(state)
        if state.get("phase") not in {
            "HOST_CUTOVER_VALIDATED",
            "OLD_KEY_REVOKED",
        }:
            raise TransactionError(
                "legacy recovery requires HOST_CUTOVER_VALIDATED or OLD_KEY_REVOKED"
            )
        if self.bootstrap_secret is None:
            raise TransactionError("legacy recovery requires the old credential")
        credential_info = self._validate_legacy_credential_prebinding(state)
        self._revalidate_recorded_evidence(
            state,
            evidence_file,
            maximum_age_seconds,
            allow_stale=True,
        )
        runtime_secret = read_secret(self._runtime_output(state), "runtime key output")
        if hmac.compare_digest(self.bootstrap_secret, runtime_secret):
            raise TransactionError("old and runtime credentials must differ")
        self._verify_runtime(state, runtime_secret, runtime)

        intent = intents.get("old_key_revoke")
        if not isinstance(intent, dict):
            raise TransactionError("legacy revoke intent is missing")
        if state.get("phase") == "HOST_CUTOVER_VALIDATED":
            if old.get("revoked") is not False:
                raise TransactionError("legacy old-key state is inconsistent")
            self._validate_pending_legacy_revoke_intent(state, intent, old_id)
        else:
            if old.get("revoked") is not True:
                raise TransactionError("legacy old-key state is inconsistent")
            self._validate_completed_legacy_reconciliation(
                state, intent, old_id, credential_info
            )

        self._require_direct_401(self.api.current_user, "old-key current_user probe")
        token_probe = getattr(self.api, "token_authorization", None)
        if not callable(token_probe):
            raise TransactionError("old-key token probe is unavailable")
        self._require_direct_401(token_probe, "old-key token probe")

        if state.get("phase") == "HOST_CUTOVER_VALIDATED":
            intent.update(
                {
                    "status": "completed",
                    "legacy_reconciliation": {
                        "method": "dual_endpoint_401_no_delete",
                        "current_user_status": 401,
                        "token_status": 401,
                        "confirmed_old_key_id": old_id,
                        "credential_file": credential_info,
                        "proved_at": iso_now(),
                    },
                }
            )
            old["revoked"] = True
            self._transition(state, "OLD_KEY_REVOKED")
            self.failpoint("after_legacy_revocation_reconciled")

        # Re-prove the deployed runtime after the local irreversible phase mark.
        self._verify_runtime(state, runtime_secret, runtime)
        if state.get("phase") == "OLD_KEY_REVOKED":
            self._transition(state, "FINALIZED")
        return self._sanitized_status(state)

    def finalize(
        self, evidence_file: Path, *, maximum_age_seconds: int
    ) -> dict[str, object]:
        state = self.store.load()
        if state is None:
            raise TransactionError("transaction state does not exist")
        self._validate_api_binding(state)
        if state.get("phase") == "FINALIZED":
            return self._sanitized_status(state)
        if state.get("phase") not in {"HOST_CUTOVER_VALIDATED", "OLD_KEY_REVOKED"}:
            raise TransactionError(
                "finalize requires fresh HOST_CUTOVER_VALIDATED evidence"
            )
        allow_stale = self._revoke_resume_allows_stale_evidence(state)
        self._revalidate_recorded_evidence(
            state,
            evidence_file,
            maximum_age_seconds,
            allow_stale=allow_stale,
        )
        runtime = state.get("runtime_key")
        if not isinstance(runtime, dict):
            raise TransactionError("runtime key state is malformed")
        runtime_secret = read_secret(self._runtime_output(state), "runtime key output")
        self._verify_runtime(state, runtime_secret, runtime)

        if state.get("phase") == "HOST_CUTOVER_VALIDATED":
            if self.bootstrap_secret is None:
                raise TransactionError("bootstrap credential is required to finalize")
            old = state.get("old_key")
            if not isinstance(old, dict):
                raise TransactionError("old-key state is malformed")
            old_id = require_uuid(old.get("id"), "old API-key ID")
            runtime_id = require_uuid(runtime.get("id"), "runtime API-key ID")
            revoker_id, revoker_user_id = self._validate_distinct_revoker(
                state, old_id=old_id, runtime_id=runtime_id
            )
            intents = state.setdefault("intents", {})
            if not isinstance(intents, dict):
                raise TransactionError("transaction intents are malformed")
            revoke_intent = intents.get("old_key_revoke")
            if not isinstance(revoke_intent, dict):
                # Freshly prove that the protected bootstrap file still maps to
                # the exact key scheduled for revocation.
                user = self.api.current_user()
                user_id = require_uuid(user.get("id"), "current-user ID")
                rows = self.api.list_keys(user_id)
                selected = [item for item in rows if item.get("id") == old_id]
                if len(selected) != 1 or not truncated_matches(
                    self.bootstrap_secret, selected[0].get("truncated")
                ):
                    raise TransactionError(
                        "old key no longer matches the finalize target"
                    )
                revoke_intent = {
                    "status": "pending",
                    "id": old_id,
                    "actor": "distinct_revoker",
                    "revoker_key_id": revoker_id,
                    "revoker_user_id": revoker_user_id,
                    "started_at": iso_now(),
                    "evidence_sha256": state["cutover_evidence"]["sha256"],  # type: ignore[index]
                    "delete_started": False,
                    "delete_attempts": 0,
                    "authorization_checks": 0,
                    "token_authorization_checks": 0,
                    "inventory_checks": 0,
                    "reconciliation_pending": False,
                }
                intents["old_key_revoke"] = revoke_intent
                self._save(state)
            elif (
                revoke_intent.get("status") != "pending"
                or revoke_intent.get("id") != old_id
                or revoke_intent.get("evidence_sha256")
                != state["cutover_evidence"]["sha256"]  # type: ignore[index]
                or type(revoke_intent.get("delete_started")) is not bool
            ):
                raise TransactionError("old-key revoke intent is inconsistent")
            self._normalize_revoke_intent(state, revoke_intent)
            if (
                revoke_intent.get("revoker_key_id") != revoker_id
                or revoke_intent.get("revoker_user_id") != revoker_user_id
            ):
                raise TransactionError("old-key revoker binding changed")
            delete_attempts = int(revoke_intent["delete_attempts"])
            delete_started = revoke_intent["delete_started"] is True
            prechecks = (
                MAX_REVOKE_AUTH_CHECKS_PER_FINALIZE
                if delete_attempts >= MAX_REVOKE_DELETE_ATTEMPTS
                else REVOKE_RESUME_PRECHECKS
                if delete_started
                else 1
            )
            revoked = self._poll_old_key_revocation(
                state, revoke_intent, attempts=prechecks
            )
            if not revoked:
                if delete_attempts >= MAX_REVOKE_DELETE_ATTEMPTS:
                    raise ReconciliationRequired(
                        "old key remains authorized after bounded reconciliation; "
                        "direct 401 proof is pending"
                    )
                self._attempt_bound_old_key_delete(state, revoke_intent, old_id)
                postchecks = MAX_REVOKE_AUTH_CHECKS_PER_FINALIZE - prechecks
                revoked = self._poll_old_key_revocation(
                    state, revoke_intent, attempts=postchecks
                )
                if not revoked:
                    raise ReconciliationRequired(
                        "old key remains authorized after bounded reconciliation; "
                        "resume finalize with the same immutable evidence"
                    )
            if (
                revoke_intent.get("revocation_proof")
                != "current_user_401_and_token_401"
                or revoke_intent.get("last_inventory_absent") is not True
            ):
                raise TransactionError("old-key revocation proof is missing")
            revoke_intent.update(
                {
                    "status": "completed",
                    "uncertain": False,
                    "reconciliation_pending": False,
                }
            )
            old["revoked"] = True
            self._transition(state, "OLD_KEY_REVOKED")

        # The old credential is no longer usable; prove the deployed runtime
        # credential and exact target still work before closing the journal.
        self._verify_runtime(state, runtime_secret, runtime)
        if state.get("phase") == "OLD_KEY_REVOKED":
            self._transition(state, "FINALIZED")
        return self._sanitized_status(state)

    def _reconcile_owned_for_rollback(self, state: dict[str, object]) -> None:
        """Resolve only uniquely attributable pending POSTs; never create here."""

        target = state.get("target")
        intents = state.get("intents")
        config = state.get("config")
        if (
            not isinstance(target, dict)
            or not isinstance(intents, dict)
            or not isinstance(config, dict)
        ):
            raise TransactionError("stored rollback state is malformed")
        operator_id = require_uuid(state.get("operator_user_id"), "operator user ID")

        project_intent = intents.get("project")
        if not target.get("project_id") and isinstance(project_intent, dict):
            name = validate_text(project_intent.get("name"), "pending project name")
            preexisting = project_intent.get("preexisting_ids")
            if project_intent.get("status") != "pending" or not isinstance(
                preexisting, list
            ):
                raise TransactionError("pending project intent is malformed")
            candidates = [
                item
                for item in self.api.list_projects(("log_data",))
                if item.get("name") == name and item.get("id") not in preexisting
            ]
            if len(candidates) > 1:
                raise TransactionError(
                    "rollback found multiple pending project candidates"
                )
            if len(candidates) == 1:
                project_id = require_uuid(candidates[0].get("id"), "project ID")
                if _creator_id(candidates[0]) != operator_id:
                    raise TransactionError("rollback project creator does not match")
                validate_project_identity(candidates[0], project_id, name)
                target.update({"project_id": project_id, "project_owned": True})
                project_intent.update({"status": "reconciled", "id": project_id})
                self._save(state)

        project_id_value = target.get("project_id")
        log_stream_intent = intents.get("log_stream")
        if (
            project_id_value
            and not target.get("log_stream_id")
            and isinstance(log_stream_intent, dict)
        ):
            project_id = require_uuid(project_id_value, "project ID")
            name = validate_text(
                log_stream_intent.get("name"), "pending Log-stream name"
            )
            preexisting = log_stream_intent.get("preexisting_ids")
            if (
                log_stream_intent.get("status") != "pending"
                or log_stream_intent.get("project_id") != project_id
                or not isinstance(preexisting, list)
            ):
                raise TransactionError("pending Log-stream intent is malformed")
            candidates = [
                item
                for item in self.api.list_log_streams(project_id)
                if item.get("name") == name and item.get("id") not in preexisting
            ]
            if len(candidates) > 1:
                raise TransactionError(
                    "rollback found multiple pending Log-stream candidates"
                )
            if len(candidates) == 1:
                log_stream_id = require_uuid(candidates[0].get("id"), "Log-stream ID")
                if _creator_id(candidates[0]) != operator_id:
                    raise TransactionError("rollback Log-stream creator does not match")
                validate_log_stream_identity(
                    candidates[0], project_id, log_stream_id, name
                )
                target.update(
                    {"log_stream_id": log_stream_id, "log_stream_owned": True}
                )
                log_stream_intent.update({"status": "reconciled", "id": log_stream_id})
                self._save(state)

        runtime = state.get("runtime_key")
        runtime_intent = intents.get("runtime_key")
        if (
            not (isinstance(runtime, dict) and runtime.get("id"))
            and isinstance(runtime_intent, dict)
            and runtime_intent.get("status") == "pending"
        ):
            description = validate_text(
                runtime_intent.get("description"), "pending runtime-key description"
            )
            preexisting = runtime_intent.get("preexisting_ids")
            if not isinstance(preexisting, list):
                raise TransactionError("pending runtime-key intent is malformed")
            rows = self.api.list_keys(operator_id)
            candidates = [
                item
                for item in rows
                if item.get("description") == description
                and item.get("id") not in preexisting
            ]
            if len(candidates) > 1:
                raise TransactionError(
                    "rollback found multiple pending API-key candidates"
                )
            if len(candidates) == 1:
                key_id = require_uuid(candidates[0].get("id"), "runtime API-key ID")
                runtime = {
                    "id": key_id,
                    "description": description,
                    "project_id": target.get("project_id"),
                    "project_role": config.get("runtime_role"),
                    "output": None,
                    "owned": True,
                    "status": "candidate",
                }
                state["runtime_key"] = runtime
                runtime_intent.update(
                    {"status": "reconciled", "id": key_id, "candidate_owned": True}
                )
                self._save(state)

    def rollback(self) -> dict[str, object]:
        state = self.store.load()
        if state is None:
            raise TransactionError("transaction state does not exist")
        self._validate_api_binding(state)
        if state.get("phase") == TERMINAL_ROLLBACK_PHASE:
            return self._sanitized_status(state)
        if phase_index(state.get("phase")) >= phase_index("OLD_KEY_REVOKED"):
            raise TransactionError("rollback is forbidden after old-key revocation")
        intents = state.get("intents")
        revoke_intent = (
            intents.get("old_key_revoke") if isinstance(intents, dict) else None
        )
        if (
            isinstance(revoke_intent, dict)
            and revoke_intent.get("delete_started") is True
        ):
            raise TransactionError(
                "rollback is forbidden after old-key revocation started"
            )
        if self.bootstrap_secret is None:
            raise TransactionError("bootstrap credential is required for rollback")
        self._reconcile_owned_for_rollback(state)
        user_id = require_uuid(state.get("operator_user_id"), "operator user ID")
        runtime = state.get("runtime_key")
        if (
            isinstance(runtime, dict)
            and runtime.get("owned") is True
            and runtime.get("id")
        ):
            key_id = require_uuid(runtime.get("id"), "runtime API-key ID")
            rows = self.api.list_keys(user_id)
            selected = [item for item in rows if item.get("id") == key_id]
            output = runtime.get("output")
            if not isinstance(output, dict):
                try:
                    output_secret = read_secret(
                        self._runtime_output(state), "runtime key output"
                    )
                except TransactionError as exc:
                    if "readable protected file" not in str(exc):
                        raise
                else:
                    if len(selected) == 1 and truncated_matches(
                        output_secret, selected[0].get("truncated")
                    ):
                        output = _file_record(
                            self._runtime_output(state), "runtime key output"
                        )
                        runtime["output"] = output
                        self._save(state)
            if selected:
                self.api.delete_key(key_id)
            if any(item.get("id") == key_id for item in self.api.list_keys(user_id)):
                raise TransactionError("owned runtime API key remains after rollback")
            if isinstance(output, dict):
                # Exact key absence is established above. A missing file is now
                # an idempotent crash-resume success; a replacement inode still
                # fails closed and is never unlinked.
                unlink_owned_file(output, missing_ok=True)
                self.failpoint("after_runtime_output_unlink")
            runtime["rolled_back"] = True
            self._save(state)

        target = state.get("target")
        if not isinstance(target, dict):
            raise TransactionError("stored target is malformed")
        project_id = target.get("project_id")
        log_stream_id = target.get("log_stream_id")
        if (
            target.get("log_stream_owned") is True
            and project_id
            and log_stream_id
            and self.api.get_log_stream(str(project_id), str(log_stream_id)) is not None
        ):
            self.api.delete_log_stream(str(project_id), str(log_stream_id))
            if self.api.get_log_stream(str(project_id), str(log_stream_id)) is not None:
                raise TransactionError("owned Log stream remains after rollback")
            target["log_stream_rolled_back"] = True
            self._save(state)
        if (
            target.get("project_owned") is True
            and project_id
            and self.api.get_project(str(project_id)) is not None
        ):
            self.api.delete_project(str(project_id))
            if self.api.get_project(str(project_id)) is not None:
                raise TransactionError("owned project remains after rollback")
            target["project_rolled_back"] = True
            self._save(state)
        state["phase"] = TERMINAL_ROLLBACK_PHASE
        history = state.setdefault("history", [])
        if isinstance(history, list):
            history.append(_history_entry(TERMINAL_ROLLBACK_PHASE))
        self._save(state)
        return self._sanitized_status(state)


def _file_record(path: Path, label: str) -> dict[str, object]:
    raw, info = read_protected_bytes(path, MAX_SECRET_BYTES, label)
    return {
        "path": str(path),
        "device": info.st_dev,
        "inode": info.st_ino,
        "size": info.st_size,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _reject_secret_fields(document: object) -> None:
    pending = [document]
    visited = 0
    while pending:
        value = pending.pop()
        visited += 1
        if visited > 100_000:
            raise TransactionError("cutover evidence is too deeply structured")
        if isinstance(value, dict):
            for key, item in value.items():
                normalized = str(key).lower().replace("-", "_")
                if (
                    normalized
                    in {"secret", "password", "token", "authorization", "api_key"}
                    or normalized.endswith("_secret")
                    or normalized.endswith("_password")
                    or normalized.endswith("_token")
                ):
                    raise TransactionError(
                        "cutover evidence contains a secret-bearing field"
                    )
                pending.append(item)
        elif isinstance(value, list):
            pending.extend(value)


def build_config(args: argparse.Namespace) -> dict[str, object]:
    expires = parse_timestamp(args.runtime_key_expires_at, "runtime key expiry")
    if expires <= utc_now() + dt.timedelta(minutes=5):
        raise TransactionError("runtime key expiry must be more than five minutes away")
    return {
        "api_base": validate_api_base(args.api_base),
        "old_key_id": require_uuid(args.old_key_id, "old API-key ID"),
        "project_name": validate_text(args.project_name, "project name"),
        "project_id": require_uuid(args.project_id, "project ID")
        if args.project_id
        else None,
        "adopt_project": bool(args.adopt_project),
        "log_stream_name": validate_text(args.log_stream_name, "Log-stream name"),
        "log_stream_id": (
            require_uuid(args.log_stream_id, "Log-stream ID")
            if args.log_stream_id
            else None
        ),
        "adopt_log_stream": bool(args.adopt_log_stream),
        "runtime_description": validate_text(
            args.runtime_description, "runtime-key description", maximum=256
        ),
        "runtime_key_expires_at": expires.isoformat().replace("+00:00", "Z"),
        "runtime_key_output": str(Path(args.runtime_key_output)),
        "runtime_role": args.runtime_role,
    }


def add_state_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--state-dir", type=Path, required=True)


def add_credential_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--api-base", required=True)
    parser.add_argument("--bootstrap-key-file", type=Path, required=True)


def add_revoker_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--revoker-key-file", type=Path, required=True)
    parser.add_argument("--revoker-key-id", required=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap = subparsers.add_parser("bootstrap")
    add_state_argument(bootstrap)
    add_credential_arguments(bootstrap)
    bootstrap.add_argument("--old-key-id", required=True)
    bootstrap.add_argument("--project-name", required=True)
    bootstrap.add_argument("--project-id", default="")
    bootstrap.add_argument("--adopt-project", action="store_true")
    bootstrap.add_argument("--log-stream-name", required=True)
    bootstrap.add_argument("--log-stream-id", default="")
    bootstrap.add_argument("--adopt-log-stream", action="store_true")
    bootstrap.add_argument("--runtime-description", required=True)
    bootstrap.add_argument(
        "--runtime-role",
        choices=RUNTIME_ROLES,
        default="annotator",
        help=(
            "Project-scoped candidate role. Annotator is attempted by default; "
            "bootstrap still requires an explicit live log_data permission."
        ),
    )
    bootstrap.add_argument("--runtime-key-expires-at", required=True)
    bootstrap.add_argument("--runtime-key-output", type=Path, required=True)
    bootstrap.add_argument("--retry-uncertain", action="store_true")

    evidence = subparsers.add_parser("record-cutover-evidence")
    add_state_argument(evidence)
    evidence.add_argument("--evidence-file", type=Path, required=True)
    evidence.add_argument("--maximum-age-seconds", type=int, default=900)

    finalize = subparsers.add_parser("finalize")
    add_state_argument(finalize)
    add_credential_arguments(finalize)
    add_revoker_arguments(finalize)
    finalize.add_argument("--evidence-file", type=Path, required=True)
    finalize.add_argument("--maximum-age-seconds", type=int, default=900)

    legacy_recovery = subparsers.add_parser("reconcile-legacy-revocation")
    add_state_argument(legacy_recovery)
    add_credential_arguments(legacy_recovery)
    legacy_recovery.add_argument("--confirm-old-key-id", required=True)
    legacy_recovery.add_argument("--evidence-file", type=Path, required=True)
    legacy_recovery.add_argument("--maximum-age-seconds", type=int, default=900)

    rollback = subparsers.add_parser("rollback")
    add_state_argument(rollback)
    add_credential_arguments(rollback)

    status = subparsers.add_parser("status")
    add_state_argument(status)
    return parser.parse_args()


def _transaction_with_credential(
    store: StateStore, api_base: str, credential_file: Path
) -> GalileoBootstrapTransaction:
    secret, credential_info = read_secret_with_info(
        credential_file, "bootstrap credential"
    )
    api = HttpGalileoApi(api_base, secret)
    return GalileoBootstrapTransaction(
        store,
        api,
        runtime_api_factory=lambda runtime_secret: HttpGalileoApi(
            api.api_base, runtime_secret
        ),
        bootstrap_secret=secret,
        bootstrap_credential_info=credential_info,
    )


def _transaction_with_revoker(
    store: StateStore,
    api_base: str,
    old_credential_file: Path,
    revoker_credential_file: Path,
    revoker_key_id: str,
) -> GalileoBootstrapTransaction:
    old_secret, old_credential_info = read_secret_with_info(
        old_credential_file, "old bootstrap credential"
    )
    revoker_secret = read_secret(revoker_credential_file, "revoker credential")
    old_api = HttpGalileoApi(api_base, old_secret)
    revoker_api = HttpGalileoApi(api_base, revoker_secret)
    return GalileoBootstrapTransaction(
        store,
        old_api,
        runtime_api_factory=lambda runtime_secret: HttpGalileoApi(
            old_api.api_base, runtime_secret
        ),
        bootstrap_secret=old_secret,
        revoker_api=revoker_api,
        revoker_secret=revoker_secret,
        revoker_key_id=require_uuid(revoker_key_id, "revoker API-key ID"),
        bootstrap_credential_info=old_credential_info,
    )


def main() -> None:
    args = parse_args()
    try:
        with StateStore(args.state_dir) as store:
            if args.command == "bootstrap":
                transaction = _transaction_with_credential(
                    store, args.api_base, args.bootstrap_key_file
                )
                result = transaction.bootstrap(
                    build_config(args), retry_uncertain=args.retry_uncertain
                )
            elif args.command == "record-cutover-evidence":
                if args.maximum_age_seconds <= 0:
                    raise TransactionError("maximum evidence age must be positive")
                transaction = GalileoBootstrapTransaction(
                    store,
                    None,
                    runtime_api_factory=lambda _: None,
                    bootstrap_secret=None,
                )
                result = transaction.record_cutover_evidence(
                    args.evidence_file, maximum_age_seconds=args.maximum_age_seconds
                )
            elif args.command == "finalize":
                if args.maximum_age_seconds <= 0:
                    raise TransactionError("maximum evidence age must be positive")
                transaction = _transaction_with_revoker(
                    store,
                    args.api_base,
                    args.bootstrap_key_file,
                    args.revoker_key_file,
                    args.revoker_key_id,
                )
                result = transaction.finalize(
                    args.evidence_file, maximum_age_seconds=args.maximum_age_seconds
                )
            elif args.command == "reconcile-legacy-revocation":
                if args.maximum_age_seconds <= 0:
                    raise TransactionError("maximum evidence age must be positive")
                transaction = _transaction_with_credential(
                    store, args.api_base, args.bootstrap_key_file
                )
                result = transaction.reconcile_legacy_revocation(
                    args.evidence_file,
                    maximum_age_seconds=args.maximum_age_seconds,
                    confirmed_old_key_id=args.confirm_old_key_id,
                )
            elif args.command == "rollback":
                transaction = _transaction_with_credential(
                    store, args.api_base, args.bootstrap_key_file
                )
                result = transaction.rollback()
            else:
                state = store.load()
                if state is None:
                    raise TransactionError("transaction state does not exist")
                result = GalileoBootstrapTransaction._sanitized_status(state)
        print(json.dumps(result, sort_keys=True))
    except (TransactionError, ValueError) as exc:
        raise SystemExit(f"ERROR: {exc}") from None


if __name__ == "__main__":
    main()

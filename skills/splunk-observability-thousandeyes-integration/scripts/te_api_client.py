#!/usr/bin/env python3
"""Fail-closed ThousandEyes v7 apply helper for rendered integration assets.

The client is intentionally fixed to ``https://api.thousandeyes.com/v7``.
Secrets are accepted only through mode-600 files, responses are never written
to predictable temporary paths, and create operations retain non-secret IDs in
mode-600 local state before performing a collection readback.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from contextlib import contextmanager
from typing import Any, Iterable


API_BASE = "https://api.thousandeyes.com/v7"
MAX_RESPONSE_BYTES = 10 * 1024 * 1024
SAFE_PATH_RE = re.compile(r"^[A-Za-z0-9._~/-]+$")
SAFE_KEY_RE = re.compile(r"^[A-Za-z0-9._:-]+$")
SAFE_FIELD_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")
STATE_SCHEMA_VERSION = 2
MAX_STATE_BYTES = 1024 * 1024
DEFAULT_ID_KEYS = (
    "id",
    "streamId",
    "connectorId",
    "testId",
    "ruleId",
    "labelId",
    "tagId",
    "dashboardId",
    "templateId",
)


class ApplyError(RuntimeError):
    """An apply precondition, request, or readback failed."""


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Keep bearer-authenticated requests on the fixed API origin."""

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def read_secret_file(raw_path: str) -> str:
    path = Path(raw_path)
    if not hasattr(os, "O_NOFOLLOW"):
        raise ApplyError("this runtime cannot enforce O_NOFOLLOW for secret files")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ApplyError(f"cannot securely open secret file: {path}") from exc
    try:
        before = os.fstat(fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_size < 1
            or before.st_size > 65536
        ):
            raise ApplyError(
                f"secret file must be a non-empty single-link mode-600 regular file: {path}"
            )
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(fd)
        if (
            (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            )
            != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            )
            or after.st_nlink != 1
        ):
            raise ApplyError(f"secret file changed while it was read: {path}")
    finally:
        os.close(fd)
    try:
        lines = b"".join(chunks).decode("utf-8").splitlines()
    except UnicodeError as exc:
        raise ApplyError(f"secret file is not readable UTF-8: {path}") from exc
    if len(lines) != 1 or not lines[0] or "\x00" in lines[0]:
        raise ApplyError(f"secret file must contain exactly one non-empty line: {path}")
    return lines[0]


def load_payload(raw_path: str) -> dict[str, Any]:
    path = Path(raw_path)
    if path.is_symlink() or not path.is_file():
        raise ApplyError(f"payload must be a regular, non-symlink JSON file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ApplyError(f"payload is not readable JSON: {path}") from exc
    if not isinstance(payload, dict) or not payload:
        raise ApplyError(f"payload must be a non-empty JSON object: {path}")
    return payload


def replace_exact(value: Any, placeholder: str, replacement: str) -> Any:
    if isinstance(value, dict):
        return {key: replace_exact(item, placeholder, replacement) for key, item in value.items()}
    if isinstance(value, list):
        return [replace_exact(item, placeholder, replacement) for item in value]
    if value == placeholder:
        return replacement
    return value


def substituted_payload(args: argparse.Namespace) -> dict[str, Any]:
    payload = load_payload(args.payload_file)
    if args.secret_placeholder or args.secret_file:
        if not args.secret_placeholder or not args.secret_file:
            raise ApplyError("--secret-placeholder and --secret-file must be supplied together")
        secret = read_secret_file(args.secret_file)
        try:
            replaced = replace_exact(payload, args.secret_placeholder, secret)
            if replaced == payload:
                raise ApplyError(
                    f"secret placeholder {args.secret_placeholder!r} was absent from the payload"
                )
            payload = replaced
        finally:
            secret = ""
    if args.value_placeholder or args.value is not None:
        if not args.value_placeholder or args.value is None:
            raise ApplyError("--value-placeholder and --value must be supplied together")
        replaced = replace_exact(payload, args.value_placeholder, args.value)
        if replaced == payload:
            raise ApplyError(f"value placeholder {args.value_placeholder!r} was absent from the payload")
        payload = replaced
    return payload


def validate_path(path: str) -> str:
    normalized = path.strip("/")
    if not normalized or not SAFE_PATH_RE.fullmatch(normalized) or ".." in normalized.split("/"):
        raise ApplyError(f"unsafe ThousandEyes API path: {path!r}")
    return normalized


def request_url(path: str, account_group_id: str) -> str:
    normalized = validate_path(path)
    url = f"{API_BASE}/{normalized}"
    if account_group_id:
        if not account_group_id.isdigit():
            raise ApplyError("account group ID must contain digits only")
        url = f"{url}?{urllib.parse.urlencode({'aid': account_group_id})}"
    return url


def api_request(
    method: str,
    path: str,
    token: str,
    account_group_id: str,
    payload: dict[str, Any] | None = None,
    *,
    allow_not_found: bool = False,
) -> tuple[int, Any]:
    data = None
    if payload is not None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(
        request_url(path, account_group_id),
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            **({"Content-Type": "application/json"} if payload is not None else {}),
        },
    )
    try:
        opener = urllib.request.build_opener(NoRedirectHandler)
        with opener.open(req, timeout=30) as response:
            if response.status < 200 or response.status >= 300:
                raise ApplyError(
                    f"ThousandEyes {method} {path} returned unexpected HTTP {response.status}"
                )
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ApplyError("ThousandEyes response exceeded the 10 MiB safety limit")
            if not raw:
                return response.status, {}
            try:
                return response.status, json.loads(raw.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise ApplyError(
                    f"ThousandEyes {method} {path} returned a non-JSON success response"
                ) from exc
    except urllib.error.HTTPError as exc:
        if allow_not_found and exc.code == 404:
            return 404, {}
        # Do not echo the response body; connector responses can contain a
        # credential-bearing header value.
        raise ApplyError(f"ThousandEyes {method} {path} failed with HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ApplyError(f"ThousandEyes {method} {path} transport failed: {exc.reason}") from exc


def iter_dicts(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from iter_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_dicts(child)


def parse_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def payload_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def extract_id(value: Any, id_keys: tuple[str, ...]) -> str | None:
    if not isinstance(value, dict):
        return None
    candidates: list[dict[str, Any]] = [value]
    # TE create responses may wrap the created resource once. Never recurse
    # through arbitrary nested dictionaries where an unrelated generic `id`
    # (for example, an agent or header object) could be mistaken for the new
    # resource ID.
    for wrapper in (
        "stream",
        "connector",
        "test",
        "alertRule",
        "rule",
        "template",
        "data",
    ):
        child = value.get(wrapper)
        if isinstance(child, dict):
            candidates.append(child)
        elif isinstance(child, list) and len(child) == 1 and isinstance(child[0], dict):
            candidates.append(child[0])
    for obj in candidates:
        for key in id_keys:
            candidate = obj.get(key)
            if isinstance(candidate, (str, int)) and str(candidate).strip():
                return str(candidate).strip()
    return None


def object_id(obj: dict[str, Any], id_keys: tuple[str, ...]) -> str | None:
    for key in id_keys:
        value = obj.get(key)
        if isinstance(value, (str, int)) and str(value).strip():
            return str(value).strip()
    return None


def find_by_id(value: Any, wanted: str, id_keys: tuple[str, ...]) -> dict[str, Any] | None:
    for obj in iter_dicts(value):
        if object_id(obj, id_keys) == wanted:
            return obj
    return None


def stable_identity(
    desired: dict[str, Any],
    identity_fields: tuple[str, ...],
    optional_fields: tuple[str, ...] = (),
    constants: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not identity_fields:
        raise ApplyError(
            "ensure-create requires authoritative, non-empty --identity-fields before mutation"
        )
    constants = constants or {}
    all_fields = (*identity_fields, *optional_fields, *constants)
    if len(all_fields) != len(set(all_fields)):
        raise ApplyError("ensure-create identity fields, optional fields, and constants must be unique")
    identity: dict[str, Any] = {}
    for field in identity_fields:
        if not SAFE_FIELD_RE.fullmatch(field):
            raise ApplyError(f"unsafe identity field: {field!r}")
        if field not in desired:
            raise ApplyError(f"identity field {field!r} is absent from the create payload")
        value = desired[field]
        if value is None or value == "" or value == [] or value == {}:
            raise ApplyError(
                f"identity field {field!r} must be non-empty in the create payload"
            )
        identity[field] = {"present": True, "value": value}
    for field in optional_fields:
        if not SAFE_FIELD_RE.fullmatch(field):
            raise ApplyError(f"unsafe optional identity field: {field!r}")
        identity[field] = (
            {"present": True, "value": desired[field]}
            if field in desired
            else {"present": False}
        )
    for field, value in constants.items():
        if not SAFE_FIELD_RE.fullmatch(field) or value is None or value == "":
            raise ApplyError(f"invalid identity constant: {field!r}")
        identity[field] = {"present": True, "value": value}
    return identity


def parse_identity_constants(values: list[str]) -> dict[str, str]:
    constants: dict[str, str] = {}
    for item in values:
        field, separator, value = item.partition("=")
        field = field.strip()
        value = value.strip()
        if not separator or not SAFE_FIELD_RE.fullmatch(field) or not value:
            raise ApplyError(
                "--identity-constant must use a safe non-empty FIELD=VALUE form"
            )
        if field in constants:
            raise ApplyError(f"duplicate identity constant: {field!r}")
        constants[field] = value
    return constants


def find_identity_matches(
    value: Any,
    identity: dict[str, Any],
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for obj in iter_dicts(value):
        matched = True
        for field, expectation in identity.items():
            present = bool(expectation.get("present"))
            if present != (field in obj):
                matched = False
                break
            if present and obj[field] != expectation.get("value"):
                matched = False
                break
        if matched:
            matches.append(obj)
    return matches


def find_converged(
    value: Any,
    desired: dict[str, Any],
    verify_fields: tuple[str, ...],
) -> dict[str, Any] | None:
    for obj in iter_dicts(value):
        if all(field in desired and obj.get(field) == desired[field] for field in verify_fields):
            return obj
    return None


def state_path(state_dir: Path, key: str) -> Path:
    if not SAFE_KEY_RE.fullmatch(key):
        raise ApplyError(f"unsafe state key: {key!r}")
    return state_dir / f"{key}.json"


def validate_state_dir(state_dir: Path, *, create: bool) -> None:
    if state_dir.parent.is_symlink():
        raise ApplyError(f"apply state parent must not be a symlink: {state_dir.parent}")
    if not state_dir.exists():
        if not create:
            return
        # Concurrent first use may race here. exist_ok avoids a spurious
        # FileExistsError; the descriptor-independent lstat checks below still
        # reject a symlink or non-private directory created by an attacker.
        state_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    metadata = state_dir.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise ApplyError(f"apply state directory must be a real directory: {state_dir}")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ApplyError(f"apply state directory must have mode 0700 or stricter: {state_dir}")


def _read_private_json(path: Path) -> dict[str, Any]:
    if not hasattr(os, "O_NOFOLLOW"):
        raise ApplyError("this runtime cannot enforce O_NOFOLLOW for apply state")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ApplyError(f"cannot securely open apply state: {path}") from exc
    try:
        before = os.fstat(fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_size < 1
            or before.st_size > MAX_STATE_BYTES
        ):
            raise ApplyError(f"apply state must be a private single-link regular file: {path}")
        chunks: list[bytes] = []
        remaining = MAX_STATE_BYTES + 1
        while remaining:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(fd)
        if (
            (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            or after.st_nlink != 1
        ):
            raise ApplyError(f"apply state changed while it was read: {path}")
    finally:
        os.close(fd)
    raw = b"".join(chunks)
    if len(raw) > MAX_STATE_BYTES:
        raise ApplyError(f"apply state exceeds the {MAX_STATE_BYTES}-byte limit: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ApplyError(f"apply state is unreadable or corrupt: {path}") from exc
    if not isinstance(value, dict):
        raise ApplyError(f"apply state has an invalid schema: {path}")
    return value


def read_state(state_dir: Path, key: str) -> dict[str, Any] | None:
    validate_state_dir(state_dir, create=False)
    path = state_path(state_dir, key)
    if not path.exists():
        return None
    return _read_private_json(path)


def write_state(state_dir: Path, key: str, value: dict[str, Any]) -> None:
    validate_state_dir(state_dir, create=True)
    path = state_path(state_dir, key)
    if path.exists() or path.is_symlink():
        _read_private_json(path)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=state_dir, prefix=".te-state-", delete=False
        ) as handle:
            temp_path = Path(handle.name)
            os.chmod(temp_path, 0o600)
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        os.chmod(path, 0o600)
        directory_fd = os.open(state_dir, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


@contextmanager
def create_state_lock(state_dir: Path, key: str):
    """Serialize one logical create across preflight, POST, and readback."""
    validate_state_dir(state_dir, create=True)
    # Validate the key with the same allowlist used for state filenames.
    state_path(state_dir, key)
    lock_path = state_dir / f".{key}.lock"
    if not hasattr(os, "O_NOFOLLOW"):
        raise ApplyError("this runtime cannot enforce O_NOFOLLOW for create locks")
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW
    try:
        fd = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise ApplyError(f"cannot securely open create lock: {lock_path}") from exc
    try:
        metadata = os.fstat(fd)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise ApplyError(f"create lock must be a private single-link file: {lock_path}")
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def create_state_record(
    *,
    status: str,
    desired_digest: str,
    identity_fields: tuple[str, ...],
    identity: dict[str, Any],
    collection_path: str,
    create_path: str,
    object_id_value: str = "",
    reason: str = "",
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": STATE_SCHEMA_VERSION,
        "status": status,
        "payload_sha256": desired_digest,
        "identity_fields": list(identity_fields),
        "identity": identity,
        "collection_path": collection_path,
        "create_path": create_path,
        "verified_exists": status == "verified",
        "manual_reconcile": status in {"in_progress", "ambiguous"},
    }
    if object_id_value:
        value["id"] = object_id_value
    if reason:
        value["reason"] = reason
    return value


def write_ambiguous_create_state(
    state_dir: Path,
    key: str,
    *,
    desired_digest: str,
    identity_fields: tuple[str, ...],
    identity: dict[str, Any],
    collection_path: str,
    create_path: str,
    reason: str,
    object_id_value: str = "",
) -> None:
    write_state(
        state_dir,
        key,
        create_state_record(
            status="ambiguous",
            desired_digest=desired_digest,
            identity_fields=identity_fields,
            identity=identity,
            collection_path=collection_path,
            create_path=create_path,
            object_id_value=object_id_value,
            reason=reason,
        ),
    )


def prepare_create(args: argparse.Namespace) -> dict[str, Any]:
    rendered_payload = load_payload(args.payload_file)
    desired = substituted_payload(args)
    # Fingerprint the non-secret rendered payload. Token rotation must not
    # create a secret-derived state oracle or look like unrelated config drift.
    desired_digest = payload_digest(rendered_payload)
    identity_fields = parse_csv(args.identity_fields)
    if len(identity_fields) != len(set(identity_fields)):
        raise ApplyError("ensure-create identity fields must be unique")
    optional_identity_fields = parse_csv(getattr(args, "identity_optional_fields", ""))
    identity_constants = parse_identity_constants(getattr(args, "identity_constant", []))
    identity = stable_identity(
        desired,
        identity_fields,
        optional_identity_fields,
        identity_constants,
    )
    identity_fields = tuple(identity)
    id_keys = parse_csv(args.id_keys) or DEFAULT_ID_KEYS
    if any(not SAFE_FIELD_RE.fullmatch(key) for key in id_keys):
        raise ApplyError("ensure-create ID keys contain an unsafe field name")
    collection_path = validate_path(args.collection_path)
    create_path = validate_path(args.create_path)
    return {
        "desired": desired,
        "desired_digest": desired_digest,
        "identity_fields": identity_fields,
        "identity": identity,
        "id_keys": id_keys,
        "collection_path": collection_path,
        "create_path": create_path,
        "state_dir": Path(args.state_dir),
    }


def _ensure_create_locked(
    args: argparse.Namespace,
    token: str,
    prepared: dict[str, Any],
) -> str:
    desired = prepared["desired"]
    desired_digest = prepared["desired_digest"]
    identity_fields = prepared["identity_fields"]
    identity = prepared["identity"]
    id_keys = prepared["id_keys"]
    collection_path = prepared["collection_path"]
    create_path = prepared["create_path"]
    state_dir = prepared["state_dir"]

    # Read durable state before any API request. A persisted in-progress state
    # means the prior process may have reached POST and must never auto-retry.
    previous = read_state(state_dir, args.key)
    if previous is not None:
        previous_status = str(previous.get("status", "")).strip()
        if previous_status in {"in_progress", "ambiguous"}:
            reason = str(previous.get("reason", "prior create did not converge")).strip()
            raise ApplyError(
                f"create state for {args.key} is {previous_status} ({reason}); "
                "manual reconciliation is required and automatic POST retry is blocked"
            )
        if previous_status not in {"", "verified", "created_pending_readback"}:
            raise ApplyError(
                f"create state for {args.key} has unknown status {previous_status!r}; "
                "manual reconciliation is required"
            )
        previous_id = str(previous.get("id", "")).strip()
        if not previous_id:
            raise ApplyError(
                f"state for {args.key} has no retained object ID; manual reconciliation is required"
            )
        previous_digest = str(previous.get("payload_sha256", "")).strip()
        if not previous_digest:
            raise ApplyError(
                f"state for {args.key} predates payload fingerprinting; reconcile it before retrying"
            )
        if previous_digest != desired_digest:
            raise ApplyError(
                f"rendered payload for {args.key} changed after create; no update schema is encoded"
            )
        _, before = api_request("GET", collection_path, token, args.account_group_id)
        found = find_by_id(before, previous_id, id_keys)
        if found is None:
            raise ApplyError(
                f"retained object ID {previous_id!r} is absent from live readback; refusing a duplicate create"
            )
        if not find_identity_matches([found], identity):
            raise ApplyError(
                f"retained object ID {previous_id!r} no longer matches rendered identity fields; "
                "review drift before retrying"
            )
        write_state(
            state_dir,
            args.key,
            create_state_record(
                status="verified",
                desired_digest=desired_digest,
                identity_fields=identity_fields,
                identity=identity,
                collection_path=collection_path,
                create_path=create_path,
                object_id_value=previous_id,
            ),
        )
        print(f"SKIPPED {args.key}: retained live ID {previous_id} exists", file=sys.stderr)
        return previous_id

    _, before = api_request("GET", collection_path, token, args.account_group_id)
    existing_matches = find_identity_matches(before, identity)
    if len(existing_matches) > 1:
        raise ApplyError(
            f"multiple live objects match the stable identity for {args.key}; "
            "manual reconciliation is required before mutation"
        )
    if existing_matches:
        existing_id = object_id(existing_matches[0], id_keys)
        if not existing_id:
            raise ApplyError(
                f"live object matches {args.key} identity but exposes no usable ID; refusing a duplicate create"
            )
        write_state(
            state_dir,
            args.key,
            create_state_record(
                status="verified",
                desired_digest=desired_digest,
                identity_fields=identity_fields,
                identity=identity,
                collection_path=collection_path,
                create_path=create_path,
                object_id_value=existing_id,
            ),
        )
        print(f"SKIPPED {args.key}: adopted existing live object {existing_id}", file=sys.stderr)
        return existing_id

    # Persist and fsync intent before POST. If the process is interrupted at
    # any later instruction, this in-progress record blocks a second POST.
    write_state(
        state_dir,
        args.key,
        create_state_record(
            status="in_progress",
            desired_digest=desired_digest,
            identity_fields=identity_fields,
            identity=identity,
            collection_path=collection_path,
            create_path=create_path,
            reason="create intent persisted before POST",
        ),
    )
    try:
        _, created = api_request("POST", create_path, token, args.account_group_id, desired)
    except (ApplyError, OSError, ValueError) as exc:
        write_ambiguous_create_state(
            state_dir,
            args.key,
            desired_digest=desired_digest,
            identity_fields=identity_fields,
            identity=identity,
            collection_path=collection_path,
            create_path=create_path,
            reason="POST outcome is unknown",
        )
        raise ApplyError(
            f"create for {args.key} did not return a trustworthy result; manual reconciliation is required"
        ) from exc

    created_id = extract_id(created, id_keys)
    if not created_id:
        write_ambiguous_create_state(
            state_dir,
            args.key,
            desired_digest=desired_digest,
            identity_fields=identity_fields,
            identity=identity,
            collection_path=collection_path,
            create_path=create_path,
            reason="successful POST response exposed no usable object ID",
        )
        raise ApplyError(
            f"create for {args.key} returned success without a usable ID; "
            "manual reconciliation is required and automatic POST retry is blocked"
        )

    write_state(
        state_dir,
        args.key,
        create_state_record(
            status="created_pending_readback",
            desired_digest=desired_digest,
            identity_fields=identity_fields,
            identity=identity,
            collection_path=collection_path,
            create_path=create_path,
            object_id_value=created_id,
        ),
    )
    try:
        _, after = api_request("GET", collection_path, token, args.account_group_id)
    except (ApplyError, OSError, ValueError) as exc:
        write_ambiguous_create_state(
            state_dir,
            args.key,
            desired_digest=desired_digest,
            identity_fields=identity_fields,
            identity=identity,
            collection_path=collection_path,
            create_path=create_path,
            object_id_value=created_id,
            reason="post-create collection readback failed",
        )
        raise ApplyError(
            f"create for {args.key} returned ID {created_id!r} but readback failed; "
            "manual reconciliation is required"
        ) from exc
    live = find_by_id(after, created_id, id_keys)
    if live is None or not find_identity_matches([live], identity):
        write_ambiguous_create_state(
            state_dir,
            args.key,
            desired_digest=desired_digest,
            identity_fields=identity_fields,
            identity=identity,
            collection_path=collection_path,
            create_path=create_path,
            object_id_value=created_id,
            reason="post-create readback did not expose the returned ID with matching identity",
        )
        raise ApplyError(
            f"create for {args.key} returned ID {created_id!r} but exact collection readback failed; "
            "manual reconciliation is required and automatic POST retry is blocked"
        )
    write_state(
        state_dir,
        args.key,
        create_state_record(
            status="verified",
            desired_digest=desired_digest,
            identity_fields=identity_fields,
            identity=identity,
            collection_path=collection_path,
            create_path=create_path,
            object_id_value=created_id,
        ),
    )
    print(f"CREATED {args.key}: live ID {created_id} verified by collection readback", file=sys.stderr)
    return created_id


def ensure_create(args: argparse.Namespace, token: str) -> str:
    prepared = prepare_create(args)
    state_dir = prepared["state_dir"]
    with create_state_lock(state_dir, args.key):
        return _ensure_create_locked(args, token, prepared)


def ensure_put(args: argparse.Namespace, token: str) -> str:
    desired = substituted_payload(args)
    verify_fields = parse_csv(args.verify_fields)
    if not verify_fields:
        raise ApplyError("ensure-put requires at least one --verify-fields entry")
    # Collection/read endpoint preflight occurs before any PUT.
    api_request("GET", args.preflight_path, token, args.account_group_id)
    status, current = api_request(
        "GET",
        args.resource_path,
        token,
        args.account_group_id,
        allow_not_found=True,
    )
    if status == 200 and find_converged(current, desired, verify_fields) is not None:
        print(f"SKIPPED {args.key}: live resource already converged", file=sys.stderr)
        return args.value or args.key
    if status == 404 and args.require_existing:
        raise ApplyError(f"required update target does not exist: {args.resource_path}")

    api_request("PUT", args.resource_path, token, args.account_group_id, desired)
    _, readback = api_request("GET", args.resource_path, token, args.account_group_id)
    if find_converged(readback, desired, verify_fields) is None:
        raise ApplyError(
            f"PUT for {args.key} returned success but readback did not match: {', '.join(verify_fields)}"
        )
    write_state(Path(args.state_dir), args.key, {"resource": args.resource_path, "converged": True})
    print(f"UPDATED {args.key}: live readback verified", file=sys.stderr)
    return args.value or args.key


def post_action(args: argparse.Namespace, token: str) -> str:
    del token
    raise ApplyError(
        "post-action is disabled: the configured readback does not prove the POST action's "
        "postcondition, so interruption-safe retry cannot be guaranteed"
    )


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_")
            if any(word in normalized for word in ("token", "password", "secret", "authorization")):
                result[key] = "[REDACTED]"
            elif normalized == "headers":
                result[key] = "[REDACTED]"
            else:
                result[key] = redact(item)
        return result
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def add_payload_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--payload-file", required=True)
    parser.add_argument("--secret-placeholder", default="")
    parser.add_argument("--secret-file", default="")
    parser.add_argument("--value-placeholder", default="")
    parser.add_argument("--value", default=None)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--token-file", required=True)
    parser.add_argument("--account-group-id", default="")
    parser.add_argument("--state-dir", required=True)
    sub = parser.add_subparsers(dest="action", required=True)

    preflight = sub.add_parser("preflight")
    preflight.add_argument("--path", required=True)

    get = sub.add_parser("get")
    get.add_argument("--path", required=True)

    create = sub.add_parser("ensure-create")
    create.add_argument("--key", required=True)
    create.add_argument("--collection-path", required=True)
    create.add_argument("--create-path", required=True)
    create.add_argument("--identity-fields", required=True)
    create.add_argument("--identity-optional-fields", default="")
    create.add_argument("--identity-constant", action="append", default=[])
    create.add_argument("--id-keys", default=",".join(DEFAULT_ID_KEYS))
    add_payload_options(create)

    put = sub.add_parser("ensure-put")
    put.add_argument("--key", required=True)
    put.add_argument("--preflight-path", required=True)
    put.add_argument("--resource-path", required=True)
    put.add_argument("--verify-fields", required=True)
    put.add_argument("--require-existing", action="store_true")
    add_payload_options(put)

    post = sub.add_parser("post-action")
    post.add_argument("--key", required=True)
    post.add_argument("--action-path", required=True)
    post.add_argument("--readback-path", required=True)

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        token = read_secret_file(args.token_file)
        if args.account_group_id and not args.account_group_id.isdigit():
            raise ApplyError("account group ID must contain digits only")
        if args.action == "preflight":
            api_request("GET", args.path, token, args.account_group_id)
            print("PREFLIGHT OK", file=sys.stderr)
        elif args.action == "get":
            _, body = api_request("GET", args.path, token, args.account_group_id)
            print(json.dumps(redact(body), indent=2, sort_keys=True))
        elif args.action == "ensure-create":
            print(ensure_create(args, token))
        elif args.action == "ensure-put":
            print(ensure_put(args, token))
        elif args.action == "post-action":
            print(post_action(args, token))
        else:  # pragma: no cover
            raise ApplyError(f"unknown action: {args.action}")
    except (ApplyError, OSError, ValueError) as exc:
        print(f"te_api_client FAILED: {exc}", file=sys.stderr)
        return 2
    finally:
        if "token" in locals():
            token = ""
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Fail-closed ThousandEyes v7 apply helper for rendered integration assets.

The client is intentionally fixed to ``https://api.thousandeyes.com/v7``.
Secrets are accepted only through mode-600 files, responses are never written
to predictable temporary paths, and create operations retain non-secret IDs in
mode-600 local state before performing a collection readback.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable


API_BASE = "https://api.thousandeyes.com/v7"
MAX_RESPONSE_BYTES = 10 * 1024 * 1024
SAFE_PATH_RE = re.compile(r"^[A-Za-z0-9._~/-]+$")
SAFE_KEY_RE = re.compile(r"^[A-Za-z0-9._:-]+$")
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
    if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
        raise ApplyError(f"secret file must be a non-empty regular, non-symlink file: {path}")
    mode = path.stat().st_mode & 0o777
    if mode != 0o600:
        raise ApplyError(f"secret file must have mode 600 (found {oct(mode)}): {path}")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
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
    for obj in iter_dicts(value):
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


def find_by_identity(
    value: Any,
    desired: dict[str, Any],
    identity_fields: tuple[str, ...],
) -> dict[str, Any] | None:
    if not identity_fields:
        return None
    for obj in iter_dicts(value):
        if all(field in desired and obj.get(field) == desired[field] for field in identity_fields):
            return obj
    return None


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


def read_state(state_dir: Path, key: str) -> dict[str, Any] | None:
    if state_dir.is_symlink() or (state_dir.exists() and not state_dir.is_dir()):
        raise ApplyError(f"apply state directory must be a real directory: {state_dir}")
    path = state_path(state_dir, key)
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise ApplyError(f"apply state must be a regular, non-symlink file: {path}")
    if path.stat().st_mode & 0o777 != 0o600:
        raise ApplyError(f"apply state must have mode 600: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ApplyError(f"apply state is unreadable or corrupt: {path}") from exc
    if not isinstance(value, dict):
        raise ApplyError(f"apply state has an invalid schema: {path}")
    return value


def write_state(state_dir: Path, key: str, value: dict[str, Any]) -> None:
    if state_dir.is_symlink() or (state_dir.exists() and not state_dir.is_dir()):
        raise ApplyError(f"apply state directory must be a real directory: {state_dir}")
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    state_dir.chmod(0o700)
    path = state_path(state_dir, key)
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
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def ensure_create(args: argparse.Namespace, token: str) -> str:
    desired = substituted_payload(args)
    desired_digest = payload_digest(desired)
    identity_fields = parse_csv(args.identity_fields)
    id_keys = parse_csv(args.id_keys) or DEFAULT_ID_KEYS
    state_dir = Path(args.state_dir)
    _, before = api_request("GET", args.collection_path, token, args.account_group_id)

    previous = read_state(state_dir, args.key)
    if previous is not None:
        previous_id = str(previous.get("id", "")).strip()
        if not previous_id:
            raise ApplyError(f"state for {args.key} has no retained object ID")
        previous_digest = str(previous.get("payload_sha256", "")).strip()
        if not previous_digest:
            raise ApplyError(
                f"state for {args.key} predates payload fingerprinting; reconcile it before retrying"
            )
        if previous_digest != desired_digest:
            raise ApplyError(
                f"rendered payload for {args.key} changed after create; no update schema is encoded"
            )
        found = find_by_id(before, previous_id, id_keys)
        if found is None:
            raise ApplyError(
                f"retained object ID {previous_id!r} is absent from live readback; refusing a duplicate create"
            )
        matched = find_by_identity([found], desired, identity_fields)
        if identity_fields and matched is None:
            raise ApplyError(
                f"retained object ID {previous_id!r} no longer matches rendered identity fields; review drift before retrying"
            )
        write_state(
            state_dir,
            args.key,
            {"id": previous_id, "payload_sha256": desired_digest, "verified_exists": True},
        )
        print(f"SKIPPED {args.key}: retained live ID {previous_id} exists", file=sys.stderr)
        return previous_id

    existing = find_by_identity(before, desired, identity_fields)
    if existing is not None:
        existing_id = object_id(existing, id_keys)
        if not existing_id:
            raise ApplyError(
                f"live object matches {args.key} identity but exposes no usable ID; refusing a duplicate create"
            )
        write_state(
            state_dir,
            args.key,
            {"id": existing_id, "payload_sha256": desired_digest, "verified_exists": True},
        )
        print(f"SKIPPED {args.key}: adopted existing live object {existing_id}", file=sys.stderr)
        return existing_id

    _, created = api_request(
        "POST", args.create_path, token, args.account_group_id, desired
    )
    created_id = extract_id(created, id_keys)
    if created_id:
        # Retain the ID before the follow-up GET. If readback is temporarily
        # unavailable, a retry will fail closed instead of issuing another POST.
        write_state(
            state_dir,
            args.key,
            {"id": created_id, "payload_sha256": desired_digest, "verified_exists": False},
        )

    _, after = api_request("GET", args.collection_path, token, args.account_group_id)
    live = find_by_id(after, created_id, id_keys) if created_id else None
    if live is None:
        live = find_by_identity(after, desired, identity_fields)
    if live is None:
        raise ApplyError(
            f"create for {args.key} returned success but collection readback did not expose the object"
        )
    live_id = object_id(live, id_keys) or created_id
    if not live_id:
        raise ApplyError(f"created {args.key} is visible but exposes no usable object ID")
    write_state(
        state_dir,
        args.key,
        {"id": live_id, "payload_sha256": desired_digest, "verified_exists": True},
    )
    print(f"CREATED {args.key}: live ID {live_id} verified by collection readback", file=sys.stderr)
    return live_id


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
    state_dir = Path(args.state_dir)
    previous = read_state(state_dir, args.key)
    if previous is not None:
        api_request("GET", args.readback_path, token, args.account_group_id)
        print(f"SKIPPED {args.key}: prior action and readback retained", file=sys.stderr)
        return args.key
    api_request("GET", args.readback_path, token, args.account_group_id)
    api_request("POST", args.action_path, token, args.account_group_id, {})
    api_request("GET", args.readback_path, token, args.account_group_id)
    write_state(state_dir, args.key, {"readback": args.readback_path, "converged": True})
    print(f"APPLIED {args.key}: follow-up resource read succeeded", file=sys.stderr)
    return args.key


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

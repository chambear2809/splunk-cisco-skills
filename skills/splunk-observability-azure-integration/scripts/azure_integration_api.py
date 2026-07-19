#!/usr/bin/env python3
"""Splunk Observability Cloud /v2/integration client for Azure (type=Azure).

Key conventions:
- Base URL: https://api.<realm>.observability.splunkcloud.com/v2
- Read-only GET auth: API-scoped organization token or administrator session/User
  API access token; POST/PUT/DELETE require the administrator session/User token
- appId / secretKey: read from chmod-600 files; never passed as CLI flags
- Only GET retries {429, 502, 503, 504}; each mutation dispatches once
- PUT body strips read-back fields (created, lastUpdated, creator, lastUpdatedBy, id)
- appId + secretKey are omitted on GET by the Splunk API; drift detection uses
  SHA-256 hash comparison vs state/credential-hashes.json
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import hmac
import http.client
import importlib
import json
import math
import os
import pwd
import random
import re
import stat
import sys
import time
import urllib.parse
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


def _load_provider_apply_state() -> Any:
    """Load only this client's verified sibling helper under a unique name."""
    module_name = (
        "skills.splunk-observability-azure-integration.scripts._apply_state"
    )
    try:
        client_path = Path(__file__).resolve(strict=True)
        helper_path = client_path.with_name("_apply_state.py")
        initial_metadata = helper_path.lstat()
        resolved_helper = helper_path.resolve(strict=True)
        repository_root = client_path.parents[3]
    except (OSError, RuntimeError) as exc:
        raise ImportError("Azure apply-state helper is unavailable") from exc
    if (
        stat.S_ISLNK(initial_metadata.st_mode)
        or not stat.S_ISREG(initial_metadata.st_mode)
        or resolved_helper.parent != client_path.parent
        or repository_root
        / "skills"
        / "splunk-observability-azure-integration"
        / "scripts"
        / "azure_integration_api.py"
        != client_path
    ):
        raise ImportError("Azure apply-state helper is not a verified sibling file")

    root_entry = os.fspath(repository_root)
    if not sys.path or sys.path[0] != root_entry:
        sys.path.insert(0, root_entry)

    def verify_origin(module: Any) -> None:
        try:
            module_path = Path(module.__file__)
            module_metadata = module_path.lstat()
            module_origin = module_path.resolve(strict=True)
            spec_origin = Path(module.__spec__.origin).resolve(strict=True)
            current_metadata = helper_path.lstat()
        except (AttributeError, OSError, RuntimeError, TypeError) as exc:
            raise ImportError("Azure apply-state helper origin is invalid") from exc
        initial_identity = (
            initial_metadata.st_dev,
            initial_metadata.st_ino,
            initial_metadata.st_mode,
        )
        current_identity = (
            current_metadata.st_dev,
            current_metadata.st_ino,
            current_metadata.st_mode,
        )
        if (
            stat.S_ISLNK(module_metadata.st_mode)
            or not stat.S_ISREG(module_metadata.st_mode)
            or stat.S_ISLNK(current_metadata.st_mode)
            or not stat.S_ISREG(current_metadata.st_mode)
            or module_origin != resolved_helper
            or spec_origin != resolved_helper
            or current_identity != initial_identity
        ):
            raise ImportError("Azure apply-state helper has the wrong origin")

    existing = sys.modules.get(module_name)
    if existing is not None:
        verify_origin(existing)
    try:
        module = importlib.import_module(module_name)
    except (ImportError, OSError, RuntimeError) as exc:
        raise ImportError("Azure apply-state helper could not be loaded") from exc
    verify_origin(module)
    return module


_apply_state = _load_provider_apply_state()
SecureDirectory = _apply_state.SecureDirectory
append_step = _apply_state.append_step
claim_rollback_attempt = _apply_state.claim_rollback_attempt
contains_high_confidence_secret = _apply_state.contains_high_confidence_secret
is_high_confidence_secret_key = _apply_state.is_high_confidence_secret_key
open_secure_lock_file = _apply_state.open_secure_lock_file
read_private_file_bytes = _apply_state.read_private_file_bytes
read_secret_file = _apply_state.read_secret_file
read_secret_file_material = _apply_state.read_secret_file_material
redact = _apply_state.redact
secure_private_directory = _apply_state.secure_private_directory
write_private_json = _apply_state.write_private_json


_RETRYABLE_STATUSES = {429, 502, 503, 504}
SUPPORTED_REALMS = frozenset(
    {"us0", "us1", "us2", "us3", "eu0", "eu1", "eu2", "au0", "jp0", "sg0"}
)
PLAN_SCHEMA_VERSION = 3
OBSERVED_SCHEMA_VERSION = 1
MAX_OBSERVED_BYTES = 4 * 1024 * 1024
PLAN_FIELDS = frozenset(
    {
        "schema_version",
        "plan_id",
        "provider",
        "realm",
        "action",
        "integration_id",
        "integration_name",
        "expected_enabled_state",
        "observed_at",
        "reviewed_state",
        "reviewed_state_sha256",
    }
)
AZURE_CREDENTIAL_BINDING_FIELDS = frozenset({"app_id_sha256", "secret_key_sha256"})
POSTCONDITION_ATTEMPTS = 5
POSTCONDITION_DELAY_SECONDS = 0.2
MAX_RETRY_DELAY_SECONDS = 30.0
MAX_GET_ATTEMPTS = 10
INTEGRATION_API_CAP = 10_000
MAX_PLAN_BYTES = 64 * 1024
_SERVER_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~-]{0,255}$")
_FORBIDDEN_PERCENT_ESCAPE = re.compile(r"%(?:40|2f|3f|23|20|09|0d|0a|5c|3a)", re.IGNORECASE)
_ROLLBACK_CAPABILITY = object()

# Fields the Splunk API returns on GET but that must be stripped before PUT.
READ_BACK_FIELDS: tuple[str, ...] = (
    "created", "lastUpdated", "creator", "lastUpdatedBy",
    "lastUpdatedByName", "createdByName", "id",
)

# Fields omitted on GET that must be reconstructed; local hash comparison is needed.
CREDENTIAL_FIELDS: tuple[str, ...] = ("appId", "secretKey")
REVIEWED_ROOT_FIELDS = frozenset(
    {
        "id",
        "name",
        "type",
        "enabled",
        "tenantId",
        "azureEnvironment",
        "subscriptions",
        "pollRate",
        "useBatchApi",
        "importAzureMonitor",
        "syncGuestOsNamespaces",
        "services",
        "additionalServices",
        "customNamespacesPerService",
        "resourceFilterRules",
        "namedToken",
        "created",
        "lastUpdated",
        "creator",
        "lastUpdatedBy",
        "lastUpdatedByName",
        "createdByName",
    }
)


class ApiError(Exception):
    """Raised when an API call fails."""


class AmbiguousMutationError(ApiError):
    """Raised when a single mutation attempt has an uncertain outcome."""


class ProtocolResponseError(ApiError):
    """Raised when a dispatched mutation returns an invalid response object."""


class _ReviewedStateSource(Enum):
    LIVE_RESPONSE = auto()
    OUTBOUND_REQUEST = auto()
    PROJECTED_ARTIFACT = auto()


class _NoRedirectHandler(HTTPRedirectHandler):
    """Refuse redirects so the authentication header cannot move hosts."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201
        return None


def validate_realm(realm: str) -> str:
    """Return a reviewed realm or fail before any credential read."""
    if (
        not isinstance(realm, str)
        or realm not in SUPPORTED_REALMS
        or any(character.isspace() for character in realm)
        or any(character in realm for character in "@/:?#%\\")
    ):
        raise ApiError(
            f"unsupported Splunk Observability realm {realm!r}; allowed: "
            f"{', '.join(sorted(SUPPORTED_REALMS))}"
        )
    return realm


def _validate_api_url(url: str) -> None:
    """Validate the final parsed authenticated destination and API path."""
    if any(character.isspace() for character in url) or _FORBIDDEN_PERCENT_ESCAPE.search(url):
        raise ApiError("Splunk Observability API URL contains whitespace or encoded delimiters")
    parsed = urllib.parse.urlsplit(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ApiError("Splunk Observability API URL contains an invalid port") from exc
    allowed_hosts = {
        f"api.{realm}.observability.splunkcloud.com" for realm in SUPPORTED_REALMS
    }
    if (
        parsed.scheme != "https"
        or parsed.hostname not in allowed_hosts
        or parsed.netloc != parsed.hostname
        or port is not None
        or parsed.username is not None
        or parsed.password is not None
        or "@" in parsed.netloc
        or parsed.fragment
    ):
        raise ApiError(
            "authenticated Splunk Observability requests require an allowlisted "
            "HTTPS API host with no userinfo, explicit port, fragment, or redirect"
        )

    path_parts = parsed.path.split("/")
    valid_path = parsed.path == "/v2/integration"
    if len(path_parts) == 4 and path_parts[:3] == ["", "v2", "integration"]:
        valid_path = bool(_SERVER_ID_PATTERN.fullmatch(path_parts[3]))
    if not valid_path:
        raise ApiError("Splunk Observability API URL has an unreviewed path")

    if parsed.query:
        if parsed.path != "/v2/integration":
            raise ApiError("Splunk Observability API query is allowed only on the list endpoint")
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
        if set(query) != {"type", "limit", "offset"} or any(len(values) != 1 for values in query.values()):
            raise ApiError("Splunk Observability API URL has unreviewed query parameters")
        if query["type"] != ["Azure"]:
            raise ApiError("Splunk Observability API list query must be type=Azure")
        for key in ("limit", "offset"):
            if not query[key][0].isdigit():
                raise ApiError("Splunk Observability API pagination values must be decimal integers")


def _max_retries() -> int:
    raw = os.environ.get("O11Y_MAX_RETRIES")
    if raw is None:
        return 4
    try:
        return min(MAX_GET_ATTEMPTS, max(1, int(raw)))
    except ValueError:
        return 4


def _retry_after(exc: HTTPError, attempt: int) -> float:
    ra = exc.headers.get("Retry-After") if exc.headers else None
    if ra:
        try:
            parsed = float(ra)
            if math.isfinite(parsed) and parsed >= 0:
                return min(MAX_RETRY_DELAY_SECONDS, parsed)
        except (TypeError, ValueError):
            pass
    return min(MAX_RETRY_DELAY_SECONDS, (2.0 ** attempt) + random.random())


def _request(method: str, url: str, token: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    method = method.upper()
    _validate_api_url(url)
    headers = {
        "X-SF-Token": token,
        "Accept": "application/json",
        "User-Agent": "splunk-observability-azure-integration/1 (+splunk-cisco-skills)",
    }
    data: bytes | None = None
    if body is not None:
        try:
            data = json.dumps(body, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError, UnicodeEncodeError) as exc:
            raise ApiError(
                f"{method} request body is not strict UTF-8 JSON; body suppressed"
            ) from exc
        headers["Content-Type"] = "application/json"

    req = Request(url, data=data, headers=headers, method=method)
    opener = build_opener(_NoRedirectHandler())
    max_attempts = _max_retries() if method == "GET" else 1
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            response = opener.open(req, timeout=60)
        except HTTPError as exc:
            last_exc = exc
            if method == "GET" and exc.code in _RETRYABLE_STATUSES and attempt < max_attempts - 1:
                time.sleep(_retry_after(exc, attempt))
                continue
            request_id = ""
            if exc.headers:
                request_id = exc.headers.get("X-Request-Id") or ""
            suffix = f" (request-id {request_id})" if request_id else ""
            if method != "GET":
                raise AmbiguousMutationError(
                    f"single {method} attempt returned HTTP {exc.code}{suffix}; "
                    "response body suppressed"
                ) from exc
            raise ApiError(
                f"{method} {url} -> HTTP {exc.code}{suffix}; response body suppressed"
            ) from exc
        except (URLError, TimeoutError, http.client.HTTPException, OSError) as exc:
            last_exc = exc
            if method == "GET" and attempt < max_attempts - 1:
                time.sleep(min(MAX_RETRY_DELAY_SECONDS, (2.0 ** attempt) + random.random()))
                continue
            if method != "GET":
                raise AmbiguousMutationError(
                    f"single {method} transport outcome is ambiguous; response detail suppressed"
                ) from exc
            raise ApiError(f"{method} {url} -> transport failure: {exc}") from exc

        try:
            with response as resp:
                status = getattr(resp, "status", None)
                if status is None:
                    status = resp.getcode()
                if status != 200:
                    if method != "GET":
                        raise AmbiguousMutationError(
                            f"single {method} attempt returned HTTP {status}; "
                            "response body suppressed"
                        )
                    raise ApiError(f"{method} {url} -> HTTP {status}; response body suppressed")
                raw = resp.read()
        except AmbiguousMutationError:
            raise
        except (TimeoutError, http.client.HTTPException, OSError) as exc:
            last_exc = exc
            if method == "GET" and attempt < max_attempts - 1:
                time.sleep(min(MAX_RETRY_DELAY_SECONDS, (2.0 ** attempt) + random.random()))
                continue
            if method != "GET":
                raise AmbiguousMutationError(
                    f"single {method} response outcome is ambiguous; response detail suppressed"
                ) from exc
            raise ApiError(f"{method} {url} -> response transport failure: {exc}") from exc

        if method == "DELETE":
            if raw:
                raise AmbiguousMutationError(
                    "single DELETE response unexpectedly contained a body; response body suppressed"
                )
            return {}
        if not raw:
            return {}
        try:
            parsed = _strict_json_loads(raw, label=f"{method} integration API response")
            if not isinstance(parsed, dict):
                raise ApiError(f"{method} integration API response must be a JSON object")
        except ApiError as exc:
            if method != "GET":
                raise AmbiguousMutationError(
                    f"single {method} response could not be trusted; response body suppressed"
                ) from exc
            raise
        return parsed
    raise ApiError(f"{method} {url} exhausted retries: {last_exc}")


def _base_url(realm: str) -> str:
    validated = validate_realm(realm)
    url = f"https://api.{validated}.observability.splunkcloud.com/v2"
    _validate_api_url(f"{url}/integration")
    return url


def _validate_cli_destinations(realm: str, integration_id: str = "") -> None:
    """Validate every destination derivable from CLI input before token reads."""
    base = _base_url(realm)
    query = urllib.parse.urlencode({"type": "Azure", "limit": 100, "offset": 0})
    _validate_api_url(f"{base}/integration?{query}")
    if integration_id:
        _validate_api_url(f"{base}/integration/{_validate_server_id(integration_id)}")


def _validate_server_id(integration_id: str) -> str:
    if not isinstance(integration_id, str) or not _SERVER_ID_PATTERN.fullmatch(integration_id):
        raise ApiError("integration ID must be a non-empty server-assigned opaque ID")
    return integration_id


def _validate_exact_name(name: Any) -> str:
    if (
        not isinstance(name, str)
        or not name
        or name.strip() != name
        or len(name) > 512
        or any(ord(character) < 0x20 for character in name)
    ):
        raise ApiError("integration name must be one exact non-empty canonical string")
    return name


def _strip_read_back(integration: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in integration.items() if k not in READ_BACK_FIELDS}


# ---------------------------------------------------------------------------
# Credential hash helpers.
# ---------------------------------------------------------------------------


def _sha256_file(path: str) -> str:
    p = Path(path)
    try:
        p.lstat()
    except FileNotFoundError:
        return ""
    try:
        raw = read_private_file_bytes(p, label="credential file")
    except (OSError, PermissionError, ValueError) as exc:
        raise ApiError(str(exc)) from exc
    return hashlib.sha256(raw).hexdigest()


def _load_cred_hashes(state_dir: Path) -> dict[str, str]:
    p = state_dir / "credential-hashes.json"
    try:
        p.lstat()
    except FileNotFoundError:
        return {}
    try:
        raw = read_private_file_bytes(
            p, max_bytes=64 * 1024, label="credential hash state"
        )
        payload = _strict_json_loads(raw, label=f"credential hash state {p}")
    except (OSError, PermissionError, ValueError) as exc:
        raise ApiError(f"credential hash state is unreadable or invalid: {p}: {exc}") from exc
    return _validate_cred_hash_state(payload)


def _validate_cred_hash_state(payload: Any) -> dict[str, str]:
    expected_fields = {"app_id_sha256", "secret_sha256"}
    if not isinstance(payload, dict) or set(payload) != expected_fields:
        raise ApiError("credential hash state schema mismatch")
    for field in expected_fields:
        digest = payload[field]
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ApiError(
                f"credential hash state {field} must be a lowercase SHA-256"
            )
    return payload


def _save_cred_hashes(state_dir: Path, hashes: dict[str, str]) -> None:
    p = state_dir / "credential-hashes.json"
    validated = _validate_cred_hash_state(hashes)
    try:
        write_private_json(p, validated, redact_value=False)
    except (OSError, PermissionError, ValueError) as exc:
        raise ApiError(str(exc)) from exc


def check_credential_drift(
    state_dir: Path,
    app_id_file: str,
    secret_file: str,
) -> list[str]:
    """Compare local file hashes vs stored hashes. Returns warnings on mismatch."""
    stored = _load_cred_hashes(state_dir)
    warnings: list[str] = []
    for field, path in (("app_id_sha256", app_id_file), ("secret_sha256", secret_file)):
        if not path:
            continue
        current = _sha256_file(path)
        saved = stored.get(field, "")
        if saved and saved != current:
            warnings.append(
                f"credential drift: {field} hash changed since last apply "
                f"(last={saved[:12]}... current={current[:12]}...). Re-apply to update."
            )
    return warnings


# ---------------------------------------------------------------------------
# Public API operations.
# ---------------------------------------------------------------------------


def list_azure_integrations(realm: str, token: str) -> list[dict[str, Any]]:
    """Return complete Azure coverage using bounded offset pagination."""
    limit = 100
    offset = 0
    collected: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    advertised_total: int | None = None
    for _page_number in range(100):
        query = urllib.parse.urlencode({"type": "Azure", "limit": limit, "offset": offset})
        response = _request("GET", f"{_base_url(realm)}/integration?{query}", token)
        if not isinstance(response, dict) or set(response) != {"count", "results"}:
            raise ApiError(
                "GET /integration requires the official count/results pagination envelope"
            )
        page = response["results"]
        page_total = response["count"]
        if type(page_total) is not int or page_total < 0:
            raise ApiError("GET /integration returned an invalid total count")
        if not isinstance(page, list) or not all(isinstance(item, dict) for item in page):
            raise ApiError("GET /integration returned a malformed integration page")
        if page_total is not None and page_total >= INTEGRATION_API_CAP:
            raise ApiError("GET /integration reached the ambiguous documented 10,000 cap")
        if advertised_total is None:
            advertised_total = page_total
        elif page_total is not None and page_total != advertised_total:
            raise ApiError("GET /integration changed its total count during pagination")

        for item in page:
            if item.get("type") != "Azure":
                raise ApiError("GET /integration type filter returned a non-Azure object")
            integration_id = _validate_server_id(item.get("id"))
            _validate_exact_name(item.get("name"))
            _project_live_reviewed_state(item)
            if integration_id in seen_ids:
                raise ApiError(f"GET /integration repeated integration ID {integration_id!r}")
            seen_ids.add(integration_id)
            collected.append(item)

        if not page and offset < advertised_total:
            raise ApiError("GET /integration stopped before complete advertised coverage")
        previous_offset = offset
        offset += len(page)
        if offset <= previous_offset and offset < advertised_total:
            raise ApiError("GET /integration pagination made no progress")
        if offset > advertised_total:
            raise ApiError("GET /integration returned more records than advertised")
        if offset == advertised_total:
            break
    else:
        raise ApiError("GET /integration exceeded the 100-page safety bound")
    if len(collected) != advertised_total:
        raise ApiError("GET /integration did not provide complete advertised coverage")
    return collected


def resolve_legacy_name(realm: str, token: str, name: str) -> dict[str, Any]:
    """Read-only exact legacy-name resolver; never used implicitly for mutation."""
    _validate_exact_name(name)
    integrations = list_azure_integrations(realm, token)
    _require_name_decision_coverage(integrations)
    matches = [item for item in integrations if item.get("name") == name]
    if not matches:
        raise ApiError(f"no Azure integration exactly matches legacy name {name!r}")
    if len(matches) != 1:
        raise ApiError(f"multiple Azure integrations exactly match legacy name {name!r}")
    _validate_server_id(matches[0].get("id"))
    return matches[0]


def _require_name_decision_coverage(integrations: list[dict[str, Any]]) -> None:
    if len(integrations) >= INTEGRATION_API_CAP:
        raise ApiError(
            "cannot prove exact-name uniqueness at the documented 10,000 integration cap"
        )


def get_integration(realm: str, token: str, integration_id: str) -> dict[str, Any]:
    integration_id = _validate_server_id(integration_id)
    url = f"{_base_url(realm)}/integration/{integration_id}"
    response = _request("GET", url, token)
    if not isinstance(response, dict):
        raise ApiError("GET /integration/{id} returned a malformed response")
    if response:
        _project_live_reviewed_state(response)
    return response


def create_integration(realm: str, token: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{_base_url(realm)}/integration"
    wire = _strip_read_back(payload)
    _project_outbound_reviewed_state(wire)
    return _request("POST", url, token, wire)


def update_integration(
    realm: str,
    token: str,
    integration_id: str,
    payload: dict[str, Any],
    *,
    _capability: object | None = None,
) -> dict[str, Any]:
    if "enabled" not in payload or type(payload["enabled"]) is not bool:
        raise ApiError(
            "integration update requires an explicit Boolean enabled field; "
            "use reviewed rollback to disable"
        )
    if payload.get("enabled") is False and _capability is not _ROLLBACK_CAPABILITY:
        raise ApiError("refusing disabling PUT; use the reviewed rollback plan workflow")
    integration_id = _validate_server_id(integration_id)
    url = f"{_base_url(realm)}/integration/{integration_id}"
    wire = _strip_read_back(payload)
    _project_outbound_reviewed_state(wire)
    return _request("PUT", url, token, wire)


def delete_integration(
    realm: str,
    token: str,
    integration_id: str,
    *,
    _capability: object | None = None,
) -> dict[str, Any]:
    """Issue one gated DELETE attempt; direct Python rollback bypass is refused."""
    if _capability is not _ROLLBACK_CAPABILITY:
        raise ApiError("direct delete is disabled; use the reviewed rollback plan workflow")
    integration_id = _validate_server_id(integration_id)
    url = f"{_base_url(realm)}/integration/{integration_id}"
    return _request("DELETE", url, token)


def disable_integration(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    """Refuse the legacy ungated GET+PUT rollback entry point."""
    raise ApiError("direct disable is disabled; use the reviewed rollback plan workflow")


# ---------------------------------------------------------------------------
# Rollback plan, locking, and exact-ID mutation.
# ---------------------------------------------------------------------------


def _canonical_plan_bytes(plan: dict[str, Any]) -> bytes:
    return json.dumps(
        plan,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _strict_json_loads(raw: bytes, *, label: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        document: dict[str, Any] = {}
        for key, value in pairs:
            if key in document:
                raise ValueError(f"duplicate JSON object key {key!r}")
            document[key] = value
        return document

    def reject_constant(value: str) -> Any:
        raise ValueError(f"non-standard JSON constant {value!r}")

    try:
        return json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ApiError(f"{label} is not valid UTF-8 JSON (strict parsing required): {exc}") from exc


def _validate_reviewed_root_shape(value: dict[str, Any]) -> None:
    string_fields = {
        "id",
        "name",
        "type",
        "tenantId",
        "azureEnvironment",
        "namedToken",
        "creator",
        "lastUpdatedBy",
    }
    nullable_name_fields = {"createdByName", "lastUpdatedByName"}
    boolean_fields = {
        "enabled",
        "useBatchApi",
        "importAzureMonitor",
        "syncGuestOsNamespaces",
    }
    list_fields = {"subscriptions", "services", "additionalServices"}
    for field in string_fields & value.keys():
        if not isinstance(value[field], str):
            raise ApiError("reviewed state response schema mismatch")
    for field in boolean_fields & value.keys():
        if type(value[field]) is not bool:
            raise ApiError("reviewed state response schema mismatch")
    for field in nullable_name_fields & value.keys():
        if value[field] is not None and not isinstance(value[field], str):
            raise ApiError("reviewed state response schema mismatch")
    for field in {"created", "lastUpdated"} & value.keys():
        if type(value[field]) is not int:
            raise ApiError("reviewed state response schema mismatch")
    if "pollRate" in value and type(value["pollRate"]) is not int:
        raise ApiError("reviewed state response schema mismatch")
    for field in list_fields & value.keys():
        if not isinstance(value[field], list) or not all(
            isinstance(item, str) for item in value[field]
        ):
            raise ApiError("reviewed state response schema mismatch")
    if "customNamespacesPerService" in value:
        namespaces = value["customNamespacesPerService"]
        if not isinstance(namespaces, dict) or not all(
            isinstance(service, str)
            and service
            and isinstance(items, list)
            and all(isinstance(item, str) for item in items)
            for service, items in namespaces.items()
        ):
            raise ApiError("reviewed state response schema mismatch")
    if "resourceFilterRules" in value:
        rules = value["resourceFilterRules"]
        if not isinstance(rules, list) or not all(
            isinstance(rule, dict) for rule in rules
        ):
            raise ApiError("reviewed state response schema mismatch")


def _validate_disable_reviewed_state(value: dict[str, Any]) -> None:
    if value.get("azureEnvironment") not in {"AZURE", "AZURE_US_GOVERNMENT"}:
        raise ApiError("Azure disable requires a supported azureEnvironment")
    poll_rate = value.get("pollRate")
    if type(poll_rate) is not int or not 60_000 <= poll_rate <= 600_000:
        raise ApiError("Azure disable requires pollRate between 60000 and 600000 ms")


def _walk_reviewed_state(
    value: Any,
    *,
    source: _ReviewedStateSource,
    _path: tuple[str, ...] = (),
) -> Any:
    """Project Azure state through an explicit response/request/artifact boundary."""
    if not isinstance(source, _ReviewedStateSource):
        raise ApiError("reviewed state source mode is invalid")
    if isinstance(value, dict):
        projected: dict[str, Any] = {}
        if not _path:
            unknown = set(value) - REVIEWED_ROOT_FIELDS - set(CREDENTIAL_FIELDS)
            if unknown:
                raise ApiError("reviewed state response schema mismatch")
            _validate_reviewed_root_shape(value)
        elif _path == ("resourceFilterRules", "*"):
            if set(value) != {"filter"} or not isinstance(value["filter"], dict):
                raise ApiError("reviewed state response schema mismatch")
        elif _path == ("resourceFilterRules", "*", "filter"):
            if set(value) != {"source"} or not isinstance(value["source"], str):
                raise ApiError("reviewed state response schema mismatch")
        elif _path != ("customNamespacesPerService",):
            raise ApiError("reviewed state response schema mismatch")
        for key, item in value.items():
            if not isinstance(key, str):
                raise ApiError("reviewed state is not strict JSON")
            if not _path and key in CREDENTIAL_FIELDS:
                if source is not _ReviewedStateSource.OUTBOUND_REQUEST:
                    raise ApiError(
                        "reviewed state contains response-side credential material"
                    )
                if not isinstance(item, str) or not item:
                    raise ApiError("outbound Azure credentials must be non-empty strings")
                continue
            if is_high_confidence_secret_key(key):
                raise ApiError(
                    "reviewed state contains unexpected credential material"
                )
            if not _path and key in {"id", "name", "type"}:
                projected[key] = item
                continue
            projected[key] = _walk_reviewed_state(
                item,
                source=source,
                _path=(*_path, key),
            )
        return projected
    if isinstance(value, list):
        return [
            _walk_reviewed_state(
                item,
                source=source,
                _path=(*_path, "*"),
            )
            for item in value
        ]
    if isinstance(value, str):
        if contains_high_confidence_secret(value):
            raise ApiError("reviewed state contains unexpected credential material")
        return value
    if type(value) is float and not math.isfinite(value):
        raise ApiError("reviewed state contains a non-finite number")
    if value is None or type(value) in {bool, int, float}:
        return value
    raise ApiError("reviewed state is not strict JSON")


def _project_live_reviewed_state(value: Any) -> Any:
    return _walk_reviewed_state(value, source=_ReviewedStateSource.LIVE_RESPONSE)


def _project_outbound_reviewed_state(value: Any) -> Any:
    return _walk_reviewed_state(value, source=_ReviewedStateSource.OUTBOUND_REQUEST)


def _validate_projected_reviewed_state(value: Any) -> Any:
    projected = _walk_reviewed_state(
        value,
        source=_ReviewedStateSource.PROJECTED_ARTIFACT,
    )
    if projected != value:
        raise ApiError("reviewed state artifact is not canonical")
    return projected


def _reviewed_state_sha256(state: dict[str, Any]) -> str:
    validated = _validate_projected_reviewed_state(state)
    return hashlib.sha256(
        json.dumps(
            validated,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _validate_observed_snapshot(
    document: Any, *, expected_realm: str
) -> dict[str, Any]:
    validated_expected_realm = validate_realm(expected_realm)
    expected_fields = {
        "schema_version", "provider", "realm", "captured_at", "count", "results"
    }
    if not isinstance(document, dict) or set(document) != expected_fields:
        raise ApiError("observed snapshot schema mismatch")
    if type(document["schema_version"]) is not int or document["schema_version"] != OBSERVED_SCHEMA_VERSION:
        raise ApiError(f"observed snapshot schema_version must be {OBSERVED_SCHEMA_VERSION}")
    if document["provider"] != "Azure" or document["realm"] != validated_expected_realm:
        raise ApiError("observed snapshot provider or realm does not match rollback")
    captured_at = document["captured_at"]
    if not isinstance(captured_at, str):
        raise ApiError("observed snapshot captured_at must be an ISO-8601 timestamp")
    try:
        parsed_capture = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ApiError("observed snapshot captured_at must be an ISO-8601 timestamp") from exc
    if parsed_capture.tzinfo is None:
        raise ApiError("observed snapshot captured_at must include a timezone")
    count = document["count"]
    results = document["results"]
    if type(count) is not int or count < 0 or count >= INTEGRATION_API_CAP:
        raise ApiError("observed snapshot count is invalid or reaches the ambiguous 10,000 cap")
    if not isinstance(results, list) or len(results) != count:
        raise ApiError("observed snapshot count/results coverage is incomplete")
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    for item in results:
        if not isinstance(item, dict) or item.get("type") != "Azure":
            raise ApiError("observed snapshot contains a malformed or wrong-provider result")
        integration_id = _validate_server_id(item.get("id"))
        name = _validate_exact_name(item.get("name"))
        if integration_id in seen_ids:
            raise ApiError(f"observed snapshot repeats integration ID {integration_id!r}")
        if name in seen_names:
            raise ApiError(f"observed snapshot repeats integration name {name!r}")
        if _validate_projected_reviewed_state(item) != item:
            raise ApiError("observed snapshot must not contain credential material")
        if type(item.get("enabled")) is not bool:
            raise ApiError("observed snapshot integration enabled state must be Boolean")
        seen_ids.add(integration_id)
        seen_names.add(name)
    return document


def write_observed_snapshot(
    path: Path, *, realm: str, integrations: list[dict[str, Any]]
) -> dict[str, Any]:
    sanitized = [_project_live_reviewed_state(item) for item in integrations]
    document = {
        "schema_version": OBSERVED_SCHEMA_VERSION,
        "provider": "Azure",
        "realm": validate_realm(realm),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "count": len(sanitized),
        "results": sanitized,
    }
    snapshot = _validate_observed_snapshot(document, expected_realm=realm)
    try:
        serialized = (json.dumps(snapshot, indent=2, allow_nan=False) + "\n").encode(
            "utf-8"
        )
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ApiError("observed snapshot is not strict UTF-8 JSON") from exc
    if len(serialized) > MAX_OBSERVED_BYTES:
        raise ApiError(
            f"observed snapshot exceeds the {MAX_OBSERVED_BYTES}-byte limit"
        )
    try:
        write_private_json(path, snapshot, redact_value=False)
    except (OSError, PermissionError, ValueError) as exc:
        raise ApiError(str(exc)) from exc
    return snapshot


def load_observed_snapshot(path: Path, *, expected_realm: str) -> dict[str, Any]:
    try:
        raw = read_private_file_bytes(
            path, max_bytes=MAX_OBSERVED_BYTES, label="observed state snapshot"
        )
    except (OSError, PermissionError, ValueError) as exc:
        raise ApiError(str(exc)) from exc
    document = _strict_json_loads(raw, label=f"observed state snapshot {path}")
    return _validate_observed_snapshot(document, expected_realm=expected_realm)


def _select_reviewed_state(
    snapshot: dict[str, Any], *, integration_id: str, integration_name: str
) -> dict[str, Any]:
    matches = [item for item in snapshot["results"] if item.get("id") == integration_id]
    if len(matches) != 1:
        raise ApiError("observed snapshot must contain the exact integration ID exactly once")
    selected = matches[0]
    if selected.get("name") != integration_name or selected.get("type") != "Azure":
        raise ApiError("observed snapshot target type/name does not match rollback flags")
    return selected


def _validate_rollback_plan(plan: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise ApiError("rollback plan must be a JSON object")
    action = plan.get("action")
    allowed_fields = PLAN_FIELDS | ({"credential_binding"} if action == "disable" else set())
    required_fields = allowed_fields
    unknown = set(plan) - allowed_fields
    missing = required_fields - set(plan)
    if unknown or missing:
        raise ApiError(
            "rollback plan schema mismatch: "
            f"missing={sorted(missing)} unknown={sorted(unknown)}"
        )
    if type(plan["schema_version"]) is not int or plan["schema_version"] != PLAN_SCHEMA_VERSION:
        raise ApiError(f"rollback plan schema_version must be {PLAN_SCHEMA_VERSION}")
    plan_id = plan["plan_id"]
    try:
        parsed_plan_id = uuid.UUID(plan_id) if isinstance(plan_id, str) else None
    except (ValueError, AttributeError):
        parsed_plan_id = None
    if (
        parsed_plan_id is None
        or parsed_plan_id.version != 4
        or str(parsed_plan_id) != plan_id
    ):
        raise ApiError("rollback plan plan_id must be a canonical lowercase UUID4")
    if plan["provider"] != "Azure":
        raise ApiError("rollback plan provider must be Azure")
    validate_realm(plan["realm"])
    if plan["action"] not in {"disable", "delete"}:
        raise ApiError("rollback plan action must be disable or delete")
    _validate_server_id(plan["integration_id"])
    _validate_exact_name(plan["integration_name"])
    if type(plan["expected_enabled_state"]) is not bool:
        raise ApiError("rollback plan expected_enabled_state must be Boolean")
    if plan["action"] == "disable" and plan["expected_enabled_state"] is not True:
        raise ApiError("disable rollback plans require expected_enabled_state=true")
    if not isinstance(plan["observed_at"], str):
        raise ApiError("rollback plan observed_at must be a timestamp")
    try:
        observed_at = datetime.fromisoformat(plan["observed_at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise ApiError("rollback plan observed_at must be an ISO-8601 timestamp") from exc
    if observed_at.tzinfo is None:
        raise ApiError("rollback plan observed_at must include a timezone")
    reviewed_state = plan["reviewed_state"]
    if (
        not isinstance(reviewed_state, dict)
        or _validate_projected_reviewed_state(reviewed_state) != reviewed_state
    ):
        raise ApiError("rollback plan reviewed_state is malformed or contains credentials")
    if (
        reviewed_state.get("id") != plan["integration_id"]
        or reviewed_state.get("type") != "Azure"
        or reviewed_state.get("name") != plan["integration_name"]
        or reviewed_state.get("enabled") is not plan["expected_enabled_state"]
    ):
        raise ApiError("rollback plan reviewed_state identity/state mismatch")
    reviewed_hash = plan["reviewed_state_sha256"]
    if (
        not isinstance(reviewed_hash, str)
        or not re.fullmatch(r"[0-9a-f]{64}", reviewed_hash)
        or not hmac.compare_digest(reviewed_hash, _reviewed_state_sha256(reviewed_state))
    ):
        raise ApiError("rollback plan reviewed_state_sha256 mismatch")
    if plan["action"] == "disable":
        _validate_disable_reviewed_state(reviewed_state)
        binding = plan["credential_binding"]
        if not isinstance(binding, dict) or set(binding) != AZURE_CREDENTIAL_BINDING_FIELDS:
            raise ApiError("Azure disable credential_binding schema mismatch")
        for field in AZURE_CREDENTIAL_BINDING_FIELDS:
            if not isinstance(binding[field], str) or not re.fullmatch(
                r"[0-9a-f]{64}", binding[field]
            ):
                raise ApiError(f"Azure credential_binding.{field} must be lowercase SHA-256")
    return plan


def rollback_plan_sha256(plan: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_plan_bytes(_validate_rollback_plan(plan))).hexdigest()


def render_rollback_plan(
    plan_path: Path,
    *,
    realm: str,
    action: str,
    integration_id: str,
    integration_name: str,
    expected_enabled_state: bool,
    observed_state_file: str = "",
    app_id_file: str = "",
    secret_file: str = "",
) -> dict[str, Any]:
    """Render a reviewable, secret-free rollback plan without network access."""
    validated_realm = validate_realm(realm)
    validated_id = _validate_server_id(integration_id)
    if action not in {"disable", "delete"}:
        raise ApiError("rollback plan action must be disable or delete")
    if action == "disable" and expected_enabled_state is not True:
        raise ApiError("disable rollback plans require expected_enabled_state=true")
    if not observed_state_file:
        raise ApiError("rollback plan render requires --observed-state-file")
    snapshot = load_observed_snapshot(
        Path(observed_state_file), expected_realm=validated_realm
    )
    reviewed_state = _select_reviewed_state(
        snapshot,
        integration_id=validated_id,
        integration_name=_validate_exact_name(integration_name),
    )
    if reviewed_state["enabled"] is not expected_enabled_state:
        raise ApiError("expected enabled state does not match the observed snapshot")
    credential_binding: dict[str, str] | None = None
    if action == "disable":
        _app_id, app_id_raw, _secret_key, secret_raw = _load_azure_credential_material(
            app_id_file, secret_file
        )
        credential_binding = {
            "app_id_sha256": hashlib.sha256(app_id_raw).hexdigest(),
            "secret_key_sha256": hashlib.sha256(secret_raw).hexdigest(),
        }
    elif app_id_file or secret_file:
        raise ApiError("delete rollback plans must not include credential files")
    document: dict[str, Any] = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "plan_id": str(uuid.uuid4()),
        "provider": "Azure",
        "realm": validated_realm,
        "action": action,
        "integration_id": validated_id,
        "integration_name": integration_name,
        "expected_enabled_state": expected_enabled_state,
        "observed_at": snapshot["captured_at"],
        "reviewed_state": reviewed_state,
        "reviewed_state_sha256": _reviewed_state_sha256(reviewed_state),
    }
    if credential_binding is not None:
        document["credential_binding"] = credential_binding
    plan = _validate_rollback_plan(
        document
    )
    try:
        serialized = (json.dumps(plan, indent=2, allow_nan=False) + "\n").encode(
            "utf-8"
        )
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ApiError("rollback plan is not strict UTF-8 JSON") from exc
    if len(serialized) > MAX_PLAN_BYTES:
        raise ApiError(f"rollback plan exceeds the {MAX_PLAN_BYTES}-byte limit")
    if plan_path.is_symlink():
        raise ApiError(f"rollback plan path must not be a symlink: {plan_path}")
    try:
        write_private_json(plan_path, plan, redact_value=False)
    except (OSError, PermissionError, ValueError) as exc:
        raise ApiError(str(exc)) from exc
    return {"plan": plan, "plan_hash": rollback_plan_sha256(plan), "plan_file": str(plan_path)}


def _load_private_plan(path: Path) -> dict[str, Any]:
    try:
        raw = read_private_file_bytes(
            path,
            max_bytes=MAX_PLAN_BYTES,
            label="rollback plan",
        )
    except (OSError, PermissionError, ValueError) as exc:
        raise ApiError(
            f"rollback plan must be a stable owned single-hardlink mode-0600 file: {exc}"
        ) from exc
    document = _strict_json_loads(raw, label=f"rollback plan {path}")
    return _validate_rollback_plan(document)


def load_rollback_plan(path: Path, expected_sha256: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256 or ""):
        raise ApiError("--plan-hash must be exactly 64 hexadecimal characters")
    plan = _load_private_plan(path)
    actual = rollback_plan_sha256(plan)
    if not hmac.compare_digest(actual, expected_sha256.lower()):
        raise ApiError("rollback plan SHA-256 mismatch; render and review a fresh plan")
    return plan


def _account_lock_root_path() -> Path:
    """Return a caller-environment-independent lock root for the real uid."""
    if not hasattr(os, "getuid"):
        raise ApiError("secure rollback locking requires a Unix uid")
    account = pwd.getpwuid(os.getuid())
    home = Path(account.pw_dir)
    if not home.is_absolute():
        raise ApiError("account home from uid lookup must be absolute")
    return home / ".local" / "state" / "splunk-cisco-skills" / "integration-rollback-locks"


@contextmanager
def _account_scoped_lock(namespace: str, realm: str, value: str):
    """Hold a canonical per-account lock in a caller-independent directory."""
    if namespace not in {"target", "name"}:
        raise ApiError("invalid canonical integration lock namespace")
    realm = validate_realm(realm)
    if not isinstance(value, str) or not value:
        raise ApiError("canonical integration lock value must be a non-empty string")
    lock_dir = _account_lock_root_path()
    lock_identity = f"Azure:{namespace}:{realm}:{value}".encode("utf-8")
    lock_name = hashlib.sha256(lock_identity).hexdigest() + ".lock"
    lock_path = lock_dir / lock_name
    manager = secure_private_directory(lock_dir)
    directory: SecureDirectory | None = None
    descriptor: int | None = None
    try:
        directory = manager.__enter__()
        directory_metadata = os.fstat(directory.fd)
        current_uid = os.getuid()
        if (
            directory_metadata.st_uid != current_uid
            or stat.S_IMODE(directory_metadata.st_mode) != 0o700
        ):
            raise ApiError(
                f"canonical rollback lock root must be owned mode 0700: {lock_dir}"
            )
        lock_path = directory.path / lock_name
        descriptor = open_secure_lock_file(
            directory, lock_name, label=f"{namespace} integration lock"
        )
        fcntl.flock(descriptor, fcntl.LOCK_EX)
    except ApiError:
        if descriptor is not None:
            os.close(descriptor)
        if directory is not None:
            manager.__exit__(None, None, None)
        raise
    except PermissionError as exc:
        if descriptor is not None:
            os.close(descriptor)
        if directory is not None:
            manager.__exit__(None, None, None)
        raise ApiError(str(exc)) from exc
    except (OSError, ValueError) as exc:
        if descriptor is not None:
            os.close(descriptor)
        if directory is not None:
            manager.__exit__(None, None, None)
        raise ApiError(f"could not acquire secure integration lock: {lock_path}") from exc
    assert directory is not None and descriptor is not None
    try:
        yield directory
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)
            manager.__exit__(None, None, None)


@contextmanager
def _target_lock(realm: str, integration_id: str):
    """Hold a secure lock keyed only by the exact server-assigned target ID."""
    integration_id = _validate_server_id(integration_id)
    with _account_scoped_lock("target", realm, integration_id) as directory:
        yield directory


@contextmanager
def _name_lock(realm: str, integration_name: str):
    """Serialize the local exact-name list/update/create decision."""
    if not isinstance(integration_name, str) or not integration_name:
        raise ApiError("integration name lock requires a non-empty exact name")
    _validate_exact_name(integration_name)
    with _account_scoped_lock("name", realm, integration_name):
        yield


def _visible_fingerprint(
    integration: dict[str, Any], *, source: _ReviewedStateSource
) -> str:
    reviewed = _walk_reviewed_state(integration, source=source)
    visible = {
        key: value
        for key, value in reviewed.items()
        if key not in READ_BACK_FIELDS
    }
    return hashlib.sha256(
        json.dumps(
            visible,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _configuration_fingerprint(
    integration: dict[str, Any], *, source: _ReviewedStateSource
) -> str:
    reviewed = _walk_reviewed_state(integration, source=source)
    configuration = {
        key: value
        for key, value in reviewed.items()
        if key not in READ_BACK_FIELDS
        and key != "enabled"
    }
    return hashlib.sha256(
        json.dumps(
            configuration,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _mutation_response_id(
    response: Any, *, method: str, expected_id: str | None = None
) -> str:
    """Validate a documented response object without trusting returned credentials."""
    try:
        response_without_id = dict(response)
        response_without_id.pop("id", None)
        _project_live_reviewed_state(response_without_id)
    except (ApiError, TypeError, ValueError) as exc:
        raise ProtocolResponseError(
            f"{method} response violated the credential-free integration schema"
        ) from exc
    try:
        integration_id = _validate_server_id(response.get("id"))
    except (ApiError, AttributeError) as exc:
        raise AmbiguousMutationError(
            f"{method} response did not contain a valid server-assigned integration ID"
        ) from exc
    if expected_id is not None and integration_id != expected_id:
        raise AmbiguousMutationError(
            f"{method} response integration ID did not match the exact target"
        )
    return integration_id


def _assert_exact_live(
    live: dict[str, Any],
    plan: dict[str, Any],
    *,
    expected_enabled: bool,
) -> None:
    if not live:
        raise ApiError(f"integration ID {plan['integration_id']!r} is missing (HTTP 200 empty)")
    if live.get("id") != plan["integration_id"]:
        raise ApiError("exact-ID GET returned a different integration ID")
    if live.get("type") != "Azure":
        raise ApiError("exact-ID GET returned the wrong provider type")
    if live.get("name") != plan["integration_name"]:
        raise ApiError("exact-ID GET returned a different integration name")
    if type(live.get("enabled")) is not bool:
        raise ApiError("exact-ID GET returned a non-Boolean enabled state")
    if live["enabled"] is not expected_enabled:
        raise ApiError(
            f"exact-ID GET enabled state drifted: expected {expected_enabled}, "
            f"found {live['enabled']}"
        )


def _assert_matches_reviewed_state(live: dict[str, Any], plan: dict[str, Any]) -> None:
    sanitized = _project_live_reviewed_state(live)
    if not hmac.compare_digest(
        _reviewed_state_sha256(sanitized), plan["reviewed_state_sha256"]
    ):
        raise ApiError(
            "exact-ID live state no longer matches the reviewed observed snapshot"
        )


def _load_azure_credential_material(
    app_id_file: str,
    secret_file: str,
) -> tuple[str, bytes, str, bytes]:
    if not app_id_file or not secret_file:
        raise ApiError("Azure disable requires explicit --app-id-file and --secret-file")
    try:
        app_id, app_id_raw = read_secret_file_material(app_id_file)
        secret_key, secret_raw = read_secret_file_material(secret_file)
    except (OSError, PermissionError, ValueError) as exc:
        raise ApiError(str(exc)) from exc
    return app_id, app_id_raw, secret_key, secret_raw


def _build_disable_payload(
    live: dict[str, Any],
    app_id: str,
    secret_key: str,
) -> dict[str, Any]:
    payload = _strip_read_back(live)
    payload.update({"appId": app_id, "secretKey": secret_key, "enabled": False})
    required = {
        "type": "Azure",
        "name": str,
        "tenantId": str,
        "subscriptions": list,
        "appId": str,
        "secretKey": str,
        "enabled": bool,
    }
    for field, expected_type in required.items():
        value = payload.get(field)
        if field == "type":
            if value != expected_type:
                raise ApiError("cannot reconstruct provider-valid Azure disable payload: wrong type")
        elif type(value) is not expected_type or (isinstance(value, (str, list)) and not value):
            raise ApiError(
                f"cannot reconstruct provider-valid Azure disable payload: invalid {field}"
            )
    return payload


def _poll_disabled(
    realm: str,
    token: str,
    plan: dict[str, Any],
) -> dict[str, Any]:
    last_error = ""
    for attempt in range(POSTCONDITION_ATTEMPTS):
        current = get_integration(realm, token, plan["integration_id"])
        try:
            _assert_exact_live(current, plan, expected_enabled=False)
            return current
        except ApiError as exc:
            last_error = str(exc)
        if attempt < POSTCONDITION_ATTEMPTS - 1:
            time.sleep(POSTCONDITION_DELAY_SECONDS)
    raise ApiError(f"disable postcondition was not reached: {last_error}")


def _poll_deleted(realm: str, token: str, plan: dict[str, Any]) -> None:
    for attempt in range(POSTCONDITION_ATTEMPTS):
        current = get_integration(realm, token, plan["integration_id"])
        if current == {}:
            return
        if current.get("id") != plan["integration_id"]:
            raise ApiError("delete verification GET returned a different integration ID")
        if current.get("type") != "Azure" or current.get("name") != plan["integration_name"]:
            raise ApiError("delete verification GET returned a drifted target")
        if attempt < POSTCONDITION_ATTEMPTS - 1:
            time.sleep(POSTCONDITION_DELAY_SECONDS)
    raise ApiError("delete postcondition was not reached; exact-ID GET remained non-empty")


def _validate_acknowledgement(
    plan: dict[str, Any],
    acknowledge_disable: str,
    acknowledge_delete: str,
) -> None:
    supplied = [value for value in (acknowledge_disable, acknowledge_delete) if value]
    if len(supplied) != 1:
        raise ApiError("exactly one action-specific rollback acknowledgement is required")
    expected_id = plan["integration_id"]
    if plan["action"] == "disable":
        if acknowledge_disable != expected_id or acknowledge_delete:
            raise ApiError("--accept-disable-integration must equal the planned integration ID")
    elif acknowledge_delete != expected_id or acknowledge_disable:
        raise ApiError("--accept-delete-integration must equal the planned integration ID")


def apply_rollback(
    *,
    realm: str,
    token: str,
    state_dir: Path,
    plan_path: Path,
    plan_sha256: str,
    action: str,
    integration_id: str,
    apply_gate: bool,
    acknowledge_disable: str = "",
    acknowledge_delete: str = "",
    app_id_file: str = "",
    secret_file: str = "",
) -> dict[str, Any]:
    """Apply one exact-ID rollback while continuously holding its target lock."""
    validate_realm(realm)
    if not apply_gate:
        raise ApiError("rollback mutation requires the explicit --apply gate")
    plan = load_rollback_plan(plan_path, plan_sha256)
    integration_id = _validate_server_id(integration_id)
    if plan["realm"] != realm or plan["action"] != action or plan["integration_id"] != integration_id:
        raise ApiError("rollback flags do not match the canonical reviewed plan")
    _validate_acknowledgement(plan, acknowledge_disable, acknowledge_delete)
    if action == "delete" and (app_id_file or secret_file):
        raise ApiError("delete rollback rejects Azure credential files")
    credential_material: tuple[str, bytes, str, bytes] | None = None
    if action == "disable":
        credential_material = _load_azure_credential_material(app_id_file, secret_file)
        _app_id, app_id_raw, _secret_key, secret_raw = credential_material
        actual_binding = {
            "app_id_sha256": hashlib.sha256(app_id_raw).hexdigest(),
            "secret_key_sha256": hashlib.sha256(secret_raw).hexdigest(),
        }
        if any(
            not hmac.compare_digest(actual_binding[field], plan["credential_binding"][field])
            for field in AZURE_CREDENTIAL_BINDING_FIELDS
        ):
            raise ApiError(
                "Azure credential files changed since plan review; render a fresh plan"
            )

    with _target_lock(realm, integration_id) as claim_root:
        listing = list_azure_integrations(realm, token)
        name_matches = [
            item
            for item in listing
            if item.get("name") == plan["integration_name"] and item.get("type") == "Azure"
        ]
        if len(name_matches) != 1 or name_matches[0].get("id") != integration_id:
            raise ApiError(
                "complete preflight listing no longer has one exact reviewed name/type/ID"
            )
        first = get_integration(realm, token, integration_id)
        _assert_exact_live(first, plan, expected_enabled=plan["expected_enabled_state"])
        _assert_matches_reviewed_state(first, plan)
        first_fingerprint = _visible_fingerprint(
            first, source=_ReviewedStateSource.LIVE_RESPONSE
        )
        second = get_integration(realm, token, integration_id)
        _assert_exact_live(second, plan, expected_enabled=plan["expected_enabled_state"])
        _assert_matches_reviewed_state(second, plan)
        if not hmac.compare_digest(
            first_fingerprint,
            _visible_fingerprint(second, source=_ReviewedStateSource.LIVE_RESPONSE),
        ):
            raise ApiError("visible integration fingerprint changed between preflight reads")
        preconfiguration_fingerprint = _configuration_fingerprint(
            second, source=_ReviewedStateSource.LIVE_RESPONSE
        )

        if action == "disable":
            assert credential_material is not None
            app_id, _app_id_raw, secret_key, _secret_raw = credential_material
            payload = _build_disable_payload(second, app_id, secret_key)
            try:
                idempotency_key = claim_rollback_attempt(
                    state_dir,
                    plan_path=plan_path,
                    claim_root=claim_root,
                    provider="Azure",
                    realm=realm,
                    action=action,
                    integration_id=integration_id,
                    plan_id=plan["plan_id"],
                    plan_sha256=plan_sha256,
                )
            except (OSError, PermissionError, ValueError) as exc:
                raise ApiError(str(exc)) from exc
            try:
                mutation_response = update_integration(
                    realm,
                    token,
                    integration_id,
                    payload,
                    _capability=_ROLLBACK_CAPABILITY,
                )
                _mutation_response_id(
                    mutation_response,
                    method="PUT",
                    expected_id=integration_id,
                )
            except ProtocolResponseError as protocol_error:
                append_step(
                    state_dir,
                    "integration",
                    "disable",
                    idempotency_key,
                    "failed",
                    {},
                    notes="single PUT completed but its response violated the reviewed schema",
                )
                raise ApiError(
                    "single PUT completed but its response violated the reviewed schema; "
                    "operator resolution is required"
                ) from protocol_error
            except AmbiguousMutationError as mutation_error:
                try:
                    reconciled = get_integration(realm, token, integration_id)
                    reconciliation = {
                        "found": bool(reconciled),
                        "enabled": reconciled.get("enabled") if reconciled else None,
                        "fingerprint": _visible_fingerprint(
                            reconciled, source=_ReviewedStateSource.LIVE_RESPONSE
                        ) if reconciled else None,
                    }
                except ApiError as reconcile_error:
                    reconciliation = {"reconciliation_error": str(reconcile_error)}
                append_step(
                    state_dir,
                    "integration",
                    "disable",
                    idempotency_key,
                    "failed",
                    redact(reconciliation),
                    notes="single PUT attempt failed; exact-ID reconciliation requires operator resolution",
                )
                raise ApiError(
                    "single PUT attempt failed; exact-ID reconciliation was recorded and "
                    "operator resolution is required"
                ) from mutation_error
            try:
                confirmed = _poll_disabled(realm, token, plan)
                drift_check = get_integration(realm, token, integration_id)
                _assert_exact_live(drift_check, plan, expected_enabled=False)
                if any(
                    not hmac.compare_digest(
                        preconfiguration_fingerprint,
                        _configuration_fingerprint(
                            postcondition,
                            source=_ReviewedStateSource.LIVE_RESPONSE,
                        ),
                    )
                    for postcondition in (confirmed, drift_check)
                ):
                    raise ApiError("configuration fingerprint changed during disable")
            except ApiError as postcondition_error:
                append_step(
                    state_dir,
                    "integration",
                    "disable",
                    idempotency_key,
                    "failed",
                    redact({"postcondition_error": str(postcondition_error)}),
                    notes=(
                        "single PUT completed but bounded disable postcondition polling failed "
                        "or final verification failed"
                    ),
                )
                raise
            journal = {
                "id": integration_id,
                "type": "Azure",
                "name": plan["integration_name"],
                "enabled": False,
                "fingerprint": _visible_fingerprint(
                    drift_check, source=_ReviewedStateSource.LIVE_RESPONSE
                ),
            }
            append_step(
                state_dir,
                "integration",
                "disable",
                idempotency_key,
                "success",
                redact(journal),
            )
            return {"result": "disabled", "id": integration_id, "name": plan["integration_name"]}

        try:
            idempotency_key = claim_rollback_attempt(
                state_dir,
                plan_path=plan_path,
                claim_root=claim_root,
                provider="Azure",
                realm=realm,
                action=action,
                integration_id=integration_id,
                plan_id=plan["plan_id"],
                plan_sha256=plan_sha256,
            )
        except (OSError, PermissionError, ValueError) as exc:
            raise ApiError(str(exc)) from exc
        try:
            mutation_response = delete_integration(
                realm,
                token,
                integration_id,
                _capability=_ROLLBACK_CAPABILITY,
            )
            if mutation_response != {}:
                raise AmbiguousMutationError(
                    "DELETE HTTP 200 response unexpectedly contained a body"
                )
        except AmbiguousMutationError as mutation_error:
            try:
                reconciled = get_integration(realm, token, integration_id)
                reconciliation = {
                    "found": bool(reconciled),
                    "enabled": reconciled.get("enabled") if reconciled else None,
                    "fingerprint": _visible_fingerprint(
                        reconciled, source=_ReviewedStateSource.LIVE_RESPONSE
                    ) if reconciled else None,
                }
            except ApiError as reconcile_error:
                reconciliation = {"reconciliation_error": str(reconcile_error)}
            append_step(
                state_dir,
                "integration",
                "delete",
                idempotency_key,
                "failed",
                redact(reconciliation),
                notes="single DELETE attempt failed; exact-ID reconciliation requires operator resolution",
            )
            raise ApiError(
                "single DELETE attempt failed; exact-ID reconciliation was recorded and "
                "operator resolution is required"
            ) from mutation_error
        try:
            _poll_deleted(realm, token, plan)
            if get_integration(realm, token, integration_id) != {}:
                raise ApiError(
                    "delete verification drifted: second exact-ID GET was not HTTP 200 empty"
                )
        except ApiError as postcondition_error:
            append_step(
                state_dir,
                "integration",
                "delete",
                idempotency_key,
                "failed",
                redact({"postcondition_error": str(postcondition_error)}),
                notes=(
                    "single DELETE completed but bounded delete postcondition polling failed "
                    "or final verification failed"
                ),
            )
            raise
        journal = {
            "id": integration_id,
            "type": "Azure",
            "name": plan["integration_name"],
            "deleted": True,
        }
        append_step(
            state_dir,
            "integration",
            "delete",
            idempotency_key,
            "success",
            redact(journal),
        )
        return {"result": "deleted", "id": integration_id, "name": plan["integration_name"]}


# ---------------------------------------------------------------------------
# Higher-level operations.
# ---------------------------------------------------------------------------


def upsert(
    realm: str,
    token: str,
    payload: dict[str, Any],
    state_dir: Path,
    app_id_file: str = "",
    secret_file: str = "",
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Idempotent create-or-update keyed on integration name.

    After a successful apply, stores SHA-256 hashes of the credential files
    in state/credential-hashes.json for later drift detection.
    """
    validate_realm(realm)
    name = payload.get("name") or ""
    if not name:
        raise ApiError("payload.name is required")
    requested_enabled = payload.get("enabled", True)
    if type(requested_enabled) is not bool:
        raise ApiError("payload.enabled must be Boolean")
    payload = _strip_read_back(payload)
    idempotency_key = f"azure-upsert:{name}"
    credential_hashes: dict[str, str] = {}

    # Inline/placeholder credentials are never authoritative. Both files are
    # required and their stable captured bytes overwrite any payload fields.
    if not app_id_file or not secret_file:
        raise ApiError("Azure upsert requires both --app-id-file and --secret-file")
    try:
        app_id, app_id_raw = read_secret_file_material(app_id_file)
        secret_key, secret_raw = read_secret_file_material(secret_file)
    except (OSError, PermissionError, ValueError) as exc:
        raise ApiError(str(exc)) from exc
    payload = {**payload, "appId": app_id, "secretKey": secret_key}
    credential_hashes["app_id_sha256"] = hashlib.sha256(app_id_raw).hexdigest()
    credential_hashes["secret_sha256"] = hashlib.sha256(secret_raw).hexdigest()

    if dry_run:
        return {"result": "dry-run", "name": name, "would_send": redact(payload)}

    # The authoritative name decision is made after acquiring the canonical
    # local lock.  Remote hosts are outside this process-local coordination,
    # so every duplicate observed by this re-list still fails closed.
    with _name_lock(realm, name):
        existing = list_azure_integrations(realm, token)
        _require_name_decision_coverage(existing)
        matches = [item for item in existing if item.get("name") == name]
        if len(matches) > 1:
            raise ApiError(f"multiple Azure integrations exactly match name {name!r}; refusing upsert")
        match = matches[0] if matches else None

        if match:
            if requested_enabled is False:
                raise ApiError("upsert cannot disable an existing integration; use reviewed rollback")
            integration_id = _validate_server_id(match.get("id"))
            decision_fingerprint = _reviewed_state_sha256(
                _project_live_reviewed_state(match)
            )
            # Global local lock order is name -> target. Rollback takes only the
            # target lock, so its preflight/mutation transaction cannot overlap
            # this read-modify-write and no lock cycle is possible.
            with _target_lock(realm, integration_id):
                current = get_integration(realm, token, integration_id)
                if current == {}:
                    raise ApiError("exact-ID upsert target disappeared after name resolution")
                if (
                    current.get("id") != integration_id
                    or current.get("type") != "Azure"
                    or current.get("name") != name
                ):
                    raise ApiError("exact-ID upsert target drifted after name resolution")
                current_fingerprint = _reviewed_state_sha256(
                    _project_live_reviewed_state(current)
                )
                if not hmac.compare_digest(decision_fingerprint, current_fingerprint):
                    raise ApiError(
                        "exact-ID upsert target changed while waiting for the target lock; "
                        "refusing a stale update"
                    )
                merged = _strip_read_back({**current, **payload})
                merged["enabled"] = requested_enabled
                try:
                    result = update_integration(realm, token, integration_id, merged)
                    _mutation_response_id(
                        result,
                        method="PUT",
                        expected_id=integration_id,
                    )
                except ProtocolResponseError as protocol_error:
                    append_step(
                        state_dir,
                        "integration",
                        "update",
                        idempotency_key,
                        "failed",
                        {},
                        notes="single PUT completed but its response violated the reviewed schema",
                    )
                    raise ApiError(
                        "single PUT completed but its response violated the reviewed schema; "
                        "operator resolution is required"
                    ) from protocol_error
                except AmbiguousMutationError as mutation_error:
                    try:
                        reconciled = get_integration(realm, token, integration_id)
                        reconciliation = {
                            "found": bool(reconciled),
                            "id": reconciled.get("id") if reconciled else None,
                            "enabled": reconciled.get("enabled") if reconciled else None,
                            "fingerprint": _visible_fingerprint(
                                reconciled,
                                source=_ReviewedStateSource.LIVE_RESPONSE,
                            ) if reconciled else None,
                        }
                    except ApiError as reconcile_error:
                        reconciliation = {"reconciliation_error": str(reconcile_error)}
                    append_step(
                        state_dir,
                        "integration",
                        "update",
                        idempotency_key,
                        "failed",
                        reconciliation,
                        notes="single PUT attempt was ambiguous; exact-ID reconciliation requires operator resolution",
                    )
                    raise ApiError(
                        "single PUT attempt was ambiguous; exact-ID reconciliation was recorded "
                        "and operator resolution is required"
                    ) from mutation_error
                try:
                    confirmed = get_integration(realm, token, integration_id)
                    if (
                        not confirmed
                        or confirmed.get("id") != integration_id
                        or confirmed.get("type") != "Azure"
                        or confirmed.get("name") != name
                        or confirmed.get("enabled") is not requested_enabled
                        or not hmac.compare_digest(
                            _configuration_fingerprint(
                                merged,
                                source=_ReviewedStateSource.OUTBOUND_REQUEST,
                            ),
                            _configuration_fingerprint(
                                confirmed,
                                source=_ReviewedStateSource.LIVE_RESPONSE,
                            ),
                        )
                    ):
                        raise ApiError("Azure update postcondition did not match the requested configuration")
                    after = list_azure_integrations(realm, token)
                    same_name = [
                        item for item in after
                        if item.get("type") == "Azure" and item.get("name") == name
                    ]
                    if len(same_name) != 1 or same_name[0].get("id") != integration_id:
                        raise ApiError("Azure update could not prove post-mutation name uniqueness")
                except ApiError as postcondition_error:
                    append_step(
                        state_dir,
                        "integration",
                        "update",
                        idempotency_key,
                        "failed",
                        {"postcondition_error": str(postcondition_error)},
                        notes="single PUT completed but exact postcondition verification failed",
                    )
                    raise
                append_step(
                    state_dir,
                    "integration",
                    "update",
                    idempotency_key,
                    "success",
                    redact(result),
                )
                _record_credential_hashes(state_dir, credential_hashes)
                return {"result": "updated", "name": name, "id": integration_id}

        payload_enabled = {**payload, "enabled": requested_enabled}
        try:
            result = create_integration(realm, token, payload_enabled)
            integration_id = _mutation_response_id(result, method="POST")
        except ProtocolResponseError as protocol_error:
            append_step(
                state_dir,
                "integration",
                "create",
                idempotency_key,
                "failed",
                {},
                notes="single POST completed but its response violated the reviewed schema",
            )
            raise ApiError(
                "single POST completed but its response violated the reviewed schema; "
                "operator resolution is required"
            ) from protocol_error
        except AmbiguousMutationError as mutation_error:
            try:
                after = list_azure_integrations(realm, token)
                candidates = [
                    item.get("id") for item in after
                    if item.get("type") == "Azure" and item.get("name") == name
                ]
                reconciliation = {"candidate_ids": candidates}
            except ApiError as reconcile_error:
                reconciliation = {"reconciliation_error": str(reconcile_error)}
            append_step(
                state_dir,
                "integration",
                "create",
                idempotency_key,
                "failed",
                reconciliation,
                notes="single POST attempt was ambiguous; exact-name reconciliation requires operator resolution",
            )
            raise ApiError(
                "single POST attempt was ambiguous; exact-name reconciliation was recorded "
                "and operator resolution is required"
            ) from mutation_error
        with _target_lock(realm, integration_id):
            try:
                confirmed = get_integration(realm, token, integration_id)
                if (
                    not confirmed
                    or confirmed.get("id") != integration_id
                    or confirmed.get("type") != "Azure"
                    or confirmed.get("name") != name
                    or confirmed.get("enabled") is not requested_enabled
                    or not hmac.compare_digest(
                        _configuration_fingerprint(
                            payload_enabled,
                            source=_ReviewedStateSource.OUTBOUND_REQUEST,
                        ),
                        _configuration_fingerprint(
                            confirmed,
                            source=_ReviewedStateSource.LIVE_RESPONSE,
                        ),
                    )
                ):
                    raise ApiError("Azure create postcondition did not match the requested configuration")
                after = list_azure_integrations(realm, token)
                same_name = [
                    item for item in after
                    if item.get("type") == "Azure" and item.get("name") == name
                ]
                if len(same_name) != 1 or same_name[0].get("id") != integration_id:
                    raise ApiError("Azure create could not prove post-mutation name uniqueness")
            except ApiError as postcondition_error:
                append_step(
                    state_dir,
                    "integration",
                    "create",
                    idempotency_key,
                    "failed",
                    {"postcondition_error": str(postcondition_error)},
                    notes="single POST completed but exact postcondition verification failed",
                )
                raise
        append_step(
            state_dir, "integration", "create", idempotency_key, "success", redact(result)
        )
        _record_credential_hashes(state_dir, credential_hashes)
        return {"result": "created", "name": name, "id": integration_id}


def _record_credential_hashes(state_dir: Path, hashes: dict[str, str]) -> None:
    if hashes:
        _save_cred_hashes(state_dir, dict(hashes))


def _load_payload_file(path: str) -> dict[str, Any]:
    try:
        raw = read_private_file_bytes(
            path,
            allow_loose=True,
            max_bytes=MAX_OBSERVED_BYTES,
            label="integration payload",
        )
    except (OSError, PermissionError, ValueError) as exc:
        raise ApiError(str(exc)) from exc
    payload = _strict_json_loads(raw, label=f"integration payload {path}")
    if not isinstance(payload, dict):
        raise ApiError("integration payload must be a JSON object")
    return payload


def discover(realm: str, token: str, output_path: Path | None, state_dir: Path) -> dict[str, Any]:
    integrations = list_azure_integrations(realm, token)
    if output_path:
        snapshot = write_observed_snapshot(
            output_path, realm=realm, integrations=integrations
        )
    else:
        snapshot = _validate_observed_snapshot(
            {
                "schema_version": OBSERVED_SCHEMA_VERSION,
                "provider": "Azure",
                "realm": validate_realm(realm),
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "count": len(integrations),
                "results": [
                    _project_live_reviewed_state(item) for item in integrations
                ],
            },
            expected_realm=realm,
        )
    append_step(
        state_dir, "validation", "discover", f"azure-discover:{realm}", "success",
        {"count": len(integrations)},
    )
    return snapshot


def disable_by_name(realm: str, token: str, name: str, state_dir: Path) -> dict[str, Any]:
    del realm, token, name, state_dir
    raise ApiError(
        "name-based disable is read-only adoption only; resolve the exact ID and render a rollback plan"
    )


def delete_by_name(realm: str, token: str, name: str, state_dir: Path) -> dict[str, Any]:
    del realm, token, name, state_dir
    raise ApiError(
        "name-based delete is prohibited; resolve the exact ID and render a distinct delete plan"
    )


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


_REJECTED_SECRET_FLAGS: tuple[str, ...] = (
    "--token", "--access-token", "--api-token", "--o11y-token", "--admin-token",
    "--sf-token", "--app-id", "--app-secret", "--client-secret", "--password", "--secret",
)
_KNOWN_VALUE_FLAGS = frozenset({
    "--realm", "--token-file", "--state-dir", "--payload-file", "--app-id-file",
    "--secret-file", "--integration-id", "--integration-name", "--expected-enabled-state",
    "--plan-file", "--plan-hash", "--observed-state-file", "--accept-disable-integration",
    "--accept-delete-integration", "--output",
})
_KNOWN_FLAG_ONLY = frozenset({"--allow-loose-token-perms", "--dry-run", "--apply", "--help"})


def _reject_direct_secret_flags() -> None:
    for arg in sys.argv[1:]:
        flag = arg.split("=", 1)[0]
        if flag in _REJECTED_SECRET_FLAGS:
            print(
                f"FAIL: refusing direct-secret flag {flag}. Use --token-file, --app-id-file, "
                f"or --secret-file (all chmod 600).",
                flush=True,
            )
            sys.exit(2)
        if arg.startswith("--") and flag not in _KNOWN_VALUE_FLAGS | _KNOWN_FLAG_ONLY:
            print(f"FAIL: unrecognized argument: {flag}", flush=True)
            sys.exit(2)
        if "=" in arg and flag in _KNOWN_FLAG_ONLY:
            print(f"FAIL: flag does not accept a value: {flag}", flush=True)
            sys.exit(2)


def _parse() -> argparse.Namespace:
    _reject_direct_secret_flags()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--realm", required=True)
    p.add_argument("--token-file", default="")
    p.add_argument("--state-dir", required=True)
    p.add_argument("--payload-file", default="")
    p.add_argument("--app-id-file", default="")
    p.add_argument("--secret-file", default="")
    p.add_argument("--allow-loose-token-perms", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--integration-id", default="")
    p.add_argument("--integration-name", default="")
    p.add_argument("--expected-enabled-state", choices=("true", "false"), default="true")
    p.add_argument("--plan-file", default="")
    p.add_argument("--plan-hash", default="")
    p.add_argument("--observed-state-file", default="")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--accept-disable-integration", default="")
    p.add_argument("--accept-delete-integration", default="")
    p.add_argument("--output", default="")
    p.add_argument(
        "command",
        choices=(
            "list",
            "get",
            "upsert",
            "discover",
            "check-drift",
            "resolve-legacy-name",
            "rollback",
        ),
    )
    p.add_argument("rollback_action", nargs="?", choices=("disable", "delete"))
    return p.parse_args()


def main() -> int:
    args = _parse()
    try:
        # Validate both the realm and the final constructed HTTPS destination
        # before any token file can be opened.
        _validate_cli_destinations(args.realm, args.integration_id)
        state_dir = Path(args.state_dir)

        if args.command == "rollback":
            if args.dry_run:
                raise ApiError("--dry-run is not accepted with rollback")
            if not args.plan_file or not args.rollback_action or not args.integration_id:
                raise ApiError(
                    "rollback requires --plan-file, a positional disable/delete action, and --integration-id"
                )
            plan_path = Path(args.plan_file)
            if not args.apply:
                if args.plan_hash or args.accept_disable_integration or args.accept_delete_integration:
                    raise ApiError("offline rollback render does not accept apply acknowledgements")
                if args.token_file or args.allow_loose_token_perms:
                    raise ApiError("offline rollback render does not accept token options")
                if not args.integration_name:
                    raise ApiError("offline rollback render requires --integration-name")
                rendered = render_rollback_plan(
                    plan_path,
                    realm=args.realm,
                    action=args.rollback_action,
                    integration_id=args.integration_id,
                    integration_name=args.integration_name,
                    expected_enabled_state=args.expected_enabled_state == "true",
                    observed_state_file=args.observed_state_file,
                    app_id_file=args.app_id_file,
                    secret_file=args.secret_file,
                )
                print(json.dumps(rendered, indent=2))
                return 0

            # Local plan, action, ID, and acknowledgement gates are all checked
            # before the token read. apply_rollback loads and hashes the plan a
            # second time immediately before entering the locked live workflow.
            preview = load_rollback_plan(plan_path, args.plan_hash)
            if args.observed_state_file:
                raise ApiError("rollback --apply uses the snapshot bound in the plan")
            if (
                preview["realm"] != args.realm
                or preview["action"] != args.rollback_action
                or preview["integration_id"] != args.integration_id
            ):
                raise ApiError("rollback flags do not match the canonical reviewed plan")
            _validate_acknowledgement(
                preview,
                args.accept_disable_integration,
                args.accept_delete_integration,
            )
            if args.allow_loose_token_perms:
                raise ApiError("rollback --apply requires strict mode-600 token permissions")
            if args.rollback_action == "delete" and (args.app_id_file or args.secret_file):
                raise ApiError("delete rollback rejects Azure credential files")
            if not args.token_file:
                raise ApiError("rollback --apply requires --token-file")
            try:
                token = read_secret_file(
                    args.token_file,
                    allow_loose=args.allow_loose_token_perms,
                )
            except (OSError, PermissionError, ValueError) as exc:
                raise ApiError(str(exc)) from exc
            result = apply_rollback(
                realm=args.realm,
                token=token,
                state_dir=state_dir,
                plan_path=plan_path,
                plan_sha256=args.plan_hash,
                action=args.rollback_action,
                integration_id=args.integration_id,
                apply_gate=args.apply,
                acknowledge_disable=args.accept_disable_integration,
                acknowledge_delete=args.accept_delete_integration,
                app_id_file=args.app_id_file,
                secret_file=args.secret_file,
            )
            print(json.dumps(result, indent=2))
            return 0

        if (
            args.apply
            or args.rollback_action
            or args.plan_hash
            or args.accept_disable_integration
            or args.accept_delete_integration
            or args.observed_state_file
        ):
            raise ApiError("rollback-only flags require the `rollback` command")
        if not args.token_file:
            raise ApiError("--token-file is required for live API commands")
        if args.command == "upsert" and (not args.app_id_file or not args.secret_file):
            raise ApiError("Azure upsert requires both --app-id-file and --secret-file")
        try:
            token = read_secret_file(
                args.token_file,
                allow_loose=args.allow_loose_token_perms,
            )
        except (OSError, PermissionError, ValueError) as exc:
            raise ApiError(str(exc)) from exc

        if args.command == "list":
            items = list_azure_integrations(args.realm, token)
            print(json.dumps([redact(i) for i in items], indent=2))

        elif args.command == "get":
            if not args.integration_id:
                raise ApiError("--integration-id is required for `get`")
            print(json.dumps(redact(get_integration(args.realm, token, args.integration_id)), indent=2))

        elif args.command == "upsert":
            if not args.payload_file:
                raise ApiError("--payload-file is required for `upsert`")
            payload = _load_payload_file(args.payload_file)
            result = upsert(
                args.realm, token, payload, state_dir,
                app_id_file=args.app_id_file,
                secret_file=args.secret_file,
                dry_run=args.dry_run,
            )
            print(json.dumps(result, indent=2))

        elif args.command == "discover":
            output_path = Path(args.output) if args.output else None
            snapshot = discover(args.realm, token, output_path, state_dir)
            print(json.dumps(snapshot, indent=2))

        elif args.command == "resolve-legacy-name":
            if not args.integration_name:
                raise ApiError("--integration-name is required for `resolve-legacy-name`")
            resolved = resolve_legacy_name(args.realm, token, args.integration_name)
            print(
                json.dumps(
                    redact(
                        {
                            "provider": "Azure",
                            "name": resolved.get("name"),
                            "id": resolved.get("id"),
                            "enabled": resolved.get("enabled"),
                        }
                    ),
                    indent=2,
                )
            )

        elif args.command == "check-drift":
            if not args.app_id_file and not args.secret_file:
                raise ApiError("--app-id-file or --secret-file required for `check-drift`")
            warnings = check_credential_drift(state_dir, args.app_id_file, args.secret_file)
            if warnings:
                for w in warnings:
                    print(f"WARN: {w}", flush=True)
                return 1
            print("OK: no credential drift detected")

    except (ApiError, OSError, PermissionError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAIL: {redact(str(exc))}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

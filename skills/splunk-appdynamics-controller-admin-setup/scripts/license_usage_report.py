#!/usr/bin/env python3
"""Read-only AppDynamics Controller license usage reporter."""

from __future__ import annotations

import argparse
import base64
import binascii
import csv
import json
import os
import re
import ssl
import stat
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib import error, parse, request


SECRET_ARG_RE = re.compile(
    r"^(--(?:password|pass|secret|client-secret|api-key|token|access-token|events-api-key|controller-password))(?:=.*)?$"
)

SENSITIVE_QUERY_KEYS = {
    "access_key",
    "accesskey",
    "api_key",
    "apikey",
    "client_secret",
    "licensekey",
    "license_key",
    "password",
    "secret",
    "token",
}

SENSITIVE_FIELD_MARKERS = (
    "access_key",
    "accesskey",
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "client_secret",
    "license_key",
    "licensekey",
    "password",
    "refresh_token",
    "secret",
    "token",
)

SAFE_FIELD_KEYS = {
    "token_format",
}

UUID_LIKE_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{5,12}\b")
JWT_LIKE_RE = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
APPD_ACCEPT_HEADER = "application/vnd.appd.cntrl+json;v=1, application/json;q=0.9, */*;q=0.1"
LICENSE_PERMISSION_RE = re.compile(r"\b(ACCOUNT_LICENSE|LICENSE_USAGE|LICENSE_RULE)\b")

LICENSE_ENDPOINT_PERMISSIONS = {
    "account_info": "ACCOUNT_LICENSE",
    "grouped_application_usage": "ACCOUNT_LICENSE",
    "grouped_host_usage": "ACCOUNT_LICENSE",
    "account_usage": "LICENSE_USAGE",
    "allocation_usage": "LICENSE_USAGE",
    "allocations": "LICENSE_RULE",
    "license_rules": "LICENSE_RULE",
}


class ConfigError(Exception):
    """Local configuration or authentication setup failed."""


@dataclass
class EndpointResult:
    name: str
    method: str
    path: str
    ok: bool
    status_code: int | None = None
    payload: Any = None
    error: str = ""
    duration_ms: int = 0

    def public(self, include_payload: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": self.name,
            "method": self.method,
            "path": redact_url_path(self.path),
            "ok": self.ok,
            "status_code": self.status_code,
            "duration_ms": self.duration_ms,
        }
        if self.error:
            result["error"] = redact_string(self.error)
        if include_payload:
            result["payload"] = redact(self.payload)
        return result


def reject_direct_secret_args(argv: list[str]) -> None:
    for arg in argv:
        if SECRET_ARG_RE.match(arg):
            raise ConfigError(
                "Refusing direct-secret CLI input. Use --client-secret-file or --oauth-token-file."
            )


def env_default(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def normalize_controller_url(value: str) -> str:
    text = value.strip()
    if not text:
        raise ConfigError("--controller-url is required")
    if "://" not in text:
        text = f"https://{text}"
    parsed = parse.urlsplit(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigError("--controller-url must be a controller host or an http(s) URL")
    if parsed.username or parsed.password:
        raise ConfigError("--controller-url must not contain inline credentials")
    if parsed.query or parsed.fragment:
        raise ConfigError("--controller-url must not contain a query string or fragment")
    if parsed.path not in {"", "/"}:
        raise ConfigError("--controller-url must be the Controller origin only, without a path")
    return text.rstrip("/")


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso8601(value: str, label: str) -> str:
    text = value.strip()
    if not text:
        raise ConfigError(f"{label} must not be empty")
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ConfigError(f"{label} must be ISO-8601, for example 2026-05-28T00:00:00Z") from exc
    if parsed.tzinfo is None:
        raise ConfigError(f"{label} must include a timezone, preferably Z")
    return iso_utc(parsed)


def looks_like_inline_secret(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    if "/" in text or "\\" in text:
        return False
    return bool(JWT_LIKE_RE.fullmatch(text) or UUID_LIKE_RE.fullmatch(text) or (len(text) >= 24 and re.search(r"[A-Za-z]", text) and re.search(r"\d", text)))


def assert_secret_file(path: str, label: str) -> Path:
    if not path:
        raise ConfigError(f"{label} is required")
    secret_path = Path(path).expanduser()
    if not secret_path.is_file():
        if looks_like_inline_secret(path):
            raise ConfigError(
                f"{label} must point at a chmod-600 file; received a value that looks like an inline secret. "
                "Create a local secret file and pass its path."
            )
        raise ConfigError(f"{label} does not exist: {secret_path}")
    if secret_path.stat().st_size == 0:
        raise ConfigError(f"{label} is empty: {secret_path}")
    mode = stat.S_IMODE(secret_path.stat().st_mode)
    if mode != 0o600:
        raise ConfigError(f"{label} must be chmod 600; found {mode:03o}: {secret_path}")
    return secret_path


def read_secret_file(path: str, label: str) -> str:
    secret_path = assert_secret_file(path, label)
    value = secret_path.read_text(encoding="utf-8").strip()
    if not value:
        raise ConfigError(f"{label} is empty after trimming whitespace: {secret_path}")
    return value


def build_ssl_context() -> ssl.SSLContext | None:
    ca_cert = env_default("APPD_CA_CERT")
    verify_ssl = env_default("APPD_VERIFY_SSL", "true")
    if ca_cert:
        ca_path = Path(ca_cert).expanduser()
        if not ca_path.is_file():
            raise ConfigError(f"APPD_CA_CERT does not exist: {ca_path}")
        return ssl.create_default_context(cafile=str(ca_path))
    if verify_ssl.lower() in {"false", "0", "no", "off"}:
        print(
            "WARN: TLS verification is disabled for AppDynamics API calls (APPD_VERIFY_SSL=false).",
            file=sys.stderr,
        )
        return ssl._create_unverified_context()  # noqa: SLF001 - stdlib escape hatch for lab controllers.
    if verify_ssl.lower() in {"true", "1", "yes", "on", ""}:
        return ssl.create_default_context()
    raise ConfigError(f"APPD_VERIFY_SSL must be true or false; got {verify_ssl!r}")


def controller_url_join(base: str, path: str) -> str:
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def redact_string(value: str) -> str:
    text = JWT_LIKE_RE.sub("<redacted:jwt>", value)
    if "Bearer " in text:
        text = re.sub(r"Bearer\s+\S+", "Bearer <redacted:token>", text)
    text = re.sub(
        r'("(?:access_key|accessKey|licenseKey|client_secret|access_token|refresh_token|token)"\s*:\s*")([^"]+)(")',
        r"\1<redacted>\3",
        text,
    )
    return text


def redact_url_path(value: str) -> str:
    if not value:
        return value
    text = UUID_LIKE_RE.sub("<redacted:id-or-key>", value)
    text = re.sub(r"(/allocation/)[^/?#]+", r"\1<redacted:license-key>", text)
    parsed = parse.urlsplit(text)
    if not parsed.query:
        return text
    query_pairs = parse.parse_qsl(parsed.query, keep_blank_values=True)
    safe_pairs = []
    for key, item in query_pairs:
        if key.lower() in SENSITIVE_QUERY_KEYS or "secret" in key.lower() or "token" in key.lower():
            safe_pairs.append((key, "<redacted>"))
        else:
            safe_pairs.append((key, item))
    return parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parse.urlencode(safe_pairs), parsed.fragment))


def redact(value: Any, parent_key: str = "") -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in SAFE_FIELD_KEYS:
                result[key] = redact(item)
            elif any(marker in lowered for marker in SENSITIVE_FIELD_MARKERS):
                if "file" in lowered:
                    result[key] = str(item)
                elif "license" in lowered:
                    result[key] = "<redacted:license-key>"
                elif "access" in lowered and "key" in lowered:
                    result[key] = "<redacted:access-key>"
                else:
                    result[key] = "<redacted>"
            else:
                result[key] = redact(item, lowered)
        return result
    if isinstance(value, list):
        return [redact(item, parent_key) for item in value]
    if isinstance(value, str):
        if parent_key and any(marker in parent_key for marker in SENSITIVE_FIELD_MARKERS):
            return "<redacted>"
        return redact_string(value)
    return value


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def safe_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def metric_value(value: Any, preferred: str = "max") -> float | None:
    if isinstance(value, dict):
        for key in (preferred, "avg", "count", "min"):
            number = safe_number(value.get(key))
            if number is not None:
                return number
    return safe_number(value)


def decode_jwt_payload(token: str) -> dict[str, Any] | None:
    parts = token.split(".")
    if len(parts) != 3:
        return None
    payload_segment = parts[1]
    payload_segment += "=" * (-len(payload_segment) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload_segment.encode("ascii"))
        payload = json.loads(decoded.decode("utf-8"))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def count_claim(value: Any) -> int | None:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return len(value)
    if value is None:
        return None
    return 1


def claim_value(payload: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in payload:
            return payload[name]
    return None


def token_auth_context(token: str) -> dict[str, Any]:
    payload = decode_jwt_payload(token)
    if payload is None:
        return {"token_format": "opaque"}
    account_id_claim = payload.get("acctId") or payload.get("accountId")
    tenant_id_claim = payload.get("tntId") or payload.get("tenantId")
    return {
        "token_format": "jwt",
        "id_type": payload.get("idType", ""),
        "principal": payload.get("sub", ""),
        "account_name_claim": payload.get("acctName", ""),
        "account_id_claim_present": bool(account_id_claim),
        "tenant_id_claim_present": bool(tenant_id_claim),
        "role_count": count_claim(claim_value(payload, "roleIds", "roles")),
        "account_permission_count": count_claim(claim_value(payload, "acctPerm", "accountPermissions")),
    }


def endpoint_permission_hint(name: str) -> str | None:
    for prefix, permission in LICENSE_ENDPOINT_PERMISSIONS.items():
        if name == prefix or name.startswith(f"{prefix}:"):
            return permission
    return None


def append_live_validation_warnings(
    warnings: list[str],
    auth_context: dict[str, Any],
    results: list[EndpointResult],
    account_id: str,
) -> None:
    forbidden_permissions: set[str] = set()
    for result in results:
        if result.status_code != 403:
            continue
        hinted = endpoint_permission_hint(result.name)
        if hinted:
            forbidden_permissions.add(hinted)
        forbidden_permissions.update(LICENSE_PERMISSION_RE.findall(result.error or ""))
    if forbidden_permissions:
        if auth_context.get("id_type") == "API_CLIENT" and auth_context.get("role_count") == 0:
            warnings.append(
                "OAuth token is for an API Client and the token exposes zero role IDs. Assign and save roles on "
                "Administration > API Clients; Administration > Users roles do not grant API Client access."
            )
        if auth_context.get("id_type") == "API_CLIENT" and auth_context.get("account_permission_count") == 0:
            warnings.append(
                "OAuth token exposes zero account permission claims. License endpoints require API Client roles with "
                "ACCOUNT_LICENSE, LICENSE_USAGE, and LICENSE_RULE read permissions; rely on endpoint status because "
                "some SaaS tokens omit effective permissions from claims."
            )
        warnings.append(
            "License API returned 403 for permission(s) "
            f"{', '.join(sorted(forbidden_permissions))}. Confirm the API Client itself has a saved role assignment "
            "on Administration > API Clients."
        )

    account_endpoint_failed = any(
        result.status_code in {400, 404}
        and result.name in {"account_info", "account_usage", "allocations", "grouped_application_usage", "grouped_host_usage"}
        for result in results
    )
    if account_endpoint_failed:
        warnings.append(
            f"Account-scoped License API endpoint failed for account ID {account_id}. APPD_ACCOUNT_ID must be the numeric "
            "License API accountId; GUID-like OAuth acctId/tntId values are not accepted by these endpoints."
        )


class AppDClient:
    def __init__(self, controller_url: str, token: str, timeout: int = 30) -> None:
        self.controller_url = controller_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.ssl_context = build_ssl_context()

    def get_json(self, name: str, path: str, query: dict[str, Any] | list[tuple[str, Any]] | None = None) -> EndpointResult:
        if isinstance(query, dict):
            pairs: list[tuple[str, Any]] = list(query.items())
        else:
            pairs = list(query or [])
        url = controller_url_join(self.controller_url, path)
        if pairs:
            url = f"{url}?{parse.urlencode(pairs, doseq=True)}"
        return self._json_request(name, "GET", url, path if not pairs else f"{path}?{parse.urlencode(pairs, doseq=True)}")

    def _json_request(self, name: str, method: str, url: str, display_path: str) -> EndpointResult:
        started = time.monotonic()
        req = request.Request(
            url,
            method=method,
            headers={
                "Accept": APPD_ACCEPT_HEADER,
                "Authorization": f"Bearer {self.token}",
            },
        )
        try:
            with request.urlopen(req, timeout=self.timeout, context=self.ssl_context) as response:
                body = response.read()
                payload = json.loads(body.decode("utf-8")) if body else None
                return EndpointResult(
                    name=name,
                    method=method,
                    path=display_path,
                    ok=True,
                    status_code=response.status,
                    payload=payload,
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            return EndpointResult(
                name=name,
                method=method,
                path=display_path,
                ok=False,
                status_code=exc.code,
                error=body or exc.reason,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        except error.URLError as exc:
            return EndpointResult(
                name=name,
                method=method,
                path=display_path,
                ok=False,
                error=str(exc.reason),
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            return EndpointResult(
                name=name,
                method=method,
                path=display_path,
                ok=False,
                error=f"response was not JSON: {exc}",
                duration_ms=int((time.monotonic() - started) * 1000),
            )


def oauth_token(controller_url: str, account_name: str, api_client_name: str, client_secret_file: str, timeout: int) -> str:
    secret = read_secret_file(client_secret_file, "AppDynamics OAuth client secret file")
    data = parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": api_client_name if "@" in api_client_name else f"{api_client_name}@{account_name}",
            "client_secret": secret,
        }
    ).encode("utf-8")
    req = request.Request(
        controller_url_join(controller_url, "/controller/api/oauth/access_token"),
        method="POST",
        data=data,
        headers={
            "Accept": APPD_ACCEPT_HEADER,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with request.urlopen(req, timeout=timeout, context=build_ssl_context()) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise ConfigError(f"OAuth token request failed with HTTP {exc.code}: {redact_string(body)}") from exc
    except error.URLError as exc:
        raise ConfigError(f"OAuth token request failed: {redact_string(str(exc.reason))}") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError(f"OAuth token response was not JSON: {exc}") from exc
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise ConfigError("OAuth token response did not contain access_token")
    return token


def collect_app_ids(applications: Any, explicit_ids: list[str], max_apps: int) -> tuple[list[str], list[str]]:
    ids = [str(item) for item in explicit_ids if str(item)]
    warnings: list[str] = []
    if ids:
        return ids, warnings
    if not isinstance(applications, list):
        return [], warnings
    for app in applications:
        if not isinstance(app, dict):
            continue
        app_id = app.get("id") or app.get("appId")
        if app_id is not None:
            ids.append(str(app_id))
    deduped = list(dict.fromkeys(ids))
    if len(deduped) > max_apps:
        warnings.append(f"Deep application usage limited to first {max_apps} of {len(deduped)} applications.")
        return deduped[:max_apps], warnings
    return deduped, warnings


def collect_host_ids(grouped_application_usage: Any, explicit_ids: list[str], max_hosts: int) -> tuple[list[str], list[str]]:
    ids = [str(item) for item in explicit_ids if str(item)]
    warnings: list[str] = []
    if not ids and isinstance(grouped_application_usage, dict):
        for app_item in (grouped_application_usage.get("items") or {}).values():
            if not isinstance(app_item, dict):
                continue
            host_items = ((app_item.get("hosts") or {}).get("items") or {})
            if isinstance(host_items, dict):
                ids.extend(str(host_id) for host_id in host_items)
    deduped = list(dict.fromkeys(ids))
    if len(deduped) > max_hosts:
        warnings.append(f"Deep host usage limited to first {max_hosts} of {len(deduped)} hosts.")
        return deduped[:max_hosts], warnings
    return deduped, warnings


def summarize_usage_payload(payload: Any, source: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not isinstance(payload, dict):
        return rows
    license_rule = payload.get("licenseRule") if isinstance(payload.get("licenseRule"), dict) else {}
    for package in as_list(payload.get("packages")):
        if not isinstance(package, dict):
            continue
        package_name = package.get("packageName") or package.get("name") or package.get("package") or "unknown"
        for unit_usage in as_list(package.get("unitUsages") or package.get("usages")):
            if not isinstance(unit_usage, dict):
                continue
            data_items = as_list(unit_usage.get("data"))
            if not data_items:
                data_items = [unit_usage]
            for data in data_items:
                if not isinstance(data, dict):
                    continue
                used = metric_value(data.get("used"))
                provisioned = metric_value(data.get("provisioned"))
                rows.append(
                    {
                        "source": source,
                        "account_id": payload.get("accountId"),
                        "license_rule": license_rule.get("name"),
                        "package": package_name,
                        "usage_type": unit_usage.get("usageType") or data.get("usageType"),
                        "timestamp": data.get("timestamp"),
                        "provisioned": provisioned,
                        "used": used,
                        "registered_type": "",
                        "registered": "",
                    }
                )
                for registration in as_list(data.get("registrations")):
                    if isinstance(registration, dict):
                        rows.append(
                            {
                                "source": source,
                                "account_id": payload.get("accountId"),
                                "license_rule": license_rule.get("name"),
                                "package": package_name,
                                "usage_type": unit_usage.get("usageType") or data.get("usageType"),
                                "timestamp": data.get("timestamp"),
                                "provisioned": provisioned,
                                "used": used,
                                "registered_type": registration.get("type"),
                                "registered": metric_value(registration.get("registered")),
                            }
                        )
    return rows


def summarize_account_info(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    packages = payload.get("packages")
    if not isinstance(packages, list):
        return []
    rows: list[dict[str, Any]] = []
    for package in packages:
        if not isinstance(package, dict):
            continue
        rows.append(
            {
                "name": package.get("packageName") or package.get("name") or package.get("package") or "unknown",
                "type": package.get("type", ""),
                "kind": package.get("kind", ""),
                "family": package.get("family", ""),
                "license_units": package.get("licenseUnits", ""),
                "start_date": package.get("startDate", ""),
                "expiration_date": package.get("expirationDate", ""),
            }
        )
    return rows


def summarize_grouped_usage(payload: Any, source: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not isinstance(payload, dict):
        return rows
    items = payload.get("items")
    if not isinstance(items, dict) and source == "host":
        items = (payload.get("hosts") or {}).get("items") if isinstance(payload.get("hosts"), dict) else None
    if not isinstance(items, dict) and source == "application":
        items = (payload.get("applications") or {}).get("items") if isinstance(payload.get("applications"), dict) else None
    if not isinstance(items, dict):
        return rows
    for item_id, item in items.items():
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "source": source,
                "id": item.get("appId") or item.get("host") or item_id,
                "name": item.get("appName") or item.get("host") or item_id,
                "v_cpu": item.get("vCpu", ""),
                "nodes": len(as_list(item.get("nodes"))),
                "containers": len(as_list(item.get("containers"))),
                "agents": len(as_list(item.get("agents"))),
            }
        )
    return rows


def summarize_application_inventory(payload: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for app in as_list(payload):
        if not isinstance(app, dict):
            continue
        app_id = app.get("id") or app.get("appId")
        app_name = app.get("name") or app.get("appName") or app_id
        rows.append(
            {
                "source": "application_inventory",
                "id": app_id,
                "name": app_name,
                "v_cpu": "",
                "nodes": "",
                "containers": "",
                "agents": "",
            }
        )
    return rows


def summarize_allocations(payload: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for allocation in as_list(payload):
        if not isinstance(allocation, dict):
            continue
        rows.append(
            {
                "id": allocation.get("id", ""),
                "name": allocation.get("name", ""),
                "filters": len(as_list(allocation.get("filters"))),
                "limits": len(as_list(allocation.get("limits"))),
                "tags": ",".join(str(tag) for tag in as_list(allocation.get("tags"))),
            }
        )
    return rows


def summarize_license_rules(payload: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rule in as_list(payload):
        if not isinstance(rule, dict):
            continue
        rows.append(
            {
                "id": rule.get("id", ""),
                "name": rule.get("name", ""),
                "enabled": rule.get("enabled", ""),
                "total_licenses": rule.get("total_licenses", ""),
                "peak_usage": rule.get("peak_usage", ""),
                "entitlements": len(as_list(rule.get("entitlements"))),
                "constraints": len(as_list(rule.get("constraints"))),
            }
        )
    return rows


def endpoint_table(results: list[EndpointResult]) -> str:
    lines = ["| Check | Result | HTTP | Duration |", "| --- | --- | ---: | ---: |"]
    for result in results:
        status = "Healthy" if result.ok else "Review"
        http = result.status_code if result.status_code is not None else ""
        name = result.name.replace("_", " ").replace(":", " / ")
        lines.append(f"| {name} | {status} | {http} | {result.duration_ms} ms |")
    return "\n".join(lines)


def auth_context_table(context: dict[str, Any]) -> str:
    def value(key: str) -> Any:
        item = context.get(key, "")
        return "" if item is None else item

    rows = [
        {"field": "Token format", "value": value("token_format")},
        {"field": "Identity type", "value": value("id_type")},
        {"field": "Principal", "value": value("principal")},
        {"field": "Account claim", "value": value("account_name_claim")},
        {"field": "Account ID claim present", "value": value("account_id_claim_present")},
        {"field": "Tenant claim present", "value": value("tenant_id_claim_present")},
        {"field": "Role claims", "value": value("role_count")},
        {"field": "Account permission claims", "value": value("account_permission_count")},
    ]
    return markdown_table(["field", "value"], rows, "- No OAuth context available.")


def display_label(header: str) -> str:
    replacements = {
        "account_id": "Account ID",
        "account_name": "Account",
        "account_permission_count": "Account Permission Claims",
        "expiration_date": "Expiration",
        "http": "HTTP",
        "id": "ID",
        "latest_used": "Latest Used",
        "license_rule": "License Rule",
        "license_units": "License Units",
        "peak_time": "Peak Time",
        "peak_used": "Peak Used",
        "provisioned": "Provisioned",
        "registered_type": "Registered Type",
        "start_date": "Start Date",
        "usage_type": "Usage Type",
        "utilization": "Utilization",
        "v_cpu": "vCPU",
    }
    if header in replacements:
        return replacements[header]
    return header.replace("_", " ").title()


def format_number(value: Any) -> str:
    number = safe_number(value)
    if number is None:
        return ""
    if number.is_integer():
        return f"{int(number):,}"
    rendered = f"{number:,.2f}".rstrip("0").rstrip(".")
    return rendered


def format_percent(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.1f}%"


def format_cell(value: Any, header: str = "") -> str:
    safe_value = redact(value)
    if safe_value is None or safe_value == "None":
        return ""
    if isinstance(safe_value, bool):
        return "Yes" if safe_value else "No"
    if header in {"id", "account_id"}:
        return str(safe_value).replace("\n", " ").replace("|", "\\|")
    if isinstance(safe_value, (int, float)) and not isinstance(safe_value, bool):
        return format_number(safe_value)
    text = str(safe_value).replace("\n", " ").replace("|", "\\|")
    return "" if text == "None" else text


def markdown_table(headers: list[str], rows: list[dict[str, Any]], empty: str) -> str:
    if not rows:
        return empty
    lines = [
        "| " + " | ".join(display_label(header) for header in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        values = [format_cell(row.get(header, ""), header) for header in headers]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def friendly_warning(warning: str) -> str:
    if warning == "No host IDs available for grouped host usage.":
        return (
            "Host-level expansion was not available because grouped application usage did not include host identifiers. "
            "Account-level, allocation-level, and application inventory sections remain usable."
        )
    return warning


def report_summary_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    sections = report["sections"]
    results = report["endpoint_results"]
    healthy = sum(1 for result in results if result.ok)
    status = "Complete" if report.get("succeeded") and healthy == len(results) else "Partial"
    return [
        {"metric": "Report status", "value": status},
        {"metric": "Account", "value": f"{report['inputs']['account_name']} ({report['inputs']['account_id']})"},
        {"metric": "Controller", "value": report["inputs"]["controller_url"]},
        {
            "metric": "Reporting window",
            "value": f"{report['inputs']['date_from']} to {report['inputs']['date_to']}",
        },
        {"metric": "Granularity", "value": f"{report['inputs']['granularity_minutes']} minutes"},
        {"metric": "Licensed packages", "value": len(sections["account_info"])},
        {"metric": "Usage samples collected", "value": len(sections["usage"])},
        {"metric": "Applications observed", "value": len(sections["applications"])},
        {"metric": "Allocations observed", "value": len(sections["allocations"])},
        {"metric": "API readbacks", "value": f"{healthy}/{len(results)} healthy"},
    ]


def display_source(source: str) -> str:
    if source == "account":
        return "Account"
    if source.startswith("allocation_usage:"):
        return f"Allocation: {source.split(':', 1)[1]}"
    return source.replace("_", " ").title()


def usage_highlight_rows(rows: list[dict[str, Any]], source_prefix: str, limit: int = 10) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        if row.get("registered_type"):
            continue
        source = str(row.get("source") or "")
        if source_prefix and not source.startswith(source_prefix):
            continue
        package = str(row.get("package") or "")
        usage_type = str(row.get("usage_type") or "")
        if not package or not usage_type:
            continue
        license_rule = str(row.get("license_rule") or "")
        key = (source, license_rule, package, usage_type)
        item = grouped.setdefault(
            key,
            {
                "source": display_source(source),
                "license_rule": license_rule,
                "package": package,
                "usage_type": usage_type,
                "peak_used_value": None,
                "peak_used": "",
                "latest_used": "",
                "provisioned_value": None,
                "provisioned": "",
                "utilization_value": None,
                "utilization": "",
                "peak_time": "",
                "samples": 0,
            },
        )
        item["samples"] += 1
        used = safe_number(row.get("used"))
        provisioned = safe_number(row.get("provisioned"))
        timestamp = str(row.get("timestamp") or "")
        if provisioned is not None and (
            item["provisioned_value"] is None or provisioned > item["provisioned_value"]
        ):
            item["provisioned_value"] = provisioned
            item["provisioned"] = format_number(provisioned)
        if used is not None and (item["peak_used_value"] is None or used > item["peak_used_value"]):
            item["peak_used_value"] = used
            item["peak_used"] = format_number(used)
            item["peak_time"] = timestamp
        if timestamp and timestamp >= str(item.get("latest_time") or ""):
            item["latest_time"] = timestamp
            item["latest_used"] = format_number(used)

    highlights: list[dict[str, Any]] = []
    for item in grouped.values():
        used = item["peak_used_value"]
        provisioned = item["provisioned_value"]
        utilization = (used / provisioned * 100) if used is not None and provisioned else None
        item["utilization_value"] = utilization
        item["utilization"] = format_percent(utilization)
        highlights.append(item)

    active = [item for item in highlights if (item["peak_used_value"] or 0) > 0]
    selected = active or highlights
    selected.sort(
        key=lambda item: (
            item["utilization_value"] is None,
            -(item["utilization_value"] or 0),
            -(item["peak_used_value"] or 0),
            str(item["package"]),
            str(item["usage_type"]),
        )
    )
    return selected[:limit]


def application_context_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        source = "Inventory only" if row.get("source") == "application_inventory" else "Grouped usage"
        result.append(
            {
                "id": row.get("id", ""),
                "name": row.get("name", ""),
                "coverage": source,
                "v_cpu": row.get("v_cpu", ""),
                "nodes": row.get("nodes", ""),
                "containers": row.get("containers", ""),
                "agents": row.get("agents", ""),
            }
        )
    return result


def auth_context_is_actionable(report: dict[str, Any]) -> bool:
    if any(result.status_code == 403 for result in report.get("endpoint_results", [])):
        return True
    for warning in report.get("warnings", []):
        text = str(warning)
        if "API Client" in text or "permission" in text or "403" in text:
            return True
    return False


def write_csv(path: Path, sections: dict[str, list[dict[str, Any]]]) -> None:
    def csv_safe(value: Any) -> Any:
        if isinstance(value, (dict, list)):
            value = json.dumps(value, sort_keys=True)
        if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
            return "'" + value
        return value

    fieldnames = [
        "section",
        "source",
        "account_id",
        "license_rule",
        "package",
        "usage_type",
        "timestamp",
        "provisioned",
        "used",
        "registered_type",
        "registered",
        "id",
        "name",
        "v_cpu",
        "nodes",
        "containers",
        "agents",
        "type",
        "kind",
        "family",
        "license_units",
        "start_date",
        "expiration_date",
        "filters",
        "limits",
        "tags",
        "enabled",
        "total_licenses",
        "peak_usage",
        "entitlements",
        "constraints",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for section, rows in sections.items():
            for row in rows:
                safe_row = redact(row)
                if isinstance(safe_row, dict):
                    safe_row["section"] = section
                    writer.writerow({key: csv_safe(value) for key, value in safe_row.items()})


def render_markdown(report: dict[str, Any]) -> str:
    sections = report["sections"]
    warnings = report.get("warnings", [])
    notes_block = (
        "\n".join(f"- {redact_string(friendly_warning(str(warning)))}" for warning in warnings)
        if warnings
        else "- No collection limitations were observed."
    )
    account_usage_highlights = usage_highlight_rows(sections["usage"], "account")
    allocation_usage_highlights = usage_highlight_rows(sections["usage"], "allocation_usage")
    allocation_block = ""
    if allocation_usage_highlights:
        allocation_block = (
            "\n\n### Allocation Consumption\n\n"
            + markdown_table(
                ["source", "package", "usage_type", "peak_used", "latest_used", "provisioned", "utilization", "peak_time"],
                allocation_usage_highlights,
                "- No allocation-level usage rows returned.",
            )
        )
    auth_context_block = ""
    if auth_context_is_actionable(report):
        auth_context_block = "\n\n### Permission Troubleshooting Context\n\n" + auth_context_table(
            report.get("auth_context", {})
        )
    return f"""# AppDynamics License Consumption Report

Generated: {report['generated_at']}

## Executive Summary

{markdown_table(['metric', 'value'], report_summary_rows(report), '- Report summary was not available.')}

## Consumption Highlights

The table below summarizes peak account-level consumption during the reporting window. The full timestamp-level export is available in the generated JSON and CSV files.

{markdown_table(['package', 'usage_type', 'peak_used', 'latest_used', 'provisioned', 'utilization', 'peak_time', 'samples'], account_usage_highlights, '- No account-level license consumption rows returned.')}
{allocation_block}

## Licensed Portfolio

{markdown_table(['name', 'family', 'type', 'kind', 'license_units', 'start_date', 'expiration_date'], sections['account_info'], '- No licensed package rows returned.')}

## Application Context

{markdown_table(['id', 'name', 'coverage', 'v_cpu', 'nodes', 'containers', 'agents'], application_context_rows(sections['applications']), '- Deep application usage was not requested or no application rows returned.')}

## Allocation Context

{markdown_table(['id', 'name', 'filters', 'limits', 'tags'], sections['allocations'], '- No allocation rows returned.')}

## License Rule Context

{markdown_table(['id', 'name', 'enabled', 'total_licenses', 'peak_usage', 'entitlements', 'constraints'], sections['license_rules'], '- No license rule rows returned. This is expected for tenants without legacy license-rule objects.')}

## Report Notes

{notes_block}

## Collection Appendix

### API Readback Status

{endpoint_table(report['endpoint_results'])}
{auth_context_block}
"""


def write_reports(out: Path, report: dict[str, Any], include_raw: bool) -> None:
    out.mkdir(parents=True, exist_ok=True)
    out.chmod(0o700)
    public_report = {
        key: value
        for key, value in report.items()
        if key not in {"raw_payloads", "endpoint_results"}
    }
    public_report["endpoint_results"] = [result.public(include_payload=False) for result in report["endpoint_results"]]
    (out / "license-usage-report.json").write_text(
        json.dumps(redact(public_report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (out / "license-usage-report.md").write_text(render_markdown(report), encoding="utf-8")
    write_csv(out / "license-usage-report.csv", report["sections"])
    for report_path in (
        out / "license-usage-report.json",
        out / "license-usage-report.md",
        out / "license-usage-report.csv",
    ):
        report_path.chmod(0o600)
    if include_raw:
        raw_dir = out / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_dir.chmod(0o700)
        for name, payload in report["raw_payloads"].items():
            safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("._") or "payload"
            (raw_dir / f"{safe_name}.json").write_text(
                json.dumps(redact(payload), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            (raw_dir / f"{safe_name}.json").chmod(0o600)


def fetch_report(args: argparse.Namespace) -> dict[str, Any]:
    if args.oauth_token_file:
        token = read_secret_file(args.oauth_token_file, "AppDynamics OAuth token file")
    else:
        if not args.account_name or not args.api_client_name:
            raise ConfigError("--account-name and --api-client-name are required when using --client-secret-file")
        token = oauth_token(args.controller_url, args.account_name, args.api_client_name, args.client_secret_file, args.timeout)
    auth_context = token_auth_context(token)

    client = AppDClient(args.controller_url, token, args.timeout)
    account_id = str(args.account_id)
    date_query = {
        "dateFrom": args.date_from,
        "dateTo": args.date_to,
        "granularityMinutes": args.granularity_minutes,
    }
    rich_usage_query = {
        **date_query,
        "includeEntityTypes": "true",
        "includeConsumptionBased": "true",
    }
    results: list[EndpointResult] = []
    warnings: list[str] = []
    raw_payloads: dict[str, Any] = {}

    account_info = client.get_json("account_info", f"/controller/licensing/v1/account/{account_id}/info")
    results.append(account_info)
    if account_info.ok:
        raw_payloads["account_info"] = account_info.payload

    account_usage = client.get_json(
        "account_usage",
        f"/controller/licensing/v1/usage/account/{account_id}",
        rich_usage_query,
    )
    results.append(account_usage)
    if account_usage.ok:
        raw_payloads["account_usage"] = account_usage.payload

    applications: EndpointResult | None = None
    grouped_app_usage: EndpointResult | None = None
    grouped_host_usage: EndpointResult | None = None
    allocations: EndpointResult | None = None
    license_rules: EndpointResult | None = None
    allocation_usage_results: list[EndpointResult] = []

    if args.deep:
        applications = client.get_json("applications", "/controller/rest/applications", {"output": "JSON"})
        results.append(applications)
        if applications.ok:
            raw_payloads["applications"] = applications.payload
        app_ids, app_warnings = collect_app_ids(applications.payload if applications and applications.ok else None, args.app_id, args.max_apps)
        warnings.extend(app_warnings)
        if app_ids:
            grouped_app_usage = client.get_json(
                "grouped_application_usage",
                f"/controller/licensing/v1/account/{account_id}/grouped-usage/application/by-id",
                [("appId", app_id) for app_id in app_ids] + [("includeAgents", "true")],
            )
            results.append(grouped_app_usage)
            if grouped_app_usage.ok:
                raw_payloads["grouped_application_usage"] = grouped_app_usage.payload
        else:
            warnings.append("No application IDs available for grouped application usage.")

        host_ids, host_warnings = collect_host_ids(
            grouped_app_usage.payload if grouped_app_usage and grouped_app_usage.ok else None,
            args.host_id,
            args.max_hosts,
        )
        warnings.extend(host_warnings)
        if host_ids:
            grouped_host_usage = client.get_json(
                "grouped_host_usage",
                f"/controller/licensing/v1/account/{account_id}/grouped-usage/host",
                [("hostId", host_id) for host_id in host_ids] + [("includeAgents", "true")],
            )
            results.append(grouped_host_usage)
            if grouped_host_usage.ok:
                raw_payloads["grouped_host_usage"] = grouped_host_usage.payload
        else:
            warnings.append("No host IDs available for grouped host usage.")

        allocations = client.get_json("allocations", f"/controller/licensing/v1/account/{account_id}/allocation")
        results.append(allocations)
        if allocations.ok:
            raw_payloads["allocations"] = allocations.payload
            allocation_items = [item for item in as_list(allocations.payload) if isinstance(item, dict)]
            if len(allocation_items) > args.max_allocations:
                warnings.append(
                    f"Allocation usage limited to first {args.max_allocations} of {len(allocation_items)} allocations."
                )
            for allocation in allocation_items[: args.max_allocations]:
                license_key = allocation.get("licenseKey")
                if not license_key:
                    continue
                allocation_name = str(allocation.get("name") or allocation.get("id") or "allocation")
                allocation_result = client.get_json(
                    f"allocation_usage:{allocation_name}",
                    f"/controller/licensing/v1/usage/account/{account_id}/allocation/{parse.quote(str(license_key), safe='')}",
                    {**date_query, "includeEntityTypes": "true"},
                )
                results.append(allocation_result)
                allocation_usage_results.append(allocation_result)
                if allocation_result.ok:
                    raw_payloads[f"allocation_usage_{allocation_name}"] = allocation_result.payload

        license_rules = client.get_json("license_rules", "/controller/mds/v1/license/rules")
        results.append(license_rules)
        if license_rules.ok:
            raw_payloads["license_rules"] = license_rules.payload

    useful_license_readbacks = [
        result
        for result in [account_info, account_usage, allocations, license_rules]
        if result is not None and result.ok
    ]
    if not useful_license_readbacks:
        warnings.append("No useful license readback succeeded; check API client permissions and account ID.")
    append_live_validation_warnings(warnings, auth_context, results, account_id)

    usage_rows = summarize_usage_payload(account_usage.payload, "account") if account_usage.ok else []
    for allocation_result in allocation_usage_results:
        if allocation_result.ok:
            usage_rows.extend(summarize_usage_payload(allocation_result.payload, allocation_result.name))

    application_rows = summarize_grouped_usage(grouped_app_usage.payload, "application") if grouped_app_usage and grouped_app_usage.ok else []
    if not application_rows and applications and applications.ok:
        application_rows = summarize_application_inventory(applications.payload)

    sections = {
        "account_info": summarize_account_info(account_info.payload) if account_info.ok else [],
        "usage": usage_rows,
        "applications": application_rows,
        "hosts": summarize_grouped_usage(grouped_host_usage.payload, "host") if grouped_host_usage and grouped_host_usage.ok else [],
        "allocations": summarize_allocations(allocations.payload) if allocations and allocations.ok else [],
        "license_rules": summarize_license_rules(license_rules.payload) if license_rules and license_rules.ok else [],
    }
    return {
        "generated_at": iso_utc(datetime.now(timezone.utc)),
        "inputs": {
            "controller_url": args.controller_url.rstrip("/"),
            "account_name": args.account_name,
            "account_id": account_id,
            "date_from": args.date_from,
            "date_to": args.date_to,
            "granularity_minutes": args.granularity_minutes,
            "deep": args.deep,
        },
        "warnings": warnings,
        "auth_context": auth_context,
        "sections": sections,
        "endpoint_results": results,
        "raw_payloads": raw_payloads,
        "succeeded": bool(useful_license_readbacks),
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    reject_direct_secret_args(argv)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    parser = argparse.ArgumentParser(description="Poll AppDynamics Controller license usage APIs and render reports.")
    parser.add_argument("--controller-url", default=env_default("APPD_CONTROLLER_URL"), required=not bool(env_default("APPD_CONTROLLER_URL")))
    parser.add_argument("--account-name", default=env_default("APPD_ACCOUNT_NAME"))
    parser.add_argument("--account-id", default=env_default("APPD_ACCOUNT_ID"), required=not bool(env_default("APPD_ACCOUNT_ID")))
    parser.add_argument("--api-client-name", default=env_default("APPD_API_CLIENT_NAME"))
    parser.add_argument("--client-secret-file", default=env_default("APPD_OAUTH_CLIENT_SECRET_FILE"))
    parser.add_argument("--oauth-token-file", default=env_default("APPD_OAUTH_TOKEN_FILE"))
    parser.add_argument("--from", dest="date_from", default=env_default("APPD_LICENSE_REPORT_FROM", iso_utc(now - timedelta(hours=24))))
    parser.add_argument("--to", dest="date_to", default=env_default("APPD_LICENSE_REPORT_TO", iso_utc(now)))
    parser.add_argument("--granularity-minutes", type=int, default=int(env_default("APPD_LICENSE_GRANULARITY_MINUTES", "60")))
    parser.add_argument("--deep", action="store_true", default=env_default("APPD_LICENSE_DEEP", "").lower() in {"1", "true", "yes"})
    parser.add_argument("--app-id", action="append", default=[])
    parser.add_argument("--host-id", action="append", default=[])
    parser.add_argument("--max-apps", type=int, default=int(env_default("APPD_LICENSE_MAX_APPS", "50")))
    parser.add_argument("--max-hosts", type=int, default=int(env_default("APPD_LICENSE_MAX_HOSTS", "50")))
    parser.add_argument("--max-allocations", type=int, default=int(env_default("APPD_LICENSE_MAX_ALLOCATIONS", "25")))
    parser.add_argument("--include-raw", action="store_true", default=env_default("APPD_LICENSE_INCLUDE_RAW", "").lower() in {"1", "true", "yes"})
    parser.add_argument("--timeout", type=int, default=int(env_default("APPD_TIMEOUT_SECONDS", "30")))
    parser.add_argument("--output-dir", default=env_default("APPD_LICENSE_REPORT_OUTPUT_DIR", "./appd-license-report"))
    args = parser.parse_args(argv)

    args.controller_url = normalize_controller_url(args.controller_url)
    try:
        account_id = int(str(args.account_id))
    except ValueError as exc:
        raise ConfigError(
            "--account-id must be the numeric AppDynamics License API accountId; do not use GUID-like OAuth acctId/tntId values"
        ) from exc
    if account_id <= 0:
        raise ConfigError("--account-id must be a positive AppDynamics License API accountId")
    if not args.account_name:
        raise ConfigError("--account-name is required")
    if args.granularity_minutes <= 0:
        raise ConfigError("--granularity-minutes must be greater than zero")
    if args.max_apps <= 0 or args.max_hosts <= 0 or args.max_allocations <= 0:
        raise ConfigError("--max-apps, --max-hosts, and --max-allocations must be greater than zero")
    if args.oauth_token_file and args.client_secret_file:
        raise ConfigError("Use either --oauth-token-file or --client-secret-file, not both")
    if not args.oauth_token_file and not args.client_secret_file:
        raise ConfigError("Set --client-secret-file or --oauth-token-file")
    args.date_from = parse_iso8601(args.date_from, "--from")
    args.date_to = parse_iso8601(args.date_to, "--to")
    if args.date_from >= args.date_to:
        raise ConfigError("--from must be earlier than --to")
    return args


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
        report = fetch_report(args)
        write_reports(Path(args.output_dir), report, args.include_raw)
    except ConfigError as exc:
        print(f"FAIL: {redact_string(str(exc))}", file=sys.stderr)
        return 2
    if not report["succeeded"]:
        print(f"FAIL: no useful license readback succeeded; reports written to {args.output_dir}", file=sys.stderr)
        return 1
    print(f"Wrote AppDynamics license usage report to {args.output_dir}")
    if report["warnings"]:
        for warning in report["warnings"]:
            print(f"WARN: {redact_string(warning)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

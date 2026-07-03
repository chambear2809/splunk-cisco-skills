#!/usr/bin/env python3
"""Splunk Observability Cloud /v2/integration client for AWSCloudWatch.

Wraps the public REST API documented at:
- https://dev.splunk.com/observability/reference/api/integrations/latest
- https://docs.splunk.com/en/splunk-observability-cloud/manage-data/connect-to-your-cloud-service-provider/connect-to-aws/connect-to-aws-using-the-splunk-api

Key conventions (verified against `o11y_dashboard_api.py` /
`o11y_native_api.py` patterns in this repo):

- Base URL: `https://api.<realm>.observability.splunkcloud.com/v2`.
- Auth header: `X-SF-Token: <admin user API access token>`.
- Token reads from chmod-600 file ONLY -- never accepted as a CLI flag.
- Retry on transient statuses {429, 502, 503, 504} with `Retry-After` honored,
  exponential backoff with jitter, `O11Y_MAX_RETRIES` env override.
- All apply steps recorded to ``apply-state.json`` (chmod 600) with secrets
  scrubbed via the ``_apply_state`` redactor.
- PUT body strips read-back fields (``metricStreamsSyncState``, ``largeVolume``,
  ``created``, ``lastUpdated``, ``creator``, ``lastUpdatedBy``,
  ``lastUpdatedByName``, ``createdByName``, ``id``).
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _apply_state import append_step, read_secret_file, redact, write_private_json  # noqa: E402

_RETRYABLE_STATUSES = {429, 502, 503, 504}
SUPPORTED_REALMS = {
    "us0",
    "us1",
    "us2",
    "us3",
    "eu0",
    "eu1",
    "eu2",
    "au0",
    "jp0",
    "sg0",
}

# Read-back fields the renderer strips before PUT.
READ_BACK_FIELDS: tuple[str, ...] = (
    "metricStreamsSyncState",
    "largeVolume",
    "created",
    "lastUpdated",
    "creator",
    "lastUpdatedBy",
    "lastUpdatedByName",
    "createdByName",
    "id",
)


class ApiError(Exception):
    """Raised when an API call fails."""


class _NoRedirectHandler(HTTPRedirectHandler):
    """Refuse redirects so the X-SF-Token never moves to another URL."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201
        return None


def _validate_api_url(url: str) -> None:
    """Allow authenticated calls only to a supported realm's HTTPS API host."""
    parsed = urllib.parse.urlsplit(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ApiError("Splunk Observability API URL contains an invalid port") from exc
    allowed_hosts = {
        f"api.{realm}.observability.splunkcloud.com" for realm in SUPPORTED_REALMS
    }
    if (
        parsed.scheme.lower() != "https"
        or parsed.hostname not in allowed_hosts
        or port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or any(ch.isspace() for ch in url)
    ):
        raise ApiError(
            "authenticated Splunk Observability API requests require a supported "
            "https://api.<realm>.observability.splunkcloud.com URL without embedded "
            "credentials, a nonstandard port, fragments, or whitespace"
        )


def _max_retries() -> int:
    raw = os.environ.get("O11Y_MAX_RETRIES")
    if raw is None:
        return 4
    try:
        value = int(raw)
    except ValueError:
        return 4
    return max(1, value)


def _retry_after_seconds(exc: HTTPError, attempt: int) -> float:
    retry_after = exc.headers.get("Retry-After") if exc.headers else None
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except (TypeError, ValueError):
            pass
    return min(30.0, (2.0 ** attempt) + random.random())


def _request(method: str, url: str, token: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    _validate_api_url(url)
    headers = {
        "X-SF-Token": token,
        "Accept": "application/json",
        "User-Agent": "splunk-observability-aws-integration/1 (+splunk-cisco-skills)",
    }
    data: bytes | None = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method)
    opener = build_opener(_NoRedirectHandler())

    max_attempts = _max_retries()
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            with opener.open(request, timeout=60) as response:
                text = response.read().decode("utf-8")
                if not text:
                    return {}
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return {"_raw": text}
        except HTTPError as exc:
            last_exc = exc
            if exc.code in _RETRYABLE_STATUSES and attempt < max_attempts - 1:
                time.sleep(_retry_after_seconds(exc, attempt))
                continue
            request_id = ""
            if exc.headers:
                request_id = exc.headers.get("X-Request-Id") or exc.headers.get("X-Amzn-RequestId") or ""
            suffix = f" (request-id {request_id})" if request_id else ""
            raise ApiError(f"{method} {url} -> HTTP {exc.code}{suffix}; response body suppressed") from exc
        except URLError as exc:
            last_exc = exc
            if attempt < max_attempts - 1:
                time.sleep(min(30.0, (2.0 ** attempt) + random.random()))
                continue
            raise ApiError(f"{method} {url} -> URLError: {exc}") from exc
    raise ApiError(f"{method} {url} exhausted retries: {last_exc}")


def _base_url(realm: str) -> str:
    if realm not in SUPPORTED_REALMS:
        raise ApiError(
            f"unsupported Splunk Observability realm {realm!r}; allowed: "
            f"{', '.join(sorted(SUPPORTED_REALMS))}"
        )
    return f"https://api.{realm}.observability.splunkcloud.com/v2"


def _strip_read_back(integration: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in integration.items() if k not in READ_BACK_FIELDS}


# ---------------------------------------------------------------------------
# Public API operations.
# ---------------------------------------------------------------------------


def list_aws_integrations(realm: str, token: str) -> list[dict[str, Any]]:
    """List every AWS integration using server filtering and bounded pagination."""

    limit = 1000
    offset = 0
    collected: list[dict[str, Any]] = []
    for _page in range(100):
        query = urllib.parse.urlencode(
            {"type": "AWSCloudWatch", "limit": limit, "offset": offset}
        )
        response = _request("GET", f"{_base_url(realm)}/integration?{query}", token)
        if isinstance(response, list):
            page = response
            total = len(page)
        elif isinstance(response, dict):
            page = response.get("results")
            if page is None:
                page = response.get("items") or []
            total = response.get("count")
        else:
            raise ApiError("GET /integration returned an unsupported response shape")
        if not isinstance(page, list) or not all(isinstance(item, dict) for item in page):
            raise ApiError("GET /integration returned a malformed integration page")
        collected.extend(
            item for item in page if item.get("type") == "AWSCloudWatch"
        )
        offset += len(page)
        if isinstance(total, int):
            if total < 0:
                raise ApiError("GET /integration returned a negative count")
            if offset >= total:
                break
        elif len(page) < limit:
            break
        if not page:
            raise ApiError("GET /integration pagination stopped before the advertised count")
    else:
        raise ApiError("GET /integration exceeded the 100-page safety bound")
    return collected


def validate_integration_credentials(realm: str, token: str, integration_id: str) -> None:
    """Ask Splunk Observability to validate the integration's live credentials."""

    if not integration_id or any(character.isspace() for character in integration_id):
        raise ApiError("live AWSCloudWatch integration has an invalid id")
    encoded_id = urllib.parse.quote(integration_id, safe="")
    _request("GET", f"{_base_url(realm)}/integration/validate/{encoded_id}", token)


def validate_live_integration(
    integrations: list[dict[str, Any]],
    desired: dict[str, Any],
    expected_aws_account_id: str = "",
) -> dict[str, Any]:
    """Require one enabled live object matching the rendered identity and scope."""

    name = str(desired.get("name") or "")
    if not name:
        raise ApiError("rendered AWS integration payload has no name")
    matches = [item for item in integrations if item.get("name") == name]
    if not matches:
        raise ApiError(f"no live AWSCloudWatch integration matches rendered name {name!r}")
    if len(matches) != 1:
        raise ApiError(f"multiple live AWSCloudWatch integrations match rendered name {name!r}")

    live = matches[0]
    if not live.get("id"):
        raise ApiError(f"live AWSCloudWatch integration {name!r} has no server-assigned id")
    if live.get("enabled") is not True:
        raise ApiError(f"live AWSCloudWatch integration {name!r} is not enabled")

    expected_auth = str(desired.get("authMethod") or "")
    if str(live.get("authMethod") or "") != expected_auth:
        raise ApiError(f"live AWSCloudWatch integration {name!r} has the wrong authMethod")

    expected_regions = desired.get("regions")
    live_regions = live.get("regions")
    if (
        not isinstance(expected_regions, list)
        or not all(isinstance(region, str) and region for region in expected_regions)
        or not isinstance(live_regions, list)
        or not all(isinstance(region, str) and region for region in live_regions)
        or sorted(set(live_regions)) != sorted(set(expected_regions))
        or len(expected_regions) != len(set(expected_regions))
        or len(live_regions) != len(set(live_regions))
    ):
        raise ApiError(f"live AWSCloudWatch integration {name!r} regions do not match the rendered scope")

    if expected_auth == "ExternalId":
        if not re.fullmatch(r"[0-9]{12}", expected_aws_account_id):
            raise ApiError("a 12-digit expected AWS account ID is required for ExternalId validation")
        role_arn = str(live.get("roleArn") or live.get("roleARN") or "")
        role_match = re.fullmatch(
            r"arn:(?:aws|aws-us-gov|aws-cn):iam::([0-9]{12}):role/(.+)",
            role_arn,
        )
        if not role_match or role_match.group(1) != expected_aws_account_id:
            raise ApiError(
                f"live AWSCloudWatch integration {name!r} roleArn does not belong to the expected AWS account"
            )
        expected_role_arn = str(desired.get("roleArn") or "")
        if expected_role_arn and "${" not in expected_role_arn and role_arn != expected_role_arn:
            raise ApiError(
                f"live AWSCloudWatch integration {name!r} roleArn does not match the rendered role"
            )

    def normalized_strings(value: Any) -> list[str] | None:
        if value is None:
            return []
        if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
            return None
        if len(value) != len(set(value)):
            return None
        return sorted(value)

    for field, aliases in (
        ("services", ("services",)),
        ("customCloudWatchNamespaces", ("customCloudWatchNamespaces", "customCloudwatchNamespaces")),
    ):
        expected_value = normalized_strings(desired.get(field))
        live_raw = next((live[key] for key in aliases if key in live), None)
        live_value = normalized_strings(live_raw)
        if expected_value is None or live_value is None or live_value != expected_value:
            raise ApiError(f"live AWSCloudWatch integration {name!r} field {field} does not match")

    def canonical_list(value: Any, *, sort_stats: bool = False) -> list[str] | None:
        if value is None:
            return []
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            return None
        normalized = []
        for item in value:
            copy = dict(item)
            if sort_stats and "stats" in copy:
                stats = copy["stats"]
                if not isinstance(stats, list) or not all(isinstance(stat, str) for stat in stats):
                    return None
                copy["stats"] = sorted(stats)
            normalized.append(json.dumps(copy, sort_keys=True, separators=(",", ":")))
        return sorted(normalized)

    for field in ("namespaceSyncRules", "customNamespaceSyncRules", "metricStatsToSyncs"):
        sort_stats = field == "metricStatsToSyncs"
        if canonical_list(live.get(field), sort_stats=sort_stats) != canonical_list(
            desired.get(field), sort_stats=sort_stats
        ):
            raise ApiError(f"live AWSCloudWatch integration {name!r} field {field} does not match")

    integer_defaults = {
        "pollRate": 300_000,
        "metadataPollRate": 900_000,
        "inactiveMetricsPollRate": 1_200_000,
    }
    for field, default in integer_defaults.items():
        live_value = live.get(field, default)
        desired_value = desired.get(field, default)
        if (
            isinstance(live_value, bool)
            or not isinstance(live_value, int)
            or isinstance(desired_value, bool)
            or not isinstance(desired_value, int)
            or live_value != desired_value
        ):
            raise ApiError(f"live AWSCloudWatch integration {name!r} field {field} does not match")

    boolean_defaults = {
        "importCloudWatch": True,
        "enableAwsUsage": False,
        "enableCheckLargeVolume": True,
        "syncCustomNamespacesOnly": False,
        "syncLoadBalancerTargetGroupTags": False,
        "ignoreAllStatusMetrics": False,
        "collectOnlyRecommendedStats": False,
    }
    for field, default in boolean_defaults.items():
        live_value = live.get(field, default)
        desired_value = desired.get(field, default)
        if not isinstance(live_value, bool) or not isinstance(desired_value, bool) or live_value != desired_value:
            raise ApiError(f"live AWSCloudWatch integration {name!r} field {field} does not match")

    desired_streams = desired.get("useMetricStreamsSync") is True
    live_stream_state = str(live.get("metricStreamsSyncState") or "")
    if desired_streams and live_stream_state != "ENABLED":
        raise ApiError(f"live AWSCloudWatch integration {name!r} metric stream sync is not enabled")
    if not desired_streams and live_stream_state != "DISABLED":
        raise ApiError(f"live AWSCloudWatch integration {name!r} is not in polling-only mode")
    desired_external = desired.get("metricStreamsManagedExternally") is True
    live_external = live.get("metricStreamsManagedExternally", False)
    if not isinstance(live_external, bool) or live_external != desired_external:
        raise ApiError(
            f"live AWSCloudWatch integration {name!r} metric-stream ownership does not match the rendered scope"
        )
    return live


def get_integration(realm: str, token: str, integration_id: str) -> dict[str, Any]:
    url = f"{_base_url(realm)}/integration/{urllib.parse.quote(integration_id, safe='')}"
    return _request("GET", url, token)


def create_integration(realm: str, token: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{_base_url(realm)}/integration"
    body = _strip_read_back(payload)
    return _request("POST", url, token, body)


def update_integration(realm: str, token: str, integration_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{_base_url(realm)}/integration/{urllib.parse.quote(integration_id, safe='')}"
    body = _strip_read_back(payload)
    return _request("PUT", url, token, body)


def delete_integration(realm: str, token: str, integration_id: str) -> dict[str, Any]:
    url = f"{_base_url(realm)}/integration/{urllib.parse.quote(integration_id, safe='')}"
    return _request("DELETE", url, token)


# ---------------------------------------------------------------------------
# Higher-level operations used by the rendered apply scripts.
# ---------------------------------------------------------------------------


def upsert(
    realm: str,
    token: str,
    payload: dict[str, Any],
    state_dir: Path,
    *,
    aws_access_key_id_file: str = "",
    aws_secret_access_key_file: str = "",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Idempotent create-or-update keyed on integration name."""
    name = payload.get("name") or ""
    if not name:
        raise ApiError("payload.name is required")
    idempotency_key = f"integration-upsert:{name}"

    auth_method = str(payload.get("authMethod", ""))
    if auth_method == "SecurityToken":
        if not aws_access_key_id_file or not aws_secret_access_key_file:
            raise ApiError(
                "SecurityToken apply requires --aws-access-key-id-file and "
                "--aws-secret-access-key-file."
            )
        try:
            payload = {
                **payload,
                "token": read_secret_file(aws_access_key_id_file),
                "key": read_secret_file(aws_secret_access_key_file),
                "enabled": True,
            }
        except (PermissionError, ValueError) as exc:
            raise ApiError(str(exc)) from exc
    elif auth_method == "ExternalId":
        # A new ExternalId integration must first be created disabled so its
        # server-generated externalId can be placed in the IAM trust policy.
        # This client will update an existing integration, but refuses to
        # perform only the first half of a new two-phase onboarding.
        payload = {**payload, "enabled": True}
    else:
        raise ApiError(f"unsupported AWS authMethod {auth_method!r}")

    if dry_run:
        result = {"result": "dry-run", "name": name, "would_send": redact(payload)}
        if auth_method == "ExternalId":
            result["precondition"] = (
                "Only an existing integration with a concrete roleArn can be updated; "
                "new ExternalId onboarding remains a two-phase handoff."
            )
        return result

    existing = list_aws_integrations(realm, token)
    match = next((i for i in existing if i.get("name") == name), None)

    if match:
        if auth_method == "ExternalId":
            role_arn = str(payload.get("roleArn", ""))
            if not role_arn or "${" in role_arn:
                role_arn = str(match.get("roleArn", ""))
            if not role_arn:
                raise ApiError(
                    "existing ExternalId integration has no concrete roleArn; complete the IAM handoff first"
                )
            payload = {**payload, "roleArn": role_arn, "enabled": True}
        merged = {**match, **payload}
        merged["id"] = match["id"]
        merged["enabled"] = bool(payload.get("enabled", True))
        result = update_integration(realm, token, match["id"], merged)
        append_step(state_dir, "integration", "update", idempotency_key, "success", redact(result))
        return {"result": "updated", "name": name, "id": match["id"]}

    if auth_method == "ExternalId":
        raise ApiError(
            "new ExternalId onboarding is two-phase: create disabled to obtain "
            "externalId/sfxAwsAccountArn, deploy the matching IAM trust role, then "
            "PUT roleArn with enabled=true. Follow 01-authentication.md; no integration "
            "was created."
        )
    result = create_integration(realm, token, payload)
    append_step(state_dir, "integration", "create", idempotency_key, "success", redact(result))
    return {"result": "created", "name": name, "id": result.get("id")}


def discover(realm: str, token: str, output_path: Path | None, state_dir: Path) -> dict[str, Any]:
    """Read all AWS integrations and write a redacted snapshot."""
    integrations = list_aws_integrations(realm, token)
    snapshot = {
        "discovered_at_realm": realm,
        "count": len(integrations),
        "integrations": [redact(i) for i in integrations],
    }
    if output_path:
        write_private_json(output_path, snapshot)
    append_step(state_dir, "validation", "discover", f"discover:{realm}", "success", {"count": len(integrations)})
    return snapshot


def diff(spec_payload: dict[str, Any], live_payload: dict[str, Any]) -> dict[str, list[str]]:
    """Compare spec vs live and bucket per the drift-handling design."""
    safe_to_converge: list[str] = []
    operator_confirm: list[str] = []
    adopt_from_live: list[str] = []

    sensitive = {"useMetricStreamsSync", "metricStreamsManagedExternally", "regions", "authMethod", "roleArn"}
    spec_clean = _strip_read_back(spec_payload)
    live_clean = _strip_read_back(live_payload)

    spec_keys = set(spec_clean) - {"enabled", "id"}
    live_keys = set(live_clean) - {"enabled", "id"}

    for key in spec_keys:
        if key not in live_clean:
            safe_to_converge.append(f"{key} (spec sets {spec_clean[key]!r}, live unset)")
        elif spec_clean[key] != live_clean[key]:
            bucket = operator_confirm if key in sensitive else safe_to_converge
            bucket.append(f"{key} (spec={spec_clean[key]!r} live={live_clean[key]!r})")
    for key in live_keys - spec_keys:
        adopt_from_live.append(f"{key} (live={live_clean[key]!r}, spec leaves unset)")

    return {
        "safe_to_converge": safe_to_converge,
        "operator_confirm_required": operator_confirm,
        "adopt_from_live": adopt_from_live,
    }


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


_REJECTED_SECRET_FLAGS: tuple[str, ...] = (
    "--token", "--access-token", "--api-token", "--o11y-token", "--admin-token",
    "--sf-token", "--external-id", "--aws-access-key-id", "--aws-secret-access-key",
    "--aws-secret-key", "--password",
)


def _reject_direct_secret_flags() -> None:
    for arg in sys.argv[1:]:
        # Match exact flag (`--token`) or `--token=...` form.
        flag = arg.split("=", 1)[0]
        if flag in _REJECTED_SECRET_FLAGS:
            print(
                f"FAIL: refusing direct-secret flag {flag}. Use --token-file PATH "
                f"(chmod 600). For AWS access keys use --aws-access-key-id-file / "
                f"--aws-secret-access-key-file in setup.sh.",
                flush=True,
            )
            sys.exit(2)


def _parse() -> argparse.Namespace:
    _reject_direct_secret_flags()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--realm", required=True)
    p.add_argument("--token-file", required=True, help="chmod-600 file containing the admin user API access token")
    p.add_argument("--state-dir", required=True, help="rendered <output-dir>/state directory")
    p.add_argument("--payload-file", help="JSON payload for upsert")
    p.add_argument("--allow-loose-token-perms", action="store_true")
    p.add_argument("--aws-access-key-id-file", default="")
    p.add_argument("--aws-secret-access-key-file", default="")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "command",
        choices=("list", "get", "upsert", "delete", "discover", "validate"),
    )
    p.add_argument("--integration-id", default="")
    p.add_argument("--output", default="")
    p.add_argument("--expected-aws-account-id", default="")
    return p.parse_args()


def main() -> int:
    args = _parse()
    try:
        token = read_secret_file(args.token_file, allow_loose=args.allow_loose_token_perms)
    except (PermissionError, ValueError) as exc:
        print(f"FAIL: {exc}", flush=True)
        return 2

    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)

    try:
        if args.command == "list":
            items = list_aws_integrations(args.realm, token)
            print(json.dumps([redact(i) for i in items], indent=2))
        elif args.command == "validate":
            if not args.payload_file:
                raise ApiError("--payload-file is required for `validate`")
            desired = json.loads(Path(args.payload_file).read_text(encoding="utf-8"))
            items = list_aws_integrations(args.realm, token)
            name = str(desired.get("name") or "")
            matches = [item for item in items if item.get("name") == name]
            if len(matches) != 1 or not matches[0].get("id"):
                # Reuse the detailed validator's precise missing/duplicate/id error.
                validate_live_integration(matches, desired, args.expected_aws_account_id)
            integration_id = str(matches[0]["id"])
            detailed = get_integration(args.realm, token, integration_id)
            if not detailed or str(detailed.get("id") or "") != integration_id:
                raise ApiError("GET /integration/{id} did not return the selected AWS integration")
            live = validate_live_integration([detailed], desired, args.expected_aws_account_id)
            validate_integration_credentials(args.realm, token, str(live.get("id") or ""))
            print(
                json.dumps(
                    {
                        "result": "validated",
                        "name": live.get("name"),
                        "id": live.get("id"),
                        "enabled": live.get("enabled"),
                    },
                    indent=2,
                )
            )
        elif args.command == "get":
            if not args.integration_id:
                raise ApiError("--integration-id is required for `get`")
            print(json.dumps(redact(get_integration(args.realm, token, args.integration_id)), indent=2))
        elif args.command == "upsert":
            if not args.payload_file:
                raise ApiError("--payload-file is required for `upsert`")
            payload = json.loads(Path(args.payload_file).read_text(encoding="utf-8"))
            result = upsert(
                args.realm,
                token,
                payload,
                state_dir,
                aws_access_key_id_file=args.aws_access_key_id_file,
                aws_secret_access_key_file=args.aws_secret_access_key_file,
                dry_run=args.dry_run,
            )
            print(json.dumps(result, indent=2))
        elif args.command == "delete":
            if not args.integration_id:
                raise ApiError("--integration-id is required for `delete`")
            result = delete_integration(args.realm, token, args.integration_id)
            append_step(state_dir, "integration", "delete", f"integration-delete:{args.integration_id}", "success", redact(result))
            print(json.dumps(redact(result), indent=2))
        elif args.command == "discover":
            output_path = Path(args.output) if args.output else None
            snapshot = discover(args.realm, token, output_path, state_dir)
            print(json.dumps(snapshot, indent=2))
    except ApiError as exc:
        print(f"FAIL: {exc}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

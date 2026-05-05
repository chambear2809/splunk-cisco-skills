#!/usr/bin/env python3
"""Splunk Observability Cloud dashboard API helper using token files only."""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


# Maximum retry attempts for transient HTTP errors (429 / 502 / 503 / 504).
# Override at test time via the O11Y_MAX_RETRIES env var.
def _max_retries() -> int:
    raw = os.environ.get("O11Y_MAX_RETRIES")
    if raw is None:
        return 4
    try:
        value = int(raw)
    except ValueError:
        return 4
    return max(1, value)


_RETRYABLE_STATUSES = {429, 502, 503, 504}


class ApiError(Exception):
    """Raised when an API call fails."""


def read_token(path: Path) -> str:
    token = path.read_text(encoding="utf-8").strip()
    if not token:
        raise ApiError(f"Token file is empty: {path}")
    return token


def _retry_after_seconds(exc: HTTPError, attempt: int) -> float:
    # Honor Retry-After when present (RFC-7231 numeric seconds form).
    retry_after = exc.headers.get("Retry-After") if exc.headers else None
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except (TypeError, ValueError):
            pass
    # Exponential backoff with jitter: 1s, 2s, 4s, 8s + random 0-1s.
    return min(30.0, (2.0 ** attempt) + random.random())


def request_json(method: str, url: str, token: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None
    headers = {
        "X-SF-Token": token,
        "Accept": "application/json",
        "User-Agent": "splunk-observability-dashboard-builder/1 (+splunk-cisco-skills)",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method)
    max_attempts = _max_retries()
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            with urlopen(request, timeout=60) as response:  # noqa: S310 - operator-supplied API URL
                text = response.read().decode("utf-8")
                return json.loads(text) if text else {}
        except HTTPError as exc:
            last_exc = exc
            # Retry on transient statuses; non-retryable errors raise immediately.
            if exc.code in _RETRYABLE_STATUSES and attempt < max_attempts - 1:
                time.sleep(_retry_after_seconds(exc, attempt))
                continue
            text = exc.read().decode("utf-8", errors="replace")
            raise ApiError(f"{method} {url} failed with HTTP {exc.code}: {text}") from exc
        except URLError as exc:
            last_exc = exc
            # Network errors get one retry pass.
            if attempt < max_attempts - 1:
                time.sleep(min(30.0, (2.0 ** attempt) + random.random()))
                continue
            raise ApiError(f"{method} {url} failed: {exc.reason}") from exc
    # Defensive: should not reach here, but surface the last error if we do.
    raise ApiError(f"{method} {url} failed after {max_attempts} attempts: {last_exc}")


def api_base(realm: str) -> str:
    if not realm:
        raise ApiError("realm is required.")
    return f"https://api.{realm}.observability.splunkcloud.com/v2"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def safe_plan_path(plan_dir: Path, relative: str) -> Path:
    """Resolve a plan-relative file path and refuse to escape plan_dir.

    The renderer writes payload files under plan_dir and records their
    relative paths inside apply-plan.json. A malicious or buggy plan
    file could otherwise smuggle ``../../../etc/passwd`` into a
    ``payload_file`` field, and ``plan_dir / "../../etc/passwd"`` would
    happily resolve to a real path outside the plan tree. We reject any
    candidate that is not contained under the resolved plan directory.
    """
    if not isinstance(relative, str) or not relative:
        raise ApiError(f"plan payload file must be a non-empty string (got {relative!r})")
    plan_root = plan_dir.resolve()
    candidate = (plan_root / relative).resolve()
    try:
        candidate.relative_to(plan_root)
    except ValueError as exc:
        raise ApiError(
            f"plan payload file {relative!r} escapes plan directory {plan_root}"
        ) from exc
    return candidate


def load_plan_json(plan_dir: Path, relative: str) -> dict[str, Any]:
    """Load a JSON file recorded in apply-plan.json with traversal protection."""
    return load_json(safe_plan_path(plan_dir, relative))


def replace_placeholders(value: Any, group_id: str, chart_ids: dict[str, str]) -> Any:
    if isinstance(value, str):
        if value == "${dashboard_group_id}":
            return group_id
        for key, chart_id in chart_ids.items():
            if value == f"${{chart:{key}}}":
                return chart_id
        return value
    if isinstance(value, list):
        return [replace_placeholders(item, group_id, chart_ids) for item in value]
    if isinstance(value, dict):
        return {key: replace_placeholders(child, group_id, chart_ids) for key, child in value.items()}
    return value


def merge_object(existing: dict[str, Any], rendered: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    merged.update(rendered)
    return merged


def require_update_ids(plan: dict[str, Any]) -> tuple[str, dict[str, str]]:
    dashboard_id = str(plan.get("dashboard", {}).get("id", "") or "")
    if not dashboard_id:
        raise ApiError("--update-existing requires dashboard.id in the dashboard spec.")
    chart_ids: dict[str, str] = {}
    for chart in plan.get("charts", []):
        key = str(chart.get("key", "") or "")
        chart_id = str(chart.get("id", "") or "")
        if not key:
            raise ApiError("--update-existing requires every chart plan item to have a key.")
        if not chart_id:
            raise ApiError(
                "--update-existing requires every chart to define chart_id "
                f"(missing for chart key {key!r})."
            )
        chart_ids[key] = chart_id
    return dashboard_id, chart_ids


def apply_plan(
    plan_dir: Path,
    realm: str,
    token_file: Path | None,
    dry_run: bool,
    update_existing: bool = False,
) -> dict[str, Any]:
    plan = load_json(plan_dir / "apply-plan.json")
    if update_existing:
        return reconcile_plan(plan_dir, plan, realm, token_file, dry_run)

    effective_realm = realm or plan.get("realm", "")
    base = api_base(effective_realm)
    if plan.get("mode") != "classic-api":
        raise ApiError("Only classic-api apply plans can be applied.")

    sequence = []
    group_info = plan["dashboard_group"]
    group_id = group_info.get("id", "")
    if group_id:
        sequence.append({"action": "use-dashboard-group", "id": group_id})
    else:
        sequence.append({"action": "create-dashboard-group", "payload_file": group_info["payload_file"]})

    for chart in plan["charts"]:
        sequence.append({"action": "create-chart", "key": chart["key"], "payload_file": chart["payload_file"]})
    sequence.append({"action": "create-dashboard", "payload_file": plan["dashboard"]["payload_file"]})

    if dry_run:
        return {"ok": True, "dry_run": True, "realm": effective_realm, "sequence": sequence}

    if token_file is None:
        raise ApiError("--token-file is required for live apply (only --dry-run can omit it).")
    token = read_token(token_file)
    if not group_id:
        group_payload = load_plan_json(plan_dir, group_info["payload_file"])
        group_response = request_json("POST", f"{base}/dashboardgroup", token, group_payload)
        group_id = str(group_response.get("id", ""))
        if not group_id:
            raise ApiError("Dashboard group creation response did not contain id.")

    chart_ids: dict[str, str] = {}
    for chart in plan["charts"]:
        payload = load_plan_json(plan_dir, chart["payload_file"])
        response = request_json("POST", f"{base}/chart", token, payload)
        chart_id = str(response.get("id", ""))
        if not chart_id:
            raise ApiError(f"Chart creation response for {chart['key']} did not contain id.")
        chart_ids[chart["key"]] = chart_id

    dashboard_payload = replace_placeholders(load_plan_json(plan_dir, plan["dashboard"]["payload_file"]), group_id, chart_ids)
    dashboard_response = request_json("POST", f"{base}/dashboard", token, dashboard_payload)
    dashboard_id = str(dashboard_response.get("id", ""))
    if not dashboard_id:
        raise ApiError("Dashboard creation response did not contain id.")

    return {
        "ok": True,
        "realm": effective_realm,
        "created_dashboard_group": not bool(group_info.get("id", "")),
        "dashboard_group_id": group_id,
        "chart_ids": chart_ids,
        "dashboard_id": dashboard_id,
    }


def reconcile_plan(
    plan_dir: Path,
    plan: dict[str, Any],
    realm: str,
    token_file: Path | None,
    dry_run: bool,
) -> dict[str, Any]:
    effective_realm = realm or plan.get("realm", "")
    base = api_base(effective_realm)
    if plan.get("mode") != "classic-api":
        raise ApiError("Only classic-api apply plans can be reconciled.")

    dashboard_id, chart_ids = require_update_ids(plan)
    group_info = plan["dashboard_group"]
    group_id = str(group_info.get("id", "") or "")
    sequence = [{"action": "fetch-dashboard", "id": dashboard_id}]
    if group_id:
        sequence.extend(
            [
                {"action": "fetch-dashboard-group", "id": group_id},
                {
                    "action": "update-dashboard-group",
                    "id": group_id,
                    "payload_file": group_info["payload_file"],
                },
            ]
        )
    else:
        sequence.append({"action": "use-current-dashboard-group", "from": dashboard_id})

    for chart in plan["charts"]:
        chart_id = chart_ids[chart["key"]]
        sequence.extend(
            [
                {"action": "fetch-chart", "key": chart["key"], "id": chart_id},
                {
                    "action": "update-chart",
                    "key": chart["key"],
                    "id": chart_id,
                    "payload_file": chart["payload_file"],
                },
            ]
        )
    sequence.append(
        {
            "action": "update-dashboard",
            "id": dashboard_id,
            "payload_file": plan["dashboard"]["payload_file"],
        }
    )

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "mode": "update-existing",
            "realm": effective_realm,
            "sequence": sequence,
        }

    if token_file is None:
        raise ApiError("--token-file is required for live apply (only --dry-run can omit it).")
    token = read_token(token_file)

    current_dashboard = request_json("GET", f"{base}/dashboard/{dashboard_id}", token)
    if not group_id:
        group = current_dashboard.get("group", {})
        group_dict = group if isinstance(group, dict) else {}
        group_id = str(
            current_dashboard.get("groupId")
            or current_dashboard.get("dashboardGroupId")
            or group_dict.get("id", "")
        )
    if not group_id:
        raise ApiError(
            "Could not determine dashboard group ID. Set dashboard_group.id in the spec."
        )

    if str(group_info.get("id", "") or ""):
        group_payload = load_plan_json(plan_dir, group_info["payload_file"])
        current_group = request_json("GET", f"{base}/dashboardgroup/{group_id}", token)
        request_json(
            "PUT",
            f"{base}/dashboardgroup/{group_id}",
            token,
            merge_object(current_group, group_payload),
        )

    for chart in plan["charts"]:
        chart_id = chart_ids[chart["key"]]
        current_chart = request_json("GET", f"{base}/chart/{chart_id}", token)
        chart_payload = load_plan_json(plan_dir, chart["payload_file"])
        request_json(
            "PUT",
            f"{base}/chart/{chart_id}",
            token,
            merge_object(current_chart, chart_payload),
        )

    dashboard_payload = replace_placeholders(
        load_plan_json(plan_dir, plan["dashboard"]["payload_file"]),
        group_id,
        chart_ids,
    )
    request_json(
        "PUT",
        f"{base}/dashboard/{dashboard_id}",
        token,
        merge_object(current_dashboard, dashboard_payload),
    )
    return {
        "ok": True,
        "mode": "update-existing",
        "realm": effective_realm,
        "created_dashboard_group": False,
        "dashboard_group_id": group_id,
        "chart_ids": chart_ids,
        "dashboard_id": dashboard_id,
    }


def require_live_validation_cleanup_plan(plan: dict[str, Any]) -> None:
    group_name = str(plan.get("dashboard_group", {}).get("name", "") or "")
    dashboard_name = str(plan.get("dashboard", {}).get("name", "") or "")
    names = [name for name in (group_name, dashboard_name) if name]
    if not names or any(not name.startswith("codex_live_validation") for name in names):
        raise ApiError(
            "cleanup is limited to codex_live_validation* dashboard plans. "
            "Use the Observability UI/API directly for non-validation dashboard cleanup."
        )


def delete_object(base: str, token: str, object_type: str, object_id: str) -> dict[str, Any]:
    endpoint_type = {
        "dashboard-group": "dashboardgroup",
    }.get(object_type, object_type)
    url = f"{base}/{endpoint_type}/{object_id}"
    try:
        request_json("DELETE", url, token)
        return {"status": "deleted"}
    except ApiError as exc:
        if "HTTP 404" in str(exc):
            return {"status": "already_absent"}
        raise


def cleanup_apply_result(
    apply_result: Path,
    realm: str,
    token_file: Path | None,
    dry_run: bool,
) -> dict[str, Any]:
    result = load_json(apply_result)
    plan_dir = apply_result.resolve().parent
    plan = load_json(plan_dir / "apply-plan.json")
    require_live_validation_cleanup_plan(plan)

    effective_realm = realm or result.get("realm") or plan.get("realm", "")
    base = api_base(str(effective_realm))
    plan_group = plan.get("dashboard_group", {})
    created_group = bool(result.get("created_dashboard_group"))
    if "created_dashboard_group" not in result:
        created_group = not bool(plan_group.get("id", "")) and bool(plan_group.get("name", ""))

    dashboard_id = str(result.get("dashboard_id", "") or "")
    group_id = str(result.get("dashboard_group_id", "") or "")
    raw_chart_ids = result.get("chart_ids", {})
    chart_ids: dict[str, str] = {}
    if isinstance(raw_chart_ids, dict):
        chart_ids = {str(key): str(value) for key, value in raw_chart_ids.items() if value}

    sequence: list[dict[str, str]] = []
    if dashboard_id:
        sequence.append({"action": "delete-dashboard", "id": dashboard_id})
    for key, chart_id in chart_ids.items():
        sequence.append({"action": "delete-chart", "key": key, "id": chart_id})
    if group_id and created_group:
        sequence.append({"action": "delete-dashboard-group", "id": group_id})
    elif group_id:
        sequence.append({"action": "keep-dashboard-group", "id": group_id})

    delete_steps = [item for item in sequence if item["action"].startswith("delete-")]
    if not delete_steps:
        raise ApiError(f"No cleanup object IDs found in apply result: {apply_result}")

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "mode": "cleanup",
            "realm": effective_realm,
            "sequence": sequence,
        }

    if token_file is None:
        raise ApiError("--token-file is required for live cleanup (only --dry-run can omit it).")
    token = read_token(token_file)
    deleted: list[dict[str, str]] = []
    for item in delete_steps:
        action = item["action"]
        object_type = action.removeprefix("delete-")
        object_id = item["id"]
        status = delete_object(base, token, object_type, object_id)
        deleted.append({**item, **status})

    return {
        "ok": True,
        "mode": "cleanup",
        "realm": effective_realm,
        "deleted": deleted,
        "kept": [item for item in sequence if item["action"].startswith("keep-")],
    }


def normalize_metric_query(query: str) -> str:
    query = query.strip()
    if not query:
        return ""
    if ":" in query:
        return query
    if re.fullmatch(r"[A-Za-z0-9_.-]+", query):
        return f"sf_metric:*{query}*"
    return query


def discover_metrics(realm: str, token_file: Path, query: str, limit: int) -> dict[str, Any]:
    token = read_token(token_file)
    params = {"limit": str(limit)}
    normalized_query = normalize_metric_query(query)
    if normalized_query:
        params["query"] = normalized_query
    url = f"{api_base(realm)}/metric?{urlencode(params)}"
    return request_json("GET", url, token)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--plan-dir", required=True, type=Path)
    apply_parser.add_argument("--realm", default="")
    # --token-file is only required for live apply; --dry-run can omit it
    # so CI preview-only jobs do not need a real token path on disk.
    apply_parser.add_argument("--token-file", type=Path, default=None)
    apply_parser.add_argument("--dry-run", action="store_true")
    apply_parser.add_argument("--update-existing", action="store_true")

    cleanup_parser = subparsers.add_parser("cleanup")
    cleanup_parser.add_argument("--apply-result", required=True, type=Path)
    cleanup_parser.add_argument("--realm", default="")
    cleanup_parser.add_argument("--token-file", type=Path, default=None)
    cleanup_parser.add_argument("--dry-run", action="store_true")

    discover_parser = subparsers.add_parser("discover-metrics")
    discover_parser.add_argument("--realm", required=True)
    discover_parser.add_argument("--token-file", required=True, type=Path)
    discover_parser.add_argument("--query", default="")
    discover_parser.add_argument("--limit", type=int, default=25)

    args = parser.parse_args()
    try:
        if args.command == "apply":
            if not args.dry_run and args.token_file is None:
                parser.error("apply requires --token-file unless --dry-run is set.")
            result = apply_plan(
                args.plan_dir,
                args.realm,
                args.token_file,
                args.dry_run,
                update_existing=args.update_existing,
            )
        elif args.command == "cleanup":
            if not args.dry_run and args.token_file is None:
                parser.error("cleanup requires --token-file unless --dry-run is set.")
            result = cleanup_apply_result(
                args.apply_result,
                args.realm,
                args.token_file,
                args.dry_run,
            )
        elif args.command == "discover-metrics":
            result = discover_metrics(args.realm, args.token_file, args.query, args.limit)
        else:
            parser.error("unknown command")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, json.JSONDecodeError, ApiError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

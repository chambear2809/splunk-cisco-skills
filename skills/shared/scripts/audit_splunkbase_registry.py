#!/usr/bin/env python3
"""Audit Splunkbase-backed app registry metadata.

The default mode is offline: it validates the registry's embedded metadata.
Use --live to fetch current public Splunkbase listings and compare latest
version, release date, and platform compatibility.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import sys
import urllib.request
from html import unescape
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = REPO_ROOT / "skills/shared/app_registry.json"
PLATFORM_VERSIONS_PATH = REPO_ROOT / "skills/shared/references/splunk_platform_versions.json"
USER_AGENT = "splunk-cisco-skills/platform-compatibility-audit"
VERSION_RE = re.compile(r"^(\d+(?:\.\d+)*(?:[.-][A-Za-z0-9]+)?)\b")
DATE_RE = re.compile(r"([A-Z][a-z]+ \d{1,2}, 20\d{2})")
TARGET_RE = re.compile(r"^(\d+)\.(\d+)(?:\.\d+)?$")
CLOUD_RELEASE_FIELDS = (
    "cloud_compatible",
    "install_method_single",
    "install_method_distributed",
)


def default_compatibility_target() -> str:
    payload = json.loads(PLATFORM_VERSIONS_PATH.read_text(encoding="utf-8"))
    target = str((payload.get("defaults") or {}).get("splunkbase_compatibility_target", "")).strip()
    if not target:
        raise ValueError(
            "defaults.splunkbase_compatibility_target is missing from "
            f"{PLATFORM_VERSIONS_PATH}"
        )
    return target


def normalize_compatibility_target(value: str) -> str:
    match = TARGET_RE.fullmatch(str(value).strip())
    if not match:
        raise argparse.ArgumentTypeError(
            "target Splunk version must use MAJOR.MINOR or MAJOR.MINOR.PATCH"
        )
    return f"{match.group(1)}.{match.group(2)}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit Splunkbase registry metadata.")
    parser.add_argument("--registry", default=str(REGISTRY_PATH))
    parser.add_argument(
        "--target-splunk-version",
        default=normalize_compatibility_target(default_compatibility_target()),
        type=normalize_compatibility_target,
        help="Platform compatibility target (default: shared platform-version contract).",
    )
    parser.add_argument("--live", action="store_true", help="Fetch public Splunkbase pages.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--max-workers", type=int, default=12)
    return parser.parse_args()


def clean_html(value: str) -> str:
    text = unescape(re.sub(r"<[^>]+>", " ", value))
    return re.sub(r"\s+", " ", text).strip()


def segment(text: str, label: str, stops: list[str]) -> str:
    stop_pattern = "|".join(re.escape(stop) for stop in stops)
    match = re.search(re.escape(label) + r"\s*(.*?)\s*(?=" + stop_pattern + r")", text)
    return match.group(1).strip(" :") if match else ""


def parse_platform_versions(value: str) -> list[str]:
    return re.findall(r"(?<!\d)\d+\.\d+(?!\d)", value or "")


def registry_apps(registry: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        app
        for app in registry.get("apps", [])
        if str(app.get("splunkbase_id", "")).strip().isdigit()
    ]


def release_objects(payload: Any) -> list[dict[str, Any]]:
    """Return release objects from supported Splunkbase API response shapes."""

    if isinstance(payload, list):
        releases = payload
    elif isinstance(payload, dict):
        # Preserve parse_cloud_release_metadata's existing wrapper fallbacks.
        releases = payload.get("releases") or payload.get("results") or [payload]
    else:
        releases = []
    return [item for item in releases if isinstance(item, dict)]


def parse_cloud_release_metadata(payload: Any) -> dict[str, Any]:
    """Extract optional Cloud install facts from a Splunkbase release response."""

    release = next(iter(release_objects(payload)), None)
    if release is None:
        raise ValueError("Splunkbase release API returned no release object")
    return {field: release.get(field) for field in CLOUD_RELEASE_FIELDS}


def parse_verified_platform_versions(payload: Any, verified_version: str) -> list[Any]:
    """Return the exact product_versions for a verified release, or [] if absent."""

    release = next(
        (
            item
            for item in release_objects(payload)
            if str(item.get("name", "")).strip() == str(verified_version).strip()
        ),
        None,
    )
    if release is None:
        return []
    product_versions = release.get("product_versions")
    return product_versions if isinstance(product_versions, list) else []


def fetch_release_payload(app_id: str) -> Any:
    url = f"https://splunkbase.splunk.com/api/v1/app/{app_id}/release/"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def fetch_cloud_release_metadata(app_id: str) -> dict[str, Any]:
    return parse_cloud_release_metadata(fetch_release_payload(app_id))


def fetch_splunkbase(
    app_id: str,
    include_cloud_metadata: bool = False,
    verified_release_version: str | None = None,
) -> dict[str, Any]:
    url = f"https://splunkbase.splunk.com/app/{app_id}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=25) as response:
        text = clean_html(response.read().decode("utf-8", "replace"))

    latest = segment(
        text,
        "Latest Version",
        ["Visibility", "Rating", "Downloads", "Platform Version", "Product"],
    )
    platform = segment(
        text,
        "Platform Version",
        ["Rating", "Downloads", "Product", "CIM Version", "Categories", "Built by"],
    )
    version_match = VERSION_RE.search(latest)
    date_match = DATE_RE.search(latest)
    result = {
        "splunkbase_id": app_id,
        "latest_version": version_match.group(1) if version_match else "",
        "latest_release_date": date_match.group(1) if date_match else "",
        "platform_versions": parse_platform_versions(platform),
        "platform_raw": platform,
        "url": url,
    }
    if verified_release_version is not None:
        release_payload = fetch_release_payload(app_id)
        if include_cloud_metadata:
            result.update(parse_cloud_release_metadata(release_payload))
        result["verified_platform_versions"] = parse_verified_platform_versions(
            release_payload,
            verified_release_version,
        )
    elif include_cloud_metadata:
        result.update(fetch_cloud_release_metadata(app_id))
    return result


def compatibility_status(platform_versions: list[str], target: str) -> str:
    return "supported" if target in platform_versions else "unsupported"


def audit_offline(apps: list[dict[str, Any]], target: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for app in apps:
        app_id = str(app.get("splunkbase_id", "")).strip()
        platforms = app.get("platform_versions")
        status = app.get("compatibility_status")
        expected = compatibility_status(platforms or [], target) if isinstance(platforms, list) else ""
        if not isinstance(platforms, list) or not all(isinstance(item, str) for item in platforms):
            findings.append({"id": app_id, "severity": "error", "field": "platform_versions", "message": "missing or invalid"})
        if status not in {"supported", "unsupported"}:
            findings.append({"id": app_id, "severity": "error", "field": "compatibility_status", "message": "missing or invalid"})
        elif expected and status != expected:
            findings.append(
                {
                    "id": app_id,
                    "severity": "error",
                    "field": "compatibility_status",
                    "message": f"{status} does not match platform_versions for {target}",
                }
            )
        if "cloud_compatible" in app:
            if not isinstance(app.get("cloud_compatible"), bool):
                findings.append(
                    {
                        "id": app_id,
                        "severity": "error",
                        "field": "cloud_compatible",
                        "message": "must be boolean when explicitly declared",
                    }
                )
            for field in ("install_method_single", "install_method_distributed"):
                if not isinstance(app.get(field), str) or not app[field].strip():
                    findings.append(
                        {
                            "id": app_id,
                            "severity": "error",
                            "field": field,
                            "message": "must be a non-empty string when cloud_compatible is declared",
                        }
                    )
            if app.get("cloud_compatible") is False:
                for field in ("install_method_single", "install_method_distributed"):
                    value = app.get(field)
                    if isinstance(value, str) and value.strip() and value != "rejected":
                        findings.append(
                            {
                                "id": app_id,
                                "severity": "error",
                                "field": field,
                                "message": "must be rejected when cloud_compatible is false",
                            }
                        )
        else:
            for field in ("install_method_single", "install_method_distributed"):
                if field in app and (
                    not isinstance(app.get(field), str) or not app[field].strip()
                ):
                    findings.append(
                        {
                            "id": app_id,
                            "severity": "error",
                            "field": field,
                            "message": "must be a non-empty string when explicitly declared",
                        }
                    )
        if app.get("latest_verified_version") != app.get("latest_release_version"):
            verified_platforms = app.get("verified_platform_versions")
            if not isinstance(verified_platforms, list) or not all(
                isinstance(item, str) for item in verified_platforms
            ):
                findings.append(
                    {
                        "id": app_id,
                        "severity": "error",
                        "field": "verified_platform_versions",
                        "message": (
                            "must be a list of strings when latest_verified_version "
                            "differs from latest_release_version"
                        ),
                    }
                )
        for field in (
            "latest_verified_version",
            "latest_verified_date",
            "latest_release_version",
            "latest_release_date",
            "last_verified_date",
        ):
            if not isinstance(app.get(field), str) or not app[field].strip():
                findings.append({"id": app_id, "severity": "error", "field": field, "message": "missing or invalid"})
    return findings


def audit_live(apps: list[dict[str, Any]], target: str, max_workers: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_id = {str(app["splunkbase_id"]).strip(): app for app in apps}
    live_entries: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_id = {
            executor.submit(
                fetch_splunkbase,
                app_id,
                any(field in app for field in CLOUD_RELEASE_FIELDS),
                (
                    str(app.get("latest_verified_version", "")).strip()
                    if app.get("latest_verified_version")
                    != app.get("latest_release_version")
                    else None
                ),
            ): app_id
            for app_id, app in by_id.items()
        }
        for future in concurrent.futures.as_completed(future_to_id):
            app_id = future_to_id[future]
            try:
                live_entries.append(future.result())
            except Exception as exc:  # noqa: BLE001 - surface fetch failure, keep auditing
                findings.append(
                    {
                        "id": app_id,
                        "app_name": by_id[app_id].get("app_name", ""),
                        "severity": "error",
                        "field": "live_fetch",
                        "message": f"live fetch failed: {exc}",
                    }
                )

    for live in live_entries:
        app = by_id[live["splunkbase_id"]]
        expected_status = compatibility_status(live["platform_versions"], target)
        comparisons = {
            "latest_release_version": live["latest_version"],
            "latest_release_date": live["latest_release_date"],
            "platform_versions": live["platform_versions"],
            "compatibility_status": expected_status,
        }
        for field in CLOUD_RELEASE_FIELDS:
            if field in app:
                comparisons[field] = live.get(field)
        if app.get("latest_verified_version") != app.get("latest_release_version"):
            comparisons["verified_platform_versions"] = live.get(
                "verified_platform_versions",
                [],
            )
        for field, expected in comparisons.items():
            actual = app.get(field)
            if actual != expected:
                findings.append(
                    {
                        "id": live["splunkbase_id"],
                        "app_name": app.get("app_name", ""),
                        "severity": "error",
                        "field": field,
                        "actual": actual,
                        "expected": expected,
                    }
                )
    return live_entries, findings


def main() -> int:
    args = parse_args()
    registry = json.loads(Path(args.registry).read_text(encoding="utf-8"))
    apps = registry_apps(registry)
    offline_findings = audit_offline(apps, args.target_splunk_version)
    configuration_findings: list[dict[str, Any]] = []
    declared_target = str(registry.get("compatibility_target", "")).strip()
    contract_target = default_compatibility_target()
    if declared_target != contract_target:
        configuration_findings.append(
            {
                "id": "registry",
                "severity": "error",
                "field": "compatibility_target",
                "actual": declared_target,
                "expected": contract_target,
            }
        )

    live_entries: list[dict[str, Any]] = []
    live_findings: list[dict[str, Any]] = []
    if args.live:
        live_entries, live_findings = audit_live(apps, args.target_splunk_version, args.max_workers)

    payload = {
        "registry": str(Path(args.registry)),
        "target_splunk_version": args.target_splunk_version,
        "splunkbase_app_count": len(apps),
        "configuration_findings": configuration_findings,
        "offline_findings": offline_findings,
        "live_findings": live_findings,
        "live_entries": live_entries,
        "ok": not configuration_findings and not offline_findings and not live_findings,
    }

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"Splunkbase registry apps: {len(apps)}")
        print(f"Target Splunk version: {args.target_splunk_version}")
        for finding in configuration_findings + offline_findings + live_findings:
            print(
                "ERROR "
                f"{finding.get('id')}/{finding.get('app_name', '')} "
                f"{finding.get('field')}: {finding.get('actual', finding.get('message'))!r} "
                f"!= {finding.get('expected', '')!r}"
            )
        print("OK" if payload["ok"] else "FAILED")

    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

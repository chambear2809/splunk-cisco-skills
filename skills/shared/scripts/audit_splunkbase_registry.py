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
USER_AGENT = "splunk-cisco-skills/10.4-readiness-audit"
VERSION_RE = re.compile(r"^(\d+(?:\.\d+)*(?:[.-][A-Za-z0-9]+)?)\b")
DATE_RE = re.compile(r"([A-Z][a-z]+ \d{1,2}, 20\d{2})")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit Splunkbase registry metadata.")
    parser.add_argument("--registry", default=str(REGISTRY_PATH))
    parser.add_argument("--target-splunk-version", default="10.4")
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


def fetch_splunkbase(app_id: str) -> dict[str, Any]:
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
    return {
        "splunkbase_id": app_id,
        "latest_version": version_match.group(1) if version_match else "",
        "latest_release_date": date_match.group(1) if date_match else "",
        "platform_versions": parse_platform_versions(platform),
        "platform_raw": platform,
        "url": url,
    }


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
        for field in ("latest_verified_version", "latest_release_date", "latest_verified_date", "last_verified_date"):
            if not isinstance(app.get(field), str) or not app[field].strip():
                findings.append({"id": app_id, "severity": "error", "field": field, "message": "missing or invalid"})
    return findings


def audit_live(apps: list[dict[str, Any]], target: str, max_workers: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_id = {str(app["splunkbase_id"]).strip(): app for app in apps}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        live_entries = list(executor.map(fetch_splunkbase, by_id))

    findings: list[dict[str, Any]] = []
    for live in live_entries:
        app = by_id[live["splunkbase_id"]]
        expected_status = compatibility_status(live["platform_versions"], target)
        comparisons = {
            "latest_verified_version": live["latest_version"],
            "latest_release_date": live["latest_release_date"],
            "latest_verified_date": live["latest_release_date"],
            "platform_versions": live["platform_versions"],
            "compatibility_status": expected_status,
        }
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

    live_entries: list[dict[str, Any]] = []
    live_findings: list[dict[str, Any]] = []
    if args.live:
        live_entries, live_findings = audit_live(apps, args.target_splunk_version, args.max_workers)

    payload = {
        "registry": str(Path(args.registry)),
        "target_splunk_version": args.target_splunk_version,
        "splunkbase_app_count": len(apps),
        "offline_findings": offline_findings,
        "live_findings": live_findings,
        "live_entries": live_entries,
        "ok": not offline_findings and not live_findings,
    }

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"Splunkbase registry apps: {len(apps)}")
        print(f"Target Splunk version: {args.target_splunk_version}")
        for finding in offline_findings + live_findings:
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

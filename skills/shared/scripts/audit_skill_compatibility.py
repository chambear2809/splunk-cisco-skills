#!/usr/bin/env python3
"""Audit explicit Splunk Cloud 10.5 compatibility metadata for every skill."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = REPO_ROOT / "skills"
REGISTRY_PATH = REPO_ROOT / "skills/shared/app_registry.json"
PLATFORM_VERSIONS_PATH = (
    REPO_ROOT / "skills/shared/references/splunk_platform_versions.json"
)
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---", re.DOTALL)
STATUS_KEY = "splunk_cloud_10_5"
VERIFIED_KEY = "compatibility_verified"
VERIFIED_DATE = "2026-07-02"

COMPATIBILITY_TEXT = {
    "supported": (
        "Splunk Cloud Platform 10.5.2605: supported. Self-managed paths retain "
        "the verified public 10.4 baseline where applicable."
    ),
    "conditional": (
        "Splunk Cloud Platform 10.5.2605: conditional. Follow documented package, "
        "entitlement, topology, and customer-managed runtime guardrails; "
        "self-managed paths remain on the public 10.4 baseline."
    ),
    "blocked": (
        "Splunk Cloud Platform 10.5.2605: blocked for the primary package because "
        "current upstream compatibility metadata does not advertise 10.5; render "
        "or hand off only unless an explicit approved override is recorded."
    ),
    "self-managed-10.4": (
        "Splunk Cloud Platform 10.5.2605: not applicable. This self-managed runtime "
        "workflow remains on the public Splunk Enterprise or Universal Forwarder "
        "10.4 baseline."
    ),
    "not-applicable": (
        "No direct Splunk Platform runtime dependency. This workflow can be used "
        "alongside Splunk Cloud Platform 10.5.2605 through its documented external "
        "APIs or handoffs."
    ),
    "delegated": (
        "Splunk Cloud Platform 10.5.2605: delegated. Compatibility is determined by "
        "the selected child skill; this router does not install a runtime or package "
        "itself."
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit per-skill Splunk Cloud 10.5 compatibility metadata."
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    return parser.parse_args()


def skill_files() -> list[Path]:
    return sorted(
        path
        for path in SKILLS_DIR.glob("*/SKILL.md")
        if path.parent.name != "shared" and not path.parent.name.startswith(".")
    )


def load_frontmatter(path: Path) -> dict[str, Any]:
    match = FRONTMATTER_RE.match(path.read_text(encoding="utf-8"))
    if not match:
        return {}
    loaded = yaml.safe_load(match.group(1)) or {}
    return loaded if isinstance(loaded, dict) else {}


def registry_apps_by_skill() -> dict[str, list[dict[str, Any]]]:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    grouped: dict[str, list[dict[str, Any]]] = {}
    for app in registry.get("apps", []):
        grouped.setdefault(str(app.get("skill", "")), []).append(app)
    return grouped


def audit() -> dict[str, Any]:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    versions = json.loads(PLATFORM_VERSIONS_PATH.read_text(encoding="utf-8"))
    expected_target = str(
        (versions.get("defaults") or {}).get("splunkbase_compatibility_target", "")
    )
    findings: list[dict[str, str]] = []
    rows: list[dict[str, Any]] = []
    apps_by_skill = registry_apps_by_skill()

    if expected_target != "10.5":
        findings.append(
            {
                "skill": "shared-contract",
                "field": "splunkbase_compatibility_target",
                "message": f"expected 10.5, found {expected_target or '<missing>'}",
            }
        )
    if str(registry.get("compatibility_target", "")) != expected_target:
        findings.append(
            {
                "skill": "shared-contract",
                "field": "registry.compatibility_target",
                "message": "registry and platform-version targets differ",
            }
        )

    for path in skill_files():
        skill = path.parent.name
        metadata = load_frontmatter(path)
        status_metadata = metadata.get("metadata")
        status = (
            str(status_metadata.get(STATUS_KEY, ""))
            if isinstance(status_metadata, dict)
            else ""
        )
        verified = (
            str(status_metadata.get(VERIFIED_KEY, ""))
            if isinstance(status_metadata, dict)
            else ""
        )
        compatibility = str(metadata.get("compatibility", "")).strip()
        apps = apps_by_skill.get(skill, [])
        unsupported = [
            str(app.get("splunkbase_id", ""))
            for app in apps
            if app.get("compatibility_status") == "unsupported"
        ]

        if status not in COMPATIBILITY_TEXT:
            findings.append(
                {
                    "skill": skill,
                    "field": f"metadata.{STATUS_KEY}",
                    "message": f"missing or invalid status {status!r}",
                }
            )
        elif compatibility != COMPATIBILITY_TEXT[status]:
            findings.append(
                {
                    "skill": skill,
                    "field": "compatibility",
                    "message": "text does not match the declared compatibility profile",
                }
            )
        if verified != VERIFIED_DATE:
            findings.append(
                {
                    "skill": skill,
                    "field": f"metadata.{VERIFIED_KEY}",
                    "message": f"expected {VERIFIED_DATE}, found {verified or '<missing>'}",
                }
            )
        if unsupported and status == "supported":
            findings.append(
                {
                    "skill": skill,
                    "field": f"metadata.{STATUS_KEY}",
                    "message": (
                        "cannot be unconditionally supported while registry app IDs "
                        + ", ".join(unsupported)
                        + " omit 10.5"
                    ),
                }
            )
        if status == "blocked" and not unsupported:
            findings.append(
                {
                    "skill": skill,
                    "field": f"metadata.{STATUS_KEY}",
                    "message": "blocked profile requires a registry-backed 10.5 gap",
                }
            )

        rows.append(
            {
                "skill": skill,
                "status": status,
                "compatibility": compatibility,
                "splunkbase_apps": [
                    {
                        "id": str(app.get("splunkbase_id", "")),
                        "name": str(app.get("app_name", "")),
                        "status": str(app.get("compatibility_status", "not-applicable")),
                    }
                    for app in apps
                ],
            }
        )

    counts = Counter(row["status"] for row in rows)
    return {
        "target": "10.5.2605",
        "verified": VERIFIED_DATE,
        "skill_count": len(rows),
        "status_counts": dict(sorted(counts.items())),
        "findings": findings,
        "skills": rows,
        "ok": not findings,
    }


def main() -> int:
    args = parse_args()
    payload = audit()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"Skills audited: {payload['skill_count']}")
        print(f"Target: {payload['target']}")
        for status, count in payload["status_counts"].items():
            print(f"{status}: {count}")
        for finding in payload["findings"]:
            print(
                f"ERROR {finding['skill']} {finding['field']}: "
                f"{finding['message']}",
                file=sys.stderr,
            )
        print("OK" if payload["ok"] else "FAILED")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

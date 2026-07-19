#!/usr/bin/env python3
"""Audit explicit Splunk Cloud 10.5 compatibility metadata for every skill."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:  # Keep the standalone audit usable before dev deps install.
    yaml = None


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from skills.shared.skill_catalog import SkillCatalog, load_catalog  # noqa: E402


SKILLS_DIR = REPO_ROOT / "skills"
REGISTRY_PATH = REPO_ROOT / "skills/shared/app_registry.json"
PLATFORM_VERSIONS_PATH = (
    REPO_ROOT / "skills/shared/references/splunk_platform_versions.json"
)
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---", re.DOTALL)
STATUS_KEY = "splunk_cloud_10_5"
VERIFIED_KEY = "compatibility_verified"
VERIFIED_DATE = "2026-07-02"
BLOCKING_PACKAGE_RELATIONSHIPS = {"primary", "private-primary"}

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
        "no repo-selected or otherwise approved release has 10.5 compatibility "
        "evidence; render or hand off only unless an explicit approved override "
        "is recorded."
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
        "the canonical replacement or selected child skill; this compatibility alias "
        "or router does not own a runtime or package."
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit per-skill Splunk Cloud 10.5 compatibility metadata."
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    return parser.parse_args()


def skill_files(catalog: SkillCatalog | None = None) -> list[Path]:
    manifest = catalog or load_catalog()
    return sorted(REPO_ROOT / record.path for record in manifest.skills)


def load_frontmatter(path: Path) -> dict[str, Any]:
    match = FRONTMATTER_RE.match(path.read_text(encoding="utf-8"))
    if not match:
        return {}
    if yaml is not None:
        loaded = yaml.safe_load(match.group(1)) or {}
        return loaded if isinstance(loaded, dict) else {}

    # The audit only needs the one scalar and two metadata keys that this repo
    # standardizes. Avoid pretending this is a general YAML implementation.
    loaded: dict[str, Any] = {}
    metadata: dict[str, str] = {}
    in_metadata = False
    for line in match.group(1).splitlines():
        if line == "metadata:":
            in_metadata = True
            loaded["metadata"] = metadata
            continue
        if not line.startswith(" "):
            in_metadata = False
        if in_metadata and line.startswith("  ") and ":" in line:
            key, raw = line.strip().split(":", 1)
            metadata[key] = _parse_quoted_scalar(raw.strip())
        elif line.startswith("compatibility:"):
            loaded["compatibility"] = _parse_quoted_scalar(
                line.split(":", 1)[1].strip()
            )
    return loaded


def _parse_quoted_scalar(raw: str) -> str:
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {'"', "'"}:
        try:
            value = ast.literal_eval(raw)
        except (SyntaxError, ValueError):
            return raw[1:-1]
        return str(value)
    return raw


def registry_apps_by_skill() -> dict[str, list[dict[str, Any]]]:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    grouped: dict[str, list[dict[str, Any]]] = {}
    for app in registry.get("apps", []):
        grouped.setdefault(str(app.get("skill", "")), []).append(app)
    return grouped


def audit() -> dict[str, Any]:
    catalog = load_catalog()
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    versions = json.loads(PLATFORM_VERSIONS_PATH.read_text(encoding="utf-8"))
    expected_target = str(
        (versions.get("defaults") or {}).get("splunkbase_compatibility_target", "")
    )
    findings: list[dict[str, str]] = []
    rows: list[dict[str, Any]] = []
    apps_by_skill = registry_apps_by_skill()
    expected_skills = set(catalog.by_name)
    topology_skills = [
        str(entry.get("skill", ""))
        for entry in registry.get("skill_topologies", [])
        if isinstance(entry, dict) and entry.get("skill")
    ]
    if len(topology_skills) != len(set(topology_skills)):
        findings.append(
            {
                "skill": "shared-contract",
                "field": "registry.skill_topologies",
                "message": "duplicate skill identities",
            }
        )
    if set(topology_skills) != expected_skills:
        findings.append(
            {
                "skill": "shared-contract",
                "field": "registry.skill_topologies",
                "message": "identities do not match skills/catalog.yaml",
            }
        )

    for app in registry.get("apps", []):
        app_id = str(app.get("splunkbase_id", "")).strip()
        if app_id.isdigit():
            continue
        if not str(app.get("app_name", "")).strip():
            continue
        for field in (
            "package_source",
            "reviewed_version",
            "target_product",
            "production_status",
            "compatibility_classification",
            "notes",
        ):
            if not str(app.get(field, "")).strip():
                findings.append(
                    {
                        "skill": str(app.get("skill", "private-package")),
                        "field": f"registry.{field}",
                        "message": (
                            f"private/local package {app.get('app_name')} must declare {field}"
                        ),
                    }
                )

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

    for path in skill_files(catalog):
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
            if str(app.get("relationship", "primary"))
            in BLOCKING_PACKAGE_RELATIONSHIPS
            and app.get("compatibility_status") == "unsupported"
        ]
        verified_supported = [
            str(app.get("splunkbase_id", ""))
            for app in apps
            if str(app.get("relationship", "primary"))
            in BLOCKING_PACKAGE_RELATIONSHIPS
            and "10.5" in (app.get("verified_platform_versions") or [])
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
        if status == "blocked" and verified_supported:
            findings.append(
                {
                    "skill": skill,
                    "field": f"metadata.{STATUS_KEY}",
                    "message": (
                        "blocked profile conflicts with a repo-verified 10.5 release for app IDs "
                        + ", ".join(verified_supported)
                    ),
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
                        "relationship": str(app.get("relationship", "primary")),
                        "status": str(
                            app.get("compatibility_status")
                            or app.get("compatibility_classification")
                            or app.get("production_status")
                            or "unclassified"
                        ),
                        "release_version": str(app.get("latest_release_version", "")),
                        "verified_version": str(
                            app.get("latest_verified_version")
                            or app.get("reviewed_version", "")
                        ),
                        "verified_status": (
                            (
                                "supported"
                                if expected_target
                                in (app.get("verified_platform_versions") or [])
                                else "unsupported"
                            )
                            if "verified_platform_versions" in app
                            else (
                                str(app.get("compatibility_status", "unclassified"))
                                if app.get("latest_verified_version")
                                == app.get("latest_release_version")
                                and app.get("latest_verified_version")
                                else str(
                                    app.get("compatibility_classification")
                                    or app.get("production_status")
                                    or "unverified"
                                )
                            )
                        ),
                        "cloud_compatible": app.get("cloud_compatible"),
                    }
                    for app in apps
                ],
            }
        )

    counts = Counter(row["status"] for row in rows)
    return {
        "catalog_sha256": catalog.checksum,
        "target": "10.5.2605",
        "verified": VERIFIED_DATE,
        "skill_count": len(rows),
        "status_counts": {
            status: counts.get(status, 0) for status in COMPATIBILITY_TEXT
        },
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

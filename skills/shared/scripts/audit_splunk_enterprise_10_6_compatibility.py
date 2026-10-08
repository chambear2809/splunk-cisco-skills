#!/usr/bin/env python3
"""Audit the separate self-managed Splunk Enterprise 10.6 compatibility contract."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
from skills.shared.skill_catalog import load_catalog  # noqa: E402
from skills.shared.scripts.audit_skill_compatibility import load_frontmatter as frontmatter  # noqa: E402

VERSIONS = REPO_ROOT / "skills/shared/references/splunk_platform_versions.json"
REGISTRY = REPO_ROOT / "skills/shared/app_registry.json"
MATRIX = REPO_ROOT / "SPLUNK_ENTERPRISE_10_6_COMPATIBILITY.md"
COMPATIBILITY_FIELD = "splunk_enterprise_10_6"
VERIFIED_KEY = "enterprise_compatibility_verified"
VALID = {"supported", "conditional", "blocked", "not-applicable", "delegated"}


def valid_evidence_date(stamp: str, baseline: str) -> bool:
    """Keep the historical baseline while accepting newly collected evidence."""
    try:
        value = date.fromisoformat(stamp)
        original = date.fromisoformat(baseline)
    except ValueError:
        return False
    return value.isoformat() == stamp and original.isoformat() == baseline and value >= original


def selected_package_evidence(app: dict[str, Any]) -> dict[str, Any]:
    """Return evidence for the exact package version the workflow selects by default."""
    verified_version = str(app.get("latest_verified_version") or "")
    public_version = str(app.get("latest_release_version") or "")
    split_pin = bool(verified_version and public_version and verified_version != public_version)
    if split_pin:
        selected_version = verified_version
        platforms = app.get("verified_platform_versions") or []
        if app.get("verified_release_evidence_status") == "historical-review-only-not-currently-reproducible":
            platforms = []
    else:
        selected_version = public_version or verified_version
        platforms = app.get("platform_versions") or []
    supports = "10.6" in platforms
    latest_supports = "10.6" in (app.get("platform_versions") or [])
    evidence = (
        f"selected `{selected_version}` explicitly lists Enterprise 10.6"
        if supports else
        f"selected `{selected_version or 'unknown'}` has no explicit Enterprise 10.6 evidence"
    )
    if split_pin and not supports and latest_supports:
        evidence += f"; newer public `{public_version}` lists 10.6 but is not the selected verified pin"
    return {"version": selected_version, "evidence": evidence, "supports": supports}


def audit() -> dict[str, Any]:
    catalog = load_catalog()
    versions = json.loads(VERSIONS.read_text(encoding="utf-8"))
    apps = json.loads(REGISTRY.read_text(encoding="utf-8")).get("apps", [])
    apps_by_skill: dict[str, list[dict[str, Any]]] = {}
    for app in apps:
        apps_by_skill.setdefault(str(app.get("skill", "")), []).append(app)
    verified = str(versions.get("enterprise_compatibility_verified_date", ""))
    rows: list[dict[str, Any]] = []
    findings: list[str] = []
    for item in catalog.skills:
        path = REPO_ROOT / item.path
        data = frontmatter(path)
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        status = str(metadata.get(COMPATIBILITY_FIELD, ""))
        stamp = str(metadata.get(VERIFIED_KEY, ""))
        if status not in VALID:
            findings.append(f"{item.name}: missing or invalid {COMPATIBILITY_FIELD}={status!r}")
        if not valid_evidence_date(stamp, verified):
            findings.append(f"{item.name}: {VERIFIED_KEY} must be YYYY-MM-DD on or after baseline {verified}")
        linked = apps_by_skill.get(item.name, [])
        package_evidence = {id(app): selected_package_evidence(app) for app in linked}
        if linked and status == "supported" and any(
            not evidence["supports"] for evidence in package_evidence.values()
        ):
            findings.append(f"{item.name}: supported requires explicit 10.6 evidence for every package")
        if status == "blocked" and item.name != "splunk-enterprise-kubernetes-setup":
            findings.append(f"{item.name}: blocked classification requires a documented 10.6 blocker")
        rows.append({
            "skill": item.name,
                "status": status,
                "verified": stamp,
            "packages": [
                {
                    "name": str(app.get("app_name", "")),
                    "id": str(app.get("splunkbase_id", "")),
                    "version": package_evidence[id(app)]["version"],
                    "supports": package_evidence[id(app)]["supports"],
                    "evidence": package_evidence[id(app)]["evidence"],
                }
                for app in linked
            ],
        })
    counts = Counter(row["status"] for row in rows)
    return {
        "target": "Splunk Enterprise 10.6",
        "verified": verified,
        "skill_count": len(rows),
        "counts": {key: counts.get(key, 0) for key in sorted(VALID)},
        "findings": findings,
        "skills": rows,
        "ok": not findings,
    }


def render(payload: dict[str, Any]) -> str:
    lines = [
        "# Splunk Enterprise 10.6 Compatibility",
        "",
        "_Generated from `skills/catalog.yaml`, skill frontmatter, `app_registry.json`, and `splunk_platform_versions.json`._",
        "",
        "This matrix is the self-managed Enterprise track. Splunk Cloud Platform `10.5.2605` and its Splunkbase `10.5` package evidence remain separate. Cloud compatibility does not qualify Enterprise 10.6 support.",
        "A skill or package without explicit Enterprise 10.6 evidence for its exact default-selected package release remains conditional or blocked. A newer public release does not qualify a different verified pin. Public package metadata is not binary or checksum verification.",
        "",
        f"Baseline evidence date: `{payload['verified']}`. Canonical skills audited: `{payload['skill_count']}`. Newly verified skills retain their own dates below.",
        "",
        "## Summary",
        "",
        "| Status | Skills |",
        "| --- | ---: |",
    ]
    for status, count in payload["counts"].items():
        lines.append(f"| {status} | {count} |")
    lines += ["", "## Complete matrix", "", "| Skill | Enterprise 10.6 status | Verified | Enterprise 10.6 package evidence |", "| --- | --- | --- | --- |"]
    for row in payload["skills"]:
        package_text = "; ".join(
            f"{p['id'] or 'local'} `{p['name']}` {p['evidence']}" for p in row["packages"]
        ) or "No direct package evidence recorded"
        package_text = package_text.replace("|", r"\|")
        lines.append(f"| `{row['skill']}` | {row['status']} | {row.get('verified', payload['verified'])} | {package_text} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--json", action="store_true")
    group.add_argument("--write", action="store_true")
    group.add_argument("--check", action="store_true")
    args = parser.parse_args()
    payload = audit()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif args.write:
        MATRIX.write_text(render(payload), encoding="utf-8")
    elif args.check:
        if MATRIX.read_text(encoding="utf-8") != render(payload):
            print("Enterprise 10.6 matrix is out of date; run with --write", file=sys.stderr)
            return 1
    else:
        print(f"Skills audited: {payload['skill_count']}")
        print(f"Target: {payload['target']}")
        print("OK" if payload["ok"] else "FAILED")
    for finding in payload["findings"]:
        print(f"ERROR {finding}", file=sys.stderr)
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

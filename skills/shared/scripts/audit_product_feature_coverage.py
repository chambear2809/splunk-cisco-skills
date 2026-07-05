#!/usr/bin/env python3
"""Offline audit for repo-wide product and feature coverage contracts."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = REPO_ROOT / "skills"
REGISTRY_PATH = SKILLS_DIR / "shared" / "app_registry.json"
EVIDENCE_PATH = SKILLS_DIR / "shared" / "references" / "splunkbase_registry_evidence.json"

CATALOG_DOCS = (
    "AGENTS.md",
    "CLAUDE.md",
    "SKILL_REQUIREMENTS.md",
)

ROUTER_CONTRACTS = {
    "cisco-product-setup": {
        "path": "skills/cisco-product-setup/reference.md",
        "required": ("Automated Route Families", "Route Type", "manual_gap"),
    },
    "cisco-data-fabric-setup": {
        "path": "skills/cisco-data-fabric-setup/reference.md",
        "required": ("Product Boundary", "coverage-report", "product-matrix", "gap-register"),
    },
    "splunk-appdynamics-setup": {
        "path": "skills/splunk-appdynamics-setup/reference.md",
        "required": ("Family", "Owner", "splunk-appdynamics-apm-setup"),
    },
    "splunk-security-portfolio-setup": {
        "path": "skills/splunk-security-portfolio-setup/reference.md",
        "required": ("Product Coverage", "Splunk Enterprise Security", "Splunk SOAR"),
    },
    "splunk-observability-deep-native-workflows": {
        "path": "skills/splunk-observability-deep-native-workflows/reference.md",
        "required": ("Product Coverage Matrix", "Surface", "Coverage", "Owning follow-up"),
    },
    "splunk-supported-addons-setup": {
        "path": "skills/splunk-supported-addons-setup/reference.md",
        "required": ("Supported Add-ons", "Coverage", "profile"),
    },
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def skill_names() -> set[str]:
    return {
        path.name
        for path in SKILLS_DIR.iterdir()
        if path.is_dir()
        and path.name != "shared"
        and not path.name.startswith(".")
        and (path / "SKILL.md").is_file()
    }


def catalog_skills(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    return set(re.findall(r"^\| `([^`]+)` \|", text, flags=re.MULTILINE))


def check_catalogs(skills: set[str], errors: list[str], summary: dict[str, Any]) -> None:
    for rel_path in CATALOG_DOCS:
        actual = catalog_skills(REPO_ROOT / rel_path)
        missing = sorted(skills - actual)
        extra = sorted(actual - skills)
        summary[f"{rel_path}:skills"] = len(actual)
        if missing:
            errors.append(f"{rel_path}: missing skill entries: {', '.join(missing)}")
        if extra:
            errors.append(f"{rel_path}: unknown skill entries: {', '.join(extra)}")

    ux_text = (REPO_ROOT / "SKILL_UX_CATALOG.md").read_text(encoding="utf-8")
    ux_rows = set(re.findall(r"^\| `([^`]+)` \|", ux_text, flags=re.MULTILINE))
    summary["SKILL_UX_CATALOG.md:skills"] = len(ux_rows)
    if ux_rows != skills:
        errors.append("SKILL_UX_CATALOG.md: generated catalog is not in sync with skills/")


def check_registry(skills: set[str], errors: list[str], summary: dict[str, Any]) -> None:
    registry = load_json(REGISTRY_PATH)
    evidence = load_json(EVIDENCE_PATH)
    apps = registry.get("apps", [])
    if not isinstance(apps, list) or not apps:
        errors.append("skills/shared/app_registry.json: apps must be a non-empty list")
        return

    numeric_ids: set[str] = set()
    missing_skill: list[str] = []
    duplicate_ids: set[str] = set()
    seen_ids: set[str] = set()
    for app in apps:
        if not isinstance(app, dict):
            errors.append("skills/shared/app_registry.json: every app entry must be an object")
            continue
        app_id = str(app.get("splunkbase_id", ""))
        app_name = str(app.get("app_name", "<unnamed>"))
        skill = str(app.get("skill", ""))
        if not skill or skill not in skills:
            missing_skill.append(f"{app_id or 'N/A'}:{app_name}->{skill or '<missing>'}")
        if app_id:
            if app_id in seen_ids:
                duplicate_ids.add(app_id)
            seen_ids.add(app_id)
        if app_id.isdigit():
            numeric_ids.add(app_id)

    if missing_skill:
        errors.append("app registry entries route to missing skills: " + ", ".join(missing_skill))
    if duplicate_ids:
        errors.append("app registry has duplicate splunkbase IDs: " + ", ".join(sorted(duplicate_ids)))

    evidence_ids = {
        str(app.get("splunkbase_id"))
        for app in evidence.get("apps", [])
        if isinstance(app, dict) and str(app.get("splunkbase_id", "")).isdigit()
    }
    if evidence.get("app_count") != len(numeric_ids):
        errors.append(
            "splunkbase evidence app_count does not match numeric registry entries: "
            f"{evidence.get('app_count')} != {len(numeric_ids)}"
        )
    if evidence_ids != numeric_ids:
        errors.append("splunkbase evidence IDs do not match numeric app registry IDs")

    summary["app_registry:apps"] = len(apps)
    summary["app_registry:numeric_apps"] = len(numeric_ids)
    summary["app_registry:routed_apps"] = len(apps) - len(missing_skill)


def check_router_contracts(skills: set[str], errors: list[str], summary: dict[str, Any]) -> None:
    covered = 0
    for skill, contract in ROUTER_CONTRACTS.items():
        if skill not in skills:
            errors.append(f"{skill}: router skill is missing")
            continue
        path = REPO_ROOT / str(contract["path"])
        if not path.is_file():
            errors.append(f"{path.relative_to(REPO_ROOT)}: router reference is missing")
            continue
        text = path.read_text(encoding="utf-8")
        missing = [fragment for fragment in contract["required"] if fragment not in text]
        if missing:
            errors.append(
                f"{path.relative_to(REPO_ROOT)}: missing coverage marker(s): "
                + ", ".join(missing)
            )
        else:
            covered += 1
    summary["router_contracts:covered"] = covered
    summary["router_contracts:expected"] = len(ROUTER_CONTRACTS)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit repo-wide product and feature coverage contracts."
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable audit output.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    errors: list[str] = []
    summary: dict[str, Any] = {}
    skills = skill_names()
    summary["skills:on_disk"] = len(skills)

    check_catalogs(skills, errors, summary)
    check_registry(skills, errors, summary)
    check_router_contracts(skills, errors, summary)

    payload = {"ok": not errors, "summary": summary, "errors": errors}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif errors:
        print("Product/feature coverage audit failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
    else:
        print("Product/feature coverage audit passed.")
        for key in sorted(summary):
            print(f"- {key}: {summary[key]}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())

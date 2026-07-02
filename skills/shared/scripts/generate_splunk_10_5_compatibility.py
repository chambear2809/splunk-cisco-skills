#!/usr/bin/env python3
"""Generate the complete Splunk Cloud 10.5 skill compatibility matrix."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from audit_skill_compatibility import COMPATIBILITY_TEXT, REPO_ROOT, audit  # noqa: E402


OUTPUT_PATH = REPO_ROOT / "SPLUNK_10_5_COMPATIBILITY.md"
GENERATED_BANNER = (
    "_Generated from `skills/*/SKILL.md`, `skills/shared/app_registry.json`, and "
    "`skills/shared/references/splunk_platform_versions.json`; do not edit manually._"
)
STATUS_LABELS = {
    "supported": "Supported",
    "conditional": "Conditional",
    "blocked": "Blocked",
    "self-managed-10.4": "Self-managed 10.4",
    "not-applicable": "Not applicable",
    "delegated": "Delegated",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    return parser.parse_args()


def escape(value: str) -> str:
    return str(value).replace("|", r"\|").replace("\n", "<br>")


def package_evidence(app: dict[str, object]) -> str:
    app_id = str(app["id"])
    name = str(app["name"])
    relationship = str(app["relationship"])
    status = str(app["status"])
    release = str(app["release_version"])
    verified = str(app["verified_version"])
    verified_status = str(app["verified_status"])
    identity = f"{app_id} `{name}`" if app_id else f"private/local `{name}`"
    details: list[str] = []
    if release:
        details.append(f"latest {release}: {status}")
    else:
        details.append(status)
    if verified and (verified != release or not release):
        details.append(f"verified {verified}: {verified_status}")
    if app["cloud_compatible"] is False:
        details.append("Cloud install: rejected")
    return f"{relationship}: {identity} ({'; '.join(details)})"


def render() -> str:
    payload = audit()
    if not payload["ok"]:
        raise RuntimeError("skill compatibility audit failed; fix findings first")

    lines = [
        "# Splunk 10.5 Skill Compatibility",
        "",
        GENERATED_BANNER,
        "",
        "This matrix classifies every repository skill against Splunk Cloud Platform",
        "`10.5.2605`. It does not invent a self-managed Splunk Enterprise 10.5 runtime:",
        "self-managed workflows retain the current public 10.4 baseline.",
        "",
        "## Summary",
        "",
        "| Status | Skills | Meaning |",
        "| --- | ---: | --- |",
    ]
    for status in STATUS_LABELS:
        lines.append(
            f"| {STATUS_LABELS[status]} | {payload['status_counts'].get(status, 0)} "
            f"| {escape(COMPATIBILITY_TEXT[status])} |"
        )

    lines.extend(
        [
            "",
            "`Blocked` means the primary upstream package currently omits 10.5. The",
            "generic installer refuses known incompatible packages unless an explicit",
            "approved override is supplied. `Conditional` includes entitlement, package,",
            "topology, customer-managed runtime, or product-specific prerequisites.",
            "",
            "## Complete Matrix",
            "",
            "| Skill | Status | Splunkbase package evidence | Compatibility contract |",
            "| --- | --- | --- | --- |",
        ]
    )
    for row in payload["skills"]:
        apps = row["splunkbase_apps"]
        app_text = ", ".join(package_evidence(app) for app in apps) or (
            "No direct Splunkbase package"
        )
        lines.append(
            f"| `{row['skill']}` | {STATUS_LABELS.get(row['status'], row['status'])} "
            f"| {escape(app_text)} | {escape(row['compatibility'])} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    args = parse_args()
    rendered = render()
    if args.write:
        OUTPUT_PATH.write_text(rendered, encoding="utf-8")
        return 0
    current = OUTPUT_PATH.read_text(encoding="utf-8") if OUTPUT_PATH.exists() else ""
    if current != rendered:
        print(
            "SPLUNK_10_5_COMPATIBILITY.md is out of date. Run "
            "`python3 skills/shared/scripts/generate_splunk_10_5_compatibility.py --write`.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

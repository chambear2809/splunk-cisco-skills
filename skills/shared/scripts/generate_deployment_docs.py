#!/usr/bin/env python3
"""Generate deployment matrix docs from app_registry.json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = REPO_ROOT / "skills/shared/app_registry.json"
CLOUD_DOC_PATH = REPO_ROOT / "CLOUD_DEPLOYMENT_MATRIX.md"
ROLE_DOC_PATH = REPO_ROOT / "DEPLOYMENT_ROLE_MATRIX.md"

SUPPORT_LABELS = {
    "required": "Required",
    "supported": "Supported",
    "none": "None",
}

PAIRING_LABELS = {
    "search-tier": "Search tier",
    "indexer": "Indexer",
    "heavy-forwarder": "HF",
    "universal-forwarder": "UF",
    "external-collector": "External collector",
}

GENERATED_BANNER = (
    "_Generated from `skills/shared/app_registry.json` by "
    "`skills/shared/scripts/generate_deployment_docs.py`; do not edit manually._"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate deployment matrix docs from skills/shared/app_registry.json."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the checked-in docs differ from generated output.",
    )
    mode.add_argument(
        "--write",
        action="store_true",
        help="Write the generated output to the checked-in docs.",
    )
    return parser.parse_args()


def load_registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    def clean(cell: str) -> str:
        return str(cell).replace("|", r"\|").replace("\n", "<br>")

    table_lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        table_lines.append("| " + " | ".join(clean(cell) for cell in row) + " |")
    return "\n".join(table_lines)


def pairing_summary(pairings: list[str]) -> str:
    if not pairings:
        return "None"
    labels = [PAIRING_LABELS.get(role, role) for role in pairings]
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} or {labels[1]}"
    return f"{', '.join(labels[:-1])}, or {labels[-1]}"


def support_label(value: str) -> str:
    if value not in SUPPORT_LABELS:
        raise ValueError(f"Unknown role-support value: {value}")
    return SUPPORT_LABELS[value]


def validate_registry(registry: dict) -> None:
    roles = registry.get("deployment_roles", [])
    role_descriptions = registry.get("deployment_role_descriptions", {})
    if set(roles) != set(role_descriptions):
        raise ValueError("deployment_role_descriptions must cover every deployment role.")

    apps_by_name = {app["app_name"]: app for app in registry.get("apps", [])}
    known_skills = {entry["skill"] for entry in registry.get("skill_topologies", [])}

    for row in registry.get("documentation", {}).get("cloud_matrix_rows", []):
        for key in ("kind", "label", "cloud_install_path", "cloud_config_path", "notes"):
            if not row.get(key):
                raise ValueError(f"Cloud matrix row is missing required key: {key}")
        kind = row["kind"]
        if kind == "app":
            app_name = row.get("app_name", "")
            if app_name not in apps_by_name:
                raise ValueError(f"Cloud matrix app row references unknown app: {app_name}")
        elif kind == "workflow":
            skill = row.get("skill", "")
            if skill not in known_skills:
                raise ValueError(f"Cloud matrix workflow row references unknown skill: {skill}")
            if not row.get("splunkbase_id"):
                raise ValueError("Cloud matrix workflow rows must declare splunkbase_id.")
        else:
            raise ValueError(f"Unknown cloud matrix row kind: {kind}")


def render_cloud_matrix(registry: dict) -> str:
    apps_by_name = {app["app_name"]: app for app in registry.get("apps", [])}
    rows = []
    for row in registry["documentation"]["cloud_matrix_rows"]:
        if row["kind"] == "app":
            splunkbase_id = apps_by_name[row["app_name"]]["splunkbase_id"]
        else:
            splunkbase_id = row["splunkbase_id"]
        rows.append(
            [
                row["label"],
                splunkbase_id,
                row["cloud_install_path"],
                row["cloud_config_path"],
                row["notes"],
            ]
        )

    table = markdown_table(
        ["Skill", "Splunkbase ID", "Cloud install path", "Cloud config path", "Notes"],
        rows,
    )

    return "\n".join(
        [
            "# Cloud Deployment Matrix",
            "",
            GENERATED_BANNER,
            "",
            "This document defines the normal Splunk Cloud deployment model for the",
            "repo's cloud-supported apps and workflows.",
            "",
            "For cross-platform placement across search tiers, indexers, forwarders, and",
            "external collectors, see",
            "[`DEPLOYMENT_ROLE_MATRIX.md`](DEPLOYMENT_ROLE_MATRIX.md).",
            "",
            "## Default Rule",
            "",
            "- For apps published on Splunkbase, prefer **ACS Splunkbase installs** and let",
            "  ACS fetch the latest compatible release. Use `--source splunkbase` with the",
            "  app's Splunkbase ID.",
            "- Use private package uploads (`acs apps install private`) only for genuinely",
            "  private or pre-vetted apps that do not have a public Splunkbase listing.",
            "- Keep vendor archives in `splunk-ta/` as the local cache and review copy.",
            "- Use **ACS** for Splunk Cloud app installation, index management, and restarts.",
            "- Use **search-tier REST** for post-install app configuration when the",
            "  `search-api` allow list permits it.",
            "- Do **not** require extract/repack as part of the normal workflow.",
            "- Treat anything under `splunk-ta/_unpacked/` as review-only.",
            "",
            "## App And Workflow Matrix",
            "",
            table,
            "",
            "## Stream Heavy Forwarder Model",
            "",
            "For Splunk Stream on Splunk Cloud:",
            "",
            "- install `splunk_app_stream` on the Splunk Cloud search tier",
            "- install `Splunk_TA_stream` on a customer-controlled HF/UF",
            "- use the local overlay template in:",
            "  `skills/splunk-stream-setup/templates/splunk-cloud-hf-netflow-any/`",
            "- configure HF forwarding to Splunk Cloud at the host layer",
            "",
            "## SC4S External Collector Model",
            "",
            "For Splunk Connect for Syslog on Splunk Cloud:",
            "",
            "- create or validate indexes and HEC tokens against the Cloud stack",
            "- run the SC4S syslog-ng container on infrastructure you control",
            "- send SC4S output directly to Splunk Cloud HEC on `443`",
            "- keep SC4S runtime files, token material, and local archive/disk-buffer storage",
            "  on the customer-managed host or Kubernetes cluster",
            "",
            "## Cloud Access Architecture",
            "",
            "Splunk Cloud exposes two distinct API surfaces. The scripts in this repo use",
            "both depending on the operation.",
            "",
            "### ACS vs Search-Tier REST (8089)",
            "",
            markdown_table(
                ["Operation", "ACS (no 8089 needed)", "REST 8089 required"],
                [
                    ["App install / uninstall", "Yes", "--"],
                    ["Index create / check", "Yes", "--"],
                    ["HEC token management", "Yes", "--"],
                    ["Stack restart", "Yes", "--"],
                    ["IP allowlist management", "Yes", "--"],
                    ["TA account setup (OAuth, API keys)", "--", "Yes"],
                    ["Input enablement / configuration", "--", "Yes"],
                    ["Conf / macro updates", "--", "Yes"],
                    ["Saved search toggles", "--", "Yes"],
                    ["Validation (app state, data flow)", "--", "Yes"],
                    ["Oneshot search", "--", "Yes"],
                ],
            ),
            "",
            "Port 443 on Splunk Cloud serves Splunk Web (the browser UI). The full REST API",
            "(`/servicesNS/...`, `/services/...`) is documented exclusively on port 8089.",
            "ACS does not expose app-specific custom REST handlers.",
            "",
            "### Automatic Search-API Access",
            "",
            "When a script detects a Cloud target, the shared helpers automatically:",
            "",
            "1. **Resolve the current search head** via `acs config current-stack` and",
            "   build a direct search-head REST URL (`https://sh-i-*.stack.splunkcloud.com:8089`).",
            "2. **Switch to stack-local credentials** (`STACK_USERNAME` / `STACK_PASSWORD`)",
            "   for 8089 authentication.",
            "3. **Add the current public IP to the search-api allowlist** via",
            "   `acs ip-allowlist create search-api --subnets <ip>/32` if it is not already",
            "   listed.",
            "",
            "This means a user with valid ACS credentials can run any skill against Splunk",
            "Cloud without manually configuring the search-api IP allowlist or knowing the",
            "direct search-head hostname.",
            "",
            "To disable the automatic allowlist management (for example, in environments",
            "where IP allowlists are controlled externally), set:",
            "",
            "```bash",
            'export SPLUNK_SKIP_ALLOWLIST="true"',
            "```",
            "",
            "### Why Direct Search Heads?",
            "",
            "After an ACS app install, the load-balanced stack hostname",
            "(`stack.splunkcloud.com:8089`) can take time to reflect the new app across all",
            "search-head cluster members. The direct search-head URL bypasses this",
            "propagation delay and sees the installed app immediately.",
            "",
            "## What `_unpacked` Means",
            "",
            "The `_unpacked` trees exist only so we can:",
            "",
            "- inspect package internals",
            "- identify Cloud compatibility risks",
            "- document vendor package limitations",
            "",
            "They are not the normal installation source for this repo's Cloud workflow.",
            "",
        ]
    )


def render_role_matrix(registry: dict) -> str:
    role_rows = [
        [f"`{role}`", registry["deployment_role_descriptions"][role]]
        for role in registry["deployment_roles"]
    ]

    skill_rows = []
    for entry in registry["skill_topologies"]:
        role_support = entry["role_support"]
        skill_rows.append(
            [
                f"`{entry['skill']}`",
                support_label(role_support["search-tier"]),
                support_label(role_support["indexer"]),
                support_label(role_support["heavy-forwarder"]),
                support_label(role_support["universal-forwarder"]),
                support_label(role_support["external-collector"]),
                pairing_summary(entry.get("cloud_pairing", [])),
                entry["notes"],
            ]
        )

    app_rows = []
    for app in registry["apps"]:
        role_support = app["role_support"]
        app_rows.append(
            [
                f"`{app['app_name']}`",
                f"`{app['skill']}`",
                support_label(role_support["search-tier"]),
                support_label(role_support["indexer"]),
                support_label(role_support["heavy-forwarder"]),
                support_label(role_support["universal-forwarder"]),
                support_label(role_support["external-collector"]),
            ]
        )

    return "\n".join(
        [
            "# Deployment Role Matrix",
            "",
            GENERATED_BANNER,
            "",
            "This document defines the repo's role-based placement model across all",
            "supported Splunk deployment topologies.",
            "",
            "The role matrix documents where each app or skill meaningfully belongs. The",
            "runtime layer currently uses it for warning-only placement checks, Cloud pairing",
            "warnings, and selected split-workflow decisions such as role-aware Stream app",
            "installs.",
            "",
            "## Role Definitions",
            "",
            markdown_table(["Role", "Meaning"], role_rows),
            "",
            "Platform and role are separate concepts:",
            "",
            "- Platform answers whether the scripts are targeting Splunk Cloud or Splunk Enterprise APIs.",
            "- Role answers where a package or end-to-end skill belongs inside that platform topology.",
            "- Delivery plane answers how that package is pushed there, such as ACS, direct REST, SSH staging, deployer, or cluster-manager workflows.",
            "",
            "For Cloud-specific install and API behavior, see",
            "[`CLOUD_DEPLOYMENT_MATRIX.md`](CLOUD_DEPLOYMENT_MATRIX.md).",
            "",
            "## Skill Topologies",
            "",
            markdown_table(
                [
                    "Skill",
                    "Search Tier",
                    "Indexer",
                    "Heavy Forwarder",
                    "Universal Forwarder",
                    "External Collector",
                    "Cloud Pairing",
                    "Notes",
                ],
                skill_rows,
            ),
            "",
            "## App And Package Placement",
            "",
            markdown_table(
                [
                    "App / Package",
                    "Skill",
                    "Search Tier",
                    "Indexer",
                    "Heavy Forwarder",
                    "Universal Forwarder",
                    "External Collector",
                ],
                app_rows,
            ),
            "",
            "## Notes On Split Deployments",
            "",
            "- Splunk Cloud pairing is skill-specific, not global.",
            "- The API-collector family can run entirely on the Cloud search tier or on a",
            "  customer-managed heavy forwarder.",
            "- Splunk Stream is intentionally split:",
            "  - `splunk_app_stream` on the search tier",
            "  - `Splunk_TA_stream` on a heavy or universal forwarder",
            "  - `Splunk_TA_stream_wire_data` on indexers and, where useful, search or heavy-forwarder tiers",
            "- SC4S is modeled as an `external-collector` workflow rather than an app",
            "  placement inside Splunk.",
            "",
        ]
    )


def write_or_check(path: Path, content: str, check: bool) -> bool:
    if check:
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current != content:
            print(
                f"{path.relative_to(REPO_ROOT)} is out of date. Run "
                "`python3 skills/shared/scripts/generate_deployment_docs.py --write`.",
                file=sys.stderr,
            )
            return False
        return True

    path.write_text(content, encoding="utf-8")
    return True


def main() -> int:
    args = parse_args()
    check = args.check
    registry = load_registry()
    validate_registry(registry)

    outputs = {
        CLOUD_DOC_PATH: render_cloud_matrix(registry),
        ROLE_DOC_PATH: render_role_matrix(registry),
    }

    success = True
    for path, content in outputs.items():
        success = write_or_check(path, content, check) and success

    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Render package-verified security appliance supported add-on assets."""

from __future__ import annotations

import argparse
import json
import stat
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = REPO_ROOT / "splunk-security-appliance-ta-rendered"

PRODUCTS: dict[str, dict[str, Any]] = {
    "carbon_black": {
        "label": "Carbon Black",
        "app": "Splunk_TA_bit9-carbonblack",
        "id": "2790",
        "version": "3.0.0",
        "source_pack": "carbon_black",
        "transport": "json_file_monitor",
        "sourcetypes": ["bit9:carbonblack:json"],
        "eventtypes": [
            "bit9_carbonblack_alert",
            "bit9_carbonblack_network",
            "carbonblack_endpoint_processes",
            "edr_carbonblack_alert",
        ],
        "lookups": ["bit9_cbs_actions_lookup", "bit9_cbs_description_lookup"],
    },
    "symantec_endpoint_protection": {
        "label": "Symantec Endpoint Protection",
        "app": "Splunk_TA_symantec-ep",
        "id": "2772",
        "version": "4.0.0",
        "source_pack": "symantec_endpoint_protection",
        "transport": "file_monitor_or_sc4s_syslog",
        "sourcetypes": [
            "symantec:ep:syslog",
            "symantec:ep:admin:file",
            "symantec:ep:admin:syslog",
            "symantec:ep:risk:file",
            "symantec:ep:risk:syslog",
            "symantec:ep:security:file",
            "symantec:ep:security:syslog",
            "symantec:ep:traffic:file",
            "symantec:ep:traffic:syslog",
        ],
        "eventtypes": [
            "symantec_ep_admin_authentication",
            "symantec_ep_risk",
            "symantec_ep_security_alert",
            "symantec_ep_traffic",
        ],
        "lookups": [
            "symantec_ep_action_lookup",
            "symantec_ep_data_model_lookup",
            "symantec_ep_severity_lookup",
        ],
    },
}

SYMANTEC_MONITORS = [
    ("scm_admin.tmp", "symantec:ep:admin:file"),
    ("agt_risk.tmp", "symantec:ep:risk:file"),
    ("agt_security.tmp", "symantec:ep:security:file"),
    ("agt_traffic.tmp", "symantec:ep:traffic:file"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render security appliance add-on assets.")
    parser.add_argument("--phase", choices=("render", "list"), default="render")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--products",
        default="carbon_black,symantec_endpoint_protection",
        help="Selectors: carbon_black,symantec_endpoint_protection",
    )
    parser.add_argument("--index", default="endpoint", help="Target security event index.")
    parser.add_argument("--carbon-black-json-dir", default="/var/lib/carbonblack/json")
    parser.add_argument("--symantec-dump-dir", default="/var/lib/symantec_ep/dump")
    parser.add_argument("--syslog-port", default="514")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def selected_products(raw: str) -> list[str]:
    values = [item.strip().lower() for item in raw.split(",") if item.strip()]
    unknown = [item for item in values if item not in PRODUCTS]
    if not values or unknown:
        raise SystemExit(f"ERROR: choose product selectors from {', '.join(PRODUCTS)}")
    return values


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def render_inputs(args: argparse.Namespace, products: list[str]) -> str:
    lines = [
        "# Starter local/inputs.conf overlays from extracted package templates.",
        "# Enable only on the approved file-monitor owner.",
        "",
    ]
    if "carbon_black" in products:
        lines += [
            f"[monitor://{args.carbon_black_json_dir}]",
            "disabled = 1",
            "sourcetype = bit9:carbonblack:json",
            f"index = {args.index}",
            "",
        ]
    if "symantec_endpoint_protection" in products:
        for filename, sourcetype in SYMANTEC_MONITORS:
            lines += [
                f"[monitor://{args.symantec_dump_dir}/{filename}]",
                "disabled = 1",
                f"sourcetype = {sourcetype}",
                f"index = {args.index}",
                "",
            ]
    return "\n".join(lines).rstrip() + "\n"


def render_transport(args: argparse.Namespace, products: list[str]) -> str:
    lines = [
        "# Security Appliance Transport Handoff",
        "",
        f"Default syslog port for Symantec EP handoff: `{args.syslog_port}`",
        f"Target index: `{args.index}`",
        "",
    ]
    if "carbon_black" in products:
        lines += [
            "## Carbon Black",
            "",
            "Transport owner: upstream Carbon Black JSON export/script or pub-sub bridge.",
            f"Splunk file monitor directory: `{args.carbon_black_json_dir}`",
            "Package source type: `bit9:carbonblack:json`",
            "",
        ]
    if "symantec_endpoint_protection" in products:
        lines += [
            "## Symantec Endpoint Protection",
            "",
            "Transport owner: file monitor from SEP manager dump files or SC4S/syslog.",
            "Package syslog source types:",
            "- `symantec:ep:syslog`",
            "- `symantec:ep:admin:syslog`",
            "- `symantec:ep:risk:syslog`",
            "- `symantec:ep:security:syslog`",
            "- `symantec:ep:traffic:syslog`",
            "",
            "Do not ingest SEP as generic `syslog`; stamp the package source type at the collector or parsing tier.",
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"


def render_plan(args: argparse.Namespace, products: list[str]) -> str:
    rows = [
        f"| `{key}` | `{profile['app']}` | `{profile['id']}` | `{profile['version']}` | `{profile['transport']}` | `{profile['source_pack']}` |"
        for key, profile in ((key, PRODUCTS[key]) for key in products)
    ]
    return f"""# Security Appliance Supported Add-ons Setup Plan

Target index: `{args.index}`

| Selector | App | Splunkbase | Verified | Transport | Source Pack |
| --- | --- | --- | --- | --- | --- |
{chr(10).join(rows)}

Unresolved security products remain generic install-only until exact package
IDs and extracted package contents are verified.
"""


def render_install_commands(args: argparse.Namespace, products: list[str]) -> str:
    lines = ["#!/usr/bin/env bash", "set -euo pipefail", "", "# Review before running. No secrets are embedded in this file."]
    for key in products:
        profile = PRODUCTS[key]
        lines.append(
            f"bash skills/splunk-app-install/scripts/install_app.sh --source splunkbase --app-id {profile['id']} --app-version {profile['version']} --no-update  # {profile['app']}"
        )
    packs = ",".join(PRODUCTS[key]["source_pack"] for key in products)
    lines += [
        f"bash skills/splunk-security-appliance-ta-setup/scripts/setup.sh --create-index --index {args.index}",
        f"bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh --phase collect --source-pack {packs}",
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_validation(args: argparse.Namespace, products: list[str]) -> str:
    clauses = []
    for key in products:
        sourcetypes = ",".join(f'"{item}"' for item in PRODUCTS[key]["sourcetypes"])
        clauses.append(f"(index={args.index} sourcetype IN ({sourcetypes}))")
    return f"""# Security appliance validation searches

{' OR '.join(clauses)}
| stats count min(_time) as first_seen max(_time) as last_seen by sourcetype host source
| convert ctime(first_seen) ctime(last_seen)

index=_internal source=*splunkd.log* ({' OR '.join(PRODUCTS[key]['app'] for key in products)} OR symantec OR carbonblack)
| stats count values(log_level) as levels by component
"""


def render_assets(args: argparse.Namespace, products: list[str]) -> dict[str, Any]:
    output = Path(args.output_dir).expanduser().resolve() / "splunk-security-appliance-ta"
    files = [
        "inputs.local.conf.template",
        "install-commands.sh",
        "metadata.json",
        "profile-plan.md",
        "transport-handoff.md",
        "validation-searches.spl",
    ]
    if args.dry_run:
        return {"ok": True, "dry_run": True, "output_dir": str(output), "files": files}
    metadata = {
        "index": args.index,
        "products": products,
        "profiles": {key: PRODUCTS[key] for key in products},
    }
    write_file(output / "metadata.json", json.dumps(metadata, indent=2, sort_keys=True))
    write_file(output / "profile-plan.md", render_plan(args, products))
    write_file(output / "inputs.local.conf.template", render_inputs(args, products))
    write_file(output / "transport-handoff.md", render_transport(args, products))
    write_file(output / "install-commands.sh", render_install_commands(args, products), executable=True)
    write_file(output / "validation-searches.spl", render_validation(args, products))
    return {"ok": True, "dry_run": False, "output_dir": str(output), "files": sorted(files)}


def emit(payload: dict[str, Any], json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"Output: {payload.get('output_dir', '')}")
        if payload.get("files"):
            print("Files: " + ", ".join(payload["files"]))


def main() -> int:
    args = parse_args()
    products = selected_products(args.products)
    if args.phase == "list":
        emit({"ok": True, "products": products, "profiles": {key: PRODUCTS[key] for key in products}}, args.json)
        return 0
    emit(render_assets(args, products), args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

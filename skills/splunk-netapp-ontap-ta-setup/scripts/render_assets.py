#!/usr/bin/env python3
"""Render package-verified NetApp ONTAP supported add-on assets."""

from __future__ import annotations

import argparse
import json
import stat
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = REPO_ROOT / "splunk-netapp-ontap-ta-rendered"

PRODUCTS: dict[str, dict[str, Any]] = {
    "ontap": {
        "label": "NetApp ONTAP core",
        "app": "Splunk_TA_ontap",
        "id": "3418",
        "version": "3.2.0",
        "role": "scheduler and collection workers",
    },
    "extractions": {
        "label": "ONTAP Field Extractions",
        "app": "TA-ONTAP-FieldExtractions",
        "id": "5615",
        "version": "3.0.3",
        "role": "search-time field extractions and eventtypes",
    },
    "indexes": {
        "label": "ONTAP Indexes",
        "app": "SA-ONTAPIndex",
        "id": "5616",
        "version": "3.0.3",
        "role": "ontap index definition",
    },
}

SOURCETYPES = [
    "ontap:perf",
    "ontap:volume",
    "ontap:aggr",
    "ontap:disk",
    "ontap:system",
    "ontap:lun",
    "ontap:ems",
    "ontap:syslog",
]

HYDRA_SOURCETYPES = [
    "hydra_access",
    "hydra_gatekeeper",
    "hydra_gateway",
    "hydra_scheduler",
    "hydra_worker",
]

EVENTTYPES = [
    "ontap_aggr",
    "ontap_disk",
    "ontap_lun",
    "ontap_system_cluster",
    "ontap_volume",
    "ontap_vserver",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render NetApp ONTAP supported add-on assets.")
    parser.add_argument("--phase", choices=("render", "list"), default="render")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--products", default="ontap,extractions,indexes", help="Selectors: ontap,extractions,indexes")
    parser.add_argument("--index", default="ontap", help="Target ONTAP event index.")
    parser.add_argument("--account-name", default="ontap_prod", help="ONTAP account stanza name.")
    parser.add_argument("--worker-count", default="8", help="Expected worker count for review notes.")
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


def render_inputs(args: argparse.Namespace) -> str:
    return f"""# Starter local/inputs.conf review overlay for Splunk_TA_ontap.
# Keep collection centralized on approved ONTAP collection nodes.

[ta_ontap_collection_scheduler://nidhogg]
disabled = 1
account = {args.account_name}
index = {args.index}

[ta_ontap_collection_worker://alpha]
disabled = 1
account = {args.account_name}
index = {args.index}

[ta_ontap_collection_worker://beta]
disabled = 1
account = {args.account_name}
index = {args.index}
"""


def render_scheduler_worker(args: argparse.Namespace) -> str:
    return f"""# ONTAP Scheduler And Worker Placement

Account: `{args.account_name}`
Index: `{args.index}`
Expected worker count for review: `{args.worker_count}`

The extracted package uses `ta_ontap_collection_scheduler` and
`ta_ontap_collection_worker` stanzas. Keep the scheduler and workers on the
approved collection tier and avoid duplicate schedulers for the same ONTAP
cluster/account.

## Hydra Troubleshooting Checks

- Search `_internal` for `hydra_scheduler` and `hydra_worker`.
- Confirm worker stanzas such as `alpha` and `beta` start after scheduler
  initialization.
- Validate data coverage for `ontap:perf`, `ontap:volume`, `ontap:system`,
  `ontap:aggr`, and `ontap:disk`.

## ITSI Handoff

After source type coverage is present, hand storage-service modeling to
`splunk-itsi-config` or the appropriate ITSI content pack workflow.
"""


def render_plan(args: argparse.Namespace, products: list[str]) -> str:
    rows = [
        f"| `{key}` | `{profile['app']}` | `{profile['id']}` | `{profile['version']}` | `{profile['role']}` |"
        for key, profile in ((key, PRODUCTS[key]) for key in products)
    ]
    return f"""# NetApp ONTAP Supported Add-ons Setup Plan

Target index: `{args.index}`

| Selector | App | Splunkbase | Verified | Role |
| --- | --- | --- | --- | --- |
{chr(10).join(rows)}

Package ONTAP source types: {', '.join(f'`{item}`' for item in SOURCETYPES)}
Hydra troubleshooting source types: {', '.join(f'`{item}`' for item in HYDRA_SOURCETYPES)}
"""


def render_install_commands(args: argparse.Namespace, products: list[str]) -> str:
    lines = ["#!/usr/bin/env bash", "set -euo pipefail", "", "# Review before running. No secrets are embedded in this file."]
    for key in products:
        profile = PRODUCTS[key]
        lines.append(
            f"bash skills/splunk-app-install/scripts/install_app.sh --source splunkbase --app-id {profile['id']} --app-version {profile['version']} --no-update  # {profile['app']}"
        )
    lines += [
        f"bash skills/splunk-netapp-ontap-ta-setup/scripts/setup.sh --create-index --index {args.index}",
        "bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh --phase collect --source-pack netapp_ontap",
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_validation(args: argparse.Namespace) -> str:
    sourcetypes = ",".join(f'"{item}"' for item in SOURCETYPES)
    hydra = ",".join(f'"{item}"' for item in HYDRA_SOURCETYPES)
    return f"""# NetApp ONTAP validation searches

index={args.index} sourcetype IN ({sourcetypes})
| stats count min(_time) as first_seen max(_time) as last_seen by sourcetype host source
| convert ctime(first_seen) ctime(last_seen)

index=_internal sourcetype IN ({hydra})
| stats count values(log_level) as levels by sourcetype component

index=_internal source=*splunkd.log* (ta_ontap_collection_scheduler OR ta_ontap_collection_worker OR SA-Hydra OR Splunk_TA_ontap)
| stats count values(log_level) as levels by component
"""


def render_assets(args: argparse.Namespace, products: list[str]) -> dict[str, Any]:
    output = Path(args.output_dir).expanduser().resolve() / "splunk-netapp-ontap-ta"
    files = [
        "inputs.local.conf.template",
        "install-commands.sh",
        "metadata.json",
        "profile-plan.md",
        "scheduler-worker-placement.md",
        "validation-searches.spl",
    ]
    if args.dry_run:
        return {"ok": True, "dry_run": True, "output_dir": str(output), "files": files}
    metadata = {
        "index": args.index,
        "products": products,
        "profiles": {key: PRODUCTS[key] for key in products},
        "sourcetypes": SOURCETYPES,
        "hydra_sourcetypes": HYDRA_SOURCETYPES,
        "eventtypes": EVENTTYPES,
        "source_pack": "netapp_ontap",
    }
    write_file(output / "metadata.json", json.dumps(metadata, indent=2, sort_keys=True))
    write_file(output / "profile-plan.md", render_plan(args, products))
    write_file(output / "inputs.local.conf.template", render_inputs(args))
    write_file(output / "scheduler-worker-placement.md", render_scheduler_worker(args))
    write_file(output / "install-commands.sh", render_install_commands(args, products), executable=True)
    write_file(output / "validation-searches.spl", render_validation(args))
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

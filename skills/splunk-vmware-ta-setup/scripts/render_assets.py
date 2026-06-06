#!/usr/bin/env python3
"""Render Splunk VMware setup assets."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


DEFAULT_DOCS = [
    "https://help.splunk.com/en/splunk-cloud-platform/get-data-in/splunk-supported-add-ons/vmware",
    "https://help.splunk.com/en/splunk-cloud-platform/get-data-in/splunk-supported-add-ons",
]


def slug(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-").lower()
    return text or "vmware"


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def indexes_conf(event_index: str, esxi_index: str, metrics_index: str) -> str:
    return f"""# Review before placing on indexers or a cluster-manager bundle.
[{event_index}]
homePath = $SPLUNK_DB/{event_index}/db
coldPath = $SPLUNK_DB/{event_index}/colddb
thawedPath = $SPLUNK_DB/{event_index}/thaweddb

[{esxi_index}]
homePath = $SPLUNK_DB/{esxi_index}/db
coldPath = $SPLUNK_DB/{esxi_index}/colddb
thawedPath = $SPLUNK_DB/{esxi_index}/thaweddb

[{metrics_index}]
datatype = metric
homePath = $SPLUNK_DB/{metrics_index}/db
coldPath = $SPLUNK_DB/{metrics_index}/colddb
thawedPath = $SPLUNK_DB/{metrics_index}/thaweddb
"""


def validation_spl(event_index: str, esxi_index: str, metrics_index: str) -> str:
    return f"""# VMware package and data validation searches.
| rest /services/apps/local | search title IN ("Splunk_TA_vmware","Splunk_TA_esxilogs","Splunk_TA_vmware_inframon") | table title version disabled

| eventcount summarize=false index={event_index} index={esxi_index} index={metrics_index}

index={event_index} OR index={esxi_index} sourcetype=vmware* earliest=-24h
| stats count min(_time) as first max(_time) as last by index sourcetype host
| convert ctime(first) ctime(last)

| mstats count where index={metrics_index} earliest=-24h by metric_name
"""


def install_commands() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail

# Install one approved VMware package at a time. Package values are local file
# paths, not Splunkbase IDs, because VMware deployments commonly use a package
# set selected for the target Splunk and VMware support matrix.
: "${VMWARE_PACKAGE:?Set VMWARE_PACKAGE to the local .spl/.tgz package path}"
bash skills/splunk-app-install/scripts/install_app.sh --source local --file "${VMWARE_PACKAGE}" --no-update
"""


def plan_md(args: argparse.Namespace) -> str:
    vc = args.vcenter_host or "<vcenter-host>"
    return f"""# Splunk VMware Setup Plan

## Target Indexes

- vCenter inventory/task/event/log index: `{args.event_index}`
- ESXi syslog index: `{args.esxi_index}`
- VMware metrics index: `{args.metrics_index}` (`datatype = metric`)

## Package Placement

- Search tier: VMware app UI, dashboards, macros, lookups, and search-time knowledge.
- Indexers or cluster manager: index definitions and any parser package required by the selected VMware package family.
- Heavy forwarder / Data Collection Node: vCenter API collection for `{vc}` using account stanza `{args.vcenter_account}`.
- External syslog collector: ESXi syslog path, commonly through `splunk-connect-for-syslog-setup`.

## Operator Sequence

1. Install the approved VMware package set with `install-commands.sh` or `splunk-app-install`.
2. Apply `indexes.conf.template` on indexers or the cluster manager.
3. Configure the vCenter account using `vcenter-account-runbook.md`.
4. Configure one collection owner per vCenter scope.
5. Configure ESXi syslog using `esxi-syslog-runbook.md`.
6. Run `validation-searches.spl`.
7. Hand off ITSI entity and KPI modeling using `itsi-readiness.md`.

## Guardrails

- Do not run duplicate vCenter collection owners for the same scope.
- Do not paste vCenter credentials into chat, environment-variable prefixes, or command-line flags.
- Keep metrics in a metrics index and align dashboard macros with the final index names.
"""


def vcenter_runbook(args: argparse.Namespace) -> str:
    vc = args.vcenter_host or "<vcenter-host>"
    return f"""# vCenter Account Runbook

Account stanza: `{args.vcenter_account}`
vCenter host: `{vc}`

1. Create a least-privilege vCenter service account for inventory, task/event,
   log, and performance collection.
2. Store the password in a local chmod 600 file:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/vcenter_password
```

3. Configure the account in the selected VMware add-on account workflow.
4. Assign one collection owner for `{vc}`. Do not duplicate the same vCenter
   scope across multiple DCNs.
5. Confirm collection intervals and checkpoint location before enabling inputs.
"""


def esxi_runbook(args: argparse.Namespace) -> str:
    return f"""# ESXi Syslog Runbook

Target index: `{args.esxi_index}`

1. Choose the syslog owner: SC4S, syslog-ng, Splunk Enterprise receiver, or a
   customer-managed forwarding path.
2. Render collector assets in `splunk-connect-for-syslog-setup` when SC4S owns
   normalization.
3. Point ESXi hosts at the approved receiver using TCP/TLS or UDP according to
   the site standard.
4. Preserve host identity and sourcetype mapping expected by the selected VMware
   ESXi Logs package.
5. Validate data with `validation-searches.spl` before dashboard or ITSI claims.
"""


def itsi_readiness(args: argparse.Namespace) -> str:
    return f"""# VMware ITSI Readiness

Run these checks before enabling VMware content packs, service trees, or KPI
templates:

- vCenter inventory appears in `{args.event_index}` with stable host, cluster,
  datastore, and VM identifiers.
- ESXi host logs appear in `{args.esxi_index}` with consistent hostnames.
- Metrics appear in `{args.metrics_index}` through `mstats`.
- Dashboard macros point at the selected indexes.
- Entity aliases do not create duplicates between vCenter names, ESXi hostnames,
  DNS names, and IP addresses.

Suggested handoff:

```bash
VMWARE_RENDERED_DIR="${{VMWARE_RENDERED_DIR:-splunk-vmware-ta-rendered}}"
DSRD_RENDERED_DIR="${{DSRD_RENDERED_DIR:-splunk-data-source-readiness-doctor-rendered}}"
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh --phase source-packs --json
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh --phase collect --targets itsi --evidence-file "${{VMWARE_RENDERED_DIR}}/vmware-readiness-evidence.template.json" --output-dir "${{DSRD_RENDERED_DIR}}"
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh --phase synthesize --targets itsi --evidence-file "${{VMWARE_RENDERED_DIR}}/vmware-readiness-evidence.template.json" --collector-results-file "${{DSRD_RENDERED_DIR}}/live-collector-results.redacted.json" --output-dir "${{DSRD_RENDERED_DIR}}"
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh --phase doctor --targets itsi --evidence-file "${{DSRD_RENDERED_DIR}}/evidence/live-evidence.synthesized.json" --output-dir "${{DSRD_RENDERED_DIR}}"
bash skills/splunk-itsi-config/scripts/setup.sh --help
```
"""


def readiness_evidence(args: argparse.Namespace) -> str:
    payload = {
        "platform": "auto",
        "targets": ["itsi"],
        "products": {"itsi": {"installed": True}},
        "data_sources": [
            {
                "name": "VMware vCenter inventory and events",
                "skill": "splunk-vmware-ta-setup",
                "expected_indexes": [args.event_index],
                "expected_sourcetypes": ["vmware:*"],
                "sample_events": {
                    "count": 0,
                    "latest_age_minutes": 999999,
                    "volume_below_baseline": True,
                },
                "itsi": {
                    "expected_content_packs": ["VMware Monitoring"],
                    "content_pack_profile": {
                        "profile": "vmware",
                        "event_indexes": [args.event_index],
                        "metrics_indexes": [args.metrics_index],
                    },
                },
            },
            {
                "name": "VMware ESXi syslog",
                "skill": "splunk-vmware-ta-setup",
                "expected_indexes": [args.esxi_index],
                "expected_sourcetypes": ["vmw-syslog", "vmware:esxlog:*"],
                "sample_events": {
                    "count": 0,
                    "latest_age_minutes": 999999,
                    "volume_below_baseline": True,
                },
                "itsi": {
                    "expected_content_packs": ["VMware Monitoring"],
                    "content_pack_profile": {
                        "profile": "vmware",
                        "log_indexes": [args.esxi_index],
                    },
                },
            },
            {
                "name": "VMware performance metrics",
                "skill": "splunk-vmware-ta-setup",
                "expected_indexes": [args.metrics_index],
                "metrics": {
                    "expected_indexes": [args.metrics_index],
                    "expected_dimensions": ["host", "moid", "instance"],
                    "metric_names_missing": ["<replace-after-mpreview>"],
                    "dimensions_missing": ["host", "moid", "instance"],
                    "mstats_zero_results": True,
                },
                "itsi": {
                    "expected_content_packs": ["VMware Monitoring"],
                    "content_pack_profile": {
                        "profile": "vmware",
                        "metrics_indexes": [args.metrics_index],
                    },
                },
            },
        ],
        "handoffs": {"unrouted": []},
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def metadata(args: argparse.Namespace, files: list[str]) -> dict[str, object]:
    return {
        "skill": "splunk-vmware-ta-setup",
        "event_index": args.event_index,
        "esxi_index": args.esxi_index,
        "metrics_index": args.metrics_index,
        "vcenter_account": args.vcenter_account,
        "vcenter_host": args.vcenter_host,
        "files": files,
        "handoffs": [
            "splunk-app-install",
            "splunk-connect-for-syslog-setup",
            "splunk-agent-management-setup",
            "splunk-data-source-readiness-doctor",
            "splunk-itsi-config",
        ],
        "docs": DEFAULT_DOCS,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-index", default="vmware")
    parser.add_argument("--esxi-index", default="vmware_esxi")
    parser.add_argument("--metrics-index", default="vmware_metrics")
    parser.add_argument("--vcenter-account", default="vc_prod")
    parser.add_argument("--vcenter-host", default="")
    parser.add_argument("--output-dir", default="splunk-vmware-ta-rendered")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    output = Path(args.output_dir).expanduser().resolve()
    files = [
        "vmware-plan.md",
        "indexes.conf.template",
        "validation-searches.spl",
        "vcenter-account-runbook.md",
        "esxi-syslog-runbook.md",
        "itsi-readiness.md",
        "vmware-readiness-evidence.template.json",
        "install-commands.sh",
        "metadata.json",
    ]
    write(output / "vmware-plan.md", plan_md(args))
    write(output / "indexes.conf.template", indexes_conf(args.event_index, args.esxi_index, args.metrics_index))
    write(output / "validation-searches.spl", validation_spl(args.event_index, args.esxi_index, args.metrics_index))
    write(output / "vcenter-account-runbook.md", vcenter_runbook(args))
    write(output / "esxi-syslog-runbook.md", esxi_runbook(args))
    write(output / "itsi-readiness.md", itsi_readiness(args))
    write(output / "vmware-readiness-evidence.template.json", readiness_evidence(args))
    write(output / "install-commands.sh", install_commands())
    write(output / "metadata.json", json.dumps(metadata(args, files), indent=2, sort_keys=True))

    result = {"ok": True, "output_dir": str(output), "files": files, "metadata": metadata(args, files)}
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Rendered VMware setup assets to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

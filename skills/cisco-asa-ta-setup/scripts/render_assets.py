#!/usr/bin/env python3
"""Render Cisco ASA TA setup assets."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "skills" / "shared" / "lib"))

from render_first_app import main  # noqa: E402


CONFIG = {
    "skill_name": "cisco-asa-ta-setup",
    "title": "Cisco ASA TA Setup",
    "description": "Render Cisco ASA/FTD syslog and Splunk_TA_cisco-asa readiness assets.",
    "default_output_dir": "cisco-asa-ta-rendered",
    "profile_dir": "cisco-asa-ta",
    "primary_app_name": "Splunk_TA_cisco-asa",
    "primary_splunkbase_id": "1620",
    "source_types": ["cisco:asa"],
    "handoff_skills": [
        "splunk-app-install",
        "splunk-connect-for-syslog-setup",
        "splunk-cim-data-model-setup",
        "splunk-enterprise-security-config",
        "splunk-data-source-readiness-doctor",
    ],
    "arguments": [
        {"flag": "--index", "default": "cisco_asa", "help": "Target ASA event index."},
        {"flag": "--sourcetype", "default": "cisco:asa", "help": "Normalized ASA source type."},
        {
            "flag": "--syslog-owner",
            "default": "sc4s",
            "choices": ["sc4s", "syslog-ng", "splunk", "customer"],
            "help": "Owner of the syslog receive path.",
        },
        {
            "flag": "--sc4s-vendor-product",
            "default": "cisco_asa",
            "help": "SC4S vendor_product override for Cisco ASA data.",
        },
        {"flag": "--include-ftd", "action": "store_true", "help": "Include Firepower Threat Defense checklist rows."},
    ],
    "metadata": {
        "app_name": "Splunk_TA_cisco-asa",
        "splunkbase_id": "1620",
        "latest_verified_version": "6.0.1",
        "index": "{{index}}",
        "sourcetype": "{{sourcetype}}",
        "syslog_owner": "{{syslog_owner}}",
        "sc4s_vendor_product": "{{sc4s_vendor_product}}",
        "include_ftd": "{{include_ftd}}",
        "source_package": "splunk-ta/_unpacked/Splunk_TA_cisco-asa-6.0.1/Splunk_TA_cisco-asa",
        "cim_models": ["Network_Traffic", "Intrusion_Detection"],
    },
    "plan_md": """# Cisco ASA TA Setup Plan

Add-on: `Splunk_TA_cisco-asa` (Splunkbase `1620`, verified `6.0.1`)
Index: `{{index}}`
Source type: `{{sourcetype}}`
Syslog owner: `{{syslog_owner}}`
SC4S vendor_product: `{{sc4s_vendor_product}}`
Include FTD checklist: `{{include_ftd}}`

## Role Placement

| Role | Placement |
| --- | --- |
| `search-tier` | Install TA for search-time knowledge and CIM mappings |
| `indexer` | Install TA when parsing/index-time transforms run on indexers |
| `heavy-forwarder` | Install TA when syslog is received or parsed on a heavy forwarder |
| `external-collector` | Own SC4S/syslog receiver and forward to Splunk |
| `universal-forwarder` | Not a direct ASA network syslog receiver |

## Device Logging Checklist

- Send ASA/FTD syslog to the reviewed receiver path and preserve host/source.
- Keep severity and message ID fields intact for connection, teardown, ACL, VPN,
  threat, and intrusion messages.
- Confirm receiver metadata maps events to `{{sourcetype}}` before scoring CIM.
- Review sourcetype and index routing before enabling ES detections or PCI
  reports that depend on firewall traffic.
""",
    "handoffs_md": """# Cisco ASA Handoffs

## App Install

Install `Splunk_TA_cisco-asa` through `splunk-app-install` or the Splunk Cloud
app workflow. The rendered command is a reviewable handoff; `setup.sh --install`
and `setup.sh --all` execute that installer explicitly.

## Syslog Receiver

Use `splunk-connect-for-syslog-setup` or the customer syslog owner to configure
the receiver. For SC4S, review vendor_product `{{sc4s_vendor_product}}` and
route to index `{{index}}` with sourcetype `{{sourcetype}}`.

## Security Readiness

Hand off CIM acceleration to `splunk-cim-data-model-setup` and ES content/risk
readiness to `splunk-enterprise-security-config`. Use
`splunk-data-source-readiness-doctor` source pack `cisco_asa` after data lands.
""",
    "install_commands": """#!/usr/bin/env bash
set -euo pipefail

# Review before running. This file contains no secrets.
bash skills/splunk-app-install/scripts/install_app.sh --source splunkbase --app-id 1620
bash skills/splunk-connect-for-syslog-setup/scripts/setup.sh --help
bash skills/splunk-cim-data-model-setup/scripts/setup.sh --help
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh --phase collect --source-pack cisco_asa
""",
    "validation_searches": """# Cisco ASA validation searches

index={{index}} sourcetype={{sourcetype}}
| stats count min(_time) as first_seen max(_time) as last_seen dc(host) as hosts dc(src) as srcs dc(dest) as dests values(action) as actions by dvc sourcetype
| convert ctime(first_seen) ctime(last_seen)

| tstats count from datamodel=Network_Traffic.All_Traffic where All_Traffic.sourcetype={{sourcetype}} by All_Traffic.action All_Traffic.src All_Traffic.dest

| tstats count from datamodel=Intrusion_Detection.IDS_Attacks where IDS_Attacks.sourcetype={{sourcetype}} by IDS_Attacks.signature IDS_Attacks.src IDS_Attacks.dest

index=_internal source=*splunkd.log* (Splunk_TA_cisco-asa OR cisco:asa OR "{{sc4s_vendor_product}}")
| stats count values(log_level) as levels by host component
""",
    "readiness_evidence": {
        "name": "Cisco ASA",
        "source_pack_id": "cisco_asa",
        "app_name": "Splunk_TA_cisco-asa",
        "expected_indexes": ["{{index}}"],
        "expected_sourcetypes": ["{{sourcetype}}"],
        "cim": {
            "expected_models": ["Network_Traffic", "Intrusion_Detection"],
            "required_fields": ["src", "dest", "action", "dvc", "signature"],
        },
        "handoffs": ["cisco-asa-ta-setup", "splunk-connect-for-syslog-setup"],
    },
    "additional_files": [
        {
            "path": "syslog-receiver-checklist.md",
            "content": """# ASA Syslog Receiver Checklist

- Receiver owner: `{{syslog_owner}}`
- Target index: `{{index}}`
- Target sourcetype: `{{sourcetype}}`
- SC4S vendor_product: `{{sc4s_vendor_product}}`
- Preserve original ASA/FTD host, source IP, facility, severity, and message ID.
- Confirm no duplicate collection path sends the same ASA messages twice.
""",
        }
    ],
}


if __name__ == "__main__":
    raise SystemExit(main(CONFIG))

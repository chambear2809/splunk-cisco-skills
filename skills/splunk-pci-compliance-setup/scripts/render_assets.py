#!/usr/bin/env python3
"""Render Splunk PCI Compliance setup assets."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "skills" / "shared" / "lib"))

from render_first_app import main  # noqa: E402


CONFIG = {
    "skill_name": "splunk-pci-compliance-setup",
    "title": "Splunk PCI Compliance Setup",
    "description": "Render PCI Compliance readiness assets.",
    "default_output_dir": "splunk-pci-compliance-rendered",
    "profile_dir": "splunk-pci-compliance",
    "primary_app_name": "SplunkPCIComplianceSuite",
    "primary_splunkbase_id": "1143",
    "handoff_skills": ["splunk-app-install", "splunk-enterprise-security-config", "splunk-cim-data-model-setup", "splunk-knowledge-objects-setup"],
    "arguments": [
        {"flag": "--platform", "default": "auto", "choices": ["cloud", "enterprise", "auto"], "help": "Target Splunk platform."},
        {"flag": "--es-app", "default": "SplunkEnterpriseSecuritySuite", "help": "Enterprise Security app name."},
        {"flag": "--cde-indexes", "default": "cardholder,netfw,identity", "help": "Comma-separated cardholder data environment indexes."},
        {"flag": "--pci-macro", "default": "pci_indexes", "help": "Primary PCI index macro."},
        {"flag": "--installer-profile", "default": "auto", "choices": ["auto", "enterprise", "enterprise-security"], "help": "Installer profile."},
    ],
    "csv_context_fields": ["cde_indexes"],
    "metadata": {
        "app_name": "SplunkPCIComplianceSuite",
        "splunkbase_ids": ["1143", "2897"],
        "platform": "{{platform}}",
        "es_app": "{{es_app}}",
        "cde_indexes": "{{cde_indexes}}",
        "pci_macro": "{{pci_macro}}",
        "installer_profile": "{{installer_profile}}",
    },
    "plan_md": """# Splunk PCI Compliance Setup Plan

App: `SplunkPCIComplianceSuite`
Splunkbase IDs: `1143` standalone Enterprise, `2897` Enterprise Security
Platform: `{{platform}}`
Installer profile: `{{installer_profile}}`
CDE indexes: `{{cde_indexes}}`
Primary macro: `{{pci_macro}}`

## Readiness Gates

- Select the correct installer for standalone Enterprise or ES.
- Confirm CDE index access for PCI roles and service accounts.
- Align `{{pci_macro}}` and related macros to reviewed CDE indexes.
- Validate CIM/data models before scoring PCI reports.
- Review report schedules and dashboard panels before compliance sign-off.
""",
    "handoffs_md": """# PCI Compliance Handoffs

- Install app `1143` or ES installer `2897` through `splunk-app-install`.
- Configure ES/CIM/data model dependencies through
  `splunk-enterprise-security-config` and `splunk-cim-data-model-setup`.
- Maintain CDE macros, lookups, and ownership through
  `splunk-knowledge-objects-setup`.
""",
    "install_commands": """#!/usr/bin/env bash
set -euo pipefail

# Review installer profile before running.
bash skills/splunk-app-install/scripts/install_app.sh --source splunkbase --app-id 1143
# For Enterprise Security installer profile, use app id 2897 instead.
bash skills/splunk-cim-data-model-setup/scripts/setup.sh --help
bash skills/splunk-knowledge-objects-setup/scripts/setup.sh --help
""",
    "validation_searches": """# PCI Compliance validation searches

| rest /services/apps/local/SplunkPCIComplianceSuite
| table title version disabled visible eai:acl.app

| rest /servicesNS/-/-/admin/macros splunk_server=local
| search title="{{pci_macro}}"
| table title definition eai:acl.app eai:acl.sharing

index IN ({{cde_indexes}})
| stats count min(_time) as first_seen max(_time) as last_seen by index sourcetype
| convert ctime(first_seen) ctime(last_seen)

| rest /servicesNS/-/-/saved/searches splunk_server=local
| search eai:acl.app=SplunkPCIComplianceSuite
| stats count values(disabled) as disabled by eai:acl.app
""",
    "readiness_evidence": {
        "name": "Splunk PCI Compliance",
        "app_name": "SplunkPCIComplianceSuite",
        "product": "Splunk App for PCI Compliance",
        "expected_indexes": "{{cde_indexes_list}}",
        "expected_macros": ["{{pci_macro}}"],
        "cim": {"expected_models": ["Authentication", "Change", "Endpoint", "Intrusion_Detection", "Malware", "Network_Traffic", "Vulnerabilities"]},
        "dashboards": {"expected": ["PCI Compliance posture", "PCI reports"]},
        "handoffs": ["splunk-pci-compliance-setup", "splunk-cim-data-model-setup", "splunk-knowledge-objects-setup"],
    },
}


if __name__ == "__main__":
    raise SystemExit(main(CONFIG))

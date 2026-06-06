#!/usr/bin/env python3
"""Render InfoSec App setup assets."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "skills" / "shared" / "lib"))

from render_first_app import main  # noqa: E402


CONFIG = {
    "skill_name": "splunk-infosec-app-setup",
    "title": "InfoSec App Setup",
    "description": "Render InfoSec App readiness assets.",
    "default_output_dir": "splunk-infosec-app-rendered",
    "profile_dir": "splunk-infosec-app",
    "primary_app_name": "infosec_app_for_splunk",
    "primary_splunkbase_id": "4240",
    "handoff_skills": ["splunk-app-install", "splunk-cim-data-model-setup", "splunk-knowledge-objects-setup", "splunk-lookup-file-editing-setup"],
    "arguments": [
        {"flag": "--platform", "default": "auto", "choices": ["cloud", "enterprise", "auto"], "help": "Target Splunk platform."},
        {"flag": "--es-app", "default": "SplunkEnterpriseSecuritySuite", "help": "Enterprise Security app name when present."},
        {"flag": "--security-indexes", "default": "security,endpoint,network", "help": "Comma-separated security indexes."},
        {"flag": "--cloud-idm-required", "default": "false", "choices": ["true", "false"], "help": "Whether Cloud IDM/support request is expected."},
        {"flag": "--lookup-owner-app", "default": "infosec_app_for_splunk", "help": "App that owns InfoSec lookups."},
    ],
    "csv_context_fields": ["security_indexes"],
    "metadata": {
        "app_name": "infosec_app_for_splunk",
        "splunkbase_id": "4240",
        "platform": "{{platform}}",
        "security_indexes": "{{security_indexes}}",
        "cloud_idm_required": "{{cloud_idm_required}}",
        "lookup_owner_app": "{{lookup_owner_app}}",
    },
    "plan_md": """# InfoSec App Setup Plan

App: `infosec_app_for_splunk` (Splunkbase `4240`)
Platform: `{{platform}}`
Security indexes: `{{security_indexes}}`
Cloud IDM required: `{{cloud_idm_required}}`

## Readiness Gates

- Authentication, endpoint, malware, network, proxy/VPN, vulnerability, and
  asset sources are present and CIM-compatible.
- InfoSec dashboard macros resolve to reviewed indexes.
- Lookup content and ownership are ready for the InfoSec dashboards.
- Splunk Cloud IDM or support-request requirements are captured before package
  deployment when the collection path needs managed infrastructure.
""",
    "handoffs_md": """# InfoSec App Handoffs

- Package install: `splunk-app-install` with Splunkbase `4240`.
- CIM/data-model readiness: `splunk-cim-data-model-setup`.
- Dashboard macro and lookup governance: `splunk-knowledge-objects-setup`.
- Lookup editing and SHC lookup operational notes:
  `splunk-lookup-file-editing-setup`.
""",
    "install_commands": """#!/usr/bin/env bash
set -euo pipefail

# Review before running.
bash skills/splunk-app-install/scripts/install_app.sh --source splunkbase --app-id 4240
bash skills/splunk-cim-data-model-setup/scripts/setup.sh --help
bash skills/splunk-lookup-file-editing-setup/scripts/setup.sh --render --platform {{platform}}
""",
    "validation_searches": """# InfoSec App validation searches

| rest /services/apps/local/infosec_app_for_splunk
| table title version disabled visible eai:acl.app

index IN ({{security_indexes}})
| stats count min(_time) as first_seen max(_time) as last_seen by index sourcetype
| convert ctime(first_seen) ctime(last_seen)

| rest /servicesNS/-/-/admin/macros splunk_server=local
| search eai:acl.app=infosec_app_for_splunk
| table title definition eai:acl.sharing

| rest /servicesNS/-/-/data/ui/views splunk_server=local
| search eai:acl.app=infosec_app_for_splunk
| stats count by eai:acl.app
""",
    "readiness_evidence": {
        "name": "InfoSec App for Splunk",
        "app_name": "infosec_app_for_splunk",
        "product": "InfoSec App for Splunk",
        "expected_indexes": "{{security_indexes_list}}",
        "cim": {"expected_models": ["Authentication", "Endpoint", "Intrusion_Detection", "Malware", "Network_Traffic", "Vulnerabilities"]},
        "dashboards": {"expected": ["Authentication", "Endpoint", "Malware", "Network", "VPN", "Vulnerability"]},
        "handoffs": ["splunk-infosec-app-setup", "splunk-cim-data-model-setup", "splunk-knowledge-objects-setup"],
    },
    "additional_files": [
        {
            "path": "cloud-idm-support-note.md",
            "content": """# Cloud IDM Support Note

Cloud IDM required: `{{cloud_idm_required}}`

If the InfoSec deployment needs managed Cloud IDM collection, parsing, or
private app placement, open a Splunk Support request with the target app,
source add-ons, indexes, and data path. This renderer does not create support
tickets or mutate Cloud infrastructure.
""",
        }
    ],
}


if __name__ == "__main__":
    raise SystemExit(main(CONFIG))

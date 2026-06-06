#!/usr/bin/env python3
"""Render Splunk Security Content Update setup assets."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "skills" / "shared" / "lib"))

from render_first_app import main  # noqa: E402


CONFIG = {
    "skill_name": "splunk-security-content-update-setup",
    "title": "Splunk Security Content Update Setup",
    "description": "Render ESCU readiness assets.",
    "default_output_dir": "splunk-security-content-update-rendered",
    "profile_dir": "splunk-security-content-update",
    "primary_app_name": "DA-ESS-ContentUpdate",
    "primary_splunkbase_id": "3449",
    "handoff_skills": ["splunk-app-install", "splunk-enterprise-security-config", "splunk-cim-data-model-setup"],
    "arguments": [
        {"flag": "--platform", "default": "auto", "choices": ["cloud", "enterprise", "auto"], "help": "Target Splunk platform."},
        {"flag": "--es-app", "default": "SplunkEnterpriseSecuritySuite", "help": "Enterprise Security app name."},
        {"flag": "--story-filter", "default": "all", "help": "Analytic story filter to review."},
        {"flag": "--activation-policy", "default": "review-only", "help": "Correlation-search activation policy note."},
    ],
    "metadata": {
        "app_name": "DA-ESS-ContentUpdate",
        "splunkbase_id": "3449",
        "platform": "{{platform}}",
        "es_app": "{{es_app}}",
        "story_filter": "{{story_filter}}",
        "activation_policy": "{{activation_policy}}",
    },
    "plan_md": """# Security Content Update Setup Plan

App: `DA-ESS-ContentUpdate` (Splunkbase `3449`)
Platform: `{{platform}}`
Enterprise Security app: `{{es_app}}`
Analytic story filter: `{{story_filter}}`
Activation policy: `{{activation_policy}}`

## Placement

Install ESCU on the ES search tier or through the managed ES Cloud app workflow.
Do not deploy ESCU to indexers, universal forwarders, or external collectors.

## Review Gates

- Confirm ES is installed and healthy before installing or upgrading ESCU.
- Inventory analytic stories, detections, macros, lookups, and data-model
  prerequisites.
- Review correlation searches before enablement; enabling content is delegated
  to `splunk-enterprise-security-config`.
""",
    "handoffs_md": """# ESCU Handoffs

- Package install: `splunk-app-install` with Splunkbase `3449`.
- ES content, risk, notable, and correlation-search readiness:
  `splunk-enterprise-security-config`.
- CIM/data model prerequisites: `splunk-cim-data-model-setup`.

Analytic Story Detail navigation and content activation remain review steps; no
content is enabled by this skill.
""",
    "install_commands": """#!/usr/bin/env bash
set -euo pipefail

# Review before running. This file installs package only; activation is separate.
bash skills/splunk-app-install/scripts/install_app.sh --source splunkbase --app-id 3449
bash skills/splunk-enterprise-security-config/scripts/setup.sh --spec skills/splunk-enterprise-security-config/templates/es-config.example.yaml --mode preview
""",
    "validation_searches": """# ESCU validation searches

| rest /services/apps/local/DA-ESS-ContentUpdate
| table title version disabled visible eai:acl.app

| rest /servicesNS/-/-/saved/searches splunk_server=local
| search eai:acl.app=DA-ESS-ContentUpdate OR action.correlationsearch.enabled=*
| stats count values(disabled) as disabled values(action.correlationsearch.enabled) as correlation_enabled by eai:acl.app title

| rest /servicesNS/-/-/data/lookup-table-files splunk_server=local
| search eai:acl.app=DA-ESS-ContentUpdate
| stats count by eai:acl.app
""",
    "readiness_evidence": {
        "name": "Splunk Security Content Update",
        "app_name": "DA-ESS-ContentUpdate",
        "product": "Splunk Enterprise Security Content Update",
        "products": {"es": {"installed": True}},
        "es": {
            "security_content_update_missing": False,
            "analytic_story_filter": "{{story_filter}}",
            "correlation_search_activation_policy": "{{activation_policy}}",
        },
        "handoffs": ["splunk-security-content-update-setup", "splunk-enterprise-security-config"],
    },
}


if __name__ == "__main__":
    raise SystemExit(main(CONFIG))

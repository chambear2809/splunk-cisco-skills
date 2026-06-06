#!/usr/bin/env python3
"""Render Splunk Lookup File Editing setup assets."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "skills" / "shared" / "lib"))

from render_first_app import main  # noqa: E402


CONFIG = {
    "skill_name": "splunk-lookup-file-editing-setup",
    "title": "Splunk Lookup File Editing Setup",
    "description": "Render Lookup File Editing readiness assets.",
    "default_output_dir": "splunk-lookup-file-editing-rendered",
    "profile_dir": "splunk-lookup-file-editing",
    "primary_app_name": "lookup_editor",
    "primary_splunkbase_id": "1724",
    "handoff_skills": ["splunk-app-install", "splunk-knowledge-objects-setup", "splunk-kvstore-admin-setup"],
    "arguments": [
        {"flag": "--platform", "default": "auto", "choices": ["cloud", "enterprise", "auto"], "help": "Target Splunk platform."},
        {"flag": "--es-app", "default": "SplunkEnterpriseSecuritySuite", "help": "Enterprise Security app name when relevant."},
        {"flag": "--lookup-owner-app", "default": "search", "help": "App namespace to inventory for lookup ownership."},
        {"flag": "--lookup-scope", "default": "both", "choices": ["csv", "kvstore", "both"], "help": "Lookup surface to inventory."},
        {"flag": "--shc-mode", "default": "false", "choices": ["true", "false"], "help": "Render SHC allowRestReplay notes."},
    ],
    "metadata": {
        "app_name": "lookup_editor",
        "splunkbase_id": "1724",
        "platform": "{{platform}}",
        "lookup_owner_app": "{{lookup_owner_app}}",
        "lookup_scope": "{{lookup_scope}}",
        "shc_mode": "{{shc_mode}}",
    },
    "plan_md": """# Splunk Lookup File Editing Setup Plan

App: `lookup_editor` (Splunkbase `1724`)
Platform: `{{platform}}`
Lookup owner app: `{{lookup_owner_app}}`
Lookup scope: `{{lookup_scope}}`
SHC mode: `{{shc_mode}}`

## Readiness Gates

- Install Lookup Editor on the search tier only.
- Inventory CSV lookup files and KV Store lookup definitions before granting
  editor access.
- Review ACLs, ownership, automatic lookups, and app namespace boundaries.
- In SHC mode, review `allowRestReplay` and lookup backup replication behavior.
""",
    "handoffs_md": """# Lookup File Editing Handoffs

- Package install: `splunk-app-install` with Splunkbase `1724`.
- Lookup ownership, ACLs, automatic lookups, and definitions:
  `splunk-knowledge-objects-setup`.
- KV Store health, backup, restore, and collection governance:
  `splunk-kvstore-admin-setup`.
""",
    "install_commands": """#!/usr/bin/env bash
set -euo pipefail

# Review before running.
bash skills/splunk-app-install/scripts/install_app.sh --source splunkbase --app-id 1724
bash skills/splunk-knowledge-objects-setup/scripts/setup.sh --help
bash skills/splunk-kvstore-admin-setup/scripts/setup.sh --help
""",
    "validation_searches": """# Lookup File Editing validation searches

| rest /services/apps/local/lookup_editor
| table title version disabled visible eai:acl.app

| rest /servicesNS/-/-/data/lookup-table-files splunk_server=local
| search eai:acl.app="{{lookup_owner_app}}" OR "{{lookup_owner_app}}"="search"
| stats count by eai:acl.app eai:acl.owner eai:acl.sharing

| rest /servicesNS/-/-/data/transforms/lookups splunk_server=local
| search eai:acl.app="{{lookup_owner_app}}" OR "{{lookup_owner_app}}"="search"
| table title filename collection eai:acl.app eai:acl.owner eai:acl.sharing

| rest /services/server/info
| table server_roles serverName
""",
    "readiness_evidence": {
        "name": "Splunk App for Lookup File Editing",
        "app_name": "lookup_editor",
        "product": "Splunk App for Lookup File Editing",
        "knowledge_objects": {"lookup_owner_app": "{{lookup_owner_app}}", "lookup_scope": "{{lookup_scope}}"},
        "kvstore": {"inventory_required": True},
        "handoffs": ["splunk-lookup-file-editing-setup", "splunk-knowledge-objects-setup", "splunk-kvstore-admin-setup"],
    },
    "additional_files": [
        {
            "path": "shc-allow-rest-replay-runbook.md",
            "content": """# SHC allowRestReplay Backup Replication Runbook

SHC mode: `{{shc_mode}}`

1. Back up `lookup_editor` local configuration and target lookup files.
2. Review whether the app requires `allowRestReplay` for search head cluster
   replication of lookup edits.
3. Apply any reviewed app-local setting through deployer or supported Cloud
   app-management workflow.
4. Verify lookup changes replicate and can be restored from backup.

This renderer does not set `allowRestReplay` or edit lookup contents.
""",
        }
    ],
}


if __name__ == "__main__":
    raise SystemExit(main(CONFIG))

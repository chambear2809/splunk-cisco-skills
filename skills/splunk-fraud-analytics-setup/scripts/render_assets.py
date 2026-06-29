#!/usr/bin/env python3
"""Render Splunk Fraud Analytics setup assets."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "skills" / "shared" / "lib"))

from render_first_app import main  # noqa: E402


CONFIG = {
    "skill_name": "splunk-fraud-analytics-setup",
    "title": "Splunk Fraud Analytics Setup",
    "description": "Render Fraud Analytics readiness assets.",
    "default_output_dir": "splunk-fraud-analytics-rendered",
    "profile_dir": "splunk-fraud-analytics",
    "primary_app_name": "Splunk_Fraud_Analytics",
    "primary_splunkbase_id": "N/A",
    "handoff_skills": [
        "splunk-app-install",
        "splunk-enterprise-security-config",
        "splunk-lookup-file-editing-setup",
        "splunk-cim-data-model-setup",
    ],
    "arguments": [
        {"flag": "--platform", "default": "auto", "choices": ["cloud", "enterprise", "auto"], "help": "Target Splunk platform."},
        {"flag": "--es-app", "default": "SplunkEnterpriseSecuritySuite", "help": "Enterprise Security app name."},
        {"flag": "--fraud-use-case", "default": "account-takeover", "help": "Primary fraud use case."},
        {"flag": "--risk-index", "default": "risk", "help": "Risk index expected by RBA workflows."},
        {"flag": "--transaction-index", "default": "fraud", "help": "Primary transaction/event index."},
        {"flag": "--lookup-owner-app", "default": "Splunk_Fraud_Analytics", "help": "App that owns fraud lookups."},
    ],
    "metadata": {
        "app_name": "Splunk_Fraud_Analytics",
        "platform": "{{platform}}",
        "es_app": "{{es_app}}",
        "fraud_use_case": "{{fraud_use_case}}",
        "risk_index": "{{risk_index}}",
        "transaction_index": "{{transaction_index}}",
        "lookup_owner_app": "{{lookup_owner_app}}",
        "dependencies": ["SplunkEnterpriseSecuritySuite", "lookup_editor"],
    },
    "plan_md": """# Splunk Fraud Analytics Setup Plan

App: `Splunk_Fraud_Analytics`
Platform: `{{platform}}`
Enterprise Security app: `{{es_app}}`
Primary use case: `{{fraud_use_case}}`
Risk index: `{{risk_index}}`
Transaction index: `{{transaction_index}}`

## Readiness Gates

- ES is installed and data models are accelerated for the selected use case.
- Lookup File Editing is installed and delegated lookup owners are identified.
- Fraud lookup tables, account/user identifiers, transaction identifiers, and
  risk modifier fields are populated.
- Correlation searches are reviewed before enablement.
""",
    "handoffs_md": """# Fraud Analytics Handoffs

- Package install is a local package or Splunkbase handoff through
  `splunk-app-install`.
- Lookup maintenance is delegated to `splunk-lookup-file-editing-setup`.
- ES correlation searches, RBA, notable/risk action readiness, and risk index
  checks are delegated to `splunk-enterprise-security-config`.
- Data-model constraints and acceleration are delegated to
  `splunk-cim-data-model-setup`.
""",
    "install_commands": """#!/usr/bin/env bash
set -euo pipefail

# Review before running. Fraud Analytics package location is operator supplied.
bash skills/splunk-app-install/scripts/install_app.sh --help
bash skills/splunk-lookup-file-editing-setup/scripts/setup.sh --render --platform {{platform}}
bash skills/splunk-enterprise-security-config/scripts/setup.sh --spec skills/splunk-enterprise-security-config/templates/es-config.example.yaml --mode preview
""",
    "validation_searches": """# Fraud Analytics validation searches

| rest /services/apps/local/Splunk_Fraud_Analytics
| table title version disabled visible eai:acl.app

index={{risk_index}}
| stats count min(_time) as first_seen max(_time) as last_seen by sourcetype risk_object risk_object_type
| convert ctime(first_seen) ctime(last_seen)

index={{transaction_index}}
| stats count dc(user) as users dc(account) as accounts dc(src) as srcs by sourcetype

| rest /servicesNS/-/-/saved/searches splunk_server=local
| search eai:acl.app=Splunk_Fraud_Analytics OR title="*fraud*"
| table title disabled cron_schedule action.correlationsearch.enabled
""",
    "readiness_evidence": {
        "name": "Splunk Fraud Analytics",
        "app_name": "Splunk_Fraud_Analytics",
        "product": "Splunk App for Fraud Analytics",
        "expected_indexes": ["{{transaction_index}}", "{{risk_index}}"],
        "expected_macros": ["fraud_indexes", "risk_index"],
        "products": {"es": {"installed": True}},
        # "Risk" is an ES-shipped data model (not a Splunk_SA_CIM model); group it under "es".
        "es": {"risk_index": "{{risk_index}}", "correlation_search_activation_policy": "review-only", "expected_data_models": ["Risk"]},
        # CIM lists only genuine Splunk_SA_CIM data models.
        "cim": {"expected_models": ["Authentication", "Change"]},
        # "Transaction" is defined by the Splunk_Fraud_Analytics app itself, not CIM.
        "app": {"name": "Splunk_Fraud_Analytics", "expected_data_models": ["Transaction"]},
        "handoffs": ["splunk-fraud-analytics-setup", "splunk-enterprise-security-config", "splunk-lookup-file-editing-setup"],
    },
}


if __name__ == "__main__":
    raise SystemExit(main(CONFIG))

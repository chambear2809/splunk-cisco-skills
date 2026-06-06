#!/usr/bin/env python3
"""Render reviewable Splunk Add-on for Google Workspace assets.

Offline and render-first: emits package-backed modular input stanzas, account
and settings runbooks, validation SPL, and a setup plan for
Splunk_TA_Google_Workspace.
"""

from __future__ import annotations

import argparse
import json
import stat
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = REPO_ROOT / "splunk-google-workspace-ta-rendered"

APP_NAME = "Splunk_TA_Google_Workspace"
SPLUNKBASE_ID = "5556"
LATEST_VERIFIED_VERSION = "4.0.0"

REPORT_APPLICATIONS = [
    "admin",
    "login",
    "token",
    "drive",
    "calendar",
    "groups_enterprise",
    "chrome",
    "mobile",
    "chat",
    "gcp",
    "saml",
    "context_aware_access",
    "data_studio",
    "gemini_in_workspace_apps",
    "access_transparency",
]

INPUT_FAMILIES = {
    "activity_report",
    "gws_gmail_logs",
    "gws_gmail_logs_migrated",
    "gws_user_identity",
    "gws_alert_center",
    "gws_usage_report",
}

SOURCETYPES = [
    "gws:reports:admin",
    "gws:reports:login",
    "gws:reports:token",
    "gws:reports:drive",
    "gws:reports:calendar",
    "gws:reports:groups_enterprise",
    "gws:reports:chrome",
    "gws:reports:mobile",
    "gws:reports:chat",
    "gws:reports:gcp",
    "gws:reports:saml",
    "gws:reports:context_aware_access",
    "gws:reports:data_studio",
    "gws:reports:gemini_in_workspace_apps",
    "gws:reports:access_transparency",
    "gws:gmail",
    "gws:alerts",
    "gws:users:identity",
    "gws:usage_reports:user",
    "gws:usage_reports:customer",
    "gws:usage_reports:entity",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Splunk_TA_Google_Workspace assets.")
    parser.add_argument("--phase", choices=("render", "list"), default="render")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--index", default="google_workspace", help="Target event index.")
    parser.add_argument("--account-name", default="gws_prod", help="Google Workspace account stanza name.")
    parser.add_argument(
        "--inputs",
        default="activity_report,gws_gmail_logs,gws_gmail_logs_migrated,gws_user_identity,gws_alert_center,gws_usage_report",
        help="Comma-separated input families to render.",
    )
    parser.add_argument(
        "--applications",
        default="admin,login,token,drive,calendar,groups_enterprise",
        help="Comma-separated activity_report applications to render.",
    )
    parser.add_argument("--gcp-project", default="my-gcp-project", help="GCP project for Gmail BigQuery logs.")
    parser.add_argument("--customer-id", default="C01234567", help="Google Workspace customer ID for identity input.")
    parser.add_argument("--dataset-name", default="gmail_logs_dataset", help="BigQuery Gmail logs dataset.")
    parser.add_argument("--dataset-location", default="US", help="BigQuery dataset location.")
    parser.add_argument("--alert-source", default="Google Operations", help="Alert Center source filter.")
    parser.add_argument("--usage-endpoint", default="user", help="Usage report endpoint: user,customer,entity.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def parse_csv(raw: str, allowed: set[str] | None = None, label: str = "value") -> list[str]:
    values = [item.strip() for item in raw.split(",") if item.strip()]
    if allowed is not None:
        unknown = [item for item in values if item not in allowed]
        if unknown:
            raise SystemExit(f"ERROR: unknown {label}(s): {', '.join(unknown)}. Choose from {', '.join(sorted(allowed))}.")
    return values


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def render_inputs(args: argparse.Namespace, families: list[str], applications: list[str]) -> str:
    lines = [
        f"# Starter local/inputs.conf overlay for {APP_NAME} (Splunkbase {SPLUNKBASE_ID}).",
        f"# Copy reviewed stanzas into $SPLUNK_HOME/etc/apps/{APP_NAME}/local/inputs.conf.",
        f"# Reference account '{args.account_name}' configured in the add-on Configuration tab.",
        "",
    ]
    if "activity_report" in families:
        for app in applications:
            lines += [
                f"[activity_report://gws_activity_{app}]",
                "disabled = 0",
                f"account = {args.account_name}",
                f"application = {app}",
                "interval = 300",
                "lookbackOffset = 1800",
                f"index = {args.index}",
                "",
            ]
    if "gws_gmail_logs" in families:
        lines += [
            "[gws_gmail_logs://gws_gmail_logs]",
            "disabled = 0",
            f"account = {args.account_name}",
            f"gcp_project_id = {args.gcp_project}",
            f"dataset_name = {args.dataset_name}",
            f"dataset_location = {args.dataset_location}",
            "interval = 300",
            f"index = {args.index}",
            "",
        ]
    if "gws_gmail_logs_migrated" in families:
        lines += [
            "[gws_gmail_logs_migrated://gws_gmail_logs_migrated]",
            "disabled = 0",
            f"account = {args.account_name}",
            f"gcp_project_id = {args.gcp_project}",
            f"dataset_name = {args.dataset_name}",
            f"dataset_location = {args.dataset_location}",
            "table_name = activity",
            "interval = 300",
            f"index = {args.index}",
            "",
        ]
    if "gws_user_identity" in families:
        lines += [
            "[gws_user_identity://gws_user_identity]",
            "disabled = 0",
            f"account = {args.account_name}",
            f"gws_customer_id = {args.customer_id}",
            "gws_view_type = domain_public",
            "interval = 21600",
            f"index = {args.index}",
            "",
        ]
    if "gws_alert_center" in families:
        lines += [
            "[gws_alert_center://gws_alert_center]",
            "disabled = 0",
            f"account = {args.account_name}",
            f"alert_source = {args.alert_source}",
            "interval = 300",
            f"index = {args.index}",
            "",
        ]
    if "gws_usage_report" in families:
        lines += [
            f"[gws_usage_report://gws_usage_{args.usage_endpoint}]",
            "disabled = 0",
            f"account = {args.account_name}",
            f"endpoint = {args.usage_endpoint}",
            "start_date = 2026-01-01",
            "interval = 34 1 * * *",
            f"index = {args.index}",
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"


def render_settings(args: argparse.Namespace) -> str:
    return f"""# Optional local/splunk_ta_google_workspace_settings.conf overlay for {APP_NAME}.
# Configure only after review. No account secrets belong in this file.

[proxy]
proxy_enabled = 0

[logging]
loglevel = INFO

[advanced_settings]
activity_report_interval_size = 4

# Data inputs reference account = {args.account_name}; create it through the
# add-on UI or REST handler splunk_ta_google_workspace_account.
"""


def render_account_setup(args: argparse.Namespace) -> str:
    return f"""# {APP_NAME} Account Setup Runbook

The Google Workspace add-on authenticates with a delegated Google service
account and certificate/private key.

1. Create a Google Cloud service account for Splunk Workspace collection.
2. Enable the Admin SDK API, Alert Center API, and any BigQuery APIs required
   for Gmail logs.
3. Configure domain-wide delegation for the service account and grant only the
   scopes required for the selected inputs.
4. Write the certificate/private-key payload to a protected local file:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/gws_certificate
```

5. In the add-on Configuration tab, create account `{args.account_name}` with:

| Field | Value |
| --- | --- |
| `username` | delegated admin user, for example `splunk-collector@example.com` |
| `certificate` | private key/certificate value from the protected file |

REST handler: `/servicesNS/nobody/{APP_NAME}/splunk_ta_google_workspace_account`.
Secrets are stored encrypted in `storage/passwords`; this skill never places
certificate material in argv or rendered conf.

For Gmail BigQuery logs, ensure the same service account can read project
`{args.gcp_project}` dataset `{args.dataset_name}` in `{args.dataset_location}`.
"""


def render_install_commands(args: argparse.Namespace) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail

# Review before running. No secrets are embedded in this file.
bash skills/splunk-app-install/scripts/install_app.sh --source splunkbase --app-id {SPLUNKBASE_ID}
bash skills/splunk-google-workspace-ta-setup/scripts/setup.sh --create-index --index {args.index}

# Configure account {args.account_name} using account-setup.md, then enable the rendered inputs.
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh --phase collect --source-pack google_workspace
"""


def render_validation_spl(args: argparse.Namespace) -> str:
    sourcetypes = ",".join(f'"{s}"' for s in SOURCETYPES)
    return f"""# {APP_NAME} validation searches

index={args.index} sourcetype IN ({sourcetypes})
| stats count min(_time) as first_seen max(_time) as last_seen by sourcetype
| convert ctime(first_seen) ctime(last_seen)

index={args.index} sourcetype=gws:reports:admin OR sourcetype=gws:reports:login
| stats count dc(actor.email) as users dc(ipAddress) as srcs values(events.name) as event_names by app events.type

index={args.index} sourcetype=gws:gmail
| stats count by event_type actor.email

index=_internal source=*splunkd.log* ({APP_NAME} OR gws_runner OR splunk_ta_google_workspace)
| stats count values(log_level) as levels by sourcetype
"""


def render_plan_md(args: argparse.Namespace, families: list[str], applications: list[str]) -> str:
    rows = [
        "| `activity_report` | `gws:reports:<application>` | Authentication, Change, Email |",
        "| `gws_gmail_logs` | `gws:gmail` | Email |",
        "| `gws_gmail_logs_migrated` | `gws:gmail` | Email |",
        "| `gws_user_identity` | `gws:users:identity` | Identity / inventory |",
        "| `gws_alert_center` | `gws:alerts` | Alerts / Change |",
        "| `gws_usage_report` | `gws:usage_reports:<endpoint>` | Inventory / usage |",
    ]
    return f"""# {APP_NAME} Setup Plan

Add-on: `{APP_NAME}` (Splunkbase `{SPLUNKBASE_ID}`, verified `{LATEST_VERIFIED_VERSION}`)
Event index: `{args.index}`
Account: `{args.account_name}`
Rendered input families: `{", ".join(families)}`
Rendered activity applications: `{", ".join(applications)}`

## Role Placement

| Role | Support |
| --- | --- |
| `search-tier` | required for setup and knowledge objects |
| `heavy-forwarder` | supported for collection |
| `indexer` | none |
| `universal-forwarder` | none |
| `external-collector` | none |

Run each input family on exactly one collection node to avoid duplicate API
collection.

## Package-Backed Inputs

| Input family | Source type | Readiness use |
| --- | --- | --- |
{chr(10).join(rows)}

## Guardrails

- Configure the service-account certificate only through the add-on account;
  never in `inputs.conf`, shell history, or rendered files.
- Gmail logs require BigQuery dataset access in project `{args.gcp_project}`.
- Dashboard behavior is package-backed only: use shipped knowledge objects and
  any documented companion app content; this skill does not create dashboards.

## Sources

- https://splunkbase.splunk.com/app/{SPLUNKBASE_ID}
- https://splunk.github.io/splunk-add-on-for-google-workspace/
"""


def render_assets(args: argparse.Namespace, families: list[str], applications: list[str]) -> dict[str, Any]:
    output_root = Path(args.output_dir).expanduser().resolve()
    profile_dir = output_root / "splunk-google-workspace-ta"
    files = [
        "account-setup.md",
        "inputs.local.conf.template",
        "install-commands.sh",
        "metadata.json",
        "profile-plan.md",
        "settings.local.conf.template",
        "validation-searches.spl",
    ]
    if args.dry_run:
        return {"ok": True, "dry_run": True, "output_dir": str(profile_dir), "files": files}
    metadata = {
        "app_name": APP_NAME,
        "splunkbase_id": SPLUNKBASE_ID,
        "latest_verified_version": LATEST_VERIFIED_VERSION,
        "index": args.index,
        "account_name": args.account_name,
        "input_families": families,
        "activity_report_applications": applications,
        "source_package": f"splunk-ta/_unpacked/{APP_NAME}-{LATEST_VERIFIED_VERSION}/{APP_NAME}",
    }
    write_file(profile_dir / "metadata.json", json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    write_file(profile_dir / "profile-plan.md", render_plan_md(args, families, applications))
    write_file(profile_dir / "inputs.local.conf.template", render_inputs(args, families, applications))
    write_file(profile_dir / "settings.local.conf.template", render_settings(args))
    write_file(profile_dir / "account-setup.md", render_account_setup(args))
    write_file(profile_dir / "install-commands.sh", render_install_commands(args), executable=True)
    write_file(profile_dir / "validation-searches.spl", render_validation_spl(args))
    return {
        "ok": True,
        "dry_run": False,
        "output_dir": str(profile_dir),
        "files": sorted(path.name for path in profile_dir.iterdir() if path.is_file()),
    }


def emit(payload: dict[str, Any], json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    if "files" in payload:
        print(f"App: {APP_NAME} (Splunkbase {SPLUNKBASE_ID})")
        print(f"Output: {payload['output_dir']}")
        print("Files: " + ", ".join(payload["files"]))
        return
    print(json.dumps(payload, indent=2, sort_keys=True))


def main() -> int:
    args = parse_args()
    families = parse_csv(args.inputs, INPUT_FAMILIES, "input family")
    applications = parse_csv(args.applications, set(REPORT_APPLICATIONS), "application")
    if args.phase == "list":
        emit(
            {
                "ok": True,
                "app_name": APP_NAME,
                "splunkbase_id": SPLUNKBASE_ID,
                "input_families": sorted(INPUT_FAMILIES),
                "activity_report_applications": REPORT_APPLICATIONS,
                "sourcetypes": SOURCETYPES,
            },
            args.json,
        )
        return 0
    emit(render_assets(args, families, applications), args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

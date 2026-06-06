#!/usr/bin/env python3
"""Render reviewable Splunk Add-on for Google Cloud Platform (Splunk_TA_google-cloudplatform) assets.

Offline and render-first: centers on the high-value Cloud Logging -> Pub/Sub
ingestion path (the GCP SIEM feed), emits a service-account credential runbook,
a placement/CIM plan, and validation SPL grounded in the real package model.
"""

from __future__ import annotations

import argparse
import json
import stat
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = REPO_ROOT / "splunk-gcp-ta-rendered"

APP_NAME = "Splunk_TA_google-cloudplatform"
SPLUNKBASE_ID = "3088"
LATEST_VERIFIED_VERSION = "5.0.2"

# Audit log source types the add-on auto-assigns to Pub/Sub messages via props.
AUDIT_SOURCETYPES = [
    "google:gcp:pubsub:audit:admin_activity",
    "google:gcp:pubsub:audit:data_access",
    "google:gcp:pubsub:audit:system_event",
    "google:gcp:pubsub:audit:policy_denied",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Splunk_TA_google-cloudplatform assets.")
    parser.add_argument("--phase", choices=("render", "list"), default="render")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--index", default="gcp", help="Target event index for GCP logs.")
    parser.add_argument("--credential-name", default="gcp_prod", help="google_credentials stanza name.")
    parser.add_argument("--project", default="my-gcp-project", help="GCP project ID.")
    parser.add_argument("--subscription", default="splunk-export-sub", help="Pub/Sub subscription name.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def render_inputs(args: argparse.Namespace) -> str:
    return f"""# Starter local/inputs.conf overlay for {APP_NAME} (Splunkbase {SPLUNKBASE_ID}).
# Copy reviewed stanzas into $SPLUNK_HOME/etc/apps/{APP_NAME}/local/inputs.conf.
# Reference the credential '{args.credential_name}' configured in the add-on
# (see account-setup.md). No secrets belong in this file.

# Cloud Logging -> Pub/Sub log ingestion (the GCP SIEM feed).
# Export logs to a Pub/Sub topic with a log sink, then pull the subscription.
[google_cloud_pubsub://{args.project}_logs]
disabled = 0
google_credentials_name = {args.credential_name}
google_project = {args.project}
google_subscriptions = {args.subscription}
index = {args.index}
sourcetype = google:gcp:pubsub:message
"""


def render_account_setup(args: argparse.Namespace) -> str:
    return f"""# {APP_NAME} Credential Setup Runbook

The GCP add-on authenticates with a Google service account key (JSON) or an
Application Default Credential (ADC) on the collector host.

## 1. Service account + key

1. In the GCP console, create a service account for Splunk ingestion.
2. Grant least-privilege roles: `roles/pubsub.subscriber` (and
   `roles/pubsub.viewer`) on the subscription; `roles/monitoring.viewer` only
   if you also collect Cloud Monitoring metrics.
3. Create a JSON key and download it. Write it to a local protected file (never
   paste it in chat):

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/gcp_sa_key.json
```

4. In the add-on **Configuration > Google Credentials** tab, add credential
   `{args.credential_name}` and upload/paste the JSON key. The key is stored
   encrypted in `storage/passwords`.

   - Prefer ADC (no stored key) when the collector runs on GCE/GKE with an
     attached service account: set `adc_account = 1` on the credential.

## 2. Export logs to Pub/Sub

1. Create a Pub/Sub topic and a subscription (`{args.subscription}`).
2. Create a Cloud Logging sink to that topic (e.g. all `cloudaudit.googleapis.com`
   logs for audit coverage).
3. Grant the service account `roles/pubsub.subscriber` on the subscription.

The credential REST endpoint is
`/servicesNS/nobody/{APP_NAME}/google_credentials`. This skill renders inputs and
indexes only; it never transmits the service-account key.

## Audit log source types

Pub/Sub messages carrying Cloud Audit Logs are auto-classified by the add-on
into: {", ".join("`" + s + "`" for s in AUDIT_SOURCETYPES)}.
"""


def render_install_commands(args: argparse.Namespace) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail

# Review before running. No secrets are embedded in this file.
# {APP_NAME} (Splunkbase {SPLUNKBASE_ID}) install + index.

# 1. Install the add-on on the search tier or a heavy forwarder.
bash skills/splunk-app-install/scripts/install_app.sh --source splunkbase --app-id {SPLUNKBASE_ID}

# 2. Create the GCP event index.
bash skills/splunk-gcp-ta-setup/scripts/setup.sh --create-index --index {args.index}

# 3. Configure the credential and Pub/Sub export (see account-setup.md), then enable inputs.
"""


def render_validation_spl(args: argparse.Namespace) -> str:
    audit = ",".join(f'"{s}"' for s in AUDIT_SOURCETYPES)
    return f"""# {APP_NAME} validation searches

index={args.index} sourcetype IN ("google:gcp:pubsub:message",{audit})
| stats count min(_time) as first_seen max(_time) as last_seen by sourcetype
| convert ctime(first_seen) ctime(last_seen)

index={args.index} sourcetype=google:gcp:pubsub:audit:admin_activity
| stats count by protoPayload.methodName

index=_internal source=*splunkd.log* ({APP_NAME} OR google_cloud_pubsub OR "google:gcp")
| stats count values(log_level) as levels by sourcetype
"""


def render_plan_md(args: argparse.Namespace) -> str:
    audit_rows = "\n".join(f"| `{s}` | Change / Authentication |" for s in AUDIT_SOURCETYPES)
    return f"""# {APP_NAME} Setup Plan

Add-on: `{APP_NAME}` (Splunkbase `{SPLUNKBASE_ID}`, verified `{LATEST_VERIFIED_VERSION}`)
Event index: `{args.index}`
Credential: `{args.credential_name}`
Project: `{args.project}` | Subscription: `{args.subscription}`

## Role Placement

| Role | Support |
| --- | --- |
| `search-tier` | supported (can run inputs directly) |
| `heavy-forwarder` | supported (preferred dedicated collector) |
| `indexer` | none |
| `universal-forwarder` | none |
| `external-collector` | none |

## Primary Feed: Cloud Logging -> Pub/Sub

| Input | Source type | CIM |
| --- | --- | --- |
| `google_cloud_pubsub` | `google:gcp:pubsub:message` | depends on log type |
{audit_rows}

## Other Available Inputs (configure via the add-on UI)

`google_cloud_monitor` (Cloud Monitoring metrics), `google_cloud_billing`,
`google_cloud_pubsub_based_bucket`, `google_cloud_bucket_metadata`,
`google_cloud_resource_metadata*`, `google_cloud_pubsub_lite`. These use the
add-on's UCC configuration UI; this skill renders the fully-specified Pub/Sub
log path and documents the rest.

## Account Model

Configure a service-account JSON key (or ADC) in the add-on
**Configuration > Google Credentials** tab. See `account-setup.md`.

## Guardrails

- Run inputs on the search tier OR one heavy forwarder, not both, to avoid
  duplicate Pub/Sub acknowledgement and ingestion.
- Use a dedicated Pub/Sub subscription per input; the add-on acknowledges
  messages it pulls.
- Store the service-account key only via the add-on credential (encrypted), or
  use ADC; never put the key in conf files or argv.
- Grant least-privilege IAM (`roles/pubsub.subscriber`).

## Sources

- https://splunkbase.splunk.com/app/{SPLUNKBASE_ID}
- https://help.splunk.com/en/splunk-cloud-platform/get-data-in/splunk-supported-add-ons/google-cloud-platform
"""


def render_assets(args: argparse.Namespace) -> dict[str, Any]:
    output_root = Path(args.output_dir).expanduser().resolve()
    profile_dir = output_root / "splunk-gcp-ta"
    files = [
        "account-setup.md",
        "inputs.local.conf.template",
        "install-commands.sh",
        "metadata.json",
        "profile-plan.md",
        "validation-searches.spl",
    ]
    if args.dry_run:
        return {"ok": True, "dry_run": True, "output_dir": str(profile_dir), "files": files}

    metadata = {
        "app_name": APP_NAME,
        "splunkbase_id": SPLUNKBASE_ID,
        "latest_verified_version": LATEST_VERIFIED_VERSION,
        "index": args.index,
        "credential_name": args.credential_name,
        "project": args.project,
        "subscription": args.subscription,
    }
    write_file(profile_dir / "metadata.json", json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    write_file(profile_dir / "profile-plan.md", render_plan_md(args))
    write_file(profile_dir / "inputs.local.conf.template", render_inputs(args))
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
    if args.phase == "list":
        emit(
            {
                "ok": True,
                "app_name": APP_NAME,
                "splunkbase_id": SPLUNKBASE_ID,
                "primary_input": "google_cloud_pubsub",
                "audit_sourcetypes": AUDIT_SOURCETYPES,
            },
            args.json,
        )
        return 0
    emit(render_assets(args), args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

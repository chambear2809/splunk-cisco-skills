#!/usr/bin/env python3
"""Render reviewable Splunk Add-on for Okta Identity Cloud (Splunk_TA_okta_identity_cloud) assets.

Offline and render-first: emits inputs.conf stanzas, an account-setup runbook
(API token or OAuth2 client-credentials), a placement/CIM plan, and validation
SPL grounded in the real Splunk_TA_okta_identity_cloud package model.
"""

from __future__ import annotations

import argparse
import json
import stat
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = REPO_ROOT / "splunk-okta-ta-rendered"

APP_NAME = "Splunk_TA_okta_identity_cloud"
SPLUNKBASE_ID = "6553"
LATEST_VERIFIED_VERSION = "5.0.2"

# The single okta_identity_cloud modular input collects one data type per stanza,
# selected by the `metric` field. Each maps to an OktaIM2:<type> source type.
METRICS: dict[str, dict[str, str]] = {
    "log": {"sourcetype": "OktaIM2:log", "cim": "Authentication, Change", "desc": "Okta System Log events (primary security feed)."},
    "user": {"sourcetype": "OktaIM2:user", "cim": "Identity / Inventory", "desc": "Universal Directory users (state, not time-series)."},
    "group": {"sourcetype": "OktaIM2:group", "cim": "Identity / Inventory", "desc": "Universal Directory groups."},
    "app": {"sourcetype": "OktaIM2:app", "cim": "Inventory", "desc": "Universal Directory applications."},
    "groupUser": {"sourcetype": "OktaIM2:groupUser", "cim": "Identity", "desc": "Group-to-user membership."},
    "appUser": {"sourcetype": "OktaIM2:appUser", "cim": "Identity", "desc": "App-to-user assignment."},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Splunk_TA_okta_identity_cloud assets.")
    parser.add_argument("--phase", choices=("render", "list"), default="render")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--index", default="okta", help="Target event index for Okta data.")
    parser.add_argument("--account-name", default="okta_prod", help="global_account stanza name referenced by inputs.")
    parser.add_argument(
        "--metrics",
        default="log,user,group,app",
        help="Comma-separated metrics: log,user,group,app,groupUser,appUser.",
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def selected_metrics(raw: str) -> list[str]:
    metrics = [m.strip() for m in raw.split(",") if m.strip()]
    unknown = [m for m in metrics if m not in METRICS]
    if unknown:
        raise SystemExit(f"ERROR: unknown metric(s): {', '.join(unknown)}. Choose from {', '.join(METRICS)}.")
    return metrics or list(METRICS)


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def render_inputs(args: argparse.Namespace, metrics: list[str]) -> str:
    lines = [
        f"# Starter local/inputs.conf overlay for {APP_NAME} (Splunkbase {SPLUNKBASE_ID}).",
        f"# Copy reviewed stanzas into $SPLUNK_HOME/etc/apps/{APP_NAME}/local/inputs.conf.",
        f"# Reference the configured account '{args.account_name}' (see account-setup.md).",
        "# The add-on assigns the OktaIM2:<metric> source type automatically per metric.",
        "",
    ]
    for metric in metrics:
        lines += [
            f"[okta_identity_cloud://okta_{metric}]",
            "disabled = 0",
            f"global_account = {args.account_name}",
            f"metric = {metric}",
            "interval = 300" if metric == "log" else "interval = 86400",
            f"index = {args.index}",
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"


def render_account_setup(args: argparse.Namespace) -> str:
    return f"""# {APP_NAME} Account Setup Runbook

The Okta add-on authenticates to the Okta System Log / Universal Directory APIs.
Configure an account named `{args.account_name}` in the add-on Configuration tab.
Two supported `auth_type` values:

## Option A - OAuth 2.0 client credentials (recommended)

1. In the Okta Admin console, create an API Services (machine-to-machine) app
   with the client-credentials grant and grant `okta.logs.read` (and
   `okta.users.read`, `okta.groups.read`, `okta.apps.read` for Universal
   Directory metrics).
2. Write the client secret to a local protected file (never paste it in chat):

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/okta_client_secret
```

3. In the add-on Configuration tab, add an account with `domain`
   (`yourorg.okta.com`), `auth_type = OAuth2`, `client_id_oauth_credentials`,
   and the client secret value.

## Option B - API token (Basic)

1. Create an Okta API token (Security > API > Tokens).
2. Write the token to a local file:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/okta_api_token
```

3. In the add-on Configuration tab, add an account with `domain`,
   `auth_type = Basic`, and the token value (stored as `password`).

The account REST endpoint is
`/servicesNS/nobody/{APP_NAME}/Splunk_TA_okta_identity_cloud_account`; the OAuth
endpoint is `Splunk_TA_okta_identity_cloud_oauth`. Secrets are stored encrypted
in `storage/passwords`; this skill never transmits them.
"""


def render_install_commands(args: argparse.Namespace) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail

# Review before running. No secrets are embedded in this file.
# {APP_NAME} (Splunkbase {SPLUNKBASE_ID}) install + index.

# 1. Install the add-on on the search tier (and any heavy-forwarder collector).
bash skills/splunk-app-install/scripts/install_app.sh --source splunkbase --app-id {SPLUNKBASE_ID}

# 2. Create the Okta event index.
bash skills/splunk-okta-ta-setup/scripts/setup.sh --create-index --index {args.index}

# 3. Configure the account (see account-setup.md), then enable the rendered inputs.

# 4. Score post-ingest CIM/data readiness once data flows.
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh --phase collect --source-pack okta_identity_cloud
"""


def render_validation_spl(args: argparse.Namespace, metrics: list[str]) -> str:
    sourcetypes = ",".join(f'"{METRICS[m]["sourcetype"]}"' for m in metrics)
    return f"""# {APP_NAME} validation searches

index={args.index} sourcetype IN ({sourcetypes})
| stats count min(_time) as first_seen max(_time) as last_seen by sourcetype
| convert ctime(first_seen) ctime(last_seen)

index={args.index} sourcetype=OktaIM2:log
| stats count by eventType outcome.result

| datamodel Authentication Authentication search
| search sourcetype=OktaIM2:log
| stats count by action

index=_internal source=*splunkd.log* ({APP_NAME} OR okta_identity_cloud)
| stats count values(log_level) as levels by sourcetype
"""


def render_plan_md(args: argparse.Namespace, metrics: list[str]) -> str:
    rows = "\n".join(
        f"| `metric = {m}` | `{METRICS[m]['sourcetype']}` | {METRICS[m]['cim']} |" for m in metrics
    )
    return f"""# {APP_NAME} Setup Plan

Add-on: `{APP_NAME}` (Splunkbase `{SPLUNKBASE_ID}`, verified `{LATEST_VERIFIED_VERSION}`)
Event index: `{args.index}`
Account: `{args.account_name}`

## Role Placement

| Role | Support |
| --- | --- |
| `search-tier` | required (setup, auth, knowledge objects, CIM) |
| `heavy-forwarder` | supported (preferred data-collection node) |
| `indexer` | none |
| `universal-forwarder` | none |
| `external-collector` | none |

Run inputs on the search tier OR a heavy forwarder, not both, to avoid
duplicate collection.

## Inputs, Metrics, Source Types, And CIM

Single modular input `okta_identity_cloud`; one stanza per `metric`.

| Input field | Source type | CIM data models |
| --- | --- | --- |
{rows}

## Account Model

Configure a `global_account` (OAuth 2.0 client credentials or API token) in the
add-on Configuration tab before enabling inputs. See `account-setup.md`.

## Guardrails

- Run inputs on a single node (search tier or one heavy forwarder); duplicate
  inputs cause duplicate System Log ingestion.
- The System Log (`metric = log`, `OktaIM2:log`) is the primary security feed;
  Universal Directory metrics are state snapshots, not time-series.
- Store the API token / client secret only via the add-on account (encrypted);
  never in conf files or argv.
- Prefer OAuth 2.0 client credentials over a long-lived API token.

## Sources

- https://splunkbase.splunk.com/app/{SPLUNKBASE_ID}
- https://splunk.github.io/splunk-add-on-for-okta-identity-cloud/
"""


def render_assets(args: argparse.Namespace, metrics: list[str]) -> dict[str, Any]:
    output_root = Path(args.output_dir).expanduser().resolve()
    profile_dir = output_root / "splunk-okta-ta"
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
        "account_name": args.account_name,
        "metrics": metrics,
    }
    write_file(profile_dir / "metadata.json", json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    write_file(profile_dir / "profile-plan.md", render_plan_md(args, metrics))
    write_file(profile_dir / "inputs.local.conf.template", render_inputs(args, metrics))
    write_file(profile_dir / "account-setup.md", render_account_setup(args))
    write_file(profile_dir / "install-commands.sh", render_install_commands(args), executable=True)
    write_file(profile_dir / "validation-searches.spl", render_validation_spl(args, metrics))
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
    metrics = selected_metrics(args.metrics)
    if args.phase == "list":
        emit({"ok": True, "app_name": APP_NAME, "splunkbase_id": SPLUNKBASE_ID, "metrics": list(METRICS)}, args.json)
        return 0
    emit(render_assets(args, metrics), args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

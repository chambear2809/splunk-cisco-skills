#!/usr/bin/env python3
"""Render reviewable Splunk Add-on for AWS (Splunk_TA_aws) ingestion assets.

Offline and render-first: emits inputs.conf stanzas, an account-setup runbook,
a placement/CIM plan, and validation SPL grounded in the real Splunk_TA_aws
package model. Complements splunk-cloud-data-manager-setup (the automated
CloudFormation onboarding path) with a manual TA configuration path.
"""

from __future__ import annotations

import argparse
import json
import stat
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = REPO_ROOT / "splunk-aws-ta-rendered"

APP_NAME = "Splunk_TA_aws"
SPLUNKBASE_ID = "1876"
LATEST_VERIFIED_VERSION = "8.1.2"

# Feeds the user most commonly onboards. Each maps to a real modular input and
# the source type the add-on assigns. GuardDuty findings are exported to S3 and
# pulled through the SQS-based S3 input with the CustomLogs decoder.
FEEDS: dict[str, dict[str, str]] = {
    "cloudtrail": {
        "input": "aws_sqs_based_s3",
        "decoder": "CloudTrail",
        "sourcetype": "aws:cloudtrail",
        "cim": "Change, Authentication",
        "desc": "CloudTrail logs delivered to S3 with SQS/SNS notifications.",
    },
    "config": {
        "input": "aws_config",
        "decoder": "",
        "sourcetype": "aws:config",
        "cim": "Change",
        "desc": "AWS Config configuration snapshots and change notifications via SQS.",
    },
    "guardduty": {
        "input": "aws_sqs_based_s3",
        "decoder": "CustomLogs",
        "sourcetype": "aws:cloudwatch:guardduty",
        "cim": "Alerts, Intrusion Detection",
        "desc": "GuardDuty findings exported to S3 (EventBridge -> S3) and pulled via SQS.",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Splunk_TA_aws assets.")
    parser.add_argument("--phase", choices=("render", "list"), default="render")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--index", default="aws", help="Target event index for AWS data.")
    parser.add_argument("--account-name", default="aws_prod", help="Account stanza name to reference in inputs.")
    parser.add_argument(
        "--feeds",
        default="cloudtrail,config,guardduty",
        help="Comma-separated feeds to render: cloudtrail,config,guardduty.",
    )
    parser.add_argument("--sqs-region", default="us-east-1", help="AWS region of the notification SQS queue.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def selected_feeds(raw: str) -> list[str]:
    feeds = [item.strip().lower() for item in raw.split(",") if item.strip()]
    unknown = [feed for feed in feeds if feed not in FEEDS]
    if unknown:
        raise SystemExit(f"ERROR: unknown feed(s): {', '.join(unknown)}. Choose from {', '.join(FEEDS)}.")
    return feeds or list(FEEDS)


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def render_inputs(args: argparse.Namespace, feeds: list[str]) -> str:
    lines = [
        f"# Starter local/inputs.conf overlay for {APP_NAME} (Splunkbase {SPLUNKBASE_ID}).",
        f"# Copy reviewed stanzas into $SPLUNK_HOME/etc/apps/{APP_NAME}/local/inputs.conf",
        "# on the search head or heavy forwarder that runs the AWS data inputs.",
        f"# Reference the configured account stanza '{args.account_name}' created in the",
        "# add-on Configuration tab (see account-setup.md). No secrets belong in this file.",
        "",
    ]
    for feed in feeds:
        meta = FEEDS[feed]
        stanza = f"{meta['input']}://{feed}"
        lines += [f"[{stanza}]", "disabled = 0", f"aws_account = {args.account_name}"]
        if meta["input"] == "aws_sqs_based_s3":
            lines += [
                "# aws_iam_role =            # optional: assume-role name for cross-account access",
                "using_dlq = 1",
                f"sqs_queue_url = https://sqs.{args.sqs_region}.amazonaws.com/__ACCOUNT_ID__/__QUEUE_NAME__",
                f"sqs_queue_region = {args.sqs_region}",
                "sqs_batch_size = 10",
                f"s3_file_decoder = {meta['decoder']}",
            ]
        elif meta["input"] == "aws_config":
            lines += [
                f"aws_region = {args.sqs_region}",
                "sqs_queue = __CONFIG_NOTIFICATION_QUEUE__",
            ]
        lines += [f"sourcetype = {meta['sourcetype']}", f"index = {args.index}", ""]
    return "\n".join(lines).rstrip() + "\n"


def render_account_setup(args: argparse.Namespace) -> str:
    return f"""# {APP_NAME} Account Setup Runbook

The AWS add-on authenticates with an **account** object. Create it before
enabling inputs. Two supported modes:

## Option A - IAM role for EC2/EKS (recommended, no stored secret)

Run the add-on on an EC2/EKS host with an attached IAM role. In the add-on
**Configuration > Account** tab, add an account with the IAM-role option
enabled. No secret key is stored in Splunk.

## Option B - Access key + secret key

1. Create a least-privilege IAM user/role with the policy documented for the
   feeds you onboard (CloudTrail/Config/GuardDuty read + SQS receive/delete).
2. Write the secret key to a local protected file (never paste it in chat):

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/aws_secret_key
```

3. In the add-on **Configuration > Account** tab, create account
   `{args.account_name}` with the key ID and the secret key value. The add-on
   stores the secret encrypted (storage/passwords); it is never written to a
   plaintext conf file.

The REST configuration endpoint for accounts is
`/servicesNS/nobody/{APP_NAME}/account` (handler `aws_account_rh.py`); the IAM
role endpoint is `/servicesNS/nobody/{APP_NAME}/splunk_ta_aws_iam_role`.

## Notes

- This skill renders inputs and indexes; it does not transmit AWS secrets. Use
  the add-on Configuration tab or the documented REST endpoint with a secret
  file for the account.
- For fully automated onboarding via CloudFormation, use
  `splunk-cloud-data-manager-setup` instead.
"""


def render_install_commands(args: argparse.Namespace) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail

# Review before running. No secrets are embedded in this file.
# {APP_NAME} (Splunkbase {SPLUNKBASE_ID}) install + index.

# 1. Install the add-on on the search tier or a heavy forwarder.
bash skills/splunk-app-install/scripts/install_app.sh --source splunkbase --app-id {SPLUNKBASE_ID}

# 2. Create the AWS event index.
bash skills/splunk-aws-ta-setup/scripts/setup.sh --create-index --index {args.index}

# 3. Configure the account (see account-setup.md), then enable the rendered inputs.

# 4. Score post-ingest CIM/data readiness once data flows.
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh --phase collect --source-pack aws_cloudtrail
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh --phase collect --source-pack aws_securityhub_guardduty
"""


def render_validation_spl(args: argparse.Namespace, feeds: list[str]) -> str:
    sourcetypes = ",".join(f'"{FEEDS[feed]["sourcetype"]}"' for feed in feeds)
    return f"""# {APP_NAME} validation searches

index={args.index} sourcetype IN ({sourcetypes})
| stats count min(_time) as first_seen max(_time) as last_seen by sourcetype
| convert ctime(first_seen) ctime(last_seen)

index=_internal source=*splunkd.log* ({APP_NAME} OR aws_sqs_based_s3 OR aws_config OR "AWS")
| stats count values(log_level) as levels by sourcetype

| datamodel Change All_Changes search
| search sourcetype=aws:cloudtrail
| stats count by action
"""


def render_plan_md(args: argparse.Namespace, feeds: list[str]) -> str:
    feed_rows = "\n".join(
        f"| {feed} | `{FEEDS[feed]['input']}` | `{FEEDS[feed]['sourcetype']}` | {FEEDS[feed]['cim']} |" for feed in feeds
    )
    return f"""# {APP_NAME} Setup Plan

Add-on: `{APP_NAME}` (Splunkbase `{SPLUNKBASE_ID}`, verified `{LATEST_VERIFIED_VERSION}`)
Event index: `{args.index}`
Account: `{args.account_name}`

## Role Placement

| Role | Support |
| --- | --- |
| `search-tier` | supported (can run the inputs directly) |
| `heavy-forwarder` | supported (preferred dedicated collector) |
| `indexer` | none |
| `universal-forwarder` | none (no modular-input Python runtime) |
| `external-collector` | none |

## Feeds, Inputs, Source Types, And CIM

| Feed | Modular input | Source type | CIM data models |
| --- | --- | --- | --- |
{feed_rows}

## Account Model

Configure an account (IAM role or access key + secret key) in the add-on
Configuration tab before enabling inputs. See `account-setup.md`.

## Guardrails

- Run the add-on on the search tier or a dedicated heavy forwarder. It is not
  Universal-Forwarder safe (it needs the full Splunk Python runtime).
- Prefer SQS-based S3 inputs over legacy generic S3 polling for CloudTrail and
  GuardDuty at scale.
- Store AWS secret keys only via the add-on account (encrypted); never in conf
  files or argv.
- For fully automated CloudFormation onboarding, use
  `splunk-cloud-data-manager-setup`; this skill is the manual TA path.

## Sources

- https://splunkbase.splunk.com/app/{SPLUNKBASE_ID}
- https://help.splunk.com/en/splunk-cloud-platform/get-data-in/splunk-supported-add-ons/amazon-web-services
"""


def render_assets(args: argparse.Namespace, feeds: list[str]) -> dict[str, Any]:
    output_root = Path(args.output_dir).expanduser().resolve()
    profile_dir = output_root / "splunk-aws-ta"
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
        "feeds": feeds,
    }
    write_file(profile_dir / "metadata.json", json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    write_file(profile_dir / "profile-plan.md", render_plan_md(args, feeds))
    write_file(profile_dir / "inputs.local.conf.template", render_inputs(args, feeds))
    write_file(profile_dir / "account-setup.md", render_account_setup(args))
    write_file(profile_dir / "install-commands.sh", render_install_commands(args), executable=True)
    write_file(profile_dir / "validation-searches.spl", render_validation_spl(args, feeds))
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
    feeds = selected_feeds(args.feeds)
    if args.phase == "list":
        emit({"ok": True, "app_name": APP_NAME, "splunkbase_id": SPLUNKBASE_ID, "feeds": list(FEEDS)}, args.json)
        return 0
    emit(render_assets(args, feeds), args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

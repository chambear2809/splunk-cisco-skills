#!/usr/bin/env python3
"""Render reviewable Splunk Add-on for GitHub assets."""

from __future__ import annotations

import argparse
import json
import stat
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = REPO_ROOT / "splunk-github-ta-rendered"

APP_NAME = "Splunk_TA_github"
SPLUNKBASE_ID = "6254"
LATEST_VERIFIED_VERSION = "3.3.0"

INPUTS = {"audit", "user", "code_scanning", "dependabot", "secret_scanning"}
ALERT_TYPES = {
    "code_scanning": ("github_code_scanning_alerts", "code_scanning_alerts", "github:cloud:code:scanning:alerts"),
    "dependabot": ("github_dependabot_alerts", "dependabot_alerts", "github:cloud:dependabot:scanning:alerts"),
    "secret_scanning": ("github_secret_scanning_alerts", "secret_scanning_alerts", "github:cloud:secret:scanning:alerts"),
}
SOURCETYPES = [
    "github:cloud:audit",
    "github:enterprise:audit",
    "github:cloud:user",
    "github:cloud:code:scanning:alerts",
    "github:cloud:dependabot:scanning:alerts",
    "github:cloud:secret:scanning:alerts",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Splunk_TA_github assets.")
    parser.add_argument("--phase", choices=("render", "list"), default="render")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--index", default="github", help="Target GitHub event index.")
    parser.add_argument("--account-name", default="github_prod", help="GitHub PAT account stanza name.")
    parser.add_argument("--org", default="my-org", help="GitHub organization name.")
    parser.add_argument("--enterprise", default="my-enterprise", help="GitHub Enterprise slug.")
    parser.add_argument("--account-type", choices=("Organization", "Enterprise"), default="Organization")
    parser.add_argument("--events-type", choices=("web", "git", "all"), default="all")
    parser.add_argument(
        "--inputs",
        default="audit,user,code_scanning,dependabot,secret_scanning",
        help="Comma-separated inputs: audit,user,code_scanning,dependabot,secret_scanning.",
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def parse_inputs(raw: str) -> list[str]:
    values = [item.strip() for item in raw.split(",") if item.strip()]
    unknown = [item for item in values if item not in INPUTS]
    if unknown:
        raise SystemExit(f"ERROR: unknown input(s): {', '.join(unknown)}. Choose from {', '.join(sorted(INPUTS))}.")
    return values


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def account_scope_lines(args: argparse.Namespace) -> list[str]:
    if args.account_type == "Enterprise":
        return [f"account_type = {args.account_type}", f"enterprises_name = {args.enterprise}"]
    return [f"account_type = {args.account_type}", f"org_name = {args.org}"]


def render_inputs(args: argparse.Namespace, selected: list[str]) -> str:
    lines = [
        f"# Starter local/inputs.conf overlay for {APP_NAME} (Splunkbase {SPLUNKBASE_ID}).",
        f"# Copy reviewed stanzas into $SPLUNK_HOME/etc/apps/{APP_NAME}/local/inputs.conf.",
        f"# Reference account '{args.account_name}' configured in the add-on Configuration tab.",
        "",
    ]
    scope = account_scope_lines(args)
    if "audit" in selected:
        lines += [
            "[github_audit_input://github_audit]",
            "disabled = 0",
            "input_type = Audit",
            f"events_type = {args.events_type}",
            *scope,
            "use_existing_checkpoint = 0",
            "start_date = 2026-01-01T00:00:00Z",
            f"account = {args.account_name}",
            "interval = 300",
            f"index = {args.index}",
            "",
        ]
    if "user" in selected:
        lines += [
            "[github_user_input://github_user]",
            "disabled = 0",
            "input_type = User",
            f"account = {args.account_name}",
            f"org_name = {args.org}",
            "interval = 86400",
            f"index = {args.index}",
            "",
        ]
    for key, (stanza_name, alert_type, _sourcetype) in ALERT_TYPES.items():
        if key not in selected:
            continue
        lines += [
            f"[github_alerts_input://{stanza_name}]",
            "disabled = 0",
            "input_type = Alert",
            f"alert_type = {alert_type}",
            "state = open",
            "severity = critical,high,medium,low",
            *scope,
            "start_date = 2026-01-01T00:00:00Z",
            f"account = {args.account_name}",
            "interval = 300",
            f"index = {args.index}",
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"


def render_account_setup(args: argparse.Namespace) -> str:
    return f"""# {APP_NAME} Account And Streaming Runbook

## GitHub Cloud API Inputs

Create account `{args.account_name}` with a GitHub Personal Access Token (PAT)
or GitHub App token that can read audit logs, user metadata, and selected alert
APIs for `{args.org}` / `{args.enterprise}`.

Write the token to a protected local file:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/github_pat
```

REST handler: `/servicesNS/nobody/{APP_NAME}/Splunk_TA_github_account`.
Secrets are stored encrypted in `storage/passwords`; this skill never places
tokens in argv or rendered conf.

## GitHub Cloud HEC Audit Streaming

GitHub Enterprise Cloud can stream audit logs to Splunk HEC. Use a dedicated
HEC token created through `splunk-hec-service-setup`, constrained to index
`{args.index}`. Keep generic HEC events constrained by source, for example
`source = http:github` with `sourcetype = httpevent`, until package/API inputs
classify cloud audit data as `github:cloud:audit`.

## GHES Syslog / SC4S Handoff

For GitHub Enterprise Server, prefer syslog through SC4S or a reviewed HEC
pipeline and normalize to package-backed `github:enterprise:audit` where
documented. Hand off syslog transport to SC4S skills and Splunk HEC token setup
to `splunk-hec-service-setup`.
"""


def render_install_commands(args: argparse.Namespace) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail

# Review before running. No secrets are embedded in this file.
bash skills/splunk-app-install/scripts/install_app.sh --source splunkbase --app-id {SPLUNKBASE_ID}
bash skills/splunk-github-ta-setup/scripts/setup.sh --create-index --index {args.index}

# Configure account {args.account_name}, then enable the rendered inputs.
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh --phase collect --source-pack github_audit
"""


def render_validation_spl(args: argparse.Namespace) -> str:
    sourcetypes = ",".join(f'"{s}"' for s in SOURCETYPES)
    return f"""# {APP_NAME} validation searches

index={args.index} sourcetype IN ({sourcetypes})
| stats count min(_time) as first_seen max(_time) as last_seen by sourcetype
| convert ctime(first_seen) ctime(last_seen)

index={args.index} sourcetype=github:cloud:audit OR sourcetype=github:enterprise:audit
| stats count dc(actor) as actors dc(repo) as repos values(operation_type) as operations by action org

index={args.index} sourcetype IN ("github:cloud:code:scanning:alerts","github:cloud:dependabot:scanning:alerts","github:cloud:secret:scanning:alerts")
| stats count by sourcetype state severity repository.name

index=_internal source=*splunkd.log* ({APP_NAME} OR github_audit_input OR github_alerts_input)
| stats count values(log_level) as levels by sourcetype
"""


def render_plan_md(args: argparse.Namespace, selected: list[str]) -> str:
    rows = [
        "| `github_audit_input` | `github:cloud:audit` | Cloud audit API collection |",
        "| `github_user_input` | `github:cloud:user` | Cloud user metadata |",
        "| `github_alerts_input` `alert_type=code_scanning_alerts` | `github:cloud:code:scanning:alerts` | Code scanning alerts |",
        "| `github_alerts_input` `alert_type=dependabot_alerts` | `github:cloud:dependabot:scanning:alerts` | Dependabot alerts |",
        "| `github_alerts_input` `alert_type=secret_scanning_alerts` | `github:cloud:secret:scanning:alerts` | Secret scanning alerts |",
        "| HEC/syslog handoff | `httpevent` with `source=http:github` or `github:enterprise:audit` | Cloud streaming / GHES audit |",
    ]
    return f"""# {APP_NAME} Setup Plan

Add-on: `{APP_NAME}` (Splunkbase `{SPLUNKBASE_ID}`, verified `{LATEST_VERIFIED_VERSION}`)
Event index: `{args.index}`
Account: `{args.account_name}`
Rendered inputs: `{", ".join(selected)}`

## Role Placement

| Role | Support |
| --- | --- |
| `search-tier` | required for setup and knowledge objects |
| `heavy-forwarder` | supported for API collection |
| `indexer` | none |
| `universal-forwarder` | none |
| `external-collector` | supported for GHES syslog / HEC transport handoff |

## Package-Backed Inputs And Source Types

| Input | Source type | Notes |
| --- | --- | --- |
{chr(10).join(rows)}

## Guardrails

- Store PAT or GitHub App token only in the add-on account.
- Run API collection on one node per organization/enterprise.
- Keep generic `httpevent` matching source-constrained to `http:github`.
- Dashboard behavior is package-backed only; no custom dashboards are generated.
"""


def render_assets(args: argparse.Namespace, selected: list[str]) -> dict[str, Any]:
    output_root = Path(args.output_dir).expanduser().resolve()
    profile_dir = output_root / "splunk-github-ta"
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
        "inputs": selected,
        "source_package": f"splunk-ta/_unpacked/{APP_NAME}-{LATEST_VERIFIED_VERSION}/{APP_NAME}",
        "sourcetypes": SOURCETYPES,
    }
    write_file(profile_dir / "metadata.json", json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    write_file(profile_dir / "profile-plan.md", render_plan_md(args, selected))
    write_file(profile_dir / "inputs.local.conf.template", render_inputs(args, selected))
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
    selected = parse_inputs(args.inputs)
    if args.phase == "list":
        emit(
            {
                "ok": True,
                "app_name": APP_NAME,
                "splunkbase_id": SPLUNKBASE_ID,
                "inputs": sorted(INPUTS),
                "sourcetypes": SOURCETYPES,
            },
            args.json,
        )
        return 0
    emit(render_assets(args, selected), args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

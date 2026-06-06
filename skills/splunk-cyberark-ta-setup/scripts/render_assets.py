#!/usr/bin/env python3
"""Render CyberArk Splunk add-on assets."""

from __future__ import annotations

import argparse
import json
import stat
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = REPO_ROOT / "splunk-cyberark-ta-rendered"
PRODUCTS = ["epm", "epv_pta"]
EPM_APP = "Splunk_TA_cyberark_epm"
EPM_ID = "5160"
EPM_VERSION = "4.0.0"
LEGACY_APP = "Splunk_TA_cyberark"
LEGACY_ID = "2891"
LEGACY_VERSION = "1.2.0"
EPM_INPUTS = [
    "application_events",
    "inbox_events",
    "admin_audit_logs",
    "account_admin_audit_logs",
    "policy_audit",
    "policy_audit_events",
    "threat_detection",
    "policies_and_computers",
]
EPM_SOURCETYPES = [
    "cyberark:epm:raw:events",
    "cyberark:epm:raw:policy:events",
    "cyberark:epm:admin:audit",
    "cyberark:epm:account:admin:audit",
    "cyberark:epm:application:events",
    "cyberark:epm:policy:audit",
    "cyberark:epm:threat:detection",
]
LEGACY_SOURCETYPES = ["cyberark:epv:cef", "cyberark:pta:cef"]
REST_HANDLERS = [
    "splunk_ta_cyberark_epm_account",
    "splunk_ta_cyberark_epm_application_events",
    "splunk_ta_cyberark_epm_inbox_events",
    "splunk_ta_cyberark_epm_admin_audit_logs",
    "splunk_ta_cyberark_epm_account_admin_audit_logs",
    "splunk_ta_cyberark_epm_policy_audit",
    "splunk_ta_cyberark_epm_policy_audit_events",
    "splunk_ta_cyberark_epm_threat_detection",
    "splunk_ta_cyberark_epm_policies_and_computers",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Render CyberArk Splunk add-on assets.")
    p.add_argument("--phase", choices=("render", "list"), default="render")
    p.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    p.add_argument("--index", default="cyberark")
    p.add_argument("--account-name", default="cyberark_epm_prod")
    p.add_argument(
        "--products",
        default=",".join(PRODUCTS),
        help="Comma-separated products: epm,epv_pta",
    )
    p.add_argument(
        "--epm-inputs",
        default=",".join(EPM_INPUTS),
        help="Comma-separated CyberArk EPM inputs",
    )
    p.add_argument("--syslog-port", default="514")
    p.add_argument("--json", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def parse_list(raw: str, allowed: list[str], label: str) -> list[str]:
    vals = [x.strip().lower() for x in raw.split(",") if x.strip()]
    if not vals:
        raise SystemExit(
            f"ERROR: at least one {label} is required. Choose from {', '.join(allowed)}."
        )
    unknown = [x for x in vals if x not in allowed]
    if unknown:
        raise SystemExit(
            f"ERROR: unknown {label}: {', '.join(unknown)}. Choose from {', '.join(allowed)}."
        )
    return vals


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def render_inputs(
    args: argparse.Namespace, products: list[str], epm_inputs: list[str]
) -> str:
    lines = [
        f"# Starter local/inputs.conf overlay for {EPM_APP}.",
        f"# Copy reviewed stanzas into $SPLUNK_HOME/etc/apps/{EPM_APP}/local/inputs.conf.",
        "",
    ]
    if "epm" not in products:
        lines.append("# EPM inputs not selected.")
        return "\n".join(lines).rstrip() + "\n"
    for name in epm_inputs:
        lines += [
            f"[{name}://{name}]",
            "disabled = 0",
            f"account_name = {args.account_name}",
            "interval = 300",
            "start_date = 2026-01-01T00:00:00Z",
            f"index = {args.index}",
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"


def render_transport(args: argparse.Namespace, products: list[str]) -> str:
    if "epv_pta" not in products:
        return "# EPV/PTA transport not selected.\n"
    return f"""# CyberArk EPV/PTA Transport Handoff

`{LEGACY_APP}` (Splunkbase `{LEGACY_ID}`, verified `{LEGACY_VERSION}`) is archived/not-supported and parser-only.
It does not define modular inputs. Own transport outside the app:

- Preferred: SC4S/syslog receiver on UDP/TCP `{args.syslog_port}` with app-context routing.
- Stamp EPV vault events as `sourcetype=cyberark:epv:cef`.
- Stamp PTA analytics events as `sourcetype=cyberark:pta:cef`.
- Send to index `{args.index}` or a reviewed CyberArk security index.

Do not use generic `cef` or `syslog` as readiness evidence unless source is constrained to the CyberArk transport and normalized to the package source type.
"""


def render_account_setup(args: argparse.Namespace, products: list[str]) -> str:
    if "epm" not in products:
        return (
            "# CyberArk EPM account not selected.\n\n"
            "EPV/PTA is parser-only and has no account handler in the archived package.\n"
        )
    return f"""# {EPM_APP} Account Runbook

Create account `{args.account_name}` through the CyberArk EPM add-on account handler `/servicesNS/nobody/{EPM_APP}/splunk_ta_cyberark_epm_account`.

Put API credentials into a protected local file before entering them in Splunk:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/cyberark_epm_secret
```

Splunk stores the account material encrypted in `storage/passwords`. Do not add credential values to rendered files or command-line arguments.

REST handlers verified in the package: {", ".join(REST_HANDLERS)}.
"""


def render_install_commands(args: argparse.Namespace, products: list[str]) -> str:
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        "# Review before running. No secrets are embedded in this file.",
    ]
    if "epm" in products:
        lines.append(
            f"bash skills/splunk-app-install/scripts/install_app.sh --source splunkbase --app-id {EPM_ID}"
        )
    if "epv_pta" in products:
        lines.append(
            "# Archived/not-supported parser-only package: review before installing.\n"
            f"bash skills/splunk-app-install/scripts/install_app.sh --source splunkbase --app-id {LEGACY_ID}"
        )
    lines += [
        f"bash skills/splunk-cyberark-ta-setup/scripts/setup.sh --create-index --index {args.index}",
        "bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh --phase collect --source-pack cyberark_epm,cyberark_epv_pta",
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_validation_spl(args: argparse.Namespace) -> str:
    sts = ",".join(f'"{s}"' for s in EPM_SOURCETYPES + LEGACY_SOURCETYPES)
    return f"""# CyberArk validation searches

index={args.index} sourcetype IN ({sts})
| stats count min(_time) as first_seen max(_time) as last_seen by sourcetype
| convert ctime(first_seen) ctime(last_seen)

index={args.index} sourcetype IN ("cyberark:epm:threat:detection","cyberark:pta:cef")
| stats count dc(user) as users values(action) as actions by sourcetype severity

index=_internal source=*splunkd.log* (Splunk_TA_cyberark_epm OR cyberark_epm)
| stats count values(log_level) as levels by sourcetype component
"""


def render_plan(
    args: argparse.Namespace, products: list[str], epm_inputs: list[str]
) -> str:
    return f"""# CyberArk Setup Plan

Selected products: `{", ".join(products)}`
Index: `{args.index}`
EPM account: `{args.account_name}`
EPM add-on: `{EPM_APP}` Splunkbase `{EPM_ID}` verified `{EPM_VERSION}`
EPV/PTA add-on: `{LEGACY_APP}` Splunkbase `{LEGACY_ID}` verified `{LEGACY_VERSION}` archived/not-supported

## Support Boundary

CyberArk EPM is the supported API collection path. CyberArk EPV/PTA is an archived parser-only package; use it only with explicit acceptance of that status and own transport through SC4S/syslog or another reviewed ingestion path.

## Rendered Inputs

`{", ".join(epm_inputs) if "epm" in products else "none"}`

## Package-Backed Source Types

EPM: `{", ".join(EPM_SOURCETYPES)}`
EPV/PTA: `{", ".join(LEGACY_SOURCETYPES)}`
"""


def render_assets(
    args: argparse.Namespace, products: list[str], epm_inputs: list[str]
) -> dict[str, Any]:
    out = Path(args.output_dir).expanduser().resolve() / "splunk-cyberark-ta"
    files = [
        "account-setup.md",
        "inputs.local.conf.template",
        "install-commands.sh",
        "metadata.json",
        "profile-plan.md",
        "transport-handoff.md",
        "validation-searches.spl",
    ]
    if args.dry_run:
        return {"ok": True, "dry_run": True, "output_dir": str(out), "files": files}
    metadata = {
        "products": products,
        "index": args.index,
        "account_name": args.account_name,
        "apps": {
            "epm": {
                "app_name": EPM_APP,
                "splunkbase_id": EPM_ID,
                "latest_verified_version": EPM_VERSION,
                "sourcetypes": EPM_SOURCETYPES,
                "rest_handlers": REST_HANDLERS,
                "source_package": f"splunk-ta/_unpacked/{EPM_APP}-{EPM_VERSION}/{EPM_APP}",
            },
            "epv_pta": {
                "app_name": LEGACY_APP,
                "splunkbase_id": LEGACY_ID,
                "latest_verified_version": LEGACY_VERSION,
                "archived_not_supported": True,
                "sourcetypes": LEGACY_SOURCETYPES,
                "source_package": f"splunk-ta/_unpacked/{LEGACY_APP}-{LEGACY_VERSION}/{LEGACY_APP}",
            },
        },
    }
    write_file(
        out / "metadata.json", json.dumps(metadata, indent=2, sort_keys=True) + "\n"
    )
    write_file(out / "profile-plan.md", render_plan(args, products, epm_inputs))
    write_file(
        out / "inputs.local.conf.template", render_inputs(args, products, epm_inputs)
    )
    write_file(out / "transport-handoff.md", render_transport(args, products))
    write_file(out / "account-setup.md", render_account_setup(args, products))
    write_file(
        out / "install-commands.sh",
        render_install_commands(args, products),
        executable=True,
    )
    write_file(out / "validation-searches.spl", render_validation_spl(args))
    return {
        "ok": True,
        "dry_run": False,
        "output_dir": str(out),
        "files": sorted(p.name for p in out.iterdir() if p.is_file()),
    }


def emit(payload: dict[str, Any], json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif "files" in payload:
        print(f"Output: {payload['output_dir']}\nFiles: " + ", ".join(payload["files"]))
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))


def main() -> int:
    args = parse_args()
    products = parse_list(args.products, PRODUCTS, "product selector")
    epm_inputs = parse_list(args.epm_inputs, EPM_INPUTS, "EPM input selector")
    if args.phase == "list":
        emit(
            {
                "ok": True,
                "products": PRODUCTS,
                "epm_inputs": EPM_INPUTS,
                "sourcetypes": EPM_SOURCETYPES + LEGACY_SOURCETYPES,
            },
            args.json,
        )
        return 0
    emit(render_assets(args, products, epm_inputs), args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

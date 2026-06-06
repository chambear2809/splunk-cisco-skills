#!/usr/bin/env python3
"""Render RSA SecurID Splunk add-on assets."""

from __future__ import annotations

import argparse
import json
import stat
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = REPO_ROOT / "splunk-rsa-securid-ta-rendered"
PRODUCTS = ["cas", "am"]
CAS_APP = "Splunk_TA_rsa_securid_cas"
CAS_ID = "5210"
CAS_VERSION = "1.2.2"
AM_APP = "Splunk_TA_rsa-securid"
AM_ID = "2958"
AM_VERSION = "1.5.0"
CAS_ENDPOINTS = ["adminlog", "usereventlog", "riskuser"]
CAS_ENDPOINT_PATHS = {
    "adminlog": "adminlog",
    "usereventlog": "usereventlog",
    "riskuser": "/v2/users/highrisk",
}
CAS_SOURCETYPES = [
    "rsa:securid:cas:adminlog:json",
    "rsa:securid:cas:usereventlog:json",
    "rsa:securid:cas:riskuser:json",
]
AM_SOURCETYPES = [
    "rsa:securid:syslog",
    "rsa:securid:admin:syslog",
    "rsa:securid:runtime:syslog",
    "rsa:securid:system:syslog",
]
REST_HANDLERS = [
    "splunk_ta_rsa_securid_cas_account",
    "splunk_ta_rsa_securid_cas_cloud_administration_api",
    "splunk_ta_rsa_securid_cas_settings",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Render RSA SecurID Splunk add-on assets.")
    p.add_argument("--phase", choices=("render", "list"), default="render")
    p.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    p.add_argument("--index", default="rsa")
    p.add_argument("--account-name", default="rsa_cas_prod")
    p.add_argument(
        "--products",
        default=",".join(PRODUCTS),
        help="Comma-separated products: cas,am",
    )
    p.add_argument(
        "--cas-endpoints",
        default=",".join(CAS_ENDPOINTS),
        help="Comma-separated endpoints: adminlog,usereventlog,riskuser",
    )
    p.add_argument("--syslog-port", default="514")
    p.add_argument("--json", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def parse_list(raw: str, allowed: list[str], label: str) -> list[str]:
    vals = [x.strip().lower() for x in raw.split(",") if x.strip()]
    unknown = [x for x in vals if x not in allowed]
    if not vals:
        raise SystemExit(
            f"ERROR: at least one {label} is required. Choose from {', '.join(allowed)}."
        )
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
    args: argparse.Namespace, products: list[str], endpoints: list[str]
) -> str:
    lines = [
        f"# Starter local/inputs.conf overlay for {CAS_APP}.",
        f"# Copy reviewed stanzas into $SPLUNK_HOME/etc/apps/{CAS_APP}/local/inputs.conf.",
        "",
    ]
    if "cas" not in products:
        lines.append("# CAS inputs not selected.")
        return "\n".join(lines).rstrip() + "\n"
    for endpoint in endpoints:
        lines += [
            f"[cloud_administration_api://rsa_cas_{endpoint}]",
            "disabled = 0",
            f"account_name = {args.account_name}",
            f"endpoint = {CAS_ENDPOINT_PATHS[endpoint]}",
            "interval = 300",
            "startTimeAfter = 2026-01-01T00:00:00Z",
            f"index = {args.index}",
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"


def render_transport(args: argparse.Namespace, products: list[str]) -> str:
    if "am" not in products:
        return "# RSA Authentication Manager transport not selected.\n"
    return f"""# RSA SecurID Authentication Manager Transport Handoff

`{AM_APP}` (Splunkbase `{AM_ID}`, verified `{AM_VERSION}`) is syslog/parser based.
Own transport outside the app:

- Preferred: SC4S/syslog receiver on UDP/TCP `{args.syslog_port}`.
- Default AM sourcetype: `rsa:securid:syslog`.
- Use package-specific variants when the sender distinguishes admin, runtime, or system streams:
  `rsa:securid:admin:syslog`, `rsa:securid:runtime:syslog`, `rsa:securid:system:syslog`.
- Send to index `{args.index}` or a reviewed identity/security index.

Do not use generic `syslog` as readiness evidence unless constrained to RSA AM source ownership and normalized to the package source type.
"""


def render_account_setup(args: argparse.Namespace, products: list[str]) -> str:
    if "cas" not in products:
        return (
            "# RSA SecurID CAS account not selected.\n\n"
            "RSA AM is syslog/parser based and has no API account handler.\n"
        )
    return f"""# {CAS_APP} Account Runbook

Create account `{args.account_name}` through `/servicesNS/nobody/{CAS_APP}/splunk_ta_rsa_securid_cas_account`.

Write CAS API credential material to a protected local file before entering it in Splunk:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/rsa_cas_secret
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
    if "cas" in products:
        lines.append(
            f"bash skills/splunk-app-install/scripts/install_app.sh --source splunkbase --app-id {CAS_ID}"
        )
    if "am" in products:
        lines.append(
            f"bash skills/splunk-app-install/scripts/install_app.sh --source splunkbase --app-id {AM_ID}"
        )
    lines += [
        f"bash skills/splunk-rsa-securid-ta-setup/scripts/setup.sh --create-index --index {args.index}",
        "bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh --phase collect --source-pack rsa_securid_cas,rsa_securid_am",
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_validation_spl(args: argparse.Namespace) -> str:
    sts = ",".join(f'"{s}"' for s in CAS_SOURCETYPES + AM_SOURCETYPES)
    return f"""# RSA SecurID validation searches

index={args.index} sourcetype IN ({sts})
| stats count min(_time) as first_seen max(_time) as last_seen by sourcetype
| convert ctime(first_seen) ctime(last_seen)

index={args.index} sourcetype IN ("rsa:securid:cas:usereventlog:json","rsa:securid:syslog")
| stats count dc(user) as users values(result) as results by sourcetype action

index=_internal source=*splunkd.log* ({CAS_APP} OR rsa_securid_cas)
| stats count values(log_level) as levels by sourcetype component
"""


def render_plan(
    args: argparse.Namespace, products: list[str], endpoints: list[str]
) -> str:
    return f"""# RSA SecurID Setup Plan

Selected products: `{", ".join(products)}`
Index: `{args.index}`
CAS account: `{args.account_name}`
CAS add-on: `{CAS_APP}` Splunkbase `{CAS_ID}` verified `{CAS_VERSION}`
AM add-on: `{AM_APP}` Splunkbase `{AM_ID}` verified `{AM_VERSION}`

## Rendered CAS Endpoints

`{", ".join(endpoints) if "cas" in products else "none"}`

## Package-Backed Source Types

CAS: `{", ".join(CAS_SOURCETYPES)}`
AM: `{", ".join(AM_SOURCETYPES)}`
"""


def render_assets(
    args: argparse.Namespace, products: list[str], endpoints: list[str]
) -> dict[str, Any]:
    out = Path(args.output_dir).expanduser().resolve() / "splunk-rsa-securid-ta"
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
            "cas": {
                "app_name": CAS_APP,
                "splunkbase_id": CAS_ID,
                "latest_verified_version": CAS_VERSION,
                "endpoints": endpoints,
                "sourcetypes": CAS_SOURCETYPES,
                "rest_handlers": REST_HANDLERS,
                "source_package": f"splunk-ta/_unpacked/{CAS_APP}-{CAS_VERSION}/{CAS_APP}",
            },
            "am": {
                "app_name": AM_APP,
                "splunkbase_id": AM_ID,
                "latest_verified_version": AM_VERSION,
                "sourcetypes": AM_SOURCETYPES,
                "source_package": f"splunk-ta/_unpacked/{AM_APP}-{AM_VERSION}/{AM_APP}",
            },
        },
    }
    write_file(
        out / "metadata.json", json.dumps(metadata, indent=2, sort_keys=True) + "\n"
    )
    write_file(out / "profile-plan.md", render_plan(args, products, endpoints))
    write_file(
        out / "inputs.local.conf.template", render_inputs(args, products, endpoints)
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
    endpoints = parse_list(args.cas_endpoints, CAS_ENDPOINTS, "CAS endpoint selector")
    if args.phase == "list":
        emit(
            {
                "ok": True,
                "products": PRODUCTS,
                "cas_endpoints": CAS_ENDPOINTS,
                "sourcetypes": CAS_SOURCETYPES + AM_SOURCETYPES,
            },
            args.json,
        )
        return 0
    emit(render_assets(args, products, endpoints), args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

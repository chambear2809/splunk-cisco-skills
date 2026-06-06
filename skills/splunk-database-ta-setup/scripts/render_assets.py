#!/usr/bin/env python3
"""Render package-verified database supported add-on assets."""

from __future__ import annotations

import argparse
import json
import stat
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = REPO_ROOT / "splunk-database-ta-rendered"

PRODUCTS: dict[str, dict[str, Any]] = {
    "mssql": {
        "label": "Microsoft SQL Server",
        "app": "Splunk_TA_microsoft-sqlserver",
        "id": "2648",
        "version": "3.1.0",
        "source_pack": "mssql_database",
        "placement": "Windows host file/perfmon plus DB Connect JDBC handoff",
        "sourcetypes": [
            "mssql:errorlog",
            "mssql:agentlog",
            "mssql:audit",
            "mssql:instance",
            "mssql:os:dm_os_sys_info",
            "mssql:execution:dm_exec_sessions",
            "mssql:execution:dm_exec_query_stats",
            "mssql:transaction:dm_tran_locks",
        ],
        "eventtypes": [
            "microsoft_sqlserver_instance",
            "microsoft_sqlserver_error_auth",
            "microsoft_sqlserver_audit_login",
            "microsoft_sqlserver_query",
        ],
        "lookups": ["sqlserver_host_dbserver_lookup"],
    },
    "mysql": {
        "label": "MySQL",
        "app": "Splunk_TA_mysql",
        "id": "2848",
        "version": "3.2.0",
        "source_pack": "mysql_database",
        "placement": "DB Connect JDBC handoff plus reviewed host log collection",
        "sourcetypes": [
            "mysql:errorLog",
            "mysql:generalQueryLog",
            "mysql:slowQueryLog",
            "mysql:audit",
            "mysql:status",
            "mysql:variables",
            "mysql:instance:stats",
            "mysql:connection:stats",
        ],
        "eventtypes": [
            "mysql_errorLog",
            "mysql_generalQueryLog",
            "mysql_slowQueryLog",
            "mysql_audit_connection",
        ],
        "lookups": ["mysql_audit_error_lookup"],
    },
    "oracle": {
        "label": "Oracle Database",
        "app": "Splunk_TA_oracle",
        "id": "1910",
        "version": "4.2.0",
        "source_pack": "oracle_database",
        "placement": "DB Connect JDBC handoff plus alert/listener/audit file collection",
        "sourcetypes": [
            "oracle:audit:unified",
            "oracle:audit:text",
            "oracle:audit:xml",
            "oracle:listener:text",
            "oracle:alert:text",
            "oracle:database",
            "oracle:instance",
            "oracle:session",
            "oracle:sysPerf",
            "oracle:query",
        ],
        "eventtypes": [
            "oracle:audit:xml",
            "oracle:auth",
            "oracle:database",
            "oracle:instance",
            "oracle:session",
        ],
        "lookups": [
            "oracle_action_lookup",
            "oracle_audit_type_lookup",
            "oracle_returncode_lookup",
        ],
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render database supported add-on assets.")
    parser.add_argument("--phase", choices=("render", "list"), default="render")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--products", default="mssql,mysql,oracle", help="Comma-separated selectors: mssql,mysql,oracle")
    parser.add_argument("--index", default="database", help="Target database event index.")
    parser.add_argument("--server-name", default="db01", help="Host value for SQL Server host input examples.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def selected_products(raw: str) -> list[str]:
    values = [item.strip().lower() for item in raw.split(",") if item.strip()]
    unknown = [item for item in values if item not in PRODUCTS]
    if not values or unknown:
        raise SystemExit(f"ERROR: choose product selectors from {', '.join(PRODUCTS)}")
    return values


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def render_plan(args: argparse.Namespace, products: list[str]) -> str:
    rows = [
        f"| `{key}` | `{profile['app']}` | `{profile['id']}` | `{profile['version']}` | `{profile['placement']}` | `{profile['source_pack']}` |"
        for key, profile in ((key, PRODUCTS[key]) for key in products)
    ]
    return f"""# Database Supported Add-ons Setup Plan

Target index: `{args.index}`

| Selector | App | Splunkbase | Verified | Placement | Source Pack |
| --- | --- | --- | --- | --- | --- |
{chr(10).join(rows)}

## Guardrails

- Install search-time add-on knowledge on the search tier.
- Run DB Connect inputs through the `splunk-db-connect-setup` workflow and DBX identities.
- Deploy SQL Server host log and Perfmon collection only to reviewed Windows collection owners.
- Do not pass database secrets on command lines.
"""


def render_inputs(args: argparse.Namespace, products: list[str]) -> str:
    lines = [
        "# Starter local/inputs.conf overlays from extracted package source types.",
        "# Enable only on reviewed collection owners.",
        "",
    ]
    if "mssql" in products:
        lines += [
            "# Splunk_TA_microsoft-sqlserver package host log inputs",
            "[monitor://C:\\Program Files\\Microsoft SQL Server\\MSSQL*\\MSSQL\\Log\\ERRORLOG*]",
            "disabled = 1",
            "sourcetype = mssql:errorlog",
            f"index = {args.index}",
            f"host = {args.server_name}",
            "",
            "[monitor://C:\\Program Files\\Microsoft SQL Server\\MSSQL*\\MSSQL\\Log\\SQLAGENT.OUT]",
            "disabled = 1",
            "sourcetype = mssql:agentlog",
            f"index = {args.index}",
            f"host = {args.server_name}",
            "",
            "[Perfmon:sqlserver:General Statistics]",
            "disabled = 1",
            "sourcetype = Perfmon:sqlserver:General Statistics",
            f"index = {args.index}",
            "",
        ]
    for key in products:
        if key == "mssql":
            continue
        profile = PRODUCTS[key]
        lines += [
            f"# {profile['label']} has package knowledge and DB Connect templates.",
            f"# Use splunk-db-connect-setup for JDBC inputs that stamp: {', '.join(profile['sourcetypes'])}",
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"


def render_dbx(args: argparse.Namespace, products: list[str]) -> str:
    lines = [
        "# DB Connect Handoff",
        "",
        "Use `splunk-db-connect-setup` for JDBC connection objects, identities, drivers, inputs, and validation.",
        "Create any database password file locally before entering it into DB Connect so Splunk stores the secret encrypted.",
        "",
        "```bash",
        "bash skills/shared/scripts/write_secret_file.sh /tmp/db_connect_password",
        "```",
        "",
        "Selected package source types:",
        "",
    ]
    for key in products:
        profile = PRODUCTS[key]
        lines.append(f"## {profile['label']}")
        lines.extend(f"- `{sourcetype}`" for sourcetype in profile["sourcetypes"])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_install_commands(args: argparse.Namespace, products: list[str]) -> str:
    lines = ["#!/usr/bin/env bash", "set -euo pipefail", "", "# Review before running. No secrets are embedded in this file."]
    for key in products:
        profile = PRODUCTS[key]
        lines.append(
            f"bash skills/splunk-app-install/scripts/install_app.sh --source splunkbase --app-id {profile['id']} --app-version {profile['version']} --no-update  # {profile['app']}"
        )
    packs = ",".join(PRODUCTS[key]["source_pack"] for key in products)
    lines += [
        "bash skills/splunk-db-connect-setup/scripts/setup.sh --help",
        f"bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh --phase collect --source-pack {packs}",
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_validation(args: argparse.Namespace, products: list[str]) -> str:
    clauses = []
    for key in products:
        sourcetypes = ",".join(f'"{item}"' for item in PRODUCTS[key]["sourcetypes"])
        clauses.append(f"(index={args.index} sourcetype IN ({sourcetypes}))")
    return f"""# Database TA validation searches

{' OR '.join(clauses)}
| stats count min(_time) as first_seen max(_time) as last_seen by index sourcetype host source
| convert ctime(first_seen) ctime(last_seen)

index=_internal source=*splunkd.log* ({' OR '.join(PRODUCTS[key]['app'] for key in products)} OR dbx)
| stats count values(log_level) as levels by sourcetype component
"""


def render_assets(args: argparse.Namespace, products: list[str]) -> dict[str, Any]:
    output = Path(args.output_dir).expanduser().resolve() / "splunk-database-ta"
    files = [
        "db-connect-handoff.md",
        "inputs.local.conf.template",
        "install-commands.sh",
        "metadata.json",
        "profile-plan.md",
        "validation-searches.spl",
    ]
    if args.dry_run:
        return {"ok": True, "dry_run": True, "output_dir": str(output), "files": files}
    metadata = {
        "index": args.index,
        "products": products,
        "profiles": {key: PRODUCTS[key] for key in products},
        "source": "extracted Splunkbase packages",
    }
    write_file(output / "metadata.json", json.dumps(metadata, indent=2, sort_keys=True))
    write_file(output / "profile-plan.md", render_plan(args, products))
    write_file(output / "inputs.local.conf.template", render_inputs(args, products))
    write_file(output / "db-connect-handoff.md", render_dbx(args, products))
    write_file(output / "install-commands.sh", render_install_commands(args, products), executable=True)
    write_file(output / "validation-searches.spl", render_validation(args, products))
    return {"ok": True, "dry_run": False, "output_dir": str(output), "files": sorted(files)}


def emit(payload: dict[str, Any], json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(f"Output: {payload.get('output_dir', '')}")
    if payload.get("files"):
        print("Files: " + ", ".join(payload["files"]))


def main() -> int:
    args = parse_args()
    products = selected_products(args.products)
    if args.phase == "list":
        emit({"ok": True, "products": products, "profiles": {key: PRODUCTS[key] for key in products}}, args.json)
        return 0
    emit(render_assets(args, products), args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

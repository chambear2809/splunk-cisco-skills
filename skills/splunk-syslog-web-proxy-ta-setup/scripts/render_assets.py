#!/usr/bin/env python3
"""Render shared syslog, web, and proxy supported add-on assets."""

from __future__ import annotations

import argparse
import json
import stat
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = REPO_ROOT / "splunk-syslog-web-proxy-ta-rendered"

PROFILES: dict[str, dict[str, Any]] = {
    "apache": {
        "label": "Apache Web Server",
        "app": "Splunk_TA_apache",
        "id": "3186",
        "version": "3.0.0",
        "transport": "local_file_uf",
        "index_arg": "index",
        "sourcetypes": [
            "apache:access",
            "apache:access:combined",
            "apache:access:json",
            "apache:access:kv",
            "apache:error",
        ],
        "monitors": [
            ("/var/log/apache2/access.log", "apache:access:combined"),
            ("/var/log/apache2/error.log", "apache:error"),
        ],
    },
    "nginx": {
        "label": "NGINX",
        "app": "Splunk_TA_nginx",
        "id": "3258",
        "version": "3.3.0",
        "transport": "local_file_uf",
        "index_arg": "index",
        "sourcetypes": [
            "nginx:plus:access",
            "nginx:plus:kv",
            "nginx:plus:error",
            "nginx:plus:api",
            "nginx:app:protect",
        ],
        "monitors": [
            ("/var/log/nginx/access.log", "nginx:plus:access"),
            ("/var/log/nginx/error.log", "nginx:plus:error"),
        ],
    },
    "iis": {
        "label": "Microsoft IIS",
        "app": "Splunk_TA_microsoft-iis",
        "id": "3185",
        "version": "2.0.0",
        "transport": "windows_uf_iis",
        "index_arg": "windows_index",
        "sourcetypes": [
            "ms:iis:auto",
            "ms:iis:default",
            "ms:iis:default:85",
            "ms:iis:splunk",
            "ms:iis:webglobalmodule",
        ],
        "monitors": [("C:\\inetpub\\logs\\LogFiles\\W3SVC*\\*.log", "ms:iis:auto")],
    },
    "tomcat": {
        "label": "Tomcat",
        "app": "Splunk_TA_tomcat",
        "id": "2911",
        "version": "4.0.0",
        "transport": "local_file_uf",
        "index_arg": "index",
        "sourcetypes": [
            "tomcat:access:log",
            "tomcat:access:log:splunk",
            "tomcat:runtime:log",
            "tomcat:jmx",
        ],
        "monitors": [
            ("/opt/tomcat/logs/localhost_access_log*.txt", "tomcat:access:log"),
            ("/opt/tomcat/logs/catalina*.log", "tomcat:runtime:log"),
        ],
    },
    "haproxy": {
        "label": "HAProxy",
        "app": "Splunk_TA_haproxy",
        "id": "3135",
        "version": "2.0.0",
        "transport": "local_file_uf",
        "index_arg": "index",
        "sourcetypes": [
            "haproxy:default",
            "haproxy:http",
            "haproxy:tcp",
            "haproxy:clf:http",
            "haproxy:splunk:http",
        ],
        "monitors": [("/var/log/haproxy.log", "haproxy:http")],
    },
    "squid": {
        "label": "Squid Proxy",
        "app": "Splunk_TA_squid",
        "id": "2965",
        "version": "2.1.0",
        "transport": "sc4s_syslog",
        "index_arg": "syslog_index",
        "sourcetypes": ["squid:access", "squid:access:recommended"],
    },
    "bluecoat": {
        "label": "Blue Coat ProxySG",
        "app": "Splunk_TA_bluecoat-proxysg",
        "id": "2758",
        "version": "3.9.0",
        "transport": "sc4s_syslog",
        "index_arg": "syslog_index",
        "sourcetypes": [
            "bluecoat",
            "bluecoat:proxysg:access:syslog",
            "bluecoat:proxysg:access:file",
            "bluecoat:proxysg:access:kv",
        ],
    },
    "forcepoint": {
        "label": "Forcepoint Web Security",
        "app": "Splunk_TA_websense-cg",
        "id": "2966",
        "version": "1.1.0",
        "transport": "sc4s_syslog",
        "index_arg": "syslog_index",
        "sourcetypes": ["websense", "websense:cg:kv"],
    },
    "checkpoint": {
        "label": "Check Point Log Exporter",
        "app": "Splunk_TA_checkpoint_log_exporter",
        "id": "5478",
        "version": "1.2.0",
        "transport": "sc4s_syslog",
        "index_arg": "syslog_index",
        "sourcetypes": ["cp_log", "cp_log:syslog"],
    },
    "f5": {
        "label": "F5 BIG-IP",
        "app": "Splunk_TA_f5-bigip",
        "id": "2680",
        "version": "6.5.1",
        "transport": "sc4s_syslog_or_api",
        "index_arg": "syslog_index",
        "sourcetypes": [
            "f5:bigip:syslog",
            "f5:bigip:asm:syslog",
            "f5:bigip:apm:syslog",
            "f5:telemetry:json",
            "f5:bigip:ltm:icontrol",
            "f5:bigip:system:icontrol",
        ],
    },
    "citrix": {
        "label": "Citrix NetScaler",
        "app": "Splunk_TA_citrix-netscaler",
        "id": "2770",
        "version": "8.2.3",
        "transport": "sc4s_syslog_or_api",
        "index_arg": "syslog_index",
        "sourcetypes": [
            "citrix:netscaler",
            "citrix:netscaler:syslog",
            "citrix:netscaler:ipfix",
            "citrix:netscaler:ipfix:syslog",
            "citrix:netscaler:nitro",
            "citrix:netscaler:appfw",
            "citrix:netscaler:appfw:cef",
        ],
    },
    "infoblox": {
        "label": "Infoblox",
        "app": "Splunk_TA_infoblox",
        "id": "2934",
        "version": "2.2.0",
        "transport": "sc4s_syslog",
        "index_arg": "syslog_index",
        "sourcetypes": [
            "infoblox:dns",
            "infoblox:dhcp",
            "infoblox:audit",
            "infoblox:threatprotect",
            "infoblox:file",
            "infoblox:port",
        ],
    },
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Render syslog/web/proxy supported add-on assets."
    )
    p.add_argument("--phase", choices=("render", "list"), default="render")
    p.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    p.add_argument("--index", default="web")
    p.add_argument("--syslog-index", default="netproxy")
    p.add_argument("--windows-index", default="iis")
    p.add_argument(
        "--products",
        default=",".join(PROFILES),
        help="Comma-separated product selectors",
    )
    p.add_argument("--server-name", default="web01")
    p.add_argument("--log-root", default="/var/log")
    p.add_argument("--syslog-port", default="514")
    p.add_argument("--json", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def parse_products(raw: str) -> list[str]:
    vals = [x.strip().lower() for x in raw.split(",") if x.strip()]
    if not vals:
        raise SystemExit(
            f"ERROR: at least one product selector is required. Choose from {', '.join(PROFILES)}."
        )
    unknown = [x for x in vals if x not in PROFILES]
    if unknown:
        raise SystemExit(
            f"ERROR: unknown product selector(s): {', '.join(unknown)}. "
            f"Choose from {', '.join(PROFILES)}."
        )
    return vals


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def index_for(args: argparse.Namespace, product: str) -> str:
    key = PROFILES[product]["index_arg"]
    return getattr(args, key)


def source_path(args: argparse.Namespace, original: str) -> str:
    prefix = "/var/log/"
    if original.startswith(prefix):
        suffix = original[len(prefix) :]
        root = args.log_root.rstrip("/") or "/"
        return f"/{suffix}" if root == "/" else f"{root}/{suffix}"
    return original


def render_inputs(args: argparse.Namespace, products: list[str]) -> str:
    lines = [
        "# Starter local/inputs.conf overlays for host-owned file collection.",
        "# Use only on the correct Universal Forwarder or Windows UF owner.",
        "",
    ]
    for product in products:
        profile = PROFILES[product]
        if profile["transport"] not in {"local_file_uf", "windows_uf_iis"}:
            continue
        lines += [
            f"# {profile['label']} ({profile['app']}) transport: {profile['transport']}"
        ]
        for path, sourcetype in profile.get("monitors", []):
            lines += [
                f"[monitor://{source_path(args, path)}]",
                "disabled = 0",
                f"sourcetype = {sourcetype}",
                f"index = {index_for(args, product)}",
                f"host = {args.server_name}",
                "",
            ]
        if product == "iis":
            lines += [
                "# Optional IIS module inventory input from the package.",
                "[powershell://IISModules]",
                "disabled = 1",
                "sourcetype = ms:iis:webglobalmodule",
                f"index = {index_for(args, product)}",
                "",
            ]
        if product == "tomcat":
            lines += [
                "# Optional JMX input stub; configure account/connectivity in the Tomcat add-on before enabling.",
                "[tomcat://tomcat_jmx]",
                "disabled = 1",
                "sourcetype = tomcat:jmx",
                f"index = {index_for(args, product)}",
                "",
            ]
    if len(lines) == 3:
        lines.append("# No local file or Windows UF profiles selected.")
    return "\n".join(lines).rstrip() + "\n"


def render_transport(args: argparse.Namespace, products: list[str]) -> str:
    lines = [
        "# SC4S / Syslog / Appliance Transport Handoff",
        "",
        f"Default syslog port: `{args.syslog_port}`",
        f"Default appliance index: `{args.syslog_index}`",
        "",
    ]
    selected = False
    for product in products:
        profile = PROFILES[product]
        if not profile["transport"].startswith("sc4s"):
            continue
        selected = True
        lines += [
            f"## {profile['label']} ({profile['app']})",
            "",
            f"Transport owner: `{profile['transport']}`",
            f"Splunkbase: `{profile['id']}` verified `{profile['version']}`",
            f"Index: `{index_for(args, product)}`",
            "Package source types:",
            *[f"- `{s}`" for s in profile["sourcetypes"]],
            "",
            "Do not leave this data as generic `syslog`; stamp the exact package source type at the collector or heavy-forwarder parsing layer.",
            "",
        ]
    if not selected:
        lines.append("No appliance/syslog profiles selected.")
    return "\n".join(lines).rstrip() + "\n"


def render_install_commands(args: argparse.Namespace, products: list[str]) -> str:
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        "# Review before running. No secrets are embedded in this file.",
    ]
    for product in products:
        profile = PROFILES[product]
        lines.append(
            f"bash skills/splunk-app-install/scripts/install_app.sh "
            f"--source splunkbase --app-id {profile['id']}  # {profile['app']}"
        )
    packs = ",".join(pack_id(product) for product in products)
    lines.append(
        f"bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh "
        f"--phase collect --source-pack {packs}"
    )
    return "\n".join(lines).rstrip() + "\n"


def pack_id(product: str) -> str:
    return {
        "apache": "apache_web",
        "nginx": "nginx_web",
        "iis": "microsoft_iis",
        "tomcat": "tomcat_web",
        "haproxy": "haproxy",
        "squid": "squid_proxy",
        "bluecoat": "bluecoat_proxy",
        "forcepoint": "forcepoint_web",
        "checkpoint": "checkpoint_log_exporter",
        "f5": "f5_bigip",
        "citrix": "citrix_netscaler",
        "infoblox": "infoblox",
    }[product]


def render_validation_spl(args: argparse.Namespace, products: list[str]) -> str:
    clauses = []
    for product in products:
        sts = ",".join(f'"{s}"' for s in PROFILES[product]["sourcetypes"])
        clauses.append(f"(index={index_for(args, product)} sourcetype IN ({sts}))")
    apps = " OR ".join(PROFILES[p]["app"] for p in products)
    return (
        "# Syslog/web/proxy validation searches\n\n"
        + "\nOR ".join(clauses)
        + "\n| stats count min(_time) as first_seen max(_time) as last_seen by index sourcetype host source\n"
        "| convert ctime(first_seen) ctime(last_seen)\n\n"
        f"index=_internal source=*splunkd.log* ({apps})\n"
        "| stats count values(log_level) as levels by sourcetype component\n"
    )


def render_plan(args: argparse.Namespace, products: list[str]) -> str:
    rows = []
    for product in products:
        profile = PROFILES[product]
        rows.append(
            f"| `{product}` | `{profile['app']}` | `{profile['id']}` | "
            f"`{profile['version']}` | `{profile['transport']}` | `{index_for(args, product)}` |"
        )
    return (
        "# Syslog/Web/Proxy Setup Plan\n\n"
        "| Selector | App | Splunkbase | Version | Transport | Index |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        + "\n".join(rows)
        + "\n\n## Guardrails\n\n"
        "- Web-server local file monitors belong on the web server UF or a controlled log forwarder.\n"
        "- IIS logs belong on the Windows UF owner.\n"
        "- Appliance profiles belong on SC4S/syslog or a reviewed heavy-forwarder parsing path.\n"
        "- Readiness matching must use exact package source types or constrained source/source-type pairs.\n"
    )


def render_account_setup(args: argparse.Namespace, products: list[str]) -> str:
    lines = [
        "# Account And Transport Setup Runbook",
        "",
        "This shared renderer does not accept credential values and does not create Splunk encrypted accounts by default.",
        "Most selected products use host-owned log files, Windows UF IIS collection, or SC4S/syslog handoff.",
        "",
        "If an optional appliance API path is later enabled for a product such as F5 BIG-IP or Citrix NetScaler, put credentials into a protected local file first:",
        "",
        "```bash",
        "bash skills/shared/scripts/write_secret_file.sh /tmp/appliance_secret",
        "```",
        "",
        "Then enter the value through the relevant add-on setup page so Splunk stores it encrypted in `storage/passwords`. Do not place credential values in argv, rendered files, or environment variables.",
        "",
        "## Selected Transport Ownership",
        "",
    ]
    for product in products:
        profile = PROFILES[product]
        lines.append(
            f"- `{product}`: `{profile['transport']}` transport, "
            f"index `{index_for(args, product)}`, app `{profile['app']}`."
        )
    lines += [
        "",
        f"SC4S/syslog defaults use port `{args.syslog_port}` and index `{args.syslog_index}` unless overridden.",
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_assets(args: argparse.Namespace, products: list[str]) -> dict[str, Any]:
    out = Path(args.output_dir).expanduser().resolve() / "splunk-syslog-web-proxy-ta"
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
        "indexes": {
            "local_file": args.index,
            "syslog": args.syslog_index,
            "windows": args.windows_index,
        },
        "profiles": {p: PROFILES[p] for p in products},
    }
    write_file(
        out / "metadata.json", json.dumps(metadata, indent=2, sort_keys=True) + "\n"
    )
    write_file(out / "profile-plan.md", render_plan(args, products))
    write_file(out / "inputs.local.conf.template", render_inputs(args, products))
    write_file(out / "transport-handoff.md", render_transport(args, products))
    write_file(out / "account-setup.md", render_account_setup(args, products))
    write_file(
        out / "install-commands.sh",
        render_install_commands(args, products),
        executable=True,
    )
    write_file(out / "validation-searches.spl", render_validation_spl(args, products))
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
    products = parse_products(args.products)
    if args.phase == "list":
        emit({"ok": True, "products": list(PROFILES), "profiles": PROFILES}, args.json)
        return 0
    emit(render_assets(args, products), args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

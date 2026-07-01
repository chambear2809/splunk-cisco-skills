#!/usr/bin/env python3
"""Render plans for Splunk Supported Add-ons profiles."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import stat
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = SKILL_DIR / "catalog.json"
DEFAULT_OUTPUT = REPO_ROOT / "splunk-supported-addons-rendered"
ROLE_KEYS = [
    "search-tier",
    "indexer",
    "heavy-forwarder",
    "universal-forwarder",
    "external-collector",
]
ROLE_VALUES = {"required", "supported", "none"}
REQUIRED_PROFILES = {"unix-linux-os-scripts", "linux-collectd-auditd"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Splunk Supported Add-ons router assets.")
    parser.add_argument(
        "--phase",
        choices=("list", "coverage", "resolve", "render", "install-command", "readiness-command"),
        default="render",
    )
    parser.add_argument("--profile", default="unix-linux", help="Profile, domain, app name, Splunkbase ID, source type, or alias.")
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--event-index", default="os")
    parser.add_argument("--metrics-index", default="os_metrics")
    parser.add_argument("--hec-token-name", default="linux_collectd_hec")
    parser.add_argument("--tcp-port", default="2104")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def die(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def normalize(value: str) -> str:
    return " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in value).split())


def shell_join(command: list[str]) -> str:
    return " ".join(shlex.quote(str(part)) for part in command)


def load_catalog(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        die(f"Catalog not found: {path}")
    except json.JSONDecodeError as exc:
        die(f"Catalog is invalid JSON: {exc}")


def profiles_by_key(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(profile["key"]): profile for profile in catalog.get("profiles", [])}


def validate_catalog(catalog: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    profiles = catalog.get("profiles")
    domains = catalog.get("domains")
    supported_statuses = set(str(status) for status in catalog.get("supported_statuses", []))
    if not isinstance(profiles, list) or not profiles:
        errors.append("catalog must contain a non-empty profiles list")
        return errors
    if not isinstance(domains, list) or not domains:
        errors.append("catalog must contain a non-empty domains list")

    seen_profile_keys: set[str] = set()
    seen_ids: set[str] = set()
    profile_keys = set()

    for profile in profiles:
        key = str(profile.get("key", "")).strip()
        profile_keys.add(key)
        if not key:
            errors.append("profile missing key")
            continue
        if key in seen_profile_keys:
            errors.append(f"duplicate profile key: {key}")
        seen_profile_keys.add(key)

        for field in ("domain", "name", "status", "aliases", "add_on", "role_support", "source_types", "commands", "docs"):
            if field not in profile:
                errors.append(f"{key}: missing {field}")

        add_on = profile.get("add_on", {})
        if not isinstance(add_on, dict):
            errors.append(f"{key}: add_on must be an object")
            continue
        for field in ("name", "app_name", "splunkbase_id", "latest_verified_version", "latest_verified_date"):
            if not str(add_on.get(field, "")).strip():
                errors.append(f"{key}: add_on missing {field}")
        splunkbase_id = str(add_on.get("splunkbase_id", "")).strip()
        if not splunkbase_id.isdigit():
            errors.append(f"{key}: splunkbase_id must be numeric")
        elif splunkbase_id in seen_ids:
            errors.append(f"{key}: duplicate splunkbase_id {splunkbase_id}")
        else:
            seen_ids.add(splunkbase_id)

        role_support = profile.get("role_support", {})
        if not isinstance(role_support, dict):
            errors.append(f"{key}: role_support must be an object")
        else:
            if set(role_support) != set(ROLE_KEYS):
                errors.append(f"{key}: role_support must cover {', '.join(ROLE_KEYS)}")
            bad_values = sorted(set(str(value) for value in role_support.values()) - ROLE_VALUES)
            if bad_values:
                errors.append(f"{key}: invalid role_support values: {', '.join(bad_values)}")

        install = profile.get("commands", {}).get("install", [])
        if not isinstance(install, list) or splunkbase_id not in [str(part) for part in install]:
            errors.append(f"{key}: install command must include Splunkbase ID {splunkbase_id}")

        source_types = profile.get("source_types", [])
        if not isinstance(source_types, list) or not all(isinstance(item, str) and item.strip() for item in source_types):
            errors.append(f"{key}: source_types must be a non-empty string list")

        docs = profile.get("docs", [])
        if not isinstance(docs, list) or not all(str(url).startswith("https://") for url in docs):
            errors.append(f"{key}: docs must be https URLs")

    missing_profiles = sorted(REQUIRED_PROFILES - profile_keys)
    if missing_profiles:
        errors.append("missing required Unix/Linux profiles: " + ", ".join(missing_profiles))

    for domain in domains if isinstance(domains, list) else []:
        domain_key = str(domain.get("key", "")).strip()
        domain_profiles = set(domain.get("profiles", []))
        unknown = sorted(domain_profiles - profile_keys)
        if unknown:
            errors.append(f"{domain_key}: unknown profile references: {', '.join(unknown)}")
        default_profile = str(domain.get("default_profile", "")).strip()
        if default_profile and default_profile not in profile_keys:
            errors.append(f"{domain_key}: default_profile {default_profile} is not a known profile")

    glossary = catalog.get("official_glossary", {})
    if glossary:
        entries = glossary.get("entries", [])
        routes = glossary.get("routes", {})
        if not isinstance(entries, list) or not entries:
            errors.append("official_glossary.entries must be a non-empty list")
        if not isinstance(routes, dict):
            errors.append("official_glossary.routes must be an object")
            routes = {}
        seen_entries: set[str] = set()
        for entry in entries if isinstance(entries, list) else []:
            key = str(entry.get("key", "")).strip()
            name = str(entry.get("name", "")).strip()
            if not key or not name:
                errors.append("official_glossary entry missing key or name")
                continue
            if key in seen_entries:
                errors.append(f"official_glossary duplicate entry key: {key}")
            seen_entries.add(key)
        for key, route in routes.items():
            if key not in seen_entries:
                errors.append(f"official_glossary route has no matching entry: {key}")
            if not isinstance(route, dict):
                errors.append(f"official_glossary route for {key} must be an object")
                continue
            status = str(route.get("status", "")).strip()
            if status not in supported_statuses:
                errors.append(f"official_glossary route for {key} has unsupported status: {status}")
            profile_key = str(route.get("profile", "")).strip()
            if profile_key and profile_key not in profile_keys:
                errors.append(f"official_glossary route for {key} points to unknown profile: {profile_key}")

    return errors


def profile_terms(profile: dict[str, Any]) -> set[str]:
    add_on = profile.get("add_on", {})
    values = [
        profile.get("key", ""),
        profile.get("domain", ""),
        profile.get("name", ""),
        *profile.get("aliases", []),
        add_on.get("name", ""),
        add_on.get("app_name", ""),
        add_on.get("splunkbase_id", ""),
        *profile.get("source_types", []),
        *profile.get("metric_source_types", []),
    ]
    return {normalize(str(value)) for value in values if normalize(str(value))}


def resolve_profile(catalog: dict[str, Any], query: str) -> dict[str, Any]:
    profile = find_profile(catalog, query)
    if profile is None:
        die(f"No supported add-on profile matched {query!r}.")
    return profile


def find_profile(catalog: dict[str, Any], query: str) -> dict[str, Any] | None:
    profiles = catalog.get("profiles", [])
    if not profiles:
        die("Catalog has no profiles.")

    normalized_query = normalize(query or "")
    if not normalized_query:
        normalized_query = "unix linux"

    domains = catalog.get("domains", [])
    for domain in domains:
        domain_terms = {normalize(str(domain.get("key", ""))), normalize(str(domain.get("name", "")))}
        domain_terms.update(normalize(str(alias)) for alias in domain.get("aliases", []))
        if normalized_query in domain_terms:
            default_key = str(domain.get("default_profile", "")).strip()
            by_key = profiles_by_key(catalog)
            if default_key in by_key:
                return by_key[default_key]

    scored: list[tuple[int, dict[str, Any]]] = []
    query_tokens = set(normalized_query.split())
    for profile in profiles:
        terms = profile_terms(profile)
        score = 0
        if normalized_query in terms:
            score = max(score, 100)
        for term in terms:
            term_tokens = set(term.split())
            if query_tokens and query_tokens.issubset(term_tokens):
                score = max(score, 80)
            elif query_tokens & term_tokens:
                score = max(score, 10 * len(query_tokens & term_tokens))
        scored.append((score, profile))

    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored or scored[0][0] <= 0:
        return None
    return scored[0][1]


def glossary_doc_url(catalog: dict[str, Any], entry: dict[str, Any]) -> str:
    base = "https://help.splunk.com/en/supported-add-ons/splunk-supported-add-ons"
    return str(entry.get("docs", [f"{base}/{entry['key']}"])[0])


def glossary_entry_payload(catalog: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    glossary = catalog.get("official_glossary", {})
    route = dict(glossary.get("routes", {}).get(entry["key"], {}))
    status = route.pop("status", "install_only_handoff")
    payload = {
        "key": entry["key"],
        "name": entry["name"],
        "status": status,
        "doc_url": glossary_doc_url(catalog, entry),
    }
    if status == "install_only_handoff" and "handoff_skill" not in route:
        route["handoff_skill"] = "splunk-app-install"
        route["notes"] = (
            "Generic official Supported Add-on handoff: install the package through "
            "splunk-app-install using a Splunkbase, remote, or local package source, "
            "then follow the official add-on documentation for input configuration."
        )
    if status == "install_only_handoff" and "commands" not in route:
        route["commands"] = generic_install_commands()
    if entry.get("aliases"):
        payload["aliases"] = entry["aliases"]
    payload.update(route)
    return payload


def generic_install_commands() -> dict[str, list[str]]:
    return {
        "install_help": ["bash", "skills/splunk-app-install/scripts/install_app.sh", "--help"],
        "install_local_template": [
            "bash",
            "skills/splunk-app-install/scripts/install_app.sh",
            "--source",
            "local",
            "--file",
            "${ADDON_PACKAGE}",
        ],
        "install_remote_template": [
            "bash",
            "skills/splunk-app-install/scripts/install_app.sh",
            "--source",
            "remote",
            "--url",
            "${ADDON_URL}",
        ],
        "install_splunkbase_template": [
            "bash",
            "skills/splunk-app-install/scripts/install_app.sh",
            "--source",
            "splunkbase",
            "--app-id",
            "${SPLUNKBASE_APP_ID}",
        ],
    }


def handoff_install_command(coverage: dict[str, Any]) -> list[str] | None:
    """Return the most actionable setup command for a handoff profile."""
    skill = str(coverage.get("handoff_skill", "")).strip()
    if not skill or skill == "splunk-app-install":
        return None
    setup = REPO_ROOT / "skills" / skill / "scripts" / "setup.sh"
    if not setup.is_file():
        return None

    text = setup.read_text(encoding="utf-8", errors="ignore")
    command = ["bash", f"skills/{skill}/scripts/setup.sh"]
    if re.search(r"--all\s*\)", text):
        command.append("--all")
    elif re.search(r"--install\s*\)", text):
        command.append("--install")
    else:
        return None

    selector = str(coverage.get("product_selector", "")).strip()
    if selector and "--products" in text:
        command.extend(["--products", selector])
    return command


def glossary_terms(entry: dict[str, Any]) -> set[str]:
    values = [entry.get("key", ""), entry.get("name", ""), *entry.get("aliases", [])]
    return {normalize(str(value)) for value in values if normalize(str(value))}


def coverage_payload(catalog: dict[str, Any]) -> dict[str, Any]:
    glossary = catalog.get("official_glossary", {})
    entries = [glossary_entry_payload(catalog, entry) for entry in glossary.get("entries", [])]
    summary: dict[str, int] = {}
    for entry in entries:
        summary[entry["status"]] = summary.get(entry["status"], 0) + 1
    return {
        "ok": True,
        "source_url": glossary.get("source_url"),
        "last_researched": glossary.get("last_researched"),
        "entry_count": len(entries),
        "summary": dict(sorted(summary.items())),
        "entries": entries,
    }


def resolve_glossary_entry(catalog: dict[str, Any], query: str) -> dict[str, Any] | None:
    normalized_query = normalize(query or "")
    if not normalized_query:
        return None
    glossary = catalog.get("official_glossary", {})
    scored: list[tuple[int, dict[str, Any]]] = []
    query_tokens = set(normalized_query.split())
    for entry in glossary.get("entries", []):
        terms = glossary_terms(entry)
        score = 0
        if normalized_query in terms:
            score = max(score, 100)
        for term in terms:
            term_tokens = set(term.split())
            if query_tokens and query_tokens.issubset(term_tokens):
                score = max(score, 80)
            elif query_tokens & term_tokens:
                score = max(score, 10 * len(query_tokens & term_tokens))
        scored.append((score, entry))
    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored or scored[0][0] <= 0:
        return None
    return glossary_entry_payload(catalog, scored[0][1])


def coverage_exact_query(coverage: dict[str, Any], query: str) -> bool:
    normalized_query = normalize(query or "")
    terms = {normalize(str(coverage.get("key", ""))), normalize(str(coverage.get("name", "")))}
    terms.update(normalize(str(alias)) for alias in coverage.get("aliases", []))
    return bool(normalized_query and normalized_query in terms)


def profile_payload(profile: dict[str, Any]) -> dict[str, Any]:
    add_on = profile["add_on"]
    return {
        "key": profile["key"],
        "domain": profile["domain"],
        "name": profile["name"],
        "status": profile["status"],
        "add_on": add_on,
        "role_support": profile["role_support"],
        "source_types": profile.get("source_types", []),
        "metric_source_types": profile.get("metric_source_types", []),
        "commands": profile.get("commands", {}),
        "guardrails": profile.get("guardrails", []),
        "docs": profile.get("docs", []),
    }


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def render_install_commands(profile: dict[str, Any], args: argparse.Namespace) -> str:
    commands = profile.get("commands", {})
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        "# Review before running. No secrets are embedded in this file.",
        f"# Profile: {profile['name']}",
        "",
    ]
    install = commands.get("install")
    if install:
        lines.extend(["# Install or update the supported add-on from Splunkbase.", shell_join(install), ""])
    if profile["key"] == "unix-linux-os-scripts":
        forwarder_app = commands.get("forwarder_app")
        if forwarder_app:
            lines.extend(
                [
                    "# Render a deployment-server/Agent Management handoff for forwarder rollout.",
                    shell_join(forwarder_app + ["--phase", "render"]),
                    "",
                ]
            )
    if profile["key"] == "linux-collectd-auditd":
        hec = commands.get("hec")
        if hec:
            metrics_hec = ["linux:collectd:http:metrics" if part == "linux:collectd:http:json" else part for part in hec]
            lines.extend(
                [
                    "# Prepare a HEC token and receiver for CollectD JSON events. Supply token values by file to the HEC skill.",
                    shell_join(
                        hec
                        + [
                            "--token-name",
                            args.hec_token_name,
                            "--default-index",
                            args.event_index,
                            "--allowed-indexes",
                            args.event_index,
                        ]
                    ),
                    "",
                    "# Prepare a separate HEC token and receiver for CollectD metrics-index ingestion.",
                    shell_join(
                        metrics_hec
                        + [
                            "--token-name",
                            f"{args.hec_token_name}_metrics",
                            "--default-index",
                            args.metrics_index,
                            "--allowed-indexes",
                            args.metrics_index,
                        ]
                    ),
                    "",
                ]
            )
    readiness = commands.get("readiness_collect")
    if readiness:
        lines.extend(["# Render read-only post-ingest collection SPL.", shell_join(readiness), ""])
    return "\n".join(lines).rstrip() + "\n"


def render_nix_inputs(args: argparse.Namespace) -> str:
    return f"""# Starter local/inputs.conf overlay for Splunk_TA_nix.
# Copy only reviewed stanzas into $SPLUNK_HOME/etc/apps/Splunk_TA_nix/local/inputs.conf.
# Review distro-specific paths and intervals before enabling in production.

[monitor:///var/log/secure]
disabled = 0
sourcetype = linux_secure
index = {args.event_index}

[monitor:///var/log/auth.log]
disabled = 0
sourcetype = linux_secure
index = {args.event_index}

[monitor:///var/log/audit/audit.log]
disabled = 0
sourcetype = linux_audit
index = {args.event_index}

[script://./bin/cpu.sh]
disabled = 0
interval = 60
index = {args.event_index}

[script://./bin/df.sh]
disabled = 0
interval = 300
index = {args.event_index}

[script://./bin/iostat.sh]
disabled = 0
interval = 300
index = {args.event_index}

[script://./bin/interfaces.sh]
disabled = 0
interval = 300
index = {args.event_index}

[script://./bin/ps.sh]
disabled = 0
interval = 300
index = {args.event_index}

[script://./bin/vmstat.sh]
disabled = 0
interval = 300
index = {args.event_index}

[script://./bin/cpu_metric.sh]
disabled = 0
interval = 60
index = {args.metrics_index}

[script://./bin/df_metric.sh]
disabled = 0
interval = 300
index = {args.metrics_index}

[script://./bin/interfaces_metric.sh]
disabled = 0
interval = 300
index = {args.metrics_index}

[script://./bin/iostat_metric.sh]
disabled = 0
interval = 300
index = {args.metrics_index}

[script://./bin/ps_metric.sh]
disabled = 0
interval = 300
index = {args.metrics_index}

[script://./bin/vmstat_metric.sh]
disabled = 0
interval = 300
index = {args.metrics_index}
"""


def render_linux_collectd_inputs(args: argparse.Namespace) -> str:
    return f"""# Starter local/inputs.conf overlay for Splunk_TA_Linux AuditD file collection.
# CollectD HEC/TCP setup is rendered separately. Review paths before enabling.

[monitor:///var/log/audit/audit.log]
disabled = 0
sourcetype = linux:audit
index = {args.event_index}
"""


def render_linux_collectd_props() -> str:
    return """# Starter local/props.conf overlay for Splunk_TA_Linux metrics over HEC.
# Required when using the linux:collectd:http:metrics source type.

[linux:collectd:http:metrics]
METRICS_PROTOCOL = COLLECTD_HTTP
"""


def render_collectd_http(args: argparse.Namespace) -> str:
    return f"""# CollectD write_http skeleton. Replace placeholders locally.
# Do not store HEC token values in this repository.

LoadPlugin write_http
<Plugin write_http>
  <Node "splunk-hec-json">
    URL "https://SPLUNK_HEC_HOST:8088/services/collector/raw?channel=__HEC_TOKEN_VALUE__"
    Header "Authorization: Splunk __HEC_TOKEN_VALUE__"
    Format "JSON"
    Metrics true
    StoreRates true
  </Node>
</Plugin>

# For metrics-index ingestion, set the HEC input source type to:
# linux:collectd:http:metrics
# Recommended metrics index: {args.metrics_index}
"""


def render_collectd_graphite(args: argparse.Namespace) -> str:
    return f"""# CollectD write_graphite skeleton. Review host, port, and network path.
# TCP collection uses sourcetype linux:collectd:graphite and cannot collect metrics.

LoadPlugin write_graphite
<Plugin write_graphite>
  <Node "splunk-graphite">
    Host "SPLUNK_TCP_INPUT_HOST"
    Port "{args.tcp_port}"
    Protocol "tcp"
    EscapeCharacter "_"
    AlwaysAppendDS true
    SeparateInstances false
  </Node>
</Plugin>
"""


def validation_searches(profile: dict[str, Any], args: argparse.Namespace) -> str:
    if profile["key"] == "unix-linux-os-scripts":
        return f"""# Splunk_TA_nix validation searches
index={args.event_index} sourcetype IN (linux_secure,linux_audit,auditd,cpu,df,iostat,interfaces,ps,vmstat)
| stats count min(_time) as first_seen max(_time) as last_seen dc(host) as hosts by sourcetype
| convert ctime(first_seen) ctime(last_seen)

| mstats count(_value) where index={args.metrics_index} metric_name IN (cpu_metric.*,df_metric.*,interfaces_metric.*,iostat_metric.*,ps_metric.*,vmstat_metric.*) by metric_name host

index=_internal source=*splunkd.log* (Splunk_TA_nix OR cpu.sh OR df.sh OR iostat.sh OR vmstat.sh OR "permission denied")
| stats count values(log_level) as levels values(component) as components by host
"""
    return f"""# Splunk_TA_Linux validation searches
index={args.event_index} sourcetype IN ("linux:collectd:http:json","linux:collectd:graphite","linux:audit")
| stats count min(_time) as first_seen max(_time) as last_seen dc(host) as hosts by sourcetype
| convert ctime(first_seen) ctime(last_seen)

| mstats count(_value) where index={args.metrics_index} sourcetype="linux:collectd:http:metrics" by metric_name host

index=_internal source=*splunkd.log* (Splunk_TA_Linux OR "linux:collectd" OR "linux:audit" OR HEC)
| stats count values(log_level) as levels values(component) as components by host
"""


def render_plan_md(profile: dict[str, Any], args: argparse.Namespace) -> str:
    add_on = profile["add_on"]
    commands = profile.get("commands", {})
    role_rows = "\n".join(f"| `{role}` | `{profile['role_support'][role]}` |" for role in ROLE_KEYS)
    source_types = ", ".join(f"`{item}`" for item in profile.get("source_types", [])[:18])
    if len(profile.get("source_types", [])) > 18:
        source_types += f", plus {len(profile['source_types']) - 18} more"
    guardrails = "\n".join(f"- {item}" for item in profile.get("guardrails", []))
    docs = "\n".join(f"- {url}" for url in profile.get("docs", []))
    command_lines = []
    for name, command in commands.items():
        if isinstance(command, list):
            command_lines.append(f"- `{name}`: `{shell_join(command)}`")
    command_text = "\n".join(command_lines)
    return f"""# {profile['name']} Setup Plan

Profile: `{profile['key']}`
Domain: `{profile['domain']}`
Add-on: `{add_on['name']}` (`{add_on['app_name']}`)
Splunkbase ID: `{add_on['splunkbase_id']}`
Latest researched version: `{add_on['latest_verified_version']}` ({add_on['latest_verified_date']})
Rendered event index: `{args.event_index}`
Rendered metrics index: `{args.metrics_index}`

## Role Placement

| Role | Support |
| --- | --- |
{role_rows}

## Source Types

{source_types}

## Handoff Commands

{command_text}

## Guardrails

{guardrails}

## Rendered Files

- `metadata.json`
- `install-commands.sh`
- `inputs.local.conf.template`
- `validation-searches.spl`
- Additional CollectD files for the Linux CollectD profile when applicable.

## Sources

{docs}
"""


def render_assets(profile: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    output_root = Path(args.output_dir).expanduser().resolve()
    profile_dir = output_root / profile["key"]
    if args.dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "profile": profile_payload(profile),
            "output_dir": str(profile_dir),
            "files": [
                "metadata.json",
                "profile-plan.md",
                "install-commands.sh",
                "inputs.local.conf.template",
                "validation-searches.spl",
            ],
        }

    metadata = {
        "profile": profile_payload(profile),
        "render": {
            "event_index": args.event_index,
            "metrics_index": args.metrics_index,
            "hec_token_name": args.hec_token_name,
            "tcp_port": args.tcp_port,
        },
    }
    write_file(profile_dir / "metadata.json", json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    write_file(profile_dir / "profile-plan.md", render_plan_md(profile, args))
    write_file(profile_dir / "install-commands.sh", render_install_commands(profile, args), executable=True)
    write_file(profile_dir / "validation-searches.spl", validation_searches(profile, args))

    if profile["key"] == "unix-linux-os-scripts":
        write_file(profile_dir / "inputs.local.conf.template", render_nix_inputs(args))
    elif profile["key"] == "linux-collectd-auditd":
        write_file(profile_dir / "inputs.local.conf.template", render_linux_collectd_inputs(args))
        write_file(profile_dir / "props.local.conf.template", render_linux_collectd_props())
        write_file(profile_dir / "collectd-write-http.conf.template", render_collectd_http(args))
        write_file(profile_dir / "collectd-write-graphite.conf.template", render_collectd_graphite(args))

    files = sorted(path.name for path in profile_dir.iterdir() if path.is_file())
    return {
        "ok": True,
        "dry_run": False,
        "profile": profile_payload(profile),
        "output_dir": str(profile_dir),
        "files": files,
    }


def render_coverage_install_commands(coverage: dict[str, Any]) -> str:
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        "# Generic official Supported Add-on handoff.",
        f"# Add-on: {coverage['name']}",
        f"# Docs: {coverage['doc_url']}",
        "# Choose exactly one install source below and set the required environment variable first.",
        "",
        "if [[ -n \"${ADDON_PACKAGE:-}\" ]]; then",
        "  bash skills/splunk-app-install/scripts/install_app.sh --source local --file \"${ADDON_PACKAGE}\"",
        "elif [[ -n \"${ADDON_URL:-}\" ]]; then",
        "  bash skills/splunk-app-install/scripts/install_app.sh --source remote --url \"${ADDON_URL}\"",
        "elif [[ -n \"${SPLUNKBASE_APP_ID:-}\" ]]; then",
        "  bash skills/splunk-app-install/scripts/install_app.sh --source splunkbase --app-id \"${SPLUNKBASE_APP_ID}\"",
        "else",
        "  echo \"Set ADDON_PACKAGE, ADDON_URL, or SPLUNKBASE_APP_ID before running.\" >&2",
        "  exit 2",
        "fi",
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_coverage_plan_md(coverage: dict[str, Any]) -> str:
    readiness = ""
    if coverage.get("readiness_source_pack"):
        readiness = (
            "\n## Readiness Handoff\n\n"
            "After ingest is live, collect readiness evidence with:\n\n"
            "```bash\n"
            f"bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh --phase collect --source-pack {coverage['readiness_source_pack']}\n"
            "```\n"
        )
    if coverage["status"] == "handoff_profile":
        coverage_note = (
            "This entry is in the official Splunk Supported Add-ons glossary. A "
            f"local first-class domain skill owns the configuration workflow: "
            f"`{coverage.get('handoff_skill', 'splunk-app-install')}`."
        )
        config_note = (
            f"Use `{coverage.get('handoff_skill', 'splunk-app-install')}` for source types, "
            "index placement, input ownership, credential storage, and deployment role placement."
        )
    else:
        coverage_note = (
            "This entry is in the official Splunk Supported Add-ons glossary. This router "
            "does not have a first-class domain renderer for it yet, so it emits a generic "
            "install and documentation handoff instead of failing as a gap."
        )
        config_note = (
            "Follow the official add-on documentation for source types, index placement, "
            "input ownership, credential storage, and deployment role placement."
        )
    return f"""# {coverage['name']} Supported Add-on Handoff

Coverage key: `{coverage['key']}`
Coverage status: `{coverage['status']}`
Handoff skill: `{coverage.get('handoff_skill', 'splunk-app-install')}`

{coverage_note}

## Install Path

Use `install-commands.sh` with one of these environment variables:

- `ADDON_PACKAGE`: local `.tgz`, `.tar.gz`, or `.spl` package path
- `ADDON_URL`: remote package URL
- `SPLUNKBASE_APP_ID`: Splunkbase app ID when known

## Configuration Path

{config_note}

{readiness}
## Sources

- {coverage['doc_url']}
"""


def render_coverage_assets(coverage: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    output_root = Path(args.output_dir).expanduser().resolve()
    coverage_dir = output_root / coverage["key"]
    if args.dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "coverage": coverage,
            "output_dir": str(coverage_dir),
            "files": ["metadata.json", "handoff-plan.md", "install-commands.sh"],
        }

    metadata = {
        "coverage": coverage,
        "render": {
            "event_index": args.event_index,
            "metrics_index": args.metrics_index,
        },
    }
    write_file(coverage_dir / "metadata.json", json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    write_file(coverage_dir / "handoff-plan.md", render_coverage_plan_md(coverage))
    write_file(coverage_dir / "install-commands.sh", render_coverage_install_commands(coverage), executable=True)
    files = sorted(path.name for path in coverage_dir.iterdir() if path.is_file())
    return {
        "ok": True,
        "dry_run": False,
        "coverage": coverage,
        "output_dir": str(coverage_dir),
        "files": files,
    }


def emit(payload: Any, json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    if isinstance(payload, dict) and "entries" in payload:
        print(f"Supported Add-ons coverage entries: {payload.get('entry_count', 0)}")
        for status, count in payload.get("summary", {}).items():
            print(f"{status}: {count}")
        return
    if isinstance(payload, dict) and "coverage" in payload and "profile" not in payload:
        coverage = payload["coverage"]
        print(f"Coverage: {coverage['name']} ({coverage['status']})")
        if "output_dir" in payload:
            print(f"Output: {payload['output_dir']}")
        if "files" in payload:
            print("Files: " + ", ".join(payload["files"]))
        if coverage.get("profile"):
            print(f"Profile: {coverage['profile']}")
        if coverage.get("handoff_skill"):
            print(f"Handoff: {coverage['handoff_skill']}")
        if "command" in payload:
            print(shell_join(payload["command"]))
        print(f"Docs: {coverage['doc_url']}")
        return
    if isinstance(payload, dict) and "profile" in payload:
        profile = payload["profile"]
        add_on = profile["add_on"]
        print(f"Profile: {profile['name']}")
        print(f"Add-on: {add_on['name']} ({add_on['app_name']}, Splunkbase {add_on['splunkbase_id']})")
        if "output_dir" in payload:
            print(f"Output: {payload['output_dir']}")
        if "files" in payload:
            print("Files: " + ", ".join(payload["files"]))
        if "command" in payload:
            print(shell_join(payload["command"]))
        return
    print(payload)


def main() -> int:
    args = parse_args()
    catalog = load_catalog(Path(args.catalog).expanduser().resolve())
    errors = validate_catalog(catalog)
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1

    if args.phase == "coverage":
        emit(coverage_payload(catalog), args.json)
        return 0

    if args.phase == "list":
        payload = {
            "ok": True,
            "last_researched": catalog.get("last_researched"),
            "coverage_summary": coverage_payload(catalog).get("summary", {}),
            "profiles": [profile_payload(profile) for profile in catalog.get("profiles", [])],
        }
        emit(payload, args.json)
        return 0

    coverage = resolve_glossary_entry(catalog, args.profile)
    profile = find_profile(catalog, args.profile)
    if (
        coverage is not None
        and coverage.get("status") != "first_class_profile"
        and coverage_exact_query(coverage, args.profile)
    ):
        profile = None
    if args.phase == "resolve":
        if profile is not None:
            emit({"ok": True, "profile": profile_payload(profile)}, args.json)
            return 0
        if coverage is not None:
            emit({"ok": True, "coverage": coverage}, args.json)
            return 0
        die(f"No supported add-on profile or glossary entry matched {args.profile!r}.")
    if profile is None:
        coverage = resolve_glossary_entry(catalog, args.profile)
        if coverage is not None:
            if args.phase == "install-command":
                command = handoff_install_command(coverage)
                if not command:
                    die(
                        f"{coverage['name']} has no executable install route with a concrete package or Splunkbase ID; "
                        "render its handoff and invoke splunk-app-install with an explicit source"
                    )
                emit({"ok": True, "coverage": coverage, "command": command}, args.json)
                return 0
            if args.phase == "readiness-command" and coverage.get("readiness_source_pack"):
                emit(
                    {
                        "ok": True,
                        "coverage": coverage,
                        "command": [
                            "bash",
                            "skills/splunk-data-source-readiness-doctor/scripts/setup.sh",
                            "--phase",
                            "collect",
                            "--source-pack",
                            coverage["readiness_source_pack"],
                        ],
                    },
                    args.json,
                )
                return 0
            if args.phase == "render":
                emit(render_coverage_assets(coverage, args), args.json)
                return 0
            die(f"Matched {coverage['name']} but no {args.phase} handoff is available for that entry.")
        die(f"No supported add-on profile matched {args.profile!r}.")

    if args.phase == "install-command":
        emit({"ok": True, "profile": profile_payload(profile), "command": profile["commands"]["install"]}, args.json)
    elif args.phase == "readiness-command":
        emit({"ok": True, "profile": profile_payload(profile), "command": profile["commands"]["readiness_collect"]}, args.json)
    else:
        emit(render_assets(profile, args), args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

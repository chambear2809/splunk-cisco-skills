#!/usr/bin/env python3
"""Render Splunk DB Connect setup assets from a v1 spec."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import stat
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
SHARED_LIB = REPO_ROOT / "skills/shared/lib"
sys.path.insert(0, str(SHARED_LIB))

from yaml_compat import dump_yaml, load_yaml_or_json  # noqa: E402


SPEC_VERSION = "splunk-db-connect-setup/v1"
APP_ID = "2686"
APP_NAME = "splunk_app_db_connect"
APP_VERSION = "4.2.4"
APP_DATE = "April 20, 2026"
OUTPUT_SUBDIR = "splunk-db-connect"

SUPPORTED_SECTIONS = {
    "version",
    "platform",
    "topology",
    "install",
    "java",
    "drivers",
    "settings",
    "identities",
    "connections",
    "inputs",
    "outputs",
    "lookups",
    "indexes",
    "hec",
    "cloud_network",
    "ha",
    "security",
    "validation",
}

ROLE_ALIASES = {
    "search_tier": "search-tier",
    "search-head": "search-tier",
    "search_head": "search-tier",
    "search-tier": "search-tier",
    "sh": "search-tier",
    "shc": "search-tier",
    "heavy_forwarder": "heavy-forwarder",
    "heavy-forwarder": "heavy-forwarder",
    "hf": "heavy-forwarder",
    "indexer": "indexer",
    "idx": "indexer",
    "universal_forwarder": "universal-forwarder",
    "universal-forwarder": "universal-forwarder",
    "uf": "universal-forwarder",
    "deployment_server": "deployment-server",
    "deployment-server": "deployment-server",
    "ds": "deployment-server",
    "shc_member": "shc-member",
    "shc-member": "shc-member",
}

VALID_TOPOLOGIES = {
    "single_sh",
    "distributed_search",
    "dedicated_sh",
    "shc",
    "heavy_forwarder",
    "heavy_forwarder_ha",
    "cloud_victoria",
    "cloud_classic",
}

DRIVER_CATALOG: dict[str, dict[str, str]] = {
    "6149": {
        "name": "redshift",
        "label": "Amazon Redshift JDBC Driver Add-on for Splunk DB Connect",
        "version": "1.2.2",
        "release_date": "September 3, 2025",
        "status": "supported",
        "package_pattern": "amazon-redshift-jdbc-driver-add-on-for-splunk-db-connect_*",
    },
    "6150": {
        "name": "mssql",
        "label": "Microsoft SQL Server JDBC Driver Add-on for Splunk DB Connect",
        "version": "1.3.2",
        "release_date": "August 8, 2025",
        "status": "supported",
        "package_pattern": "microsoft-sql-server-jdbc-driver-add-on-for-splunk-db-connect_*",
    },
    "6151": {
        "name": "oracle",
        "label": "Oracle JDBC Driver Add-on for Splunk DB Connect",
        "version": "2.2.2",
        "release_date": "September 3, 2025",
        "status": "supported",
        "package_pattern": "oracle-jdbc-driver-add-on-for-splunk-db-connect_*",
    },
    "6152": {
        "name": "postgres",
        "label": "PostgreSQL JDBC Driver Add-on for Splunk DB Connect",
        "version": "1.2.2",
        "release_date": "September 3, 2025",
        "status": "supported",
        "package_pattern": "postgresql-jdbc-driver-add-on-for-splunk-db-connect_*",
    },
    "6153": {
        "name": "snowflake",
        "label": "Snowflake JDBC Driver Add-on for Splunk DB Connect",
        "version": "1.2.4",
        "release_date": "March 19, 2026",
        "status": "supported",
        "package_pattern": "snowflake-jdbc-driver-add-on-for-splunk-db-connect_*",
    },
    "6154": {
        "name": "mysql",
        "label": "MySQL JDBC Driver Add-on for Splunk DB Connect",
        "version": "1.1.3",
        "release_date": "September 3, 2025",
        "status": "supported",
        "package_pattern": "mysql-jdbc-driver-add-on-for-splunk-db-connect_*",
    },
    "6332": {
        "name": "db2",
        "label": "IBM DB2 JDBC Driver Add-on for Splunk DB Connect",
        "version": "1.1.1",
        "release_date": "September 22, 2025",
        "status": "supported",
        "package_pattern": "ibm-db2-jdbc-driver-add-on-for-splunk-db-connect_*",
    },
    "7095": {
        "name": "mongodb",
        "label": "MongoDB JDBC Driver Add-on for Splunk DB Connect",
        "version": "1.3.0",
        "release_date": "September 3, 2025",
        "status": "supported",
        "package_pattern": "mongodb-jdbc-driver-add-on-for-splunk-db-connect_*",
    },
    "8133": {
        "name": "athena",
        "label": "Amazon Athena JDBC Driver Add-on for Splunk DB Connect",
        "version": "1.0.1",
        "release_date": "December 16, 2025",
        "status": "supported",
        "package_pattern": "amazon-athena-jdbc-driver-add-on-for-splunk-db-connect_*",
    },
    "6759": {
        "name": "influxdb",
        "label": "InfluxDB JDBC Driver Add-on for Splunk DB Connect",
        "version": "1.0.0",
        "release_date": "March 30, 2023",
        "status": "archived",
        "package_pattern": "influxdb-jdbc-driver-add-on-for-splunk-db-connect_*",
    },
}

CUSTOM_DRIVER_DATABASES = [
    "informix",
    "sap-sql-anywhere",
    "sybase-ase",
    "sybase-iq",
    "hive",
    "bigquery",
    "databricks",
    "unsupported-jdbc-compatible",
]


class Issue:
    def __init__(self, severity: str, message: str) -> None:
        self.severity = severity
        self.message = message

    def as_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "message": self.message}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Splunk DB Connect setup assets.")
    parser.add_argument("--spec", required=True, help="YAML or JSON DB Connect setup spec.")
    parser.add_argument("--output-dir", default=str(REPO_ROOT / "splunk-db-connect-rendered"))
    parser.add_argument("--preflight", action="store_true", help="Validate the spec and print a preflight summary without writing assets.")
    parser.add_argument("--json", action="store_true", help="Emit JSON summary.")
    parser.add_argument("--install-requested", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def text(value: Any) -> str:
    return "" if value is None else str(value)


def boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def load_spec(path: Path) -> dict[str, Any]:
    payload = load_yaml_or_json(path.read_text(encoding="utf-8"), source=str(path))
    if not isinstance(payload, dict):
        raise SystemExit(f"ERROR: {path} must parse to a mapping.")
    return payload


def java_major(value: Any) -> int | None:
    raw = text(value).strip()
    match = re.search(r"\d+", raw)
    if not match:
        return None
    return int(match.group(0))


def normalize_role(value: Any) -> str:
    raw = text(value).strip().lower().replace(" ", "-")
    return ROLE_ALIASES.get(raw, raw)


def install_targets(spec: dict[str, Any]) -> set[str]:
    topology = as_dict(spec.get("topology"))
    install = as_dict(spec.get("install"))
    values = []
    values.extend(as_list(topology.get("install_targets")))
    values.extend(as_list(topology.get("install_target")))
    values.extend(as_list(install.get("targets")))
    return {normalize_role(value) for value in values if text(value).strip()}


def driver_id(driver: Any) -> str:
    if isinstance(driver, dict):
        return text(driver.get("splunkbase_id") or driver.get("id")).strip()
    return ""


def driver_name(driver: Any) -> str:
    if isinstance(driver, dict):
        return text(driver.get("name") or driver.get("database") or driver.get("splunkbase_id")).strip()
    return text(driver).strip()


def selected_driver_ids(spec: dict[str, Any]) -> list[str]:
    install = as_dict(spec.get("install"))
    ids: list[str] = []
    for value in as_list(install.get("driver_app_ids")):
        if text(value).strip():
            ids.append(text(value).strip())
    for driver in as_list(spec.get("drivers")):
        did = driver_id(driver)
        if did:
            ids.append(did)
    unique: list[str] = []
    for did in ids:
        if did not in unique:
            unique.append(did)
    return unique


def collect_install_ids(spec: dict[str, Any]) -> list[str]:
    ids = [APP_ID]
    for did in selected_driver_ids(spec):
        if did not in ids:
            ids.append(did)
    return ids


def sensitive_key(key: str) -> bool:
    lowered = key.lower()
    allowed_exact = {
        "secret_policy",
        "secrets_provider",
        "secret_store",
        "cyberark_enabled",
        "vault_enabled",
    }
    if lowered in allowed_exact:
        return False
    allowed_suffixes = (
        "_file",
        "_path",
        "_ref",
        "_reference",
        "_name",
        "_id",
        "_url",
        "_mode",
        "_provider",
        "_enabled",
    )
    markers = ("password", "secret", "token", "api_key", "apikey", "private_key", "passphrase")
    return any(marker in lowered for marker in markers) and not lowered.endswith(allowed_suffixes)


def looks_like_jdbc_secret(value: str) -> bool:
    lowered = value.lower()
    if re.search(r"jdbc:[^\s]*//[^/@:]+:[^/@]+@", value):
        return True
    return any(marker in lowered for marker in ("password=", "passwd=", "pwd=", "secret=", "token="))


def scan_secrets(value: Any, path: str = "") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if sensitive_key(str(key)) and child not in (None, ""):
                findings.append(f"{child_path} contains a direct secret; use a *_file or *_ref field.")
            findings.extend(scan_secrets(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(scan_secrets(child, f"{path}[{index}]"))
    elif isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("$7$") or stripped.lower().startswith("encrypted:"):
            findings.append(f"{path} contains a non-portable DBX encrypted value; use a secret file or external reference.")
        if looks_like_jdbc_secret(stripped):
            findings.append(f"{path} appears to embed a secret in a JDBC string.")
    return findings


def validate_spec(spec: dict[str, Any], *, install_requested: bool = False) -> list[Issue]:
    issues: list[Issue] = []
    version = text(spec.get("version")).strip()
    if version != SPEC_VERSION:
        issues.append(Issue("error", f"version must be {SPEC_VERSION!r}."))

    unknown = sorted(set(spec) - SUPPORTED_SECTIONS)
    if unknown:
        issues.append(Issue("warning", f"Unknown top-level sections will be ignored: {', '.join(unknown)}."))

    platform = as_dict(spec.get("platform"))
    platform_type = text(platform.get("type") or "enterprise").strip().lower()
    topology = as_dict(spec.get("topology"))
    topology_mode = text(topology.get("mode") or platform_type or "single_sh").strip().lower()
    install = as_dict(spec.get("install"))
    java = as_dict(spec.get("java"))
    security = as_dict(spec.get("security"))
    ha = as_dict(spec.get("ha"))

    if platform_type not in {"enterprise", "cloud_victoria", "cloud_classic"}:
        issues.append(Issue("error", "platform.type must be enterprise, cloud_victoria, or cloud_classic."))
    if topology_mode not in VALID_TOPOLOGIES:
        issues.append(Issue("error", "topology.mode is not supported for DB Connect v1."))

    major = java_major(java.get("version"))
    if platform_type == "cloud_victoria":
        if major and major not in {8, 11, 17, 21}:
            issues.append(Issue("error", "cloud_victoria java.version must be splunk-managed/cloud-managed or the JRE major version reported by Splunk Cloud."))
        issues.append(Issue("warning", "Splunk Cloud Victoria JRE is Splunk-managed; validate Java through DB Connect setup and file a support ticket for JRE issues."))
    elif major not in {17, 21}:
        issues.append(Issue("error", "java.version must resolve to Java 17 or Java 21."))

    targets = install_targets(spec)
    blocked_targets = targets.intersection({"deployment-server", "indexer", "universal-forwarder"})
    if blocked_targets:
        issues.append(Issue("error", f"DB Connect cannot be installed on: {', '.join(sorted(blocked_targets))}."))
    if "shc-member" in targets:
        issues.append(Issue("error", "Do not target SHC members directly; use the SHC deployer."))

    if topology_mode == "shc" and not text(topology.get("shc_deployer")).strip():
        issues.append(Issue("error", "topology.shc_deployer is required for SHC DB Connect deployment."))

    if platform_type == "cloud_classic" and (boolish(install.get("install_apps")) or install_requested):
        issues.append(Issue("error", "Splunk Cloud Classic DB Connect self-service install is unsupported; use IDM, customer-managed HF, or Splunk Support."))

    if platform_type == "cloud_victoria":
        if "heavy-forwarder" in targets:
            issues.append(Issue("error", "Splunk Cloud Victoria DB Connect runs on Cloud search heads; model customer-managed heavy forwarders with platform.type enterprise."))
        allowlist = as_list(as_dict(spec.get("cloud_network")).get("outbound_allowlist"))
        if as_list(spec.get("connections")) and not allowlist:
            issues.append(Issue("error", "Splunk Cloud Victoria plans require cloud_network.outbound_allowlist entries for every database endpoint."))

    if boolish(security.get("dbx_object_mutation")) or boolish(spec.get("apply_dbx_objects")):
        issues.append(Issue("error", "Live DB Connect object mutation is out of scope for splunk-db-connect-setup/v1."))

    allow_archived = boolish(install.get("allow_archived_drivers"))
    for did in selected_driver_ids(spec):
        entry = DRIVER_CATALOG.get(did)
        if entry is None:
            issues.append(Issue("warning", f"Driver Splunkbase ID {did} is not in the supported DBX driver add-on catalog; render as custom/manual coverage."))
        elif entry["status"] == "archived" and not allow_archived:
            issues.append(Issue("error", f"Driver {did} ({entry['name']}) is archived and is not part of normal install coverage."))

    custom_drivers = [driver for driver in as_list(spec.get("drivers")) if isinstance(driver, dict) and text(driver.get("type")).lower() == "custom"]
    for driver in custom_drivers:
        database = text(driver.get("database") or driver.get("name")).strip().lower()
        if database and database not in CUSTOM_DRIVER_DATABASES:
            issues.append(Issue("warning", f"Custom driver {database!r} will be treated as unsupported JDBC-compatible coverage."))

    secret_findings = scan_secrets(spec)
    for finding in secret_findings:
        issues.append(Issue("error", finding))

    if boolish(security.get("fips_mode")):
        if boolish(install.get("install_apps")) or install_requested:
            issues.append(Issue("error", "FIPS DB Connect requires a manual fresh-install path; do not use the automated Splunkbase install handoff."))
        if not boolish(security.get("fips_fresh_install")):
            issues.append(Issue("error", "security.fips_fresh_install must be true when security.fips_mode is true."))

    if boolish(security.get("require_client_cert")):
        cert_ref = text(security.get("client_certificate_ref") or security.get("client_certificate_file")).strip()
        key_ref = text(security.get("client_private_key_ref") or security.get("client_private_key_file")).strip()
        if not cert_ref or not key_ref:
            issues.append(Issue("warning", "require_client_cert is enabled but client certificate and private-key references are incomplete."))

    if topology_mode == "heavy_forwarder_ha" or boolish(ha.get("enabled")):
        if not as_list(ha.get("etcd_endpoints")):
            issues.append(Issue("warning", "HF HA requested without ha.etcd_endpoints; rendered plan will require an etcd endpoint decision."))

    if not as_list(spec.get("identities")):
        issues.append(Issue("warning", "No identities declared; rendered DBX previews will include connection shells only."))
    if not as_list(spec.get("connections")):
        issues.append(Issue("warning", "No connections declared; validation assets will focus on platform readiness."))

    return issues


def fail_on_errors(issues: list[Issue]) -> None:
    errors = [issue for issue in issues if issue.severity == "error"]
    if errors:
        for issue in issues:
            print(f"{issue.severity.upper()}: {issue.message}", file=sys.stderr)
        raise SystemExit(2)


def q(value: str) -> str:
    return shlex.quote(value)


def write(path: Path, content: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    if executable:
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def md_list(items: list[str]) -> str:
    if not items:
        return "- None declared"
    return "\n".join(f"- {item}" for item in items)


def render_preflight_summary(spec: dict[str, Any], issues: list[Issue]) -> dict[str, Any]:
    platform = as_dict(spec.get("platform"))
    topology = as_dict(spec.get("topology"))
    return {
        "spec_version": text(spec.get("version")),
        "platform": text(platform.get("type") or "enterprise"),
        "topology": text(topology.get("mode") or "single_sh"),
        "install_ids": collect_install_ids(spec),
        "drivers": selected_driver_ids(spec),
        "issues": [issue.as_dict() for issue in issues],
    }


def render_readme(spec: dict[str, Any], issues: list[Issue]) -> str:
    platform = as_dict(spec.get("platform"))
    topology = as_dict(spec.get("topology"))
    install_ids = collect_install_ids(spec)
    warnings = [issue.message for issue in issues if issue.severity == "warning"]
    return f"""# Splunk DB Connect Rendered Plan

App: `{APP_NAME}` (Splunkbase `{APP_ID}`), audited `{APP_VERSION}` on {APP_DATE}.

Platform: `{text(platform.get("type") or "enterprise")}`

Topology: `{text(topology.get("mode") or "single_sh")}`

Install handoff IDs:

{md_list([f"`{app_id}`" for app_id in install_ids])}

Warnings:

{md_list(warnings)}

## Operator Order

1. Review `security/guardrails.md`.
2. Run `preflight.sh` on every DBX runtime host.
3. Install apps only through `install/install-apps.sh` after explicit approval.
4. Place JDBC drivers on every DBX instance.
5. Review the `dbx/*.preview` files and apply DBX objects manually.
6. Run `validation/rest-checks.sh`, `validation/btool-checks.sh`, and the SPL in `validation/validation.spl`.

This packet does not contain secret values and does not mutate DB Connect objects.
"""


def render_install_script(spec: dict[str, Any]) -> str:
    ids = collect_install_ids(spec)
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        f'PROJECT_ROOT="${{PROJECT_ROOT:-{q(str(REPO_ROOT))}}}"',
        'INSTALLER="${PROJECT_ROOT}/skills/splunk-app-install/scripts/install_app.sh"',
        'if [[ ! -x "${INSTALLER}" ]]; then',
        '  echo "ERROR: splunk-app-install installer not found or not executable: ${INSTALLER}" >&2',
        "  exit 1",
        "fi",
        "",
    ]
    for app_id in ids:
        if app_id == "6759":
            lines.append('echo "SKIP: archived InfluxDB driver 6759 is not installed by the normal workflow."')
            continue
        if app_id != APP_ID:
            entry = DRIVER_CATALOG.get(app_id)
            if entry is None or entry.get("status") != "supported":
                lines.append(f'echo "SKIP: driver app {app_id} is not in the supported DBX JDBC add-on install catalog."')
                continue
        lines.extend(
            [
                f'echo "Installing Splunkbase app {app_id} through splunk-app-install"',
                f'bash "${{INSTALLER}}" --source splunkbase --app-id {q(app_id)} --update',
                "",
            ]
        )
    return "\n".join(lines)


def render_java_preflight(spec: dict[str, Any]) -> str:
    platform = as_dict(spec.get("platform"))
    platform_type = text(platform.get("type") or "enterprise").strip().lower()
    if platform_type == "cloud_victoria":
        return """#!/usr/bin/env bash
set -euo pipefail

echo "INFO: Splunk Cloud Victoria JRE is managed by Splunk on the Cloud search head."
echo "INFO: Validate it in DB Connect setup or Configuration > Settings > General."
echo "INFO: File a Splunk Support ticket if DB Connect reports Cloud JRE issues."
"""

    java = as_dict(spec.get("java"))
    java_home = text(java.get("java_home") or "")
    expected = java_major(java.get("version")) or 17
    return f"""#!/usr/bin/env bash
set -euo pipefail

EXPECTED_JAVA_MAJOR="{expected}"
JAVA_HOME_EXPECTED={q(java_home)}

if [[ -n "${{JAVA_HOME_EXPECTED}}" && ! -x "${{JAVA_HOME_EXPECTED}}/bin/java" ]]; then
  echo "ERROR: configured JAVA_HOME does not contain bin/java: ${{JAVA_HOME_EXPECTED}}" >&2
  exit 1
fi

JAVA_BIN="${{JAVA_HOME_EXPECTED:+${{JAVA_HOME_EXPECTED}}/bin/}}java"
if ! command -v "${{JAVA_BIN}}" >/dev/null 2>&1 && [[ ! -x "${{JAVA_BIN}}" ]]; then
  echo "ERROR: java executable not found. Install Java 17 or 21 and configure JAVA_HOME." >&2
  exit 1
fi

version_output="$("${{JAVA_BIN}}" -version 2>&1 | head -n 1)"
major="$(printf '%s\\n' "${{version_output}}" | sed -E 's/.*version "([0-9]+).*/\\1/')"
if [[ "${{major}}" != "17" && "${{major}}" != "21" ]]; then
  echo "ERROR: DB Connect requires Java 17 or 21; detected: ${{version_output}}" >&2
  exit 1
fi
if [[ "${{major}}" != "${{EXPECTED_JAVA_MAJOR}}" ]]; then
  echo "WARNING: spec requested Java ${{EXPECTED_JAVA_MAJOR}}, detected ${{major}}."
fi
echo "OK: ${{version_output}}"
"""


def render_preflight_script(spec: dict[str, Any]) -> str:
    platform = as_dict(spec.get("platform"))
    platform_type = text(platform.get("type") or "enterprise").strip().lower()
    if platform_type == "cloud_victoria":
        return """#!/usr/bin/env bash
set -euo pipefail

echo "INFO: Splunk Cloud Victoria runs DB Connect on Cloud search heads with a Splunk-managed JRE."
echo "INFO: Validate JRE state in DB Connect setup or Configuration > Settings > General."
echo "INFO: Use Splunk Support for Cloud JRE issues; run local Java checks only on customer-managed Enterprise/HF runtimes."
echo "Review drivers/driver-inventory.json and cloud/outbound-allowlist.md before enabling DBX connections."
"""

    return """#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

bash "${SCRIPT_DIR}/java/java-preflight.sh"

if [[ -n "${SPLUNK_HOME:-}" ]]; then
  if [[ ! -d "${SPLUNK_HOME}/etc/apps/splunk_app_db_connect" ]]; then
    echo "WARNING: splunk_app_db_connect is not present under $SPLUNK_HOME/etc/apps."
  else
    for rel in splunk_app_db_connect splunk_app_db_connect/local splunk_app_db_connect/log splunk_app_db_connect/checkpoint; do
      path="${SPLUNK_HOME}/etc/apps/${rel}"
      [[ -e "${path}" ]] && [[ -r "${path}" ]] && [[ -w "${path}" ]] && echo "OK: ${path} is readable and writable."
    done
    if find "${SPLUNK_HOME}/etc/apps/splunk_app_db_connect" -maxdepth 2 -type f ! -readable -print -quit 2>/dev/null | grep -q .; then
      echo "WARNING: Some DB Connect files are not readable by the current user."
    fi
  fi
  if [[ -d "${SPLUNK_HOME}/var/lib/splunk/kvstore" ]]; then
    echo "OK: KV Store directory exists."
  else
    echo "WARNING: KV Store directory not found; verify KV Store status before enabling DBX."
  fi
else
  echo "INFO: SPLUNK_HOME not set; skipping local app and KV Store filesystem checks."
fi

echo "Review drivers/driver-inventory.json and ensure every DBX runtime host has the same JDBC driver set."
"""


def render_custom_driver_readme() -> str:
    return """# Custom JDBC Driver App Skeleton

Use this skeleton only for reviewed JDBC drivers that are not covered by a
supported DBX driver add-on or that require a different vendor driver version.

Expected package layout:

```text
Splunk_JDBC_<driver-name>/
  default/app.conf
  default/db_connection_types.conf
  lib/dbxdrivers/<driver-name>.jar
  lib/dbxdrivers/<driver-name>-libs/
```

Put the primary JDBC JAR under `lib/dbxdrivers/`. Put dependencies under a
driver-specific `lib/dbxdrivers/<driver-name>-libs/` directory. For Splunk
Cloud, package the app as `Splunk_JDBC_<driver-name>.tgz` and submit it through
the supported app install workflow.
"""


def render_custom_driver_app_conf() -> str:
    return """[install]
state = enabled
build = 1.0.0

[launcher]
author = <operator>
description = Add-on for custom DB Connect JDBC drivers
version = 1.0.0

[ui]
is_visible = false
label = DB Connect Custom JDBC Drivers

[package]
id = Splunk_JDBC_custom
check_for_updates = false

[id]
name = Splunk_JDBC_custom
version = 1.0.0

[triggers]
reload.db_connection_types = simple
"""


def render_custom_connection_types() -> str:
    return """# Optional default/db_connection_types.conf custom connection-type template.
# Uncomment and replace every placeholder before packaging a custom driver app.
#
# [<connection-name>]
# displayName = <display-name>
# serviceClass = com.splunk.dbx2.DefaultDBX2JDBC
# jdbcDriverClass = <driver-class>
# jdbcUrlFormat = <jdbc-url-format>
# database_engine = <database-engine>
"""


def conf_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    return text(value)


def render_stanzas(items: list[Any], *, kind: str) -> str:
    lines = [
        f"# Preview only. Review and apply {kind} through DB Connect UI or a future supported mutator.",
        "# Secret values are intentionally omitted.",
        "",
    ]
    for item in items:
        if not isinstance(item, dict):
            continue
        name = text(item.get("name") or item.get("lookup_name") or "unnamed")
        lines.append(f"[{name}]")
        for key in sorted(item):
            if key in {"password", "secret", "token", "api_key", "private_key"}:
                continue
            if key.endswith("_file") or key.endswith("_ref"):
                lines.append(f"{key} = <local-secret-reference>")
                continue
            value = item[key]
            if isinstance(value, str) and "\n" in value:
                lines.append(f"{key} = <<REVIEW_SQL")
                lines.append(value.rstrip())
                lines.append("REVIEW_SQL")
            else:
                lines.append(f"{key} = {conf_value(value)}")
        lines.append("")
    return "\n".join(lines)


def render_settings(spec: dict[str, Any]) -> str:
    java = as_dict(spec.get("java"))
    settings = as_dict(spec.get("settings"))
    lines = [
        "# DB Connect settings preview only.",
        "[dbx_settings]",
        f"java_home = {text(java.get('java_home') or '<set-on-host>')}",
        f"java_version = {text(java.get('version') or '<17-or-21>')}",
    ]
    for key in sorted(settings):
        lines.append(f"{key} = {conf_value(settings[key])}")
    return "\n".join(lines)


def render_indexes(spec: dict[str, Any]) -> str:
    lines = ["# indexes.conf preview for DB Connect data paths.", ""]
    for item in as_list(spec.get("indexes")):
        if not isinstance(item, dict):
            continue
        name = text(item.get("name")).strip()
        if not name:
            continue
        lines.append(f"[{name}]")
        datatype = text(item.get("datatype") or "event")
        lines.append(f"datatype = {datatype}")
        if item.get("retention_days"):
            lines.append(f"frozenTimePeriodInSecs = {int(item['retention_days']) * 86400}")
        lines.append("")
    if len(lines) == 2:
        lines.append("# No indexes declared.")
    return "\n".join(lines)


def render_hec_handoff(spec: dict[str, Any]) -> str:
    hec = as_dict(spec.get("hec"))
    token_name = text(hec.get("token_name") or "dbx_export")
    allowed = ",".join(text(v) for v in as_list(hec.get("allowed_indexes")) if text(v))
    if not allowed:
        allowed = ",".join(text(item.get("name")) for item in as_list(spec.get("indexes")) if isinstance(item, dict) and item.get("name"))
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        f'PROJECT_ROOT="${{PROJECT_ROOT:-{q(str(REPO_ROOT))}}}"',
        'exec bash "${PROJECT_ROOT}/skills/splunk-hec-service-setup/scripts/setup.sh" \\',
        "  --phase render \\",
        f"  --token-name {q(token_name)} \\",
        f"  --allowed-indexes {q(allowed or 'main')}",
    ]
    return "\n".join(lines)


def render_validation_spl(spec: dict[str, Any]) -> str:
    sourcetypes = [text(v) for v in as_list(as_dict(spec.get("validation")).get("expected_sourcetypes")) if text(v)]
    indexes = [text(item.get("name")) for item in as_list(spec.get("indexes")) if isinstance(item, dict) and item.get("name")]
    searches = [
        '| rest /servicesNS/nobody/splunk_app_db_connect/db_connect/dbxserverstatus | table title status message',
        '| rest /servicesNS/nobody/splunk_app_db_connect/db_connect/connections | table title disabled database',
        '| rest /servicesNS/nobody/splunk_app_db_connect/db_connect/inputs | table title disabled interval index sourcetype',
    ]
    for index in indexes:
        searches.append(f"search index={index} earliest=-24h | stats count by sourcetype")
    for sourcetype in sourcetypes:
        searches.append(f'search sourcetype="{sourcetype}" earliest=-24h | stats count latest(_time) as latest by host')
    return "\n\n".join(searches) + "\n"


def render_rest_checks() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail

: "${SPLUNK_URI:=https://localhost:8089}"
: "${SPLUNK_USERNAME:=admin}"

if [[ -z "${SPLUNK_PASSWORD:-}" ]]; then
  echo "INFO: SPLUNK_PASSWORD not set; export it or use this as a command checklist."
  exit 0
fi

curl -sk -u "${SPLUNK_USERNAME}:${SPLUNK_PASSWORD}" "${SPLUNK_URI}/services/apps/local/splunk_app_db_connect?output_mode=json" >/dev/null
curl -sk -u "${SPLUNK_USERNAME}:${SPLUNK_PASSWORD}" "${SPLUNK_URI}/servicesNS/nobody/splunk_app_db_connect/db_connect/dbxserverstatus?output_mode=json" >/dev/null
echo "OK: DB Connect REST probes completed."
"""


def render_btool_checks() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail

: "${SPLUNK_HOME:=/opt/splunk}"
if [[ ! -x "${SPLUNK_HOME}/bin/splunk" ]]; then
  echo "INFO: ${SPLUNK_HOME}/bin/splunk not found; use these btool commands on a DBX runtime host."
  echo "  splunk btool db_connections list --debug"
  echo "  splunk btool db_inputs list --debug"
  echo "  splunk btool db_outputs list --debug"
  exit 0
fi

"${SPLUNK_HOME}/bin/splunk" btool db_connections list --debug
"${SPLUNK_HOME}/bin/splunk" btool db_inputs list --debug
"${SPLUNK_HOME}/bin/splunk" btool db_outputs list --debug
"""


def render_topology_shc(spec: dict[str, Any]) -> str:
    topology = as_dict(spec.get("topology"))
    members = [text(v) for v in as_list(topology.get("shc_members")) if text(v)]
    return f"""# SHC Deployer DB Connect Plan

Use the SHC deployer for DB Connect app and driver add-on placement.

Deployer: `{text(topology.get("shc_deployer") or '<required-for-shc>')}`

Members:

{md_list([f"`{member}`" for member in members])}

## Sequence

1. Stage `splunk_app_db_connect` and all JDBC driver add-ons on the deployer.
2. Put DBX local configuration in the deployer app bundle only after review.
3. Push the deployer bundle.
4. Run a rolling restart if DBX or driver placement requires it.
5. Confirm every Enterprise/customer-managed member has Java 17 or 21 and the
   same driver inventory. For Cloud Victoria SHC, validate the Splunk-managed
   JRE through DB Connect setup and route JRE issues to Splunk Support.
6. Validate KV Store and DBX task server health before enabling inputs.
"""


def render_hf_ha(spec: dict[str, Any]) -> str:
    ha = as_dict(spec.get("ha"))
    endpoints = [text(v) for v in as_list(ha.get("etcd_endpoints")) if text(v)]
    return f"""# Heavy Forwarder HA And etcd Plan

HF HA enabled: `{boolish(ha.get("enabled"))}`

Mode: `{text(ha.get("mode") or 'none')}`

etcd endpoints:

{md_list([f"`{endpoint}`" for endpoint in endpoints])}

## Requirements

- Run DB Connect only on full Splunk Enterprise heavy forwarders.
- Use at least three DB Connect instances and a three-node etcd cluster for
  active/active HA planning.
- Keep Java, DB Connect, driver add-ons, identities, and connections aligned on
  every HF; JDBC add-ons are not replicated by DB Connect HA.
- Use the DB Connect documented etcd-backed HA pattern when active/active
  scheduling is required.
- Open DB Connect management TCP/9998 and etcd TCP/2379 and TCP/2380 between
  the HA components, with etcd authentication and TLS where possible.
- Validate scheduler ownership and checkpoint behavior before enabling
  production inputs.
"""


def render_cloud_allowlist(spec: dict[str, Any]) -> str:
    rows = []
    for item in as_list(as_dict(spec.get("cloud_network")).get("outbound_allowlist")):
        if not isinstance(item, dict):
            continue
        rows.append(f"- `{text(item.get('host'))}:{text(item.get('port'))}` over `{text(item.get('protocol') or 'tcp')}`")
    return f"""# Splunk Cloud Network Plan

Splunk Cloud Victoria DB Connect runs on the Cloud search head and requires ACS
to open outbound database reachability before identities, connections, or inputs
can work. Classic Cloud self-service DBX installs are not supported by this
skill; route Classic through IDM, customer-managed heavy forwarder, or Splunk
Support.

Outbound targets:

{md_list(rows)}
"""


def render_operations_plan(spec: dict[str, Any]) -> str:
    return f"""# DB Connect Operations Plan

## Health

- Run Monitoring Console health checks for DB Connect connection configuration,
  data lab configuration, JDBC driver installation, file permissions, JVM
  installation, Java server configuration, and Kerberos environment.
- Confirm SQL Explorer, Input, Output, Lookup, and Query Explorer workflows can
  open the expected connection before enabling scheduled writes or reads.

## Backup And Restore

- Back up `splunk_app_db_connect/local`, DBX keystore/certificate artifacts,
  rendered DBX previews, and SHC deployer source bundles.
- Capture KV Store state and DBX checkpoint state before upgrades, FIPS
  rebuilds, driver changes, and HA topology changes.
- Restore only after validating Java, driver parity, KV Store health, and
  identity/connection dependency resolution.

## Upgrade And Downgrade

- Latest audited DB Connect version: `{APP_VERSION}` ({APP_DATE}).
- Do not upgrade directly from versions earlier than `3.18.5` to `4.x`; use the
  documented intermediate path.
- For `2.x`, plan `3.9.0` then `3.18.5` then `4.x`.
- For `3.x`, plan `3.18.5` then `4.x`.
- For downgrades below `3.14.0`, review `dbx-migration.conf` encryption
  downgrade state before restart.
"""


def render_federated_search_plan() -> str:
    return """# DB Connect Over Federated Search Plan

DB Connect can be exposed through Federated Search by mapping to a saved search
that runs `dbxquery`.

## Handoff

- Create and validate the DB Connect connection on the DBX runtime search head.
- Create a saved search that uses `dbxquery` and returns only reviewed fields.
- Grant the Federated Search service user access to the saved search.
- Create a federated index that points to the saved search.
- Query the federated index with `| from` after validating row limits,
  timeouts, and database load.
"""


def render_auth_handoffs(spec: dict[str, Any]) -> str:
    security = as_dict(spec.get("security"))
    return f"""# DB Connect Auth Handoffs

CyberArk enabled: `{boolish(security.get("cyberark_enabled"))}`

Vault enabled: `{boolish(security.get("vault_enabled"))}`

## SQL Server

- Validate SQL authentication, Windows authentication, Kerberos, and Microsoft
  Entra prerequisites before enabling scheduled inputs.
- Keep Kerberos keytabs, JAAS files, SPNs, and domain policy details outside
  rendered packets; reference them through file paths or external secret
  records only.
- For stored procedures, use the Microsoft JDBC driver, return one result set,
  and avoid `USE [database]` in procedure definitions.

## External Secret Stores

- CyberArk and HashiCorp Vault are handoff integrations in v1. Render specs may
  contain references such as `vault_ref` or CyberArk object identifiers, but
  never resolved secret values.
- Validate secret retrieval on each DBX runtime host before enabling inputs,
  lookups, or outputs.
"""


def render_fips_plan(spec: dict[str, Any]) -> str:
    security = as_dict(spec.get("security"))
    return f"""# DB Connect FIPS Plan

FIPS requested: `{boolish(security.get("fips_mode"))}`

- DB Connect FIPS mode requires a fresh installation path.
- Do not use self-service app installation or the automated Splunkbase install
  handoff for FIPS DB Connect.
- Set `fipsEnabled: true` for the task server and dbxquery server configuration,
  or set `SPLUNK_DBX_FIPS_ENABLED=true` through the service environment.
- Use `PKCS12` keystore/truststore handling and remove non-FIPS Bouncy Castle
  libraries if present.
- Validate this with `splunk-platform-pki-setup` before production use.
"""


def render_client_cert_plan(spec: dict[str, Any]) -> str:
    security = as_dict(spec.get("security"))
    return f"""# DB Connect Client Certificate Plan

require_client_cert requested: `{boolish(security.get("require_client_cert"))}`

- Convert private keys to PKCS8 format before loading them into DB Connect.
- Load the client certificate and private key through DB Connect
  Configuration > Settings > Keystore.
- Keep certificate and private-key material outside rendered packets; use
  `client_certificate_ref` and `client_private_key_ref` or chmod-600 local files
  in the working spec.
- Coordinate CA, truststore, and rotation work with `splunk-platform-pki-setup`.
"""


def render_security(spec: dict[str, Any], issues: list[Issue]) -> str:
    warnings = [issue.message for issue in issues if issue.severity == "warning"]
    return f"""# DB Connect Security Guardrails

- Secrets must be file-based or external references.
- JDBC URLs must not contain usernames, passwords, tokens, or wallet passphrases.
- DBX encrypted local identity values are local artifacts and are not portable input.
- `requireClientCert=true` requires certificate files to be distributed outside
  this rendered packet and protected by filesystem permissions.
- FIPS and TLS policy must be validated on every DBX runtime host.
- CyberArk and HashiCorp Vault references are rendered as handoffs only.
- FIPS mode requires a fresh manual install path and PKCS12 keystore/truststore
  handling.

Warnings:

{md_list(warnings)}
"""


def render_troubleshooting() -> str:
    return """# DB Connect Troubleshooting Runbook

## Java

- Confirm Java 17 or 21 with `java -version`.
- Confirm DBX sees the intended `JAVA_HOME`.
- Review DBX task server logs for heap, TLS, and classpath failures.

## JDBC Drivers

- Confirm the same driver add-ons or custom driver apps exist on every DBX host.
- For Splunk Cloud custom drivers, package the JAR as an app and use the
  supported Cloud app workflow.
- Do not mix archived driver add-ons into production plans.

## KV Store

- Confirm KV Store is green before configuring DBX identities and connections.
- On SHC, validate KV Store replication on every member before enabling inputs.

## Auth And TLS

- Use file-backed secrets or CyberArk/Vault references.
- For SQL Server, validate SQL auth, Windows/Kerberos, or Entra prerequisites
  before enabling scheduled inputs.
- For Oracle wallets and client certificates, validate file ownership and
  `requireClientCert=true` behavior on every DBX runtime host.

## Data Path

- Use SQL Explorer for query validation.
- Use `dbxquery` for read-path checks.
- Do not use `dbxquery` for INSERT or UPDATE operations; use `dbxoutput` for
  database writes after explicit review.
- Use `dbxoutput` only after reviewing write permissions and target tables.
- Use `dbxlookup` only after lookup preview and KV Store health are confirmed.

## SQL Server Stored Procedures

- Use the Microsoft JDBC driver instead of jTDS for stored procedure inputs.
- Avoid `USE [database]` in stored procedure definitions because DB Connect
  must fetch query metadata.
- For rising-mode inputs, pass the rising column as a parameter and call the
  procedure with `EXEC ... @column = ?`.
"""


def render_driver_inventory(spec: dict[str, Any]) -> dict[str, Any]:
    selected = []
    for did in selected_driver_ids(spec):
        entry = dict(DRIVER_CATALOG.get(did, {"name": did, "status": "custom/manual"}))
        entry["splunkbase_id"] = did
        selected.append(entry)
    custom = []
    for driver in as_list(spec.get("drivers")):
        if isinstance(driver, dict) and text(driver.get("type")).lower() == "custom":
            custom.append(driver)
    return {
        "db_connect": {
            "splunkbase_id": APP_ID,
            "app_name": APP_NAME,
            "latest_verified_version": APP_VERSION,
            "latest_verified_date": APP_DATE,
        },
        "selected_driver_addons": selected,
        "supported_driver_catalog": DRIVER_CATALOG,
        "custom_driver_databases": CUSTOM_DRIVER_DATABASES,
        "custom_drivers_requested": custom,
    }


def render_coverage(spec: dict[str, Any], issues: list[Issue]) -> dict[str, Any]:
    return {
        "skill": "splunk-db-connect-setup",
        "spec_version": SPEC_VERSION,
        "coverage": {
            "topologies": sorted(VALID_TOPOLOGIES),
            "features": [
                "settings",
                "java-diagnostics",
                "drivers",
                "cloud-custom-driver-lib-dbxdrivers",
                "custom-db-connection-types",
                "databricks-data-source",
                "identities",
                "connections",
                "inputs",
                "outputs",
                "lookups",
                "sql-explorer",
                "query-explorer-open-connection",
                "dbxquery",
                "dbxoutput",
                "dbxlookup",
                "sql-server-stored-procedures",
                "sql-server-windows-kerberos-entra",
                "sql-server-microsoft-jdbc-driver",
                "cyberark",
                "hashicorp-vault",
                "external-secret-store-handoffs",
                "fips",
                "fips-fresh-install-manual",
                "requireClientCert=true",
                "client-cert-pkcs8-keystore",
                "health-dashboards",
                "monitoring-console",
                "monitoring-console-health-checks",
                "backup-restore",
                "upgrade-downgrade",
                "dbx-2x-3x-migration",
                "db-connect-over-federated-search",
                "ha-checkpoint-sync",
                "ha-leader-election",
                "table-level-filtering-search",
                "automatic-jdbc-version-detection",
                "jvm-options-multiline",
            ],
            "delegates": ["splunk-app-install", "splunk-hec-service-setup", "splunk-platform-pki-setup"],
        },
        "issues": [issue.as_dict() for issue in issues],
    }


def render_assets(spec: dict[str, Any], output_dir: Path, issues: list[Issue]) -> Path:
    root = output_dir / OUTPUT_SUBDIR
    files: list[Path] = []

    def emit(rel: str, content: str, *, executable: bool = False) -> None:
        path = root / rel
        write(path, content, executable=executable)
        files.append(path)

    emit("README.md", render_readme(spec, issues))
    emit("preflight.sh", render_preflight_script(spec), executable=True)
    emit("install/install-apps.sh", render_install_script(spec), executable=True)
    emit("java/java-preflight.sh", render_java_preflight(spec), executable=True)
    emit("drivers/driver-inventory.json", json.dumps(render_driver_inventory(spec), indent=2, sort_keys=True))
    emit("drivers/custom-driver-app/README.md", render_custom_driver_readme())
    emit("drivers/custom-driver-app/default/app.conf", render_custom_driver_app_conf())
    emit("drivers/custom-driver-app/default/db_connection_types.conf", render_custom_connection_types())
    emit("drivers/custom-driver-app/lib/dbxdrivers/README.md", "Place reviewed JDBC driver JARs here. Use a driver-specific `<driver-name>-libs/` child directory for dependencies.\n")
    emit("drivers/custom-driver-app/metadata/default.meta", "[]\naccess = read : [ * ], write : [ admin ]\nexport = system\n")
    emit("topology/shc-deployer.md", render_topology_shc(spec))
    emit("topology/hf-ha-etcd-plan.md", render_hf_ha(spec))
    emit("cloud/outbound-allowlist.md", render_cloud_allowlist(spec))
    emit("operations/upgrade-backup-health.md", render_operations_plan(spec))
    emit("operations/federated-search.md", render_federated_search_plan())
    emit("indexes/indexes.conf", render_indexes(spec))
    emit("hec/readiness.md", "# HEC Readiness\n\nHEC is optional for DB Connect. When enabled, delegate token creation to `splunk-hec-service-setup` and keep token values in local files.\n")
    emit("hec/handoff-hec-service.sh", render_hec_handoff(spec), executable=True)
    emit("dbx/dbx_settings.conf.preview", render_settings(spec))
    emit("dbx/db_identities.conf.preview", render_stanzas(as_list(spec.get("identities")), kind="identities"))
    emit("dbx/db_connections.conf.preview", render_stanzas(as_list(spec.get("connections")), kind="connections"))
    emit("dbx/db_inputs.conf.preview", render_stanzas(as_list(spec.get("inputs")), kind="inputs"))
    emit("dbx/db_outputs.conf.preview", render_stanzas(as_list(spec.get("outputs")), kind="outputs"))
    emit("dbx/db_lookups.conf.preview", render_stanzas(as_list(spec.get("lookups")), kind="lookups"))
    emit("validation/validation.spl", render_validation_spl(spec))
    emit("validation/rest-checks.sh", render_rest_checks(), executable=True)
    emit("validation/btool-checks.sh", render_btool_checks(), executable=True)
    emit("security/guardrails.md", render_security(spec, issues))
    emit("security/auth-handoffs.md", render_auth_handoffs(spec))
    emit("security/fips-plan.md", render_fips_plan(spec))
    emit("security/client-cert-plan.md", render_client_cert_plan(spec))
    emit("troubleshooting/runbook.md", render_troubleshooting())
    emit("coverage.json", json.dumps(render_coverage(spec, issues), indent=2, sort_keys=True))

    metadata = render_preflight_summary(spec, issues)
    metadata.update(
        {
            "app": {
                "splunkbase_id": APP_ID,
                "app_name": APP_NAME,
                "latest_verified_version": APP_VERSION,
                "latest_verified_date": APP_DATE,
            },
            "output_files": sorted(str(path.relative_to(root)) for path in files),
        }
    )
    emit("metadata.json", json.dumps(metadata, indent=2, sort_keys=True))
    emit("metadata.yaml", dump_yaml(metadata, sort_keys=True))
    return root


def main() -> int:
    args = parse_args()
    spec_path = Path(args.spec).expanduser().resolve()
    spec = load_spec(spec_path)
    issues = validate_spec(spec, install_requested=args.install_requested)
    fail_on_errors(issues)
    summary = render_preflight_summary(spec, issues)

    if args.preflight:
        if args.json:
            print(json.dumps(summary, indent=2, sort_keys=True))
        else:
            print(f"Spec: {spec_path}")
            print(f"Version: {summary['spec_version']}")
            print(f"Platform: {summary['platform']}")
            print(f"Topology: {summary['topology']}")
            print("Install IDs: " + ", ".join(summary["install_ids"]))
            for issue in issues:
                print(f"{issue.severity.upper()}: {issue.message}")
        return 0

    root = render_assets(spec, Path(args.output_dir).expanduser().resolve(), issues)
    if args.json:
        summary["output_dir"] = str(root)
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(f"Rendered Splunk DB Connect assets to {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

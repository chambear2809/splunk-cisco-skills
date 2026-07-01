#!/usr/bin/env python3
"""Render Splunk Cloud ACS admin assets."""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import shlex
import stat
from pathlib import Path


FEATURES = (
    "acs",
    "search-api",
    "hec",
    "s2s",
    "search-ui",
    "idm-api",
    "idm-ui",
)

ADMIN_MODULES = (
    "allowlists",
    "indexes",
    "hec-tokens",
    "users",
    "roles",
    "capabilities",
    "app-permissions",
    "private-connectivity",
    "outbound-ports",
    "ddss",
    "limits",
    "maintenance-windows",
    "restarts",
    "apps",
    "tokens",
    "deployment",
    "license",
    "observability",
)

READ_ONLY_MODULES = (
    "capabilities",
    "apps",
    "tokens",
    "deployment",
    "license",
    "observability",
)

IDENTIFIER_RE = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"
ACCOUNT_ID_RE = r"^[0-9]{12}$"

MODULE_COMMAND_GROUPS = {
    "allowlists": ("ip-allowlist", "ip-allowlist-v6"),
    "indexes": ("indexes",),
    "hec-tokens": ("hec-token",),
    "users": ("users",),
    "roles": ("roles",),
    "capabilities": ("capabilities",),
    "app-permissions": ("permissions",),
    "private-connectivity": (),
    "outbound-ports": ("outbound-port", "outbound-port-v6"),
    "ddss": ("indexes",),
    "limits": ("limits",),
    "maintenance-windows": ("maintenance-windows",),
    "restarts": ("restart",),
    "apps": ("apps",),
    "tokens": ("token",),
    "deployment": ("deployment",),
    "license": ("license",),
    "observability": ("observability",),
}

OPERATION_MODULES = {
    "indexes": "indexes",
    "hec_tokens": "hec-tokens",
    "roles": "roles",
    "users": "users",
    "app_permissions": "app-permissions",
    "outbound_ports": "outbound-ports",
    "ddss_self_storage_locations": "ddss",
    "limits": "limits",
    "maintenance_windows": "maintenance-windows",
    "private_connectivity": "private-connectivity",
    "restarts": "restarts",
}

# Per Splunk doc: AWS groups share a 230-subnet cap across the features below.
AWS_GROUPS = {
    "search-head": ("search-api", "search-ui"),
    "indexer": ("hec", "s2s"),
    "idm": ("idm-api", "idm-ui"),
    "single-instance": ("search-api", "search-ui", "hec", "s2s"),
}
AWS_PER_FEATURE_CAP = 200
AWS_GROUP_CAP = 230
GCP_PER_FEATURE_CAP = 200

# Per Splunk doc: these features are open by default; everything else is
# closed by default. PCI/HIPAA stacks override `search-ui` to closed but the
# skill cannot detect compliance tier from public APIs; the README documents
# the exception.
DEFAULT_OPEN_FEATURES = ("acs", "hec", "s2s", "search-ui", "idm-api", "idm-ui")
DEFAULT_CLOSED_FEATURES = ("search-api",)

# Splunk Web features that depend on ACS — used by lock-out warning.
ACS_DEPENDENT_FEATURES = (
    "IP allowlist (IPv4 and IPv6)",
    "Federated Search",
    "Maintenance Windows (CMC app)",
    "Observability APIs",
    "Limits",
)

GENERATED_FILES = {
    "README.md",
    "admin-commands.sh",
    "apply-admin-plan.sh",
    "metadata.json",
    "plan.json",
    "preflight.sh",
    "apply-ipv4.sh",
    "apply-ipv6.sh",
    "inventory.sh",
    "private-connectivity-rest.sh",
    "wait-for-ready.sh",
    "audit.sh",
    "terraform-snippets.tf",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render ACS admin assets.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--modules",
        default=",".join(ADMIN_MODULES),
        help=f"CSV subset of ACS admin modules. Allowed: {', '.join(ADMIN_MODULES)}",
    )
    parser.add_argument(
        "--admin-plan-file",
        default="",
        help="Optional JSON file with broader ACS admin operations to render.",
    )
    parser.add_argument("--features", default="search-api,s2s,hec")
    parser.add_argument("--cloud-provider", choices=("aws", "gcp"), default="aws")
    parser.add_argument("--target-search-head", default="")
    parser.add_argument("--allow-acs-lockout", choices=("true", "false"), default="false")
    parser.add_argument("--strict-drift", choices=("true", "false"), default="true")
    parser.add_argument("--emit-terraform", choices=("true", "false"), default="false")
    parser.add_argument("--force", choices=("true", "false"), default="false")
    for feature in FEATURES:
        parser.add_argument(f"--{feature}-subnets", default="", dest=f"{feature.replace('-', '_')}_subnets")
        parser.add_argument(f"--{feature}-subnets-v6", default="", dest=f"{feature.replace('-', '_')}_subnets_v6")
    # Operator IPs for the ACS lock-out guard. CSV of IP/CIDR. When empty,
    # the rendered preflight does outbound public-IP discovery and fails
    # closed if discovery returns nothing while the `acs` feature is in the
    # plan and lock-out is not explicitly allowed.
    parser.add_argument("--operator-ips", default="", help="CSV of IPv4 IP/CIDR for the lock-out guard")
    parser.add_argument("--operator-ips-v6", default="", help="CSV of IPv6 IP/CIDR for the lock-out guard")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def die(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def shell_quote(value: object) -> str:
    return shlex.quote(str(value))


def csv_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def ensure_dict(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        die(f"{label} must be a JSON object.")
    return value


def ensure_list(value: object, label: str) -> list:
    if value is None:
        return []
    if not isinstance(value, list):
        die(f"{label} must be a JSON array.")
    return value


def validate_identifier(value: object, label: str, *, pattern: str = IDENTIFIER_RE) -> str:
    if not isinstance(value, str) or not value.strip():
        die(f"{label} must be a non-empty string.")
    value = value.strip()
    if not re.match(pattern, value):
        die(f"{label} has unsupported characters: {value!r}")
    return value


def validate_optional_text(value: object, label: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        die(f"{label} must be a string.")
    if "\n" in value or "\r" in value:
        die(f"{label} must be a single-line string.")
    return value.strip()


def validate_int(value: object, label: str, *, min_value: int = 0, max_value: int | None = None) -> int:
    if isinstance(value, bool):
        die(f"{label} must be an integer.")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        die(f"{label} must be an integer.")
    if parsed < min_value:
        die(f"{label} must be >= {min_value}.")
    if max_value is not None and parsed > max_value:
        die(f"{label} must be <= {max_value}.")
    return parsed


def validate_bool(value: object, label: str, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    die(f"{label} must be a boolean true/false value.")


def first_present(obj: dict, *keys: str, default: object = None) -> object:
    for key in keys:
        if key in obj:
            return obj[key]
    return default


def validate_string_list(value: object, label: str, *, pattern: str = IDENTIFIER_RE) -> list[str]:
    items = ensure_list(value, label)
    return sorted({validate_identifier(item, f"{label} entry", pattern=pattern) for item in items})


def validate_string_or_list(value: object, label: str, *, pattern: str = IDENTIFIER_RE) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list):
        items = value
    else:
        die(f"{label} must be a string or JSON array.")
    return sorted({validate_identifier(item, f"{label} entry", pattern=pattern) for item in items})


def module_command_groups(modules: list[str]) -> list[str]:
    groups: set[str] = set()
    for module in modules:
        groups.update(MODULE_COMMAND_GROUPS[module])
    return sorted(groups)


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def make_script(body: str) -> str:
    return "#!/usr/bin/env bash\nset -euo pipefail\n\n" + body.lstrip()


def clean_render_dir(render_dir: Path) -> None:
    for rel in GENERATED_FILES:
        candidate = render_dir / rel
        if candidate.is_file() or candidate.is_symlink():
            candidate.unlink()


def validate_subnet_ipv4(subnet: str, feature: str) -> str:
    try:
        net = ipaddress.IPv4Network(subnet, strict=False)
    except (ipaddress.AddressValueError, ValueError, ipaddress.NetmaskValueError) as exc:
        die(f"--{feature}-subnets contains invalid IPv4 subnet {subnet!r}: {exc}")
    return str(net)


def validate_subnet_ipv6(subnet: str, feature: str) -> str:
    try:
        net = ipaddress.IPv6Network(subnet, strict=False)
    except (ipaddress.AddressValueError, ValueError, ipaddress.NetmaskValueError) as exc:
        die(f"--{feature}-subnets-v6 contains invalid IPv6 subnet {subnet!r}: {exc}")
    return str(net)


def validate_features(features: list[str]) -> None:
    if not features:
        die("--features must specify at least one ACS feature.")
    invalid = [f for f in features if f not in FEATURES]
    if invalid:
        die(f"Unknown ACS feature(s): {', '.join(invalid)}. Allowed: {', '.join(FEATURES)}")


def validate_modules(modules: list[str]) -> None:
    if not modules:
        die("--modules must specify at least one ACS admin module.")
    invalid = [m for m in modules if m not in ADMIN_MODULES]
    if invalid:
        die(f"Unknown ACS admin module(s): {', '.join(invalid)}. Allowed: {', '.join(ADMIN_MODULES)}")


def operation_has_items(value: object) -> bool:
    if isinstance(value, list):
        return bool(value)
    if isinstance(value, dict):
        return any(bool(item) for item in value.values())
    return bool(value)


def validate_operations_match_modules(operations: dict, modules: list[str]) -> None:
    enabled = set(modules)
    mismatches = [
        f"{operation_key} requires module {module_name}"
        for operation_key, module_name in OPERATION_MODULES.items()
        if operation_has_items(operations.get(operation_key)) and module_name not in enabled
    ]
    if mismatches:
        die("--admin-plan-file contains operations outside --modules: " + "; ".join(mismatches))


def validate_subnet_caps(plan: dict, cloud_provider: str) -> None:
    """Enforce AWS / GCP subnet limits up-front so apply never gets a 4xx."""
    per_feature_cap = AWS_PER_FEATURE_CAP if cloud_provider == "aws" else GCP_PER_FEATURE_CAP

    for feature, sets in plan["features"].items():
        combined = len(sets["ipv4"]) + len(sets["ipv6"])
        if combined > per_feature_cap:
            die(
                f"Feature '{feature}' would have {combined} subnets across IPv4+IPv6, "
                f"exceeding the {cloud_provider.upper()} per-feature cap of {per_feature_cap}."
            )

    if cloud_provider != "aws":
        return

    for group, members in AWS_GROUPS.items():
        total = sum(
            len(plan["features"][m]["ipv4"]) + len(plan["features"][m]["ipv6"])
            for m in members
            if m in plan["features"]
        )
        if total > AWS_GROUP_CAP:
            die(
                f"AWS group '{group}' (members: {', '.join(members)}) would have "
                f"{total} subnets, exceeding the per-group cap of {AWS_GROUP_CAP}."
            )


def load_admin_plan(path_value: str) -> dict:
    if not path_value:
        return {}
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        die(f"--admin-plan-file does not exist or is not a file: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        die(f"--admin-plan-file must be valid JSON: {exc}")
    return ensure_dict(data, "--admin-plan-file")


def validate_indexes(raw: object) -> list[dict]:
    indexes = []
    for index, item in enumerate(ensure_list(raw, "indexes")):
        obj = ensure_dict(item, f"indexes[{index}]")
        datatype = validate_optional_text(
            obj.get("datatype") or obj.get("dataType") or "event",
            f"indexes[{index}].datatype",
        ).lower()
        record = {
            "name": validate_identifier(obj.get("name"), f"indexes[{index}].name"),
            "datatype": datatype,
            "searchableDays": validate_int(obj.get("searchableDays", 90), f"indexes[{index}].searchableDays", min_value=1),
            "maxDataSizeMB": validate_int(obj.get("maxDataSizeMB", 0), f"indexes[{index}].maxDataSizeMB", min_value=0),
        }
        if record["datatype"] not in {"event", "metric"}:
            die(f"indexes[{index}].datatype must be event or metric.")
        for source_key, dest_key in (
            ("selfStorageBucketPath", "selfStorageBucketPath"),
            ("splunkArchivalRetentionDays", "splunkArchivalRetentionDays"),
        ):
            if source_key in obj:
                if dest_key.endswith("Days"):
                    record[dest_key] = validate_int(obj[source_key], f"indexes[{index}].{source_key}", min_value=1)
                else:
                    record[dest_key] = validate_optional_text(obj[source_key], f"indexes[{index}].{source_key}")
        indexes.append(record)
    return indexes


def validate_hec_tokens(raw: object) -> list[dict]:
    tokens = []
    for index, item in enumerate(ensure_list(raw, "hec_tokens")):
        obj = ensure_dict(item, f"hec_tokens[{index}]")
        if obj.get("token") or obj.get("tokenFile"):
            die("hec_tokens entries must not contain token or tokenFile. Let ACS generate token values, then capture them from live output.")
        record = {
            "name": validate_identifier(obj.get("name"), f"hec_tokens[{index}].name"),
            "defaultIndex": validate_identifier(obj.get("defaultIndex") or obj.get("default_index"), f"hec_tokens[{index}].defaultIndex"),
            "allowedIndexes": validate_string_list(obj.get("allowedIndexes") or obj.get("allowed_indexes") or [], f"hec_tokens[{index}].allowedIndexes"),
            "disabled": validate_bool(first_present(obj, "disabled", default=False), f"hec_tokens[{index}].disabled"),
            "useAck": validate_bool(first_present(obj, "useAck", "use_ack", default=False), f"hec_tokens[{index}].useAck"),
        }
        for key in ("defaultSource", "defaultSourceType", "defaultHost", "_meta"):
            alt_key = {
                "defaultSource": "default_source",
                "defaultSourceType": "default_source_type",
                "defaultHost": "default_host",
                "_meta": "meta",
            }.get(key, key)
            value = obj.get(key, obj.get(alt_key))
            if value:
                record[key] = validate_optional_text(value, f"hec_tokens[{index}].{key}")
        tokens.append(record)
    return tokens


def _role_record(obj: dict, label: str) -> dict:
    record = {"name": validate_identifier(obj.get("name"), f"{label}.name")}
    list_fields = {
        "capabilities": "capabilities",
        "importedRoles": "imported_roles",
        "srchIndexesAllowed": "srch_indexes_allowed",
        "srchIndexesDefault": "srch_indexes_default",
    }
    for canonical, alt in list_fields.items():
        values = obj.get(canonical, obj.get(alt, []))
        if values:
            record[canonical] = validate_string_list(values, f"{label}.{canonical}")
    for canonical, alt in (
        ("defaultApp", "default_app"),
        ("srchFilter", "srch_filter"),
        ("federatedSearchManageAck", "federated_search_manage_ack"),
    ):
        value = obj.get(canonical, obj.get(alt))
        if value:
            record[canonical] = validate_optional_text(value, f"{label}.{canonical}")
    for canonical, alt in (
        ("cumulativeRtSrchJobsQuota", "cumulative_rt_srch_jobs_quota"),
        ("cumulativeSrchJobsQuota", "cumulative_srch_jobs_quota"),
        ("rtSrchJobsQuota", "rt_srch_jobs_quota"),
        ("srchDiskQuota", "srch_disk_quota"),
        ("srchJobsQuota", "srch_jobs_quota"),
        ("srchTimeWin", "srch_time_win"),
        ("srchTimeEarliest", "srch_time_earliest"),
    ):
        if canonical in obj or alt in obj:
            record[canonical] = validate_int(obj.get(canonical, obj.get(alt)), f"{label}.{canonical}", min_value=-1)
    cap_text = ",".join(record.get("capabilities", []) + record.get("importedRoles", [])).lower()
    if "fsh_manage" in cap_text and record.get("federatedSearchManageAck") != "Y":
        die(f"{label} includes fsh_manage and must set federatedSearchManageAck to 'Y'.")
    return record


def validate_roles(raw: object) -> list[dict]:
    return [_role_record(ensure_dict(item, f"roles[{index}]"), f"roles[{index}]") for index, item in enumerate(ensure_list(raw, "roles"))]


def validate_users(raw: object) -> list[dict]:
    users = []
    for index, item in enumerate(ensure_list(raw, "users")):
        obj = ensure_dict(item, f"users[{index}]")
        if obj.get("password"):
            die("users entries must not contain direct password values; use passwordFile for handoff.")
        record = {
            "name": validate_identifier(obj.get("name"), f"users[{index}].name"),
            "roles": validate_string_list(obj.get("roles") or [], f"users[{index}].roles"),
            "applySupported": False,
            "reason": "ACS user create/update can require password material; this renderer keeps user changes as a reviewed handoff to avoid secrets in argv.",
        }
        for canonical, alt in (
            ("email", "email"),
            ("fullName", "full_name"),
            ("defaultApp", "default_app"),
            ("passwordFile", "password_file"),
            ("federatedSearchManageAck", "federated_search_manage_ack"),
        ):
            value = obj.get(canonical, obj.get(alt))
            if value:
                record[canonical] = validate_optional_text(value, f"users[{index}].{canonical}")
        users.append(record)
    return users


def validate_app_permissions(raw: object) -> list[dict]:
    permissions = []
    for index, item in enumerate(ensure_list(raw, "app_permissions")):
        obj = ensure_dict(item, f"app_permissions[{index}]")
        permissions.append(
            {
                "name": validate_identifier(obj.get("name"), f"app_permissions[{index}].name"),
                "read": validate_string_list(obj.get("read") or [], f"app_permissions[{index}].read"),
                "write": validate_string_list(obj.get("write") or [], f"app_permissions[{index}].write"),
            }
        )
    return permissions


def validate_outbound_ports(raw: object) -> list[dict]:
    ports = []
    for index, item in enumerate(ensure_list(raw, "outbound_ports")):
        obj = ensure_dict(item, f"outbound_ports[{index}]")
        family = validate_optional_text(obj.get("family") or "ipv4", f"outbound_ports[{index}].family")
        if family not in {"ipv4", "ipv6"}:
            die(f"outbound_ports[{index}].family must be ipv4 or ipv6.")
        validator = validate_subnet_ipv6 if family == "ipv6" else validate_subnet_ipv4
        ports.append(
            {
                "port": validate_int(obj.get("port"), f"outbound_ports[{index}].port", min_value=1, max_value=65535),
                "family": family,
                "subnets": sorted({validator(s, f"outbound_ports[{index}].subnets") for s in ensure_list(obj.get("subnets"), f"outbound_ports[{index}].subnets")}),
            }
        )
    return ports


def validate_ddss_locations(raw: object) -> list[dict]:
    locations = []
    for index, item in enumerate(ensure_list(raw, "ddss_self_storage_locations")):
        obj = ensure_dict(item, f"ddss_self_storage_locations[{index}]")
        record = {
            "bucketName": validate_identifier(obj.get("bucketName") or obj.get("bucket_name"), f"ddss_self_storage_locations[{index}].bucketName", pattern=r"^[A-Za-z0-9][A-Za-z0-9.-]{1,253}$"),
            "title": validate_optional_text(obj.get("title"), f"ddss_self_storage_locations[{index}].title"),
        }
        if not record["title"]:
            die(f"ddss_self_storage_locations[{index}].title is required.")
        for canonical, alt in (("folder", "folder"), ("description", "description")):
            value = obj.get(canonical, obj.get(alt))
            if value:
                record[canonical] = validate_optional_text(value, f"ddss_self_storage_locations[{index}].{canonical}")
        locations.append(record)
    return locations


def validate_limits(raw: object) -> list[dict]:
    limits = []
    for index, item in enumerate(ensure_list(raw, "limits")):
        obj = ensure_dict(item, f"limits[{index}]")
        settings = ensure_dict(obj.get("settings"), f"limits[{index}].settings")
        safe_settings = {}
        for key, value in sorted(settings.items()):
            safe_key = validate_identifier(key, f"limits[{index}].settings key", pattern=r"^[A-Za-z0-9_.-]{1,128}$")
            safe_settings[safe_key] = validate_optional_text(str(value), f"limits[{index}].settings.{safe_key}")
        limits.append(
            {
                "stanza": validate_identifier(obj.get("stanza"), f"limits[{index}].stanza", pattern=r"^[A-Za-z0-9_.:-]{1,128}$"),
                "settings": safe_settings,
            }
        )
    return limits


def validate_maintenance(raw: object) -> dict:
    obj = ensure_dict(raw or {}, "maintenance_windows")
    result = {}
    if obj.get("preferencesFile") or obj.get("preferences_file"):
        result["preferencesFile"] = validate_optional_text(obj.get("preferencesFile") or obj.get("preferences_file"), "maintenance_windows.preferencesFile")
    return result


def validate_private_connectivity(raw: object) -> list[dict]:
    endpoints = []
    for index, item in enumerate(ensure_list(raw, "private_connectivity")):
        obj = ensure_dict(item, f"private_connectivity[{index}]")
        account_ids = validate_string_list(obj.get("customerAccountIds") or obj.get("customer_account_ids") or [], f"private_connectivity[{index}].customerAccountIds", pattern=ACCOUNT_ID_RE)
        features = validate_string_or_list(first_present(obj, "features", "feature", default=[]), f"private_connectivity[{index}].features", pattern=r"^(ingest|search)$")
        if not account_ids:
            die(f"private_connectivity[{index}].customerAccountIds must contain at least one AWS account ID.")
        endpoints.append({"customerAccountIds": account_ids, "features": features})
    return endpoints


def validate_restarts(raw: object) -> dict:
    obj = ensure_dict(raw or {}, "restarts")
    return {
        "restartIfRequired": validate_bool(first_present(obj, "restartIfRequired", "restart_if_required", default=False), "restarts.restartIfRequired"),
        "forceRestart": validate_bool(first_present(obj, "forceRestart", "force_restart", default=False), "restarts.forceRestart"),
    }


def validate_admin_operations(raw: dict) -> dict:
    return {
        "indexes": validate_indexes(raw.get("indexes")),
        "hec_tokens": validate_hec_tokens(raw.get("hec_tokens")),
        "roles": validate_roles(raw.get("roles")),
        "users": validate_users(raw.get("users")),
        "app_permissions": validate_app_permissions(raw.get("app_permissions")),
        "outbound_ports": validate_outbound_ports(raw.get("outbound_ports")),
        "ddss_self_storage_locations": validate_ddss_locations(raw.get("ddss_self_storage_locations")),
        "limits": validate_limits(raw.get("limits")),
        "maintenance_windows": validate_maintenance(raw.get("maintenance_windows")),
        "private_connectivity": validate_private_connectivity(raw.get("private_connectivity")),
        "restarts": validate_restarts(raw.get("restarts")),
    }


def build_plan(args: argparse.Namespace) -> dict:
    features = csv_list(args.features)
    validate_features(features)
    modules = csv_list(args.modules)
    validate_modules(modules)
    raw_admin_plan = load_admin_plan(args.admin_plan_file)
    operations = validate_admin_operations(raw_admin_plan)
    validate_operations_match_modules(operations, modules)

    operator_ips_v4 = sorted({
        validate_subnet_ipv4(ip if "/" in ip else f"{ip}/32", "operator-ips")
        for ip in csv_list(args.operator_ips)
    })
    operator_ips_v6 = sorted({
        validate_subnet_ipv6(ip if "/" in ip else f"{ip}/128", "operator-ips-v6")
        for ip in csv_list(args.operator_ips_v6)
    })

    plan = {
        "version": 1,
        "skill": "splunk-cloud-acs-admin-setup",
        "modules": modules,
        "cloud_provider": args.cloud_provider,
        "target_search_head": args.target_search_head or None,
        "allow_acs_lockout": args.allow_acs_lockout == "true",
        "strict_drift": args.strict_drift == "true",
        "force": args.force == "true",
        "features": {},
        "proposed_subnets": {},
        "operations": operations,
        "operator_ips": {"ipv4": operator_ips_v4, "ipv6": operator_ips_v6},
        "default_state_notes": {
            f: ("open by default" if f in DEFAULT_OPEN_FEATURES else "closed by default")
            for f in FEATURES
        },
    }

    for feature in features:
        ipv4_attr = f"{feature.replace('-', '_')}_subnets"
        ipv6_attr = f"{feature.replace('-', '_')}_subnets_v6"
        ipv4 = sorted({validate_subnet_ipv4(s, feature) for s in csv_list(getattr(args, ipv4_attr))})
        ipv6 = sorted({validate_subnet_ipv6(s, feature) for s in csv_list(getattr(args, ipv6_attr))})
        plan["features"][feature] = {"ipv4": ipv4, "ipv6": ipv6}

    if "allowlists" not in modules:
        planned_subnet_count = sum(
            len(sets["ipv4"]) + len(sets["ipv6"])
            for sets in plan["features"].values()
        )
        if planned_subnet_count:
            die("Allowlist subnet flags were provided, but the allowlists module is not enabled in --modules.")

    validate_subnet_caps(plan, args.cloud_provider)
    return plan


def render_plan_json(plan: dict) -> str:
    return json.dumps(plan, indent=2, sort_keys=True) + "\n"


def render_metadata(args: argparse.Namespace, plan: dict) -> str:
    return json.dumps(
        {
            "skill": "splunk-cloud-acs-admin-setup",
            "modules": plan["modules"],
            "cloud_provider": plan["cloud_provider"],
            "features_in_plan": sorted(plan["features"].keys()),
            "ipv4_subnet_count": sum(len(v["ipv4"]) for v in plan["features"].values()),
            "ipv6_subnet_count": sum(len(v["ipv6"]) for v in plan["features"].values()),
            "operation_counts": {
                key: (len(value) if isinstance(value, list) else len([k for k, v in value.items() if v]))
                for key, value in plan["operations"].items()
            },
            "allow_acs_lockout": plan["allow_acs_lockout"],
            "strict_drift": plan["strict_drift"],
            "target_search_head": plan["target_search_head"],
            "emit_terraform": args.emit_terraform == "true",
        },
        indent=2,
        sort_keys=True,
    ) + "\n"


def render_readme(plan: dict) -> str:
    rows = []
    for feature in FEATURES:
        sets = plan["features"].get(feature)
        if sets is None:
            rows.append(f"| {feature} | (not in plan) | (not in plan) |")
            continue
        ipv4_count = len(sets["ipv4"])
        ipv6_count = len(sets["ipv6"])
        rows.append(f"| {feature} | {ipv4_count} subnet(s) | {ipv6_count} subnet(s) |")
    allowlist_table = "\n".join(rows)

    operation_rows = []
    for key, value in plan["operations"].items():
        if isinstance(value, list):
            count = len(value)
        elif isinstance(value, dict):
            count = len([item for item in value.values() if item])
        else:
            count = 0
        operation_rows.append(f"| {key} | {count} item(s) |")
    operation_table = "\n".join(operation_rows)

    return f"""# Splunk Cloud ACS Admin Rendered Assets

Cloud provider: `{plan['cloud_provider']}`
Enabled modules: `{', '.join(plan['modules'])}`
Strict allowlist drift: `{plan['strict_drift']}`
Allow ACS lock-out: `{plan['allow_acs_lockout']}`
Target search head: `{plan.get('target_search_head') or '(stack default)'}`

## Allowlist summary

| Feature | IPv4 | IPv6 |
|---------|------|------|
{allowlist_table}

## Admin operation summary

| Operation group | Planned operations |
|-----------------|--------------------|
{operation_table}

## Files

- `plan.json` - full desired state and reviewed ACS admin operations.
- `preflight.sh` - ACS context, capability, command-surface, FedRAMP, lock-out,
  and subnet-limit checks.
- `inventory.sh` - read-only live inventory across ACS status, apps, indexes,
  HEC tokens, users, roles, app permissions, outbound ports, DDSS, limits,
  maintenance windows, restarts, tokens, deployment tasks, license state, and
  Observability pairing handoff state.
- `apply-ipv4.sh` and `apply-ipv6.sh` - converge allowlists to the plan.
- `apply-admin-plan.sh` - guarded apply for non-secret ACS operations from the
  plan. It refuses to run unless `ACCEPT_ACS_ADMIN_MUTATION=true`.
- `admin-commands.sh` - review-only command catalog for every planned admin
  operation, including operations intentionally blocked from automation.
- `private-connectivity-rest.sh` - ACS REST helper for API-only private
  connectivity eligibility and endpoint creation.
- `wait-for-ready.sh` - polls `GET /adminconfig/v2/status` until `Ready`.
- `audit.sh` - re-snapshots allowlists and verifies plan vs. live equality.
- `terraform-snippets.tf` - `splunk/scp` allowlist resource blocks when emitted.

## Safety notes

Adding subnets to the `acs` feature allowlist can lock operators out of IP
allowlist, Federated Search, Maintenance Windows, Observability APIs, and ACS
limits administration. `preflight.sh` refuses to apply the `acs` feature unless
your current public IP is in the planned subnet list, or
`allow_acs_lockout=true`.

The broader admin plan intentionally blocks user password operations and custom
HEC token values because those would put secret material into process argv.
Use generated review notes plus file-backed local handoff for those cases.

## AWS / GCP subnet limit math

- AWS per-feature cap: {AWS_PER_FEATURE_CAP} (IPv4 + IPv6 combined).
- AWS per-group cap: {AWS_GROUP_CAP} (sum across the group's features).
- GCP per-feature cap: {GCP_PER_FEATURE_CAP}.

`preflight.sh` enforces these before any allowlist apply call.
"""


def helper_path() -> Path:
    project_root = Path(__file__).resolve().parents[3]
    return project_root / "skills/shared/lib/credential_helpers.sh"


def render_preflight(plan: dict) -> str:
    helper = shell_quote(helper_path())
    cloud_provider = shell_quote(plan["cloud_provider"])
    target_sh = shell_quote(plan.get("target_search_head") or "")
    allow_acs_lockout = "true" if plan["allow_acs_lockout"] else "false"
    modules = plan.get("modules", list(ADMIN_MODULES))
    required_groups = " ".join(shell_quote(group) for group in module_command_groups(modules))
    allowlists_enabled = "true" if "allowlists" in modules else "false"

    return make_script(
        f"""# shellcheck disable=SC1091
source {helper}
acs_prepare_context

CLOUD_PROVIDER={cloud_provider}
TARGET_SH={target_sh}
ALLOW_ACS_LOCKOUT={allow_acs_lockout}
ALLOWLISTS_ENABLED={allowlists_enabled}
PLAN_FILE="$(dirname "$0")/plan.json"
REQUIRED_COMMAND_GROUPS=({required_groups})

if python3 - "${{PLAN_FILE}}" <<'PY'
import json, sys
plan = json.load(open(sys.argv[1], encoding="utf-8"))
raise SystemExit(0 if plan.get("operations", {{}}).get("users") else 1)
PY
then
  echo "ERROR: the admin plan contains handoff-only user operations; remove them before applying supported ACS mutations." >&2
  exit 2
fi

if [[ -n "${{TARGET_SH}}" ]]; then
  acs_command config use-stack "${{SPLUNK_CLOUD_STACK}}" --target-sh "${{TARGET_SH}}" >/dev/null
fi

# 1. Capability check (sc_admin or equivalent ACS access).
if ! acs_command status current-stack >/dev/null 2>&1; then
  echo "ERROR: ACS API access denied. Caller needs the sc_admin role or the equivalent ACS capability set." >&2
  exit 1
fi

# 1b. Local CLI command-surface check. Private connectivity is API-only in
#     some ACS CLI releases, so that module is intentionally handled by
#     private-connectivity-rest.sh instead of requiring a CLI command.
for command_group in "${{REQUIRED_COMMAND_GROUPS[@]}}"; do
  if ! acs_command "${{command_group}}" --help >/dev/null 2>&1; then
    echo "ERROR: ACS CLI does not expose required command group: ${{command_group}}" >&2
    echo "Upgrade ACS CLI, or disable the related module for this run." >&2
    exit 1
  fi
done

# 2. FedRAMP carve-out: ACS does not manage allowlists on FedRAMP High stacks.
#    ACS surfaces the deployment type via stack metadata; we look for the
#    FedRAMP marker in the structured response and refuse to proceed.
status_payload=$(acs_command status current-stack 2>/dev/null | acs_extract_http_response_json || printf '%s' '{{}}')
fedramp_high=$(printf '%s' "${{status_payload}}" | python3 -c "
import json, sys
raw = sys.stdin.read()
try:
    data = json.loads(raw) if raw.strip() else {{}}
except Exception:
    data = {{}}
text = json.dumps(data).lower()
print('true' if ('fedramp-high' in text or 'fedramp_high' in text or 'govcloud-high' in text) else 'false')
")
if [[ "${{fedramp_high}}" == "true" && "${{ALLOWLISTS_ENABLED}}" == "true" ]]; then
  echo 'ERROR: This stack appears to be FedRAMP High. ACS does not manage IP allowlists there. Contact Splunk Support.' >&2
  exit 1
fi

# 3. Subnet limit enforcement (AWS per-feature, per-group; GCP per-feature).
python3 - "${{PLAN_FILE}}" "${{CLOUD_PROVIDER}}" <<'PY'
import json, sys
plan = json.load(open(sys.argv[1]))
provider = sys.argv[2]
PER_FEATURE = 200
GROUP_CAP = 230
AWS_GROUPS = {{
    "search-head": ("search-api", "search-ui"),
    "indexer": ("hec", "s2s"),
    "idm": ("idm-api", "idm-ui"),
    "single-instance": ("search-api", "search-ui", "hec", "s2s"),
}}
errors = []
for feature, sets in plan["features"].items():
    total = len(sets["ipv4"]) + len(sets["ipv6"])
    if total > PER_FEATURE:
        errors.append(f"feature {{feature}} has {{total}} subnets > {{PER_FEATURE}}")
if provider == "aws":
    for group, members in AWS_GROUPS.items():
        total = sum(len(plan["features"][m]["ipv4"]) + len(plan["features"][m]["ipv6"]) for m in members if m in plan["features"])
        if total > GROUP_CAP:
            errors.append(f"AWS group {{group}} ({{','.join(members)}}) has {{total}} subnets > {{GROUP_CAP}}")
if errors:
    print("ERROR: Subnet limit violations:", file=sys.stderr)
    for e in errors:
        print(f"  - {{e}}", file=sys.stderr)
    sys.exit(1)
PY

# 4. ACS feature lock-out protection. Uses real CIDR containment via Python's
#    ipaddress module so the check works for both /32 IPs and larger
#    planned subnets (e.g. /24). Fails closed: if the `acs` feature is in
#    the plan and we cannot prove that at least one operator IP is covered,
#    we refuse to render the apply scripts unless --allow-acs-lockout is set.
#
#    Operator candidates are:
#      a) IPs / CIDRs explicitly passed via --operator-ip / --operator-ip-v6
#         on `setup.sh` (preferred, especially for proxy / IPv6-only /
#         private-egress paths where outbound discovery cannot see the
#         real client). The renderer sees these as --operator-ips /
#         --operator-ips-v6 internally.
#      b) When the v4 list is empty, outbound discovery against multiple
#         independent endpoints. We do NOT do v6 discovery automatically;
#         operators on IPv6-only paths must pass --operator-ip-v6 if any
#         IPv6 subnets are in the planned `acs` set.
acs_planned_v4=$(python3 -c "import json; print(','.join(json.load(open('${{PLAN_FILE}}'))['features'].get('acs', {{}}).get('ipv4', [])))")
acs_planned_v6=$(python3 -c "import json; print(','.join(json.load(open('${{PLAN_FILE}}'))['features'].get('acs', {{}}).get('ipv6', [])))")
operator_v4=$(python3 -c "import json; print(','.join(json.load(open('${{PLAN_FILE}}')).get('operator_ips', {{}}).get('ipv4', [])))")
operator_v6=$(python3 -c "import json; print(','.join(json.load(open('${{PLAN_FILE}}')).get('operator_ips', {{}}).get('ipv6', [])))")

if [[ "${{ALLOWLISTS_ENABLED}}" == "true" && ( -n "${{acs_planned_v4}}" || -n "${{acs_planned_v6}}" ) && "${{ALLOW_ACS_LOCKOUT}}" != "true" ]]; then
  # Auto-discover v4 only when the operator did not supply one. Try multiple
  # independent endpoints so a single provider outage / egress filter does
  # not silently disable the guard.
  discovered_v4=""
  if [[ -z "${{operator_v4}}" ]]; then
    for url in https://checkip.amazonaws.com https://ifconfig.me https://api.ipify.org; do
      candidate=$(curl -sS --connect-timeout 5 --max-time 10 "${{url}}" 2>/dev/null | tr -d '[:space:]' || true)
      if [[ -n "${{candidate}}" ]]; then
        discovered_v4="${{candidate}}"
        break
      fi
    done
  fi

  # Fail closed if both candidate sources are empty for any planned family.
  if [[ -n "${{acs_planned_v4}}" && -z "${{operator_v4}}" && -z "${{discovered_v4}}" ]]; then
    cat >&2 <<EOM
ERROR: ACS lock-out guard cannot verify operator IPv4 coverage:
  - --operator-ip was not supplied, AND
  - outbound public IP discovery returned nothing (proxy/egress filter/outage).
Refusing to render the apply scripts because the planned 'acs' IPv4 subnets
would otherwise lock this caller out of ACS, IP allowlist, Federated Search,
Maintenance Windows, Observability APIs, and limits endpoints.

Re-run with one of:
  --operator-ip <your-public-ip-or-cidr>
  --allow-acs-lockout true   # only if you intend to lock out
EOM
    exit 1
  fi
  if [[ -n "${{acs_planned_v6}}" && -z "${{operator_v6}}" ]]; then
    cat >&2 <<EOM
ERROR: ACS lock-out guard cannot verify operator IPv6 coverage:
  - --operator-ip-v6 was not supplied (no automatic IPv6 discovery is
    performed because outbound IPv6 reachability does not always reflect the
    inbound admin path), AND
  - the plan includes 'acs' IPv6 subnets.
Refusing to render the apply scripts.

Re-run with one of:
  --operator-ip-v6 <your-public-ipv6-or-cidr>
  --allow-acs-lockout true   # only if you intend to lock out
EOM
    exit 1
  fi

  # Confirm at least one operator candidate is contained by the planned acs
  # subnets per family.
  contained=$(python3 - "${{acs_planned_v4}}" "${{acs_planned_v6}}" "${{operator_v4}}" "${{discovered_v4}}" "${{operator_v6}}" <<'PY'
import ipaddress, sys
acs_v4 = [s for s in sys.argv[1].split(',') if s]
acs_v6 = [s for s in sys.argv[2].split(',') if s]
ops_v4 = [s for s in (sys.argv[3] + ',' + sys.argv[4]).split(',') if s]
ops_v6 = [s for s in sys.argv[5].split(',') if s]


def covered(candidates: list[str], planned: list[str]) -> bool:
    for cand in candidates:
        try:
            ip = ipaddress.ip_interface(cand if '/' in cand else cand + '/32')
        except ValueError:
            continue
        for cidr in planned:
            try:
                net = ipaddress.ip_network(cidr, strict=False)
            except ValueError:
                continue
            if ip.network.subnet_of(net) or ip.ip in net:
                return True
    return False


problems = []
if acs_v4 and not covered(ops_v4, acs_v4):
    problems.append('ipv4')
if acs_v6 and not covered(ops_v6, acs_v6):
    problems.append('ipv6')
print(','.join(problems) if problems else 'ok')
PY
  )
  case "${{contained}}" in
    ok) ;;
    *)
      cat >&2 <<EOM
ERROR: ACS lock-out guard: planned 'acs' subnets do not cover the operator
       address(es) for: ${{contained}}.
Adding these subnets would lock this caller out of:
  - IP allowlist (IPv4 and IPv6)
  - Federated Search
  - Maintenance Windows (CMC app)
  - Observability APIs
  - Limits
Operator IPv4 candidates: ${{operator_v4:-<none>}} ${{discovered_v4:+(discovered: ${{discovered_v4}})}}
Operator IPv6 candidates: ${{operator_v6:-<none>}}

Add a covering CIDR for the missing family to the 'acs' subnet list,
pass an additional --operator-ip / --operator-ip-v6, or set
--allow-acs-lockout true to acknowledge the lock-out.
EOM
      exit 1
      ;;
  esac
fi

# 5. Drift detection: compare live state to the rendered plan, IPv4 + IPv6.
strict=$(python3 -c "import json; print('true' if json.load(open('${{PLAN_FILE}}'))['strict_drift'] else 'false')")
if [[ "${{ALLOWLISTS_ENABLED}}" == "true" && "${{strict}}" == "true" ]]; then
  drift_found=false
  for feature in $(python3 -c "import json; print(' '.join(json.load(open('${{PLAN_FILE}}'))['features'].keys()))"); do
    for family in ipv4 ipv6; do
      if [[ "${{family}}" == "ipv4" ]]; then
        cli_group=ip-allowlist
      else
        cli_group=ip-allowlist-v6
      fi
      live=$(acs_command "${{cli_group}}" describe "${{feature}}" 2>/dev/null | acs_extract_http_response_json | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    subs = data.get('subnets', []) if isinstance(data, dict) else []
    print(','.join(sorted([s if isinstance(s, str) else s.get('subnet', '') for s in subs])))
except Exception:
    print('')
")
      planned=$(python3 -c "import json; print(','.join(sorted(json.load(open('${{PLAN_FILE}}'))['features']['${{feature}}'].get('${{family}}', []))))")
      if [[ -z "${{planned}}" ]]; then
        continue
      fi
      if [[ "${{live}}" != "${{planned}}" ]]; then
        printf 'WARNING: Drift detected on %s/%s (live=%s, plan=%s)\\n' "${{feature}}" "${{family}}" "${{live}}" "${{planned}}" >&2
        drift_found=true
      fi
    done
  done
  if [[ "${{drift_found}}" == "true" ]]; then
    echo 'ERROR: Live state has drifted from the rendered plan. Re-render or pass --force on the parent setup.sh.' >&2
    exit 1
  fi
fi

echo 'OK: ACS admin preflight passed.'
"""
    )


def render_apply(plan: dict, ipv6: bool) -> str:
    if "allowlists" not in plan.get("modules", []):
        family = "IPv6" if ipv6 else "IPv4"
        return make_script(f"echo 'SKIP: allowlists module is disabled; no {family} allowlist apply.'\n")

    helper = shell_quote(helper_path())
    target_sh = shell_quote(plan.get("target_search_head") or "")
    family = "ipv6" if ipv6 else "ipv4"
    # Per Splunk ACS CLI docs (acs ip-allowlist --help, acs ip-allowlist-v6 --help):
    # IPv4 uses `acs ip-allowlist {describe,create,delete}`.
    # IPv6 uses the SEPARATE top-level command `acs ip-allowlist-v6 {describe,create,delete}`.
    cli_group = "ip-allowlist-v6" if ipv6 else "ip-allowlist"

    return make_script(
        f"""# shellcheck disable=SC1091
source {helper}
acs_prepare_context

TARGET_SH={target_sh}
PLAN_FILE="$(dirname "$0")/plan.json"
FAMILY={family!r}
CLI_GROUP={cli_group!r}

if [[ -n "${{TARGET_SH}}" ]]; then
  acs_command config use-stack "${{SPLUNK_CLOUD_STACK}}" --target-sh "${{TARGET_SH}}" >/dev/null
fi

features=$(python3 -c "import json; print(' '.join(sorted(json.load(open('${{PLAN_FILE}}'))['features'].keys())))")
for feature in ${{features}}; do
  planned=$(python3 -c "import json; print(','.join(sorted(json.load(open('${{PLAN_FILE}}'))['features']['${{feature}}']['${{FAMILY}}'])))" 2>/dev/null || echo "")

  if [[ -z "${{planned}}" ]]; then
    log "SKIP: no ${{FAMILY}} subnets were specified for '${{feature}}'; preserving live state."
    continue
  fi

  # Per Splunk ACS CLI docs, the read-only subcommand is `describe` (not `list`).
  live_json=$(acs_command "${{CLI_GROUP}}" describe "${{feature}}" 2>/dev/null \\
    | acs_extract_http_response_json || {{ echo "ERROR: could not read live ${{FAMILY}} allowlist for '${{feature}}'; refusing blind convergence." >&2; exit 1; }})
  live=$(printf '%s' "${{live_json}}" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    subs = data.get('subnets', []) if isinstance(data, dict) else []
    print(','.join(sorted([s if isinstance(s, str) else s.get('subnet', '') for s in subs])))
except Exception:
    print('')
")

  to_add=$(python3 - "${{planned}}" "${{live}}" <<'PY'
import sys
planned = set(filter(None, sys.argv[1].split(',')))
live = set(filter(None, sys.argv[2].split(',')))
print(','.join(sorted(planned - live)))
PY
  )
  to_remove=$(python3 - "${{planned}}" "${{live}}" <<'PY'
import sys
planned = set(filter(None, sys.argv[1].split(',')))
live = set(filter(None, sys.argv[2].split(',')))
print(','.join(sorted(live - planned)))
PY
  )

  if [[ -n "${{to_add}}" ]]; then
    log "Adding ${{FAMILY}} subnets to '${{feature}}': ${{to_add}}"
    acs_command "${{CLI_GROUP}}" create "${{feature}}" --subnets "${{to_add}}" >/dev/null
  fi
  if [[ -n "${{to_remove}}" ]]; then
    log "Removing ${{FAMILY}} subnets from '${{feature}}': ${{to_remove}}"
    acs_command "${{CLI_GROUP}}" delete "${{feature}}" --subnets "${{to_remove}}" >/dev/null
  fi
done

log "OK: ${{FAMILY}} apply complete. Run wait-for-ready.sh to confirm Ready status."
"""
    )


def render_wait_for_ready() -> str:
    helper = shell_quote(helper_path())
    return make_script(
        f"""# shellcheck disable=SC1091
source {helper}
acs_prepare_context

TIMEOUT_SECS=${{TIMEOUT_SECS:-900}}
INTERVAL_SECS=${{INTERVAL_SECS:-10}}
waited=0

# `acs status current-stack` returns
#   {{"status": {{"infrastructure": {{"status": "Ready" | "Pending" | "Failed"}}}}}}
parse_status() {{
  python3 -c "
import json, sys
text = sys.stdin.read()
if not text.strip():
    print('unknown'); sys.exit(0)
try:
    data = json.loads(text)
except Exception:
    print('unknown'); sys.exit(0)
infra = (data.get('infrastructure') or (data.get('status') or {{}}).get('infrastructure') or {{}})
print(infra.get('status', 'unknown'))
"
}}

while (( waited < TIMEOUT_SECS )); do
  payload=$(acs_command status current-stack 2>/dev/null | acs_extract_http_response_json || printf '%s' '{{}}')
  status=$(printf '%s' "${{payload}}" | parse_status)
  case "${{status}}" in
    Ready)
      echo "OK: ACS reports Ready."
      exit 0
      ;;
    Failed)
      echo "ERROR: ACS reports Failed status. See ${{payload}}" >&2
      exit 1
      ;;
    *)
      log "ACS status=${{status}}, waiting..."
      sleep "${{INTERVAL_SECS}}"
      waited=$((waited + INTERVAL_SECS))
      ;;
  esac
done

echo "ERROR: Timed out waiting for ACS to reach Ready." >&2
exit 1
"""
    )


def render_audit(plan: dict) -> str:
    if "allowlists" not in plan.get("modules", []):
        return make_script("echo 'SKIP: allowlists module is disabled; no allowlist audit.'\n")

    helper = shell_quote(helper_path())
    return make_script(
        f"""# shellcheck disable=SC1091
source {helper}
acs_prepare_context

PLAN_FILE="$(dirname "$0")/plan.json"
TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)
AUDIT_DIR="$(dirname "$0")/audit/${{TIMESTAMP}}"
mkdir -p "${{AUDIT_DIR}}"

features=$(python3 -c "import json; print(' '.join(sorted(json.load(open('${{PLAN_FILE}}'))['features'].keys())))")

mismatch=false

for feature in ${{features}}; do
  for family in ipv4 ipv6; do
    # Per Splunk ACS CLI: IPv4 = `acs ip-allowlist describe`,
    # IPv6 = `acs ip-allowlist-v6 describe`.
    if [[ "${{family}}" == "ipv4" ]]; then
      cli_group=ip-allowlist
    else
      cli_group=ip-allowlist-v6
    fi
    snapshot_path="${{AUDIT_DIR}}/${{feature}}-${{family}}.json"
    acs_command "${{cli_group}}" describe "${{feature}}" 2>/dev/null \\
      | acs_extract_http_response_json > "${{snapshot_path}}" || {{ echo "ERROR: could not read live ${{family}} allowlist for '${{feature}}'; audit is incomplete." >&2; exit 1; }}

    live=$(python3 -c "
import json, sys
try:
    data = json.load(open(sys.argv[1]))
except Exception:
    data = {{}}
subs = data.get('subnets', []) if isinstance(data, dict) else []
print(','.join(sorted([s if isinstance(s, str) else s.get('subnet', '') for s in subs])))
" "${{snapshot_path}}" 2>/dev/null || printf '')
    planned=$(python3 -c "
import json, sys
plan = json.load(open(sys.argv[1]))
print(','.join(sorted(plan['features'].get(sys.argv[2], {{}}).get(sys.argv[3], []))))
" "${{PLAN_FILE}}" "${{feature}}" "${{family}}" 2>/dev/null || printf '')
    if [[ -z "${{planned}}" ]]; then
      printf 'SKIP: feature=%s family=%s was unspecified; live state preserved\n' "${{feature}}" "${{family}}"
      continue
    fi
    if [[ "${{live}}" != "${{planned}}" ]]; then
      printf 'MISMATCH: feature=%s family=%s live=%s plan=%s\\n' "${{feature}}" "${{family}}" "${{live}}" "${{planned}}"
      mismatch=true
    fi
  done
done

if [[ "${{mismatch}}" == "true" ]]; then
  echo "WARNING: Live state differs from the rendered plan. See ${{AUDIT_DIR}} for details." >&2
  exit 1
fi
echo "OK: Live state matches the rendered plan. Snapshot saved to ${{AUDIT_DIR}}."
"""
    )


def bash_cmd(parts: list[object]) -> str:
    return " ".join(shell_quote(part) for part in parts)


def add_optional_flag(parts: list[object], flag: str, record: dict, key: str) -> None:
    value = record.get(key)
    if value not in (None, "", []):
        parts.extend([flag, value])


def add_bool_flag(parts: list[object], flag: str, record: dict, key: str) -> None:
    if key in record:
        parts.append(f"{flag}={'true' if record.get(key) else 'false'}")


def role_flags(record: dict, *, for_create: bool) -> list[object]:
    parts: list[object] = []
    if for_create:
        parts.extend(["--name", record["name"]])
    field_flags = {
        "capabilities": "--capabilities",
        "importedRoles": "--imported-roles",
        "srchIndexesAllowed": "--srch-indexes-allowed",
        "srchIndexesDefault": "--srch-indexes-default",
    }
    for key, flag in field_flags.items():
        if record.get(key):
            parts.extend([flag, ",".join(record[key])])
    scalar_flags = {
        "defaultApp": "--default-app",
        "srchFilter": "--srch-filter",
        "federatedSearchManageAck": "--federated-search-manage-ack",
        "cumulativeRtSrchJobsQuota": "--cumulative-rt-srch-jobs-quota",
        "cumulativeSrchJobsQuota": "--cumulative-srch-jobs-quota",
        "rtSrchJobsQuota": "--rt-srch-jobs-quota",
        "srchDiskQuota": "--srch-disk-quota",
        "srchJobsQuota": "--srch-jobs-quota",
        "srchTimeWin": "--srch-time-win",
        "srchTimeEarliest": "--srch-time-earliest",
    }
    for key, flag in scalar_flags.items():
        add_optional_flag(parts, flag, record, key)
    return parts


def hec_token_flags(record: dict, *, for_create: bool) -> list[object]:
    parts: list[object] = []
    if for_create:
        parts.extend(["--name", record["name"]])
    parts.extend(["--default-index", record["defaultIndex"]])
    for key, flag in (
        ("defaultSource", "--default-source"),
        ("defaultSourceType", "--default-source-type"),
        ("defaultHost", "--default-host"),
        ("_meta", "--_meta"),
    ):
        if key in record:
            parts.extend([flag, record[key]])
    if record.get("allowedIndexes"):
        parts.extend(["--allowed-indexes", ",".join(record["allowedIndexes"])])
    parts.append(f"--disabled={'true' if record.get('disabled') else 'false'}")
    parts.append(f"--use-ack={'true' if record.get('useAck') else 'false'}")
    return parts


def render_inventory(plan: dict) -> str:
    helper = shell_quote(helper_path())
    modules = " ".join(shell_quote(m) for m in plan["modules"])
    return make_script(
        f"""# shellcheck disable=SC1091
source {helper}
acs_prepare_context

SNAPSHOT_DIR="$(dirname "$0")/inventory/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "${{SNAPSHOT_DIR}}"
MODULES=({modules})

capture() {{
  local name="$1"
  shift
  log "Inventory: ${{name}}"
  if "$@" > "${{SNAPSHOT_DIR}}/${{name}}.json" 2> "${{SNAPSHOT_DIR}}/${{name}}.stderr"; then
    :
  else
    printf '{{"status":"unavailable","name":"%s"}}\\n' "${{name}}" > "${{SNAPSHOT_DIR}}/${{name}}.json"
  fi
}}

capture status-current-stack acs_command status current-stack

for module in "${{MODULES[@]}}"; do
  case "${{module}}" in
    allowlists)
      for feature in acs search-api hec s2s search-ui idm-api idm-ui; do
        capture "allowlist-${{feature}}-ipv4" acs_command ip-allowlist describe "${{feature}}"
        capture "allowlist-${{feature}}-ipv6" acs_command ip-allowlist-v6 describe "${{feature}}"
      done
      ;;
    indexes)
      capture indexes acs_command indexes list
      ;;
    ddss)
      capture ddss-self-storage-locations acs_command indexes self-storage-locations list
      ;;
    hec-tokens)
      capture hec-tokens acs_command hec-token list
      ;;
    users)
      capture users acs_command users list
      ;;
    roles)
      capture roles acs_command roles list
      ;;
    capabilities)
      capture capabilities acs_command capabilities list
      ;;
    app-permissions)
      capture app-permissions acs_command permissions apps list
      ;;
    outbound-ports)
      capture outbound-ports-ipv4 acs_command outbound-port list
      capture outbound-ports-ipv6 acs_command outbound-port-v6 list
      ;;
    limits)
      capture limits acs_command limits list
      ;;
    maintenance-windows)
      capture maintenance-window-schedules acs_command maintenance-windows schedules list
      capture maintenance-window-preferences acs_command maintenance-windows preferences describe
      ;;
    restarts)
      capture restart-status acs_command restart status
      ;;
    apps)
      capture apps acs_command apps list
      ;;
    tokens)
      capture tokens acs_command token list
      ;;
    deployment)
      capture deployment-status acs_command deployment status
      ;;
    license)
      capture license acs_command license
      ;;
    observability)
      cat > "${{SNAPSHOT_DIR}}/observability-handoff.json" <<'JSON'
{{"status":"delegated","skill":"splunk-observability-cloud-integration-setup","reason":"ACS observability pairing mutates Unified Identity and centralized RBAC; use the dedicated Observability workflow for apply guardrails."}}
JSON
      ;;
    private-connectivity)
      if [[ -n "${{STACK_TOKEN:-}}" && -n "${{SPLUNK_CLOUD_STACK:-}}" ]]; then
        endpoint="${{ACS_SERVER:-https://admin.splunk.com}}/${{SPLUNK_CLOUD_STACK}}/adminconfig/v2/private-connectivity/eligibility"
        curl -fsS -K <(printf 'header = "Authorization: Bearer %s"\\n' "${{STACK_TOKEN}}") "${{endpoint}}" > "${{SNAPSHOT_DIR}}/private-connectivity-eligibility.json" \\
          || printf '{{"status":"unavailable","name":"private-connectivity-eligibility"}}\\n' > "${{SNAPSHOT_DIR}}/private-connectivity-eligibility.json"
      else
        printf '{{"status":"skipped","reason":"STACK_TOKEN and SPLUNK_CLOUD_STACK required for API-only private connectivity endpoint"}}\\n' \\
          > "${{SNAPSHOT_DIR}}/private-connectivity-eligibility.json"
      fi
      ;;
  esac
done

log "OK: ACS inventory snapshot saved to ${{SNAPSHOT_DIR}}"
"""
    )


def render_admin_commands(plan: dict) -> str:
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        "# Review-only command catalog. This file intentionally does not execute",
        "# live mutations; apply-admin-plan.sh is the guarded executor.",
        "",
    ]
    ops = plan["operations"]
    for index in ops["indexes"]:
        create = ["acs", "indexes", "create", "--name", index["name"], "--data-type", index["datatype"], "--searchable-days", index["searchableDays"], "--max-data-size-mb", index["maxDataSizeMB"]]
        update = ["acs", "indexes", "update", index["name"], "--searchable-days", index["searchableDays"], "--max-data-size-mb", index["maxDataSizeMB"]]
        for key, flag in (("selfStorageBucketPath", "--self-storage-bucket-path"), ("splunkArchivalRetentionDays", "--splunk-archival-retention-days")):
            if key in index:
                create.extend([flag, index[key]])
                update.extend([flag, index[key]])
        lines.append(f"echo {shell_quote('index: ' + index['name'])}")
        lines.append(f"echo {shell_quote(bash_cmd(create))}")
        lines.append(f"echo {shell_quote(bash_cmd(update))}")
    for token in ops["hec_tokens"]:
        command = ["acs", "hec-token", "create", *hec_token_flags(token, for_create=True)]
        lines.append(f"echo {shell_quote('hec-token: ' + token['name'])}")
        lines.append(f"echo {shell_quote(bash_cmd(command))}")
    for role in ops["roles"]:
        lines.append(f"echo {shell_quote('role: ' + role['name'])}")
        lines.append(f"echo {shell_quote(bash_cmd(['acs', 'roles', 'create', *role_flags(role, for_create=True)]))}")
        lines.append(f"echo {shell_quote(bash_cmd(['acs', 'roles', 'update', role['name'], *role_flags(role, for_create=False)]))}")
    for user in ops["users"]:
        lines.append(f"echo {shell_quote('user handoff only: ' + user['name'] + ' - ' + user['reason'])}")
    for app in ops["app_permissions"]:
        command = ["acs", "permissions", "apps", "update", "--name", app["name"]]
        if app["read"]:
            command.extend(["--read", ",".join(app["read"])])
        if app["write"]:
            command.extend(["--write", ",".join(app["write"])])
        lines.append(f"echo {shell_quote('app-permissions: ' + app['name'])}")
        lines.append(f"echo {shell_quote(bash_cmd(command))}")
    for port in ops["outbound_ports"]:
        command = ["acs", "outbound-port-v6" if port["family"] == "ipv6" else "outbound-port", "create", port["port"], "--subnets", ",".join(port["subnets"])]
        lines.append(f"echo {shell_quote('outbound-port: ' + str(port['port']) + '/' + port['family'])}")
        lines.append(f"echo {shell_quote(bash_cmd(command))}")
    for location in ops["ddss_self_storage_locations"]:
        command = ["acs", "indexes", "self-storage-locations", "create", "--bucket-name", location["bucketName"], "--title", location["title"]]
        add_optional_flag(command, "--folder", location, "folder")
        add_optional_flag(command, "--description", location, "description")
        lines.append(f"echo {shell_quote('ddss: ' + location['bucketName'])}")
        lines.append(f"echo {shell_quote(bash_cmd(command))}")
    for limit in ops["limits"]:
        command = ["acs", "limits", "set", limit["stanza"]]
        command.extend(f"{key}={value}" for key, value in sorted(limit["settings"].items()))
        lines.append(f"echo {shell_quote('limits: ' + limit['stanza'])}")
        lines.append(f"echo {shell_quote(bash_cmd(command))}")
    if ops["maintenance_windows"].get("preferencesFile"):
        command = ["acs", "maintenance-windows", "preferences", "update", "--file", ops["maintenance_windows"]["preferencesFile"]]
        lines.append(f"echo {shell_quote('maintenance-windows preferences update')}")
        lines.append(f"echo {shell_quote(bash_cmd(command))}")
    for endpoint in ops["private_connectivity"]:
        lines.append(f"echo {shell_quote('private-connectivity endpoint: accounts=' + ','.join(endpoint['customerAccountIds']))}")
        lines.append("echo './private-connectivity-rest.sh apply'")
    if ops["restarts"].get("forceRestart") or ops["restarts"].get("restartIfRequired"):
        lines.append("echo 'restart: acs restart current-stack'")
    lines.append("")
    return "\n".join(lines)


def render_apply_admin_plan(plan: dict) -> str:
    helper = shell_quote(helper_path())
    ops = plan["operations"]
    mutation_lists = (
        "indexes",
        "hec_tokens",
        "users",
        "roles",
        "app_permissions",
        "outbound_ports",
        "ddss_self_storage_locations",
        "limits",
        "private_connectivity",
    )
    has_mutations = any(ops.get(key) for key in mutation_lists)
    has_mutations = has_mutations or bool(ops["maintenance_windows"].get("preferencesFile"))
    has_mutations = has_mutations or bool(
        ops["restarts"].get("forceRestart") or ops["restarts"].get("restartIfRequired")
    )
    if not has_mutations:
        return make_script("echo 'SKIP: no ACS admin-plan mutations were requested.'\n")
    lines = [
        "# shellcheck disable=SC1091",
        f"source {helper}",
        "acs_prepare_context",
        "",
        'if [[ "${ACCEPT_ACS_ADMIN_MUTATION:-false}" != "true" ]]; then',
        "  echo 'ERROR: Set ACCEPT_ACS_ADMIN_MUTATION=true to apply broad ACS admin operations.' >&2",
        "  exit 1",
        "fi",
        "",
    ]
    if ops["users"]:
        lines.extend(
            [
                "echo 'ERROR: user operations require password material and are handoff-only; remove them from the apply plan before applying supported operations.' >&2",
                "exit 2",
                "",
            ]
        )
    for index in ops["indexes"]:
        create_flags = ["--name", index["name"], "--data-type", index["datatype"], "--searchable-days", index["searchableDays"], "--max-data-size-mb", index["maxDataSizeMB"]]
        update_flags = ["--searchable-days", index["searchableDays"], "--max-data-size-mb", index["maxDataSizeMB"]]
        for key, flag in (("selfStorageBucketPath", "--self-storage-bucket-path"), ("splunkArchivalRetentionDays", "--splunk-archival-retention-days")):
            if key in index:
                create_flags.extend([flag, index[key]])
                update_flags.extend([flag, index[key]])
        lines.extend(
            [
                f"if acs_command indexes describe {shell_quote(index['name'])} >/dev/null 2>&1; then",
                f"  acs_command indexes update {shell_quote(index['name'])} {bash_cmd(update_flags)} >/dev/null",
                "else",
                f"  acs_command indexes create {bash_cmd(create_flags)} >/dev/null",
                "fi",
                "",
            ]
        )
    for token in ops["hec_tokens"]:
        create_flags = hec_token_flags(token, for_create=True)
        update_flags = hec_token_flags(token, for_create=False)
        lines.extend(
            [
                f"if acs_command hec-token describe {shell_quote(token['name'])} >/dev/null 2>&1; then",
                f"  acs_command hec-token update {shell_quote(token['name'])} {bash_cmd(update_flags)} >/dev/null",
                "else",
                f"  acs_command hec-token create {bash_cmd(create_flags)} >/dev/null",
                "fi",
                "",
            ]
        )
    for role in ops["roles"]:
        lines.extend(
            [
                f"if acs_command roles describe {shell_quote(role['name'])} >/dev/null 2>&1; then",
                f"  acs_command roles update {shell_quote(role['name'])} {bash_cmd(role_flags(role, for_create=False))} >/dev/null",
                "else",
                f"  acs_command roles create {bash_cmd(role_flags(role, for_create=True))} >/dev/null",
                "fi",
                "",
            ]
        )
    for app in ops["app_permissions"]:
        flags: list[object] = ["--name", app["name"]]
        if app["read"]:
            flags.extend(["--read", ",".join(app["read"])])
        if app["write"]:
            flags.extend(["--write", ",".join(app["write"])])
        lines.append(f"acs_command permissions apps update {bash_cmd(flags)} >/dev/null")
    for port in ops["outbound_ports"]:
        group = "outbound-port-v6" if port["family"] == "ipv6" else "outbound-port"
        lines.append(f"acs_command {group} create {shell_quote(port['port'])} --subnets {shell_quote(','.join(port['subnets']))} >/dev/null")
    for location in ops["ddss_self_storage_locations"]:
        flags: list[object] = ["--bucket-name", location["bucketName"], "--title", location["title"]]
        add_optional_flag(flags, "--folder", location, "folder")
        add_optional_flag(flags, "--description", location, "description")
        lines.append(f"acs_command indexes self-storage-locations create {bash_cmd(flags)} >/dev/null")
    for limit in ops["limits"]:
        settings = [f"{key}={value}" for key, value in sorted(limit["settings"].items())]
        lines.append(f"acs_command limits set {shell_quote(limit['stanza'])} {bash_cmd(settings)} >/dev/null")
    if ops["maintenance_windows"].get("preferencesFile"):
        lines.append(f"acs_command maintenance-windows preferences update --file {shell_quote(ops['maintenance_windows']['preferencesFile'])} >/dev/null")
    if ops["private_connectivity"]:
        lines.append('./private-connectivity-rest.sh apply')
    if ops["restarts"].get("forceRestart"):
        lines.append("acs_command restart current-stack >/dev/null")
    elif ops["restarts"].get("restartIfRequired"):
        lines.extend(
            [
                'if [[ "$(acs_restart_required 2>/dev/null || echo false)" == "true" ]]; then',
                "  acs_command restart current-stack >/dev/null",
                "fi",
            ]
        )
    lines.append("echo 'OK: ACS admin plan apply completed.'")
    return make_script("\n".join(lines))


def render_private_connectivity_rest(plan: dict) -> str:
    helper = shell_quote(helper_path())
    endpoint_payloads = json.dumps(plan["operations"]["private_connectivity"], indent=2)
    return make_script(
        f"""# shellcheck disable=SC1091
source {helper}
acs_prepare_context

ACTION="${{1:-eligibility}}"
BASE="${{ACS_SERVER:-https://admin.splunk.com}}/${{SPLUNK_CLOUD_STACK:-}}/adminconfig/v2/private-connectivity"

if [[ -z "${{SPLUNK_CLOUD_STACK:-}}" || -z "${{STACK_TOKEN:-}}" ]]; then
  echo "ERROR: SPLUNK_CLOUD_STACK and STACK_TOKEN are required for ACS private connectivity REST calls." >&2
  exit 1
fi

case "${{ACTION}}" in
  eligibility)
    curl -fsS -K <(printf 'header = "Authorization: Bearer %s"\\n' "${{STACK_TOKEN}}") "${{BASE}}/eligibility"
    ;;
  apply)
    tmp_dir="$(mktemp -d)"
    trap 'rm -rf "${{tmp_dir}}"' EXIT
    python3 - "${{tmp_dir}}" <<'PY'
import json
import pathlib
import sys

payloads = {endpoint_payloads}
tmp_dir = pathlib.Path(sys.argv[1])
for index, item in enumerate(payloads):
    body = {{
        "customerAccountIds": item["customerAccountIds"],
        "feature": item["features"],
    }}
    (tmp_dir / f"private-connectivity-{{index}}.json").write_text(json.dumps(body), encoding="utf-8")
PY
    for body in "${{tmp_dir}}"/private-connectivity-*.json; do
      [[ -f "${{body}}" ]] || continue
      curl -fsS --request POST \\
        -K <(printf 'header = "Authorization: Bearer %s"\\n' "${{STACK_TOKEN}}") \\
        --header "Content-Type: application/json" \\
        --data @"${{body}}" \\
        "${{BASE}}/endpoints"
    done
    ;;
  *)
    echo "Usage: $0 [eligibility|apply]" >&2
    exit 1
    ;;
esac
"""
    )


def render_terraform_snippets(plan: dict) -> str:
    if not plan["features"]:
        return "# splunk/scp Terraform snippets (no features in plan)\n"
    # Per the Splunk Cloud Platform Terraform Provider docs, the resource type
    # is `scp_ip_allowlists` (plural) and accepts the documented features
    # (acs, search-api, hec, s2s, search-ui, idm-api, idm-ui). The provider
    # currently exposes IPv4 only via this resource; IPv6 lists must be
    # managed via the ACS CLI / API until the provider adds an IPv6 resource.
    lines = [
        "# Splunk Cloud Platform Terraform Provider snippets.",
        "# Provider: splunk/scp (https://registry.terraform.io/providers/splunk/scp/latest).",
        "# Note: the provider exposes IPv4 allowlists via scp_ip_allowlists; IPv6",
        "# lists must continue to be managed through the ACS CLI / acs ip-allowlist-v6.",
        "",
        'terraform {',
        '  required_providers {',
        '    scp = {',
        '      source  = "splunk/scp"',
        '    }',
        '  }',
        '}',
        "",
        'provider "scp" {',
        '  stack          = var.stack',
        '  authentication = var.scp_auth_token',
        "}",
        "",
    ]
    for feature, sets in sorted(plan["features"].items()):
        if sets["ipv4"]:
            # Provider docs require the resource name to match the feature
            # name to avoid duplicate-resource errors.
            tf_name = feature.replace("-", "_")
            lines.append(f'resource "scp_ip_allowlists" "{tf_name}" {{')
            lines.append(f'  feature = "{feature}"')
            ipv4_block = ", ".join(f'"{s}"' for s in sets["ipv4"])
            lines.append(f"  subnets = [{ipv4_block}]")
            lines.append("}")
            lines.append("")
        if sets["ipv6"]:
            lines.append(f"# IPv6 allowlist for feature '{feature}' is not exposed by")
            lines.append("# splunk/scp at this time. Manage it via:")
            ipv6_csv = ",".join(sets["ipv6"])
            lines.append(f"#   acs ip-allowlist-v6 create {feature} --subnets '{ipv6_csv}'")
            lines.append("")
    return "\n".join(lines)


def render_all(args: argparse.Namespace) -> dict:
    plan = build_plan(args)

    output_dir = Path(args.output_dir).expanduser().resolve()
    render_dir = output_dir / "acs-admin"
    render_dir.mkdir(parents=True, exist_ok=True)
    clean_render_dir(render_dir)

    artifacts = {
        "README.md": render_readme(plan),
        "admin-commands.sh": render_admin_commands(plan),
        "apply-admin-plan.sh": render_apply_admin_plan(plan),
        "metadata.json": render_metadata(args, plan),
        "plan.json": render_plan_json(plan),
        "preflight.sh": render_preflight(plan),
        "apply-ipv4.sh": render_apply(plan, ipv6=False),
        "apply-ipv6.sh": render_apply(plan, ipv6=True),
        "inventory.sh": render_inventory(plan),
        "private-connectivity-rest.sh": render_private_connectivity_rest(plan),
        "wait-for-ready.sh": render_wait_for_ready(),
        "audit.sh": render_audit(plan),
    }
    if args.emit_terraform == "true":
        artifacts["terraform-snippets.tf"] = render_terraform_snippets(plan)

    for name, content in artifacts.items():
        path = render_dir / name
        write_file(path, content, executable=name.endswith(".sh"))

    return {
        "render_dir": str(render_dir),
        "files": sorted(artifacts.keys()),
        "plan": plan,
    }


def main() -> None:
    args = parse_args()
    if args.dry_run:
        plan = build_plan(args)
        if args.json:
            print(json.dumps({"plan": plan}, indent=2, sort_keys=True))
        else:
            print(json.dumps(plan, indent=2, sort_keys=True))
        return
    result = render_all(args)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Rendered {len(result['files'])} ACS admin asset(s) to {result['render_dir']}")
        for name in result["files"]:
            print(f"  - {name}")


if __name__ == "__main__":
    main()

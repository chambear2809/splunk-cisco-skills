#!/usr/bin/env python3
"""Build the product-setup catalog from SCAN plus local overrides."""

from __future__ import annotations

import argparse
import configparser
import io
import json
import re
import tarfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_ROOT = REPO_ROOT / "skills/cisco-product-setup"
CATALOG_PATH = SKILL_ROOT / "catalog.json"
OVERRIDES_PATH = SKILL_ROOT / "catalog_overrides.json"
SCAN_GLOB = "splunk-cisco-app-navigator-*.tar.gz"
SCAN_PRODUCTS_MEMBER = "splunk-cisco-app-navigator/default/products.conf"
SECURITY_CLOUD_PRODUCTS_PATH = REPO_ROOT / "skills/cisco-security-cloud-setup/products.json"
REGISTRY_PATH = REPO_ROOT / "skills/shared/app_registry.json"

TEMPLATE_PATHS = {
    "security_cloud": "skills/cisco-security-cloud-setup/template.example",
    "secure_access": "skills/cisco-secure-access-setup/template.example",
    "dc_networking": "skills/cisco-dc-networking-setup/template.example",
    "catalyst": "skills/cisco-catalyst-ta-setup/template.example",
    "meraki": "skills/cisco-meraki-ta-setup/template.example",
    "intersight": "skills/cisco-intersight-setup/template.example",
    "thousandeyes": "skills/cisco-thousandeyes-setup/template.example",
    "appdynamics": "skills/cisco-appdynamics-setup/template.example",
}

DC_ACCOUNT_TEMPLATE_SECTION = {
    "aci": "aci_account",
    "nd": "nexus_dashboard_account",
    "nexus9k": "nexus_9k_account",
}

CATALYST_ACCOUNT_TEMPLATE_SECTION = {
    "catalyst_center": "catalyst_center_account",
    "ise": "ise_account",
    "sdwan": "sdwan_account",
    "cybervision": "cyber_vision_account",
}

DC_DEFAULT_NAMES = {
    "aci": "ACI_PROD",
    "nd": "NEXUS_DASHBOARD_PROD",
    "nexus9k": "NEXUS9K_PROD",
}

DC_DEFAULT_INDEX = {
    "aci": "cisco_aci",
    "nd": "cisco_nd",
    "nexus9k": "cisco_nexus_9k",
}

CATALYST_DEFAULT_NAMES = {
    "catalyst_center": "DNAC_PROD",
    "ise": "ISE_PROD",
    "sdwan": "SDWAN_PROD",
    "cybervision": "CYBERVISION_PROD",
}

CATALYST_DEFAULT_INDEX = {
    "catalyst_center": "catalyst",
    "ise": "ise",
    "sdwan": "sdwan",
    "cybervision": "cybervision",
}

GENERATED_BANNER = (
    "Generated from the packaged SCAN catalog plus "
    "skills/cisco-product-setup/catalog_overrides.json."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Verify catalog.json is up to date.")
    mode.add_argument("--write", action="store_true", help="Write catalog.json.")
    parser.add_argument(
        "--scan-package",
        default="",
        help="Optional explicit path to the SCAN tarball. Defaults to the newest match in splunk-ta/.",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def find_scan_package(explicit: str) -> Path:
    if explicit:
        path = Path(explicit)
        if not path.is_absolute():
            path = REPO_ROOT / explicit
        if not path.is_file():
            raise SystemExit(f"SCAN package not found: {path}")
        return path

    matches = sorted((REPO_ROOT / "splunk-ta").glob(SCAN_GLOB), key=scan_package_sort_key)
    if not matches:
        raise SystemExit(f"No SCAN package matching {SCAN_GLOB} found in splunk-ta/.")
    return matches[-1]


def scan_package_sort_key(path: Path) -> tuple[tuple[int, ...], str]:
    match = re.search(r"(\d+(?:\.\d+)+)", path.name)
    version = tuple(int(part) for part in match.group(1).split(".")) if match else ()
    return version, path.name


def split_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def normalize(value: str) -> str:
    lowered = value.lower().replace("&", " and ").replace("_", " ")
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered).strip()
    return lowered


def unique_ordered(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        cleaned = value.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        output.append(cleaned)
    return output


def extract_display_aliases(display_name: str) -> list[str]:
    aliases = [display_name]
    no_parens = re.sub(r"\s*\([^)]*\)", "", display_name).strip()
    if no_parens and no_parens != display_name:
        aliases.append(no_parens)

    for match in re.findall(r"\(([^)]+)\)", display_name):
        aliases.append(match.strip())
        for piece in re.split(r"[/,]", match):
            piece = piece.strip()
            if piece:
                aliases.append(piece)
    return unique_ordered(aliases)


def load_scan_products(scan_package: Path) -> list[dict]:
    with tarfile.open(scan_package, "r:gz") as archive:
        raw = archive.extractfile(SCAN_PRODUCTS_MEMBER)
        if raw is None:
            raise SystemExit(f"{SCAN_PRODUCTS_MEMBER} not found in {scan_package.name}")
        text = raw.read().decode("utf-8")

    parser = configparser.ConfigParser(strict=False)
    parser.optionxform = str
    parser.read_file(io.StringIO(text))

    products: list[dict] = []
    for section in parser.sections():
        if section.startswith("<"):
            continue
        if parser.get(section, "disabled", fallback="0").strip() == "1":
            continue

        display_name = parser.get(section, "display_name", fallback=section).strip()
        aliases = split_csv(parser.get(section, "aliases", fallback=""))
        keywords = split_csv(parser.get(section, "keywords", fallback=""))
        search_terms = unique_ordered(
            [
                section,
                section.replace("_", " "),
                *extract_display_aliases(display_name),
                *aliases,
                *keywords,
            ]
        )

        products.append(
            {
                "id": section,
                "display_name": display_name,
                "status": parser.get(section, "status", fallback="").strip(),
                "category": parser.get(section, "category", fallback="").strip(),
                "subcategory": parser.get(section, "subcategory", fallback="").strip(),
                "description": parser.get(section, "description", fallback="").strip(),
                "value_proposition": parser.get(section, "value_proposition", fallback="").strip(),
                "addon": parser.get(section, "addon", fallback="").strip(),
                "addon_uid": parser.get(section, "addon_uid", fallback="").strip(),
                "addon_label": parser.get(section, "addon_label", fallback="").strip(),
                "app_viz": parser.get(section, "app_viz", fallback="").strip(),
                "app_viz_uid": parser.get(section, "app_viz_uid", fallback="").strip(),
                "app_viz_label": parser.get(section, "app_viz_label", fallback="").strip(),
                "app_viz_2": parser.get(section, "app_viz_2", fallback="").strip(),
                "prereq_apps": split_csv(parser.get(section, "prereq_apps", fallback="")),
                "prereq_labels": split_csv(parser.get(section, "prereq_labels", fallback="")),
                "dashboards": split_csv(parser.get(section, "dashboards", fallback="")),
                "sourcetypes": split_csv(parser.get(section, "sourcetypes", fallback="")),
                "aliases": aliases,
                "keywords": keywords,
                "learn_more_url": parser.get(section, "learn_more_url", fallback="").strip(),
                "search_terms": search_terms,
            }
        )

    return products


def security_cloud_template_check(product_key: str) -> dict:
    return {"contains": [f"# PRODUCT={product_key}"]}


def env_var_check(*names: str) -> dict:
    return {"env_vars": sorted(set(names))}


def ini_section_check(*names: str) -> dict:
    return {"ini_sections": sorted(set(names))}


def merge_template_checks(base: dict, extra: dict | None) -> dict:
    merged: dict[str, list[str]] = {}
    for source in (base, extra or {}):
        for key, values in source.items():
            merged[key] = sorted(set(merged.get(key, []) + list(values)))
    return merged


def sorted_unique(items: list[str]) -> list[str]:
    return sorted(set(item for item in items if item))


def normalize_secret_rules(rules: list[dict] | None) -> list[dict]:
    normalized: list[dict] = []
    for rule in rules or []:
        field = str(rule.get("field", "")).strip()
        value = str(rule.get("value", "")).strip()
        secret_keys = sorted_unique(list(rule.get("secret_keys", [])))
        if not field or not value or not secret_keys:
            continue
        normalized.append(
            {
                "field": field,
                "value": value,
                "secret_keys": secret_keys,
            }
        )
    return normalized


def build_security_cloud_product_route(
    product_key: str, security_products: dict, override: dict
) -> dict:
    meta = security_products[product_key]
    optional_keys = sorted_unique(list(meta.get("defaults", {}).keys()))
    accepted_non_secret = sorted_unique(["name", *meta.get("required_fields", []), *optional_keys])
    accepted_secret = sorted_unique(meta.get("secret_fields", []))
    required_secret = sorted_unique(meta.get("required_secret_fields", []))
    conditional_required_secret_rules = normalize_secret_rules(
        meta.get("conditional_required_secret_fields")
    )
    return {
        "route_type": "security_cloud_product",
        "primary_skill": "cisco-security-cloud-setup",
        "companion_skills": [],
        "install_apps": ["CiscoSecurityCloud"],
        "template_paths": [TEMPLATE_PATHS["security_cloud"]],
        "template_checks": merge_template_checks(
            security_cloud_template_check(product_key), override.get("template_checks")
        ),
        "required_non_secret_keys": sorted_unique(meta.get("required_fields", [])),
        "optional_non_secret_keys": optional_keys,
        "accepted_non_secret_keys": accepted_non_secret,
        "secret_keys": accepted_secret,
        "required_secret_keys": required_secret,
        "conditional_required_secret_rules": conditional_required_secret_rules,
        "route": {
            "product_key": product_key,
            "default_name": meta.get("default_name", ""),
            "defaults": meta.get("defaults", {}),
        },
    }


def build_security_cloud_variant_route(
    override: dict, security_products: dict
) -> dict:
    variant_key = override.get("variant_key", "variant")
    variants: dict[str, dict] = {}
    accepted_non_secret = {variant_key}
    accepted_secret: set[str] = set()
    template_checks = {}
    for variant, product_key in override["variants"].items():
        meta = security_products[product_key]
        optional_keys = sorted_unique(list(meta.get("defaults", {}).keys()))
        variants[variant] = {
            "product_key": product_key,
            "default_name": meta.get("default_name", ""),
            "defaults": meta.get("defaults", {}),
            "required_non_secret_keys": sorted_unique(meta.get("required_fields", [])),
            "optional_non_secret_keys": optional_keys,
            "secret_keys": sorted_unique(meta.get("secret_fields", [])),
            "required_secret_keys": sorted_unique(meta.get("required_secret_fields", [])),
            "conditional_required_secret_rules": normalize_secret_rules(
                meta.get("conditional_required_secret_fields")
            ),
        }
        accepted_non_secret.update(meta.get("required_fields", []))
        accepted_non_secret.update(optional_keys)
        accepted_non_secret.add("name")
        accepted_secret.update(meta.get("secret_fields", []))
        template_checks = merge_template_checks(
            template_checks, security_cloud_template_check(product_key)
        )

    return {
        "route_type": "security_cloud_variant",
        "primary_skill": "cisco-security-cloud-setup",
        "companion_skills": [],
        "install_apps": ["CiscoSecurityCloud"],
        "template_paths": [TEMPLATE_PATHS["security_cloud"]],
        "template_checks": merge_template_checks(template_checks, override.get("template_checks")),
        "required_non_secret_keys": [variant_key],
        "optional_non_secret_keys": sorted_unique(
            override.get("extra_required_non_secret_keys", [])
            + override.get("extra_optional_non_secret_keys", [])
        ),
        "accepted_non_secret_keys": sorted_unique(
            list(accepted_non_secret)
            + override.get("extra_required_non_secret_keys", [])
            + override.get("extra_optional_non_secret_keys", [])
        ),
        "secret_keys": sorted_unique(list(accepted_secret) + override.get("extra_secret_keys", [])),
        "route": {
            "variant_key": variant_key,
            "default_variant": override.get("default_variant", ""),
            "variants": variants,
        },
    }


def build_secure_access_route(override: dict) -> dict:
    extra_required = override.get("extra_required_non_secret_keys", [])
    extra_secret = override.get("extra_secret_keys", [])
    extra_optional = override.get("extra_optional_non_secret_keys", [])
    base_required = ["org_id", "base_url", "timezone", "storage_region"]
    base_optional = [
        "discover_org_id",
        "investigate_index",
        "privateapp_index",
        "appdiscovery_index",
        "search_interval",
        "refresh_rate",
        "dns_index",
        "proxy_index",
        "firewall_index",
        "dlp_index",
        "ravpn_index",
    ]
    base_secret = ["api_key", "api_secret"]
    template_vars = [
        "ORG_ID",
        "BASE_URL",
        "TIMEZONE",
        "STORAGE_REGION",
        "INVESTIGATE_INDEX",
        "PRIVATEAPP_INDEX",
        "APPDISCOVERY_INDEX",
        "SEARCH_INTERVAL",
        "REFRESH_RATE",
        "DNS_INDEX",
        "PROXY_INDEX",
        "FIREWALL_INDEX",
        "DLP_INDEX",
        "RAVPN_INDEX",
    ]
    if "cloudlock_name" in extra_required or "cloudlock_name" in extra_optional:
        template_vars.extend(
            [
                "CLOUDLOCK_NAME",
                "CLOUDLOCK_URL",
                "CLOUDLOCK_START_DATE",
                "CLOUDLOCK_SHOW_INCIDENT_DETAILS",
                "CLOUDLOCK_SHOW_UEBA",
            ]
        )
    return {
        "route_type": "secure_access",
        "primary_skill": "cisco-secure-access-setup",
        "companion_skills": [],
        "install_apps": ["cisco-cloud-security"],
        "template_paths": [TEMPLATE_PATHS["secure_access"]],
        "template_checks": merge_template_checks(
            env_var_check(*template_vars), override.get("template_checks")
        ),
        "required_non_secret_keys": sorted_unique(base_required + extra_required),
        "optional_non_secret_keys": sorted_unique(base_optional + extra_optional),
        "accepted_non_secret_keys": sorted_unique(base_required + base_optional + extra_required + extra_optional),
        "secret_keys": sorted_unique(base_secret + extra_secret),
        "route": {
            "apply_dashboard_defaults": True,
            "bootstrap_roles": True,
            "accept_terms": True,
        },
    }


def build_dc_networking_route(override: dict) -> dict:
    account_type = override["account_type"]
    required = ["name", "username", "device_ip" if account_type == "nexus9k" else "hostname"]
    optional = ["port", "proxy_enabled", "verify_ssl"]
    if account_type in {"aci", "nd"}:
        optional.extend(["auth_type", "login_domain"])
    return {
        "route_type": "dc_networking",
        "primary_skill": "cisco-dc-networking-setup",
        "companion_skills": [],
        "install_apps": ["cisco_dc_networking_app_for_splunk"],
        "template_paths": [TEMPLATE_PATHS["dc_networking"]],
        "template_checks": merge_template_checks(
            ini_section_check(DC_ACCOUNT_TEMPLATE_SECTION[account_type]),
            override.get("template_checks"),
        ),
        "required_non_secret_keys": sorted_unique(required),
        "optional_non_secret_keys": sorted_unique(optional),
        "accepted_non_secret_keys": sorted_unique(required + optional),
        "secret_keys": ["password"],
        "route": {
            "account_type": account_type,
            "default_name": DC_DEFAULT_NAMES[account_type],
            "default_index": DC_DEFAULT_INDEX[account_type],
            "input_type": account_type,
        },
    }


def build_catalyst_stack_route(override: dict) -> dict:
    account_type = override["account_type"]
    required = ["name", "host"]
    secret_keys = ["api_token"] if account_type == "cybervision" else ["password"]
    if account_type != "cybervision":
        required.append("username")
    optional = ["use_ca_cert", "verify_ssl"]
    return {
        "route_type": "catalyst_stack",
        "primary_skill": "cisco-catalyst-ta-setup",
        "companion_skills": ["cisco-enterprise-networking-setup"],
        "install_apps": ["cisco-catalyst-app"],
        "template_paths": [
            TEMPLATE_PATHS["catalyst"],
        ],
        "template_checks": merge_template_checks(
            ini_section_check(CATALYST_ACCOUNT_TEMPLATE_SECTION[account_type]),
            override.get("template_checks"),
        ),
        "required_non_secret_keys": sorted_unique(required),
        "optional_non_secret_keys": sorted_unique(optional),
        "accepted_non_secret_keys": sorted_unique(required + optional),
        "secret_keys": secret_keys,
        "route": {
            "account_type": account_type,
            "default_name": CATALYST_DEFAULT_NAMES[account_type],
            "default_index": CATALYST_DEFAULT_INDEX[account_type],
            "input_type": account_type,
        },
    }


def build_meraki_route(override: dict) -> dict:
    return {
        "route_type": "meraki",
        "primary_skill": "cisco-meraki-ta-setup",
        "companion_skills": ["cisco-enterprise-networking-setup"]
        if override.get("install_companion_app")
        else [],
        "install_apps": ["Splunk_TA_cisco_meraki"]
        + (["cisco-catalyst-app"] if override.get("install_companion_app") else []),
        "template_paths": [TEMPLATE_PATHS["meraki"]],
        "template_checks": merge_template_checks(
            ini_section_check("organization_account"),
            override.get("template_checks"),
        ),
        "required_non_secret_keys": ["name", "org_id"],
        "optional_non_secret_keys": ["region", "max_api_rate", "auto_inputs", "index"],
        "accepted_non_secret_keys": ["auto_inputs", "index", "max_api_rate", "name", "org_id", "region"],
        "secret_keys": ["api_key"],
        "route": {
            "default_name": "MERAKI_PROD",
            "default_index": "meraki",
            "install_companion_app": bool(override.get("install_companion_app")),
        },
    }


def build_intersight_route(override: dict) -> dict:
    return {
        "route_type": "intersight",
        "primary_skill": "cisco-intersight-setup",
        "companion_skills": [],
        "install_apps": ["Splunk_TA_Cisco_Intersight"],
        "template_paths": [TEMPLATE_PATHS["intersight"]],
        "template_checks": merge_template_checks(
            ini_section_check("intersight_account"),
            override.get("template_checks"),
        ),
        "required_non_secret_keys": ["name", "client_id"],
        "optional_non_secret_keys": ["hostname", "create_defaults"],
        "accepted_non_secret_keys": ["client_id", "create_defaults", "hostname", "name"],
        "secret_keys": ["client_secret"],
        "route": {
            "default_name": "INTERSIGHT_PROD",
            "default_index": "intersight",
        },
    }


def build_thousandeyes_route(override: dict) -> dict:
    return {
        "route_type": "thousandeyes",
        "primary_skill": "cisco-thousandeyes-setup",
        "companion_skills": [],
        "install_apps": ["ta_cisco_thousandeyes"],
        "template_paths": [TEMPLATE_PATHS["thousandeyes"]],
        "template_checks": merge_template_checks(
            ini_section_check("thousandeyes_account"),
            override.get("template_checks"),
        ),
        "required_non_secret_keys": ["account_group"],
        "optional_non_secret_keys": [
            "account",
            "index",
            "input_type",
            "hec_token",
            "pathvis_enabled",
            "pathvis_index",
            "pathvis_interval",
            "poll_interval",
            "poll_timeout",
        ],
        "accepted_non_secret_keys": [
            "account",
            "account_group",
            "hec_token",
            "index",
            "input_type",
            "pathvis_enabled",
            "pathvis_index",
            "pathvis_interval",
            "poll_interval",
            "poll_timeout",
        ],
        "secret_keys": [],
        "route": {
            "default_input_type": "all",
            "default_index": "thousandeyes_metrics",
            "default_hec_token": "thousandeyes",
        },
    }


def build_appdynamics_route(override: dict) -> dict:
    return {
        "route_type": "appdynamics",
        "primary_skill": "cisco-appdynamics-setup",
        "companion_skills": [],
        "install_apps": ["Splunk_TA_AppDynamics"],
        "template_paths": [TEMPLATE_PATHS["appdynamics"]],
        "template_checks": merge_template_checks(
            ini_section_check("controller_account"),
            override.get("template_checks"),
        ),
        "required_non_secret_keys": ["name", "controller_url", "client_name"],
        "optional_non_secret_keys": ["create_inputs", "index"],
        "accepted_non_secret_keys": ["client_name", "controller_url", "create_inputs", "index", "name"],
        "secret_keys": ["client_secret"],
        "route": {
            "default_name": "PROD",
            "default_index": "appdynamics",
            "default_create_inputs": "recommended",
        },
    }


def build_route(product: dict, override: dict, security_products: dict) -> dict:
    route_type = override["route_type"]
    if route_type == "security_cloud_product":
        return build_security_cloud_product_route(override["product_key"], security_products, override)
    if route_type == "security_cloud_variant":
        return build_security_cloud_variant_route(override, security_products)
    if route_type == "secure_access":
        return build_secure_access_route(override)
    if route_type == "dc_networking":
        return build_dc_networking_route(override)
    if route_type == "catalyst_stack":
        return build_catalyst_stack_route(override)
    if route_type == "meraki":
        return build_meraki_route(override)
    if route_type == "intersight":
        return build_intersight_route(override)
    if route_type == "thousandeyes":
        return build_thousandeyes_route(override)
    if route_type == "appdynamics":
        return build_appdynamics_route(override)
    raise ValueError(f"Unknown route_type for {product['id']}: {route_type}")


def generic_manual_gap_reason(product: dict) -> str:
    detail = []
    if product["addon"]:
        detail.append(f"addon {product['addon']}")
    if product["app_viz"]:
        detail.append(f"viz app {product['app_viz']}")
    if detail:
        joined = " and ".join(detail)
        return (
            f"No cisco-product-setup route is defined yet for this product's "
            f"{joined}."
        )
    return "No local setup route is defined for this product yet."


def build_catalog(scan_package: Path) -> dict:
    overrides = load_json(OVERRIDES_PATH).get("products", {})
    security_products = load_json(SECURITY_CLOUD_PRODUCTS_PATH)
    registry = load_json(REGISTRY_PATH)
    known_skills = {entry["skill"] for entry in registry["skill_topologies"]}
    known_apps = {entry["app_name"] for entry in registry["apps"]}

    products = []
    for product in load_scan_products(scan_package):
        override = overrides.get(product["id"], {})
        state_override = override.get("automation_state", "")

        if state_override:
            automation_state = state_override
        elif "route_type" in override:
            automation_state = "automated"
        elif product["status"] in {"retired", "deprecated"}:
            automation_state = "unsupported_legacy"
        elif product["status"] == "roadmap":
            automation_state = "unsupported_roadmap"
        else:
            automation_state = "manual_gap"

        entry = {
            **product,
            "search_terms": unique_ordered(product["search_terms"]),
            "normalized_search_terms": unique_ordered([normalize(term) for term in product["search_terms"]]),
            "automation_state": automation_state,
            "primary_skill": "",
            "companion_skills": [],
            "install_apps": [],
            "template_paths": [],
            "template_checks": {},
            "required_non_secret_keys": [],
            "optional_non_secret_keys": [],
            "accepted_non_secret_keys": [],
            "secret_keys": [],
            "required_secret_keys": [],
            "conditional_required_secret_rules": [],
            "route_type": "",
            "route": {},
            "notes": override.get("notes", ""),
            "manual_gap_reason": "",
        }

        if automation_state == "automated":
            route_meta = build_route(product, override, security_products)
            entry.update(
                {
                    "primary_skill": route_meta["primary_skill"],
                    "companion_skills": route_meta["companion_skills"],
                    "install_apps": route_meta["install_apps"],
                    "template_paths": route_meta["template_paths"],
                    "template_checks": route_meta["template_checks"],
                    "required_non_secret_keys": route_meta["required_non_secret_keys"],
                    "optional_non_secret_keys": route_meta["optional_non_secret_keys"],
                    "accepted_non_secret_keys": route_meta["accepted_non_secret_keys"],
                    "secret_keys": route_meta["secret_keys"],
                    "required_secret_keys": route_meta.get("required_secret_keys", []),
                    "conditional_required_secret_rules": route_meta.get(
                        "conditional_required_secret_rules", []
                    ),
                    "route_type": route_meta["route_type"],
                    "route": route_meta["route"],
                }
            )
        elif automation_state == "manual_gap":
            entry["manual_gap_reason"] = override.get(
                "manual_gap_reason", generic_manual_gap_reason(product)
            )
        elif automation_state == "unsupported_legacy":
            entry["manual_gap_reason"] = (
                "This product is retired or deprecated in the SCAN catalog."
            )
        elif automation_state == "unsupported_roadmap":
            entry["manual_gap_reason"] = (
                "This product is a roadmap / coverage-gap item in the SCAN catalog."
            )

        for skill_name in [entry["primary_skill"], *entry["companion_skills"]]:
            if skill_name and skill_name not in known_skills:
                raise ValueError(f"Unknown skill in product catalog: {skill_name}")
        for app_name in entry["install_apps"]:
            if app_name not in known_apps:
                raise ValueError(f"Unknown install app in product catalog: {app_name}")

        products.append(entry)

    products.sort(key=lambda item: (item["display_name"].lower(), item["id"]))

    catalog = {
        "description": GENERATED_BANNER,
        "scan_package": scan_package.name,
        "product_count": len(products),
        "products": products,
    }

    validate_catalog(catalog)
    return catalog


def validate_ini_sections(path: Path, names: list[str]) -> None:
    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")
    existing = set(parser.sections())
    for name in names:
        if name not in existing:
            raise ValueError(f"Template {path.relative_to(REPO_ROOT)} missing INI section {name}")


def validate_env_vars(path: Path, names: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    for name in names:
        if not re.search(rf"(?m)^\s*#?\s*{re.escape(name)}=", text):
            raise ValueError(f"Template {path.relative_to(REPO_ROOT)} missing env var {name}")


def validate_contains(path: Path, snippets: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    for snippet in snippets:
        if snippet not in text:
            raise ValueError(
                f"Template {path.relative_to(REPO_ROOT)} missing marker {snippet!r}"
            )


def validate_catalog(catalog: dict) -> None:
    products = catalog["products"]
    ids = {product["id"] for product in products}
    if len(ids) != len(products):
        raise ValueError("Duplicate product IDs in generated catalog.")

    for product in products:
        if product["automation_state"] != "automated":
            continue
        if not product["primary_skill"]:
            raise ValueError(f"Automated product missing primary skill: {product['id']}")
        if not product["install_apps"]:
            raise ValueError(f"Automated product missing install apps: {product['id']}")
        for rel_path in product["template_paths"]:
            template_path = REPO_ROOT / rel_path
            if not template_path.is_file():
                raise ValueError(f"Template path not found: {rel_path}")
            checks = product.get("template_checks", {})
            if checks.get("ini_sections"):
                validate_ini_sections(template_path, checks["ini_sections"])
            if checks.get("env_vars"):
                validate_env_vars(template_path, checks["env_vars"])
            if checks.get("contains"):
                validate_contains(template_path, checks["contains"])


def render_catalog(catalog: dict) -> str:
    return json.dumps(catalog, indent=2, sort_keys=True) + "\n"


def main() -> int:
    args = parse_args()
    scan_package = find_scan_package(args.scan_package)
    catalog = build_catalog(scan_package)
    rendered = render_catalog(catalog)

    if args.check:
        current = CATALOG_PATH.read_text(encoding="utf-8") if CATALOG_PATH.exists() else ""
        if current != rendered:
            print(
                "skills/cisco-product-setup/catalog.json is out of date. Run "
                "`python3 skills/cisco-product-setup/scripts/build_catalog.py --write`."
            )
            return 1
        return 0

    CATALOG_PATH.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

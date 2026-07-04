#!/usr/bin/env python3
"""Build the product-setup catalog from SCAN plus local overrides."""

from __future__ import annotations

import argparse
import configparser
import hashlib
import io
import json
import re
import tarfile
import urllib.request
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit


REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_ROOT = REPO_ROOT / "skills/cisco-product-setup"
CATALOG_PATH = SKILL_ROOT / "catalog.json"
OVERRIDES_PATH = SKILL_ROOT / "catalog_overrides.json"
SCAN_SOURCE_MANIFEST_PATH = SKILL_ROOT / "scan_source.json"
SCAN_SOURCE_FIXTURE_PATH = SKILL_ROOT / "scan_products.fixture.json"
SCAN_SOURCE_URL = "https://is4s.s3.amazonaws.com/scan/products.conf"
SCAN_SOURCE_SCHEMA_VERSION = 1
SCAN_GLOB = "splunk-cisco-app-navigator-*.tar.gz"
SCAN_APP_CONF_MEMBER = "splunk-cisco-app-navigator/default/app.conf"
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
    "spaces": "skills/cisco-spaces-setup/template.example",
    "webex": "skills/cisco-webex-setup/template.example",
    "ucs_ta": "skills/cisco-ucs-ta-setup/template.example",
    "secure_email_web_gateway": "skills/cisco-secure-email-web-gateway-setup/template.example",
    "talos_intelligence": "skills/cisco-talos-intelligence-setup/template.example",
    "asa_ta": "skills/cisco-asa-ta-setup/template.example",
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
    "Generated from the pinned normalized SCAN catalog source plus "
    "skills/cisco-product-setup/catalog_overrides.json local overrides and "
    "synthetic products."
)

SCAN_STRING_FIELDS = (
    "id",
    "display_name",
    "status",
    "category",
    "subcategory",
    "description",
    "value_proposition",
    "addon",
    "addon_uid",
    "addon_label",
    "app_viz",
    "app_viz_uid",
    "app_viz_label",
    "app_viz_2",
    "learn_more_url",
)
SCAN_LIST_FIELDS = (
    "prereq_apps",
    "prereq_labels",
    "dashboards",
    "sourcetypes",
    "aliases",
    "keywords",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Verify catalog.json is up to date.")
    mode.add_argument("--write", action="store_true", help="Write catalog.json.")
    mode.add_argument(
        "--check-live-source",
        action="store_true",
        help="Compare the pinned SCAN source provenance with the live public catalog.",
    )
    parser.add_argument(
        "--scan-package",
        default="",
        help=(
            "Optional explicit SCAN tarball for one-off comparison output. "
            "Normal builds use the pinned normalized source fixture."
        ),
    )
    parser.add_argument(
        "--refresh-source",
        action="store_true",
        help=(
            "Fetch the public SCAN products.conf, refresh the normalized source "
            "fixture and provenance manifest, then rebuild catalog.json. Requires --write."
        ),
    )
    parser.add_argument(
        "--source-url",
        default=SCAN_SOURCE_URL,
        help=argparse.SUPPRESS,
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


def scan_app_version(scan_package: Path) -> str:
    if not scan_package.is_file():
        return ""

    try:
        with tarfile.open(scan_package, "r:gz") as archive:
            raw = archive.extractfile(SCAN_APP_CONF_MEMBER)
            if raw is None:
                return ""
            text = raw.read().decode("utf-8")
    except (OSError, tarfile.TarError, UnicodeDecodeError):
        return ""

    parser = configparser.ConfigParser(strict=False)
    parser.optionxform = str
    try:
        parser.read_file(io.StringIO(text))
    except configparser.Error:
        return ""

    return parser.get(
        "id",
        "version",
        fallback=parser.get("launcher", "version", fallback=""),
    ).strip()


def version_sort_tuple(raw: str) -> tuple[int, ...]:
    # Only dotted decimal versions (e.g. "1.2.3", "1.0") are sortable as
    # numeric tuples here. Pre-release suffixes ("1.2.3-rc1", "1.0a2") fall
    # through to an empty tuple by design; callers (e.g. scan_package_sort_key)
    # then fall back to the filename regex which still uses dotted decimals,
    # so a "1.2.3-rc1" SCAN package sorts immediately after "1.2.3" by name.
    if not re.fullmatch(r"\d+(?:\.\d+)+", raw):
        return ()
    return tuple(int(part) for part in raw.split("."))


def scan_package_sort_key(path: Path) -> tuple[tuple[int, ...], str]:
    app_version = scan_app_version(path)
    version = version_sort_tuple(app_version)
    if not version:
        match = re.search(r"(\d+(?:\.\d+)+)", path.name)
        version = version_sort_tuple(match.group(1)) if match else ()
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


def product_search_terms(product: dict) -> list[str]:
    display_name = str(product.get("display_name") or product.get("id", ""))
    addon = str(product.get("addon", ""))
    app_viz = str(product.get("app_viz", ""))
    app_viz_2 = str(product.get("app_viz_2", ""))
    return unique_ordered(
        [
            str(product.get("id", "")),
            str(product.get("id", "")).replace("_", " "),
            *extract_display_aliases(display_name),
            *list(product.get("aliases", [])),
            *list(product.get("keywords", [])),
            addon,
            addon.replace("_", " ").replace("-", " "),
            str(product.get("addon_label", "")),
            app_viz,
            app_viz.replace("_", " ").replace("-", " "),
            str(product.get("app_viz_label", "")),
            app_viz_2,
            app_viz_2.replace("_", " ").replace("-", " "),
        ]
    )


def scan_product(values: dict) -> dict:
    product = {field: str(values.get(field, "")).strip() for field in SCAN_STRING_FIELDS}
    for field in SCAN_LIST_FIELDS:
        raw = values.get(field, [])
        if not isinstance(raw, list):
            raise ValueError(f"SCAN product {product['id'] or '<unknown>'}: {field} must be a list")
        product[field] = [str(item).strip() for item in raw if str(item).strip()]

    display_name = product["display_name"] or product["id"]
    product["display_name"] = display_name
    product["search_terms"] = product_search_terms(product)
    if not product["id"]:
        raise ValueError("SCAN source contains a product without an id")
    return product


def parse_scan_products(text: str) -> list[dict]:
    parser = configparser.ConfigParser(strict=False)
    parser.optionxform = str
    parser.read_file(io.StringIO(text))

    products: list[dict] = []
    for section in parser.sections():
        if section.startswith("<"):
            continue
        if parser.get(section, "disabled", fallback="0").strip() == "1":
            continue

        products.append(
            scan_product(
                {
                "id": section,
                "display_name": parser.get(section, "display_name", fallback=section),
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
                "aliases": split_csv(parser.get(section, "aliases", fallback="")),
                "keywords": split_csv(parser.get(section, "keywords", fallback="")),
                "learn_more_url": parser.get(section, "learn_more_url", fallback="").strip(),
                }
            )
        )

    return products


def load_scan_products(scan_package: Path) -> list[dict]:
    with tarfile.open(scan_package, "r:gz") as archive:
        raw = archive.extractfile(SCAN_PRODUCTS_MEMBER)
        if raw is None:
            raise SystemExit(f"{SCAN_PRODUCTS_MEMBER} not found in {scan_package.name}")
        text = raw.read().decode("utf-8")
    return parse_scan_products(text)


def sanitized_scan_product(product: dict) -> dict:
    return {
        field: product[field]
        for field in (*SCAN_STRING_FIELDS, *SCAN_LIST_FIELDS)
        if product.get(field) not in ("", [], {})
    }


def render_scan_fixture(products: list[dict]) -> str:
    payload = {
        "schema_version": SCAN_SOURCE_SCHEMA_VERSION,
        "products": [sanitized_scan_product(product) for product in products],
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def parse_scan_source_header(text: str) -> tuple[str, str]:
    catalog_match = re.search(r"(?m)^#\s*version\s*=\s*(\S+)\s*$", text)
    minimum_match = re.search(r"(?m)^#\s*min_app_version\s*=\s*(\S+)\s*$", text)
    if not catalog_match or not minimum_match:
        raise ValueError("SCAN products.conf is missing version or min_app_version provenance")
    return catalog_match.group(1), minimum_match.group(1)


def fetch_scan_source(source_url: str) -> bytes:
    if source_url != SCAN_SOURCE_URL:
        raise ValueError(f"SCAN source URL must be the canonical {SCAN_SOURCE_URL}")
    requested = urlsplit(source_url)
    if requested.scheme.lower() != "https" or not requested.hostname:
        raise ValueError("SCAN source URL must use HTTPS")
    requested_origin = (requested.scheme.lower(), requested.hostname.lower(), requested.port or 443)
    request = urllib.request.Request(
        source_url,
        headers={"User-Agent": "splunk-cisco-skills/catalog-source-refresh"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        final = urlsplit(response.geturl())
        final_origin = (final.scheme.lower(), (final.hostname or "").lower(), final.port or 443)
        if final_origin != requested_origin:
            raise ValueError("SCAN source redirect changed origin")
        source_payload = response.read(5_000_001)
    if len(source_payload) > 5_000_000:
        raise ValueError("SCAN products.conf exceeds the 5 MB source limit")
    return source_payload


def refresh_scan_source(source_url: str) -> None:
    source_payload = fetch_scan_source(source_url)
    text = source_payload.decode("utf-8")
    catalog_version, minimum_scan_version = parse_scan_source_header(text)
    products = parse_scan_products(text)
    fixture_text = render_scan_fixture(products)
    fixture_payload = fixture_text.encode("utf-8")
    manifest = {
        "schema_version": SCAN_SOURCE_SCHEMA_VERSION,
        "source": {
            "kind": "scan_public_catalog",
            "url": source_url,
            "catalog_version": catalog_version,
            "minimum_scan_version": minimum_scan_version,
            "sha256": sha256_bytes(source_payload),
            "retrieved_date": date.today().isoformat(),
        },
        "fixture": {
            "path": SCAN_SOURCE_FIXTURE_PATH.name,
            "sha256": sha256_bytes(fixture_payload),
            "product_count": len(products),
            "normalization": (
                "Parsed SCAN product fields consumed by build_catalog.py; comments, "
                "disabled stanzas, and unused vendor package files are excluded."
            ),
        },
    }
    SCAN_SOURCE_FIXTURE_PATH.write_text(fixture_text, encoding="utf-8")
    SCAN_SOURCE_MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def check_live_scan_source(source_url: str) -> bool:
    manifest = load_json(SCAN_SOURCE_MANIFEST_PATH)
    expected = manifest.get("source")
    if not isinstance(expected, dict):
        raise ValueError("SCAN source manifest must contain a source object")
    validate_scan_source_metadata(expected)
    _, pinned_catalog_source = load_scan_source_fixture()
    expected_fixture_sha = pinned_catalog_source["normalized_fixture_sha256"]
    source_payload = fetch_scan_source(source_url)
    text = source_payload.decode("utf-8")
    catalog_version, minimum_scan_version = parse_scan_source_header(text)
    live_products = parse_scan_products(text)
    normalized_fixture_sha = sha256_bytes(
        render_scan_fixture(live_products).encode("utf-8")
    )
    actual = {
        "catalog_version": catalog_version,
        "minimum_scan_version": minimum_scan_version,
        "sha256": sha256_bytes(source_payload),
    }
    drift = {
        field: {"pinned": expected.get(field), "live": value}
        for field, value in actual.items()
        if expected.get(field) != value
    }
    if expected_fixture_sha != normalized_fixture_sha:
        drift["normalized_fixture_sha256"] = {
            "pinned": expected_fixture_sha,
            "live": normalized_fixture_sha,
        }
    if drift:
        print(json.dumps({"ok": False, "source_url": source_url, "drift": drift}, indent=2))
        return False
    print(
        json.dumps(
            {
                "ok": True,
                "source_url": source_url,
                **actual,
                "normalized_fixture_sha256": normalized_fixture_sha,
                "normalized_product_count": len(live_products),
            },
            indent=2,
        )
    )
    return True


def validate_scan_source_metadata(source_meta: dict) -> None:
    if source_meta.get("kind") != "scan_public_catalog":
        raise ValueError("SCAN source provenance kind must be scan_public_catalog")
    if source_meta.get("url") != SCAN_SOURCE_URL:
        raise ValueError(f"SCAN source provenance URL must be {SCAN_SOURCE_URL}")

    retrieved_date = source_meta.get("retrieved_date")
    if not isinstance(retrieved_date, str):
        raise ValueError("SCAN source provenance retrieved_date must use YYYY-MM-DD")
    try:
        parsed_retrieved_date = date.fromisoformat(retrieved_date)
    except ValueError as exc:
        raise ValueError(
            "SCAN source provenance retrieved_date must be a valid YYYY-MM-DD date"
        ) from exc
    if parsed_retrieved_date.isoformat() != retrieved_date:
        raise ValueError("SCAN source provenance retrieved_date must use canonical YYYY-MM-DD")


def load_scan_source_fixture() -> tuple[list[dict], dict]:
    manifest = load_json(SCAN_SOURCE_MANIFEST_PATH)
    if manifest.get("schema_version") != SCAN_SOURCE_SCHEMA_VERSION:
        raise ValueError("Unsupported SCAN source manifest schema_version")

    fixture_meta = manifest.get("fixture")
    source_meta = manifest.get("source")
    if not isinstance(fixture_meta, dict) or not isinstance(source_meta, dict):
        raise ValueError("SCAN source manifest must contain source and fixture objects")
    fixture_name = str(fixture_meta.get("path", "")).strip()
    fixture_path = (SKILL_ROOT / fixture_name).resolve()
    if not fixture_name or fixture_path.parent != SKILL_ROOT.resolve():
        raise ValueError("SCAN source fixture path must be a file in cisco-product-setup")
    fixture_payload = fixture_path.read_bytes()
    expected_fixture_sha = str(fixture_meta.get("sha256", "")).strip()
    actual_fixture_sha = sha256_bytes(fixture_payload)
    if not re.fullmatch(r"[0-9a-f]{64}", expected_fixture_sha):
        raise ValueError("SCAN source fixture SHA-256 is missing or invalid")
    if actual_fixture_sha != expected_fixture_sha:
        raise ValueError(
            f"SCAN source fixture checksum mismatch: {actual_fixture_sha} != {expected_fixture_sha}"
        )

    fixture = json.loads(fixture_payload)
    if fixture.get("schema_version") != SCAN_SOURCE_SCHEMA_VERSION:
        raise ValueError("Unsupported SCAN source fixture schema_version")
    raw_products = fixture.get("products")
    if not isinstance(raw_products, list) or not all(
        isinstance(product, dict) for product in raw_products
    ):
        raise ValueError("SCAN source fixture products must be a list of objects")
    products = [scan_product(product) for product in raw_products]
    if len(products) != fixture_meta.get("product_count"):
        raise ValueError("SCAN source fixture product_count does not match fixture contents")
    product_ids = [product["id"] for product in products]
    if len(product_ids) != len(set(product_ids)):
        raise ValueError("SCAN source fixture contains duplicate product IDs")

    validate_scan_source_metadata(source_meta)
    for field in ("catalog_version", "minimum_scan_version", "sha256"):
        if not str(source_meta.get(field, "")).strip():
            raise ValueError(f"SCAN source provenance is missing {field}")
    if not re.fullmatch(r"[0-9a-f]{64}", str(source_meta["sha256"])):
        raise ValueError("SCAN source SHA-256 is invalid")

    catalog_source = dict(source_meta)
    catalog_source.update(
        {
            "normalized_fixture": fixture_name,
            "normalized_fixture_sha256": actual_fixture_sha,
        }
    )
    return products, catalog_source


def load_scan_package_source(scan_package: Path) -> tuple[list[dict], dict]:
    package_payload = scan_package.read_bytes()
    return load_scan_products(scan_package), {
        "kind": "scan_package",
        "package": scan_package.name,
        "app_version": scan_app_version(scan_package),
        "sha256": sha256_bytes(package_payload),
    }


def synthetic_product_entry(raw: dict) -> dict:
    product_id = str(raw["id"]).strip()
    display_name = str(raw.get("display_name", product_id)).strip()
    aliases = [str(item).strip() for item in raw.get("aliases", []) if str(item).strip()]
    keywords = [str(item).strip() for item in raw.get("keywords", []) if str(item).strip()]
    addon = str(raw.get("addon", "")).strip()
    addon_label = str(raw.get("addon_label", "")).strip()
    app_viz = str(raw.get("app_viz", "")).strip()
    app_viz_label = str(raw.get("app_viz_label", "")).strip()
    app_viz_2 = str(raw.get("app_viz_2", "")).strip()
    product = {
        "id": product_id,
        "display_name": display_name,
        "status": str(raw.get("status", "active")).strip(),
        "category": str(raw.get("category", "")).strip(),
        "subcategory": str(raw.get("subcategory", "")).strip(),
        "description": str(raw.get("description", "")).strip(),
        "value_proposition": str(raw.get("value_proposition", "")).strip(),
        "addon": addon,
        "addon_uid": str(raw.get("addon_uid", "")).strip(),
        "addon_label": addon_label,
        "app_viz": app_viz,
        "app_viz_uid": str(raw.get("app_viz_uid", "")).strip(),
        "app_viz_label": app_viz_label,
        "app_viz_2": app_viz_2,
        "prereq_apps": list(raw.get("prereq_apps", [])),
        "prereq_labels": list(raw.get("prereq_labels", [])),
        "dashboards": list(raw.get("dashboards", [])),
        "sourcetypes": list(raw.get("sourcetypes", [])),
        "aliases": aliases,
        "keywords": keywords,
        "learn_more_url": str(raw.get("learn_more_url", "")).strip(),
    }
    product["search_terms"] = product_search_terms(product)
    return product


def apply_product_metadata_override(product: dict, override: dict) -> dict:
    """Overlay local routing labels without mutating the pinned SCAN fixture."""
    effective = dict(product)
    display_name = str(override.get("display_name", "")).strip()
    if display_name:
        effective["display_name"] = display_name

    for field in ("aliases", "keywords"):
        additions = override.get(f"{field}_add", []) or []
        if not isinstance(additions, list):
            raise ValueError(f"{product['id']}: {field}_add must be a list")
        effective[field] = unique_ordered(
            [*list(product.get(field, [])), *[str(item) for item in additions]]
        )

    if "sourcetypes_override" in override:
        sourcetypes = override.get("sourcetypes_override") or []
        if not isinstance(sourcetypes, list):
            raise ValueError(f"{product['id']}: sourcetypes_override must be a list")
        effective["sourcetypes"] = unique_ordered([str(item) for item in sourcetypes])

    effective["search_terms"] = product_search_terms(effective)
    return effective


def load_synthetic_products(overrides_doc: dict) -> list[dict]:
    products = []
    for raw in overrides_doc.get("synthetic_products", []) or []:
        if not isinstance(raw, dict) or not raw.get("id"):
            raise ValueError("Synthetic products must be objects with an id.")
        products.append(synthetic_product_entry(raw))
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
        "required_secret_keys": [],
        "conditional_required_secret_rules": [],
        "route": {
            "variant_key": variant_key,
            "default_variant": override.get("default_variant", ""),
            "variants": variants,
        },
    }


def build_asa_ta_route(override: dict) -> dict:
    defaults = {
        "index": "cisco_asa",
        "sourcetype": "cisco:asa",
        "syslog_owner": "sc4s",
        "sc4s_vendor_product": "cisco_asa",
        "include_ftd": "true",
    }
    defaults.update(
        {
            str(key): str(value)
            for key, value in (override.get("defaults", {}) or {}).items()
        }
    )
    optional = sorted(defaults)
    return {
        "route_type": "asa_ta",
        "primary_skill": "cisco-asa-ta-setup",
        "companion_skills": [],
        "install_apps": ["Splunk_TA_cisco-asa"],
        "template_paths": [TEMPLATE_PATHS["asa_ta"]],
        "template_checks": merge_template_checks(
            {
                "contains": [
                    "index: cisco_asa",
                    "sourcetype: cisco:asa",
                    "syslog_owner: sc4s",
                ]
            },
            override.get("template_checks"),
        ),
        "required_non_secret_keys": [],
        "optional_non_secret_keys": optional,
        "accepted_non_secret_keys": optional,
        "secret_keys": [],
        "required_secret_keys": [],
        "conditional_required_secret_rules": [],
        "route": {
            "default_index": defaults["index"],
            "default_sourcetype": defaults["sourcetype"],
            "default_syslog_owner": defaults["syslog_owner"],
            "default_sc4s_vendor_product": defaults["sc4s_vendor_product"],
            "default_include_ftd": defaults["include_ftd"],
            "defaults": defaults,
            "sourcetypes": [defaults["sourcetype"]],
            "handoff": (
                "Install the ASA TA and render the selected external syslog receiver "
                "handoff; completion requires live cisco:asa event evidence."
            ),
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
        "install_apps": ["TA-cisco-cloud-security-addon", "cisco-cloud-security"],
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


def build_app_install_only_route(product: dict, override: dict) -> dict:
    install_apps = unique_ordered(list(override.get("install_apps", [])))
    if not install_apps:
        install_apps = unique_ordered([product.get("addon", ""), product.get("app_viz", "")])
    handoff = override.get(
        "handoff",
        "Install and validate the listed app(s), then complete product-specific "
        "input setup in the app UI or vendor-supported workflow.",
    )
    return {
        "route_type": "app_install_only",
        "primary_skill": "splunk-app-install",
        "companion_skills": [],
        "install_apps": install_apps,
        "template_paths": [],
        "template_checks": {},
        "required_non_secret_keys": [],
        "optional_non_secret_keys": [],
        "accepted_non_secret_keys": [],
        "secret_keys": [],
        "required_secret_keys": [],
        "conditional_required_secret_rules": [],
        "route": {
            "configuration": "manual",
            "validation": "installed_apps",
            "handoff": handoff,
        },
    }


def build_workflow_handoff_route(product: dict, override: dict) -> dict:
    primary_skill = override["primary_skill"]
    companion_skills = unique_ordered(list(override.get("companion_skills", [])))
    workflow_scripts = unique_ordered(list(override.get("workflow_scripts", [])))
    install_apps = unique_ordered(list(override.get("install_apps", [])))
    sourcetypes = unique_ordered(list(product.get("sourcetypes", [])))
    handoff = override.get(
        "handoff",
        "Use the listed workflow scripts to render/apply collector assets, then "
        "validate the product sourcetypes in Splunk.",
    )
    return {
        "route_type": "workflow_handoff",
        "primary_skill": primary_skill,
        "companion_skills": companion_skills,
        "install_apps": install_apps,
        "template_paths": list(override.get("template_paths", [])),
        "template_checks": dict(override.get("template_checks", {})),
        "required_non_secret_keys": sorted_unique(list(override.get("required_non_secret_keys", []))),
        "optional_non_secret_keys": sorted_unique(list(override.get("optional_non_secret_keys", []))),
        "accepted_non_secret_keys": sorted_unique(
            list(override.get("required_non_secret_keys", []))
            + list(override.get("optional_non_secret_keys", []))
        ),
        "secret_keys": sorted_unique(list(override.get("secret_keys", []))),
        "required_secret_keys": sorted_unique(list(override.get("required_secret_keys", []))),
        "conditional_required_secret_rules": list(
            override.get("conditional_required_secret_rules", [])
        ),
        "route": {
            "handoff": handoff,
            "sourcetypes": sourcetypes,
            "workflow_scripts": workflow_scripts,
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
        "install_apps": ["TA_cisco_catalyst", "cisco-catalyst-app"],
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
        # `verify_ssl` is exposed for self-hosted Intersight Virtual
        # Appliance deployments that use a private CA / self-signed cert.
        # Public intersight.com SaaS users do not need to set it.
        "optional_non_secret_keys": ["hostname", "create_defaults", "verify_ssl"],
        "accepted_non_secret_keys": ["client_id", "create_defaults", "hostname", "name", "verify_ssl"],
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
            "alert_rules",
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
            "alert_rules",
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
        # `verify_ssl` is exposed because AppDynamics controllers can be
        # self-hosted with self-signed TLS certs; SaaS controllers do not
        # need to set it.
        "optional_non_secret_keys": ["create_inputs", "index", "verify_ssl"],
        "accepted_non_secret_keys": ["client_name", "controller_url", "create_inputs", "index", "name", "verify_ssl"],
        "secret_keys": ["client_secret"],
        "route": {
            "default_name": "PROD",
            "default_index": "appdynamics",
            "default_create_inputs": "recommended",
        },
    }


def build_spaces_route(override: dict) -> dict:
    return {
        "route_type": "spaces",
        "primary_skill": "cisco-spaces-setup",
        "companion_skills": [],
        "install_apps": ["ta_cisco_spaces"],
        "template_paths": [TEMPLATE_PATHS["spaces"]],
        "template_checks": merge_template_checks(
            ini_section_check("meta_stream"),
            override.get("template_checks"),
        ),
        "required_non_secret_keys": ["name", "region"],
        "optional_non_secret_keys": ["auto_inputs", "location_updates_status", "index"],
        "accepted_non_secret_keys": ["auto_inputs", "index", "location_updates_status", "name", "region"],
        "secret_keys": ["activation_token"],
        "required_secret_keys": ["activation_token"],
        "route": {
            "default_name": "production",
            "default_index": "cisco_spaces",
            "default_auto_inputs": "true",
        },
    }


def build_webex_route(override: dict) -> dict:
    return {
        "route_type": "webex",
        "primary_skill": "cisco-webex-setup",
        "companion_skills": [],
        "install_apps": ["ta_cisco_webex_add_on_for_splunk", "cisco_webex_meetings_app_for_splunk"],
        "template_paths": [TEMPLATE_PATHS["webex"]],
        "template_checks": merge_template_checks(
            ini_section_check("account"),
            override.get("template_checks"),
        ),
        "required_non_secret_keys": ["name", "client_id", "scope"],
        "optional_non_secret_keys": [
            "account_region",
            "auto_inputs",
            "calling_index",
            "contact_center_index",
            "endpoint",
            "end_time",
            "gov_api_reference_link",
            "input_type",
            "instance_url",
            "interval",
            "is_gov_account",
            "locations",
            "loglevel",
            "meetings_index",
            "method",
            "org_id",
            "proxy_enabled",
            "proxy_port",
            "proxy_rdns",
            "proxy_type",
            "proxy_url",
            "proxy_username",
            "query_params",
            "query_template",
            "request_body",
            "redirect_url",
            "site_url",
            "start_time",
            "webex_base_url",
            "webex_contact_center_region",
            "webex_endpoint",
        ],
        "accepted_non_secret_keys": [
            "account_region",
            "auto_inputs",
            "calling_index",
            "client_id",
            "contact_center_index",
            "endpoint",
            "end_time",
            "gov_api_reference_link",
            "input_type",
            "instance_url",
            "interval",
            "is_gov_account",
            "locations",
            "loglevel",
            "meetings_index",
            "method",
            "name",
            "org_id",
            "proxy_enabled",
            "proxy_port",
            "proxy_rdns",
            "proxy_type",
            "proxy_url",
            "proxy_username",
            "query_params",
            "query_template",
            "request_body",
            "redirect_url",
            "scope",
            "site_url",
            "start_time",
            "webex_base_url",
            "webex_contact_center_region",
            "webex_endpoint",
        ],
        "secret_keys": ["client_secret", "access_token", "refresh_token", "proxy_password"],
        "required_secret_keys": ["client_secret"],
        "route": {
            "default_name": "WEBEX_PROD",
            "default_meetings_index": "wx",
            "default_calling_index": "wxc",
            "default_contact_center_index": "wxcc",
            "default_input_type": "core",
            "default_endpoint": "webexapis.com",
        },
    }


def build_ucs_ta_route(override: dict) -> dict:
    return {
        "route_type": "ucs_ta",
        "primary_skill": "cisco-ucs-ta-setup",
        "companion_skills": [],
        "install_apps": ["Splunk_TA_cisco-ucs"],
        "template_paths": [TEMPLATE_PATHS["ucs_ta"]],
        "template_checks": merge_template_checks(
            ini_section_check("server"),
            override.get("template_checks"),
        ),
        "required_non_secret_keys": ["name", "server_url", "account_name"],
        "optional_non_secret_keys": [
            "create_default_task",
            "description",
            "disable_ssl_verification",
            "index",
            "interval",
            "sourcetype",
            "task_name",
            "templates",
        ],
        "accepted_non_secret_keys": [
            "account_name",
            "create_default_task",
            "description",
            "disable_ssl_verification",
            "index",
            "interval",
            "name",
            "server_url",
            "sourcetype",
            "task_name",
            "templates",
        ],
        "secret_keys": ["account_password"],
        "required_secret_keys": ["account_password"],
        "route": {
            "default_name": "UCS_PROD",
            "default_index": "cisco_ucs",
            "default_interval": "300",
            "default_sourcetype": "cisco:ucs",
            "default_templates": "UCS_Fault,UCS_Inventory,UCS_Performance",
        },
    }


def build_secure_email_web_gateway_route(product: dict, override: dict) -> dict:
    product_id = product.get("id", "")
    if product_id == "cisco_esa":
        product_key = "esa"
        install_apps = ["Splunk_TA_cisco-esa"]
    elif product_id == "cisco_wsa":
        product_key = "wsa"
        install_apps = ["Splunk_TA_cisco-wsa"]
    else:
        product_key = override.get("product", "both")
        install_apps = list(override.get("install_apps", ["Splunk_TA_cisco-esa", "Splunk_TA_cisco-wsa"]))
    return {
        "route_type": "secure_email_web_gateway",
        "primary_skill": "cisco-secure-email-web-gateway-setup",
        "companion_skills": ["splunk-connect-for-syslog-setup"],
        "install_apps": install_apps,
        "template_paths": [TEMPLATE_PATHS["secure_email_web_gateway"]],
        "template_checks": merge_template_checks(
            ini_section_check("products"),
            override.get("template_checks"),
        ),
        "required_non_secret_keys": [],
        "optional_non_secret_keys": ["esa_index", "wsa_index", "render_handoff"],
        "accepted_non_secret_keys": ["esa_index", "render_handoff", "wsa_index"],
        "secret_keys": [],
        "required_secret_keys": [],
        "route": {
            "product": product_key,
            "default_esa_index": "email",
            "default_wsa_index": "netproxy",
            "handoff": "Use splunk-connect-for-syslog-setup for SC4S runtime deployment; this route prepares Splunk-side indexes, macros, parser packages, and optional handoff snippets.",
        },
    }


def build_talos_intelligence_route(override: dict) -> dict:
    return {
        "route_type": "talos_intelligence",
        "primary_skill": "cisco-talos-intelligence-setup",
        "companion_skills": ["splunk-enterprise-security-config"],
        "install_apps": ["Splunk_TA_Talos_Intelligence"],
        "template_paths": [TEMPLATE_PATHS["talos_intelligence"]],
        "template_checks": merge_template_checks(
            ini_section_check("deployment"),
            override.get("template_checks"),
        ),
        "required_non_secret_keys": [],
        "optional_non_secret_keys": ["enable_ip_blacklist", "index"],
        "accepted_non_secret_keys": ["enable_ip_blacklist", "index"],
        "secret_keys": ["service_account"],
        "required_secret_keys": [],
        "route": {
            "default_index": "talos_intelligence",
            "default_enable_ip_blacklist": "false",
            "support_posture": "Enterprise Security Cloud 7.3.2+; non-FedRAMP; service account material is normally Splunk Cloud-provisioned.",
        },
    }


def build_route(product: dict, override: dict, security_products: dict) -> dict:
    route_type = override["route_type"]
    if route_type == "security_cloud_product":
        return build_security_cloud_product_route(override["product_key"], security_products, override)
    if route_type == "security_cloud_variant":
        return build_security_cloud_variant_route(override, security_products)
    if route_type == "asa_ta":
        return build_asa_ta_route(override)
    if route_type == "secure_access":
        return build_secure_access_route(override)
    if route_type == "app_install_only":
        return build_app_install_only_route(product, override)
    if route_type == "workflow_handoff":
        return build_workflow_handoff_route(product, override)
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
    if route_type == "spaces":
        return build_spaces_route(override)
    if route_type == "webex":
        return build_webex_route(override)
    if route_type == "ucs_ta":
        return build_ucs_ta_route(override)
    if route_type == "secure_email_web_gateway":
        return build_secure_email_web_gateway_route(product, override)
    if route_type == "talos_intelligence":
        return build_talos_intelligence_route(override)
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


def build_catalog(scan_package: Path | None = None) -> dict:
    overrides_doc = load_json(OVERRIDES_PATH)
    overrides = overrides_doc.get("products", {})
    security_products = load_json(SECURITY_CLOUD_PRODUCTS_PATH)
    registry = load_json(REGISTRY_PATH)
    known_skills = {entry["skill"] for entry in registry["skill_topologies"]}
    known_apps = {entry["app_name"] for entry in registry["apps"]}

    products = []
    if scan_package is None:
        scan_products, scan_source = load_scan_source_fixture()
    else:
        scan_products, scan_source = load_scan_package_source(scan_package)
    source_products = scan_products + load_synthetic_products(overrides_doc)
    for product in source_products:
        override = overrides.get(product["id"], {})
        product = apply_product_metadata_override(product, override)
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

        if automation_state in {"automated", "partial"} and "route_type" in override:
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
        elif automation_state == "no_plans_available":
            entry["manual_gap_reason"] = override.get(
                "manual_gap_reason",
                "No verified local setup workflow is available for this product yet.",
            )
        elif automation_state == "unsupported_legacy":
            entry["manual_gap_reason"] = (
                override.get(
                    "manual_gap_reason",
                    "This product is retired or deprecated in the SCAN catalog.",
                )
            )
        elif automation_state == "unsupported_roadmap":
            entry["manual_gap_reason"] = (
                override.get(
                    "manual_gap_reason",
                    "This product is a roadmap / coverage-gap item in the SCAN catalog.",
                )
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
        "product_count": len(products),
        "products": products,
        "scan_source": scan_source,
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
    if args.check_live_source:
        if args.scan_package or args.refresh_source:
            raise SystemExit("--check-live-source cannot be combined with source mutation options")
        return 0 if check_live_scan_source(args.source_url) else 1
    if args.refresh_source and not args.write:
        raise SystemExit("--refresh-source requires --write")
    if args.refresh_source and args.scan_package:
        raise SystemExit("--refresh-source cannot be combined with --scan-package")
    if args.write and args.scan_package:
        raise SystemExit(
            "--write cannot be combined with --scan-package; use the pinned fixture or "
            "refresh it with --refresh-source --write"
        )
    if args.refresh_source:
        refresh_scan_source(args.source_url)

    scan_package = find_scan_package(args.scan_package) if args.scan_package else None
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

    if args.write:
        CATALOG_PATH.write_text(rendered, encoding="utf-8")
        return 0

    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

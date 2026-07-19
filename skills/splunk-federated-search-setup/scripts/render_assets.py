#!/usr/bin/env python3
"""Render Splunk Federated Search assets.

Supports the full Splunk Federated Search product surface:

- Federated Search for Splunk (FSS2S, type=splunk) in standard or transparent
  mode, with multiple providers per render and one or more federated indexes
  per provider.
- Legacy Federated Search for Amazon S3 (FSS3, type=aws_s3, Splunk Cloud
  Platform only), rendered as payload-shaped inventory/migration evidence with
  explicit Splunk 10.5 phased-deprecation guidance. No legacy CRUD is emitted.
- Data Management app federation handoffs for current Amazon S3,
  Microsoft Azure, Azure Databricks, Snowflake, and DDSS connection/dataset
  workflows, including Glue, Iceberg REST, Splunk-native catalog, Delta Lake,
  Iceberg, JSON, and Parquet distinctions. These are readiness handoffs, not
  legacy provider payloads.
- Dedicated handoff-only coverage for Amazon Security Lake Federated Analytics
  (type=aws_lake) and Cisco Security Analytics and Logging federation
  (type=aws_s3_sal). The renderer never masquerades either as generic aws_s3
  and does not invent provider, subscriber, dataset, or index CRUD.
- File-based apply for Splunk Enterprise standalone search heads, a fail-closed
  SHC deployer bundle handoff, plus an FSS2S-only REST apply path that works on
  both Splunk Enterprise and Splunk Cloud Platform.
- Global federated-search enable/disable through
  /services/data/federated/settings/general.
- Live status helper that probes connectivityStatus per provider.

Spec input is either a YAML/JSON file (--spec) or repeated --provider /
--federated-index CLI flags for back-compat with single-provider workflows.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GENERATED_FILES = {
    "README.md",
    "metadata.json",
    "data-management-federation-handoff.md",
    "specialized-federation-handoff.md",
    "legacy-fss3-migration.md",
    "federated.conf.template",
    "indexes.conf",
    "server.conf",
    "preflight.sh",
    "apply-search-head.sh",
    "apply-shc-deployer.sh",
    "apply-rest.sh",
    "status.sh",
    "global-enable.sh",
    "global-disable.sh",
}

S2S_DATASET_TYPES = ("index", "metricindex", "savedsearch", "lastjob", "datamodel")
FSS3_DATASET_TYPES = ("glue_table",)
ALL_DATASET_TYPES = S2S_DATASET_TYPES + FSS3_DATASET_TYPES
EMBEDDED_PRIVATE_SECRET_READER = r'''def read_private_secret(path_value, label):
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "geteuid"):
        raise SystemExit(
            f"ERROR: {label} cannot be read safely: O_NOFOLLOW/geteuid is unavailable"
        )
    path = Path(path_value).expanduser()
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise SystemExit(
            f"ERROR: {label} must be a readable, non-symlink regular file: {path}: {exc}"
        )
    try:
        before = os.fstat(descriptor)
        mode = stat.S_IMODE(before.st_mode)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise SystemExit(f"ERROR: {label} must be a single-link regular file: {path}")
        if before.st_uid != os.geteuid():
            raise SystemExit(f"ERROR: {label} must be owned by the current user: {path}")
        if mode & 0o077:
            raise SystemExit(
                f"ERROR: {label} permissions must be 0600 or stricter: {path} has {mode:04o}"
            )
        if not 1 <= before.st_size <= 65536:
            raise SystemExit(
                f"ERROR: {label} size must be between 1 and 65536 bytes: {path}"
            )
        chunks = []
        remaining = 65537
        while remaining:
            chunk = os.read(descriptor, min(remaining, 8192))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        data = b"".join(chunks)
        before_fingerprint = (
            before.st_dev, before.st_ino, before.st_mode, before.st_uid, before.st_size,
            before.st_mtime_ns, before.st_ctime_ns, before.st_nlink,
        )
        after_fingerprint = (
            after.st_dev, after.st_ino, after.st_mode, after.st_uid, after.st_size,
            after.st_mtime_ns, after.st_ctime_ns, after.st_nlink,
        )
        if before_fingerprint != after_fingerprint or len(data) != before.st_size:
            raise SystemExit(f"ERROR: {label} changed while it was read: {path}")
    finally:
        os.close(descriptor)
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise SystemExit(f"ERROR: {label} must contain UTF-8 text: {path}: {exc}")
    if len(lines) != 1 or "\x00" in lines[0] or not lines[0].strip():
        raise SystemExit(
            f"ERROR: {label} must contain exactly one non-empty line: {path}"
        )
    return lines[0].strip()
'''
FEDERATED_SEARCH_OVERVIEW_URL = "https://help.splunk.com/en/splunk-cloud-platform/search/federated-search/10.5.2605/welcome-to-splunk-federated-search/overview-of-the-federated-search-options-for-the-splunk-platform"
AMAZON_S3_OVERVIEW_URL = "https://help.splunk.com/en/splunk-cloud-platform/search/federated-search/10.5.2605/run-federated-searches-over-amazon-s3-datasets/overview-of-federated-search-for-amazon-s3"
AMAZON_SECURITY_LAKE_URL = "https://help.splunk.com/en/splunk-cloud-platform/search/federated-search/10.5.2605/ingest-and-search-amazon-security-lake-datasets/about-federated-analytics"
FEDERATED_CONF_URL = "https://help.splunk.com/en/splunk-enterprise/administer/admin-manual/10.4/configuration-file-reference/10.4.0-configuration-file-reference/federated.conf"
S3_DATA_CATALOG_OPTIONS = [
    {
        "key": "aws_glue",
        "label": "AWS Glue catalog table",
        "formats": ["apache_iceberg", "delta_lake", "non_table_json_or_parquet"],
        "ownership": "customer_managed",
        "notes": "The Glue table must reference the selected S3 location. Iceberg and Delta are table formats; non-table datasets use JSON or Parquet files.",
        "source_url": AMAZON_S3_OVERVIEW_URL,
    },
    {
        "key": "iceberg_rest",
        "label": "Apache Iceberg REST catalog",
        "formats": ["apache_iceberg"],
        "ownership": "customer_managed",
        "notes": "The S3 connection records the catalog URL. Current public documentation does not support Iceberg REST catalogs that require authorization.",
        "source_url": AMAZON_S3_OVERVIEW_URL,
    },
    {
        "key": "splunk_native",
        "label": "Splunk-native data catalog",
        "formats": ["inferred_or_operator_defined_schema_and_partitions"],
        "ownership": "splunk_managed",
        "notes": "Splunk can crawl the dataset to infer schema and partitions, or the operator can define them manually. Data-routing-plus-search datasets use a Splunk-native catalog.",
        "source_url": AMAZON_S3_OVERVIEW_URL,
    },
]
DATA_MANAGEMENT_FEDERATION_HANDOFFS = [
    {
        "key": "amazon_s3_data_management",
        "label": "Federated Search for Amazon S3 through the Data Management app",
        "stage": "available by activation",
        "lifecycle": "available_by_activation",
        "automation": "ui_handoff",
        "configuration_surface": "data_management_connection_and_dataset",
        "availability": "Splunk Cloud Platform deployments in AWS regions",
        "activation": "Contact Splunk sales for activation; existing FSS3/Federated Analytics customers can have a tenant-specific access path.",
        "dataset_model": "Data Management app connections and datasets; datasets can support federated search and, where documented, data routing.",
        "notes": "Use Data Management for new Amazon S3 federation. Legacy `aws_s3` definitions in this renderer are payload-shaped inventory and migration evidence only; no legacy CRUD is emitted.",
        "source_url": AMAZON_S3_OVERVIEW_URL,
    },
    {
        "key": "microsoft_azure",
        "label": "Federated Search for Microsoft Azure",
        "stage": "available by activation",
        "lifecycle": "available_by_activation",
        "automation": "ui_handoff",
        "configuration_surface": "data_management_connection_and_dataset",
        "availability": "Splunk Cloud Platform deployments in AWS regions",
        "activation": "Contact Splunk sales for activation and confirm target-tenant commercial terms before building the connection.",
        "dataset_model": "Data Management app connection plus datasets over Azure Data Lake Storage and Azure Blob Storage containers.",
        "notes": "Azure datasets can be federated-search-only or data-routing-plus-federated-search when the tenant supports the documented Data Management workflow.",
        "source_url": FEDERATED_SEARCH_OVERVIEW_URL,
    },
    {
        "key": "azure_databricks",
        "label": "Federated Search for Azure Databricks",
        "stage": "available by activation",
        "lifecycle": "available_by_activation",
        "automation": "ui_handoff",
        "configuration_surface": "data_management_connection_and_dataset",
        "availability": "Splunk Cloud Platform deployments in AWS regions",
        "activation": "Contact Splunk sales for activation; existing FSS3/Federated Analytics users apply through the documented access path.",
        "dataset_model": "Data Management app connection using Azure Databricks Delta Sharing to Unity Catalog schemas and tables.",
        "notes": "Searches use SPL2. This renderer does not create Databricks Delta Sharing credentials or Unity Catalog datasets.",
        "source_url": FEDERATED_SEARCH_OVERVIEW_URL,
    },
    {
        "key": "snowflake",
        "label": "Federated Search for Snowflake",
        "stage": "available by activation in Splunk Cloud 10.5",
        "lifecycle": "available_by_activation",
        "automation": "ui_handoff",
        "configuration_surface": "data_management_connection_and_dataset",
        "availability": "Splunk Cloud Platform deployments in AWS regions; Snowflake warehouses must run on AWS",
        "activation": "Contact Splunk sales for activation; confirm any applicable commercial entitlement without assuming a universal Data Scan Unit model.",
        "dataset_model": "Data Management app connection for one Snowflake warehouse/database/schema plus datasets backed by tables or views.",
        "notes": "Require USAGE on the warehouse, database, and schema; a Splunk-region IPv4 ingress network rule and Snowflake network policy; a service-user authentication policy; and a programmatic access token kept outside this repo.",
        "source_url": FEDERATED_SEARCH_OVERVIEW_URL,
    },
    {
        "key": "ddss",
        "label": "Federated Search for DDSS",
        "stage": "available by activation in Splunk Cloud 10.5",
        "lifecycle": "available_by_activation",
        "automation": "ui_handoff",
        "configuration_surface": "data_management_dataset",
        "availability": "Splunk Cloud Platform deployments in AWS regions with DDSS data stored in Amazon S3",
        "activation": "Contact Splunk sales for activation; confirm any applicable commercial entitlement without assuming a universal Data Scan Unit model.",
        "dataset_model": "Data Management app DDSS dataset identified by a configured S3 bucket path and its associated DDSS index.",
        "notes": "Require an SQS queue, S3 event notification, and the generated S3 bucket and SQS queue policies. Current federated search does not support DDSS locations in Azure or GCP.",
        "source_url": FEDERATED_SEARCH_OVERVIEW_URL,
    },
]
SPECIALIZED_FEDERATION_HANDOFFS = [
    {
        "key": "amazon_security_lake_federated_analytics",
        "label": "Federated Analytics for Amazon Security Lake",
        "provider_type": "aws_lake",
        "stage": "available by activation",
        "lifecycle": "available_by_activation",
        "automation": "ui_handoff",
        "availability": "Splunk Cloud Platform deployments in AWS regions; Amazon Security Lake and Splunk Cloud must be in the same AWS region",
        "activation": "Contact Splunk sales to activate Federated Analytics, then use the documented Amazon Security Lake provider workflow.",
        "dataset_model": "A dedicated `aws_lake` provider coordinates local data lake indexes for recent threat detection and federated indexes for historical threat hunting over OCSF datasets.",
        "notes": "Do not represent Federated Analytics as a generic `aws_s3` provider. This renderer emits a readiness handoff only and does not create Amazon Security Lake subscribers, data lake indexes, or federated indexes.",
        "source_url": AMAZON_SECURITY_LAKE_URL,
    },
    {
        "key": "cisco_security_analytics_and_logging",
        "label": "Federated Search for Cisco Security Analytics and Logging (FS-SAL)",
        "provider_type": "aws_s3_sal",
        "stage": "documented provider type; tenant availability requires confirmation",
        "lifecycle": "documented_conditional",
        "automation": "ui_handoff",
        "availability": "Cisco SAL and Splunk tenant, licensing, region, and supported onboarding dependent",
        "activation": "Confirm the supported Cisco SAL federation onboarding path with Cisco and Splunk before configuration.",
        "dataset_model": "A dedicated `aws_s3_sal` provider represents Cisco Security Analytics and Logging federation.",
        "notes": "Do not substitute a generic `aws_s3` provider. The public configuration reference identifies `aws_s3_sal`, but this repo does not have a stable customer-facing CRUD contract for creating it.",
        "source_url": FEDERATED_CONF_URL,
    },
]
SPECIALIZED_HANDOFF_BY_TYPE = {
    item["provider_type"]: item for item in SPECIALIZED_FEDERATION_HANDOFFS
}
LEGACY_FSS3_LIFECYCLE = {
    "key": "legacy_fss3_provider_payload",
    "provider_type": "aws_s3",
    "lifecycle": "legacy_phased_deprecation",
    "automation": "rendered_migration_evidence_only",
    "preferred_replacement": "Federated Search for Amazon S3 through Data Management app connections and datasets",
    "guidance": "Inventory existing legacy providers, recreate access through the current Data Management connection/dataset model, validate equivalent SPL2 searches and RBAC, then retire the legacy provider only after cutover evidence is complete.",
    "source_url": FEDERATED_CONF_URL,
}

PASSWORD_PLACEHOLDER_PREFIX = "__FEDERATED_PASSWORD_FILE_BASE64__"


class SpecError(SystemExit):
    """Raised when the operator-supplied spec is invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(f"ERROR: {message}")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class S2SProvider:
    name: str
    host_port: str
    service_account: str
    password_file: str
    mode: str = "standard"
    app_context: str = "search"
    disabled: bool = False

    @property
    def use_fsh_knowledge_objects(self) -> str:
        # Splunk forces useFSHKnowledgeObjects to 0 for standard, 1 for
        # transparent regardless of operator input. Render the documented
        # value so btool output matches expectations.
        return "1" if self.mode == "transparent" else "0"


@dataclass
class FSS3Provider:
    name: str
    aws_account_id: str
    aws_region: str
    database: str
    data_catalog: str
    aws_glue_tables_allowlist: list[str] = field(default_factory=list)
    aws_s3_paths_allowlist: list[str] = field(default_factory=list)
    aws_kms_keys_arn_allowlist: list[str] = field(default_factory=list)
    disabled: bool = False


@dataclass
class SpecializedProviderHandoff:
    name: str
    provider_type: str
    disabled: bool = False


@dataclass
class FederatedIndex:
    name: str
    provider: str
    dataset_type: str
    dataset_name: str
    disabled: bool = False


@dataclass
class Spec:
    splunk_home: str
    app_name: str
    federated_search_enabled: bool
    max_preview_generation_duration: int
    max_preview_generation_inputcount: int
    shc_replication: bool
    restart_splunk: bool
    s2s_providers: list[S2SProvider]
    fss3_providers: list[FSS3Provider]
    specialized_provider_handoffs: list[SpecializedProviderHandoff]
    federated_indexes: list[FederatedIndex]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def shell_quote(value: object) -> str:
    return shlex.quote(str(value))


def make_script(body: str) -> str:
    return "#!/usr/bin/env bash\nset -euo pipefail\n\n" + body.lstrip()


def enterprise_version_gate(spec: Spec) -> str:
    helper = shell_quote(
        Path(__file__).resolve().parents[2]
        / "shared/lib/platform_version_helpers.sh"
    )
    splunk_home = shell_quote(spec.splunk_home)
    return f'''platform_version_helpers="${{SPLUNK_PLATFORM_VERSION_HELPERS:-{helper}}}"
[[ -r "${{platform_version_helpers}}" ]] || {{ echo "ERROR: platform version helper is missing: ${{platform_version_helpers}}" >&2; exit 1; }}
# shellcheck disable=SC1090
source "${{platform_version_helpers}}"
enterprise_version="$(spv_require_supported_splunk_home {splunk_home})"
echo "PASS: supported Splunk Enterprise runtime ${{enterprise_version}}."
'''


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def clean_render_dir(render_dir: Path) -> None:
    for rel in GENERATED_FILES:
        candidate = render_dir / rel
        if candidate.is_file() or candidate.is_symlink():
            candidate.unlink()
    aws_dir = render_dir / "aws-s3-providers"
    if aws_dir.is_dir():
        for child in aws_dir.iterdir():
            if child.is_file():
                child.unlink()


def boolish(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y", "on"}:
        return True
    if text in {"false", "0", "no", "n", "off"}:
        return False
    return default


def parse_int(value: Any, *, label: str, minimum: int = 0) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise SpecError(f"{label} must be an integer (got {value!r}).") from exc
    if parsed < minimum:
        raise SpecError(f"{label} must be >= {minimum} (got {parsed}).")
    return parsed


def list_of_str(value: Any, *, label: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        # Allow comma-separated CLI usage: "a,b,c".
        return [item.strip() for item in value.split(",") if item.strip()]
    if not isinstance(value, list):
        raise SpecError(f"{label} must be a list (got {type(value).__name__}).")
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            out.append(text)
    return out


def no_newline(value: str, label: str) -> None:
    if "\n" in value or "\r" in value:
        raise SpecError(f"{label} must not contain newlines.")


def validate_provider_name(name: str, *, label: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name or ""):
        raise SpecError(
            f"{label} '{name}' must contain only letters, numbers, underscores, and hyphens."
        )


def validate_index_name(name: str, *, label: str) -> None:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,2047}", name or ""):
        raise SpecError(
            f"{label} '{name}' must start with a lowercase letter or number and contain "
            "lowercase letters, numbers, underscores, or hyphens."
        )
    if "kvstore" in name:
        raise SpecError(f"{label} must not contain 'kvstore'.")


def validate_host_port(host_port: str, *, label: str) -> None:
    if not re.fullmatch(r"[^:\s]+:[0-9]{1,5}", host_port or ""):
        raise SpecError(f"{label} must look like host:management_port (got {host_port!r}).")
    port = int(host_port.rsplit(":", 1)[1])
    if port < 1 or port > 65535:
        raise SpecError(f"{label} port must be between 1 and 65535 (got {port}).")


def validate_aws_account_id(value: str, *, label: str) -> None:
    if not re.fullmatch(r"[0-9]{12}", value or ""):
        raise SpecError(f"{label} must be a 12-digit AWS account ID (got {value!r}).")


def validate_aws_region(value: str, *, label: str) -> None:
    if not re.fullmatch(r"[a-z0-9-]+", value or ""):
        raise SpecError(f"{label} must contain lowercase letters, digits, and hyphens.")


def validate_glue_database(value: str, *, label: str) -> None:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", value or ""):
        raise SpecError(
            f"{label} must contain only lowercase letters, numbers, underscores, and hyphens."
        )


def validate_glue_arn(value: str, *, label: str) -> None:
    if not value.startswith("arn:aws:glue:") or ":catalog" not in value:
        raise SpecError(f"{label} must be an AWS Glue Data Catalog ARN (arn:aws:glue:...:catalog).")


def validate_kms_arn(value: str, *, label: str) -> None:
    if not value.startswith("arn:aws:kms:"):
        raise SpecError(f"{label} entries must be AWS KMS key ARNs (arn:aws:kms:...).")


def validate_s3_path(value: str, *, label: str) -> None:
    if not value.startswith("s3://"):
        raise SpecError(f"{label} entries must be Amazon S3 URIs (s3://...).")
    # FSS3 explicitly rejects file-terminated paths and leading/trailing whitespace.
    if "\n" in value or "\r" in value:
        raise SpecError(f"{label} must not contain newlines.")


# ---------------------------------------------------------------------------
# Spec loading
# ---------------------------------------------------------------------------


def load_spec_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in {".json"}:
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise SpecError(f"Spec file is not valid JSON: {exc}") from exc
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError as exc:
        raise SpecError(
            "YAML spec files require PyYAML. Install repo dependencies with "
            "`python3 -m pip install -r requirements-agent.txt`, or use a JSON spec."
        ) from exc
    try:
        return yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise SpecError(f"Spec file is not valid YAML: {exc}") from exc


def parse_kv_pairs(text: str, *, label: str) -> dict[str, Any]:
    """Parse a key=value comma-separated string (CLI repeated-flag form).

    Lists use semicolons inside a value: paths=s3://a/;s3://b/
    """
    pairs: dict[str, Any] = {}
    for token in text.split(","):
        token = token.strip()
        if not token:
            continue
        if "=" not in token:
            raise SpecError(f"{label} fragment '{token}' must be key=value.")
        key, value = token.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise SpecError(f"{label} fragment '{token}' has empty key.")
        if ";" in value:
            pairs[key] = [item.strip() for item in value.split(";") if item.strip()]
        else:
            pairs[key] = value
    return pairs


# ---------------------------------------------------------------------------
# Spec normalization
# ---------------------------------------------------------------------------


def _normalize_s2s(raw: dict[str, Any], known_provider_names: set[str]) -> S2SProvider:
    name = str(raw.get("name") or "").strip()
    validate_provider_name(name, label="S2S provider name")
    if name in known_provider_names:
        raise SpecError(f"Duplicate provider name: {name}")
    mode = str(raw.get("mode") or "standard").strip().lower()
    if mode not in {"standard", "transparent"}:
        raise SpecError(f"S2S provider {name} mode must be standard or transparent.")
    host_port = str(raw.get("host_port") or raw.get("hostPort") or "").strip()
    validate_host_port(host_port, label=f"S2S provider {name} host_port")
    service_account = str(raw.get("service_account") or raw.get("serviceAccount") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.@:-]+", service_account or ""):
        raise SpecError(f"S2S provider {name} service_account contains unsupported characters.")
    password_file = str(raw.get("password_file") or "").strip()
    no_newline(password_file, f"S2S provider {name} password_file")
    app_context = str(raw.get("app_context") or raw.get("appContext") or "search").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", app_context):
        raise SpecError(f"S2S provider {name} app_context contains unsupported characters.")
    return S2SProvider(
        name=name,
        host_port=host_port,
        service_account=service_account,
        password_file=password_file,
        mode=mode,
        app_context=app_context,
        disabled=boolish(raw.get("disabled"), default=False),
    )


def _normalize_fss3(raw: dict[str, Any], known_provider_names: set[str]) -> FSS3Provider:
    name = str(raw.get("name") or "").strip()
    validate_provider_name(name, label="FSS3 provider name")
    if name in known_provider_names:
        raise SpecError(f"Duplicate provider name: {name}")
    aws_account_id = str(raw.get("aws_account_id") or raw.get("awsAccountId") or "").strip()
    validate_aws_account_id(aws_account_id, label=f"FSS3 provider {name} aws_account_id")
    aws_region = str(raw.get("aws_region") or raw.get("awsRegion") or "").strip()
    validate_aws_region(aws_region, label=f"FSS3 provider {name} aws_region")
    database = str(raw.get("database") or "").strip()
    validate_glue_database(database, label=f"FSS3 provider {name} database")
    data_catalog = str(raw.get("data_catalog") or raw.get("dataCatalog") or "").strip()
    validate_glue_arn(data_catalog, label=f"FSS3 provider {name} data_catalog")
    glue_tables = list_of_str(
        raw.get("aws_glue_tables_allowlist") or raw.get("awsGlueTablesAllowlist"),
        label=f"FSS3 provider {name} aws_glue_tables_allowlist",
    )
    if not glue_tables:
        raise SpecError(
            f"FSS3 provider {name} must list at least one Glue table in aws_glue_tables_allowlist."
        )
    for table in glue_tables:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", table):
            raise SpecError(
                f"FSS3 provider {name} Glue table '{table}' must contain only lowercase "
                "letters, digits, underscores, and hyphens."
            )
    s3_paths = list_of_str(
        raw.get("aws_s3_paths_allowlist") or raw.get("awsS3PathsAllowlist"),
        label=f"FSS3 provider {name} aws_s3_paths_allowlist",
    )
    if not s3_paths:
        raise SpecError(
            f"FSS3 provider {name} must list at least one S3 location in aws_s3_paths_allowlist."
        )
    for path in s3_paths:
        validate_s3_path(path, label=f"FSS3 provider {name} aws_s3_paths_allowlist entry")
    kms_keys = list_of_str(
        raw.get("aws_kms_keys_arn_allowlist") or raw.get("awsKmsKeysArnAllowlist"),
        label=f"FSS3 provider {name} aws_kms_keys_arn_allowlist",
    )
    for kms in kms_keys:
        validate_kms_arn(kms, label=f"FSS3 provider {name} aws_kms_keys_arn_allowlist entry")
    return FSS3Provider(
        name=name,
        aws_account_id=aws_account_id,
        aws_region=aws_region,
        database=database,
        data_catalog=data_catalog,
        aws_glue_tables_allowlist=glue_tables,
        aws_s3_paths_allowlist=s3_paths,
        aws_kms_keys_arn_allowlist=kms_keys,
        disabled=boolish(raw.get("disabled"), default=False),
    )


def _normalize_specialized_handoff(
    raw: dict[str, Any], known_provider_names: set[str]
) -> SpecializedProviderHandoff:
    name = str(raw.get("name") or "").strip()
    validate_provider_name(name, label="specialized federation handoff name")
    if name in known_provider_names:
        raise SpecError(f"Duplicate provider name: {name}")
    provider_type = str(raw.get("type") or "").strip().lower()
    if provider_type not in SPECIALIZED_HANDOFF_BY_TYPE:
        raise SpecError(
            f"Specialized federation handoff {name} type must be one of "
            f"{tuple(SPECIALIZED_HANDOFF_BY_TYPE)} (got {provider_type!r})."
        )
    return SpecializedProviderHandoff(
        name=name,
        provider_type=provider_type,
        disabled=boolish(raw.get("disabled"), default=False),
    )


def _normalize_index(
    raw: dict[str, Any],
    s2s_providers: list[S2SProvider],
    fss3_providers: list[FSS3Provider],
    specialized_provider_handoffs: list[SpecializedProviderHandoff],
) -> FederatedIndex:
    name = str(raw.get("name") or "").strip()
    validate_index_name(name, label="federated index name")
    provider = str(raw.get("provider") or "").strip()
    if not provider:
        raise SpecError(f"federated index {name} requires a provider name.")
    s2s_lookup = {p.name: p for p in s2s_providers}
    fss3_lookup = {p.name: p for p in fss3_providers}
    specialized_lookup = {p.name: p for p in specialized_provider_handoffs}
    if provider in specialized_lookup:
        provider_type = specialized_lookup[provider].provider_type
        raise SpecError(
            f"federated index {name} references handoff-only provider '{provider}' "
            f"(type={provider_type}). This repo has no stable public CRUD contract "
            "for that provider's dataset or index objects; review "
            "specialized-federation-handoff.md instead."
        )
    if provider not in s2s_lookup and provider not in fss3_lookup:
        raise SpecError(
            f"federated index {name} references unknown provider '{provider}'. "
            f"Known providers: {sorted(set(s2s_lookup) | set(fss3_lookup) | set(specialized_lookup))}"
        )
    dataset_type = str(raw.get("dataset_type") or raw.get("datasetType") or "").strip()
    if dataset_type not in ALL_DATASET_TYPES:
        raise SpecError(
            f"federated index {name} dataset_type must be one of {ALL_DATASET_TYPES} "
            f"(got {dataset_type!r})."
        )
    dataset_name = str(raw.get("dataset_name") or raw.get("datasetName") or "").strip()
    if not dataset_name:
        raise SpecError(f"federated index {name} requires dataset_name.")
    no_newline(dataset_name, f"federated index {name} dataset_name")
    # Cross-mode validation:
    if provider in s2s_lookup:
        owning = s2s_lookup[provider]
        if owning.mode == "transparent":
            raise SpecError(
                f"federated index {name} references transparent-mode provider '{provider}'. "
                "Transparent mode does not use federated indexes."
            )
        if dataset_type not in S2S_DATASET_TYPES:
            raise SpecError(
                f"federated index {name} on FSS2S provider '{provider}' must use one of "
                f"{S2S_DATASET_TYPES} dataset types."
            )
    else:  # FSS3 provider
        if dataset_type != "glue_table":
            raise SpecError(
                f"federated index {name} on FSS3 provider '{provider}' must use "
                "dataset_type=glue_table."
            )
        owning_fss3 = fss3_lookup[provider]
        if dataset_name not in owning_fss3.aws_glue_tables_allowlist:
            raise SpecError(
                f"federated index {name} dataset_name '{dataset_name}' is not in the "
                f"aws_glue_tables_allowlist for FSS3 provider '{provider}'."
            )
    return FederatedIndex(
        name=name,
        provider=provider,
        dataset_type=dataset_type,
        dataset_name=dataset_name,
        disabled=boolish(raw.get("disabled"), default=False),
    )


def normalize_spec(raw: dict[str, Any]) -> Spec:
    if not isinstance(raw, dict):
        raise SpecError("Spec must be a mapping at the top level.")
    splunk_home = str(raw.get("splunk_home") or "/opt/splunk").strip()
    app_name = str(raw.get("app_name") or "ZZZ_cisco_skills_federated_search").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", app_name):
        raise SpecError("app_name must contain only letters, numbers, underscore, dot, colon, or hyphen.")
    federated_search_enabled = boolish(raw.get("federated_search_enabled"), default=True)
    max_dur = parse_int(
        raw.get("max_preview_generation_duration", 0),
        label="max_preview_generation_duration",
    )
    max_inp = parse_int(
        raw.get("max_preview_generation_inputcount", 0),
        label="max_preview_generation_inputcount",
    )
    shc_replication = boolish(raw.get("shc_replication"), default=True)
    restart_splunk = boolish(raw.get("restart_splunk"), default=True)

    raw_providers = raw.get("providers") or []
    if not isinstance(raw_providers, list):
        raise SpecError("`providers` must be a list when provided.")
    s2s: list[S2SProvider] = []
    fss3: list[FSS3Provider] = []
    specialized_handoffs: list[SpecializedProviderHandoff] = []
    seen_names: set[str] = set()
    for entry in raw_providers:
        if not isinstance(entry, dict):
            raise SpecError("Each `providers` entry must be a mapping.")
        provider_type = str(entry.get("type") or "splunk").strip().lower()
        if provider_type == "splunk":
            provider = _normalize_s2s(entry, seen_names)
            s2s.append(provider)
            seen_names.add(provider.name)
        elif provider_type == "aws_s3":
            provider_s3 = _normalize_fss3(entry, seen_names)
            fss3.append(provider_s3)
            seen_names.add(provider_s3.name)
        elif provider_type in SPECIALIZED_HANDOFF_BY_TYPE:
            provider_handoff = _normalize_specialized_handoff(entry, seen_names)
            specialized_handoffs.append(provider_handoff)
            seen_names.add(provider_handoff.name)
        else:
            raise SpecError(
                f"Provider {entry.get('name')!r} type must be 'splunk', 'aws_s3', "
                f"or a handoff-only type in {tuple(SPECIALIZED_HANDOFF_BY_TYPE)} "
                f"(got {provider_type!r})."
            )

    if not s2s and not fss3 and not specialized_handoffs:
        raise SpecError("Spec must declare at least one provider.")

    # Standard mode: multiple providers per remote host are allowed only when
    # they have distinct app_context values. Transparent mode: never allow
    # duplicate host:port.
    s2s_by_endpoint: dict[str, list[S2SProvider]] = {}
    for prov in s2s:
        s2s_by_endpoint.setdefault(prov.host_port, []).append(prov)
    for endpoint, group in s2s_by_endpoint.items():
        modes = {p.mode for p in group}
        # Order matters: mixed standard+transparent must surface BEFORE the
        # generic "transparent shares endpoint" check or the operator gets a
        # less-specific error message.
        if "standard" in modes and "transparent" in modes:
            raise SpecError(
                f"Mixed standard+transparent mode providers point at {endpoint}. "
                "Splunk documentation warns this can introduce duplicate events."
            )
        if "transparent" in modes and len(group) > 1:
            raise SpecError(
                f"Multiple providers point at {endpoint} but at least one is transparent-mode. "
                "Splunk does not support transparent-mode providers sharing a remote host. "
                "Use distinct host_port values or switch the providers to standard mode."
            )
        if len(group) > 1 and modes == {"standard"}:
            contexts = [p.app_context for p in group]
            if len(set(contexts)) != len(contexts):
                raise SpecError(
                    f"Multiple standard-mode providers point at {endpoint} with the same "
                    f"app_context. Set distinct app_context values per provider."
                )

    raw_indexes = raw.get("federated_indexes") or []
    if not isinstance(raw_indexes, list):
        raise SpecError("`federated_indexes` must be a list when provided.")
    indexes: list[FederatedIndex] = []
    seen_index_names: set[str] = set()
    for entry in raw_indexes:
        if not isinstance(entry, dict):
            raise SpecError("Each `federated_indexes` entry must be a mapping.")
        idx = _normalize_index(entry, s2s, fss3, specialized_handoffs)
        if idx.name in seen_index_names:
            raise SpecError(f"Duplicate federated index name: {idx.name}")
        seen_index_names.add(idx.name)
        indexes.append(idx)

    # If any standard-mode S2S providers exist but no federated indexes
    # reference them, surface a warning-equivalent SpecError so the operator
    # is reminded to map datasets. Standard mode without federated indexes is
    # functionally a no-op for searches.
    standard_s2s_names = {p.name for p in s2s if p.mode == "standard"}
    referenced = {idx.provider for idx in indexes}
    unreferenced = sorted(standard_s2s_names - referenced)
    if unreferenced:
        # Soft warning — do not fail; standard-mode providers can be created
        # before their indexes are mapped. Print to stderr by raising no error.
        # We surface this via metadata.json.warnings so the operator sees it.
        pass

    return Spec(
        splunk_home=splunk_home,
        app_name=app_name,
        federated_search_enabled=federated_search_enabled,
        max_preview_generation_duration=max_dur,
        max_preview_generation_inputcount=max_inp,
        shc_replication=shc_replication,
        restart_splunk=restart_splunk,
        s2s_providers=s2s,
        fss3_providers=fss3,
        specialized_provider_handoffs=specialized_handoffs,
        federated_indexes=indexes,
    )


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def password_token_for(provider: S2SProvider) -> str:
    """Stable substitution token for a provider's password file.

    Format: __FEDERATED_PASSWORD_FILE_BASE64__<PROVIDER>__
    The PASSWORD_PLACEHOLDER_PREFIX already ends with `__`, so we append the
    sanitized provider name directly with no separator and a trailing `__`.
    """
    safe = re.sub(r"[^A-Za-z0-9]+", "_", provider.name).strip("_") or "PROVIDER"
    return f"{PASSWORD_PLACEHOLDER_PREFIX}{safe.upper()}__"


def render_federated_template(spec: Spec) -> str:
    if not spec.s2s_providers:
        lines = ["# No FSS2S (type=splunk) providers were declared in the spec."]
        if spec.fss3_providers:
            lines.extend(
                [
                    "# Legacy Federated Search for Amazon S3 (type=aws_s3) is not",
                    "# applied by this skill. Review the payload-shaped inventory in",
                    "# aws-s3-providers/ and follow legacy-fss3-migration.md.",
                ]
            )
        if spec.specialized_provider_handoffs:
            lines.extend(
                [
                    "# Amazon Security Lake (type=aws_lake) and Cisco SAL",
                    "# (type=aws_s3_sal) requests are handoff-only. No provider or index",
                    "# CRUD is emitted; review specialized-federation-handoff.md.",
                ]
            )
        return "\n".join(lines) + "\n"
    lines = [
        "# Rendered by splunk-federated-search-setup. Review before applying.",
        "# Each provider's `password` field is substituted by the apply scripts",
        "# from the operator-supplied --password-file paths.",
        "",
    ]
    for provider in spec.s2s_providers:
        token = password_token_for(provider)
        lines.append(f"[provider://{provider.name}]")
        lines.append("type = splunk")
        lines.append(f"hostPort = {provider.host_port}")
        lines.append(f"serviceAccount = {provider.service_account}")
        lines.append(f"password = {token}")
        lines.append(f"mode = {provider.mode}")
        if provider.mode == "standard":
            lines.append(f"appContext = {provider.app_context}")
            lines.append("useFSHKnowledgeObjects = 0")
        else:
            lines.append("useFSHKnowledgeObjects = 1")
        if provider.disabled:
            lines.append("disabled = 1")
        else:
            lines.append("disabled = 0")
        lines.append("")
    lines.append("[general]")
    lines.append(f"max_preview_generation_duration = {spec.max_preview_generation_duration}")
    lines.append(f"max_preview_generation_inputcount = {spec.max_preview_generation_inputcount}")
    return "\n".join(lines).rstrip() + "\n"


def render_indexes(spec: Spec) -> str:
    s2s_provider_names = {p.name for p in spec.s2s_providers}
    relevant = [idx for idx in spec.federated_indexes if idx.provider in s2s_provider_names]
    if not relevant:
        return (
            "# No FSS2S federated indexes were declared in the spec.\n"
            "# Transparent-mode providers do not use federated indexes.\n"
            "# Legacy FSS3 definitions are migration evidence only on 10.5; no CRUD is emitted.\n"
        )
    lines = [
        "# Rendered by splunk-federated-search-setup. Review before applying.",
        "",
    ]
    for idx in relevant:
        lines.append(f"[federated:{idx.name}]")
        lines.append(f"federated.provider = {idx.provider}")
        lines.append(f"federated.dataset = {idx.dataset_type}:{idx.dataset_name}")
        if idx.disabled:
            lines.append("disabled = 1")
        else:
            lines.append("disabled = 0")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_server(spec: Spec) -> str:
    has_standard_s2s = any(p.mode == "standard" for p in spec.s2s_providers)
    if not spec.shc_replication or not has_standard_s2s:
        return (
            "# No SHC federated index replication setting requested.\n"
            "# Either shc_replication is false in the spec, or the spec has no\n"
            "# standard-mode FSS2S providers.\n"
        )
    return "\n".join(
        [
            "# Rendered for search head cluster deployer use BEFORE creating",
            "# federated indexes. Push this app through the deployer first so",
            "# every SHC member learns to replicate federated index definitions.",
            "[shclustering]",
            "conf_replication_include.indexes = true",
            "",
        ]
    )


def render_aws_s3_payload(provider: FSS3Provider) -> str:
    payload = {
        "name": provider.name,
        "type": "aws_s3",
        "aws_account_id": provider.aws_account_id,
        "aws_region": provider.aws_region,
        "database": provider.database,
        "data_catalog": provider.data_catalog,
        "aws_glue_tables_allowlist": ",".join(provider.aws_glue_tables_allowlist),
        "aws_s3_paths_allowlist": ",".join(provider.aws_s3_paths_allowlist),
        "disabled": "1" if provider.disabled else "0",
    }
    if provider.aws_kms_keys_arn_allowlist:
        payload["aws_kms_keys_arn_allowlist"] = ",".join(provider.aws_kms_keys_arn_allowlist)
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def render_aws_s3_readme(spec: Spec) -> str:
    if not spec.fss3_providers:
        return ""
    lines = [
        "# Federated Search for Amazon S3 — Migration Evidence",
        "",
        "## Lifecycle warning",
        "",
        "The rendered `type=aws_s3` payload is the legacy provider path. Splunk",
        "10.5 documentation describes phased deprecation of legacy FS-S3 provider",
        "and federated-index operations in preparation for migration to the Data",
        "Management app. Prefer current Amazon S3 connections and datasets for new",
        "designs. These payload-shaped files are inventory/migration evidence only",
        "on 10.5 and are never consumed by the rendered apply scripts.",
        "",
        "Legacy Splunk Cloud FSS3 definitions used REST or Splunk Web, not",
        "`federated.conf`. On 10.5, the renderer writes one payload-shaped JSON",
        "inventory record per provider under `aws-s3-providers/<name>.json`. The",
        "rendered `apply-rest.sh` refuses legacy-only plans and excludes legacy",
        "providers/indexes from mixed FSS2S applies.",
        "",
        "## AWS prerequisites",
        "",
        "Before validating or migrating an existing legacy definition, the AWS administrator must:",
        "",
        "1. Create the AWS Glue database and Glue tables that you list in",
        "   `aws_glue_tables_allowlist`. Each Glue table must reference an S3",
        "   location path that appears in `aws_s3_paths_allowlist`.",
        "2. Attach the Splunk-generated Glue Data Catalog resource policy to the",
        "   target AWS Glue catalog. (Use Splunk Web's **Generate policy** action",
        "   on the FSS3 provider page if you have not generated it yet.)",
        "3. Attach the Splunk-generated S3 bucket policy to each S3 bucket whose",
        "   prefix appears in `aws_s3_paths_allowlist`.",
        "4. If S3 buckets or Glue metadata are encrypted with customer-managed",
        "   AWS KMS keys, attach the Splunk-generated KMS key policy to each KMS",
        "   key listed in `aws_kms_keys_arn_allowlist`.",
        "5. Confirm the AWS Glue database region matches the Splunk Cloud",
        "   deployment region; FSS3 does not support cross-region searches.",
        "",
        "## Splunk Cloud prerequisites",
        "",
        "1. Inventory the existing provider and read-only federated indexes.",
        "2. Confirm the migrated Data Management connection and datasets.",
        "3. Validate equivalent SPL2, RBAC, schema/time/partition, cost, and result behavior before retirement.",
        "",
        "## Per-provider payloads",
        "",
    ]
    for provider in spec.fss3_providers:
        lines.append(f"- `aws-s3-providers/{provider.name}.json`")
    return "\n".join(lines).rstrip() + "\n"


def render_data_management_handoff() -> str:
    lines = [
        "# Data Management App Federation Handoff",
        "",
        "Current Splunk Cloud federated-search expansion is centered on Data",
        "Management app connections and datasets. This renderer automates",
        "reviewable Splunk-to-Splunk assets and retains payload-shaped legacy",
        "`aws_s3` inventory solely for migration evidence. It does not emit legacy",
        "FSS3 or Data Management app CRUD.",
        "",
        "| Surface | Stage | Availability | Operator action |",
        "| --- | --- | --- | --- |",
    ]
    for item in DATA_MANAGEMENT_FEDERATION_HANDOFFS:
        lines.append(
            f"| {item['label']} | {item['stage']} | {item['availability']} | {item['activation']} |"
        )
    lines.extend(
        [
            "",
            "## Amazon S3 Data Catalog Options",
            "",
            "Current Amazon S3 connections require each federated-search dataset to",
            "have a catalog. Choose the catalog explicitly; these are not interchangeable",
            "with the legacy provider-level `data_catalog` ARN field.",
            "",
            "| Catalog | Ownership | Supported formats/model | Notes |",
            "| --- | --- | --- | --- |",
        ]
    )
    for catalog in S3_DATA_CATALOG_OPTIONS:
        formats = ", ".join(catalog["formats"])
        lines.append(
            f"| {catalog['label']} | `{catalog['ownership']}` | {formats} | {catalog['notes']} |"
        )
    lines.extend(
        [
            "",
            "## Readiness Checklist",
            "",
            "- Contact Splunk sales to activate each requested Data Management federation surface. Confirm any applicable commercial entitlement for the target tenant; do not infer one universal Data Scan Unit model across all surfaces.",
            "- Confirm the Splunk Cloud deployment region and provider-region constraints before designing datasets.",
            "- Define connections and datasets in the Data Management app where the current docs require UI-driven setup.",
            "- For Azure datasets, decide whether each dataset is federated-search-only or data-routing-plus-federated-search.",
            "- For Azure Databricks, collect Delta Sharing and Unity Catalog readiness without placing credentials in this repo.",
            "- For Snowflake, require a role with `USAGE` on the warehouse, database, and schema; a Splunk-region IPv4 ingress network rule and Snowflake network policy; a service-user authentication policy; and a programmatic access token (PAT) kept outside this repository. Azure/GCP Snowflake warehouses are unsupported.",
            "- For DDSS, confirm the S3 self-storage location and associated DDSS index already exist, then create an SQS queue and S3 event notification and apply the generated S3 bucket and SQS queue policies. Route DDSS location lifecycle ownership to `splunk-cloud-acs-admin-setup`.",
            "- For current Amazon S3 workflows, use the Data Management app connection/dataset model; treat any older provider definition as read-only migration inventory.",
            "- Confirm roles have the current `edit_connections` and `edit_datasets` capabilities before the Data Management handoff.",
            "- Validate SPL2 searches against representative time fields and partitions before production routing.",
            "",
            "## Per-Surface Notes",
            "",
        ]
    )
    for item in DATA_MANAGEMENT_FEDERATION_HANDOFFS:
        lines.extend(
            [
                f"### {item['label']}",
                "",
                f"- Dataset model: {item['dataset_model']}",
                f"- Lifecycle: `{item['lifecycle']}`; automation: `{item['automation']}`.",
                f"- Notes: {item['notes']}",
                f"- Source: {item['source_url']}",
                "",
            ]
        )
    lines.extend(
        [
            "## Boundary",
            "",
            "No Microsoft Azure, Azure Databricks, Snowflake, DDSS, Apache Iceberg, Delta Lake,",
            "or Data Management app connection/dataset API writes are emitted by this",
            "renderer. Add a first-class apply path only after Splunk publishes a stable",
            "public contract that matches the tenant experience.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def render_specialized_federation_handoff(spec: Spec) -> str:
    lines = [
        "# Specialized Federation Handoffs",
        "",
        "Amazon Security Lake Federated Analytics and Cisco Security Analytics",
        "and Logging use dedicated provider types. They must not be represented",
        "as generic `aws_s3` providers. This renderer records reviewed intent and",
        "prerequisites but emits no provider, subscriber, dataset, or index CRUD.",
        "",
        "| Surface | Provider type | Lifecycle | Automation | Availability |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in SPECIALIZED_FEDERATION_HANDOFFS:
        lines.append(
            f"| {item['label']} | `{item['provider_type']}` | `{item['lifecycle']}` | "
            f"`{item['automation']}` | {item['availability']} |"
        )
    lines.extend(["", "## Requested Handoffs", ""])
    if spec.specialized_provider_handoffs:
        for provider in spec.specialized_provider_handoffs:
            item = SPECIALIZED_HANDOFF_BY_TYPE[provider.provider_type]
            lines.append(
                f"- `{provider.name}` -> `{provider.provider_type}` ({item['label']}); "
                f"disabled intent: `{str(provider.disabled).lower()}`."
            )
    else:
        lines.append(
            "- None declared in this spec. Add a handoff-only `providers:` entry with "
            "`type: aws_lake` or `type: aws_s3_sal` to record intent without emitting CRUD."
        )
    lines.extend(["", "## Per-Surface Readiness", ""])
    for item in SPECIALIZED_FEDERATION_HANDOFFS:
        lines.extend(
            [
                f"### {item['label']}",
                "",
                f"- Dedicated provider type: `{item['provider_type']}`.",
                f"- Stage: {item['stage']}.",
                f"- Activation: {item['activation']}",
                f"- Dataset model: {item['dataset_model']}",
                f"- Guardrail: {item['notes']}",
                f"- Source: {item['source_url']}",
                "",
            ]
        )
    lines.extend(
        [
            "## Boundary",
            "",
            "- `aws_lake` is a dedicated Amazon Security Lake Federated Analytics provider, not ordinary FSS3.",
            "- `aws_s3_sal` is a dedicated Cisco SAL provider, not ordinary FSS3.",
            "- The current public contracts do not justify generating customer-facing CRUD payloads for either type here.",
            "- Create subscribers, data lake indexes, federated indexes, SAL associations, and access policy through the documented product workflow and validate them in the target tenant.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def render_legacy_fss3_migration(spec: Spec) -> str:
    provider_names = [provider.name for provider in spec.fss3_providers]
    lines = [
        "# Legacy Federated Search for Amazon S3 Migration",
        "",
        f"- Provider type: `{LEGACY_FSS3_LIFECYCLE['provider_type']}`",
        f"- Lifecycle: `{LEGACY_FSS3_LIFECYCLE['lifecycle']}`",
        f"- Preferred replacement: {LEGACY_FSS3_LIFECYCLE['preferred_replacement']}",
        f"- Source: {LEGACY_FSS3_LIFECYCLE['source_url']}",
        "",
        "Splunk 10.5 configuration documentation describes phased deprecation of",
        "legacy FS-S3 provider and federated-index operations as Splunk moves the",
        "current Amazon S3 workflow to Data Management app connections and datasets.",
        "The legacy renderer remains only to inventory and migrate reviewed existing",
        "tenants; it never applies provider or index CRUD and is not an architecture",
        "for a new deployment.",
        "",
        "## Legacy Providers In This Plan",
        "",
    ]
    if provider_names:
        lines.extend(f"- `{name}`" for name in provider_names)
    else:
        lines.append("- None.")
    lines.extend(
        [
            "",
            "## Migration Checklist",
            "",
            "1. Inventory the legacy provider, mapped federated indexes, roles, saved searches, alerts, dashboards, and Data Scan Unit usage.",
            "2. Confirm current Federated Search for Amazon S3 activation and the `edit_connections` and `edit_datasets` capabilities for the target Splunk Cloud tenant.",
            "3. Create a Data Management Amazon S3 connection with reviewed IAM trust and resource policies.",
            "4. Recreate datasets using the appropriate AWS Glue, Apache Iceberg REST, or Splunk-native catalog model; preserve time fields, partitions, schema, formats, and encryption requirements.",
            "5. Reapply dataset RBAC and validate representative SPL2 searches, result shape, time filtering, cost, and performance against the legacy path.",
            "6. Update dependent knowledge objects only after equivalent results are proven, then monitor a controlled cutover window.",
            "7. Disable and remove the legacy provider and indexes only through a separately reviewed change with rollback evidence.",
            "",
            "This skill does not automatically delete or migrate a legacy provider.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def render_readme(spec: Spec) -> str:
    s2s_count = len(spec.s2s_providers)
    fss3_count = len(spec.fss3_providers)
    specialized_count = len(spec.specialized_provider_handoffs)
    idx_count = len(spec.federated_indexes)
    standard_count = sum(1 for p in spec.s2s_providers if p.mode == "standard")
    transparent_count = sum(1 for p in spec.s2s_providers if p.mode == "transparent")
    sections = [
        "# Splunk Federated Search Rendered Assets",
        "",
        f"FSS2S providers: {s2s_count} ({standard_count} standard, {transparent_count} transparent)  ",
        f"FSS3 providers:  {fss3_count}  ",
        f"Specialized provider handoffs: {specialized_count}  ",
        f"Federated indexes: {idx_count}  ",
        f"App: `{spec.app_name}`  ",
        "",
        "## Files",
        "",
        "- `federated.conf.template` — FSS2S provider stanzas (passwords substituted at apply time)",
        "- `indexes.conf` — FSS2S federated index stanzas",
        "- `server.conf` — `[shclustering] conf_replication_include.indexes = true` for SHC",
        "- `preflight.sh` — local btool sanity checks",
        "- `apply-search-head.sh` — file-based apply on a standalone Splunk Enterprise SH",
        "- `apply-shc-deployer.sh` — fail-closed handoff to SHC bundle validation/apply",
        "- `apply-rest.sh` — FSS2S-only REST apply for Splunk Enterprise or Splunk Cloud; refuses legacy-only plans",
        "- `status.sh` — REST GET /services/data/federated/provider; reports connectivityStatus per provider",
        "- `global-enable.sh` / `global-disable.sh` — toggle the global federated-search switch",
        "- `aws-s3-providers/<name>.json` — payload-shaped inventory/migration evidence for each legacy FSS3 provider; never apply input",
        "- `data-management-federation-handoff.md` — current Data Management app federation and S3 catalog readiness",
        "- `specialized-federation-handoff.md` — dedicated `aws_lake` Amazon Security Lake and `aws_s3_sal` Cisco SAL handoffs",
        "- `legacy-fss3-migration.md` — phased-deprecation and migration guidance for legacy `aws_s3` providers",
        "- `metadata.json` — machine-readable summary of the rendered plan",
        "",
        "Service-account passwords are never embedded. Apply scripts read them from",
        "the operator-supplied `password_file` path declared per FSS2S provider in",
        "the spec.",
        "",
        "## What's NOT created",
        "",
        "- Splunk Cloud IP allow-lists (use Splunk Web → Settings → Server settings → IP allow list).",
        "- AWS Glue tables, S3 bucket policies, or KMS key policies (operator/AWS admin task).",
        "- Data Management app connections or datasets for current Amazon S3, Microsoft Azure, Azure Databricks, Snowflake, DDSS, Apache Iceberg, or Delta Lake workflows.",
        "- Amazon Security Lake `aws_lake` providers, subscribers, data lake indexes, or federated indexes.",
        "- Cisco SAL `aws_s3_sal` providers or associated datasets/indexes.",
        "- Service accounts on remote Splunk deployments. Standard mode requires the",
        "  service account role on the remote SH to read the mapped datasets;",
        "  transparent mode against an SHC additionally requires the",
        "  `list_search_head_clustering` capability so Splunk can detect duplicate",
        "  transparent providers across cluster members.",
        "",
        "## Standard mode knowledge object coordination",
        "",
        "Standard-mode federated searches blend local FSH knowledge objects with",
        "remote search-head knowledge objects. If your federated searches reference",
        "lookups, calculated fields, eventtypes, or tags that exist only on the",
        "FSH, install matching definitions on the remote SH (or on every member of",
        "a remote SHC) before relying on those searches.",
    ]
    return "\n".join(sections).rstrip() + "\n"


def render_preflight(spec: Spec) -> str:
    splunk_home = shell_quote(spec.splunk_home)
    return make_script(
        enterprise_version_gate(spec)
        + f"""splunk_home={splunk_home}
test -x "${{splunk_home}}/bin/splunk"
"${{splunk_home}}/bin/splunk" btool federated list --debug >/dev/null
"${{splunk_home}}/bin/splunk" btool indexes list --debug >/dev/null
"""
    )


def _password_substitution_python_block(spec: Spec) -> str:
    """Python helper that substitutes per-provider password placeholders.

    Embedded in apply-search-head.sh and apply-shc-deployer.sh via heredoc.
    """
    if not spec.s2s_providers:
        return (
            'echo "INFO: No FSS2S providers in spec; skipping federated.conf substitution."\n'
        )
    mapping_lines: list[str] = []
    for provider in spec.s2s_providers:
        token = password_token_for(provider)
        mapping_lines.append(
            f"  ({json.dumps(token)}, {json.dumps(provider.password_file)}, {json.dumps(provider.name)}),"
        )
    mapping_block = "\n".join(mapping_lines)
    return (
        'python3 - "${target_dir}/federated.conf" <<\'PY\'\n'
        "import os\n"
        "import stat\n"
        "import sys\n"
        "import tempfile\n"
        "from pathlib import Path\n"
        "\n"
        f"{EMBEDDED_PRIVATE_SECRET_READER}\n"
        "target = Path(sys.argv[1])\n"
        "text = Path('federated.conf.template').read_text(encoding='utf-8')\n"
        "mapping = [\n"
        f"{mapping_block}\n"
        "]\n"
        "for token, password_file, provider_name in mapping:\n"
        "    if token not in text:\n"
        "        continue\n"
        "    if not password_file:\n"
        "        raise SystemExit(f'ERROR: provider {provider_name} requires a password_file but none was set.')\n"
        "    pw = read_private_secret(password_file, f'password_file for provider {provider_name}')\n"
        "    text = text.replace(token, pw)\n"
        "descriptor, temporary_name = tempfile.mkstemp(prefix=f'.{target.name}.', dir=target.parent)\n"
        "temporary = Path(temporary_name)\n"
        "try:\n"
        "    os.fchmod(descriptor, 0o600)\n"
        "    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:\n"
        "        descriptor = -1\n"
        "        stream.write(text)\n"
        "        stream.flush()\n"
        "        os.fsync(stream.fileno())\n"
        "    os.replace(temporary, target)\n"
        "finally:\n"
        "    if descriptor >= 0:\n"
        "        os.close(descriptor)\n"
        "    try:\n"
        "        temporary.unlink()\n"
        "    except FileNotFoundError:\n"
        "        pass\n"
        "PY\n"
        'chmod 600 "${target_dir}/federated.conf"\n'
    )


def render_apply_local(spec: Spec, *, shc: bool) -> str:
    if not spec.s2s_providers and (spec.fss3_providers or spec.specialized_provider_handoffs):
        return make_script(
            "echo 'HANDOFF ONLY: legacy aws_s3 migration evidence and specialized aws_lake/aws_s3_sal requests have no supported local apply contract in this skill.' >&2\n"
            "exit 2\n"
        )
    if shc:
        return make_script(
            "echo 'HANDOFF: SHC deployer staging is not a completed cluster apply. Use the rendered files with splunk-search-head-cluster-setup bundle validation/apply after secure password injection.' >&2\n"
            "exit 2\n"
        )
    splunk_home = shell_quote(spec.splunk_home)
    app_name = shell_quote(spec.app_name)
    base = "${splunk_home}/etc/shcluster/apps" if shc else "${splunk_home}/etc/apps"
    server_copy = (
        'cp server.conf "${target_dir}/server.conf"\n'
        if shc and spec.shc_replication and any(p.mode == "standard" for p in spec.s2s_providers)
        else ""
    )
    restart = (
        '"${splunk_home}/bin/splunk" restart\n'
        if spec.restart_splunk and not shc
        else 'echo "Review rendered changes and restart or push the bundle as appropriate."\n'
    )
    fss3_note = (
        'echo "INFO: Legacy FSS3 definitions are migration evidence only on 10.5; no legacy CRUD was performed."\n'
        if spec.fss3_providers
        else ""
    )
    indexes_copy = (
        'cp indexes.conf "${target_dir}/indexes.conf"\n'
        if any(idx for idx in spec.federated_indexes if idx.provider in {p.name for p in spec.s2s_providers})
        else 'echo "INFO: No FSS2S federated indexes in spec; indexes.conf not copied."\n'
    )
    return make_script(
        enterprise_version_gate(spec)
        + f"""splunk_home={splunk_home}
app_name={app_name}

target_dir="{base}/${{app_name}}/local"
mkdir -p "${{target_dir}}"

{_password_substitution_python_block(spec)}{indexes_copy}{server_copy}{fss3_note}{restart}"""
    )


def _rest_provider_payload_block(spec: Spec) -> str:
    """Embedded Python helper that POSTs each provider/index via REST.

    Reads SPLUNK_REST_URI / SPLUNK_REST_USER / SPLUNK_REST_PASSWORD_FILE from
    env so passwords stay off argv.
    """
    s2s_payloads_lines: list[str] = []
    for provider in spec.s2s_providers:
        s2s_payloads_lines.append(
            "  {"
            + (
                f"'name': {json.dumps(provider.name)}, 'type': 'splunk', "
                f"'hostPort': {json.dumps(provider.host_port)}, "
                f"'serviceAccount': {json.dumps(provider.service_account)}, "
                f"'mode': {json.dumps(provider.mode)}, "
                f"'appContext': {json.dumps(provider.app_context if provider.mode == 'standard' else '')}, "
                f"'useFSHKnowledgeObjects': {json.dumps(provider.use_fsh_knowledge_objects)}, "
                f"'disabled': {json.dumps('1' if provider.disabled else '0')}, "
                f"'_password_file': {json.dumps(provider.password_file)}"
            )
            + "},"
        )
    s2s_block = "\n".join(s2s_payloads_lines) if s2s_payloads_lines else ""

    indexes_payloads_lines: list[str] = []
    s2s_provider_names = {provider.name for provider in spec.s2s_providers}
    for idx in spec.federated_indexes:
        if idx.provider not in s2s_provider_names:
            continue
        indexes_payloads_lines.append(
            "  {"
            + (
                f"'name': {json.dumps('federated:' + idx.name)}, "
                f"'federated.provider': {json.dumps(idx.provider)}, "
                f"'federated.dataset': {json.dumps(idx.dataset_type + ':' + idx.dataset_name)}, "
                f"'disabled': {json.dumps('1' if idx.disabled else '0')}"
            )
            + "},"
        )
    indexes_block = "\n".join(indexes_payloads_lines) if indexes_payloads_lines else ""

    return (
        "python3 - <<'PY'\n"
        "import json\n"
        "import os\n"
        "import stat\n"
        "import sys\n"
        "import urllib.error\n"
        "import urllib.parse\n"
        "import urllib.request\n"
        "import ssl\n"
        "from pathlib import Path\n"
        "\n"
        f"{EMBEDDED_PRIVATE_SECRET_READER}\n"
        "splunk_uri = os.environ.get('SPLUNK_REST_URI', '').rstrip('/')\n"
        "splunk_user = os.environ.get('SPLUNK_REST_USER', '')\n"
        "splunk_pw_file = os.environ.get('SPLUNK_REST_PASSWORD_FILE', '')\n"
        "# Prefer the canonical SPLUNK_VERIFY_SSL name and fall back to the\n"
        "# legacy SPLUNK_REST_VERIFY_SSL alias for operators who already set it.\n"
        "_verify_raw = os.environ.get('SPLUNK_VERIFY_SSL', os.environ.get('SPLUNK_REST_VERIFY_SSL', 'true'))\n"
        "verify_ssl = _verify_raw.lower() not in {'false', '0', 'no'}\n"
        "if not splunk_uri or not splunk_user or not splunk_pw_file:\n"
        "    raise SystemExit('ERROR: set SPLUNK_REST_URI, SPLUNK_REST_USER, SPLUNK_REST_PASSWORD_FILE before apply-rest.sh.')\n"
        "if any(character.isspace() for character in splunk_uri):\n"
        "    raise SystemExit('ERROR: SPLUNK_REST_URI must not contain whitespace.')\n"
        "try:\n"
        "    parsed_uri = urllib.parse.urlsplit(splunk_uri)\n"
        "    parsed_uri.port\n"
        "except ValueError:\n"
        "    raise SystemExit('ERROR: SPLUNK_REST_URI is invalid or contains an invalid port.')\n"
        "scheme = parsed_uri.scheme.lower()\n"
        "if scheme not in {'http', 'https'} or not parsed_uri.hostname:\n"
        "    raise SystemExit('ERROR: SPLUNK_REST_URI must be an absolute https://host[:port] origin.')\n"
        "if parsed_uri.username is not None or parsed_uri.password is not None:\n"
        "    raise SystemExit('ERROR: SPLUNK_REST_URI must not contain embedded userinfo credentials.')\n"
        "if parsed_uri.path not in {'', '/'} or parsed_uri.query or parsed_uri.fragment:\n"
        "    raise SystemExit('ERROR: SPLUNK_REST_URI must not contain a path, query, or fragment.')\n"
        "allow_insecure_http = os.environ.get('SPLUNK_ALLOW_INSECURE_HTTP', '').strip().lower() in {'1', 'true', 'yes', 'on'}\n"
        "if scheme == 'http' and not allow_insecure_http:\n"
        "    raise SystemExit('ERROR: REST apply refuses plaintext HTTP. Use HTTPS, or set SPLUNK_ALLOW_INSECURE_HTTP=true only for an isolated short-lived lab.')\n"
        "if scheme == 'http':\n"
        "    print('WARNING: LAB ONLY: SPLUNK_ALLOW_INSECURE_HTTP=true sends Splunk credentials and provider passwords over plaintext HTTP.', file=sys.stderr)\n"
        "splunk_pw = read_private_secret(splunk_pw_file, 'SPLUNK_REST_PASSWORD_FILE')\n"
        "ctx = None if verify_ssl else ssl._create_unverified_context()\n"
        "class NoRedirectHandler(urllib.request.HTTPRedirectHandler):\n"
        "    def redirect_request(self, req, fp, code, msg, headers, newurl):\n"
        "        return None\n"
        "transport_handler = urllib.request.HTTPSHandler(context=ctx) if scheme == 'https' else urllib.request.HTTPHandler()\n"
        "opener = urllib.request.build_opener(NoRedirectHandler(), transport_handler)\n"
        "import base64\n"
        "auth = 'Basic ' + base64.b64encode(f'{splunk_user}:{splunk_pw}'.encode()).decode()\n"
        "\n"
        "def post(path, payload):\n"
        "    body = urllib.parse.urlencode(payload, doseq=True).encode()\n"
        "    req = urllib.request.Request(\n"
        "        splunk_uri + path,\n"
        "        data=body,\n"
        "        method='POST',\n"
        "        headers={'Authorization': auth, 'Content-Type': 'application/x-www-form-urlencoded'},\n"
        "    )\n"
        "    try:\n"
        "        with opener.open(req, timeout=60) as resp:\n"
        "            return resp.status\n"
        "    except urllib.error.HTTPError as exc:\n"
        "        # 409 means the entity already exists; fall through to update via name-keyed POST.\n"
        "        if exc.code == 409:\n"
        "            return 409\n"
        "        body = exc.read().decode('utf-8', errors='replace')\n"
        "        raise SystemExit(f'ERROR: POST {path} failed HTTP {exc.code}: {body}')\n"
        "\n"
        "def post_or_update(collection_path, name, payload):\n"
        "    status = post(collection_path, payload)\n"
        "    if status == 409:\n"
        "        # Already exists; PUT-style update on the keyed endpoint.\n"
        "        update = {k: v for k, v in payload.items() if k != 'name'}\n"
        "        post(f'{collection_path}/{urllib.parse.quote(name, safe=\"\")}', update)\n"
        "\n"
        "# Step 1: FSS2S providers\n"
        "s2s_payloads = [\n"
        f"{s2s_block}\n"
        "]\n"
        "for entry in s2s_payloads:\n"
        "    pw_file = entry.pop('_password_file')\n"
        "    if not pw_file:\n"
        "        raise SystemExit(f\"ERROR: provider {entry['name']} requires a password_file in the spec.\")\n"
        "    entry['password'] = read_private_secret(pw_file, f\"password_file for provider {entry['name']}\")\n"
        "    if entry['mode'] == 'transparent':\n"
        "        # Splunk forces useFSHKnowledgeObjects=1 for transparent and ignores appContext.\n"
        "        entry.pop('appContext', None)\n"
        "    print(f\"Provider {entry['name']} (FSS2S, {entry['mode']}): POST /services/data/federated/provider\")\n"
        "    post_or_update('/services/data/federated/provider', entry['name'], entry)\n"
        "\n"
        "# Step 2: FSS2S standard-mode federated indexes\n"
        "index_payloads = [\n"
        f"{indexes_block}\n"
        "]\n"
        "for entry in index_payloads:\n"
        "    print(f\"Federated index {entry['name']}: POST /services/data/federated/index\")\n"
        "    post_or_update('/services/data/federated/index', entry['name'], entry)\n"
        "\n"
        "print('REST apply complete.')\n"
        "PY\n"
    )


def render_apply_rest(spec: Spec) -> str:
    if not spec.s2s_providers and (spec.fss3_providers or spec.specialized_provider_handoffs):
        return make_script(
            "echo 'HANDOFF ONLY: legacy aws_s3 migration evidence and specialized aws_lake/aws_s3_sal requests have no supported REST CRUD contract in this skill.' >&2\n"
            "exit 2\n"
        )
    legacy_warning = (
        "echo 'WARNING: legacy aws_s3 providers and indexes are excluded from this FSS2S REST apply; use legacy-fss3-migration.md.' >&2\n"
        if spec.fss3_providers
        else ""
    )
    return make_script(
        "echo 'Splunk Federated Search REST apply'\n"
        "echo 'Required env: SPLUNK_REST_URI=https://<sh>:8089 SPLUNK_REST_USER=admin SPLUNK_REST_PASSWORD_FILE=/path/to/admin_pw'\n"
        "echo 'Optional lab-only env: SPLUNK_VERIFY_SSL=false for self-signed TLS; SPLUNK_ALLOW_INSECURE_HTTP=true for an isolated plaintext lab endpoint'\n"
        "\n"
        + legacy_warning
        + _rest_provider_payload_block(spec)
    )


def _rest_shell_curl_prelude() -> str:
    return r"""splunk_uri="${SPLUNK_REST_URI:-}"
splunk_user="${SPLUNK_REST_USER:-}"
splunk_pw_file="${SPLUNK_REST_PASSWORD_FILE:-}"
if [[ -z "${splunk_uri}" || -z "${splunk_user}" || -z "${splunk_pw_file}" ]]; then
  echo 'ERROR: set SPLUNK_REST_URI, SPLUNK_REST_USER, SPLUNK_REST_PASSWORD_FILE.' >&2
  exit 1
fi
if [[ -L "${splunk_pw_file}" || ! -f "${splunk_pw_file}" || ! -s "${splunk_pw_file}" ]]; then
  echo "ERROR: password file must be a non-symlink regular file and must not be empty." >&2
  exit 1
fi
if ! python3 - "${splunk_uri}" <<'PY_URI'
import os
import sys
from urllib.parse import urlsplit

raw = sys.argv[1]
try:
    parsed = urlsplit(raw)
    parsed.port
except ValueError:
    raise SystemExit(1)
allow_http = os.environ.get("SPLUNK_ALLOW_INSECURE_HTTP", "").strip().lower() in {
    "1", "true", "yes", "on"
}
valid = (
    parsed.scheme.lower() in ({"https", "http"} if allow_http else {"https"})
    and bool(parsed.hostname)
    and parsed.username is None
    and parsed.password is None
    and parsed.path in ("", "/")
    and not parsed.query
    and not parsed.fragment
    and not any(character.isspace() for character in raw)
)
raise SystemExit(0 if valid else 1)
PY_URI
then
  echo "ERROR: SPLUNK_REST_URI must be a credential-free HTTPS origin. Plaintext HTTP requires SPLUNK_ALLOW_INSECURE_HTTP=true for an isolated lab." >&2
  exit 1
fi

transport_args=(--proto '=https' --proto-redir '=https' --max-redirs 0 --globoff)
case "${splunk_uri}" in
  [Hh][Tt][Tt][Pp]://*)
    echo "WARNING: LAB ONLY: sending Splunk credentials over plaintext HTTP." >&2
    transport_args=(--proto '=http,https' --proto-redir '=http,https' --max-redirs 0 --globoff)
    ;;
esac

verify_args=()
_verify_raw="${SPLUNK_VERIFY_SSL:-${SPLUNK_REST_VERIFY_SSL:-true}}"
if [[ "${_verify_raw,,}" == "false" || "${_verify_raw}" == "0" || "${_verify_raw,,}" == "no" ]]; then
  verify_args+=(--insecure)
elif [[ -n "${SPLUNK_CA_CERT:-}" ]]; then
  [[ -r "${SPLUNK_CA_CERT}" ]] || { echo "ERROR: SPLUNK_CA_CERT is not readable." >&2; exit 1; }
  verify_args+=(--cacert "${SPLUNK_CA_CERT}")
fi

splunk_pw="$(cat "${splunk_pw_file}")"
if [[ -z "${splunk_pw}" || "${splunk_pw}" == *$'\n'* || "${splunk_pw}" == *$'\r'*
      || "${splunk_user}" == *:* || "${splunk_user}" == *$'\n'* || "${splunk_user}" == *$'\r'* ]]; then
  echo "ERROR: Splunk username and password file must each contain one non-empty line." >&2
  exit 1
fi
escaped_user="${splunk_user//\\/\\\\}"
escaped_user="${escaped_user//\"/\\\"}"
escaped_pw="${splunk_pw//\\/\\\\}"
escaped_pw="${escaped_pw//\"/\\\"}"
user_pass_file="$(mktemp)"
chmod 600 "${user_pass_file}"
trap 'rm -f "${user_pass_file}"' EXIT INT TERM
printf 'user = "%s:%s"\n' "${escaped_user}" "${escaped_pw}" > "${user_pass_file}"
splunk_pw=""
escaped_pw=""

splunk_rest_curl() {
  local url="$1"
  shift
  command curl -q -fsS "${verify_args[@]}" -K "${user_pass_file}" "$@" "${url}" \
    "${transport_args[@]}"
}

"""


def render_status(spec: Spec) -> str:
    return make_script(
        _rest_shell_curl_prelude()
        + "echo '== Federated providers =='\n"
        "splunk_rest_curl \"${splunk_uri%/}/services/data/federated/provider?output_mode=json&count=0\" \\\n"
        "  | python3 -c '\n"
        "import json, sys\n"
        "data = json.load(sys.stdin)\n"
        "for entry in data.get(\"entry\", []):\n"
        "    name = entry.get(\"name\", \"<unknown>\")\n"
        "    content = entry.get(\"content\", {}) or {}\n"
        "    summary = {k: content.get(k) for k in (\"type\", \"mode\", \"hostPort\", \"serviceAccount\", \"appContext\", \"useFSHKnowledgeObjects\", \"connectivityStatus\", \"disabled\")}\n"
        "    summary = {k: v for k, v in summary.items() if v not in (None, \"\")}\n"
        "    print(f\"{name}: {json.dumps(summary, sort_keys=True)}\")\n"
        "'\n"
        "echo ''\n"
        "echo '== Federated indexes =='\n"
        "splunk_rest_curl \"${splunk_uri%/}/services/data/federated/index?output_mode=json&count=0\" \\\n"
        "  | python3 -c '\n"
        "import json, sys\n"
        "data = json.load(sys.stdin)\n"
        "for entry in data.get(\"entry\", []):\n"
        "    name = entry.get(\"name\", \"<unknown>\")\n"
        "    content = entry.get(\"content\", {}) or {}\n"
        "    summary = {k: content.get(k) for k in (\"federated.provider\", \"federated.dataset\", \"disabled\")}\n"
        "    summary = {k: v for k, v in summary.items() if v not in (None, \"\")}\n"
        "    print(f\"{name}: {json.dumps(summary, sort_keys=True)}\")\n"
        "'\n"
        "echo ''\n"
        "echo '== Global federated-search switch =='\n"
        "splunk_rest_curl \"${splunk_uri%/}/services/data/federated/settings/general?output_mode=json\" \\\n"
        "  | python3 -c '\n"
        "import json, sys\n"
        "data = json.load(sys.stdin)\n"
        "for entry in data.get(\"entry\", []):\n"
        "    content = entry.get(\"content\", {}) or {}\n"
        "    print(json.dumps({k: content.get(k) for k in (\"disabled\",)}, sort_keys=True))\n"
        "'\n"
    )


def render_global_toggle(spec: Spec, *, enable: bool) -> str:
    flag = "false" if enable else "true"
    label = "ENABLE" if enable else "DISABLE"
    return make_script(
        f"# Global federated-search {label} (POST /services/data/federated/settings/general).\n"
        + _rest_shell_curl_prelude()
        + f"splunk_rest_curl \"${{splunk_uri%/}}/services/data/federated/settings/general\" -X POST -d 'disabled={flag}'\n"
        + f"echo 'Global federated-search switch updated: disabled={flag}'\n"
    )


def render_metadata(spec: Spec, *, render_dir: Path) -> str:
    standard_s2s_names = {p.name for p in spec.s2s_providers if p.mode == "standard"}
    referenced = {idx.provider for idx in spec.federated_indexes}
    unmapped_standard = sorted(standard_s2s_names - referenced)
    warnings = [
        f"Standard-mode FSS2S provider '{name}' has no federated_indexes entries; "
        "searches against it will return nothing until you map at least one dataset."
        for name in unmapped_standard
    ]
    if spec.fss3_providers:
        warnings.append(
            "Legacy type=aws_s3 FSS3 provider inventory is in a phased-deprecation "
            "migration path on Splunk 10.5. Prefer Data Management app Amazon S3 "
            "connections and datasets for new designs. No legacy CRUD is emitted; "
            "review legacy-fss3-migration.md."
        )
    if spec.specialized_provider_handoffs:
        warnings.append(
            "Specialized aws_lake and aws_s3_sal entries are handoff-only; no provider, "
            "dataset, subscriber, data lake index, or federated index CRUD is emitted."
        )
    payload = {
        "app_name": spec.app_name,
        "splunk_home": spec.splunk_home,
        "federated_search_enabled": spec.federated_search_enabled,
        "max_preview_generation_duration": spec.max_preview_generation_duration,
        "max_preview_generation_inputcount": spec.max_preview_generation_inputcount,
        "shc_replication": spec.shc_replication,
        "restart_splunk": spec.restart_splunk,
        "providers": {
            "splunk_to_splunk": [
                {
                    "name": p.name,
                    "mode": p.mode,
                    "host_port": p.host_port,
                    "service_account": p.service_account,
                    "app_context": p.app_context if p.mode == "standard" else "",
                    "disabled": p.disabled,
                    "password_file": p.password_file,
                }
                for p in spec.s2s_providers
            ],
            "amazon_s3": [
                {
                    "name": p.name,
                    "provider_type": "aws_s3",
                    "lifecycle": LEGACY_FSS3_LIFECYCLE["lifecycle"],
                    "automation": LEGACY_FSS3_LIFECYCLE["automation"],
                    "preferred_replacement": LEGACY_FSS3_LIFECYCLE["preferred_replacement"],
                    "aws_account_id": p.aws_account_id,
                    "aws_region": p.aws_region,
                    "database": p.database,
                    "data_catalog": p.data_catalog,
                    "aws_glue_tables_allowlist": p.aws_glue_tables_allowlist,
                    "aws_s3_paths_allowlist": p.aws_s3_paths_allowlist,
                    "aws_kms_keys_arn_allowlist": p.aws_kms_keys_arn_allowlist,
                    "disabled": p.disabled,
                }
                for p in spec.fss3_providers
            ],
            "specialized_handoffs": [
                {
                    "name": p.name,
                    "provider_type": p.provider_type,
                    "lifecycle": SPECIALIZED_HANDOFF_BY_TYPE[p.provider_type]["lifecycle"],
                    "automation": "ui_handoff",
                    "disabled": p.disabled,
                }
                for p in spec.specialized_provider_handoffs
            ],
        },
        "federated_indexes": [
            {
                "name": idx.name,
                "provider": idx.provider,
                "dataset_type": idx.dataset_type,
                "dataset_name": idx.dataset_name,
                "disabled": idx.disabled,
            }
            for idx in spec.federated_indexes
        ],
        "warnings": warnings,
        "data_management_federation_handoffs": DATA_MANAGEMENT_FEDERATION_HANDOFFS,
        "specialized_federation_handoffs": SPECIALIZED_FEDERATION_HANDOFFS,
        "federation_handoffs": (
            DATA_MANAGEMENT_FEDERATION_HANDOFFS + SPECIALIZED_FEDERATION_HANDOFFS
        ),
        "amazon_s3_data_catalog_options": S3_DATA_CATALOG_OPTIONS,
        "legacy_fss3": LEGACY_FSS3_LIFECYCLE,
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


# ---------------------------------------------------------------------------
# Argparse + entrypoint
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Splunk Federated Search assets.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--spec",
        default="",
        help="YAML or JSON spec file (FSS2S automation plus legacy FSS3 migration evidence).",
    )
    # Single-provider back-compat flags.
    parser.add_argument("--mode", choices=("standard", "transparent"), default="standard")
    parser.add_argument("--splunk-home", default="/opt/splunk")
    parser.add_argument("--app-name", default="ZZZ_cisco_skills_federated_search")
    parser.add_argument("--provider-name", default="remote_provider")
    parser.add_argument("--remote-host-port", default="")
    parser.add_argument("--service-account", default="")
    parser.add_argument("--password-file", default="")
    parser.add_argument("--app-context", default="search")
    parser.add_argument("--use-fsh-knowledge-objects", choices=("true", "false"), default="false")
    parser.add_argument("--federated-index-name", default="remote_main")
    parser.add_argument(
        "--dataset-type",
        choices=ALL_DATASET_TYPES,
        default="index",
    )
    parser.add_argument("--dataset-name", default="main")
    parser.add_argument("--shc-replication", choices=("true", "false"), default="true")
    parser.add_argument("--max-preview-generation-duration", default="0")
    parser.add_argument("--max-preview-generation-inputcount", default="0")
    parser.add_argument("--restart-splunk", choices=("true", "false"), default="true")
    parser.add_argument("--federated-search-enabled", choices=("true", "false"), default="true")
    # Repeated CLI flags for multi-provider/multi-index without YAML.
    parser.add_argument(
        "--provider",
        action="append",
        default=[],
        help="Repeatable: type=splunk,name=foo,mode=standard,host_port=h:p,service_account=u,password_file=/p,app_context=search",
    )
    parser.add_argument(
        "--federated-index",
        action="append",
        default=[],
        help="Repeatable: name=foo,provider=remote_prod,dataset_type=index,dataset_name=main",
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def spec_from_cli(args: argparse.Namespace) -> Spec:
    """Build a spec dict from back-compat single-provider + repeated flags."""
    # Back-compat guard: the old single-flag CLI rejected
    # --use-fsh-knowledge-objects true for standard mode because Splunk forces
    # the field to 0 in standard mode regardless of operator input. Surface
    # the same error so existing scripts that relied on the rejection do not
    # silently start ignoring the flag.
    if (
        args.mode == "standard"
        and args.use_fsh_knowledge_objects == "true"
        and not args.spec
        and not args.provider
    ):
        raise SpecError(
            "--use-fsh-knowledge-objects true is valid only for transparent mode providers; "
            "Splunk forces useFSHKnowledgeObjects = 0 in standard mode."
        )
    raw: dict[str, Any] = {
        "splunk_home": args.splunk_home,
        "app_name": args.app_name,
        "federated_search_enabled": args.federated_search_enabled,
        "max_preview_generation_duration": args.max_preview_generation_duration,
        "max_preview_generation_inputcount": args.max_preview_generation_inputcount,
        "shc_replication": args.shc_replication,
        "restart_splunk": args.restart_splunk,
        "providers": [],
        "federated_indexes": [],
    }
    # Repeated --provider flags.
    for spec_str in args.provider:
        provider_dict = parse_kv_pairs(spec_str, label="--provider")
        raw["providers"].append(provider_dict)
    # Repeated --federated-index flags.
    for spec_str in args.federated_index:
        index_dict = parse_kv_pairs(spec_str, label="--federated-index")
        raw["federated_indexes"].append(index_dict)
    # Back-compat single-provider flags. Only used when --spec is absent and
    # no repeated --provider flags were given.
    if not raw["providers"] and args.remote_host_port and args.service_account:
        raw["providers"].append(
            {
                "name": args.provider_name,
                "type": "splunk",
                "mode": args.mode,
                "host_port": args.remote_host_port,
                "service_account": args.service_account,
                "password_file": args.password_file,
                "app_context": args.app_context,
            }
        )
    if not raw["federated_indexes"] and args.mode == "standard" and raw["providers"]:
        # Only auto-generate the default index when a single S2S provider was
        # synthesized from back-compat flags AND it is standard mode.
        only_provider = raw["providers"][0]
        if only_provider.get("type", "splunk") == "splunk" and only_provider.get("mode") == "standard":
            raw["federated_indexes"].append(
                {
                    "name": args.federated_index_name,
                    "provider": only_provider["name"],
                    "dataset_type": args.dataset_type,
                    "dataset_name": args.dataset_name,
                }
            )
    return normalize_spec(raw)


def render(spec: Spec, *, output_dir: Path, dry_run: bool) -> dict[str, Any]:
    render_dir = output_dir / "federated-search"
    assets: list[str] = []
    if not dry_run:
        clean_render_dir(render_dir)
        files = {
            "README.md": render_readme(spec),
            "metadata.json": render_metadata(spec, render_dir=render_dir),
            "data-management-federation-handoff.md": render_data_management_handoff(),
            "specialized-federation-handoff.md": render_specialized_federation_handoff(spec),
            "legacy-fss3-migration.md": render_legacy_fss3_migration(spec),
            "federated.conf.template": render_federated_template(spec),
            "indexes.conf": render_indexes(spec),
            "server.conf": render_server(spec),
            "preflight.sh": render_preflight(spec),
            "apply-search-head.sh": render_apply_local(spec, shc=False),
            "apply-shc-deployer.sh": render_apply_local(spec, shc=True),
            "apply-rest.sh": render_apply_rest(spec),
            "status.sh": render_status(spec),
            "global-enable.sh": render_global_toggle(spec, enable=True),
            "global-disable.sh": render_global_toggle(spec, enable=False),
        }
        for rel, content in files.items():
            write_file(render_dir / rel, content, executable=rel.endswith(".sh"))
            assets.append(rel)
        # FSS3 REST payloads + AWS prerequisites README.
        if spec.fss3_providers:
            aws_dir = render_dir / "aws-s3-providers"
            aws_dir.mkdir(parents=True, exist_ok=True)
            for provider in spec.fss3_providers:
                rel_path = f"aws-s3-providers/{provider.name}.json"
                write_file(render_dir / rel_path, render_aws_s3_payload(provider))
                assets.append(rel_path)
            write_file(render_dir / "aws-s3-providers/README.md", render_aws_s3_readme(spec))
            assets.append("aws-s3-providers/README.md")
    return {
        "target": "federated-search",
        "output_dir": str(output_dir),
        "render_dir": str(render_dir),
        "assets": sorted(assets),
        "dry_run": dry_run,
        "providers": {
            "splunk_to_splunk_count": len(spec.s2s_providers),
            "amazon_s3_count": len(spec.fss3_providers),
            "specialized_handoff_count": len(spec.specialized_provider_handoffs),
        },
        "federated_index_count": len(spec.federated_indexes),
        "commands": {
            "preflight": [["./preflight.sh"]],
            "apply": (
                [
                    ["./apply-search-head.sh"],
                    ["./apply-shc-deployer.sh"],
                    ["./apply-rest.sh"],
                ]
                if spec.s2s_providers
                else []
            ),
            "status": [["./status.sh"]],
            "global_toggle": [["./global-enable.sh"], ["./global-disable.sh"]],
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.spec:
        raw = load_spec_file(Path(args.spec).expanduser())
        spec = normalize_spec(raw)
    else:
        spec = spec_from_cli(args)
    output_dir = Path(args.output_dir).expanduser().resolve()
    payload = render(spec, output_dir=output_dir, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif args.dry_run:
        print(f"Would render Federated Search assets under {payload['render_dir']}")
    else:
        print(f"Rendered Federated Search assets under {payload['render_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

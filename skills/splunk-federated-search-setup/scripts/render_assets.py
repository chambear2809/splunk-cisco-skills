#!/usr/bin/env python3
"""Render Splunk Federated Search assets.

Supports the full Splunk Federated Search product surface:

- Federated Search for Splunk (FSS2S, type=splunk) in standard or transparent
  mode, with multiple providers per render and one or more federated indexes
  per provider.
- Federated Search for Amazon S3 (FSS3, type=aws_s3, Splunk Cloud Platform
  only), rendered as a REST payload because FSS3 cannot be configured through
  federated.conf and is created by POSTing to /services/data/federated/provider.
- File-based apply for Splunk Enterprise standalone search heads and SHC
  deployer bundles, plus a REST apply path that works on both Splunk
  Enterprise and Splunk Cloud Platform.
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
    federated_indexes: list[FederatedIndex]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def shell_quote(value: object) -> str:
    return shlex.quote(str(value))


def make_script(body: str) -> str:
    return "#!/usr/bin/env bash\nset -euo pipefail\n\n" + body.lstrip()


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


def _normalize_index(
    raw: dict[str, Any],
    s2s_providers: list[S2SProvider],
    fss3_providers: list[FSS3Provider],
) -> FederatedIndex:
    name = str(raw.get("name") or "").strip()
    validate_index_name(name, label="federated index name")
    provider = str(raw.get("provider") or "").strip()
    if not provider:
        raise SpecError(f"federated index {name} requires a provider name.")
    s2s_lookup = {p.name: p for p in s2s_providers}
    fss3_lookup = {p.name: p for p in fss3_providers}
    if provider not in s2s_lookup and provider not in fss3_lookup:
        raise SpecError(
            f"federated index {name} references unknown provider '{provider}'. "
            f"Known providers: {sorted(set(s2s_lookup) | set(fss3_lookup))}"
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
        else:
            raise SpecError(
                f"Provider {entry.get('name')!r} type must be 'splunk' or 'aws_s3' "
                f"(got {provider_type!r})."
            )

    if not s2s and not fss3:
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
        idx = _normalize_index(entry, s2s, fss3)
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
        return (
            "# No FSS2S (type=splunk) providers were declared in the spec.\n"
            "# Federated Search for Amazon S3 (type=aws_s3) is created via REST,\n"
            "# not federated.conf; see aws-s3-providers/ and apply-rest.sh.\n"
        )
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
            "# FSS3 federated indexes are created via REST; see apply-rest.sh.\n"
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
        "# Federated Search for Amazon S3 — Apply Notes",
        "",
        "Splunk Cloud Platform creates FSS3 providers through REST or Splunk Web,",
        "**not** through `federated.conf`. The renderer therefore writes one JSON",
        "payload per FSS3 provider under `aws-s3-providers/<name>.json`. The",
        "rendered `apply-rest.sh` will POST each payload to:",
        "",
        "    https://<splunk-cloud-host>:<mport>/services/data/federated/provider",
        "",
        "with form-encoded fields. The Splunk admin user must hold the",
        "`admin_all_objects` capability.",
        "",
        "## AWS prerequisites",
        "",
        "Before applying, the AWS administrator must:",
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
        "1. The IP allow-list use case **Search head API access** must include",
        "   the source IP/CIDR that runs `apply-rest.sh`.",
        "2. The Splunk admin user supplied to the apply script needs",
        "   `admin_all_objects`.",
        "3. After provider creation, map federated indexes to the Glue tables",
        "   via federated_indexes entries with `dataset_type: glue_table`.",
        "",
        "## Per-provider payloads",
        "",
    ]
    for provider in spec.fss3_providers:
        lines.append(f"- `aws-s3-providers/{provider.name}.json`")
    return "\n".join(lines).rstrip() + "\n"


def render_readme(spec: Spec) -> str:
    s2s_count = len(spec.s2s_providers)
    fss3_count = len(spec.fss3_providers)
    idx_count = len(spec.federated_indexes)
    standard_count = sum(1 for p in spec.s2s_providers if p.mode == "standard")
    transparent_count = sum(1 for p in spec.s2s_providers if p.mode == "transparent")
    sections = [
        "# Splunk Federated Search Rendered Assets",
        "",
        f"FSS2S providers: {s2s_count} ({standard_count} standard, {transparent_count} transparent)  ",
        f"FSS3 providers:  {fss3_count}  ",
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
        "- `apply-shc-deployer.sh` — file-based apply through the SHC deployer bundle",
        "- `apply-rest.sh` — REST-based apply for both Splunk Enterprise and Splunk Cloud Platform",
        "- `status.sh` — REST GET /services/data/federated/provider; reports connectivityStatus per provider",
        "- `global-enable.sh` / `global-disable.sh` — toggle the global federated-search switch",
        "- `aws-s3-providers/<name>.json` — REST payload for each FSS3 provider (Splunk Cloud only)",
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
        f"""splunk_home={splunk_home}
test -x "${{splunk_home}}/bin/splunk"
"${{splunk_home}}/bin/splunk" btool federated list --debug >/dev/null || true
"${{splunk_home}}/bin/splunk" btool indexes list --debug >/dev/null || true
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
        "import sys\n"
        "from pathlib import Path\n"
        "\n"
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
        "    pw_path = Path(password_file)\n"
        "    if not pw_path.is_file():\n"
        "        raise SystemExit(f'ERROR: password_file missing for provider {provider_name}: {pw_path}')\n"
        "    pw = pw_path.read_text(encoding='utf-8').strip()\n"
        "    if not pw:\n"
        "        raise SystemExit(f'ERROR: password_file is empty for provider {provider_name}: {pw_path}')\n"
        "    text = text.replace(token, pw)\n"
        "target.write_text(text, encoding='utf-8')\n"
        "PY\n"
        'chmod 600 "${target_dir}/federated.conf"\n'
    )


def render_apply_local(spec: Spec, *, shc: bool) -> str:
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
        'echo "INFO: FSS3 providers are not file-managed; run apply-rest.sh against Splunk Cloud."\n'
        if spec.fss3_providers
        else ""
    )
    indexes_copy = (
        'cp indexes.conf "${target_dir}/indexes.conf"\n'
        if any(idx for idx in spec.federated_indexes if idx.provider in {p.name for p in spec.s2s_providers})
        else 'echo "INFO: No FSS2S federated indexes in spec; indexes.conf not copied."\n'
    )
    return make_script(
        f"""splunk_home={splunk_home}
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
    fss3_payloads_lines: list[str] = []
    for provider in spec.fss3_providers:
        fss3_payloads_lines.append(
            f"  ({json.dumps(provider.name)}, Path('aws-s3-providers') / {json.dumps(provider.name + '.json')}),"
        )
    fss3_block = "\n".join(fss3_payloads_lines) if fss3_payloads_lines else ""

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
    for idx in spec.federated_indexes:
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
        "import sys\n"
        "import urllib.error\n"
        "import urllib.parse\n"
        "import urllib.request\n"
        "import ssl\n"
        "from pathlib import Path\n"
        "\n"
        "splunk_uri = os.environ.get('SPLUNK_REST_URI', '').rstrip('/')\n"
        "splunk_user = os.environ.get('SPLUNK_REST_USER', '')\n"
        "splunk_pw_file = os.environ.get('SPLUNK_REST_PASSWORD_FILE', '')\n"
        "verify_ssl = os.environ.get('SPLUNK_REST_VERIFY_SSL', 'true').lower() not in {'false', '0', 'no'}\n"
        "if not splunk_uri or not splunk_user or not splunk_pw_file:\n"
        "    raise SystemExit('ERROR: set SPLUNK_REST_URI, SPLUNK_REST_USER, SPLUNK_REST_PASSWORD_FILE before apply-rest.sh.')\n"
        "splunk_pw_path = Path(splunk_pw_file)\n"
        "if not splunk_pw_path.is_file():\n"
        "    raise SystemExit(f'ERROR: SPLUNK_REST_PASSWORD_FILE does not exist: {splunk_pw_path}')\n"
        "splunk_pw = splunk_pw_path.read_text(encoding='utf-8').strip()\n"
        "if not splunk_pw:\n"
        "    raise SystemExit('ERROR: SPLUNK_REST_PASSWORD_FILE is empty.')\n"
        "ctx = None if verify_ssl else ssl._create_unverified_context()\n"
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
        "        with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:\n"
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
        "    pw_path = Path(pw_file)\n"
        "    if not pw_path.is_file():\n"
        "        raise SystemExit(f\"ERROR: password_file missing for provider {entry['name']}: {pw_path}\")\n"
        "    entry['password'] = pw_path.read_text(encoding='utf-8').strip()\n"
        "    if not entry['password']:\n"
        "        raise SystemExit(f\"ERROR: password_file is empty for provider {entry['name']}: {pw_path}\")\n"
        "    if entry['mode'] == 'transparent':\n"
        "        # Splunk forces useFSHKnowledgeObjects=1 for transparent and ignores appContext.\n"
        "        entry.pop('appContext', None)\n"
        "    print(f\"Provider {entry['name']} (FSS2S, {entry['mode']}): POST /services/data/federated/provider\")\n"
        "    post_or_update('/services/data/federated/provider', entry['name'], entry)\n"
        "\n"
        "# Step 2: FSS3 providers (Splunk Cloud Platform only)\n"
        "fss3_payload_paths = [\n"
        f"{fss3_block}\n"
        "]\n"
        "for name, payload_path in fss3_payload_paths:\n"
        "    payload = json.loads(Path(payload_path).read_text(encoding='utf-8'))\n"
        "    print(f'Provider {name} (FSS3): POST /services/data/federated/provider')\n"
        "    post_or_update('/services/data/federated/provider', name, payload)\n"
        "\n"
        "# Step 3: federated indexes (FSS2S standard mode + FSS3)\n"
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
    return make_script(
        "echo 'Splunk Federated Search REST apply'\n"
        "echo 'Required env: SPLUNK_REST_URI=https://<sh>:8089 SPLUNK_REST_USER=admin SPLUNK_REST_PASSWORD_FILE=/path/to/admin_pw'\n"
        "echo 'Optional env: SPLUNK_REST_VERIFY_SSL=false (only for self-signed dev clusters)'\n"
        "\n"
        + _rest_provider_payload_block(spec)
    )


def render_status(spec: Spec) -> str:
    return make_script(
        "splunk_uri=\"${SPLUNK_REST_URI:-}\"\n"
        "splunk_user=\"${SPLUNK_REST_USER:-}\"\n"
        "splunk_pw_file=\"${SPLUNK_REST_PASSWORD_FILE:-}\"\n"
        "if [[ -z \"${splunk_uri}\" || -z \"${splunk_user}\" || -z \"${splunk_pw_file}\" ]]; then\n"
        "  echo 'ERROR: set SPLUNK_REST_URI, SPLUNK_REST_USER, SPLUNK_REST_PASSWORD_FILE.' >&2\n"
        "  exit 1\n"
        "fi\n"
        "if [[ ! -s \"${splunk_pw_file}\" ]]; then\n"
        "  echo \"ERROR: password file missing or empty: ${splunk_pw_file}\" >&2\n"
        "  exit 1\n"
        "fi\n"
        "verify_arg=\"--cacert /etc/ssl/certs/ca-certificates.crt\"\n"
        "if [[ \"${SPLUNK_REST_VERIFY_SSL:-true}\" == \"false\" ]]; then\n"
        "  verify_arg=\"--insecure\"\n"
        "fi\n"
        "user_pass_file=\"$(mktemp)\"\n"
        "trap 'rm -f \"${user_pass_file}\"' EXIT INT TERM\n"
        "{ printf 'user = %s\\n' \"${splunk_user}\"; printf 'password = '; cat \"${splunk_pw_file}\"; printf '\\n'; } > \"${user_pass_file}\"\n"
        "chmod 600 \"${user_pass_file}\"\n"
        "echo '== Federated providers =='\n"
        "curl -fsS ${verify_arg} -K \"${user_pass_file}\" \"${splunk_uri%/}/services/data/federated/provider?output_mode=json&count=0\" \\\n"
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
        "curl -fsS ${verify_arg} -K \"${user_pass_file}\" \"${splunk_uri%/}/services/data/federated/index?output_mode=json&count=0\" \\\n"
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
        "curl -fsS ${verify_arg} -K \"${user_pass_file}\" \"${splunk_uri%/}/services/data/federated/settings/general?output_mode=json\" \\\n"
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
        "splunk_uri=\"${SPLUNK_REST_URI:-}\"\n"
        "splunk_user=\"${SPLUNK_REST_USER:-}\"\n"
        "splunk_pw_file=\"${SPLUNK_REST_PASSWORD_FILE:-}\"\n"
        "if [[ -z \"${splunk_uri}\" || -z \"${splunk_user}\" || -z \"${splunk_pw_file}\" ]]; then\n"
        "  echo 'ERROR: set SPLUNK_REST_URI, SPLUNK_REST_USER, SPLUNK_REST_PASSWORD_FILE.' >&2\n"
        "  exit 1\n"
        "fi\n"
        "verify_arg=\"--cacert /etc/ssl/certs/ca-certificates.crt\"\n"
        "if [[ \"${SPLUNK_REST_VERIFY_SSL:-true}\" == \"false\" ]]; then\n"
        "  verify_arg=\"--insecure\"\n"
        "fi\n"
        "user_pass_file=\"$(mktemp)\"\n"
        "trap 'rm -f \"${user_pass_file}\"' EXIT INT TERM\n"
        "{ printf 'user = %s\\n' \"${splunk_user}\"; printf 'password = '; cat \"${splunk_pw_file}\"; printf '\\n'; } > \"${user_pass_file}\"\n"
        "chmod 600 \"${user_pass_file}\"\n"
        f"curl -fsS ${{verify_arg}} -K \"${{user_pass_file}}\" -X POST -d 'disabled={flag}' \\\n"
        "  \"${splunk_uri%/}/services/data/federated/settings/general\"\n"
        f"echo 'Global federated-search switch updated: disabled={flag}'\n"
    )


def render_metadata(spec: Spec, *, render_dir: Path) -> str:
    standard_s2s_names = {p.name for p in spec.s2s_providers if p.mode == "standard"}
    referenced = {idx.provider for idx in spec.federated_indexes}
    unmapped_standard = sorted(standard_s2s_names - referenced)
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
        "warnings": (
            [
                f"Standard-mode FSS2S provider '{name}' has no federated_indexes entries; "
                "searches against it will return nothing until you map at least one dataset."
                for name in unmapped_standard
            ]
        ),
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
        help="YAML or JSON spec file (multi-provider, multi-index, FSS2S + FSS3).",
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
        },
        "federated_index_count": len(spec.federated_indexes),
        "commands": {
            "preflight": [["./preflight.sh"]],
            "apply": [
                ["./apply-search-head.sh"],
                ["./apply-shc-deployer.sh"],
                ["./apply-rest.sh"],
            ],
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

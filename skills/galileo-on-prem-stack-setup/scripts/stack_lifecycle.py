#!/usr/bin/env python3
"""Fail-closed Galileo On-Prem stack bundle and lifecycle engine."""

from __future__ import annotations

import argparse
import base64
import copy
import datetime as dt
import hashlib
import ipaddress
import io
import json
import os
import pwd
import re
import shutil
import socket
import ssl
import stat
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

try:
    import yaml
except ModuleNotFoundError as exc:  # pragma: no cover
    raise SystemExit("ERROR: PyYAML is required") from exc


SKILL_DIR = Path(__file__).resolve().parents[1]
FEATURE_MATRIX = SKILL_DIR / "references" / "deployment-feature-matrix.json"
RETENTION_HELPER = SKILL_DIR / "scripts" / "retain_resources.py"
BUNDLE_SCHEMA = "galileo-on-prem-stack-bundle/v1"
RELEASE_CONTRACT_SCHEMA = "galileo-on-prem-stack-release-contract/v1"
IMAGE_EVIDENCE_SCHEMA = "galileo-on-prem-stack-rendered-image-inventory/v1"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
DNS_RE = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
ITEM_RE = re.compile(r"[^a-z0-9._-]+")
PLACEHOLDER_RE = re.compile(r"<[^>\n]+>|\b(?:TODO|CHANGEME|REPLACE_ME)\b", re.I)
SECRET_VALUE_RE = re.compile(
    r"(?:password|passwd|token|private.?key|api.?key|cookie.?secret|client.?secret|dockerconfig)(?:\s*[:=]|\s+\S)|\bBearer\s+\S+|-----BEGIN\s+[A-Z ]*PRIVATE KEY-----",
    re.I,
)
RUNTIME_CATEGORIES = (
    "dependency",
    "schema_or_enable_flag",
    "image",
    "crd",
    "hook_or_migration",
    "cluster_scoped_object",
    "api_kind",
    "service_or_route",
    "persistence",
)
CLUSTER_KINDS = {
    "ClusterRole",
    "ClusterRoleBinding",
    "CustomResourceDefinition",
    "MutatingWebhookConfiguration",
    "ValidatingWebhookConfiguration",
    "APIService",
    "Namespace",
    "StorageClass",
    "IngressClass",
    "GatewayClass",
    "PriorityClass",
    "PersistentVolume",
    "Node",
    "RuntimeClass",
    "CSIDriver",
    "CSINode",
    "VolumeAttachment",
    "VolumeSnapshotClass",
    "VolumeGroupSnapshotClass",
}
FORBIDDEN_HELM_WORDS = {
    "--atomic",
    "--reuse-values",
    "--force",
    "--take-ownership",
    "--replace",
    "--cleanup-on-fail",
    "--disable-openapi-validation",
    "--skip-schema-validation",
    "--insecure-skip-tls-verify",
    "--pass-credentials",
    "--no-hooks",
}


class ContractError(RuntimeError):
    pass


class StrictSafeLoader(yaml.SafeLoader):
    """Safe YAML loader with unambiguous mapping semantics.

    Deployment evidence must never depend on PyYAML's last-key-wins behavior.
    Aliases and merge keys are also rejected so a reviewed path has exactly one
    lexical source in security-sensitive inputs and rendered evidence.
    """

    def compose_node(self, parent: Any, index: Any) -> Any:
        if self.check_event(yaml.AliasEvent):
            raise yaml.constructor.ConstructorError(None, None, "YAML aliases are not allowed", self.peek_event().start_mark)
        return super().compose_node(parent, index)

    def construct_mapping(self, node: Any, deep: bool = False) -> dict[Any, Any]:
        if not isinstance(node, yaml.MappingNode):
            raise yaml.constructor.ConstructorError(None, None, "expected a mapping", node.start_mark)
        result: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                raise yaml.constructor.ConstructorError(None, None, "YAML merge keys are not allowed", key_node.start_mark)
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in result
            except TypeError as exc:
                raise yaml.constructor.ConstructorError(None, None, "unhashable YAML mapping key", key_node.start_mark) from exc
            if duplicate:
                raise yaml.constructor.ConstructorError(None, None, f"duplicate YAML key: {key!r}", key_node.start_mark)
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def strict_yaml_load(data: str | bytes) -> Any:
    return yaml.load(data, Loader=StrictSafeLoader)


def strict_yaml_load_all(data: str | bytes) -> list[Any]:
    return list(yaml.load_all(data, Loader=StrictSafeLoader))


def fail(message: str) -> None:
    raise ContractError(message)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def lexical_absolute(raw: str | Path) -> Path:
    path = Path(raw).expanduser()
    return path if path.is_absolute() else Path.cwd() / path


def reject_symlink_ancestors(path: Path, field: str) -> None:
    absolute = lexical_absolute(path)
    current = Path(absolute.anchor)
    for part in absolute.parts[1:-1]:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            fail(f"{field} has a missing ancestor")
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            fail(f"{field} has a symlink or non-directory ancestor")


def secure_read(
    raw: str | Path,
    field: str,
    *,
    private: bool = False,
    one_link: bool = True,
    owner: bool = True,
    limit: int = 1024 * 1024 * 1024,
) -> tuple[Path, bytes, os.stat_result]:
    path = lexical_absolute(raw)
    reject_symlink_ancestors(path, field)
    try:
        initial = path.lstat()
    except FileNotFoundError:
        fail(f"{field} does not exist")
    if stat.S_ISLNK(initial.st_mode) or not stat.S_ISREG(initial.st_mode):
        fail(f"{field} must be a regular non-symlink file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except (FileNotFoundError, OSError) as exc:
        fail(f"cannot securely open {field}: {type(exc).__name__}")
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            fail(f"{field} must be a regular non-symlink file")
        if owner and before.st_uid != os.getuid():
            fail(f"{field} must be owned by the current user")
        if one_link and before.st_nlink != 1:
            fail(f"{field} must have exactly one hard link")
        if private and stat.S_IMODE(before.st_mode) & 0o077:
            fail(f"{field} must have mode 0600 or stricter")
        blocks: list[bytes] = []
        size = 0
        while True:
            block = os.read(descriptor, min(1024 * 1024, limit + 1 - size))
            if not block:
                break
            blocks.append(block)
            size += len(block)
            if size > limit:
                fail(f"{field} exceeds the safe size limit")
        after = os.fstat(descriptor)
        try:
            live = path.lstat()
        except FileNotFoundError:
            fail(f"{field} changed while being read")
        identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        if identity_before != identity_after or (live.st_dev, live.st_ino) != (after.st_dev, after.st_ino) or stat.S_ISLNK(live.st_mode):
            fail(f"{field} changed while being read")
        return path, b"".join(blocks), after
    finally:
        os.close(descriptor)


def sha256_file(path: Path) -> str:
    return sha256_bytes(secure_read(path, str(path), owner=True)[1])


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def yaml_bytes(value: Any) -> bytes:
    return yaml.safe_dump(value, sort_keys=True, default_flow_style=False).encode()


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def utc_text(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time(value: Any, field: str) -> dt.datetime:
    if not isinstance(value, str) or not value:
        fail(f"{field} must be an ISO-8601 UTC timestamp")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        fail(f"{field} must be an ISO-8601 UTC timestamp")
    if parsed.tzinfo is None:
        fail(f"{field} must include a timezone")
    return parsed.astimezone(dt.timezone.utc)


def duration_seconds(value: str) -> int:
    match = re.fullmatch(r"([1-9][0-9]*)([smh])", value)
    if not match:
        fail("duration must be a positive Helm duration")
    return int(match.group(1)) * {"s": 1, "m": 60, "h": 3600}[match.group(2)]


def helm_process_timeout(value: str) -> int:
    """Allow Helm's validated timeout plus bounded client-side cleanup time."""
    return min(duration_seconds(value) + 120, 4 * 3600 + 120)


def assert_mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(f"{field} must be a mapping")
    return value


def assert_list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        fail(f"{field} must be a list")
    return value


def quantity_bytes(value: Any, field: str) -> int:
    if not isinstance(value, str):
        fail(f"{field} must be a Kubernetes byte quantity")
    match = re.fullmatch(r"([1-9][0-9]*)([KMGTP]i?|[kMGTPE])", value)
    if not match:
        fail(f"{field} must use a positive Kubernetes storage quantity")
    suffix = match.group(2)
    binary = {"Ki": 2**10, "Mi": 2**20, "Gi": 2**30, "Ti": 2**40, "Pi": 2**50}
    decimal = {"k": 10**3, "K": 10**3, "M": 10**6, "G": 10**9, "T": 10**12, "P": 10**15, "E": 10**18}
    return int(match.group(1)) * (binary.get(suffix) or decimal[suffix])


def cpu_millicores(value: Any, field: str) -> int:
    if not isinstance(value, str):
        fail(f"{field} must be a Kubernetes CPU quantity")
    if re.fullmatch(r"[1-9][0-9]*m", value):
        return int(value[:-1])
    if re.fullmatch(r"[1-9][0-9]*", value):
        return int(value) * 1000
    fail(f"{field} must use integer cores or positive millicores")


def require_str(mapping: dict[str, Any], key: str, where: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        fail(f"{where}.{key} must be a nonempty string")
    return value.strip()


def check_keys(mapping: dict[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        fail(f"{where} contains unknown fields: {', '.join(unknown)}")


def load_yaml(path: Path, field: str = "file", *, private: bool = False) -> Any:
    try:
        raw = secure_read(path, field, private=private)[1]
        value = strict_yaml_load(raw.decode("utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        fail(f"cannot read valid YAML from {field}: {type(exc).__name__}")
    return value


def safe_input_file(
    raw: str,
    field: str,
    *,
    private: bool = False,
    one_link: bool = True,
) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        fail(f"{field} is required")
    path, _, _ = secure_read(raw, field, private=private, one_link=one_link)
    return path


def safe_name(value: str, field: str) -> str:
    if len(value) > 63 or not DNS_RE.fullmatch(value):
        fail(f"{field} must be a DNS-label-safe Kubernetes name")
    return value


def console_url(value: str) -> str:
    parsed = urlparse(value)
    try:
        parsed.port
    except ValueError:
        fail("--galileo-console-url contains an invalid port")
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        fail("--galileo-console-url must be an HTTPS URL without embedded credentials")
    if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        fail("--galileo-console-url must be an origin URL without path, params, query, or fragment")
    return value.rstrip("/") + "/"


def contains_placeholder(value: Any) -> bool:
    if isinstance(value, str):
        return bool(PLACEHOLDER_RE.search(value))
    if isinstance(value, list):
        return any(contains_placeholder(item) for item in value)
    if isinstance(value, dict):
        return any(contains_placeholder(key) or contains_placeholder(item) for key, item in value.items())
    return False


def reject_secret_like_scalars(value: Any, field: str) -> None:
    """Keep credential-shaped literal material out of durable specs/bundles."""
    if isinstance(value, str):
        parsed = urlparse(value)
        if SECRET_VALUE_RE.search(value) or (parsed.scheme and (parsed.username is not None or parsed.password is not None)):
            fail(f"{field} contains credential-shaped scalar content")
    if isinstance(value, list):
        for item in value:
            reject_secret_like_scalars(item, field)
    elif isinstance(value, dict):
        for item in value.values():
            reject_secret_like_scalars(item, field)


def normalized_key(value: str) -> str:
    """Normalize snake/kebab/dotted/camel/case variants for key policy."""
    separated = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    separated = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", separated)
    return re.sub(r"[^a-z0-9]", "", separated.lower())


def key_tokens(value: str) -> tuple[str, ...]:
    separated = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    separated = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", separated)
    return tuple(
        token.lower()
        for token in re.split(r"[^A-Za-z0-9]+", separated)
        if token
    )


def classify_key(
    path: tuple[str, ...],
    parent_schema: str,
) -> str:
    """Classify one key through the shared durable-secret boundary.

    Callers establish exact structural context first and pass either
    ``nonsecret-values-structural`` or ``kubernetes-structural``. Reference
    classification is intentionally limited to the reviewed values contract;
    rendered CR fields named ``secretRef`` are not trusted without a known
    Kubernetes built-in path and are therefore classified as literals.
    """
    if not path:
        return "ordinary"
    key = path[-1]
    normalized = normalized_key(key)
    tokens = key_tokens(key)
    if parent_schema in {"nonsecret-values-structural", "kubernetes-structural"}:
        if normalized in {
            "automountserviceaccounttoken",
            "serviceaccounttoken",
            "tokenexpirationseconds",
            "expirationseconds",
        }:
            return "structural_nonsecret"
    if parent_schema == "nonsecret-values":
        if (
            normalized in {"existingsecret", "secretname", "secretref", "secretkeyref"}
            or normalized.endswith("secretname")
        ):
            return "secret_reference"
    # Conservative containment, after the exact exemptions above, catches
    # wrapper fields such as secretValue, databasePasswordConfig, and
    # accessTokenData instead of relying on a bypassable suffix list.
    sensitive_fragments = (
        "secret",
        "password",
        "passwd",
        "token",
        "privatekey",
        "apikey",
        "accesskey",
        "credential",
        "authorization",
        "signingkey",
        "encryptionkey",
        "licensekey",
        "dockerconfig",
    )
    if "pwd" in tokens or any(fragment in normalized for fragment in sensitive_fragments):
        return "secret_literal"
    return "ordinary"


def load_spec(path: Path, cli_console: str) -> dict[str, Any]:
    spec = assert_mapping(load_yaml(path, "--spec"), "spec")
    allowed = {
        "schema_version", "deployment_id", "environment", "installation_method", "galileo_console_url",
        "target", "stack", "galileoctl", "crds", "storage", "data_services", "node_pools",
        "routing", "monitoring", "wizard", "air_gap", "authorization",
        "coverage", "exceptions", "lab_bootstrap",
    }
    check_keys(spec, allowed, "spec")
    if spec.get("schema_version") != 1 or isinstance(spec.get("schema_version"), bool):
        fail("spec.schema_version must be 1")
    if contains_placeholder(spec):
        fail("spec contains unresolved placeholder values")
    reject_secret_like_scalars(spec, "spec")
    deployment = safe_name(require_str(spec, "deployment_id", "spec"), "spec.deployment_id")
    environment = require_str(spec, "environment", "spec")
    if environment not in {"lab", "staging", "production"}:
        fail("spec.environment must be lab, staging, or production")
    installation_method = require_str(spec, "installation_method", "spec")
    if installation_method not in {"helm-cli", "galileoctl", "deployment-script", "step-by-step"}:
        fail("spec.installation_method must select helm-cli, galileoctl, deployment-script, or step-by-step")
    configured_console = console_url(require_str(spec, "galileo_console_url", "spec"))
    if configured_console != console_url(cli_console):
        fail("--galileo-console-url does not match spec.galileo_console_url")

    target = assert_mapping(spec.get("target"), "spec.target")
    check_keys(target, {"kube_context", "api_server", "ca_sha256", "cluster_uid", "namespace", "namespace_create", "namespace_uid"}, "spec.target")
    require_str(target, "kube_context", "spec.target")
    api = require_str(target, "api_server", "spec.target")
    parsed_api = urlparse(api)
    try:
        parsed_api.port
    except ValueError:
        fail("spec.target.api_server contains an invalid port")
    if parsed_api.scheme != "https" or not parsed_api.hostname or parsed_api.username is not None or parsed_api.password is not None or parsed_api.query or parsed_api.fragment:
        fail("spec.target.api_server must be a credential-free HTTPS URL without query/fragment")
    ca = require_str(target, "ca_sha256", "spec.target").lower()
    if not SHA_RE.fullmatch(ca):
        fail("spec.target.ca_sha256 must be 64 lowercase hexadecimal characters")
    require_str(target, "cluster_uid", "spec.target")
    safe_name(require_str(target, "namespace", "spec.target"), "spec.target.namespace")
    if not isinstance(target.get("namespace_create"), bool):
        fail("spec.target.namespace_create must be boolean")
    if target["namespace_create"]:
        fail(
            "namespace creation is a separate operator handoff; Stack preflight requires "
            "namespace_create=false and an exact pre-existing namespace_uid"
        )
    require_str(target, "namespace_uid", "spec.target")

    stack = assert_mapping(spec.get("stack"), "spec.stack")
    check_keys(stack, {"release_name", "chart_archive", "chart_sha256", "chart_version", "nonsecret_values_file", "runtime_secret_value_paths", "timeout"}, "spec.stack")
    safe_name(require_str(stack, "release_name", "spec.stack"), "spec.stack.release_name")
    require_str(stack, "chart_archive", "spec.stack")
    chart_sha = require_str(stack, "chart_sha256", "spec.stack")
    if not SHA_RE.fullmatch(chart_sha):
        fail("spec.stack.chart_sha256 must be a lowercase SHA-256")
    require_str(stack, "chart_version", "spec.stack")
    require_str(stack, "nonsecret_values_file", "spec.stack")
    timeout = require_str(stack, "timeout", "spec.stack")
    stack_secret_paths = assert_list(stack.get("runtime_secret_value_paths"), "spec.stack.runtime_secret_value_paths")
    if (
        not stack_secret_paths
        or len(stack_secret_paths) != len(set(stack_secret_paths))
        or any(
            not isinstance(value, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*", value)
            for value in stack_secret_paths
        )
    ):
        fail("spec.stack.runtime_secret_value_paths must contain unique exact dotted value paths")
    timeout_match = re.fullmatch(r"([1-9][0-9]*)([smh])", timeout)
    if not timeout_match:
        fail("spec.stack.timeout must be a positive Helm duration such as 120m")
    seconds = duration_seconds(timeout)
    if seconds < 900 or seconds > 4 * 3600:
        fail("spec.stack.timeout must be between 15m and 4h")

    crds = assert_mapping(spec.get("crds"), "spec.crds")
    check_keys(crds, {"mode", "upgrade_compatibility_evidence", "conversion_evidence", "stored_versions_evidence"}, "spec.crds")
    if crds.get("mode") not in {"shared", "dedicated"}:
        fail("spec.crds.mode must be shared or dedicated")
    for key in ("upgrade_compatibility_evidence", "conversion_evidence", "stored_versions_evidence"):
        value = crds.get(key)
        if not isinstance(value, str) or len(value) > 512:
            fail(f"spec.crds.{key} must be a bounded string")

    coverage = assert_mapping(spec.get("coverage"), "spec.coverage")
    coverage_keys = {
        "enforce_runtime_inventory", "reviewed_components", "reviewed_kinds",
        "reviewed_images", "reviewed_crds", "reviewed_hooks",
        "reviewed_cluster_scoped_kinds", "reviewed_pvcs", "reviewed_routes",
        "reviewed_schema_or_enable_flags",
    }
    check_keys(coverage, coverage_keys, "spec.coverage")
    if coverage.get("enforce_runtime_inventory") is not True:
        fail("spec.coverage.enforce_runtime_inventory must be true")
    for key in coverage_keys - {"enforce_runtime_inventory"}:
        values = assert_list(coverage.get(key), f"spec.coverage.{key}")
        if any(not isinstance(item, str) or not item for item in values) or len(values) != len(set(values)):
            fail(f"spec.coverage.{key} must contain unique nonempty strings")

    galileoctl = assert_mapping(spec.get("galileoctl"), "spec.galileoctl")
    if not isinstance(galileoctl.get("enabled"), bool):
        fail("spec.galileoctl.enabled must be boolean")
    if galileoctl["enabled"]:
        ctl_keys = {"enabled", "release_name", "chart_archive", "chart_sha256", "chart_version", "nonsecret_values_file", "runtime_secret_value_paths", "port_forward_only", "auth_enabled", "management_roles_enabled", "audit_persistence"}
        check_keys(galileoctl, ctl_keys, "spec.galileoctl")
        safe_name(require_str(galileoctl, "release_name", "spec.galileoctl"), "spec.galileoctl.release_name")
        require_str(galileoctl, "chart_archive", "spec.galileoctl")
        if not SHA_RE.fullmatch(require_str(galileoctl, "chart_sha256", "spec.galileoctl")):
            fail("spec.galileoctl.chart_sha256 must be a lowercase SHA-256")
        require_str(galileoctl, "chart_version", "spec.galileoctl")
        require_str(galileoctl, "nonsecret_values_file", "spec.galileoctl")
        ctl_secret_paths = assert_list(galileoctl.get("runtime_secret_value_paths"), "spec.galileoctl.runtime_secret_value_paths")
        if not ctl_secret_paths or any(not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*", value) for value in ctl_secret_paths) or len(ctl_secret_paths) != len(set(ctl_secret_paths)):
            fail("spec.galileoctl.runtime_secret_value_paths must contain unique exact dotted value paths")
        for key in ("port_forward_only", "auth_enabled", "management_roles_enabled", "audit_persistence"):
            if not isinstance(galileoctl.get(key), bool):
                fail(f"spec.galileoctl.{key} must be boolean")
        if galileoctl["port_forward_only"] is not True or galileoctl["auth_enabled"] is not True:
            fail("galileoctl must default to authenticated port-forward-only access")
        if galileoctl["management_roles_enabled"] is not False:
            fail("galileoctl management roles must be disabled in the immutable base bundle")
    else:
        check_keys(galileoctl, {"enabled"}, "spec.galileoctl")

    for key in ("storage", "data_services", "node_pools", "routing", "monitoring", "wizard", "air_gap", "authorization", "lab_bootstrap"):
        assert_mapping(spec.get(key), f"spec.{key}")
    check_keys(
        spec["storage"],
        {
            "default_class", "classes", "restore_tested", "snapshot_evidence",
            "restore_evidence", "snapshot_evidence_observed_at", "restore_evidence_observed_at",
            "restore_evidence_max_age_days", "operator_claims",
        },
        "spec.storage",
    )
    check_keys(spec["data_services"], {
        "postgres", "redis", "object_store", "clickhouse_backup_verified",
        "clickhouse_restore_verified", "postgres_backup_verified",
        "postgres_restore_verified", "postgres_backup_frequency_hours",
        "object_store_backup_verified", "object_store_restore_verified",
        "object_store_nondefault_secret", "object_store_support_exception",
        "redis_support_exception", "postgres_backup_evidence", "postgres_restore_evidence",
        "clickhouse_backup_evidence", "clickhouse_restore_evidence",
        "object_store_backup_evidence", "object_store_restore_evidence",
        "object_store_backup_bucket", "backup_evidence_observed_at",
        "restore_evidence_observed_at", "restore_evidence_max_age_days",
        "readiness",
    }, "spec.data_services")
    check_keys(spec["node_pools"], {"autoscaler_validated", "cse_sizing_reference", "production_count_exception", "pools"}, "spec.node_pools")
    check_keys(
        spec["routing"],
        {
            "domain", "console_host", "api_host", "grafana_host", "tls_secret_names", "tls_bindings",
            "ingress_class", "gateway_class", "load_balancer_services",
            "load_balancer_lifecycle", "prerequisite_load_balancers",
            "load_balancer_addresses", "dns_validated",
            "certificate_min_valid_days", "tls_required", "streaming_timeout_seconds",
            "streaming_timeout_controls", "public_metrics_blocked", "metrics_protection_resources",
            "trace_route_before_api_catchall", "routes",
        },
        "spec.routing",
    )
    check_keys(spec["monitoring"], {"enabled", "alert_owner", "expected_components"}, "spec.monitoring")
    check_keys(spec["wizard"], {
        "enabled", "gpu_enabled", "gpu_resource", "gpu_node_label",
        "startup_timeout_minutes", "offline_model_sha256", "expected_deployments",
        "triton_required", "hpa_required", "network_policy_required",
        "multi_gpu_cse_reference", "multi_gpu_model_support_evidence",
    }, "spec.wizard")
    check_keys(spec["authorization"], {"rbac_enforced", "evidence"}, "spec.authorization")
    check_keys(spec["lab_bootstrap"], {"enabled", "enable_hostpath_storage", "metallb_address_pool", "service_cidrs", "pod_cidrs", "network_nonoverlap_evidence", "network_evidence_observed_at", "node_labels"}, "spec.lab_bootstrap")
    storage_classes = assert_list(spec["storage"].get("classes"), "spec.storage.classes")
    for index, storage_class in enumerate(storage_classes):
        row = assert_mapping(storage_class, f"spec.storage.classes[{index}]")
        check_keys(row, {"name", "minimum_size_gib", "reclaim_policy", "allow_expansion", "snapshots"}, f"spec.storage.classes[{index}]")
        require_str(row, "name", f"spec.storage.classes[{index}]")
        if row.get("reclaim_policy") not in {"Retain", "Delete"}:
            fail("storage reclaim_policy must be Retain or Delete")
        if not isinstance(row.get("allow_expansion"), bool) or not isinstance(row.get("snapshots"), bool):
            fail("storage allow_expansion and snapshots must be boolean")
        if "minimum_size_gib" in row and (not isinstance(row["minimum_size_gib"], int) or isinstance(row["minimum_size_gib"], bool) or row["minimum_size_gib"] < 1):
            fail("storage minimum_size_gib must be a positive integer")
    if not isinstance(spec["storage"].get("restore_tested"), bool):
        fail("spec.storage.restore_tested must be boolean")
    for section, fields in (
        (spec["storage"], ("snapshot_evidence", "restore_evidence")),
        (
            spec["data_services"],
            (
                "postgres_backup_evidence", "postgres_restore_evidence",
                "clickhouse_backup_evidence", "clickhouse_restore_evidence",
                "object_store_backup_evidence", "object_store_restore_evidence",
                "object_store_backup_bucket",
            ),
        ),
    ):
        for field in fields:
            value = section.get(field)
            if not isinstance(value, str) or len(value) > 512:
                fail(f"evidence field {field} must be a bounded string")
    for field in ("snapshot_evidence_observed_at", "restore_evidence_observed_at"):
        observed = spec["storage"].get(field)
        if observed not in {None, ""}:
            parse_time(observed, f"spec.storage.{field}")
    restore_age = spec["storage"].get("restore_evidence_max_age_days")
    if not isinstance(restore_age, int) or isinstance(restore_age, bool) or not 1 <= restore_age <= 365:
        fail("spec.storage.restore_evidence_max_age_days must be 1..365")
    operator_claims = assert_list(spec["storage"].get("operator_claims"), "spec.storage.operator_claims")
    operator_keys: set[tuple[str, str, str]] = set()
    for index, row_value in enumerate(operator_claims):
        row = assert_mapping(row_value, f"spec.storage.operator_claims[{index}]")
        check_keys(
            row,
            {"kind", "name", "claim_name", "expected_pvc_names", "expected_pvc_owners"},
            f"spec.storage.operator_claims[{index}]",
        )
        kind = require_str(row, "kind", f"spec.storage.operator_claims[{index}]")
        if kind not in {"ClickHouseInstallation", "ClickHouseKeeperInstallation", "RabbitmqCluster"}:
            fail("operator_claims kind is not an approved Galileo persistence-bearing CR")
        name = safe_name(require_str(row, "name", f"spec.storage.operator_claims[{index}]"), "operator claim CR name")
        claim_name = safe_name(require_str(row, "claim_name", f"spec.storage.operator_claims[{index}]"), "operator claim template name")
        names = assert_list(row.get("expected_pvc_names"), f"spec.storage.operator_claims[{index}].expected_pvc_names")
        if not names or any(not isinstance(value, str) or safe_name(value, "operator-generated PVC name") != value for value in names) or len(names) != len(set(names)):
            fail("operator_claims expected_pvc_names must contain unique exact names")
        owner_rows = assert_list(
            row.get("expected_pvc_owners"),
            f"spec.storage.operator_claims[{index}].expected_pvc_owners",
        )
        owner_by_pvc: dict[str, tuple[str, str]] = {}
        for owner_index, owner_value in enumerate(owner_rows):
            owner = assert_mapping(
                owner_value,
                f"spec.storage.operator_claims[{index}].expected_pvc_owners[{owner_index}]",
            )
            check_keys(
                owner,
                {"pvc_name", "kind", "name"},
                f"spec.storage.operator_claims[{index}].expected_pvc_owners[{owner_index}]",
            )
            pvc_name = safe_name(
                require_str(owner, "pvc_name", "operator PVC owner"),
                "operator PVC owner pvc_name",
            )
            owner_kind = require_str(owner, "kind", "operator PVC owner")
            if owner_kind not in {
                "StatefulSet", "ClickHouseInstallation",
                "ClickHouseKeeperInstallation", "RabbitmqCluster",
            }:
                fail("operator PVC owner kind is not an approved persistence controller")
            owner_name = safe_name(
                require_str(owner, "name", "operator PVC owner"),
                "operator PVC owner name",
            )
            if pvc_name in owner_by_pvc:
                fail("operator_claims expected_pvc_owners contains a duplicate PVC")
            owner_by_pvc[pvc_name] = (owner_kind, owner_name)
        if set(owner_by_pvc) != set(names):
            fail("operator_claims must bind one exact direct controller owner for every expected PVC")
        identity = (kind, name, claim_name)
        if identity in operator_keys:
            fail("operator_claims contains a duplicate CR/template identity")
        operator_keys.add(identity)
    for field in ("backup_evidence_observed_at", "restore_evidence_observed_at"):
        observed = spec["data_services"].get(field)
        if observed not in {None, ""}:
            parse_time(observed, f"spec.data_services.{field}")
    data_restore_age = spec["data_services"].get("restore_evidence_max_age_days")
    if not isinstance(data_restore_age, int) or isinstance(data_restore_age, bool) or not 1 <= data_restore_age <= 365:
        fail("spec.data_services.restore_evidence_max_age_days must be 1..365")
    for key in ("clickhouse_backup_verified", "clickhouse_restore_verified", "postgres_backup_verified", "postgres_restore_verified", "object_store_backup_verified", "object_store_restore_verified", "object_store_nondefault_secret"):
        if key in spec["data_services"] and not isinstance(spec["data_services"][key], bool):
            fail(f"spec.data_services.{key} must be boolean")
    frequency = spec["data_services"].get("postgres_backup_frequency_hours")
    if not isinstance(frequency, int) or isinstance(frequency, bool) or frequency < 1 or frequency > 168:
        fail("spec.data_services.postgres_backup_frequency_hours must be 1..168")
    allowed_data = {
        "postgres": {"external-ha", "self-hosted-ha", "bundled-lab"},
        "redis": {"managed", "external-ha", "in-cluster-exception"},
        "object_store": {"external-s3", "external-gcs", "external-s3-compatible", "in-cluster-minio", "external-azure-blob-exception"},
    }
    for key, allowed_values in allowed_data.items():
        if spec["data_services"].get(key) not in allowed_values:
            fail(f"spec.data_services.{key} must be one of the documented topology values")
    support_exception = spec["data_services"].get("redis_support_exception")
    if spec["data_services"]["redis"] == "in-cluster-exception":
        if not isinstance(support_exception, str) or not support_exception.strip():
            fail("in-cluster Redis requires a written Galileo support exception")
    elif support_exception not in {None, ""}:
        fail("redis_support_exception is allowed only for in-cluster-exception")
    object_store_exception = spec["data_services"].get("object_store_support_exception")
    if spec["data_services"]["object_store"] == "external-azure-blob-exception":
        if not isinstance(object_store_exception, str) or not object_store_exception.strip():
            fail("Azure Blob core storage requires a written Galileo/CSE support exception resolving the documentation conflict")
    elif object_store_exception not in {None, ""}:
        fail("object_store_support_exception is allowed only for external-azure-blob-exception")
    readiness = assert_mapping(spec["data_services"].get("readiness"), "spec.data_services.readiness")
    check_keys(readiness, {"observed_at", "postgres", "redis", "object_store", "clickhouse", "rabbitmq"}, "spec.data_services.readiness")
    for service in ("postgres", "redis", "object_store", "clickhouse", "rabbitmq"):
        proof = assert_mapping(readiness.get(service), f"spec.data_services.readiness.{service}")
        required = {"ownership", "reachable", "tls", "authenticated", "ha_ready", "version", "reference"}
        if service == "object_store":
            required |= {"bucket_exists"}
        if service == "redis":
            required |= {"persistence_or_rebuild_decision"}
        if service == "rabbitmq":
            required |= {"persistence_ready", "queue_recovery_reference"}
        check_keys(proof, required, f"spec.data_services.readiness.{service}")
        string_keys = {"ownership", "version", "reference", "persistence_or_rebuild_decision", "queue_recovery_reference"}
        for key in required - string_keys:
            if not isinstance(proof.get(key), bool):
                fail(f"spec.data_services.readiness.{service}.{key} must be boolean")
        for key in required & string_keys:
            if not isinstance(proof.get(key), str) or len(proof[key]) > 512:
                fail(f"spec.data_services.readiness.{service}.{key} must be a bounded string")
        if proof["ownership"] not in {"external", "release-managed"}:
            fail(f"spec.data_services.readiness.{service}.ownership must be external or release-managed")
    if readiness.get("observed_at") not in {None, ""}:
        parse_time(readiness["observed_at"], "spec.data_services.readiness.observed_at")
    expected_ownership = {
        "postgres": "release-managed" if spec["data_services"]["postgres"] == "bundled-lab" else "external",
        "redis": "release-managed" if spec["data_services"]["redis"] == "in-cluster-exception" else "external",
        "object_store": "release-managed" if spec["data_services"]["object_store"] == "in-cluster-minio" else "external",
    }
    for service, ownership in expected_ownership.items():
        if readiness[service]["ownership"] != ownership:
            fail(f"data-service topology requires readiness.{service}.ownership={ownership}")
    node_pools = spec["node_pools"]
    if not isinstance(node_pools.get("autoscaler_validated"), bool):
        fail("spec.node_pools.autoscaler_validated must be boolean")
    if not isinstance(node_pools.get("cse_sizing_reference"), str):
        fail("spec.node_pools.cse_sizing_reference must be a string")
    count_exception = node_pools.get("production_count_exception")
    if count_exception not in {None, ""} and (not isinstance(count_exception, str) or not count_exception.strip()):
        fail("spec.node_pools.production_count_exception must be null or a written CSE exception")
    pools = assert_list(node_pools.get("pools"), "spec.node_pools.pools")
    seen_roles: set[str] = set()
    for index, pool_value in enumerate(pools):
        pool = assert_mapping(pool_value, f"spec.node_pools.pools[{index}]")
        check_keys(pool, {"role", "label_value", "min_nodes", "max_nodes", "min_cpu", "min_memory", "min_ephemeral_storage", "architecture", "failure_domains", "taints"}, f"spec.node_pools.pools[{index}]")
        role = require_str(pool, "role", f"spec.node_pools.pools[{index}]")
        if role not in {"core", "runner", "ml"} or role in seen_roles:
            fail("node pool roles must be unique core, runner, or optional ml")
        seen_roles.add(role)
        if pool.get("label_value") != f"galileo-{role}":
            fail(f"node pool {role} must use label value galileo-{role}")
        for count_key in ("min_nodes", "max_nodes"):
            count = pool.get(count_key)
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                fail(f"node pool {role} {count_key} must be a nonnegative integer")
        if pool["max_nodes"] < pool["min_nodes"]:
            fail(f"node pool {role} max_nodes must be at least min_nodes")
        cpu_millicores(pool.get("min_cpu"), f"node pool {role} min_cpu")
        quantity_bytes(pool.get("min_memory"), f"node pool {role} min_memory")
        quantity_bytes(pool.get("min_ephemeral_storage"), f"node pool {role} min_ephemeral_storage")
        if pool.get("architecture") not in {"amd64", "arm64"}:
            fail(f"node pool {role} architecture must be amd64 or arm64")
        domains = assert_list(pool.get("failure_domains"), f"node pool {role} failure_domains")
        if any(not isinstance(item, str) or not item for item in domains):
            fail(f"node pool {role} failure_domains must contain nonempty strings")
        taints = assert_list(pool.get("taints"), f"node pool {role} taints")
        if any(
            not isinstance(item, str)
            or not re.fullmatch(r"[A-Za-z0-9./_-]+=[^:=]*:(?:NoSchedule|PreferNoSchedule|NoExecute)", item)
            for item in taints
        ):
            fail(f"node pool {role} taints must contain nonempty key=value:effect strings")
    if "core" not in seen_roles or "runner" not in seen_roles:
        fail("node_pools must declare core and runner pools")
    routes = assert_list(spec["routing"].get("routes"), "spec.routing.routes")
    routing_domain = require_str(spec["routing"], "domain", "spec.routing").lower().rstrip(".")
    if len(routing_domain) > 253 or "." not in routing_domain or any(not DNS_RE.fullmatch(label) for label in routing_domain.split(".")):
        fail("spec.routing.domain must be an exact reviewed DNS domain")
    console_host = str(urlparse(configured_console).hostname).lower().rstrip(".")
    if console_host != routing_domain and not console_host.endswith(f".{routing_domain}"):
        fail("Galileo console hostname must remain under spec.routing.domain")
    for route in routes:
        parsed_route = urlparse(route) if isinstance(route, str) else None
        try:
            if parsed_route is not None:
                parsed_route.port
        except ValueError:
            parsed_route = None
        if (
            parsed_route is None
            or parsed_route.scheme != "https"
            or not parsed_route.hostname
            or parsed_route.username is not None
            or parsed_route.password is not None
            or parsed_route.query
            or parsed_route.fragment
        ):
            fail("spec.routing.routes must contain credential-free HTTPS URLs without query/fragment")
        route_host = parsed_route.hostname.lower().rstrip(".")
        if route_host != routing_domain and not route_host.endswith(f".{routing_domain}"):
            fail("spec.routing.routes must remain under the reviewed Galileo routing domain")
    reviewed_hosts: list[str] = []
    for key in ("console_host", "api_host", "grafana_host"):
        host = require_str(spec["routing"], key, "spec.routing").lower().rstrip(".")
        if len(host) > 253 or any(not DNS_RE.fullmatch(label) for label in host.split(".")):
            fail(f"spec.routing.{key} must be a valid DNS hostname")
        if host != routing_domain and not host.endswith(f".{routing_domain}"):
            fail(f"spec.routing.{key} must remain under the reviewed routing domain")
        reviewed_hosts.append(host)
        spec["routing"][key] = host
    if console_host != spec["routing"]["console_host"].lower().rstrip(".") or len(set(reviewed_hosts)) != 3:
        fail("routing console/api/grafana hosts must be distinct and console-bound")
    for key in ("tls_secret_names", "load_balancer_addresses"):
        values = assert_list(spec["routing"].get(key), f"spec.routing.{key}")
        if not values or any(not isinstance(item, str) or not item for item in values) or len(values) != len(set(values)):
            fail(f"spec.routing.{key} must contain unique nonempty strings")
    tls_bindings = assert_list(spec["routing"].get("tls_bindings"), "spec.routing.tls_bindings")
    reviewed_tls_bindings: set[tuple[str, str]] = set()
    for index, value in enumerate(tls_bindings):
        row = assert_mapping(value, f"spec.routing.tls_bindings[{index}]")
        check_keys(row, {"host", "secret"}, f"spec.routing.tls_bindings[{index}]")
        host = require_str(row, "host", f"spec.routing.tls_bindings[{index}]").lower().rstrip(".")
        secret_name = safe_name(
            require_str(row, "secret", f"spec.routing.tls_bindings[{index}]"),
            "routing TLS Secret",
        )
        if host not in reviewed_hosts or (host, secret_name) in reviewed_tls_bindings:
            fail("routing tls_bindings must uniquely bind only reviewed Galileo hosts")
        reviewed_tls_bindings.add((host, secret_name))
    if {host for host, _ in reviewed_tls_bindings} != set(reviewed_hosts):
        fail("routing tls_bindings must bind every reviewed Galileo host")
    if {secret for _, secret in reviewed_tls_bindings} != set(spec["routing"]["tls_secret_names"]):
        fail("routing tls_bindings Secret set must exactly equal tls_secret_names")
    release_load_balancers = assert_list(
        spec["routing"].get("load_balancer_services"),
        "spec.routing.load_balancer_services",
    )
    if (
        any(not isinstance(item, str) or not item for item in release_load_balancers)
        or len(release_load_balancers) != len(set(release_load_balancers))
    ):
        fail("spec.routing.load_balancer_services must contain unique exact release-rendered Service names")
    for name in spec["routing"]["tls_secret_names"] + spec["routing"]["load_balancer_services"]:
        safe_name(name, "routing Kubernetes resource name")
    prerequisite_load_balancers = assert_list(
        spec["routing"].get("prerequisite_load_balancers"),
        "spec.routing.prerequisite_load_balancers",
    )
    prerequisite_identities: set[tuple[str, str]] = set()
    prerequisite_addresses: set[str] = set()
    for index, value in enumerate(prerequisite_load_balancers):
        row = assert_mapping(value, f"spec.routing.prerequisite_load_balancers[{index}]")
        check_keys(
            row,
            {"namespace", "name", "uid", "addresses"},
            f"spec.routing.prerequisite_load_balancers[{index}]",
        )
        namespace = safe_name(
            require_str(row, "namespace", f"spec.routing.prerequisite_load_balancers[{index}]"),
            "routing prerequisite namespace",
        )
        name = safe_name(
            require_str(row, "name", f"spec.routing.prerequisite_load_balancers[{index}]"),
            "routing prerequisite Service name",
        )
        uid = require_str(row, "uid", f"spec.routing.prerequisite_load_balancers[{index}]")
        if len(uid) > 128 or not re.fullmatch(r"[A-Za-z0-9._:-]+", uid):
            fail("routing prerequisite Service UID is invalid")
        addresses = assert_list(
            row.get("addresses"),
            f"spec.routing.prerequisite_load_balancers[{index}].addresses",
        )
        if (
            not addresses
            or any(not isinstance(item, str) or not item for item in addresses)
            or len(addresses) != len(set(addresses))
        ):
            fail("routing prerequisite Service addresses must be unique and nonempty")
        identity = (namespace, name)
        if identity in prerequisite_identities:
            fail("routing prerequisite LoadBalancer identities must be unique")
        prerequisite_identities.add(identity)
        prerequisite_addresses.update(addresses)
    load_balancer_lifecycle = spec["routing"].get("load_balancer_lifecycle")
    if load_balancer_lifecycle not in {
        "external-preinstalled", "release-managed-staged-handoff",
    }:
        fail("spec.routing.load_balancer_lifecycle must select an exact supported lifecycle")
    if spec["environment"] == "production":
        if load_balancer_lifecycle == "external-preinstalled":
            if not prerequisite_load_balancers:
                fail("production requires an exact pre-existing external LoadBalancer Service identity")
            if release_load_balancers:
                fail("external-preinstalled routing requires no release-rendered LoadBalancer Service")
            if prerequisite_addresses != set(spec["routing"]["load_balancer_addresses"]):
                fail("routing prerequisite Service address union must equal load_balancer_addresses")
        elif not release_load_balancers or prerequisite_load_balancers:
            fail(
                "release-managed-staged-handoff requires exact rendered LoadBalancer names and no spoofable prerequisite Service"
            )
    for address in spec["routing"]["load_balancer_addresses"]:
        try:
            ipaddress.ip_address(address)
        except ValueError:
            hostname = address.lower().rstrip(".")
            if len(hostname) > 253 or any(not DNS_RE.fullmatch(label) for label in hostname.split(".")):
                fail("routing load_balancer_addresses must contain exact IP addresses or DNS hostnames")
    for key in ("ingress_class", "gateway_class"):
        value = spec["routing"].get(key)
        if value not in {None, ""} and (not isinstance(value, str) or not value.strip()):
            fail(f"spec.routing.{key} must be null or a nonempty string")
        if isinstance(value, str) and value:
            safe_name(value, f"spec.routing.{key}")
    if not spec["routing"].get("ingress_class") and not spec["routing"].get("gateway_class"):
        fail("routing requires an explicit ingress_class or gateway_class")
    if not isinstance(spec["routing"].get("dns_validated"), bool):
        fail("spec.routing.dns_validated must be boolean")
    days = spec["routing"].get("certificate_min_valid_days")
    if not isinstance(days, int) or isinstance(days, bool) or days < 1 or days > 365:
        fail("spec.routing.certificate_min_valid_days must be 1..365")
    for key in ("tls_required", "public_metrics_blocked", "trace_route_before_api_catchall"):
        if not isinstance(spec["routing"].get(key), bool):
            fail(f"spec.routing.{key} must be boolean")
    if not isinstance(spec["routing"].get("streaming_timeout_seconds"), int) or isinstance(spec["routing"].get("streaming_timeout_seconds"), bool):
        fail("spec.routing.streaming_timeout_seconds must be an integer")
    timeout_controls = assert_list(spec["routing"].get("streaming_timeout_controls"), "spec.routing.streaming_timeout_controls")
    timeout_identities: set[tuple[str, str, str]] = set()
    for index, value in enumerate(timeout_controls):
        row = assert_mapping(value, f"spec.routing.streaming_timeout_controls[{index}]")
        check_keys(row, {"kind", "name", "annotation", "minimum_seconds"}, f"spec.routing.streaming_timeout_controls[{index}]")
        kind = require_str(row, "kind", "streaming timeout control")
        name = safe_name(require_str(row, "name", "streaming timeout control"), "streaming timeout control name")
        annotation = require_str(row, "annotation", "streaming timeout control")
        minimum = row.get("minimum_seconds")
        if not re.fullmatch(r"[A-Za-z0-9./_-]+", annotation) or not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < spec["routing"]["streaming_timeout_seconds"]:
            fail("streaming timeout control must bind a safe annotation and reviewed minimum")
        identity = (kind, name, annotation)
        if identity in timeout_identities:
            fail("streaming timeout controls contain a duplicate identity")
        timeout_identities.add(identity)
    metrics_controls = assert_list(spec["routing"].get("metrics_protection_resources"), "spec.routing.metrics_protection_resources")
    metrics_identities: set[tuple[str, str]] = set()
    for index, value in enumerate(metrics_controls):
        row = assert_mapping(value, f"spec.routing.metrics_protection_resources[{index}]")
        check_keys(row, {"kind", "name"}, f"spec.routing.metrics_protection_resources[{index}]")
        identity = (
            require_str(row, "kind", "metrics protection resource"),
            safe_name(require_str(row, "name", "metrics protection resource"), "metrics protection resource name"),
        )
        if identity in metrics_identities:
            fail("metrics protection resources contain a duplicate identity")
        metrics_identities.add(identity)
    if spec["environment"] == "production" and (not timeout_controls or not metrics_controls):
        fail("production routing requires exact rendered streaming-timeout and metrics-protection controls")
    if not isinstance(spec["monitoring"].get("enabled"), bool):
        fail("spec.monitoring.enabled must be boolean")
    alert_owner = spec["monitoring"].get("alert_owner")
    if not isinstance(alert_owner, str) or (alert_owner and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._@/+:-]{0,127}", alert_owner)):
        fail("spec.monitoring.alert_owner must be empty or a bounded team/on-call identifier")
    monitoring_components = assert_list(spec["monitoring"].get("expected_components"), "spec.monitoring.expected_components")
    allowed_monitoring = {"prometheus", "grafana", "fluent-bit", "prometheus-adapter", "kube-state-metrics", "alertmanager", "victorialogs"}
    seen_monitoring: set[str] = set()
    for index, component_value in enumerate(monitoring_components):
        component = assert_mapping(component_value, f"spec.monitoring.expected_components[{index}]")
        check_keys(
            component,
            {"name", "workloads", "services", "required_kinds", "resources", "persistence_required"},
            f"spec.monitoring.expected_components[{index}]",
        )
        name = require_str(component, "name", f"spec.monitoring.expected_components[{index}]")
        if name not in allowed_monitoring or name in seen_monitoring:
            fail("monitoring component names must be unique reviewed Galileo monitoring components")
        seen_monitoring.add(name)
        for key in ("workloads", "services", "required_kinds"):
            values = assert_list(component.get(key), f"monitoring {name} {key}")
            if (
                (key != "services" and not values)
                or any(not isinstance(value, str) or not value for value in values)
                or len(values) != len(set(values))
            ):
                fail(f"monitoring {name} {key} must contain unique exact names/kinds")
        resources = assert_list(component.get("resources"), f"monitoring {name} resources")
        resource_identities: set[tuple[str, str]] = set()
        for resource_index, resource_value in enumerate(resources):
            resource = assert_mapping(resource_value, f"monitoring {name} resources[{resource_index}]")
            check_keys(resource, {"kind", "name"}, f"monitoring {name} resources[{resource_index}]")
            kind = require_str(resource, "kind", f"monitoring {name} resource")
            resource_name = safe_name(
                require_str(resource, "name", f"monitoring {name} resource"),
                f"monitoring {name} resource name",
            )
            identity = (kind, resource_name)
            if identity in resource_identities:
                fail(f"monitoring {name} resources contain duplicate exact identities")
            resource_identities.add(identity)
        if {kind for kind, _ in resource_identities} != set(component["required_kinds"]):
            fail(f"monitoring {name} resources must exactly cover required_kinds")
        if not isinstance(component.get("persistence_required"), bool):
            fail(f"monitoring {name} persistence_required must be boolean")
    if spec["monitoring"]["enabled"] != bool(monitoring_components):
        fail("monitoring enabled must exactly match a nonempty expected_components inventory")
    if not isinstance(spec["authorization"].get("rbac_enforced"), bool) or not isinstance(spec["authorization"].get("evidence"), str):
        fail("spec.authorization requires boolean rbac_enforced and string evidence")
    if not isinstance(spec["wizard"].get("enabled"), bool) or not isinstance(spec["wizard"].get("gpu_enabled"), bool):
        fail("spec.wizard enabled/gpu_enabled must be boolean")
    if spec["wizard"].get("gpu_enabled") and spec["wizard"].get("enabled") is not True:
        fail("Wizard GPU mode requires Wizard enabled")
    expected_wizard = assert_list(spec["wizard"].get("expected_deployments"), "spec.wizard.expected_deployments")
    if any(not isinstance(name, str) or not name or safe_name(name, "Wizard deployment") != name for name in expected_wizard) or len(expected_wizard) != len(set(expected_wizard)):
        fail("Wizard expected_deployments must contain unique Kubernetes names")
    if spec["wizard"]["enabled"] != bool(expected_wizard):
        fail("Wizard enabled must exactly match a nonempty expected_deployments list")
    for key in ("triton_required", "hpa_required", "network_policy_required"):
        if not isinstance(spec["wizard"].get(key), bool):
            fail(f"spec.wizard.{key} must be boolean")
        if spec["wizard"].get(key) and not spec["wizard"]["enabled"]:
            fail(f"spec.wizard.{key} requires Wizard enabled")
    for key in ("multi_gpu_cse_reference", "multi_gpu_model_support_evidence"):
        value = spec["wizard"].get(key)
        if not isinstance(value, str) or len(value) > 512:
            fail(f"spec.wizard.{key} must be a bounded string")
    if not isinstance(spec["wizard"].get("startup_timeout_minutes", 40), int) or isinstance(spec["wizard"].get("startup_timeout_minutes", 40), bool) or spec["wizard"].get("startup_timeout_minutes", 40) < 40:
        fail("Wizard startup timeout must allow at least 40 minutes")
    if spec["wizard"].get("gpu_enabled"):
        if spec["wizard"].get("gpu_resource") != "nvidia.com/gpu" or spec["wizard"].get("gpu_node_label") != "galileo-node-type=galileo-ml":
            fail("Wizard GPU mode requires the exact reviewed GPU resource and ML node label")
    if spec["wizard"].get("enabled") and duration_seconds(spec["stack"]["timeout"]) < (spec["wizard"]["startup_timeout_minutes"] + 10) * 60:
        fail("Stack Helm timeout must exceed Wizard startup timeout by at least 10 minutes")
    offline_sha = spec["wizard"].get("offline_model_sha256")
    if offline_sha not in {None, ""} and not isinstance(offline_sha, str):
        fail("Wizard offline model SHA-256 must be a string or null")
    if isinstance(offline_sha, str) and offline_sha and not SHA_RE.fullmatch(offline_sha):
        fail("Wizard offline model SHA-256 must be lowercase hexadecimal")
    air_gap = spec["air_gap"]
    check_keys(air_gap, {"enabled", "verified_contract_file", "verified_contract_sha256"}, "spec.air_gap")
    if not isinstance(air_gap.get("enabled"), bool):
        fail("spec.air_gap.enabled must be boolean")
    if air_gap["enabled"]:
        require_str(air_gap, "verified_contract_file", "spec.air_gap")
        if not SHA_RE.fullmatch(require_str(air_gap, "verified_contract_sha256", "spec.air_gap")):
            fail("spec.air_gap.verified_contract_sha256 must be a lowercase SHA-256")
        if spec["wizard"].get("enabled") and not SHA_RE.fullmatch(str(spec["wizard"].get("offline_model_sha256", ""))):
            fail("air-gapped Wizard requires an exact offline_model_sha256")
    elif air_gap.get("verified_contract_file") not in {None, ""} or air_gap.get("verified_contract_sha256") not in {None, ""}:
        fail("disabled air_gap rejects a contract file/digest")
    exceptions = assert_list(spec.get("exceptions"), "spec.exceptions")
    if any(not isinstance(item, str) or not item.strip() for item in exceptions):
        fail("spec.exceptions must contain nonempty reviewed exception strings")
    for key in ("enabled", "enable_hostpath_storage"):
        if not isinstance(spec["lab_bootstrap"].get(key), bool):
            fail(f"spec.lab_bootstrap.{key} must be boolean")
    assert_mapping(spec["lab_bootstrap"].get("node_labels"), "spec.lab_bootstrap.node_labels")
    for key in ("network_nonoverlap_evidence",):
        value = spec["lab_bootstrap"].get(key)
        if not isinstance(value, str) or len(value) > 512:
            fail(f"spec.lab_bootstrap.{key} must be a bounded string")
    lab_network_time = spec["lab_bootstrap"].get("network_evidence_observed_at")
    if lab_network_time not in {None, ""}:
        parse_time(lab_network_time, "spec.lab_bootstrap.network_evidence_observed_at")
    for key in ("service_cidrs", "pod_cidrs"):
        cidrs = assert_list(spec["lab_bootstrap"].get(key), f"spec.lab_bootstrap.{key}")
        for value in cidrs:
            if not isinstance(value, str):
                fail(f"spec.lab_bootstrap.{key} must contain CIDR strings")
            try:
                canonical = str(ipaddress.ip_network(value, strict=False))
            except ValueError:
                fail(f"spec.lab_bootstrap.{key} contains an invalid CIDR")
            if canonical != value:
                fail(f"spec.lab_bootstrap.{key} CIDRs must be canonical")
        if spec["lab_bootstrap"].get("metallb_address_pool") and not cidrs:
            fail(f"lab MetalLB bootstrap requires explicit reviewed {key}")
    spec["deployment_id"] = deployment
    spec["galileo_console_url"] = configured_console
    return spec


def validate_values_no_secrets(path: Path) -> dict[str, Any]:
    data = load_yaml(path, "non-secret values file")
    values = assert_mapping(data, "non-secret values")
    reject_secret_like_scalars(values, "non-secret values")
    reject_unbound_helm_value_actions(values, "non-secret values")

    def validate_reference(key: str, item: Any, field: str) -> bool:
        """Accept only closed, identifier-only Secret reference shapes."""
        normalized = normalized_key(key)
        if classify_key((key,), "nonsecret-values") != "secret_reference":
            return False
        scalar_name_reference = (
            normalized in {"existingsecret", "secretname"}
            or normalized.endswith("secretname")
        )
        if scalar_name_reference:
            if not isinstance(item, str) or not DNS_RE.fullmatch(item):
                fail(f"{field} must be a DNS-label-safe Secret name")
            return True
        if isinstance(item, str):
            if normalized != "secretref" or not DNS_RE.fullmatch(item):
                fail(f"{field} must be a closed Secret reference mapping")
            return True
        reference = assert_mapping(item, field)
        allowed = {"name", "optional"}
        if normalized == "secretkeyref":
            allowed.add("key")
        check_keys(reference, allowed, field)
        name = reference.get("name")
        if not isinstance(name, str) or not DNS_RE.fullmatch(name):
            fail(f"{field}.name must be a DNS-label-safe Secret name")
        if normalized == "secretkeyref":
            secret_key_name = reference.get("key")
            if not isinstance(secret_key_name, str) or not re.fullmatch(r"[-._A-Za-z0-9]+", secret_key_name):
                fail(f"{field}.key must be a nonempty Secret data-key identifier")
        if "optional" in reference and not isinstance(reference["optional"], bool):
            fail(f"{field}.optional must be boolean")
        return True

    def walk(
        value: Any,
        trail: tuple[str, ...] = (),
        sensitive_context: bool = False,
    ) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                key_text = str(key)
                child_field = ".".join(trail + (key_text,))
                if validate_reference(key_text, item, f"non-secret values.{child_field}"):
                    continue
                structural = (
                    normalized_key(key_text)
                    in {
                        "automountserviceaccounttoken",
                        "serviceaccounttoken",
                    }
                    and isinstance(item, bool)
                ) or (
                    normalized_key(key_text)
                    in {"tokenexpirationseconds", "expirationseconds"}
                    and isinstance(item, int)
                    and not isinstance(item, bool)
                )
                classification = classify_key(
                    trail + (key_text,),
                    "nonsecret-values-structural" if structural else "nonsecret-values",
                )
                child_sensitive = sensitive_context or classification == "secret_literal"
                populated_scalar = not isinstance(item, (dict, list)) and item not in (None, "", False)
                if child_sensitive and populated_scalar:
                    # A chart may call a credential-bearing field *Ref* or
                    # *Name* while still accepting a literal.  Keep all
                    # populated secret-shaped inputs in the runtime-only file.
                    fail(f"non-secret values contain a populated secret-like field at {'.'.join(trail + (key_text,))}")
                walk(item, trail + (key_text,), child_sensitive)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, trail + (str(index),), sensitive_context)
        elif sensitive_context and value not in (None, "", False):
            fail(
                "non-secret values contain a populated secret-like field at "
                f"{'.'.join(trail)}"
            )

    walk(values)
    return values


def validate_runtime_secret_values(
    path: Path,
    field: str,
    allowed_paths: list[str] | None = None,
) -> dict[str, Any]:
    raw_bytes = secure_read(path, field, private=True)[1]
    if re.search(rb"(?:^|[\s\[{,])[&*][A-Za-z0-9_-]+", raw_bytes):
        fail(f"{field} rejects YAML anchors and aliases")
    try:
        document = strict_yaml_load(raw_bytes.decode("utf-8"))
    except (UnicodeError, yaml.YAMLError):
        fail(f"{field} must contain valid UTF-8 YAML")
    mapping = assert_mapping(document, field)
    if not mapping:
        fail(f"{field} must be a nonempty values mapping")
    reject_unbound_helm_value_actions(mapping, field)
    leaf_paths: set[str] = set()

    def collect(value: Any, trail: tuple[str, ...] = ()) -> None:
        if isinstance(value, dict):
            if not value:
                fail(f"{field} contains an empty mapping")
            for key, child in value.items():
                if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", key):
                    fail(f"{field} contains an invalid value key")
                collect(child, trail + (key,))
        elif isinstance(value, list):
            fail(f"{field} rejects list-valued overrides")
        else:
            if not isinstance(value, str) or not value:
                fail(f"{field} leaf values must be nonempty strings")
            leaf_paths.add(".".join(trail))
            if re.fullmatch(r"(?i)(?:password|changeme|admin|secret|default|test|demo|example)", value.strip()):
                fail(f"{field} contains a known placeholder/default credential")

    collect(mapping)
    if allowed_paths is not None and leaf_paths != set(allowed_paths):
        fail(f"{field} leaf paths differ from the exact reviewed runtime-secret allowlist")
    return mapping


def shadow_secret_values(
    value: Any,
    trail: tuple[str, ...] = (),
    only_path: str | None = None,
) -> Any:
    """Perturb one reviewed leaf (or all leaves for legacy fixture use)."""
    if isinstance(value, dict):
        return {
            key: shadow_secret_values(child, trail + (str(key),), only_path)
            for key, child in value.items()
        }
    if not isinstance(value, str):
        fail("runtime Secret shadowing requires string-only scalar values")
    path = ".".join(trail)
    if only_path is not None and path != only_path:
        return value
    token = hashlib.sha256((path + "\0" + value).encode()).hexdigest()
    return f"runtime-shadow-{token}"


def secret_payload_shape(document: dict[str, Any]) -> dict[str, Any]:
    copy_document = copy.deepcopy(document)
    if copy_document.get("kind") == "Secret":
        for field in ("data", "stringData"):
            payload = copy_document.get(field)
            if payload is not None:
                if not isinstance(payload, dict):
                    fail("rendered Secret payload must be a mapping")
                copy_document[field] = {str(key): "<runtime-secret>" for key in sorted(payload)}
    return copy_document


def canonical_redacted_manifest(documents: list[dict[str, Any]]) -> bytes:
    """Serialize every rendered object while replacing only Secret payloads."""
    # Keep this serializer safe when called independently of preflight.  No
    # caller may obtain durable bytes for an invalid plaintext credential
    # placement merely by skipping the surrounding workflow validator.
    validate_rendered_secret_placement(documents)
    redacted: list[dict[str, Any]] = []
    for document in documents:
        item = copy.deepcopy(document)
        if item.get("kind") == "Secret":
            metadata = item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}
            identity = f"{metadata.get('namespace', '')}/{metadata.get('name', '')}"
            for payload_field in ("data", "stringData"):
                payload = item.get(payload_field)
                if payload is None:
                    continue
                if not isinstance(payload, dict):
                    fail("rendered Secret payload must be a mapping")
                item[payload_field] = {
                    str(key): f"<redacted:{identity}/{payload_field}/{key}>"
                    for key in sorted(payload)
                }
        redacted.append(item)
    return yaml.safe_dump_all(
        redacted,
        sort_keys=True,
        explicit_start=True,
        default_flow_style=False,
    ).encode("utf-8")


def validate_rendered_secret_placement(documents: list[dict[str, Any]]) -> None:
    """Reject credential material rendered anywhere except Secret payloads.

    This runs before any redacted render or inventory is persisted.  It is
    deliberately conservative: a chart that cannot keep credentials in
    Secret data/stringData remains a CSE handoff instead of leaking material
    into the immutable review packet.
    """
    default_value = re.compile(
        r"^(?:password|changeme|admin|secret|default|test|demo|example|guest)$",
        re.I,
    )

    def validate_secret_name(value: Any, field: str) -> None:
        if not isinstance(value, str) or not DNS_RE.fullmatch(value):
            fail(f"rendered {field} must be a DNS-label-safe Secret name")

    def validate_secret_key(value: Any, field: str) -> None:
        if not isinstance(value, str) or not re.fullmatch(r"[-._A-Za-z0-9]+", value):
            fail(f"rendered {field} must be a nonempty Secret data-key identifier")

    def closed_reference(value: Any, allowed: set[str], field: str) -> dict[str, Any]:
        reference = assert_mapping(value, f"rendered {field}")
        check_keys(reference, allowed, f"rendered {field}")
        if "optional" in reference and not isinstance(reference["optional"], bool):
            fail(f"rendered {field}.optional must be boolean")
        return reference

    def is_index(value: str) -> bool:
        return value.isdigit()

    active_pod_spec_prefixes: set[tuple[str, ...]] = set()

    def in_pod_spec(trail: tuple[str, ...], suffix: tuple[str, ...]) -> bool:
        return any(trail == prefix + suffix for prefix in active_pod_spec_prefixes)

    def is_container_path(trail: tuple[str, ...], field: str) -> bool:
        if len(trail) < 4 or trail[-2] != field or not is_index(trail[-1]):
            return False
        container_index = trail[-4:-2]
        return (
            len(container_index) == 2
            and container_index[0] in {"containers", "initContainers", "ephemeralContainers"}
            and is_index(container_index[1])
            and in_pod_spec(trail[:-4], ())
        )

    def is_projected_service_account_path(trail: tuple[str, ...]) -> bool:
        for prefix in active_pod_spec_prefixes:
            if trail[: len(prefix)] != prefix:
                continue
            remainder = trail[len(prefix):]
            if (
                len(remainder) == 6
                and remainder[0] == "volumes"
                and is_index(remainder[1])
                and remainder[2] == "projected"
                and remainder[3] == "sources"
                and is_index(remainder[4])
                and remainder[5] == "serviceAccountToken"
            ):
                return True
        return False

    def is_kubernetes_structural_field(trail: tuple[str, ...], value: Any) -> bool:
        normalized = normalized_key(trail[-1]) if trail else ""
        if normalized == "automountserviceaccounttoken":
            return isinstance(value, bool) and any(
                trail == prefix + (trail[-1],) for prefix in active_pod_spec_prefixes
            )
        if normalized == "serviceaccounttoken":
            return isinstance(value, dict) and is_projected_service_account_path(trail)
        if normalized in {"tokenexpirationseconds", "expirationseconds"}:
            return (
                isinstance(value, int)
                and not isinstance(value, bool)
                and is_projected_service_account_path(trail[:-1])
            )
        return False

    def consume_kubernetes_reference(value: Any, trail: tuple[str, ...], identity: str) -> bool:
        """Validate only reference shapes at exact built-in PodSpec paths."""
        field = ".".join(trail)
        if (
            len(trail) >= 2
            and trail[-2] == "imagePullSecrets"
            and is_index(trail[-1])
            and in_pod_spec(trail[:-2], ())
        ):
            reference = closed_reference(value, {"name"}, field)
            validate_secret_name(reference.get("name"), f"{identity} {field}.name")
            return True
        if len(trail) >= 2 and trail[-2:] == ("valueFrom", "secretKeyRef"):
            # The parent of valueFrom must be an EnvVar in a container env[].
            env_path = trail[:-2]
            if not is_container_path(env_path, "env"):
                return False
            reference = closed_reference(value, {"name", "key", "optional"}, field)
            validate_secret_name(reference.get("name"), f"{identity} {field}.name")
            validate_secret_key(reference.get("key"), f"{identity} {field}.key")
            return True
        if len(trail) >= 2 and trail[-1] == "secretRef":
            env_from_path = trail[:-1]
            if not is_container_path(env_from_path, "envFrom"):
                return False
            reference = closed_reference(value, {"name", "optional"}, field)
            validate_secret_name(reference.get("name"), f"{identity} {field}.name")
            return True
        if (
            len(trail) >= 3
            and trail[-1] == "secret"
            and trail[-3] == "volumes"
            and is_index(trail[-2])
            and in_pod_spec(trail[:-3], ())
        ):
            reference = closed_reference(value, {"secretName", "items", "defaultMode", "optional"}, field)
            validate_secret_name(reference.get("secretName"), f"{identity} {field}.secretName")
            items = reference.get("items", [])
            if not isinstance(items, list):
                fail(f"rendered {identity} {field}.items must be a list")
            for index, item in enumerate(items):
                item_field = f"{field}.items.{index}"
                item_map = closed_reference(item, {"key", "path", "mode"}, item_field)
                validate_secret_key(item_map.get("key"), f"{identity} {item_field}.key")
                if not isinstance(item_map.get("path"), str) or not item_map["path"]:
                    fail(f"rendered {identity} {item_field}.path must be nonempty")
                if "mode" in item_map and not isinstance(item_map["mode"], int):
                    fail(f"rendered {identity} {item_field}.mode must be integer")
            return True
        if (
            len(trail) >= 6
            and trail[-1] == "secret"
            and trail[-3] == "sources"
            and is_index(trail[-2])
            and "projected" in trail[:-3]
            and "volumes" in trail[:-3]
            and any(
                trail == prefix + ("volumes", trail[len(prefix) + 1], "projected", "sources", trail[-2], "secret")
                for prefix in active_pod_spec_prefixes
                if len(trail) == len(prefix) + 6
            )
        ):
            reference = closed_reference(value, {"name", "items", "optional"}, field)
            validate_secret_name(reference.get("name"), f"{identity} {field}.name")
            items = reference.get("items", [])
            if not isinstance(items, list):
                fail(f"rendered {identity} {field}.items must be a list")
            for index, item in enumerate(items):
                item_field = f"{field}.items.{index}"
                item_map = closed_reference(item, {"key", "path", "mode"}, item_field)
                validate_secret_key(item_map.get("key"), f"{identity} {item_field}.key")
                if not isinstance(item_map.get("path"), str) or not item_map["path"]:
                    fail(f"rendered {identity} {item_field}.path must be nonempty")
            return True
        return False

    def walk(
        value: Any,
        identity: str,
        trail: tuple[str, ...] = (),
        sensitive_context: bool = False,
    ) -> None:
        if isinstance(value, dict):
            if consume_kubernetes_reference(value, trail, identity):
                return
            # Pod env entries are the common place a chart can accidentally
            # materialize a password. A real Secret reference is allowed; a
            # literal value is never allowed for a credential-shaped name.
            env_name = value.get("name")
            if (
                isinstance(env_name, str)
                and classify_key((env_name,), "rendered") == "secret_literal"
                and is_container_path(trail, "env")
                and ("value" in value or "valueFrom" in value)
            ):
                if "value" in value and value.get("value") not in (None, ""):
                    fail(
                        f"rendered {identity} contains plaintext credential env {env_name}"
                    )
                value_from = value.get("valueFrom")
                if not isinstance(value_from, dict) or not isinstance(
                    value_from.get("secretKeyRef"), dict
                ):
                    fail(
                        f"rendered {identity} credential env {env_name} must use secretKeyRef"
                    )
            for key, child in value.items():
                key_text = str(key)
                child_trail = trail + (key_text,)
                structural_token_field = is_kubernetes_structural_field(
                    child_trail, child
                )
                classification = classify_key(
                    child_trail,
                    "kubernetes-structural" if structural_token_field else "rendered",
                )
                child_sensitive = sensitive_context or classification == "secret_literal" or bool(
                    re.fullmatch(r"(?i)auth(?:entication|orization)?", key_text)
                )
                if (
                    (classification == "secret_literal" or sensitive_context)
                    and not isinstance(child, (dict, list))
                    and child not in (None, "", False)
                    and not structural_token_field
                ):
                    fail(
                        f"rendered {identity} contains plaintext credential-shaped field "
                        f"{'.'.join(child_trail)} outside a Secret payload"
                    )
                walk(
                    child,
                    identity,
                    child_trail,
                    child_sensitive and not structural_token_field,
                )
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, identity, trail + (str(index),), sensitive_context)
        elif isinstance(value, str):
            parsed = urlparse(value)
            if (
                sensitive_context
                or
                SECRET_VALUE_RE.search(value)
                or (sensitive_context and default_value.fullmatch(value.strip()))
                or (parsed.scheme and (parsed.username is not None or parsed.password is not None))
            ):
                fail(
                    f"rendered {identity} contains credential-shaped scalar content outside "
                    "a Secret payload"
                )

    for document in documents:
        metadata = document.get("metadata", {}) if isinstance(document.get("metadata"), dict) else {}
        identity = f"{document.get('kind', '')}/{metadata.get('name', '')}"
        if document.get("kind") == "Secret":
            # Payloads are inspected only in memory for obvious default/sample
            # values. Their bytes, hashes, and parsed endpoints are never
            # emitted to evidence.
            for payload_field in ("data", "stringData"):
                payload = document.get(payload_field, {})
                if not isinstance(payload, dict):
                    fail(f"rendered {identity} {payload_field} must be a mapping")
                for key, raw_value in payload.items():
                    if not isinstance(raw_value, str):
                        fail(f"rendered {identity} Secret payload values must be strings")
                    decoded = raw_value
                    if payload_field == "data":
                        try:
                            decoded = base64.b64decode(raw_value, validate=True).decode("utf-8")
                        except (ValueError, UnicodeError):
                            # Opaque binary/certificate material is not made
                            # durable and needs CSE classification in the
                            # unresolved secret-payload ledger.
                            continue
                    if default_value.fullmatch(decoded.strip()):
                        fail(
                            f"rendered {identity} Secret payload {key} contains a known "
                            "default/sample value"
                        )
            # Scan only metadata values, not structural apiVersion/kind/type;
            # a literal "kind: Secret" is schema, not credential material.
            walk(metadata, identity, ("metadata",))
            continue
        kind = document.get("kind")
        if kind == "Pod":
            active_pod_spec_prefixes = {("spec",)}
        elif kind == "CronJob":
            active_pod_spec_prefixes = {("spec", "jobTemplate", "spec", "template", "spec")}
        elif kind in {
            "Deployment",
            "StatefulSet",
            "DaemonSet",
            "ReplicaSet",
            "ReplicationController",
            "Job",
        }:
            active_pod_spec_prefixes = {("spec", "template", "spec")}
        else:
            active_pod_spec_prefixes = set()
        walk(document, identity)


def validate_secret_leaf_influence(
    actual: bytes,
    shadow: bytes,
    field: str,
) -> tuple[str, list[str]]:
    actual_documents = rendered_documents(actual, f"{field} actual render")
    shadow_documents = rendered_documents(shadow, f"{field} shadow render")
    actual_shapes = [secret_payload_shape(document) for document in actual_documents]
    shadow_shapes = [secret_payload_shape(document) for document in shadow_documents]
    if actual_shapes != shadow_shapes:
        fail(
            f"{field} runtime values influence objects, metadata, or non-Secret fields; "
            "reviewed runtime values may influence Secret payload values only"
        )
    def payloads(documents: list[dict[str, Any]]) -> dict[tuple[str, str, str, str], str]:
        result: dict[tuple[str, str, str, str], str] = {}
        for document in documents:
            if document.get("kind") != "Secret":
                continue
            metadata = document.get("metadata", {})
            identity = (str(metadata.get("namespace", "")), str(metadata.get("name", "")))
            for payload_field in ("data", "stringData"):
                payload = document.get(payload_field, {})
                if not isinstance(payload, dict):
                    fail(f"{field} rendered Secret payload must be a mapping")
                for key, value in payload.items():
                    if not isinstance(value, str):
                        fail(f"{field} rendered Secret payload values must be strings")
                    result[(identity[0], identity[1], payload_field, str(key))] = value
        return result

    actual_payloads = payloads(actual_documents)
    shadow_payloads = payloads(shadow_documents)
    changed = sorted(
        "/".join(key)
        for key in actual_payloads
        if actual_payloads[key] != shadow_payloads[key]
    )
    if set(actual_payloads) != set(shadow_payloads) or not changed:
        fail(f"{field} reviewed runtime-secret path is unused or changes Secret payload structure")
    return sha256_bytes(json_bytes(actual_shapes)), changed


def validate_secret_overlay_is_payload_only(actual: bytes, shadow: bytes, field: str) -> str:
    """Compatibility wrapper for one perturbation render."""
    return validate_secret_leaf_influence(actual, shadow, field)[0]


def shared_crd_controls(values: dict[str, Any]) -> bool:
    def get(*keys: str) -> Any:
        current: Any = values
        for key in keys:
            if not isinstance(current, dict) or key not in current:
                return None
            current = current[key]
        return current

    return all(
        value is expected
        for value, expected in (
            (get("global", "disable_crds"), True),
            (get("clickhouse-operator", "global", "disable_crds"), True),
            (get("rabbitmq-operator", "global", "disable_crds"), True),
            (get("sequencing", "crd_management", "enabled"), False),
        )
    )


def safe_tar_members(data: bytes, label: str) -> list[tuple[str, bytes]]:
    if len(data) > 512 * 1024 * 1024:
        fail(f"{label} exceeds the 512 MiB archive limit")
    result: list[tuple[str, bytes]] = []
    total = 0
    seen_names: set[str] = set()
    try:
        archive = tarfile.open(fileobj=io.BytesIO(data), mode="r:*")
    except tarfile.TarError:
        fail(f"{label} is not a valid tar archive")
    with archive:
        members = archive.getmembers()
        if len(members) > 20000:
            fail(f"{label} has too many archive members")
        for member in members:
            pure = PurePosixPath(member.name)
            if pure.is_absolute() or ".." in pure.parts or not pure.parts or "\\" in member.name or member.name.rstrip("/") != pure.as_posix():
                fail(f"{label} contains an unsafe path")
            canonical_name = pure.as_posix()
            if canonical_name in seen_names:
                fail(f"{label} contains duplicate archive paths")
            seen_names.add(canonical_name)
            if member.issym() or member.islnk() or member.isdev() or member.isfifo():
                fail(f"{label} contains links or special files")
            if member.isdir():
                continue
            if not member.isfile() or member.size > 64 * 1024 * 1024:
                fail(f"{label} contains an unsupported member")
            total += member.size
            if total > 1024 * 1024 * 1024:
                fail(f"{label} expands beyond the 1 GiB limit")
            handle = archive.extractfile(member)
            if handle is None:
                fail(f"cannot inspect {label} member")
            result.append((member.name, handle.read()))
    return result


def recursive_chart_members(chart_bytes: bytes, label: str) -> list[tuple[str, bytes]]:
    files = list(safe_tar_members(chart_bytes, label))
    queue: list[tuple[str, bytes, int]] = [
        (name, body, 1)
        for name, body in files
        if name.endswith((".tgz", ".tar.gz")) and "/charts/" in name
    ]
    inspected_bytes = sum(len(body) for _, body in files)
    while queue:
        archive_name, archive_body, depth = queue.pop(0)
        if depth > 8:
            fail("nested chart archive depth exceeds the safe inspection limit")
        for nested_name, nested_body in safe_tar_members(archive_body, archive_name):
            source = f"{archive_name}!/{nested_name}"
            files.append((source, nested_body))
            inspected_bytes += len(nested_body)
            if len(files) > 50000 or inspected_bytes > 1024 * 1024 * 1024:
                fail("recursive chart inspection exceeds safe file/byte limits")
            if nested_name.endswith((".tgz", ".tar.gz")) and "/charts/" in nested_name:
                queue.append((source, nested_body, depth + 1))
    return files


def packaged_crds(chart_bytes: bytes) -> list[tuple[str, dict[str, Any], bytes]]:
    result: list[tuple[str, dict[str, Any], bytes]] = []
    for source, body in recursive_chart_members(chart_bytes, "galileo-stack"):
        if "/crds/" not in source or not source.endswith((".yaml", ".yml")):
            continue
        try:
            documents = strict_yaml_load_all(body)
        except yaml.YAMLError:
            fail("packaged CRD YAML is invalid")
        for document in documents:
            if isinstance(document, dict) and document.get("kind") == "CustomResourceDefinition":
                name = document.get("metadata", {}).get("name")
                if not isinstance(name, str) or not name:
                    fail("packaged CRD is missing metadata.name")
                result.append((name, document, yaml_bytes(document)))
    names = [item[0] for item in result]
    if len(names) != len(set(names)):
        fail("packaged CRD inventory contains duplicate names")
    return result


def active_crds_from_render(
    include_crds_render: bytes,
    static_crd_superset: list[tuple[str, dict[str, Any], bytes]],
) -> list[tuple[str, dict[str, Any], bytes]]:
    """Return the values-aware CRD set emitted by exact ``--include-crds``.

    Recursive ``crds/`` inspection is only one static source: Galileo operator
    and sequencing charts may render CRDs from ``templates/``. The active set
    is therefore the exact values-aware include stream. A same-name packaged
    CRD must match it; otherwise it is classified as a rendered-template CRD
    for the non-executable CSE handoff.
    """
    static_by_name = {name: document for name, document, _ in static_crd_superset}
    active: list[tuple[str, dict[str, Any], bytes]] = []
    seen: set[str] = set()
    for document in rendered_documents(include_crds_render, "values-aware CRD render"):
        if document.get("kind") != "CustomResourceDefinition":
            continue
        name = document.get("metadata", {}).get("name")
        if not isinstance(name, str) or not name or name in seen:
            fail("values-aware CRD render contains a missing or duplicate CRD name")
        static = static_by_name.get(name)
        if static is not None and normalized_crd_spec(static) != normalized_crd_spec(document):
            fail(f"values-aware CRD {name} differs from the same-name pinned crds/ artifact")
        seen.add(name)
        active.append((name, document, yaml_bytes(document)))
    if not active:
        fail("the exact values-aware Galileo Stack render contains no active packaged CRDs")
    return sorted(active, key=lambda item: item[0])


def crd_established(document: dict[str, Any]) -> bool:
    return any(
        condition.get("type") == "Established" and condition.get("status") == "True"
        for condition in document.get("status", {}).get("conditions", [])
        if isinstance(condition, dict)
    )


def normalized_crd_spec(document: dict[str, Any]) -> Any:
    spec = copy.deepcopy(document.get("spec"))
    if not isinstance(spec, dict):
        return spec
    # Kubernetes API-server defaults that do not change the effective CRD
    # contract. All schema/conversion/version/scope/name surfaces remain exact.
    if spec.get("preserveUnknownFields") is False:
        spec.pop("preserveUnknownFields", None)
    conversion = spec.get("conversion")
    if isinstance(conversion, dict) and conversion == {"strategy": "None"}:
        spec.pop("conversion", None)
    return spec


def assert_schema_not_narrowed(old: Any, new: Any, path: str = "openAPIV3Schema") -> None:
    if not isinstance(old, dict):
        return
    if not isinstance(new, dict):
        fail(f"CRD schema removed reviewed object at {path}")
    if old.get("type") and new.get("type") != old.get("type"):
        fail(f"CRD schema changed type at {path}")
    old_required = set(old.get("required", [])) if isinstance(old.get("required"), list) else set()
    new_required = set(new.get("required", [])) if isinstance(new.get("required"), list) else set()
    if not new_required <= old_required:
        fail(f"CRD schema added required fields at {path}")
    if "enum" not in old and "enum" in new:
        fail(f"CRD schema added an enum constraint at {path}")
    if isinstance(old.get("enum"), list) and isinstance(new.get("enum"), list) and not set(old["enum"]) <= set(new["enum"]):
        fail(f"CRD schema narrowed enum values at {path}")
    if "minimum" not in old and "minimum" in new:
        fail(f"CRD schema added a minimum at {path}")
    if "minimum" in old and "minimum" in new and new["minimum"] > old["minimum"]:
        fail(f"CRD schema raised minimum at {path}")
    if "maximum" not in old and "maximum" in new:
        fail(f"CRD schema added a maximum at {path}")
    if "maximum" in old and "maximum" in new and new["maximum"] < old["maximum"]:
        fail(f"CRD schema lowered maximum at {path}")
    if not old.get("pattern") and new.get("pattern"):
        fail(f"CRD schema added a narrowing pattern at {path}")
    if old.get("pattern") and new.get("pattern") != old.get("pattern"):
        fail(f"CRD schema changed pattern at {path}")
    # Reject newly introduced or changed validation surfaces unless the small
    # set of mathematically safe widenings above proves compatibility.  This
    # intentionally trades automation breadth for stored-object safety.
    strict_constraints = {
        "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "minLength",
        "maxLength", "minItems", "maxItems", "uniqueItems", "minProperties",
        "maxProperties", "format", "not", "oneOf", "anyOf", "allOf",
        "x-kubernetes-validations", "x-kubernetes-list-type",
        "x-kubernetes-list-map-keys", "x-kubernetes-map-type",
    }
    for key in strict_constraints:
        if key not in old and key in new:
            fail(f"CRD schema added narrowing validation {key} at {path}")
        if key in old and new.get(key) != old.get(key):
            fail(f"CRD schema changed validation {key} at {path}")
    if old.get("nullable") is True and new.get("nullable") is not True:
        fail(f"CRD schema removed nullable compatibility at {path}")
    if old.get("x-kubernetes-preserve-unknown-fields") is True and new.get("x-kubernetes-preserve-unknown-fields") is not True:
        fail(f"CRD schema removed preserve-unknown-fields compatibility at {path}")
    old_additional = old.get("additionalProperties", True)
    new_additional = new.get("additionalProperties", True)
    if old_additional is True and new_additional is not True:
        fail(f"CRD schema narrowed additionalProperties at {path}")
    if isinstance(old_additional, dict):
        if not isinstance(new_additional, dict):
            if new_additional is not True:
                fail(f"CRD schema removed additionalProperties schema at {path}")
        else:
            assert_schema_not_narrowed(old_additional, new_additional, f"{path}.additionalProperties")
    old_properties = old.get("properties", {}) if isinstance(old.get("properties"), dict) else {}
    new_properties = new.get("properties", {}) if isinstance(new.get("properties"), dict) else {}
    if not set(old_properties) <= set(new_properties):
        fail(f"CRD schema removed properties at {path}")
    for name, old_child in old_properties.items():
        assert_schema_not_narrowed(old_child, new_properties[name], f"{path}.properties.{name}")
    if "items" not in old and "items" in new:
        fail(f"CRD schema added item constraints at {path}")
    if "items" in old:
        assert_schema_not_narrowed(old["items"], new.get("items"), f"{path}.items")


def crd_upgrade_diff(name: str, live: dict[str, Any], desired: dict[str, Any]) -> dict[str, Any]:
    live_versions = {
        str(item.get("name")): item
        for item in live.get("spec", {}).get("versions", [])
        if isinstance(item, dict) and item.get("name")
    }
    desired_versions = {
        str(item.get("name")): item
        for item in desired.get("spec", {}).get("versions", [])
        if isinstance(item, dict) and item.get("name")
    }
    served_or_storage = {
        version for version, row in live_versions.items()
        if row.get("served") is True or row.get("storage") is True
    }
    stored_versions = {
        str(value) for value in live.get("status", {}).get("storedVersions", [])
    }
    if not served_or_storage <= set(desired_versions) or not stored_versions <= set(desired_versions):
        fail(f"CRD upgrade removes served/storage/stored versions for {name}")
    for version in served_or_storage:
        if live_versions[version].get("served") is True and desired_versions[version].get("served") is not True:
            fail(f"CRD upgrade stops serving live version {name}/{version}")
        if live_versions[version].get("storage") is True and desired_versions[version].get("storage") is not True:
            fail(f"CRD upgrade changes the live storage version {name}/{version}")
        old_schema = live_versions[version].get("schema", {}).get("openAPIV3Schema")
        new_schema = desired_versions[version].get("schema", {}).get("openAPIV3Schema")
        assert_schema_not_narrowed(old_schema, new_schema, f"{name}.{version}")
    live_spec = normalized_crd_spec(live)
    desired_spec = normalized_crd_spec(desired)
    return {
        "name": name,
        "changed": live_spec != desired_spec,
        "live_spec_sha256": sha256_bytes(json_bytes(live_spec)),
        "target_spec_sha256": sha256_bytes(json_bytes(desired_spec)),
        "live_versions": sorted(live_versions),
        "target_versions": sorted(desired_versions),
        "stored_versions": sorted(stored_versions),
    }


def rendered_documents(data: bytes, field: str) -> list[dict[str, Any]]:
    try:
        documents = strict_yaml_load_all(data)
    except yaml.YAMLError:
        fail(f"{field} did not render valid YAML")
    result: list[dict[str, Any]] = []
    pending = [item for item in documents if isinstance(item, dict)]
    inspected = 0
    while pending:
        document = pending.pop(0)
        inspected += 1
        if inspected > 50000:
            fail(f"{field} contains too many rendered objects")
        if document.get("kind") != "List":
            result.append(document)
            continue
        items = document.get("items")
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            fail(f"{field} contains an invalid Kubernetes List")
        pending[0:0] = items
    return result


def validate_rendered_cluster_permissions(
    documents: list[dict[str, Any]],
    kube: list[str],
    env: dict[str, str],
    api_resources: dict[str, dict[str, Any]],
    namespace: str,
) -> list[dict[str, Any]]:
    """Derive, but never exercise, a proposed installer permission plan."""
    plan: list[dict[str, Any]] = []
    gvks = sorted({
        f"{document.get('apiVersion', '')}|{document.get('kind', '')}"
        for document in documents
    })
    for gvk in gvks:
        row = api_resources.get(gvk)
        if not isinstance(row, dict) or not isinstance(row.get("resource"), str):
            fail(f"rendered authorization lacks API discovery for {gvk}")
        plan.append({
            "gvk": gvk,
            "resource": row["resource"],
            "namespaced": row.get("namespaced") is True,
            "namespace": namespace if row.get("namespaced") is True else "",
            "proposed_verbs": ["get", "create", "update", "patch", "delete"],
            "authorized_by_this_skill": False,
        })
    return plan


def validate_rendered_scope(
    documents: list[dict[str, Any]],
    namespace: str,
    api_scopes: dict[str, bool] | None = None,
) -> None:
    """Keep namespaced resources inside the reviewed target namespace.

    Exact cluster-scoped kinds must already be discovered/classified from the
    pinned chart and pass authorization review. Namespace objects are never
    accepted from Helm; explicit namespace creation has its own gated action.
    """
    for document in documents:
        kind = str(document.get("kind", ""))
        metadata = document.get("metadata", {}) if isinstance(document.get("metadata"), dict) else {}
        rendered_namespace = metadata.get("namespace")
        if kind == "Namespace":
            fail("Helm render contains a Namespace; use the separately gated namespace-create action")
        api_version = str(document.get("apiVersion", ""))
        scope_key = f"{api_version}|{kind}"
        namespaced = api_scopes.get(scope_key) if api_scopes is not None else kind not in CLUSTER_KINDS
        if api_scopes is not None and scope_key not in api_scopes:
            fail(f"rendered GVK scope is not proven by API discovery or an active CRD: {scope_key}")
        if not namespaced:
            if rendered_namespace not in {None, ""}:
                fail(f"cluster-scoped rendered resource {kind} unexpectedly declares a namespace")
            continue
        if rendered_namespace not in {None, "", namespace}:
            fail(f"rendered {kind}/{metadata.get('name', '')} escapes the reviewed target namespace")


def discovered_api_resources(kube: list[str], env: dict[str, str]) -> dict[str, dict[str, Any]]:
    output = run_checked(kube + ["api-resources", "--no-headers", "-o", "wide"], env, limit=8 * 1024 * 1024)
    resources: dict[str, dict[str, Any]] = {}
    for line in output.decode(errors="replace").splitlines():
        columns = line.split()
        indexes = [index for index, value in enumerate(columns) if value in {"true", "false"}]
        if len(indexes) != 1 or indexes[0] < 1 or indexes[0] + 1 >= len(columns):
            fail("kubectl api-resources returned an unparseable scope row")
        scope_index = indexes[0]
        api_version, namespaced_text, kind = (
            columns[scope_index - 1], columns[scope_index], columns[scope_index + 1]
        )
        name = columns[0]
        key = f"{api_version}|{kind}"
        namespaced = namespaced_text == "true"
        row = {"namespaced": namespaced, "resource": name}
        if key in resources and resources[key] != row:
            fail(f"API discovery returned conflicting scope for {key}")
        resources[key] = row
    if not resources:
        fail("Kubernetes API discovery returned no resource scopes")
    return resources


def discovered_api_scopes(kube: list[str], env: dict[str, str]) -> dict[str, bool]:
    return {key: bool(value["namespaced"]) for key, value in discovered_api_resources(kube, env).items()}


def add_active_crd_scopes(
    scopes: dict[str, bool],
    active_crds: list[tuple[str, dict[str, Any], bytes]],
) -> dict[str, bool]:
    result = dict(scopes)
    for _, document, _ in active_crds:
        crd_spec = document.get("spec", {})
        group = crd_spec.get("group")
        kind = crd_spec.get("names", {}).get("kind")
        namespaced = crd_spec.get("scope") == "Namespaced"
        if not isinstance(group, str) or not isinstance(kind, str) or crd_spec.get("scope") not in {"Namespaced", "Cluster"}:
            fail("active CRD lacks an exact group/kind/scope contract")
        for version in crd_spec.get("versions", []):
            if not isinstance(version, dict) or not isinstance(version.get("name"), str):
                fail("active CRD contains an invalid version")
            result[f"{group}/{version['name']}|{kind}"] = namespaced
    return result


def add_active_crd_resources(
    resources: dict[str, dict[str, Any]],
    active_crds: list[tuple[str, dict[str, Any], bytes]],
) -> dict[str, dict[str, Any]]:
    result = copy.deepcopy(resources)
    for _, document, _ in active_crds:
        crd_spec = document.get("spec", {})
        group = crd_spec.get("group")
        kind = crd_spec.get("names", {}).get("kind")
        plural = crd_spec.get("names", {}).get("plural")
        scope = crd_spec.get("scope")
        if not all(isinstance(value, str) and value for value in (group, kind, plural)) or scope not in {"Namespaced", "Cluster"}:
            fail("active CRD lacks an exact discovery resource contract")
        for version in crd_spec.get("versions", []):
            if not isinstance(version, dict) or not isinstance(version.get("name"), str):
                fail("active CRD contains an invalid discovery version")
            result[f"{group}/{version['name']}|{kind}"] = {
                "namespaced": scope == "Namespaced",
                "resource": f"{plural}.{group}",
            }
    return result


def pod_specs(documents: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    result: list[tuple[str, dict[str, Any]]] = []
    seen: set[int] = set()
    for document in documents:
        kind = str(document.get("kind", ""))
        name = str(document.get("metadata", {}).get("name", ""))
        spec = document.get("spec", {})
        if kind in {"Deployment", "StatefulSet", "DaemonSet", "ReplicaSet"}:
            pod = spec.get("template", {}).get("spec")
        elif kind in {"Job"}:
            pod = spec.get("template", {}).get("spec")
        elif kind == "CronJob":
            pod = spec.get("jobTemplate", {}).get("spec", {}).get("template", {}).get("spec")
        elif kind == "Pod":
            pod = spec
        else:
            pod = None
        if isinstance(pod, dict):
            result.append((f"{kind}/{name}", pod))
            seen.add(id(pod))
        stack: list[tuple[str, Any]] = [("spec", spec)]
        inspected = 0
        while stack:
            path, value = stack.pop()
            inspected += 1
            if inspected > 100000:
                fail(f"rendered object {kind}/{name} exceeds the pod-spec inspection limit")
            if isinstance(value, dict):
                container_lists = [value.get(key) for key in ("containers", "initContainers", "ephemeralContainers")]
                if id(value) not in seen and any(
                    isinstance(containers, list)
                    and any(isinstance(container, dict) and isinstance(container.get("image"), str) for container in containers)
                    for containers in container_lists
                ):
                    result.append((f"{kind}/{name}@{path}", value))
                    seen.add(id(value))
                stack.extend((f"{path}.{key}", child) for key, child in value.items())
            elif isinstance(value, list):
                stack.extend((f"{path}[{index}]", child) for index, child in enumerate(value))
    return result


def validate_gpu_rendering(documents: list[dict[str, Any]], wizard: dict[str, Any], eligible_nodes: list[dict[str, Any]]) -> dict[str, Any]:
    resource_name = str(wizard.get("gpu_resource") or "nvidia.com/gpu")
    gpu_pods: list[tuple[str, dict[str, Any]]] = []
    max_gpu_limit = 0
    for identity, pod in pod_specs(documents):
        has_gpu = False
        for container in list(pod.get("initContainers", [])) + list(pod.get("containers", [])):
            resources = container.get("resources", {}) if isinstance(container, dict) else {}
            requests = resources.get("requests", {}) if isinstance(resources, dict) else {}
            limits = resources.get("limits", {}) if isinstance(resources, dict) else {}
            requested, limited = requests.get(resource_name), limits.get(resource_name)
            if requested is not None or limited is not None:
                if limited is None or not str(limited).isdigit() or int(str(limited)) < 1:
                    fail(f"{identity} must have a positive GPU limit")
                if requested is not None and (
                    not str(requested).isdigit()
                    or int(str(requested)) < 1
                    or str(requested) != str(limited)
                ):
                    fail(f"{identity} GPU request, when set, must equal its positive limit")
                max_gpu_limit = max(max_gpu_limit, int(str(limited)))
                has_gpu = True
        if has_gpu:
            gpu_pods.append((identity, pod))
    if wizard.get("gpu_enabled"):
        if not gpu_pods:
            fail("Wizard GPU mode rendered no positive GPU limit")
        for identity, pod in gpu_pods:
            selector = pod.get("nodeSelector", {})
            affinity_text = json.dumps(pod.get("affinity", {}), sort_keys=True)
            if not (isinstance(selector, dict) and selector.get("galileo-node-type") == "galileo-ml") and not ("galileo-node-type" in affinity_text and "galileo-ml" in affinity_text):
                fail(f"{identity} lacks the Galileo ML node selector/affinity")
            tolerations = pod.get("tolerations", [])
            for node in eligible_nodes:
                for taint in node.get("spec", {}).get("taints", []):
                    if taint.get("effect") not in {"NoSchedule", "NoExecute"}:
                        continue
                    matched = any(
                        isinstance(toleration, dict)
                        and toleration.get("key") == taint.get("key")
                        and toleration.get("effect", taint.get("effect")) == taint.get("effect")
                        and (
                            toleration.get("operator") == "Exists"
                            or str(toleration.get("value", "")) == str(taint.get("value", ""))
                        )
                        for toleration in tolerations
                    )
                    if not matched:
                        fail(f"{identity} does not tolerate taint {taint.get('key')} on an eligible GPU node")
    elif gpu_pods:
        fail("CPU-only profile rendered GPU requests")
    expected = set(wizard.get("expected_deployments", []))
    workload_names = {
        str(document.get("metadata", {}).get("name", ""))
        for document in documents
        if document.get("kind") in {"Deployment", "StatefulSet"}
    }
    service_names = {
        str(document.get("metadata", {}).get("name", ""))
        for document in documents
        if document.get("kind") == "Service"
    }
    observed = {
        name for name in expected
        if name in workload_names and (name in service_names or any(service.startswith(name + "-") for service in service_names))
    }
    if expected != observed:
        fail("Wizard enabled deployment names must each render an exact workload and Service")
    if not wizard.get("enabled") and any("wizard" in name.lower() for name in workload_names | service_names):
        fail("Wizard-disabled profile rendered a Wizard workload or Service")
    if wizard.get("triton_required") and not any("triton" in name.lower() for name in workload_names):
        fail("Wizard Triton intent rendered no named Triton workload")
    hpa_targets = {
        str(document.get("spec", {}).get("scaleTargetRef", {}).get("name", ""))
        for document in documents if document.get("kind") == "HorizontalPodAutoscaler"
    }
    if wizard.get("hpa_required") and not expected <= hpa_targets:
        fail("Wizard HPA intent does not cover every expected deployment")
    if wizard.get("network_policy_required"):
        policies = [document for document in documents if document.get("kind") == "NetworkPolicy"]
        if len(policies) < len(expected):
            fail("Wizard network-policy intent lacks per-deployment isolation resources")
    if max_gpu_limit > 1:
        if (
            not str(wizard.get("multi_gpu_cse_reference", "")).strip()
            or not str(wizard.get("multi_gpu_model_support_evidence", "")).strip()
            or not any(int(node.get("status", {}).get("allocatable", {}).get(resource_name, "0")) >= max_gpu_limit for node in eligible_nodes)
        ):
            fail("multi-GPU Wizard requires CSE/model support evidence and one eligible node with sufficient allocatable GPUs")
    return {
        "enabled": bool(wizard.get("enabled")),
        "expected_deployments": sorted(expected),
        "gpu_workloads": sorted(identity for identity, _ in gpu_pods),
        "max_gpu_limit": max_gpu_limit,
        "triton_required": bool(wizard.get("triton_required")),
        "hpa_required": bool(wizard.get("hpa_required")),
        "network_policy_required": bool(wizard.get("network_policy_required")),
    }


def validate_galileoctl_render(
    documents: list[dict[str, Any]],
    policy: dict[str, Any],
    claims: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate a nonmutating galileoctl console handoff render."""
    public_surfaces: list[str] = []
    service_rows: list[dict[str, Any]] = []
    for document in documents:
        kind = str(document.get("kind", ""))
        name = str(document.get("metadata", {}).get("name", ""))
        spec = document.get("spec", {})
        if kind in {"Ingress", "Gateway", "HTTPRoute"}:
            public_surfaces.append(f"{kind}/{name}")
        if kind == "Service":
            service_type = str(spec.get("type", "ClusterIP"))
            external_ips = spec.get("externalIPs", [])
            if service_type in {"NodePort", "LoadBalancer", "ExternalName"} or external_ips:
                public_surfaces.append(f"Service/{name}:{service_type}")
            service_rows.append({"name": name, "type": service_type})
    proxy_workloads: set[str] = set()
    host_surfaces: list[str] = []
    for identity, pod in pod_specs(documents):
        if any(pod.get(key) is True for key in ("hostNetwork", "hostPID", "hostIPC")):
            host_surfaces.append(identity)
        for container in list(pod.get("initContainers", [])) + list(pod.get("containers", [])):
            if not isinstance(container, dict):
                continue
            if any(isinstance(port, dict) and port.get("hostPort") not in {None, 0} for port in container.get("ports", [])):
                host_surfaces.append(identity)
            identity_text = f"{container.get('name', '')} {container.get('image', '')}".lower()
            if "oauth2-proxy" in identity_text:
                proxy_workloads.add(identity)
    if policy.get("port_forward_only") and (public_surfaces or host_surfaces):
        fail("port-forward-only galileoctl render exposes a route, public Service, host network, or hostPort")
    if policy.get("auth_enabled") and not proxy_workloads:
        fail("authenticated galileoctl render contains no actual oauth2-proxy workload container")
    if policy.get("audit_persistence") and not claims:
        fail("galileoctl audit persistence renders neither a PVC nor StatefulSet claim template")
    return {
        "services": sorted(service_rows, key=lambda row: row["name"]),
        "oauth2_proxy_workloads": sorted(proxy_workloads),
        "persistent_claims": sorted(f"{row['source']}/{row['name']}" for row in claims),
        "public_surfaces": sorted(public_surfaces),
        "host_surfaces": sorted(set(host_surfaces)),
    }


def validate_monitoring_rendering(documents: list[dict[str, Any]], monitoring: dict[str, Any]) -> dict[str, Any]:
    rows = monitoring.get("expected_components", [])
    object_rows = [
        (str(document.get("kind", "")), str(document.get("metadata", {}).get("name", "")))
        for document in documents
    ]
    workload_names = {name for kind, name in object_rows if kind in {"Deployment", "StatefulSet", "DaemonSet"}}
    service_names = {name for kind, name in object_rows if kind == "Service"}
    kinds = {kind for kind, _ in object_rows}
    declared = {row["name"] for row in rows}
    def component_for_name(value: str) -> str:
        normalized = value.lower().replace("_", "-")
        for component, patterns in (
            ("prometheus-adapter", ("prometheus-adapter",)),
            ("kube-state-metrics", ("kube-state-metrics",)),
            ("fluent-bit", ("fluent-bit",)),
            ("victorialogs", ("victorialogs", "victoria-logs")),
            ("alertmanager", ("alertmanager",)),
            ("grafana", ("grafana",)),
            ("prometheus", ("prometheus",)),
        ):
            if any(pattern in normalized for pattern in patterns):
                return component
        return ""

    recognized = {component_for_name(name) for _, name in object_rows} - {""}
    if not monitoring.get("enabled"):
        if recognized:
            fail("monitoring-disabled profile rendered recognized monitoring components")
        return {"enabled": False, "components": []}
    if recognized != declared:
        fail("rendered monitoring component set differs from explicit expected_components")
    result: list[dict[str, Any]] = []
    for row in rows:
        expected_workloads = set(row["workloads"])
        expected_services = set(row["services"])
        if not expected_workloads <= workload_names or not expected_services <= service_names:
            fail(f"monitoring component {row['name']} lacks exact reviewed workloads/services")
        expected_resources = {
            (resource["kind"], resource["name"])
            for resource in row["resources"]
        }
        if not expected_resources <= set(object_rows) or not set(row["required_kinds"]) <= kinds:
            fail(f"monitoring component {row['name']} lacks exact reviewed resource identities")
        observed_named_workloads = {
            name for name in workload_names if component_for_name(name) == row["name"]
        }
        observed_named_services = {
            name for name in service_names if component_for_name(name) == row["name"]
        }
        if observed_named_workloads != expected_workloads or observed_named_services != expected_services:
            fail(f"monitoring component {row['name']} workload/Service set differs from exact reviewed identities")
        expected_workload_documents = [
            document for document in documents
            if document.get("kind") in {"Deployment", "StatefulSet", "DaemonSet"}
            and document.get("metadata", {}).get("name") in expected_workloads
        ]
        component_pvcs = {
            name for kind, name in object_rows
            if kind == "PersistentVolumeClaim"
            and any(token in name.lower() for token in (row["name"], *expected_workloads))
        }
        persistent = bool(component_pvcs)
        for workload in expected_workload_documents:
            workload_spec = workload.get("spec", {})
            if workload.get("kind") == "StatefulSet" and workload_spec.get("volumeClaimTemplates"):
                persistent = True
            pod_spec = workload_spec.get("template", {}).get("spec", {})
            referenced_claims = {
                volume.get("persistentVolumeClaim", {}).get("claimName")
                for volume in pod_spec.get("volumes", [])
                if isinstance(volume, dict)
            }
            if {value for value in referenced_claims if isinstance(value, str)} & component_pvcs:
                persistent = True
        if row["persistence_required"] and not persistent:
            fail(f"monitoring component {row['name']} requires rendered persistence")
        result.append({
            "name": row["name"],
            "workloads": sorted(expected_workloads),
            "services": sorted(expected_services),
            "required_kinds": sorted(row["required_kinds"]),
            "resources": [
                {"kind": kind, "name": name}
                for kind, name in sorted(expected_resources)
            ],
            "persistent": persistent,
        })
    return {"enabled": True, "components": sorted(result, key=lambda item: item["name"])}


def validate_data_service_rendering(documents: list[dict[str, Any]], data: dict[str, Any]) -> dict[str, Any]:
    identities = [
        (str(document.get("kind", "")), str(document.get("metadata", {}).get("name", "")).lower())
        for document in documents
    ]
    tokens = {
        "postgres": ("postgres", "postgresql"),
        "redis": ("redis",),
        "object_store": ("minio",),
        "clickhouse": ("clickhouse",),
        "rabbitmq": ("rabbitmq", "rabbit"),
    }
    result: list[dict[str, Any]] = []
    for service, service_tokens in tokens.items():
        proof = data["readiness"][service]
        matches = sorted(
            f"{kind}/{name}" for kind, name in identities
            if any(token in name or token in kind.lower() for token in service_tokens)
            and kind not in {"ConfigMap", "Secret"}
        )
        if proof["ownership"] == "release-managed" and not matches:
            fail(f"release-managed {service} topology rendered no identifiable service/workload/operator CR")
        if proof["ownership"] == "external" and any(
            identity.split("/", 1)[0] in {"StatefulSet", "Deployment", "ClickHouseInstallation", "ClickHouseKeeperInstallation", "RabbitmqCluster"}
            for identity in matches
        ):
            fail(f"external {service} topology unexpectedly renders an in-release workload/operator CR")
        result.append({"service": service, "ownership": proof["ownership"], "rendered_identities": matches})
    return {"services": result}


def validate_node_pools(spec: dict[str, Any], nodes_document: Any) -> dict[str, int]:
    nodes = assert_mapping(nodes_document, "node inventory").get("items", [])
    if not isinstance(nodes, list):
        fail("node inventory items must be a list")
    pools = {pool["role"]: pool for pool in spec["node_pools"]["pools"]}
    observed = {role: 0 for role in pools}
    domains = {role: set() for role in pools}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        metadata = node.get("metadata", {})
        node_spec = node.get("spec", {})
        status_value = node.get("status", {})
        labels = metadata.get("labels", {})
        if node_spec.get("unschedulable") is True or not any(condition.get("type") == "Ready" and condition.get("status") == "True" for condition in status_value.get("conditions", []) if isinstance(condition, dict)):
            continue
        label = labels.get("galileo-node-type")
        matching = [pool for pool in pools.values() if pool["label_value"] == label]
        if not matching:
            continue
        pool = matching[0]
        role = pool["role"]
        allocatable = status_value.get("allocatable", {})
        if cpu_millicores(str(allocatable.get("cpu", "")), f"node {metadata.get('name')} cpu") < cpu_millicores(pool["min_cpu"], f"pool {role} min_cpu"):
            fail(f"node {metadata.get('name')} is below {role} CPU minimum")
        if quantity_bytes(str(allocatable.get("memory", "")), f"node {metadata.get('name')} memory") < quantity_bytes(pool["min_memory"], f"pool {role} memory"):
            fail(f"node {metadata.get('name')} is below {role} memory minimum")
        if quantity_bytes(str(allocatable.get("ephemeral-storage", "")), f"node {metadata.get('name')} ephemeral storage") < quantity_bytes(pool["min_ephemeral_storage"], f"pool {role} ephemeral storage"):
            fail(f"node {metadata.get('name')} is below {role} ephemeral-storage minimum")
        if labels.get("kubernetes.io/arch") != pool["architecture"]:
            fail(f"node {metadata.get('name')} architecture differs from {role} pool")
        live_taints = {f"{item.get('key')}={item.get('value', '')}:{item.get('effect')}" for item in node_spec.get("taints", []) if isinstance(item, dict)}
        reviewed_taints = set(pool["taints"])
        if not reviewed_taints.issubset(live_taints):
            fail(f"node {metadata.get('name')} taints differ from {role} pool")
        live_hard_taints = {
            taint for taint in live_taints
            if taint.rsplit(":", 1)[-1] in {"NoSchedule", "NoExecute"}
        }
        reviewed_hard_taints = {
            taint for taint in reviewed_taints
            if taint.rsplit(":", 1)[-1] in {"NoSchedule", "NoExecute"}
        }
        if live_hard_taints != reviewed_hard_taints:
            fail(
                f"node {metadata.get('name')} has an unreviewed hard taint in {role} pool"
            )
        domain = labels.get("topology.kubernetes.io/zone") or labels.get("kubernetes.io/hostname")
        if isinstance(domain, str):
            domains[role].add(domain)
        observed[role] += 1
    for role, pool in pools.items():
        if observed[role] < pool["min_nodes"] or observed[role] > pool["max_nodes"]:
            fail(f"live {role} node count is outside the reviewed range")
        if pool["failure_domains"] and not set(pool["failure_domains"]).issubset(domains[role]):
            fail(f"live {role} failure domains differ from the reviewed pool")
    if spec["environment"] == "production":
        exception = spec["node_pools"].get("production_count_exception")
        if not exception and not (4 <= observed.get("core", 0) <= 10 and 1 <= observed.get("runner", 0) <= 5):
            fail("production requires 4-10 core and 1-5 runner nodes or a written CSE count exception")
        for role, cpu, memory, disk in (("core", "4", "16Gi", "100Gi"), ("runner", "8", "32Gi", "200Gi")):
            pool = pools[role]
            if cpu_millicores(pool["min_cpu"], role) < cpu_millicores(cpu, role) or quantity_bytes(pool["min_memory"], role) < quantity_bytes(memory, role) or quantity_bytes(pool["min_ephemeral_storage"], role) < quantity_bytes(disk, role):
                fail(f"production {role} pool is below documented per-node minimums")
        if not spec["node_pools"]["autoscaler_validated"] or not spec["node_pools"]["cse_sizing_reference"].strip():
            fail("production node pools require autoscaler and CSE sizing evidence")
    return observed


def validate_node_pool_rendering(documents: list[dict[str, Any]], spec: dict[str, Any]) -> list[dict[str, str]]:
    if spec["environment"] != "production":
        return []
    pools = {pool["label_value"]: pool for pool in spec["node_pools"]["pools"]}
    placements: list[dict[str, str]] = []
    for identity, pod in pod_specs(documents):
        selector = pod.get("nodeSelector")
        label = selector.get("galileo-node-type") if isinstance(selector, dict) else None
        if label not in pools:
            fail(f"production workload {identity} lacks an exact reviewed Galileo node-pool selector")
        pool = pools[label]
        has_gpu = any(
            isinstance(container, dict)
            and "nvidia.com/gpu" in container.get("resources", {}).get("limits", {})
            for container in list(pod.get("initContainers", [])) + list(pod.get("containers", []))
        )
        if pool["role"] == "ml" and not has_gpu:
            fail(f"non-GPU workload {identity} is placed on the ML pool")
        if "runner" in identity.lower() and pool["role"] != "runner":
            fail(f"runner workload {identity} is not placed on the runner pool")
        tolerations = pod.get("tolerations", [])
        for taint in pool["taints"]:
            key_value, effect = taint.rsplit(":", 1)
            key, value = key_value.split("=", 1)
            matched = any(
                isinstance(toleration, dict)
                and toleration.get("key") == key
                and toleration.get("effect", effect) == effect
                and (
                    toleration.get("operator") == "Exists"
                    or str(toleration.get("value", "")) == value
                )
                for toleration in tolerations
            )
            if not matched:
                fail(f"production workload {identity} does not tolerate reviewed {pool['role']} taint {taint}")
            if effect == "NoExecute" and any(
                isinstance(toleration, dict)
                and toleration.get("key") == key
                and toleration.get("effect", effect) == effect
                and "tolerationSeconds" in toleration
                for toleration in tolerations
            ):
                fail(
                    f"production workload {identity} has a time-bounded NoExecute "
                    f"toleration for reviewed {pool['role']} taint {taint}"
                )
        placements.append({"workload": identity, "role": pool["role"], "label_value": label})
    if not placements:
        fail("production render contains no schedulable workloads")
    return sorted(placements, key=lambda item: item["workload"])


def validate_rendered_images(documents: list[dict[str, Any]], require_digest: bool) -> list[str]:
    images: set[str] = set()
    for _, pod in pod_specs(documents):
        for container in list(pod.get("initContainers", [])) + list(pod.get("containers", [])) + list(pod.get("ephemeralContainers", [])):
            image = container.get("image") if isinstance(container, dict) else None
            if isinstance(image, str) and image:
                images.add(image)
    if not images:
        fail("rendered chart contains no inspectable workload images")
    for image in images:
        if image.endswith(":latest") or ":latest@" in image:
            fail("rendered image inventory contains a mutable latest tag")
        if require_digest and not re.search(r"@sha256:[0-9a-f]{64}$", image):
            fail("production/air-gap image inventory must be digest pinned")
    return sorted(images)


def rendered_image_items(
    documents: list[dict[str, Any]],
    release: str,
    spec: dict[str, Any],
) -> list[dict[str, Any]]:
    """Inventory each exact image with a conservative eligible-architecture set.

    A selector can narrow the set.  When it does not, every reviewed pool is
    eligible, which intentionally forces an air-gap attestation to cover the
    safe over-approximation instead of guessing at scheduler placement.
    """
    pools = spec["node_pools"]["pools"]
    all_architectures = sorted({str(pool["architecture"]) for pool in pools})
    by_label = {
        str(pool["label_value"]): str(pool["architecture"])
        for pool in pools
    }
    items: list[dict[str, Any]] = []
    for identity, pod in pod_specs(documents):
        selectors = pod.get("nodeSelector", {})
        if not isinstance(selectors, dict):
            fail(f"workload {identity} nodeSelector must be a mapping")
        selected_architecture = selectors.get("kubernetes.io/arch")
        selected_pool = selectors.get("galileo-node-type")
        if selected_architecture is not None:
            if selected_architecture not in {"amd64", "arm64"}:
                fail(f"workload {identity} has an unsupported architecture selector")
            eligible_architectures = [str(selected_architecture)]
        elif selected_pool is not None:
            if selected_pool not in by_label:
                fail(f"workload {identity} selects an undeclared Galileo node pool")
            eligible_architectures = [by_label[str(selected_pool)]]
        else:
            eligible_architectures = all_architectures
        if not eligible_architectures:
            fail(f"workload {identity} has no provable eligible architecture")
        for container_type, containers in (
            ("initContainer", pod.get("initContainers", [])),
            ("container", pod.get("containers", [])),
            ("ephemeralContainer", pod.get("ephemeralContainers", [])),
        ):
            for container in containers if isinstance(containers, list) else []:
                if not isinstance(container, dict) or not isinstance(container.get("image"), str) or not container["image"]:
                    continue
                image = container["image"]
                digest_match = re.search(r"@(sha256:[0-9a-f]{64})$", image)
                items.append({
                    "release": release,
                    "source_object": identity,
                    "container_type": container_type,
                    "container": str(container.get("name", "")),
                    "image": image,
                    "digest": digest_match.group(1) if digest_match else None,
                    "eligible_architectures": eligible_architectures,
                })
    if not items:
        fail("rendered image evidence contains no workload/init/hook/test images")
    return sorted(items, key=lambda item: (item["release"], item["source_object"], item["container_type"], item["container"], item["image"]))


def rendered_resource_inventory(
    release_documents: list[tuple[str, list[dict[str, Any]]]],
    claims: list[dict[str, Any]],
    routing: dict[str, Any],
    spec: dict[str, Any],
    bundle_sha256: str,
    api_scopes: dict[str, bool],
    feature_matrix: Path = FEATURE_MATRIX,
) -> dict[str, Any]:
    """Return a canonical, secret-free exact rendered-resource inventory."""
    matrix = json.loads(secure_read(feature_matrix, "deployment feature matrix")[1])
    features = {item["id"]: item for item in matrix["features"]}
    items: list[dict[str, Any]] = []
    workloads: list[dict[str, Any]] = []
    rbac: list[dict[str, Any]] = []
    for release, documents in release_documents:
        ctl_release = spec["galileoctl"]["enabled"] and release == spec["galileoctl"].get("release_name")
        for document in documents:
            kind = str(document.get("kind", ""))
            api_version = str(document.get("apiVersion", ""))
            metadata = document.get("metadata", {}) if isinstance(document.get("metadata"), dict) else {}
            name = str(metadata.get("name", ""))
            if not api_version or not kind or not name:
                fail("rendered resource inventory found an object without apiVersion/kind/name")
            if kind in {"Ingress", "HTTPRoute", "Gateway", "GatewayClass"}:
                class_id = "routing.gateway-routes" if "Gateway" in kind or kind == "HTTPRoute" else "routing.ingress-resources"
            elif kind in {"PersistentVolumeClaim", "PersistentVolume", "StorageClass", "VolumeSnapshot"}:
                class_id = "production.storage"
            elif kind == "CustomResourceDefinition":
                class_id = "crd.helm-directory"
            elif ctl_release and kind in {"Role", "RoleBinding", "ClusterRole", "ClusterRoleBinding", "ServiceAccount"}:
                class_id = "galileoctl.rbac"
            elif ctl_release:
                class_id = "galileoctl.validation"
            else:
                class_id = "stack.base"
            if class_id not in features:
                fail(f"rendered resource {kind}/{name} has no reviewed product classification")
            annotations = metadata.get("annotations", {}) if isinstance(metadata.get("annotations"), dict) else {}
            hooks = sorted(
                value.strip()
                for value in str(annotations.get("helm.sh/hook", "")).split(",")
                if value.strip()
            )
            scope_key = f"{api_version}|{kind}"
            if scope_key not in api_scopes:
                fail(f"rendered resource inventory lacks API scope evidence for {scope_key}")
            cluster_scoped = not api_scopes[scope_key]
            items.append({
                "api_version": api_version,
                "kind": kind,
                "name": name,
                "namespace": "" if cluster_scoped else str(metadata.get("namespace") or spec["target"]["namespace"]),
                "release": release,
                "cluster_scoped": cluster_scoped,
                "helm_hooks": hooks,
                "classification_id": class_id,
                "owners": features[class_id]["owners"],
            })
            if kind in {"Role", "ClusterRole"}:
                rules: list[dict[str, Any]] = []
                for rule in document.get("rules", []) if isinstance(document.get("rules"), list) else []:
                    if not isinstance(rule, dict):
                        fail(f"rendered RBAC {kind}/{name} has an invalid rule")
                    rules.append({
                        "api_groups": sorted(str(value) for value in rule.get("apiGroups", [])),
                        "resources": sorted(str(value) for value in rule.get("resources", [])),
                        "verbs": sorted(str(value) for value in rule.get("verbs", [])),
                    })
                rbac.append({"release": release, "identity": f"{kind}/{name}", "rules": rules})
        for identity, pod in pod_specs(documents):
            containers: list[dict[str, str]] = []
            for container_type, values in (
                ("initContainer", pod.get("initContainers", [])),
                ("container", pod.get("containers", [])),
                ("ephemeralContainer", pod.get("ephemeralContainers", [])),
            ):
                for container in values if isinstance(values, list) else []:
                    if not isinstance(container, dict):
                        fail(f"rendered workload {identity} has an invalid container")
                    containers.append({
                        "type": container_type,
                        "name": str(container.get("name", "")),
                        "image": str(container.get("image", "")),
                    })
            workloads.append({"release": release, "identity": identity, "containers": containers})
    items.sort(key=lambda item: (item["release"], item["kind"], item["namespace"], item["name"]))
    workloads.sort(key=lambda item: (item["release"], item["identity"]))
    rbac.sort(key=lambda item: (item["release"], item["identity"]))
    identities = [(item["release"], item["kind"], item["namespace"], item["name"]) for item in items]
    if len(identities) != len(set(identities)):
        fail("rendered resource inventory contains duplicate exact identities")
    return {
        "schema": "galileo-on-prem-stack-rendered-resource-inventory/v1",
        "generated_by": "galileo-on-prem-stack-setup",
        "bundle_sha256": bundle_sha256,
        "items": items,
        "workloads": workloads,
        "claims": sorted(claims, key=lambda item: (item["source"], item["name"])),
        "routing": routing,
        "rbac": rbac,
    }


def rendered_hook_inventory(documents: list[dict[str, Any]], namespace: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for document in documents:
        metadata = document.get("metadata", {}) if isinstance(document.get("metadata"), dict) else {}
        annotations = metadata.get("annotations", {}) if isinstance(metadata.get("annotations"), dict) else {}
        events = sorted(value.strip() for value in str(annotations.get("helm.sh/hook", "")).split(",") if value.strip())
        if not events:
            continue
        row: dict[str, Any] = {
            "api_version": str(document.get("apiVersion", "")),
            "kind": str(document.get("kind", "")),
            "name": str(metadata.get("name", "")),
            "namespace": str(metadata.get("namespace") or namespace),
            "events": events,
            "weight": str(annotations.get("helm.sh/hook-weight", "0")),
            "delete_policy": sorted(
                value.strip() for value in str(annotations.get("helm.sh/hook-delete-policy", "")).split(",") if value.strip()
            ),
            "pod_specs": [],
        }
        for identity, pod in pod_specs([document]):
            pod_row = {
                "identity": identity,
                "service_account": str(pod.get("serviceAccountName", "default")),
                "automount_service_account_token": pod.get("automountServiceAccountToken", None),
                "host_network": bool(pod.get("hostNetwork")),
                "host_pid": bool(pod.get("hostPID")),
                "host_ipc": bool(pod.get("hostIPC")),
                "containers": [],
            }
            for container in list(pod.get("initContainers", [])) + list(pod.get("containers", [])):
                if not isinstance(container, dict):
                    continue
                pod_row["containers"].append({
                    "name": str(container.get("name", "")),
                    "image": str(container.get("image", "")),
                    "command": [str(value) for value in container.get("command", [])],
                    "args": [str(value) for value in container.get("args", [])],
                })
            row["pod_specs"].append(pod_row)
        rows.append(row)
    return sorted(rows, key=lambda row: (row["kind"], row["namespace"], row["name"]))


def endpoint_host(value: str) -> str:
    candidate = value.strip().strip("'\"")
    if not candidate or len(candidate) > 2048:
        return ""
    parsed = urlparse(candidate if "://" in candidate else f"//{candidate}")
    try:
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return ""
    if not host:
        return ""
    host = host.lower().rstrip(".")
    try:
        parsed_ip = ipaddress.ip_address(host)
    except ValueError:
        # Single-label strings are too ambiguous to treat as durable endpoint
        # evidence (a credential can easily look like one). Kubernetes-local
        # destinations must be represented by their reviewed FQDN.
        if "." not in host or len(host) > 253 or any(
            not DNS_RE.fullmatch(label) for label in host.split(".")
        ):
            return ""
        parsed_ip = None
    display_host = f"[{host}]" if isinstance(parsed_ip, ipaddress.IPv6Address) and port is not None else host
    return f"{display_host}:{port}" if port is not None else host


def rendered_endpoint_items(
    release_documents: list[tuple[str, list[dict[str, Any]]]],
    release_values: list[tuple[str, Any]],
) -> list[dict[str, str]]:
    """Extract secret-free runtime host evidence from exact render + non-secret values."""
    found: set[tuple[str, str, str]] = set()
    url_pattern = re.compile(r"(?:https?|grpcs?|postgres(?:ql)?|redis|amqps?|s3)://[^\s'\"<>]+", re.I)
    assignment_pattern = re.compile(
        r"(?:^|[\s,;])(?:--)?[A-Za-z0-9_.-]*(?:host|endpoint|url|address|server|broker|dsn)"
        r"[=:]\s*([^\s,;]+)",
        re.I,
    )

    def add_value(value: str, purpose: str, source: str, key_hint: str = "") -> None:
        candidates = url_pattern.findall(value)
        candidates.extend(match.group(1) for match in assignment_pattern.finditer(value))
        if re.search(r"host|endpoint|url|address|server|broker|dsn", key_hint, re.I):
            candidates.append(value)
        for candidate in candidates:
            host = endpoint_host(candidate)
            if not host:
                continue
            safe_purpose = item_id("endpoint", purpose)[:128]
            safe_source = item_id("source", source)[:240]
            found.add((host, safe_purpose, safe_source))

    def walk(value: Any, purpose: str, source: str, trail: tuple[str, ...] = ()) -> None:
        if isinstance(value, dict):
            # Rendered Secret bodies are decoded only by the dedicated in-memory
            # branch below; this general walker never persists their content.
            if str(value.get("kind", "")) == "Secret":
                return
            if isinstance(value.get("name"), str) and isinstance(value.get("value"), str):
                add_value(
                    value["value"],
                    purpose,
                    f"{source}@{'.'.join(trail + ('value',))}",
                    value["name"],
                )
            for key, child in value.items():
                next_trail = trail + (str(key),)
                if isinstance(child, str):
                    add_value(child, purpose, f"{source}@{'.'.join(next_trail)}", str(key))
                else:
                    walk(child, purpose, source, next_trail)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                next_trail = trail + (str(index),)
                if isinstance(child, str):
                    add_value(
                        child,
                        purpose,
                        f"{source}@{'.'.join(next_trail)}",
                        trail[-1] if trail else "",
                    )
                else:
                    walk(child, purpose, source, next_trail)

    for release, documents in release_documents:
        for document in documents:
            if document.get("kind") == "Secret":
                # Secret payloads are never mined for durable endpoint rows.
                # A versioned non-secret endpoint contract is required when a
                # Secret carries a DSN/URL; preflight reports that open gate.
                continue
            identity = f"{document.get('kind', '')}/{document.get('metadata', {}).get('name', '')}"
            walk(document, release, identity)
    for release, values in release_values:
        walk(values, release, "nonsecret-values")
    return [
        {"host": host, "purpose": purpose, "source": source}
        for host, purpose, source in sorted(found)
    ]


def endpoint_inventory_evidence(
    image_inventory: dict[str, Any], items: list[dict[str, str]]
) -> dict[str, Any]:
    return {
        "schema": "galileo-on-prem-stack-rendered-endpoint-inventory/v1",
        "generated_by": "galileo-on-prem-stack-setup",
        "source_bundle_sha256": image_inventory["source_bundle_sha256"],
        "charts": image_inventory["charts"],
        "inputs": image_inventory["inputs"],
        "redacted_render_sha256": image_inventory["redacted_render_sha256"],
        "target": image_inventory["target"],
        "created_at": image_inventory["created_at"],
        "items": items,
    }


def validate_endpoint_inventory_evidence(document: Any, raw: bytes) -> dict[str, Any]:
    evidence = assert_mapping(document, "rendered endpoint inventory evidence")
    expected = {"schema", "generated_by", "source_bundle_sha256", "charts", "inputs", "redacted_render_sha256", "target", "created_at", "items"}
    if set(evidence) != expected or evidence.get("schema") != "galileo-on-prem-stack-rendered-endpoint-inventory/v1" or evidence.get("generated_by") != "galileo-on-prem-stack-setup":
        fail("rendered endpoint inventory evidence fields differ")
    if raw != json_bytes(evidence):
        fail("rendered endpoint inventory evidence is not canonical JSON")
    items = evidence.get("items")
    if not isinstance(items, list):
        fail("rendered endpoint inventory items must be a list")
    seen: set[tuple[str, str, str]] = set()
    for index, item_value in enumerate(items):
        item = assert_mapping(item_value, f"rendered endpoint inventory items[{index}]")
        if set(item) != {"host", "purpose", "source"}:
            fail("rendered endpoint inventory item fields differ")
        identity = (item.get("host"), item.get("purpose"), item.get("source"))
        if any(not isinstance(value, str) or not value or len(value) > 512 for value in identity) or endpoint_host(identity[0]) != identity[0] or identity in seen:
            fail("rendered endpoint inventory item is invalid or duplicated")
        seen.add(identity)
    if items != [{"host": host, "purpose": purpose, "source": source} for host, purpose, source in sorted(seen)]:
        fail("rendered endpoint inventory items are not canonically sorted")
    return evidence


def validate_rendered_image_evidence(
    document: Any,
    raw: bytes,
    spec: dict[str, Any],
    manifest: dict[str, Any],
    preflight_evidence: dict[str, Any],
) -> dict[str, Any]:
    evidence = assert_mapping(document, "rendered image inventory evidence")
    fields = {
        "schema", "generated_by", "source_bundle_sha256", "charts", "inputs",
        "redacted_render_sha256", "target", "created_at", "items",
    }
    if set(evidence) != fields or evidence.get("schema") != IMAGE_EVIDENCE_SCHEMA:
        fail("rendered image inventory evidence fields differ from the exact contract")
    if raw != json_bytes(evidence):
        fail("rendered image inventory evidence is not canonical JSON")
    if evidence.get("generated_by") != "galileo-on-prem-stack-setup" or evidence.get("source_bundle_sha256") != manifest["bundle_sha256"]:
        fail("rendered image inventory evidence source binding differs")
    expected_charts = [{
        "name": "galileo-stack",
        "release": spec["stack"]["release_name"],
        "version": spec["stack"]["chart_version"],
        "sha256": spec["stack"]["chart_sha256"],
    }]
    if spec["galileoctl"]["enabled"]:
        expected_charts.append({
            "name": "galileoctl",
            "release": spec["galileoctl"]["release_name"],
            "version": spec["galileoctl"]["chart_version"],
            "sha256": spec["galileoctl"]["chart_sha256"],
        })
    if evidence.get("charts") != expected_charts:
        fail("rendered image inventory evidence chart binding differs")
    manifest_files = {item["path"]: item["sha256"] for item in manifest["files"]}
    expected_inputs = {
        "stack_nonsecret_values_sha256": manifest_files[spec["stack"]["nonsecret_values_file"]],
        "stack_secret_contract_sha256": preflight_evidence["secret_contract_sha256"],
        "galileoctl_nonsecret_values_sha256": (
            manifest_files[spec["galileoctl"]["nonsecret_values_file"]]
            if spec["galileoctl"]["enabled"] else ""
        ),
        "galileoctl_secret_contract_sha256": preflight_evidence["galileoctl_secret_contract_sha256"],
    }
    if evidence.get("inputs") != expected_inputs:
        fail("rendered image inventory evidence values binding differs")
    expected_target = {
        "context": spec["target"]["kube_context"],
        "api_server": spec["target"]["api_server"],
        "ca_sha256": spec["target"]["ca_sha256"],
        "kube_system_uid": spec["target"]["cluster_uid"],
        "namespace": spec["target"]["namespace"],
        "namespace_uid": preflight_evidence["target"]["namespace_uid"],
    }
    if evidence.get("target") != expected_target or evidence.get("created_at") != preflight_evidence["created_at"]:
        fail("rendered image inventory evidence target/time binding differs")
    if not SHA_RE.fullmatch(str(evidence.get("redacted_render_sha256", ""))):
        fail("rendered image inventory redacted render digest is invalid")
    items = evidence.get("items")
    if not isinstance(items, list) or not items:
        fail("rendered image inventory evidence is empty")
    expected_releases = {spec["stack"]["release_name"]}
    if spec["galileoctl"]["enabled"]:
        expected_releases.add(spec["galileoctl"]["release_name"])
    def sort_key(item: dict[str, Any]) -> tuple[str, str, str, str, str]:
        return (item["release"], item["source_object"], item["container_type"], item["container"], item["image"])
    seen: set[tuple[str, str, str, str, str]] = set()
    for index, item_value in enumerate(items):
        item = assert_mapping(item_value, f"rendered image inventory items[{index}]")
        if set(item) != {
            "release", "source_object", "container_type", "container", "image",
            "digest", "eligible_architectures",
        }:
            fail("rendered image inventory item fields differ from the exact contract")
        if item.get("release") not in expected_releases or item.get("container_type") not in {"container", "initContainer", "ephemeralContainer"}:
            fail("rendered image inventory item release/container type is invalid")
        for field in ("source_object", "container", "image"):
            value = item.get(field)
            if not isinstance(value, str) or not value or len(value) > 512 or any(character.isspace() for character in value):
                fail(f"rendered image inventory item {field} is invalid")
        image = item["image"]
        match = re.search(r"@(sha256:[0-9a-f]{64})$", image)
        expected_digest = match.group(1) if match else None
        if item.get("digest") != expected_digest:
            fail("rendered image inventory item digest differs from its image reference")
        architectures = item.get("eligible_architectures")
        if (
            not isinstance(architectures, list)
            or not architectures
            or architectures != sorted(set(architectures))
            or any(value not in {"amd64", "arm64"} for value in architectures)
        ):
            fail("rendered image inventory item eligible_architectures is invalid")
        identity = (item["release"], item["source_object"], item["container_type"], item["container"], image)
        if identity in seen:
            fail("rendered image inventory contains a duplicate source/container/image row")
        seen.add(identity)
    try:
        sorted_items = sorted(items, key=sort_key)
    except KeyError:
        fail("rendered image inventory item is missing a sort field")
    if items != sorted_items:
        fail("rendered image inventory items are not canonically sorted")
    if sorted({item["image"] for item in items}) != preflight_evidence["rendered_images"]:
        fail("rendered image inventory differs from preflight's exact image set")
    return evidence


def validate_retention_rendered(documents: list[dict[str, Any]]) -> list[str]:
    """Require durable objects to be retained in Helm's post-rendered manifest."""
    protected: list[str] = []
    for document in documents:
        kind = document.get("kind")
        name = str(document.get("metadata", {}).get("name", ""))
        if kind == "PersistentVolumeClaim":
            policy = document.get("metadata", {}).get("annotations", {}).get("helm.sh/resource-policy")
            if policy != "keep":
                fail(f"rendered PVC {name!r} lacks Helm keep policy")
            protected.append(f"PersistentVolumeClaim/{name}")
        elif kind == "StatefulSet":
            spec = document.get("spec", {})
            claims = spec.get("volumeClaimTemplates", []) if isinstance(spec, dict) else []
            if claims:
                retention = spec.get("persistentVolumeClaimRetentionPolicy", {})
                if retention.get("whenDeleted") != "Retain" or retention.get("whenScaled") != "Retain":
                    fail(f"rendered StatefulSet {name!r} lacks Retain deletion/scaling policy")
                for claim in claims:
                    if not isinstance(claim, dict) or claim.get("metadata", {}).get("annotations", {}).get("helm.sh/resource-policy") != "keep":
                        fail(f"rendered StatefulSet {name!r} has an unprotected volumeClaimTemplate")
                protected.append(f"StatefulSet/{name}")
    return sorted(protected)


def rendered_claims(documents: list[dict[str, Any]], storage: dict[str, Any], environment: str) -> list[dict[str, Any]]:
    policies = {item["name"]: item for item in storage["classes"]}
    result: list[dict[str, Any]] = []
    for document in documents:
        kind = document.get("kind")
        parent = str(document.get("metadata", {}).get("name", ""))
        claims: list[dict[str, Any]] = []
        if kind == "PersistentVolumeClaim":
            claims = [document]
        elif kind == "StatefulSet":
            value = document.get("spec", {}).get("volumeClaimTemplates", [])
            claims = value if isinstance(value, list) else []
        elif kind in {"ClickHouseInstallation", "ClickHouseKeeperInstallation", "RabbitmqCluster"}:
            stack: list[Any] = [document.get("spec", {})]
            while stack:
                value = stack.pop()
                if isinstance(value, dict):
                    templates = value.get("volumeClaimTemplates")
                    if isinstance(templates, list):
                        claims.extend(template for template in templates if isinstance(template, dict))
                    persistence = value.get("persistence")
                    if kind == "RabbitmqCluster" and isinstance(persistence, dict) and persistence.get("storage"):
                        claims.append({
                            "metadata": {"name": "persistence"},
                            "spec": {
                                "storageClassName": persistence.get("storageClassName") or persistence.get("storageClass"),
                                "accessModes": persistence.get("accessModes", ["ReadWriteOnce"]),
                                "resources": {"requests": {"storage": persistence.get("storage")}},
                            },
                        })
                    stack.extend(value.values())
                elif isinstance(value, list):
                    stack.extend(value)
            if environment == "production" and not claims:
                fail(f"production persistence-bearing operator CR {kind}/{parent} has no classifiable claim template")
        for claim in claims:
            if not isinstance(claim, dict):
                fail("rendered claim must be a mapping")
            claim_spec = assert_mapping(claim.get("spec"), "rendered claim spec")
            name = str(claim.get("metadata", {}).get("name", ""))
            storage_class = claim_spec.get("storageClassName")
            if not isinstance(storage_class, str) or not storage_class or storage_class not in policies:
                fail(f"rendered claim {kind}/{parent}/{name} lacks an exact reviewed StorageClass")
            access_modes = claim_spec.get("accessModes")
            if not isinstance(access_modes, list) or not access_modes or any(mode not in {"ReadWriteOnce", "ReadWriteMany", "ReadOnlyMany", "ReadWriteOncePod"} for mode in access_modes):
                fail(f"rendered claim {kind}/{parent}/{name} has unsupported accessModes")
            requested = claim_spec.get("resources", {}).get("requests", {}).get("storage")
            requested_bytes = quantity_bytes(requested, f"rendered claim {kind}/{parent}/{name} storage")
            policy_min = int(policies[storage_class].get("minimum_size_gib", 1)) * 2**30
            minimum = max(policy_min, 200 * 2**30) if environment == "production" else policy_min
            if requested_bytes < minimum:
                fail(f"rendered claim {kind}/{parent}/{name} is below its reviewed storage minimum")
            replicas = document.get("spec", {}).get("replicas", 1) if kind in {"StatefulSet", "RabbitmqCluster"} else 1
            if not isinstance(replicas, int) or isinstance(replicas, bool) or replicas < 0:
                fail(f"rendered StatefulSet {parent} has an invalid replica count")
            expected_names: list[str] = []
            expected_owners: list[dict[str, str]] = []
            if kind in {"ClickHouseInstallation", "ClickHouseKeeperInstallation", "RabbitmqCluster"}:
                matches = [
                    row for row in storage["operator_claims"]
                    if row["kind"] == kind and row["name"] == parent and row["claim_name"] == name
                ]
                if len(matches) != 1:
                    fail(f"operator claim {kind}/{parent}/{name} requires one exact expected_pvc_names contract")
                expected_names = sorted(matches[0]["expected_pvc_names"])
                expected_owners = sorted(
                    matches[0]["expected_pvc_owners"],
                    key=lambda item: item["pvc_name"],
                )
                replicas = len(expected_names)
            result.append({
                "source": f"{kind}/{parent}",
                "name": name,
                "storage_class": storage_class,
                "requested_bytes": requested_bytes,
                "access_modes": sorted(access_modes),
                "replicas": replicas,
                "operator_generated": kind in {"ClickHouseInstallation", "ClickHouseKeeperInstallation", "RabbitmqCluster"},
                "expected_pvc_names": expected_names,
                "expected_pvc_owners": expected_owners,
            })
    return sorted(result, key=lambda item: (item["source"], item["name"]))


def validate_live_claims(live_document: Any, expected_claims: list[dict[str, Any]], release_names: set[str]) -> list[str]:
    """Legacy shape-only diagnostic; never establishes PVC provenance.

    The connected preflight intentionally does not call this helper. Exact
    controller UID, retained StatefulSet, PV claimRef, and Helm provenance are
    not proven by a namespace PVC list, so the machine-readable handoff keeps
    ``persistent_claim_provenance_incomplete`` open.
    """
    live = assert_mapping(live_document, "live PVC inventory")
    items = live.get("items")
    if not isinstance(items, list):
        fail("live PVC inventory items must be a list")
    expected_by_name: dict[str, dict[str, Any]] = {}
    expected_owners: dict[str, tuple[str, str]] = {}
    for claim in expected_claims:
        source_kind, source_name = claim["source"].split("/", 1)
        if source_kind == "PersistentVolumeClaim":
            names = [claim["name"]]
        elif source_kind == "StatefulSet":
            names = [f"{claim['name']}-{source_name}-{ordinal}" for ordinal in range(claim["replicas"])]
        elif source_kind in {"ClickHouseInstallation", "ClickHouseKeeperInstallation", "RabbitmqCluster"}:
            names = claim["expected_pvc_names"]
            owner_rows = claim.get("expected_pvc_owners")
            if not isinstance(owner_rows, list):
                fail("operator-generated claim lacks exact direct-owner evidence")
            expected_owners.update({
                row["pvc_name"]: (row["kind"], row["name"])
                for row in owner_rows
                if isinstance(row, dict)
            })
            if set(expected_owners).intersection(set(names)) != set(names):
                fail("operator-generated claim direct-owner evidence is incomplete")
        else:
            fail("rendered claim source kind is unsupported")
        for name in names:
            if name in expected_by_name:
                fail("rendered claim mapping produces duplicate live PVC names")
            expected_by_name[name] = claim
    observed: dict[str, dict[str, Any]] = {}
    for pvc_value in items:
        pvc = assert_mapping(pvc_value, "live PVC")
        metadata = pvc.get("metadata", {})
        labels = metadata.get("labels", {})
        annotations = metadata.get("annotations", {})
        owner = labels.get("app.kubernetes.io/instance") or annotations.get("meta.helm.sh/release-name")
        name = metadata.get("name")
        controllers = [
            reference for reference in metadata.get("ownerReferences", [])
            if isinstance(reference, dict) and reference.get("controller") is True
        ]
        direct_controller = (
            (controllers[0].get("kind"), controllers[0].get("name"))
            if len(controllers) == 1 else None
        )
        generated_expected = isinstance(name, str) and name in expected_owners
        deterministic_vct_expected = (
            isinstance(name, str)
            and name in expected_by_name
            and expected_by_name[name]["source"].startswith("StatefulSet/")
        )
        known_generated_controller = direct_controller in set(expected_owners.values())
        if owner not in release_names and not generated_expected and not known_generated_controller and not deterministic_vct_expected:
            continue
        if not isinstance(name, str) or not name or name in observed:
            fail("release-owned live PVC has a missing or duplicate name")
        observed[name] = pvc
    if set(observed) != set(expected_by_name):
        missing = sorted(set(expected_by_name) - set(observed))
        extra = sorted(set(observed) - set(expected_by_name))
        fail(f"release-owned live PVC set differs from rendered claims (missing={missing[:3]}, extra={extra[:3]})")
    for name, pvc in observed.items():
        expected = expected_by_name[name]
        if name in expected_owners:
            controllers = [
                reference
                for reference in pvc.get("metadata", {}).get("ownerReferences", [])
                if isinstance(reference, dict) and reference.get("controller") is True
            ]
            expected_owner = expected_owners.get(name)
            if (
                expected_owner is None
                or len(controllers) != 1
                or (controllers[0].get("kind"), controllers[0].get("name")) != expected_owner
                or not isinstance(controllers[0].get("uid"), str)
                or not controllers[0]["uid"]
            ):
                fail(f"controller-generated live PVC {name} differs from its exact direct controller owner")
        pvc_spec = pvc.get("spec", {})
        status_value = pvc.get("status", {})
        requested = pvc_spec.get("resources", {}).get("requests", {}).get("storage")
        capacity = status_value.get("capacity", {}).get("storage")
        if (
            status_value.get("phase") != "Bound"
            or pvc_spec.get("storageClassName") != expected["storage_class"]
            or sorted(pvc_spec.get("accessModes", [])) != expected["access_modes"]
            or quantity_bytes(requested, f"live PVC {name} request") != expected["requested_bytes"]
            or quantity_bytes(capacity, f"live PVC {name} capacity") < expected["requested_bytes"]
        ):
            fail(f"release-owned live PVC {name} differs from rendered class/request/access/capacity")
    return sorted(observed)


def validate_rendered_routing(documents: list[dict[str, Any]], routing: dict[str, Any], environment: str) -> dict[str, Any]:
    hosts: set[str] = set()
    tls_secrets: set[str] = set()
    classes: set[str] = set()
    paths: list[str] = []
    host_paths: dict[str, list[str]] = {}
    tls_bindings: set[tuple[str, str]] = set()
    load_balancers: set[str] = set()
    resources: list[dict[str, Any]] = []
    for document in documents:
        kind = document.get("kind")
        name = str(document.get("metadata", {}).get("name", ""))
        resource_spec = document.get("spec", {})
        if kind == "Ingress":
            ingress_class = resource_spec.get("ingressClassName") or document.get("metadata", {}).get("annotations", {}).get("kubernetes.io/ingress.class")
            if isinstance(ingress_class, str):
                classes.add(ingress_class)
            for tls in resource_spec.get("tls", []):
                if isinstance(tls, dict):
                    if isinstance(tls.get("secretName"), str):
                        tls_secrets.add(tls["secretName"])
                        tls_bindings.update(
                            (str(host).lower(), tls["secretName"])
                            for host in tls.get("hosts", [])
                            if isinstance(host, str)
                        )
                    hosts.update(str(host).lower() for host in tls.get("hosts", []) if isinstance(host, str))
            for rule in resource_spec.get("rules", []):
                if not isinstance(rule, dict):
                    continue
                if isinstance(rule.get("host"), str):
                    rule_host = rule["host"].lower()
                    hosts.add(rule_host)
                    host_paths.setdefault(rule_host, [])
                else:
                    rule_host = ""
                for path in rule.get("http", {}).get("paths", []):
                    if isinstance(path, dict) and isinstance(path.get("path"), str):
                        paths.append(path["path"])
                        if rule_host:
                            host_paths[rule_host].append(path["path"])
            resources.append({"kind": "Ingress", "name": name})
        elif kind == "HTTPRoute":
            route_hosts = [str(host).lower() for host in resource_spec.get("hostnames", []) if isinstance(host, str)]
            hosts.update(route_hosts)
            for host in route_hosts:
                host_paths.setdefault(host, [])
            for rule in resource_spec.get("rules", []):
                for match in rule.get("matches", []) if isinstance(rule, dict) else []:
                    value = match.get("path", {}).get("value") if isinstance(match, dict) else None
                    if isinstance(value, str):
                        paths.append(value)
                        for host in route_hosts:
                            host_paths[host].append(value)
            resources.append({"kind": "HTTPRoute", "name": name})
        elif kind == "Gateway" and isinstance(resource_spec.get("gatewayClassName"), str):
            classes.add(resource_spec["gatewayClassName"])
            for listener in resource_spec.get("listeners", []):
                if isinstance(listener, dict):
                    listener_host = listener.get("hostname")
                    if isinstance(listener.get("hostname"), str):
                        hosts.add(listener["hostname"].lower())
                    reference = listener.get("tls", {}).get("certificateRefs", [])
                    for item in reference:
                        if isinstance(item, dict) and isinstance(item.get("name"), str):
                            tls_secrets.add(item["name"])
                            if isinstance(listener_host, str):
                                tls_bindings.add((listener_host.lower(), item["name"]))
            resources.append({"kind": "Gateway", "name": name})
        elif kind == "Service" and resource_spec.get("type") == "LoadBalancer":
            load_balancers.add(name)
            resources.append({"kind": "Service", "name": name})
    expected_hosts = {routing["console_host"], routing["api_host"], routing["grafana_host"]}
    expected_hosts.update(str(urlparse(route).hostname).lower() for route in routing["routes"])
    if environment == "production":
        if expected_hosts != hosts:
            fail("rendered route host set differs from the exact reviewed hosts")
        if set(routing["tls_secret_names"]) != tls_secrets:
            fail("rendered TLS Secret references differ from the reviewed contract")
        reviewed_tls_bindings = {
            (str(item["host"]).lower(), str(item["secret"]))
            for item in routing["tls_bindings"]
        }
        if tls_bindings != reviewed_tls_bindings:
            fail("rendered TLS host-to-Secret bindings differ from the exact reviewed contract")
        expected_classes = {value for value in (routing.get("ingress_class"), routing.get("gateway_class")) if value}
        if expected_classes != classes:
            fail("rendered ingress/gateway class set differs from the reviewed contract")
        if set(routing["load_balancer_services"]) != load_balancers:
            fail("rendered LoadBalancer services differ from the reviewed contract")
        for route in routing["routes"]:
            parsed = urlparse(route)
            expected_path = parsed.path or "/"
            routed_paths = host_paths.get(str(parsed.hostname).lower(), [])
            if not any(path == "/" or expected_path == path or expected_path.startswith(path.rstrip("/") + "/") for path in routed_paths):
                fail(f"rendered routes do not cover reviewed URL path {route}")
        if any(path.rstrip("/").endswith("/metrics") for path in paths):
            fail("rendered public route exposes a metrics path")
        api_paths = host_paths.get(routing["api_host"], [])
        trace_indexes = [index for index, path in enumerate(api_paths) if path == "/otel/v1/traces"]
        catchall_indexes = [index for index, path in enumerate(api_paths) if path in {"/", "/api", "/api/"}]
        if not trace_indexes or (catchall_indexes and min(trace_indexes) >= min(catchall_indexes)):
            fail("rendered trace route is absent or ordered after an API catch-all")
        objects = {
            (str(document.get("kind", "")), str(document.get("metadata", {}).get("name", ""))): document
            for document in documents
        }
        for control in routing["streaming_timeout_controls"]:
            document = objects.get((control["kind"], control["name"]))
            annotations = document.get("metadata", {}).get("annotations", {}) if isinstance(document, dict) else {}
            raw_value = annotations.get(control["annotation"]) if isinstance(annotations, dict) else None
            match = re.fullmatch(r"([0-9]+)(?:s)?", str(raw_value or ""))
            if match is None or int(match.group(1)) < control["minimum_seconds"]:
                fail("rendered streaming timeout control differs from its exact reviewed annotation minimum")
        rendered_identities = set(objects)
        required_metrics = {(row["kind"], row["name"]) for row in routing["metrics_protection_resources"]}
        if not required_metrics <= rendered_identities:
            fail("rendered metrics-protection resources differ from the reviewed contract")
    if any(not item["name"] for item in resources) or len({(item["kind"], item["name"]) for item in resources}) != len(resources):
        fail("rendered routing resources have missing or duplicate identities")
    return {
        "hosts": sorted(hosts),
        "tls_secret_names": sorted(tls_secrets),
        "classes": sorted(classes),
        "paths": paths,
        "host_paths": {host: values for host, values in sorted(host_paths.items())},
        "tls_bindings": [{"host": host, "secret": secret} for host, secret in sorted(tls_bindings)],
        "load_balancer_services": sorted(load_balancers),
        "resources": sorted(resources, key=lambda item: (item["kind"], item["name"])),
    }


def release_owned_resource(
    item: dict[str, Any],
    kind: str,
    identities: set[tuple[str, str]],
    release_names: set[str],
) -> bool:
    metadata = item.get("metadata", {})
    identity = (kind, metadata.get("name"))
    labels = metadata.get("labels", {})
    annotations = metadata.get("annotations", {})
    owner = labels.get("app.kubernetes.io/instance") or annotations.get("meta.helm.sh/release-name")
    return identity in identities and owner in release_names and bool(metadata.get("uid"))


def require_tls_key_marker(marker: bytes, name: str) -> None:
    if marker.decode(errors="replace").strip() != "present":
        fail(f"TLS Secret {name} is missing tls.key")


def certificate_dns_name_matches(pattern: str, host: str) -> bool:
    pattern_value = pattern.lower().rstrip(".")
    host_value = host.lower().rstrip(".")
    if pattern_value.startswith("*."):
        suffix = pattern_value[2:]
        return host_value.endswith(f".{suffix}") and len(host_value.split(".")) == len(suffix.split(".")) + 1
    return pattern_value == host_value


def validate_tls_secret_certificates(
    kube: list[str],
    env: dict[str, str],
    namespace: str,
    routing: dict[str, Any],
    temp: Path,
    prefix: str,
) -> dict[str, list[str]]:
    hosts_by_secret: dict[str, list[str]] = {}
    for index, name in enumerate(routing["tls_secret_names"]):
        marker = run_checked(
            kube + ["get", "secret", name, "--namespace", namespace, "-o", "go-template={{if index .data \"tls.key\"}}present{{end}}"],
            env,
            limit=16,
        )
        require_tls_key_marker(marker, name)
        encoded = run_checked(
            kube + ["get", "secret", name, "--namespace", namespace, "-o", "jsonpath={.data.tls\\.crt}"],
            env,
            limit=1024 * 1024,
        )
        try:
            certificate = base64.b64decode(encoded.strip(), validate=True)
        except ValueError:
            fail(f"TLS Secret {name} has invalid certificate encoding")
        if b"PRIVATE KEY" in certificate:
            fail(f"TLS Secret {name} certificate field contains private-key material")
        cert_path = temp / f"{prefix}-public-certificate-{index}.pem"
        write_private(cert_path, certificate)
        try:
            decoded = ssl._ssl._test_decode_cert(str(cert_path))  # type: ignore[attr-defined]
            expiry = float(ssl.cert_time_to_seconds(decoded["notAfter"]))
        except (KeyError, ValueError, ssl.SSLError):
            fail(f"TLS Secret {name} certificate cannot be safely decoded")
        if expiry < utc_now().timestamp() + routing["certificate_min_valid_days"] * 86400:
            fail(f"TLS Secret {name} certificate expires inside the reviewed safety window")
        hosts_by_secret[name] = sorted(
            {value.lower() for kind, value in decoded.get("subjectAltName", []) if kind == "DNS"}
        )
    for binding in routing["tls_bindings"]:
        certificate_hosts = hosts_by_secret.get(binding["secret"], [])
        if not any(certificate_dns_name_matches(value, binding["host"]) for value in certificate_hosts):
            fail(
                f"TLS Secret {binding['secret']} certificate SANs do not cover its exact reviewed host {binding['host']}"
            )
    return hosts_by_secret


def validate_dns_exact(routing: dict[str, Any]) -> dict[str, list[str]]:
    reviewed_ips: set[str] = set()
    for value in routing["load_balancer_addresses"]:
        try:
            reviewed_ips.add(str(ipaddress.ip_address(value)))
        except ValueError:
            reviewed_ips.update(item[4][0] for item in socket.getaddrinfo(value, 443, type=socket.SOCK_STREAM))
    if not reviewed_ips:
        fail("reviewed LoadBalancer addresses resolve to an empty set")
    results: dict[str, list[str]] = {}
    for host in (routing["console_host"], routing["api_host"], routing["grafana_host"]):
        resolved = {item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
        if resolved != reviewed_ips:
            fail(f"DNS for {host} does not exactly equal the reviewed load-balancer address set")
        results[host] = sorted(resolved)
    return results


def validate_prerequisite_load_balancer_services(
    services: dict[str, Any], routing: dict[str, Any]
) -> tuple[list[dict[str, Any]], set[str]]:
    expected_rows = {
        (row["namespace"], row["name"]): row
        for row in routing["prerequisite_load_balancers"]
    }
    observed_rows: list[dict[str, Any]] = []
    observed_addresses: set[str] = set()
    for service in services.get("items", []):
        metadata = service.get("metadata", {})
        identity = (metadata.get("namespace"), metadata.get("name"))
        if identity not in expected_rows:
            continue
        expected = expected_rows.pop(identity)
        if metadata.get("uid") != expected["uid"]:
            fail("reviewed routing prerequisite Service UID changed")
        if service.get("spec", {}).get("type") != "LoadBalancer":
            fail("reviewed routing prerequisite Service is not a LoadBalancer")
        addresses: set[str] = set()
        for item in service.get("status", {}).get("loadBalancer", {}).get("ingress", []):
            address = item.get("ip") or item.get("hostname") if isinstance(item, dict) else None
            if isinstance(address, str):
                addresses.add(address)
                observed_addresses.add(address)
        if addresses != set(expected["addresses"]):
            fail("pre-existing LoadBalancer Service addresses differ from its exact reviewed identity")
        observed_rows.append({
            "namespace": str(identity[0]),
            "name": str(identity[1]),
            "uid": str(metadata["uid"]),
            "addresses": sorted(addresses),
        })
    if expected_rows:
        fail("an exact reviewed routing prerequisite LoadBalancer Service is absent")
    if observed_addresses != set(routing["load_balancer_addresses"]):
        fail("pre-existing LoadBalancer addresses differ from the reviewed routing contract")
    return sorted(observed_rows, key=lambda item: (item["namespace"], item["name"])), observed_addresses


def validate_routing_prerequisites(
    kube: list[str], env: dict[str, str], namespace: str, routing: dict[str, Any], temp: Path
) -> dict[str, Any]:
    """Validate pre-existing controller, DNS/LB and public TLS inputs."""
    if routing.get("dns_validated") is not True:
        fail("production routing requires explicit DNS-validation attestation")
    ingress_class = routing.get("ingress_class")
    gateway_class = routing.get("gateway_class")
    if ingress_class:
        doc = parse_json_bytes(run_checked(kube + ["get", "ingressclass", ingress_class, "-o", "json"], env), "IngressClass")
        if doc.get("metadata", {}).get("name") != ingress_class or not doc.get("spec", {}).get("controller"):
            fail("reviewed IngressClass is absent or has no controller owner")
    if gateway_class:
        doc = parse_json_bytes(run_checked(kube + ["get", "gatewayclass", gateway_class, "-o", "json"], env), "GatewayClass")
        accepted = any(condition.get("type") == "Accepted" and condition.get("status") == "True" for condition in doc.get("status", {}).get("conditions", []) if isinstance(condition, dict))
        if doc.get("metadata", {}).get("name") != gateway_class or not doc.get("spec", {}).get("controllerName") or not accepted:
            fail("reviewed GatewayClass is absent, unowned, or not Accepted")
    # Read only the exact reviewed prerequisite identities.  Namespace-wide or
    # all-cluster Service listing can expose unrelated tenants and lets an
    # unrelated object accidentally satisfy a routing observation.
    service_items: list[dict[str, Any]] = []
    for row in routing["prerequisite_load_balancers"]:
        service_items.append(
            parse_json_bytes(
                run_checked(
                    kube
                    + [
                        "get",
                        "service",
                        row["name"],
                        "--namespace",
                        row["namespace"],
                        "-o",
                        "json",
                    ],
                    env,
                ),
                "routing prerequisite Service",
            )
        )
    services = {"items": service_items}
    observed_rows, observed_addresses = validate_prerequisite_load_balancer_services(services, routing)
    previous_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(5)
    try:
        dns_results = validate_dns_exact(routing)
    except OSError:
        fail("production routing DNS/LB prerequisite resolution failed")
    finally:
        socket.setdefaulttimeout(previous_timeout)
    certificate_hosts = validate_tls_secret_certificates(
        kube, env, namespace, routing, temp, "prerequisite"
    )
    return {
        "load_balancers": sorted(observed_rows, key=lambda item: (item["namespace"], item["name"])),
        "addresses": sorted(observed_addresses),
        "certificate_hosts_by_secret": certificate_hosts,
        "dns_answers": dns_results,
        "dns_validated": True,
    }


def validate_live_routing(
    kube: list[str],
    env: dict[str, str],
    namespace: str,
    routing: dict[str, Any],
    rendered: dict[str, Any],
    release_names: set[str],
    temp: Path,
) -> dict[str, Any]:
    if routing.get("dns_validated") is not True:
        fail("production routing requires explicit DNS-validation attestation")
    ingress_class = routing.get("ingress_class")
    gateway_class = routing.get("gateway_class")
    if ingress_class:
        ingress_class_doc = parse_json_bytes(run_checked(kube + ["get", "ingressclass", ingress_class, "-o", "json"], env), "IngressClass")
        if ingress_class_doc.get("metadata", {}).get("name") != ingress_class or not ingress_class_doc.get("spec", {}).get("controller"):
            fail("reviewed IngressClass is absent or has no controller owner")
    if gateway_class:
        gateway_class_doc = parse_json_bytes(run_checked(kube + ["get", "gatewayclass", gateway_class, "-o", "json"], env), "GatewayClass")
        accepted = any(item.get("type") == "Accepted" and item.get("status") == "True" for item in gateway_class_doc.get("status", {}).get("conditions", []) if isinstance(item, dict))
        if gateway_class_doc.get("metadata", {}).get("name") != gateway_class or not gateway_class_doc.get("spec", {}).get("controllerName") or not accepted:
            fail("reviewed GatewayClass is absent, unowned, or not Accepted")
    identities = {(item["kind"], item["name"]) for item in rendered["resources"]}

    ingresses = parse_json_bytes(run_checked(kube + ["get", "ingress", "--namespace", namespace, "-o", "json"], env), "live Ingresses")
    expected_hosts = {routing["console_host"], routing["api_host"], routing["grafana_host"]}
    expected_hosts.update(str(urlparse(route).hostname).lower() for route in routing["routes"])
    admitted_hosts: set[str] = set()
    admitted_addresses: set[str] = set()
    live_host_paths: dict[str, list[str]] = {}
    live_tls_bindings: set[tuple[str, str]] = set()
    live_resources: list[dict[str, str]] = []
    for ingress in ingresses.get("items", []):
        if not release_owned_resource(ingress, "Ingress", identities, release_names):
            continue
        live_resources.append({"kind": "Ingress", "name": str(ingress["metadata"]["name"]), "uid": str(ingress["metadata"]["uid"])})
        live_ingress_class = ingress.get("spec", {}).get("ingressClassName") or ingress.get("metadata", {}).get("annotations", {}).get("kubernetes.io/ingress.class")
        if ingress_class and live_ingress_class != ingress_class:
            continue
        addresses = ingress.get("status", {}).get("loadBalancer", {}).get("ingress", [])
        if not addresses:
            continue
        admitted_addresses.update(
            str(address.get("ip") or address.get("hostname"))
            for address in addresses
            if isinstance(address, dict) and (address.get("ip") or address.get("hostname"))
        )
        for rule in ingress.get("spec", {}).get("rules", []):
            if not isinstance(rule, dict) or not isinstance(rule.get("host"), str):
                continue
            host = rule["host"].lower()
            admitted_hosts.add(host)
            live_host_paths.setdefault(host, []).extend(
                path["path"]
                for path in rule.get("http", {}).get("paths", [])
                if isinstance(path, dict) and isinstance(path.get("path"), str)
            )
        for tls in ingress.get("spec", {}).get("tls", []):
            if isinstance(tls, dict) and isinstance(tls.get("secretName"), str):
                live_tls_bindings.update(
                    (str(host).lower(), tls["secretName"])
                    for host in tls.get("hosts", [])
                    if isinstance(host, str)
                )
    if ingress_class and not expected_hosts.issubset(admitted_hosts):
        fail("live Ingress routes are not admitted for all reviewed hosts")
    if ingress_class and admitted_addresses != set(routing["load_balancer_addresses"]):
        fail("live Ingress admission addresses differ from the exact reviewed LoadBalancer addresses")
    if gateway_class:
        gateways = parse_json_bytes(run_checked(kube + ["get", "gateway", "--namespace", namespace, "-o", "json"], env), "live Gateways")
        gateway_names = {
            item.get("metadata", {}).get("name")
            for item in gateways.get("items", [])
            if release_owned_resource(item, "Gateway", identities, release_names)
            and item.get("spec", {}).get("gatewayClassName") == gateway_class
            and all(
                any(condition.get("type") == condition_type and condition.get("status") == "True" for condition in item.get("status", {}).get("conditions", []) if isinstance(condition, dict))
                for condition_type in ("Accepted", "Programmed")
            )
        }
        if not gateway_names:
            fail("no live Accepted Gateway is owned by the reviewed GatewayClass")
        for item in gateways.get("items", []):
            if item.get("metadata", {}).get("name") in gateway_names:
                live_resources.append({"kind": "Gateway", "name": str(item["metadata"]["name"]), "uid": str(item["metadata"]["uid"])})
                for listener in item.get("spec", {}).get("listeners", []):
                    if not isinstance(listener, dict) or not isinstance(listener.get("hostname"), str):
                        continue
                    for reference in listener.get("tls", {}).get("certificateRefs", []):
                        if isinstance(reference, dict) and isinstance(reference.get("name"), str):
                            live_tls_bindings.add((listener["hostname"].lower(), reference["name"]))
        routes = parse_json_bytes(run_checked(kube + ["get", "httproute", "--namespace", namespace, "-o", "json"], env), "live HTTPRoutes")
        for route in routes.get("items", []):
            if not release_owned_resource(route, "HTTPRoute", identities, release_names):
                continue
            parents = route.get("status", {}).get("parents", [])
            accepted = any(
                parent.get("parentRef", {}).get("name") in gateway_names
                and all(
                    any(condition.get("type") == condition_type and condition.get("status") == "True" for condition in parent.get("conditions", []) if isinstance(condition, dict))
                    for condition_type in ("Accepted", "ResolvedRefs")
                )
                for parent in parents
                if isinstance(parent, dict)
            )
            if accepted:
                route_hosts = [str(host).lower() for host in route.get("spec", {}).get("hostnames", []) if isinstance(host, str)]
                admitted_hosts.update(route_hosts)
                for rule in route.get("spec", {}).get("rules", []):
                    for match in rule.get("matches", []) if isinstance(rule, dict) else []:
                        value = match.get("path", {}).get("value") if isinstance(match, dict) else None
                        if isinstance(value, str):
                            for host in route_hosts:
                                live_host_paths.setdefault(host, []).append(value)
                live_resources.append({"kind": "HTTPRoute", "name": str(route["metadata"]["name"]), "uid": str(route["metadata"]["uid"])})
        if not expected_hosts.issubset(admitted_hosts):
            fail("live HTTPRoutes are not Accepted for all reviewed hosts")
    if admitted_hosts != expected_hosts:
        fail("live admitted route host set differs from exact reviewed hosts")
    expected_host_paths = {host: paths for host, paths in rendered["host_paths"].items() if paths}
    if {host: paths for host, paths in sorted(live_host_paths.items()) if paths} != expected_host_paths:
        fail("live route host/path ordering differs from exact rendered routes")
    expected_tls_bindings = {(item["host"], item["secret"]) for item in rendered["tls_bindings"]}
    if live_tls_bindings != expected_tls_bindings:
        fail("live TLS host-to-Secret bindings differ from exact rendered routes")
    services = parse_json_bytes(run_checked(kube + ["get", "service", "--namespace", namespace, "-o", "json"], env), "live Services")
    expected_services = set(routing["load_balancer_services"])
    observed_addresses: set[str] = set()
    found_services: set[str] = set()
    for service in services.get("items", []):
        name = service.get("metadata", {}).get("name")
        if name not in expected_services or not release_owned_resource(service, "Service", identities, release_names):
            continue
        found_services.add(name)
        live_resources.append({"kind": "Service", "name": str(name), "uid": str(service["metadata"]["uid"])})
        if service.get("spec", {}).get("type") != "LoadBalancer":
            fail(f"reviewed routing Service {name} is not type LoadBalancer")
        for item in service.get("status", {}).get("loadBalancer", {}).get("ingress", []):
            if isinstance(item, dict):
                address = item.get("ip") or item.get("hostname")
                if isinstance(address, str):
                    observed_addresses.add(address)
    if found_services != expected_services:
        fail("live release-owned LoadBalancer Service set differs from the reviewed rendered contract")
    if expected_services and set(routing["load_balancer_addresses"]) != observed_addresses:
        fail("live release-owned LoadBalancer addresses differ from the reviewed routing contract")
    previous_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(5)
    try:
        dns_results = validate_dns_exact(routing)
    except OSError:
        fail("production routing DNS/LB resolution failed")
    finally:
        socket.setdefaulttimeout(previous_timeout)
    certificate_hosts = validate_tls_secret_certificates(kube, env, namespace, routing, temp, "live")
    live_identities = {(item["kind"], item["name"]) for item in live_resources}
    if live_identities != identities:
        fail("live release-owned routing object set differs from exact rendered identities")
    return {
        "services": sorted(found_services),
        "addresses": sorted(observed_addresses),
        "certificate_hosts_by_secret": certificate_hosts,
        "dns_answers": dns_results,
        "admitted_hosts": sorted(admitted_hosts),
        "dns_validated": True,
        "resources": sorted(live_resources, key=lambda item: (item["kind"], item["name"])),
    }


def image_evidence_charts(spec: dict[str, Any]) -> list[dict[str, str]]:
    charts = [{
        "name": "galileo-stack",
        "release": spec["stack"]["release_name"],
        "version": spec["stack"]["chart_version"],
        "sha256": spec["stack"]["chart_sha256"],
    }]
    if spec["galileoctl"]["enabled"]:
        charts.append({
            "name": "galileoctl",
            "release": spec["galileoctl"]["release_name"],
            "version": spec["galileoctl"]["chart_version"],
            "sha256": spec["galileoctl"]["chart_sha256"],
        })
    return charts


def validate_air_gap_contract(
    document: Any,
    spec: dict[str, Any],
    current_image_evidence: dict[str, Any] | None,
    nonsecret_inputs: dict[str, str] | None = None,
) -> None:
    """Validate the seed -> air-gap -> final Stack contract.

    The air-gap bundle is produced from a connected, non-mutating Stack
    preflight.  Its ``stack_seed`` preserves the exact render contract.  A
    final air-gap-enabled preflight must reproduce that contract byte-for-byte
    semantically (except for its new immutable bundle identity/timestamp).
    """
    contract = assert_mapping(document, "air-gap contract")
    if contract.get("schema") != "galileo-on-prem-air-gap-bundle/v1" or not SHA_RE.fullmatch(str(contract.get("bundle_sha256", ""))):
        fail("air-gap contract schema or bundle digest is invalid")
    charts = contract.get("charts")
    if not isinstance(charts, list):
        fail("air-gap contract chart inventory is invalid")
    matching = [item for item in charts if isinstance(item, dict) and item.get("name") == "galileo-stack"]
    if len(matching) != 1 or matching[0].get("version") != spec["stack"]["chart_version"] or matching[0].get("sha256") != spec["stack"]["chart_sha256"]:
        fail("air-gap contract does not bind the exact galileo-stack chart")
    if spec["galileoctl"]["enabled"]:
        ctl_matching = [item for item in charts if isinstance(item, dict) and item.get("name") == "galileoctl"]
        if len(ctl_matching) != 1 or ctl_matching[0].get("version") != spec["galileoctl"]["chart_version"] or ctl_matching[0].get("sha256") != spec["galileoctl"]["chart_sha256"]:
            fail("air-gap contract does not bind the exact galileoctl chart")
    seed = assert_mapping(contract.get("stack_seed"), "air-gap contract stack_seed")
    seed_fields = {
        "evidence_sha256", "source_bundle_sha256", "charts", "inputs",
        "redacted_render_sha256", "target", "items",
    }
    if set(seed) != seed_fields:
        fail("air-gap contract stack_seed fields differ from the exact contract")
    for key in ("evidence_sha256", "source_bundle_sha256", "redacted_render_sha256"):
        if not SHA_RE.fullmatch(str(seed.get(key, ""))):
            fail(f"air-gap contract stack_seed.{key} is invalid")
    if (
        seed["evidence_sha256"] != contract.get("stack_image_evidence_sha256")
        or seed["source_bundle_sha256"] != contract.get("stack_bundle_sha256")
    ):
        fail("air-gap contract seed hashes differ from its embedded canonical Stack evidence bindings")
    if seed.get("charts") != image_evidence_charts(spec):
        fail("air-gap contract seed does not bind the exact Stack release chart set")
    seed_inputs = assert_mapping(seed.get("inputs"), "air-gap contract stack_seed.inputs")
    expected_input_keys = {
        "stack_nonsecret_values_sha256", "stack_secret_contract_sha256",
        "galileoctl_nonsecret_values_sha256", "galileoctl_secret_contract_sha256",
    }
    if set(seed_inputs) != expected_input_keys:
        fail("air-gap contract seed input fields differ from the exact contract")
    for key, value in seed_inputs.items():
        if (key.startswith("galileoctl_") and not spec["galileoctl"]["enabled"]):
            if value != "":
                fail("air-gap contract seed unexpectedly binds disabled galileoctl values")
        elif not SHA_RE.fullmatch(str(value)):
            fail(f"air-gap contract seed input digest is invalid: {key}")
    if nonsecret_inputs is not None:
        for key in ("stack_nonsecret_values_sha256", "galileoctl_nonsecret_values_sha256"):
            if seed_inputs.get(key) != nonsecret_inputs.get(key):
                fail("final Stack non-secret values differ from the air-gap seed")
    target = assert_mapping(seed.get("target"), "air-gap contract stack_seed.target")
    expected_target_fields = {
        "context", "api_server", "ca_sha256", "kube_system_uid", "namespace", "namespace_uid",
    }
    if set(target) != expected_target_fields:
        fail("air-gap contract seed target fields differ from the exact contract")
    expected_static_target = {
        "context": spec["target"]["kube_context"],
        "api_server": spec["target"]["api_server"],
        "ca_sha256": spec["target"]["ca_sha256"],
        "kube_system_uid": spec["target"]["cluster_uid"],
        "namespace": spec["target"]["namespace"],
        "namespace_uid": spec["target"].get("namespace_uid") or "absent",
    }
    if target != expected_static_target:
        fail("air-gap contract seed target differs from the final reviewed target")
    seed_items = seed.get("items")
    if not isinstance(seed_items, list) or not seed_items:
        fail("air-gap contract seed image evidence is empty")
    seed_images: set[str] = set()
    seed_architectures: dict[str, set[str]] = {}
    for index, item_value in enumerate(seed_items):
        item = assert_mapping(item_value, f"air-gap contract stack_seed.items[{index}]")
        if set(item) != {
            "release", "source_object", "container_type", "container", "image",
            "digest", "eligible_architectures",
        }:
            fail("air-gap contract seed image row fields differ")
        image = item.get("image")
        digest = item.get("digest")
        eligible = item.get("eligible_architectures")
        if (
            not isinstance(image, str)
            or not isinstance(digest, str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
            or not image.endswith(f"@{digest}")
            or not isinstance(eligible, list)
            or not eligible
            or eligible != sorted(set(eligible))
            or any(value not in {"amd64", "arm64"} for value in eligible)
        ):
            fail("air-gap contract seed contains a non-digest-pinned image")
        seed_images.add(image)
        seed_architectures.setdefault(image, set()).update(eligible)

    images = contract.get("stack_images")
    if not isinstance(images, list) or not images:
        fail("air-gap contract Stack image inventory is empty")
    image_fields = {
        "source", "source_digest", "mirror", "mirror_digest", "archive_file",
        "archive_sha256", "architectures", "uses", "scan_attestation_file",
        "source_scan_attestation_sha256", "scan_attestation_sha256",
    }
    sources: set[str] = set()
    mirrors: set[str] = set()
    aggregate_rows = contract.get("images")
    if not isinstance(aggregate_rows, list):
        fail("air-gap aggregate image inventory is invalid")
    for index, item_value in enumerate(images):
        item = assert_mapping(item_value, f"air-gap contract stack_images[{index}]")
        if set(item) != image_fields:
            fail("air-gap contract Stack image row fields differ")
        source, source_digest = item.get("source"), item.get("source_digest")
        mirror, digest = item.get("mirror"), item.get("mirror_digest")
        if (
            not isinstance(source, str)
            or not source
            or not isinstance(source_digest, str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", source_digest)
            or not isinstance(mirror, str)
            or not mirror
            or not isinstance(digest, str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
            or source_digest != digest
            or source == mirror
        ):
            fail("air-gap contract mirror identity is invalid")
        for path_key, prefix in (("archive_file", "images/"), ("scan_attestation_file", "scans/")):
            path_value = item.get(path_key)
            path = PurePosixPath(path_value) if isinstance(path_value, str) else PurePosixPath("/")
            if (
                not isinstance(path_value, str)
                or not path_value.startswith(prefix)
                or path.is_absolute()
                or ".." in path.parts
                or "\\" in path_value
            ):
                fail(f"air-gap contract {path_key} is not a safe canonical relative path")
        for hash_key in (
            "archive_sha256", "source_scan_attestation_sha256", "scan_attestation_sha256",
        ):
            if not SHA_RE.fullmatch(str(item.get(hash_key, ""))):
                fail(f"air-gap contract {hash_key} is invalid")
        architectures = item.get("architectures")
        uses = item.get("uses")
        if (
            not isinstance(architectures, list)
            or not architectures
            or architectures != sorted(set(architectures))
            or any(value not in {"amd64", "arm64"} for value in architectures)
            or not isinstance(uses, list)
            or not uses
            or uses != sorted(set(uses))
            or any(not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._/:-]{1,240}", value) for value in uses)
        ):
            fail("air-gap contract architectures/uses are invalid")
        if item not in aggregate_rows:
            fail("air-gap Stack image row is absent from the exact aggregate image inventory")
        normalized_source = source if "@sha256:" in source else f"{source}@{source_digest}"
        if "@sha256:" in mirror and not mirror.endswith(f"@{digest}"):
            fail("air-gap mirror reference digest differs from mirror_digest")
        normalized = mirror if "@sha256:" in mirror else f"{mirror}@{digest}"
        if not seed_architectures.get(normalized, set()).issubset(set(architectures)):
            fail("air-gap image architectures do not cover every eligible Stack workload architecture")
        if normalized_source in sources or normalized in mirrors:
            fail("air-gap contract contains duplicate Stack source or mirror image identities")
        sources.add(normalized_source)
        mirrors.add(normalized)
    if mirrors != seed_images:
        fail("air-gap Stack mirrors do not exactly cover the canonical Stack seed render")
    if current_image_evidence is not None:
        current = assert_mapping(current_image_evidence, "current rendered image evidence")
        for key in ("charts", "inputs", "redacted_render_sha256", "target", "items"):
            if current.get(key) != seed.get(key):
                fail(f"final Stack render differs from air-gap seed field: {key}")
        current_images = {item["image"] for item in current["items"]}
        if current_images != mirrors:
            fail("final rendered image set differs from exact air-gap Stack mirrors")


def item_id(category: str, *parts: str) -> str:
    raw = ".".join((category,) + parts).lower()
    cleaned = ITEM_RE.sub("-", raw).strip("-.")
    return cleaned[:240] or f"{category}.unknown"


def component_classification(name: str) -> str:
    normalized = name.lower().replace("_", "-")
    direct = {
        "galileo-base": "stack.base", "api": "stack.api", "data-service": "stack.data-service",
        "ingest-service": "stack.ingest-service", "runners": "stack.runners", "runner": "stack.runners",
        "comet": "stack.comet", "authz": "stack.authz", "ui": "stack.ui",
        "postgres-v16": "data.postgresql", "postgresql": "data.postgresql", "redis": "data.redis",
        "clickhouse-operator": "data.clickhouse-operator", "clickhouse-keeper": "data.clickhouse-keeper",
        "clickhouse": "data.clickhouse", "rabbitmq-operator": "data.rabbitmq-operator",
        "rabbitmq-cluster": "data.rabbitmq-cluster", "messaging-topology-operator": "data.messaging-topology",
        "minio": "data.minio", "cert-manager": "routing.cert-manager", "galileo-tls": "routing.galileo-tls",
        "ingress-nginx": "routing.ingress-nginx", "envoy-gateway": "routing.envoy-gateway",
        "gateway-routes": "routing.gateway-routes", "ingress-resources": "routing.ingress-resources",
        "prometheus": "monitoring.prometheus", "grafana": "monitoring.grafana", "fluent-bit": "monitoring.fluent-bit",
        "prometheus-adapter": "monitoring.prometheus-adapter", "kube-state-metrics": "monitoring.kube-state-metrics",
        "alertmanager": "monitoring.alertmanager", "wizard": "wizard.service",
        "cluster-autoscaler": "autoscaling.cluster-autoscaler", "agent-control": "agent-control.deployment",
        "luna-studio": "luna.release", "galileoctl": "galileoctl.validation",
    }
    if normalized in direct:
        return direct[normalized]
    # Packaged dependency archives are commonly name-version.tgz. Strip only
    # a syntactically version-like suffix, then require an exact approved name.
    without_version = re.sub(r"-v?[0-9]+(?:\.[0-9A-Za-z]+)*(?:[-+][0-9A-Za-z.-]+)?$", "", normalized)
    return direct.get(without_version, "")


def source_component(source: str) -> str:
    parts = PurePosixPath(source).parts
    if "charts" in parts:
        indexes = [index for index, part in enumerate(parts) if part == "charts"]
        if indexes and indexes[-1] + 1 < len(parts):
            archive_name = parts[indexes[-1] + 1].split("!", 1)[0]
            return archive_name.removesuffix(".tgz").removesuffix(".tar.gz")
    if parts and parts[0] == "galileoctl":
        return "galileoctl"
    return "galileo-base"


def classification(category: str, name: str, source: str, kind: str = "") -> str:
    lower = f"{name} {source} {kind}".lower()
    component = source_component(source)
    component_id = component_classification(component)
    nested = component != "galileo-base"
    if nested and not component_id:
        return ""
    if category == "dependency":
        return component_classification(name)
    if category == "schema_or_enable_flag":
        if "disable_crds" in lower:
            return "crd.operator-templates"
        if "crd_management" in lower:
            return "crd.sequencing-hook"
        if "wizard" in lower or "gpu" in lower:
            return "wizard.service"
        return "install.values.questionnaire"
    if category == "crd":
        if "clickhouse" in lower:
            return "data.clickhouse-operator"
        if "rabbit" in lower or "messaging" in lower:
            return "data.rabbitmq-operator"
        if "cert-manager" in lower or "certificat" in lower:
            return "routing.cert-manager"
        return "crd.helm-directory"
    if category == "hook_or_migration":
        if "migrat" in lower or "alembic" in lower or "postgres" in lower:
            return "data.postgresql-migrations"
        if "sequenc" in lower or "crd" in lower:
            return "crd.sequencing-hook"
        return component_id or "stack.base"
    if category == "cluster_scoped_object":
        if "customresourcedefinition" in lower:
            return "crd.helm-directory"
        if "cert" in lower:
            return "routing.cert-manager"
        return component_id or "stack.base"
    if category == "service_or_route":
        if "httproute" in lower or "gateway" in lower:
            return "routing.gateway-routes"
        if "ingress" in lower:
            return "routing.ingress-resources"
        return component_id or "stack.base"
    if category == "persistence":
        return component_id if component_id.startswith("data.") else "production.storage"
    return component_id or "stack.base"


def combine_runtime_inventories(
    *inventories: dict[str, Any],
    feature_matrix: Path = FEATURE_MATRIX,
) -> dict[str, Any]:
    if not inventories:
        fail("runtime inventory union requires at least one chart")
    matrix = json.loads(secure_read(feature_matrix, "deployment feature matrix")[1])
    features = {item["id"]: item for item in matrix["features"]}
    combined: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    chart_hashes: list[str] = []
    for inventory in inventories:
        chart_hash = inventory.get("chart_sha256")
        if not isinstance(chart_hash, str) or not SHA_RE.fullmatch(chart_hash):
            fail("runtime inventory union found an invalid chart hash")
        chart_hashes.append(chart_hash)
        for item_value in inventory.get("items", []):
            item = assert_mapping(item_value, "runtime inventory item")
            identity = str(item.get("id", ""))
            if identity in seen_ids:
                suffix = 2
                while f"{identity}-{suffix}" in seen_ids:
                    suffix += 1
                item = dict(item, id=f"{identity}-{suffix}")
            classification_id = item.get("classification_id")
            if classification_id not in features or item.get("owners") != features[classification_id]["owners"]:
                fail("runtime inventory union found an unowned classification")
            seen_ids.add(str(item["id"]))
            combined.append(item)
    return {
        "schema_version": 1,
        "chart_sha256": sha256_bytes(json_bytes(sorted(chart_hashes))),
        "generated_by": "galileo-on-prem-stack-setup",
        "observed_categories": list(RUNTIME_CATEGORIES),
        "observed_empty_categories": {
            category: "No item of this category was present in the exact inspected enabled chart set."
            for category in RUNTIME_CATEGORIES
            if not any(item["category"] == category for item in combined)
        },
        "items": sorted(combined, key=lambda item: item["id"]),
    }


def unbound_helm_action_reason(action: str) -> str:
    # Any alias of the root context, or reflection into an aliased/root value,
    # can recover Release/Capabilities without a direct token. The handoff
    # render must remain reproducible, so these forms are never accepted.
    if re.search(r"\$[A-Za-z_][A-Za-z0-9_]*\s*:?=\s*[.$](?:\s|$)", action):
        return "aliased Helm root context"
    if re.search(r"(?<![A-Za-z0-9_.])(?:index|dig|get|hasKey|pluck|pick|omit|deepCopy|merge|mergeOverwrite)(?=\s|\()", action):
        return "reflective Helm context access"
    if re.search(r"(?<![A-Za-z0-9_.])(?:with|range)\s+[.$](?:\s|$)", action):
        return "unbounded Helm root traversal"
    if re.search(r"(?<![A-Za-z0-9_.])lookup(?=\s|\()", action):
        return "Helm lookup"
    if ".Capabilities" in action:
        return ".Capabilities."
    if ".Release" in action:
        scrubbed = re.sub(r"\.Release\.(?:Name|Namespace|Service)\b", "", action)
        if ".Release" in scrubbed:
            return "unreviewed or aliased .Release field"
        # Even safe direct fields may not be captured/aliased/indexed or used
        # as a function/pipeline subject. Allow only ordinary output/value
        # positions with simple formatting functions.
        if re.search(r"(?:\$\w+\s*:=|index\s+|with\s+|range\s+|\bset\s+).*\.Release|\.Release\.(?:Name|Namespace|Service)\s*\|", action):
            return "aliased/pipelined .Release field"
    for function in (
        "bcrypt", "encryptAES", "genCA", "genPrivateKey", "genSelfSignedCert",
        "genSignedCert", "htpasswd", "now", "randAlpha", "randAlphaNum",
        "randAscii", "randBytes", "randNumeric", "randInt", "derivePassword",
        "shuffle", "getHostByName", "uuidv4",
    ):
        if re.search(rf"(?<![A-Za-z0-9_.]){re.escape(function)}(?=\s|\()", action):
            return f"nondeterministic Helm function {function}"
    return ""


def reject_unbound_helm_value_actions(value: Any, source: str) -> None:
    if isinstance(value, str):
        for action in re.finditer(r"{{-?(.*?)-?}}", value, re.DOTALL):
            reason = unbound_helm_action_reason(action.group(1))
            if reason:
                fail(f"automated lifecycle rejects {reason} in values: {source}")
    elif isinstance(value, dict):
        for key, child in value.items():
            reject_unbound_helm_value_actions(child, f"{source}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_unbound_helm_value_actions(child, f"{source}[{index}]")


def reject_cluster_dependent_helm_templates(files: list[tuple[str, bytes]]) -> None:
    """Reject Helm templates whose output is not preflight-reproducible.

    The lifecycle binds the exact client-side render before mutation. Helm's
    live discovery/release-state surfaces and random generators would let the
    real install/upgrade render differ and bypass bound resource, image,
    endpoint, and Secret-derived inventories. Scan every recursively unpacked
    file under every chart's templates directory, including helpers and NOTES.
    Apparent uses in template comments intentionally fail closed.
    """
    for source, body in files:
        if "/templates/" not in f"/{source}":
            continue
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            fail(f"Helm template is not valid UTF-8: {source}")
        for action in re.finditer(r"{{-?(.*?)-?}}", text, re.DOTALL):
            reason = unbound_helm_action_reason(action.group(1))
            if reason:
                fail(
                    f"automated lifecycle rejects {reason} because the live mutation render "
                    f"could differ from bound preflight evidence: {source}"
                )
            if re.search(r"(?<![A-Za-z0-9_.])tpl(?=\s|\()", action.group(1)):
                fail(
                    "automated lifecycle rejects Helm tpl because dynamically evaluated content "
                    f"cannot be proven free of unbound actions: {source}"
                )


def inspect_chart(
    path: Path,
    expected_sha: str,
    expected_version: str,
    expected_name: str,
    feature_matrix: Path = FEATURE_MATRIX,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _, raw, _ = secure_read(path, f"{expected_name} chart archive")
    actual_sha = sha256_bytes(raw)
    if actual_sha != expected_sha:
        fail(f"{expected_name} chart SHA-256 does not match the deployment spec")
    root_members = safe_tar_members(raw, expected_name)
    chart_yaml = [(name, body) for name, body in root_members if name.endswith("/Chart.yaml") and "/charts/" not in name]
    if len(chart_yaml) != 1:
        fail(f"{expected_name} archive must have exactly one top-level Chart.yaml")
    try:
        chart = assert_mapping(strict_yaml_load(chart_yaml[0][1]), f"{expected_name} Chart.yaml")
    except yaml.YAMLError:
        fail(f"{expected_name} Chart.yaml is invalid")
    if chart.get("name") != expected_name:
        fail(f"chart name is {chart.get('name')!r}, expected {expected_name!r}")
    if str(chart.get("version", "")) != expected_version:
        fail(f"chart version is {chart.get('version')!r}, expected {expected_version!r}")

    files: list[tuple[str, bytes]] = list(root_members)
    archive_queue: list[tuple[str, bytes, int]] = [
        (member_name, body, 1)
        for member_name, body in root_members
        if member_name.endswith((".tgz", ".tar.gz")) and "/charts/" in member_name
    ]
    inspected_bytes = sum(len(body) for _, body in root_members)
    while archive_queue:
        member_name, body, depth = archive_queue.pop(0)
        if depth > 8:
            fail("nested chart archive depth exceeds the safe inspection limit")
        for nested_name, nested_body in safe_tar_members(body, member_name):
            source = f"{member_name}!/{nested_name}"
            files.append((source, nested_body))
            inspected_bytes += len(nested_body)
            if len(files) > 50000 or inspected_bytes > 1024 * 1024 * 1024:
                fail("recursive chart inspection exceeds safe file/byte limits")
            if nested_name.endswith((".tgz", ".tar.gz")) and "/charts/" in nested_name:
                archive_queue.append((source, nested_body, depth + 1))

    reject_cluster_dependent_helm_templates(files)

    matrix = json.loads(secure_read(feature_matrix, "deployment feature matrix")[1])
    features = {item["id"]: item for item in matrix["features"]}
    found: dict[str, dict[str, Any]] = {}

    def add(category: str, name: str, source: str, kind: str = "") -> None:
        identity = item_id(category, source, name)
        suffix = 2
        candidate = identity
        while candidate in found:
            candidate = f"{identity}-{suffix}"
            suffix += 1
        class_id = classification(category, name, source, kind)
        if class_id not in features:
            fail(f"runtime inventory item {candidate} has no reviewed classification")
        found[candidate] = {
            "id": candidate,
            "category": category,
            "classification_id": class_id,
            "owners": features[class_id]["owners"],
            "source_ref": source,
        }

    chart_documents: list[tuple[str, dict[str, Any]]] = []
    for source, body in files:
        if not source.endswith("/Chart.yaml"):
            continue
        try:
            chart_document = assert_mapping(strict_yaml_load(body), f"Chart.yaml {source}")
        except yaml.YAMLError:
            fail(f"invalid Chart.yaml in {source}")
        nested_name = chart_document.get("name")
        if not isinstance(nested_name, str) or not nested_name:
            fail(f"Chart.yaml has no exact name in {source}")
        if source != chart_yaml[0][0] and not component_classification(nested_name):
            fail(f"nested chart {nested_name!r} has no reviewed exact component classification")
        chart_documents.append((source, chart_document))

    dependencies: list[dict[str, Any]] = []
    for source, chart_document in chart_documents:
        chart_dependencies = chart_document.get("dependencies") or []
        if not isinstance(chart_dependencies, list):
            fail(f"Chart.yaml dependencies must be a list in {source}")
        for dep in chart_dependencies:
            if not isinstance(dep, dict) or not isinstance(dep.get("name"), str) or not dep["name"]:
                fail(f"Chart.yaml dependency lacks an exact name in {source}")
            dependencies.append(dep)
            add("dependency", dep["name"], source)

    kinds: set[str] = set()
    images: set[str] = set()
    crds: set[str] = set()
    hooks: set[str] = set()
    pvcs: set[str] = set()
    routes: set[str] = set()
    components = {str(dep["name"]) for dep in dependencies}
    for source, body in files:
        if len(body) > 20 * 1024 * 1024:
            continue
        text = body.decode("utf-8", errors="replace")
        lower_source = source.lower()
        if source.endswith("values.schema.json"):
            try:
                schema = json.loads(text)
            except json.JSONDecodeError:
                fail(f"invalid values schema in {source}")

            def schema_walk(node: Any, trail: tuple[str, ...] = ()) -> None:
                if not isinstance(node, dict):
                    return
                props = node.get("properties")
                if isinstance(props, dict):
                    for key, child in props.items():
                        next_trail = trail + (str(key),)
                        if re.search(r"enabled|disable|image|storage|route|ingress|gateway|wizard|gpu|provider", str(key), re.I):
                            add("schema_or_enable_flag", ".".join(next_trail), source)
                        schema_walk(child, next_trail)
            schema_walk(schema)
        values_name = PurePosixPath(source.split("!/", 1)[-1]).name.lower()
        if values_name.endswith((".yaml", ".yml")) and values_name.startswith(("values", "example-values")):
            try:
                values_document = strict_yaml_load(text)
            except yaml.YAMLError:
                fail(f"invalid values YAML in {source}")
            if values_document is not None and not isinstance(values_document, dict):
                fail(f"values YAML root must be a mapping in {source}")
            reject_unbound_helm_value_actions(values_document, source)
            pending: list[tuple[tuple[str, ...], Any]] = [((), values_document or {})]
            visited = 0
            while pending:
                trail, node = pending.pop()
                visited += 1
                if visited > 100000:
                    fail(f"values YAML exceeds safe inspection limit in {source}")
                if isinstance(node, dict):
                    for raw_key, child in node.items():
                        key = str(raw_key)
                        next_trail = trail + (key,)
                        if re.search(
                            r"enabled|enable|disable|image|repository|tag|digest|storage|route|ingress|gateway|wizard|gpu|provider|className|persistence|tls|autoscal",
                            key,
                            re.I,
                        ):
                            add("schema_or_enable_flag", ".".join(next_trail), source)
                        if key.lower() == "image" and isinstance(child, str) and child:
                            add("image", f"values:{'.'.join(next_trail)}={child}", source)
                        if key.lower() == "image" and isinstance(child, dict):
                            repository = child.get("repository")
                            digest = child.get("digest")
                            tag = child.get("tag")
                            if isinstance(repository, str) and repository:
                                suffix = f"@{digest}" if isinstance(digest, str) and digest else (f":{tag}" if isinstance(tag, str) and tag else "")
                                add("image", f"values:{'.'.join(next_trail)}={repository}{suffix}", source)
                        pending.append((next_trail, child))
                elif isinstance(node, list):
                    pending.extend((trail + (str(index),), child) for index, child in enumerate(node))
        if not ("/templates/" in source or "/crds/" in source or source.endswith(("values.yaml", "example-values.yaml"))):
            continue
        for match in re.finditer(r"(?m)^\s*kind:\s*[\"']?([A-Za-z][A-Za-z0-9.]*)", text):
            kind = match.group(1)
            kinds.add(kind)
            add("api_kind", kind, source, kind)
            if kind in CLUSTER_KINDS:
                add("cluster_scoped_object", kind, source, kind)
            if kind in {"Service", "Ingress", "HTTPRoute", "Gateway"}:
                routes.add(f"{kind}:{source}")
                add("service_or_route", kind, source, kind)
            if kind in {"PersistentVolumeClaim", "StatefulSet"}:
                pvcs.add(f"{kind}:{source}")
                add("persistence", kind, source, kind)
        for match in re.finditer(r"(?m)^\s*image:\s*[\"']?([^\s\"']+)", text):
            image = match.group(1)
            if image.startswith("{{"):
                image = f"templated:{source}:{match.start()}"
            if image not in images:
                images.add(image)
                add("image", image, source)
        if "/crds/" in source and re.search(r"kind:\s*CustomResourceDefinition", text):
            name_match = re.search(r"(?ms)kind:\s*CustomResourceDefinition.*?\n\s*name:\s*([^\s]+)", text)
            crd_name = name_match.group(1) if name_match else source
            crds.add(crd_name)
            add("crd", crd_name, source, "CustomResourceDefinition")
        if "helm.sh/hook" in text or re.search(r"migrat|alembic|sequenc", lower_source):
            hooks.add(source)
            add("hook_or_migration", PurePosixPath(source).name, source)

    inventory = {
        "schema_version": 1,
        "chart_sha256": actual_sha,
        "generated_by": "galileo-on-prem-stack-setup",
        "observed_categories": list(RUNTIME_CATEGORIES),
        "observed_empty_categories": {
            category: "No item of this category was present in the exact inspected chart archive."
            for category in RUNTIME_CATEGORIES
            if not any(item["category"] == category for item in found.values())
        },
        "items": sorted(found.values(), key=lambda item: item["id"]),
    }
    report = {
        "chart": {"name": chart["name"], "version": str(chart["version"]), "sha256": actual_sha, "kubeVersion": chart.get("kubeVersion", "")},
        "dependencies": sorted(components),
        "api_kinds": sorted(kinds),
        "images": sorted(images),
        "crds": sorted(crds),
        "hooks_or_migrations": sorted(hooks),
        "persistence": sorted(pvcs),
        "routes": sorted(routes),
    }
    return report, inventory


def write_private(path: Path, data: bytes, mode: int = 0o600) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, mode)
    try:
        view = memoryview(data)
        written = 0
        while written < len(view):
            count = os.write(descriptor, view[written:])
            if count <= 0:
                fail(f"short write while creating private artifact {path.name}")
            written += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def ensure_private_directory(path: Path, anchor: Path) -> None:
    anchor_info = anchor.lstat()
    if stat.S_ISLNK(anchor_info.st_mode) or not stat.S_ISDIR(anchor_info.st_mode) or anchor_info.st_uid != os.getuid() or stat.S_IMODE(anchor_info.st_mode) != 0o700:
        fail("private state anchor must be current-user-owned, real, and mode 0700")
    try:
        relative = path.relative_to(anchor)
    except ValueError:
        fail("private state path escaped its anchor")
    current = anchor
    for part in relative.parts:
        current = current / part
        try:
            current.mkdir(mode=0o700)
        except FileExistsError:
            pass
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            fail("private state directory is unsafe")


def commit_evidence_generation(
    state_dir: Path,
    bundle_sha256: str,
    created_at: str,
    artifacts: tuple[tuple[str, bytes], ...],
) -> tuple[str, Path]:
    """Atomically commit one immutable, manifest-bound evidence generation."""
    names = [name for name, _ in artifacts]
    if len(names) != len(set(names)) or any(
        PurePosixPath(name).name != name or name.startswith(".") for name in names
    ):
        fail("evidence generation artifact names are invalid or duplicated")
    files = [
        {"path": name, "sha256": sha256_bytes(body), "size": len(body)}
        for name, body in sorted(artifacts)
    ]
    base_manifest = {
        "schema": "galileo-on-prem-stack-evidence-generation/v1",
        "bundle_sha256": bundle_sha256,
        "created_at": created_at,
        "files": files,
    }
    generation_id = sha256_bytes(json_bytes(base_manifest))
    generation_manifest = {
        **base_manifest,
        "generation_id": generation_id,
    }
    generation_manifest_bytes = json_bytes(generation_manifest)
    generations_dir = state_dir / "generations"
    ensure_private_directory(generations_dir, state_dir.parent.parent)
    pending = Path(
        tempfile.mkdtemp(prefix=".pending-", dir=generations_dir)
    )
    os.chmod(pending, 0o700)
    final = generations_dir / generation_id
    try:
        for name, body in artifacts:
            write_private(pending / name, body)
        write_private(pending / "generation-manifest.json", generation_manifest_bytes)
        directory_fd = os.open(pending, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        if final.exists():
            fail("evidence generation identifier collision")
        os.replace(pending, final)
        generations_fd = os.open(
            generations_dir, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        )
        try:
            os.fsync(generations_fd)
        finally:
            os.close(generations_fd)
        pointer = {
            "schema": "galileo-on-prem-stack-evidence-pointer/v1",
            "generation_id": generation_id,
            "generation_manifest_sha256": sha256_bytes(generation_manifest_bytes),
        }
        pointer_temp = state_dir / f".current-{generation_id}.tmp"
        write_private(pointer_temp, json_bytes(pointer))
        os.replace(pointer_temp, state_dir / "current.json")
        state_fd = os.open(state_dir, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(state_fd)
        finally:
            os.close(state_fd)
    except Exception:
        if pending.exists():
            shutil.rmtree(pending)
        raise
    return generation_id, final


def verified_evidence_generation(
    state_dir: Path,
    generation_id: str,
    bundle_sha256: str,
) -> Path:
    if not SHA_RE.fullmatch(generation_id):
        fail("--evidence-generation must be a lowercase SHA-256 generation ID")
    generation = state_dir / "generations" / generation_id
    manifest_raw = secure_read(
        generation / "generation-manifest.json",
        "evidence generation manifest",
        private=True,
    )[1]
    try:
        manifest = assert_mapping(json.loads(manifest_raw), "evidence generation manifest")
    except json.JSONDecodeError:
        fail("evidence generation manifest is invalid JSON")
    if (
        manifest_raw != json_bytes(manifest)
        or set(manifest) != {
            "schema", "bundle_sha256", "created_at", "files", "generation_id"
        }
        or manifest.get("schema") != "galileo-on-prem-stack-evidence-generation/v1"
        or manifest.get("bundle_sha256") != bundle_sha256
        or manifest.get("generation_id") != generation_id
    ):
        fail("evidence generation manifest binding differs")
    created_at = manifest.get("created_at")
    if not isinstance(created_at, str):
        fail("evidence generation created_at must be an RFC3339 string")
    parse_time(created_at, "evidence generation created_at")
    if not SHA_RE.fullmatch(str(manifest.get("bundle_sha256", ""))):
        fail("evidence generation bundle digest is invalid")
    file_rows = assert_list(manifest.get("files"), "evidence generation files")
    expected_files = {"generation-manifest.json"}
    seen_names: set[str] = set()
    normalized_rows: list[dict[str, Any]] = []
    for row_value in file_rows:
        row = assert_mapping(row_value, "evidence generation file")
        if set(row) != {"path", "sha256", "size"}:
            fail("evidence generation file record fields differ")
        name = row.get("path")
        if (
            not isinstance(name, str)
            or PurePosixPath(name).name != name
            or name.startswith(".")
            or name == "generation-manifest.json"
            or name in seen_names
        ):
            fail("evidence generation file path is invalid")
        if not SHA_RE.fullmatch(str(row.get("sha256", ""))):
            fail("evidence generation file digest is invalid")
        size = row.get("size")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            fail("evidence generation file size is invalid")
        seen_names.add(name)
        raw = secure_read(generation / name, f"evidence generation {name}", private=True)[1]
        if sha256_bytes(raw) != row.get("sha256") or len(raw) != size:
            fail(f"evidence generation artifact differs: {name}")
        expected_files.add(name)
        normalized_rows.append({"path": name, "sha256": row["sha256"], "size": size})
    if normalized_rows != sorted(normalized_rows, key=lambda row: row["path"]):
        fail("evidence generation file records are not canonically ordered")
    base_manifest = {
        "schema": manifest["schema"],
        "bundle_sha256": manifest["bundle_sha256"],
        "created_at": created_at,
        "files": normalized_rows,
    }
    if sha256_bytes(json_bytes(base_manifest)) != generation_id:
        fail("evidence generation ID differs from its canonical manifest")
    generation_info = generation.lstat()
    if (
        stat.S_ISLNK(generation_info.st_mode)
        or not stat.S_ISDIR(generation_info.st_mode)
        or generation_info.st_uid != os.getuid()
        or stat.S_IMODE(generation_info.st_mode) != 0o700
    ):
        fail("evidence generation directory is unsafe")
    actual_entries = {path.name for path in generation.iterdir()}
    if actual_entries != expected_files:
        fail("evidence generation contains missing or extra files")
    return generation


def verified_current_evidence_generation(
    state_dir: Path,
    bundle_sha256: str,
) -> tuple[str, Path]:
    """Resolve the atomic current pointer and bind its exact manifest bytes."""
    pointer_raw = secure_read(
        state_dir / "current.json",
        "current evidence generation pointer",
        private=True,
    )[1]
    try:
        pointer = assert_mapping(json.loads(pointer_raw), "current evidence generation pointer")
    except json.JSONDecodeError:
        fail("current evidence generation pointer is invalid JSON")
    if (
        pointer_raw != json_bytes(pointer)
        or set(pointer) != {
            "schema",
            "generation_id",
            "generation_manifest_sha256",
        }
        or pointer.get("schema") != "galileo-on-prem-stack-evidence-pointer/v1"
        or not SHA_RE.fullmatch(str(pointer.get("generation_id", "")))
        or not SHA_RE.fullmatch(str(pointer.get("generation_manifest_sha256", "")))
    ):
        fail("current evidence generation pointer binding differs")
    generation_id = str(pointer["generation_id"])
    generation = verified_evidence_generation(state_dir, generation_id, bundle_sha256)
    manifest_raw = secure_read(
        generation / "generation-manifest.json",
        "current evidence generation manifest",
        private=True,
    )[1]
    if sha256_bytes(manifest_raw) != pointer["generation_manifest_sha256"]:
        fail("current evidence generation pointer manifest digest differs")
    return generation_id, generation


def bundle_digest(root: Path) -> tuple[str, list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if relative == "bundle-manifest.json" or path.is_dir():
            continue
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            fail(f"unsafe file in bundle staging area: {relative}")
        records.append({"path": relative, "sha256": sha256_file(path), "mode": f"{stat.S_IMODE(info.st_mode):04o}"})
    digest = sha256_bytes(json_bytes(records))
    return digest, records


def canonical_apply_plan(spec: dict[str, Any], retention_sha: str) -> dict[str, Any]:
    method = spec["installation_method"]
    staged_routing = (
        spec["environment"] == "production"
        and spec["routing"]["load_balancer_lifecycle"] == "release-managed-staged-handoff"
    )
    return {
        "schema_version": 1,
        "state": "rendered",
        "deployment_id": spec["deployment_id"],
        "environment": spec["environment"],
        "deployment_spec_sha256": sha256_bytes(yaml_bytes(spec)),
        "crd_mode": spec["crds"]["mode"],
        "release": spec["stack"]["release_name"],
        "namespace": spec["target"]["namespace"],
        "method": method,
        "automated_by_this_skill": False,
        "candidate_for_automation": False,
        "operator_handoff": (
            "Use galileoctl UI for first install; use its CLI workstation/CI alternative only with exact current-release Galileo/CSE authorization."
            if method == "galileoctl"
            else (
                "Stage and validate the release-managed LoadBalancer, DNS, and TLS through a jointly reviewed manual handoff."
                if staged_routing
                else "Use the exact render and connected preflight evidence in a Galileo/CSE joint-session handoff; this skill performs no Helm or Kubernetes mutation."
            )
        ),
        "secret_values_rendered": False,
        "automatic_rollback": False,
        "retention_post_renderer_sha256": retention_sha,
        "next_action": "review runtime-inventory.json, bind coverage lists, rerender, preflight, then execute through the reviewed Galileo/CSE handoff",
    }


def inspect_chart_action(spec_path: Path, cli_console: str, output: Path) -> dict[str, Any]:
    """Emit review inventory only; never create a deployable lifecycle bundle."""
    spec = load_spec(spec_path, cli_console)
    stack = spec["stack"]
    stack_chart = safe_input_file(stack["chart_archive"], "spec.stack.chart_archive")
    stack_values = safe_input_file(stack["nonsecret_values_file"], "spec.stack.nonsecret_values_file")
    values = validate_values_no_secrets(stack_values)
    if spec["crds"]["mode"] == "shared" and not shared_crd_controls(values):
        fail("shared CRD review requires all four explicit CRD controls")
    stack_report, runtime_inventory = inspect_chart(
        stack_chart, stack["chart_sha256"], stack["chart_version"], "galileo-stack"
    )
    ctl_report: dict[str, Any] | None = None
    ctl_inventory: dict[str, Any] | None = None
    ctl = spec["galileoctl"]
    if ctl["enabled"]:
        ctl_chart = safe_input_file(ctl["chart_archive"], "spec.galileoctl.chart_archive")
        validate_values_no_secrets(safe_input_file(ctl["nonsecret_values_file"], "spec.galileoctl.nonsecret_values_file"))
        ctl_report, ctl_inventory = inspect_chart(ctl_chart, ctl["chart_sha256"], ctl["chart_version"], "galileoctl")
        runtime_inventory = combine_runtime_inventories(runtime_inventory, ctl_inventory)
    output = lexical_absolute(output)
    probe = output
    while not probe.exists():
        probe = probe.parent
    reject_symlink_ancestors(probe / "sentinel", "output directory")
    probe_info = probe.lstat()
    if stat.S_ISLNK(probe_info.st_mode) or not stat.S_ISDIR(probe_info.st_mode) or probe_info.st_uid != os.getuid():
        fail("output directory ancestor must be a current-user-owned real directory")
    root = output / spec["deployment_id"] / "inventory"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(output / spec["deployment_id"], 0o700)
    os.chmod(root, 0o700)
    destination = root / stack["chart_sha256"]
    if destination.exists():
        fail("inventory destination already exists; review it or use a new private output root")
    with tempfile.TemporaryDirectory(prefix=".galileo-stack-inspect-", dir=root) as temp_name:
        temp = Path(temp_name)
        os.chmod(temp, 0o700)
        write_private(temp / "runtime-inventory.json", json_bytes(runtime_inventory))
        write_private(temp / "chart-inventory.json", json_bytes({"stack": stack_report, "galileoctl": ctl_report}))
        coverage_template = {
            "enforce_runtime_inventory": True,
            "reviewed_components": sorted(item["id"] for item in runtime_inventory["items"] if item["category"] == "dependency"),
            "reviewed_schema_or_enable_flags": sorted(item["id"] for item in runtime_inventory["items"] if item["category"] == "schema_or_enable_flag"),
            "reviewed_kinds": sorted(item["id"] for item in runtime_inventory["items"] if item["category"] == "api_kind"),
            "reviewed_images": sorted(item["id"] for item in runtime_inventory["items"] if item["category"] == "image"),
            "reviewed_crds": sorted(item["id"] for item in runtime_inventory["items"] if item["category"] == "crd"),
            "reviewed_hooks": sorted(item["id"] for item in runtime_inventory["items"] if item["category"] == "hook_or_migration"),
            "reviewed_cluster_scoped_kinds": sorted(item["id"] for item in runtime_inventory["items"] if item["category"] == "cluster_scoped_object"),
            "reviewed_pvcs": sorted(item["id"] for item in runtime_inventory["items"] if item["category"] == "persistence"),
            "reviewed_routes": sorted(item["id"] for item in runtime_inventory["items"] if item["category"] == "service_or_route"),
        }
        write_private(temp / "coverage-review.yaml", yaml_bytes(coverage_template))
        os.rename(temp, destination)
        os.chmod(destination, 0o700)
    return {
        "action": "inspect-chart",
        "state": "coverage-review-required",
        "deployable": False,
        "inventory": str(destination / "runtime-inventory.json"),
        "coverage_review": str(destination / "coverage-review.yaml"),
    }


def render(spec_path: Path, cli_console: str, output: Path) -> dict[str, Any]:
    spec = load_spec(spec_path, cli_console)
    stack = spec["stack"]
    source_chart = safe_input_file(stack["chart_archive"], "spec.stack.chart_archive")
    source_values = safe_input_file(stack["nonsecret_values_file"], "spec.stack.nonsecret_values_file")
    values = validate_values_no_secrets(source_values)
    if spec["crds"]["mode"] == "shared" and not shared_crd_controls(values):
        fail("shared CRD review requires all four explicit CRD controls plus the handoff --skip-crds command")
    chart_report, runtime_inventory = inspect_chart(
        source_chart, stack["chart_sha256"].lower(), stack["chart_version"], "galileo-stack"
    )

    retention_helper = safe_input_file(str(RETENTION_HELPER), "retention post-renderer")
    retention_sha = sha256_file(retention_helper)
    ctl_sources: dict[str, Path] = {}
    ctl_report: dict[str, Any] | None = None
    ctl_inventory: dict[str, Any] | None = None
    ctl = spec["galileoctl"]
    if ctl.get("enabled") is True:
        ctl_sources["chart"] = safe_input_file(ctl["chart_archive"], "spec.galileoctl.chart_archive")
        ctl_sources["values"] = safe_input_file(ctl["nonsecret_values_file"], "spec.galileoctl.nonsecret_values_file")
        validate_values_no_secrets(ctl_sources["values"])
        ctl_report, ctl_inventory = inspect_chart(
            ctl_sources["chart"], ctl["chart_sha256"].lower(), ctl["chart_version"], "galileoctl"
        )
        runtime_inventory = combine_runtime_inventories(runtime_inventory, ctl_inventory)
    compare_coverage(spec, runtime_inventory)

    air_gap_contract_bytes: bytes | None = None
    if spec["air_gap"].get("enabled"):
        air_gap_path = safe_input_file(spec["air_gap"]["verified_contract_file"], "spec.air_gap.verified_contract_file")
        air_gap_contract_bytes = secure_read(air_gap_path, "air-gap contract")[1]
        if sha256_bytes(air_gap_contract_bytes) != spec["air_gap"]["verified_contract_sha256"]:
            fail("air-gap contract SHA-256 does not match the deployment spec")
        try:
            contract_document = json.loads(air_gap_contract_bytes)
        except json.JSONDecodeError:
            fail("air-gap contract must be JSON")
        validate_air_gap_contract(
            contract_document,
            spec,
            None,
            {
                "stack_nonsecret_values_sha256": sha256_file(source_values),
                "galileoctl_nonsecret_values_sha256": (
                    sha256_file(ctl_sources["values"]) if ctl_sources else ""
                ),
            },
        )
    normalized = copy.deepcopy(spec)
    normalized["stack"]["chart_archive"] = "artifacts/galileo-stack.tgz"
    normalized["stack"]["nonsecret_values_file"] = "values/stack-values.yaml"
    if ctl_sources:
        normalized["galileoctl"]["chart_archive"] = "artifacts/galileoctl.tgz"
        normalized["galileoctl"]["nonsecret_values_file"] = "values/galileoctl-values.yaml"
    if air_gap_contract_bytes is not None:
        normalized["air_gap"]["verified_contract_file"] = "contracts/air-gap-metadata.json"

    output = lexical_absolute(output)
    # Existing ancestors must be real directories; do not render through a
    # symlinked output path.
    probe = output
    while not probe.exists():
        probe = probe.parent
    reject_symlink_ancestors(probe / "sentinel", "output directory")
    probe_info = probe.lstat()
    if stat.S_ISLNK(probe_info.st_mode) or not stat.S_ISDIR(probe_info.st_mode) or probe_info.st_uid != os.getuid():
        fail("output directory ancestor must be a current-user-owned real directory")
    deployment_root = output / spec["deployment_id"]
    deployment_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root_info = deployment_root.lstat()
    if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode) or root_info.st_uid != os.getuid():
        fail("deployment output root must be a current-user-owned non-symlink directory")
    os.chmod(deployment_root, 0o700)
    with tempfile.TemporaryDirectory(prefix=".galileo-stack-render-", dir=deployment_root) as temp_name:
        temp = Path(temp_name)
        os.chmod(temp, 0o700)
        (temp / "artifacts").mkdir(mode=0o700)
        (temp / "values").mkdir(mode=0o700)
        (temp / "helpers").mkdir(mode=0o700)
        (temp / "contracts").mkdir(mode=0o700)
        write_private(temp / "deployment-spec.yaml", yaml_bytes(normalized))
        write_private(temp / "chart-inventory.json", json_bytes({"stack": chart_report, "galileoctl": ctl_report}))
        write_private(temp / "runtime-inventory.json", json_bytes(runtime_inventory))
        write_private(
            temp / "contracts" / "deployment-feature-matrix.json",
            secure_read(FEATURE_MATRIX, "Stack feature matrix")[1],
        )
        if air_gap_contract_bytes is not None:
            write_private(temp / "contracts" / "air-gap-metadata.json", air_gap_contract_bytes)
        write_private(temp / "apply-plan.json", json_bytes(canonical_apply_plan(normalized, retention_sha)))
        write_private(temp / "artifacts" / "galileo-stack.tgz", secure_read(source_chart, "stack chart archive")[1])
        write_private(temp / "values" / "stack-values.yaml", secure_read(source_values, "stack non-secret values")[1])
        write_private(temp / "helpers" / "retain_resources.py", secure_read(retention_helper, "retention post-renderer")[1], mode=0o700)
        if sha256_file(temp / "artifacts" / "galileo-stack.tgz") != stack["chart_sha256"].lower():
            fail("stack chart changed while rendering")
        copied_values = validate_values_no_secrets(temp / "values" / "stack-values.yaml")
        if spec["crds"]["mode"] == "shared" and not shared_crd_controls(copied_values):
            fail("Stack values changed while rendering shared CRD controls")
        if sha256_file(temp / "helpers" / "retain_resources.py") != retention_sha:
            fail("retention post-renderer changed while rendering")
        if ctl_sources:
            write_private(temp / "artifacts" / "galileoctl.tgz", secure_read(ctl_sources["chart"], "galileoctl chart archive")[1])
            write_private(temp / "values" / "galileoctl-values.yaml", secure_read(ctl_sources["values"], "galileoctl non-secret values")[1])
            if sha256_file(temp / "artifacts" / "galileoctl.tgz") != ctl["chart_sha256"].lower():
                fail("galileoctl chart changed while rendering")
            validate_values_no_secrets(temp / "values" / "galileoctl-values.yaml")
        digest, records = bundle_digest(temp)
        manifest = {
            "schema": BUNDLE_SCHEMA,
            "contract_version": 1,
            "generated_by": "galileo-on-prem-stack-setup",
            "feature_matrix_sha256": sha256_file(FEATURE_MATRIX),
            "retention_post_renderer_sha256": retention_sha,
            "bundle_sha256": digest,
            "files": records,
        }
        write_private(temp / "bundle-manifest.json", json_bytes(manifest))
        destination = deployment_root / digest
        if destination.exists():
            verify_bundle(destination)
        else:
            os.rename(temp, destination)
            os.chmod(destination, 0o700)
    return {"action": "render", "state": "rendered", "bundle": str(destination), "bundle_sha256": digest, "runtime_inventory": str(destination / "runtime-inventory.json")}


def verify_bundle(bundle: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    bundle = lexical_absolute(bundle)
    reject_symlink_ancestors(bundle / "sentinel", "bundle")
    info = bundle.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        fail("bundle directory must be current-user-owned, non-symlink, and mode 0700")
    parent_info = bundle.parent.lstat()
    if stat.S_ISLNK(parent_info.st_mode) or not stat.S_ISDIR(parent_info.st_mode) or parent_info.st_uid != os.getuid() or stat.S_IMODE(parent_info.st_mode) != 0o700:
        fail("bundle parent must be current-user-owned, non-symlink, and mode 0700")
    manifest_path = bundle / "bundle-manifest.json"
    manifest_info = manifest_path.lstat()
    if stat.S_ISLNK(manifest_info.st_mode) or not stat.S_ISREG(manifest_info.st_mode) or manifest_info.st_uid != os.getuid() or manifest_info.st_nlink != 1 or stat.S_IMODE(manifest_info.st_mode) != 0o600:
        fail("bundle manifest must be current-user-owned, regular, one-link, and mode 0600")
    try:
        manifest_raw = secure_read(manifest_path, "bundle manifest", private=True)[1]
        manifest = assert_mapping(json.loads(manifest_raw), "bundle manifest")
    except json.JSONDecodeError:
        fail("bundle manifest is not valid JSON")
    manifest_keys = {
        "schema", "contract_version", "generated_by", "feature_matrix_sha256",
        "retention_post_renderer_sha256", "bundle_sha256", "files",
    }
    if set(manifest) != manifest_keys:
        fail("bundle manifest fields differ from the canonical contract")
    if manifest_raw != json_bytes(manifest):
        fail("bundle manifest is not canonical JSON")
    if manifest.get("schema") != BUNDLE_SCHEMA or manifest.get("contract_version") != 1 or isinstance(manifest.get("contract_version"), bool) or manifest.get("generated_by") != "galileo-on-prem-stack-setup" or not SHA_RE.fullmatch(str(manifest.get("bundle_sha256", ""))):
        fail("invalid bundle manifest")
    if bundle.name != manifest["bundle_sha256"]:
        fail("bundle directory name does not match bundle SHA-256")
    records = assert_list(manifest.get("files"), "bundle manifest files")
    expected: dict[str, dict[str, Any]] = {}
    for record_value in records:
        record = assert_mapping(record_value, "bundle manifest file record")
        if set(record) != {"path", "sha256", "mode"}:
            fail("bundle manifest file record fields differ")
        relative = record.get("path")
        pure = PurePosixPath(relative) if isinstance(relative, str) else None
        if pure is None or pure.is_absolute() or ".." in pure.parts or not pure.parts or relative != pure.as_posix():
            fail("bundle manifest contains an unsafe file path")
        if not SHA_RE.fullmatch(str(record.get("sha256", ""))) or record.get("mode") not in {"0600", "0700"}:
            fail("bundle manifest file hash/mode is invalid")
        if relative in expected:
            fail("bundle manifest has duplicate file records")
        expected[relative] = record
    actual_paths: set[str] = set()
    for root, directories, files in os.walk(bundle, topdown=True, followlinks=False):
        root_path = Path(root)
        for name in list(directories):
            info = (root_path / name).lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                fail("bundle contains an unsafe directory")
        for name in files:
            path = root_path / name
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                fail("bundle contains a symlink or special file")
            if path != manifest_path:
                actual_paths.add(path.relative_to(bundle).as_posix())
    if actual_paths != set(expected):
        fail("bundle contains missing or untracked files")
    for relative, record in expected.items():
        path = bundle / relative
        path_info = path.lstat()
        if stat.S_ISLNK(path_info.st_mode) or not stat.S_ISREG(path_info.st_mode) or path_info.st_uid != os.getuid() or path_info.st_nlink != 1:
            fail(f"unsafe bundle file: {relative}")
        captured = secure_read(path, f"bundle file {relative}")[1]
        required_mode = "0700" if relative == "helpers/retain_resources.py" else "0600"
        if record["mode"] != required_mode or stat.S_IMODE(path_info.st_mode) != int(record["mode"], 8) or sha256_bytes(captured) != record["sha256"]:
            fail(f"bundle file drift: {relative}")
    computed, computed_records = bundle_digest(bundle)
    if computed != manifest["bundle_sha256"] or computed_records != records:
        fail("bundle digest drift")
    bundled_feature_matrix = bundle / "contracts" / "deployment-feature-matrix.json"
    bundled_retention_helper = bundle / "helpers" / "retain_resources.py"
    feature_sha = sha256_file(bundled_feature_matrix)
    helper_sha = sha256_file(bundled_retention_helper)
    if manifest["feature_matrix_sha256"] != feature_sha or manifest["retention_post_renderer_sha256"] != helper_sha:
        fail("bundle contract no longer matches the reviewed feature matrix or retention renderer")

    raw_spec = assert_mapping(load_yaml(bundle / "deployment-spec.yaml", "bundled spec"), "bundled spec")
    bundled_console = require_str(raw_spec, "galileo_console_url", "bundled spec")
    spec = load_spec(bundle / "deployment-spec.yaml", bundled_console)
    if secure_read(bundle / "deployment-spec.yaml", "bundled spec", private=True)[1] != yaml_bytes(spec):
        fail("bundled deployment spec is not in canonical normalized form")
    if spec["stack"]["chart_archive"] != "artifacts/galileo-stack.tgz" or spec["stack"]["nonsecret_values_file"] != "values/stack-values.yaml":
        fail("bundled Stack artifact paths differ from the canonical contract")
    ctl = spec["galileoctl"]
    if ctl["enabled"] and (ctl["chart_archive"] != "artifacts/galileoctl.tgz" or ctl["nonsecret_values_file"] != "values/galileoctl-values.yaml"):
        fail("bundled galileoctl artifact paths differ from the canonical contract")
    if spec["air_gap"]["enabled"] and spec["air_gap"]["verified_contract_file"] != "contracts/air-gap-metadata.json":
        fail("bundled air-gap contract path differs from the canonical contract")

    expected_paths = {
        "deployment-spec.yaml", "chart-inventory.json", "runtime-inventory.json",
        "apply-plan.json", "artifacts/galileo-stack.tgz", "values/stack-values.yaml",
        "helpers/retain_resources.py", "contracts/deployment-feature-matrix.json",
    }
    if ctl["enabled"]:
        expected_paths.update({"artifacts/galileoctl.tgz", "values/galileoctl-values.yaml"})
    if spec["air_gap"]["enabled"]:
        expected_paths.add("contracts/air-gap-metadata.json")
    if set(expected) != expected_paths:
        fail("bundle file set differs from the canonical deployment contract")
    stack_values = bundle / spec["stack"]["nonsecret_values_file"]
    values = validate_values_no_secrets(stack_values)
    if spec["crds"]["mode"] == "shared" and not shared_crd_controls(values):
        fail("shared CRD review requires all four explicit CRD controls")
    stack_report, runtime_inventory = inspect_chart(
        bundle / spec["stack"]["chart_archive"],
        spec["stack"]["chart_sha256"],
        spec["stack"]["chart_version"],
        "galileo-stack",
        bundled_feature_matrix,
    )
    ctl_report: dict[str, Any] | None = None
    if ctl["enabled"]:
        validate_values_no_secrets(bundle / ctl["nonsecret_values_file"])
        ctl_report, ctl_inventory = inspect_chart(
            bundle / ctl["chart_archive"],
            ctl["chart_sha256"],
            ctl["chart_version"],
            "galileoctl",
            bundled_feature_matrix,
        )
        runtime_inventory = combine_runtime_inventories(
            runtime_inventory,
            ctl_inventory,
            feature_matrix=bundled_feature_matrix,
        )
    expected_chart_inventory = {"stack": stack_report, "galileoctl": ctl_report}
    for relative, canonical in (
        ("chart-inventory.json", expected_chart_inventory),
        ("runtime-inventory.json", runtime_inventory),
        ("apply-plan.json", canonical_apply_plan(spec, helper_sha)),
    ):
        raw = secure_read(bundle / relative, f"bundled {relative}", private=True)[1]
        try:
            observed = json.loads(raw)
        except json.JSONDecodeError:
            fail(f"bundled {relative} is invalid JSON")
        if observed != canonical or raw != json_bytes(canonical):
            fail(f"bundled {relative} differs from exact derived metadata")
    compare_coverage(spec, runtime_inventory)
    if spec["air_gap"]["enabled"]:
        contract_bytes = secure_read(bundle / "contracts/air-gap-metadata.json", "bundled air-gap contract", private=True)[1]
        if sha256_bytes(contract_bytes) != spec["air_gap"]["verified_contract_sha256"]:
            fail("bundled air-gap contract digest differs")
        try:
            contract = json.loads(contract_bytes)
        except json.JSONDecodeError:
            fail("bundled air-gap contract is invalid JSON")
        validate_air_gap_contract(
            contract,
            spec,
            None,
            {
                "stack_nonsecret_values_sha256": expected[spec["stack"]["nonsecret_values_file"]]["sha256"],
                "galileoctl_nonsecret_values_sha256": (
                    expected[spec["galileoctl"]["nonsecret_values_file"]]["sha256"]
                    if spec["galileoctl"]["enabled"] else ""
                ),
            },
        )
    return manifest, spec


def resolve_executable(raw: str, name: str) -> str:
    if not raw or any(char.isspace() for char in raw):
        fail(f"--{name}-bin must be a single executable name or path")
    candidate = Path(raw)
    resolved = str(lexical_absolute(candidate)) if "/" in raw else (shutil.which(raw, path="/usr/local/bin:/usr/bin:/bin:/snap/bin") or "")
    if not resolved or not Path(resolved).is_file() or not os.access(resolved, os.X_OK):
        fail(f"--{name}-bin does not resolve to an executable")
    return resolved


def minimal_env(temp: Path) -> dict[str, str]:
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin:/snap/bin",
        "XDG_CONFIG_HOME": str(temp / "xdg-config"),
        "XDG_CACHE_HOME": str(temp / "xdg-cache"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "HELM_CONFIG_HOME": str(temp / "helm-config"),
        "HELM_CACHE_HOME": str(temp / "helm-cache"),
        "HELM_DATA_HOME": str(temp / "helm-data"),
        "HELM_PLUGINS": str(temp / "helm-plugins"),
    }
    for directory in ("xdg-config", "xdg-cache", "helm-config", "helm-cache", "helm-data", "helm-plugins"):
        (temp / directory).mkdir(mode=0o700, exist_ok=True)
    return env


def run_checked(
    args: list[str],
    env: dict[str, str],
    *,
    stdin: bytes | None = None,
    limit: int = 128 * 1024 * 1024,
    process_timeout: int = 300,
) -> bytes:
    if any(word in FORBIDDEN_HELM_WORDS for word in args):
        fail("internal command contains a forbidden Helm option")
    try:
        result = subprocess.run(args, input=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, check=False, timeout=process_timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        fail(f"command execution failed safely: {type(exc).__name__}")
    if len(result.stdout) > limit or len(result.stderr) > limit:
        fail("command output exceeded the safe in-memory limit")
    if result.returncode != 0:
        fail(f"command failed with exit code {result.returncode}; sensitive output was suppressed")
    return result.stdout


def kubeconfig_path(raw: str) -> Path:
    if raw:
        return safe_input_file(raw, "--kubeconfig", private=True)
    default = Path(pwd.getpwuid(os.getuid()).pw_dir) / ".kube" / "config"
    return safe_input_file(str(default), "default kubeconfig", private=True)


def validate_kubeconfig_auth(path: Path, context: str) -> None:
    config = assert_mapping(load_yaml(path, "kubeconfig", private=True), "kubeconfig")
    contexts = {item.get("name"): item.get("context") for item in config.get("contexts", []) if isinstance(item, dict)}
    selected = contexts.get(context)
    if not isinstance(selected, dict) or not isinstance(selected.get("user"), str):
        fail("reviewed kube context has no explicit user identity")
    users = {item.get("name"): item.get("user") for item in config.get("users", []) if isinstance(item, dict)}
    user = users.get(selected["user"])
    if not isinstance(user, dict):
        fail("reviewed kube context user is absent")
    if "exec" in user or "auth-provider" in user:
        fail("exec/auth-provider kubeconfig authentication is not supported in the isolated lifecycle; generate a short-lived mode-0600 static client-certificate or tokenFile kubeconfig out of band")
    if "token" in user:
        fail("inline kubeconfig tokens are rejected; use a current-user-owned mode-0600 tokenFile or client certificate")
    if not any(key in user for key in ("tokenFile", "client-certificate", "client-certificate-data")):
        fail("kubeconfig user must use tokenFile or client-certificate authentication")


def kubeconfig_binding(path: Path, context: str) -> tuple[str, str]:
    config = assert_mapping(load_yaml(path, "kubeconfig"), "kubeconfig")
    contexts = {item.get("name"): item.get("context") for item in config.get("contexts", []) if isinstance(item, dict)}
    if context not in contexts or not isinstance(contexts[context], dict):
        fail("reviewed kube context is absent from kubeconfig")
    cluster_name = contexts[context].get("cluster")
    clusters = {item.get("name"): item.get("cluster") for item in config.get("clusters", []) if isinstance(item, dict)}
    cluster = clusters.get(cluster_name)
    if not isinstance(cluster, dict):
        fail("reviewed kube context has no cluster record")
    if cluster.get("insecure-skip-tls-verify") is not None or cluster.get("proxy-url") is not None or cluster.get("tls-server-name") is not None:
        fail("kubeconfig cluster rejects insecure TLS, proxy URL, and TLS server-name overrides")
    server = cluster.get("server")
    if not isinstance(server, str):
        fail("kubeconfig cluster has no server")
    if isinstance(cluster.get("certificate-authority-data"), str):
        try:
            ca_bytes = base64.b64decode(cluster["certificate-authority-data"], validate=True)
        except ValueError:
            fail("kubeconfig certificate-authority-data is invalid base64")
    elif isinstance(cluster.get("certificate-authority"), str):
        ca_path = Path(cluster["certificate-authority"])
        if not ca_path.is_absolute():
            ca_path = path.parent / ca_path
        ca_bytes = secure_read(ca_path, "kubeconfig certificate-authority", one_link=False)[1]
    else:
        fail("kubeconfig cluster does not provide a certificate authority")
    return server.rstrip("/"), sha256_bytes(ca_bytes)


def snapshot_kubeconfig(source: Path, temp: Path) -> Path:
    config = assert_mapping(load_yaml(source, "kubeconfig", private=True), "kubeconfig")
    base = source.parent
    for cluster_item in config.get("clusters", []):
        cluster = cluster_item.get("cluster") if isinstance(cluster_item, dict) else None
        if not isinstance(cluster, dict):
            continue
        ca_ref = cluster.pop("certificate-authority", None)
        if isinstance(ca_ref, str):
            path = Path(ca_ref) if Path(ca_ref).is_absolute() else base / ca_ref
            cluster["certificate-authority-data"] = base64.b64encode(secure_read(path, "kubeconfig certificate-authority")[1]).decode()
    for user_index, user_item in enumerate(config.get("users", [])):
        user = user_item.get("user") if isinstance(user_item, dict) else None
        if not isinstance(user, dict):
            continue
        for key, data_key in (("client-certificate", "client-certificate-data"), ("client-key", "client-key-data")):
            ref = user.pop(key, None)
            if isinstance(ref, str):
                path = Path(ref) if Path(ref).is_absolute() else base / ref
                user[data_key] = base64.b64encode(secure_read(path, f"kubeconfig {key}", private=(key == "client-key"))[1]).decode()
        token_ref = user.pop("tokenFile", None)
        if isinstance(token_ref, str):
            path = Path(token_ref) if Path(token_ref).is_absolute() else base / token_ref
            token_destination = temp / f"kube-token-{user_index}"
            write_private(token_destination, secure_read(path, "kubeconfig token file", private=True)[1])
            user["tokenFile"] = str(token_destination)
    destination = temp / "kubeconfig.yaml"
    write_private(destination, yaml_bytes(config))
    return destination


def snapshot_file(
    source: Path,
    destination: Path,
    field: str,
    *,
    private: bool = False,
    mode: int = 0o600,
) -> Path:
    write_private(destination, secure_read(source, field, private=private)[1], mode=mode)
    return destination


def assert_snapshot_digest(snapshot: Path, expected: str, field: str) -> None:
    if sha256_file(snapshot) != expected:
        fail(f"{field} changed between integrity gate and private snapshot")


def kubectl_base(kubectl: str, kubeconfig: Path, context: str) -> list[str]:
    return [kubectl, "--kubeconfig", str(kubeconfig), "--context", context]


def helm_base(helm: str, kubeconfig: Path, context: str) -> list[str]:
    return [helm, "--kubeconfig", str(kubeconfig), "--kube-context", context]


def parse_json_bytes(data: bytes, field: str) -> Any:
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        fail(f"{field} returned invalid JSON")


def release_inventory(helm_cmd: list[str], env: dict[str, str], namespace: str, name: str) -> list[dict[str, Any]]:
    output = run_checked(helm_cmd + ["list", "--all", "--namespace", namespace, "--filter", f"^{re.escape(name)}$", "--output", "json"], env)
    releases = parse_json_bytes(output, "helm list --all")
    if not isinstance(releases, list):
        fail("helm list --all returned an invalid release inventory")
    exact = [item for item in releases if isinstance(item, dict) and item.get("name") == name and item.get("namespace") == namespace]
    if len(exact) > 1:
        fail("multiple exact Helm release identities were returned")
    return exact


def release_version(release: dict[str, Any], chart_name: str) -> str:
    chart = release.get("chart")
    prefix = f"{chart_name}-"
    if not isinstance(chart, str) or not chart.startswith(prefix) or not chart[len(prefix):]:
        fail(f"existing release is not an exact {chart_name} chart identity")
    return chart[len(prefix):]


KUBERNETES_SEMVER_RE = re.compile(
    r"^v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*))?"
    r"(?:\+([0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*))?$"
)


def canonical_kubernetes_server_version(
    version_document: dict[str, Any],
) -> tuple[str, str, int, int, int]:
    """Return raw and exact Helm-compatible server SemVer without synthesis."""
    server = assert_mapping(
        version_document.get("serverVersion"),
        "kubectl serverVersion",
    )
    raw = server.get("gitVersion")
    if not isinstance(raw, str):
        fail("Kubernetes serverVersion.gitVersion must be an exact SemVer string")
    match = KUBERNETES_SEMVER_RE.fullmatch(raw)
    if match is None:
        fail("Kubernetes serverVersion.gitVersion is not canonical semantic versioning")
    major, minor, patch = (int(match.group(index)) for index in (1, 2, 3))
    reported_major = str(server.get("major", ""))
    reported_minor = str(server.get("minor", "")).rstrip("+")
    if reported_major != str(major) or reported_minor != str(minor):
        fail("Kubernetes serverVersion major/minor differs from gitVersion")
    normalized = raw[1:] if raw.startswith("v") else raw
    return raw, normalized, major, minor, patch


def _semver_precedence(value: str) -> tuple[Any, ...]:
    match = KUBERNETES_SEMVER_RE.fullmatch(value)
    if match is None:
        fail("Kubernetes version constraint contains invalid semantic versioning")
    prerelease = match.group(4)
    prerelease_key: tuple[Any, ...] = ()
    if prerelease is not None:
        prerelease_key = tuple(
            (0, int(item)) if item.isdigit() else (1, item)
            for item in prerelease.split(".")
        )
    return (
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3)),
        1 if prerelease is None else 0,
        prerelease_key,
    )


def validate_simple_chart_kube_constraint(
    constraint: str,
    exact_version: str,
) -> bool:
    """Evaluate simple Helm comparator sets; Helm evaluates every full constraint.

    Returns False for richer Helm constraint syntax (OR, wildcards, tilde,
    caret, or hyphen ranges), which is intentionally left to the later exact
    ``helm template --kube-version`` call rather than approximated.
    """
    if not constraint.strip():
        return True
    if any(token in constraint for token in ("||", "*", "~", "^")):
        return False
    token_re = re.compile(
        r"(>=|<=|>|<|=)?\s*"
        r"(v?(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
        r"(?:-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?"
        r"(?:\+[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?)"
    )
    comparisons: list[tuple[str, str]] = []
    position = 0
    for match in token_re.finditer(constraint):
        if constraint[position:match.start()].strip(" ,"):
            return False
        comparisons.append((match.group(1) or "=", match.group(2)))
        position = match.end()
    if not comparisons or constraint[position:].strip(" ,"):
        return False
    actual = _semver_precedence(exact_version)
    for operator, required_value in comparisons:
        required = _semver_precedence(required_value)
        accepted = {
            "=": actual == required,
            ">": actual > required,
            ">=": actual >= required,
            "<": actual < required,
            "<=": actual <= required,
        }[operator]
        if not accepted:
            fail(
                f"Kubernetes {exact_version} does not satisfy pinned chart "
                f"kubeVersion constraint {constraint!r}"
            )
    return True


def release_observation_state(
    stack_releases: list[dict[str, Any]],
    galileoctl_enabled: bool,
    galileoctl_release: dict[str, Any] | None,
) -> str:
    stack_deployed = bool(stack_releases) and str(stack_releases[0].get("status", "")).lower() == "deployed"
    ctl_deployed = not galileoctl_enabled or (
        galileoctl_release is not None
        and str(galileoctl_release.get("status", "")).lower() == "deployed"
    )
    if not stack_releases:
        return "absent-observed"
    if stack_deployed and ctl_deployed:
        # Chart name/version and Helm status alone do not bind the installed
        # values, Secret inputs, manifest, revision, or live object UIDs to the
        # reviewed bundle. Keep the observation explicitly unverified.
        return "unverified-observed"
    return "unverified-degraded-observed"


def require_release_lifecycle_state(release: dict[str, Any], action: str, label: str) -> None:
    status_value = str(release.get("status", "")).lower()
    if action == "upgrade" and status_value != "deployed":
        fail(f"{label} upgrade requires an exactly deployed Helm release, not {status_value or 'unknown'}")
    if action == "rollback" and status_value not in {"deployed", "failed"}:
        fail(f"{label} rollback rejects pending/uninstalled Helm release state {status_value or 'unknown'}")


def version_key(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:\+[0-9A-Za-z.-]+)?", value)
    if not match:
        fail(f"chart version {value!r} must be stable semantic versioning for automated upgrade")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def assert_upgrade_direction(current: str, target: str) -> None:
    if version_key(target) <= version_key(current):
        fail("upgrade target must be strictly newer than the exact live chart version")


def release_operation_mode(
    releases: list[dict[str, Any]], action: str, chart_name: str, target_version: str, label: str
) -> str:
    """Return an exact mutation mode; partial/same-version resume is disabled."""
    if action not in {"install", "upgrade"}:
        fail("release operation mode is limited to install/upgrade")
    if not releases:
        if action == "upgrade":
            fail(f"{label} upgrade requires an existing exact release")
        return "install"
    release = releases[0]
    status_value = str(release.get("status", "")).lower()
    if status_value != "deployed":
        fail(f"{label} resume requires a deployed release, not {status_value or 'unknown'}")
    current = release_version(release, chart_name)
    if current == target_version:
        fail(
            f"{label} already has the target chart version but live values/Secret provenance cannot be proven; "
            "automated partial resume and same-version reconfiguration are disabled"
        )
    if action == "install":
        fail(f"{label} install found an existing non-target release")
    assert_upgrade_direction(current, target_version)
    return "upgrade"


def release_contract(spec: dict[str, Any], bundle_sha: str, namespace_uid: str) -> dict[str, Any]:
    return {
        "schema": RELEASE_CONTRACT_SCHEMA,
        "release": spec["stack"]["release_name"],
        "namespace": spec["target"]["namespace"],
        "bundle_sha256": bundle_sha,
        "chart": {"name": "galileo-stack", "version": spec["stack"]["chart_version"], "sha256": spec["stack"]["chart_sha256"]},
        "target": {
            "context": spec["target"]["kube_context"],
            "api_server": spec["target"]["api_server"],
            "ca_sha256": spec["target"]["ca_sha256"],
            "kube_system_uid": spec["target"]["cluster_uid"],
            "namespace_uid": namespace_uid,
        },
    }


def validate_release_contract(document: Any, spec: dict[str, Any], bundle_sha: str) -> dict[str, Any]:
    contract = assert_mapping(document, "release contract")
    if set(contract) != {"schema", "release", "namespace", "bundle_sha256", "chart", "target"}:
        fail("release contract fields differ")
    target = assert_mapping(contract.get("target"), "release contract target")
    expected_prefix = release_contract(spec, bundle_sha, str(target.get("namespace_uid", "")))
    if contract != expected_prefix or not str(contract["target"]["namespace_uid"]):
        fail("release contract binding differs")
    return contract


def assert_namespace_binding(expected: str, observed: str) -> None:
    if expected != observed:
        fail("namespace UID/presence changed immediately before mutation")


def recheck_target(kube: list[str], kubeconfig: Path, env: dict[str, str], spec: dict[str, Any], evidence: dict[str, Any]) -> str:
    server, ca_hash = kubeconfig_binding(kubeconfig, spec["target"]["kube_context"])
    system = parse_json_bytes(run_checked(kube + ["get", "namespace", "kube-system", "-o", "json"], env), "kube-system")
    uid = system.get("metadata", {}).get("uid")
    if server != spec["target"]["api_server"].rstrip("/") or ca_hash != spec["target"]["ca_sha256"] or uid != spec["target"]["cluster_uid"]:
        fail("target identity changed immediately before mutation")
    namespace = spec["target"]["namespace"]
    probe = run_checked(kube + ["get", "namespace", namespace, "--ignore-not-found", "-o", "json"], env)
    observed = str(parse_json_bytes(probe, "namespace").get("metadata", {}).get("uid", "")) if probe.strip() else "absent"
    assert_namespace_binding(evidence["target"]["namespace_uid"], observed)
    return observed


def recheck_release_state(
    helm_cmd: list[str],
    env: dict[str, str],
    spec: dict[str, Any],
    action: str,
    evidence: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    namespace = spec["target"]["namespace"]
    stack = release_inventory(helm_cmd, env, namespace, spec["stack"]["release_name"])
    if action in {"install", "upgrade"}:
        mode = release_operation_mode(stack, action, "galileo-stack", spec["stack"]["chart_version"], "Stack")
        if evidence is None or mode != evidence.get("release_mode"):
            fail("Stack release state changed immediately before mutation")
    elif stack:
        require_release_lifecycle_state(stack[0], action, "Stack")
        current = release_version(stack[0], "galileo-stack")
        if current != spec["stack"]["chart_version"]:
            fail("exact Stack release chart/version changed immediately before mutation")
    else:
        fail(f"{action} requires the exact Stack release")
    ctl: list[dict[str, Any]] = []
    if spec["galileoctl"]["enabled"]:
        ctl = release_inventory(helm_cmd, env, namespace, spec["galileoctl"]["release_name"])
        if action in {"install", "upgrade"}:
            mode = release_operation_mode(ctl, action, "galileoctl", spec["galileoctl"]["chart_version"], "galileoctl")
            if evidence is None or mode != evidence.get("galileoctl_release_mode"):
                fail("galileoctl release state changed immediately before mutation")
        elif ctl:
            require_release_lifecycle_state(ctl[0], action, "galileoctl")
            current = release_version(ctl[0], "galileoctl")
            if current != spec["galileoctl"]["chart_version"]:
                fail("exact galileoctl release chart/version changed immediately before mutation")
        else:
            fail(f"{action} requires the exact galileoctl release")
    return stack, ctl


def compare_coverage(spec: dict[str, Any], inventory: dict[str, Any]) -> None:
    mapping = {
        "reviewed_components": "dependency",
        "reviewed_schema_or_enable_flags": "schema_or_enable_flag",
        "reviewed_kinds": "api_kind",
        "reviewed_images": "image",
        "reviewed_crds": "crd",
        "reviewed_hooks": "hook_or_migration",
        "reviewed_cluster_scoped_kinds": "cluster_scoped_object",
        "reviewed_pvcs": "persistence",
        "reviewed_routes": "service_or_route",
    }
    for spec_key, category in mapping.items():
        observed = sorted(item["id"] for item in inventory["items"] if item["category"] == category)
        reviewed = sorted(spec["coverage"][spec_key])
        if observed != reviewed:
            fail(f"runtime inventory review drift in spec.coverage.{spec_key}; copy exact IDs from runtime-inventory.json and rerender")


def preflight(args: argparse.Namespace, for_action: str | None = None) -> dict[str, Any]:
    bundle = lexical_absolute(args.bundle)
    manifest, spec = verify_bundle(bundle)
    if console_url(args.galileo_console_url) != spec["galileo_console_url"]:
        fail("--galileo-console-url does not match the bundled deployment")
    secret = safe_input_file(args.secret_values_file, "--secret-values-file", private=True)
    ctl_secret: Path | None = None
    if spec["galileoctl"].get("enabled"):
        ctl_secret = safe_input_file(args.galileoctl_secret_values_file, "--galileoctl-secret-values-file", private=True)
    action = for_action or args.for_action
    if action == "rollback":
        fail(
            "automated rollback is disabled: render a Galileo/CSE recovery handoff and validate the "
            "complete target release, values, CRDs, persistence, routing, and data-service state"
        )
    inventory = json.loads(secure_read(bundle / "runtime-inventory.json", "bundled runtime inventory", private=True)[1])
    compare_coverage(spec, inventory)

    kubeconfig_source = kubeconfig_path(args.kubeconfig)
    validate_kubeconfig_auth(kubeconfig_source, spec["target"]["kube_context"])
    helm = resolve_executable(args.helm_bin, "helm")
    kubectl = resolve_executable(args.kubectl_bin, "kubectl")
    with tempfile.TemporaryDirectory(prefix=".galileo-stack-preflight-", dir=bundle.parent) as temp_name:
        temp = Path(temp_name)
        os.chmod(temp, 0o700)
        env = minimal_env(temp)
        kubeconfig = snapshot_kubeconfig(kubeconfig_source, temp)
        context = spec["target"]["kube_context"]
        validate_kubeconfig_auth(kubeconfig, context)
        kube = kubectl_base(kubectl, kubeconfig, context)
        helm_cmd = helm_base(helm, kubeconfig, context)
        helm_version = run_checked([helm, "version", "--short"], env, limit=1024).decode(errors="replace").strip()
        if not re.fullmatch(r"v3\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)*", helm_version):
            fail("Helm 3 is required")
        server, ca_hash = kubeconfig_binding(kubeconfig, context)
        if server != spec["target"]["api_server"].rstrip("/") or ca_hash != spec["target"]["ca_sha256"]:
            fail("active kubeconfig API server or decoded CA hash differs from the reviewed target")
        version = parse_json_bytes(run_checked(kube + ["version", "-o", "json"], env), "kubectl version")
        (
            kubernetes_version_raw,
            kubernetes_version,
            kubernetes_major,
            kubernetes_minor,
            _kubernetes_patch,
        ) = canonical_kubernetes_server_version(version)
        if kubernetes_major != 1 or kubernetes_minor < 27:
            fail("Kubernetes 1.27 or newer is required by policy")
        chart_inventory = json.loads(secure_read(bundle / "chart-inventory.json", "bundled chart inventory", private=True)[1])
        constraint = str(chart_inventory.get("stack", {}).get("chart", {}).get("kubeVersion", ""))
        # Simple comparator sets receive an early explicit diagnostic. Richer
        # Helm constraints are evaluated by the exact subsequent template call
        # with this same, unsynthesized patch/prerelease/build version.
        validate_simple_chart_kube_constraint(constraint, kubernetes_version)
        system_ns = parse_json_bytes(run_checked(kube + ["get", "namespace", "kube-system", "-o", "json"], env), "kube-system namespace")
        cluster_uid = system_ns.get("metadata", {}).get("uid")
        if cluster_uid != spec["target"]["cluster_uid"]:
            fail("kube-system UID differs from the reviewed target")
        namespace = spec["target"]["namespace"]
        ns_probe = run_checked(kube + ["get", "namespace", namespace, "--ignore-not-found", "-o", "json"], env)
        if ns_probe.strip():
            ns_doc = parse_json_bytes(ns_probe, "namespace")
            namespace_uid = str(ns_doc.get("metadata", {}).get("uid", ""))
            if spec["target"]["namespace_create"] or namespace_uid != spec["target"].get("namespace_uid"):
                fail("namespace presence/UID differs from the reviewed target")
        else:
            namespace_uid = "absent"
            if not spec["target"]["namespace_create"]:
                fail("reviewed existing namespace is absent")

        if action not in {"install", "upgrade", "rollback", "uninstall", "status"}:
            fail("--for-action must select install, upgrade, rollback, uninstall, or status")
        releases = release_inventory(helm_cmd, env, namespace, spec["stack"]["release_name"])
        if action in {"upgrade", "rollback", "uninstall", "status"} and not releases:
            fail(f"{action} preflight requires the exact existing release")
        release_mode = "observed"
        if action in {"install", "upgrade"}:
            release_mode = release_operation_mode(
                releases, action, "galileo-stack", spec["stack"]["chart_version"], "Stack"
            )
        elif releases:
            require_release_lifecycle_state(releases[0], action, "Stack")
            current_version = release_version(releases[0], "galileo-stack")
            if action in {"rollback", "uninstall", "status"} and current_version != spec["stack"]["chart_version"]:
                fail("existing release chart/version differs from the exact reviewed bundle")
        ctl_releases: list[dict[str, Any]] = []
        ctl_release_mode = "disabled"
        if spec["galileoctl"]["enabled"]:
            ctl_releases = release_inventory(helm_cmd, env, namespace, spec["galileoctl"]["release_name"])
            if action in {"upgrade", "rollback", "uninstall", "status"} and not ctl_releases:
                fail(f"{action} preflight requires the exact existing galileoctl release")
            if action in {"install", "upgrade"}:
                ctl_release_mode = release_operation_mode(
                    ctl_releases,
                    action,
                    "galileoctl",
                    spec["galileoctl"]["chart_version"],
                    "galileoctl",
                )
            elif ctl_releases:
                require_release_lifecycle_state(ctl_releases[0], action, "galileoctl")
                ctl_version = release_version(ctl_releases[0], "galileoctl")
                if ctl_version != spec["galileoctl"]["chart_version"]:
                    fail("existing galileoctl chart/version differs from the exact reviewed bundle")
        if action in {"install", "upgrade"}:
            modes = {release_mode}
            if spec["galileoctl"]["enabled"]:
                modes.add(ctl_release_mode)

        auth = spec["authorization"]
        check_keys(auth, {"rbac_enforced", "evidence"}, "spec.authorization")
        if spec["environment"] == "production" and (auth.get("rbac_enforced") is not True or not isinstance(auth.get("evidence"), str) or not auth["evidence"]):
            fail("production requires explicit RBAC-enforcement evidence")
        permissions = [
            ("get", "namespaces", None),
            ("get", "customresourcedefinitions.apiextensions.k8s.io", None),
            ("list", "customresourcedefinitions.apiextensions.k8s.io", None),
            ("get", "storageclasses.storage.k8s.io", None),
            ("get", "nodes", None),
            ("list", "nodes", None),
        ]
        for resource in (
            "secrets", "configmaps", "services", "deployments.apps",
            "statefulsets.apps", "jobs.batch", "serviceaccounts",
            "roles.rbac.authorization.k8s.io",
            "rolebindings.rbac.authorization.k8s.io",
            "persistentvolumeclaims", "ingresses.networking.k8s.io",
            "httproutes.gateway.networking.k8s.io",
        ):
            permissions.extend((("get", resource, namespace), ("list", resource, namespace)))
        denied = []
        for verb, resource, ns in permissions:
            command = kube + ["auth", "can-i", verb, resource]
            if ns:
                command += ["--namespace", ns]
            result = run_checked(command, env, limit=64).decode().strip().lower()
            if result != "yes":
                denied.append(f"{verb}:{resource}:{ns or 'cluster'}")
        if denied:
            fail("required read-only observer authorization cannot be proven: " + ", ".join(denied[:8]))

        # The recursive archive inventory is a static superset only. Disabled
        # dependencies can package CRDs, so the active lifecycle set is
        # derived later from the exact values-aware --include-crds render.
        static_crd_superset = packaged_crds(
            secure_read(bundle / spec["stack"]["chart_archive"], "bundled stack chart", private=True)[1]
        )
        crd_upgrade_inventory: list[dict[str, Any]] = []
        active_crd_inventory: list[dict[str, str]] = []

        storage = spec["storage"]
        check_keys(
            storage,
            {"default_class", "classes", "restore_tested", "snapshot_evidence", "restore_evidence", "snapshot_evidence_observed_at", "restore_evidence_observed_at", "restore_evidence_max_age_days", "operator_claims"},
            "spec.storage",
        )
        storage_class = require_str(storage, "default_class", "spec.storage")
        classes = assert_list(storage.get("classes"), "spec.storage.classes")
        declared = [item for item in classes if isinstance(item, dict) and item.get("name") == storage_class]
        if len(declared) != 1:
            fail("default StorageClass must have one exact reviewed policy")
        names = [item.get("name") for item in classes if isinstance(item, dict)]
        if len(names) != len(set(names)):
            fail("reviewed StorageClass policies contain duplicate names")
        policy = declared[0]
        for class_policy in classes:
            reviewed_name = class_policy["name"]
            sc = parse_json_bytes(run_checked(kube + ["get", "storageclass", reviewed_name, "-o", "json"], env), f"StorageClass {reviewed_name}")
            if sc.get("metadata", {}).get("name") != reviewed_name or sc.get("reclaimPolicy") != class_policy.get("reclaim_policy") or bool(sc.get("allowVolumeExpansion")) != bool(class_policy.get("allow_expansion")):
                fail(f"live StorageClass {reviewed_name} reclaim/expansion policy differs from reviewed policy")
            if spec["environment"] == "production" and (
                class_policy.get("reclaim_policy") != "Retain"
                or class_policy.get("allow_expansion") is not True
                or class_policy.get("snapshots") is not True
                or int(class_policy.get("minimum_size_gib", 0)) < 200
            ):
                fail(f"production StorageClass {reviewed_name} lacks Retain/expansion/snapshot/200Gi policy")
        if spec["environment"] == "production":
            if policy.get("reclaim_policy") != "Retain" or policy.get("snapshots") is not True or storage.get("restore_tested") is not True:
                fail("production storage requires Retain, snapshots, expansion, and restore evidence")
            snapshot_observed = parse_time(storage.get("snapshot_evidence_observed_at"), "spec.storage.snapshot_evidence_observed_at")
            restore_observed = parse_time(storage.get("restore_evidence_observed_at"), "spec.storage.restore_evidence_observed_at")
            now_utc = utc_now()
            if (
                not storage.get("snapshot_evidence", "").strip()
                or not storage.get("restore_evidence", "").strip()
                or snapshot_observed > now_utc + dt.timedelta(minutes=5)
                or snapshot_observed < now_utc - dt.timedelta(hours=24)
                or restore_observed > now_utc + dt.timedelta(minutes=5)
                or restore_observed < now_utc - dt.timedelta(days=storage["restore_evidence_max_age_days"])
            ):
                fail("production StorageClass snapshot capability must be current and restore drill within its reviewed max age")
            data = spec["data_services"]
            if data.get("postgres") not in {"external-ha", "self-hosted-ha"}:
                fail("production PostgreSQL must be external HA or reviewed self-hosted HA")
            if data.get("redis") not in {"managed", "external-ha", "in-cluster-exception"}:
                fail("production Redis must be managed/external HA or have a written Galileo exception")
            if data.get("object_store") not in {"external-s3", "external-gcs", "external-s3-compatible", "in-cluster-minio", "external-azure-blob-exception"}:
                fail("production object storage profile is invalid")
            if data.get("object_store") == "in-cluster-minio" and (data.get("object_store_nondefault_secret") is not True or policy.get("reclaim_policy") != "Retain"):
                fail("production in-cluster MinIO requires non-default secrets and retained storage")
            if (
                data.get("clickhouse_backup_verified") is not True
                or data.get("clickhouse_restore_verified") is not True
                or data.get("postgres_backup_verified") is not True
                or data.get("postgres_restore_verified") is not True
                or data.get("postgres_backup_frequency_hours", 999) > 24
            ):
                fail("production requires daily PostgreSQL and ClickHouse backup/restore evidence")
            if data.get("object_store_backup_verified") is not True or data.get("object_store_restore_verified") is not True:
                fail("production requires object-store backup/restore evidence")
            data_evidence_fields = (
                "postgres_backup_evidence", "postgres_restore_evidence",
                "clickhouse_backup_evidence", "clickhouse_restore_evidence",
                "object_store_backup_evidence", "object_store_restore_evidence",
                "object_store_backup_bucket",
            )
            backup_observed = parse_time(data.get("backup_evidence_observed_at"), "spec.data_services.backup_evidence_observed_at")
            restore_observed = parse_time(data.get("restore_evidence_observed_at"), "spec.data_services.restore_evidence_observed_at")
            if (
                any(not str(data.get(field, "")).strip() for field in data_evidence_fields)
                or backup_observed > now_utc + dt.timedelta(minutes=5)
                or backup_observed < now_utc - dt.timedelta(hours=min(data["postgres_backup_frequency_hours"], 24))
                or restore_observed > now_utc + dt.timedelta(minutes=5)
                or restore_observed < now_utc - dt.timedelta(days=data["restore_evidence_max_age_days"])
            ):
                fail("production data-service backup evidence must meet its frequency and restore drill its reviewed max age")
            readiness = data["readiness"]
            external_services = {
                service for service in ("postgres", "redis", "object_store", "clickhouse", "rabbitmq")
                if readiness[service]["ownership"] == "external"
            }
            if external_services or action != "install":
                readiness_time = parse_time(readiness.get("observed_at"), "spec.data_services.readiness.observed_at")
                if readiness_time > now_utc + dt.timedelta(minutes=5) or readiness_time < now_utc - dt.timedelta(minutes=30):
                    fail("production data-service readiness evidence must be observed in the last 30 minutes")
            for service in ("postgres", "redis", "object_store", "clickhouse", "rabbitmq"):
                proof = readiness[service]
                if proof["ownership"] == "release-managed" and action == "install":
                    continue
                required_true = {"reachable", "tls", "authenticated", "ha_ready"}
                if service == "object_store":
                    required_true.add("bucket_exists")
                if service == "rabbitmq":
                    required_true.add("persistence_ready")
                if any(proof.get(key) is not True for key in required_true) or not proof.get("version", "").strip() or not proof.get("reference", "").strip():
                    fail(f"production {service} readiness lacks reachable/TLS/auth/HA/version evidence")
            if readiness["postgres"]["ownership"] == "external" or action != "install":
                postgres_major = re.match(r"v?([0-9]+)", readiness["postgres"]["version"])
                if postgres_major is None or int(postgres_major.group(1)) < 13:
                    fail("production PostgreSQL readiness must prove version 13 or newer")
            if not readiness["redis"]["persistence_or_rebuild_decision"].strip():
                fail("production Redis requires an explicit persistence or rebuild decision")
            if not readiness["rabbitmq"]["queue_recovery_reference"].strip():
                fail("production RabbitMQ requires a queue recovery/queue-loss decision reference")
            if spec["monitoring"].get("enabled") is not True or not spec["monitoring"].get("alert_owner"):
                fail("production requires monitoring and a named alert owner")
        nodes_document = parse_json_bytes(run_checked(kube + ["get", "nodes", "-o", "json"], env), "nodes")
        observed_node_pools = validate_node_pools(spec, nodes_document)
        routing = spec["routing"]
        if routing.get("tls_required") is not True or routing.get("streaming_timeout_seconds", 0) < 120 or routing.get("public_metrics_blocked") is not True or routing.get("trace_route_before_api_catchall") is not True:
            fail("routing must enforce TLS, 120-second streaming, protected metrics, and trace route ordering")

        wizard = spec["wizard"]
        eligible_gpu_nodes: list[dict[str, Any]] = []
        if wizard.get("gpu_enabled"):
            for node in nodes_document.get("items", []):
                labels = node.get("metadata", {}).get("labels", {})
                allocatable = node.get("status", {}).get("allocatable", {})
                if labels.get("galileo-node-type") == "galileo-ml" and int(allocatable.get("nvidia.com/gpu", "0")) > 0:
                    eligible_gpu_nodes.append(node)
            if not eligible_gpu_nodes:
                fail("Wizard GPU mode has no labeled node with allocatable nvidia.com/gpu")
        stack_chart = snapshot_file(bundle / spec["stack"]["chart_archive"], temp / "galileo-stack.tgz", "bundled stack chart")
        stack_values = snapshot_file(bundle / spec["stack"]["nonsecret_values_file"], temp / "stack-values.yaml", "bundled stack values")
        secret_snapshot = snapshot_file(secret, temp / "stack-secret-values.yaml", "runtime stack secret values", private=True)
        stack_nonsecret_document = validate_values_no_secrets(stack_values)
        stack_secret_document = validate_runtime_secret_values(
            secret_snapshot,
            "Stack runtime Secret values",
            spec["stack"]["runtime_secret_value_paths"],
        )
        manifest_files = {record["path"]: record["sha256"] for record in manifest["files"]}
        assert_snapshot_digest(stack_chart, spec["stack"]["chart_sha256"], "Stack chart")
        assert_snapshot_digest(stack_values, manifest_files[spec["stack"]["nonsecret_values_file"]], "Stack non-secret values")
        retention_helper = snapshot_file(
            bundle / "helpers" / "retain_resources.py",
            temp / "retain_resources.py",
            "bundled retention renderer",
            mode=0o700,
        )
        assert_snapshot_digest(
            retention_helper,
            manifest_files["helpers/retain_resources.py"],
            "retention renderer",
        )
        template_args = helm_cmd + ["template", spec["stack"]["release_name"], str(stack_chart), "--namespace", namespace, "-f", str(stack_values), "-f", str(secret_snapshot), "--post-renderer", str(retention_helper), "--kube-version", kubernetes_version]
        # Both ownership modes inventory CRDs outside the Stack manifest.
        # Shared mode proves the platform owner's exact live schema. Dedicated
        # mode remains a non-executable handoff and cannot yield deployment
        # authorization. The workload evidence render always uses --skip-crds.
        rendered = run_checked(template_args + ["--skip-crds"], env, process_timeout=helm_process_timeout(spec["stack"]["timeout"]))
        secret_influence: dict[str, list[str]] = {}
        secret_payload_shape_sha256 = ""
        changed_payload_owner: dict[str, str] = {}
        for index, secret_path in enumerate(spec["stack"]["runtime_secret_value_paths"]):
            shadow_secret_path = temp / f"stack-secret-shadow-{index}.yaml"
            write_private(
                shadow_secret_path,
                yaml_bytes(shadow_secret_values(stack_secret_document, only_path=secret_path)),
            )
            shadow_rendered = run_checked(
                helm_cmd + ["template", spec["stack"]["release_name"], str(stack_chart), "--namespace", namespace, "-f", str(stack_values), "-f", str(shadow_secret_path), "--post-renderer", str(retention_helper), "--kube-version", kubernetes_version, "--skip-crds"],
                env,
                process_timeout=helm_process_timeout(spec["stack"]["timeout"]),
            )
            shape_digest, changed_paths = validate_secret_leaf_influence(
                rendered,
                shadow_rendered,
                f"Stack runtime-secret leaf {secret_path}",
            )
            if secret_payload_shape_sha256 and shape_digest != secret_payload_shape_sha256:
                fail("runtime-secret leaf renders do not share one canonical Secret payload shape")
            secret_payload_shape_sha256 = shape_digest
            for changed_path in changed_paths:
                if changed_path in changed_payload_owner:
                    fail(
                        "runtime-secret leaf influence overlaps another leaf; obtain an exact "
                        "CSE many-to-one derivation contract"
                    )
                changed_payload_owner[changed_path] = secret_path
            secret_influence[secret_path] = changed_paths
        secret_contract_sha256 = sha256_bytes(
            json_bytes({
                "paths": spec["stack"]["runtime_secret_value_paths"],
                "payload_shape_sha256": secret_payload_shape_sha256,
                "influence": secret_influence,
            })
        )
        include_crds_render = run_checked(
            template_args + ["--include-crds"],
            env,
            process_timeout=helm_process_timeout(spec["stack"]["timeout"]),
        )
        stack_documents = rendered_documents(rendered, "galileo-stack")
        active_crds = active_crds_from_render(include_crds_render, static_crd_superset)
        static_crd_names = {name for name, _, _ in static_crd_superset}
        active_crd_inventory = [
            {
                "name": name,
                "spec_sha256": sha256_bytes(json_bytes(normalized_crd_spec(document))),
                "source_class": "chart-crds" if name in static_crd_names else "rendered-template",
            }
            for name, document, _ in active_crds
        ]
        api_resources = add_active_crd_resources(discovered_api_resources(kube, env), active_crds)
        api_scopes = {key: bool(value["namespaced"]) for key, value in api_resources.items()}
        validate_rendered_scope(stack_documents, namespace, api_scopes)
        installer_permission_plan = validate_rendered_cluster_permissions(
            stack_documents, kube, env, api_resources, namespace
        )
        for crd_name, desired_crd, crd_body in active_crds:
            live_bytes = run_checked(
                kube + ["get", "customresourcedefinition", crd_name, "--ignore-not-found", "-o", "json"],
                env,
            )
            live_crd = parse_json_bytes(live_bytes, f"CRD {crd_name}") if live_bytes.strip() else None
            if spec["crds"]["mode"] == "shared":
                if not isinstance(live_crd, dict) or not crd_established(live_crd):
                    fail(f"shared CRD owner has not installed an Established {crd_name}")
                if normalized_crd_spec(live_crd) != normalized_crd_spec(desired_crd):
                    fail(f"shared CRD schema differs from the exact active packaged schema: {crd_name}")
            elif action == "install":
                if live_crd is not None:
                    fail(f"dedicated fresh install found a pre-existing active CRD collision: {crd_name}")
            else:
                if not isinstance(live_crd, dict) or not crd_established(live_crd):
                    fail(f"dedicated existing release lacks an Established active CRD: {crd_name}")
                if action == "upgrade":
                    crd_upgrade_inventory.append(crd_upgrade_diff(crd_name, live_crd, desired_crd))
                if action in {"rollback", "uninstall", "status"} and normalized_crd_spec(live_crd) != normalized_crd_spec(desired_crd):
                    fail(f"installed CRD schema differs from the exact reviewed release: {crd_name}")
            if spec["crds"]["mode"] == "dedicated" and action in {"install", "upgrade"}:
                run_checked(
                    kube + ["apply", "--server-side", "--field-manager", "galileo-on-prem-stack-setup", "--dry-run=server", "-f", "-"],
                    env,
                    stdin=crd_body,
                )
        if action == "upgrade" and spec["crds"]["mode"] == "dedicated" and any(item["changed"] for item in crd_upgrade_inventory):
            if any(not spec["crds"][key].strip() for key in ("upgrade_compatibility_evidence", "conversion_evidence", "stored_versions_evidence")):
                fail("changed dedicated CRDs require CSE compatibility, conversion, and storedVersions evidence")
        rendered_node_placements = validate_node_pool_rendering(stack_documents, spec)
        retained_resources = validate_retention_rendered(stack_documents)
        expected_claims = rendered_claims(stack_documents, spec["storage"], spec["environment"])
        rendered_routing = validate_rendered_routing(stack_documents, routing, spec["environment"])
        wizard_rendering = validate_gpu_rendering(stack_documents, wizard, eligible_gpu_nodes)
        monitoring_rendering = validate_monitoring_rendering(stack_documents, spec["monitoring"])
        data_service_rendering = validate_data_service_rendering(stack_documents, spec["data_services"])
        hook_inventory = rendered_hook_inventory(stack_documents, namespace)
        all_rendered_images = set(validate_rendered_images(stack_documents, spec["environment"] == "production" or spec["air_gap"].get("enabled") is True))
        if b"kind: Secret" not in rendered and b"kind:\n  Secret" not in rendered:
            # Not all releases render native Secrets, so this remains informational.
            pass
        # Shared/preinstalled CRDs support a full non-persisting API-server
        # admission review. Dedicated install cannot validate dependent CRs
        # before the external CRD handoff, so it stays explicitly incomplete.
        if namespace_uid != "absent" and (spec["crds"]["mode"] == "shared" or action != "install"):
            run_checked(kube + ["apply", "--dry-run=server", "--namespace", namespace, "-f", "-"], env, stdin=rendered)

        galileoctl_privileged = False
        ctl_documents: list[dict[str, Any]] = []
        ctl_rendered = b""
        ctl_secret_contract_sha256 = ""
        ctl_secret_payload_shape_sha256 = ""
        ctl_secret_influence: dict[str, list[str]] = {}
        ctl_nonsecret_document: dict[str, Any] | None = None
        ctl_secret_document: dict[str, Any] | None = None
        if spec["galileoctl"].get("enabled"):
            ctl_chart = snapshot_file(bundle / spec["galileoctl"]["chart_archive"], temp / "galileoctl.tgz", "bundled galileoctl chart")
            ctl_values = snapshot_file(bundle / spec["galileoctl"]["nonsecret_values_file"], temp / "galileoctl-values.yaml", "bundled galileoctl values")
            ctl_secret_snapshot = snapshot_file(ctl_secret, temp / "galileoctl-secret-values.yaml", "runtime galileoctl secret values", private=True)
            ctl_nonsecret_document = validate_values_no_secrets(ctl_values)
            ctl_secret_document = validate_runtime_secret_values(
                ctl_secret_snapshot,
                "galileoctl runtime Secret values",
                spec["galileoctl"]["runtime_secret_value_paths"],
            )
            assert_snapshot_digest(ctl_chart, spec["galileoctl"]["chart_sha256"], "galileoctl chart")
            assert_snapshot_digest(ctl_values, manifest_files[spec["galileoctl"]["nonsecret_values_file"]], "galileoctl non-secret values")
            ctl_rendered = run_checked(helm_cmd + ["template", spec["galileoctl"]["release_name"], str(ctl_chart), "--namespace", namespace, "-f", str(ctl_values), "-f", str(ctl_secret_snapshot), "--skip-crds", "--post-renderer", str(retention_helper), "--kube-version", kubernetes_version], env, process_timeout=helm_process_timeout(spec["stack"]["timeout"]))
            ctl_changed_payload_owner: dict[str, str] = {}
            for index, secret_path in enumerate(
                spec["galileoctl"]["runtime_secret_value_paths"]
            ):
                shadow_path = temp / f"galileoctl-secret-shadow-{index}.yaml"
                write_private(
                    shadow_path,
                    yaml_bytes(
                        shadow_secret_values(
                            ctl_secret_document,
                            only_path=secret_path,
                        )
                    ),
                )
                shadow_rendered = run_checked(
                    helm_cmd
                    + [
                        "template",
                        spec["galileoctl"]["release_name"],
                        str(ctl_chart),
                        "--namespace",
                        namespace,
                        "-f",
                        str(ctl_values),
                        "-f",
                        str(shadow_path),
                        "--skip-crds",
                        "--post-renderer",
                        str(retention_helper),
                        "--kube-version",
                        kubernetes_version,
                    ],
                    env,
                    process_timeout=helm_process_timeout(spec["stack"]["timeout"]),
                )
                shape_digest, changed_paths = validate_secret_leaf_influence(
                    ctl_rendered,
                    shadow_rendered,
                    f"galileoctl runtime-secret leaf {secret_path}",
                )
                if (
                    ctl_secret_payload_shape_sha256
                    and shape_digest != ctl_secret_payload_shape_sha256
                ):
                    fail(
                        "galileoctl runtime-secret leaf renders do not share one "
                        "canonical Secret payload shape"
                    )
                ctl_secret_payload_shape_sha256 = shape_digest
                for changed_path in changed_paths:
                    if changed_path in ctl_changed_payload_owner:
                        fail(
                            "galileoctl runtime-secret leaf influence overlaps another "
                            "leaf; obtain an exact CSE many-to-one derivation contract"
                        )
                    ctl_changed_payload_owner[changed_path] = secret_path
                ctl_secret_influence[secret_path] = changed_paths
            ctl_secret_contract_sha256 = sha256_bytes(
                json_bytes({
                    "paths": spec["galileoctl"]["runtime_secret_value_paths"],
                    "payload_shape_sha256": ctl_secret_payload_shape_sha256,
                    "influence": ctl_secret_influence,
                })
            )
            ctl_documents = rendered_documents(ctl_rendered, "galileoctl")
            validate_rendered_scope(ctl_documents, namespace, api_scopes)
            installer_permission_plan.extend(
                validate_rendered_cluster_permissions(
                    ctl_documents, kube, env, api_resources, namespace
                )
            )
            rendered_node_placements.extend(validate_node_pool_rendering(ctl_documents, spec))
            retained_resources.extend(validate_retention_rendered(ctl_documents))
            expected_claims.extend(rendered_claims(ctl_documents, spec["storage"], spec["environment"]))
            all_rendered_images.update(validate_rendered_images(ctl_documents, spec["environment"] == "production" or spec["air_gap"].get("enabled") is True))
            ctl_claims = rendered_claims(
                ctl_documents,
                spec["storage"],
                spec["environment"],
            )
            galileoctl_rendering = validate_galileoctl_render(
                ctl_documents,
                spec["galileoctl"],
                ctl_claims,
            )
            for document in ctl_documents:
                if document.get("kind") in {"ClusterRole", "ClusterRoleBinding"}:
                    galileoctl_privileged = True
                if document.get("kind") in {"Role", "ClusterRole"}:
                    for rule in document.get("rules", []):
                        resources = rule.get("resources", []) if isinstance(rule, dict) else []
                        if any(resource in {"secrets", "pods/exec", "*"} for resource in resources):
                            galileoctl_privileged = True
            if namespace_uid != "absent":
                run_checked(kube + ["apply", "--dry-run=server", "--namespace", namespace, "-f", "-"], env, stdin=ctl_rendered)
        else:
            galileoctl_rendering = {"enabled": False}
        live_routing: dict[str, Any] | None = None
        routing_prerequisites: dict[str, Any] | None = None
        if spec["environment"] == "production":
            if namespace_uid == "absent":
                fail("production install requires a pre-created reviewed namespace")
            if routing.get("load_balancer_lifecycle") == "external-preinstalled":
                routing_prerequisites = validate_routing_prerequisites(
                    kube, env, namespace, routing, temp
                )
            else:
                routing_prerequisites = {
                    "state": "release-managed-staged-handoff",
                    "validated": False,
                    "reason": (
                        "LoadBalancer address, TLS Secret, and DNS convergence are "
                        "post-install observations for this reviewed lifecycle."
                    ),
                }
            if action == "install":
                # Release-owned routing objects do not exist before a fresh
                # External installation has not created these identities yet;
                # a later read-only observation must bind exact UIDs/owners.
                live_routing = {"state": "post-apply-required", "resources": []}
            else:
                routing_release_names = {spec["stack"]["release_name"]}
                if spec["galileoctl"]["enabled"]:
                    routing_release_names.add(spec["galileoctl"]["release_name"])
                live_routing = validate_live_routing(
                    kube,
                    env,
                    namespace,
                    routing,
                    rendered_routing,
                    routing_release_names,
                    temp,
                )
        if spec["air_gap"].get("enabled"):
            contract_path = bundle / spec["air_gap"]["verified_contract_file"]
            contract_bytes = secure_read(contract_path, "bundled air-gap contract", private=True)[1]
            if sha256_bytes(contract_bytes) != spec["air_gap"]["verified_contract_sha256"]:
                fail("bundled air-gap contract digest differs from the deployment spec")
            try:
                contract_document = json.loads(contract_bytes)
            except json.JSONDecodeError:
                fail("bundled air-gap contract is invalid JSON")
            validate_air_gap_contract(
                contract_document,
                spec,
                None,
                {
                    "stack_nonsecret_values_sha256": manifest_files[spec["stack"]["nonsecret_values_file"]],
                    "galileoctl_nonsecret_values_sha256": (
                        manifest_files[spec["galileoctl"]["nonsecret_values_file"]]
                        if spec["galileoctl"]["enabled"] else ""
                    ),
                },
            )

    state_dir = bundle.parent / ".state" / manifest["bundle_sha256"]
    ensure_private_directory(state_dir, bundle.parent)
    now = utc_now()
    resource_inventory = rendered_resource_inventory(
        [(spec["stack"]["release_name"], stack_documents)]
        + ([(spec["galileoctl"]["release_name"], ctl_documents)] if ctl_documents else []),
        expected_claims,
        rendered_routing,
        spec,
        manifest["bundle_sha256"],
        api_scopes,
        bundle / "contracts" / "deployment-feature-matrix.json",
    )
    resource_inventory_bytes = json_bytes(resource_inventory)
    bundled_runtime_inventory = assert_mapping(
        json.loads(secure_read(bundle / "runtime-inventory.json", "bundled runtime inventory")[1]),
        "bundled runtime inventory",
    )
    matrix_document = assert_mapping(
        json.loads(
            secure_read(
                bundle / "contracts" / "deployment-feature-matrix.json",
                "bundled Stack feature matrix",
            )[1]
        ),
        "bundled Stack feature matrix",
    )
    runtime_by_class: dict[str, list[str]] = {}
    for item_value in bundled_runtime_inventory.get("items", []):
        item = assert_mapping(item_value, "bundled runtime inventory item")
        runtime_by_class.setdefault(str(item.get("classification_id", "")), []).append(
            str(item.get("id", ""))
        )
    feature_ledger: list[dict[str, Any]] = []
    for feature_value in matrix_document.get("features", []):
        feature = assert_mapping(feature_value, "Stack feature matrix row")
        if "galileo-on-prem-stack-setup" not in feature.get("owners", []):
            continue
        feature_id = str(feature.get("id", ""))
        runtime_ids = sorted(runtime_by_class.get(feature_id, []))
        applicability = "enabled-or-present" if runtime_ids else "handoff-or-not-present"
        feature_ledger.append({
            "id": feature_id,
            "applicability": applicability,
            "disposition": "observed-incomplete" if runtime_ids else "cse-handoff",
            "runtime_inventory_item_ids": runtime_ids,
            "evidence_artifact_ids": ["runtime-inventory.json"] if runtime_ids else [],
            "unresolved_gaps": [
                f"feature_disposition_requires_cse_review:{feature_id}"
            ],
            "source_urls": sorted(
                str(value)
                for value in feature.get("source_urls", [])
                if isinstance(value, str) and value
            ),
        })
    feature_ledger.sort(key=lambda row: row["id"])
    expected_owned_ids = sorted(
        str(feature.get("id", ""))
        for feature in matrix_document.get("features", [])
        if isinstance(feature, dict)
        and "galileo-on-prem-stack-setup" in feature.get("owners", [])
    )
    if [row["id"] for row in feature_ledger] != expected_owned_ids:
        fail("full Stack feature coverage ledger omits or reorders owned matrix IDs")
    unresolved_gates = [
        "external_cse_authorization_required",
        "live_release_provenance_receipt_missing",
        "route_backend_contract_missing",
        "tls_cryptographic_handshake_evidence_missing",
        "monitoring_semantic_smoke_evidence_missing",
        "object_storage_bucket_policy_evidence_missing",
        "secret_endpoint_contract_missing",
        "rendered_secret_payload_classification_incomplete",
        "persistent_claim_provenance_incomplete",
        "cse_values_contract_missing",
    ]
    unresolved_gates.extend(
        gap
        for row in feature_ledger
        for gap in row["unresolved_gaps"]
    )
    if namespace_uid == "absent" or spec["target"].get("namespace_create"):
        unresolved_gates.append("namespace_creation_handoff_required")
    if spec["crds"]["mode"] == "dedicated":
        unresolved_gates.append("crd_install_handoff_required")
    if any(item.get("source_class") == "rendered-template" for item in active_crd_inventory):
        unresolved_gates.append("templated_crd_operator_handoff_required")
    if spec["wizard"].get("gpu_enabled"):
        unresolved_gates.append("wizard_workload_binding_incomplete")
        unresolved_gates.append("nvidia_device_plugin_readiness_unvalidated")
    if spec["wizard"].get("enabled"):
        unresolved_gates.append("stack_model_evidence_missing")
    if spec["air_gap"].get("enabled"):
        unresolved_gates.extend(
            [
                "endpoint_rewrite_evidence_missing",
                "architecture_workload_binding_missing",
            ]
        )
    if spec["routing"].get("load_balancer_lifecycle") == "release-managed-staged-handoff":
        unresolved_gates.extend(
            [
                "lb_address_pending_post_install",
                "tls_secret_pending_post_install",
                "dns_pending_post_install",
            ]
        )
    method_gap = {
        "galileoctl": "galileoctl_ui_cli_method_artifact_and_CSE_review_missing",
        "deployment-script": "deployment_script_artifact_hash_and_static_review_missing",
        "step-by-step": "step_by_step_ordered_chart_contract_missing",
    }.get(spec["installation_method"])
    if method_gap:
        unresolved_gates.append(method_gap)
    unresolved_gates = sorted(set(unresolved_gates))
    evidence = {
        "schema_version": 1,
        "action": action,
        "bundle_sha256": manifest["bundle_sha256"],
        "helm_version": helm_version,
        "kubernetes_version_raw": kubernetes_version_raw,
        "kubernetes_version": kubernetes_version,
        "created_at": utc_text(now),
        "expires_at": utc_text(now + dt.timedelta(minutes=30)),
        "target": {"context": spec["target"]["kube_context"], "api_server": spec["target"]["api_server"], "ca_sha256": spec["target"]["ca_sha256"], "cluster_uid": spec["target"]["cluster_uid"], "namespace": namespace, "namespace_uid": namespace_uid},
        "secret_contract_sha256": secret_contract_sha256,
        "secret_payload_shape_sha256": secret_payload_shape_sha256,
        "secret_influence": secret_influence,
        "galileoctl_secret_contract_sha256": (
            ctl_secret_contract_sha256 if ctl_secret else ""
        ),
        "galileoctl_secret_payload_shape_sha256": (
            ctl_secret_payload_shape_sha256 if ctl_secret else ""
        ),
        "galileoctl_secret_influence": ctl_secret_influence,
        "release_present": bool(releases),
        "release_version": release_version(releases[0], "galileo-stack") if releases else "",
        "release_mode": release_mode,
        "galileoctl_release_present": bool(ctl_releases),
        "galileoctl_release_version": release_version(ctl_releases[0], "galileoctl") if ctl_releases else "",
        "galileoctl_release_mode": ctl_release_mode,
        "galileoctl_privileged": galileoctl_privileged,
        "galileoctl_rendering": galileoctl_rendering,
        "retained_resources": sorted(set(retained_resources)),
        "expected_claims": sorted(expected_claims, key=lambda item: (item["source"], item["name"])),
        "rendered_images": sorted(all_rendered_images),
        "observed_node_pools": observed_node_pools,
        "rendered_node_placements": sorted(rendered_node_placements, key=lambda item: item["workload"]),
        "rendered_routing": rendered_routing,
        "live_routing": live_routing,
        "routing_prerequisites": routing_prerequisites,
        "rendered_resource_inventory_sha256": sha256_bytes(resource_inventory_bytes),
        "wizard_rendering": wizard_rendering,
        "monitoring_rendering": monitoring_rendering,
        "data_service_rendering": data_service_rendering,
        "hook_inventory": hook_inventory,
        "active_crds": active_crd_inventory,
        "api_scopes_sha256": sha256_bytes(json_bytes(api_scopes)),
        "crd_upgrade_inventory": sorted(crd_upgrade_inventory, key=lambda item: item["name"]),
        "installer_permission_plan": sorted(
            installer_permission_plan,
            key=lambda item: (item["gvk"], item["namespace"]),
        ),
        "unresolved_gates": unresolved_gates,
        "feature_coverage_ledger": feature_ledger,
    }
    validate_rendered_secret_placement(stack_documents + ctl_documents)
    image_items = rendered_image_items(
        stack_documents,
        spec["stack"]["release_name"],
        spec,
    )
    if ctl_documents:
        image_items.extend(
            rendered_image_items(
                ctl_documents,
                spec["galileoctl"]["release_name"],
                spec,
            )
        )
    image_items.sort(key=lambda item: (item["release"], item["source_object"], item["container_type"], item["container"], item["image"]))
    redacted_manifest_bytes = canonical_redacted_manifest(
        stack_documents + ctl_documents
    )
    image_inventory = {
        "schema": IMAGE_EVIDENCE_SCHEMA,
        "generated_by": "galileo-on-prem-stack-setup",
        "source_bundle_sha256": manifest["bundle_sha256"],
        "charts": [{
            "name": "galileo-stack",
            "release": spec["stack"]["release_name"],
            "version": spec["stack"]["chart_version"],
            "sha256": spec["stack"]["chart_sha256"],
        }] + ([{
            "name": "galileoctl",
            "release": spec["galileoctl"]["release_name"],
            "version": spec["galileoctl"]["chart_version"],
            "sha256": spec["galileoctl"]["chart_sha256"],
        }] if spec["galileoctl"]["enabled"] else []),
        "inputs": {
            "stack_nonsecret_values_sha256": manifest_files[spec["stack"]["nonsecret_values_file"]],
            "stack_secret_contract_sha256": secret_contract_sha256,
            "galileoctl_nonsecret_values_sha256": (
                manifest_files[spec["galileoctl"]["nonsecret_values_file"]]
                if spec["galileoctl"]["enabled"] else ""
            ),
            "galileoctl_secret_contract_sha256": ctl_secret_contract_sha256,
        },
        # This digest cannot verify guessed credentials: every Secret payload
        # scalar is replaced by a fixed identity/path marker first.
        "redacted_render_sha256": sha256_bytes(redacted_manifest_bytes),
        "target": {
            "context": spec["target"]["kube_context"],
            "api_server": spec["target"]["api_server"],
            "ca_sha256": spec["target"]["ca_sha256"],
            "kube_system_uid": spec["target"]["cluster_uid"],
            "namespace": namespace,
            "namespace_uid": namespace_uid,
        },
        "created_at": evidence["created_at"],
        "items": image_items,
    }
    image_inventory_bytes = json_bytes(image_inventory)
    if spec["air_gap"].get("enabled"):
        validate_air_gap_contract(contract_document, spec, image_inventory)
    evidence["rendered_image_inventory_sha256"] = sha256_bytes(image_inventory_bytes)
    validate_rendered_image_evidence(image_inventory, image_inventory_bytes, spec, manifest, evidence)
    endpoint_items = rendered_endpoint_items(
        [(spec["stack"]["release_name"], stack_documents)]
        + ([(spec["galileoctl"]["release_name"], ctl_documents)] if ctl_documents else []),
        [(spec["stack"]["release_name"], stack_nonsecret_document)]
        + ([(spec["galileoctl"]["release_name"], ctl_nonsecret_document)] if ctl_nonsecret_document is not None else []),
    )
    endpoint_inventory = endpoint_inventory_evidence(image_inventory, endpoint_items)
    endpoint_inventory_bytes = json_bytes(endpoint_inventory)
    validate_endpoint_inventory_evidence(endpoint_inventory, endpoint_inventory_bytes)
    evidence["rendered_endpoint_inventory_sha256"] = sha256_bytes(endpoint_inventory_bytes)
    handoff = {
        "schema": "galileo-on-prem-stack-handoff-candidate/v1",
        "generated_by": "galileo-on-prem-stack-setup",
        "authorized": False,
        "production_ready": False,
        "action": action,
        "bundle_sha256": manifest["bundle_sha256"],
        "chart": {
            "name": "galileo-stack",
            "version": spec["stack"]["chart_version"],
            "sha256": spec["stack"]["chart_sha256"],
        },
        "inputs": image_inventory["inputs"],
        "target": evidence["target"],
        "helm_version": helm_version,
        "kubernetes_version_raw": kubernetes_version_raw,
        "kubernetes_version": kubernetes_version,
        "redacted_render_sha256": image_inventory["redacted_render_sha256"],
        "redacted_manifest_sha256": sha256_bytes(redacted_manifest_bytes),
        "resource_inventory_sha256": sha256_bytes(resource_inventory_bytes),
        "image_inventory_sha256": sha256_bytes(image_inventory_bytes),
        "endpoint_inventory_sha256": sha256_bytes(endpoint_inventory_bytes),
        "active_crds": active_crd_inventory,
        "crd_mode": spec["crds"]["mode"],
        "secret_influence": secret_influence,
        "galileoctl_secret_influence": ctl_secret_influence,
        "galileoctl_rendering": galileoctl_rendering,
        "hook_inventory": hook_inventory,
        "installer_permission_plan": evidence["installer_permission_plan"],
        "unresolved_gates": unresolved_gates,
        "feature_coverage_ledger": feature_ledger,
        # No executable argv is emitted while required evidence remains open.
        # This avoids accidentally substituting Helm for galileoctl/script/
        # step-by-step ownership or constructing unsafe action-specific syntax.
        "operator_command_argv": None,
        "operator_command_reason": "unresolved_gates_require_method_and_action_specific_Galileo_CSE_command",
        "operator_command_executed": False,
        "required_external_approval": {
            "galileo_cse": True,
            "joint_session": True,
            "authenticated_by_this_skill": False,
        },
        "post_install_read_only_commands": [],
        "post_install_command_reason": (
            "No executable observation argv is emitted until a signed/adopted release receipt "
            "binds the exact live Helm revision and release-owned object identities."
        ),
        "warnings": [
            "No automatic rollback or cleanup is performed.",
            "Never delete PVCs, PVs, CRDs, buckets, databases, queues, or the namespace without a separate reviewed recovery decision.",
        ],
    }
    handoff_bytes = json_bytes(handoff)
    evidence["handoff_candidate_sha256"] = sha256_bytes(handoff_bytes)
    evidence_bytes = json_bytes(evidence)
    artifacts: tuple[tuple[str, bytes], ...] = (
        ("rendered-image-inventory-evidence.json", image_inventory_bytes),
        ("rendered-endpoint-inventory-evidence.json", endpoint_inventory_bytes),
        ("rendered-resource-inventory-evidence.json", resource_inventory_bytes),
        ("rendered-manifest-redacted.yaml", redacted_manifest_bytes),
        ("handoff-candidate.json", handoff_bytes),
        ("preflight.json", evidence_bytes),
        ("release-contract.json", json_bytes(release_contract(spec, manifest["bundle_sha256"], namespace_uid))),
    )
    generation_id, generation_dir = commit_evidence_generation(
        state_dir,
        manifest["bundle_sha256"],
        evidence["created_at"],
        artifacts,
    )
    return {
        "action": "preflight",
        "state": "preflight-incomplete" if unresolved_gates else "evidence-complete-handoff-required",
        "production_ready": False,
        "authorized": False,
        "unresolved_gates": unresolved_gates,
        "for_action": action,
        "bundle_sha256": manifest["bundle_sha256"],
        "expires_at": evidence["expires_at"],
        "evidence_generation": generation_id,
        "generation_manifest": str(generation_dir / "generation-manifest.json"),
        "release_contract": str(generation_dir / "release-contract.json"),
        "rendered_image_inventory": str(generation_dir / "rendered-image-inventory-evidence.json"),
        "rendered_endpoint_inventory": str(generation_dir / "rendered-endpoint-inventory-evidence.json"),
        "rendered_resource_inventory": str(generation_dir / "rendered-resource-inventory-evidence.json"),
        "redacted_manifest": str(generation_dir / "rendered-manifest-redacted.yaml"),
        "handoff_candidate": str(generation_dir / "handoff-candidate.json"),
    }



def load_exact_plan(bundle: Path, bundle_sha: str, action: str) -> dict[str, Any]:
    path = bundle.parent / ".state" / bundle_sha / f"{action}-plan.json"
    try:
        plan = assert_mapping(json.loads(secure_read(path, f"{action} plan", private=True)[1]), f"{action} plan")
    except json.JSONDecodeError:
        fail(f"a valid {action} plan is required")
    reject_secret_like_scalars(plan, f"{action} plan")
    base = {"schema_version", "action", "bundle_sha256", "release", "namespace", "data_deletion", "automatic_rollback"}
    if action == "rollback" and plan.get("strategy") == "previous-immutable-bundle":
        expected = base | {"strategy", "previous_bundle_sha256", "previous_chart"}
    elif action == "rollback" and plan.get("strategy") == "emergency-helm-revision":
        expected = base | {"strategy", "revision"}
    elif action == "uninstall":
        expected = base | {"execution", "reason", "retained_resources", "hooks_or_migrations"}
    else:
        fail(f"{action} plan strategy is invalid")
    if set(plan) != expected or plan.get("schema_version") != 1 or isinstance(plan.get("schema_version"), bool) or plan.get("action") != action or plan.get("bundle_sha256") != bundle_sha:
        fail(f"{action} plan binding differs")
    if plan.get("data_deletion") is not False or plan.get("automatic_rollback") is not False:
        fail(f"{action} plan safety flags differ")
    return plan


def helm_action(args: argparse.Namespace, action: str) -> dict[str, Any]:
    """Permanent fail-closed compatibility sentinel for historical callers."""
    fail(
        f"automated apply-{action} is disabled; use render plus connected read-only preflight "
        "evidence in a Galileo/CSE joint-session deployment handoff"
    )


def status(args: argparse.Namespace) -> dict[str, Any]:
    bundle = lexical_absolute(args.bundle)
    manifest, spec = verify_bundle(bundle)
    if console_url(args.galileo_console_url) != spec["galileo_console_url"]:
        fail("--galileo-console-url does not match the bundle")
    kubeconfig_source = kubeconfig_path(args.kubeconfig)
    validate_kubeconfig_auth(kubeconfig_source, spec["target"]["kube_context"])
    helm = resolve_executable(args.helm_bin, "helm")
    kubectl = resolve_executable(args.kubectl_bin, "kubectl")
    with tempfile.TemporaryDirectory(prefix=".galileo-stack-status-", dir=bundle.parent) as temp_name:
        temp = Path(temp_name)
        os.chmod(temp, 0o700)
        env = minimal_env(temp)
        kubeconfig = snapshot_kubeconfig(kubeconfig_source, temp)
        context = spec["target"]["kube_context"]
        validate_kubeconfig_auth(kubeconfig, context)
        kube = kubectl_base(kubectl, kubeconfig, context)
        helm_cmd = helm_base(helm, kubeconfig, context)
        server, ca_hash = kubeconfig_binding(kubeconfig, context)
        system = parse_json_bytes(run_checked(kube + ["get", "namespace", "kube-system", "-o", "json"], env), "kube-system")
        system_uid = str(system.get("metadata", {}).get("uid", ""))
        if server != spec["target"]["api_server"].rstrip("/") or ca_hash != spec["target"]["ca_sha256"] or system_uid != spec["target"]["cluster_uid"]:
            fail("status target identity differs from the reviewed bundle")
        namespace_probe = run_checked(kube + ["get", "namespace", spec["target"]["namespace"], "--ignore-not-found", "-o", "json"], env)
        namespace_uid = str(parse_json_bytes(namespace_probe, "namespace").get("metadata", {}).get("uid", "")) if namespace_probe.strip() else "absent"
        expected_namespace_uid = spec["target"].get("namespace_uid") or "absent"
        if namespace_uid != expected_namespace_uid:
            fail("status namespace UID/presence differs from the reviewed bundle")
        releases = release_inventory(helm_cmd, env, spec["target"]["namespace"], spec["stack"]["release_name"])
        if releases and release_version(releases[0], "galileo-stack") != spec["stack"]["chart_version"]:
            fail("status found a different Stack chart/version")
        ctl_release: dict[str, Any] | None = None
        if spec["galileoctl"]["enabled"]:
            ctl_releases = release_inventory(helm_cmd, env, spec["target"]["namespace"], spec["galileoctl"]["release_name"])
            if ctl_releases and release_version(ctl_releases[0], "galileoctl") != spec["galileoctl"]["chart_version"]:
                fail("status found a different galileoctl chart/version")
            ctl_release = ctl_releases[0] if ctl_releases else None
        routing_observation: dict[str, Any] | None = None
        exact_live_pvcs: list[str] | None = None
        if spec["environment"] == "production":
            state_dir = bundle.parent / ".state" / manifest["bundle_sha256"]
            if args.evidence_generation:
                generation = verified_evidence_generation(
                    state_dir,
                    args.evidence_generation,
                    manifest["bundle_sha256"],
                )
                preflight_path = generation / "preflight.json"
                try:
                    preflight_raw = secure_read(preflight_path, "status preflight evidence", private=True)[1]
                    preflight_document = assert_mapping(json.loads(preflight_raw), "status preflight evidence")
                except json.JSONDecodeError:
                    fail("production status preflight evidence is invalid JSON")
                if (
                    preflight_document.get("bundle_sha256") != manifest["bundle_sha256"]
                    or not isinstance(preflight_document.get("rendered_routing"), dict)
                    or not isinstance(preflight_document.get("expected_claims"), list)
                ):
                    fail("production status preflight inventory binding differs from the reviewed bundle")
                # Preflight evidence describes an intended render, not proof
                # that an externally executed installation is that render.
                # Keep it available for diagnostics without promoting status.
                routing_observation = {"evidence_available": True, "live_provenance_verified": False}
                exact_live_pvcs = []
        # Do not enumerate namespace-wide objects: a shared namespace can hold
        # unrelated workloads, and this release has no authenticated adoption
        # receipt binding exact live UIDs/specs to the reviewed render.
        resources: dict[str, Any] = {
            "available": False,
            "reason": "resource_inventory_unavailable_without_verified_release_provenance",
            "items": [],
        }
    # Namespace-wide resources may belong to unrelated releases. Without an
    # exact release-owned rendered/live inventory and application smoke test,
    # observation must never be promoted to postdeploy-healthy.
    return {
        "action": "status",
        "state": release_observation_state(releases, spec["galileoctl"]["enabled"], ctl_release),
        "production_ready": False,
        "application_smoke_validated": False,
        "release": releases[0] if releases else None,
        "galileoctl_release": ctl_release,
        "routing": routing_observation,
        "release_owned_pvcs": exact_live_pvcs,
        "resources": resources,
    }


def plan_action(args: argparse.Namespace, action: str) -> dict[str, Any]:
    bundle = lexical_absolute(args.bundle)
    manifest, spec = verify_bundle(bundle)
    state_dir = bundle.parent / ".state" / manifest["bundle_sha256"]
    ensure_private_directory(state_dir, bundle.parent)
    plan: dict[str, Any] = {"schema_version": 1, "action": action, "bundle_sha256": manifest["bundle_sha256"], "release": spec["stack"]["release_name"], "namespace": spec["target"]["namespace"], "data_deletion": False, "automatic_rollback": False}
    if action == "rollback":
        plan.update({
            "execution": "manual-handoff-only",
            "reason": (
                "No executable rollback is emitted: the exact prior Helm revision, chart, values, "
                "secret-path influence contract, CRDs, migrations, routes, and persistent-data recovery evidence "
                "must be rebound in a Galileo/CSE joint session."
            ),
            "required_bindings": [
                "prior_release_revision",
                "prior_chart_archive_sha256",
                "prior_nonsecret_values_sha256",
                "prior_runtime_secret_contract",
                "prior_redacted_manifest_sha256",
                "crd_compatibility",
                "persistent_data_restore_point",
                "route_and_tls_contract",
            ],
            "operator_command_argv": None,
            "authorized": False,
        })
    else:
        inventory = json.loads(secure_read(bundle / "chart-inventory.json", "bundled chart inventory", private=True)[1])
        plan.update({
            "execution": "manual-handoff-only",
            "reason": "Automated Helm uninstall is disabled until exact-chart integration proves release-owned PVC and StatefulSet claim retention across uninstall and all hooks.",
            "retained_resources": ["namespace", "PVCs", "PVs", "CRDs", "buckets", "external databases"],
            "hooks_or_migrations": inventory["stack"].get("hooks_or_migrations", []),
        })
    destination = state_dir / f"{action}-plan.json"
    temp_path = state_dir / f".{action}-plan.tmp"
    if temp_path.exists():
        temp_path.unlink()
    write_private(temp_path, json_bytes(plan))
    os.replace(temp_path, destination)
    return {"action": f"plan-{action}", "state": "planned", "plan": str(destination), **plan}


def rollback(args: argparse.Namespace) -> dict[str, Any]:
    """Fail-closed sentinel; rollback is a reviewed external recovery handoff."""
    fail(
        "automated rollback is disabled; use the reviewed Galileo/CSE manual recovery handoff"
    )

def uninstall(args: argparse.Namespace) -> dict[str, Any]:
    fail(
        "automated uninstall is disabled; use the retention-safe Galileo/CSE retirement handoff"
    )


def validate_microk8s_cli_target(
    microk8s: str,
    env: dict[str, str],
    temp: Path,
    expected_server: str,
    expected_ca_sha256: str,
    expected_cluster_uid: str,
) -> None:
    raw = run_checked([microk8s, "config"], env, limit=4 * 1024 * 1024)
    try:
        config = assert_mapping(strict_yaml_load(raw.decode("utf-8")), "MicroK8s CLI kubeconfig")
    except (UnicodeError, yaml.YAMLError):
        fail("MicroK8s CLI returned an invalid kubeconfig")
    context = config.get("current-context")
    if not isinstance(context, str) or not context:
        fail("MicroK8s CLI kubeconfig lacks current-context")
    path = temp / "microk8s-cli-kubeconfig"
    write_private(path, yaml_bytes(config))
    server, ca_sha256 = kubeconfig_binding(path, context)
    system = parse_json_bytes(
        run_checked([microk8s, "kubectl", "get", "namespace", "kube-system", "-o", "json"], env),
        "MicroK8s CLI kube-system",
    )
    if (
        server != expected_server
        or ca_sha256 != expected_ca_sha256
        or str(system.get("metadata", {}).get("uid", "")) != expected_cluster_uid
    ):
        fail("local MicroK8s CLI target differs from the reviewed kubectl target")


def address_interval(value: str) -> tuple[int, int, int]:
    text = value.strip()
    try:
        if "-" in text:
            start_text, end_text = text.split("-", 1)
            start, end = ipaddress.ip_address(start_text), ipaddress.ip_address(end_text)
            if start.version != end.version or int(start) > int(end):
                raise ValueError
            return start.version, int(start), int(end)
        network = ipaddress.ip_network(text, strict=False)
        return network.version, int(network.network_address), int(network.broadcast_address)
    except ValueError:
        fail(f"invalid address/range/CIDR evidence: {value}")


def intervals_overlap(left: tuple[int, int, int], right: tuple[int, int, int]) -> bool:
    return left[0] == right[0] and max(left[1], right[1]) <= min(left[2], right[2])


def validate_metallb_nonoverlap(
    pool: str,
    nodes: dict[str, Any],
    services: dict[str, Any],
    pods: dict[str, Any],
    existing_ranges: list[str],
    service_cidrs: list[str],
    pod_cidrs: list[str],
    evidence: str,
    evidence_observed_at: Any,
) -> dict[str, Any]:
    proposed = address_interval(pool)
    addresses: set[str] = set()
    for node in nodes.get("items", []):
        for item in node.get("status", {}).get("addresses", []):
            if item.get("type") in {"InternalIP", "ExternalIP"} and isinstance(item.get("address"), str):
                addresses.add(item["address"])
    for service in services.get("items", []):
        service_spec = service.get("spec", {})
        for value in [service_spec.get("clusterIP"), service_spec.get("loadBalancerIP"), *service_spec.get("clusterIPs", []), *service_spec.get("externalIPs", [])]:
            if isinstance(value, str) and value not in {"", "None"}:
                addresses.add(value)
        for item in service.get("status", {}).get("loadBalancer", {}).get("ingress", []):
            if isinstance(item, dict) and isinstance(item.get("ip"), str):
                addresses.add(item["ip"])
    for pod in pods.get("items", []):
        for value in [pod.get("status", {}).get("podIP"), *(item.get("ip") for item in pod.get("status", {}).get("podIPs", []) if isinstance(item, dict))]:
            if isinstance(value, str) and value:
                addresses.add(value)
    conflicting = sorted(
        value for value in addresses
        if intervals_overlap(proposed, address_interval(value))
    )
    overlapping_pools = sorted(
        value for value in existing_ranges
        if intervals_overlap(proposed, address_interval(value))
    )
    overlapping_cluster_cidrs = sorted(
        value for value in service_cidrs + pod_cidrs
        if intervals_overlap(proposed, address_interval(value))
    )
    observed = parse_time(evidence_observed_at, "spec.lab_bootstrap.network_evidence_observed_at")
    now = utc_now()
    if (
        conflicting
        or overlapping_pools
        or overlapping_cluster_cidrs
        or not evidence.strip()
        or observed > now + dt.timedelta(minutes=5)
        or observed < now - dt.timedelta(hours=24)
    ):
        fail("lab MetalLB range overlaps live addresses/pools or lacks fresh reviewed network non-overlap evidence")
    return {
        "pool": pool,
        "live_addresses_sha256": sha256_bytes(json_bytes(sorted(addresses))),
        "existing_ranges": sorted(existing_ranges),
        "service_cidrs": sorted(service_cidrs),
        "pod_cidrs": sorted(pod_cidrs),
        "network_evidence": evidence,
        "network_evidence_observed_at": utc_text(observed),
    }


def lab_action(args: argparse.Namespace, action: str) -> dict[str, Any]:
    """Render or observe a lab bootstrap; never mutate MicroK8s or nodes."""
    if action == "apply":
        mutation_handoff("apply-lab-bootstrap")
    if action == "render":
        result = render(Path(args.spec), args.galileo_console_url, Path(args.output_dir))
        result["action"] = "render-lab-bootstrap"
        return result
    if action != "preflight":
        fail("unsupported lab bootstrap action")

    bundle = lexical_absolute(args.bundle)
    manifest, spec = verify_bundle(bundle)
    lab = spec["lab_bootstrap"]
    if spec["environment"] != "lab" or lab.get("enabled") is not True:
        fail("lab bootstrap observation is limited to an explicitly enabled lab environment")
    check_keys(
        lab,
        {
            "enabled",
            "enable_hostpath_storage",
            "metallb_address_pool",
            "service_cidrs",
            "pod_cidrs",
            "network_nonoverlap_evidence",
            "network_evidence_observed_at",
            "node_labels",
        },
        "spec.lab_bootstrap",
    )
    labels = assert_mapping(lab.get("node_labels"), "spec.lab_bootstrap.node_labels")
    if any(value not in {"galileo-core", "galileo-runner", "galileo-ml"} for value in labels.values()):
        fail("lab node labels must use exact values galileo-core, galileo-runner, or galileo-ml")
    pool = lab.get("metallb_address_pool")
    if pool:
        try:
            start_text, end_text = str(pool).split("-", 1)
            start = ipaddress.ip_address(start_text)
            end = ipaddress.ip_address(end_text)
        except ValueError:
            fail("lab MetalLB pool must be an explicit start-end address range")
        if (
            start.version != end.version
            or int(start) > int(end)
            or start.is_loopback
            or start.is_multicast
            or end.is_multicast
        ):
            fail("lab MetalLB range is invalid")

    kubeconfig_source = kubeconfig_path(args.kubeconfig)
    validate_kubeconfig_auth(kubeconfig_source, spec["target"]["kube_context"])
    kubectl = resolve_executable(args.kubectl_bin, "kubectl")
    with tempfile.TemporaryDirectory(prefix=".galileo-lab-observe-", dir=bundle.parent) as temp_name:
        temp = Path(temp_name)
        os.chmod(temp, 0o700)
        env = minimal_env(temp)
        kubeconfig = snapshot_kubeconfig(kubeconfig_source, temp)
        context = spec["target"]["kube_context"]
        validate_kubeconfig_auth(kubeconfig, context)
        kube = kubectl_base(kubectl, kubeconfig, context)
        server, ca_hash = kubeconfig_binding(kubeconfig, context)
        system = parse_json_bytes(
            run_checked(kube + ["get", "namespace", "kube-system", "-o", "json"], env),
            "kube-system",
        )
        system_uid = str(system.get("metadata", {}).get("uid", ""))
        namespace_probe = run_checked(
            kube
            + [
                "get",
                "namespace",
                spec["target"]["namespace"],
                "--ignore-not-found",
                "-o",
                "json",
            ],
            env,
        )
        namespace_uid = (
            str(parse_json_bytes(namespace_probe, "namespace").get("metadata", {}).get("uid", ""))
            if namespace_probe.strip()
            else "absent"
        )
        expected_namespace_uid = spec["target"].get("namespace_uid") or "absent"
        if (
            server != spec["target"]["api_server"].rstrip("/")
            or ca_hash != spec["target"]["ca_sha256"]
            or system_uid != spec["target"]["cluster_uid"]
            or namespace_uid != expected_namespace_uid
        ):
            fail("lab bootstrap target or namespace identity differs from the reviewed bundle")
        nodes = parse_json_bytes(
            run_checked(kube + ["get", "nodes", "-o", "json"], env),
            "nodes",
        )
        existing = {
            str(item.get("metadata", {}).get("name", ""))
            for item in nodes.get("items", [])
        }
        if not set(labels).issubset(existing):
            fail("lab bootstrap node-label map names absent nodes")
        network_evidence: dict[str, Any] | None = None
        if pool:
            services = parse_json_bytes(
                run_checked(kube + ["get", "service", "--all-namespaces", "-o", "json"], env),
                "lab Services",
            )
            pods = parse_json_bytes(
                run_checked(kube + ["get", "pod", "--all-namespaces", "-o", "json"], env),
                "lab Pods",
            )
            api_resources = run_checked(
                kube + ["api-resources", "--api-group=metallb.io", "-o", "name"],
                env,
                limit=1024 * 1024,
            ).decode(errors="replace")
            existing_ranges: list[str] = []
            if "ipaddresspool" in api_resources.lower():
                pools_document = parse_json_bytes(
                    run_checked(
                        kube
                        + [
                            "get",
                            "ipaddresspools.metallb.io",
                            "--all-namespaces",
                            "-o",
                            "json",
                        ],
                        env,
                    ),
                    "MetalLB pools",
                )
                for item in pools_document.get("items", []):
                    existing_ranges.extend(
                        str(value)
                        for value in item.get("spec", {}).get("addresses", [])
                        if isinstance(value, str)
                    )
            network_evidence = validate_metallb_nonoverlap(
                str(pool),
                nodes,
                services,
                pods,
                existing_ranges,
                lab["service_cidrs"],
                lab["pod_cidrs"],
                lab["network_nonoverlap_evidence"],
                lab["network_evidence_observed_at"],
            )

    state_dir = bundle.parent / ".state" / manifest["bundle_sha256"]
    ensure_private_directory(state_dir, bundle.parent)
    now = utc_now()
    body = {
        "schema": "galileo-on-prem-stack-lab-observation/v1",
        "bundle_sha256": manifest["bundle_sha256"],
        "created_at": utc_text(now),
        "target": {
            "context": spec["target"]["kube_context"],
            "api_server": server,
            "ca_sha256": ca_hash,
            "cluster_uid": system_uid,
            "namespace_uid": namespace_uid,
        },
        "nodes": sorted(existing),
        "network": network_evidence,
        "state": "preflight-incomplete",
        "production_ready": False,
        "authorized": False,
        "unresolved_gates": [
            "lab_bootstrap_operator_handoff_required",
            "microk8s_target_and_addon_mutation_unperformed",
            "node_label_mutation_unperformed",
        ],
    }
    destination = state_dir / "lab-bootstrap-observation.json"
    temp_path = state_dir / ".lab-bootstrap-observation.tmp"
    if temp_path.exists():
        temp_path.unlink()
    write_private(temp_path, json_bytes(body))
    os.replace(temp_path, destination)
    return {
        "action": "preflight-lab-bootstrap",
        "state": "preflight-incomplete",
        "production_ready": False,
        "authorized": False,
        "bundle_sha256": manifest["bundle_sha256"],
        "evidence": str(destination),
        "unresolved_gates": body["unresolved_gates"],
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Galileo On-Prem Stack lifecycle (secret-safe, render-first)")
    actions = result.add_mutually_exclusive_group(required=True)
    for flag in ("inspect-chart", "render", "preflight", "apply-install", "apply-upgrade", "status", "plan-rollback", "apply-rollback", "plan-uninstall", "apply-uninstall", "render-lab-bootstrap", "preflight-lab-bootstrap", "apply-lab-bootstrap"):
        actions.add_argument(f"--{flag}", action="store_true")
    result.add_argument("--spec", default="")
    result.add_argument("--bundle", default="")
    result.add_argument("--output-dir", default="galileo-on-prem-rendered")
    result.add_argument("--galileo-console-url", default="", help="Exact Galileo instance console URL, for example https://console.demo-v2.galileocloud.io/")
    result.add_argument("--secret-values-file", default="")
    result.add_argument("--galileoctl-secret-values-file", default="")
    result.add_argument("--approval-file", default="")
    result.add_argument("--previous-bundle", default="")
    result.add_argument("--revision", default="")
    result.add_argument(
        "--evidence-generation",
        default="",
        help="Exact immutable preflight generation ID for status correlation",
    )
    result.add_argument("--for-action", default="install")
    result.add_argument("--yes-release", default="")
    result.add_argument("--yes-namespace", default="")
    result.add_argument("--kubeconfig", default="")
    result.add_argument("--helm-bin", default="helm", help="Single executable name/path; command strings are rejected")
    result.add_argument("--kubectl-bin", default="kubectl", help="Single executable name/path; command strings are rejected")
    result.add_argument("--microk8s-bin", default="microk8s", help="Single MicroK8s executable name/path")
    for flag in ("accept-install", "accept-upgrade", "accept-rollback", "accept-uninstall", "accept-namespace-create", "accept-cluster-wide-crds", "accept-privileged-galileoctl", "accept-emergency-helm-revision", "accept-retain-data", "accept-nonproduction-bootstrap"):
        result.add_argument(f"--{flag}", action="store_true")
    result.add_argument("--json", action="store_true")
    return result


def mutation_handoff(action: str) -> dict[str, Any]:
    """Permanent fail-closed entry point for every advertised apply flag.

    Keeping the historical flags as explicit sentinels prevents older runbooks
    from falling through to a different action while guaranteeing that no
    bundle, state directory, executable, kubeconfig, or subprocess is touched.
    """
    fail(
        f"{action} is handoff-only: this skill performs no Helm, Kubernetes, "
        "MicroK8s, node-label, CRD, rollback, or uninstall mutation; use the "
        "canonical render/preflight evidence in a Galileo/CSE joint session"
    )


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        for selected, name in (
            (args.apply_install, "apply-install"),
            (args.apply_upgrade, "apply-upgrade"),
            (args.apply_rollback, "apply-rollback"),
            (args.apply_uninstall, "apply-uninstall"),
            (args.apply_lab_bootstrap, "apply-lab-bootstrap"),
        ):
            if selected:
                mutation_handoff(name)
        if not args.galileo_console_url:
            fail("--galileo-console-url is required")
        if args.inspect_chart:
            if not args.spec:
                fail("--inspect-chart requires --spec")
            outcome = inspect_chart_action(Path(args.spec), args.galileo_console_url, Path(args.output_dir))
        elif args.render:
            if not args.spec:
                fail("--render requires --spec")
            outcome = render(Path(args.spec), args.galileo_console_url, Path(args.output_dir))
        elif args.preflight:
            if not args.bundle:
                fail("--preflight requires --bundle")
            outcome = preflight(args)
        elif args.apply_install or args.apply_upgrade:
            raise AssertionError("apply sentinel dispatch failed")
        elif args.status:
            outcome = status(args)
        elif args.plan_rollback:
            outcome = plan_action(args, "rollback")
        elif args.apply_rollback:
            raise AssertionError("apply sentinel dispatch failed")
        elif args.plan_uninstall:
            outcome = plan_action(args, "uninstall")
        elif args.apply_uninstall:
            raise AssertionError("apply sentinel dispatch failed")
        elif args.render_lab_bootstrap:
            outcome = lab_action(args, "render")
        elif args.preflight_lab_bootstrap:
            outcome = lab_action(args, "preflight")
        else:
            raise AssertionError("apply sentinel dispatch failed")
        if args.json:
            print(json.dumps(outcome, indent=2, sort_keys=True))
        else:
            print(f"{outcome['action']}: {outcome['state']}")
            for key in ("bundle", "runtime_inventory", "inventory", "coverage_review", "release_contract", "rendered_image_inventory", "plan"):
                if key in outcome:
                    print(f"{key}: {outcome[key]}")
        return 0
    except ContractError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

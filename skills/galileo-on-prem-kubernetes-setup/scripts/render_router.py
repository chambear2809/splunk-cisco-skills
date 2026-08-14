#!/usr/bin/env python3
"""Render and validate the non-mutating Galileo On-Prem deployment router."""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


CONTRACT_VERSION = "galileo-on-prem-kubernetes-router/v2"
SPEC_API_VERSION = "galileo.ai/on-prem-deployment/v1"
SPEC_KIND = "GalileoOnPremDeploymentPlan"
SKILL_NAME = "galileo-on-prem-kubernetes-setup"
MARKER = ".galileo-on-prem-kubernetes-setup"
SKILL_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = SKILL_DIR.parent.parent
MATRIX_PATH = SKILL_DIR / "references" / "deployment-feature-matrix.json"
SOURCE_LEDGER_PATH = SKILL_DIR / "references" / "source-ledger.md"

REQUIRED_RUNTIME_CATEGORIES = {
    "dependency",
    "schema_or_enable_flag",
    "image",
    "crd",
    "hook_or_migration",
    "cluster_scoped_object",
    "api_kind",
    "service_or_route",
    "persistence",
}
MUTATING_STATUSES = {"delegated_apply", "direct_apply"}
PLACEHOLDER_RE = re.compile(r"(?:\bTODO\b|CHANGEME|REPLACE[_ -]?ME|<[^>]+>)", re.I)
SAFE_ID_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
FEATURE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
SENSITIVE_KEY_RE = re.compile(
    r"(?:^|_)(?:token|password|authorization|api_key|api_token|client_secret|"
    r"private_key|access_key|secret_value|repository_password)$",
    re.I,
)
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?:^|[\s,;{[(])(?:token|password|authorization|api[ _-]?key|api[ _-]?token|"
    r"client[ _-]?secret|private[ _-]?key|access[ _-]?key|secret[ _-]?value|"
    r"repository[ _-]?password|galileo[ _-]?api[ _-]?key)\s*[:=]\s*\S+",
    re.I,
)
BEARER_VALUE_RE = re.compile(r"(?:^|\s)bearer\s+[A-Za-z0-9._~+/=-]{8,}", re.I)
PRIVATE_KEY_VALUE_RE = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----", re.I)
URL_USERINFO_RE = re.compile(r"https?://[^\s/@:]+:[^\s/@]+@", re.I)
DNS_NAME_RE = re.compile(
    r"^(?=.{1,253}\.?$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.?$",
    re.I,
)
MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_HASH_BYTES = 64 * 1024 * 1024 * 1024
DOCUMENTATION_CONFLICTS = [
    "Kubernetes version floors differ across official pages.",
    "Release-name and timeout examples differ.",
    "The 31-chart list omits components named elsewhere.",
    "Agent Control and Luna Studio ownership can be standalone or umbrella.",
    "Redis support/topology and core Azure object-storage claims conflict.",
    "VictoriaLogs is described but absent from published chart inventories.",
    "Public sizing estimates differ and on-prem DR is not generically documented.",
]

ALLOWED_KEYS: dict[tuple[str, ...], set[str]] = {
    (): {
        "api_version", "kind", "metadata", "galileo", "target", "artifacts",
        "installation", "routing", "node_pools", "storage", "data_services",
        "monitoring", "features", "identity", "email", "air_gap", "operations",
        "approvals",
    },
    ("metadata",): {"deployment_id", "environment", "profile", "owner", "change_ticket"},
    ("galileo",): {"console_url", "api_url", "domain"},
    ("target",): {
        "kube_context", "api_server", "ca_sha256", "kube_system_uid", "namespace",
        "namespace_uid", "distribution", "kubernetes_version",
    },
    ("artifacts",): {
        "galileo_stack_chart", "galileo_stack_sha256", "galileoctl_chart",
        "galileoctl_sha256", "agent_control_chart", "agent_control_sha256",
        "agent_control_ownership_evidence", "luna_studio_chart",
        "luna_studio_sha256", "luna_studio_ownership_evidence",
        "questionnaire_values_file", "secret_values_file",
        "repository_credentials_file", "image_manifest", "model_bundle",
        "stack_runtime_inventory",
    },
    ("installation",): {
        "method", "stack_release", "galileoctl_release", "timeout",
        "namespace_create", "shared_cluster", "crd_ownership", "child_ownership",
    },
    ("installation", "child_ownership"): {"agent_control", "luna_studio"},
    ("routing",): {
        "mode", "tls_mode", "certificate_secret", "ingress_class", "gateway_class",
        "load_balancer_address", "public_hosts",
    },
    ("routing", "public_hosts"): {"console", "api", "galileoctl", "agent_control", "luna_studio"},
    ("node_pools",): {"core", "runner", "ml"},
    ("node_pools", "core"): {"minimum_nodes", "labels", "taints"},
    ("node_pools", "runner"): {"minimum_nodes", "labels", "taints"},
    ("node_pools", "ml"): {"minimum_nodes", "labels", "taints"},
    ("storage",): {
        "default_class", "require_explicit_class", "data_class", "object_store_class",
        "snapshot_class", "reclaim_policy",
    },
    ("data_services",): {"postgres", "redis", "object_storage", "clickhouse", "rabbitmq"},
    ("data_services", "postgres"): {"mode", "version", "ha", "backup_evidence"},
    ("data_services", "redis"): {"mode", "version", "ha", "cluster_mode"},
    ("data_services", "object_storage"): {
        "provider", "mode", "backup_evidence", "support_exception",
    },
    ("data_services", "clickhouse"): {"backup_evidence"},
    ("data_services", "rabbitmq"): {"queue_purge_allowed"},
    ("monitoring",): {"prometheus", "grafana", "fluent_bit", "alerts", "owner"},
    ("features",): {"wizard", "agent_control", "luna_studio", "platform_postdeploy", "mcp", "lemonade"},
    ("features", "wizard"): {"enabled", "gpu_enabled", "offline_models"},
    ("features", "agent_control"): {"enabled", "topology"},
    ("features", "luna_studio"): {"enabled", "topology", "training_mode"},
    ("features", "platform_postdeploy"): {"enabled"},
    ("features", "mcp"): {"enabled"},
    ("features", "lemonade"): {"enabled"},
    ("identity",): {"sso_mode", "first_admin_owner", "break_glass_documented"},
    ("email",): {"mode", "sender", "test_requires_approval"},
    ("air_gap",): {"enabled", "registry", "no_egress", "architectures"},
    ("operations",): {"backups_verified", "restore_drill", "rollback_approved", "soak_days", "production_gate"},
    ("approvals",): {"cse_values_approved", "cse_ticket", "cluster_change_approved", "exceptions"},
}
ARTIFACT_PATH_KEYS = {
    "galileo_stack_chart", "galileoctl_chart", "agent_control_chart",
    "agent_control_ownership_evidence", "luna_studio_chart",
    "luna_studio_ownership_evidence", "questionnaire_values_file",
    "secret_values_file", "repository_credentials_file", "image_manifest",
    "model_bundle", "stack_runtime_inventory",
}


class ContractError(ValueError):
    """Raised when an input or immutable bundle violates the contract."""


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def pretty_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    fd, _ = open_regular_nofollow(path, MAX_HASH_BYTES)
    try:
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    finally:
        os.close(fd)
    return digest.hexdigest()


def open_regular_nofollow(path: Path, max_bytes: int) -> tuple[int, os.stat_result]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.EMLINK}:
            raise ContractError(f"refusing symlink input: {path}") from exc
        raise
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ContractError(f"input must be a regular file: {path}")
        if info.st_size > max_bytes:
            raise ContractError(f"input exceeds {max_bytes} bytes: {path}")
        return fd, info
    except Exception:
        os.close(fd)
        raise


def read_regular_nofollow(path: Path, max_bytes: int = MAX_INPUT_BYTES) -> bytes:
    fd, info = open_regular_nofollow(path, max_bytes)
    try:
        chunks: list[bytes] = []
        remaining = info.st_size
        while remaining:
            chunk = os.read(fd, min(1024 * 1024, remaining))
            if not chunk:
                raise ContractError(f"input changed during bounded read: {path}")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(fd, 1):
            raise ContractError(f"input grew during bounded read: {path}")
        return b"".join(chunks)
    finally:
        os.close(fd)


def load_data(path: Path) -> dict[str, Any]:
    try:
        text = read_regular_nofollow(path).decode("utf-8")
    except FileNotFoundError as exc:
        raise ContractError(f"input file not found: {path}") from exc
    try:
        value = json.loads(text)
    except json.JSONDecodeError as json_error:
        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ContractError(
                f"{path} is not JSON; install PyYAML to read YAML specs ({json_error.msg})"
            ) from exc
        try:
            value = yaml.safe_load(text)
        except Exception as exc:  # pragma: no cover - library-specific details
            raise ContractError(f"cannot parse {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{path} must contain one object")
    return value


def require_dict(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise ContractError(f"{key} must be an object")
    return value


def reject_unknown_keys(value: dict[str, Any], path: tuple[str, ...] = ()) -> None:
    allowed = ALLOWED_KEYS.get(path)
    if allowed is None:
        raise ContractError(f"internal schema has no object definition for {'.'.join(path)}")
    unknown = sorted(set(value) - allowed)
    if unknown:
        label = ".".join(path) or "root"
        raise ContractError(f"unknown {label} key(s): {', '.join(unknown)}")
    for key, child in value.items():
        child_path = (*path, key)
        if isinstance(child, dict):
            if child_path not in ALLOWED_KEYS:
                raise ContractError(f"unexpected object at {'.'.join(child_path)}")
            reject_unknown_keys(child, child_path)


def reject_inline_secrets(value: Any, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if SENSITIVE_KEY_RE.search(key) and not key.lower().endswith("_file"):
                if child not in (None, "", False):
                    raise ContractError(f"inline secret-like field is forbidden: {'.'.join((*path, key))}")
            reject_inline_secrets(child, (*path, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_inline_secrets(child, (*path, str(index)))
    elif isinstance(value, str):
        if "\x00" in value or any(ord(char) < 32 and char not in "\n\r\t" for char in value):
            raise ContractError(f"control character in {'.'.join(path)}")
        if PLACEHOLDER_RE.search(value):
            raise ContractError(f"unresolved placeholder in {'.'.join(path)}")
        if any(pattern.search(value) for pattern in (
            SECRET_ASSIGNMENT_RE, BEARER_VALUE_RE, PRIVATE_KEY_VALUE_RE,
            URL_USERINFO_RE,
        )):
            raise ContractError(
                f"secret-looking value is forbidden in {'.'.join(path)}; "
                "record only a secret-file path in an approved *_file field"
            )


def require_string(obj: dict[str, Any], key: str, path: str, *, allow_empty: bool = False) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        suffix = " (empty is allowed)" if allow_empty else ""
        raise ContractError(f"{path}.{key} must be a string{suffix}")
    return value.strip()


def require_bool(obj: dict[str, Any], key: str, path: str) -> bool:
    value = obj.get(key)
    if not isinstance(value, bool):
        raise ContractError(f"{path}.{key} must be true or false")
    return value


def require_int(obj: dict[str, Any], key: str, path: str, minimum: int = 0) -> int:
    value = obj.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ContractError(f"{path}.{key} must be an integer >= {minimum}")
    return value


def require_string_list(obj: dict[str, Any], key: str, path: str) -> list[str]:
    value = obj.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ContractError(f"{path}.{key} must be a list of nonempty strings")
    normalized = [item.strip() for item in value]
    if len(normalized) != len(set(normalized)):
        raise ContractError(f"{path}.{key} contains duplicate values")
    return normalized


def require_enum(obj: dict[str, Any], key: str, path: str, allowed: set[str]) -> str:
    value = require_string(obj, key, path)
    if value not in allowed:
        raise ContractError(f"{path}.{key} must be one of: {', '.join(sorted(allowed))}")
    return value


def validate_https_url(value: str, field: str, *, allow_path: bool = False) -> None:
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError as exc:
        raise ContractError(f"{field} has an invalid port") from exc
    if (
        parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
        or (not allow_path and parsed.path not in {"", "/"}) or parsed.query or parsed.fragment
    ):
        raise ContractError(
            f"{field} must be an HTTPS origin URL without user information, "
            "a non-root path, query, or fragment"
        )


def validate_dns_name(value: str, field: str) -> str:
    normalized = value.rstrip(".").lower()
    if not normalized or not DNS_NAME_RE.fullmatch(value) or "." not in normalized:
        raise ContractError(f"{field} must be a fully qualified DNS hostname without a scheme or port")
    return normalized


def hostname_within_domain(hostname: str, domain: str) -> bool:
    return hostname == domain or hostname.endswith(f".{domain}")


def validate_spec(spec: dict[str, Any]) -> None:
    reject_unknown_keys(spec)
    reject_inline_secrets(spec)
    if spec.get("api_version") != SPEC_API_VERSION:
        raise ContractError(f"api_version must be {SPEC_API_VERSION}")
    if spec.get("kind") != SPEC_KIND:
        raise ContractError(f"kind must be {SPEC_KIND}")

    for section in (
        "metadata", "galileo", "target", "artifacts", "installation", "routing",
        "node_pools", "storage", "data_services", "monitoring", "features",
        "identity", "email", "air_gap", "operations", "approvals",
    ):
        require_dict(spec, section)

    metadata = require_dict(spec, "metadata")
    deployment_id = require_string(metadata, "deployment_id", "metadata")
    if not SAFE_ID_RE.fullmatch(deployment_id) or len(deployment_id) > 63 or ".." in deployment_id:
        raise ContractError("metadata.deployment_id must be a safe lowercase identifier of at most 63 characters")
    require_enum(metadata, "environment", "metadata", {"lab", "staging", "production"})
    require_string(metadata, "profile", "metadata")
    require_string(metadata, "owner", "metadata")
    require_string(metadata, "change_ticket", "metadata")

    galileo = require_dict(spec, "galileo")
    console_url = require_string(galileo, "console_url", "galileo")
    validate_https_url(console_url, "galileo.console_url")
    console_hostname = validate_dns_name(
        urlsplit(console_url).hostname or "", "galileo.console_url hostname"
    )
    api_url = require_string(galileo, "api_url", "galileo", allow_empty=True)
    api_hostname = ""
    if api_url:
        validate_https_url(api_url, "galileo.api_url")
        api_hostname = validate_dns_name(
            urlsplit(api_url).hostname or "", "galileo.api_url hostname"
        )
    galileo_domain = validate_dns_name(
        require_string(galileo, "domain", "galileo"), "galileo.domain"
    )
    for field, hostname in (
        ("galileo.console_url", console_hostname),
        ("galileo.api_url", api_hostname),
    ):
        if hostname and not hostname_within_domain(hostname, galileo_domain):
            raise ContractError(f"{field} hostname must equal or be a subdomain of galileo.domain")

    target = require_dict(spec, "target")
    require_string(target, "kube_context", "target")
    api_server = require_string(target, "api_server", "target")
    validate_https_url(api_server, "target.api_server")
    for key in ("ca_sha256",):
        digest = require_string(target, key, "target", allow_empty=True)
        if digest and not SHA256_RE.fullmatch(digest):
            raise ContractError(f"target.{key} must be a SHA-256 hex digest")
    for key in ("kube_system_uid", "namespace_uid"):
        require_string(target, key, "target", allow_empty=True)
    namespace = require_string(target, "namespace", "target")
    if not SAFE_ID_RE.fullmatch(namespace) or len(namespace) > 63 or "." in namespace:
        raise ContractError("target.namespace must be a valid lowercase DNS label")
    require_enum(target, "distribution", "target", {"microk8s", "eks", "gke", "aks", "openshift", "rke2", "kubernetes", "other"})
    version = require_string(target, "kubernetes_version", "target")
    if not re.fullmatch(r"v?\d+\.\d+(?:\.\d+)?(?:[-+][0-9A-Za-z.-]+)?", version):
        raise ContractError("target.kubernetes_version must be an explicit semantic version")

    artifacts = require_dict(spec, "artifacts")
    for key in ALLOWED_KEYS[("artifacts",)]:
        require_string(artifacts, key, "artifacts", allow_empty=True)
    for key in ("galileo_stack_sha256", "galileoctl_sha256", "agent_control_sha256", "luna_studio_sha256"):
        digest = artifacts[key]
        if digest and not SHA256_RE.fullmatch(digest):
            raise ContractError(f"artifacts.{key} must be a SHA-256 hex digest")

    installation = require_dict(spec, "installation")
    require_enum(
        installation,
        "method",
        "installation",
        {
            "galileoctl",
            "helm-cli",
            "deployment-script",
            "step-by-step",
        },
    )
    for key in ("stack_release", "galileoctl_release"):
        release = require_string(installation, key, "installation")
        if not SAFE_ID_RE.fullmatch(release) or len(release) > 53:
            raise ContractError(f"installation.{key} must be a safe explicit Helm release name")
    timeout = require_string(installation, "timeout", "installation")
    if not re.fullmatch(r"[1-9]\d*[smh]", timeout):
        raise ContractError("installation.timeout must be an explicit duration such as 120m")
    require_bool(installation, "namespace_create", "installation")
    shared = require_bool(installation, "shared_cluster", "installation")
    crd_owner = require_enum(installation, "crd_ownership", "installation", {"dedicated", "preinstalled-shared"})
    if shared and crd_owner != "preinstalled-shared":
        raise ContractError("a shared cluster requires installation.crd_ownership=preinstalled-shared")
    ownership = require_dict(installation, "child_ownership")
    require_enum(ownership, "agent_control", "installation.child_ownership", {"disabled", "standalone", "umbrella"})
    require_enum(ownership, "luna_studio", "installation.child_ownership", {"disabled", "standalone", "umbrella"})

    routing = require_dict(spec, "routing")
    route_mode = require_enum(routing, "mode", "routing", {"ingress", "gateway-api", "private"})
    tls_mode = require_enum(
        routing,
        "tls_mode",
        "routing",
        {"customer-certificate", "cert-manager", "external-termination"},
    )
    for key in ("certificate_secret", "ingress_class", "gateway_class", "load_balancer_address"):
        require_string(routing, key, "routing", allow_empty=True)
    if tls_mode == "customer-certificate" and not routing["certificate_secret"]:
        raise ContractError(
            "routing.certificate_secret is required for customer-certificate TLS mode"
        )
    if route_mode == "ingress" and not routing["ingress_class"]:
        raise ContractError("routing.ingress_class is required for ingress mode")
    if route_mode == "gateway-api" and not routing["gateway_class"]:
        raise ContractError("routing.gateway_class is required for gateway-api mode")
    hosts = require_dict(routing, "public_hosts")
    normalized_hosts: dict[str, str] = {}
    for key in ALLOWED_KEYS[("routing", "public_hosts")]:
        raw_host = require_string(hosts, key, "routing.public_hosts", allow_empty=True)
        normalized_hosts[key] = (
            validate_dns_name(raw_host, f"routing.public_hosts.{key}") if raw_host else ""
        )
        if normalized_hosts[key] and not hostname_within_domain(normalized_hosts[key], galileo_domain):
            raise ContractError(
                f"routing.public_hosts.{key} must equal or be a subdomain of galileo.domain"
            )
    if normalized_hosts["console"] and normalized_hosts["console"] != console_hostname:
        raise ContractError(
            "galileo.console_url hostname must match routing.public_hosts.console"
        )
    if api_hostname and normalized_hosts["api"] and normalized_hosts["api"] != api_hostname:
        raise ContractError("galileo.api_url hostname must match routing.public_hosts.api")

    node_pools = require_dict(spec, "node_pools")
    required_node_labels = {
        "core": "galileo-node-type=galileo-core",
        "runner": "galileo-node-type=galileo-runner",
        "ml": "galileo-node-type=galileo-ml",
    }
    for pool_name in ("core", "runner", "ml"):
        pool = require_dict(node_pools, pool_name)
        minimum_nodes = require_int(pool, "minimum_nodes", f"node_pools.{pool_name}")
        labels = require_string_list(pool, "labels", f"node_pools.{pool_name}")
        require_string_list(pool, "taints", f"node_pools.{pool_name}")
        if minimum_nodes > 0 and required_node_labels[pool_name] not in labels:
            raise ContractError(
                f"node_pools.{pool_name}.labels must include the current documented "
                f"{required_node_labels[pool_name]!r}; a version-specific difference "
                "requires reviewed chart/CSE evidence and a skill contract update"
            )

    storage = require_dict(spec, "storage")
    for key in ("default_class", "data_class", "object_store_class", "snapshot_class"):
        require_string(storage, key, "storage", allow_empty=True)
    require_bool(storage, "require_explicit_class", "storage")
    require_enum(storage, "reclaim_policy", "storage", {"Retain", "Delete"})

    services = require_dict(spec, "data_services")
    postgres = require_dict(services, "postgres")
    require_enum(postgres, "mode", "data_services.postgres", {"bundled", "external"})
    require_string(postgres, "version", "data_services.postgres")
    require_bool(postgres, "ha", "data_services.postgres")
    require_string(postgres, "backup_evidence", "data_services.postgres", allow_empty=True)
    redis = require_dict(services, "redis")
    require_enum(redis, "mode", "data_services.redis", {"bundled", "external"})
    require_string(redis, "version", "data_services.redis")
    require_bool(redis, "ha", "data_services.redis")
    if require_bool(redis, "cluster_mode", "data_services.redis"):
        raise ContractError("data_services.redis.cluster_mode must be false")
    object_storage = require_dict(services, "object_storage")
    object_provider = require_enum(
        object_storage,
        "provider",
        "data_services.object_storage",
        {"minio", "s3-compatible", "aws-s3", "gcs", "azure-blob"},
    )
    object_mode = require_enum(
        object_storage,
        "mode",
        "data_services.object_storage",
        {"bundled", "external"},
    )
    if object_provider == "minio" and object_mode != "bundled":
        raise ContractError(
            "data_services.object_storage.provider=minio requires mode=bundled; "
            "use s3-compatible for customer-managed MinIO"
        )
    if object_provider != "minio" and object_mode != "external":
        raise ContractError(
            "external object-storage providers require data_services.object_storage.mode=external"
        )
    require_string(object_storage, "backup_evidence", "data_services.object_storage", allow_empty=True)
    object_exception = require_string(
        object_storage,
        "support_exception",
        "data_services.object_storage",
        allow_empty=True,
    )
    if object_provider == "azure-blob" and not object_exception:
        raise ContractError(
            "core Azure Blob requires a written Galileo support decision because "
            "the current umbrella and Azure deployment guides conflict"
        )
    if object_provider != "azure-blob" and object_exception:
        raise ContractError(
            "data_services.object_storage.support_exception is allowed only for azure-blob"
        )
    require_string(require_dict(services, "clickhouse"), "backup_evidence", "data_services.clickhouse", allow_empty=True)
    if require_bool(require_dict(services, "rabbitmq"), "queue_purge_allowed", "data_services.rabbitmq"):
        raise ContractError("data_services.rabbitmq.queue_purge_allowed must remain false")

    monitoring = require_dict(spec, "monitoring")
    for key in ("prometheus", "grafana", "fluent_bit", "alerts"):
        require_bool(monitoring, key, "monitoring")
    require_string(monitoring, "owner", "monitoring")

    features = require_dict(spec, "features")
    wizard = require_dict(features, "wizard")
    wizard_enabled = require_bool(wizard, "enabled", "features.wizard")
    gpu_enabled = require_bool(wizard, "gpu_enabled", "features.wizard")
    offline_models = require_bool(wizard, "offline_models", "features.wizard")
    if (gpu_enabled or offline_models) and not wizard_enabled:
        raise ContractError("Wizard GPU/offline models require features.wizard.enabled=true")
    for name in ("agent_control", "luna_studio"):
        section = require_dict(features, name)
        enabled = require_bool(section, "enabled", f"features.{name}")
        topology = require_enum(section, "topology", f"features.{name}", {"disabled", "standalone", "umbrella"})
        owner_topology = ownership[name]
        if enabled and topology == "disabled":
            raise ContractError(f"features.{name}.topology cannot be disabled when enabled")
        if not enabled and topology != "disabled":
            raise ContractError(f"features.{name}.topology must be disabled when the feature is disabled")
        if topology != owner_topology:
            raise ContractError(f"features.{name}.topology must match installation.child_ownership.{name}")
    luna = require_dict(features, "luna_studio")
    luna_training = require_enum(luna, "training_mode", "features.luna_studio", {"disabled", "in-cluster-gpu", "vertex-ai", "remote", "hybrid"})
    if luna["enabled"] and luna_training == "disabled":
        raise ContractError("features.luna_studio.training_mode must select an enabled training topology")
    if not luna["enabled"] and luna_training != "disabled":
        raise ContractError("features.luna_studio.training_mode must be disabled when Luna Studio is disabled")
    for name in ("platform_postdeploy", "mcp", "lemonade"):
        require_bool(require_dict(features, name), "enabled", f"features.{name}")

    identity = require_dict(spec, "identity")
    require_enum(identity, "sso_mode", "identity", {"oidc", "saml", "disabled"})
    require_string(identity, "first_admin_owner", "identity")
    require_bool(identity, "break_glass_documented", "identity")
    email = require_dict(spec, "email")
    require_enum(email, "mode", "email", {"smtp", "sendgrid", "disabled"})
    require_string(email, "sender", "email", allow_empty=True)
    require_bool(email, "test_requires_approval", "email")
    air_gap = require_dict(spec, "air_gap")
    air_enabled = require_bool(air_gap, "enabled", "air_gap")
    require_string(air_gap, "registry", "air_gap", allow_empty=True)
    if require_bool(air_gap, "no_egress", "air_gap") and not air_enabled:
        raise ContractError("air_gap.no_egress requires air_gap.enabled=true")
    require_string_list(air_gap, "architectures", "air_gap")
    operations = require_dict(spec, "operations")
    for key in ("backups_verified", "restore_drill", "rollback_approved", "production_gate"):
        require_bool(operations, key, "operations")
    require_int(operations, "soak_days", "operations")
    approvals = require_dict(spec, "approvals")
    require_bool(approvals, "cse_values_approved", "approvals")
    require_string(approvals, "cse_ticket", "approvals", allow_empty=True)
    require_bool(approvals, "cluster_change_approved", "approvals")
    require_string_list(approvals, "exceptions", "approvals")


def load_matrix() -> tuple[dict[str, Any], dict[str, dict[str, Any]], str, str, str]:
    matrix = load_data(MATRIX_PATH)
    if matrix.get("schema_version") != 1:
        raise ContractError("feature matrix schema_version must be 1")
    if matrix.get("product_area") != "Galileo On-Prem Kubernetes deployment surfaces":
        raise ContractError("feature matrix product_area is invalid")
    features = matrix.get("features")
    if not isinstance(features, list) or matrix.get("feature_count") != len(features):
        raise ContractError("feature matrix feature_count does not match features")
    statuses = matrix.get("supported_statuses")
    if not isinstance(statuses, list) or not statuses or any(not isinstance(item, str) for item in statuses):
        raise ContractError("feature matrix supported_statuses must be a nonempty string list")
    status_set = set(statuses)
    official_sources = matrix.get("official_source_inventory")
    if not isinstance(official_sources, list) or not official_sources:
        raise ContractError("feature matrix official_source_inventory must be nonempty")
    official_by_url: dict[str, dict[str, str]] = {}
    for index, source in enumerate(official_sources):
        if not isinstance(source, dict) or set(source) != {"url", "title", "scope"}:
            raise ContractError(
                f"official source {index} must contain exactly url, title, and scope"
            )
        for key in ("url", "title", "scope"):
            if not isinstance(source[key], str) or not source[key].strip():
                raise ContractError(f"official source {index} has empty {key}")
        url = source["url"]
        validate_https_url(url, f"official source {index}", allow_path=True)
        if urlsplit(url).hostname != "helm.galileo.ai":
            raise ContractError("official source inventory must use helm.galileo.ai")
        if url in official_by_url:
            raise ContractError(f"duplicate official source URL: {url}")
        official_by_url[url] = source
    by_id: dict[str, dict[str, Any]] = {}
    required = {"id", "domain", "name", "status", "owners", "automation_boundary", "validation_evidence", "source_urls"}
    for index, row in enumerate(features):
        if not isinstance(row, dict):
            raise ContractError(f"feature matrix row {index} must be an object")
        missing = required - set(row)
        if missing:
            raise ContractError(f"feature matrix row {index} missing {sorted(missing)}")
        feature_id = row["id"]
        if not isinstance(feature_id, str) or not FEATURE_ID_RE.fullmatch(feature_id):
            raise ContractError(f"feature matrix row {index} has invalid id")
        if feature_id in by_id:
            raise ContractError(f"duplicate feature id: {feature_id}")
        for key in ("domain", "name", "automation_boundary", "validation_evidence"):
            if not isinstance(row[key], str) or not row[key].strip():
                raise ContractError(f"feature {feature_id} has empty {key}")
        if row["status"] not in status_set:
            raise ContractError(f"feature {feature_id} uses undeclared status {row['status']}")
        if not isinstance(row["owners"], list) or any(not isinstance(owner, str) or not owner for owner in row["owners"]):
            raise ContractError(f"feature {feature_id} owners must be strings")
        if len(row["owners"]) != len(set(row["owners"])):
            raise ContractError(f"feature {feature_id} has duplicate owners")
        if not isinstance(row["source_urls"], list) or not row["source_urls"]:
            raise ContractError(f"feature {feature_id} source_urls must be nonempty")
        for url in row["source_urls"]:
            if not isinstance(url, str):
                raise ContractError(f"feature {feature_id} has a non-string source URL")
            validate_https_url(url, f"feature {feature_id} source URL", allow_path=True)
            if urlsplit(url).hostname != "helm.galileo.ai":
                raise ContractError(f"feature {feature_id} source URL must use helm.galileo.ai")
            if url not in official_by_url:
                raise ContractError(
                    f"feature {feature_id} source URL is absent from official_source_inventory"
                )
        by_id[feature_id] = row
    covered_urls = {
        url for row in features for url in row["source_urls"]
    }
    uncovered_sources = sorted(set(official_by_url) - covered_urls)
    if uncovered_sources:
        raise ContractError(
            "official source inventory contains uncovered pages: "
            + ", ".join(uncovered_sources)
        )
    ledger_text = read_regular_nofollow(SOURCE_LEDGER_PATH).decode("utf-8")
    missing_from_ledger = sorted(url for url in official_by_url if url not in ledger_text)
    if missing_from_ledger:
        raise ContractError(
            "official source inventory is missing from source-ledger.md: "
            + ", ".join(missing_from_ledger)
        )
    feature_ids_sha = sha256_bytes(canonical_bytes(sorted(by_id)))
    semantic_rows = [
        {
            "id": row["id"], "name": row["name"], "status": row["status"],
            "owners": sorted(row["owners"]), "automation_boundary": row["automation_boundary"],
            "validation_evidence": row["validation_evidence"], "source_urls": sorted(row["source_urls"]),
        }
        for row in sorted(features, key=lambda value: value["id"])
    ]
    contracts_sha = sha256_bytes(canonical_bytes(semantic_rows))
    matrix_sha = sha256_bytes(canonical_bytes(matrix))
    return matrix, by_id, feature_ids_sha, contracts_sha, matrix_sha


def resolve_input_path(raw: str, spec_dir: Path) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = spec_dir / path
    return Path(os.path.abspath(path))


def normalize_artifact_paths(spec: dict[str, Any], spec_dir: Path) -> None:
    """Bind every configured file reference to the render-time intake directory."""
    artifacts = require_dict(spec, "artifacts")
    for key in sorted(ARTIFACT_PATH_KEYS):
        raw = artifacts[key]
        if raw:
            artifacts[key] = str(resolve_input_path(raw, spec_dir))


def lstat_directory(path: Path, label: str) -> os.stat_result:
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise ContractError(f"{label} directory not found: {path}") from exc
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise ContractError(f"{label} must be a real directory, not a symlink: {path}")
    return info


def reject_symlink_ancestors(path: Path, label: str) -> None:
    absolute = Path(os.path.abspath(path.expanduser()))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            return
        if stat.S_ISLNK(info.st_mode):
            raise ContractError(f"{label} has a symlink ancestor: {current}")
        if current != absolute and not stat.S_ISDIR(info.st_mode):
            raise ContractError(f"{label} ancestor is not a directory: {current}")


def prepare_output_root(raw: Path) -> Path:
    expanded = raw.expanduser()
    if ".." in expanded.parts:
        raise ContractError("output root must not contain '..' path traversal")
    output_root = Path(os.path.abspath(expanded))
    broad_roots = {
        Path("/"), Path.home(), PROJECT_ROOT, PROJECT_ROOT / "skills", SKILL_DIR,
        Path(os.path.realpath(tempfile.gettempdir())),
    }
    if output_root in broad_roots:
        raise ContractError(f"refusing broad output root: {output_root}")
    reject_symlink_ancestors(output_root, "output root")
    parent_info = lstat_directory(output_root.parent, "output-root parent")
    if parent_info.st_mode & 0o002:
        raise ContractError(f"output-root parent is world-writable: {output_root.parent}")
    try:
        info = output_root.lstat()
    except FileNotFoundError:
        os.mkdir(output_root, 0o700)
        os.chmod(output_root, 0o700)
        info = lstat_directory(output_root, "output root")
    else:
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise ContractError(f"output root must be a real directory: {output_root}")
        if info.st_uid != os.getuid():
            raise ContractError(f"preexisting output root is not owned by the current user: {output_root}")
        if stat.S_IMODE(info.st_mode) & 0o022:
            raise ContractError(f"preexisting output root must not be group/world writable: {output_root}")
    if info.st_uid != os.getuid():
        raise ContractError(f"output root is not owned by the current user: {output_root}")
    return output_root


def ensure_private_directory(path: Path, label: str) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        os.mkdir(path, 0o700)
        os.chmod(path, 0o700)
        info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise ContractError(f"{label} must be a real directory: {path}")
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ContractError(f"{label} must be current-user-owned with mode 0700: {path}")


def inspect_path(raw: str, spec_dir: Path, *, secret: bool = False) -> dict[str, Any]:
    if not raw:
        return {"configured": False, "exists": False, "safe_regular_file": False}
    path = resolve_input_path(raw, spec_dir)
    result: dict[str, Any] = {"configured": True, "path": raw, "exists": False, "safe_regular_file": False}
    try:
        info = path.lstat()
    except FileNotFoundError:
        return result
    result["exists"] = True
    result["file_type"] = "regular" if stat.S_ISREG(info.st_mode) else "other"
    result["symlink"] = stat.S_ISLNK(info.st_mode)
    result["mode"] = f"{stat.S_IMODE(info.st_mode):04o}"
    result["hard_links"] = info.st_nlink
    result["owned_by_current_user"] = info.st_uid == os.getuid()
    if secret:
        safe_mode = stat.S_IMODE(info.st_mode) & 0o077 == 0
        result["safe_regular_file"] = (
            stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode)
            and info.st_nlink == 1 and info.st_uid == os.getuid() and safe_mode
        )
    else:
        result["safe_regular_file"] = stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode)
    return result


def runtime_coverage(
    raw_path: str,
    spec_dir: Path,
    stack_sha: str,
    features: dict[str, dict[str, Any]],
    *,
    inventory_override: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str], list[str], list[str], list[str]]:
    uncovered: list[str] = []
    unowned: list[str] = []
    duplicate: list[str] = []
    unclassified: list[str] = []
    for feature_id, row in features.items():
        if not row["owners"]:
            unowned.append(feature_id)
        if row["status"] in MUTATING_STATUSES and len(row["owners"]) > 1:
            duplicate.append(feature_id)

    pending = {
        "schema_version": 1,
        "status": "pending",
        "chart_sha256": "",
        "generated_by": "",
        "observed_categories": [],
        "observed_empty_categories": {},
        "items": [],
        "validation_issues": [],
    }
    if not raw_path and inventory_override is None:
        unclassified.append("runtime.inventory.pending")
        pending["validation_issues"] = sorted(unclassified)
        return pending, sorted(uncovered), sorted(unowned), sorted(duplicate), sorted(unclassified)
    if inventory_override is None:
        path = resolve_input_path(raw_path, spec_dir)
        try:
            runtime_info = path.lstat()
        except FileNotFoundError:
            unclassified.append("runtime.inventory.missing")
            pending["source_path"] = raw_path
            pending["validation_issues"] = sorted(unclassified)
            return pending, sorted(uncovered), sorted(unowned), sorted(duplicate), sorted(unclassified)
        if not stat.S_ISREG(runtime_info.st_mode) or stat.S_ISLNK(runtime_info.st_mode):
            unclassified.append("runtime.inventory.unsafe-file-type")
            pending["source_path"] = raw_path
            pending["validation_issues"] = sorted(unclassified)
            return pending, sorted(uncovered), sorted(unowned), sorted(duplicate), sorted(unclassified)
        try:
            inventory = load_data(path)
        except (ContractError, OSError, UnicodeError) as exc:
            unclassified.append(f"runtime.inventory.invalid:{type(exc).__name__}")
            pending["source_path"] = raw_path
            pending["validation_issues"] = sorted(unclassified)
            return pending, sorted(uncovered), sorted(unowned), sorted(duplicate), sorted(unclassified)
    else:
        inventory = inventory_override

    # Runtime inventory is copied into the immutable packet. Apply the same
    # value-level secret screen as the deployment spec before anything is
    # normalized or written.
    reject_inline_secrets(inventory)

    allowed_root = {"schema_version", "chart_sha256", "generated_by", "observed_categories", "observed_empty_categories", "items"}
    unknown_root = sorted(set(inventory) - allowed_root)
    if unknown_root:
        unclassified.extend(f"runtime.inventory.unknown-field:{key}" for key in unknown_root)
    if inventory.get("schema_version") != 1:
        unclassified.append("runtime.inventory.schema-version")
    chart_digest = inventory.get("chart_sha256")
    if not isinstance(chart_digest, str) or not SHA256_RE.fullmatch(chart_digest):
        unclassified.append("runtime.inventory.chart-digest-invalid")
        chart_digest = ""
    elif not stack_sha:
        unclassified.append("runtime.inventory.chart-digest-unbound")
    elif chart_digest.lower() != stack_sha.lower():
        unclassified.append("runtime.inventory.chart-digest-mismatch")
    generated_by = inventory.get("generated_by")
    if generated_by != "galileo-on-prem-stack-setup":
        unclassified.append("runtime.inventory.generated-by-invalid")
        generated_by = ""
    observed = inventory.get("observed_categories")
    if not isinstance(observed, list) or any(not isinstance(item, str) for item in observed):
        observed_set: set[str] = set()
        unclassified.append("runtime.inventory.observed-categories-invalid")
    else:
        observed_set = set(observed)
        if len(observed) != len(observed_set):
            unclassified.append("runtime.inventory.observed-categories-duplicate")
    for category in sorted(REQUIRED_RUNTIME_CATEGORIES - observed_set):
        unclassified.append(f"runtime.category.not-observed:{category}")
    for category in sorted(observed_set - REQUIRED_RUNTIME_CATEGORIES):
        unclassified.append(f"runtime.category.unknown:{category}")
    empty = inventory.get("observed_empty_categories")
    if not isinstance(empty, dict):
        empty = {}
        unclassified.append("runtime.inventory.observed-empty-categories-invalid")
    normalized_empty: dict[str, str] = {}
    for category, reason in empty.items():
        if category not in REQUIRED_RUNTIME_CATEGORIES or not isinstance(reason, str) or not reason.strip():
            unclassified.append(f"runtime.category.empty-evidence-invalid:{category}")
        else:
            normalized_empty[category] = reason.strip()

    raw_items = inventory.get("items")
    if not isinstance(raw_items, list):
        raw_items = []
        unclassified.append("runtime.inventory.items-invalid")
    normalized_items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    counts = {category: 0 for category in REQUIRED_RUNTIME_CATEGORIES}
    required_item = {"id", "category", "classification_id", "owners"}
    allowed_item = required_item | {"source_ref"}
    for index, item in enumerate(raw_items):
        if not isinstance(item, dict):
            unclassified.append(f"runtime.item.invalid:{index}")
            continue
        missing = sorted(required_item - set(item))
        unknown = sorted(set(item) - allowed_item)
        item_id = item.get("id") if isinstance(item.get("id"), str) else f"index-{index}"
        if missing:
            unclassified.append(f"runtime.item.missing-field:{item_id}:{','.join(missing)}")
        if unknown:
            unclassified.append(f"runtime.item.unknown-field:{item_id}:{','.join(unknown)}")
        if not isinstance(item.get("id"), str) or not FEATURE_ID_RE.fullmatch(item["id"]):
            unclassified.append(f"runtime.item.invalid-id:{index}")
            continue
        item_id = item["id"]
        if item_id in seen_ids:
            unclassified.append(f"runtime.item.duplicate-id:{item_id}")
            continue
        seen_ids.add(item_id)
        category = item.get("category")
        if category not in REQUIRED_RUNTIME_CATEGORIES:
            unclassified.append(f"runtime.item.unknown-category:{item_id}")
            category = str(category or "")
        else:
            counts[category] += 1
        classification = item.get("classification_id")
        if not isinstance(classification, str) or classification not in features:
            unclassified.append(f"runtime.item.unclassified:{item_id}")
            if isinstance(classification, str) and classification:
                uncovered.append(classification)
        else:
            feature = features[classification]
            if feature["status"] == "unsupported":
                unclassified.append(f"runtime.item.classified-unsupported:{item_id}")
        owners = item.get("owners")
        if not isinstance(owners, list) or any(not isinstance(owner, str) or not owner for owner in owners):
            owners = []
            unowned.append(f"runtime:{item_id}")
        elif len(owners) != len(set(owners)):
            unclassified.append(f"runtime.item.duplicate-owner-entry:{item_id}")
        if isinstance(classification, str) and classification in features:
            expected = set(features[classification]["owners"])
            actual = set(owners)
            if not actual:
                pass
            elif actual != expected:
                unclassified.append(f"runtime.item.owner-mismatch:{item_id}")
            if features[classification]["status"] in MUTATING_STATUSES and len(actual) > 1:
                duplicate.append(f"runtime:{item_id}")
        source_ref = item.get("source_ref", "")
        if source_ref is not None and not isinstance(source_ref, str):
            unclassified.append(f"runtime.item.source-ref-invalid:{item_id}")
            source_ref = ""
        normalized_items.append({
            "id": item_id,
            "category": category,
            "classification_id": classification if isinstance(classification, str) else "",
            "owners": sorted(owners),
            "source_ref": source_ref or "",
        })
    for category in sorted(REQUIRED_RUNTIME_CATEGORIES):
        if category in observed_set and counts[category] == 0 and category not in normalized_empty:
            unclassified.append(f"runtime.category.no-items-or-empty-evidence:{category}")
        if counts[category] > 0 and category in normalized_empty:
            unclassified.append(f"runtime.category.items-and-empty-evidence:{category}")

    normalized = {
        "schema_version": 1,
        "status": "classified" if not unclassified and not unowned and not duplicate and not uncovered else "blocked",
        "chart_sha256": chart_digest.lower(),
        "generated_by": generated_by.strip(),
        "observed_categories": sorted(observed_set),
        "observed_empty_categories": dict(sorted(normalized_empty.items())),
        "items": sorted(normalized_items, key=lambda value: value["id"]),
        "source_path": raw_path,
    }
    return normalized, sorted(set(uncovered)), sorted(set(unowned)), sorted(set(duplicate)), sorted(set(unclassified))


def path_gap(
    gaps: list[dict[str, Any]], key: str, raw: str, spec_dir: Path, *, secret: bool = False,
    required: bool = True, supplied_sha: str = "",
) -> dict[str, Any]:
    evidence = inspect_path(raw, spec_dir, secret=secret)
    if required and not raw:
        gaps.append({"key": key, "severity": "error", "message": "Required artifact path is not configured."})
    elif raw and not evidence["exists"]:
        gaps.append({"key": key, "severity": "error", "message": "Configured artifact path does not exist."})
    elif raw and not evidence["safe_regular_file"]:
        message = "Secret path must be a current-user-owned, one-link regular file with mode 0600 or tighter." if secret else "Artifact path must be a regular file, not a symlink or special file."
        gaps.append({"key": key, "severity": "error", "message": message})
    elif raw and supplied_sha:
        actual = sha256_file(resolve_input_path(raw, spec_dir))
        evidence["sha256_matches"] = actual.lower() == supplied_sha.lower()
        evidence["actual_sha256"] = actual
        if not evidence["sha256_matches"]:
            gaps.append({"key": f"{key}.digest", "severity": "error", "message": "Artifact SHA-256 does not match the reviewed specification."})
    return evidence


def version_tuple(raw: str) -> tuple[int, int, int]:
    match = re.match(r"v?(\d+)\.(\d+)(?:\.(\d+))?", raw)
    if not match:
        return (0, 0, 0)
    return tuple(int(value or 0) for value in match.groups())  # type: ignore[return-value]


def build_gaps(spec: dict[str, Any], spec_dir: Path, coverage: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    artifacts = spec["artifacts"]
    features = spec["features"]
    environment = spec["metadata"]["environment"]
    evidence: dict[str, Any] = {}
    galileoctl_required = spec["installation"]["method"] == "galileoctl"
    artifact_contracts = (
        ("galileo-stack-chart", "galileo_stack_chart", "galileo_stack_sha256", True),
        (
            "galileoctl-chart",
            "galileoctl_chart",
            "galileoctl_sha256",
            galileoctl_required,
        ),
        ("questionnaire-values", "questionnaire_values_file", "", True),
        ("image-manifest", "image_manifest", "", spec["air_gap"]["enabled"]),
    )
    for gap_key, path_key, sha_key, required in artifact_contracts:
        digest = artifacts[sha_key] if sha_key else ""
        if required and sha_key and not digest:
            gaps.append({"key": f"artifact.{gap_key}.digest", "severity": "error", "message": "Required artifact SHA-256 is not configured."})
        evidence[path_key] = path_gap(
            gaps, f"artifact.{gap_key}", artifacts[path_key], spec_dir,
            required=required, supplied_sha=digest,
        )
    for name, sha_key, evidence_key in (
        ("agent_control", "agent_control_sha256", "agent_control_ownership_evidence"),
        ("luna_studio", "luna_studio_sha256", "luna_studio_ownership_evidence"),
    ):
        enabled = features[name]["enabled"]
        topology = features[name]["topology"]
        chart_key = f"{name}_chart"
        chart_required = enabled and topology == "standalone"
        if chart_required and not artifacts[sha_key]:
            gaps.append({"key": f"artifact.{name}.digest", "severity": "error", "message": "Standalone optional-product chart SHA-256 is required."})
        evidence[chart_key] = path_gap(
            gaps, f"artifact.{name}.chart", artifacts[chart_key], spec_dir,
            required=chart_required, supplied_sha=artifacts[sha_key],
        )
        evidence[evidence_key] = path_gap(
            gaps, f"artifact.{name}.ownership", artifacts[evidence_key], spec_dir,
            required=enabled,
        )
    for key in ("secret_values_file", "repository_credentials_file"):
        evidence[key] = path_gap(gaps, f"secret-path.{key}", artifacts[key], spec_dir, secret=True, required=True)
    if spec["air_gap"]["enabled"] and spec["features"]["wizard"]["offline_models"]:
        evidence["model_bundle"] = path_gap(gaps, "artifact.model-bundle", artifacts["model_bundle"], spec_dir, required=True)
    if coverage["unclassified_runtime_inventory"]:
        gaps.append({"key": "coverage.runtime-inventory", "severity": "error", "message": "Exact chart runtime inventory is missing, invalid, or contains unclassified items."})
    if coverage["uncovered"] or coverage["unowned"] or coverage["duplicate_mutation_owners"]:
        gaps.append({"key": "coverage.semantic", "severity": "error", "message": "Coverage has uncovered, unowned, or duplicate mutation ownership entries."})

    target = spec["target"]
    for key in ("ca_sha256", "kube_system_uid"):
        if not target[key]:
            gaps.append({"key": f"target.{key}", "severity": "error", "message": "Target-bound preflight identity is missing."})
    if not spec["installation"]["namespace_create"] and not target["namespace_uid"]:
        gaps.append({"key": "target.namespace_uid", "severity": "error", "message": "Existing namespace UID is required when namespace creation is disabled."})
    if version_tuple(target["kubernetes_version"]) < (1, 27, 0):
        gaps.append({"key": "target.kubernetes-version", "severity": "error", "message": "Version is below the default 1.27 floor; attach a chart-specific written exception."})
    if not spec["routing"]["load_balancer_address"] and spec["routing"]["mode"] != "private":
        gaps.append({"key": "routing.load-balancer", "severity": "error", "message": "External routing has no reviewed load-balancer address."})
    if not spec["routing"]["public_hosts"]["console"] or not spec["routing"]["public_hosts"]["api"]:
        gaps.append({"key": "routing.hosts", "severity": "error", "message": "Console and API hosts are required."})
    storage = spec["storage"]
    if not storage["data_class"] or not storage["object_store_class"]:
        gaps.append({"key": "storage.classes", "severity": "error", "message": "Explicit data and object-storage classes are required."})
    if storage["reclaim_policy"] == "Delete":
        gaps.append({"key": "storage.reclaim-policy", "severity": "error", "message": "Delete reclaim policy requires a documented data-retention exception."})
    if spec["features"]["wizard"]["gpu_enabled"] and spec["node_pools"]["ml"]["minimum_nodes"] < 1:
        gaps.append({"key": "gpu.ml-nodes", "severity": "error", "message": "GPU mode requires at least one planned ML node and later live GPU evidence."})
    if spec["air_gap"]["enabled"] and not spec["air_gap"]["registry"]:
        gaps.append({"key": "air-gap.registry", "severity": "error", "message": "Air-gap mode requires an internal registry destination."})
    if not spec["monitoring"]["alerts"]:
        gaps.append({"key": "monitoring.alerts", "severity": "error", "message": "Production completion requires monitored, owned alerts."})

    services = spec["data_services"]
    if not services["postgres"]["backup_evidence"]:
        gaps.append({"key": "backup.postgresql", "severity": "error", "message": "PostgreSQL backup evidence is missing."})
    if not services["clickhouse"]["backup_evidence"]:
        gaps.append({"key": "backup.clickhouse", "severity": "error", "message": "ClickHouse backup evidence is missing."})
    if not services["object_storage"]["backup_evidence"]:
        gaps.append({"key": "backup.object-storage", "severity": "error", "message": "Object-storage protection evidence is missing."})
    if services["redis"]["mode"] == "bundled":
        gaps.append({"key": "redis.bundled-support", "severity": "error", "message": "Bundled Redis requires a written support exception for production use."})
    if environment == "production":
        if spec["node_pools"]["core"]["minimum_nodes"] < 4:
            gaps.append({"key": "production.core-nodes", "severity": "error", "message": "Default production planning requires at least four CSE-sized core workers."})
        if spec["node_pools"]["runner"]["minimum_nodes"] < 1:
            gaps.append({"key": "production.runner-nodes", "severity": "error", "message": "Documented production planning requires at least one CSE-sized runner worker; CSE may require more for availability and workload."})
        for service in ("postgres", "redis"):
            if not services[service]["ha"]:
                gaps.append({"key": f"production.{service}-ha", "severity": "error", "message": f"Production {service} is not configured for HA."})
        approvals = spec["approvals"]
        if not approvals["cse_values_approved"] or not approvals["cse_ticket"]:
            gaps.append({"key": "approval.cse-values", "severity": "error", "message": "Galileo approval and ticket evidence are required."})
        if not approvals["cluster_change_approved"]:
            gaps.append({"key": "approval.cluster-change", "severity": "error", "message": "Cluster-change approval is required."})
        operations = spec["operations"]
        if not operations["backups_verified"] or not operations["restore_drill"]:
            gaps.append({"key": "production.backup-restore", "severity": "error", "message": "Verified backups and a restore drill are required."})
        if operations["soak_days"] < 3:
            gaps.append({"key": "production.soak", "severity": "error", "message": "Three incident-free days are required."})
        if not spec["identity"]["break_glass_documented"]:
            gaps.append({"key": "production.break-glass", "severity": "error", "message": "Identity break-glass and offboarding procedures are required."})
    else:
        gaps.append({"key": "environment.nonproduction", "severity": "warning", "message": "Lab/staging evidence cannot satisfy production readiness."})
    return sorted(gaps, key=lambda item: (item["severity"], item["key"])), evidence


def build_plan(spec: dict[str, Any]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    if spec["air_gap"]["enabled"]:
        nodes.append({
            "id": "air-gap", "owner": "galileo-on-prem-air-gap-setup", "depends_on": [],
            "requested_action": "Render, verify, and separately gate registry mirroring; return a digest-bound artifact contract.",
        })
    method = spec["installation"]["method"]
    stack_action = {
        "galileoctl": (
            "Render the source-backed Method A UI/CLI handoff for the pinned galileoctl "
            "and Stack releases; require pre-deploy validation, a reviewed dry run, "
            "explicit operator apply evidence, temporary managementRoles for the UI "
            "path only, and post-deploy validation."
        ),
        "helm-cli": (
            "Create a new immutable Stack bundle, run target-bound preflight, and use "
            "the child's independent install or upgrade approval."
        ),
        "deployment-script": (
            "Validate and hand off the exact hashed vendor script, chart configuration, "
            "and sequential values without modifying or executing undocumented logic."
        ),
        "step-by-step": (
            "Render the Galileo-approved ordered-chart operator handoff with exact "
            "versions and ownership; do not mix it with umbrella release ownership."
        ),
    }[method]
    nodes.append({
        "id": "stack", "owner": "galileo-on-prem-stack-setup",
        "depends_on": ["air-gap"] if spec["air_gap"]["enabled"] else [],
        "installation_method": method,
        "requested_action": stack_action,
    })
    for name, owner in (
        ("agent_control", "galileo-on-prem-agent-control-setup"),
        ("luna_studio", "galileo-on-prem-luna-studio-setup"),
    ):
        feature = spec["features"][name]
        if not feature["enabled"]:
            continue
        topology = feature["topology"]
        action = (
            "Render a reviewed umbrella overlay and return it to a new Stack bundle; do not create a separate release."
            if topology == "umbrella" else
            "Render and independently gate the pinned standalone release after the verified Stack contract."
        )
        nodes.append({
            "id": name.replace("_", "-"), "owner": owner, "depends_on": ["stack"],
            "topology": topology, "requested_action": action,
        })
    post_dependencies = ["stack"] + [node["id"] for node in nodes if node["id"] in {"agent-control", "luna-studio"}]
    for feature_name, node_id, owner in (
        ("platform_postdeploy", "platform-postdeploy", "galileo-platform-setup"),
        ("mcp", "mcp", "galileo-mcp-server-setup"),
        ("lemonade", "lemonade", "galileo-lemonade-instrumentation-setup"),
    ):
        if spec["features"][feature_name]["enabled"]:
            nodes.append({
                "id": node_id, "owner": owner, "depends_on": post_dependencies,
                "requested_action": "Render and validate the running-instance workflow only after postdeploy health evidence.",
            })
    return nodes


def markdown_table(rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> str:
    lines = ["| " + " | ".join(title for _, title in columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for row in rows:
        values = []
        for key, _ in columns:
            value = row.get(key, "")
            if isinstance(value, list):
                value = ", ".join(str(item) for item in value)
            values.append(str(value).replace("|", "\\|").replace("\n", " "))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def write_private(path: Path, content: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    path.chmod(0o600)


def source_ledger_json(matrix: dict[str, Any]) -> dict[str, Any]:
    urls: dict[str, set[str]] = {}
    for feature in matrix["features"]:
        for url in feature["source_urls"]:
            urls.setdefault(url, set()).add(feature["id"])
    return {
        "schema_version": 1,
        "reviewed_on": matrix["reviewed_on"],
        "official_source_count": len(matrix["official_source_inventory"]),
        "uncovered_official_sources": [],
        "sources": [
            {
                "url": url,
                "title": next(
                    source["title"]
                    for source in matrix["official_source_inventory"]
                    if source["url"] == url
                ),
                "scope": next(
                    source["scope"]
                    for source in matrix["official_source_inventory"]
                    if source["url"] == url
                ),
                "feature_ids": sorted(feature_ids),
            }
            for url, feature_ids in sorted(urls.items())
        ],
    }


def build_coverage_report(
    matrix: dict[str, Any],
    feature_ids_sha: str,
    contracts_sha: str,
    matrix_sha: str,
    runtime: dict[str, Any],
    uncovered: list[str],
    unowned: list[str],
    duplicate: list[str],
    unclassified: list[str],
) -> dict[str, Any]:
    complete = not (uncovered or unowned or duplicate or unclassified)
    return {
        "schema_version": 1,
        "product_area": matrix["product_area"],
        "feature_count": matrix["feature_count"],
        "feature_ids_sha256": feature_ids_sha,
        "feature_contracts_sha256": contracts_sha,
        "matrix_sha256": matrix_sha,
        "static_documentation_coverage_complete": not (
            uncovered or unowned or duplicate
        ),
        "runtime_inventory_supplied": runtime["status"] != "pending",
        "coverage_complete": complete,
        "uncovered": uncovered,
        "unowned": unowned,
        "duplicate_mutation_owners": duplicate,
        "unclassified_runtime_inventory": unclassified,
    }


def build_bundle_payloads(
    spec: dict[str, Any],
    matrix: dict[str, Any],
    runtime: dict[str, Any],
    coverage: dict[str, Any],
    gaps: list[dict[str, Any]],
    artifact_evidence: dict[str, Any],
    bundle_id: str,
    bundle_identity: dict[str, str],
) -> dict[str, bytes]:
    """Regenerate every immutable packet file except its file manifest."""
    blocking = [gap for gap in gaps if gap["severity"] == "error"]
    state = "blocked" if blocking else "rendered"
    coverage_complete = coverage["coverage_complete"]
    deployment_id = spec["metadata"]["deployment_id"]
    status_payload = {
        "schema_version": 1,
        "skill": SKILL_NAME,
        "deployment_id": deployment_id,
        "bundle_id": bundle_id,
        "state": state,
        "coverage_complete": coverage_complete,
        "production_ready": False,
        "gpu_profile_statically_validated": False,
        "gpu_profile_live_validated": False,
        "blocking_gap_count": len(blocking),
        "warning_gap_count": len(gaps) - len(blocking),
        "allowed_parent_states": ["rendered", "blocked"],
    }
    metadata = {
        "schema_version": 1,
        "skill": SKILL_NAME,
        "contract_version": CONTRACT_VERSION,
        "deployment_id": deployment_id,
        "bundle_id": bundle_id,
        **bundle_identity,
        "source_reviewed_on": matrix["reviewed_on"],
        "parent_is_non_mutating": True,
    }
    plan_nodes = build_plan(spec)
    orchestration = {
        "schema_version": 1,
        "deployment_id": deployment_id,
        "bundle_id": bundle_id,
        "parent_actions": ["render", "doctor", "coverage", "status"],
        "mutation_authorized": False,
        "nodes": plan_nodes,
    }
    doctor = {
        "schema_version": 1,
        "deployment_id": deployment_id,
        "state": state,
        "coverage_complete": coverage_complete,
        "production_ready": False,
        "gaps": gaps,
        "artifact_evidence": artifact_evidence,
        "documentation_conflicts": DOCUMENTATION_CONFLICTS,
    }

    coverage_md = "# Galileo On-Prem deployment coverage\n\n" + markdown_table([
        {"gate": "Static documentation", "result": str(coverage["static_documentation_coverage_complete"]).lower()},
        {"gate": "Runtime inventory supplied", "result": str(coverage["runtime_inventory_supplied"]).lower()},
        {"gate": "Complete coverage", "result": str(coverage_complete).lower()},
        {"gate": "Feature count", "result": matrix["feature_count"]},
    ], [("gate", "Gate"), ("result", "Result")]) + "\n\n"
    for key in (
        "uncovered", "unowned", "duplicate_mutation_owners",
        "unclassified_runtime_inventory",
    ):
        coverage_md += f"## {key}\n\n"
        values = coverage[key]
        coverage_md += (
            "- None\n\n" if not values
            else "".join(f"- `{value}`\n" for value in values) + "\n"
        )
    gaps_md = "# Gap register\n\n" + markdown_table(
        gaps or [{"severity": "none", "key": "none", "message": "No parent-detected gaps."}],
        [("severity", "Severity"), ("key", "Key"), ("message", "Message")],
    ) + "\n"
    plan_md = (
        "# Galileo On-Prem orchestration plan\n\n"
        "This parent does not execute these nodes. Each owner renders and gates its own work.\n\n"
        + markdown_table(
            plan_nodes,
            [("id", "Node"), ("owner", "Owner"), ("depends_on", "Depends on"), ("requested_action", "Handoff")],
        )
        + "\n"
    )
    doctor_md = (
        "# Galileo On-Prem deployment doctor\n\n"
        f"- State: **{state}**\n"
        f"- Coverage complete: **{str(coverage_complete).lower()}**\n"
        "- Production ready: **false**\n"
        f"- Blocking gaps: **{len(blocking)}**\n\n"
        "See `gap-register.md`, `coverage-report.md`, and `handoff.md`.\n"
    )
    handoff_md = (
        "# Child-skill handoff\n\n"
        "This packet authorizes no live change. Review the immutable bundle and invoke each selected child independently.\n\n"
        + plan_md.split("\n\n", 2)[-1]
    )
    return {
        MARKER: (CONTRACT_VERSION + "\n").encode(),
        "metadata.json": pretty_bytes(metadata),
        "deployment-spec.normalized.json": pretty_bytes(spec),
        "feature-matrix.json": pretty_bytes(matrix),
        "runtime-inventory.normalized.json": pretty_bytes(runtime),
        "orchestration-plan.json": pretty_bytes(orchestration),
        "orchestration-plan.md": plan_md.encode(),
        "coverage-report.json": pretty_bytes(coverage),
        "coverage-report.md": coverage_md.encode(),
        "source-ledger.json": pretty_bytes(source_ledger_json(matrix)),
        "gap-register.json": pretty_bytes({"schema_version": 1, "gaps": gaps}),
        "gap-register.md": gaps_md.encode(),
        "doctor-report.json": pretty_bytes(doctor),
        "doctor-report.md": doctor_md.encode(),
        "status.json": pretty_bytes(status_payload),
        "handoff.md": handoff_md.encode(),
    }


def build_bundle_manifest(bundle_id: str, payloads: dict[str, bytes]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "bundle_id": bundle_id,
        "files": [
            {"path": name, "sha256": sha256_bytes(payloads[name]), "size": len(payloads[name])}
            for name in sorted(payloads)
        ],
    }


def render(spec_path: Path, output_root: Path, console_override: str, runtime_override: str, operation: str, validate_after: bool) -> tuple[Path, dict[str, Any], int]:
    spec = load_data(spec_path)
    if console_override:
        galileo = spec.get("galileo")
        if not isinstance(galileo, dict):
            raise ContractError("galileo must be an object before --galileo-console-url can be applied")
        galileo["console_url"] = console_override
    if runtime_override:
        artifacts = spec.get("artifacts")
        if not isinstance(artifacts, dict):
            raise ContractError("artifacts must be an object before --runtime-inventory can be applied")
        artifacts["stack_runtime_inventory"] = runtime_override
    validate_spec(spec)
    spec_dir = Path(os.path.abspath(spec_path)).parent
    normalize_artifact_paths(spec, spec_dir)
    validate_spec(spec)
    matrix, features, feature_ids_sha, contracts_sha, matrix_sha = load_matrix()
    runtime, uncovered, unowned, duplicate, unclassified = runtime_coverage(
        spec["artifacts"]["stack_runtime_inventory"], Path("/"),
        spec["artifacts"]["galileo_stack_sha256"], features,
    )
    coverage = build_coverage_report(
        matrix, feature_ids_sha, contracts_sha, matrix_sha, runtime,
        uncovered, unowned, duplicate, unclassified,
    )
    coverage_complete = coverage["coverage_complete"]
    gaps, artifact_evidence = build_gaps(spec, Path("/"), coverage)
    blocking = [gap for gap in gaps if gap["severity"] == "error"]
    spec_sha = sha256_bytes(canonical_bytes(spec))
    runtime_sha = sha256_bytes(canonical_bytes(runtime))
    bundle_identity = {
        "contract_version": CONTRACT_VERSION,
        "spec_sha256": spec_sha,
        "matrix_sha256": matrix_sha,
        "runtime_inventory_sha256": runtime_sha,
    }
    bundle_id = sha256_bytes(canonical_bytes(bundle_identity))
    deployment_id = spec["metadata"]["deployment_id"]
    output_root = prepare_output_root(output_root)
    deployment_dir = output_root / deployment_id
    ensure_private_directory(deployment_dir, "deployment output")
    final_dir = deployment_dir / bundle_id
    state = "blocked" if blocking else "rendered"
    payloads = build_bundle_payloads(
        spec, matrix, runtime, coverage, gaps, artifact_evidence,
        bundle_id, bundle_identity,
    )
    if final_dir.exists():
        validate_bundle(final_dir)
    else:
        temp_dir = Path(tempfile.mkdtemp(prefix=".bundle-", dir=deployment_dir))
        temp_dir.chmod(0o700)
        try:
            for name, content in payloads.items():
                write_private(temp_dir / name, content)
            manifest = build_bundle_manifest(bundle_id, payloads)
            write_private(temp_dir / "bundle-manifest.json", pretty_bytes(manifest))
            os.replace(temp_dir, final_dir)
        except Exception:
            for child in temp_dir.iterdir() if temp_dir.exists() else []:
                child.unlink(missing_ok=True)
            if temp_dir.exists():
                temp_dir.rmdir()
            raise
    if validate_after or operation in {"doctor", "coverage"}:
        validate_bundle(final_dir)
    exit_code = 0
    if operation == "coverage" and not coverage_complete:
        exit_code = 2
    if operation == "doctor" and (not coverage_complete or blocking):
        exit_code = 2
    result = {
        "operation": operation,
        "bundle_dir": str(final_dir),
        "bundle_id": bundle_id,
        "state": state,
        "coverage_complete": coverage_complete,
        "blocking_gap_count": len(blocking),
        "coverage": {key: coverage[key] for key in ("uncovered", "unowned", "duplicate_mutation_owners", "unclassified_runtime_inventory")},
    }
    return final_dir, result, exit_code


def resolve_bundle(path: Path) -> Path:
    expanded = path.expanduser()
    if ".." in expanded.parts:
        raise ContractError("bundle path must not contain '..' path traversal")
    path = Path(os.path.abspath(expanded))
    if path in {
        Path("/"), Path.home(), PROJECT_ROOT, PROJECT_ROOT / "skills", SKILL_DIR,
        Path(os.path.realpath(tempfile.gettempdir())),
    }:
        raise ContractError(f"refusing broad bundle/output directory: {path}")
    reject_symlink_ancestors(path, "bundle path")
    lstat_directory(path, "bundle/output")

    def safe_regular(candidate: Path) -> bool:
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            return False
        return stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode)

    def real_directories(parent: Path) -> list[Path]:
        directories: list[Path] = []
        for child in parent.iterdir():
            info = child.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise ContractError(f"symlink found while locating bundle: {child}")
            if stat.S_ISDIR(info.st_mode):
                directories.append(child)
        return sorted(directories)

    if safe_regular(path / MARKER):
        return path
    candidates: list[Path] = []
    for child in real_directories(path):
        if safe_regular(child / MARKER):
            candidates.append(child)
            continue
        for grandchild in real_directories(child):
            if safe_regular(grandchild / MARKER):
                candidates.append(grandchild)
    if len(candidates) != 1:
        raise ContractError(f"expected exactly one immutable bundle under {path}; found {len(candidates)}")
    return candidates[0]


def validate_bundle(raw_path: Path) -> dict[str, Any]:
    bundle = resolve_bundle(raw_path)
    bundle_info = bundle.lstat()
    if bundle_info.st_uid != os.getuid():
        raise ContractError(f"bundle directory must be owned by current user: {bundle}")
    if bundle_info.st_nlink < 2:
        raise ContractError(f"bundle directory has an invalid link count: {bundle}")
    if stat.S_IMODE(bundle_info.st_mode) != 0o700:
        raise ContractError(f"bundle directory mode must be 0700: {bundle}")
    manifest_path = bundle / "bundle-manifest.json"
    try:
        manifest_info = manifest_path.lstat()
    except FileNotFoundError:
        raise ContractError("bundle-manifest.json is missing or unsafe")
    if not stat.S_ISREG(manifest_info.st_mode) or stat.S_ISLNK(manifest_info.st_mode):
        raise ContractError("bundle-manifest.json is missing or unsafe")
    if manifest_info.st_uid != os.getuid() or manifest_info.st_nlink != 1:
        raise ContractError("bundle-manifest.json must be current-user-owned with exactly one hard link")
    if stat.S_IMODE(manifest_info.st_mode) != 0o600:
        raise ContractError("bundle-manifest.json mode must be 0600")
    manifest = load_data(manifest_path)
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("files"), list):
        raise ContractError("invalid bundle manifest")
    listed: set[str] = set()
    for row in manifest["files"]:
        if not isinstance(row, dict) or set(row) != {"path", "sha256", "size"}:
            raise ContractError("invalid bundle manifest row")
        name = row["path"]
        if not isinstance(name, str) or Path(name).name != name or name == "bundle-manifest.json":
            raise ContractError("unsafe bundle manifest path")
        if name in listed:
            raise ContractError(f"duplicate manifest path: {name}")
        if not isinstance(row["sha256"], str) or not SHA256_RE.fullmatch(row["sha256"]):
            raise ContractError(f"invalid manifest checksum for {name}")
        if isinstance(row["size"], bool) or not isinstance(row["size"], int) or row["size"] < 0:
            raise ContractError(f"invalid manifest size for {name}")
        listed.add(name)
        target = bundle / name
        try:
            info = target.lstat()
        except FileNotFoundError:
            info = None
        if info is None or not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise ContractError(f"manifest file missing or unsafe: {name}")
        if info.st_uid != os.getuid() or info.st_nlink != 1:
            raise ContractError(f"bundle file must be current-user-owned with exactly one hard link: {name}")
        if stat.S_IMODE(info.st_mode) != 0o600:
            raise ContractError(f"bundle file mode must be 0600: {name}")
        if info.st_size != row["size"] or sha256_file(target) != row["sha256"]:
            raise ContractError(f"bundle file checksum/size drift: {name}")
    actual = {child.name for child in bundle.iterdir()}
    expected = listed | {"bundle-manifest.json"}
    if actual != expected:
        raise ContractError(f"bundle has missing or extra files: {sorted(actual ^ expected)}")
    spec = load_data(bundle / "deployment-spec.normalized.json")
    matrix = load_data(bundle / "feature-matrix.json")
    runtime = load_data(bundle / "runtime-inventory.normalized.json")
    marker_content = read_regular_nofollow(bundle / MARKER, 1024)
    if marker_content != (CONTRACT_VERSION + "\n").encode("utf-8"):
        raise ContractError("bundle marker content is invalid")
    validate_spec(spec)
    for key in sorted(ARTIFACT_PATH_KEYS):
        raw = spec["artifacts"][key]
        if raw and not Path(raw).is_absolute():
            raise ContractError(
                f"normalized artifact path must be absolute: artifacts.{key}"
            )
    current_matrix, features, feature_ids_sha, contracts_sha, current_matrix_sha = load_matrix()
    if canonical_bytes(matrix) != canonical_bytes(current_matrix):
        raise ContractError("bundled feature matrix does not match the current reviewed matrix")

    static_uncovered: list[str]
    static_unowned: list[str]
    static_duplicate: list[str]
    expected_unclassified: list[str]
    if runtime.get("status") == "pending":
        allowed_pending = {
            "schema_version", "status", "chart_sha256", "generated_by",
            "observed_categories", "observed_empty_categories", "items",
            "validation_issues", "source_path",
        }
        if set(runtime) - allowed_pending:
            raise ContractError("pending runtime inventory contains unknown fields")
        for key, expected_value in (
            ("schema_version", 1), ("status", "pending"), ("chart_sha256", ""),
            ("generated_by", ""), ("observed_categories", []),
            ("observed_empty_categories", {}), ("items", []),
        ):
            if runtime.get(key) != expected_value:
                raise ContractError(f"pending runtime inventory has invalid {key}")
        expected_runtime, static_uncovered, static_unowned, static_duplicate, expected_unclassified = runtime_coverage(
            spec["artifacts"]["stack_runtime_inventory"], Path("/"),
            spec["artifacts"]["galileo_stack_sha256"], features,
        )
        if runtime != expected_runtime:
            raise ContractError("pending runtime inventory normalization drift")
    else:
        raw_runtime = {
            key: runtime.get(key)
            for key in (
                "schema_version", "chart_sha256", "generated_by",
                "observed_categories", "observed_empty_categories", "items",
            )
        }
        expected_runtime, static_uncovered, static_unowned, static_duplicate, expected_unclassified = runtime_coverage(
            spec["artifacts"]["stack_runtime_inventory"], Path("/"),
            spec["artifacts"]["galileo_stack_sha256"],
            features, inventory_override=raw_runtime,
        )
        if runtime != expected_runtime:
            raise ContractError("bundled runtime inventory does not match recomputed classification")

    expected_coverage = build_coverage_report(
        current_matrix, feature_ids_sha, contracts_sha, current_matrix_sha,
        expected_runtime, static_uncovered, static_unowned, static_duplicate,
        expected_unclassified,
    )
    expected_gaps, expected_artifact_evidence = build_gaps(
        spec, Path("/"), expected_coverage
    )
    blocking_count = sum(gap["severity"] == "error" for gap in expected_gaps)
    expected_state = "blocked" if blocking_count else "rendered"
    spec_sha = sha256_bytes(canonical_bytes(spec))
    runtime_sha = sha256_bytes(canonical_bytes(expected_runtime))
    identity = {
        "contract_version": CONTRACT_VERSION,
        "spec_sha256": spec_sha,
        "matrix_sha256": current_matrix_sha,
        "runtime_inventory_sha256": runtime_sha,
    }
    bundle_id = sha256_bytes(canonical_bytes(identity))
    if bundle.name != bundle_id or manifest.get("bundle_id") != bundle_id:
        raise ContractError("bundle identity does not match normalized contents")
    expected_payloads = build_bundle_payloads(
        spec, current_matrix, expected_runtime, expected_coverage, expected_gaps,
        expected_artifact_evidence, bundle_id, identity,
    )
    if listed != set(expected_payloads):
        raise ContractError(
            f"bundle manifest artifact set does not match contract: "
            f"{sorted(listed ^ set(expected_payloads))}"
        )
    for name, expected_content in expected_payloads.items():
        actual_content = read_regular_nofollow(bundle / name)
        if actual_content != expected_content:
            raise ContractError(
                f"bundle artifact does not match recomputed normalized inputs: {name}"
            )
    expected_manifest = build_bundle_manifest(bundle_id, expected_payloads)
    if manifest != expected_manifest or read_regular_nofollow(manifest_path) != pretty_bytes(expected_manifest):
        raise ContractError("bundle manifest does not match recomputed packet artifacts")
    return {
        "valid": True,
        "bundle_dir": str(bundle),
        "bundle_id": bundle_id,
        "state": expected_state,
        "coverage_complete": expected_coverage["coverage_complete"],
        "production_ready": False,
        "blocking_gap_count": blocking_count,
    }


def emit(value: dict[str, Any], json_output: bool) -> None:
    if json_output:
        print(json.dumps(value, indent=2, sort_keys=True))
    else:
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                print(f"{key}: {json.dumps(item, sort_keys=True)}")
            else:
                print(f"{key}: {str(item).lower() if isinstance(item, bool) else item}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--operation", choices=("render", "doctor", "coverage"))
    parser.add_argument("--spec")
    parser.add_argument("--output-dir")
    parser.add_argument("--runtime-inventory", default="")
    parser.add_argument("--galileo-console-url", default="")
    parser.add_argument("--validate-rendered", action="store_true")
    parser.add_argument("--inspect")
    parser.add_argument("--validate-path")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    selected = sum(bool(value) for value in (args.operation, args.inspect, args.validate_path))
    if selected != 1:
        parser.error("select exactly one operation, inspect, or validate-path")
    if args.operation and (not args.spec or not args.output_dir):
        parser.error("render operations require --spec and --output-dir")
    return args


def main() -> int:
    args = parse_args()
    try:
        if args.inspect or args.validate_path:
            result = validate_bundle(Path(args.inspect or args.validate_path))
            result["operation"] = "status" if args.inspect else "validate"
            emit(result, args.json)
            return 0
        _, result, exit_code = render(
            Path(os.path.abspath(Path(args.spec).expanduser())), Path(args.output_dir),
            args.galileo_console_url, args.runtime_inventory, args.operation,
            args.validate_rendered,
        )
        emit(result, args.json)
        return exit_code
    except (ContractError, OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

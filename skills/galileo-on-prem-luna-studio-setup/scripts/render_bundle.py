#!/usr/bin/env python3
"""Render and validate immutable, non-secret Luna Studio bundles."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import stat
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import NoReturn
from urllib.parse import urlsplit, urlunsplit

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "skills" / "shared" / "lib"))
from yaml_compat import dump_yaml, load_yaml_or_json  # noqa: E402

SCHEMA = "galileo-on-prem-luna-studio-bundle/v1"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
DNS = re.compile(r"^(?=.{1,63}$)[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
DNS_SUBDOMAIN = re.compile(
    r"^(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*$"
)
SECRET_KEY = re.compile(r"^[A-Za-z0-9._-]{1,253}$")
SENSITIVE = re.compile(
    r"(?:password|passwd|token|api_?key|secret|private_?key|credential|connection_?string)"
)
SENSITIVE_VALUE = re.compile(
    r"(?i)(?:bearer\s+\S+|(?:password|passwd|token|api[_-]?key|secret|credential)\s*[:=]\s*\S+|-----BEGIN [A-Z ]*PRIVATE KEY-----|https?://[^/@\s:]+:[^/@\s]+@)"
)
SAFE_REFS = {
    "imagepull_secret",
    "imagepullsecret",
    "tls_secret_name",
    "tlssecretname",
    "secret_name",
    "secretname",
    "secret_key_name",
    "secretkeyname",
    "existing_secret",
    "existingsecret",
}


def fail(message: str) -> NoReturn:
    raise SystemExit(f"ERROR: {message}")


@dataclass(frozen=True)
class SecureInput:
    path: Path
    data: bytes
    sha256: str


def secure_read(
    raw: str | Path, label: str, private: bool = False, limit: int = 512 * 1024 * 1024
) -> SecureInput:
    candidate = Path(raw).expanduser()
    path = Path(
        os.path.abspath(
            candidate if candidate.is_absolute() else Path.cwd() / candidate
        )
    )
    cursor = path.parent
    while True:
        try:
            ancestor = os.lstat(cursor)
        except OSError:
            fail(f"{label} has an unavailable ancestor")
        if stat.S_ISLNK(ancestor.st_mode) or not stat.S_ISDIR(ancestor.st_mode):
            fail(f"{label} has a symlink/non-directory ancestor")
        if cursor.parent == cursor:
            break
        cursor = cursor.parent
    try:
        before = os.lstat(path)
    except OSError:
        fail(f"{label} is unavailable")
    if (
        stat.S_ISLNK(before.st_mode)
        or not stat.S_ISREG(before.st_mode)
        or before.st_uid != os.getuid()
        or before.st_nlink != 1
    ):
        fail(f"{label} must be a current-user-owned regular file with one link")
    mode = stat.S_IMODE(before.st_mode)
    if (private and mode & 0o077) or (not private and mode & 0o022):
        fail(f"{label} has unsafe permissions")
    if before.st_size > limit:
        fail(f"{label} exceeds its size limit")
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
        )
    except OSError:
        fail(f"{label} could not be opened safely")
    try:
        opened = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_mtime_ns,
            opened.st_ctime_ns,
        ):
            fail(f"{label} changed before read")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, limit + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > limit:
                fail(f"{label} exceeds its size limit")
        final = os.fstat(descriptor)
        if (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_mtime_ns,
            opened.st_ctime_ns,
        ) != (
            final.st_dev,
            final.st_ino,
            final.st_size,
            final.st_mtime_ns,
            final.st_ctime_ns,
        ):
            fail(f"{label} changed while read")
    finally:
        os.close(descriptor)
    data = b"".join(chunks)
    return SecureInput(path, data, hashlib.sha256(data).hexdigest())


def mapping(artifact: SecureInput) -> dict:
    try:
        value = load_yaml_or_json(artifact.data.decode(), source=str(artifact.path))
    except UnicodeDecodeError:
        fail(f"{artifact.path} is not UTF-8")
    if not isinstance(value, dict):
        fail(f"{artifact.path} must contain a mapping")
    return value


def checked(raw: str, expected: str, label: str) -> SecureInput:
    artifact = secure_read(raw, label)
    if not HEX64.fullmatch(expected) or artifact.sha256 != expected.lower():
        fail(f"{label} SHA-256 mismatch")
    return artifact


def only(value: dict, allowed: set[str], where: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        fail(f"unknown {where} field(s): {', '.join(unknown)}")


def text(value: dict, key: str, where: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result.strip() or "CHANGE_ME" in result:
        fail(f"{where}.{key} must be resolved")
    return result.strip()


def boolean(value: dict, key: str, where: str) -> bool:
    result = value.get(key)
    if not isinstance(result, bool):
        fail(f"{where}.{key} must be boolean")
    return result


def integer_gpu_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        fail("training.gpu.count must be an integer, not a boolean")
    return value


def origin(raw: str) -> str:
    parsed = urlsplit(raw.strip())
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        fail(
            "URL must be an HTTPS origin without credentials, path, query, or fragment"
        )
    try:
        port = parsed.port
    except ValueError:
        fail("URL port is invalid")
    host = parsed.hostname.lower()
    netloc = f"[{host}]" if ":" in host else host
    if port:
        netloc += f":{port}"
    return urlunsplit(("https", netloc, "/", "", ""))


def scan(node: object, location: str = "$") -> None:
    if isinstance(node, dict):
        if str(node.get("kind", "")).lower() == "secret":
            for key in ("data", "stringData"):
                if node.get(key) not in (None, "", {}, []):
                    fail(f"Secret.{key} is forbidden at {location}")
        for key, value in node.items():
            normalized = re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_")
            if normalized in {
                "galileo_secrets",
                "secrets",
                "secret_values",
                "secretvalues",
            } and value not in (None, "", {}, []):
                fail(f"secret subtree is forbidden at {location}.{key}")
            safe = normalized in SAFE_REFS or normalized.endswith(
                ("_secret_name", "_secret_key_name", "secretname", "secretkeyname")
            )
            if (
                SENSITIVE.search(normalized)
                and not safe
                and not isinstance(value, (dict, list))
                and value not in {None, ""}
            ):
                fail(f"secret-like scalar is forbidden at {location}.{key}")
            scan(value, f"{location}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            scan(value, f"{location}[{index}]")
    elif isinstance(node, str) and SENSITIVE_VALUE.search(node):
        fail(f"credential-shaped text is forbidden at {location}")


HELM_ACTION = re.compile(rb"(?s){{-?(.*?)-?}}")
HELM_DYNAMIC_FUNCTION = re.compile(
    rb"(?i)(?<![A-Za-z0-9_.])(?:"
    rb"lookup|tpl|rand[A-Za-z0-9_]*|shuffle|uuidv4|now|ago|date|dateInZone|"
    rb"dateModify|mustDateModify|htmlDate|htmlDateInZone|env|expandenv|"
    rb"getHostByName|genPrivateKey|genCA|genCAWithKey|genSelfSignedCert|"
    rb"genSelfSignedCertWithKey|genSignedCert|genSignedCertWithKey|encryptAES|"
    rb"htpasswd|bcrypt|dig|pluck|call"
    rb")(?=\s|\()"
)
HELM_FILES_ACCESS = re.compile(rb"(?i)(?<![A-Za-z0-9_])\.Files\b")
HELM_RUNTIME_CONTEXT = re.compile(
    rb"(?i)(?:\.(?:Capabilities|Release)\b|[\"'](?:Capabilities|Release|Files)[\"'])"
)
HELM_ROOT_ALIAS = re.compile(
    rb"(?i)\$[A-Za-z_][A-Za-z0-9_]*\s*:?=\s*(?:\.|\$)(?=\s|[|)])"
)
HELM_ROOT_ACCESSOR = re.compile(rb"(?i)(?<![A-Za-z0-9_.])(?:index|get)(?=\s|\()")
HELM_TEXT_SUFFIXES = {".yaml", ".yml", ".tpl", ".txt", ".json"}


def reject_dynamic_helm(body: bytes, label: str) -> None:
    for match in HELM_ACTION.finditer(body):
        action = match.group(1)
        if (
            HELM_DYNAMIC_FUNCTION.search(action)
            or HELM_FILES_ACCESS.search(action)
            or HELM_RUNTIME_CONTEXT.search(action)
            or HELM_ROOT_ALIAS.search(action)
            or HELM_ROOT_ACCESSOR.search(action)
        ):
            fail(
                f"{label} uses nondeterministic, runtime-context, network, environment, tpl, or .Files access; exact client rendering cannot be proven"
            )


def chart(artifact: SecureInput, expected_version: str) -> dict:
    try:
        context = tarfile.open(fileobj=io.BytesIO(artifact.data), mode="r:*")
    except tarfile.TarError:
        fail("chart archive is malformed")
    total = 0
    chart_bytes = None
    chart_count = 0
    seen: set[str] = set()
    roots: set[str] = set()
    templates: list[str] = []
    hooks: list[str] = []
    pvcs: list[str] = []

    def scan_dependency(payload: bytes, prefix: str, depth: int) -> None:
        if depth > 4:
            fail("chart dependency nesting exceeds four levels")
        try:
            dependency = tarfile.open(fileobj=io.BytesIO(payload), mode="r:*")
        except tarfile.TarError:
            fail("chart dependency archive is malformed")
        with dependency:
            if dependency.pax_headers:
                fail("chart dependency contains global PAX overrides")
            members = dependency.getmembers()
            if not members or len(members) > 5000:
                fail("chart dependency member count is invalid")
            names: set[str] = set()
            expanded = 0
            for nested in members:
                nested_name = (
                    nested.name[:-1]
                    if nested.isdir() and nested.name.endswith("/")
                    else nested.name
                )
                nested_path = PurePosixPath(nested_name)
                if (
                    "\\" in nested_name
                    or "//" in nested_name
                    or nested_name.startswith("./")
                    or nested_path.as_posix() != nested_name
                    or nested_path.is_absolute()
                    or ".." in nested_path.parts
                    or "." in nested_path.parts
                    or not nested_path.parts
                    or nested_name in names
                    or len(nested_name) > 1024
                    or nested.pax_headers
                    or nested.issparse()
                    or not (nested.isfile() or nested.isdir())
                ):
                    fail("chart dependency contains unsafe entries")
                names.add(nested_name)
                expanded += nested.size
                if nested.size > 64 * 1024 * 1024 or expanded > 128 * 1024 * 1024:
                    fail("chart dependency exceeds inspection bounds")
                if not nested.isfile():
                    continue
                handle = dependency.extractfile(nested)
                body = handle.read(64 * 1024 * 1024 + 1) if handle else b""
                qualified = f"{prefix}!{nested_name}"
                if len(body) > 64 * 1024 * 1024:
                    fail("chart dependency member exceeds inspection bound")
                if nested_path.suffix == ".tgz" and "charts" in nested_path.parts:
                    scan_dependency(body, qualified, depth + 1)
                if nested_path.suffix.lower() in HELM_TEXT_SUFFIXES:
                    if len(body) > 2 * 1024 * 1024:
                        fail("chart dependency text member exceeds inspection bound")
                    reject_dynamic_helm(body, qualified)
                if "templates" not in nested_path.parts:
                    continue
                if len(body) > 2 * 1024 * 1024:
                    fail("chart dependency template exceeds inspection bound")
                reject_dynamic_helm(body, qualified)
                templates.append(qualified)
                lowered = body.lower()
                if b"helm.sh/hook" in lowered:
                    hooks.append(qualified)
                if (
                    b"kind: persistentvolumeclaim" in lowered
                    or b"volumeclaimtemplates" in lowered
                    or b"finalizers:" in lowered
                ):
                    pvcs.append(qualified)

    with context as archive:
        if archive.pax_headers:
            fail("chart contains global PAX overrides")
        members = archive.getmembers()
        if not members or len(members) > 10000:
            fail("chart member count is invalid")
        for member in members:
            raw_name = (
                member.name[:-1]
                if member.isdir() and member.name.endswith("/")
                else member.name
            )
            pure = PurePosixPath(raw_name)
            canonical = pure.as_posix()
            if (
                "\\" in raw_name
                or "//" in raw_name
                or raw_name.startswith("./")
                or canonical != raw_name
                or pure.is_absolute()
                or ".." in pure.parts
                or "." in pure.parts
                or not pure.parts
                or len(member.name) > 1024
                or canonical in seen
            ):
                fail("chart contains unsafe or duplicate paths")
            seen.add(canonical)
            roots.add(pure.parts[0])
            if (
                not (member.isfile() or member.isdir())
                or member.pax_headers
                or member.issparse()
            ):
                fail("chart contains links, sparse/special types, or PAX overrides")
            if member.size > 64 * 1024 * 1024:
                fail("chart member is oversized")
            total += member.size
            if total > 256 * 1024 * 1024:
                fail("chart expands beyond 256 MiB")
            if member.isfile() and len(pure.parts) == 2 and pure.name == "Chart.yaml":
                chart_count += 1
                handle = archive.extractfile(member)
                chart_bytes = handle.read() if handle else None
            if member.isfile() and "templates" in pure.parts:
                if member.size > 2 * 1024 * 1024:
                    fail("chart template exceeds the inspection bound")
                templates.append(member.name)
                handle = archive.extractfile(member)
                body = handle.read(2 * 1024 * 1024).lower() if handle else b""
                if b"helm.sh/hook" in body:
                    hooks.append(member.name)
                if (
                    b"kind: persistentvolumeclaim" in body
                    or b"volumeclaimtemplates" in body
                    or b"finalizers:" in body
                ):
                    pvcs.append(member.name)
            if (
                member.isfile()
                and pure.suffix.lower() in HELM_TEXT_SUFFIXES
                and "templates" not in pure.parts
            ):
                handle = archive.extractfile(member)
                body = handle.read(2 * 1024 * 1024 + 1) if handle else b""
                if len(body) > 2 * 1024 * 1024:
                    fail("chart text member exceeds the inspection bound")
                reject_dynamic_helm(body, member.name)
            elif member.isfile() and "templates" in pure.parts:
                reject_dynamic_helm(body, member.name)
            if member.isfile() and pure.suffix == ".tgz" and "charts" in pure.parts:
                handle = archive.extractfile(member)
                dependency_body = handle.read(64 * 1024 * 1024 + 1) if handle else b""
                if len(dependency_body) > 64 * 1024 * 1024:
                    fail("chart dependency archive exceeds inspection bound")
                scan_dependency(dependency_body, member.name, 1)
    if roots != {"luna-studio"} or chart_count != 1 or chart_bytes is None:
        fail("chart must have one exact-name root and one root Chart.yaml")
    meta = load_yaml_or_json(chart_bytes.decode(), source=f"{artifact.path}!Chart.yaml")
    if (
        not isinstance(meta, dict)
        or meta.get("apiVersion") != "v2"
        or meta.get("name") != "luna-studio"
    ):
        fail("chart identity must be luna-studio apiVersion v2")
    if (
        str(meta.get("version", "")) != expected_version
        or not str(meta.get("appVersion", "")).strip()
    ):
        fail("chart version/appVersion identity mismatch")
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", expected_version)
    if not match or tuple(map(int, match.groups())) < (2, 1, 5):
        fail("Luna Studio chart must be 2.1.5 or newer")
    return {
        "name": "luna-studio",
        "version": expected_version,
        "app_version": str(meta["appVersion"]),
        "template_files": sorted(templates),
        "hook_templates": sorted(hooks),
        "pvc_templates": sorted(pvcs),
        "expanded_bytes": total,
    }


def write(path: Path, data: bytes | str, mode: int = 0o600) -> None:
    path.write_bytes(data if isinstance(data, bytes) else data.encode())
    path.chmod(mode)


def write_json(path: Path, value: object) -> None:
    write(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def fsync_directory(path: Path) -> None:
    descriptor = os.open(
        path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def bundle_files(root: Path) -> list[Path]:
    paths: list[Path] = []
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        dirs.sort()
        files.sort()
        for name in files:
            if name not in {"MANIFEST.sha256", "BUNDLE.sha256"}:
                paths.append(Path(current) / name)
    return sorted(paths, key=lambda item: item.relative_to(root).as_posix())


def payload(root: Path, identity: bool = False) -> bytes:
    lines = []
    for path in bundle_files(root):
        artifact = secure_read(path, "bundle payload")
        relative = path.relative_to(root).as_posix()
        digest = artifact.sha256
        if identity and relative == "metadata.json":
            try:
                meta = json.loads(artifact.data)
            except json.JSONDecodeError:
                fail("bundle metadata is not valid JSON")
            meta["bundle_sha256"] = "PENDING"
            digest = hashlib.sha256(
                (json.dumps(meta, indent=2, sort_keys=True) + "\n").encode()
            ).hexdigest()
        lines.append(
            f"{digest}  {stat.S_IMODE(os.lstat(path).st_mode):04o}  {relative}"
        )
    return ("\n".join(lines) + "\n").encode()


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def canonical_overlay(contract: dict) -> dict:
    secrets = contract["secret_contracts"]
    store = contract["object_store"]
    route = contract["routing"]
    training = contract["training"]
    resilience = contract["resilience"]
    luna = {
        "enabled": True,
        "networkpolicy_enabled": resilience["network_policy"],
        "frontend_url": route["public_url"],
        "cors_origins": json.dumps([route["public_url"].rstrip("/")]),
        "jwt_secret": {"name": secrets["jwt"]["name"]},
        "admin": {"secret": {"name": secrets["admin"]["name"]}},
        "database": {"enabled": True, "secret_name": secrets["database"]["name"]},
        "ui": {
            "enabled": True,
            "public_url": route["public_url"],
            "nextauth_secret": {"name": secrets["nextauth"]["name"]},
        },
        "cloud_providers": {"provider": store["provider"]},
        "training": {"platform": {"provider": training["provider"]}},
    }
    provider_storage_key = "container" if store["provider"] == "azure" else "bucket"
    luna["cloud_providers"][store["provider"]] = {
        "storage": {provider_storage_key: store["bucket"]},
        "auth": {"mode": store["auth_mode"]},
    }
    auth = secrets["object_auth"]
    if auth:
        luna["cloud_providers"][store["provider"]]["auth"][store["auth_mode"]] = {
            "secret": {"name": auth["name"]}
        }
    if secrets["galileo_api"]:
        luna["galileo_api"] = {"secret": {"name": secrets["galileo_api"]["name"]}}
    if route["mode"] == "ingress":
        luna["ingress"] = {
            "enabled": True,
            "className": route["ingress_class"],
            "tls_secret_name": route["tls_secret_name"],
            "hosts": [
                {
                    "host": urlsplit(route["public_url"]).hostname,
                    "paths": [{"path": "/", "pathType": "Prefix"}],
                }
            ],
        }
    else:
        luna["ingress"] = {"enabled": False}
    if route["mode"] == "gateway":
        luna["gateway"] = {
            "enabled": True,
            "hostnames": [urlsplit(route["public_url"]).hostname],
        }
    if training["provider"] == "kubernetes":
        gpu = training["gpu"]
        luna["training"].update(
            {
                "gpu": {
                    "enabled": gpu["enabled"],
                    "count": gpu["count"],
                    "type": gpu["resource"],
                },
                "nodeSelector": gpu["node_selector"],
                "tolerations": gpu["tolerations"],
            }
        )
        if training["remote"]:
            remote = training["remote"]
            luna["training"]["remote_cluster"] = {
                "enabled": True,
                "api_server": remote["api_server"],
                "namespace": remote["namespace"],
                "secret_name": remote["secret_name"],
                "secret_key": remote["secret_key"],
            }
    else:
        luna["training"]["platform"]["vertex_ai"] = training["vertex_ai"]
    return {"galileo_services": {"luna_finetune": luna}}


def canonical_coverage(contract: dict) -> dict:
    return {
        "schema": "galileo-on-prem-luna-studio-coverage/v1",
        "features": [
            "backend",
            "ui",
            "four-secrets",
            "postgres-asyncpg",
            "alembic",
            "gcs",
            "s3",
            "azure",
            "minio",
            "ingress",
            "gateway",
            "customer-route",
            "kubernetes-training",
            "gpu",
            "vertex-ai",
            "remote-training",
            "hpa",
            "pdb",
            "network-policy",
        ],
        "uncovered": [],
        "unowned": [],
        "duplicate_mutation_owners": [],
        "ownership": contract["deployment"]["ownership"],
    }


def canonical_lifecycle(contract: dict) -> dict:
    deployment = contract["deployment"]
    return {
        "schema": "galileo-on-prem-luna-studio-lifecycle/v1",
        "owner": deployment["ownership"],
        "release": deployment["release_name"],
        "namespace": deployment["namespace"],
        "install_order": [
            "core-api-database-routing",
            "out-of-band-secrets",
            "luna-studio",
            "dns-tls-login-storage",
            "training-validation",
        ],
        "phases": [
            "preflight",
            "status",
            "plan-rollback",
            "plan-uninstall",
        ],
        "mutation_execution": "galileo-cse-joint-session-handoff-only",
        "blocked_apply_modes": [
            "apply-install",
            "apply-upgrade",
            "apply-rollback",
            "apply-uninstall",
        ],
        "handoff_evidence": [
            "metadata.json",
            "lifecycle.json",
            "fresh preflight evidence",
            "fresh rendered image evidence",
            "fresh rendered endpoint evidence",
        ],
        "automatic_rollback": False,
        "umbrella_direct_mutation_allowed": False,
        "secret_contracts": contract["secret_contracts"],
        "training": contract["training"],
    }


def canonical_doctor(contract: dict) -> str:
    return (
        "# Luna Studio doctor\n\n"
        f"- Ownership: `{contract['deployment']['ownership']}`.\n"
        "- Four mandatory Secret contracts are present.\n"
        "- All apply modes are fail-closed Galileo/CSE joint-session handoffs; this skill performs no mutation.\n"
        "- Live database, object-store, migration, GPU, route, and training evidence remains required.\n"
    )


def canonical_metadata(contract: dict, bundle_sha256: str) -> dict:
    deployment = contract["deployment"]
    chart_info = contract["chart"]
    return {
        "schema": SCHEMA,
        "bundle_sha256": bundle_sha256,
        "deployment_id": deployment["id"],
        "environment": deployment["environment"],
        "galileo_console_url": contract["galileo_console_url"],
        "namespace": deployment["namespace"],
        "release_name": deployment["release_name"],
        "ownership": deployment["ownership"],
        "timeout": deployment["timeout"],
        "chart": chart_info,
        "parent_contract_sha256": contract["parent_contract_sha256"],
        "parent_stack": contract["parent_stack"],
        "base_values_sha256": contract["base_values_sha256"],
        "database": contract["database"],
        "secret_contracts": contract["secret_contracts"],
        "object_store": contract["object_store"],
        "routing": contract["routing"],
        "training": contract["training"],
        "resilience": contract["resilience"],
        "cse_reference": contract["approval"]["cse_reference"],
        "chart_has_delete_risk": bool(
            chart_info and (chart_info["hook_templates"] or chart_info["pvc_templates"])
        ),
    }


def validate_bundle(root: Path) -> dict:
    try:
        root_info = os.lstat(root)
    except OSError:
        fail("bundle is unavailable")
    if (
        not stat.S_ISDIR(root_info.st_mode)
        or stat.S_ISLNK(root_info.st_mode)
        or root_info.st_uid != os.getuid()
        or stat.S_IMODE(root_info.st_mode) != 0o700
    ):
        fail("bundle root must be current-user-owned mode 0700")
    for current, dirs, files in os.walk(root, followlinks=False):
        for name in dirs:
            info = os.lstat(Path(current) / name)
            if (
                not stat.S_ISDIR(info.st_mode)
                or stat.S_ISLNK(info.st_mode)
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o700
            ):
                fail("bundle directory contract failed")
        for name in files:
            info = os.lstat(Path(current) / name)
            if (
                not stat.S_ISREG(info.st_mode)
                or stat.S_ISLNK(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) not in {0o600, 0o700}
            ):
                fail("bundle file contract failed")
    manifest = root / "MANIFEST.sha256"
    digest_file = root / "BUNDLE.sha256"
    manifest_artifact = secure_read(manifest, "bundle manifest")
    digest_artifact = secure_read(digest_file, "bundle digest")
    if manifest_artifact.data != payload(root):
        fail("bundle manifest drifted")
    digest = hashlib.sha256(payload(root, identity=True)).hexdigest()
    try:
        recorded_digest = digest_artifact.data.decode("ascii").strip()
    except UnicodeDecodeError:
        fail("bundle digest is not ASCII")
    if recorded_digest != digest:
        fail("bundle digest drifted")
    contract_artifact = secure_read(
        root / "normalized-spec.json", "normalized deployment spec"
    )
    contract = mapping(contract_artifact)
    if contract_artifact.data != canonical_json(contract):
        fail("normalized deployment spec is not canonical JSON")
    only(
        contract,
        {
            "schema",
            "galileo_console_url",
            "deployment",
            "chart",
            "parent_contract_sha256",
            "parent_stack",
            "ownership_evidence_sha256",
            "base_values_sha256",
            "database",
            "secret_contracts",
            "object_store",
            "routing",
            "training",
            "resilience",
            "approval",
        },
        "normalized deployment spec",
    )
    if contract.get("schema") != "galileo-on-prem-luna-studio-normalized-spec/v1":
        fail("normalized deployment spec schema is unsupported")
    for name, keys in (
        (
            "deployment",
            {"id", "environment", "namespace", "release_name", "ownership", "timeout"},
        ),
        ("database", {"preprovisioned", "asyncpg", "startup_migrations"}),
        ("object_store", {"provider", "auth_mode", "bucket"}),
        ("routing", {"mode", "public_url", "tls_secret_name", "ingress_class"}),
        ("resilience", {"hpa", "pdb", "network_policy"}),
        ("approval", {"cse_reference", "production_values_approved"}),
    ):
        value = contract.get(name)
        if not isinstance(value, dict):
            fail(f"normalized deployment spec {name} is not a mapping")
        only(value, keys, f"normalized deployment spec {name}")
    deployment_contract = contract["deployment"]
    if (
        deployment_contract.get("environment")
        not in {"development", "staging", "production"}
        or deployment_contract.get("release_name") != "luna-studio"
        or deployment_contract.get("ownership")
        not in {"standalone", "umbrella-overlay"}
        or not DNS.fullmatch(str(deployment_contract.get("namespace", "")))
        or not re.fullmatch(
            r"[1-9][0-9]*[smh]", str(deployment_contract.get("timeout", ""))
        )
    ):
        fail("normalized deployment target is invalid")
    if origin(str(contract.get("galileo_console_url", ""))) != contract.get(
        "galileo_console_url"
    ):
        fail("normalized Galileo console URL is invalid")
    if any(contract["database"].get(key) is not True for key in contract["database"]):
        fail("normalized database readiness contract is invalid")
    if any(
        not isinstance(contract[section].get(key), bool)
        for section, keys in (
            ("resilience", ("hpa", "pdb", "network_policy")),
            ("approval", ("production_values_approved",)),
        )
        for key in keys
    ):
        fail("normalized boolean policy is invalid")
    if deployment_contract["environment"] == "production" and (
        not all(contract["resilience"].values())
        or contract["approval"]["production_values_approved"] is not True
    ):
        fail("normalized production resilience/approval policy is invalid")
    store_contract = contract["object_store"]
    supported_modes = {
        "gcp": {"workload_identity", "oidc", "service_account"},
        "aws": {"irsa", "static", "sts"},
        "azure": {"managed_identity", "connection_string", "sas"},
        "minio": {"static"},
    }
    if (
        store_contract.get("provider") not in supported_modes
        or store_contract.get("auth_mode")
        not in supported_modes[store_contract["provider"]]
        or not isinstance(store_contract.get("bucket"), str)
        or not store_contract["bucket"].strip()
    ):
        fail("normalized object-store contract is invalid")
    route_contract = contract["routing"]
    if (
        route_contract.get("mode") not in {"ingress", "gateway", "customer"}
        or origin(str(route_contract.get("public_url", "")))
        != route_contract.get("public_url")
        or not DNS_SUBDOMAIN.fullmatch(str(route_contract.get("tls_secret_name", "")))
        or not isinstance(route_contract.get("ingress_class"), str)
        or (
            route_contract["mode"] == "ingress"
            and not DNS_SUBDOMAIN.fullmatch(route_contract["ingress_class"])
        )
    ):
        fail("normalized routing contract is invalid")
    training_contract = contract.get("training")
    if not isinstance(training_contract, dict):
        fail("normalized training contract is not a mapping")
    only(
        training_contract,
        {"provider", "remote", "gpu", "vertex_ai"},
        "normalized training contract",
    )
    gpu_contract = training_contract.get("gpu")
    if not isinstance(gpu_contract, dict):
        fail("normalized GPU contract is not a mapping")
    only(
        gpu_contract,
        {"enabled", "count", "resource", "node_selector", "tolerations"},
        "normalized GPU contract",
    )
    if training_contract.get("provider") not in {"kubernetes", "vertex_ai"}:
        fail("normalized training provider is invalid")
    secret_contracts = contract.get("secret_contracts")
    if not isinstance(secret_contracts, dict):
        fail("normalized Secret contracts are not a mapping")
    only(
        secret_contracts,
        {
            "jwt",
            "admin",
            "database",
            "nextauth",
            "galileo_api",
            "object_auth",
            "remote",
        },
        "normalized Secret contracts",
    )
    for name in ("jwt", "admin", "database", "nextauth"):
        item = secret_contracts.get(name)
        if not isinstance(item, dict) or set(item) != {"name", "keys"}:
            fail(f"normalized mandatory Secret contract {name} is invalid")
    conditional_auth = store_contract["auth_mode"] not in {
        "workload_identity",
        "irsa",
        "managed_identity",
    }
    if conditional_auth != bool(secret_contracts.get("object_auth")):
        fail("normalized object-store Secret selection is invalid")
    meta_artifact = secure_read(root / "metadata.json", "bundle metadata")
    meta = mapping(meta_artifact)
    if meta_artifact.data != canonical_json(meta):
        fail("bundle metadata is not canonical duplicate-free JSON")
    if meta.get("schema") != SCHEMA or meta.get("bundle_sha256") != digest:
        fail("bundle metadata contract failed")
    only(
        meta,
        {
            "schema",
            "bundle_sha256",
            "deployment_id",
            "environment",
            "galileo_console_url",
            "namespace",
            "release_name",
            "ownership",
            "timeout",
            "chart",
            "parent_contract_sha256",
            "parent_stack",
            "base_values_sha256",
            "database",
            "secret_contracts",
            "object_store",
            "routing",
            "training",
            "resilience",
            "cse_reference",
            "chart_has_delete_risk",
        },
        "bundle metadata",
    )
    if meta != canonical_metadata(contract, digest):
        fail("bundle metadata differs from the normalized deployment spec")
    if (
        meta.get("ownership") not in {"standalone", "umbrella-overlay"}
        or meta.get("release_name") != "luna-studio"
        or not DNS.fullmatch(str(meta.get("namespace", "")))
    ):
        fail("bundle ownership/target identity is invalid")
    if origin(str(meta.get("galileo_console_url", ""))) != meta.get(
        "galileo_console_url"
    ):
        fail("bundle Galileo console URL is not canonical")
    if (
        not isinstance(meta.get("parent_contract_sha256"), str)
        or not HEX64.fullmatch(meta["parent_contract_sha256"])
        or not isinstance(meta.get("base_values_sha256"), str)
        or not HEX64.fullmatch(meta["base_values_sha256"])
    ):
        fail("bundle source hashes are invalid")
    parent_artifact = secure_read(
        root / "artifacts" / "parent-stack-contract.json", "parent stack contract"
    )
    parent_doc = mapping(parent_artifact)
    if parent_artifact.data != canonical_json(parent_doc):
        fail("parent stack contract is not canonical duplicate-free JSON")
    only(
        parent_doc,
        {"schema", "release", "namespace", "bundle_sha256", "chart", "target"},
        "parent stack contract",
    )
    expected_parent = {
        "release": parent_doc.get("release"),
        "bundle_sha256": parent_doc.get("bundle_sha256"),
        "chart": parent_doc.get("chart"),
        "target": parent_doc.get("target"),
    }
    if (
        parent_artifact.sha256 != meta["parent_contract_sha256"]
        or parent_doc.get("schema") != "galileo-on-prem-stack-release-contract/v1"
        or parent_doc.get("namespace") != meta["namespace"]
        or meta.get("parent_stack") != expected_parent
    ):
        fail("bundle parent identity contract is invalid")
    if contract.get("parent_stack") != expected_parent:
        fail("normalized parent identity differs from the bundled contract")
    base_artifact = secure_read(root / "values" / "base-values.yaml", "base values")
    if base_artifact.sha256 != meta["base_values_sha256"]:
        fail("bundle base-values hash is invalid")
    if base_artifact.sha256 != contract.get("base_values_sha256"):
        fail("normalized spec base-values binding is invalid")
    scan(mapping(base_artifact))
    overlay_artifact = secure_read(
        root / "values" / "luna-studio-overlay.yaml", "Luna overlay"
    )
    scan(mapping(overlay_artifact))
    if overlay_artifact.data != dump_yaml(canonical_overlay(contract)).encode():
        fail("Luna overlay differs from exact normalized semantics")
    if meta["ownership"] == "standalone":
        chart_artifact = secure_read(
            root / "artifacts" / "luna-studio.tgz", "Luna Studio chart"
        )
        chart_meta = meta.get("chart")
        if (
            not isinstance(chart_meta, dict)
            or set(chart_meta)
            != {
                "name",
                "version",
                "app_version",
                "template_files",
                "hook_templates",
                "pvc_templates",
                "expanded_bytes",
                "sha256",
            }
            or chart_meta.get("sha256") != chart_artifact.sha256
        ):
            fail("bundle chart metadata is invalid")
        inspected = chart(chart_artifact, str(chart_meta.get("version", "")))
        inspected["sha256"] = chart_artifact.sha256
        if chart_meta != inspected:
            fail("bundle chart inspection has drifted")
        if contract.get("chart") != chart_meta:
            fail("normalized chart identity differs from the bundled chart")
        if contract.get("ownership_evidence_sha256") is not None:
            fail("standalone normalized spec unexpectedly binds umbrella ownership")
    else:
        if meta.get("chart") is not None:
            fail("umbrella overlay must not carry standalone chart metadata")
        proof_artifact = secure_read(
            root / "artifacts" / "umbrella-ownership-evidence.json",
            "ownership evidence",
        )
        proof = mapping(proof_artifact)
        if proof_artifact.data != canonical_json(proof):
            fail("umbrella ownership evidence is not canonical duplicate-free JSON")
        only(
            proof,
            {"schema", "component", "owner", "parent_bundle_sha256", "parent_chart"},
            "ownership evidence",
        )
        if proof != {
            "schema": "galileo-on-prem-umbrella-ownership-evidence/v1",
            "component": "luna-studio",
            "owner": "galileo-stack",
            "parent_bundle_sha256": parent_doc.get("bundle_sha256"),
            "parent_chart": parent_doc.get("chart"),
        }:
            fail("umbrella ownership evidence is invalid")
        if (
            contract.get("ownership_evidence_sha256")
            != secure_read(
                root / "artifacts" / "umbrella-ownership-evidence.json",
                "ownership evidence",
            ).sha256
        ):
            fail("normalized umbrella evidence digest differs")
        if contract.get("chart") is not None:
            fail("umbrella normalized spec unexpectedly binds a standalone chart")
    coverage = mapping(secure_read(root / "coverage-report.json", "coverage report"))
    lifecycle = mapping(secure_read(root / "lifecycle.json", "lifecycle contract"))
    if secure_read(
        root / "coverage-report.json", "coverage report"
    ).data != canonical_json(canonical_coverage(contract)):
        fail("coverage report differs from exact normalized semantics")
    if secure_read(
        root / "lifecycle.json", "lifecycle contract"
    ).data != canonical_json(canonical_lifecycle(contract)):
        fail("lifecycle contract differs from exact normalized semantics")
    if (
        secure_read(root / "doctor-report.md", "doctor report").data
        != canonical_doctor(contract).encode()
    ):
        fail("doctor report differs from exact normalized semantics")
    only(
        coverage,
        {
            "schema",
            "features",
            "uncovered",
            "unowned",
            "duplicate_mutation_owners",
            "ownership",
        },
        "coverage report",
    )
    only(
        lifecycle,
        {
            "schema",
            "owner",
            "release",
            "namespace",
            "install_order",
            "phases",
            "mutation_execution",
            "blocked_apply_modes",
            "handoff_evidence",
            "automatic_rollback",
            "umbrella_direct_mutation_allowed",
            "secret_contracts",
            "training",
        },
        "lifecycle contract",
    )
    if (
        coverage.get("schema") != "galileo-on-prem-luna-studio-coverage/v1"
        or coverage.get("ownership") != meta["ownership"]
        or coverage.get("uncovered") != []
        or coverage.get("unowned") != []
        or coverage.get("duplicate_mutation_owners") != []
    ):
        fail("bundle coverage contract is invalid")
    if (
        lifecycle.get("schema") != "galileo-on-prem-luna-studio-lifecycle/v1"
        or lifecycle.get("owner") != meta["ownership"]
        or lifecycle.get("release") != "luna-studio"
        or lifecycle.get("namespace") != meta["namespace"]
        or lifecycle.get("secret_contracts") != meta.get("secret_contracts")
        or lifecycle.get("training") != meta.get("training")
        or lifecycle.get("mutation_execution")
        != "galileo-cse-joint-session-handoff-only"
        or lifecycle.get("blocked_apply_modes")
        != [
            "apply-install",
            "apply-upgrade",
            "apply-rollback",
            "apply-uninstall",
        ]
        or lifecycle.get("automatic_rollback") is not False
        or lifecycle.get("umbrella_direct_mutation_allowed") is not False
    ):
        fail("bundle lifecycle contract is invalid")
    expected_files = {
        "metadata.json",
        "coverage-report.json",
        "lifecycle.json",
        "doctor-report.md",
        "normalized-spec.json",
        "values/base-values.yaml",
        "values/luna-studio-overlay.yaml",
        "artifacts/parent-stack-contract.json",
        "MANIFEST.sha256",
        "BUNDLE.sha256",
    }
    expected_files.add(
        "artifacts/luna-studio.tgz"
        if meta.get("ownership") == "standalone"
        else "artifacts/umbrella-ownership-evidence.json"
    )
    actual_files: set[str] = set()
    actual_dirs: set[str] = set()
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        for name in dirs:
            actual_dirs.add((Path(current) / name).relative_to(root).as_posix())
        for name in files:
            actual_files.add((Path(current) / name).relative_to(root).as_posix())
    if actual_files != expected_files or actual_dirs != {"values", "artifacts"}:
        fail("bundle contains missing or extra files/directories")
    for relative in actual_files:
        if stat.S_IMODE(os.lstat(root / relative).st_mode) != 0o600:
            fail("bundle file mode must be exactly 0600")
    return meta


def secret_ref(
    secrets: dict, key: str, expected_keys: list[str], required: bool = True
) -> dict | None:
    value = secrets.get(key)
    if not isinstance(value, dict):
        fail(f"secrets.{key} must be a mapping")
    only(value, {"enabled", "name", "keys"}, f"secrets.{key}")
    enabled = (
        boolean(value, "enabled", f"secrets.{key}") if "enabled" in value else required
    )
    if required and not enabled:
        fail(f"secrets.{key} is mandatory")
    if not enabled:
        return None
    name = text(value, "name", f"secrets.{key}")
    keys = value.get("keys")
    if (
        not DNS_SUBDOMAIN.fullmatch(name)
        or not isinstance(keys, list)
        or len(keys) != len(set(keys))
        or any(
            not isinstance(item, str) or not SECRET_KEY.fullmatch(item) for item in keys
        )
    ):
        fail(f"secrets.{key} contract is invalid")
    if expected_keys and set(keys) != set(expected_keys):
        fail(f"secrets.{key} keys differ from the documented contract")
    return {"name": name, "keys": sorted(keys)}


def render(spec_artifact: SecureInput, output: Path, console_arg: str) -> None:
    spec = mapping(spec_artifact)
    only(
        spec,
        {
            "api_version",
            "galileo",
            "deployment",
            "chart",
            "umbrella",
            "values",
            "secrets",
            "database",
            "object_store",
            "routing",
            "training",
            "resilience",
            "approval",
        },
        "root",
    )
    if spec.get("api_version") != "galileo-on-prem-luna-studio-setup/v1":
        fail("api_version is unsupported")
    console = origin(console_arg)
    galileo = spec.get("galileo")
    if not isinstance(galileo, dict):
        fail("galileo must be a mapping")
    only(galileo, {"console_url"}, "galileo")
    if galileo.get("console_url") and origin(galileo["console_url"]) != console:
        fail("CLI and spec Galileo console URLs differ")
    deployment = spec.get("deployment")
    chart_spec = spec.get("chart")
    parent = spec.get("umbrella")
    values = spec.get("values")
    for name, value in (
        ("deployment", deployment),
        ("chart", chart_spec),
        ("umbrella", parent),
        ("values", values),
    ):
        if not isinstance(value, dict):
            fail(f"{name} must be a mapping")
    only(
        deployment,
        {"id", "environment", "namespace", "release_name", "ownership", "timeout"},
        "deployment",
    )
    deployment_id = text(deployment, "id", "deployment")
    environment = text(deployment, "environment", "deployment")
    if environment not in {"development", "staging", "production"}:
        fail("deployment.environment is invalid")
    namespace = text(deployment, "namespace", "deployment")
    release = text(deployment, "release_name", "deployment")
    if not DNS.fullmatch(namespace) or release != "luna-studio":
        fail("namespace/release identity is invalid")
    ownership = text(deployment, "ownership", "deployment")
    timeout = text(deployment, "timeout", "deployment")
    if ownership not in {"standalone", "umbrella-overlay"} or not re.fullmatch(
        r"[1-9][0-9]*[smh]", timeout
    ):
        fail("ownership or timeout is invalid")
    only(
        parent,
        {
            "parent_contract_file",
            "parent_contract_sha256",
            "ownership_evidence_file",
            "ownership_evidence_sha256",
        },
        "umbrella",
    )
    parent_artifact = checked(
        text(parent, "parent_contract_file", "umbrella"),
        text(parent, "parent_contract_sha256", "umbrella"),
        "parent stack contract",
    )
    parent_doc = mapping(parent_artifact)
    if parent_artifact.data != canonical_json(parent_doc):
        fail("parent stack contract must be canonical duplicate-free JSON")
    only(
        parent_doc,
        {"schema", "release", "namespace", "bundle_sha256", "chart", "target"},
        "parent stack contract",
    )
    required_target = {
        "context",
        "api_server",
        "ca_sha256",
        "kube_system_uid",
        "namespace_uid",
    }
    parent_target = parent_doc.get("target")
    parent_chart = parent_doc.get("chart")
    valid_parent_chart = (
        isinstance(parent_chart, dict)
        and set(parent_chart) == {"name", "version", "sha256"}
        and parent_chart.get("name") == "galileo-stack"
        and isinstance(parent_chart.get("version"), str)
        and bool(parent_chart["version"].strip())
        and HEX64.fullmatch(str(parent_chart.get("sha256", "")))
    )
    if (
        parent_doc.get("schema") != "galileo-on-prem-stack-release-contract/v1"
        or parent_doc.get("namespace") != namespace
        or not isinstance(parent_doc.get("release"), str)
        or not HEX64.fullmatch(str(parent_doc.get("bundle_sha256", "")))
        or not valid_parent_chart
        or not isinstance(parent_target, dict)
        or set(parent_target) != required_target
        or any(
            not isinstance(parent_target[k], str) or not parent_target[k]
            for k in required_target
        )
    ):
        fail("parent stack release contract is incomplete or targets another namespace")
    if not str(parent_target["api_server"]).startswith(
        "https://"
    ) or not HEX64.fullmatch(str(parent_target["ca_sha256"])):
        fail("parent stack target endpoint/CA identity is invalid")
    only(chart_spec, {"archive", "sha256", "version"}, "chart")
    chart_artifact = None
    chart_info = None
    ownership_artifact = None
    if ownership == "standalone":
        if any(
            str(parent.get(k, "")).strip()
            for k in ("ownership_evidence_file", "ownership_evidence_sha256")
        ):
            fail("standalone mode rejects umbrella ownership evidence")
        chart_artifact = checked(
            text(chart_spec, "archive", "chart"),
            text(chart_spec, "sha256", "chart"),
            "Luna Studio chart",
        )
        chart_info = chart(chart_artifact, text(chart_spec, "version", "chart"))
        chart_info["sha256"] = chart_artifact.sha256
    else:
        if any(
            str(chart_spec.get(k, "")).strip() for k in ("archive", "sha256", "version")
        ):
            fail("umbrella-overlay rejects a standalone chart")
        ownership_artifact = checked(
            text(parent, "ownership_evidence_file", "umbrella"),
            text(parent, "ownership_evidence_sha256", "umbrella"),
            "umbrella ownership evidence",
        )
        proof = mapping(ownership_artifact)
        if ownership_artifact.data != canonical_json(proof):
            fail("ownership evidence must be canonical duplicate-free JSON")
        only(
            proof,
            {"schema", "component", "owner", "parent_bundle_sha256", "parent_chart"},
            "umbrella ownership evidence",
        )
        if (
            proof.get("schema") != "galileo-on-prem-umbrella-ownership-evidence/v1"
            or proof.get("component") != "luna-studio"
            or proof.get("owner") != "galileo-stack"
            or proof.get("parent_bundle_sha256") != parent_doc["bundle_sha256"]
            or proof.get("parent_chart") != parent_chart
        ):
            fail(
                "umbrella evidence does not bind Luna to the exact parent Stack package"
            )
    only(values, {"base_file", "base_sha256"}, "values")
    base_artifact = checked(
        text(values, "base_file", "values"),
        text(values, "base_sha256", "values"),
        "non-secret base values",
    )
    scan(mapping(base_artifact))
    secrets = spec.get("secrets")
    if not isinstance(secrets, dict):
        fail("secrets must be a mapping")
    only(secrets, {"jwt", "admin", "database", "nextauth", "galileo_api"}, "secrets")
    contracts = {
        "jwt": secret_ref(secrets, "jwt", ["jwt-secret-key"]),
        "admin": secret_ref(secrets, "admin", ["username", "password"]),
        "database": secret_ref(
            secrets,
            "database",
            ["connection-string", "host", "port", "database", "username", "password"],
        ),
        "nextauth": secret_ref(secrets, "nextauth", ["secret"]),
        "galileo_api": secret_ref(
            secrets, "galileo_api", ["api-url", "api-key"], required=False
        ),
    }
    database = spec.get("database")
    if not isinstance(database, dict):
        fail("database must be a mapping")
    only(database, {"preprovisioned", "asyncpg", "startup_migrations"}, "database")
    if not all(
        boolean(database, key, "database")
        for key in ("preprovisioned", "asyncpg", "startup_migrations")
    ):
        fail("Luna requires pre-provisioned asyncpg database and startup migrations")
    store = spec.get("object_store")
    if not isinstance(store, dict):
        fail("object_store must be a mapping")
    only(store, {"provider", "auth_mode", "bucket", "auth_secret"}, "object_store")
    provider = text(store, "provider", "object_store")
    auth_mode = text(store, "auth_mode", "object_store")
    bucket = text(store, "bucket", "object_store")
    modes = {
        "gcp": {"workload_identity", "oidc", "service_account"},
        "aws": {"irsa", "static", "sts"},
        "azure": {"managed_identity", "connection_string", "sas"},
        "minio": {"static"},
    }
    if provider not in modes or auth_mode not in modes[provider]:
        fail("object-store provider/auth mode is invalid")
    auth_secret = store.get("auth_secret")
    if not isinstance(auth_secret, dict):
        fail("object_store.auth_secret must be a mapping")
    only(auth_secret, {"name", "keys"}, "object_store.auth_secret")
    conditional = auth_mode not in {"workload_identity", "irsa", "managed_identity"}
    if not conditional and (
        str(auth_secret.get("name", "")).strip()
        or auth_secret.get("keys") not in (None, [])
    ):
        fail("identity-based object-store auth rejects a static auth Secret")
    auth_contract = secret_ref(
        {"auth": {**auth_secret, "enabled": conditional}}, "auth", [], required=False
    )
    if conditional and (auth_contract is None or not auth_contract["keys"]):
        fail(
            "selected object-store auth mode requires a non-empty out-of-band Secret contract"
        )
    route = spec.get("routing")
    if not isinstance(route, dict):
        fail("routing must be a mapping")
    only(route, {"mode", "public_url", "tls_secret_name", "ingress_class"}, "routing")
    route_mode = text(route, "mode", "routing")
    public_url = origin(text(route, "public_url", "routing"))
    route_host = urlsplit(public_url).hostname
    tls_name = text(route, "tls_secret_name", "routing")
    if route_mode not in {
        "ingress",
        "gateway",
        "customer",
    } or not DNS_SUBDOMAIN.fullmatch(tls_name):
        fail("routing contract is invalid")
    if not isinstance(route_host, str) or not DNS_SUBDOMAIN.fullmatch(route_host):
        fail("routing.public_url must use one exact DNS hostname without wildcards")
    if route_mode == "ingress" and not DNS_SUBDOMAIN.fullmatch(
        text(route, "ingress_class", "routing")
    ):
        fail("routing.ingress_class is invalid")
    training = spec.get("training")
    if not isinstance(training, dict):
        fail("training must be a mapping")
    only(training, {"provider", "remote_cluster", "gpu", "vertex_ai"}, "training")
    training_provider = text(training, "provider", "training")
    if training_provider not in {"kubernetes", "vertex_ai"}:
        fail("training.provider is invalid")
    remote = training.get("remote_cluster")
    gpu = training.get("gpu")
    vertex = training.get("vertex_ai")
    if (
        not isinstance(remote, dict)
        or not isinstance(gpu, dict)
        or not isinstance(vertex, dict)
    ):
        fail("training subcontracts must be mappings")
    only(
        remote,
        {
            "enabled",
            "api_server",
            "ca_sha256",
            "kube_system_uid",
            "namespace",
            "namespace_uid",
            "secret_name",
            "secret_key",
        },
        "training.remote_cluster",
    )
    remote_enabled = boolean(remote, "enabled", "training.remote_cluster")
    remote_contract = None
    if remote_enabled:
        if training_provider != "kubernetes" or not str(
            remote.get("api_server", "")
        ).startswith("https://"):
            fail("remote training requires kubernetes and an HTTPS API server")
        remote_contract = {
            key: text(remote, key, "training.remote_cluster")
            for key in (
                "api_server",
                "ca_sha256",
                "kube_system_uid",
                "namespace",
                "namespace_uid",
                "secret_name",
                "secret_key",
            )
        }
        if (
            origin(remote_contract["api_server"]) != remote_contract["api_server"]
            or not HEX64.fullmatch(remote_contract["ca_sha256"])
            or not DNS.fullmatch(remote_contract["namespace"])
            or not DNS_SUBDOMAIN.fullmatch(remote_contract["secret_name"])
            or not SECRET_KEY.fullmatch(remote_contract["secret_key"])
        ):
            fail("remote training identity/Secret contract is invalid")
    only(
        gpu,
        {"enabled", "count", "resource", "node_selector", "tolerations"},
        "training.gpu",
    )
    gpu_enabled = boolean(gpu, "enabled", "training.gpu")
    count = integer_gpu_count(gpu.get("count"))
    selector = gpu.get("node_selector")
    tolerations = gpu.get("tolerations")
    if gpu_enabled:
        valid_selector = (
            isinstance(selector, dict)
            and selector
            and all(
                isinstance(k, str) and k and isinstance(v, str)
                for k, v in selector.items()
            )
        )
        valid_tolerations = (
            isinstance(tolerations, list)
            and tolerations
            and all(
                isinstance(item, dict)
                and set(item) <= {"key", "operator", "value", "effect"}
                and isinstance(item.get("key"), str)
                and item["key"]
                and item.get("operator", "Equal") in {"Equal", "Exists"}
                and item.get("effect", "")
                in {"", "NoSchedule", "PreferNoSchedule", "NoExecute"}
                for item in tolerations
            )
        )
        if (
            training_provider != "kubernetes"
            or count < 1
            or gpu.get("resource") != "nvidia.com/gpu"
            or not valid_selector
            or not valid_tolerations
        ):
            fail(
                "GPU training requires positive NVIDIA capacity, selector, and structured tolerations"
            )
    elif count != 0:
        fail("CPU training must request zero GPUs")
    only(
        vertex,
        {"project_id", "location", "pipeline_name", "pipeline_root"},
        "training.vertex_ai",
    )
    vertex_contract = None
    if training_provider == "vertex_ai":
        if remote_enabled or gpu_enabled:
            fail("Vertex AI rejects remote-cluster and in-cluster GPU settings")
        vertex_contract = {
            key: text(vertex, key, "training.vertex_ai")
            for key in ("project_id", "location", "pipeline_name", "pipeline_root")
        }
        if not vertex_contract["pipeline_root"].startswith("gs://"):
            fail("Vertex pipeline_root must use gs://")
    resilience = spec.get("resilience")
    approval = spec.get("approval")
    if not isinstance(resilience, dict) or not isinstance(approval, dict):
        fail("resilience and approval must be mappings")
    only(resilience, {"hpa", "pdb", "network_policy"}, "resilience")
    resilience_contract = {
        key: boolean(resilience, key, "resilience")
        for key in ("hpa", "pdb", "network_policy")
    }
    for key, enabled in resilience_contract.items():
        if environment == "production" and not enabled:
            fail(f"production requires resilience.{key}")
    only(approval, {"cse_reference", "production_values_approved"}, "approval")
    cse = text(approval, "cse_reference", "approval")
    production_approved = boolean(approval, "production_values_approved", "approval")
    if environment == "production" and not production_approved:
        fail("production values require Galileo approval")
    training_contract = {
        "provider": training_provider,
        "remote": remote_contract,
        "gpu": {
            "enabled": gpu_enabled,
            "count": count,
            "resource": gpu.get("resource"),
            "node_selector": selector,
            "tolerations": tolerations,
        },
        "vertex_ai": vertex_contract,
    }
    secret_contracts = {
        **contracts,
        "object_auth": auth_contract,
        "remote": (
            {
                "name": remote_contract["secret_name"],
                "keys": [remote_contract["secret_key"]],
            }
            if remote_contract
            else None
        ),
    }
    ingress_class = (
        text(route, "ingress_class", "routing")
        if route_mode == "ingress"
        else str(route.get("ingress_class", "")).strip()
    )
    contract = {
        "schema": "galileo-on-prem-luna-studio-normalized-spec/v1",
        "galileo_console_url": console,
        "deployment": {
            "id": deployment_id,
            "environment": environment,
            "namespace": namespace,
            "release_name": release,
            "ownership": ownership,
            "timeout": timeout,
        },
        "chart": chart_info,
        "parent_contract_sha256": parent_artifact.sha256,
        "parent_stack": {
            "release": parent_doc["release"],
            "bundle_sha256": parent_doc["bundle_sha256"],
            "chart": parent_chart,
            "target": parent_target,
        },
        "ownership_evidence_sha256": (
            ownership_artifact.sha256 if ownership_artifact else None
        ),
        "base_values_sha256": base_artifact.sha256,
        "database": {
            key: boolean(database, key, "database")
            for key in ("preprovisioned", "asyncpg", "startup_migrations")
        },
        "secret_contracts": secret_contracts,
        "object_store": {
            "provider": provider,
            "auth_mode": auth_mode,
            "bucket": bucket,
        },
        "routing": {
            "mode": route_mode,
            "public_url": public_url,
            "tls_secret_name": tls_name,
            "ingress_class": ingress_class,
        },
        "training": training_contract,
        "resilience": resilience_contract,
        "approval": {
            "cse_reference": cse,
            "production_values_approved": production_approved,
        },
    }
    overlay = canonical_overlay(contract)
    if output in {
        Path("/"),
        Path.home(),
        REPO_ROOT,
        Path.cwd(),
        Path(tempfile.gettempdir()),
    } or os.path.lexists(output):
        fail("output path is broad or already exists")
    if not output.parent.is_dir():
        fail("output parent must already exist")
    parent_info = os.lstat(output.parent)
    if parent_info.st_uid != os.getuid() or stat.S_IMODE(parent_info.st_mode) & 0o022:
        fail("output parent must be current-user-owned and not group/world writable")
    cursor = output.parent
    while True:
        info = os.lstat(cursor)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            fail("output path contains a symlink/non-directory ancestor")
        if cursor.parent == cursor:
            break
        cursor = cursor.parent
    temp = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    temp.chmod(0o700)
    try:
        (temp / "values").mkdir(mode=0o700)
        (temp / "artifacts").mkdir(mode=0o700)
        write(temp / "normalized-spec.json", canonical_json(contract))
        write(temp / "values" / "base-values.yaml", base_artifact.data)
        write(temp / "values" / "luna-studio-overlay.yaml", dump_yaml(overlay))
        write(temp / "artifacts" / "parent-stack-contract.json", parent_artifact.data)
        if chart_artifact:
            write(temp / "artifacts" / "luna-studio.tgz", chart_artifact.data)
        if ownership_artifact:
            write(
                temp / "artifacts" / "umbrella-ownership-evidence.json",
                ownership_artifact.data,
            )
        write_json(temp / "coverage-report.json", canonical_coverage(contract))
        write_json(temp / "lifecycle.json", canonical_lifecycle(contract))
        write(temp / "doctor-report.md", canonical_doctor(contract))
        metadata = canonical_metadata(contract, "PENDING")
        write_json(temp / "metadata.json", metadata)
        identity = hashlib.sha256(payload(temp, identity=True)).hexdigest()
        metadata["bundle_sha256"] = identity
        write_json(temp / "metadata.json", metadata)
        write(temp / "MANIFEST.sha256", payload(temp))
        write(temp / "BUNDLE.sha256", identity + "\n")
        fsync_directory(temp)
        validate_bundle(temp)
        if os.path.lexists(output):
            fail("output appeared during render; refusing overwrite")
        os.rename(temp, output)
        fsync_directory(output.parent)
    except BaseException:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    print(
        json.dumps(
            {"status": "rendered", "ownership": ownership, "output_dir": str(output)},
            sort_keys=True,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec")
    parser.add_argument("--output-dir")
    parser.add_argument("--galileo-console-url")
    parser.add_argument("--validate-output")
    args = parser.parse_args()
    if args.validate_output:
        meta = validate_bundle(
            Path(os.path.abspath(Path(args.validate_output).expanduser()))
        )
        print(
            json.dumps(
                {"status": "valid", "ownership": meta["ownership"]}, sort_keys=True
            )
        )
        return 0
    if not all((args.spec, args.output_dir, args.galileo_console_url)):
        fail("--spec, --output-dir, and --galileo-console-url are required")
    render(
        secure_read(args.spec, "deployment spec"),
        Path(os.path.abspath(Path(args.output_dir).expanduser())),
        args.galileo_console_url,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

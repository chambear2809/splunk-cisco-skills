#!/usr/bin/env python3
"""Render or verify an immutable, non-secret Agent Control bundle."""

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

SCHEMA = "galileo-on-prem-agent-control-bundle/v1"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
DNS_LABEL = re.compile(r"^(?=.{1,63}$)[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
DNS_SUBDOMAIN = re.compile(
    r"^(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*$"
)
SECRET_KEY = re.compile(r"^[A-Za-z0-9._-]{1,253}$")
SECRET_SCALAR_KEYS = {
    "password",
    "passwd",
    "token",
    "api_key",
    "apikey",
    "secret_key",
    "client_secret",
    "private_key",
    "connection_string",
    "database_url",
}
FORBIDDEN_SECRET_SUBTREES = {
    "galileo_secrets",
    "secrets",
    "secret_values",
    "secretvalues",
}
SENSITIVE_KEY_RE = re.compile(
    r"(?:password|passwd|token|api_?key|secret|private_?key|credential|connection_?string)"
)
SENSITIVE_VALUE_RE = re.compile(
    r"(?i)(?:bearer\s+\S+|(?:password|passwd|token|api[_-]?key|secret|credential)\s*[:=]\s*\S+|-----BEGIN [A-Z ]*PRIVATE KEY-----|https?://[^/@\s:]+:[^/@\s]+@)"
)
SAFE_REFERENCE_KEYS = {
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
    path_text: str | Path,
    label: str,
    *,
    private: bool = False,
    max_bytes: int = 512 * 1024 * 1024,
) -> SecureInput:
    """Read once through an O_NOFOLLOW descriptor and bind validation to bytes."""
    raw = Path(path_text).expanduser()
    path = raw if raw.is_absolute() else Path.cwd() / raw
    path = Path(os.path.abspath(path))
    cursor = path.parent
    while True:
        try:
            ancestor = os.lstat(cursor)
        except OSError:
            fail(f"{label} has an unavailable ancestor")
        if stat.S_ISLNK(ancestor.st_mode) or not stat.S_ISDIR(ancestor.st_mode):
            fail(f"{label} has a symlink or non-directory ancestor")
        if cursor.parent == cursor:
            break
        cursor = cursor.parent
    try:
        before = os.lstat(path)
    except OSError:
        fail(f"{label} is unavailable")
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        fail(f"{label} must be a regular non-symlink file")
    if before.st_uid != os.getuid() or before.st_nlink != 1:
        fail(f"{label} must be current-user-owned with exactly one link")
    mode = stat.S_IMODE(before.st_mode)
    if (private and mode & 0o077) or (not private and mode & 0o022):
        fail(f"{label} has unsafe permissions")
    if before.st_size > max_bytes:
        fail(f"{label} exceeds the size limit")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        fail(f"{label} could not be opened safely")
    try:
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            fail(f"{label} changed during validation")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, max_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > max_bytes:
                fail(f"{label} exceeds the size limit")
        final = os.fstat(descriptor)
        if (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ) != (
            final.st_dev,
            final.st_ino,
            final.st_size,
            final.st_mtime_ns,
            final.st_ctime_ns,
        ):
            fail(f"{label} changed while being read")
    finally:
        os.close(descriptor)
    data = b"".join(chunks)
    return SecureInput(path=path, data=data, sha256=hashlib.sha256(data).hexdigest())


def mapping_from_input(artifact: SecureInput) -> dict:
    try:
        text = artifact.data.decode("utf-8")
    except UnicodeDecodeError:
        fail(f"input is not UTF-8: {artifact.path}")
    document = load_yaml_or_json(text, source=str(artifact.path))
    if not isinstance(document, dict):
        fail(f"expected a mapping in {artifact.path}")
    return document


def read_mapping(path: Path) -> dict:
    return mapping_from_input(secure_read(path, "bundle JSON"))


def only_keys(value: dict, allowed: set[str], where: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        fail(f"unknown {where} field(s): {', '.join(unknown)}")


def required_text(mapping: dict, key: str, where: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        fail(f"{where}.{key} must be a non-empty string")
    if value.startswith("CHANGE_ME") or "/CHANGE_ME" in value:
        fail(f"{where}.{key} is unresolved")
    return value.strip()


def bool_value(mapping: dict, key: str, where: str) -> bool:
    value = mapping.get(key)
    if not isinstance(value, bool):
        fail(f"{where}.{key} must be true or false")
    return value


def validate_url(raw: str) -> str:
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
            "Galileo console URL must be an HTTPS origin without credentials, path, query, or fragment"
        )
    try:
        port = parsed.port
    except ValueError:
        fail("Galileo console URL has an invalid port")
    host = parsed.hostname.lower()
    netloc = f"[{host}]" if ":" in host else host
    if port is not None:
        netloc += f":{port}"
    return urlunsplit(("https", netloc, "/", "", ""))


def validate_external_file(path_text: str, expected: str, label: str) -> SecureInput:
    artifact = secure_read(path_text, label)
    if not HEX64.fullmatch(expected) or artifact.sha256 != expected.lower():
        fail(f"{label} SHA-256 does not match the reviewed value")
    return artifact


def scan_nonsecret(node: object, location: str = "$") -> None:
    if isinstance(node, dict):
        if str(node.get("kind", "")).lower() == "secret":
            for secret_field in ("data", "stringData"):
                if node.get(secret_field) not in (None, "", {}, []):
                    fail(
                        f"non-secret values contain Kubernetes Secret.{secret_field} at {location}"
                    )
        for key, value in node.items():
            normalized = re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_")
            if normalized in FORBIDDEN_SECRET_SUBTREES and value not in (
                None,
                "",
                {},
                [],
            ):
                fail(
                    f"non-secret values contain forbidden secret subtree at {location}.{key}"
                )
            safe_reference = normalized in SAFE_REFERENCE_KEYS or normalized.endswith(
                ("_secret_name", "_secret_key_name", "secretname", "secretkeyname")
            )
            if (
                (
                    normalized in SECRET_SCALAR_KEYS
                    or (SENSITIVE_KEY_RE.search(normalized) and not safe_reference)
                )
                and not isinstance(value, (dict, list))
                and value not in {None, ""}
            ):
                fail(
                    f"non-secret values contain a secret-like scalar at {location}.{key}"
                )
            scan_nonsecret(value, f"{location}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            scan_nonsecret(value, f"{location}[{index}]")
    elif isinstance(node, str) and SENSITIVE_VALUE_RE.search(node):
        fail(f"non-secret values contain credential-shaped text at {location}")


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


def inspect_chart(artifact: SecureInput, expected_version: str) -> dict:
    total = 0
    chart_yaml: bytes | None = None
    template_names: list[str] = []
    hook_templates: list[str] = []
    pvc_templates: list[str] = []

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
                template_names.append(qualified)
                lowered = body.lower()
                if b"helm.sh/hook" in lowered:
                    hook_templates.append(qualified)
                if (
                    b"kind: persistentvolumeclaim" in lowered
                    or b"volumeclaimtemplates" in lowered
                    or b"finalizers:" in lowered
                ):
                    pvc_templates.append(qualified)

    try:
        archive_context = tarfile.open(fileobj=io.BytesIO(artifact.data), mode="r:*")
    except tarfile.TarError:
        fail("chart archive is malformed")
    with archive_context as archive:
        if archive.pax_headers:
            fail("chart archive contains global PAX overrides")
        members = archive.getmembers()
        if not members:
            fail("chart archive is empty")
        if len(members) > 10000:
            fail("chart archive contains too many members")
        seen: set[str] = set()
        roots: set[str] = set()
        chart_yaml_count = 0
        for member in members:
            raw_name = (
                member.name[:-1]
                if member.isdir() and member.name.endswith("/")
                else member.name
            )
            pure = PurePosixPath(raw_name)
            if (
                "\\" in raw_name
                or "//" in raw_name
                or raw_name.startswith("./")
                or pure.as_posix() != raw_name
                or pure.is_absolute()
                or ".." in pure.parts
                or "." in pure.parts
                or not pure.parts
                or len(member.name) > 1024
            ):
                fail("chart archive contains an unsafe path")
            canonical = pure.as_posix()
            if canonical in seen:
                fail("chart archive contains duplicate member names")
            seen.add(canonical)
            roots.add(pure.parts[0])
            if (
                not (member.isfile() or member.isdir())
                or member.pax_headers
                or member.issparse()
            ):
                fail("chart archive contains unsupported entry types or PAX overrides")
            if member.size > 64 * 1024 * 1024:
                fail("chart archive contains an oversized member")
            total += max(member.size, 0)
            if total > 256 * 1024 * 1024:
                fail("chart archive expands beyond 256 MiB")
            if member.isfile() and pure.name == "Chart.yaml" and len(pure.parts) == 2:
                chart_yaml_count += 1
                extracted = archive.extractfile(member)
                chart_yaml = extracted.read() if extracted else None
            if member.isfile() and "templates" in pure.parts:
                if member.size > 2 * 1024 * 1024:
                    fail("chart template exceeds the inspection bound")
                template_names.append(member.name)
                extracted = archive.extractfile(member)
                body = extracted.read(2 * 1024 * 1024) if extracted else b""
                lowered = body.lower()
                if b"helm.sh/hook" in lowered:
                    hook_templates.append(member.name)
                if (
                    b"kind: persistentvolumeclaim" in lowered
                    or b"volumeclaimtemplates" in lowered
                    or b"finalizers:" in lowered
                ):
                    pvc_templates.append(member.name)
            if (
                member.isfile()
                and pure.suffix.lower() in HELM_TEXT_SUFFIXES
                and "templates" not in pure.parts
            ):
                extracted = archive.extractfile(member)
                body = extracted.read(2 * 1024 * 1024 + 1) if extracted else b""
                if len(body) > 2 * 1024 * 1024:
                    fail("chart text member exceeds the inspection bound")
                reject_dynamic_helm(body, member.name)
            elif member.isfile() and "templates" in pure.parts:
                reject_dynamic_helm(body, member.name)
            if member.isfile() and pure.suffix == ".tgz" and "charts" in pure.parts:
                extracted = archive.extractfile(member)
                dependency_body = (
                    extracted.read(64 * 1024 * 1024 + 1) if extracted else b""
                )
                if len(dependency_body) > 64 * 1024 * 1024:
                    fail("chart dependency archive exceeds inspection bound")
                scan_dependency(dependency_body, member.name, 1)
    if roots != {"agent-control"} or chart_yaml is None or chart_yaml_count != 1:
        fail("chart archive must have exactly one root and one root Chart.yaml")
    metadata = load_yaml_or_json(
        chart_yaml.decode("utf-8"), source=f"{artifact.path}!Chart.yaml"
    )
    if (
        not isinstance(metadata, dict)
        or metadata.get("apiVersion") != "v2"
        or metadata.get("name") != "agent-control"
    ):
        fail("chart identity must be agent-control")
    if str(metadata.get("version", "")) != expected_version:
        fail("chart version does not match deployment spec")
    if (
        not isinstance(metadata.get("appVersion"), (str, int))
        or not str(metadata["appVersion"]).strip()
    ):
        fail("Agent Control Chart.yaml must declare appVersion")
    return {
        "name": "agent-control",
        "version": expected_version,
        "app_version": str(metadata.get("appVersion", "")),
        "template_files": sorted(template_names),
        "hook_templates": sorted(hook_templates),
        "pvc_templates": sorted(pvc_templates),
        "expanded_bytes": total,
    }


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    path.chmod(0o600)


def write_text(path: Path, value: str, executable: bool = False) -> None:
    path.write_text(value, encoding="utf-8")
    path.chmod(0o700 if executable else 0o600)


def fsync_directory(path: Path) -> None:
    descriptor = os.open(
        path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def bundle_payload_files(root: Path) -> list[Path]:
    paths: list[Path] = []
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        dirs.sort()
        files.sort()
        for name in files:
            path = Path(current) / name
            if name not in {"MANIFEST.sha256", "BUNDLE.sha256"}:
                paths.append(path)
    return sorted(paths, key=lambda item: item.relative_to(root).as_posix())


def manifest_payload(root: Path) -> bytes:
    lines: list[str] = []
    for path in bundle_payload_files(root):
        artifact = secure_read(path, "bundle payload")
        relative = path.relative_to(root).as_posix()
        mode = stat.S_IMODE(os.lstat(path).st_mode)
        lines.append(f"{artifact.sha256}  {mode:04o}  {relative}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def identity_payload(root: Path) -> bytes:
    """Hash payload with metadata's identity field normalized to avoid a cycle."""
    lines: list[str] = []
    for path in bundle_payload_files(root):
        artifact = secure_read(path, "bundle payload")
        relative = path.relative_to(root).as_posix()
        if relative == "metadata.json":
            try:
                metadata = json.loads(artifact.data)
            except json.JSONDecodeError:
                fail("bundle metadata is not valid JSON")
            metadata["bundle_sha256"] = "PENDING"
            payload = (json.dumps(metadata, indent=2, sort_keys=True) + "\n").encode()
            digest = hashlib.sha256(payload).hexdigest()
        else:
            digest = artifact.sha256
        mode = stat.S_IMODE(os.lstat(path).st_mode)
        lines.append(f"{digest}  {mode:04o}  {relative}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def canonical_overlay(contract: dict) -> dict:
    database = contract["database"]
    routing = contract["routing"]
    feature = contract["feature_flag"]
    value = {
        "galileo_config": {"agent_control_database_name": database["name"]},
        "galileo_services": {
            "agent_control": {
                "enabled": True,
                "bootstrap_database": database["bootstrap"],
            }
        },
    }
    if routing["mode"] != "none":
        value["galileo_config"]["agent_control_url"] = routing["external_url"]
    if routing["mode"] == "nginx":
        value["galileo_infra"] = {
            "ingress_nginx": {"agent_control_route": {"enabled": True}}
        }
    elif routing["mode"] == "gateway":
        value["galileo_infra"] = {
            "gateway_routes": {
                "enabled": True,
                "routes": {"agent-control": {"enabled": True}},
            }
        }
    if feature["source"] == "helm-env":
        value["galileo_config"].setdefault("additional_env_vars", {})[
            "GALILEO_FEATURE_FLAG_AGENT_CONTROL"
        ] = "enabled"
    return value


def canonical_coverage(contract: dict) -> dict:
    return {
        "schema": "galileo-on-prem-agent-control-coverage/v1",
        "features": [
            "service",
            "postgres-database",
            "bootstrap-job",
            "alembic-migrations",
            "api-auth",
            "hpa",
            "pdb",
            "network-policy",
            "ui-same-origin-proxy",
            "direct-route",
            "dns-tls",
            "feature-flag",
            "health-docs",
            "air-gap-images",
        ],
        "uncovered": [],
        "unowned": [],
        "duplicate_mutation_owners": [],
        "ownership": contract["deployment"]["ownership"],
    }


def canonical_lifecycle(contract: dict) -> dict:
    deployment = contract["deployment"]
    return {
        "schema": "galileo-on-prem-agent-control-lifecycle/v1",
        "owner": deployment["ownership"],
        "release": deployment["release_name"],
        "namespace": deployment["namespace"],
        "install_order": [
            "api",
            "authz",
            "agent-control",
            "direct-route-if-enabled",
            "ui",
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
        "secret_contract": contract["secret_contract"],
    }


def canonical_doctor(contract: dict) -> str:
    lines = [
        "# Agent Control doctor",
        "",
        "- Ownership is unique and hash-bound.",
        "- No secret values were copied into this bundle.",
        "- All apply modes are fail-closed Galileo/CSE joint-session handoffs; this skill performs no mutation.",
    ]
    if contract["deployment"]["ownership"] == "umbrella-overlay":
        lines.append(
            "- Direct Agent Control mutation is blocked; submit the overlay to the parent stack executor."
        )
    if contract["database"]["bootstrap"]:
        lines.append(
            "- Database bootstrap is enabled and must be separately reviewed before mutation."
        )
    return "\n".join(lines) + "\n"


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
        "secret_contract": contract["secret_contract"],
        "routing": contract["routing"],
        "feature_flag": contract["feature_flag"],
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
    if not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode):
        fail("bundle must be a directory, not a symlink")
    if root_info.st_uid != os.getuid() or stat.S_IMODE(root_info.st_mode) != 0o700:
        fail("bundle root must be current-user-owned mode 0700")
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        for name in dirs:
            path = Path(current) / name
            info = os.lstat(path)
            if (
                not stat.S_ISDIR(info.st_mode)
                or stat.S_ISLNK(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_nlink < 1
                or stat.S_IMODE(info.st_mode) != 0o700
            ):
                fail(
                    "bundle directories must be current-user-owned real directories mode 0700"
                )
        for name in files:
            path = Path(current) / name
            info = os.lstat(path)
            if (
                not stat.S_ISREG(info.st_mode)
                or stat.S_ISLNK(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_nlink != 1
            ):
                fail(
                    "bundle files must be current-user-owned regular files with one link"
                )
            if stat.S_IMODE(info.st_mode) not in {0o600, 0o700}:
                fail("bundle file mode must be 0600 or 0700")
    manifest = root / "MANIFEST.sha256"
    bundle_hash_file = root / "BUNDLE.sha256"
    manifest_artifact = secure_read(manifest, "bundle manifest")
    bundle_hash_artifact = secure_read(bundle_hash_file, "bundle digest")
    expected_manifest = manifest_payload(root)
    if manifest_artifact.data != expected_manifest:
        fail("bundle manifest or file content has drifted")
    actual_bundle = hashlib.sha256(identity_payload(root)).hexdigest()
    if (
        bundle_hash_artifact.data.decode("ascii", errors="strict").strip()
        != actual_bundle
    ):
        fail("bundle digest does not match its manifest")
    contract_artifact = secure_read(
        root / "normalized-spec.json", "normalized deployment spec"
    )
    contract = mapping_from_input(contract_artifact)
    if contract_artifact.data != canonical_json(contract):
        fail("normalized deployment spec is not canonical JSON")
    only_keys(
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
            "secret_contract",
            "routing",
            "feature_flag",
            "resilience",
            "approval",
        },
        "normalized deployment spec",
    )
    if contract.get("schema") != "galileo-on-prem-agent-control-normalized-spec/v1":
        fail("normalized deployment spec schema is unsupported")
    for name, keys in (
        (
            "deployment",
            {"id", "environment", "namespace", "release_name", "ownership", "timeout"},
        ),
        ("database", {"name", "bootstrap", "preprovisioned_and_granted"}),
        ("routing", {"mode", "external_url", "tls_secret_name", "ui_proxy_enabled"}),
        ("feature_flag", {"enabled", "source"}),
        ("resilience", {"hpa", "pdb", "network_policy"}),
        ("approval", {"cse_reference", "production_values_approved"}),
    ):
        value = contract.get(name)
        if not isinstance(value, dict):
            fail(f"normalized deployment spec {name} is not a mapping")
        only_keys(value, keys, f"normalized deployment spec {name}")
    deployment_contract = contract["deployment"]
    if (
        deployment_contract.get("environment")
        not in {"development", "staging", "production"}
        or deployment_contract.get("release_name") != "agent-control"
        or deployment_contract.get("ownership")
        not in {"standalone", "umbrella-overlay"}
        or not DNS_LABEL.fullmatch(str(deployment_contract.get("namespace", "")))
        or not re.fullmatch(
            r"[1-9][0-9]*[smh]", str(deployment_contract.get("timeout", ""))
        )
    ):
        fail("normalized deployment target is invalid")
    if validate_url(str(contract.get("galileo_console_url", ""))) != contract.get(
        "galileo_console_url"
    ):
        fail("normalized Galileo console URL is invalid")
    database_contract = contract["database"]
    if (
        not isinstance(database_contract.get("bootstrap"), bool)
        or not isinstance(database_contract.get("preprovisioned_and_granted"), bool)
        or database_contract["bootstrap"]
        == database_contract["preprovisioned_and_granted"]
        or (
            deployment_contract["environment"] == "production"
            and database_contract["bootstrap"]
        )
    ):
        fail("normalized database ownership policy is invalid")
    if any(
        not isinstance(contract[section].get(key), bool)
        for section, keys in (
            ("feature_flag", ("enabled",)),
            ("resilience", ("hpa", "pdb", "network_policy")),
            ("approval", ("production_values_approved",)),
        )
        for key in keys
    ):
        fail("normalized boolean policy is invalid")
    if contract["feature_flag"]["enabled"] is not True:
        fail("normalized Agent Control feature flag must be enabled")
    if deployment_contract["environment"] == "production" and (
        not all(contract["resilience"].values())
        or contract["approval"]["production_values_approved"] is not True
    ):
        fail("normalized production resilience/approval policy is invalid")
    metadata_artifact = secure_read(root / "metadata.json", "bundle metadata")
    metadata = mapping_from_input(metadata_artifact)
    if metadata_artifact.data != canonical_json(metadata):
        fail("bundle metadata is not canonical duplicate-free JSON")
    if (
        metadata.get("schema") != SCHEMA
        or metadata.get("bundle_sha256") != actual_bundle
    ):
        fail("metadata bundle contract is invalid")
    only_keys(
        metadata,
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
            "secret_contract",
            "routing",
            "feature_flag",
            "resilience",
            "cse_reference",
            "chart_has_delete_risk",
        },
        "bundle metadata",
    )
    if metadata != canonical_metadata(contract, actual_bundle):
        fail("bundle metadata differs from the normalized deployment spec")
    if (
        metadata.get("ownership") not in {"standalone", "umbrella-overlay"}
        or metadata.get("release_name") != "agent-control"
        or not DNS_LABEL.fullmatch(str(metadata.get("namespace", "")))
    ):
        fail("bundle target/ownership metadata is invalid")
    if validate_url(str(metadata.get("galileo_console_url", ""))) != metadata.get(
        "galileo_console_url"
    ):
        fail("bundle Galileo console URL is not canonical")
    if (
        not isinstance(metadata.get("parent_contract_sha256"), str)
        or not HEX64.fullmatch(metadata["parent_contract_sha256"])
        or not isinstance(metadata.get("base_values_sha256"), str)
        or not HEX64.fullmatch(metadata["base_values_sha256"])
    ):
        fail("bundle source hashes are invalid")
    parent_artifact = secure_read(
        root / "artifacts" / "parent-stack-contract.json", "parent stack contract"
    )
    parent_doc = mapping_from_input(parent_artifact)
    if parent_artifact.data != canonical_json(parent_doc):
        fail("parent stack contract is not canonical duplicate-free JSON")
    only_keys(
        parent_doc,
        {"schema", "release", "namespace", "bundle_sha256", "chart", "target"},
        "parent stack contract",
    )
    if (
        parent_artifact.sha256 != metadata["parent_contract_sha256"]
        or parent_doc.get("schema") != "galileo-on-prem-stack-release-contract/v1"
        or parent_doc.get("namespace") != metadata["namespace"]
    ):
        fail("bundle parent contract is invalid")
    expected_parent = {
        "release": parent_doc.get("release"),
        "bundle_sha256": parent_doc.get("bundle_sha256"),
        "chart": parent_doc.get("chart"),
        "target": parent_doc.get("target"),
    }
    if metadata.get("parent_stack") != expected_parent:
        fail("bundle parent identity is not exact")
    if contract.get("parent_stack") != expected_parent:
        fail("normalized parent identity differs from the bundled contract")
    base_artifact = secure_read(root / "values" / "base-values.yaml", "base values")
    if base_artifact.sha256 != metadata["base_values_sha256"]:
        fail("bundle base-values hash is invalid")
    if base_artifact.sha256 != contract.get("base_values_sha256"):
        fail("normalized spec base-values binding is invalid")
    scan_nonsecret(mapping_from_input(base_artifact))
    overlay_artifact = secure_read(
        root / "values" / "agent-control-overlay.yaml", "Agent Control overlay"
    )
    scan_nonsecret(mapping_from_input(overlay_artifact))
    if (
        overlay_artifact.data
        != dump_yaml(canonical_overlay(contract), sort_keys=True).encode()
    ):
        fail("Agent Control overlay differs from exact normalized semantics")
    if metadata["ownership"] == "standalone":
        chart_artifact = secure_read(
            root / "artifacts" / "agent-control.tgz", "Agent Control chart"
        )
        chart_meta = metadata.get("chart")
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
        expected_chart = inspect_chart(
            chart_artifact, str(chart_meta.get("version", ""))
        )
        expected_chart["sha256"] = chart_artifact.sha256
        if chart_meta != expected_chart:
            fail("bundle chart inspection has drifted")
        if contract.get("chart") != chart_meta:
            fail("normalized chart identity differs from the bundled chart")
        if contract.get("ownership_evidence_sha256") is not None:
            fail("standalone normalized spec unexpectedly binds umbrella ownership")
    else:
        if metadata.get("chart") is not None:
            fail("umbrella overlay must not carry standalone chart metadata")
        proof_artifact = secure_read(
            root / "artifacts" / "umbrella-ownership-evidence.json",
            "ownership evidence",
        )
        proof = mapping_from_input(proof_artifact)
        if proof_artifact.data != canonical_json(proof):
            fail("umbrella ownership evidence is not canonical duplicate-free JSON")
        only_keys(
            proof,
            {"schema", "component", "owner", "parent_bundle_sha256", "parent_chart"},
            "umbrella ownership evidence",
        )
        if proof != {
            "schema": "galileo-on-prem-umbrella-ownership-evidence/v1",
            "component": "agent-control",
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
    coverage = read_mapping(root / "coverage-report.json")
    lifecycle = read_mapping(root / "lifecycle.json")
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
    only_keys(
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
    only_keys(
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
            "secret_contract",
        },
        "lifecycle contract",
    )
    if (
        coverage.get("schema") != "galileo-on-prem-agent-control-coverage/v1"
        or coverage.get("ownership") != metadata["ownership"]
        or coverage.get("uncovered") != []
        or coverage.get("unowned") != []
        or coverage.get("duplicate_mutation_owners") != []
    ):
        fail("bundle coverage contract is invalid")
    if (
        lifecycle.get("schema") != "galileo-on-prem-agent-control-lifecycle/v1"
        or lifecycle.get("owner") != metadata["ownership"]
        or lifecycle.get("release") != "agent-control"
        or lifecycle.get("namespace") != metadata["namespace"]
        or lifecycle.get("secret_contract") != metadata.get("secret_contract")
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
        "values/agent-control-overlay.yaml",
        "artifacts/parent-stack-contract.json",
        "MANIFEST.sha256",
        "BUNDLE.sha256",
    }
    expected_files.add(
        "artifacts/agent-control.tgz"
        if metadata.get("ownership") == "standalone"
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
    return metadata


def render(spec_path: Path, output: Path, console_override: str) -> None:
    spec = mapping_from_input(secure_read(spec_path, "deployment spec"))
    only_keys(
        spec,
        {
            "api_version",
            "galileo",
            "deployment",
            "chart",
            "umbrella",
            "values",
            "database",
            "secrets",
            "routing",
            "feature_flag",
            "resilience",
            "approval",
        },
        "root",
    )
    if spec.get("api_version") != "galileo-on-prem-agent-control-setup/v1":
        fail("unsupported api_version")
    console = validate_url(console_override)
    galileo = spec.get("galileo")
    if not isinstance(galileo, dict):
        fail("galileo must be a mapping")
    only_keys(galileo, {"console_url"}, "galileo")
    if galileo.get("console_url"):
        if validate_url(str(galileo["console_url"])) != console:
            fail("CLI and spec Galileo console URLs differ")

    deployment = spec.get("deployment")
    if not isinstance(deployment, dict):
        fail("deployment must be a mapping")
    only_keys(
        deployment,
        {"id", "environment", "namespace", "release_name", "ownership", "timeout"},
        "deployment",
    )
    deployment_id = required_text(deployment, "id", "deployment")
    environment = required_text(deployment, "environment", "deployment")
    if environment not in {"development", "staging", "production"}:
        fail("deployment.environment is invalid")
    namespace = required_text(deployment, "namespace", "deployment")
    release = required_text(deployment, "release_name", "deployment")
    if not DNS_LABEL.fullmatch(namespace) or not DNS_LABEL.fullmatch(release):
        fail("namespace and release_name must be DNS-1123 labels")
    if release != "agent-control":
        fail("Agent Control release_name must be agent-control")
    ownership = required_text(deployment, "ownership", "deployment")
    if ownership not in {"standalone", "umbrella-overlay"}:
        fail("ownership must be standalone or umbrella-overlay")
    timeout = required_text(deployment, "timeout", "deployment")
    if not re.fullmatch(r"[1-9][0-9]*[smh]", timeout):
        fail("deployment.timeout must be a positive Helm duration")

    parent = spec.get("umbrella")
    if not isinstance(parent, dict):
        fail("umbrella must be a mapping")
    only_keys(
        parent,
        {
            "parent_contract_file",
            "parent_contract_sha256",
            "ownership_evidence_file",
            "ownership_evidence_sha256",
        },
        "umbrella",
    )
    parent_artifact = validate_external_file(
        required_text(parent, "parent_contract_file", "umbrella"),
        required_text(parent, "parent_contract_sha256", "umbrella"),
        "parent stack contract",
    )
    parent_doc = mapping_from_input(parent_artifact)
    if parent_artifact.data != canonical_json(parent_doc):
        fail("parent stack contract must be canonical duplicate-free JSON")
    if parent_doc.get("schema") != "galileo-on-prem-stack-release-contract/v1":
        fail("parent stack contract schema is unsupported")
    only_keys(
        parent_doc,
        {"schema", "release", "namespace", "bundle_sha256", "chart", "target"},
        "parent stack contract",
    )
    if parent_doc.get("namespace") != namespace:
        fail("parent stack contract targets a different namespace")
    if (
        not isinstance(parent_doc.get("release"), str)
        or not parent_doc["release"].strip()
    ):
        fail("parent stack contract is missing its release")
    if not isinstance(parent_doc.get("bundle_sha256"), str) or not HEX64.fullmatch(
        parent_doc["bundle_sha256"]
    ):
        fail("parent stack contract is missing a valid bundle digest")
    parent_chart = parent_doc.get("chart")
    if (
        not isinstance(parent_chart, dict)
        or set(parent_chart) != {"name", "version", "sha256"}
        or parent_chart.get("name") != "galileo-stack"
        or not isinstance(parent_chart.get("version"), str)
        or not parent_chart["version"].strip()
        or not isinstance(parent_chart.get("sha256"), str)
        or not HEX64.fullmatch(parent_chart["sha256"])
    ):
        fail(
            "parent stack contract must bind the exact galileo-stack chart/version/digest"
        )
    parent_target = parent_doc.get("target")
    required_target = {
        "context",
        "api_server",
        "ca_sha256",
        "kube_system_uid",
        "namespace_uid",
    }
    if not isinstance(parent_target, dict) or set(parent_target) != required_target:
        fail("parent stack contract target identity is incomplete")
    if any(
        not isinstance(parent_target[key], str) or not parent_target[key].strip()
        for key in required_target
    ):
        fail("parent stack contract target identity values must be non-empty strings")
    if not str(parent_target["api_server"]).startswith(
        "https://"
    ) or not HEX64.fullmatch(str(parent_target["ca_sha256"])):
        fail("parent stack target endpoint or CA digest is invalid")

    chart_info: dict | None = None
    chart_artifact: SecureInput | None = None
    ownership_artifact: SecureInput | None = None
    chart = spec.get("chart")
    if not isinstance(chart, dict):
        fail("chart must be a mapping")
    only_keys(chart, {"archive", "sha256", "version"}, "chart")
    if ownership == "standalone":
        if any(
            str(parent.get(k, "")).strip()
            for k in ("ownership_evidence_file", "ownership_evidence_sha256")
        ):
            fail("standalone mode rejects umbrella ownership evidence")
        chart_artifact = validate_external_file(
            required_text(chart, "archive", "chart"),
            required_text(chart, "sha256", "chart"),
            "Agent Control chart",
        )
        chart_info = inspect_chart(
            chart_artifact, required_text(chart, "version", "chart")
        )
        chart_info["sha256"] = chart_artifact.sha256
    else:
        if any(str(chart.get(k, "")).strip() for k in ("archive", "sha256", "version")):
            fail("umbrella-overlay mode rejects a standalone chart")
        ownership_artifact = validate_external_file(
            required_text(parent, "ownership_evidence_file", "umbrella"),
            required_text(parent, "ownership_evidence_sha256", "umbrella"),
            "umbrella ownership evidence",
        )
        ownership_doc = mapping_from_input(ownership_artifact)
        if ownership_artifact.data != canonical_json(ownership_doc):
            fail("ownership evidence must be canonical duplicate-free JSON")
        only_keys(
            ownership_doc,
            {"schema", "component", "owner", "parent_bundle_sha256", "parent_chart"},
            "umbrella ownership evidence",
        )
        if (
            ownership_doc.get("schema")
            != "galileo-on-prem-umbrella-ownership-evidence/v1"
            or ownership_doc.get("component") != "agent-control"
            or ownership_doc.get("owner") != "galileo-stack"
            or ownership_doc.get("parent_bundle_sha256") != parent_doc["bundle_sha256"]
            or ownership_doc.get("parent_chart") != parent_chart
        ):
            fail("ownership evidence does not bind agent-control to galileo-stack")

    values = spec.get("values")
    if not isinstance(values, dict):
        fail("values must be a mapping")
    only_keys(values, {"base_file", "base_sha256"}, "values")
    base_artifact = validate_external_file(
        required_text(values, "base_file", "values"),
        required_text(values, "base_sha256", "values"),
        "non-secret base values",
    )
    base_doc = mapping_from_input(base_artifact)
    scan_nonsecret(base_doc)

    database = spec.get("database")
    secrets = spec.get("secrets")
    routing = spec.get("routing")
    feature = spec.get("feature_flag")
    resilience = spec.get("resilience")
    approval = spec.get("approval")
    for name, value in (
        ("database", database),
        ("secrets", secrets),
        ("routing", routing),
        ("feature_flag", feature),
        ("resilience", resilience),
        ("approval", approval),
    ):
        if not isinstance(value, dict):
            fail(f"{name} must be a mapping")
    only_keys(database, {"name", "bootstrap", "preprovisioned_and_granted"}, "database")
    db_name = required_text(database, "name", "database")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", db_name):
        fail("database.name must be a PostgreSQL identifier")
    bootstrap = bool_value(database, "bootstrap", "database")
    precreated = bool_value(database, "preprovisioned_and_granted", "database")
    if bootstrap == precreated:
        fail("choose exactly one database ownership path")
    if environment == "production" and bootstrap:
        fail(
            "production database bootstrap requires a separate reviewed exception; pre-provision the database"
        )
    only_keys(secrets, {"postgres", "api", "runtime_auth_enabled"}, "secrets")
    postgres = secrets.get("postgres")
    api = secrets.get("api")
    if not isinstance(postgres, dict) or not isinstance(api, dict):
        fail("postgres and api Secret references must be mappings")
    only_keys(postgres, {"name", "user_key", "password_key"}, "secrets.postgres")
    only_keys(api, {"name", "key"}, "secrets.api")
    runtime_auth = bool_value(secrets, "runtime_auth_enabled", "secrets")
    secret_contract = {
        "postgres": {
            k: required_text(postgres, k, "secrets.postgres")
            for k in ("name", "user_key", "password_key")
        },
        "api": {k: required_text(api, k, "secrets.api") for k in ("name", "key")},
        "runtime_auth_enabled": runtime_auth,
    }
    for name in (secret_contract["postgres"]["name"], secret_contract["api"]["name"]):
        if not DNS_SUBDOMAIN.fullmatch(name):
            fail("Secret names must be DNS subdomains")
    for key in (
        secret_contract["postgres"]["user_key"],
        secret_contract["postgres"]["password_key"],
        secret_contract["api"]["key"],
    ):
        if not SECRET_KEY.fullmatch(key):
            fail("Secret data keys are invalid")
    only_keys(
        routing,
        {"mode", "external_url", "tls_secret_name", "ui_proxy_enabled"},
        "routing",
    )
    route_mode = required_text(routing, "mode", "routing")
    if route_mode not in {"none", "nginx", "gateway", "customer"}:
        fail("routing.mode is invalid")
    ui_proxy = bool_value(routing, "ui_proxy_enabled", "routing")
    if not ui_proxy:
        fail("the Controls UI same-origin proxy must remain enabled")
    external_url = str(routing.get("external_url", "")).strip()
    tls_name = str(routing.get("tls_secret_name", "")).strip()
    if route_mode == "none" and (external_url or tls_name):
        fail("routing.none rejects external route settings")
    if route_mode != "none":
        external_url = validate_url(required_text(routing, "external_url", "routing"))
        route_host = urlsplit(external_url).hostname
        if not isinstance(route_host, str) or not DNS_SUBDOMAIN.fullmatch(route_host):
            fail(
                "routing.external_url must use one exact DNS hostname without wildcards"
            )
        tls_name = required_text(routing, "tls_secret_name", "routing")
        if not DNS_SUBDOMAIN.fullmatch(tls_name):
            fail("routing.tls_secret_name is invalid")
    only_keys(feature, {"enabled", "source"}, "feature_flag")
    if not bool_value(feature, "enabled", "feature_flag"):
        fail("Agent Control deployment requires the feature flag enabled")
    feature_source = required_text(feature, "source", "feature_flag")
    if feature_source not in {"central", "helm-env"}:
        fail("feature_flag.source is invalid")
    only_keys(resilience, {"hpa", "pdb", "network_policy"}, "resilience")
    for key in ("hpa", "pdb", "network_policy"):
        if environment == "production" and not bool_value(
            resilience, key, "resilience"
        ):
            fail(f"production requires resilience.{key}=true")
    only_keys(approval, {"cse_reference", "production_values_approved"}, "approval")
    cse_reference = required_text(approval, "cse_reference", "approval")
    if environment == "production" and not bool_value(
        approval, "production_values_approved", "approval"
    ):
        fail("production values require Galileo approval")

    contract = {
        "schema": "galileo-on-prem-agent-control-normalized-spec/v1",
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
            "name": db_name,
            "bootstrap": bootstrap,
            "preprovisioned_and_granted": precreated,
        },
        "secret_contract": secret_contract,
        "routing": {
            "mode": route_mode,
            "external_url": external_url,
            "tls_secret_name": tls_name,
            "ui_proxy_enabled": ui_proxy,
        },
        "feature_flag": {"enabled": True, "source": feature_source},
        "resilience": {
            key: bool_value(resilience, key, "resilience")
            for key in ("hpa", "pdb", "network_policy")
        },
        "approval": {
            "cse_reference": cse_reference,
            "production_values_approved": bool_value(
                approval, "production_values_approved", "approval"
            ),
        },
    }
    overlay = canonical_overlay(contract)

    if output in {
        Path("/"),
        Path.home(),
        REPO_ROOT,
        Path.cwd(),
        Path(tempfile.gettempdir()),
    }:
        fail("broad output roots are forbidden")
    if os.path.lexists(output):
        fail("output directory already exists; immutable bundles are never overwritten")
    if not output.parent.is_dir():
        fail("output parent must already exist")
    parent_info = os.lstat(output.parent)
    if parent_info.st_uid != os.getuid() or stat.S_IMODE(parent_info.st_mode) & 0o022:
        fail("output parent must be current-user-owned and not group/world writable")
    cursor = output.parent
    while True:
        info = os.lstat(cursor)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            fail("output path has a symlink or non-directory ancestor")
        if cursor.parent == cursor:
            break
        cursor = cursor.parent
    temp = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    try:
        temp.chmod(0o700)
        (temp / "values").mkdir(mode=0o700)
        (temp / "artifacts").mkdir(mode=0o700)
        write_json(temp / "normalized-spec.json", contract)
        (temp / "values" / "base-values.yaml").write_bytes(base_artifact.data)
        (temp / "values" / "base-values.yaml").chmod(0o600)
        write_text(
            temp / "values" / "agent-control-overlay.yaml",
            dump_yaml(overlay, sort_keys=True),
        )
        (temp / "artifacts" / "parent-stack-contract.json").write_bytes(
            parent_artifact.data
        )
        (temp / "artifacts" / "parent-stack-contract.json").chmod(0o600)
        if chart_artifact:
            (temp / "artifacts" / "agent-control.tgz").write_bytes(chart_artifact.data)
            (temp / "artifacts" / "agent-control.tgz").chmod(0o600)
        if ownership_artifact:
            (temp / "artifacts" / "umbrella-ownership-evidence.json").write_bytes(
                ownership_artifact.data
            )
            (temp / "artifacts" / "umbrella-ownership-evidence.json").chmod(0o600)
        write_json(temp / "coverage-report.json", canonical_coverage(contract))
        write_json(temp / "lifecycle.json", canonical_lifecycle(contract))
        write_text(temp / "doctor-report.md", canonical_doctor(contract))
        metadata = canonical_metadata(contract, "PENDING")
        write_json(temp / "metadata.json", metadata)
        metadata_path = temp / "metadata.json"
        bundle_hash = hashlib.sha256(identity_payload(temp)).hexdigest()
        metadata["bundle_sha256"] = bundle_hash
        write_json(metadata_path, metadata)
        final_manifest = manifest_payload(temp)
        write_text(temp / "MANIFEST.sha256", final_manifest.decode("utf-8"))
        write_text(temp / "BUNDLE.sha256", bundle_hash + "\n")
        fsync_directory(temp)
        validate_bundle(temp)
        if os.path.lexists(output):
            fail("output appeared during render; existing data was not changed")
        os.rename(temp, output)
        fsync_directory(output.parent)
    except BaseException:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    print(
        json.dumps(
            {"status": "rendered", "output_dir": str(output), "ownership": ownership},
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
        metadata = validate_bundle(
            Path(os.path.abspath(Path(args.validate_output).expanduser()))
        )
        print(
            json.dumps(
                {"status": "valid", "ownership": metadata["ownership"]}, sort_keys=True
            )
        )
        return 0
    if not all((args.spec, args.output_dir, args.galileo_console_url)):
        fail("--spec, --output-dir, and --galileo-console-url are required")
    render(
        Path(os.path.abspath(Path(args.spec).expanduser())),
        Path(os.path.abspath(Path(args.output_dir).expanduser())),
        args.galileo_console_url,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

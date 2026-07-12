#!/usr/bin/env python3
"""Render Splunk Observability OTel Collector deployment assets."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import shlex
import shutil
import stat
import sys
import tarfile
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qsl, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared" / "lib"))
from yaml_compat import YamlCompatError, load_yaml_or_json  # noqa: E402


TA_APP_ID = "7125"
COLLECTOR_AUDITED_VERSION = "0.154.2"
CHART_AUDITED_VERSION = "0.154.0"
CHART_NAME = "splunk-otel-collector"
CHART_ARCHIVE_NAME = f"{CHART_NAME}-{CHART_AUDITED_VERSION}.tgz"
CHART_ARCHIVE_URL = (
    "https://github.com/signalfx/splunk-otel-collector-chart/releases/download/"
    f"splunk-otel-collector-{CHART_AUDITED_VERSION}/{CHART_ARCHIVE_NAME}"
)
CHART_ARCHIVE_SHA256 = "613f788d786bf741be770512c7c297c4b70d3ab5426ac337b0416209e66bc7b0"
COLLECTOR_STANDARD_SOURCE_IMAGE = "quay.io/signalfx/splunk-otel-collector:0.154.0"
COLLECTOR_STANDARD_IMAGE = (
    "quay.io/signalfx/splunk-otel-collector@"
    "sha256:b37160d858a5ad3344301424fba8cdb4d7cc12430383616e0ebc5fb39ad33410"
)
COLLECTOR_FIPS_SOURCE_IMAGE = "quay.io/signalfx/splunk-otel-collector-fips:0.154.0"
COLLECTOR_FIPS_IMAGE = (
    "quay.io/signalfx/splunk-otel-collector-fips@"
    "sha256:b11a6e592248a2281cf95a765d30660a9951f04b0935f91d9ae93db5839b3b52"
)
COLLECTOR_WINDOWS_SOURCE_IMAGE = "quay.io/signalfx/splunk-otel-collector-windows:0.154.0"
COLLECTOR_WINDOWS_IMAGE = (
    "quay.io/signalfx/splunk-otel-collector-windows@"
    "sha256:aedfa35fcbff3dcf92bbcc195e9631ed2648d83e836ee2f9f0a2536d3a1a1e9a"
)
FARGATE_NODE_DISCOVERER_SOURCE_IMAGE = "public.ecr.aws/amazonlinux/amazonlinux:latest"
FARGATE_NODE_DISCOVERER_RELEASE_TAG = "2023.12.20260629.0"
FARGATE_NODE_DISCOVERER_INDEX_DIGEST = (
    "sha256:336b735f8f0aa1d591802beb01d2ef85c6a4a3f411ea4ffa35cad8ba5db282af"
)
FARGATE_NODE_DISCOVERER_IMAGE = (
    "public.ecr.aws/amazonlinux/amazonlinux:"
    f"{FARGATE_NODE_DISCOVERER_RELEASE_TAG}@{FARGATE_NODE_DISCOVERER_INDEX_DIGEST}"
)
FARGATE_NODE_DISCOVERER_PLATFORM_DIGESTS = {
    "linux/amd64": "sha256:9874a0629e48491e1da97b2966202f83cd3a7915002bffa42a0bdf88417c755d",
    "linux/arm64/v8": "sha256:eda490c9c952ae0cf099a44e749d43e3ea50e89481fa4ab4f99fc297a2c50aa2",
}
FARGATE_NODE_DISCOVERER_AUDITED_AT = "2026-07-02T08:28:42Z"
K8S_AUXILIARY_IMAGE_PINS = {
    "registry.access.redhat.com/ubi9/ubi": (
        "registry.access.redhat.com/ubi9/ubi@"
        "sha256:8bf0e8f20737e9c8a68c8a498299e9504ab397b1b1f2837acb2fef12ec698f0e"
    ),
    "busybox:latest": (
        "busybox@sha256:fd8d9aa63ba2f0982b5304e1ee8d3b90a210bc1ffb5314d980eb6962f1a9715d"
    ),
    "ghcr.io/open-telemetry/opentelemetry-operator/opentelemetry-operator:0.153.0": (
        "ghcr.io/open-telemetry/opentelemetry-operator/opentelemetry-operator@"
        "sha256:71c80734e698e0a38039aeb5a6fad7129ca68eaa31eb262752c1e5015b319a24"
    ),
    "registry.k8s.io/kubectl:v1.35.1": (
        "registry.k8s.io/kubectl@"
        "sha256:c93e4fb811b3217ef69ee7a79a9a15fb277887cd1c3002fbe154e676037a274a"
    ),
    "ghcr.io/open-telemetry/opentelemetry-go-instrumentation/autoinstrumentation-go:v0.24.0": (
        "ghcr.io/open-telemetry/opentelemetry-go-instrumentation/autoinstrumentation-go@"
        "sha256:664715c04cb854ffdbb920ea1289a86b0717f39e46b18e6584caa9e1f2e4d83f"
    ),
    "ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-apache-httpd:1.0.4": (
        "ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-apache-httpd@"
        "sha256:c519018eb569926a44d5e078f1dcc301aa6cf8c6f35afe809b67f4eb37d0458d"
    ),
    "ghcr.io/signalfx/splunk-otel-dotnet/splunk-otel-dotnet:v1.14.0": (
        "ghcr.io/signalfx/splunk-otel-dotnet/splunk-otel-dotnet@"
        "sha256:dea496508f6d94d417bc3f26d0bd0a4dd3a16049b6a2a5753c2a21a8035be910"
    ),
    "ghcr.io/signalfx/splunk-otel-java/splunk-otel-java:v2.28.0": (
        "ghcr.io/signalfx/splunk-otel-java/splunk-otel-java@"
        "sha256:8c3092572c4a433cb4fc258655880215d4c3dd0bf090d31fa0343a865180bfa9"
    ),
    "ghcr.io/signalfx/splunk-otel-java/splunk-otel-java-csa:v2.28.0": (
        "ghcr.io/signalfx/splunk-otel-java/splunk-otel-java-csa@"
        "sha256:6c2c1d95c3753a4bcd9ea51c27498a242ea3de9a72345bb64d7c836fcf1c2abb"
    ),
    "ghcr.io/signalfx/splunk-otel-js/splunk-otel-js:v4.8.0": (
        "ghcr.io/signalfx/splunk-otel-js/splunk-otel-js@"
        "sha256:97f0536ba942e110e3e8a493d265e11c26064c502614ad0b67069f429431484a"
    ),
    "quay.io/signalfx/splunk-otel-instrumentation-python:v2.7.0": (
        "quay.io/signalfx/splunk-otel-instrumentation-python@"
        "sha256:d488c507e0cacc64b81423b96f6e53b30f2602a0e4bcc614658182f6aa13d5b4"
    ),
    "quay.io/signalfx/splunk-otel-instrumentation-python:v2.11.0-secureapp": (
        "quay.io/signalfx/splunk-otel-instrumentation-python@"
        "sha256:f47a8f0f7362da98f0e0ac0f5ac83492555b495c6c37c411680bb055bd1f2dbe"
    ),
    "ghcr.io/open-telemetry/opentelemetry-ebpf-instrumentation/ebpf-instrument:v0.9.0": (
        "ghcr.io/open-telemetry/opentelemetry-ebpf-instrumentation/ebpf-instrument@"
        "sha256:26f82b148dfe8cb0530561ab72a3cb5490b3ae5df556a33c27984af2e28542cf"
    ),
    "ghcr.io/open-telemetry/opentelemetry-operator/target-allocator:0.152.0": (
        "ghcr.io/open-telemetry/opentelemetry-operator/target-allocator@"
        "sha256:85a08d334a480c33aff1f0e9d9e432202c1e0bf23f58f8bd11aececa5506a4c6"
    ),
}
INSTRUMENTATION_KUBECTL_IMAGE_TAG = "v1.35.1"
INSTRUMENTATION_AUDITED_VERSION = "0.154.2"
OBI_AUDITED_VERSION = "v0.6.0"
OBI_ARCHIVE_SHA256 = {
    "amd64": "da5f3501a4ae1de67930fa8dca2c822138417796c40266193af0d36effa20b95",
    "arm64": "4b31902024f3e98dd93f3a28efd45a07c189f1943bb36d75a2c34dc1e0aff249",
}
OBI_BINARY_SHA256 = {
    "amd64": "3667f3a040b9125eeac88c8a8f2fab67e45f48ade259461d30a09dc9f4ea839e",
    "arm64": "72903f7dda88d9ad70263d7c749064ede26aaa8040490807c518c62dc581aa6b",
}
LINUX_INSTALLER_URL = (
    "https://raw.githubusercontent.com/signalfx/splunk-otel-collector/"
    f"v{COLLECTOR_AUDITED_VERSION}/packaging/installer/install.sh"
)
LINUX_INSTALLER_SHA256 = "16f2c34ad1a91bf0817f5675eca3d705af5385377e87fda23537808efd5f7e29"
TA_LATEST_VERSION = "0.154.2"
TA_PUBLISHED_DATE = "2026-06-17"
TA_SPLUNK_MIN_VERSION = "9.0"
TA_SPLUNK_MAX_VERSION = "10.4"
TA_SUPPORTED_ROOTS = (
    "Splunk_TA_otel",
    "Splunk_TA_otel_linux_x86_64",
    "Splunk_TA_otel_windows_x86_64",
)
TA_REQUIRED_FILES = (
    "default/app.conf",
    "default/inputs.conf",
    "README/inputs.conf.spec",
    "configs/agent_config.yaml",
    "configs/gateway_config.yaml",
)
TA_PLATFORM_BINARIES = {
    "linux-x86-64": "linux_x86_64/bin/Splunk_TA_otel",
    "windows-x86-64": "windows_x86_64/bin/Splunk_TA_otel.exe",
}
SECRET_KEY_PATTERN = re.compile(
    r"(token|secret|password|api[_-]?key|access[_-]?key|authorization|credential|private[_-]?key|headers?|cookie)",
    re.IGNORECASE,
)
SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(splunk_access_token|splunk_hec_token|access_token\s*=|token\s*=|password\s*=|secret\s*=|api[_-]?key\s*=|access[_-]?key\s*=|authorization\s*[:=]|bearer\s+)",
    re.IGNORECASE,
)
SECRET_FLAG_PATTERN = re.compile(
    r"^--?(splunk[-_])?(access[-_]?token|token|password|secret|api[-_]?key|access[-_]?key|authorization|headers?|cookie)(=|$)",
    re.IGNORECASE,
)
TA_SPLUNKBASE_METADATA = {
    "splunkbase_app_id": TA_APP_ID,
    "name": "Splunk Add-On for OpenTelemetry Collector",
    "latest_version": TA_LATEST_VERSION,
    "published_date": TA_PUBLISHED_DATE,
    "compatible_splunk_versions": {
        "min": TA_SPLUNK_MIN_VERSION,
        "max": TA_SPLUNK_MAX_VERSION,
        "listed": [
            "10.4",
            "10.3",
            "10.2",
            "10.1",
            "10.0",
            "9.4",
            "9.3",
            "9.2",
            "9.1",
            "9.0",
        ],
    },
    "splunk_enterprise_compatible": True,
    "splunk_cloud_compatible": True,
    "fips_compatible": False,
    "fedramp_status": "not_documented",
    "sources": {
        "splunkbase": "https://splunkbase.splunk.com/app/7125",
        "docs_install": "https://help.splunk.com/en/splunk-observability-cloud/manage-data/splunk-distribution-of-the-opentelemetry-collector/get-started-with-the-splunk-distribution-of-the-opentelemetry-collector/splunk-add-on-for-opentelemetry-collector/install-the-technical-add-on",
        "upstream": "https://github.com/signalfx/splunk-otel-collector/tree/v0.154.2/packaging/ta-v2",
    },
    "filename": "splunk-add-on-for-opentelemetry-collector_01542.tgz",
    "sha256": "928e66efb5591c3e9c07e2eae2008b605aa7cf10ae9cc48acff88f417811a7da",
    "signed_available": False,
}
TA_ARTIFACTS = {
    "Splunk_TA_otel": {
        "splunkbase_app_id": "7125",
        "filename": "splunk-add-on-for-opentelemetry-collector_01542.tgz",
        "sha256": "928e66efb5591c3e9c07e2eae2008b605aa7cf10ae9cc48acff88f417811a7da",
        "cloud_compatible": True,
        "source": "https://splunkbase.splunk.com/app/7125",
    },
    "Splunk_TA_otel_linux_x86_64": {
        "splunkbase_app_id": "8698",
        "filename": "splunk-add-on-for-opentelemetry-collector-for-linux-x86_64_01542.tgz",
        "sha256": "efd048ae1c30fa81adbe05f9e3de0dced90cfe8a89dc750b116ca812bb3471de",
        "cloud_compatible": False,
        "source": "https://splunkbase.splunk.com/app/8698",
    },
    "Splunk_TA_otel_windows_x86_64": {
        "splunkbase_app_id": "8699",
        "filename": "splunk-add-on-for-opentelemetry-collector-for-windows-x86_64_01542.tgz",
        "sha256": "c66825ef1020c53237767d643953a8e6033c51cda92aad875a54fefcf51aea63",
        "cloud_compatible": False,
        "source": "https://splunkbase.splunk.com/app/8699",
    },
}


def str_bool(value: str) -> bool:
    return value == "true"


def yaml_scalar(value: str | int | bool) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return json.dumps(value)


def shell_quote(value: str) -> str:
    return shlex.quote(value)


def shell_env_default(name: str, value: str) -> str:
    """Render a Bash assignment without placing an untrusted default in ${...}."""

    return (
        f'{name}="${{{name}:-}}"\n'
        f'if [[ -z "${{{name}}}" ]]; then\n'
        f"    {name}={shell_quote(value)}\n"
        "fi"
    )


def shell_env_alias_default(name: str, env_name: str, value: str) -> str:
    """Render an assignment supporting a documented environment alias safely."""

    return (
        name + '="${' + env_name + ':-${' + name + ':-}}"\n'
        f'if [[ -z "${{{name}}}" ]]; then\n'
        f"    {name}={shell_quote(value)}\n"
        "fi"
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_single_line(value: str, label: str) -> None:
    if "\n" in value or "\r" in value or "\x00" in value:
        raise ValueError(f"{label} must be a single-line value")


def exact_semver(value: str) -> bool:
    """Return true only for one exact SemVer, never a range or moving tag."""

    return bool(
        re.fullmatch(
            r"(?:0|[1-9][0-9]*)\."
            r"(?:0|[1-9][0-9]*)\."
            r"(?:0|[1-9][0-9]*)"
            r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
            r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?",
            value,
        )
    )


def exact_numeric_release(value: str) -> bool:
    return bool(re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", value))


def normalized_absolute_linux_path(value: str) -> bool:
    """Validate a shell-safe, normalized absolute Linux filesystem path."""

    if not value.startswith("/") or value == "/":
        return False
    if not re.fullmatch(r"/[A-Za-z0-9._/-]+", value):
        return False
    if any(part in ("", ".", "..") for part in value.split("/")[1:]):
        return False
    return str(PurePosixPath(value)) == value


def valid_linux_account_name(value: str) -> bool:
    """Accept the conservative useradd-compatible service-account subset."""

    return bool(re.fullmatch(r"(?=.{1,32}\Z)[a-z_][a-z0-9_-]*\$?", value))


def valid_splunk_index(value: str) -> bool:
    return bool(re.fullmatch(r"[_A-Za-z0-9][A-Za-z0-9_.-]*", value))


def read_bounded_nofollow_text(
    path: Path,
    *,
    label: str,
    maximum_bytes: int,
) -> str:
    """Read one stable, single-link UTF-8 file snapshot without following links."""

    if not hasattr(os, "O_NOFOLLOW"):
        raise SystemExit(f"{label} requires O_NOFOLLOW support")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise SystemExit(
            f"{label} must be a readable non-symlink regular file: {path}"
        ) from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise SystemExit(f"{label} must be a single-link regular file: {path}")
        if before.st_size < 1 or before.st_size > maximum_bytes:
            raise SystemExit(
                f"{label} size must be between 1 byte and {maximum_bytes} bytes: {path}"
            )
        chunks: list[bytes] = []
        remaining = maximum_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        def fingerprint(info: os.stat_result) -> tuple[int, int, int, int, int, int]:
            return (
                info.st_dev,
                info.st_ino,
                info.st_size,
                info.st_mtime_ns,
                info.st_ctime_ns,
                info.st_nlink,
            )
        if fingerprint(before) != fingerprint(after):
            raise SystemExit(f"{label} changed while it was read: {path}")
        data = b"".join(chunks)
        if len(data) != before.st_size or len(data) > maximum_bytes:
            raise SystemExit(f"{label} changed or exceeded its size bound: {path}")
    finally:
        os.close(descriptor)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SystemExit(f"{label} must be UTF-8 text: {path}") from exc


def validate_extra_values(path: Path) -> None:
    """Reject overlays that bypass the file-backed secret contract."""

    text = read_bounded_nofollow_text(
        path,
        label="--extra-values-file",
        maximum_bytes=32 * 1024 * 1024,
    )
    # The repository YAML compatibility layer deliberately supports only a
    # conservative block-style subset when PyYAML is unavailable.  Flow-style
    # mappings would otherwise be treated as scalar strings by that fallback,
    # so reject sensitive flow keys before parsing.  This keeps the secret
    # contract fail-closed on minimal Python installations too.
    sensitive_flow_key = re.compile(
        r"(?i)(?:^|[,{]\s*)[\"']?"
        r"(?:[a-z0-9_.-]*token|authorization|client[-_]?key|client[-_]?secret|password|secret|api[-_]?key)"
        r"[\"']?\s*:"
    )
    try:
        json.loads(text)
        is_json = True
    except json.JSONDecodeError:
        is_json = False
    if not is_json:
        for raw_line in text.splitlines():
            if raw_line.lstrip().startswith("#"):
                continue
            code = raw_line.split(" #", 1)[0]
            if "{" in code and sensitive_flow_key.search(code):
                raise SystemExit(
                    f"--extra-values-file uses a flow-style sensitive mapping that cannot be audited safely: {path}. "
                    "Use block YAML plus this skill's file-backed secret options instead."
                )
    try:
        payload = load_yaml_or_json(text, source=str(path))
    except YamlCompatError as exc:
        raise SystemExit(f"--extra-values-file is not valid YAML/JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"--extra-values-file must contain a YAML mapping: {path}")

    secret_block = payload.get("secret", {})
    if not isinstance(secret_block, dict):
        raise SystemExit(f"--extra-values-file secret must be a mapping: {path}")
    if secret_block.get("create") is True:
        raise SystemExit(
            f"--extra-values-file attempts to enable secret.create: {path}. "
            "Externally-created file-backed secrets are required."
        )

    sensitive_keys = {
        "accesstoken",
        "token",
        "clientkey",
        "clientsecret",
        "password",
        "secret",
        "apikey",
    }
    safe_env_reference = re.compile(
        r"^\$\{env:(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?::-)?\}$"
    )
    generic_assignment = re.compile(
        r"(?i)(?:^|[;,\s])(?:--?)?"
        r"(?P<key>[A-Za-z_][A-Za-z0-9_.-]*)\s*[:=]\s*"
        r"(?P<value>[^;,\s]+)"
    )
    flag_value = re.compile(
        r"(?i)(?:^|\s)--(?P<key>[A-Za-z_][A-Za-z0-9_.-]*)\s+(?P<value>\S+)"
    )
    bearer_value = re.compile(r"(?i)(?:^|\s)bearer\s+(?P<value>\S+)")
    url_candidate = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s\"']+")
    sensitive_assignment_suffixes = (
        "password",
        "passwd",
        "pwd",
        "secret",
        "token",
        "apikey",
        "accesskey",
        "accountkey",
        "sharedaccesskey",
        "privatekey",
        "authorization",
    )

    def sensitive_assignment_name(value: str) -> bool:
        normalized = re.sub(r"[^a-z0-9]", "", value.lower())
        return normalized.endswith(sensitive_assignment_suffixes)
    referenced_secret_envs: set[str] = set()
    secret_backed_envs: set[str] = set()
    inline_envs: set[str] = set()

    def safe_header_mapping(value: object) -> bool:
        if not isinstance(value, dict) or not value:
            return False
        for header, item in value.items():
            if not isinstance(item, str):
                return False
            if SECRET_KEY_PATTERN.search(str(header)):
                match = safe_env_reference.fullmatch(item)
                if not match:
                    return False
                referenced_secret_envs.add(match.group("name"))
            elif SECRET_ASSIGNMENT_PATTERN.search(item):
                return False
        return True

    def inspect(node: object, location: str = "") -> None:
        if isinstance(node, dict):
            semantic_name = str(node.get("name", ""))
            semantic_value = node.get("value")
            if semantic_name and "value" in node and semantic_value not in (None, ""):
                inline_envs.add(semantic_name)
            value_from = node.get("valueFrom")
            if (
                semantic_name
                and isinstance(value_from, dict)
                and isinstance(value_from.get("secretKeyRef"), dict)
            ):
                secret_backed_envs.add(semantic_name)
            semantic_name_sensitive = bool(
                SECRET_KEY_PATTERN.search(semantic_name)
                or re.search(r"(?i)(authorization|credential|headers?)", semantic_name)
            )
            semantic_value_sensitive = bool(
                isinstance(semantic_value, str)
                and SECRET_ASSIGNMENT_PATTERN.search(semantic_value)
            )
            if semantic_value not in (None, "") and (
                semantic_name_sensitive or semantic_value_sensitive
            ):
                raise SystemExit(
                    f"--extra-values-file contains inline secret-like environment/header material at {location or '<root>'}: {path}. "
                    "Use a Kubernetes Secret valueFrom reference instead."
                )
            for raw_key, value in node.items():
                key = str(raw_key)
                normalized = re.sub(r"[^a-z0-9]", "", key.lower())
                child_location = f"{location}.{key}" if location else key
                root_secret_mapping = child_location == "secret" and isinstance(value, dict)
                sensitive_key = bool(
                    normalized in sensitive_keys
                    or SECRET_KEY_PATTERN.search(key)
                    or normalized in {"authorization", "xsf token".replace(" ", "")}
                )
                if normalized in {
                    "valuefrom",
                    "secretkeyref",
                    "configmapkeyref",
                    "fieldref",
                    "resourcefieldref",
                    "name",
                    "key",
                    "optional",
                }:
                    sensitive_key = False
                in_header_mapping = bool(
                    re.search(r"(?i)(^|\.)(headers?)(\.|$)", child_location)
                )
                safe_header_value = (
                    normalized in {"header", "headers"} and safe_header_mapping(value)
                ) or (
                    in_header_mapping
                    and isinstance(value, str)
                    and bool(safe_env_reference.fullmatch(value))
                )
                safe_env_match = (
                    safe_env_reference.fullmatch(value) if isinstance(value, str) else None
                )
                if sensitive_key and safe_env_match:
                    referenced_secret_envs.add(safe_env_match.group("name"))
                    safe_header_value = True
                if (
                    sensitive_key
                    and not root_secret_mapping
                    and not safe_header_value
                    and value not in (None, "", {})
                ):
                    raise SystemExit(
                        f"--extra-values-file contains inline secret material at {child_location}: {path}. "
                        "Use this skill's file-backed secret options instead."
                    )
                inspect(value, child_location)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                inspect(value, f"{location}[{index}]")
        elif isinstance(node, str):
            scalar = node.strip()
            for raw_url in url_candidate.findall(scalar):
                try:
                    parsed = urlsplit(raw_url.rstrip(".,)"))
                except ValueError as exc:
                    raise SystemExit(
                        f"--extra-values-file contains a malformed URL-like scalar at {location or '<root>'}: {path}."
                    ) from exc
                if parsed.username is not None or parsed.password is not None:
                    raise SystemExit(
                        f"--extra-values-file contains URL userinfo credentials at {location or '<root>'}: {path}. "
                        "Use a Secret-backed environment reference instead."
                    )
                for query_key, query_value in parse_qsl(
                    parsed.query, keep_blank_values=True
                ):
                    if sensitive_assignment_name(query_key) and query_value:
                        match = safe_env_reference.fullmatch(query_value)
                        if not match:
                            raise SystemExit(
                                f"--extra-values-file contains a credential-like URL query value at {location or '<root>'}: {path}. "
                                "Use a Secret-backed environment reference instead."
                            )
                        referenced_secret_envs.add(match.group("name"))
            if re.search(
                r"-----BEGIN (?:[A-Z0-9][A-Z0-9-]* )*PRIVATE KEY-----",
                scalar,
                flags=re.IGNORECASE,
            ):
                raise SystemExit(
                    f"--extra-values-file contains inline private-key material at {location or '<root>'}: {path}."
                )
            matches = [
                match
                for match in generic_assignment.finditer(scalar)
                if sensitive_assignment_name(match.group("key"))
            ]
            matches.extend(
                match
                for match in flag_value.finditer(scalar)
                if sensitive_assignment_name(match.group("key"))
            )
            matches.extend(bearer_value.finditer(scalar))
            for match in matches:
                candidate = match.group("value").strip("\"'")
                env_match = safe_env_reference.fullmatch(candidate)
                if env_match:
                    referenced_secret_envs.add(env_match.group("name"))
                    continue
                raise SystemExit(
                    f"--extra-values-file contains an inline credential assignment at {location or '<root>'}: {path}. "
                    "Use a Secret-backed environment reference instead."
                )

    inspect(payload)
    inline_references = sorted(referenced_secret_envs & inline_envs)
    if inline_references:
        raise SystemExit(
            "--extra-values-file resolves sensitive env references from inline values: "
            + ", ".join(inline_references)
            + ". Use valueFrom.secretKeyRef."
        )
    unresolved_references = sorted(referenced_secret_envs - secret_backed_envs)
    if unresolved_references:
        raise SystemExit(
            "--extra-values-file has sensitive env references without a matching valueFrom.secretKeyRef: "
            + ", ".join(unresolved_references)
        )

    protected_paths = (
        ("fullnameOverride",),
        ("nameOverride",),
        ("namespaceOverride",),
        ("clusterName",),
        ("cloudProvider",),
        ("distribution",),
        ("environment",),
        ("isWindows",),
        ("priorityClassName",),
        ("secret",),
        ("splunkObservability", "realm"),
        ("splunkObservability", "accessToken"),
        ("splunkObservability", "ingestUrl"),
        ("splunkObservability", "apiUrl"),
        ("splunkObservability", "metricsEnabled"),
        ("splunkObservability", "tracesEnabled"),
        ("splunkObservability", "profilingEnabled"),
        ("splunkObservability", "secureAppEnabled"),
        # Deprecated uncorrelated event format. Use clusterReceiver.eventsEnabled
        # through --enable-events so routing and completion evidence stay typed.
        ("splunkObservability", "infrastructureMonitoringEventsEnabled"),
        ("splunkPlatform", "endpoint"),
        ("splunkPlatform", "token"),
        ("splunkPlatform", "index"),
        ("splunkPlatform", "metricsIndex"),
        ("splunkPlatform", "tracesIndex"),
        ("splunkPlatform", "insecureSkipVerify"),
        ("splunkPlatform", "clientCert"),
        ("splunkPlatform", "clientKey"),
        ("splunkPlatform", "caFile"),
        ("splunkPlatform", "otlpIngest"),
        ("splunkPlatform", "logsEnabled"),
        ("splunkPlatform", "metricsEnabled"),
        ("splunkPlatform", "tracesEnabled"),
        ("splunkPlatform", "sendingQueue", "persistentQueue"),
        ("splunkPlatform", "fsyncEnabled"),
        ("agent", "enabled"),
        ("agent", "hostNetwork"),
        ("agent", "service", "enabled"),
        ("agent", "featureGates"),
        ("agent", "discovery", "enabled"),
        ("clusterReceiver", "enabled"),
        ("clusterReceiver", "eventsEnabled"),
        ("clusterReceiver", "k8sEventsEnabled"),
        ("clusterReceiver", "k8sObjects"),
        ("clusterReceiver", "featureGates"),
        ("gateway", "enabled"),
        ("gateway", "replicaCount"),
        ("gateway", "featureGates"),
        ("operator", "enabled"),
        ("operator", "fullnameOverride"),
        ("operator", "nameOverride"),
        ("operator", "namespaceOverride"),
        ("operator", "admissionWebhooks"),
        ("operatorcrds", "install"),
        ("certmanager", "enabled"),
        ("instrumentation", "enabled"),
        ("instrumentation", "installationJob", "enabled"),
        ("instrumentation", "installationJob", "image", "tag"),
        ("obi", "enabled"),
        ("obi", "fullnameOverride"),
        ("obi", "nameOverride"),
        ("obi", "namespaceOverride"),
        ("targetallocator", "enabled"),
        ("targetallocator", "fullnameOverride"),
        ("targetallocator", "nameOverride"),
        ("targetallocator", "namespaceOverride"),
        ("rbac", "customRules"),
        ("logsCollection", "containers", "enabled"),
        ("logsCollection", "journald", "enabled"),
        ("autodetect", "prometheus"),
        ("autodetect", "istio"),
        ("featureGates", "sendK8sEventsToSplunkO11y"),
        ("featureGates", "enableK8sEntities"),
        ("featureGates", "useEntityEventsForK8sProperties"),
        ("image", "otelcol", "repository"),
        ("image", "otelcol", "tag"),
        ("image", "otelcol", "digest"),
    )

    def contains_path(node: object, parts: tuple[str, ...]) -> bool:
        current = node
        for part in parts:
            if not isinstance(current, dict) or part not in current:
                return False
            current = current[part]
        return True

    for protected_path in protected_paths:
        if contains_path(payload, protected_path):
            raise SystemExit(
                "--extra-values-file overrides lifecycle-owned value "
                f"{'.'.join(protected_path)}: {path}. Use the corresponding typed skill option."
            )


def load_k8s_objects_file(path_value: str) -> list[dict[str, object]]:
    """Load a bounded, typed Kubernetes object-receiver specification."""

    if not path_value:
        return []
    path = Path(path_value)
    if not path.is_file() or path.is_symlink():
        raise ValueError("--k8s-objects-file must be a non-symlink regular file")
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("--k8s-objects-file must not exceed 1 MiB")
    try:
        payload = load_yaml_or_json(path.read_text(encoding="utf-8"), source=str(path))
    except (OSError, UnicodeError, YamlCompatError) as exc:
        raise ValueError(f"--k8s-objects-file is not valid readable YAML/JSON: {exc}") from exc
    if not isinstance(payload, list) or len(payload) > 50:
        raise ValueError("--k8s-objects-file must contain a YAML/JSON list of at most 50 objects")

    allowed = {
        "name",
        "mode",
        "group",
        "namespaces",
        "label_selector",
        "field_selector",
        "interval",
    }
    resource_re = re.compile(r"(?=.{1,63}\Z)[a-z](?:[-a-z0-9]*[a-z0-9])?")
    group_re = re.compile(r"(?=.{1,253}\Z)[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?")
    namespace_re = re.compile(r"(?=.{1,63}\Z)[a-z0-9](?:[-a-z0-9]*[a-z0-9])?")
    duration_re = re.compile(r"(?:[1-9][0-9]*(?:ms|s|m|h))+")
    normalized: list[dict[str, object]] = []
    identities: set[tuple[str, str]] = set()
    for index, raw in enumerate(payload):
        if not isinstance(raw, dict) or not raw:
            raise ValueError(f"--k8s-objects-file item {index + 1} must be a mapping")
        unknown = set(map(str, raw)) - allowed
        if unknown:
            raise ValueError(
                f"--k8s-objects-file item {index + 1} has unsupported keys: {', '.join(sorted(unknown))}"
            )
        name = raw.get("name")
        group = raw.get("group", "")
        mode = raw.get("mode", "pull")
        if not isinstance(name, str) or not resource_re.fullmatch(name):
            raise ValueError(f"--k8s-objects-file item {index + 1} requires a valid plural resource name")
        if name in {"secrets", "configmaps"}:
            raise ValueError(
                f"--k8s-objects-file item {index + 1} requests {name}, which may contain credentials and is never exported by this skill"
            )
        if not isinstance(group, str) or (group and not group_re.fullmatch(group)):
            raise ValueError(f"--k8s-objects-file item {index + 1} has an invalid API group")
        if mode not in {"pull", "watch"}:
            raise ValueError(f"--k8s-objects-file item {index + 1} mode must be pull or watch")
        identity = (group, name)
        if identity in identities:
            raise ValueError(f"--k8s-objects-file repeats resource {name}.{group or 'core'}")
        identities.add(identity)

        item: dict[str, object] = {"name": name, "mode": mode}
        if group:
            item["group"] = group
        namespaces = raw.get("namespaces")
        if namespaces is not None:
            if (
                not isinstance(namespaces, list)
                or not namespaces
                or len(namespaces) > 100
                or any(not isinstance(ns, str) or not namespace_re.fullmatch(ns) for ns in namespaces)
                or len(namespaces) != len(set(namespaces))
            ):
                raise ValueError(
                    f"--k8s-objects-file item {index + 1} namespaces must be a unique nonempty DNS-name list"
                )
            item["namespaces"] = namespaces
        for key in ("label_selector", "field_selector"):
            value = raw.get(key)
            if value is not None:
                if not isinstance(value, str) or not value or len(value) > 1024:
                    raise ValueError(f"--k8s-objects-file item {index + 1} {key} must be a nonempty string")
                try:
                    validate_single_line(value, key)
                except ValueError as exc:
                    raise ValueError(f"--k8s-objects-file item {index + 1} {exc}") from exc
                item[key] = value
        interval = raw.get("interval")
        if interval is not None:
            if mode != "pull" or not isinstance(interval, str) or not duration_re.fullmatch(interval):
                raise ValueError(
                    f"--k8s-objects-file item {index + 1} interval must be a positive pull-mode duration such as 15m"
                )
            item["interval"] = interval
        normalized.append(item)
    return normalized


def render_k8s_objects_values(objects: list[dict[str, object]]) -> list[str]:
    if not objects:
        return ["  k8sObjects: []"]
    lines = ["  k8sObjects:"]
    for item in objects:
        lines.append("    -")
        lines.append(f"      name: {yaml_scalar(str(item['name']))}")
        lines.append(f"      mode: {yaml_scalar(str(item['mode']))}")
        for key in ("group", "label_selector", "field_selector", "interval"):
            if key in item:
                lines.append(f"      {key}: {yaml_scalar(str(item[key]))}")
        if "namespaces" in item:
            lines.append("      namespaces:")
            lines.extend(f"        - {yaml_scalar(str(ns))}" for ns in item["namespaces"])
    return lines


def render_k8s_object_rbac_values(objects: list[dict[str, object]]) -> list[str]:
    if not objects:
        return ["  customRules: []"]
    grouped: dict[str, list[str]] = {}
    for item in objects:
        grouped.setdefault(str(item.get("group", "")), []).append(str(item["name"]))
    lines = ["  customRules:"]
    for group, resources in grouped.items():
        lines.extend(("    -", "      apiGroups:", f"        - {yaml_scalar(group)}", "      resources:"))
        lines.extend(f"        - {yaml_scalar(resource)}" for resource in resources)
        lines.extend(("      verbs:", '        - "get"', '        - "list"', '        - "watch"'))
    return lines


def write_text(path: Path, content: str, executable: bool = False) -> None:
    """Atomically replace a generated text file without following final symlinks."""

    path.parent.mkdir(parents=True, exist_ok=True)
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory_fd = os.open(path.parent, directory_flags)
    temporary_name = ""
    try:
        try:
            existing = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        if existing is not None and stat.S_ISLNK(existing.st_mode):
            raise RuntimeError(f"refusing to replace generated-file symlink: {path}")

        open_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        for _ in range(128):
            temporary_name = f".{path.name}.{os.getpid()}.{os.urandom(12).hex()}.tmp"
            try:
                file_fd = os.open(temporary_name, open_flags, 0o600, dir_fd=directory_fd)
                break
            except FileExistsError:
                temporary_name = ""
        else:
            raise RuntimeError(f"could not allocate an atomic output file beside {path}")

        try:
            with os.fdopen(file_fd, "w", encoding="utf-8", newline="") as stream:
                os.fchmod(stream.fileno(), 0o755 if executable else 0o644)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            try:
                os.close(file_fd)
            except OSError:
                pass
            raise

        os.replace(
            temporary_name,
            path.name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        temporary_name = ""
        os.fsync(directory_fd)
    finally:
        if temporary_name:
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
        os.close(directory_fd)


def bash_array(name: str, values: list[str]) -> str:
    if not values:
        return f"{name}=()\n"
    def array_value(value: str) -> str:
        quoted = shell_quote(value)
        # shlex.quote deliberately leaves commas in otherwise safe words, but
        # ShellCheck SC2054 treats comma-bearing array literals as suspicious.
        # Force an ordinary single-quoted word without changing argv semantics.
        if "," in value and quoted == value:
            return "'" + value.replace("'", "'\"'\"'") + "'"
        return quoted

    body = "\n".join(f"    {array_value(value)}" for value in values)
    return f"{name}=(\n{body}\n)\n"


def secret_name(release_name: str) -> str:
    return f"{release_name}-splunk"


def helm_fullname(release_name: str, chart_name: str) -> str:
    """Mirror the standard fullname helper used by the pinned Helm chart."""

    value = release_name if chart_name in release_name else f"{release_name}-{chart_name}"
    return value[:63].rstrip("-")


def bounded_k8s_name(value: str, limit: int) -> str:
    """Bound a generated name while retaining collision-resistant identity."""

    if len(value) <= limit:
        return value.rstrip("-")
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return f"{value[: limit - len(digest) - 1].rstrip('-')}-{digest}"


def cluster_receiver_name(collector_fullname: str, distribution: str) -> str:
    value = f"{collector_fullname}-k8s-cluster-receiver"
    limit = 52 if distribution == "eks/fargate" else 63
    return value[:limit].rstrip("-")


def operator_fullname(release_name: str) -> str:
    # The operator chart appends "-controller-manager-service-cert" (32
    # characters) without another truncation.
    raw = release_name if "operator" in release_name else f"{release_name}-operator"
    return bounded_k8s_name(raw, 31)


def target_allocator_fullname(release_name: str) -> str:
    # The target allocator appends "-ta" to its fullname.
    raw = release_name if "targetallocator" in release_name else f"{release_name}-targetallocator"
    return bounded_k8s_name(raw, 60)


def obi_fullname(release_name: str) -> str:
    raw = release_name if "obi" in release_name else f"{release_name}-obi"
    return bounded_k8s_name(raw, 63)


def bool_arg(parser: argparse.ArgumentParser, name: str, default: bool) -> None:
    parser.add_argument(
        f"--{name}",
        choices=("true", "false"),
        default="true" if default else "false",
    )


def version_tuple(value: str) -> tuple[int, ...]:
    parts = [int(part) for part in re.findall(r"\d+", value)]
    return tuple(parts[:3])


def version_in_range(value: str, minimum: str, maximum: str) -> bool:
    current = version_tuple(value)
    low = version_tuple(minimum)
    high = version_tuple(maximum)
    if not current or not low or not high:
        return False
    lower_width = len(low)
    upper_width = len(high)
    current_for_low = (current + (0,) * lower_width)[:lower_width]
    current_for_high = (current + (0,) * upper_width)[:upper_width]
    return low <= current_for_low and current_for_high <= high


def valid_host_port(value: str) -> bool:
    match = re.fullmatch(
        r"(?:\[[0-9A-Fa-f:]+\]|[A-Za-z0-9._-]+):([0-9]{1,5})",
        value,
    )
    return bool(match and 1 <= int(match.group(1)) <= 65535)


def valid_listen_interface(value: str) -> bool:
    if value == "localhost":
        return True
    candidate = value[1:-1] if value.startswith("[") and value.endswith("]") else value
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return False
    return True


def normalized_listen_interface(value: str) -> str:
    if value == "localhost":
        return value
    candidate = value[1:-1] if value.startswith("[") and value.endswith("]") else value
    parsed = ipaddress.ip_address(candidate)
    return f"[{parsed.compressed}]" if parsed.version == 6 else parsed.compressed


def valid_http_url(value: str, *, https_only: bool = False) -> bool:
    """Validate a non-secret HTTP endpoint safe to persist in rendered assets."""

    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError:
        return False
    allowed_schemes = {"https"} if https_only else {"http", "https"}
    return bool(
        parsed.scheme.lower() in allowed_schemes
        and parsed.hostname
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
    )


def valid_linux_env_url(value: str) -> bool:
    """Validate a URL that the upstream installer persists in EnvironmentFile syntax."""

    return bool(
        valid_http_url(value, https_only=True)
        and not re.search(r'''[\s'"\\]''', value)
    )


def diagnostic_redactor_script() -> str:
    return r"""#!/usr/bin/env python3
# Fail-closed redaction for Collector diagnostics and support bundles.

import re
import sys

text = sys.stdin.read()
key = r"(?:[A-Za-z0-9_.-]*(?:access[_ -]?token|hec[_ -]?token|client[_ -]?secret|api[_ -]?key|access[_ -]?key|password|authorization|credential|private[_ -]?key|headers?|cookie|secret|token)[A-Za-z0-9_.-]*)"
quoted = re.compile(
    rf'''(?ix)
    (?P<prefix>["'][^"'\r\n]*{key}[^"'\r\n]*["']\s*:\s*)
    (?P<quote>["'])(?P<value>.*?)(?P=quote)
    '''
)
assignment = re.compile(
    rf'''(?ix)
    (?P<prefix>(?<![A-Za-z0-9_.-]){key}\s*[:=]\s*)
    (?P<value>[^\r\n]+)
    '''
)
bearer = re.compile(r"(?i)(\bBearer\s+)[^\s,;\"']+")
cli = re.compile(
    rf'''(?ix)
    (?P<prefix>--?{key}(?:=|\s+))(?P<value>[^\s]+)
    '''
)

text = bearer.sub(r"\1__REDACTED__", text)
text = quoted.sub(lambda match: f'{match.group("prefix")}"__REDACTED__"', text)
text = assignment.sub(lambda match: f'{match.group("prefix")}__REDACTED__', text)
text = cli.sub(lambda match: f'{match.group("prefix")}__REDACTED__', text)
sys.stdout.write(text)
"""


def k8s_image_post_renderer_script(targets: list[dict[str, str]]) -> str:
    """Return the audited, fail-closed image allowlist post-renderer."""

    source_pins = {
        COLLECTOR_STANDARD_SOURCE_IMAGE: COLLECTOR_STANDARD_IMAGE,
        COLLECTOR_FIPS_SOURCE_IMAGE: COLLECTOR_FIPS_IMAGE,
        COLLECTOR_WINDOWS_SOURCE_IMAGE: COLLECTOR_WINDOWS_IMAGE,
        FARGATE_NODE_DISCOVERER_SOURCE_IMAGE: FARGATE_NODE_DISCOVERER_IMAGE,
        **K8S_AUXILIARY_IMAGE_PINS,
    }
    collector_repositories = (
        "quay.io/signalfx/splunk-otel-collector",
        "quay.io/signalfx/splunk-otel-collector-fips",
        "quay.io/signalfx/splunk-otel-collector-windows",
    )
    template = r'''#!/usr/bin/env python3
"""Rewrite audited chart images to digests and reject mutable image drift."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


SOURCE_PINS = __SOURCE_PINS__
PINNED_IMAGES = set(SOURCE_PINS.values())
TARGETS = __TARGETS__
COLLECTOR_REPOSITORIES = __COLLECTOR_REPOSITORIES__
DIGEST_IMAGE = re.compile(r"^.+@sha256:[0-9a-f]{64}$")


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: Kubernetes image pin verification failed: {message}")


def unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def indentation(line: str) -> int:
    prefix = line[: len(line) - len(line.lstrip(" \t"))]
    if "\t" in prefix:
        fail("tab-indented YAML is outside the audited Helm output contract")
    return len(prefix)


def scalar(line: str, key: str) -> str | None:
    content = line.rstrip("\r\n")
    match = re.fullmatch(rf"[ ]*{re.escape(key)}:[ ]*([^#\s]+)[ ]*", content)
    return unquote(match.group(1)) if match else None


def split_documents(text: str) -> list[list[str]]:
    documents = re.split(r"(?m)(?=^---[ \t]*\r?$)", text)
    return [document.splitlines(keepends=True) for document in documents if document]


def identity(lines: list[str]) -> tuple[str, str]:
    kind = ""
    name = ""
    for index, line in enumerate(lines):
        if indentation(line) == 0 and scalar(line, "kind") is not None:
            kind = scalar(line, "kind") or ""
        if line.rstrip("\r\n") != "metadata:":
            continue
        for child in lines[index + 1 :]:
            stripped = child.strip()
            if stripped and not stripped.startswith("#") and indentation(child) == 0:
                break
            if indentation(child) > 0 and scalar(child, "name") is not None:
                name = scalar(child, "name") or ""
                break
        break
    return kind, name


def container_image_lines(lines: list[str], section: str, container: str) -> list[int]:
    locations: list[int] = []
    for index, line in enumerate(lines):
        if line.strip() != f"{section}:":
            continue
        section_indent = indentation(line)
        item_indent: int | None = None
        cursor = index + 1
        while cursor < len(lines):
            candidate = lines[cursor]
            stripped = candidate.strip()
            candidate_indent = indentation(candidate)
            if stripped and not stripped.startswith("#"):
                if candidate_indent < section_indent:
                    break
                if candidate_indent == section_indent and not stripped.startswith("-"):
                    break
            match = re.fullmatch(
                r"[ ]*-[ ]+name:[ ]*([^#\s]+)[ ]*",
                candidate.rstrip("\r\n"),
            )
            if match:
                if item_indent is None:
                    item_indent = candidate_indent
                if candidate_indent == item_indent and unquote(match.group(1)) == container:
                    child_images: list[int] = []
                    child = cursor + 1
                    while child < len(lines):
                        child_line = lines[child]
                        child_stripped = child_line.strip()
                        child_indent = indentation(child_line)
                        if child_stripped and not child_stripped.startswith("#") and child_indent <= item_indent:
                            break
                        if child_indent > item_indent and scalar(child_line, "image") is not None:
                            child_images.append(child)
                        child += 1
                    if len(child_images) != 1:
                        fail(
                            f"container {container!r} in {section!r} has "
                            f"{len(child_images)} image fields"
                        )
                    locations.extend(child_images)
            cursor += 1
    return locations


def is_collector_image(image: str) -> bool:
    return any(
        image == repository or image.startswith(repository + ":") or image.startswith(repository + "@")
        for repository in COLLECTOR_REPOSITORIES
    )


def repository_of(image: str) -> str:
    without_digest = image.split("@", 1)[0]
    prefix, separator, leaf = without_digest.rpartition("/")
    if ":" in leaf:
        leaf = leaf.split(":", 1)[0]
    return f"{prefix}{separator}{leaf}"


def audited_pins_for(image: str) -> set[str]:
    repository = repository_of(image)
    return {
        pinned
        for source, pinned in SOURCE_PINS.items()
        if repository_of(source) == repository
    }


def target_locations(
    documents: list[list[str]],
    expected_key: str,
) -> dict[tuple[int, int], dict[str, str]]:
    result: dict[tuple[int, int], dict[str, str]] = {}
    for target in TARGETS:
        matching_documents = [
            index
            for index, lines in enumerate(documents)
            if identity(lines) == (target["kind"], target["name"])
        ]
        if len(matching_documents) != 1:
            fail(
                f"expected one {target['kind']} named {target['name']!r}, "
                f"found {len(matching_documents)}"
            )
        document_index = matching_documents[0]
        lines = documents[document_index]
        image_lines = container_image_lines(lines, target["section"], target["container"])
        if len(image_lines) != 1:
            fail(
                f"expected one {target['section']} container {target['container']!r} "
                f"in {target['kind']}/{target['name']}, found {len(image_lines)}"
            )
        location = (document_index, image_lines[0])
        if location in result:
            fail(f"duplicate image target at {target['kind']}/{target['name']}")
        actual = scalar(lines[image_lines[0]], "image")
        expected = target[expected_key]
        if actual != expected:
            fail(
                f"{target['kind']}/{target['name']} container {target['container']!r} "
                f"uses {actual!r}; expected {expected!r}"
            )
        result[location] = target
    return result


def validate_all_images(
    documents: list[list[str]],
    targets_by_location: dict[tuple[int, int], dict[str, str]],
    *,
    rewritten: bool,
) -> None:
    for document_index, lines in enumerate(documents):
        for line_index, line in enumerate(lines):
            image = scalar(line, "image")
            if image is None:
                continue
            location = (document_index, line_index)
            if is_collector_image(image) and location not in targets_by_location:
                fail(f"Collector image {image!r} appeared outside an audited named workload target")
            repository_pins = audited_pins_for(image)
            if rewritten:
                if repository_pins:
                    if image in repository_pins:
                        continue
                    fail(f"audited image repository was rewritten to an unknown digest: {image!r}")
                if DIGEST_IMAGE.fullmatch(image):
                    continue
            else:
                if repository_pins:
                    if image in SOURCE_PINS:
                        continue
                    fail(f"audited image repository used an unknown tag or digest: {image!r}")
                if DIGEST_IMAGE.fullmatch(image):
                    continue
            state = "post-rendered" if rewritten else "chart-rendered"
            fail(
                f"{state} image {image!r} is neither in the audited image map nor "
                "a custom @sha256 digest pin"
            )


def rewrite(text: str) -> str:
    documents = split_documents(text)
    locations = target_locations(documents, "source")
    validate_all_images(documents, locations, rewritten=False)
    for lines in documents:
        for index, line in enumerate(lines):
            image = scalar(line, "image")
            if image not in SOURCE_PINS:
                continue
            ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
            lines[index] = f"{' ' * indentation(line)}image: {SOURCE_PINS[image]}{ending}"
    pinned_locations = target_locations(documents, "pinned")
    validate_all_images(documents, pinned_locations, rewritten=True)
    return "".join("".join(lines) for lines in documents)


def verify_manifest(text: str) -> None:
    documents = split_documents(text)
    locations = target_locations(documents, "pinned")
    validate_all_images(documents, locations, rewritten=True)


def verify_json_images(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "image" and isinstance(child, str):
                if is_collector_image(child):
                    if child not in {target["pinned"] for target in TARGETS}:
                        fail(f"live object has unaudited Collector image {child!r}")
                elif audited_pins_for(child) and child not in audited_pins_for(child):
                    fail(f"live object has an unknown digest for an audited image repository: {child!r}")
                elif not audited_pins_for(child) and not DIGEST_IMAGE.fullmatch(child):
                    fail(f"live object has mutable or unaudited image {child!r}")
            verify_json_images(child)
    elif isinstance(value, list):
        for child in value:
            verify_json_images(child)


def controller_owner(payload: dict):
    """Return one complete controller owner reference, if present."""

    metadata = payload.get("metadata") or {}
    references = metadata.get("ownerReferences") or []
    controllers = [
        item
        for item in references
        if isinstance(item, dict) and item.get("controller") is True
    ]
    if len(controllers) > 1:
        fail("live Pod has multiple controller owner references")
    if not controllers:
        return None
    owner = controllers[0]
    kind = str(owner.get("kind") or "")
    name = str(owner.get("name") or "")
    if not kind or not name:
        fail("live Pod controller owner reference is incomplete")
    return kind, name


def targets_for_primary_pod(payload: dict) -> list[dict[str, str]]:
    """Resolve an exact primary Pod controller to rendered core targets."""

    owner = controller_owner(payload)
    if owner is None:
        return []
    kind, name = owner
    if kind == "ReplicaSet":
        metadata = payload.get("metadata") or {}
        labels = metadata.get("labels") or {}
        pod_template_hash = labels.get("pod-template-hash")
        if not isinstance(pod_template_hash, str) or not re.fullmatch(
            r"[a-z0-9]+", pod_template_hash
        ):
            return []
        deployment_names = {
            target["name"]
            for target in TARGETS
            if target["kind"] == "Deployment"
            and name == f"{target['name']}-{pod_template_hash}"
        }
        if not deployment_names:
            return []
        if len(deployment_names) != 1:
            fail("live Pod ReplicaSet owner ambiguously matches rendered Deployments")
        resolved_kind = "Deployment"
        resolved_name = next(iter(deployment_names))
    else:
        resolved_kind = kind
        resolved_name = name
    return [
        target
        for target in TARGETS
        if (target["kind"], target["name"]) == (resolved_kind, resolved_name)
    ]


def verify_target_containers(
    pod_spec: dict,
    object_targets: list[dict[str, str]],
    identity: str,
) -> None:
    for target in object_targets:
        containers = pod_spec.get(target["section"], [])
        matches = [
            item
            for item in containers
            if isinstance(item, dict) and item.get("name") == target["container"]
        ]
        if len(matches) != 1 or matches[0].get("image") != target["pinned"]:
            fail(
                f"live {identity} does not have exactly one {target['container']!r} "
                f"container pinned to {target['pinned']!r}"
            )


def verify_pod_payload(payload: dict, *, primary: bool) -> None:
    owner_targets = targets_for_primary_pod(payload)
    if primary and not owner_targets:
        fail("primary live Pod is not owned by an exact rendered core controller")
    if owner_targets:
        name = str((payload.get("metadata") or {}).get("name") or "<unknown>")
        verify_target_containers(payload.get("spec") or {}, owner_targets, f"Pod/{name}")


def completed_job(payload: dict) -> bool:
    owner = controller_owner(payload)
    return str((payload.get("status") or {}).get("phase") or "") == "Succeeded" and (
        owner is not None and owner[0] == "Job"
    )


def verify_active_pod(payload: dict) -> None:
    metadata = payload.get("metadata") or {}
    status = payload.get("status") or {}
    phase = str(status.get("phase") or "")
    ready = any(
        isinstance(row, dict)
        and row.get("type") == "Ready"
        and row.get("status") == "True"
        for row in (status.get("conditions") or [])
    )
    if phase != "Running" or not ready or metadata.get("deletionTimestamp"):
        fail("live Pod is not active, Running, Ready, and non-terminating")


def parse_object_json(text: str, kind: str, name: str) -> dict:
    try:
        payload = json.loads(text)
    except (TypeError, ValueError) as exc:
        fail(f"live object JSON is invalid: {exc}")
    if payload.get("kind") != kind or payload.get("metadata", {}).get("name") != name:
        fail(f"live object is not {kind}/{name}")
    return payload


def verify_object_json(text: str, kind: str, name: str) -> None:
    payload = parse_object_json(text, kind, name)
    verify_json_images(payload)
    if kind == "Pod":
        verify_pod_payload(payload, primary=False)
        return
    object_targets = [
        target for target in TARGETS if (target["kind"], target["name"]) == (kind, name)
    ]
    pod_spec = payload.get("spec", {}).get("template", {}).get("spec", {})
    verify_target_containers(pod_spec, object_targets, f"{kind}/{name}")


def verify_object_list_json(text: str) -> None:
    try:
        payload = json.loads(text)
    except (TypeError, ValueError) as exc:
        fail(f"live object-list JSON is invalid: {exc}")
    if not isinstance(payload.get("items"), list):
        fail("live object-list JSON has no items array")
    for item in payload["items"]:
        verify_json_images(item)
        if isinstance(item, dict) and item.get("kind") == "Pod":
            verify_pod_payload(item, primary=False)


def verify_runtime_pod_json(text: str, name: str, membership: str) -> None:
    if membership not in {"primary", "auxiliary"}:
        fail("live Pod membership must be primary or auxiliary")
    payload = parse_object_json(text, "Pod", name)
    verify_json_images(payload)
    if completed_job(payload):
        raise SystemExit(10)
    verify_pod_payload(payload, primary=membership == "primary")
    verify_active_pod(payload)


def main() -> None:
    if len(sys.argv) == 1:
        sys.stdout.write(rewrite(sys.stdin.read()))
        return
    if len(sys.argv) == 3 and sys.argv[1] == "--verify":
        verify_manifest(Path(sys.argv[2]).read_text(encoding="utf-8"))
        return
    if len(sys.argv) == 4 and sys.argv[1] == "--verify-object-json":
        verify_object_json(sys.stdin.read(), sys.argv[2], sys.argv[3])
        return
    if len(sys.argv) == 4 and sys.argv[1] == "--verify-runtime-pod-json":
        verify_runtime_pod_json(sys.stdin.read(), sys.argv[2], sys.argv[3])
        return
    if len(sys.argv) == 2 and sys.argv[1] == "--verify-object-list-json":
        verify_object_list_json(sys.stdin.read())
        return
    fail(
        "usage: post-render stdin, --verify MANIFEST, --verify-object-json KIND NAME, "
        "--verify-runtime-pod-json NAME MEMBERSHIP, or --verify-object-list-json"
    )


if __name__ == "__main__":
    main()
'''
    return (
        template.replace("__SOURCE_PINS__", json.dumps(source_pins, sort_keys=True))
        .replace("__TARGETS__", json.dumps(targets, sort_keys=True))
        .replace("__COLLECTOR_REPOSITORIES__", json.dumps(collector_repositories))
    )


def helm_release_guard_script(release: str, namespace: str) -> str:
    """Return bounded parsers that prove a same-name Helm release is ours."""

    template = r'''#!/usr/bin/env python3
"""Validate exact Helm list and release-metadata records before mutation."""

import argparse
import json
import re
import sys


EXPECTED_RELEASE = __RELEASE__
EXPECTED_NAMESPACE = __NAMESPACE__
EXPECTED_CHART = __CHART__
MAXIMUM_BYTES = 4 * 1024 * 1024
KNOWN_STATUSES = {
    "deployed",
    "failed",
    "pending-install",
    "pending-upgrade",
    "pending-rollback",
    "superseded",
    "uninstalled",
    "uninstalling",
}


def fail(message):
    raise SystemExit("ERROR: Helm release ownership guard failed: " + message)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", action="store_true")
    parser.add_argument("--allow-absent", action="store_true")
    parser.add_argument("--allowed-status", action="append", default=[])
    parser.add_argument("--expected-revision", type=int)
    args = parser.parse_args()
    allowed = set(args.allowed_status)
    if not allowed or not allowed <= KNOWN_STATUSES:
        fail("one or more known --allowed-status values are required")
    data = sys.stdin.buffer.read(MAXIMUM_BYTES + 1)
    if len(data) > MAXIMUM_BYTES:
        fail("Helm output exceeds the 4 MiB safety bound")
    if args.metadata:
        try:
            fields = data.decode("utf-8").strip("\r\n").split("\t")
        except UnicodeDecodeError as exc:
            fail("Helm release metadata is not UTF-8: " + str(exc))
        if len(fields) != 6:
            fail("Helm release metadata does not contain exactly six fields")
        release, namespace, revision, status, chart_name, chart_version = fields
        if release != EXPECTED_RELEASE or namespace != EXPECTED_NAMESPACE:
            fail("Helm release metadata does not match the rendered target")
        if not re.fullmatch(r"[1-9][0-9]*", revision):
            fail("the release metadata revision is invalid")
        if args.expected_revision is not None and int(revision) != args.expected_revision:
            fail(
                "release revision changed concurrently (expected %d, found %s)"
                % (args.expected_revision, revision)
            )
        if status not in allowed:
            fail("release metadata status %r is not safe for this operation" % status)
        if chart_name != EXPECTED_CHART:
            fail("the same-name release belongs to foreign chart %r" % chart_name)
        if not re.fullmatch(r"[0-9][0-9A-Za-z.+-]*", chart_version):
            fail("the release chart version is invalid")
        print("%s\t%s\t%s\t%s" % (revision, status, chart_name, chart_version))
        return
    try:
        releases = json.loads(data)
    except (UnicodeDecodeError, ValueError) as exc:
        fail("Helm list output is not valid JSON: " + str(exc))
    if not isinstance(releases, list):
        fail("Helm list output is not a JSON list")
    matches = [
        item
        for item in releases
        if isinstance(item, dict) and item.get("name") == EXPECTED_RELEASE
    ]
    if not matches:
        if args.allow_absent:
            print("absent")
            return
        fail("the expected release is absent")
    if len(matches) != 1:
        fail("Helm returned duplicate exact-name release records")
    item = matches[0]
    if item.get("namespace") != EXPECTED_NAMESPACE:
        fail("the release namespace does not match the rendered target")
    chart = item.get("chart")
    if not isinstance(chart, str) or not chart:
        fail("the Helm list chart field is missing")
    status = item.get("status")
    if status not in allowed:
        fail("release status %r is not safe for this operation" % status)
    revision = str(item.get("revision", ""))
    if not re.fullmatch(r"[1-9][0-9]*", revision):
        fail("the release revision is invalid")
    if args.expected_revision is not None and int(revision) != args.expected_revision:
        fail(
            "release revision changed concurrently (expected %d, found %s)"
            % (args.expected_revision, revision)
        )
    print("%s\t%s\t%s" % (revision, status, chart))


if __name__ == "__main__":
    main()
'''
    return (
        template.replace("__RELEASE__", json.dumps(release))
        .replace("__NAMESPACE__", json.dumps(namespace))
        .replace("__CHART__", json.dumps(CHART_NAME))
    )


def instrumentation_lifecycle_script(name: str, namespace: str, release: str) -> str:
    """Return the fail-closed ownership and rollback helper for the Job-owned CR."""

    template = r'''#!/usr/bin/env python3
"""Validate and restore the chart Job-owned Instrumentation resource."""

import json
import os
import stat
import sys


EXPECTED_NAME = __NAME__
EXPECTED_NAMESPACE = __NAMESPACE__
EXPECTED_RELEASE = __RELEASE__
MAXIMUM_BYTES = 4 * 1024 * 1024


def fail(message):
    raise SystemExit("ERROR: Instrumentation lifecycle guard failed: " + message)


def decode(data, source):
    if len(data) > MAXIMUM_BYTES:
        fail(source + " exceeds the 4 MiB safety bound")
    try:
        payload = json.loads(data)
    except (UnicodeDecodeError, ValueError) as exc:
        fail(source + " is not valid JSON: " + str(exc))
    if not isinstance(payload, dict):
        fail(source + " is not a JSON object")
    return payload


def read_stdin():
    return decode(sys.stdin.buffer.read(MAXIMUM_BYTES + 1), "stdin")


def read_snapshot(path):
    if not hasattr(os, "O_NOFOLLOW"):
        fail("snapshot verification requires O_NOFOLLOW support")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        fail("cannot open the rollback snapshot safely: " + str(exc))
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            fail("rollback snapshot must be a single-link regular file")
        if before.st_size < 2 or before.st_size > MAXIMUM_BYTES:
            fail("rollback snapshot size is outside the safety bound")
        chunks = []
        remaining = MAXIMUM_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        before_fingerprint = (
            before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
            before.st_ctime_ns, before.st_nlink,
        )
        after_fingerprint = (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
            after.st_ctime_ns, after.st_nlink,
        )
        if before_fingerprint != after_fingerprint:
            fail("rollback snapshot changed while it was read")
    finally:
        os.close(descriptor)
    return decode(b"".join(chunks), "rollback snapshot")


def verify_identity(payload, kind, name):
    metadata = payload.get("metadata")
    if payload.get("kind") != kind or not isinstance(metadata, dict):
        fail("live object is not " + kind + "/" + name)
    if metadata.get("name") != name or metadata.get("namespace") != EXPECTED_NAMESPACE:
        fail("live object has an unexpected name or namespace")
    if metadata.get("deletionTimestamp"):
        fail(kind + "/" + name + " is already terminating")
    labels = metadata.get("labels")
    if not isinstance(labels, dict):
        fail(kind + "/" + name + " has no ownership labels")
    if labels.get("app.kubernetes.io/managed-by") != "Helm":
        fail(kind + "/" + name + " is not managed by Helm")
    if labels.get("app.kubernetes.io/instance") != EXPECTED_RELEASE:
        fail(kind + "/" + name + " belongs to another Helm release")


def verify_instrumentation(payload):
    verify_identity(payload, "Instrumentation", EXPECTED_NAME)
    annotations = payload["metadata"].get("annotations")
    if not isinstance(annotations, dict):
        fail("Instrumentation has no Helm ownership annotations")
    if annotations.get("meta.helm.sh/release-name") != EXPECTED_RELEASE:
        fail("Instrumentation belongs to another Helm release")
    if annotations.get("meta.helm.sh/release-namespace") != EXPECTED_NAMESPACE:
        fail("Instrumentation belongs to another Helm release namespace")


def sanitized(payload):
    verify_instrumentation(payload)
    result = json.loads(json.dumps(payload))
    result.pop("status", None)
    metadata = result["metadata"]
    for key in (
        "creationTimestamp", "deletionGracePeriodSeconds", "deletionTimestamp",
        "generation", "managedFields", "resourceVersion", "selfLink", "uid",
    ):
        metadata.pop(key, None)
    return result


def emit(payload):
    json.dump(payload, sys.stdout, separators=(",", ":"), sort_keys=True)
    sys.stdout.write("\n")


def emit_delete_options(payload, kind, name):
    if kind == "Instrumentation":
        verify_instrumentation(payload)
    else:
        verify_identity(payload, kind, name)
    metadata = payload["metadata"]
    uid = metadata.get("uid")
    resource_version = metadata.get("resourceVersion")
    if not isinstance(uid, str) or not uid:
        fail("live " + kind + " has no UID for conditional deletion")
    if not isinstance(resource_version, str) or not resource_version:
        fail("live " + kind + " has no resourceVersion for conditional deletion")
    emit(
        {
            "apiVersion": "v1",
            "kind": "DeleteOptions",
            "preconditions": {"uid": uid, "resourceVersion": resource_version},
        }
    )


def main():
    if sys.argv[1:] == ["--verify-owned"]:
        verify_instrumentation(read_stdin())
        return
    if sys.argv[1:] == ["--sanitize-snapshot"]:
        emit(sanitized(read_stdin()))
        return
    if len(sys.argv) == 3 and sys.argv[1] == "--prepare-replace":
        current = read_stdin()
        verify_instrumentation(current)
        snapshot = read_snapshot(sys.argv[2])
        verify_instrumentation(snapshot)
        resource_version = current["metadata"].get("resourceVersion")
        uid = current["metadata"].get("uid")
        if not isinstance(resource_version, str) or not resource_version:
            fail("live Instrumentation has no resourceVersion for atomic replacement")
        if not isinstance(uid, str) or not uid:
            fail("live Instrumentation has no UID for atomic replacement")
        snapshot["metadata"]["resourceVersion"] = resource_version
        snapshot["metadata"]["uid"] = uid
        emit(snapshot)
        return
    if len(sys.argv) == 4 and sys.argv[1] == "--verify-helm-object":
        verify_identity(read_stdin(), sys.argv[2], sys.argv[3])
        return
    if len(sys.argv) == 4 and sys.argv[1] == "--delete-options":
        emit_delete_options(read_stdin(), sys.argv[2], sys.argv[3])
        return
    fail(
        "usage: --verify-owned, --sanitize-snapshot, "
        "--prepare-replace SNAPSHOT, --verify-helm-object KIND NAME, "
        "or --delete-options KIND NAME"
    )


if __name__ == "__main__":
    main()
'''
    return (
        template.replace("__NAME__", json.dumps(name))
        .replace("__NAMESPACE__", json.dumps(namespace))
        .replace("__RELEASE__", json.dumps(release))
    )


def ta_effective_listen_interface(args: argparse.Namespace) -> str:
    if args.ta_listen_interface:
        return normalized_listen_interface(args.ta_listen_interface)
    if args.ta_mode == "gateway":
        return "0.0.0.0"
    return "localhost"


def linux_effective_listen_interface(args: argparse.Namespace) -> str:
    if args.listen_interface:
        return normalized_listen_interface(args.listen_interface)
    return "127.0.0.1" if args.linux_mode == "agent" else "0.0.0.0"


def linux_effective_health_endpoint(args: argparse.Namespace) -> str:
    if args.linux_health_endpoint:
        return args.linux_health_endpoint
    listen = linux_effective_listen_interface(args)
    candidate = listen[1:-1] if listen.startswith("[") and listen.endswith("]") else listen
    if candidate == "0.0.0.0":
        health_host = "127.0.0.1"
    elif candidate == "::":
        health_host = "[::1]"
    else:
        health_host = listen
    return f"http://{health_host}:13133/"


def linux_effective_ingest_url(args: argparse.Namespace) -> str:
    return (
        args.linux_ingest_url.rstrip("/")
        if args.linux_ingest_url
        else f"https://ingest.{args.realm}.observability.splunkcloud.com"
    )


def effective_obi_version(args: argparse.Namespace) -> str:
    return args.obi_version or OBI_AUDITED_VERSION


def effective_obi_install_dir(args: argparse.Namespace) -> str:
    return args.obi_install_dir or "/usr/local/bin"


def validate_ta_env(value: str) -> None:
    validate_single_line(value, "--ta-collector-env")
    if "=" not in value or value.startswith("="):
        raise ValueError("expected KEY=VALUE")
    key, env_value = value.split("=", 1)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
        raise ValueError("environment variable key must match [A-Za-z_][A-Za-z0-9_]*")
    if SECRET_KEY_PATTERN.search(key) or SECRET_ASSIGNMENT_PATTERN.search(env_value):
        raise ValueError("secret-like TA collector env values must not be rendered; use TA secret modes or runtime environment injection")


def validate_ta_cmd_arg(value: str) -> None:
    validate_single_line(value, "--ta-collector-cmd-arg")
    if SECRET_FLAG_PATTERN.search(value) or SECRET_ASSIGNMENT_PATTERN.search(value):
        raise ValueError("secret-like TA collector command args must not be rendered")


def reject_direct_secret_arguments(argv: list[str]) -> None:
    """Fail before argparse can echo a forbidden secret value in an error."""

    alternatives = {
        "--access-token": "--o11y-token-file",
        "--o11y-token": "--o11y-token-file",
        "--token": "--o11y-token-file",
        "--api-token": "--o11y-token-file",
        "--sf-token": "--o11y-token-file",
        "--hec-token": "--platform-hec-token-file",
        "--platform-hec-token": "--platform-hec-token-file",
        "--ta-access-token": "--o11y-token-file",
        "--splunk-access-token": "--o11y-token-file",
        "--otel-ta-access-token": "--o11y-token-file",
    }
    allowed_secret_control_options = {
        "--o11y-token-file",
        "--platform-hec-token-file",
        "--hec-token-name",
        "--ta-secret-mode",
        "--accept-ta-token-in-conf",
    }
    for argument in argv:
        if not argument.startswith("-"):
            continue
        option = argument.split("=", 1)[0]
        replacement = alternatives.get(option)
        if replacement:
            raise SystemExit(
                f"ERROR: {option} values are not accepted on argv; use {replacement}."
            )
        if (
            SECRET_KEY_PATTERN.search(option)
            and option not in allowed_secret_control_options
        ):
            raise SystemExit(
                f"ERROR: unknown secret-like option {option} is not accepted; use a documented file-backed secret option."
            )


def parse_args() -> argparse.Namespace:
    reject_direct_secret_arguments(sys.argv[1:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--realm", default="")
    parser.add_argument("--render-k8s", action="store_true")
    parser.add_argument("--render-linux", action="store_true")
    parser.add_argument("--render-ta", action="store_true")
    parser.add_argument("--render-platform-hec-helper", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")

    parser.add_argument("--namespace", default="splunk-otel")
    parser.add_argument("--release-name", default="splunk-otel-collector")
    parser.add_argument("--cluster-name", default="")
    parser.add_argument(
        "--distribution",
        choices=("", "eks", "eks/auto-mode", "eks/fargate", "gke", "gke/autopilot", "aks", "openshift"),
        default="",
    )
    parser.add_argument("--cloud-provider", choices=("", "aws", "gcp", "azure"), default="")
    parser.add_argument("--chart-version", default=CHART_AUDITED_VERSION)
    parser.add_argument("--kube-context", default="")
    parser.add_argument("--extra-values-file", action="append", default=[])
    parser.add_argument("--k8s-objects-file", default="")
    parser.add_argument("--accept-cluster-wide-object-rbac", action="store_true")
    parser.add_argument("--o11y-ingest-url", default="")
    parser.add_argument("--o11y-api-url", default="")
    parser.add_argument("--platform-hec-url", default="")
    parser.add_argument("--platform-hec-index", default="k8s_logs")
    parser.add_argument("--platform-metrics-index", default="")
    parser.add_argument("--platform-traces-index", default="")
    parser.add_argument("--platform-otlp-endpoint", default="")
    parser.add_argument("--platform-otlp-protocol", choices=("grpc", "http"), default="grpc")
    bool_arg(parser, "platform-otlp-insecure", False)
    parser.add_argument("--platform-hec-ca-file", default="")
    parser.add_argument("--platform-hec-client-cert-file", default="")
    parser.add_argument("--platform-hec-client-key-file", default="")
    parser.add_argument("--platform-otlp-ca-file", default="")
    parser.add_argument("--platform-otlp-client-cert-file", default="")
    parser.add_argument("--platform-otlp-client-key-file", default="")
    parser.add_argument("--hec-platform", choices=("cloud", "enterprise"), default="cloud")
    parser.add_argument("--hec-token-name", default="splunk_otel_k8s_logs")
    parser.add_argument("--hec-description", default="Managed by splunk-observability-otel-collector-setup")
    parser.add_argument("--hec-default-index", default="")
    parser.add_argument("--hec-allowed-indexes", default="")
    parser.add_argument("--hec-source", default="")
    parser.add_argument("--hec-sourcetype", default="")
    parser.add_argument("--hec-use-ack", choices=("true", "false"), default="false")
    parser.add_argument("--hec-port", default="8088")
    parser.add_argument("--hec-enable-ssl", choices=("true", "false"), default="true")
    parser.add_argument("--hec-splunk-home", default="/opt/splunk")
    parser.add_argument("--hec-app-name", default="splunk_httpinput")
    parser.add_argument("--hec-restart-splunk", choices=("true", "false"), default="true")
    parser.add_argument(
        "--hec-s2s-indexes-validation",
        choices=("disabled", "disabled_for_internal", "enabled_for_all"),
        default="disabled_for_internal",
    )
    parser.add_argument("--eks-cluster-name", default="")
    parser.add_argument("--aws-region", default="")
    parser.add_argument("--priority-class-name", default="")
    parser.add_argument("--gateway-replicas", default="3")
    bool_arg(parser, "agent-enabled", True)
    bool_arg(parser, "gateway-enabled", False)
    bool_arg(parser, "network-explorer-enabled", False)
    bool_arg(parser, "render-priority-class", False)
    bool_arg(parser, "windows-nodes", False)
    bool_arg(parser, "cluster-receiver-enabled", True)
    bool_arg(parser, "agent-host-network", True)
    bool_arg(parser, "platform-persistent-queue-enabled", False)
    parser.add_argument("--platform-persistent-queue-path", default="/var/addon/splunk/exporter_queue")
    bool_arg(parser, "platform-fsync-enabled", False)
    bool_arg(parser, "platform-logs-enabled", False)
    bool_arg(parser, "platform-metrics-enabled", False)
    bool_arg(parser, "platform-traces-enabled", False)
    parser.add_argument("--accept-experimental-platform-traces", action="store_true")
    parser.add_argument("--accept-insecure-platform-hec", action="store_true")
    bool_arg(parser, "target-allocator-enabled", False)
    bool_arg(parser, "k8s-entities-enabled", False)
    bool_arg(parser, "entity-events-enabled", False)
    bool_arg(parser, "fips-enabled", False)
    bool_arg(parser, "instrumentation-installation-job", True)
    parser.add_argument(
        "--instrumentation-kubectl-image-tag",
        default=INSTRUMENTATION_KUBECTL_IMAGE_TAG,
    )

    parser.add_argument("--o11y-token-file", default="")
    parser.add_argument("--platform-hec-token-file", default="")

    parser.add_argument("--execution", choices=("local", "ssh"), default="local")
    parser.add_argument("--linux-host", default="")
    parser.add_argument("--ssh-user", default="")
    parser.add_argument("--ssh-port", default="22")
    parser.add_argument("--ssh-key-file", default="")
    parser.add_argument("--linux-mode", choices=("agent", "gateway"), default="agent")
    parser.add_argument("--memory-mib", default="512")
    parser.add_argument("--listen-interface", default="")
    parser.add_argument("--linux-api-url", default="")
    parser.add_argument("--linux-ingest-url", default="")
    parser.add_argument("--linux-hec-url", default="")
    parser.add_argument("--collector-config", default="")
    parser.add_argument("--linux-health-endpoint", default="")
    parser.add_argument("--service-user", default="")
    parser.add_argument("--service-group", default="")
    bool_arg(parser, "skip-collector-repo", False)
    parser.add_argument("--repo-channel", choices=("primary", "beta", "test"), default="primary")
    parser.add_argument("--deployment-environment", default="")
    parser.add_argument("--service-name", default="")
    parser.add_argument(
        "--instrumentation-mode",
        choices=("none", "preload", "systemd"),
        default="none",
    )
    parser.add_argument("--instrumentation-sdks", default="")
    parser.add_argument("--npm-path", default="")
    parser.add_argument("--otlp-endpoint", default="")
    parser.add_argument("--otlp-endpoint-protocol", default="")
    parser.add_argument("--metrics-exporter", default="")
    parser.add_argument("--logs-exporter", default="")
    parser.add_argument("--instrumentation-version", default=INSTRUMENTATION_AUDITED_VERSION)
    parser.add_argument("--collector-version", default=COLLECTOR_AUDITED_VERSION)
    parser.add_argument("--godebug", default="")
    parser.add_argument("--obi-version", default="")
    parser.add_argument("--obi-install-dir", default="")
    parser.add_argument(
        "--installer-url",
        default=LINUX_INSTALLER_URL,
    )
    parser.add_argument("--installer-sha256", default=LINUX_INSTALLER_SHA256)
    parser.add_argument(
        "--ta-target",
        choices=("deployment-server", "heavy-forwarder", "universal-forwarder"),
        default="deployment-server",
    )
    parser.add_argument("--ta-package-path", action="append", default=[])
    parser.add_argument(
        "--ta-package-flavor",
        choices=("auto", "multi-os", "linux-x86-64", "windows-x86-64"),
        default="auto",
    )
    parser.add_argument("--ta-mode", choices=("agent", "gateway", "agent-to-gateway"), default="agent")
    parser.add_argument("--ta-listen-interface", default="")
    parser.add_argument("--ta-gateway-url", default="")
    parser.add_argument(
        "--ta-collector-log-level",
        choices=("error", "warn", "info", "debug"),
        default="error",
    )
    parser.add_argument("--ta-collector-env", action="append", default=[])
    parser.add_argument("--ta-collector-cmd-arg", action="append", default=[])
    parser.add_argument("--ta-serverclass-whitelist", default="")
    parser.add_argument("--ta-enable-opamp", action="store_true")
    parser.add_argument("--splunk-version", default="")
    parser.add_argument(
        "--ta-secret-mode",
        choices=("placeholder", "inputs-conf", "legacy-file", "environment"),
        default="placeholder",
    )
    parser.add_argument("--accept-ta-token-in-conf", action="store_true")
    parser.add_argument("--ta-fips-required", action="store_true")
    parser.add_argument("--ta-fedramp-required", action="store_true")
    parser.add_argument("--accept-ta-regulated-override", action="store_true")
    parser.add_argument("--ta-allow-unaudited-package", action="store_true")

    bool_arg(parser, "enable-metrics", True)
    bool_arg(parser, "enable-traces", True)
    bool_arg(parser, "enable-logs", False)
    bool_arg(parser, "enable-journald", False)
    parser.add_argument("--metrics-explicit", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--traces-explicit", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--logs-explicit", action="store_true", help=argparse.SUPPRESS)
    bool_arg(parser, "enable-profiling", False)
    bool_arg(parser, "enable-memory-profiling", False)
    bool_arg(parser, "enable-events", False)
    bool_arg(parser, "enable-discovery", False)
    bool_arg(parser, "enable-autoinstrumentation", False)
    bool_arg(parser, "enable-prometheus-autodetect", False)
    bool_arg(parser, "enable-istio-autodetect", False)
    bool_arg(parser, "enable-obi", False)
    bool_arg(parser, "enable-operator-crds", True)
    bool_arg(parser, "enable-certmanager", False)
    bool_arg(parser, "enable-secure-app", False)
    args = parser.parse_args()
    if args.json and not args.dry_run:
        parser.error("--json requires --dry-run")
    try:
        args.k8s_objects = load_k8s_objects_file(args.k8s_objects_file)
    except ValueError as exc:
        parser.error(str(exc))
    if not exact_semver(args.chart_version):
        parser.error(
            "--chart-version must be one exact semantic version; empty values, "
            f"ranges, and moving tags are not supported (audited: {CHART_AUDITED_VERSION})"
        )
    if args.render_k8s and args.chart_version != CHART_AUDITED_VERSION:
        parser.error(
            f"Kubernetes render/apply is audited only for chart {CHART_AUDITED_VERSION}; "
            "a different version requires a new archive, schema, image, and regression audit"
        )
    if not exact_numeric_release(args.collector_version):
        parser.error(
            "--collector-version must be one exact numeric X.Y.Z release; empty values, "
            f"prereleases, ranges, and moving tags are not supported (audited: {COLLECTOR_AUDITED_VERSION})"
        )
    if args.render_linux and args.collector_version != COLLECTOR_AUDITED_VERSION:
        parser.error(
            "executable Linux packets are restricted to the audited "
            f"--collector-version {COLLECTOR_AUDITED_VERSION}; use the reviewed "
            "package-manager/upgrade handoff and update the source ledger and tests "
            "before adopting another release"
        )
    # Catch non-numeric or non-positive --gateway-replicas at parse time so
    # the failure surfaces as a clean argparse-style error instead of an
    # unhandled ValueError deep inside k8s_values() during rendering.
    try:
        replicas = int(args.gateway_replicas)
    except (TypeError, ValueError):
        parser.error(
            f"--gateway-replicas must be an integer (got {args.gateway_replicas!r})"
        )
    if replicas < 1:
        parser.error(
            f"--gateway-replicas must be >= 1 (got {replicas})"
        )
    if str_bool(args.network_explorer_enabled):
        if replicas not in (1, 3):
            parser.error(
                "Network Explorer requires exactly one gateway replica; omit "
                "--gateway-replicas or set it to 1"
            )
        replicas = 1
    args.gateway_replicas = str(replicas)
    if not re.fullmatch(r"[1-9][0-9]*", args.memory_mib):
        parser.error("--memory-mib must be a positive integer")
    if not args.render_k8s and (args.extra_values_file or args.k8s_objects_file):
        parser.error("--extra-values-file and --k8s-objects-file require --render-k8s")
    if not args.render_k8s and args.accept_cluster_wide_object_rbac:
        parser.error("--accept-cluster-wide-object-rbac requires --render-k8s")
    if not args.render_k8s and any(
        (
            bool(args.platform_hec_url),
            bool(args.o11y_ingest_url),
            bool(args.o11y_api_url),
            bool(args.platform_otlp_endpoint),
            args.accept_insecure_platform_hec,
            bool(args.platform_hec_ca_file),
            bool(args.platform_hec_client_cert_file),
            bool(args.platform_hec_client_key_file),
            str_bool(args.platform_otlp_insecure),
            bool(args.platform_otlp_ca_file),
            bool(args.platform_otlp_client_cert_file),
            bool(args.platform_otlp_client_key_file),
            str_bool(args.platform_persistent_queue_enabled),
            str_bool(args.platform_fsync_enabled),
            str_bool(args.platform_logs_enabled),
            str_bool(args.platform_metrics_enabled),
            str_bool(args.platform_traces_enabled),
            str_bool(args.fips_enabled),
        )
    ):
        parser.error("Splunk Platform OTLP/queue/signal/FIPS options require --render-k8s")
    if not args.render_linux and any(
        (
            args.execution != "local",
            bool(args.linux_host),
            bool(args.ssh_user),
            args.ssh_port != "22",
            bool(args.ssh_key_file),
            args.linux_mode != "agent",
            args.memory_mib != "512",
            bool(args.listen_interface),
            bool(args.linux_api_url),
            bool(args.linux_ingest_url),
            bool(args.collector_config),
            bool(args.linux_health_endpoint),
            bool(args.service_user),
            bool(args.service_group),
            str_bool(args.skip_collector_repo),
            args.repo_channel != "primary",
            bool(args.service_name),
            args.instrumentation_mode != "none",
            bool(args.instrumentation_sdks),
            bool(args.npm_path),
            bool(args.otlp_endpoint),
            bool(args.otlp_endpoint_protocol),
            bool(args.metrics_exporter),
            bool(args.logs_exporter),
            str_bool(args.enable_memory_profiling),
            args.instrumentation_version != INSTRUMENTATION_AUDITED_VERSION,
            args.collector_version != COLLECTOR_AUDITED_VERSION,
            bool(args.godebug),
            bool(args.obi_version),
            bool(args.obi_install_dir),
            args.installer_url != LINUX_INSTALLER_URL,
            args.installer_sha256.lower() != LINUX_INSTALLER_SHA256,
        )
    ):
        parser.error("Linux installer/runtime options require --render-linux")
    if not args.render_ta and any(
        (
            bool(args.ta_package_path),
            args.ta_target != "deployment-server",
            args.ta_package_flavor != "auto",
            args.ta_mode != "agent",
            bool(args.ta_listen_interface),
            bool(args.ta_gateway_url),
            args.ta_collector_log_level != "error",
            bool(args.ta_collector_env),
            bool(args.ta_collector_cmd_arg),
            bool(args.ta_serverclass_whitelist),
            args.ta_enable_opamp,
            bool(args.splunk_version),
            args.ta_secret_mode != "placeholder",
            args.accept_ta_token_in_conf,
            args.ta_fips_required,
            args.ta_fedramp_required,
            args.accept_ta_regulated_override,
            args.ta_allow_unaudited_package,
        )
    ):
        parser.error("Technical Add-on options require --render-ta")
    expected_provider = {
        "eks": "aws",
        "eks/auto-mode": "aws",
        "eks/fargate": "aws",
        "gke": "gcp",
        "gke/autopilot": "gcp",
        "aks": "azure",
    }.get(args.distribution)
    if expected_provider and args.cloud_provider and args.cloud_provider != expected_provider:
        parser.error(
            f"--distribution {args.distribution} is incompatible with --cloud-provider {args.cloud_provider}; "
            f"expected {expected_provider}"
        )
    if bool(args.eks_cluster_name) != bool(args.aws_region):
        parser.error("--eks-cluster-name and --aws-region must be supplied together")
    if args.eks_cluster_name and args.distribution not in {"eks", "eks/auto-mode", "eks/fargate"}:
        parser.error("--eks-cluster-name requires an EKS --distribution")
    if str_bool(args.render_priority_class) and not args.priority_class_name:
        parser.error("--render-priority-class requires --priority-class-name")
    if args.installer_sha256 and not re.fullmatch(r"[0-9a-fA-F]{64}", args.installer_sha256):
        parser.error("--installer-sha256 must be exactly 64 hexadecimal characters")
    if not args.installer_sha256:
        parser.error("--installer-sha256 is required; unverified installer execution is not supported")
    if args.render_linux and args.installer_sha256.lower() != LINUX_INSTALLER_SHA256:
        parser.error(
            "executable Linux packets require the audited installer SHA-256 "
            f"{LINUX_INSTALLER_SHA256}; an alternate HTTPS mirror is allowed only "
            "when it serves those exact reviewed bytes"
        )
    if not re.fullmatch(r"v1\.\d+\.\d+", args.instrumentation_kubectl_image_tag):
        parser.error("--instrumentation-kubectl-image-tag must look like v1.MINOR.PATCH")
    if args.render_k8s and args.instrumentation_kubectl_image_tag != INSTRUMENTATION_KUBECTL_IMAGE_TAG:
        parser.error(
            "Kubernetes instrumentation Job image is digest-audited only for "
            f"kubectl {INSTRUMENTATION_KUBECTL_IMAGE_TAG}; custom tags require a new digest audit"
        )
    single_line_fields = (
        "realm",
        "namespace",
        "release_name",
        "cluster_name",
        "distribution",
        "cloud_provider",
        "platform_hec_url",
        "platform_hec_index",
        "platform_metrics_index",
        "platform_traces_index",
        "platform_otlp_endpoint",
        "listen_interface",
        "ta_listen_interface",
        "ta_gateway_url",
    )
    for field in single_line_fields:
        try:
            validate_single_line(str(getattr(args, field)), f"--{field.replace('_', '-')}")
        except ValueError as exc:
            parser.error(str(exc))
    if args.ta_listen_interface and not valid_listen_interface(args.ta_listen_interface):
        parser.error("--ta-listen-interface must be localhost or an IPv4/IPv6 address")
    if args.listen_interface and not valid_listen_interface(args.listen_interface):
        parser.error("--listen-interface must be localhost or an IPv4/IPv6 address")
    for field in (
        "kube_context",
        "o11y_ingest_url",
        "o11y_api_url",
        "platform_otlp_endpoint",
        "linux_host",
        "ssh_user",
        "ssh_port",
        "memory_mib",
        "linux_api_url",
        "linux_ingest_url",
        "linux_hec_url",
        "collector_config",
        "linux_health_endpoint",
        "service_user",
        "service_group",
        "deployment_environment",
        "service_name",
        "instrumentation_sdks",
        "npm_path",
        "otlp_endpoint",
        "otlp_endpoint_protocol",
        "metrics_exporter",
        "logs_exporter",
        "instrumentation_version",
        "collector_version",
        "godebug",
        "obi_version",
        "obi_install_dir",
        "installer_url",
    ):
        try:
            validate_single_line(str(getattr(args, field)), f"--{field.replace('_', '-')}")
        except ValueError as exc:
            parser.error(str(exc))
    if not valid_http_url(args.installer_url, https_only=True):
        parser.error("--installer-url must be a credential-free HTTPS URL without query or fragment")
    for label, url in (
        ("--o11y-ingest-url", args.o11y_ingest_url),
        ("--o11y-api-url", args.o11y_api_url),
    ):
        if url and not valid_http_url(url, https_only=True):
            parser.error(f"{label} must be a credential-free HTTPS URL without query or fragment")
    for label, field in (
        ("--api-url", "linux_api_url"),
        ("--ingest-url", "linux_ingest_url"),
    ):
        url = str(getattr(args, field))
        if url and not valid_linux_env_url(url):
            parser.error(
                f"{label} must be a credential-free HTTPS URL without whitespace, quotes, "
                "backslashes, query, or fragment"
            )
        if url:
            setattr(args, field, url.rstrip("/"))
    if args.platform_hec_url:
        if not valid_http_url(args.platform_hec_url):
            parser.error("--platform-hec-url must be a credential-free HTTP(S) URL without query or fragment")
        if args.platform_hec_url.lower().startswith("http://") and not args.accept_insecure_platform_hec:
            parser.error("plaintext Platform HEC requires --accept-insecure-platform-hec")
        if not args.platform_hec_url.rstrip("/").endswith("/services/collector/event"):
            parser.error("--platform-hec-url must end in /services/collector/event")
    for label, index_name in (
        ("--platform-hec-index", args.platform_hec_index),
        ("--platform-metrics-index", args.platform_metrics_index),
        ("--platform-traces-index", args.platform_traces_index),
        ("--hec-default-index", args.hec_default_index),
    ):
        if index_name and not valid_splunk_index(index_name):
            parser.error(
                f"{label} must match [_A-Za-z0-9][A-Za-z0-9_.-]*"
            )
    if args.hec_allowed_indexes:
        allowed_indexes = [value.strip() for value in args.hec_allowed_indexes.split(",")]
        if any(not value or not valid_splunk_index(value) for value in allowed_indexes):
            parser.error(
                "--hec-allowed-indexes must be a comma-separated list of valid Splunk index names"
            )
    if args.linux_health_endpoint and not valid_http_url(args.linux_health_endpoint):
        parser.error("--linux-health-endpoint must be a credential-free HTTP(S) URL without query or fragment")
    for label, account_name in (
        ("--service-user", args.service_user),
        ("--service-group", args.service_group),
    ):
        if account_name and not valid_linux_account_name(account_name):
            parser.error(
                f"{label} must be a lowercase Linux account name (1-32 characters; "
                "letters, digits, underscore, hyphen, and an optional trailing $)"
            )
    if args.realm and not re.fullmatch(r"[a-z][a-z0-9-]{1,31}", args.realm):
        parser.error("--realm must be a lowercase Splunk realm identifier")
    for label, value in (
        ("--deployment-environment", args.deployment_environment),
        ("--service-name", args.service_name),
    ):
        if value and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,254}", value):
            parser.error(
                f"{label} contains characters that are unsafe in the upstream systemd/env-file templates"
            )
    if args.instrumentation_sdks:
        sdks = args.instrumentation_sdks.split(",")
        if not sdks or len(sdks) != len(set(sdks)) or any(
            sdk not in {"java", "node", "dotnet"} for sdk in sdks
        ):
            parser.error(
                "--instrumentation-sdks must be a unique comma-separated subset of java,node,dotnet"
            )
    exporter_re = r"[a-z][a-z0-9_.-]*"
    if args.metrics_exporter:
        exporters = args.metrics_exporter.split(",")
        if (
            any(not re.fullmatch(exporter_re, exporter) for exporter in exporters)
            or len(exporters) != len(set(exporters))
            or ("none" in exporters and len(exporters) != 1)
        ):
            parser.error(
                "--metrics-exporter must be 'none' or a unique comma-separated list of safe exporter identifiers"
            )
    if args.logs_exporter and not re.fullmatch(exporter_re, args.logs_exporter):
        parser.error("--logs-exporter must be one safe exporter identifier such as otlp or none")
    if args.godebug and not re.fullmatch(
        r"[A-Za-z0-9_]+=[A-Za-z0-9_.+-]+(?:,[A-Za-z0-9_]+=[A-Za-z0-9_.+-]+)*",
        args.godebug,
    ):
        parser.error("--godebug must be a comma-separated KEY=VALUE list without whitespace or quotes")
    if args.collector_config and not normalized_absolute_linux_path(args.collector_config):
        parser.error("--collector-config must be a normalized absolute target-host Linux path")
    if args.npm_path and not normalized_absolute_linux_path(args.npm_path):
        parser.error("--npm-path must be a normalized absolute target-host Linux path")
    if args.obi_install_dir and not normalized_absolute_linux_path(args.obi_install_dir):
        parser.error("--obi-install-dir must be a normalized absolute target-host Linux path")
    if args.render_linux and args.execution == "ssh":
        if args.linux_host and not re.fullmatch(r"[A-Za-z0-9._:-]+", args.linux_host):
            parser.error("--linux-host contains unsupported characters")
        if args.ssh_user and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", args.ssh_user):
            parser.error("--ssh-user contains unsupported characters")
        if not args.ssh_port.isdigit() or not 1 <= int(args.ssh_port) <= 65535:
            parser.error("--ssh-port must be an integer from 1 through 65535")
    if args.linux_hec_url:
        parser.error(
            "--linux-hec-url/--hec-url is deprecated upstream and scheduled for removal; "
            "use a reviewed --collector-config or the Splunk Platform/Universal Forwarder handoff"
        )
    if str_bool(args.windows_nodes) and str_bool(args.enable_obi):
        parser.error("--enable-obi is Linux-only and cannot be combined with --windows-nodes")
    if str_bool(args.windows_nodes) and str_bool(args.enable_discovery):
        parser.error("--enable-discovery is Linux-only and cannot be combined with --windows-nodes")
    if args.render_k8s and args.distribution == "eks/fargate" and str_bool(args.windows_nodes):
        parser.error("EKS Fargate cannot schedule Windows Collector containers")
    if args.render_k8s and args.distribution == "eks/fargate" and str_bool(args.enable_obi):
        parser.error("EKS Fargate does not support the OBI DaemonSet")
    if args.render_k8s and args.distribution == "gke/autopilot" and str_bool(args.enable_obi):
        parser.error("GKE Autopilot does not support the privileged/hostPath OBI DaemonSet")
    if args.render_k8s and args.distribution == "gke/autopilot" and str_bool(args.windows_nodes):
        parser.error("GKE Autopilot does not support this chart's Windows collector mode")
    if args.render_k8s and args.distribution == "openshift" and str_bool(args.enable_obi):
        parser.error(
            "OpenShift OBI requires an explicit SCC handoff; use splunk-observability-k8s-auto-instrumentation-setup"
        )
    if not args.render_k8s:
        k8s_only_enabled = [
            name
            for enabled, name in (
                (str_bool(args.enable_events), "--enable-events"),
                (str_bool(args.enable_journald), "--enable-journald"),
                (str_bool(args.k8s_entities_enabled), "--k8s-entities-enabled"),
                (str_bool(args.entity_events_enabled), "--entity-events-enabled"),
                (str_bool(args.target_allocator_enabled), "--target-allocator-enabled"),
                (str_bool(args.enable_prometheus_autodetect), "--enable-prometheus-autodetect"),
                (str_bool(args.enable_istio_autodetect), "--enable-istio-autodetect"),
                (str_bool(args.enable_certmanager), "--enable-certmanager"),
                (str_bool(args.enable_secure_app), "--enable-secure-app"),
                (str_bool(args.gateway_enabled), "--gateway"),
                (str_bool(args.network_explorer_enabled), "--enable-network-explorer"),
                (str_bool(args.windows_nodes), "--windows-nodes"),
                (str_bool(args.render_priority_class), "--render-priority-class"),
                (not str_bool(args.agent_enabled), "--disable-agent"),
                (not str_bool(args.cluster_receiver_enabled), "--disable-cluster-receiver"),
            )
            if enabled
        ]
        if k8s_only_enabled:
            parser.error(
                "Kubernetes-only options require --render-k8s: " + ", ".join(k8s_only_enabled)
            )
    if args.render_ta:
        unsupported_ta_signal_disables = [
            name
            for explicit, enabled, name in (
                (args.metrics_explicit, str_bool(args.enable_metrics), "--disable-metrics"),
                (args.traces_explicit, str_bool(args.enable_traces), "--disable-traces"),
                (args.logs_explicit, str_bool(args.enable_logs), "--disable-logs"),
            )
            if explicit and not enabled
        ]
        if unsupported_ta_signal_disables:
            parser.error(
                "the audited TA packages use an all-signal Collector config and cannot honor: "
                + ", ".join(unsupported_ta_signal_disables)
            )
    if args.render_ta and not args.render_k8s and not args.render_linux:
        unsupported_ta_flags = [
            name
            for enabled, name in (
                (str_bool(args.enable_profiling), "--enable-profiling"),
                (str_bool(args.enable_memory_profiling), "--enable-memory-profiling"),
                (str_bool(args.enable_discovery), "--enable-discovery"),
                (str_bool(args.enable_autoinstrumentation), "--enable-autoinstrumentation"),
                (str_bool(args.enable_obi), "--enable-obi"),
                (bool(args.deployment_environment), "--deployment-environment"),
                (bool(args.service_name), "--service-name"),
                (args.instrumentation_mode != "none", "--instrumentation-mode"),
            )
            if enabled
        ]
        if unsupported_ta_flags:
            parser.error(
                "these signal/runtime options are not implemented by the TA renderer: "
                + ", ".join(unsupported_ta_flags)
            )
    if str_bool(args.windows_nodes) and str_bool(args.enable_autoinstrumentation):
        parser.error(
            "the Windows-node Helm release cannot own Kubernetes auto-instrumentation; "
            "use the Linux release or splunk-observability-k8s-auto-instrumentation-setup"
        )
    if args.render_linux and str_bool(args.fips_enabled):
        parser.error(
            "--fips-enabled selects the Kubernetes FIPS image only; the Linux installer does not select a FIPS package. "
            "Use the documented Linux FIPS artifact handoff in a separate reviewed workflow"
        )
    if str_bool(args.fips_enabled) and any(
        (str_bool(args.enable_discovery), str_bool(args.enable_obi))
    ):
        parser.error("FIPS mode cannot be combined with discovery/Smart Agent receivers or OBI")
    if str_bool(args.enable_certmanager) and not str_bool(args.enable_autoinstrumentation):
        parser.error("--enable-certmanager requires --enable-autoinstrumentation")
    if args.render_k8s and str_bool(args.enable_secure_app) and not str_bool(args.enable_traces):
        parser.error("--enable-secure-app requires the Splunk Observability traces pipeline")
    if (
        args.render_k8s
        and str_bool(args.enable_autoinstrumentation)
        and (str_bool(args.enable_traces) or platform_traces_enabled(args))
        and not args.deployment_environment
    ):
        parser.error(
            "Kubernetes auto-instrumentation with traces requires a nonempty --deployment-environment"
        )
    if str_bool(args.entity_events_enabled) and not str_bool(args.enable_metrics):
        parser.error("--entity-events-enabled requires the Observability metrics pipeline")
    if str_bool(args.platform_traces_enabled) and not args.accept_experimental_platform_traces:
        parser.error(
            "Splunk Platform trace export conflicts with current product support documentation; "
            "pass --accept-experimental-platform-traces only for a reviewed test deployment"
        )
    for label, cert_path, key_path in (
        ("HEC", args.platform_hec_client_cert_file, args.platform_hec_client_key_file),
        ("OTLP", args.platform_otlp_client_cert_file, args.platform_otlp_client_key_file),
    ):
        if bool(cert_path) != bool(key_path):
            parser.error(f"{label} mTLS requires both the client certificate and private-key file")
    if str_bool(args.platform_metrics_enabled) and not platform_metrics_enabled(args):
        parser.error(
            "--platform-metrics-enabled requires --platform-hec-url, --platform-hec-token-file "
            "or the HEC helper, and --platform-metrics-index"
        )
    if str_bool(args.platform_traces_enabled) and not platform_traces_enabled(args):
        parser.error(
            "--platform-traces-enabled requires --platform-hec-url, --platform-hec-token-file "
            "or the HEC helper, and --platform-traces-index"
        )
    if str_bool(args.platform_traces_enabled) and not (
        platform_metrics_enabled(args) or platform_logs_enabled(args)
    ):
        parser.error(
            "chart 0.154.0 does not accept a traces-only splunkPlatform destination; "
            "enable a reviewed Platform metrics or logs pipeline as well"
        )
    if args.platform_otlp_endpoint:
        if args.platform_otlp_protocol == "http" and not re.match(
            r"^https?://", args.platform_otlp_endpoint, re.IGNORECASE
        ):
            parser.error("HTTP --platform-otlp-endpoint must be an http:// or https:// URL")
        if args.platform_otlp_protocol == "http" and not valid_http_url(args.platform_otlp_endpoint):
            parser.error(
                "HTTP --platform-otlp-endpoint must be credential-free and contain no query or fragment"
            )
        if args.platform_otlp_protocol == "grpc" and re.match(
            r"^https?://", args.platform_otlp_endpoint, re.IGNORECASE
        ):
            parser.error("gRPC --platform-otlp-endpoint must be HOST:PORT without a URL scheme")
        if args.platform_otlp_protocol == "grpc" and not valid_host_port(args.platform_otlp_endpoint):
            parser.error("gRPC --platform-otlp-endpoint must be a valid HOST:PORT")
        if (
            args.platform_otlp_protocol == "http"
            and args.platform_otlp_endpoint.lower().startswith("http://")
            and not str_bool(args.platform_otlp_insecure)
        ):
            parser.error("plaintext HTTP OTLP requires --platform-otlp-insecure true")
        if (
            args.platform_otlp_protocol == "http"
            and args.platform_otlp_endpoint.lower().startswith("https://")
            and str_bool(args.platform_otlp_insecure)
        ):
            parser.error("HTTPS OTLP cannot be combined with --platform-otlp-insecure true")
        if str_bool(args.platform_otlp_insecure) and any(
            (
                args.platform_otlp_ca_file,
                args.platform_otlp_client_cert_file,
                args.platform_otlp_client_key_file,
            )
        ):
            parser.error("plaintext OTLP cannot be combined with CA or mTLS files")
    if args.otlp_endpoint and not valid_host_port(args.otlp_endpoint):
        parser.error("--otlp-endpoint must be a valid HOST:PORT")
    if args.render_linux and str_bool(args.enable_autoinstrumentation) and args.instrumentation_mode == "none":
        parser.error("Linux auto-instrumentation requires --instrumentation-mode preload or systemd")
    if args.render_linux and str_bool(args.enable_autoinstrumentation):
        if not str_bool(args.enable_logs) and args.logs_exporter not in ("", "none"):
            parser.error("--disable-logs cannot be combined with an active --logs-exporter")
        if str_bool(args.enable_logs) and args.logs_exporter == "none":
            parser.error("--enable-logs cannot be combined with --logs-exporter none")
        if not str_bool(args.enable_metrics) and args.metrics_exporter not in ("", "none"):
            parser.error("--disable-metrics cannot be combined with an active --metrics-exporter")
        if str_bool(args.enable_metrics) and args.metrics_exporter == "none":
            parser.error("--enable-metrics cannot be combined with --metrics-exporter none")
    if args.render_linux and not str_bool(args.enable_autoinstrumentation) and any(
        (
            bool(args.deployment_environment),
            bool(args.service_name),
            args.instrumentation_mode != "none",
            bool(args.instrumentation_sdks),
            bool(args.npm_path),
            bool(args.otlp_endpoint),
            bool(args.otlp_endpoint_protocol),
            bool(args.metrics_exporter),
            bool(args.logs_exporter),
            args.instrumentation_version != INSTRUMENTATION_AUDITED_VERSION,
        )
    ):
        parser.error("Linux SDK instrumentation options require --enable-autoinstrumentation")
    if args.render_linux and not str_bool(args.enable_obi) and any(
        (bool(args.obi_version), bool(args.obi_install_dir))
    ):
        parser.error("--obi-version and --obi-install-dir require --enable-obi")
    if args.render_linux and str_bool(args.enable_obi):
        obi_version = effective_obi_version(args)
        if not exact_semver(obi_version.removeprefix("v")):
            parser.error(
                "Linux OBI requires one exact semantic --obi-version; empty input uses "
                f"the audited {OBI_AUDITED_VERSION}, while ranges and moving tags are rejected"
            )
        if obi_version.removeprefix("v") != OBI_AUDITED_VERSION.removeprefix("v"):
            parser.error(
                "executable Linux packets are restricted to the audited "
                f"--obi-version {OBI_AUDITED_VERSION}; update the source ledger, "
                "checksum contract, and tests before adopting another release"
            )
    if args.render_linux and str_bool(args.enable_autoinstrumentation) and not exact_numeric_release(
        args.instrumentation_version
    ):
        parser.error(
            "Linux auto-instrumentation requires one exact semantic "
            "--instrumentation-version; empty values, ranges, and moving tags are not supported; "
            f"the audited release is {INSTRUMENTATION_AUDITED_VERSION}"
        )
    if (
        args.render_linux
        and str_bool(args.enable_autoinstrumentation)
        and args.instrumentation_version != INSTRUMENTATION_AUDITED_VERSION
    ):
        parser.error(
            "executable Linux packets are restricted to the audited "
            f"--instrumentation-version {INSTRUMENTATION_AUDITED_VERSION}; use the "
            "reviewed upgrade handoff and update the source ledger and tests before "
            "adopting another release"
        )
    if args.render_linux and args.repo_channel == "test":
        parser.error(
            "--repo-channel test disables upstream package signature verification and is not supported"
        )
    if args.render_linux and args.collector_config and not args.linux_health_endpoint:
        parser.error(
            "--collector-config requires --linux-health-endpoint because a custom config may move or disable health_check"
        )
    if args.render_linux and any(
        (str_bool(args.enable_profiling), str_bool(args.enable_memory_profiling))
    ) and not str_bool(args.enable_autoinstrumentation):
        parser.error(
            "Linux profiling options require auto-instrumentation; a Collector config alone does not activate SDK profiling"
        )
    if args.render_linux and str_bool(args.enable_secure_app) and not args.render_k8s:
        parser.error("--enable-secure-app is implemented only by the Kubernetes chart path")
    if args.render_linux and str_bool(args.enable_autoinstrumentation) and not str_bool(args.enable_traces):
        parser.error(
            "the Linux installer cannot disable auto-instrumented traces independently; "
            "remove --disable-traces or disable auto-instrumentation; a custom Collector config does not control SDK export"
        )
    if args.render_linux and not args.collector_config and not str_bool(args.enable_metrics):
        parser.error(
            "the upstream Linux default config always includes host/internal metrics pipelines; "
            "--disable-metrics requires a reviewed --collector-config"
        )
    if args.render_linux and not args.collector_config and not str_bool(args.enable_traces):
        parser.error(
            "the upstream Linux default config always includes a trace pipeline; "
            "--disable-traces requires a reviewed --collector-config"
        )
    if (args.render_linux or args.render_ta) and not args.realm:
        parser.error("--realm is required for Linux and Technical Add-on rendering")
    if args.render_k8s and any(
        (str_bool(args.k8s_entities_enabled), str_bool(args.entity_events_enabled))
    ) and not observability_destination_enabled(args):
        parser.error(
            "Kubernetes entities require an Observability metrics, traces, profiling, or Secure Application destination"
        )
    if (
        args.render_k8s
        and str_bool(args.enable_events)
        and not (observability_destination_enabled(args) or platform_logs_enabled(args))
    ):
        parser.error(
            "Kubernetes events/entities require either an Observability destination or an effective Splunk Platform logs destination"
        )
    if args.render_k8s and args.k8s_objects and not (
        observability_destination_enabled(args) or platform_logs_enabled(args)
    ):
        parser.error(
            "Kubernetes object collection requires either an Observability destination or an effective Splunk Platform logs destination"
        )
    if args.render_k8s and args.k8s_objects and not args.accept_cluster_wide_object_rbac:
        parser.error(
            "--k8s-objects-file requires --accept-cluster-wide-object-rbac because the chart grants get/list/watch through a ClusterRole"
        )
    if args.render_k8s and observability_destination_enabled(args) and not args.realm:
        parser.error("--realm is required when a Splunk Observability destination is enabled")
    if args.render_k8s and str_bool(args.network_explorer_enabled):
        if not str_bool(args.enable_metrics):
            parser.error("Network Explorer requires the Observability metrics destination")
        if str_bool(args.windows_nodes):
            parser.error("Network Explorer's eBPF chart requires Linux nodes")
        if args.distribution in {"eks/fargate", "gke/autopilot"}:
            parser.error(
                "Network Explorer's eBPF DaemonSet is not supported by this serverless/autopilot topology"
            )
        if args.distribution == "openshift":
            parser.error(
                "Network Explorer on OpenShift requires the documented SELinux SPC policy, "
                "privileged/anyuid SCC grants, service accounts, and a reviewed kernel image; "
                "use the explicit OpenShift handoff instead of this generic profile"
            )
    if args.render_k8s and not (
        observability_destination_enabled(args) or platform_destination_enabled(args)
    ):
        parser.error(
            "Kubernetes rendering requires at least one effective Splunk Observability or Splunk Platform destination"
        )
    effective_agent = str_bool(args.agent_enabled) and args.distribution != "eks/fargate"
    effective_gateway = effective_gateway_enabled(args)
    dns_label = re.compile(r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$")
    if args.render_k8s and (
        len(args.release_name) > 53 or not dns_label.fullmatch(args.release_name)
    ):
        parser.error("--release-name must be a lowercase DNS label no longer than 53 characters")
    if args.render_k8s and (
        len(args.namespace) > 63 or not dns_label.fullmatch(args.namespace)
    ):
        parser.error("--namespace must be a lowercase DNS label no longer than 63 characters")
    if args.render_k8s and args.priority_class_name and (
        len(args.priority_class_name) > 253
        or not re.fullmatch(
            r"[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?", args.priority_class_name
        )
    ):
        parser.error("--priority-class-name must be a lowercase DNS subdomain")
    collector_resource_name = helm_fullname(args.release_name, CHART_NAME)
    # Several chart templates append suffixes without another truncation.  The
    # tightest enabled core object is the cluster-receiver ConfigMap/PDB suffix
    # (26 characters); the external-secret validation hook is next (16).
    collector_name_limit = 37 if effective_cluster_receiver_enabled(args) else 47
    if len(collector_resource_name) > collector_name_limit:
        parser.error(
            "--release-name produces chart resource names longer than Kubernetes' 63-character limit"
        )
    if (
        str_bool(args.enable_autoinstrumentation)
        and str_bool(args.instrumentation_installation_job)
        and len(f"{collector_resource_name}-inst-hook") > 63
    ):
        parser.error("--release-name is too long for the instrumentation installation Job name")
    if args.render_k8s and not effective_agent and any(
        (
            str_bool(args.enable_discovery),
            str_bool(args.enable_prometheus_autodetect),
            str_bool(args.enable_istio_autodetect),
        )
    ):
        parser.error("Kubernetes discovery and autodetect require the agent DaemonSet")
    if args.render_k8s and any(
        (
            str_bool(args.enable_discovery),
            str_bool(args.enable_prometheus_autodetect),
            str_bool(args.enable_istio_autodetect),
        )
    ) and not (str_bool(args.enable_metrics) or platform_metrics_enabled(args)):
        parser.error(
            "Kubernetes discovery and autodetect require an effective Observability or Splunk Platform metrics pipeline"
        )
    if args.render_k8s and any(
        (
            str_bool(args.enable_events),
            str_bool(args.k8s_entities_enabled),
            str_bool(args.entity_events_enabled),
            bool(args.k8s_objects),
        )
    ) and not str_bool(args.cluster_receiver_enabled):
        parser.error("Kubernetes events, objects, and entity features require the cluster receiver")
    if args.render_k8s and str_bool(args.target_allocator_enabled) and not (
        effective_agent
        and (str_bool(args.enable_metrics) or platform_metrics_enabled(args))
    ):
        parser.error(
            "Target Allocator requires the agent DaemonSet and an effective Observability or Splunk Platform metrics pipeline"
        )
    if args.render_k8s and str_bool(args.enable_obi) and not (
        effective_agent and effective_agent_host_network(args)
    ):
        parser.error("OBI requires the agent DaemonSet with agent.hostNetwork=true")
    if args.render_k8s and str_bool(args.enable_obi) and not args.cluster_name:
        parser.error("Kubernetes OBI requires an explicit --cluster-name")
    if args.render_k8s and str_bool(args.enable_obi) and not (
        str_bool(args.enable_traces) or platform_traces_enabled(args)
    ):
        parser.error("Kubernetes OBI requires an effective trace destination")
    if args.render_k8s and any(
        (
            str_bool(args.enable_profiling),
            str_bool(args.enable_secure_app),
            str_bool(args.enable_autoinstrumentation),
        )
    ) and not (effective_agent or effective_gateway):
        parser.error("Profiling, Secure Application, and auto-instrumentation require an agent or gateway ingress workload")
    if args.render_k8s and str_bool(args.enable_autoinstrumentation) and not (
        str_bool(args.enable_traces) or platform_traces_enabled(args)
    ):
        parser.error("Kubernetes auto-instrumentation requires an enabled trace destination")
    persistence_requested = str_bool(args.platform_persistent_queue_enabled) or str_bool(
        args.platform_fsync_enabled
    )
    if args.render_k8s and persistence_requested and not normalized_absolute_linux_path(
        args.platform_persistent_queue_path
    ):
        parser.error(
            "--platform-persistent-queue-path must be a normalized absolute Linux path "
            "below / using only letters, digits, dot, underscore, hyphen, and slash"
        )
    if args.render_k8s and persistence_requested and not platform_destination_enabled(args):
        parser.error("Platform persistent queue/fsync requires an effective Splunk Platform destination")
    if args.render_k8s and persistence_requested and not platform_logs_enabled(args):
        parser.error(
            "chart 0.154.0 mounts Platform persistent queue storage only when Platform logs are enabled"
        )
    if args.render_k8s and str_bool(args.platform_fsync_enabled) and not str_bool(
        args.platform_persistent_queue_enabled
    ):
        parser.error("--platform-fsync-enabled requires --platform-persistent-queue-enabled")
    if args.render_k8s and persistence_requested and (
        not effective_agent
        or effective_gateway
        or args.distribution in {"eks/fargate", "gke/autopilot"}
        or str_bool(args.windows_nodes)
    ):
        parser.error(
            "Platform persistent queue/fsync requires a non-Autopilot Linux agent DaemonSet "
            "with the gateway disabled; chart 0.154.0 does not persist gateway exports"
        )
    if args.render_k8s and not any(
        (effective_agent, effective_gateway, effective_cluster_receiver_enabled(args))
    ):
        parser.error("Kubernetes rendering requires at least one agent, gateway, or cluster-receiver workload")
    if args.render_k8s and str_bool(args.enable_traces) and not (effective_agent or effective_gateway):
        parser.error("Kubernetes trace ingestion requires an agent or gateway workload")
    if args.render_k8s and str_bool(args.platform_logs_enabled) and not platform_logs_enabled(args):
        parser.error(
            "--platform-logs-enabled requires a complete Splunk Platform HEC destination or "
            "--platform-otlp-endpoint"
        )
    if args.render_k8s and str_bool(args.enable_logs):
        if not platform_logs_enabled(args):
            parser.error(
                "--enable-logs requires a complete Splunk Platform HEC destination or "
                "--platform-otlp-endpoint"
            )
        if not effective_agent:
            parser.error(
                "container-log collection requires the agent DaemonSet; EKS Fargate and agent-disabled "
                "topologies need a separate supported log router"
            )
    if args.render_k8s and str_bool(args.enable_journald):
        if not platform_logs_enabled(args):
            parser.error(
                "--enable-journald requires a complete Splunk Platform HEC destination or "
                "--platform-otlp-endpoint"
            )
        if (
            not effective_agent
            or str_bool(args.windows_nodes)
            or args.distribution in {"eks/fargate", "gke/autopilot"}
        ):
            parser.error(
                "journald collection requires a non-Autopilot Linux agent DaemonSet"
            )
    if args.platform_otlp_endpoint and not platform_otlp_logs_enabled(args):
        parser.error(
            "--platform-otlp-endpoint is only effective with --platform-logs-enabled, "
            "--enable-logs, or --enable-journald"
        )
    if any(
        (
            args.platform_otlp_ca_file,
            args.platform_otlp_client_cert_file,
            args.platform_otlp_client_key_file,
        )
    ) and not platform_otlp_logs_enabled(args):
        parser.error("Platform OTLP TLS files require an effective OTLP log destination")
    if str_bool(args.platform_otlp_insecure) and not args.platform_otlp_endpoint:
        parser.error("--platform-otlp-insecure requires --platform-otlp-endpoint")
    effective_hec_destination = any(
        (
            platform_hec_logs_enabled(args),
            platform_metrics_enabled(args),
            platform_traces_enabled(args),
        )
    )
    if args.platform_hec_url.lower().startswith("http://") and any(
        (
            args.platform_hec_ca_file,
            args.platform_hec_client_cert_file,
            args.platform_hec_client_key_file,
        )
    ):
        parser.error("plaintext Platform HEC cannot be combined with CA or mTLS files")
    if (
        args.render_k8s
        and args.platform_hec_url
        and not effective_hec_destination
        and not args.render_platform_hec_helper
    ):
        parser.error("--platform-hec-url was supplied without an effective HEC destination")
    if any(
        (
            args.platform_hec_ca_file,
            args.platform_hec_client_cert_file,
            args.platform_hec_client_key_file,
        )
    ) and not effective_hec_destination:
        parser.error("Platform HEC TLS files require an effective HEC destination")
    if args.platform_hec_token_file and not effective_hec_destination and not args.render_platform_hec_helper:
        parser.error("--platform-hec-token-file was supplied without an effective HEC destination")
    if args.ta_mode == "agent-to-gateway" and not args.ta_gateway_url:
        parser.error("--ta-gateway-url is required when --ta-mode agent-to-gateway")
    if args.ta_mode == "agent-to-gateway" and args.ta_enable_opamp:
        parser.error(
            "--ta-enable-opamp is not compatible with the generated agent-to-gateway config, which has no OpAMP extension"
        )
    if args.ta_mode == "agent-to-gateway" and not valid_host_port(args.ta_gateway_url):
        parser.error("--ta-gateway-url must be a TLS OTLP HOST:PORT endpoint without a URL scheme")
    for env_value in args.ta_collector_env:
        try:
            validate_ta_env(env_value)
        except ValueError as exc:
            parser.error(f"--ta-collector-env rejected: {exc}")
    for cmd_arg in args.ta_collector_cmd_arg:
        try:
            validate_ta_cmd_arg(cmd_arg)
        except ValueError as exc:
            parser.error(f"--ta-collector-cmd-arg rejected: {exc}")
    listed_versions = set(TA_SPLUNKBASE_METADATA["compatible_splunk_versions"]["listed"])
    if args.splunk_version and not re.fullmatch(r"[0-9]+\.[0-9]+(?:\.[0-9]+)?", args.splunk_version):
        parser.error("--splunk-version must be an exact MAJOR.MINOR or MAJOR.MINOR.PATCH version")
    requested_version = version_tuple(args.splunk_version) if args.splunk_version else ()
    requested_train = ".".join(str(part) for part in requested_version[:2])
    if args.splunk_version and requested_train not in listed_versions:
        parser.error(
            f"--splunk-version {args.splunk_version} is not in the TA family's audited "
            f"compatibility trains: {', '.join(TA_SPLUNKBASE_METADATA['compatible_splunk_versions']['listed'])}"
        )
    regulated_requested = args.ta_fips_required or args.ta_fedramp_required
    if regulated_requested and not args.accept_ta_regulated_override:
        parser.error(
            "The audited Splunkbase TA artifacts are not FIPS-compatible and do not document FedRAMP package status; "
            "pass --accept-ta-regulated-override to render an explicit warning packet."
        )
    if args.render_platform_hec_helper:
        hec_allowed_indexes(args)
    return args


def rendered_plan(args: argparse.Namespace) -> dict[str, object]:
    output_dir = Path(args.output_dir)
    commands: list[str] = []
    preparation_commands: list[str] = []
    if args.render_platform_hec_helper:
        preparation_commands.extend(
            [
                f"bash {output_dir / 'platform-hec' / 'render-hec-service.sh'}",
                f"bash {output_dir / 'platform-hec' / 'apply-hec-service.sh'}",
            ]
        )
    if args.render_k8s:
        if args.eks_cluster_name and args.aws_region:
            commands.append(f"bash {output_dir / 'k8s' / 'eks-update-kubeconfig.sh'}")
        commands.append(f"bash {output_dir / 'k8s' / 'preflight.sh'}")
        commands.append(f"bash {output_dir / 'k8s' / 'validate-secrets.sh'}")
        if str_bool(args.render_priority_class) and args.priority_class_name:
            commands.append(f"bash {output_dir / 'k8s' / 'priority-class.sh'}")
        commands.extend(
            [
                f"bash {output_dir / 'k8s' / 'create-secret.sh'}",
                f"bash {output_dir / 'k8s' / 'helm-install.sh'}",
                f"bash {output_dir / 'k8s' / 'status.sh'}",
            ]
        )
    if args.render_linux:
        linux_script = "install-ssh.sh" if args.execution == "ssh" else "install-local.sh"
        commands.append(f"bash {output_dir / 'linux' / linux_script}")
        linux_status = "status-ssh.sh" if args.execution == "ssh" else "status-local.sh"
        commands.append(f"bash {output_dir / 'linux' / linux_status}")
    if args.render_ta:
        commands.append(f"bash {output_dir / 'ta' / 'preflight-ta.sh'}")
        commands.append(f"bash {output_dir / 'ta' / 'stage-ta-package.sh'}")
        if args.ta_target == "deployment-server":
            commands.append(f"bash {output_dir / 'ta' / 'apply-deployment-server.sh'}")
        else:
            commands.append(f"bash {output_dir / 'ta' / 'apply-local-uf.sh'}")
        commands.append(f"bash {output_dir / 'ta' / 'status-ta.sh'}")
    return {
        "output_dir": str(output_dir),
        "render_k8s": args.render_k8s,
        "render_linux": args.render_linux,
        "render_ta": args.render_ta,
        "render_platform_hec_helper": args.render_platform_hec_helper,
        "preparation_commands": preparation_commands,
        "apply_commands": commands,
        "warnings": warnings(args),
    }


def platform_hec_token_configured(args: argparse.Namespace) -> bool:
    return bool(args.platform_hec_token_file) or bool(args.render_platform_hec_helper)


def platform_hec_token_path(args: argparse.Namespace, output_dir: Path) -> str:
    if args.platform_hec_token_file:
        return args.platform_hec_token_file
    return str(output_dir / ".secrets" / "splunk_platform_hec_token")


def platform_otlp_logs_enabled(args: argparse.Namespace) -> bool:
    return platform_logs_requested(args) and bool(args.platform_otlp_endpoint)


def platform_logs_requested(args: argparse.Namespace) -> bool:
    """Whether any typed source or extension needs the Platform logs pipeline."""

    return any(
        (
            str_bool(args.platform_logs_enabled),
            str_bool(args.enable_logs),
            str_bool(args.enable_journald),
        )
    )


def platform_hec_logs_enabled(args: argparse.Namespace) -> bool:
    return (
        platform_logs_requested(args)
        and not platform_otlp_logs_enabled(args)
        and bool(args.platform_hec_url)
        and platform_hec_token_configured(args)
    )


def platform_metrics_enabled(args: argparse.Namespace) -> bool:
    return (
        str_bool(args.platform_metrics_enabled)
        and bool(args.platform_hec_url)
        and bool(args.platform_metrics_index)
        and platform_hec_token_configured(args)
    )


def platform_traces_enabled(args: argparse.Namespace) -> bool:
    return (
        str_bool(args.platform_traces_enabled)
        and bool(args.platform_hec_url)
        and bool(args.platform_traces_index)
        and platform_hec_token_configured(args)
    )


def platform_logs_enabled(args: argparse.Namespace) -> bool:
    return platform_hec_logs_enabled(args) or platform_otlp_logs_enabled(args)


def platform_hec_token_required(args: argparse.Namespace) -> bool:
    return (
        platform_hec_logs_enabled(args)
        or platform_metrics_enabled(args)
        or platform_traces_enabled(args)
    )


def platform_destination_enabled(args: argparse.Namespace) -> bool:
    return (
        platform_logs_enabled(args)
        or platform_metrics_enabled(args)
        or platform_traces_enabled(args)
    )


def observability_destination_enabled(args: argparse.Namespace) -> bool:
    """Whether the rendered chart needs a Splunk Observability realm/token."""

    return any(
        (
            str_bool(args.enable_metrics),
            str_bool(args.enable_traces),
            str_bool(args.enable_profiling),
            str_bool(args.enable_secure_app),
        )
    )


def effective_gateway_enabled(args: argparse.Namespace) -> bool:
    return bool(
        str_bool(args.gateway_enabled)
        or str_bool(args.network_explorer_enabled)
        or args.distribution == "eks/fargate"
    )


def effective_agent_host_network(args: argparse.Namespace) -> bool:
    if args.distribution == "eks/fargate" or str_bool(args.windows_nodes):
        return False
    return str_bool(args.agent_host_network)


def effective_cluster_receiver_enabled(args: argparse.Namespace) -> bool:
    return bool(
        str_bool(args.cluster_receiver_enabled)
        and (
            str_bool(args.enable_metrics)
            or platform_metrics_enabled(args)
            or str_bool(args.enable_events)
            or bool(args.k8s_objects)
            or str_bool(args.k8s_entities_enabled)
            or str_bool(args.entity_events_enabled)
        )
    )


def warnings(args: argparse.Namespace) -> list[str]:
    result: list[str] = []
    logs_enabled = platform_logs_enabled(args)
    if str_bool(args.enable_logs) and args.render_k8s and not logs_enabled:
        result.append(
            "Kubernetes container logs require either Splunk Platform HEC plus a token file, or --platform-otlp-endpoint; rendered chart values leave Platform logs disabled."
        )
    if str_bool(args.enable_journald) and args.render_k8s:
        result.append(
            "Kubernetes journald collection is enabled for Linux agent nodes; unit selection, journal directory, host journalctl mounts, and optional index remain reviewed extra-values settings."
        )
    if (
        args.render_k8s
        and str_bool(args.platform_logs_enabled)
        and not any((str_bool(args.enable_logs), str_bool(args.enable_journald), str_bool(args.enable_events), bool(args.k8s_objects)))
    ):
        result.append(
            "The Splunk Platform logs pipeline is enabled without a typed built-in log source; verify that a reviewed extra-values overlay enables extraFileLogs or another supported source."
        )
    if args.platform_hec_url and not args.platform_hec_url.rstrip("/").endswith("/services/collector/event"):
        result.append(
            "Splunk's chart recommends a HEC endpoint ending in /services/collector/event for correct field extraction."
        )
    if str_bool(args.platform_metrics_enabled) and not platform_metrics_enabled(args):
        result.append(
            "Splunk Platform metrics require --platform-hec-url, a HEC token file/helper, and --platform-metrics-index."
        )
    if str_bool(args.platform_traces_enabled) and not platform_traces_enabled(args):
        result.append(
            "Splunk Platform traces require --platform-hec-url, a HEC token file/helper, and --platform-traces-index."
        )
    if args.render_platform_hec_helper and args.render_k8s and args.platform_hec_url:
        result.append(
            "Run platform-hec/apply-hec-service.sh before k8s/create-secret.sh if the Splunk Platform HEC token file does not already exist."
        )
    if args.render_platform_hec_helper and args.render_k8s and not args.platform_hec_url:
        result.append(
            "The Splunk Platform HEC helper is rendered, but the Platform logs pipeline remains disabled until --platform-hec-url is supplied."
        )
    if args.platform_hec_token_file and args.render_linux:
        result.append(
            "The Linux installer path uses the Observability access token; platform HEC token handling is Kubernetes-only in this workflow."
        )
    if args.distribution == "eks/fargate" and args.render_k8s and not str_bool(args.gateway_enabled):
        result.append(
            "EKS Fargate does not support the agent DaemonSet; gateway.enabled is rendered true so applications have a collector endpoint."
        )
    if args.distribution == "eks/fargate" and args.render_k8s:
        result.append(
            "The chart's mutable Amazon Linux Fargate init image is replaced by the audited "
            f"multi-architecture digest {FARGATE_NODE_DISCOVERER_INDEX_DIGEST}; "
            "preflight and live status fail closed if the named initContainer is not pinned."
        )
    if args.distribution == "eks/auto-mode" and args.render_k8s:
        if effective_gateway_enabled(args):
            result.append(
                "EKS Auto Mode gateway deployment requires configured EKS Pod Identity for AWS resource detection."
            )
        result.append(
            "EKS Auto Mode uses host networking for IMDS-backed resource detection; if an extra-values overlay disables agent or cluster-receiver host networking, configure EKS Pod Identity."
        )
    if str_bool(args.network_explorer_enabled) and args.render_k8s:
        result.append(
            "Network Explorer compatibility mode forces one Collector gateway replica; deploy the separate upstream OpenTelemetry eBPF Helm chart from the rendered handoff. That chart is not covered by Splunk support."
        )
    if str_bool(args.windows_nodes) and args.render_k8s:
        result.append(
            "Windows node support normally needs a separate Helm release; disable one cluster receiver if you also install a Linux release."
        )
    if str_bool(args.enable_autoinstrumentation) and args.render_k8s and not str_bool(args.enable_operator_crds):
        result.append(
            "Auto-instrumentation is enabled but operator CRD installation is disabled; install OpenTelemetry Operator CRDs before applying."
        )
    if str_bool(args.enable_certmanager):
        result.append(
            "The Operator is configured to use an existing cert-manager installation; the deprecated bundled cert-manager subchart stays disabled and preflight checks its CRDs."
        )
    if str_bool(args.enable_autoinstrumentation) and args.render_k8s:
        if str_bool(args.instrumentation_installation_job):
            result.append(
                "Kubernetes Operator auto-instrumentation is alpha; the installation Job path avoids the Helm first-install webhook race. Its audited kubectl v1.35.1 image supports Kubernetes server minors 1.34 through 1.36 in this packet."
            )
        else:
            result.append(
                "Kubernetes Operator auto-instrumentation is alpha and the installation Job is disabled. Helm 4 first install is rejected because upstream resource mode races the operator webhook; use the default Job or an externally reviewed two-step install."
            )
    if (
        args.render_linux
        and str_bool(args.enable_logs)
        and str_bool(args.enable_autoinstrumentation)
    ):
        result.append(
            "Linux --enable-logs configures auto-instrumented application log export only; use a Universal Forwarder/TA for host logs."
        )
    if (
        args.render_linux
        and str_bool(args.enable_logs)
        and not str_bool(args.enable_autoinstrumentation)
    ):
        result.append(
            "Linux --enable-logs records OTLP application-log validation scope but adds no host file/journal source; use a Universal Forwarder/TA for host logs."
        )
    if args.render_linux and not args.listen_interface and args.linux_mode == "agent":
        result.append(
            "Linux agent receivers default to loopback (127.0.0.1); set --listen-interface explicitly only when remote clients require it."
        )
    if args.render_linux and args.collector_config:
        result.append(
            "The Linux custom Collector config exists on the target host and cannot be inspected during rendering; validate its pipelines with the pinned collector before apply."
        )
    if args.render_linux and "fips140=on" in args.godebug.lower():
        result.append(
            "GODEBUG=fips140=on does not select or prove use of Splunk's Linux FIPS package; regulated deployment requires the release FIPS artifact handoff and independent evidence."
        )
    if args.render_k8s and str_bool(args.enable_obi):
        result.append(
            "Kubernetes OBI is enabled; confirm every scheduled Linux node passes the rendered kernel, architecture, and privilege preflight."
        )
    if args.render_linux and str_bool(args.enable_obi):
        result.append(
            "Linux OBI scope is a pinned binary install/version check only; runtime configuration, privileges, endpoint wiring, and process supervision remain a handoff."
        )
    if args.render_ta and not args.ta_package_path:
        result.append(
            "TA rendering has no --ta-package-path; output uses generic artifact metadata and cannot stage packages until a .tgz is supplied."
        )
    if args.render_ta and args.ta_secret_mode == "placeholder":
        result.append(
            "TA token handling is placeholder-only; rendered local/inputs.conf.template intentionally omits token values."
        )
    if args.render_ta and args.ta_secret_mode == "environment":
        result.append(
            "TA environment secret mode requires the runtime environment to provide SPLUNK_ACCESS_TOKEN; Splunk conf does not store the token."
        )
    if args.render_ta and (args.ta_fips_required or args.ta_fedramp_required):
        result.append(
            "Regulated-environment override accepted even though the audited TA artifacts are not FIPS-compatible and do not document FedRAMP package status."
        )
    return result


def k8s_values(args: argparse.Namespace) -> str:
    logs_enabled = platform_logs_enabled(args)
    container_logs_enabled = str_bool(args.enable_logs) and logs_enabled
    otlp_logs_enabled = platform_otlp_logs_enabled(args)
    platform_enabled = platform_destination_enabled(args)
    observability_enabled = observability_destination_enabled(args)
    gateway_enabled = effective_gateway_enabled(args)
    agent_enabled = str_bool(args.agent_enabled) and args.distribution != "eks/fargate"
    send_objects_or_events_to_o11y = bool(
        (str_bool(args.enable_events) or args.k8s_objects) and observability_enabled
    )
    lines = [
        "# Generated by splunk-observability-otel-collector-setup.",
        "# Token values are intentionally omitted; use k8s/create-secret.sh.",
        f"clusterName: {yaml_scalar(args.cluster_name)}",
        f"cloudProvider: {yaml_scalar(args.cloud_provider)}",
        f"distribution: {yaml_scalar(args.distribution)}",
        f"environment: {yaml_scalar(args.deployment_environment)}",
        f"isWindows: {yaml_scalar(str_bool(args.windows_nodes))}",
        f"priorityClassName: {yaml_scalar(args.priority_class_name)}",
        "",
        "secret:",
        "  create: false",
        f"  name: {yaml_scalar(secret_name(args.release_name))}",
        "",
        "clusterReceiver:",
        f"  enabled: {yaml_scalar(effective_cluster_receiver_enabled(args))}",
        f"  eventsEnabled: {yaml_scalar(str_bool(args.enable_events))}",
        f"  priorityClassName: {yaml_scalar(args.priority_class_name)}",
    ]
    lines.extend(render_k8s_objects_values(args.k8s_objects))
    lines.extend([
        "",
        "rbac:",
    ])
    lines.extend(render_k8s_object_rbac_values(args.k8s_objects))
    lines.extend([
        "",
        "featureGates:",
        f"  sendK8sEventsToSplunkO11y: {yaml_scalar(send_objects_or_events_to_o11y)}",
        "",
        "logsCollection:",
        "  containers:",
        f"    enabled: {yaml_scalar(container_logs_enabled)}",
        "  journald:",
        f"    enabled: {yaml_scalar(str_bool(args.enable_journald) and logs_enabled)}",
        "",
        "agent:",
        f"  enabled: {yaml_scalar(agent_enabled)}",
        f"  hostNetwork: {yaml_scalar(effective_agent_host_network(args))}",
        "  service:",
        f"    enabled: {yaml_scalar(agent_enabled)}",
        "  discovery:",
        f"    enabled: {yaml_scalar(str_bool(args.enable_discovery))}",
        "",
        "autodetect:",
        f"  prometheus: {yaml_scalar(str_bool(args.enable_prometheus_autodetect))}",
        f"  istio: {yaml_scalar(str_bool(args.enable_istio_autodetect))}",
        "",
        "operator:",
        f"  enabled: {yaml_scalar(str_bool(args.enable_autoinstrumentation))}",
        f"  fullnameOverride: {yaml_scalar(operator_fullname(args.release_name))}",
        "  admissionWebhooks:",
        "    autoGenerateCert:",
        f"      enabled: {yaml_scalar(not str_bool(args.enable_certmanager))}",
        "    certManager:",
        f"      enabled: {yaml_scalar(str_bool(args.enable_certmanager))}",
        "",
        "operatorcrds:",
        f"  install: {yaml_scalar(str_bool(args.enable_operator_crds) and str_bool(args.enable_autoinstrumentation))}",
        "",
        "certmanager:",
        "  enabled: false",
        "",
        "instrumentation:",
        f"  enabled: {yaml_scalar(str_bool(args.enable_autoinstrumentation))}",
        "  installationJob:",
        f"    enabled: {yaml_scalar(str_bool(args.instrumentation_installation_job) and str_bool(args.enable_autoinstrumentation))}",
        "    image:",
        f"      tag: {yaml_scalar(args.instrumentation_kubectl_image_tag)}",
        "",
        "obi:",
        f"  enabled: {yaml_scalar(str_bool(args.enable_obi))}",
        f"  fullnameOverride: {yaml_scalar(obi_fullname(args.release_name))}",
        "",
        "gateway:",
        f"  enabled: {yaml_scalar(gateway_enabled)}",
        f"  replicaCount: {yaml_scalar(int(args.gateway_replicas))}",
        f"  priorityClassName: {yaml_scalar(args.priority_class_name)}",
        "",
        "targetallocator:",
        f"  enabled: {yaml_scalar(str_bool(args.target_allocator_enabled))}",
        f"  fullnameOverride: {yaml_scalar(target_allocator_fullname(args.release_name))}",
        "",
    ])
    if observability_enabled:
        insert_at = lines.index("clusterReceiver:")
        lines[insert_at:insert_at] = [
            "splunkObservability:",
            f"  realm: {yaml_scalar(args.realm)}",
            '  accessToken: ""',
            f"  ingestUrl: {yaml_scalar(args.o11y_ingest_url)}",
            f"  apiUrl: {yaml_scalar(args.o11y_api_url)}",
            f"  metricsEnabled: {yaml_scalar(str_bool(args.enable_metrics))}",
            f"  tracesEnabled: {yaml_scalar(str_bool(args.enable_traces))}",
            f"  profilingEnabled: {yaml_scalar(str_bool(args.enable_profiling))}",
            f"  secureAppEnabled: {yaml_scalar(str_bool(args.enable_secure_app))}",
            "",
        ]
    # These feature gates are explicit because Kubernetes entity emission and
    # entity-event property updates are experimental in chart 0.154.0.
    feature_index = lines.index("featureGates:") + 2
    lines[feature_index:feature_index] = [
        f"  enableK8sEntities: {yaml_scalar(str_bool(args.k8s_entities_enabled))}",
        f"  useEntityEventsForK8sProperties: {yaml_scalar(str_bool(args.entity_events_enabled))}",
    ]
    if platform_enabled:
        insert_at = lines.index("clusterReceiver:")
        platform_lines = [
            "splunkPlatform:",
            f"  endpoint: {yaml_scalar(args.platform_hec_url)}",
            '  token: ""',
            f"  index: {yaml_scalar(args.platform_hec_index)}",
            f"  metricsIndex: {yaml_scalar(args.platform_metrics_index)}",
            f"  tracesIndex: {yaml_scalar(args.platform_traces_index)}",
            f"  logsEnabled: {yaml_scalar(logs_enabled)}",
            f"  metricsEnabled: {yaml_scalar(platform_metrics_enabled(args))}",
            f"  tracesEnabled: {yaml_scalar(platform_traces_enabled(args))}",
            "  insecureSkipVerify: false",
            "  otlpIngest:",
            f"    enabled: {yaml_scalar(otlp_logs_enabled)}",
            f"    endpoint: {yaml_scalar(args.platform_otlp_endpoint)}",
            f"    protocol: {yaml_scalar(args.platform_otlp_protocol)}",
            f"    insecure: {yaml_scalar(str_bool(args.platform_otlp_insecure))}",
            "    insecureSkipVerify: false",
        ]
        otlp_tls = (
            ("platform_otlp_client_cert_file", "    clientCert:"),
            ("platform_otlp_client_key_file", "    clientKey:"),
            ("platform_otlp_ca_file", "    caFile:"),
        )
        for field, yaml_key in otlp_tls:
            if getattr(args, field):
                platform_lines.append(f'{yaml_key} "__FILE_BACKED__"')
        tls_placeholders = (
            ("platform_hec_client_cert_file", "  clientCert:"),
            ("platform_hec_client_key_file", "  clientKey:"),
            ("platform_hec_ca_file", "  caFile:"),
        )
        for field, yaml_key in tls_placeholders:
            if getattr(args, field):
                platform_lines.append(f'{yaml_key} "__FILE_BACKED__"')
        platform_lines.extend(
            [
                "  sendingQueue:",
                "    persistentQueue:",
                f"      enabled: {yaml_scalar(str_bool(args.platform_persistent_queue_enabled))}",
                f"      storagePath: {yaml_scalar(args.platform_persistent_queue_path)}",
                f"  fsyncEnabled: {yaml_scalar(str_bool(args.platform_fsync_enabled))}",
                "",
            ]
        )
        lines[insert_at:insert_at] = platform_lines
    if str_bool(args.fips_enabled):
        lines.extend(
            [
                "image:",
                "  otelcol:",
                '    repository: "quay.io/signalfx/splunk-otel-collector-fips"',
                "",
            ]
        )
    elif str_bool(args.windows_nodes):
        lines.extend(
            [
                "image:",
                "  otelcol:",
                '    repository: "quay.io/signalfx/splunk-otel-collector-windows"',
            ]
        )
    if str_bool(args.windows_nodes):
        lines.extend(
            [
                "readinessProbe:",
                "  initialDelaySeconds: 60",
                "livenessProbe:",
                "  initialDelaySeconds: 60",
                "",
            ]
        )
    return "\n".join(lines)


def render_k8s(args: argparse.Namespace, output_dir: Path) -> None:
    k8s_dir = output_dir / "k8s"
    if k8s_dir.exists():
        shutil.rmtree(k8s_dir)
    k8s_dir.mkdir(parents=True, exist_ok=True)
    write_text(k8s_dir / "redact-stream.py", diagnostic_redactor_script(), executable=True)
    owner_skill = "splunk-observability-otel-collector-setup"
    ownership_go_template = (
        '{{index .metadata.annotations "splunk.com/owner-skill"}}'
        '{{"\\t"}}{{index .metadata.annotations "splunk.com/release-name"}}'
        '{{"\\t"}}{{index .metadata.annotations "splunk.com/release-namespace"}}'
        '{{"\\t"}}{{.metadata.uid}}'
        '{{"\\t"}}{{.metadata.resourceVersion}}'
    )

    collector_fullname = helm_fullname(args.release_name, CHART_NAME)
    cluster_receiver_fullname = cluster_receiver_name(collector_fullname, args.distribution)
    if str_bool(args.fips_enabled):
        collector_source_image = COLLECTOR_FIPS_SOURCE_IMAGE
        collector_pinned_image = COLLECTOR_FIPS_IMAGE
    elif str_bool(args.windows_nodes):
        collector_source_image = COLLECTOR_WINDOWS_SOURCE_IMAGE
        collector_pinned_image = COLLECTOR_WINDOWS_IMAGE
    else:
        collector_source_image = COLLECTOR_STANDARD_SOURCE_IMAGE
        collector_pinned_image = COLLECTOR_STANDARD_IMAGE
    image_targets: list[dict[str, str]] = []

    def add_image_target(kind: str, name: str, section: str, container: str, source: str, pinned: str) -> None:
        image_targets.append(
            {
                "kind": kind,
                "name": name,
                "section": section,
                "container": container,
                "source": source,
                "pinned": pinned,
            }
        )

    if str_bool(args.agent_enabled) and args.distribution != "eks/fargate":
        add_image_target(
            "DaemonSet",
            f"{collector_fullname}-agent",
            "containers",
            "otel-collector",
            collector_source_image,
            collector_pinned_image,
        )
    if effective_gateway_enabled(args):
        add_image_target(
            "Deployment",
            collector_fullname,
            "containers",
            "otel-collector",
            collector_source_image,
            collector_pinned_image,
        )
    if effective_cluster_receiver_enabled(args):
        cluster_kind = "StatefulSet" if args.distribution == "eks/fargate" else "Deployment"
        add_image_target(
            cluster_kind,
            cluster_receiver_fullname,
            "containers",
            "otel-collector",
            collector_source_image,
            collector_pinned_image,
        )
        if args.distribution == "eks/fargate":
            add_image_target(
                "StatefulSet",
                cluster_receiver_fullname,
                "initContainers",
                "cluster-receiver-node-discoverer",
                FARGATE_NODE_DISCOVERER_SOURCE_IMAGE,
                FARGATE_NODE_DISCOVERER_IMAGE,
            )

    fargate_post_renderer_name = "k8s-image-post-renderer.py"
    fargate_post_renderer_plugin_name = "splunk-audited-image-pin"
    write_text(
        k8s_dir / fargate_post_renderer_name,
        k8s_image_post_renderer_script(image_targets),
        executable=True,
    )
    plugin_dir = k8s_dir / "helm-plugins" / fargate_post_renderer_plugin_name
    write_text(
        plugin_dir / "plugin.yaml",
        f"""apiVersion: v1
type: postrenderer/v1
name: {fargate_post_renderer_plugin_name}
version: 1.0.0
runtime: subprocess
sourceURL: https://github.com/chambear2809/splunk-cisco-skills
runtimeConfig:
  platformCommand:
    - command: ${{HELM_PLUGIN_DIR}}/run.sh
""",
    )
    write_text(
        plugin_dir / "run.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail

plugin_dir="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
exec python3 "${{plugin_dir}}/../../{fargate_post_renderer_name}"
""",
        executable=True,
    )
    job_owned_instrumentation = (
        str_bool(args.enable_autoinstrumentation)
        and str_bool(args.instrumentation_installation_job)
    )
    helm_release_guard_name = "helm-release-guard.py"
    write_text(
        k8s_dir / helm_release_guard_name,
        helm_release_guard_script(args.release_name, args.namespace),
        executable=True,
    )
    instrumentation_guard_name = ""
    if job_owned_instrumentation:
        instrumentation_guard_name = "instrumentation-lifecycle.py"
        write_text(
            k8s_dir / instrumentation_guard_name,
            instrumentation_lifecycle_script(
                collector_fullname,
                args.namespace,
                args.release_name,
            ),
            executable=True,
        )
    values_path = k8s_dir / "values.yaml"
    write_text(values_path, k8s_values(args))
    if str_bool(args.network_explorer_enabled):
        write_text(
            k8s_dir / "network-explorer-handoff.md",
            f"""# Network Explorer eBPF handoff

This Collector release is rendered in gateway mode with exactly one gateway
replica, as required by Network Explorer. The chart's OTLP gRPC metrics
receiver and SignalFx exporter provide the Collector-side transport.

Prerequisites to prove before the eBPF apply:

- Kubernetes `1.24+`, Helm `3.9+`, and Linux worker nodes.
- Supported kernels `3.10-3.19`, `4.0-4.20`, or `5.0-5.19`, excluding
  `4.15.0`, `4.19.57`, and `5.1.16`; verify the current official matrix.
- Kernel headers available on every target node (automatic installation needs
  internet access; otherwise preinstall the exact matching headers).
- This profile is not for GKE Autopilot, EKS Fargate, Windows, or OpenShift.
  OpenShift requires a separate SELinux `spc_t` policy, privileged and `anyuid`
  SCC grants, service accounts/RBAC, and a reviewed OpenShift kernel image.

Network telemetry still requires the separate upstream
`open-telemetry/opentelemetry-ebpf` Helm chart. Splunk documents that chart as
outside Splunk support/SLA coverage. The platform owner must select and audit
an exact chart version, images, privileges, tolerations, and rollback before
running a command derived from this review-only template:

```bash
helm upgrade --install my-opentelemetry-ebpf open-telemetry/opentelemetry-ebpf \\
  --namespace {args.namespace} \\
  --version <PINNED_EBPF_CHART_VERSION> \\
  --set endpoint.address={collector_fullname}.{args.namespace}.svc.cluster.local
```

Validate the eBPF DaemonSet, gateway OTLP reception, representative `tcp.*`,
`udp.*`, `dns.*`, and `http.*` metrics, and the populated Network Explorer UI
independently. Do not scale this Collector
gateway above one replica while this Network Explorer integration is active.

Official setup contract:
<https://help.splunk.com/en/splunk-observability-cloud/monitor-infrastructure/network-explorer/set-up-network-explorer-in-kubernetes>
""",
        )
    values_hash = sha256_file(values_path)
    write_text(
        k8s_dir / "verify-overlay.py",
        r'''#!/usr/bin/env python3
"""Hash one immutable values snapshot through a stable no-follow descriptor."""

import hashlib
import hmac
import os
import re
import stat
import sys


path, expected = sys.argv[1:]
if not re.fullmatch(r"[0-9a-f]{64}", expected):
    raise SystemExit("ERROR: rendered values snapshot has an invalid expected digest")
if not hasattr(os, "O_NOFOLLOW"):
    raise SystemExit("ERROR: values snapshot verification requires O_NOFOLLOW support")
try:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
except OSError as exc:
    raise SystemExit("ERROR: rendered values snapshot is missing, unreadable, or a symlink") from exc
try:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise SystemExit("ERROR: rendered values snapshot must be a single-link regular file")
    if before.st_size < 1 or before.st_size > 32 * 1024 * 1024:
        raise SystemExit("ERROR: rendered values snapshot size is outside the 32 MiB bound")
    digest = hashlib.sha256()
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
    after = os.fstat(descriptor)
    fingerprints = lambda info: (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
        info.st_nlink,
    )
    if fingerprints(before) != fingerprints(after):
        raise SystemExit("ERROR: rendered values snapshot changed during verification")
finally:
    os.close(descriptor)
if not hmac.compare_digest(digest.hexdigest(), expected):
    raise SystemExit("ERROR: rendered values snapshot changed after policy validation")
''',
        executable=True,
    )
    write_text(
        k8s_dir / "verify-secret-revision.py",
        r'''#!/usr/bin/env python3
"""Validate the only mutable Helm values overlay without following links."""

from __future__ import annotations

import json
import os
import re
import stat
import sys


path = sys.argv[1]
if not hasattr(os, "O_NOFOLLOW"):
    raise SystemExit("ERROR: secret-revision validation requires O_NOFOLLOW support")
try:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
except OSError as exc:
    raise SystemExit("ERROR: secret-revision values must be a non-symlink regular file") from exc
try:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise SystemExit("ERROR: secret-revision values must be a single-link regular file")
    if before.st_size < 2 or before.st_size > 4096:
        raise SystemExit("ERROR: secret-revision values size is outside the safe bound")
    chunks = []
    while True:
        chunk = os.read(descriptor, 4096)
        if not chunk:
            break
        chunks.append(chunk)
    after = os.fstat(descriptor)
    fingerprint_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
        before.st_nlink,
    )
    fingerprint_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
        after.st_nlink,
    )
    if fingerprint_after != fingerprint_before:
        raise SystemExit("ERROR: secret-revision values changed during validation")
finally:
    os.close(descriptor)

raw = b"".join(chunks)
try:
    payload = json.loads(raw)
except (UnicodeDecodeError, json.JSONDecodeError) as exc:
    raise SystemExit("ERROR: secret-revision values must be canonical JSON") from exc
canonical = (json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
if raw != canonical:
    raise SystemExit("ERROR: secret-revision values must use the exact canonical JSON encoding")
components = {"agent", "clusterReceiver", "gateway"}
if not isinstance(payload, dict) or set(payload) != components:
    raise SystemExit("ERROR: secret-revision values has unexpected top-level keys")
revisions = set()
for component in components:
    value = payload[component]
    if not isinstance(value, dict) or set(value) != {"podAnnotations"}:
        raise SystemExit("ERROR: secret-revision values has an unexpected component schema")
    annotations = value["podAnnotations"]
    if not isinstance(annotations, dict) or set(annotations) != {"splunk.com/secret-revision"}:
        raise SystemExit("ERROR: secret-revision values has unexpected annotations")
    revision = annotations["splunk.com/secret-revision"]
    if not isinstance(revision, str) or not re.fullmatch(
        r"(?:rendered|[0-9]{8}T[0-9]{6}Z-[0-9]+-[0-9]+)", revision
    ):
        raise SystemExit("ERROR: secret-revision value has an invalid format")
    revisions.add(revision)
if len(revisions) != 1:
    raise SystemExit("ERROR: secret-revision annotations must use one identical value")
''',
        executable=True,
    )
    write_text(
        k8s_dir / "k8s-object-preconditions.py",
        r'''#!/usr/bin/env python3
"""Bind Kubernetes update/delete requests to one observed object generation."""

import json
import re
import sys


if len(sys.argv) != 4:
    raise SystemExit("ERROR: expected MODE UID RESOURCE_VERSION")
mode, uid, resource_version = sys.argv[1:]
safe_value = re.compile(r"[A-Za-z0-9._:-]{1,256}")
if not safe_value.fullmatch(uid) or not safe_value.fullmatch(resource_version):
    raise SystemExit("ERROR: Kubernetes UID/resourceVersion has an unsafe format")
if mode == "bind-manifest":
    payload = json.load(sys.stdin)
    metadata = payload.get("metadata")
    if not isinstance(payload, dict) or not isinstance(metadata, dict):
        raise SystemExit("ERROR: generated Kubernetes manifest has no metadata")
    metadata["uid"] = uid
    metadata["resourceVersion"] = resource_version
elif mode == "delete-options":
    payload = {
        "apiVersion": "v1",
        "kind": "DeleteOptions",
        "preconditions": {"uid": uid, "resourceVersion": resource_version},
    }
else:
    raise SystemExit("ERROR: unsupported Kubernetes precondition mode")
json.dump(payload, sys.stdout, separators=(",", ":"), sort_keys=True)
''',
        executable=True,
    )
    write_text(
        k8s_dir / "add-secret-ownership.py",
        r'''#!/usr/bin/env python3
"""Add the exact ownership metadata required by the Secret lifecycle guard."""

import json
import sys


owner, release, namespace, expected_name = sys.argv[1:]
payload = json.load(sys.stdin)
metadata = payload.get("metadata", {})
if (
    payload.get("apiVersion") != "v1"
    or payload.get("kind") != "Secret"
    or metadata.get("name") != expected_name
    or metadata.get("namespace") != namespace
    or not isinstance(payload.get("data"), dict)
    or not payload["data"]
):
    raise SystemExit("ERROR: generated Secret manifest has an unexpected identity")
metadata.setdefault("labels", {}).update(
    {
        "app.kubernetes.io/managed-by": owner,
        "app.kubernetes.io/instance": release,
    }
)
metadata.setdefault("annotations", {}).update(
    {
        "splunk.com/owner-skill": owner,
        "splunk.com/release-name": release,
        "splunk.com/release-namespace": namespace,
    }
)
json.dump(payload, sys.stdout, separators=(",", ":"))
''',
        executable=True,
    )
    extra_values_names = []
    extra_values_hashes = []
    for index, extra_values in enumerate(args.extra_values_file, start=1):
        source = Path(extra_values).expanduser()
        snapshot = read_bounded_nofollow_text(
            source,
            label="--extra-values-file",
            maximum_bytes=32 * 1024 * 1024,
        )
        target_name = f"extra-values-{index}.yaml"
        target = k8s_dir / target_name
        write_text(target, snapshot)
        try:
            # Validate the exact immutable snapshot consumed by Helm, not the
            # source path, so a source-file race cannot bypass secret checks.
            validate_extra_values(target)
        except BaseException:
            shutil.rmtree(k8s_dir, ignore_errors=True)
            raise
        extra_values_names.append(target_name)
        extra_values_hashes.append(sha256_file(target))

    write_text(
        k8s_dir / "verify-overlays.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
{bash_array("overlay_names", ["values.yaml", *extra_values_names])}
{bash_array("overlay_hashes", [values_hash, *extra_values_hashes])}

for index in "${{!overlay_names[@]}}"; do
    path="${{script_dir}}/${{overlay_names[$index]}}"
    expected="${{overlay_hashes[$index]}}"
    python3 "${{script_dir}}/verify-overlay.py" "${{path}}" "${{expected}}"
done
python3 "${{script_dir}}/verify-secret-revision.py" \
    "${{script_dir}}/secret-revision-values.yaml"
""",
        executable=True,
    )

    platform_token_required = platform_hec_token_required(args)
    observability_token_required = observability_destination_enabled(args)
    kube_prefix = ""
    if args.kube_context:
        kube_prefix = f"--context {shell_quote(args.kube_context)} "
        kube_context_display = (
            f"printf '%s\\n' {shell_quote('Kubernetes context: ' + args.kube_context)}"
        )
    else:
        kube_context_display = (
            "printf 'Kubernetes context: ' && kubectl config current-context"
        )
    token_file = args.o11y_token_file or "/path/to/splunk_o11y_access_token"
    platform_file = (
        platform_hec_token_path(args, output_dir)
        if platform_token_required
        else "/path/to/splunk_platform_hec_token"
    )
    secret_file_entries = [
        ("splunk_platform_hec_client_cert", args.platform_hec_client_cert_file, False),
        ("splunk_platform_hec_client_key", args.platform_hec_client_key_file, True),
        ("splunk_platform_hec_ca_file", args.platform_hec_ca_file, False),
        ("splunk_platform_otlp_client_cert", args.platform_otlp_client_cert_file, False),
        ("splunk_platform_otlp_client_key", args.platform_otlp_client_key_file, True),
        ("splunk_platform_otlp_ca_file", args.platform_otlp_ca_file, False),
    ]
    external_secret_required = bool(
        observability_token_required
        or platform_token_required
        or any(path for _, path, _ in secret_file_entries)
    )
    tls_assignments = "\n".join(
        f"{name}_file={shell_quote(path)}" for name, path, _ in secret_file_entries
    )
    tls_secret_snapshots = "\n".join(
        f'''if [[ -n "${{{name}_file}}" ]]; then
    snapshot_file {shell_quote(name)} "${{{name}_file}}" "${{secret_material_dir}}/{name}" {"true" if private else "false"} false
    secret_args+=("--from-file={name}=${{secret_material_dir}}/{name}")
fi'''
        for name, _, private in secret_file_entries
    )
    tls_validate_only = "\n".join(
        f'''if [[ -n "${{{name}_file}}" ]]; then
    validate_file {shell_quote(name)} "${{{name}_file}}" {"true" if private else "false"}
fi'''
        for name, _, private in secret_file_entries
    )
    tls_content_functions = r'''
validate_ca_bundle() {
    local label="$1" path="$2"
    command -v openssl >/dev/null 2>&1 || {
        echo "ERROR: openssl is required to validate custom TLS material." >&2
        exit 1
    }
    python3 - "${label}" "${path}" <<'PY'
import os
import re
import stat
import subprocess
import sys

label, path = sys.argv[1:]
if not hasattr(os, "O_NOFOLLOW"):
    raise SystemExit("ERROR: secure CA validation requires O_NOFOLLOW support")
try:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
except OSError as exc:
    raise SystemExit("ERROR: %s is not a readable non-symlink CA bundle: %s" % (label, path)) from exc
try:
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise SystemExit("ERROR: %s must be a single-link regular CA bundle: %s" % (label, path))
    if info.st_size < 1 or info.st_size > 4 * 1024 * 1024:
        raise SystemExit("ERROR: %s CA bundle exceeds the 4 MiB validation bound: %s" % (label, path))
    chunks = []
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            break
        chunks.append(chunk)
finally:
    os.close(descriptor)

data = b"".join(chunks)
pattern = re.compile(
    rb"-----BEGIN CERTIFICATE-----[\r\n]+[A-Za-z0-9+/=\r\n]+-----END CERTIFICATE-----"
)
certificates = pattern.findall(data)
if not certificates or pattern.sub(b"", data).strip():
    raise SystemExit("ERROR: %s is not a strict PEM certificate bundle: %s" % (label, path))
for number, certificate in enumerate(certificates, 1):
    current = subprocess.run(
        ["openssl", "x509", "-inform", "PEM", "-noout", "-checkend", "0"],
        input=certificate,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if current.returncode != 0:
        raise SystemExit(
            "ERROR: %s certificate %d is invalid or expired: %s" % (label, number, path)
        )
    soon = subprocess.run(
        ["openssl", "x509", "-inform", "PEM", "-noout", "-checkend", "2592000"],
        input=certificate,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if soon.returncode != 0:
        print(
            "WARN: %s certificate %d expires within 30 days: %s" % (label, number, path),
            file=sys.stderr,
        )
PY
}

validate_client_pair() {
    local label="$1" cert="$2" key="$3" cert_public key_public
    command -v openssl >/dev/null 2>&1 || {
        echo "ERROR: openssl is required to validate custom TLS material." >&2
        exit 1
    }
    validate_ca_bundle "${label} client" "${cert}"
    if grep -Eq 'BEGIN ENCRYPTED PRIVATE KEY|Proc-Type:[[:space:]]*4,ENCRYPTED' "${key}"; then
        echo "ERROR: ${label} client key is encrypted; passphrase-bearing keys are unsupported." >&2
        exit 1
    fi
    openssl pkey -in "${key}" -passin pass: -noout >/dev/null 2>&1 || {
        echo "ERROR: ${label} client key is invalid or requires an unsupported passphrase: ${key}" >&2
        exit 1
    }
    cert_public="$(openssl x509 -in "${cert}" -pubkey -noout 2>/dev/null \
        | openssl pkey -pubin -outform DER 2>/dev/null \
        | openssl dgst -sha256 2>/dev/null)"
    key_public="$(openssl pkey -in "${key}" -passin pass: -pubout -outform DER 2>/dev/null \
        | openssl dgst -sha256 2>/dev/null)"
    if [[ -z "${cert_public}" || "${cert_public}" != "${key_public}" ]]; then
        echo "ERROR: ${label} client certificate and private key do not match." >&2
        exit 1
    fi
}
'''
    tls_content_calls: list[str] = []
    tls_snapshot_content_calls: list[str] = []
    for label, prefix in (("Platform HEC", "splunk_platform_hec"), ("Platform OTLP", "splunk_platform_otlp")):
        ca_field = f"{prefix}_ca_file"
        cert_field = f"{prefix}_client_cert"
        key_field = f"{prefix}_client_key"
        if any(name == ca_field and path for name, path, _ in secret_file_entries):
            tls_content_calls.append(
                f'validate_ca_bundle {shell_quote(label + " CA")} "${{{ca_field}_file}}"'
            )
            tls_snapshot_content_calls.append(
                f'validate_ca_bundle {shell_quote(label + " CA snapshot")} "${{secret_material_dir}}/{ca_field}"'
            )
        if any(name == cert_field and path for name, path, _ in secret_file_entries):
            tls_content_calls.append(
                f'validate_client_pair {shell_quote(label)} "${{{cert_field}_file}}" "${{{key_field}_file}}"'
            )
            tls_snapshot_content_calls.append(
                f'validate_client_pair {shell_quote(label + " snapshot")} "${{secret_material_dir}}/{cert_field}" "${{secret_material_dir}}/{key_field}"'
            )
    tls_content_validation = "\n".join(tls_content_calls)
    tls_snapshot_content_validation = "\n".join(tls_snapshot_content_calls)
    o11y_secret_arg_block = ""
    if observability_token_required:
        o11y_secret_arg_block = '''snapshot_file "Observability token" "${o11y_token_file}" "${secret_material_dir}/splunk_observability_access_token" true true
secret_args+=("--from-file=splunk_observability_access_token=${secret_material_dir}/splunk_observability_access_token")'''
    write_text(
        k8s_dir / "validate-secrets.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail

o11y_token_file={shell_quote(token_file)}
platform_hec_token_file={shell_quote(platform_file)}
observability_token_required={shell_quote('true' if observability_token_required else 'false')}
platform_token_required={shell_quote('true' if platform_token_required else 'false')}
{tls_assignments}

file_mode() {{
    stat -c '%a' "$1" 2>/dev/null || stat -f '%A' "$1" 2>/dev/null || true
}}

validate_file() {{
    local label="$1" path="$2" private="$3" maximum="${{4:-4194304}}" mode
    if [[ ! -f "${{path}}" || -L "${{path}}" || ! -r "${{path}}" || ! -s "${{path}}" ]]; then
        echo "ERROR: ${{label}} must be a readable, nonempty regular file: ${{path}}" >&2
        exit 1
    fi
    python3 - "${{label}}" "${{path}}" "${{maximum}}" <<'PY'
import os
import stat
import sys

label, path, maximum = sys.argv[1], sys.argv[2], int(sys.argv[3])
if not hasattr(os, "O_NOFOLLOW"):
    raise SystemExit("ERROR: secure secret validation requires O_NOFOLLOW support")
try:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
except OSError as exc:
    raise SystemExit("ERROR: %s must be a readable non-symlink file: %s" % (label, path)) from exc
try:
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise SystemExit("ERROR: %s must be a single-link regular file: %s" % (label, path))
    if info.st_size < 1 or info.st_size > maximum:
        raise SystemExit("ERROR: %s size must be between 1 and %d bytes: %s" % (label, maximum, path))
finally:
    os.close(descriptor)
PY
    if [[ "${{private}}" == "true" ]]; then
        mode="$(file_mode "${{path}}")"
        if [[ "${{mode}}" != "600" && "${{mode}}" != "0600" ]]; then
            echo "ERROR: ${{label}} must have mode 600 (found ${{mode:-unknown}}): ${{path}}" >&2
            exit 1
        fi
    fi
}}

validate_token_file() {{
    local label="$1" path="$2"
    validate_file "${{label}}" "${{path}}" true 16384
    python3 - "${{label}}" "${{path}}" <<'PY'
import os
import re
import stat
import sys

label, path = sys.argv[1:]
descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
try:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 1 <= before.st_size <= 16384:
        raise SystemExit("ERROR: %s is not a bounded single-link regular file: %s" % (label, path))
    value = os.read(descriptor, 16385)
    if len(value) > 16384 or os.read(descriptor, 1):
        raise SystemExit("ERROR: %s exceeds the 16384-byte token limit: %s" % (label, path))
    after = os.fstat(descriptor)
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns, before.st_nlink) != (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_nlink
    ):
        raise SystemExit("ERROR: %s changed during validation: %s" % (label, path))
finally:
    os.close(descriptor)
if any(marker in value for marker in (b"\\x00", b"\\r", b"\\n")):
    raise SystemExit("ERROR: %s must not contain NUL or newline bytes: %s" % (label, path))
if not re.fullmatch(rb"[A-Za-z0-9._~+/=-]+", value):
    raise SystemExit(
        "ERROR: %s must contain one config-safe token matching [A-Za-z0-9._~+/=-]+: %s"
        % (label, path)
    )
PY
}}

{tls_content_functions}

if [[ "${{observability_token_required}}" == "true" ]]; then
    validate_token_file "Observability token file" "${{o11y_token_file}}"
fi
if [[ "${{platform_token_required}}" == "true" ]]; then
    validate_token_file "Platform HEC token file" "${{platform_hec_token_file}}"
fi
{tls_validate_only}
{tls_content_validation}
""",
        executable=True,
    )

    if str_bool(args.render_priority_class) and args.priority_class_name:
        write_text(
            k8s_dir / "priority-class.sh",
            f"""#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
priority_name={shell_quote(args.priority_class_name)}
owner_skill={shell_quote(owner_skill)}
release_name={shell_quote(args.release_name)}
release_namespace={shell_quote(args.namespace)}
kubectl {kube_prefix}auth can-i get priorityclasses.scheduling.k8s.io | grep -qx 'yes' || {{
    echo "ERROR: current Kubernetes identity cannot inspect PriorityClass ownership." >&2
    exit 1
}}
if ! ownership="$(kubectl {kube_prefix}get priorityclass "${{priority_name}}" \
    --ignore-not-found -o go-template={shell_quote(ownership_go_template)})"; then
    echo "ERROR: failed to determine whether PriorityClass ${{priority_name}} exists." >&2
    exit 1
fi
if [[ -n "${{ownership}}" ]]; then
    IFS=$'\t' read -r existing_owner existing_release existing_namespace existing_uid existing_resource_version <<<"${{ownership}}"
    [[ "${{existing_owner}}" == "${{owner_skill}}" \
       && "${{existing_release}}" == "${{release_name}}" \
       && "${{existing_namespace}}" == "${{release_namespace}}" ]] || {{
        echo "ERROR: refusing to adopt or overwrite an unowned PriorityClass: ${{priority_name}}" >&2
        exit 1
    }}
fi
render_manifest() {{
cat <<'YAML'
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: {yaml_scalar(args.priority_class_name)}
  labels:
    app.kubernetes.io/managed-by: {yaml_scalar(owner_skill)}
    app.kubernetes.io/instance: {yaml_scalar(args.release_name)}
  annotations:
    splunk.com/owner-skill: {yaml_scalar(owner_skill)}
    splunk.com/release-name: {yaml_scalar(args.release_name)}
    splunk.com/release-namespace: {yaml_scalar(args.namespace)}
value: 1000000
globalDefault: false
description: "Higher priority class for the Splunk Distribution of OpenTelemetry Collector pods."
YAML
}}
if [[ -n "${{ownership}}" ]]; then
    kubectl {kube_prefix}auth can-i update priorityclasses.scheduling.k8s.io | grep -qx 'yes' || {{
        echo "ERROR: current Kubernetes identity cannot update the owned PriorityClass." >&2
        exit 1
    }}
    render_manifest \
        | kubectl {kube_prefix}create --dry-run=client -o json -f - \
        | python3 "${{script_dir}}/k8s-object-preconditions.py" bind-manifest \
            "${{existing_uid}}" "${{existing_resource_version}}" \
        | kubectl {kube_prefix}replace -f -
else
    kubectl {kube_prefix}auth can-i create priorityclasses.scheduling.k8s.io | grep -qx 'yes' || {{
        echo "ERROR: current Kubernetes identity cannot create the PriorityClass." >&2
        exit 1
    }}
    render_manifest | kubectl {kube_prefix}create -f -
fi
""",
            executable=True,
        )
        write_text(
            k8s_dir / "cleanup-priority-class.sh",
            f"""#!/usr/bin/env bash
set -euo pipefail

[[ "${{SPLUNK_OTEL_CONFIRM_PRIORITY_CLASS_DELETE:-}}" == "yes" ]] || {{
    echo "ERROR: Set SPLUNK_OTEL_CONFIRM_PRIORITY_CLASS_DELETE=yes after confirming this class is not shared." >&2
    exit 1
}}
script_dir="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
priority_name={shell_quote(args.priority_class_name)}
owner_skill={shell_quote(owner_skill)}
release_name={shell_quote(args.release_name)}
release_namespace={shell_quote(args.namespace)}
command -v kubectl >/dev/null 2>&1 || {{ echo "ERROR: kubectl is required." >&2; exit 1; }}
{kube_context_display}
kubectl {kube_prefix}auth can-i get priorityclasses.scheduling.k8s.io | grep -qx 'yes' || {{
    echo "ERROR: current Kubernetes identity cannot inspect PriorityClass ownership." >&2
    exit 1
}}
if ! ownership="$(kubectl {kube_prefix}get priorityclass "${{priority_name}}" \
    --ignore-not-found -o go-template={shell_quote(ownership_go_template)})"; then
    echo "ERROR: failed to inspect PriorityClass ${{priority_name}}." >&2
    exit 1
fi
if [[ -z "${{ownership}}" ]]; then
    echo "PriorityClass does not exist: ${{priority_name}}"
    exit 0
fi
IFS=$'\t' read -r existing_owner existing_release existing_namespace existing_uid existing_resource_version <<<"${{ownership}}"
[[ "${{existing_owner}}" == "${{owner_skill}}" \
   && "${{existing_release}}" == "${{release_name}}" \
   && "${{existing_namespace}}" == "${{release_namespace}}" ]] || {{
    echo "ERROR: refusing to delete an unowned PriorityClass: ${{priority_name}}" >&2
    exit 1
}}
kubectl {kube_prefix}auth can-i delete priorityclasses.scheduling.k8s.io | grep -qx 'yes' || {{
    echo "ERROR: current Kubernetes identity cannot delete the owned PriorityClass." >&2
    exit 1
}}
python3 "${{script_dir}}/k8s-object-preconditions.py" delete-options \
    "${{existing_uid}}" "${{existing_resource_version}}" \
    | kubectl {kube_prefix}delete \
        --raw="/apis/scheduling.k8s.io/v1/priorityclasses/${{priority_name}}" -f - >/dev/null
echo "Owned PriorityClass deletion accepted with UID/resourceVersion preconditions: ${{priority_name}}"
""",
            executable=True,
        )

    write_text(
        k8s_dir / "create-secret.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail
umask 077

script_dir="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
namespace={shell_quote(args.namespace)}
secret_name={shell_quote(secret_name(args.release_name))}
o11y_token_file={shell_quote(token_file)}
platform_hec_token_file={shell_quote(platform_file)}
platform_token_required={shell_quote('true' if platform_token_required else 'false')}
external_secret_required={shell_quote('true' if external_secret_required else 'false')}
owner_skill={shell_quote(owner_skill)}
release_name={shell_quote(args.release_name)}
{tls_assignments}

bash "${{script_dir}}/validate-secrets.sh"
secret_material_dir="$(mktemp -d "${{TMPDIR:-/tmp}}/splunk-otel-secret.XXXXXX")"
chmod 700 "${{secret_material_dir}}"
revision_tmp=""
cleanup() {{
    rm -rf -- "${{secret_material_dir}}"
    [[ -z "${{revision_tmp}}" ]] || rm -f -- "${{revision_tmp}}"
}}
trap cleanup EXIT HUP INT TERM

snapshot_file() {{
    local label="$1" source="$2" destination="$3" private="$4" token="$5"
    python3 - "${{label}}" "${{source}}" "${{destination}}" "${{private}}" "${{token}}" <<'PY'
import os
import re
import stat
import sys

label, source, destination, private, token = sys.argv[1:]
if not hasattr(os, "O_NOFOLLOW"):
    raise SystemExit("ERROR: secure Secret snapshots require O_NOFOLLOW support")
try:
    source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
except OSError as exc:
    raise SystemExit("ERROR: %s became unsafe before Secret creation" % label) from exc
try:
    before = os.fstat(source_fd)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise SystemExit("ERROR: %s must be a single-link regular file" % label)
    if private == "true" and stat.S_IMODE(before.st_mode) != 0o600:
        raise SystemExit("ERROR: %s must have mode 600" % label)
    maximum = 16384 if token == "true" else 4 * 1024 * 1024
    if before.st_size < 1 or before.st_size > maximum:
        raise SystemExit("ERROR: %s size is outside the safe bound" % label)
    chunks = []
    while True:
        chunk = os.read(source_fd, 1024 * 1024)
        if not chunk:
            break
        chunks.append(chunk)
    after = os.fstat(source_fd)
    fingerprint_before = (
        before.st_dev, before.st_ino, before.st_size,
        before.st_mtime_ns, before.st_ctime_ns, before.st_nlink,
    )
    fingerprint_after = (
        after.st_dev, after.st_ino, after.st_size,
        after.st_mtime_ns, after.st_ctime_ns, after.st_nlink,
    )
    if fingerprint_after != fingerprint_before:
        raise SystemExit("ERROR: %s changed while it was snapshotted" % label)
    value = b"".join(chunks)
    if token == "true" and any(marker in value for marker in (b"\\x00", b"\\r", b"\\n")):
        raise SystemExit("ERROR: %s must not contain NUL or newline bytes" % label)
    if token == "true" and not re.fullmatch(rb"[A-Za-z0-9._~+/=-]+", value):
        raise SystemExit("ERROR: %s is not a config-safe token" % label)
finally:
    os.close(source_fd)

destination_fd = os.open(
    destination,
    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
    0o600,
)
try:
    offset = 0
    while offset < len(value):
        written = os.write(destination_fd, value[offset:])
        if written <= 0:
            raise OSError("short Secret snapshot write")
        offset += written
    os.fchmod(destination_fd, 0o600)
    os.fsync(destination_fd)
finally:
    os.close(destination_fd)
PY
}}

secret_args=(
    create secret generic "${{secret_name}}"
    --namespace "${{namespace}}"
)
{o11y_secret_arg_block}
if [[ "${{platform_token_required}}" == "true" ]]; then
    snapshot_file "Platform HEC token" "${{platform_hec_token_file}}" "${{secret_material_dir}}/splunk_platform_hec_token" true true
    secret_args+=("--from-file=splunk_platform_hec_token=${{secret_material_dir}}/splunk_platform_hec_token")
fi
{tls_secret_snapshots}
{tls_content_functions}
{tls_snapshot_content_validation}

if kubectl {kube_prefix}auth can-i get namespaces | grep -qx 'yes'; then
    if ! kubectl {kube_prefix}get namespace "${{namespace}}" >/dev/null 2>&1; then
        kubectl {kube_prefix}create namespace "${{namespace}}"
    fi
else
    echo "WARN: cannot read cluster-scoped Namespaces; assuming ${{namespace}} already exists." >&2
fi

if [[ "${{external_secret_required}}" != "true" ]]; then
    echo "No external Collector secret is required for this destination profile."
    exit 0
fi

kubectl {kube_prefix}auth can-i get secrets --namespace "${{namespace}}" | grep -qx 'yes' || {{
    echo "ERROR: current Kubernetes identity cannot inspect retained Secret ownership." >&2
    exit 1
}}
if ! ownership="$(kubectl {kube_prefix}-n "${{namespace}}" get secret "${{secret_name}}" \
    --ignore-not-found -o go-template={shell_quote(ownership_go_template)})"; then
    echo "ERROR: failed to determine whether Collector Secret ${{namespace}}/${{secret_name}} exists." >&2
    exit 1
fi
if [[ -n "${{ownership}}" ]]; then
    IFS=$'\t' read -r existing_owner existing_release existing_namespace existing_uid existing_resource_version <<<"${{ownership}}"
    [[ "${{existing_owner}}" == "${{owner_skill}}" \
       && "${{existing_release}}" == "${{release_name}}" \
       && "${{existing_namespace}}" == "${{namespace}}" ]] || {{
        echo "ERROR: refusing to adopt or overwrite an unowned Collector Secret: ${{secret_name}}" >&2
        exit 1
    }}
fi

render_secret_manifest() {{
    kubectl {kube_prefix}"${{secret_args[@]}}" --dry-run=client -o json \
        | python3 "${{script_dir}}/add-secret-ownership.py" \
            "${{owner_skill}}" "${{release_name}}" "${{namespace}}" "${{secret_name}}"
}}
if [[ -n "${{ownership}}" ]]; then
    kubectl {kube_prefix}auth can-i update secrets --namespace "${{namespace}}" | grep -qx 'yes' || {{
        echo "ERROR: current Kubernetes identity cannot update the owned Collector Secret." >&2
        exit 1
    }}
    render_secret_manifest \
        | python3 "${{script_dir}}/k8s-object-preconditions.py" bind-manifest \
            "${{existing_uid}}" "${{existing_resource_version}}" \
        | kubectl {kube_prefix}replace -f -
else
    kubectl {kube_prefix}auth can-i create secrets --namespace "${{namespace}}" | grep -qx 'yes' || {{
        echo "ERROR: current Kubernetes identity cannot create the Collector Secret." >&2
        exit 1
    }}
    render_secret_manifest | kubectl {kube_prefix}create -f -
fi

revision="$(date -u +%Y%m%dT%H%M%SZ)-$$-$RANDOM"
revision_tmp="$(mktemp "${{script_dir}}/.secret-revision-values.XXXXXX")"
printf '{{"agent":{{"podAnnotations":{{"splunk.com/secret-revision":"%s"}}}},"clusterReceiver":{{"podAnnotations":{{"splunk.com/secret-revision":"%s"}}}},"gateway":{{"podAnnotations":{{"splunk.com/secret-revision":"%s"}}}}}}\n' \
    "${{revision}}" "${{revision}}" "${{revision}}" > "${{revision_tmp}}"
chmod 644 "${{revision_tmp}}"
python3 "${{script_dir}}/verify-secret-revision.py" "${{revision_tmp}}"
mv "${{revision_tmp}}" "${{script_dir}}/secret-revision-values.yaml"
revision_tmp=""
""",
        executable=True,
    )

    write_text(
        k8s_dir / "secret-revision-values.yaml",
        json.dumps(
            {
                component: {
                    "podAnnotations": {"splunk.com/secret-revision": "rendered"}
                }
                for component in ("agent", "clusterReceiver", "gateway")
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n",
    )

    write_text(
        k8s_dir / "cleanup-secret.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail

[[ "${{SPLUNK_OTEL_CONFIRM_SECRET_DELETE:-}}" == "yes" ]] || {{
    echo "ERROR: Set SPLUNK_OTEL_CONFIRM_SECRET_DELETE=yes after confirming the retained Collector Secret is no longer needed." >&2
    exit 1
}}
script_dir="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
namespace={shell_quote(args.namespace)}
secret_name={shell_quote(secret_name(args.release_name))}
owner_skill={shell_quote(owner_skill)}
release_name={shell_quote(args.release_name)}

command -v kubectl >/dev/null 2>&1 || {{ echo "ERROR: kubectl is required." >&2; exit 1; }}
{kube_context_display}
kubectl {kube_prefix}auth can-i get secrets --namespace "${{namespace}}" | grep -qx 'yes' || {{
    echo "ERROR: current Kubernetes identity cannot inspect retained Secret ownership." >&2
    exit 1
}}
if ! ownership="$(kubectl {kube_prefix}-n "${{namespace}}" get secret "${{secret_name}}" \
    --ignore-not-found -o go-template={shell_quote(ownership_go_template)})"; then
    echo "ERROR: failed to inspect retained Collector Secret ${{namespace}}/${{secret_name}}." >&2
    exit 1
fi
if [[ -z "${{ownership}}" ]]; then
    echo "Collector Secret does not exist: ${{namespace}}/${{secret_name}}"
    exit 0
fi
IFS=$'\t' read -r existing_owner existing_release existing_namespace existing_uid existing_resource_version <<<"${{ownership}}"
[[ "${{existing_owner}}" == "${{owner_skill}}" \
   && "${{existing_release}}" == "${{release_name}}" \
   && "${{existing_namespace}}" == "${{namespace}}" ]] || {{
    echo "ERROR: refusing to delete an unowned Collector Secret: ${{namespace}}/${{secret_name}}" >&2
    exit 1
}}
kubectl {kube_prefix}auth can-i delete secrets --namespace "${{namespace}}" | grep -qx 'yes' || {{
    echo "ERROR: current Kubernetes identity cannot delete the retained Collector Secret." >&2
    exit 1
}}
python3 "${{script_dir}}/k8s-object-preconditions.py" delete-options \
    "${{existing_uid}}" "${{existing_resource_version}}" \
    | kubectl {kube_prefix}delete \
        --raw="/api/v1/namespaces/${{namespace}}/secrets/${{secret_name}}" -f - >/dev/null
echo "Owned Collector Secret deletion accepted with UID/resourceVersion preconditions: ${{namespace}}/${{secret_name}}"
""",
        executable=True,
    )

    write_text(
        k8s_dir / "fetch-chart.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail
umask 022

script_dir="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
cache_dir="${{script_dir}}/cache"
archive="${{cache_dir}}/{CHART_ARCHIVE_NAME}"
expected_sha256={shell_quote(CHART_ARCHIVE_SHA256)}
url={shell_quote(CHART_ARCHIVE_URL)}

hash_file() {{
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{{print $1}}'
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{{print $1}}'
    else
        echo "ERROR: sha256sum or shasum is required for chart verification." >&2
        exit 1
    fi
}}
if [[ -L "${{cache_dir}}" || ( -e "${{cache_dir}}" && ! -d "${{cache_dir}}" ) ]]; then
    echo "ERROR: chart cache must be a real directory: ${{cache_dir}}" >&2
    exit 1
fi
mkdir -p "${{cache_dir}}"
if [[ -e "${{archive}}" ]]; then
    [[ -f "${{archive}}" && ! -L "${{archive}}" ]] || {{
        echo "ERROR: cached chart must be a non-symlink regular file." >&2
        exit 1
    }}
    [[ "$(hash_file "${{archive}}")" == "${{expected_sha256}}" ]] || {{
        echo "ERROR: cached chart archive digest does not match the audited release asset." >&2
        exit 1
    }}
    printf '%s\n' "${{archive}}"
    exit 0
fi
command -v curl >/dev/null 2>&1 || {{ echo "ERROR: curl is required to fetch the pinned chart." >&2; exit 1; }}
temporary="$(mktemp "${{cache_dir}}/.{CHART_ARCHIVE_NAME}.XXXXXX")"
cleanup() {{ rm -f "${{temporary}}"; }}
trap cleanup EXIT
curl -q --proto '=https' --tlsv1.2 -fsSL "${{url}}" -o "${{temporary}}"
[[ "$(hash_file "${{temporary}}")" == "${{expected_sha256}}" ]] || {{
    echo "ERROR: downloaded chart archive digest does not match the audited GitHub asset." >&2
    exit 1
}}
chmod 644 "${{temporary}}"
mv "${{temporary}}" "${{archive}}"
trap - EXIT
[[ "$(hash_file "${{archive}}")" == "${{expected_sha256}}" ]] || {{
    echo "ERROR: chart archive changed during cache publication." >&2
    exit 1
}}
printf '%s\n' "${{archive}}"
""",
        executable=True,
    )

    supply_chain_assets = [
        "fetch-chart.sh",
        fargate_post_renderer_name,
        f"helm-plugins/{fargate_post_renderer_plugin_name}/plugin.yaml",
        f"helm-plugins/{fargate_post_renderer_plugin_name}/run.sh",
        "redact-stream.py",
        "verify-overlay.py",
        "verify-secret-revision.py",
        "k8s-object-preconditions.py",
        "add-secret-ownership.py",
        "verify-overlays.sh",
        "validate-secrets.sh",
        helm_release_guard_name,
    ]
    if instrumentation_guard_name:
        supply_chain_assets.append(instrumentation_guard_name)
    supply_chain_hashes = [sha256_file(k8s_dir / name) for name in supply_chain_assets]
    write_text(
        k8s_dir / "verify-supply-chain.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail
script_dir="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
{bash_array("asset_names", supply_chain_assets)}
{bash_array("asset_hashes", supply_chain_hashes)}
for index in "${{!asset_names[@]}}"; do
    asset="${{script_dir}}/${{asset_names[$index]}}"
    expected="${{asset_hashes[$index]}}"
    [[ -f "${{asset}}" && ! -L "${{asset}}" ]] || {{
        echo "ERROR: Kubernetes supply-chain asset is missing or a symlink: ${{asset_names[$index]}}" >&2
        exit 1
    }}
    if command -v sha256sum >/dev/null 2>&1; then
        actual="$(sha256sum "${{asset}}" | awk '{{print $1}}')"
    elif command -v shasum >/dev/null 2>&1; then
        actual="$(shasum -a 256 "${{asset}}" | awk '{{print $1}}')"
    else
        echo "ERROR: sha256sum or shasum is required for supply-chain verification." >&2
        exit 1
    fi
    [[ "${{actual}}" == "${{expected}}" ]] || {{
        echo "ERROR: Kubernetes supply-chain asset changed after rendering: ${{asset_names[$index]}}" >&2
        exit 1
    }}
done
""",
        executable=True,
    )
    supply_chain_verifier_hash = sha256_file(k8s_dir / "verify-supply-chain.sh")
    supply_chain_guard = f"""
verifier="${{script_dir}}/verify-supply-chain.sh"
[[ -f "${{verifier}}" && ! -L "${{verifier}}" ]] || {{
    echo "ERROR: Kubernetes supply-chain verifier is missing or a symlink." >&2
    exit 1
}}
if command -v sha256sum >/dev/null 2>&1; then
    verifier_sha="$(sha256sum "${{verifier}}" | awk '{{print $1}}')"
elif command -v shasum >/dev/null 2>&1; then
    verifier_sha="$(shasum -a 256 "${{verifier}}" | awk '{{print $1}}')"
else
    echo "ERROR: sha256sum or shasum is required for supply-chain verification." >&2
    exit 1
fi
[[ "${{verifier_sha}}" == {shell_quote(supply_chain_verifier_hash)} ]] || {{
    echo "ERROR: Kubernetes supply-chain verifier changed after rendering." >&2
    exit 1
}}
bash "${{verifier}}"
"""
    create_secret_path = k8s_dir / "create-secret.sh"
    create_secret_text = create_secret_path.read_text(encoding="utf-8")
    create_secret_marker = 'script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
    if create_secret_text.count(create_secret_marker) != 1:
        raise RuntimeError("create-secret.sh integrity insertion point changed")
    write_text(
        create_secret_path,
        create_secret_text.replace(
            create_secret_marker,
            create_secret_marker + supply_chain_guard,
            1,
        ),
        executable=True,
    )
    helm_context_line = ""
    if args.kube_context:
        helm_context_line = f"    --kube-context {shell_quote(args.kube_context)} \\\n"
    status_context = f"--context {shell_quote(args.kube_context)} " if args.kube_context else ""
    # Helm uses --kube-context, whereas kubectl uses --context.
    helm_status_context = f" --kube-context {shell_quote(args.kube_context)}" if args.kube_context else ""
    helm_release_metadata_template = shell_quote(
        '{{.Release.Name}}{{"\\t"}}{{.Release.Namespace}}{{"\\t"}}'
        '{{.Release.Version}}{{"\\t"}}{{.Release.Info.Status}}{{"\\t"}}'
        '{{.Release.Chart.Metadata.Name}}{{"\\t"}}{{.Release.Chart.Metadata.Version}}'
    )
    helm_release_description_template = shell_quote("{{.Release.Info.Description}}")
    helm_release_query_function = f"""
query_helm_release() {{
    local absent_policy="$1"
    local expected_revision="$2"
    shift 2
    local guard_args=()
    local list_record revision _list_status _list_chart
    local status
    if [[ "${{absent_policy}}" == "allow-absent" ]]; then
        guard_args+=(--allow-absent)
    elif [[ "${{absent_policy}}" != "require-present" ]]; then
        echo "ERROR: invalid Helm release absence policy." >&2
        return 1
    fi
    if [[ "${{expected_revision}}" != "any" ]]; then
        [[ "${{expected_revision}}" =~ ^[1-9][0-9]*$ ]] || {{
            echo "ERROR: invalid expected Helm release revision." >&2
            return 1
        }}
        guard_args+=(--expected-revision "${{expected_revision}}")
    fi
    for status in "$@"; do
        guard_args+=(--allowed-status "${{status}}")
    done
    list_record="$("${{helm_command[@]}}" list --namespace "${{namespace}}" \
        --deployed --failed --pending --uninstalled --superseded --uninstalling \
        --filter "^${{release_name}}$" --max 256 --output json{helm_status_context} \
        | python3 "${{script_dir}}/{helm_release_guard_name}" "${{guard_args[@]}}")" || return 1
    if [[ "${{list_record}}" == "absent" ]]; then
        printf '%s\n' absent
        return 0
    fi
    IFS=$'\t' read -r revision _list_status _list_chart <<<"${{list_record}}"
    [[ "${{revision}}" =~ ^[1-9][0-9]*$ ]] || {{
        echo "ERROR: Helm release list returned an invalid guarded revision." >&2
        return 1
    }}
    "${{helm_command[@]}}" get all "${{release_name}}" \
        --namespace "${{namespace}}" \
        --template {helm_release_metadata_template}{helm_status_context} \
        | python3 "${{script_dir}}/{helm_release_guard_name}" \
            --metadata "${{guard_args[@]}}"
}}
"""
    values_args = ['    -f "${script_dir}/values.yaml"']
    values_args.extend(f'    -f "${{script_dir}}/{name}"' for name in extra_values_names)
    values_args.append('    -f "${script_dir}/secret-revision-values.yaml"')
    values_args_block = " \\\n".join(values_args)

    preflight_values_args = ['    -f "${script_dir}/values.yaml"']
    preflight_values_args.extend(f'    -f "${{script_dir}}/{name}"' for name in extra_values_names)
    preflight_values_args.append('    -f "${script_dir}/secret-revision-values.yaml"')
    preflight_values_block = " \\\n".join(preflight_values_args)
    preflight_helm_context = (
        f"    --kube-context {shell_quote(args.kube_context)} \\\n" if args.kube_context else ""
    )
    fargate_post_renderer_preflight = ""
    fargate_post_renderer_verify = ""
    helm_post_renderer_setup = """helm_command=(helm)
post_renderer_args=()
"""
    if fargate_post_renderer_name:
        helm_post_renderer_setup = f"""python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 8) else "ERROR: Python 3.8 or newer is required for Kubernetes image policy")'
helm_version="$(helm version --template '{{{{.Version}}}}')"
if [[ "${{helm_version}}" =~ ^v?([0-9]+)\\.([0-9]+)(\\.|$) ]]; then
    helm_major="${{BASH_REMATCH[1]}}"
    helm_minor="${{BASH_REMATCH[2]}}"
else
    echo "ERROR: could not determine Helm major/minor version from: ${{helm_version}}" >&2
    exit 1
fi
if (( helm_major == 4 )); then
    helm_command=(env "HELM_PLUGINS=${{script_dir}}/helm-plugins" helm)
    post_renderer_args=(--post-renderer {shell_quote(fargate_post_renderer_plugin_name)})
elif (( helm_major == 3 && helm_minor >= 9 )); then
    helm_command=(helm)
    post_renderer_args=(--post-renderer "${{script_dir}}/{fargate_post_renderer_name}")
else
    echo "ERROR: the pinned chart requires Helm 3.9+ or Helm 4; found ${{helm_version}}" >&2
    exit 1
fi
"""
        fargate_post_renderer_preflight = f"""
[[ -f "${{script_dir}}/{fargate_post_renderer_name}" && ! -L "${{script_dir}}/{fargate_post_renderer_name}" && -x "${{script_dir}}/{fargate_post_renderer_name}" ]] || {{
    echo "ERROR: the audited Kubernetes image post-renderer is missing, a symlink, or not executable." >&2
    exit 1
}}
[[ -f "${{script_dir}}/helm-plugins/{fargate_post_renderer_plugin_name}/plugin.yaml" && ! -L "${{script_dir}}/helm-plugins/{fargate_post_renderer_plugin_name}/plugin.yaml" ]] || {{
    echo "ERROR: the local Helm 4 image post-renderer plugin manifest is missing or a symlink." >&2
    exit 1
}}
[[ -f "${{script_dir}}/helm-plugins/{fargate_post_renderer_plugin_name}/run.sh" && ! -L "${{script_dir}}/helm-plugins/{fargate_post_renderer_plugin_name}/run.sh" && -x "${{script_dir}}/helm-plugins/{fargate_post_renderer_plugin_name}/run.sh" ]] || {{
    echo "ERROR: the local Helm 4 post-renderer plugin launcher is missing, a symlink, or not executable." >&2
    exit 1
}}
"""
        fargate_post_renderer_verify = f"""
python3 "${{script_dir}}/{fargate_post_renderer_name}" --verify "${{rendered_manifest}}"
"""
    certmanager_preflight = ""
    if str_bool(args.enable_certmanager):
        certmanager_preflight = f"""
for crd in certificates.cert-manager.io issuers.cert-manager.io; do
    kubectl {kube_prefix}get crd "${{crd}}" >/dev/null || {{
        echo "ERROR: --enable-certmanager requires an existing cert-manager installation (${{crd}} missing)." >&2
        exit 1
    }}
done
"""
    external_operator_crd_preflight = ""
    if str_bool(args.enable_autoinstrumentation) and not str_bool(args.enable_operator_crds):
        external_operator_crd_preflight = f"""
kubectl {kube_prefix}get crd instrumentations.opentelemetry.io >/dev/null || {{
    echo "ERROR: auto-instrumentation with CRD installation disabled requires instrumentations.opentelemetry.io." >&2
    exit 1
}}
"""
    target_allocator_preflight = ""
    if str_bool(args.target_allocator_enabled):
        target_allocator_preflight = f"""
for crd in servicemonitors.monitoring.coreos.com podmonitors.monitoring.coreos.com; do
    kubectl {kube_prefix}get crd "${{crd}}" >/dev/null || {{
        echo "ERROR: Target Allocator requires Prometheus Operator CRD ${{crd}}." >&2
        exit 1
    }}
done
"""
    obi_preflight = ""
    if str_bool(args.enable_obi):
        obi_preflight = f"""
kubectl {kube_prefix}version -o json | python3 -c '
import json, re, sys
data = json.load(sys.stdin)
minor = re.match(r"[0-9]+", str(data["serverVersion"]["minor"]))
if not minor or int(minor.group(0)) < 24:
    raise SystemExit("ERROR: OBI requires Kubernetes 1.24 or newer")
'
kubectl {kube_prefix}get nodes -o json | python3 -c '
import json, re, sys
nodes = json.load(sys.stdin).get("items", [])
eligible = []
ineligible = []
for node in nodes:
    info = node.get("status", {{}}).get("nodeInfo", {{}})
    if info.get("operatingSystem") != "linux":
        continue
    node_name = node.get("metadata", {{}}).get("name", "unknown")
    if info.get("architecture") not in {{"amd64", "arm64"}}:
        ineligible.append(f"{{node_name}}:unsupported-architecture")
        continue
    version = re.match(r"([0-9]+)\\.([0-9]+)", str(info.get("kernelVersion", "")))
    if not version:
        ineligible.append(f"{{node_name}}:unknown-kernel")
        continue
    major_minor = (int(version.group(1)), int(version.group(2)))
    os_image = str(info.get("osImage", "")).lower()
    rhel_family = any(name in os_image for name in ("red hat", "rhel", "rocky", "alma", "oracle linux"))
    if major_minor >= (5, 8) or (rhel_family and major_minor >= (4, 18)):
        eligible.append(node_name)
    else:
        ineligible.append("{{}}:kernel-{{}}".format(node_name, info.get("kernelVersion", "unknown")))
if not eligible:
    raise SystemExit("ERROR: OBI requires an eligible Linux amd64/arm64 node with kernel >=5.8 (or RHEL >=4.18)")
if ineligible:
    raise SystemExit("ERROR: OBI DaemonSet would schedule to ineligible Linux nodes: " + ", ".join(ineligible))
'
"""
    network_explorer_preflight = ""
    if str_bool(args.network_explorer_enabled):
        network_explorer_preflight = f"""
kubectl {kube_prefix}version -o json | python3 -c '
import json, re, sys
data = json.load(sys.stdin)
major = int(str(data["serverVersion"].get("major", "0")))
minor_match = re.match(r"[0-9]+", str(data["serverVersion"].get("minor", "")))
minor = int(minor_match.group(0)) if minor_match else -1
if (major, minor) < (1, 24):
    raise SystemExit("ERROR: Network Explorer requires Kubernetes 1.24 or newer")
'
"""
    kubectl_skew_preflight = ""
    if str_bool(args.enable_autoinstrumentation) and str_bool(args.instrumentation_installation_job):
        job_kubectl_minor = int(args.instrumentation_kubectl_image_tag.split(".")[1])
        kubectl_skew_preflight = f"""
command -v python3 >/dev/null 2>&1 || {{
    echo "ERROR: python3 is required to validate instrumentation Job kubectl skew." >&2
    exit 1
}}
server_minor="$(kubectl {kube_prefix}version -o json | python3 -c 'import json,re,sys; value=str(json.load(sys.stdin)["serverVersion"]["minor"]); match=re.match(r"[0-9]+", value); print(match.group(0) if match else "")')"
[[ "${{server_minor}}" =~ ^[0-9]+$ ]] || {{
    echo "ERROR: could not determine the Kubernetes server minor version." >&2
    exit 1
}}
if (( server_minor < {job_kubectl_minor} - 1 || server_minor > {job_kubectl_minor} + 1 )); then
    echo "ERROR: instrumentation Job kubectl {args.instrumentation_kubectl_image_tag} must be within one minor of Kubernetes server 1.${{server_minor}}." >&2
    exit 1
fi
"""
    instrumentation_resource_mode_preflight = ""
    if str_bool(args.enable_autoinstrumentation) and not str_bool(args.instrumentation_installation_job):
        instrumentation_resource_mode_preflight = """
if (( helm_major >= 4 )) && [[ "${release_preflight}" == "absent" ]]; then
    echo "ERROR: Helm 4 cannot safely first-install the Instrumentation CR in resource mode because the operator webhook is registered before it is ready. Re-enable --instrumentation-installation-job or use the upstream reviewed two-step install." >&2
    exit 1
fi
"""
    secret_rbac_preflight = ""
    if external_secret_required:
        secret_rbac_preflight = f"""
if [[ "${{namespace_exists}}" == "false" ]]; then
    kubectl {kube_prefix}auth can-i create secrets --namespace "${{namespace}}" | grep -qx 'yes' || {{
        echo "ERROR: current Kubernetes identity cannot create the retained Secret in the new namespace ${{namespace}}." >&2
        exit 1
    }}
else
kubectl {kube_prefix}auth can-i get secrets --namespace "${{namespace}}" | grep -qx 'yes' || {{
    echo "ERROR: current Kubernetes identity cannot get the retained Secret in namespace ${{namespace}}." >&2
    exit 1
}}
if ! ownership="$(kubectl {kube_prefix}-n "${{namespace}}" get secret {shell_quote(secret_name(args.release_name))} \
    --ignore-not-found -o go-template={shell_quote(ownership_go_template)})"; then
    echo "ERROR: failed to determine whether retained Collector Secret {secret_name(args.release_name)} exists." >&2
    exit 1
fi
if [[ -n "${{ownership}}" ]]; then
    IFS=$'\t' read -r existing_owner existing_release existing_namespace _existing_uid _existing_resource_version <<<"${{ownership}}"
    [[ "${{existing_owner}}" == {shell_quote(owner_skill)} \
       && "${{existing_release}}" == {shell_quote(args.release_name)} \
       && "${{existing_namespace}}" == "${{namespace}}" ]] || {{
        echo "ERROR: refusing to adopt or overwrite an unowned Collector Secret: {secret_name(args.release_name)}" >&2
        exit 1
    }}
    kubectl {kube_prefix}auth can-i patch secrets --namespace "${{namespace}}" | grep -qx 'yes' || {{
        echo "ERROR: current Kubernetes identity cannot patch the retained Secret in namespace ${{namespace}}." >&2
        exit 1
    }}
else
    kubectl {kube_prefix}auth can-i create secrets --namespace "${{namespace}}" | grep -qx 'yes' || {{
        echo "ERROR: current Kubernetes identity cannot create secrets in namespace ${{namespace}}." >&2
        exit 1
    }}
fi
fi
"""
    instrumentation_ownership_preflight = ""
    if job_owned_instrumentation:
        instrumentation_ownership_preflight = f"""
if ! instrumentation_resources="$(kubectl {kube_prefix}api-resources --api-group=opentelemetry.io -o name)"; then
    echo "ERROR: Kubernetes API discovery failed while checking Instrumentation ownership." >&2
    exit 1
fi
if grep -qx 'instrumentations.opentelemetry.io' <<<"${{instrumentation_resources}}"; then
    kubectl {kube_prefix}auth can-i get instrumentations.opentelemetry.io --namespace "${{namespace}}" | grep -qx 'yes' || {{
        echo "ERROR: current Kubernetes identity cannot inspect existing Instrumentation ownership." >&2
        exit 1
    }}
    if ! instrumentation_state="$(kubectl {kube_prefix}-n "${{namespace}}" get instrumentation {shell_quote(collector_fullname)} --ignore-not-found -o json)"; then
        echo "ERROR: failed to inspect existing Instrumentation {args.namespace}/{collector_fullname}." >&2
        exit 1
    fi
    if [[ -n "${{instrumentation_state}}" ]]; then
        printf '%s' "${{instrumentation_state}}" | python3 "${{script_dir}}/{instrumentation_guard_name}" --verify-owned
    fi
fi
"""
    write_text(
        k8s_dir / "preflight.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
namespace={shell_quote(args.namespace)}
release_name={shell_quote(args.release_name)}

for command in helm kubectl python3; do
    command -v "${{command}}" >/dev/null 2>&1 || {{
        echo "ERROR: required command not found: ${{command}}" >&2
        exit 1
    }}
done
{helm_post_renderer_setup}
{helm_release_query_function}
{fargate_post_renderer_preflight}
{supply_chain_guard}

bash "${{script_dir}}/verify-overlays.sh"
chart_archive="$(bash "${{script_dir}}/fetch-chart.sh")"
release_preflight="$(query_helm_release allow-absent any deployed)"
echo "Helm release ownership preflight: ${{release_preflight}}"
{instrumentation_resource_mode_preflight}

rendered_manifest="$(mktemp)"
trap 'rm -f "${{rendered_manifest}}"' EXIT
"${{helm_command[@]}}" template "${{release_name}}" "${{chart_archive}}" \\
    --namespace "${{namespace}}" \\
{preflight_helm_context}    "${{post_renderer_args[@]}}" \\
{preflight_values_block} > "${{rendered_manifest}}"
[[ -s "${{rendered_manifest}}" ]] || {{ echo "ERROR: helm template produced no resources." >&2; exit 1; }}
{fargate_post_renderer_verify}

kubectl {kube_prefix}cluster-info >/dev/null
{kubectl_skew_preflight}
{certmanager_preflight}
{external_operator_crd_preflight}
{target_allocator_preflight}
{obi_preflight}
{network_explorer_preflight}
{instrumentation_ownership_preflight}
namespace_exists=unknown
if kubectl {kube_prefix}auth can-i get namespaces | grep -qx 'yes'; then
    if ! kubectl {kube_prefix}get namespace "${{namespace}}" >/dev/null 2>&1; then
        namespace_exists=false
        kubectl {kube_prefix}auth can-i create namespaces | grep -qx 'yes' || {{
            echo "ERROR: namespace ${{namespace}} does not exist and the current identity cannot create it." >&2
            exit 1
        }}
    else
        namespace_exists=true
    fi
else
    echo "WARN: cannot read cluster-scoped Namespaces; assuming ${{namespace}} already exists." >&2
fi
{secret_rbac_preflight}
echo "Kubernetes preflight passed; chart values rendered successfully."
""",
        executable=True,
    )

    instrumentation_install_guard = ""
    instrumentation_install_commit = ""
    if job_owned_instrumentation:
        instrumentation_install_guard = f"""
umask 077
instrumentation_state_dir="$(mktemp -d "${{TMPDIR:-/tmp}}/splunk-otel-instrumentation.XXXXXX")"
chmod 700 "${{instrumentation_state_dir}}"
instrumentation_snapshot="${{instrumentation_state_dir}}/prestate.json"
instrumentation_current="${{instrumentation_state_dir}}/current.json"
instrumentation_restore="${{instrumentation_state_dir}}/restore.json"
helm_prior_manifest="${{instrumentation_state_dir}}/helm-prior-manifest.yaml"
helm_current_manifest="${{instrumentation_state_dir}}/helm-current-manifest.yaml"
instrumentation_prestate=absent
helm_mutation_started=false
helm_command_succeeded=false
helm_mutation_committed=false
retain_instrumentation_snapshot=false

capture_helm_prestate() {{
    if [[ "${{install_release_record}}" == "absent" ]]; then
        helm_prior_state=absent
        helm_prior_revision=0
        helm_expected_revision=1
        return 0
    fi
    IFS=$'\t' read -r helm_prior_revision helm_prior_status helm_prior_chart helm_prior_chart_version \
        <<<"${{install_release_record}}"
    [[ "${{helm_prior_status}}" == "deployed" \
       && "${{helm_prior_revision}}" =~ ^[1-9][0-9]*$ \
       && "${{helm_prior_chart}}" == {shell_quote(CHART_NAME)} \
       && -n "${{helm_prior_chart_version}}" ]] || return 1
    helm_prior_state=present
    helm_expected_revision=$((helm_prior_revision + 1))
}}

discover_instrumentation_api() {{
    kubectl {kube_prefix}api-resources --api-group=opentelemetry.io -o name
}}

capture_instrumentation_prestate() {{
    local resources
    resources="$(discover_instrumentation_api)" || {{
        echo "ERROR: Kubernetes API discovery failed before Helm mutation." >&2
        return 1
    }}
    if ! grep -qx 'instrumentations.opentelemetry.io' <<<"${{resources}}"; then
        : > "${{instrumentation_snapshot}}"
        return 0
    fi
    kubectl {kube_prefix}auth can-i get instrumentations.opentelemetry.io --namespace "${{namespace}}" | grep -qx 'yes' || {{
        echo "ERROR: current Kubernetes identity cannot capture Instrumentation prestate." >&2
        return 1
    }}
    kubectl {kube_prefix}-n "${{namespace}}" get instrumentation {shell_quote(collector_fullname)} \
        --ignore-not-found -o json > "${{instrumentation_current}}" || {{
        echo "ERROR: failed to capture Instrumentation prestate." >&2
        return 1
    }}
    if [[ -s "${{instrumentation_current}}" ]]; then
        python3 "${{script_dir}}/{instrumentation_guard_name}" --sanitize-snapshot \
            < "${{instrumentation_current}}" > "${{instrumentation_snapshot}}"
        instrumentation_prestate=present
    else
        : > "${{instrumentation_snapshot}}"
    fi
}}

rollback_instrumentation() {{
    local resources
    echo "Install did not pass its postconditions; restoring the pre-install Instrumentation state." >&2
    resources="$(discover_instrumentation_api)" || return 1
    if ! grep -qx 'instrumentations.opentelemetry.io' <<<"${{resources}}"; then
        [[ "${{instrumentation_prestate}}" == "absent" ]]
        return 0
    fi
    kubectl {kube_prefix}-n "${{namespace}}" get instrumentation {shell_quote(collector_fullname)} \
        --ignore-not-found -o json > "${{instrumentation_current}}" || return 1
    if [[ "${{instrumentation_prestate}}" == "absent" ]]; then
        if [[ -s "${{instrumentation_current}}" ]]; then
            python3 "${{script_dir}}/{instrumentation_guard_name}" --verify-owned \
                < "${{instrumentation_current}}" || return 1
            kubectl {kube_prefix}auth can-i delete instrumentations.opentelemetry.io --namespace "${{namespace}}" | grep -qx 'yes' || return 1
            python3 "${{script_dir}}/{instrumentation_guard_name}" \
                --delete-options Instrumentation {shell_quote(collector_fullname)} \
                < "${{instrumentation_current}}" \
                | kubectl {kube_prefix}delete \
                    --raw="/apis/opentelemetry.io/v1alpha1/namespaces/${{namespace}}/instrumentations/{collector_fullname}" \
                    -f - >/dev/null || return 1
        fi
        return 0
    fi
    if [[ -s "${{instrumentation_current}}" ]]; then
        python3 "${{script_dir}}/{instrumentation_guard_name}" \
            --prepare-replace "${{instrumentation_snapshot}}" \
            < "${{instrumentation_current}}" > "${{instrumentation_restore}}" || return 1
        kubectl {kube_prefix}-n "${{namespace}}" replace -f "${{instrumentation_restore}}" >/dev/null || return 1
    else
        kubectl {kube_prefix}-n "${{namespace}}" create -f "${{instrumentation_snapshot}}" >/dev/null || return 1
    fi
}}

rollback_helm_mutation() {{
    local current_record current_revision current_status current_chart current_chart_version
    current_record="$(query_helm_release require-present "${{helm_expected_revision}}" deployed)" || return 1
    IFS=$'\t' read -r current_revision current_status current_chart current_chart_version <<<"${{current_record}}"
    [[ "${{current_revision}}" == "${{helm_expected_revision}}" \
       && "${{current_status}}" == "deployed" \
       && "${{current_chart}}" == {shell_quote(CHART_NAME)} \
       && -n "${{current_chart_version}}" ]] || return 1
    if [[ "${{helm_prior_state}}" == "absent" ]]; then
        echo "Post-install validation failed; uninstalling the newly created Helm release." >&2
        "${{helm_command[@]}}" uninstall "${{release_name}}" \
            --namespace "${{namespace}}" --wait --timeout 10m{helm_status_context}
        return
    fi
    echo "Post-install validation failed; rolling Helm back to prior revision ${{helm_prior_revision}}." >&2
    "${{helm_command[@]}}" rollback "${{release_name}}" "${{helm_prior_revision}}" \
        --namespace "${{namespace}}" --wait --timeout 10m --cleanup-on-fail \
        --history-max 10{helm_status_context}
}}

prove_helm_prestate_after_failed_command() {{
    local current_record current_revision current_status current_chart current_chart_version rollback_description
    if [[ "${{helm_prior_state}}" == "absent" ]]; then
        current_record="$(query_helm_release allow-absent any \
            deployed failed pending-install pending-upgrade pending-rollback \
            superseded uninstalled uninstalling)" || return 1
        [[ "${{current_record}}" == "absent" ]] || {{
            echo "ERROR: failed new-release mutation left a Helm release record behind." >&2
            return 1
        }}
        return 0
    fi

    current_record="$(query_helm_release require-present any deployed)" || return 1
    IFS=$'\t' read -r current_revision current_status current_chart current_chart_version \
        <<<"${{current_record}}"
    [[ "${{current_status}}" == "deployed" \
       && "${{current_chart}}" == {shell_quote(CHART_NAME)} \
       && -n "${{current_revision}}" \
       && "${{current_chart_version}}" == "${{helm_prior_chart_version}}" ]] || return 1
    if [[ "${{current_revision}}" == "${{helm_prior_revision}}" ]]; then
        : # Helm failed before recording a new revision.
    elif [[ "${{current_revision}}" == "$((helm_prior_revision + 2))" ]]; then
        rollback_description="$("${{helm_command[@]}}" get all "${{release_name}}" \
            --namespace "${{namespace}}" \
            --template {helm_release_description_template}{helm_status_context})" || return 1
        [[ "${{rollback_description}}" == "Rollback to ${{helm_prior_revision}}" ]] || {{
            echo "ERROR: expected Helm's atomic rollback description for revision ${{helm_prior_revision}}." >&2
            return 1
        }}
    else
        echo "ERROR: Helm atomic failure ended at unexpected revision ${{current_revision}} (prior ${{helm_prior_revision}})." >&2
        return 1
    fi
    "${{helm_command[@]}}" get manifest "${{release_name}}" \
        --namespace "${{namespace}}" --revision "${{helm_prior_revision}}"{helm_status_context} \
        > "${{helm_prior_manifest}}" || return 1
    "${{helm_command[@]}}" get manifest "${{release_name}}" \
        --namespace "${{namespace}}"{helm_status_context} \
        > "${{helm_current_manifest}}" || return 1
    python3 - "${{helm_prior_manifest}}" "${{helm_current_manifest}}" <<'PY'
import hashlib
import sys


def digest(path):
    value = hashlib.sha256()
    with open(path, "rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            value.update(chunk)
    return value.digest()


if digest(sys.argv[1]) != digest(sys.argv[2]):
    raise SystemExit("ERROR: Helm atomic failure did not restore the prior release manifest")
PY
}}

cleanup_instrumentation_state() {{
    local cause="$1" rc=$?
    trap - EXIT HUP INT TERM
    if [[ "${{cause}}" != "EXIT" && "${{rc}}" -eq 0 ]]; then
        rc=1
    fi
    if [[ "${{helm_mutation_started}}" == "true" && "${{helm_mutation_committed}}" != "true" ]]; then
        helm_prestate_restored=true
        if [[ "${{helm_command_succeeded}}" == "true" ]]; then
            if ! rollback_helm_mutation; then
                helm_prestate_restored=false
                retain_instrumentation_snapshot=true
                rc=1
                echo "ERROR: automatic Helm release rollback was refused or failed; a concurrent revision may exist. Retain the mode-600 recovery snapshot at ${{instrumentation_snapshot}}." >&2
            fi
        elif ! prove_helm_prestate_after_failed_command; then
            helm_prestate_restored=false
            retain_instrumentation_snapshot=true
            rc=1
            echo "ERROR: Helm --atomic did not prove restoration of the prior release state. Retain the mode-600 recovery snapshot at ${{instrumentation_snapshot}}." >&2
        fi
        if [[ "${{helm_prestate_restored}}" == "true" ]] && ! rollback_instrumentation; then
            retain_instrumentation_snapshot=true
            rc=1
            echo "ERROR: automatic Instrumentation rollback failed; retain the mode-600 recovery snapshot at ${{instrumentation_snapshot}}." >&2
        elif [[ "${{helm_prestate_restored}}" != "true" ]]; then
            echo "ERROR: Instrumentation restoration was skipped to avoid mixing it with an unverified Helm revision." >&2
        fi
    fi
    rm -f -- "${{instrumentation_current}}" "${{instrumentation_restore}}" \
        "${{helm_prior_manifest}}" "${{helm_current_manifest}}"
    if [[ "${{retain_instrumentation_snapshot}}" == "true" ]]; then
        chmod 600 "${{instrumentation_snapshot}}" 2>/dev/null || true
    else
        rm -rf -- "${{instrumentation_state_dir}}"
    fi
    exit "${{rc}}"
}}

trap 'cleanup_instrumentation_state EXIT' EXIT
trap 'cleanup_instrumentation_state HUP' HUP
trap 'cleanup_instrumentation_state INT' INT
trap 'cleanup_instrumentation_state TERM' TERM
capture_helm_prestate
capture_instrumentation_prestate
helm_mutation_started=true
"""
        instrumentation_install_commit = f"""
helm_command_succeeded=true
query_helm_release require-present "${{helm_expected_revision}}" deployed >/dev/null
if ! instrumentation_resources="$(discover_instrumentation_api)" || \
   ! grep -qx 'instrumentations.opentelemetry.io' <<<"${{instrumentation_resources}}"; then
    echo "ERROR: Instrumentation API is unavailable after Helm reported success." >&2
    exit 1
fi
kubectl {kube_prefix}-n "${{namespace}}" get instrumentation {shell_quote(collector_fullname)} -o json \
    > "${{instrumentation_current}}"
python3 "${{script_dir}}/{instrumentation_guard_name}" --verify-owned \
    < "${{instrumentation_current}}"
helm_mutation_committed=true
"""

    install_release_query = (
        'install_release_record="$(query_helm_release allow-absent any deployed)"'
        if job_owned_instrumentation
        else "query_helm_release allow-absent any deployed >/dev/null"
    )

    write_text(
        k8s_dir / "helm-install.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
namespace={shell_quote(args.namespace)}
release_name={shell_quote(args.release_name)}
{helm_post_renderer_setup}
{helm_release_query_function}
{supply_chain_guard}

bash "${{script_dir}}/verify-overlays.sh"
chart_archive="$(bash "${{script_dir}}/fetch-chart.sh")"
{install_release_query}
{instrumentation_install_guard}
"${{helm_command[@]}}" upgrade --install "${{release_name}}" "${{chart_archive}}" \\
    --namespace "${{namespace}}" \\
    --atomic \\
    --wait \\
    --timeout 10m \\
    --history-max 10 \\
{helm_context_line}    "${{post_renderer_args[@]}}" \\
{values_args_block}
{instrumentation_install_commit}
""",
        executable=True,
    )

    gateway_enabled = effective_gateway_enabled(args)
    agent_enabled = str_bool(args.agent_enabled) and args.distribution != "eks/fargate"
    cluster_receiver_kind = "statefulset" if args.distribution == "eks/fargate" else "deployment"
    collector_fullname = helm_fullname(args.release_name, CHART_NAME)
    operator_resource_name = operator_fullname(args.release_name)
    target_allocator_resource_name = f"{target_allocator_fullname(args.release_name)}-ta"
    obi_resource_name = obi_fullname(args.release_name)
    cluster_receiver_fullname = cluster_receiver_name(collector_fullname, args.distribution)
    instrumentation_status_variables = ""
    instrumentation_check = ""
    if str_bool(args.enable_autoinstrumentation):
        instrumentation_status_variables = (
            f"operator_name={shell_quote(operator_resource_name)}\n"
            f"instrumentation_name={shell_quote(collector_fullname)}"
        )
        instrumentation_check = f"""
kubectl {status_context}-n "${{namespace}}" rollout status \\
    "deployment/${{operator_name}}" --timeout=180s
if kubectl {status_context}-n "${{namespace}}" get job \\
    "${{instrumentation_name}}-inst-hook" >/dev/null 2>&1; then
    kubectl {status_context}-n "${{namespace}}" wait --for=condition=Complete \\
        "job/${{instrumentation_name}}-inst-hook" --timeout=180s
fi
kubectl {status_context}-n "${{namespace}}" get instrumentation \\
    "${{instrumentation_name}}" >/dev/null
"""
        if job_owned_instrumentation:
            instrumentation_check += f"""
kubectl {status_context}-n "${{namespace}}" get instrumentation \\
    "${{instrumentation_name}}" -o json | \\
    python3 "${{script_dir}}/{instrumentation_guard_name}" --verify-owned
"""
    optional_component_checks = ""
    if str_bool(args.target_allocator_enabled):
        optional_component_checks += f"""
kubectl {status_context}-n "${{namespace}}" rollout status \\
    "deployment/{target_allocator_resource_name}" --timeout=180s
"""
    if str_bool(args.enable_obi):
        optional_component_checks += f"""
kubectl {status_context}-n "${{namespace}}" rollout status \\
    "daemonset/{obi_resource_name}" --timeout=180s
"""
    image_status_checks = ""
    checked_image_objects: set[tuple[str, str]] = set()
    for target in image_targets:
        identity_key = (target["kind"], target["name"])
        if identity_key in checked_image_objects:
            continue
        checked_image_objects.add(identity_key)
        image_status_checks += f"""
if ! kubectl {status_context}-n "${{namespace}}" get {target['kind'].lower()} {shell_quote(target['name'])} -o json 2>/dev/null | \\
    python3 "${{script_dir}}/{fargate_post_renderer_name}" --verify-object-json {shell_quote(target['kind'])} {shell_quote(target['name'])} \\
        >/dev/null 2>&1; then
    echo "ERROR: live Kubernetes workload image verification failed; verifier output suppressed." >&2
    exit 1
fi
"""
    if str_bool(args.enable_autoinstrumentation):
        image_status_checks += f"""
if ! kubectl {status_context}-n "${{namespace}}" get instrumentation "${{instrumentation_name}}" -o json 2>/dev/null | \\
    python3 "${{script_dir}}/{fargate_post_renderer_name}" --verify-object-json Instrumentation "${{instrumentation_name}}" \\
        >/dev/null 2>&1; then
    echo "ERROR: live Kubernetes workload image verification failed; verifier output suppressed." >&2
    exit 1
fi
"""
    write_text(
        k8s_dir / "status.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail

namespace={shell_quote(args.namespace)}
release_name={shell_quote(args.release_name)}
collector_name={shell_quote(collector_fullname)}
script_dir="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
cluster_receiver_name={shell_quote(cluster_receiver_fullname)}
{instrumentation_status_variables}
helm_command=(helm)
{helm_release_query_function}
{supply_chain_guard}

command -v python3 >/dev/null 2>&1 || {{
    echo "ERROR: python3 is required to validate kubectl version skew." >&2
    exit 1
}}
kubectl {status_context}version -o json | python3 -c '
import json, re, sys
payload = json.load(sys.stdin)
def component(value, label):
    if str(value.get("major")) != "1":
        raise SystemExit("ERROR: %s major version is not Kubernetes 1.x" % label)
    match = re.match(r"^[0-9]+", str(value.get("minor") or ""))
    if not match:
        raise SystemExit("ERROR: %s minor version is invalid" % label)
    return int(match.group())
client_minor = component(payload.get("clientVersion") or {{}}, "kubectl")
server_minor = component(payload.get("serverVersion") or {{}}, "kube-apiserver")
if abs(client_minor - server_minor) > 1:
    raise SystemExit(
        "ERROR: kubectl 1.%d is outside the supported +/-1 minor skew for kube-apiserver 1.%d"
        % (client_minor, server_minor)
    )
'

status_release_record="$(query_helm_release require-present any deployed)"
echo "Helm release ownership status: ${{status_release_record}}"
# Never retain the full Helm status document in a shell variable. Release notes
# can contain customer data and would otherwise be exposed by `bash -x`.
if ! helm status "${{release_name}}" --namespace "${{namespace}}"{helm_status_context} --output json 2>/dev/null | python3 -c '
import json, sys
payload = json.load(sys.stdin)
status = str(((payload.get("info") or {{}}).get("status") or "")).lower()
if status != "deployed":
    raise SystemExit("ERROR: Helm status is not deployed")
' >/dev/null 2>&1; then
    echo "ERROR: Helm status is not a valid deployed release; command output suppressed." >&2
    exit 1
fi
echo "Helm status: deployed"
expected_agent={shell_quote('true' if agent_enabled else 'false')}
expected_gateway={shell_quote('true' if gateway_enabled else 'false')}
expected_cluster_receiver={shell_quote('true' if effective_cluster_receiver_enabled(args) else 'false')}

if [[ "${{expected_agent}}" == "true" ]]; then
    kubectl {status_context}-n "${{namespace}}" rollout status \\
        "daemonset/${{collector_name}}-agent" --timeout=180s
fi
if [[ "${{expected_gateway}}" == "true" ]]; then
    kubectl {status_context}-n "${{namespace}}" rollout status \\
        "deployment/${{collector_name}}" --timeout=180s
fi
if [[ "${{expected_cluster_receiver}}" == "true" ]]; then
    kubectl {status_context}-n "${{namespace}}" rollout status \\
        "{cluster_receiver_kind}/${{cluster_receiver_name}}" --timeout=180s
fi
{image_status_checks}
{instrumentation_check}
{optional_component_checks}
log_file="$(mktemp)"
pod_list="$(mktemp)"
pod_log="$(mktemp)"
pod_json="$(mktemp)"
release_pods="$(mktemp)"
instance_pods="$(mktemp)"
cleanup() {{ rm -f "${{log_file}}" "${{pod_list}}" "${{pod_log}}" "${{pod_json}}" "${{release_pods}}" "${{instance_pods}}"; }}
trap cleanup EXIT

# Primary Collector workloads use the legacy release label, while operator,
# cert-manager, and OBI auxiliaries use app.kubernetes.io/instance. Query both
# selectors without a phase filter so Failed auxiliary Pods cannot disappear
# from the production gate. Successful Job Pods are verified, then excluded
# from active readiness and log checks by the bounded per-Pod verifier.
if ! kubectl {status_context}-n "${{namespace}}" get pods \\
    -l release="${{release_name}}" \\
    -o name \\
    >"${{release_pods}}" 2>/dev/null; then
    echo "ERROR: failed to inventory primary Collector pods; command output suppressed." >&2
    exit 1
fi
if ! kubectl {status_context}-n "${{namespace}}" get pods \\
    -l app.kubernetes.io/instance="${{release_name}}" \\
    -o name \\
    >"${{instance_pods}}" 2>/dev/null; then
    echo "ERROR: failed to inventory auxiliary Collector pods; command output suppressed." >&2
    exit 1
fi
LC_ALL=C sort -u "${{release_pods}}" "${{instance_pods}}" > "${{pod_list}}"
pod_count="$(wc -l < "${{pod_list}}" | tr -d '[:space:]')"
if ! [[ "${{pod_count}}" =~ ^[1-9][0-9]*$ ]]; then
    echo "ERROR: no collector release pods were found for log validation." >&2
    exit 1
fi
active_pod_count=0
completed_job_count=0
while IFS= read -r pod; do
    [[ -n "${{pod}}" ]] || continue
    pod_name="${{pod#pod/}}"
    if [[ "${{pod_name}}" == "${{pod}}" || -z "${{pod_name}}" ]]; then
        echo "ERROR: Collector pod inventory returned an invalid object name." >&2
        exit 1
    fi
    if grep -Fqx -- "${{pod}}" "${{release_pods}}"; then
        pod_membership=primary
    else
        pod_membership=auxiliary
    fi
    : > "${{pod_json}}"
    if ! kubectl {status_context}-n "${{namespace}}" get pod "${{pod_name}}" -o json \\
        >"${{pod_json}}" 2>/dev/null; then
        echo "ERROR: failed to fetch ${{pod}} for validation; command output suppressed." >&2
        exit 1
    fi
    if python3 "${{script_dir}}/{fargate_post_renderer_name}" \\
        --verify-runtime-pod-json "${{pod_name}}" "${{pod_membership}}" \\
        <"${{pod_json}}" >/dev/null 2>&1; then
        active_pod_count=$((active_pod_count + 1))
    else
        pod_verify_rc=$?
        if [[ "${{pod_verify_rc}}" -eq 10 ]]; then
            completed_job_count=$((completed_job_count + 1))
            continue
        fi
        echo "ERROR: Collector pod readiness or image verification failed for ${{pod}}; verifier output suppressed." >&2
        exit 1
    fi
    : > "${{pod_log}}"
    if ! kubectl {status_context}-n "${{namespace}}" logs "${{pod}}" \\
        --all-containers --prefix --tail=200 >"${{pod_log}}" 2>&1; then
        # kubectl may mix arbitrary container output into its failure stream.
        # Never echo it: a general-purpose redactor cannot prove that workload
        # data, signed URLs, or URI userinfo are absent.
        echo "ERROR: failed to retrieve collector release logs for ${{pod}}; command output suppressed." >&2
        exit 1
    fi
    cat "${{pod_log}}" >> "${{log_file}}"
done < "${{pod_list}}"
if ! [[ "${{active_pod_count}}" =~ ^[1-9][0-9]*$ ]]; then
    echo "ERROR: no active Collector pods remained after excluding successful Job pods." >&2
    exit 1
fi
echo "Collector pod validation: ${{active_pod_count}} active, ${{completed_job_count}} completed Job pod(s)"
if grep -Eiq '(^|[^a-z])(panic|fatal|exporting failed|permanent error)([^a-z]|$)' "${{log_file}}"; then
    fatal_count="$(grep -Eic '(^|[^a-z])(panic|fatal|exporting failed|permanent error)([^a-z]|$)' "${{log_file}}" || true)"
    echo "ERROR: collector logs contain ${{fatal_count}} fatal/export pipeline match(es); matched content suppressed." >&2
    exit 1
fi
if grep -Eiq 'dropping datapoint.*number of dimensions is larger than 36' "${{log_file}}"; then
    drop_count="$(grep -Eic 'dropping datapoint.*number of dimensions is larger than 36' "${{log_file}}" || true)"
    echo "ERROR: collector logs confirm ${{drop_count}} metric data-loss match(es) because datapoints exceed the 36-dimension limit; matched content suppressed." >&2
    exit 1
fi
""",
        executable=True,
    )

    instrumentation_uninstall_preflight = ""
    instrumentation_uninstall_cleanup = ""
    if job_owned_instrumentation:
        instrumentation_uninstall_preflight = f"""
instrumentation_state_dir="$(mktemp -d "${{TMPDIR:-/tmp}}/splunk-otel-uninstall.XXXXXX")"
chmod 700 "${{instrumentation_state_dir}}"
instrumentation_state="${{instrumentation_state_dir}}/instrumentation.json"
job_state="${{instrumentation_state_dir}}/job.json"
cleanup_instrumentation_state() {{ rm -rf -- "${{instrumentation_state_dir}}"; }}
trap cleanup_instrumentation_state EXIT HUP INT TERM

capture_instrumentation_uninstall_state() {{
    local resource
    for resource in instrumentations.opentelemetry.io jobs.batch; do
        kubectl {status_context}auth can-i get "${{resource}}" --namespace "${{namespace}}" | grep -qx 'yes' || {{
            echo "ERROR: current Kubernetes identity cannot inspect ${{resource}} ownership for uninstall." >&2
            return 1
        }}
    done
    : > "${{instrumentation_state}}"
    : > "${{job_state}}"
    kubectl {status_context}-n "${{namespace}}" get instrumentation "${{instrumentation_name}}" \
        --ignore-not-found -o json > "${{instrumentation_state}}" || {{
        echo "ERROR: failed to inspect Instrumentation ownership for uninstall." >&2
        return 1
    }}
    kubectl {status_context}-n "${{namespace}}" get job "${{instrumentation_name}}-inst-hook" \
        --ignore-not-found -o json > "${{job_state}}" || {{
        echo "ERROR: failed to inspect Instrumentation hook Job ownership for uninstall." >&2
        return 1
    }}
    if [[ -s "${{instrumentation_state}}" ]]; then
        python3 "${{script_dir}}/{instrumentation_guard_name}" --verify-owned < "${{instrumentation_state}}"
    fi
    if [[ -s "${{job_state}}" ]]; then
        python3 "${{script_dir}}/{instrumentation_guard_name}" --verify-helm-object \
            Job "${{instrumentation_name}}-inst-hook" < "${{job_state}}"
    fi
}}

# Refuse the Helm uninstall before mutation if same-name auxiliary objects are foreign.
capture_instrumentation_uninstall_state
"""
        instrumentation_uninstall_cleanup = f"""
# Helm removal succeeded. Re-read leftovers so delete preconditions bind to the
# post-uninstall object generation; a concurrent replacement fails closed.
capture_instrumentation_uninstall_state
if [[ -s "${{instrumentation_state}}" ]]; then
    kubectl {status_context}auth can-i delete instrumentations.opentelemetry.io --namespace "${{namespace}}" | grep -qx 'yes' || {{
        echo "ERROR: current Kubernetes identity cannot delete the owned Instrumentation." >&2
        exit 1
    }}
    python3 "${{script_dir}}/{instrumentation_guard_name}" \
        --delete-options Instrumentation "${{instrumentation_name}}" \
        < "${{instrumentation_state}}" \
        | kubectl {status_context}delete \
            --raw="/apis/opentelemetry.io/v1alpha1/namespaces/${{namespace}}/instrumentations/${{instrumentation_name}}" \
            -f - >/dev/null
fi
if [[ -s "${{job_state}}" ]]; then
    kubectl {status_context}auth can-i delete jobs.batch --namespace "${{namespace}}" | grep -qx 'yes' || {{
        echo "ERROR: current Kubernetes identity cannot delete the owned Instrumentation hook Job." >&2
        exit 1
    }}
    python3 "${{script_dir}}/{instrumentation_guard_name}" \
        --delete-options Job "${{instrumentation_name}}-inst-hook" \
        < "${{job_state}}" \
        | kubectl {status_context}delete \
            --raw="/apis/batch/v1/namespaces/${{namespace}}/jobs/${{instrumentation_name}}-inst-hook" \
            -f - >/dev/null
fi
trap - EXIT HUP INT TERM
cleanup_instrumentation_state
"""

    instrumentation_uninstall_variable = (
        f"instrumentation_name={shell_quote(collector_fullname)}"
        if job_owned_instrumentation
        else ""
    )

    write_text(
        k8s_dir / "uninstall.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail

namespace={shell_quote(args.namespace)}
release_name={shell_quote(args.release_name)}
{instrumentation_uninstall_variable}
script_dir="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
helm_command=(helm)
{helm_release_query_function}

[[ "${{SPLUNK_OTEL_CONFIRM_K8S_UNINSTALL:-}}" == "yes" ]] || {{
    echo "ERROR: Set SPLUNK_OTEL_CONFIRM_K8S_UNINSTALL=yes after reviewing the namespace, release, and Kubernetes context." >&2
    exit 1
}}
for command in helm kubectl python3; do
    command -v "${{command}}" >/dev/null 2>&1 || {{
        echo "ERROR: required command not found: ${{command}}" >&2
        exit 1
    }}
done
{supply_chain_guard}
# Resolve the exact target and prove the release exists before deleting any
# job-owned Instrumentation resources or the Helm release itself.
{kube_context_display}
uninstall_release_record="$(query_helm_release require-present any deployed failed)"
echo "Helm release ownership preflight: ${{uninstall_release_record}}"

{instrumentation_uninstall_preflight}

"${{helm_command[@]}}" uninstall "${{release_name}}" --namespace "${{namespace}}"{helm_status_context} --wait --timeout 10m
{instrumentation_uninstall_cleanup}
echo "Helm release removed. Job-created instrumentation was removed when applicable; the external Secret, operator CRDs{', and PriorityClass ' + args.priority_class_name if str_bool(args.render_priority_class) and args.priority_class_name else ''} are intentionally retained."
""",
        executable=True,
    )

    if args.eks_cluster_name and args.aws_region:
        write_text(
            k8s_dir / "eks-update-kubeconfig.sh",
            f"""#!/usr/bin/env bash
set -euo pipefail

aws eks update-kubeconfig --name {shell_quote(args.eks_cluster_name)} --region {shell_quote(args.aws_region)}
""",
            executable=True,
        )

    priority_readme_step = ""
    if str_bool(args.render_priority_class) and args.priority_class_name:
        priority_readme_step = "bash priority-class.sh\n"
    fargate_detail = ""
    if args.distribution == "eks/fargate":
        fargate_detail = (
            " The Fargate cluster-receiver node-discoverer is pinned to "
            f"`{FARGATE_NODE_DISCOVERER_IMAGE}`."
        )
    image_readme = (
        "\nSupply-chain control: `fetch-chart.sh` caches and verifies the official "
        f"chart archive (`sha256:{CHART_ARCHIVE_SHA256}`); `k8s-image-post-renderer.py` "
        "rewrites every audited chart image to a manifest digest and rejects unknown "
        f"mutable images.{fargate_detail}\n"
    )
    write_text(
        k8s_dir / "README.md",
        f"""# Splunk Observability Kubernetes OTel Collector

Review `values.yaml`, then run:

```bash
bash preflight.sh
bash validate-secrets.sh
{priority_readme_step}bash create-secret.sh
bash helm-install.sh
bash status.sh
```

Rendered namespace: `{args.namespace}`
Rendered release: `{args.release_name}`
Secret name: `{secret_name(args.release_name)}`

`values.yaml` and copied extra-values files are immutable review snapshots;
rerender instead of editing them. `secret-revision-values.yaml` is the only
mutable values file and accepts only the generated pod revision annotation.

`uninstall.sh` retains the external Secret. To delete it separately, first
confirm the active context and ownership, then run:

```bash
SPLUNK_OTEL_CONFIRM_SECRET_DELETE=yes bash cleanup-secret.sh
```

The cleanup helper refuses a Secret that is not annotated for this exact skill,
release, and namespace.
{image_readme}
""",
    )


def linux_installer_args(args: argparse.Namespace) -> list[str]:
    installer_args = [
        "--realm",
        args.realm,
        "--memory",
        args.memory_mib,
        "--mode",
        args.linux_mode,
        "--listen-interface",
        linux_effective_listen_interface(args),
    ]
    if args.linux_api_url:
        installer_args.extend(["--api-url", args.linux_api_url])
    if args.linux_ingest_url:
        installer_args.extend(["--ingest-url", args.linux_ingest_url])
    if args.linux_hec_url:
        installer_args.extend(["--hec-url", args.linux_hec_url])
    if args.collector_config:
        installer_args.extend(["--collector-config", args.collector_config])
    if args.service_user:
        installer_args.extend(["--service-user", args.service_user])
    if args.service_group:
        installer_args.extend(["--service-group", args.service_group])
    if str_bool(args.skip_collector_repo):
        installer_args.append("--skip-collector-repo")
    if args.repo_channel == "beta":
        installer_args.append("--beta")
    elif args.repo_channel == "test":
        installer_args.append("--test")
    if args.godebug:
        installer_args.extend(["--godebug", args.godebug])
    if args.deployment_environment:
        installer_args.extend(["--deployment-environment", args.deployment_environment])
    if args.service_name:
        installer_args.extend(["--service-name", args.service_name])
    if args.collector_version:
        installer_args.extend(["--collector-version", args.collector_version])
    if str_bool(args.enable_discovery):
        installer_args.append("--discovery")
    if str_bool(args.enable_autoinstrumentation):
        if args.instrumentation_mode == "systemd":
            installer_args.append("--with-systemd-instrumentation")
        elif args.instrumentation_mode == "preload":
            installer_args.append("--with-instrumentation")
        if args.instrumentation_sdks:
            installer_args.extend(["--with-instrumentation-sdk", args.instrumentation_sdks])
        if args.npm_path:
            installer_args.extend(["--npm-path", args.npm_path])
        if args.otlp_endpoint:
            installer_args.extend(["--otlp-endpoint", args.otlp_endpoint])
        if args.otlp_endpoint_protocol:
            installer_args.extend(["--otlp-endpoint-protocol", args.otlp_endpoint_protocol])
        if args.instrumentation_version:
            installer_args.extend(["--instrumentation-version", args.instrumentation_version])
        if str_bool(args.enable_metrics):
            installer_args.append("--enable-metrics")
        else:
            installer_args.append("--disable-metrics")
        if args.metrics_exporter:
            installer_args.extend(["--metrics-exporter", args.metrics_exporter])
        if args.logs_exporter:
            installer_args.extend(["--logs-exporter", args.logs_exporter])
        elif str_bool(args.enable_logs):
            installer_args.extend(["--logs-exporter", "otlp"])
        else:
            installer_args.extend(["--logs-exporter", "none"])
        installer_args.append(
            "--enable-profiler" if str_bool(args.enable_profiling) else "--disable-profiler"
        )
        installer_args.append(
            "--enable-profiler-memory"
            if str_bool(args.enable_memory_profiling)
            else "--disable-profiler-memory"
        )
    else:
        installer_args.extend(["--without-instrumentation", "--without-systemd-instrumentation"])
    if str_bool(args.enable_obi):
        installer_args.append("--with-obi")
        installer_args.extend(["--obi-version", effective_obi_version(args)])
        if args.obi_install_dir:
            installer_args.extend(["--obi-install-dir", args.obi_install_dir])
    else:
        installer_args.append("--without-obi")
    return installer_args


def render_linux(args: argparse.Namespace, output_dir: Path) -> None:
    linux_dir = output_dir / "linux"
    if linux_dir.exists():
        shutil.rmtree(linux_dir)
    linux_dir.mkdir(parents=True, exist_ok=True)

    redactor_content = diagnostic_redactor_script()
    redactor_sha256 = hashlib.sha256(redactor_content.encode("utf-8")).hexdigest()
    redactor_validation = f'''redactor_path="${{script_dir}}/redact-stream.py"
validate_redactor() {{
    local actual=""
    if [[ ! -f "${{redactor_path}}" || -L "${{redactor_path}}" || ! -r "${{redactor_path}}" ]]; then
        echo "ERROR: diagnostic redactor must be a readable, non-symlink regular file." >&2
        exit 1
    fi
    actual="$(python3 - "${{redactor_path}}" <<'PY'
import hashlib
import sys

with open(sys.argv[1], "rb") as handle:
    print(hashlib.sha256(handle.read()).hexdigest())
PY
)" || {{
        echo "ERROR: failed to hash the diagnostic redactor." >&2
        exit 1
    }}
    [[ "${{actual}}" == "{redactor_sha256}" ]] || {{
        echo "ERROR: diagnostic redactor failed its rendered SHA-256 check." >&2
        exit 1
    }}
}}
'''
    support_output_guard = r'''prepare_support_output() {
    local requested_output="$1" output_parent output_name output_parent_abs
    output_parent="$(dirname -- "${requested_output}")"
    output_name="$(basename -- "${requested_output}")"
    [[ "${output_name}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*\.tgz$ ]] || {
        echo "ERROR: support-bundle output must use a safe .tgz filename." >&2
        exit 1
    }
    output_parent_abs="$(cd -- "${output_parent}" 2>/dev/null && pwd -P)" || {
        echo "ERROR: support-bundle output parent must be an existing directory." >&2
        exit 1
    }
    output="${output_parent_abs}/${output_name}"
    if [[ -e "${output}" || -L "${output}" ]]; then
        echo "ERROR: refusing to replace an existing or symlink support-bundle output: ${output}" >&2
        exit 1
    fi
    output_stage="$(mktemp -d "${output_parent_abs}/.${output_name}.stage.XXXXXX")"
    chmod 700 "${output_stage}"
    output_tmp="${output_stage}/bundle.tgz"
}

publish_support_output() {
    if [[ ! -f "${output_tmp}" || -L "${output_tmp}" ]]; then
        echo "ERROR: staged support bundle is not a regular file." >&2
        exit 1
    fi
    chmod 600 "${output_tmp}"
    if ! ln -- "${output_tmp}" "${output}"; then
        echo "ERROR: support-bundle output appeared during creation; refusing to replace it: ${output}" >&2
        exit 1
    fi
    rm -rf "${output_stage}"
    output_stage=""
}
'''

    token_file = args.o11y_token_file or "/path/to/splunk_o11y_access_token"
    installer_args = linux_installer_args(args)
    installer_array = bash_array("installer_args", installer_args)
    token_assignment = shell_env_alias_default("TOKEN_FILE", "SPLUNK_O11Y_TOKEN_FILE", token_file)
    # Supply-chain identity is immutable after review. Changing either value
    # requires a rerender so metadata and the executable packet stay aligned.
    installer_url_assignment = f"INSTALLER_URL={shell_quote(args.installer_url)}"
    installer_sha_assignment = (
        f"INSTALLER_SHA256={shell_quote(args.installer_sha256.lower())}"
    )
    ingest_url_assignment = f"INGEST_URL={shell_quote(linux_effective_ingest_url(args))}"
    collector_config_assignment = f"COLLECTOR_CONFIG={shell_quote(args.collector_config)}"
    service_user_assignment = f"SERVICE_USER={shell_quote(args.service_user or 'splunk-otel-collector')}"
    service_group_assignment = f"SERVICE_GROUP={shell_quote(args.service_group or 'splunk-otel-collector')}"
    auto_instrumentation_assignment = (
        f"AUTO_INSTRUMENTATION_REQUESTED={shell_quote('true' if str_bool(args.enable_autoinstrumentation) else 'false')}"
    )
    obi_requested_assignment = (
        f"OBI_REQUESTED={shell_quote('true' if str_bool(args.enable_obi) else 'false')}"
    )
    obi_path_assignment = f"OBI_PATH={shell_quote(str(PurePosixPath(effective_obi_install_dir(args)) / 'obi'))}"
    diagnostic_config_paths = [
        "/etc/otel/collector/splunk-otel-collector.conf",
        "/etc/otel/collector/agent_config.yaml",
        "/etc/otel/collector/gateway_config.yaml",
    ]
    if args.collector_config and args.collector_config not in diagnostic_config_paths:
        diagnostic_config_paths.append(args.collector_config)
    diagnostic_config_paths_array = bash_array(
        "diagnostic_config_paths", diagnostic_config_paths
    )
    obi_status_block = ""
    obi_doctor_block = ""
    obi_integrity_function = ""
    obi_post_install_block = ""
    if str_bool(args.enable_obi):
        obi_path = str(PurePosixPath(effective_obi_install_dir(args)) / "obi")
        expected_obi_version = effective_obi_version(args).removeprefix("v")
        obi_integrity_function = f"""
verify_obi_binary_integrity() {{
    obi_binary_path={shell_quote(obi_path)}
    case "$(uname -m)" in
        amd64|x86_64)
            obi_expected_sha256={shell_quote(OBI_BINARY_SHA256['amd64'])}
            ;;
        arm64|aarch64)
            obi_expected_sha256={shell_quote(OBI_BINARY_SHA256['arm64'])}
            ;;
        *)
            echo "ERROR: no audited OBI binary digest exists for architecture $(uname -m)." >&2
            return 1
            ;;
    esac
    if [ ! -f "${{obi_binary_path}}" ] || [ -L "${{obi_binary_path}}" ] || [ ! -x "${{obi_binary_path}}" ]; then
        echo "ERROR: OBI must be an executable, non-symlink regular file: ${{obi_binary_path}}" >&2
        return 1
    fi
    command -v sha256sum >/dev/null 2>&1 || {{
        echo "ERROR: sha256sum is required for the audited OBI binary check." >&2
        return 1
    }}
    obi_actual_sha256="$(sha256sum "${{obi_binary_path}}" | awk '{{print $1}}')"
    if [ "${{obi_actual_sha256}}" != "${{obi_expected_sha256}}" ]; then
        echo "ERROR: installed OBI binary failed the audited architecture-specific SHA-256 check." >&2
        echo "Expected: ${{obi_expected_sha256}}" >&2
        echo "Actual:   ${{obi_actual_sha256:-unavailable}}" >&2
        return 1
    fi
}}
"""
        obi_post_install_block = f"{obi_integrity_function}\nverify_obi_binary_integrity"
        obi_status_block = f"""
{obi_integrity_function}
verify_obi_binary_integrity
obi_path={shell_quote(obi_path)}
obi_expected_version={shell_quote(expected_obi_version)}
[[ -x "${{obi_path}}" ]] || {{
    echo "ERROR: pinned OBI binary is missing or not executable: ${{obi_path}}" >&2
    exit 1
}}
obi_version_output="$("${{obi_path}}" --version 2>&1)" || {{
    printf '%s\\n' "${{obi_version_output}}" >&2
    echo "ERROR: OBI binary version check failed." >&2
    exit 1
}}
printf '%s\\n' "${{obi_version_output}}"
[[ "${{obi_version_output}}" == *"${{obi_expected_version}}"* ]] || {{
    echo "ERROR: OBI binary does not match pinned version ${{obi_expected_version}}." >&2
    exit 1
}}
echo "OBI binary validated. Runtime/service configuration is a separate handoff."
"""
        obi_doctor_block = f"""
echo '== OBI binary (runtime is not configured by this skill) =='
if [[ -x {shell_quote(obi_path)} ]]; then
    obi_version_output=""
    if obi_version_output="$({shell_quote(obi_path)} --version 2>&1)"; then
        printf '%s\\n' "${{obi_version_output}}"
    else
        obi_version_status=$?
        printf '%s\\n' "${{obi_version_output}}"
        echo "FINDING: the requested OBI binary did not pass its version probe (exit ${{obi_version_status}})."
        unhealthy_findings=1
    fi
else
    echo 'FINDING: requested OBI binary is missing or not executable: {obi_path}'
    unhealthy_findings=1
fi
"""
    validation_functions = r'''
ACCESS_TOKEN=""
validate_token_file() {
    local snapshot=""
    if ! snapshot="$(python3 - "${TOKEN_FILE}" <<'PY'
import os
import re
import stat
import sys

path = sys.argv[1]
maximum = 16 * 1024
if not hasattr(os, "O_NOFOLLOW"):
    raise SystemExit("ERROR: O_NOFOLLOW is required for safe token loading")
try:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
except OSError as exc:
    raise SystemExit("ERROR: cannot safely open Observability token file: %s" % exc)
try:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise SystemExit("ERROR: Observability token must be a non-symlink, non-hard-linked regular file")
    mode = stat.S_IMODE(before.st_mode)
    if mode != 0o600:
        raise SystemExit("ERROR: Observability token file must have mode 600 (found %03o)" % mode)
    if before.st_size < 1 or before.st_size > maximum:
        raise SystemExit("ERROR: Observability token file must contain 1 through 16384 bytes")
    data = b""
    while len(data) <= maximum:
        chunk = os.read(descriptor, maximum + 1 - len(data))
        if not chunk:
            break
        data += chunk
    after = os.fstat(descriptor)
finally:
    os.close(descriptor)
if len(data) < 1 or len(data) > maximum or after.st_size != len(data):
    raise SystemExit("ERROR: Observability token file changed or exceeded 16384 bytes while being read")
if not re.fullmatch(br"[A-Za-z0-9._~+/=-]+", data):
    raise SystemExit("ERROR: Observability token must use the documented alphabet with no newline or whitespace")
sys.stdout.buffer.write(data + b"!")
PY
)"; then
        exit 1
    fi
    [[ "${snapshot}" == *'!' ]] || {
        echo "ERROR: Observability token snapshot was incomplete." >&2
        exit 1
    }
    ACCESS_TOKEN="${snapshot%!}"
}

verify_installer() {
    local path="$1" actual=""
    case "${INSTALLER_URL}" in
        https://*) ;;
        *) echo "ERROR: Installer URL must use HTTPS." >&2; exit 1 ;;
    esac
    if command -v sha256sum >/dev/null 2>&1; then
        actual="$(sha256sum "${path}" | awk '{print $1}')"
    elif command -v shasum >/dev/null 2>&1; then
        actual="$(shasum -a 256 "${path}" | awk '{print $1}')"
    else
        echo "ERROR: sha256sum or shasum is required to verify the installer." >&2
        exit 1
    fi
    actual="$(printf '%s' "${actual}" | tr '[:upper:]' '[:lower:]')"
    if [[ ! "${INSTALLER_SHA256}" =~ ^[0-9a-fA-F]{64}$ ]] || [[ "${actual}" != "$(printf '%s' "${INSTALLER_SHA256}" | tr '[:upper:]' '[:lower:]')" ]]; then
        echo "ERROR: Linux installer SHA-256 verification failed." >&2
        echo "Expected: ${INSTALLER_SHA256}" >&2
        echo "Actual:   ${actual:-unavailable}" >&2
        exit 1
    fi
}

verify_access_token_without_argv() {
    local http_code=""
    command -v curl >/dev/null 2>&1 || {
        echo "ERROR: curl is required for secret-safe access-token verification." >&2
        exit 1
    }
    # curl --config - is available on the oldest distro/curl combinations
    # accepted by the pinned upstream installer. The restricted token alphabet
    # above makes this generated config line non-injectable, while keeping the
    # credential out of argv, process listings, and temporary files.
    if ! http_code="$({
        printf 'header = "X-Sf-Token: %s"\n' "${ACCESS_TOKEN}"
    } | curl -q --proto '=https' -sS --max-time 15 \
        --request POST --data '[]' \
        --config - \
        --header 'Content-Type: application/json' \
        --output /dev/null --write-out '%{http_code}' "${INGEST_URL}/v2/event")"; then
        echo "ERROR: Observability access-token verification failed." >&2
        exit 1
    fi
    if [[ "${http_code}" != "200" ]]; then
        echo "ERROR: Observability access-token verification returned HTTP ${http_code:-unknown}; expected 200." >&2
        exit 1
    fi
}
'''

    write_text(
        linux_dir / "preflight-local.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail

{collector_config_assignment}
{service_user_assignment}
{service_group_assignment}
{auto_instrumentation_assignment}
{obi_requested_assignment}
{obi_path_assignment}
OS_RELEASE_FILE=/etc/os-release
SYSTEMD_RUNTIME_DIR=/run/systemd/system

for required_command in bash curl python3 tar; do
    command -v "${{required_command}}" >/dev/null 2>&1 || {{
        echo "ERROR: ${{required_command}} is required on the target host before installation." >&2
        exit 1
    }}
done
python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 6) else 1)' || {{
    echo "ERROR: Python 3.6 or newer is required by the rendered Linux safety helpers." >&2
    exit 1
}}
if ! command -v sha256sum >/dev/null 2>&1 && ! command -v shasum >/dev/null 2>&1; then
    echo "ERROR: sha256sum or shasum is required on the target host." >&2
    exit 1
fi
if [[ "${{OBI_REQUESTED}}" == "true" ]]; then
    for obi_required_command in sha256sum gzip; do
        command -v "${{obi_required_command}}" >/dev/null 2>&1 || {{
            echo "ERROR: ${{obi_required_command}} is required before OBI installation; preflight will not mutate package state." >&2
            exit 1
        }}
    done
fi
package_is_installed() {{
    local package_name="$1" status=""
    if command -v rpm >/dev/null 2>&1 && rpm -q "${{package_name}}" >/dev/null 2>&1; then
        return 0
    fi
    if command -v dpkg-query >/dev/null 2>&1; then
        status="$(dpkg-query -W -f='${{Status}}' "${{package_name}}" 2>/dev/null || true)"
        [[ "${{status}}" == "install ok installed" ]] && return 0
    fi
    return 1
}}

if command -v otelcol >/dev/null 2>&1 || package_is_installed splunk-otel-collector; then
    echo "ERROR: an existing Splunk OTel Collector was detected before install; use the reviewed upgrade or uninstall workflow." >&2
    exit 1
fi
if [[ "${{AUTO_INSTRUMENTATION_REQUESTED}}" == "true" ]] && {{
    package_is_installed splunk-otel-auto-instrumentation ||
    [[ -e /usr/lib/splunk-instrumentation/libsplunk.so ]] ||
    [[ -e /usr/lib/systemd/system.conf.d/00-splunk-otel-auto-instrumentation.conf ]] ||
    [[ -e /usr/lib/splunk-instrumentation/splunk-otel-js/node_modules/@splunk/otel ]]
}}; then
    echo "ERROR: existing Splunk auto-instrumentation artifacts were detected before install." >&2
    exit 1
fi
if [[ "${{OBI_REQUESTED}}" == "true" && -e "${{OBI_PATH}}" ]]; then
    echo "ERROR: existing OBI path detected before install: ${{OBI_PATH}}" >&2
    exit 1
fi

if [[ ! -r "${{OS_RELEASE_FILE}}" ]]; then
    echo "ERROR: a readable /etc/os-release is required to validate the Linux target." >&2
    exit 1
fi
host_facts="$(python3 - "${{OS_RELEASE_FILE}}" <<'PY'
import shlex
import sys

values = {{}}
with open(sys.argv[1], encoding="utf-8") as handle:
    for raw_line in handle:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        try:
            parsed = shlex.split(raw_value, posix=True)
        except ValueError as exc:
            raise SystemExit(f"invalid /etc/os-release value for {{key}}: {{exc}}")
        values[key] = parsed[0] if len(parsed) == 1 else raw_value

print(
    "\x1f".join(
        (
            values.get("ID", ""),
            values.get("VERSION_ID", ""),
            values.get("VERSION_CODENAME", ""),
        )
    )
)
PY
)" || {{
    echo "ERROR: failed to parse /etc/os-release safely." >&2
    exit 1
}}
IFS=$'\x1f' read -r distro_id distro_version distro_codename <<< "${{host_facts}}"
if [[ "${{distro_id}}" == "debian" && -z "${{distro_codename}}" ]]; then
    case "${{distro_version}}" in
        11) distro_codename=bullseye ;;
        12) distro_codename=bookworm ;;
        13) distro_codename=trixie ;;
    esac
fi
case "${{distro_id}}" in
    ubuntu)
        case "${{distro_codename}}" in
            xenial|bionic|focal|jammy|noble) ;;
            *) echo "ERROR: unsupported Ubuntu codename: ${{distro_codename:-unknown}}." >&2; exit 1 ;;
        esac
        package_family=apt
        ;;
    debian)
        case "${{distro_codename}}" in
            bullseye|bookworm|trixie) ;;
            *) echo "ERROR: unsupported Debian codename: ${{distro_codename:-unknown}}." >&2; exit 1 ;;
        esac
        package_family=apt
        ;;
    amzn)
        case "${{distro_version}}" in
            2|2023) ;;
            *) echo "ERROR: unsupported Amazon Linux version: ${{distro_version:-unknown}}." >&2; exit 1 ;;
        esac
        package_family=rpm
        ;;
    centos|ol|rhel|rocky)
        case "${{distro_version}}" in
            7*|8*|9*|10*) ;;
            *) echo "ERROR: unsupported ${{distro_id}} version: ${{distro_version:-unknown}}." >&2; exit 1 ;;
        esac
        package_family=rpm
        ;;
    sles|opensuse*)
        case "${{distro_version}}" in
            12*|15*|42*) ;;
            *) echo "ERROR: unsupported ${{distro_id}} version: ${{distro_version:-unknown}}." >&2; exit 1 ;;
        esac
        package_family=zypper
        ;;
    *)
        echo "ERROR: unsupported Linux distribution: ${{distro_id:-unknown}}." >&2
        exit 1
        ;;
esac

host_arch="$(uname -m)"
case "${{host_arch}}" in
    amd64|x86_64|aarch64|arm64) ;;
    *) echo "ERROR: unsupported Linux architecture: ${{host_arch:-unknown}}." >&2; exit 1 ;;
esac

if [[ "$(id -u)" -ne 0 ]]; then
    command -v sudo >/dev/null 2>&1 || {{
        echo "ERROR: root or passwordless sudo is required for package installation." >&2
        exit 1
    }}
    sudo -n env true >/dev/null 2>&1 || {{
        echo "ERROR: noninteractive sudo failed; package installation cannot proceed safely." >&2
        exit 1
    }}
fi

root_command_exists() {{
    local command_name="$1"
    if [[ "$(id -u)" -eq 0 ]]; then
        command -v "${{command_name}}" >/dev/null 2>&1
    else
        sudo -n env sh -c 'command -v "$1" >/dev/null 2>&1' sh "${{command_name}}"
    fi
}}

for system_command in systemctl systemd-tmpfiles getent groupadd useradd nologin; do
    root_command_exists "${{system_command}}" || {{
        echo "ERROR: ${{system_command}} is required by the pinned Linux installer." >&2
        exit 1
    }}
done
if [[ "${{SERVICE_USER}}" != "splunk-otel-collector" ]]; then
    root_command_exists userdel || {{
        echo "ERROR: userdel is required when a custom Collector service user is selected." >&2
        exit 1
    }}
fi
if [[ "${{SERVICE_GROUP}}" != "splunk-otel-collector" ]]; then
    root_command_exists groupdel || {{
        echo "ERROR: groupdel is required when a custom Collector service group is selected." >&2
        exit 1
    }}
fi
if [[ -n "${{COLLECTOR_CONFIG}}" ]] && ! root_command_exists python3; then
    echo "ERROR: Python 3.6+ must be available through sudo to inspect a protected custom config." >&2
    exit 1
fi
if [[ ! -d "${{SYSTEMD_RUNTIME_DIR}}" ]]; then
    echo "ERROR: systemd is not active; expected runtime directory ${{SYSTEMD_RUNTIME_DIR}}." >&2
    exit 1
fi
case "${{package_family}}" in
    apt)
        root_command_exists apt-get || {{
            echo "ERROR: apt-get is required on ${{distro_id}} targets." >&2
            exit 1
        }}
        ;;
    rpm)
        root_command_exists rpm || {{
            echo "ERROR: rpm is required on ${{distro_id}} targets." >&2
            exit 1
        }}
        if ! root_command_exists yum && ! root_command_exists dnf; then
            echo "ERROR: yum or dnf is required on ${{distro_id}} targets." >&2
            exit 1
        fi
        ;;
    zypper)
        for package_command in rpm zypper; do
            root_command_exists "${{package_command}}" || {{
                echo "ERROR: ${{package_command}} is required on ${{distro_id}} targets." >&2
                exit 1
            }}
        done
        ;;
esac

if [[ -n "${{COLLECTOR_CONFIG}}" ]]; then
    config_probe=(python3)
    if [[ "$(id -u)" -ne 0 ]]; then
        config_probe=(sudo -n python3)
    fi
    "${{config_probe[@]}}" - "${{COLLECTOR_CONFIG}}" "${{SERVICE_USER}}" <<'PY'
import os
import pwd
import stat
import sys
from pathlib import PurePosixPath

path_text, service_user = sys.argv[1:]
path = PurePosixPath(path_text)
parts = path.parts
if not path.is_absolute() or len(parts) < 2:
    raise SystemExit(f"ERROR: custom Collector config path is not absolute: {{path_text}}")

directory_records = []
directory_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
directory_records.append((PurePosixPath("/"), os.fstat(directory_fd)))
try:
    current = PurePosixPath("/")
    for component in parts[1:-1]:
        flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
        next_fd = os.open(component, flags, dir_fd=directory_fd)
        os.close(directory_fd)
        directory_fd = next_fd
        current /= component
        info = os.fstat(directory_fd)
        if not stat.S_ISDIR(info.st_mode):
            raise SystemExit(f"ERROR: custom Collector config parent is not a directory: {{current}}")
        directory_records.append((current, info))

    file_fd = os.open(parts[-1], os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
    try:
        file_info = os.fstat(file_fd)
        if not stat.S_ISREG(file_info.st_mode):
            raise SystemExit(f"ERROR: custom Collector config must be a non-symlink regular file: {{path_text}}")
        if file_info.st_nlink != 1:
            raise SystemExit(f"ERROR: custom Collector config must not be hard-linked: {{path_text}}")
    finally:
        os.close(file_fd)
finally:
    os.close(directory_fd)

managed_root = PurePosixPath("/etc/otel")
managed_config_root = managed_root / "collector"
managed = path.parent == managed_config_root or managed_config_root in path.parents
try:
    pwd.getpwnam(service_user)
    service_user_exists = True
except KeyError:
    service_user_exists = False

if managed:
    # The pinned installer recursively chowns /etc/otel to the service account
    # but preserves mode bits. Owner read/search must therefore be sufficient
    # after that ownership transition; ancestors outside /etc/otel must be
    # searchable without relying on root.
    if not file_info.st_mode & stat.S_IRUSR:
        raise SystemExit(f"ERROR: managed custom Collector config needs owner-read permission after installer chown: {{path_text}}")
    for display, info in directory_records:
        inside_managed = display == managed_root or managed_root in display.parents
        required = stat.S_IXUSR if inside_managed else stat.S_IXOTH
        if not info.st_mode & required:
            raise SystemExit(f"ERROR: projected service user cannot traverse custom Collector config parent: {{display}}")
elif not service_user_exists:
    # No uid exists to probe yet. Conservatively require the future account to
    # reach the external config through ordinary 'other' permissions.
    if not file_info.st_mode & stat.S_IROTH:
        raise SystemExit(f"ERROR: future service user cannot read external custom Collector config: {{path_text}}")
    for display, info in directory_records:
        if not info.st_mode & stat.S_IXOTH:
            raise SystemExit(f"ERROR: future service user cannot traverse external config parent: {{display}}")
PY
    case "${{COLLECTOR_CONFIG}}" in
        /etc/otel/collector/*) ;;
        *)
            if id "${{SERVICE_USER}}" >/dev/null 2>&1; then
                if [[ "$(id -u)" -eq 0 ]] && command -v runuser >/dev/null 2>&1; then
                    runuser -u "${{SERVICE_USER}}" -- test -r "${{COLLECTOR_CONFIG}}" || {{
                        echo "ERROR: ${{SERVICE_USER}} cannot read custom Collector config: ${{COLLECTOR_CONFIG}}" >&2
                        exit 1
                    }}
                elif [[ "$(id -un)" == "${{SERVICE_USER}}" ]]; then
                    [[ -r "${{COLLECTOR_CONFIG}}" ]] || exit 1
                elif command -v sudo >/dev/null 2>&1; then
                    sudo -n -u "${{SERVICE_USER}}" test -r "${{COLLECTOR_CONFIG}}" || {{
                        echo "ERROR: ${{SERVICE_USER}} cannot read custom Collector config: ${{COLLECTOR_CONFIG}}" >&2
                        exit 1
                    }}
                else
                    echo "ERROR: runuser or sudo is required to verify ${{SERVICE_USER}} can read ${{COLLECTOR_CONFIG}}." >&2
                    exit 1
                fi
            fi
            ;;
    esac
fi

echo "Linux target preflight passed."
""",
        executable=True,
    )

    write_text(
        linux_dir / "install-local.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail
umask 077

script_dir="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
{token_assignment}
{installer_url_assignment}
{installer_sha_assignment}
{ingest_url_assignment}
{validation_functions}
bash "${{script_dir}}/preflight-local.sh"
validate_token_file
verify_access_token_without_argv

installer_path="$(mktemp)"
trap 'rm -f "${{installer_path}}"' EXIT
curl -q --proto '=https' -fsSL "${{INSTALLER_URL}}" -o "${{installer_path}}"
verify_installer "${{installer_path}}"
chmod 700 "${{installer_path}}"

{installer_array}

if command -v sudo >/dev/null 2>&1 && [[ "$(id -u)" -ne 0 ]]; then
    printf '%s\\n' "${{ACCESS_TOKEN}}" | sudo -n env VERIFY_ACCESS_TOKEN=false sh "${{installer_path}}" "${{installer_args[@]}}"
else
    printf '%s\\n' "${{ACCESS_TOKEN}}" | env VERIFY_ACCESS_TOKEN=false sh "${{installer_path}}" "${{installer_args[@]}}"
fi
ACCESS_TOKEN=""
{obi_post_install_block}
""",
        executable=True,
    )

    remote_installer_args = " ".join(shell_quote(value) for value in installer_args)
    remote_ingest_url = shell_quote(linux_effective_ingest_url(args))
    remote_installer_content = f"""#!/bin/sh
set -eu

installer_path="${{1:-}}"
if [ -z "${{installer_path}}" ] || [ ! -f "${{installer_path}}" ]; then
    echo "ERROR: verified installer path is required." >&2
    exit 1
fi
command -v curl >/dev/null 2>&1 || {{ echo "ERROR: curl is required for secret-safe token verification." >&2; exit 1; }}
IFS= read -r access_token
[ -n "${{access_token}}" ] || {{ echo "ERROR: access token input is empty." >&2; exit 1; }}
access_token_size="$(LC_ALL=C printf '%s' "${{access_token}}" | wc -c | tr -d '[:space:]')"
[ "${{access_token_size}}" -le 16384 ] || {{
    echo "ERROR: access token input exceeds the 16384-byte safety limit." >&2
    exit 1
}}
printf '%s' "${{access_token}}" | LC_ALL=C grep -Eq '^[A-Za-z0-9._~+/=-]+$' || {{
    echo "ERROR: access token contains characters unsafe for the upstream environment file." >&2
    exit 1
}}
http_code="$({{
    printf 'header = "X-Sf-Token: %s"\n' "${{access_token}}"
}} | curl -q --proto '=https' -sS --max-time 15 \
    --request POST --data '[]' --config - \
    --header 'Content-Type: application/json' --output /dev/null --write-out '%{{http_code}}' \
    {remote_ingest_url}/v2/event)" || {{ echo "ERROR: Observability access-token verification failed." >&2; exit 1; }}
[ "${{http_code}}" = "200" ] || {{
    echo "ERROR: Observability access-token verification returned HTTP ${{http_code:-unknown}}; expected 200." >&2
    exit 1
}}
if command -v sudo >/dev/null 2>&1 && [ "$(id -u)" -ne 0 ]; then
    printf '%s\\n' "${{access_token}}" | sudo -n env VERIFY_ACCESS_TOKEN=false sh "${{installer_path}}" {remote_installer_args}
else
    printf '%s\\n' "${{access_token}}" | env VERIFY_ACCESS_TOKEN=false sh "${{installer_path}}" {remote_installer_args}
fi
access_token=""
{obi_post_install_block}
"""
    remote_installer_sha256 = hashlib.sha256(remote_installer_content.encode("utf-8")).hexdigest()
    write_text(
        linux_dir / "remote-install.sh",
        remote_installer_content,
        executable=True,
    )

    ssh_host = args.linux_host or "linux-host.example.com"
    ssh_user = args.ssh_user or "ec2-user"
    ssh_key = args.ssh_key_file

    def ssh_key_guard(*, include_scp: bool) -> str:
        if not ssh_key:
            return ""
        array_lines = 'ssh_args+=(-i "${ssh_key_file}")\n'
        if include_scp:
            array_lines += 'scp_args+=(-i "${ssh_key_file}")\n'
        return f"""ssh_key_file={shell_quote(ssh_key)}
if [[ ! -f "${{ssh_key_file}}" || -L "${{ssh_key_file}}" || ! -r "${{ssh_key_file}}" || ! -s "${{ssh_key_file}}" ]]; then
    echo "ERROR: SSH private key must be a readable, nonempty, non-symlink regular file." >&2
    exit 1
fi
ssh_key_mode="$(stat -c '%a' "${{ssh_key_file}}" 2>/dev/null || stat -f '%A' "${{ssh_key_file}}" 2>/dev/null || true)"
if [[ "${{ssh_key_mode}}" != "600" && "${{ssh_key_mode}}" != "0600" ]]; then
    echo "ERROR: SSH private key must have mode 600 (found ${{ssh_key_mode:-unknown}})." >&2
    exit 1
fi
{array_lines}"""

    ssh_key_block = ""
    if ssh_key:
        ssh_key_block = ssh_key_guard(include_scp=True)
    host_assignment = shell_env_alias_default("LINUX_HOST", "SPLUNK_OTEL_LINUX_HOST", ssh_host)
    user_assignment = shell_env_alias_default("SSH_USER", "SPLUNK_OTEL_SSH_USER", ssh_user)
    port_assignment = shell_env_alias_default("SSH_PORT", "SPLUNK_OTEL_SSH_PORT", args.ssh_port)

    write_text(
        linux_dir / "install-ssh.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail
umask 077

script_dir="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"

{token_assignment}
{host_assignment}
{user_assignment}
{port_assignment}
{installer_url_assignment}
{installer_sha_assignment}
{ingest_url_assignment}
{validation_functions}
validate_token_file

if [[ -z "${{LINUX_HOST}}" || -z "${{SSH_USER}}" ]]; then
    echo "ERROR: LINUX_HOST and SSH_USER are required for SSH install." >&2
    exit 1
fi
[[ "${{LINUX_HOST}}" =~ ^[A-Za-z0-9._:-]+$ ]] || {{ echo "ERROR: LINUX_HOST contains unsupported characters." >&2; exit 1; }}
[[ "${{SSH_USER}}" =~ ^[A-Za-z_][A-Za-z0-9_.-]*$ ]] || {{ echo "ERROR: SSH_USER contains unsupported characters." >&2; exit 1; }}
[[ "${{SSH_PORT}}" =~ ^[0-9]+$ ]] && (( SSH_PORT >= 1 && SSH_PORT <= 65535 )) || {{
    echo "ERROR: SSH_PORT must be an integer from 1 through 65535." >&2
    exit 1
}}

ssh_target="${{SSH_USER}}@${{LINUX_HOST}}"
scp_target="${{ssh_target}}"
if [[ "${{LINUX_HOST}}" == *:* ]]; then
    scp_target="${{SSH_USER}}@[${{LINUX_HOST}}]"
fi

ssh_args=(-p "${{SSH_PORT}}")
scp_args=(-P "${{SSH_PORT}}")
{ssh_key_block}

installer_path="$(mktemp)"
remote_dir=""
cleanup() {{
    rm -f "${{installer_path}}"
    if [[ -n "${{remote_dir}}" ]]; then
        printf -v quoted_remote_dir '%q' "${{remote_dir}}"
        ssh "${{ssh_args[@]}}" "${{ssh_target}}" "rm -rf -- ${{quoted_remote_dir}}" >/dev/null 2>&1 || true
    fi
}}
trap cleanup EXIT

curl -q --proto '=https' -fsSL "${{INSTALLER_URL}}" -o "${{installer_path}}"
verify_installer "${{installer_path}}"
chmod 700 "${{installer_path}}"
if command -v sha256sum >/dev/null 2>&1; then
    remote_wrapper_actual="$(sha256sum "${{script_dir}}/remote-install.sh" | awk '{{print $1}}')"
elif command -v shasum >/dev/null 2>&1; then
    remote_wrapper_actual="$(shasum -a 256 "${{script_dir}}/remote-install.sh" | awk '{{print $1}}')"
else
    echo "ERROR: sha256sum or shasum is required to verify the remote wrapper." >&2
    exit 1
fi
[[ "${{remote_wrapper_actual}}" == "{remote_installer_sha256}" ]] || {{
    echo "ERROR: rendered remote installer wrapper failed SHA-256 verification." >&2
    exit 1
}}
remote_dir="$(ssh "${{ssh_args[@]}}" "${{ssh_target}}" 'umask 077; mktemp -d /tmp/splunk-otel-install.XXXXXX')"
[[ "${{remote_dir}}" =~ ^/tmp/splunk-otel-install\\.[A-Za-z0-9]+$ ]] || {{
    echo "ERROR: Remote host returned an unsafe temporary directory." >&2
    exit 1
}}
scp "${{scp_args[@]}}" -- "${{installer_path}}" "${{scp_target}}:${{remote_dir}}/install.sh"
scp "${{scp_args[@]}}" -- "${{script_dir}}/remote-install.sh" "${{script_dir}}/preflight-local.sh" \\
    "${{scp_target}}:${{remote_dir}}/"
remote_command="bash ${{remote_dir}}/preflight-local.sh && chmod 700 ${{remote_dir}}/install.sh ${{remote_dir}}/remote-install.sh && sh ${{remote_dir}}/remote-install.sh ${{remote_dir}}/install.sh"
# Stream the token over the existing SSH channel. It is never copied to a
# remote file and never appears in a command line.
printf '%s\\n' "${{ACCESS_TOKEN}}" \
    | ssh "${{ssh_args[@]}}" "${{ssh_target}}" "${{remote_command}}"
""",
        executable=True,
    )

    write_text(
        linux_dir / "status-local.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail
umask 077

script_dir="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
{redactor_validation}
validate_redactor
health_endpoint={shell_quote(linux_effective_health_endpoint(args))}
status_file="$(mktemp)"
journal_file=""
cleanup() {{
    rm -f "${{status_file}}"
    [[ -z "${{journal_file}}" ]] || rm -f "${{journal_file}}"
}}
trap cleanup EXIT

privileged=()
if [[ "$(id -u)" -ne 0 ]]; then
    command -v sudo >/dev/null 2>&1 || {{
        echo "ERROR: root or passwordless sudo is required to inspect Collector service logs." >&2
        exit 1
    }}
    sudo -n true >/dev/null 2>&1 || {{
        echo "ERROR: noninteractive sudo failed; Collector service/log status cannot be validated." >&2
        exit 1
    }}
    privileged=(sudo -n)
fi

if command -v systemctl >/dev/null 2>&1; then
    "${{privileged[@]}}" systemctl is-active splunk-otel-collector
    if ! "${{privileged[@]}}" systemctl status --no-pager splunk-otel-collector >"${{status_file}}" 2>&1; then
        python3 "${{redactor_path}}" < "${{status_file}}" >&2
        echo "ERROR: systemctl status failed for splunk-otel-collector." >&2
        exit 1
    fi
    python3 "${{redactor_path}}" < "${{status_file}}"
    journal_file="$(mktemp)"
    if ! "${{privileged[@]}}" journalctl -u splunk-otel-collector --since '-10 minutes' --no-pager >"${{journal_file}}" 2>&1; then
        python3 "${{redactor_path}}" < "${{journal_file}}" >&2
        echo "ERROR: failed to retrieve recent collector logs." >&2
        exit 1
    fi
    if grep -Eiq '(^|[^a-z])(panic|fatal|exporting failed|permanent error)([^a-z]|$)' "${{journal_file}}"; then
        python3 "${{redactor_path}}" < "${{journal_file}}" >&2
        echo "ERROR: Recent collector logs contain fatal/export pipeline errors." >&2
        exit 1
    fi
else
    if ! "${{privileged[@]}}" service splunk-otel-collector status >"${{status_file}}" 2>&1; then
        python3 "${{redactor_path}}" < "${{status_file}}" >&2
        echo "ERROR: service status failed for splunk-otel-collector." >&2
        exit 1
    fi
    python3 "${{redactor_path}}" < "${{status_file}}"
fi
command -v curl >/dev/null 2>&1 || {{ echo "ERROR: curl is required for the health check." >&2; exit 1; }}
curl -q -fsS --max-time 5 "${{health_endpoint}}" >/dev/null
{obi_status_block}
""",
        executable=True,
    )

    ssh_key_status_block = ""
    if ssh_key:
        ssh_key_status_block = ssh_key_guard(include_scp=True)
    write_text(
        linux_dir / "status-ssh.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
{host_assignment}
{user_assignment}
{port_assignment}
[[ -n "${{LINUX_HOST}}" && "${{LINUX_HOST}}" =~ ^[A-Za-z0-9._:-]+$ ]] || {{
    echo "ERROR: LINUX_HOST is empty or contains unsupported characters." >&2
    exit 1
}}
[[ -n "${{SSH_USER}}" && "${{SSH_USER}}" =~ ^[A-Za-z_][A-Za-z0-9_.-]*$ ]] || {{
    echo "ERROR: SSH_USER is empty or contains unsupported characters." >&2
    exit 1
}}
[[ "${{SSH_PORT}}" =~ ^[0-9]+$ ]] && (( SSH_PORT >= 1 && SSH_PORT <= 65535 )) || {{
    echo "ERROR: SSH_PORT must be an integer from 1 through 65535." >&2
    exit 1
}}
ssh_args=(-p "${{SSH_PORT}}")
scp_args=(-P "${{SSH_PORT}}")
{ssh_key_status_block}
ssh_target="${{SSH_USER}}@${{LINUX_HOST}}"
scp_target="${{ssh_target}}"
if [[ "${{LINUX_HOST}}" == *:* ]]; then
    scp_target="${{SSH_USER}}@[${{LINUX_HOST}}]"
fi
remote_dir="$(ssh "${{ssh_args[@]}}" "${{ssh_target}}" 'umask 077; mktemp -d /tmp/splunk-otel-status.XXXXXX')"
[[ "${{remote_dir}}" =~ ^/tmp/splunk-otel-status\\.[A-Za-z0-9]+$ ]] || {{
    echo "ERROR: Remote host returned an unsafe status temporary directory." >&2
    exit 1
}}
cleanup() {{
    printf -v quoted_remote_dir '%q' "${{remote_dir}}"
    ssh "${{ssh_args[@]}}" "${{ssh_target}}" "rm -rf -- ${{quoted_remote_dir}}" >/dev/null 2>&1 || true
}}
trap cleanup EXIT
scp "${{scp_args[@]}}" -- "${{script_dir}}/status-local.sh" "${{script_dir}}/redact-stream.py" \
    "${{scp_target}}:${{remote_dir}}/"
ssh "${{ssh_args[@]}}" "${{ssh_target}}" "bash ${{remote_dir}}/status-local.sh"
""",
        executable=True,
    )

    write_text(
        linux_dir / "redact-stream.py",
        redactor_content,
        executable=True,
    )

    write_text(
        linux_dir / "doctor-local.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail
umask 077

COLLECTOR_UNHEALTHY=1
DIAGNOSTIC_INCOMPLETE=2
PRODUCER_UNHEALTHY=20
PRODUCER_INCOMPLETE=21

script_dir="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
{redactor_validation}
if ! (validate_redactor); then
    exit "${{DIAGNOSTIC_INCOMPLETE}}"
fi
health_endpoint={shell_quote(linux_effective_health_endpoint(args))}
{diagnostic_config_paths_array}
privileged=()
command -v id >/dev/null 2>&1 || {{
    echo "ERROR: id is required for complete privileged diagnostics." >&2
    exit "${{DIAGNOSTIC_INCOMPLETE}}"
}}
current_uid="$(id -u)" || {{
    echo "ERROR: failed to determine the diagnostic user identity." >&2
    exit "${{DIAGNOSTIC_INCOMPLETE}}"
}}
[[ "${{current_uid}}" =~ ^[0-9]+$ ]] || {{
    echo "ERROR: id returned an invalid user identity." >&2
    exit "${{DIAGNOSTIC_INCOMPLETE}}"
}}
if [[ "${{current_uid}}" -ne 0 ]]; then
    command -v sudo >/dev/null 2>&1 || {{
        echo "ERROR: root or passwordless sudo is required for complete diagnostics." >&2
        exit "${{DIAGNOSTIC_INCOMPLETE}}"
    }}
    sudo -n env true >/dev/null 2>&1 || {{
        echo "ERROR: noninteractive sudo failed; diagnostics would be incomplete." >&2
        exit "${{DIAGNOSTIC_INCOMPLETE}}"
    }}
    privileged=(sudo -n)
fi

set +e
{{
diagnostic_failures=0
unhealthy_findings=0
echo '== package =='
package_output=""
package_status=0
if command -v rpm >/dev/null 2>&1; then
    if package_output="$(rpm -q splunk-otel-collector 2>&1)"; then
        package_status=0
    else
        package_status=$?
    fi
elif command -v dpkg-query >/dev/null 2>&1; then
    if package_output="$(dpkg-query -W splunk-otel-collector 2>&1)"; then
        package_status=0
    else
        package_status=$?
    fi
else
    echo 'ERROR: neither rpm nor dpkg-query is available; package diagnostics are incomplete.'
    diagnostic_failures=1
    package_status=-1
fi
[[ -z "${{package_output}}" ]] || printf '%s\\n' "${{package_output}}"
case "${{package_status}}" in
    0) ;;
    1)
        echo 'FINDING: the splunk-otel-collector package is not installed.'
        unhealthy_findings=1
        ;;
    -1) ;;
    *)
        echo "ERROR: package query failed unexpectedly (exit ${{package_status}}); diagnostics are incomplete."
        diagnostic_failures=1
        ;;
esac

echo '== service =='
service_state_output=""
if command -v systemctl >/dev/null 2>&1; then
    if service_state_output="$("${{privileged[@]}}" systemctl show --no-pager \
        --property=LoadState --property=ActiveState --property=SubState \
        splunk-otel-collector.service 2>&1)"; then
        printf '%s\\n' "${{service_state_output}}"
        service_load_state=""
        service_active_state=""
        service_sub_state=""
        while IFS='=' read -r service_key service_value; do
            case "${{service_key}}" in
                LoadState) service_load_state="${{service_value}}" ;;
                ActiveState) service_active_state="${{service_value}}" ;;
                SubState) service_sub_state="${{service_value}}" ;;
            esac
        done <<< "${{service_state_output}}"
        if [[ -z "${{service_load_state}}" || -z "${{service_active_state}}" || -z "${{service_sub_state}}" ]]; then
            echo 'ERROR: systemctl returned an incomplete service-state record.'
            diagnostic_failures=1
        elif [[ "${{service_load_state}}" == loaded \
            && "${{service_active_state}}" == active \
            && "${{service_sub_state}}" == running ]]; then
            echo 'Collector service state is active/running.'
        else
            echo "FINDING: Collector service is not active/running (load=${{service_load_state}}, active=${{service_active_state}}, sub=${{service_sub_state}})."
            unhealthy_findings=1
        fi
    else
        service_state_status=$?
        [[ -z "${{service_state_output}}" ]] || printf '%s\\n' "${{service_state_output}}"
        echo "ERROR: systemctl could not collect the Collector service state (exit ${{service_state_status}})."
        diagnostic_failures=1
    fi
else
    echo 'ERROR: systemctl is unavailable; complete service diagnostics require the supported systemd runtime.'
    diagnostic_failures=1
fi

echo '== health =='
health_output=""
if ! command -v curl >/dev/null 2>&1; then
    echo 'ERROR: curl is unavailable; health diagnostics are incomplete.'
    diagnostic_failures=1
elif health_output="$(curl -q -fsS --max-time 5 "${{health_endpoint}}" 2>&1)"; then
    [[ -z "${{health_output}}" ]] || printf '%s\\n' "${{health_output}}"
else
    health_status=$?
    [[ -z "${{health_output}}" ]] || printf '%s\\n' "${{health_output}}"
    echo "FINDING: Collector health endpoint did not respond successfully (curl exit ${{health_status}})."
    unhealthy_findings=1
fi
{obi_doctor_block}echo '== listeners =='
listener_output=""
listener_collection_complete=false
if command -v ss >/dev/null 2>&1; then
    if listener_output="$("${{privileged[@]}}" ss -lntp 2>&1)"; then
        listener_collection_complete=true
    else
        listener_status=$?
        [[ -z "${{listener_output}}" ]] || printf '%s\\n' "${{listener_output}}"
        echo "ERROR: ss listener collection failed (exit ${{listener_status}})."
        diagnostic_failures=1
    fi
elif command -v netstat >/dev/null 2>&1; then
    if listener_output="$("${{privileged[@]}}" netstat -lntp 2>&1)"; then
        listener_collection_complete=true
    else
        listener_status=$?
        [[ -z "${{listener_output}}" ]] || printf '%s\\n' "${{listener_output}}"
        echo "ERROR: netstat listener collection failed (exit ${{listener_status}})."
        diagnostic_failures=1
    fi
else
    echo 'ERROR: neither ss nor netstat is available; listener diagnostics are incomplete.'
    diagnostic_failures=1
fi
if [[ "${{listener_collection_complete}}" == true ]]; then
    standard_listener_found=false
    while IFS= read -r listener_line; do
        if [[ "${{listener_line}}" =~ :(4317|4318|13133|8888)([[:space:]]|$) ]]; then
            printf '%s\\n' "${{listener_line}}"
            standard_listener_found=true
        fi
    done <<< "${{listener_output}}"
    if [[ "${{standard_listener_found}}" != true ]]; then
        echo 'No standard Collector listeners found (a reviewed custom config may use different ports).'
    fi
fi

echo '== config ownership and digest (contents intentionally omitted) =='
config_count=0
hash_tool=""
if command -v sha256sum >/dev/null 2>&1; then
    hash_tool=sha256sum
elif command -v shasum >/dev/null 2>&1; then
    hash_tool=shasum
else
    echo 'ERROR: no SHA-256 tool is available; config diagnostics are incomplete.'
    diagnostic_failures=1
fi
for path in "${{diagnostic_config_paths[@]}}"; do
    config_probe_output=""
    # shellcheck disable=SC2016  # $1 belongs to the privileged child shell.
    if config_probe_output="$("${{privileged[@]}}" /bin/sh -c '
        if [ -e "$1" ] || [ -L "$1" ]; then
            printf present
        else
            printf missing
        fi
    ' splunk-otel-config-probe "${{path}}" 2>&1)"; then
        if [[ "${{config_probe_output}}" == present ]]; then
            config_count=$((config_count + 1))
            config_metadata_output=""
            if config_metadata_output="$("${{privileged[@]}}" ls -ld "${{path}}" 2>&1)"; then
                printf '%s\\n' "${{config_metadata_output}}"
            else
                config_metadata_status=$?
                [[ -z "${{config_metadata_output}}" ]] || printf '%s\\n' "${{config_metadata_output}}"
                echo "ERROR: config metadata collection failed for ${{path}} (exit ${{config_metadata_status}})."
                diagnostic_failures=1
            fi
            if [[ "${{hash_tool}}" == sha256sum ]]; then
                if ! "${{privileged[@]}}" sha256sum "${{path}}" 2>&1; then
                    echo "ERROR: config digest collection failed for ${{path}}."
                    diagnostic_failures=1
                fi
            elif [[ "${{hash_tool}}" == shasum ]]; then
                if ! "${{privileged[@]}}" shasum -a 256 "${{path}}" 2>&1; then
                    echo "ERROR: config digest collection failed for ${{path}}."
                    diagnostic_failures=1
                fi
            fi
        elif [[ "${{config_probe_output}}" != missing ]]; then
            printf '%s\\n' "${{config_probe_output}}"
            echo "ERROR: config existence probe returned an invalid response for ${{path}}."
            diagnostic_failures=1
        fi
    else
        config_probe_status=$?
        [[ -z "${{config_probe_output}}" ]] || printf '%s\\n' "${{config_probe_output}}"
        echo "ERROR: config existence probe failed for ${{path}} (exit ${{config_probe_status}})."
        diagnostic_failures=1
    fi
done
if (( config_count == 0 )); then
    echo 'FINDING: no expected Collector configuration files were found.'
    unhealthy_findings=1
fi

echo '== recent errors =='
if ! command -v journalctl >/dev/null 2>&1; then
    echo 'ERROR: journalctl is unavailable; recent-error diagnostics are incomplete.'
    diagnostic_failures=1
elif journal_output="$("${{privileged[@]}}" journalctl -u splunk-otel-collector \
    --since '-30 minutes' --no-pager -n 500 2>&1)"; then
    journal_error_match=false
    shopt -s nocasematch
    while IFS= read -r journal_line; do
        if [[ "${{journal_line}}" =~ (^|[^a-z])(error|panic|fatal|exporting[[:space:]]+failed|permanent[[:space:]]+error)([^a-z]|$) ]]; then
            printf '%s\\n' "${{journal_line}}"
            journal_error_match=true
            unhealthy_findings=1
        fi
    done <<< "${{journal_output}}"
    shopt -u nocasematch
    [[ "${{journal_error_match}}" == true ]] || echo 'No recent error-pattern matches.'
else
    journal_status=$?
    printf '%s\\n' "${{journal_output}}"
    echo "ERROR: journal collection failed (exit ${{journal_status}}); diagnostics are incomplete."
    diagnostic_failures=1
fi

echo '== diagnostic summary =='
if (( diagnostic_failures != 0 )); then
    echo 'diagnostic_complete=false'
    echo 'collector_health=unknown'
    exit "${{PRODUCER_INCOMPLETE}}"
elif (( unhealthy_findings != 0 )); then
    echo 'diagnostic_complete=true'
    echo 'collector_health=unhealthy'
    exit "${{PRODUCER_UNHEALTHY}}"
else
    echo 'diagnostic_complete=true'
    echo 'collector_health=healthy'
    exit 0
fi
}} 2>&1 | python3 "${{redactor_path}}"
doctor_pipeline_status=("${{PIPESTATUS[@]}}")
set -e
diagnostic_status="${{doctor_pipeline_status[0]:-${{PRODUCER_INCOMPLETE}}}}"
redaction_status="${{doctor_pipeline_status[1]:-${{DIAGNOSTIC_INCOMPLETE}}}}"
if (( redaction_status != 0 )); then
    echo "ERROR: diagnostic redaction failed (exit ${{redaction_status}})." >&2
    exit "${{DIAGNOSTIC_INCOMPLETE}}"
fi
case "${{diagnostic_status}}" in
    0)
        echo 'SPLUNK_OTEL_DIAGNOSTIC_RESULT=complete_healthy'
        exit 0
        ;;
    "${{PRODUCER_UNHEALTHY}}")
        echo 'SPLUNK_OTEL_DIAGNOSTIC_RESULT=complete_unhealthy'
        exit "${{COLLECTOR_UNHEALTHY}}"
        ;;
    "${{PRODUCER_INCOMPLETE}}")
        echo "ERROR: diagnostic collection was incomplete." >&2
        exit "${{DIAGNOSTIC_INCOMPLETE}}"
        ;;
    *)
        echo "ERROR: diagnostic producer exited unexpectedly (exit ${{diagnostic_status}})." >&2
        exit "${{DIAGNOSTIC_INCOMPLETE}}"
        ;;
esac
""",
        executable=True,
    )

    write_text(
        linux_dir / "support-bundle-local.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail
umask 077

script_dir="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
{redactor_validation}
{support_output_guard}
validate_redactor
output_request="${{1:-splunk-otel-support-$(date -u +%Y%m%dT%H%M%SZ).tgz}}"
output=""
output_stage=""
output_tmp=""
prepare_support_output "${{output_request}}"
work=""
cleanup() {{
    [[ -z "${{work}}" ]] || rm -rf -- "${{work}}"
    [[ -z "${{output_stage}}" ]] || rm -rf -- "${{output_stage}}"
}}
trap cleanup EXIT
work="$(mktemp -d)"

privileged=()
if [[ "$(id -u)" -ne 0 ]]; then
    command -v sudo >/dev/null 2>&1 || {{
        echo "ERROR: root or passwordless sudo is required for a complete support bundle." >&2
        exit 1
    }}
    sudo -n env true >/dev/null 2>&1 || {{
        echo "ERROR: noninteractive sudo failed; refusing to create an incomplete support bundle." >&2
        exit 1
    }}
    privileged=(sudo -n)
fi

set +e
bash "${{script_dir}}/doctor-local.sh" > "${{work}}/doctor.txt" 2>&1
doctor_status=$?
set -e
doctor_last_line=""
while IFS= read -r doctor_line || [[ -n "${{doctor_line}}" ]]; do
    doctor_last_line="${{doctor_line}}"
done < "${{work}}/doctor.txt"
collector_health=""
case "${{doctor_status}}:${{doctor_last_line}}" in
    '0:SPLUNK_OTEL_DIAGNOSTIC_RESULT=complete_healthy')
        collector_health=healthy
        ;;
    '1:SPLUNK_OTEL_DIAGNOSTIC_RESULT=complete_unhealthy')
        collector_health=unhealthy
        ;;
    *)
        echo "ERROR: doctor diagnostics, collection, or redaction was incomplete; no support bundle was published." >&2
        exit 1
        ;;
esac

set +e
"${{privileged[@]}}" journalctl -u splunk-otel-collector --since '-2 hours' --no-pager -n 2000 2>&1 \
    | python3 "${{redactor_path}}" > "${{work}}/journal-redacted.txt"
journal_pipeline_status=("${{PIPESTATUS[@]}}")
set -e
journal_status="${{journal_pipeline_status[0]:-1}}"
journal_redaction_status="${{journal_pipeline_status[1]:-1}}"
if (( journal_status != 0 )); then
    echo "ERROR: support-bundle journal collection failed (exit ${{journal_status}}); no support bundle was published." >&2
    exit 1
fi
if (( journal_redaction_status != 0 )); then
    echo "ERROR: support-bundle journal redaction failed (exit ${{journal_redaction_status}}); no support bundle was published." >&2
    exit 1
fi
printf '%s\\n' \
    'schema_version=1' \
    'diagnostics_complete=true' \
    "collector_health=${{collector_health}}" \
    "doctor_exit_code=${{doctor_status}}" \
    > "${{work}}/diagnostic-state.txt"
if ! tar -czf "${{output_tmp}}" -C "${{work}}" .; then
    echo "ERROR: support-bundle archive assembly failed; no support bundle was published." >&2
    exit 1
fi
publish_support_output
echo "Created redacted support bundle: ${{output}}"
if [[ "${{collector_health}}" == unhealthy ]]; then
    echo "Collector findings are unhealthy, but diagnostics were complete and the redacted bundle was published."
fi
echo "Review it manually before sharing; application payloads can still contain sensitive data."
""",
        executable=True,
    )

    write_text(
        linux_dir / "doctor-ssh.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail
umask 077

script_dir="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
{redactor_validation}
validate_redactor
{host_assignment}
{user_assignment}
{port_assignment}
[[ -n "${{LINUX_HOST}}" && "${{LINUX_HOST}}" =~ ^[A-Za-z0-9._:-]+$ ]] || {{ echo "ERROR: invalid LINUX_HOST." >&2; exit 1; }}
[[ -n "${{SSH_USER}}" && "${{SSH_USER}}" =~ ^[A-Za-z_][A-Za-z0-9_.-]*$ ]] || {{ echo "ERROR: invalid SSH_USER." >&2; exit 1; }}
[[ "${{SSH_PORT}}" =~ ^[0-9]+$ ]] && (( SSH_PORT >= 1 && SSH_PORT <= 65535 )) || {{ echo "ERROR: invalid SSH_PORT." >&2; exit 1; }}
ssh_args=(-p "${{SSH_PORT}}")
scp_args=(-P "${{SSH_PORT}}")
{ssh_key_status_block}
ssh_target="${{SSH_USER}}@${{LINUX_HOST}}"
scp_target="${{ssh_target}}"
[[ "${{LINUX_HOST}}" != *:* ]] || scp_target="${{SSH_USER}}@[${{LINUX_HOST}}]"
remote_dir="$(ssh "${{ssh_args[@]}}" "${{ssh_target}}" 'umask 077; mktemp -d /tmp/splunk-otel-doctor.XXXXXX')"
[[ "${{remote_dir}}" =~ ^/tmp/splunk-otel-doctor\\.[A-Za-z0-9]+$ ]] || {{ echo "ERROR: unsafe remote doctor directory." >&2; exit 1; }}
cleanup() {{ printf -v q '%q' "${{remote_dir}}"; ssh "${{ssh_args[@]}}" "${{ssh_target}}" "rm -rf -- ${{q}}" >/dev/null 2>&1 || true; }}
trap cleanup EXIT
scp "${{scp_args[@]}}" -- "${{script_dir}}/doctor-local.sh" "${{script_dir}}/redact-stream.py" "${{scp_target}}:${{remote_dir}}/"
ssh "${{ssh_args[@]}}" "${{ssh_target}}" "bash ${{remote_dir}}/doctor-local.sh"
""",
        executable=True,
    )

    write_text(
        linux_dir / "support-bundle-ssh.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail
umask 077

script_dir="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
{redactor_validation}
{support_output_guard}
validate_redactor
output="${{1:-splunk-otel-support-ssh-$(date -u +%Y%m%dT%H%M%SZ).tgz}}"
output_stage=""
output_tmp=""
{host_assignment}
{user_assignment}
{port_assignment}
[[ -n "${{LINUX_HOST}}" && "${{LINUX_HOST}}" =~ ^[A-Za-z0-9._:-]+$ ]] || {{ echo "ERROR: invalid LINUX_HOST." >&2; exit 1; }}
[[ -n "${{SSH_USER}}" && "${{SSH_USER}}" =~ ^[A-Za-z_][A-Za-z0-9_.-]*$ ]] || {{ echo "ERROR: invalid SSH_USER." >&2; exit 1; }}
[[ "${{SSH_PORT}}" =~ ^[0-9]+$ ]] && (( SSH_PORT >= 1 && SSH_PORT <= 65535 )) || {{ echo "ERROR: invalid SSH_PORT." >&2; exit 1; }}
ssh_args=(-p "${{SSH_PORT}}")
scp_args=(-P "${{SSH_PORT}}")
{ssh_key_status_block}
ssh_target="${{SSH_USER}}@${{LINUX_HOST}}"
scp_target="${{ssh_target}}"
[[ "${{LINUX_HOST}}" != *:* ]] || scp_target="${{SSH_USER}}@[${{LINUX_HOST}}]"
prepare_support_output "${{output}}"
remote_dir=""
cleanup() {{
    [[ -z "${{output_stage}}" ]] || rm -rf -- "${{output_stage}}"
    if [[ -n "${{remote_dir}}" ]]; then
        printf -v q '%q' "${{remote_dir}}"
        ssh "${{ssh_args[@]}}" "${{ssh_target}}" "rm -rf -- ${{q}}" >/dev/null 2>&1 || true
    fi
}}
trap cleanup EXIT
remote_dir="$(ssh "${{ssh_args[@]}}" "${{ssh_target}}" 'umask 077; mktemp -d /tmp/splunk-otel-support.XXXXXX')"
[[ "${{remote_dir}}" =~ ^/tmp/splunk-otel-support\\.[A-Za-z0-9]+$ ]] || {{ echo "ERROR: unsafe remote support directory." >&2; exit 1; }}
scp "${{scp_args[@]}}" -- "${{script_dir}}/doctor-local.sh" "${{script_dir}}/support-bundle-local.sh" "${{script_dir}}/redact-stream.py" "${{scp_target}}:${{remote_dir}}/"
ssh "${{ssh_args[@]}}" "${{ssh_target}}" "cd ${{remote_dir}} && bash support-bundle-local.sh support.tgz" >/dev/null
scp "${{scp_args[@]}}" -- "${{scp_target}}:${{remote_dir}}/support.tgz" "${{output_tmp}}"
tar -tzf "${{output_tmp}}" >/dev/null
publish_support_output
echo "Created redacted remote support bundle: ${{output}}"
echo "Review it manually before sharing; application payloads can still contain sensitive data."
""",
        executable=True,
    )

    uninstall_obi = ""
    if str_bool(args.enable_obi):
        uninstall_obi = " --with-obi"
        if args.obi_install_dir:
            uninstall_obi += f" --obi-install-dir {shell_quote(args.obi_install_dir)}"
    uninstall_npm = ""
    if str_bool(args.enable_autoinstrumentation) and args.npm_path:
        uninstall_npm = f" --npm-path {shell_quote(args.npm_path)}"
    auto_instrumentation_uninstall_guard = r'''
auto_instrumentation_present=false
if command -v dpkg-query >/dev/null 2>&1 \
    && dpkg-query -W -f='${Status}' splunk-otel-auto-instrumentation 2>/dev/null \
        | grep -qx 'install ok installed'; then
    auto_instrumentation_present=true
fi
if command -v rpm >/dev/null 2>&1 \
    && rpm -q splunk-otel-auto-instrumentation >/dev/null 2>&1; then
    auto_instrumentation_present=true
fi
if [[ -e /usr/lib/splunk-instrumentation/libsplunk.so \
      || -L /usr/lib/splunk-instrumentation/libsplunk.so \
      || -d /usr/lib/splunk-instrumentation/splunk-otel-js ]]; then
    auto_instrumentation_present=true
fi
if [[ "${auto_instrumentation_present}" == "true" \
      && "${SPLUNK_OTEL_CONFIRM_REMOVE_AUTO_INSTRUMENTATION:-}" != "yes" ]]; then
    echo "ERROR: The upstream uninstaller will also remove detected Splunk auto-instrumentation packages/artifacts." >&2
    echo "       Set SPLUNK_OTEL_CONFIRM_REMOVE_AUTO_INSTRUMENTATION=yes only after reviewing that additional blast radius." >&2
    exit 1
fi
'''
    runtime_secret_cleanup_function = r'''
cleanup_runtime_secret_files() {
    local action="${1:-remove}"
    local path
    local -a paths=(
        /etc/otel/collector/splunk-otel-collector.conf
        /etc/otel/collector/splunk_env
    )
    for path in "${paths[@]}"; do
        if [[ -L "${path}" ]]; then
            echo "ERROR: Refusing to remove symlink at token-bearing runtime environment path: ${path}" >&2
            return 1
        fi
        if [[ -e "${path}" && ! -f "${path}" ]]; then
            echo "ERROR: Refusing to remove non-regular token-bearing runtime environment path: ${path}" >&2
            return 1
        fi
    done
    if [[ "${action}" == "validate" ]]; then
        return 0
    fi
    rm -f -- "${paths[@]}"
    for path in "${paths[@]}"; do
        if [[ -e "${path}" || -L "${path}" ]]; then
            echo "ERROR: Token-bearing runtime environment file remains after uninstall: ${path}" >&2
            return 1
        fi
    done
    echo "Removed installer-generated token-bearing Collector environment files."
}
'''
    write_text(
        linux_dir / "uninstall-local.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail
umask 077

[[ "${{SPLUNK_OTEL_CONFIRM_UNINSTALL:-}}" == "yes" ]] || {{
    echo "ERROR: Set SPLUNK_OTEL_CONFIRM_UNINSTALL=yes after reviewing this destructive action." >&2
    exit 1
}}
{auto_instrumentation_uninstall_guard}
{installer_url_assignment}
{installer_sha_assignment}
{validation_functions}
{runtime_secret_cleanup_function}
cleanup_runtime_secret_files validate
if command -v sudo >/dev/null 2>&1 && [[ "$(id -u)" -ne 0 ]]; then
    sudo -n env true >/dev/null 2>&1 || {{
        echo "ERROR: passwordless noninteractive sudo is required for uninstall." >&2
        exit 1
    }}
fi
installer_path="$(mktemp)"
trap 'rm -f "${{installer_path}}"' EXIT
curl -q --proto '=https' -fsSL "${{INSTALLER_URL}}" -o "${{installer_path}}"
verify_installer "${{installer_path}}"
chmod 700 "${{installer_path}}"
uninstall_args=(--uninstall{uninstall_obi}{uninstall_npm})
if command -v sudo >/dev/null 2>&1 && [[ "$(id -u)" -ne 0 ]]; then
    sudo -n sh "${{installer_path}}" "${{uninstall_args[@]}}"
    sudo -n bash -c "$(declare -f cleanup_runtime_secret_files); cleanup_runtime_secret_files"
else
    sh "${{installer_path}}" "${{uninstall_args[@]}}"
    cleanup_runtime_secret_files
fi
""",
        executable=True,
    )

    write_text(
        linux_dir / "uninstall-ssh.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail
umask 077

[[ "${{SPLUNK_OTEL_CONFIRM_UNINSTALL:-}}" == "yes" ]] || {{
    echo "ERROR: Set SPLUNK_OTEL_CONFIRM_UNINSTALL=yes after reviewing this destructive action." >&2
    exit 1
}}
script_dir="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
{host_assignment}
{user_assignment}
{port_assignment}
[[ -n "${{LINUX_HOST}}" && "${{LINUX_HOST}}" =~ ^[A-Za-z0-9._:-]+$ ]] || {{
    echo "ERROR: LINUX_HOST is empty or contains unsupported characters." >&2
    exit 1
}}
[[ -n "${{SSH_USER}}" && "${{SSH_USER}}" =~ ^[A-Za-z_][A-Za-z0-9_.-]*$ ]] || {{
    echo "ERROR: SSH_USER is empty or contains unsupported characters." >&2
    exit 1
}}
[[ "${{SSH_PORT}}" =~ ^[0-9]+$ ]] && (( SSH_PORT >= 1 && SSH_PORT <= 65535 )) || {{
    echo "ERROR: SSH_PORT must be an integer from 1 through 65535." >&2
    exit 1
}}
ssh_args=(-p "${{SSH_PORT}}")
{ssh_key_status_block}
if [[ "${{SPLUNK_OTEL_CONFIRM_REMOVE_AUTO_INSTRUMENTATION:-}}" == "yes" ]]; then
    ssh "${{ssh_args[@]}}" "${{SSH_USER}}@${{LINUX_HOST}}" \
        'SPLUNK_OTEL_CONFIRM_UNINSTALL=yes SPLUNK_OTEL_CONFIRM_REMOVE_AUTO_INSTRUMENTATION=yes bash -s' \
        < "${{script_dir}}/uninstall-local.sh"
else
    ssh "${{ssh_args[@]}}" "${{SSH_USER}}@${{LINUX_HOST}}" \
        'SPLUNK_OTEL_CONFIRM_UNINSTALL=yes SPLUNK_OTEL_CONFIRM_REMOVE_AUTO_INSTRUMENTATION=no bash -s' \
        < "${{script_dir}}/uninstall-local.sh"
fi
""",
        executable=True,
    )

    write_text(
        linux_dir / "README.md",
        f"""# Splunk Observability Linux OTel Collector

Review the installer wrapper before applying.

Target prerequisites are Bash, curl, Python 3, tar, a SHA-256 tool, and root or
passwordless noninteractive sudo. `install-local.sh` runs
`preflight-local.sh`; SSH apply copies and runs the same preflight remotely
before package mutation. Status also requires complete service/journal access.

Local apply:

```bash
bash install-local.sh
bash status-local.sh
```

SSH apply:

```bash
bash install-ssh.sh
bash status-ssh.sh
```

Rendered execution mode: `{args.execution}`
Rendered Linux collector mode: `{args.linux_mode}`
Effective receiver bind: `{linux_effective_listen_interface(args)}`
Audited collector version: `{args.collector_version}`
Pinned installer SHA-256: `{args.installer_sha256.lower()}`

Linux OBI scope: `{'pinned binary install and version validation only; no OBI runtime/service is configured' if str_bool(args.enable_obi) else 'not requested'}`

Operational helpers: `doctor-local.sh`, `support-bundle-local.sh`, and the
confirmation-gated `uninstall-local.sh`. Doctor exit `0` means complete and
healthy, `1` means complete with unhealthy findings, and `2` means diagnostic
collection or redaction was incomplete; only the matching final completion
marker is authoritative. Support bundles publish for complete `0`/`1` results,
record `diagnostic-state.txt`, and refuse incomplete evidence. The installer persists its runtime
environment (including the access token) under `/etc/otel/collector`; protect
that directory and include token rotation in the operating procedure. Uninstall
deletes the installer-generated token-bearing environment files, but it cannot
revoke the token. If auto-instrumentation packages or artifacts are detected,
uninstall also requires
`SPLUNK_OTEL_CONFIRM_REMOVE_AUTO_INSTRUMENTATION=yes` because the upstream
uninstaller removes them together with the Collector. When OBI is requested,
hand off runtime configuration, privileges, endpoints, and process supervision
before claiming OBI telemetry readiness.
""",
    )


def hec_default_index(args: argparse.Namespace) -> str:
    if args.hec_default_index:
        return args.hec_default_index
    if platform_hec_logs_enabled(args):
        return args.platform_hec_index
    if platform_metrics_enabled(args):
        return args.platform_metrics_index
    if platform_traces_enabled(args):
        return args.platform_traces_index
    return args.platform_hec_index or "k8s_logs"


def hec_allowed_indexes(args: argparse.Namespace) -> str:
    indexes = [hec_default_index(args)]
    if platform_hec_logs_enabled(args):
        indexes.append(args.platform_hec_index)
    if platform_metrics_enabled(args):
        indexes.append(args.platform_metrics_index)
    if platform_traces_enabled(args):
        indexes.append(args.platform_traces_index)
    required = list(dict.fromkeys(index for index in indexes if index))
    if args.hec_allowed_indexes:
        explicit = list(
            dict.fromkeys(
                value.strip() for value in args.hec_allowed_indexes.split(",") if value.strip()
            )
        )
        missing = [index for index in required if index not in explicit]
        if missing:
            raise SystemExit(
                "--hec-allowed-indexes must include the default and every effective destination index: "
                + ", ".join(missing)
            )
        return ",".join(explicit)
    return ",".join(required)


def hec_setup_script() -> Path:
    return Path(__file__).resolve().parents[3] / "skills/splunk-hec-service-setup/scripts/setup.sh"


def hec_setup_args(args: argparse.Namespace, output_dir: Path, phase: str) -> list[str]:
    token_file = platform_hec_token_path(args, output_dir)
    setup_args = [
        "--platform",
        args.hec_platform,
        "--phase",
        phase,
        "--output-dir",
        str(output_dir / "platform-hec-service-rendered"),
        "--splunk-home",
        args.hec_splunk_home,
        "--app-name",
        args.hec_app_name,
        "--token-name",
        args.hec_token_name,
        "--description",
        args.hec_description,
        "--default-index",
        hec_default_index(args),
        "--allowed-indexes",
        hec_allowed_indexes(args),
        "--source",
        args.hec_source,
        "--sourcetype",
        args.hec_sourcetype,
        "--port",
        args.hec_port,
        "--enable-ssl",
        args.hec_enable_ssl,
        "--use-ack",
        args.hec_use_ack,
        "--s2s-indexes-validation",
        args.hec_s2s_indexes_validation,
        "--restart-splunk",
        args.hec_restart_splunk,
    ]
    if args.hec_platform == "cloud":
        setup_args.extend(["--write-token-file", token_file])
    else:
        setup_args.extend(["--token-file", token_file])
    return setup_args


def render_hec_helper_script(path: Path, setup_args: list[str], title: str) -> None:
    setup_path = str(hec_setup_script())
    args_array = bash_array("hec_args", setup_args)
    write_text(
        path,
        f"""#!/usr/bin/env bash
set -euo pipefail

# {title}
hec_setup={shell_quote(setup_path)}

{args_array}

bash "${{hec_setup}}" "${{hec_args[@]}}"
""",
        executable=True,
    )


def render_platform_hec_helper(args: argparse.Namespace, output_dir: Path) -> None:
    hec_dir = output_dir / "platform-hec"
    if hec_dir.exists():
        shutil.rmtree(hec_dir)
    hec_dir.mkdir(parents=True, exist_ok=True)

    token_file = platform_hec_token_path(args, output_dir)
    hec_render_dir = output_dir / "platform-hec-service-rendered" / "hec-service"

    render_hec_helper_script(
        hec_dir / "render-hec-service.sh",
        hec_setup_args(args, output_dir, "render"),
        "Render reusable Splunk Platform HEC service assets.",
    )
    render_hec_helper_script(
        hec_dir / "apply-hec-service.sh",
        hec_setup_args(args, output_dir, "apply"),
        "Create or update the Splunk Platform HEC token and write/read the token file.",
    )
    render_hec_helper_script(
        hec_dir / "status-hec-service.sh",
        hec_setup_args(args, output_dir, "status"),
        "Check the rendered Splunk Platform HEC service state.",
    )

    write_text(
        hec_dir / "README.md",
        f"""# Splunk Platform HEC Helper

This folder bridges the OTel Collector Kubernetes log path to the reusable
`splunk-hec-service-setup` skill.

Run this first to render the HEC service assets:

```bash
bash render-hec-service.sh
```

Review the HEC assets under:

`{hec_render_dir}`

Then create or update the token:

```bash
bash apply-hec-service.sh
```

Token file for the OTel Collector Kubernetes Secret:

`{token_file}`

Use that same path with `--platform-hec-token-file` when rendering or applying
the OTel Collector. For Splunk Cloud, ACS creates the token and writes it to the
file. For Splunk Enterprise, the HEC service helper reads or creates the local
token file before writing `inputs.conf`.

Rendered HEC platform: `{args.hec_platform}`
Rendered HEC token name: `{args.hec_token_name}`
Rendered HEC default index: `{hec_default_index(args)}`
Rendered HEC allowed indexes: `{hec_allowed_indexes(args)}`
""",
    )


def _normal_member_name(name: str) -> str:
    normalized = name.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _read_tar_text(tar: tarfile.TarFile, member_name: str) -> str:
    extracted = tar.extractfile(member_name)
    if extracted is None:
        return ""
    return extracted.read().decode("utf-8", errors="replace")


def _parse_conf(text: str) -> tuple[list[str], dict[str, dict[str, str]]]:
    stanzas: list[str] = []
    fields: dict[str, dict[str, str]] = {}
    current = ""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        stanza_match = re.match(r"^\[([^\]]+)\]$", stripped)
        if stanza_match:
            current = stanza_match.group(1)
            stanzas.append(current)
            fields.setdefault(current, {})
            continue
        if current and "=" in stripped:
            key, value = stripped.split("=", 1)
            fields[current][key.strip()] = value.strip()
    return stanzas, fields


def _first_stanza_matching(stanzas: list[str], prefix: str) -> str:
    for stanza in stanzas:
        if stanza.startswith(prefix):
            return stanza
    return stanzas[0] if stanzas else ""


def _extract_app_version(app_conf: str) -> str:
    for pattern in (
        r"(?ims)^\[launcher\].*?^\s*version\s*=\s*([^\s#]+)",
        r"(?ims)^\[id\].*?^\s*version\s*=\s*([^\s#]+)",
        r"(?im)^\s*version\s*=\s*([^\s#]+)",
    ):
        match = re.search(pattern, app_conf)
        if match:
            return match.group(1).strip()
    return ""


def _spec_rendered_stanza(spec_stanza: str) -> str:
    if not spec_stanza or "://" not in spec_stanza:
        return "Splunk_TA_otel://Splunk_TA_otel"
    if "<name>" in spec_stanza:
        return spec_stanza.replace("<name>", "Splunk_TA_otel")
    return spec_stanza


def _token_field_style(default_fields: dict[str, str], spec_fields: dict[str, str]) -> str:
    fields = set(default_fields) | set(spec_fields)
    if "splunk_access_token" in fields:
        return "current"
    if "splunk_access_token_file" in fields:
        return "legacy-file"
    return "unknown"


def _flavor_from_os(supported_os: list[str]) -> str:
    if supported_os == ["linux-x86-64"]:
        return "linux-x86-64"
    if supported_os == ["windows-x86-64"]:
        return "windows-x86-64"
    if supported_os == ["linux-x86-64", "windows-x86-64"]:
        return "multi-os"
    return "unknown"


def _inspect_ta_package(package_path: str) -> dict[str, object]:
    path = Path(package_path).expanduser().resolve()
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise SystemExit(
            f"--ta-package-path must be a readable non-symlink regular file: {path}"
        ) from exc
    with os.fdopen(descriptor, "rb") as archive_handle:
        archive_before = os.fstat(archive_handle.fileno())
        if not stat.S_ISREG(archive_before.st_mode) or archive_before.st_nlink != 1:
            raise SystemExit(
                f"--ta-package-path must be a single-link regular file: {path}"
            )
        if archive_before.st_size > 2 * 1024 * 1024 * 1024:
            raise SystemExit(f"--ta-package-path exceeds the 2 GiB archive-size safety limit: {path}")
        digest = hashlib.sha256()
        for chunk in iter(lambda: archive_handle.read(1024 * 1024), b""):
            digest.update(chunk)
        package_sha256 = digest.hexdigest()
        archive_handle.seek(0)
        try:
            tar = tarfile.open(fileobj=archive_handle, mode="r:*")
        except tarfile.TarError as exc:
            raise SystemExit(f"--ta-package-path is not a readable tar archive: {path}: {exc}") from exc
        with tar:
            all_members = tar.getmembers()
            if len(all_members) > 20_000:
                raise SystemExit(f"{path} has too many archive members ({len(all_members)} > 20000)")
            normalized_names: set[str] = set()
            expanded_size = 0
            for member in all_members:
                name = _normal_member_name(member.name)
                if not name or name == ".":
                    if not member.isdir():
                        raise SystemExit(f"unsafe root TA package member: {member.name}")
                    continue
                if name.startswith("/") or ".." in Path(name).parts:
                    raise SystemExit(f"unsafe TA package member path in --ta-package-path: {path}")
                if not (member.isfile() or member.isdir()):
                    raise SystemExit(f"unsupported TA package member type in --ta-package-path: {member.name}")
                if name in normalized_names:
                    raise SystemExit(f"duplicate TA package member in --ta-package-path: {member.name}")
                normalized_names.add(name)
                if member.isfile():
                    if member.size > 512 * 1024 * 1024:
                        raise SystemExit(f"TA package member exceeds 512 MiB: {member.name}")
                    expanded_size += member.size
            if expanded_size > 2 * 1024 * 1024 * 1024:
                raise SystemExit(f"{path} expands beyond the 2 GiB safety limit")
            members = [member for member in all_members if member.isfile()]
            names = [_normal_member_name(member.name) for member in members]
            member_by_name = dict(zip(names, members))
            roots = [root for root in TA_SUPPORTED_ROOTS if any(name.startswith(f"{root}/") for name in names)]
            if not roots:
                raise SystemExit(
                    f"{path} does not contain a supported app root. Expected one of: {', '.join(TA_SUPPORTED_ROOTS)}"
                )
            if len(roots) != 1:
                raise SystemExit(f"{path} must contain exactly one supported app root (found: {', '.join(roots)})")
            for name in (_normal_member_name(member.name) for member in all_members):
                if not name or name == ".":
                    continue
                top_level = Path(name).parts[0]
                if top_level not in roots:
                    raise SystemExit(f"{path} contains an unsupported top-level TA package member: {name}")
            app_root = roots[0]
            relative_names = {
                name[len(app_root) + 1 :]
                for name in names
                if name.startswith(f"{app_root}/")
            }
            missing = [relative for relative in TA_REQUIRED_FILES if relative not in relative_names]
            supported_os = [
                flavor
                for flavor, binary in TA_PLATFORM_BINARIES.items()
                if binary in relative_names
            ]
            binary_missing = []
            if app_root.endswith("_linux_x86_64") and "linux-x86-64" not in supported_os:
                binary_missing.append(TA_PLATFORM_BINARIES["linux-x86-64"])
            elif app_root.endswith("_windows_x86_64") and "windows-x86-64" not in supported_os:
                binary_missing.append(TA_PLATFORM_BINARIES["windows-x86-64"])
            elif app_root == "Splunk_TA_otel" and not supported_os:
                binary_missing.extend(TA_PLATFORM_BINARIES.values())
            if missing or binary_missing:
                problems = missing + binary_missing
                raise SystemExit(f"{path} is missing required TA files: {', '.join(problems)}")

            def text(relative: str) -> str:
                return _read_tar_text(tar, member_by_name[f"{app_root}/{relative}"].name)

            default_inputs = text("default/inputs.conf")
            spec = text("README/inputs.conf.spec")
            app_conf = text("default/app.conf")
            default_stanzas, default_fields_by_stanza = _parse_conf(default_inputs)
            spec_stanzas, spec_fields_by_stanza = _parse_conf(spec)
            default_stanza = _first_stanza_matching(default_stanzas, "Splunk_TA_otel")
            spec_stanza = _first_stanza_matching(spec_stanzas, "Splunk_TA_otel://")
            rendered_stanza = _spec_rendered_stanza(spec_stanza)
            default_fields = default_fields_by_stanza.get(default_stanza, {})
            spec_fields = spec_fields_by_stanza.get(spec_stanza, {})
            token_style = _token_field_style(default_fields, spec_fields)
            supported_os = sorted(supported_os)
            flavor = _flavor_from_os(supported_os)
            view_files = sorted(
                relative
                for relative in relative_names
                if relative.startswith("data/ui/views/") and not relative.endswith("/")
            )
            nav_files = sorted(
                relative for relative in relative_names if relative.startswith("data/ui/nav/")
            )
            macro_files = sorted(
                relative
                for relative in relative_names
                if relative in {"default/macros.conf", "local/macros.conf"}
            )
            archive_after = os.fstat(archive_handle.fileno())
            archive_identity_before = (
                archive_before.st_dev,
                archive_before.st_ino,
                archive_before.st_size,
                archive_before.st_mtime_ns,
                archive_before.st_ctime_ns,
                archive_before.st_nlink,
            )
            archive_identity_after = (
                archive_after.st_dev,
                archive_after.st_ino,
                archive_after.st_size,
                archive_after.st_mtime_ns,
                archive_after.st_ctime_ns,
                archive_after.st_nlink,
            )
            if archive_identity_after != archive_identity_before:
                raise SystemExit(f"--ta-package-path changed while it was inspected: {path}")
            artifact = TA_ARTIFACTS[app_root]
            package_version = _extract_app_version(app_conf)
            return {
                "path": str(path),
                "size_bytes": archive_before.st_size,
                "expanded_size_bytes": expanded_size,
                "member_count": len(all_members),
                "sha256": package_sha256,
                "matches_audited_release_sha256": package_sha256 == artifact["sha256"],
                "matches_audited_release_version": package_version == TA_LATEST_VERSION,
                "audited_artifact": artifact,
                "app_root": app_root,
                "version": package_version,
                "package_flavor": flavor,
                "supported_os": supported_os,
                "token_field_style": token_style,
                "default_stanza": default_stanza,
                "spec_stanza": spec_stanza,
                "rendered_stanza": rendered_stanza,
                "stanza_mismatch": default_stanza != rendered_stanza,
                "default_fields": default_fields,
                "spec_fields": spec_fields,
                "config_files": {
                    "agent": "configs/agent_config.yaml" in relative_names,
                    "gateway": "configs/gateway_config.yaml" in relative_names,
                },
                "platform_binaries": {
                    "linux_x86_64": TA_PLATFORM_BINARIES["linux-x86-64"] in relative_names,
                    "windows_x86_64": TA_PLATFORM_BINARIES["windows-x86-64"] in relative_names,
                },
                "dashboard_evidence": {
                    "ships_prebuilt_dashboards": bool(view_files),
                    "view_files": view_files,
                    "navigation_files": nav_files,
                    "macro_files": macro_files,
                    "conclusion": (
                        "package contains pre-built view files; complete dashboard visibility/data validation"
                        if view_files
                        else "package contains no data/ui/views files; validate collector telemetry in Observability and _internal instead"
                    ),
                },
            }


def _redact_conf_fields(fields: dict[str, str]) -> dict[str, str]:
    redacted: dict[str, str] = {}
    for key, value in fields.items():
        normalized_key = re.sub(r"[^a-z0-9]", "", key.lower())
        always_sensitive = normalized_key in {
            "splunkcollectorenvvars",
            "splunkcollectorcmdargs",
        }
        value_sensitive = bool(
            SECRET_ASSIGNMENT_PATTERN.search(value) or SECRET_FLAG_PATTERN.search(value)
        )
        redacted[key] = (
            "__REDACTED_SECRET_FIELD__"
            if SECRET_KEY_PATTERN.search(key) or always_sensitive or value_sensitive
            else value
        )
    return redacted


def _metadata_safe_package(package: dict[str, object]) -> dict[str, object]:
    safe = dict(package)
    safe["default_fields"] = _redact_conf_fields(dict(package.get("default_fields", {})))
    safe["spec_fields"] = _redact_conf_fields(dict(package.get("spec_fields", {})))
    return safe


def _generic_ta_package() -> dict[str, object]:
    return {
        "path": "",
        "size_bytes": 0,
        "expanded_size_bytes": 0,
        "member_count": 0,
        "sha256": "",
        "matches_audited_release_sha256": False,
        "matches_audited_release_version": True,
        "audited_artifact": TA_ARTIFACTS["Splunk_TA_otel"],
        "app_root": "Splunk_TA_otel",
        "version": TA_LATEST_VERSION,
        "package_flavor": "unknown",
        "supported_os": [],
        "token_field_style": "current",
        "default_stanza": "Splunk_TA_otel",
        "spec_stanza": "Splunk_TA_otel://<name>",
        "rendered_stanza": "Splunk_TA_otel://Splunk_TA_otel",
        "stanza_mismatch": True,
        "default_fields": {},
        "spec_fields": {
            "splunk_access_token": "<value>",
            "splunk_realm": "<value>",
            "splunk_config": "<value>",
            "splunk_collector_log_level": "<value>",
            "splunk_collector_env_vars": "<value>",
            "splunk_collector_cmd_args": "<value>",
        },
        "config_files": {"agent": True, "gateway": True},
        "platform_binaries": {"linux_x86_64": False, "windows_x86_64": False},
        "dashboard_evidence": {
            "ships_prebuilt_dashboards": None,
            "view_files": [],
            "navigation_files": [],
            "macro_files": [],
            "conclusion": "not audited because no package was supplied",
        },
    }


def inspect_ta_packages(args: argparse.Namespace) -> list[dict[str, object]]:
    packages = [_inspect_ta_package(package_path) for package_path in args.ta_package_path]
    if not packages:
        packages = [_generic_ta_package()]
    concrete = [package for package in packages if package["path"]]
    if args.ta_secret_mode != "placeholder" and not concrete:
        raise SystemExit("an actionable --ta-secret-mode requires at least one --ta-package-path")
    app_roots = [str(package["app_root"]) for package in concrete]
    if len(app_roots) != len(set(app_roots)):
        raise SystemExit("duplicate TA app roots are not allowed")
    if args.ta_target != "deployment-server" and len(concrete) > 1:
        raise SystemExit(f"--ta-target {args.ta_target} accepts exactly one TA package")
    if args.ta_target != "deployment-server" and concrete and not all(
        "linux-x86-64" in package["supported_os"] for package in concrete
    ):
        raise SystemExit(
            f"--ta-target {args.ta_target} uses Bash/Python local apply assets and requires a Linux-capable package; "
            "deploy Windows-only packages through a deployment server and Agent Management"
        )
    os_owners: dict[str, str] = {}
    for package in concrete:
        for supported_os in package["supported_os"]:
            if supported_os in os_owners:
                raise SystemExit(
                    "TA packages have overlapping runtime coverage for "
                    f"{supported_os}: {os_owners[supported_os]} and {package['app_root']}"
                )
            os_owners[str(supported_os)] = str(package["app_root"])
    if args.ta_package_flavor != "auto":
        for package in packages:
            flavor = package["package_flavor"]
            if flavor != "unknown" and flavor != args.ta_package_flavor:
                raise SystemExit(
                    f"{package['path']} flavor is {flavor}, not requested --ta-package-flavor {args.ta_package_flavor}"
                )
    for package in packages:
        if (
            args.ta_secret_mode != "placeholder"
            and package["path"]
            and not args.ta_allow_unaudited_package
            and not (
            package["matches_audited_release_sha256"]
            and package["matches_audited_release_version"]
            )
        ):
            artifact = package["audited_artifact"]
            raise SystemExit(
                f"{package['path']} does not match audited Splunkbase app "
                f"{artifact['splunkbase_app_id']} release {TA_LATEST_VERSION}; "
                "actionable rendering requires the official digest unless "
                "--accept-unaudited-ta-package is explicitly accepted by setup"
            )
        token_style = package["token_field_style"]
        if args.ta_secret_mode == "legacy-file" and token_style not in ("legacy-file", "unknown"):
            raise SystemExit(
                f"{package['path'] or package['app_root']} uses splunk_access_token, not legacy splunk_access_token_file."
            )
        if args.ta_secret_mode == "inputs-conf" and token_style == "legacy-file":
            raise SystemExit(
                f"{package['path']} uses legacy splunk_access_token_file; use --ta-secret-mode legacy-file."
            )
    return packages


def _percent_encode_env_value(value: str) -> str:
    return value.replace("%", "%25").replace(",", "%2C")


def ta_env_vars(args: argparse.Namespace) -> list[str]:
    values = [
        f"SPLUNK_LISTEN_INTERFACE={_percent_encode_env_value(ta_effective_listen_interface(args))}"
    ]
    if args.ta_mode == "agent-to-gateway":
        values.append(f"SPLUNK_GATEWAY_URL={_percent_encode_env_value(args.ta_gateway_url)}")
    for env_value in args.ta_collector_env:
        key, value = env_value.split("=", 1)
        values.append(f"{key}={_percent_encode_env_value(value)}")
    return values


def ta_cmd_args(args: argparse.Namespace) -> list[str]:
    values = list(args.ta_collector_cmd_arg)
    if args.ta_enable_opamp:
        values.append("--feature-gates=+splunk.opamp.enabled")
    return values


def ta_config_path(args: argparse.Namespace, app_root: str) -> str:
    if args.ta_mode == "gateway":
        return f"$SPLUNK_HOME/etc/apps/{app_root}/configs/gateway_config.yaml"
    if args.ta_mode == "agent-to-gateway":
        return f"$SPLUNK_HOME/etc/apps/{app_root}/local/agent_to_gateway_config.yaml"
    return f"$SPLUNK_HOME/etc/apps/{app_root}/configs/agent_config.yaml"


def render_ta_inputs_conf_template(args: argparse.Namespace, package: dict[str, object]) -> str:
    app_root = str(package["app_root"])
    token_style = str(package["token_field_style"])
    if token_style == "unknown":
        token_style = "legacy-file" if args.ta_secret_mode == "legacy-file" else "current"
    fields = dict(package.get("default_fields", {}))
    lines = [
        "# Generated by splunk-observability-otel-collector-setup.",
        "# Token values are intentionally omitted during render.",
        f"[{package['rendered_stanza']}]",
        f"disabled = {'true' if args.ta_secret_mode == 'placeholder' else 'false'}",
        "start_by_shell = false",
        f"interval = {fields.get('interval', '0') or '0'}",
        f"index = {fields.get('index', '_internal') or '_internal'}",
        f"sourcetype = {fields.get('sourcetype', 'Splunk_TA_otel') or 'Splunk_TA_otel'}",
    ]
    if token_style == "legacy-file":
        lines.append(f"splunk_access_token_file = $SPLUNK_HOME/etc/apps/{app_root}/local/access_token")
    elif args.ta_secret_mode == "environment":
        lines.append("splunk_access_token = ${SPLUNK_ACCESS_TOKEN}")
    elif args.ta_secret_mode == "inputs-conf":
        lines.append("splunk_access_token = __SPLUNK_O11Y_ACCESS_TOKEN__")
    else:
        lines.append("splunk_access_token =")
    lines.extend(
        [
            f"splunk_realm = {args.realm}",
            f"splunk_config = {ta_config_path(args, app_root)}",
            f"splunk_collector_log_level = {args.ta_collector_log_level}",
            f"splunk_collector_env_vars = {','.join(ta_env_vars(args))}",
            f"splunk_collector_cmd_args = {shlex.join(ta_cmd_args(args))}",
            "",
        ]
    )
    return "\n".join(lines)


def render_agent_to_gateway_config(args: argparse.Namespace) -> str:
    listen = ta_effective_listen_interface(args)
    return f"""# Generated by splunk-observability-otel-collector-setup.
# This reviewed overlay receives local OTLP and forwards metrics, traces, and
# logs to a TLS-enabled gateway collector. System trust validates the gateway.
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: {yaml_scalar(f'{listen}:4317')}
      http:
        endpoint: {yaml_scalar(f'{listen}:4318')}

processors:
  memory_limiter:
    check_interval: 1s
    limit_mib: 400
    spike_limit_mib: 100
  resourcedetection:
    detectors: [env, system]
    override: false
  batch: {{}}

exporters:
  otlp:
    endpoint: {yaml_scalar(args.ta_gateway_url)}
    tls:
      insecure: false

extensions:
  health_check:
    endpoint: {yaml_scalar(f'{listen}:13133')}

service:
  extensions: [health_check]
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, resourcedetection, batch]
      exporters: [otlp]
    metrics:
      receivers: [otlp]
      processors: [memory_limiter, resourcedetection, batch]
      exporters: [otlp]
    logs:
      receivers: [otlp]
      processors: [memory_limiter, resourcedetection, batch]
      exporters: [otlp]
"""


def ta_package_audit_md(args: argparse.Namespace, packages: list[dict[str, object]]) -> str:
    lines = [
        "# Splunk Add-On for OpenTelemetry Collector Package Audit",
        "",
        "Audited Splunkbase artifacts: `7125` (multi-OS/root), `8698` (Linux x86_64), `8699` (Windows x86_64)",
        f"Latest audited release: `{TA_LATEST_VERSION}` ({TA_PUBLISHED_DATE})",
        f"Splunk compatibility: `{TA_SPLUNK_MIN_VERSION}` through `{TA_SPLUNK_MAX_VERSION}`",
        "Cloud compatibility is artifact-specific and recorded per package below.",
        "FIPS-compatible: `false`",
        "FedRAMP status: `not documented in Splunkbase metadata`",
        "",
    ]
    for index, package in enumerate(packages, start=1):
        lines.extend(
            [
                f"## Package {index}",
                "",
                f"- Path: `{package['path'] or '(not supplied)'}`",
                f"- Splunkbase app: `{package['audited_artifact']['splunkbase_app_id']}`",
                f"- Audited filename: `{package['audited_artifact']['filename']}`",
                f"- Splunk Cloud-compatible package metadata: `{str(package['audited_artifact']['cloud_compatible']).lower()}`",
                f"- SHA-256: `{package['sha256'] or '(not audited)'}`",
                f"- Matches audited 0.154.2 package digest: `{str(package['matches_audited_release_sha256']).lower()}`",
                f"- Matches audited 0.154.2 package version: `{str(package['matches_audited_release_version']).lower()}`",
                f"- Archive members / expanded bytes: `{package['member_count']}` / `{package['expanded_size_bytes']}`",
                f"- App root: `{package['app_root']}`",
                f"- App version: `{package['version'] or '(not found)'}`",
                f"- Package flavor: `{package['package_flavor']}`",
                f"- Supported OS: `{', '.join(package['supported_os']) or '(not detected)'}`",
                f"- Token field style: `{package['token_field_style']}`",
                f"- Packaged default stanza: `{package['default_stanza']}`",
                f"- Spec stanza: `{package['spec_stanza']}`",
                f"- Rendered stanza: `{package['rendered_stanza']}`",
                f"- Stanza mismatch: `{str(package['stanza_mismatch']).lower()}`",
                f"- Agent config present: `{str(package['config_files']['agent']).lower()}`",
                f"- Gateway config present: `{str(package['config_files']['gateway']).lower()}`",
                f"- Linux binary present: `{str(package['platform_binaries']['linux_x86_64']).lower()}`",
                f"- Windows binary present: `{str(package['platform_binaries']['windows_x86_64']).lower()}`",
                f"- Ships pre-built dashboards: `{str(package['dashboard_evidence']['ships_prebuilt_dashboards']).lower()}`",
                f"- Dashboard evidence: {package['dashboard_evidence']['conclusion']}",
                "",
            ]
        )
    if args.splunk_version:
        lines.extend(
            [
                "## Splunk Version Check",
                "",
                f"- Requested Splunk version: `{args.splunk_version}`",
                "- Result: `compatible`",
                "",
            ]
        )
    return "\n".join(lines)


def ta_metadata(args: argparse.Namespace, packages: list[dict[str, object]]) -> dict[str, object]:
    return {
        "splunkbase": TA_SPLUNKBASE_METADATA,
        "target": args.ta_target,
        "mode": args.ta_mode,
        "listen_interface": ta_effective_listen_interface(args),
        "gateway_url": args.ta_gateway_url,
        "collector_log_level": args.ta_collector_log_level,
        "collector_env": ta_env_vars(args),
        "collector_cmd_args": ta_cmd_args(args),
        "serverclass_whitelist": args.ta_serverclass_whitelist or "__REVIEW_REQUIRED_NO_MATCH__",
        "secret_mode": args.ta_secret_mode,
        "signal_intent": {
            "metrics": {"explicit": args.metrics_explicit, "enabled": str_bool(args.enable_metrics)},
            "traces": {"explicit": args.traces_explicit, "enabled": str_bool(args.enable_traces)},
            "logs": {"explicit": args.logs_explicit, "enabled": str_bool(args.enable_logs)},
            "control_supported": False,
        },
        "packaged_config_signals": {"metrics": True, "traces": True, "logs": True},
        "token_in_conf_accepted": args.accept_ta_token_in_conf,
        "audited_package_required": args.ta_secret_mode != "placeholder" and not args.ta_allow_unaudited_package,
        "unaudited_package_override_accepted": args.ta_allow_unaudited_package,
        "artifact_catalog": TA_ARTIFACTS,
        "regulated_requirements": {
            "fips_required": args.ta_fips_required,
            "fedramp_required": args.ta_fedramp_required,
            "override_accepted": args.accept_ta_regulated_override,
        },
        "packages": [_metadata_safe_package(package) for package in packages],
    }


def render_ta_shell_array(name: str, values: list[str]) -> str:
    return bash_array(name, values)


def render_ta_secret_preflight(args: argparse.Namespace) -> str:
    token_file = args.o11y_token_file or "/path/to/splunk_o11y_access_token"
    token_assignment = shell_env_alias_default("TOKEN_FILE", "SPLUNK_O11Y_TOKEN_FILE", token_file)
    return f"""
{token_assignment}
TA_SECRET_MODE={shell_quote(args.ta_secret_mode)}
ACCEPT_TA_TOKEN_IN_CONF={shell_quote(str(args.accept_ta_token_in_conf).lower())}

file_mode() {{
    stat -c '%a' "$1" 2>/dev/null || stat -f '%A' "$1" 2>/dev/null || true
}}

validate_ta_token_file() {{
    local mode
    if [[ ! -f "${{TOKEN_FILE}}" || -L "${{TOKEN_FILE}}" || ! -r "${{TOKEN_FILE}}" || ! -s "${{TOKEN_FILE}}" ]]; then
        echo "ERROR: TA token must be a readable, nonempty, non-symlink regular file." >&2
        exit 1
    fi
    mode="$(file_mode "${{TOKEN_FILE}}")"
    if [[ "${{mode}}" != "600" && "${{mode}}" != "0600" ]]; then
        echo "ERROR: TA token file must have mode 600 (found ${{mode:-unknown}})." >&2
        exit 1
    fi
    if [[ "$(wc -l < "${{TOKEN_FILE}}" | tr -d '[:space:]')" != "0" ]] || ! LC_ALL=C grep -Eq '^[A-Za-z0-9._~+/=-]+$' "${{TOKEN_FILE}}"; then
        echo "ERROR: TA token file must contain one environment-safe token with no newline." >&2
        exit 1
    fi
}}

case "${{TA_SECRET_MODE}}" in
    inputs-conf)
        [[ "${{ACCEPT_TA_TOKEN_IN_CONF}}" == "true" ]] || {{
            echo "ERROR: inputs-conf mode requires ACCEPT_TA_TOKEN_IN_CONF=true." >&2
            exit 1
        }}
        validate_ta_token_file
        ;;
    legacy-file)
        validate_ta_token_file
        ;;
    environment)
        if [[ -z "${{SPLUNK_ACCESS_TOKEN:-}}" ]] || [[ ! "${{SPLUNK_ACCESS_TOKEN}}" =~ ^[A-Za-z0-9._~+/=-]+$ ]]; then
            echo "ERROR: environment mode requires a nonempty, environment-safe SPLUNK_ACCESS_TOKEN in the Splunk service environment." >&2
            exit 1
        fi
        ;;
    placeholder)
        echo "ERROR: placeholder secret mode is render-only and cannot be staged or applied." >&2
        exit 1
        ;;
    *)
        echo "ERROR: unsupported TA secret mode." >&2
        exit 1
        ;;
esac
"""


def render_ta_overlay_function(
    args: argparse.Namespace,
    packages: list[dict[str, object]],
    target_expr: str,
    template_hashes: list[str],
    gateway_hashes: list[str],
) -> str:
    app_roots = [str(package["app_root"]) for package in packages if package["path"]]
    token_file = args.o11y_token_file or "/path/to/splunk_o11y_access_token"
    token_assignment = shell_env_alias_default("TOKEN_FILE", "SPLUNK_O11Y_TOKEN_FILE", token_file)
    return f"""
umask 077
script_dir="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
{token_assignment}
TA_SECRET_MODE={shell_quote(args.ta_secret_mode)}
ACCEPT_TA_TOKEN_IN_CONF={shell_quote(str(args.accept_ta_token_in_conf).lower())}
target_base={target_expr}

{render_ta_shell_array("app_roots", app_roots)}
{render_ta_shell_array("template_hashes", template_hashes)}
{render_ta_shell_array("gateway_hashes", gateway_hashes)}

file_mode() {{
    stat -c '%a' "$1" 2>/dev/null || stat -f '%A' "$1" 2>/dev/null || true
}}

file_uid() {{
    stat -c '%u' "$1" 2>/dev/null || stat -f '%u' "$1" 2>/dev/null
}}

file_gid() {{
    stat -c '%g' "$1" 2>/dev/null || stat -f '%g' "$1" 2>/dev/null
}}

validate_token_file() {{
    local mode
    if [[ ! -f "${{TOKEN_FILE}}" || -L "${{TOKEN_FILE}}" || ! -r "${{TOKEN_FILE}}" || ! -s "${{TOKEN_FILE}}" ]]; then
        echo "ERROR: TA token must be a readable, nonempty regular file: ${{TOKEN_FILE}}" >&2
        exit 1
    fi
    mode="$(file_mode "${{TOKEN_FILE}}")"
    if [[ "${{mode}}" != "600" && "${{mode}}" != "0600" ]]; then
        echo "ERROR: TA token file must have mode 600 (found ${{mode:-unknown}})." >&2
        exit 1
    fi
    if [[ "$(wc -l < "${{TOKEN_FILE}}" | tr -d '[:space:]')" != "0" ]] || ! LC_ALL=C grep -Eq '^[A-Za-z0-9._~+/=-]+$' "${{TOKEN_FILE}}"; then
        echo "ERROR: TA token file must contain one environment-safe token with no newline." >&2
        exit 1
    fi
}}

copy_local_overlay() {{
    local app_root="$1"
    local expected_template_hash="$2"
    local expected_gateway_hash="$3"
    local template="${{script_dir}}/local/${{app_root}}/inputs.conf.template"
    [[ -f "${{template}}" && ! -L "${{template}}" ]] || {{
        echo "ERROR: rendered TA inputs template is missing, non-regular, or a symlink: ${{template}}" >&2
        exit 1
    }}
    local app_dir="${{target_base}}/${{app_root}}"
    [[ -d "${{app_dir}}" && ! -L "${{app_dir}}" ]] || {{
        echo "ERROR: staged TA app directory is missing or unsafe: ${{app_dir}}" >&2
        exit 1
    }}
    case "${{TA_SECRET_MODE}}" in
        inputs-conf)
            if [[ "${{ACCEPT_TA_TOKEN_IN_CONF}}" != "true" ]]; then
                echo "ERROR: Writing splunk_access_token into local/inputs.conf requires ACCEPT_TA_TOKEN_IN_CONF=true." >&2
                exit 1
            fi
            validate_token_file
            ;;
        legacy-file)
            validate_token_file
            ;;
        environment)
            if [[ -z "${{SPLUNK_ACCESS_TOKEN:-}}" ]] || [[ ! "${{SPLUNK_ACCESS_TOKEN}}" =~ ^[A-Za-z0-9._~+/=-]+$ ]]; then
                echo "ERROR: TA environment mode requires an environment-safe SPLUNK_ACCESS_TOKEN in the Splunk service environment." >&2
                exit 1
            fi
            ;;
        placeholder)
            echo "ERROR: Placeholder secret mode is render-only and cannot be applied." >&2
            exit 1
            ;;
        *)
            echo "ERROR: Unsupported TA secret mode: ${{TA_SECRET_MODE}}" >&2
            exit 1
            ;;
    esac
    local gateway_template="${{script_dir}}/local/${{app_root}}/agent_to_gateway_config.yaml"
    if [[ -n "${{expected_gateway_hash}}" ]]; then
        [[ -f "${{gateway_template}}" && ! -L "${{gateway_template}}" ]] || {{
            echo "ERROR: rendered TA gateway template is missing, non-regular, or a symlink: ${{gateway_template}}" >&2
            exit 1
        }}
    else
        gateway_template=""
    fi
    python3 - "${{app_dir}}" "${{template}}" "${{TA_SECRET_MODE}}" "${{TOKEN_FILE}}" \
        "${{gateway_template}}" "${{expected_template_hash}}" "${{expected_gateway_hash}}" <<'PY'
from pathlib import Path
import hashlib
import hmac
import os
import stat
import sys

if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
    raise SystemExit("ERROR: secure TA overlay apply requires O_NOFOLLOW and O_DIRECTORY support")

app_path = sys.argv[1]
template_path = Path(sys.argv[2])
secret_mode = sys.argv[3]
token_path = Path(sys.argv[4])
gateway_path = Path(sys.argv[5]) if sys.argv[5] else None
expected_template_hash = sys.argv[6]
expected_gateway_hash = sys.argv[7]
directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
app_fd = os.open(app_path, directory_flags)
local_fd = -1


def read_bound_file(path, expected_hash, label):
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise SystemExit("ERROR: %s must be a readable non-symlink regular file" % label) from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise SystemExit("ERROR: %s must be a single-link regular file" % label)
        chunks = []
        digest = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
            digest.update(chunk)
        after = os.fstat(descriptor)
        fingerprint_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
            before.st_nlink,
        )
        fingerprint_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
            after.st_nlink,
        )
        if fingerprint_after != fingerprint_before:
            raise SystemExit("ERROR: %s changed while it was read" % label)
        if expected_hash and not hmac.compare_digest(digest.hexdigest(), expected_hash):
            raise SystemExit("ERROR: %s digest differs from the rendered review packet" % label)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


template_bytes = read_bound_file(template_path, expected_template_hash, "TA inputs template")
gateway_bytes = (
    read_bound_file(gateway_path, expected_gateway_hash, "TA gateway template")
    if gateway_path is not None
    else None
)
token_bytes = (
    read_bound_file(token_path, "", "TA token file")
    if secret_mode in ("inputs-conf", "legacy-file")
    else None
)
try:
    app_stat = os.fstat(app_fd)
    if os.geteuid() not in (0, app_stat.st_uid):
        raise SystemExit(
            "ERROR: TA overlay apply must run as root or app owner uid %s" % app_stat.st_uid
        )
    try:
        os.mkdir("local", 0o750, dir_fd=app_fd)
    except FileExistsError:
        pass
    local_fd = os.open("local", directory_flags, dir_fd=app_fd)
    os.fchmod(local_fd, 0o750)
    if os.geteuid() == 0:
        os.fchown(local_fd, app_stat.st_uid, app_stat.st_gid)

    def atomic_write(name, data, mode):
        temporary = ".%s.tmp-%s" % (name, os.getpid())
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        fd = os.open(temporary, flags, mode, dir_fd=local_fd)
        try:
            offset = 0
            while offset < len(data):
                offset += os.write(fd, data[offset:])
            os.fchmod(fd, mode)
            if os.geteuid() == 0:
                os.fchown(fd, app_stat.st_uid, app_stat.st_gid)
            os.fsync(fd)
        finally:
            os.close(fd)
        try:
            os.replace(temporary, name, src_dir_fd=local_fd, dst_dir_fd=local_fd)
        except Exception:
            try:
                os.unlink(temporary, dir_fd=local_fd)
            except FileNotFoundError:
                pass
            raise

    template = template_bytes.decode("utf-8")
    if secret_mode == "inputs-conf":
        token = token_bytes.decode("utf-8")
        template = template.replace("__SPLUNK_O11Y_ACCESS_TOKEN__", token)
    atomic_write("inputs.conf", template.encode("utf-8"), 0o600)
    if secret_mode == "legacy-file":
        atomic_write("access_token", token_bytes, 0o600)
    if gateway_bytes is not None:
        atomic_write("agent_to_gateway_config.yaml", gateway_bytes, 0o640)
finally:
    if local_fd >= 0:
        os.close(local_fd)
    os.close(app_fd)
PY
}}

for index in "${{!app_roots[@]}}"; do
    copy_local_overlay \
        "${{app_roots[$index]}}" \
        "${{template_hashes[$index]}}" \
        "${{gateway_hashes[$index]}}"
done
"""


def render_ta_scripts(args: argparse.Namespace, ta_dir: Path, packages: list[dict[str, object]]) -> None:
    package_paths = [str(package["path"]) for package in packages if package["path"]]
    package_hashes = [str(package["sha256"]) for package in packages if package["path"]]
    package_sizes = [str(package["size_bytes"]) for package in packages if package["path"]]
    app_roots = [str(package["app_root"]) for package in packages if package["path"]]
    template_hashes = [
        sha256_file(ta_dir / "local" / app_root / "inputs.conf.template")
        for app_root in app_roots
    ]
    gateway_hashes = [
        (
            sha256_file(ta_dir / "local" / app_root / "agent_to_gateway_config.yaml")
            if (ta_dir / "local" / app_root / "agent_to_gateway_config.yaml").is_file()
            else ""
        )
        for app_root in app_roots
    ]
    supported_roots = ", ".join(repr(root) for root in TA_SUPPORTED_ROOTS)
    secret_preflight = render_ta_secret_preflight(args)
    target_expr = '"${SPLUNK_DEPLOYMENT_APPS:-${SPLUNK_HOME:-/opt/splunk}/etc/deployment-apps}"'
    if args.ta_target == "universal-forwarder":
        target_expr = '"${SPLUNK_APPS_DIR:-${SPLUNK_HOME:-/opt/splunkforwarder}/etc/apps}"'
    elif args.ta_target == "heavy-forwarder":
        target_expr = '"${SPLUNK_APPS_DIR:-${SPLUNK_HOME:-/opt/splunk}/etc/apps}"'
    write_text(
        ta_dir / "preflight-ta.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail

{render_ta_shell_array("packages", package_paths)}
{render_ta_shell_array("package_hashes", package_hashes)}
{render_ta_shell_array("package_sizes", package_sizes)}
{render_ta_shell_array("app_roots", app_roots)}
target_base={target_expr}

command -v python3 >/dev/null 2>&1 || {{
    echo "ERROR: TA package workflows require an external python3 interpreter." >&2
    exit 1
}}
python3 - <<'PY'
import os
import sys

if sys.version_info < (3, 6):
    raise SystemExit("ERROR: TA package workflows require Python 3.6 or newer")
missing = [name for name in ("O_NOFOLLOW", "O_DIRECTORY") if not hasattr(os, name)]
if missing:
    raise SystemExit(
        "ERROR: TA package workflows require Python os support for " + ", ".join(missing)
    )
PY

if [[ "${{#packages[@]}}" -eq 0 ]]; then
    echo "ERROR: No TA packages were supplied. Re-render with --ta-package-path PATH." >&2
    exit 1
fi
for index in "${{!packages[@]}}"; do
    package="${{packages[$index]}}"
    expected_sha256="${{package_hashes[$index]}}"
    expected_size="${{package_sizes[$index]}}"
    [[ -r "${{package}}" ]] || {{ echo "ERROR: TA package is not readable: ${{package}}" >&2; exit 1; }}
    python3 - "${{package}}" "${{expected_sha256}}" "${{expected_size}}" <<'PY'
from pathlib import Path
import hashlib
import os
import stat
import sys
import tarfile

package = Path(sys.argv[1])
expected_sha256 = sys.argv[2]
expected_size = int(sys.argv[3])
supported_roots = ({supported_roots},)
required_files = {TA_REQUIRED_FILES!r}
archive_handle = None
try:
    if not hasattr(os, "O_NOFOLLOW"):
        raise SystemExit("ERROR: secure TA package verification requires O_NOFOLLOW support")
    descriptor = os.open(package, os.O_RDONLY | os.O_NOFOLLOW)
    archive_handle = os.fdopen(descriptor, "rb")
    archive_before = os.fstat(archive_handle.fileno())
    if not stat.S_ISREG(archive_before.st_mode) or archive_before.st_nlink != 1:
        raise SystemExit(f"ERROR: TA package must be a single-link regular file: {{package}}")
    if archive_before.st_size != expected_size:
        raise SystemExit(f"ERROR: TA package size changed after render: {{package}}")
    digest = hashlib.sha256()
    for chunk in iter(lambda: archive_handle.read(1024 * 1024), b""):
        digest.update(chunk)
    actual_sha256 = digest.hexdigest()
    if actual_sha256 != expected_sha256:
        raise SystemExit(f"ERROR: TA package digest changed after render: {{package}}")
    archive_handle.seek(0)
    try:
        archive = tarfile.open(fileobj=archive_handle, mode="r:*")
    except tarfile.TarError as exc:
        raise SystemExit(f"ERROR: unreadable TA package archive: {{package}}: {{exc}}") from exc
    with archive:
        names = []
        seen = set()
        expanded_size = 0
        members = archive.getmembers()
        if len(members) > 20000:
            raise SystemExit("ERROR: TA package exceeds the member-count safety limit.")
        for member in members:
            name = member.name.replace("\\\\", "/")
            while name.startswith("./"):
                name = name[2:]
            if not name or name == ".":
                if not member.isdir():
                    raise SystemExit(f"ERROR: unsafe root TA package member: {{member.name}}")
                continue
            parts = Path(name).parts
            if name.startswith("/") or ".." in parts:
                raise SystemExit(f"ERROR: unsafe TA package member path: {{member.name}}")
            if not (member.isfile() or member.isdir()):
                raise SystemExit(f"ERROR: unsupported TA package member type: {{member.name}}")
            if name in seen:
                raise SystemExit(f"ERROR: duplicate TA package member: {{member.name}}")
            seen.add(name)
            if member.isfile():
                expanded_size += member.size
                if member.size > 512 * 1024 * 1024:
                    raise SystemExit(f"ERROR: TA package member exceeds 512 MiB: {{member.name}}")
            names.append(name)
        if len(names) > 20000 or expanded_size > 2 * 1024 * 1024 * 1024:
            raise SystemExit("ERROR: TA package exceeds archive safety limits.")
        package_roots = [
            root
            for root in supported_roots
            if any(name == root or name.startswith(root + "/") for name in names)
        ]
        if not package_roots:
            raise SystemExit("ERROR: TA package does not contain a supported Splunk_TA_otel app root.")
        if len(package_roots) != 1:
            raise SystemExit("ERROR: TA package must contain exactly one supported app root.")
        for name in names:
            if not name or name == ".":
                continue
            top_level = Path(name).parts[0]
            if top_level not in package_roots:
                raise SystemExit(f"ERROR: unsupported top-level TA package member: {{name}}")
        root = package_roots[0]
        relative_names = {{name[len(root) + 1:] for name in names if name.startswith(root + "/")}}
        missing = [name for name in required_files if name not in relative_names]
        if missing:
            raise SystemExit(f"ERROR: TA package is missing required files: {{', '.join(missing)}}")
    archive_after = os.fstat(archive_handle.fileno())
    fingerprint_before = (
        archive_before.st_dev,
        archive_before.st_ino,
        archive_before.st_size,
        archive_before.st_mtime_ns,
        archive_before.st_ctime_ns,
        archive_before.st_nlink,
    )
    fingerprint_after = (
        archive_after.st_dev,
        archive_after.st_ino,
        archive_after.st_size,
        archive_after.st_mtime_ns,
        archive_after.st_ctime_ns,
        archive_after.st_nlink,
    )
    if fingerprint_after != fingerprint_before:
        raise SystemExit(f"ERROR: TA package changed during verification: {{package}}")
finally:
    if archive_handle is not None:
        archive_handle.close()
PY
done
{secret_preflight}

path_uid() {{
    stat -c '%u' "$1" 2>/dev/null || stat -f '%u' "$1" 2>/dev/null
}}

if [[ "$(id -u)" -ne 0 ]]; then
    for app_root in "${{app_roots[@]}}"; do
        owner_path="${{target_base}}/${{app_root}}"
        if [[ -L "${{owner_path}}" ]]; then
            echo "ERROR: refusing a symlinked TA app target: ${{owner_path}}" >&2
            exit 1
        fi
        while [[ ! -e "${{owner_path}}" && "${{owner_path}}" != "/" ]]; do
            owner_path="$(dirname "${{owner_path}}")"
        done
        owner_uid="$(path_uid "${{owner_path}}")"
        if [[ "$(id -u)" != "${{owner_uid}}" ]]; then
            echo "ERROR: TA mutation must run as root or as the existing target/app owner (uid ${{owner_uid}} for ${{owner_path}})." >&2
            exit 1
        fi
    done
fi
echo "TA package preflight passed for ${{#packages[@]}} package(s): ${{app_roots[*]}}"
""",
        executable=True,
    )
    write_text(
        ta_dir / "stage-ta-package.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail
umask 022

script_dir="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
bash "${{script_dir}}/preflight-ta.sh"

{render_ta_shell_array("packages", package_paths)}
{render_ta_shell_array("package_hashes", package_hashes)}
{render_ta_shell_array("package_sizes", package_sizes)}
{render_ta_shell_array("app_roots", app_roots)}
target_base={target_expr}

if [[ "${{#packages[@]}}" -eq 0 ]]; then
    echo "ERROR: No TA packages were supplied. Re-render with --ta-package-path PATH." >&2
    exit 1
fi
mkdir -p "${{target_base}}"
for index in "${{!packages[@]}}"; do
    package="${{packages[$index]}}"
    expected_sha256="${{package_hashes[$index]}}"
    expected_size="${{package_sizes[$index]}}"
    expected_app_root="${{app_roots[$index]}}"
    python3 - "${{package}}" "${{target_base}}" "${{expected_sha256}}" "${{expected_size}}" "${{expected_app_root}}" <<'PY'
from pathlib import Path
import hashlib
import os
import secrets
import shutil
import stat
import sys
import tarfile
import tempfile
from datetime import datetime, timezone

package = Path(sys.argv[1])
target = Path(sys.argv[2]).resolve()
expected_sha256 = sys.argv[3]
expected_size = int(sys.argv[4])
expected_app_root = sys.argv[5]
supported_roots = ({supported_roots},)
required_files = {TA_REQUIRED_FILES!r}

if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
    raise SystemExit("ERROR: secure TA staging requires O_NOFOLLOW and O_DIRECTORY support")

DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW
WRITE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
MAX_LOCAL_DEPTH = 64
MAX_LOCAL_ENTRIES = 20000
MAX_LOCAL_FILE_BYTES = 512 * 1024 * 1024
MAX_LOCAL_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
local_entry_count = [0]
local_byte_count = [0]


def same_inode(left, right):
    return left.st_dev == right.st_dev and left.st_ino == right.st_ino


def open_verified_directory(name, parent_fd, expected, label):
    try:
        descriptor = os.open(name, DIRECTORY_FLAGS, dir_fd=parent_fd)
    except OSError as exc:
        raise SystemExit(
            "ERROR: %s must be a real non-symlink directory" % label
        ) from exc
    actual = os.fstat(descriptor)
    if not stat.S_ISDIR(actual.st_mode) or not same_inode(expected, actual):
        os.close(descriptor)
        raise SystemExit("ERROR: %s changed during secure TA staging" % label)
    return descriptor


def write_all(descriptor, data):
    offset = 0
    while offset < len(data):
        written = os.write(descriptor, data[offset:])
        if written <= 0:
            raise OSError("short write while preserving TA local configuration")
        offset += written


def copy_regular_file(name, source_fd, destination_fd, expected, display_name):
    if expected.st_nlink != 1:
        raise SystemExit(
            "ERROR: refusing hard-linked existing TA local file: %s" % display_name
        )
    if expected.st_size > MAX_LOCAL_FILE_BYTES:
        raise SystemExit(
            "ERROR: existing TA local file exceeds 512 MiB: %s" % display_name
        )
    local_byte_count[0] += expected.st_size
    if local_byte_count[0] > MAX_LOCAL_TOTAL_BYTES:
        raise SystemExit("ERROR: existing TA local tree exceeds 2 GiB")

    try:
        source_file_fd = os.open(name, READ_FLAGS, dir_fd=source_fd)
    except OSError as exc:
        raise SystemExit(
            "ERROR: existing TA local file became unsafe: %s" % display_name
        ) from exc
    temporary = ".splunk-otel-copy-%s" % secrets.token_hex(12)
    destination_file_fd = -1
    try:
        opened = os.fstat(source_file_fd)
        if not stat.S_ISREG(opened.st_mode) or not same_inode(expected, opened):
            raise SystemExit(
                "ERROR: existing TA local file changed during staging: %s" % display_name
            )
        destination_file_fd = os.open(
            temporary,
            WRITE_FLAGS,
            0o600,
            dir_fd=destination_fd,
        )
        while True:
            chunk = os.read(source_file_fd, 1024 * 1024)
            if not chunk:
                break
            write_all(destination_file_fd, chunk)
        after = os.fstat(source_file_fd)
        if (
            not same_inode(opened, after)
            or opened.st_size != after.st_size
            or opened.st_mtime_ns != after.st_mtime_ns
        ):
            raise SystemExit(
                "ERROR: existing TA local file changed while it was copied: %s" % display_name
            )
        os.fchmod(destination_file_fd, stat.S_IMODE(opened.st_mode) & 0o777)
        os.fsync(destination_file_fd)
        os.close(destination_file_fd)
        destination_file_fd = -1
        os.replace(
            temporary,
            name,
            src_dir_fd=destination_fd,
            dst_dir_fd=destination_fd,
        )
        temporary = ""
    finally:
        if destination_file_fd >= 0:
            os.close(destination_file_fd)
        os.close(source_file_fd)
        if temporary:
            try:
                os.unlink(temporary, dir_fd=destination_fd)
            except FileNotFoundError:
                pass


def copy_local_tree(source_fd, destination_fd, display_path="local", depth=0):
    if depth > MAX_LOCAL_DEPTH:
        raise SystemExit("ERROR: existing TA local tree exceeds 64 directory levels")
    source_before = os.fstat(source_fd)
    for name in sorted(os.listdir(source_fd)):
        local_entry_count[0] += 1
        if local_entry_count[0] > MAX_LOCAL_ENTRIES:
            raise SystemExit("ERROR: existing TA local tree exceeds 20000 entries")
        display_name = "%s/%s" % (display_path, name)
        try:
            entry = os.stat(name, dir_fd=source_fd, follow_symlinks=False)
        except FileNotFoundError as exc:
            raise SystemExit(
                "ERROR: existing TA local entry changed during staging: %s" % display_name
            ) from exc
        if stat.S_ISLNK(entry.st_mode):
            raise SystemExit(
                "ERROR: refusing symlink in existing TA local tree: %s" % display_name
            )
        if stat.S_ISREG(entry.st_mode):
            copy_regular_file(name, source_fd, destination_fd, entry, display_name)
            continue
        if not stat.S_ISDIR(entry.st_mode):
            raise SystemExit(
                "ERROR: refusing non-regular entry in existing TA local tree: %s" % display_name
            )
        source_child_fd = open_verified_directory(
            name,
            source_fd,
            entry,
            "existing TA local directory %s" % display_name,
        )
        try:
            try:
                os.mkdir(name, 0o750, dir_fd=destination_fd)
            except FileExistsError:
                pass
            try:
                destination_entry = os.stat(
                    name,
                    dir_fd=destination_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError as exc:
                raise SystemExit(
                    "ERROR: staged TA local directory disappeared: %s" % display_name
                ) from exc
            destination_child_fd = open_verified_directory(
                name,
                destination_fd,
                destination_entry,
                "staged TA local directory %s" % display_name,
            )
            try:
                copy_local_tree(
                    source_child_fd,
                    destination_child_fd,
                    display_name,
                    depth + 1,
                )
                os.fchmod(destination_child_fd, stat.S_IMODE(entry.st_mode) & 0o777)
            finally:
                os.close(destination_child_fd)
        finally:
            os.close(source_child_fd)
    source_after = os.fstat(source_fd)
    if (
        not same_inode(source_before, source_after)
        or source_before.st_mtime_ns != source_after.st_mtime_ns
    ):
        raise SystemExit(
            "ERROR: existing TA local directory changed while it was copied: %s" % display_path
        )


def chown_tree(directory_fd, uid, gid, display_path):
    os.fchown(directory_fd, uid, gid)
    for name in sorted(os.listdir(directory_fd)):
        display_name = "%s/%s" % (display_path, name)
        entry = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if stat.S_ISDIR(entry.st_mode):
            child_fd = open_verified_directory(
                name,
                directory_fd,
                entry,
                "staged TA directory %s" % display_name,
            )
            try:
                chown_tree(child_fd, uid, gid, display_name)
            finally:
                os.close(child_fd)
        elif stat.S_ISREG(entry.st_mode):
            file_fd = os.open(name, READ_FLAGS, dir_fd=directory_fd)
            try:
                opened = os.fstat(file_fd)
                if not stat.S_ISREG(opened.st_mode) or not same_inode(entry, opened):
                    raise SystemExit(
                        "ERROR: staged TA file changed during ownership update: %s" % display_name
                    )
                os.fchown(file_fd, uid, gid)
            finally:
                os.close(file_fd)
        else:
            raise SystemExit(
                "ERROR: refusing non-regular staged TA entry: %s" % display_name
            )


def verify_directory_binding(parent_fd, name, directory_fd, label):
    try:
        bound = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError as exc:
        raise SystemExit("ERROR: %s was removed during TA staging" % label) from exc
    opened = os.fstat(directory_fd)
    if not stat.S_ISDIR(bound.st_mode) or not same_inode(bound, opened):
        raise SystemExit("ERROR: %s changed during TA staging" % label)

try:
    package_descriptor = os.open(package, READ_FLAGS)
except OSError as exc:
    raise SystemExit(
        f"ERROR: TA package must be a readable non-symlink regular file: {{package}}"
    ) from exc
archive_handle = os.fdopen(package_descriptor, "rb")
archive_before = os.fstat(archive_handle.fileno())
if not stat.S_ISREG(archive_before.st_mode) or archive_before.st_nlink != 1:
    raise SystemExit(f"ERROR: TA package must be a single-link regular file: {{package}}")
if archive_before.st_size != expected_size:
    raise SystemExit(f"ERROR: TA package size changed after render: {{package}}")
digest = hashlib.sha256()
for chunk in iter(lambda: archive_handle.read(1024 * 1024), b""):
    digest.update(chunk)
actual_sha256 = digest.hexdigest()
if actual_sha256 != expected_sha256:
    raise SystemExit(f"ERROR: TA package digest changed after render: {{package}}")
archive_handle.seek(0)

app_target = target / expected_app_root
if app_target.is_symlink():
    raise SystemExit(f"ERROR: refusing to replace symlinked existing app directory: {{app_target}}")
owner_source = app_target if app_target.exists() else target
while not owner_source.exists() and owner_source != owner_source.parent:
    owner_source = owner_source.parent
owner_stat = owner_source.stat()
if os.geteuid() != 0 and os.geteuid() != owner_stat.st_uid:
    raise SystemExit(
        f"ERROR: TA staging must run as root or as target/app owner uid {{owner_stat.st_uid}}: {{owner_source}}"
    )
target.mkdir(parents=True, exist_ok=True, mode=0o755)
if os.geteuid() == 0:
    os.chown(target, owner_stat.st_uid, owner_stat.st_gid)
staging = Path(tempfile.mkdtemp(prefix=".splunk-otel-stage-", dir=target))
backup = None
final = None
try:
    with tarfile.open(fileobj=archive_handle, mode="r:*") as archive:
        members = archive.getmembers()
        if len(members) > 20000:
            raise SystemExit("ERROR: TA package exceeds the member-count safety limit.")
        normalized = []
        seen = set()
        expanded_size = 0
        for member in members:
            name = member.name.replace("\\\\", "/")
            while name.startswith("./"):
                name = name[2:]
            if not name or name == ".":
                if not member.isdir():
                    raise SystemExit(f"ERROR: unsafe root TA package member: {{member.name}}")
                continue
            parts = Path(name).parts
            if name.startswith("/") or ".." in parts:
                raise SystemExit(f"ERROR: unsafe TA package member path: {{member.name}}")
            if not (member.isfile() or member.isdir()):
                raise SystemExit(f"ERROR: unsupported TA package member type: {{member.name}}")
            if name in seen:
                raise SystemExit(f"ERROR: duplicate TA package member: {{member.name}}")
            seen.add(name)
            if member.isfile():
                if member.size > 512 * 1024 * 1024:
                    raise SystemExit(f"ERROR: TA package member exceeds 512 MiB: {{member.name}}")
                expanded_size += member.size
            if name:
                normalized.append((member, name))
        if expanded_size > 2 * 1024 * 1024 * 1024:
            raise SystemExit("ERROR: TA package exceeds the expanded-size safety limit.")
        names = [name for _, name in normalized]
        package_roots = [
            root
            for root in supported_roots
            if any(name == root or name.startswith(root + "/") for name in names)
        ]
        if len(package_roots) != 1:
            raise SystemExit("ERROR: TA package must contain exactly one supported app root.")
        app_root = package_roots[0]
        if app_root != expected_app_root:
            raise SystemExit(
                f"ERROR: TA package root changed after render: expected {{expected_app_root}}, found {{app_root}}"
            )
        for name in names:
            if not name or name == ".":
                continue
            if Path(name).parts[0] != app_root:
                raise SystemExit(f"ERROR: unsupported top-level TA package member: {{name}}")
        relative_names = {{name[len(app_root) + 1:] for name in names if name.startswith(app_root + "/")}}
        missing = [name for name in required_files if name not in relative_names]
        if missing:
            raise SystemExit(f"ERROR: TA package is missing required files: {{', '.join(missing)}}")
        for member, name in normalized:
            destination = (staging / name).resolve()
            if destination != staging and staging not in destination.parents:
                raise SystemExit(f"ERROR: TA package member escapes staging directory: {{member.name}}")
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
                os.chmod(destination, (member.mode & 0o777) | 0o750)
                continue
            source = archive.extractfile(member)
            if source is None:
                raise SystemExit(f"ERROR: could not read TA package member: {{member.name}}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with source, destination.open("wb") as handle:
                shutil.copyfileobj(source, handle)
            os.chmod(destination, member.mode & 0o777)

    archive_after = os.fstat(archive_handle.fileno())
    fingerprint_before = (
        archive_before.st_dev,
        archive_before.st_ino,
        archive_before.st_size,
        archive_before.st_mtime_ns,
        archive_before.st_ctime_ns,
        archive_before.st_nlink,
    )
    fingerprint_after = (
        archive_after.st_dev,
        archive_after.st_ino,
        archive_after.st_size,
        archive_after.st_mtime_ns,
        archive_after.st_ctime_ns,
        archive_after.st_nlink,
    )
    if fingerprint_after != fingerprint_before:
        raise SystemExit(f"ERROR: TA package changed during extraction: {{package}}")

    staged_app = staging / app_root
    target_fd = os.open(target, DIRECTORY_FLAGS)
    staging_stat = os.stat(staging.name, dir_fd=target_fd, follow_symlinks=False)
    staging_fd = open_verified_directory(
        staging.name,
        target_fd,
        staging_stat,
        "TA staging directory",
    )
    staged_app_stat = os.stat(app_root, dir_fd=staging_fd, follow_symlinks=False)
    staged_app_fd = open_verified_directory(
        app_root,
        staging_fd,
        staged_app_stat,
        "staged TA app directory",
    )
    final_fd = -1
    backup_parent_fd = -1
    backup_root_fd = -1
    backup_name = ""
    backup_moved = False
    try:
        try:
            final_stat = os.stat(app_root, dir_fd=target_fd, follow_symlinks=False)
        except FileNotFoundError:
            final_stat = None
        if final_stat is not None:
            final_fd = open_verified_directory(
                app_root,
                target_fd,
                final_stat,
                "existing TA app directory",
            )
            app_owner = os.fstat(final_fd)
            if os.geteuid() != 0 and os.geteuid() != app_owner.st_uid:
                raise SystemExit(
                    "ERROR: TA staging must run as root or existing app owner uid %s"
                    % app_owner.st_uid
                )
            try:
                local_stat = os.stat("local", dir_fd=final_fd, follow_symlinks=False)
            except FileNotFoundError:
                local_stat = None
            if local_stat is not None:
                source_local_fd = open_verified_directory(
                    "local",
                    final_fd,
                    local_stat,
                    "existing TA local directory",
                )
                try:
                    try:
                        os.mkdir("local", 0o750, dir_fd=staged_app_fd)
                    except FileExistsError:
                        pass
                    destination_local_stat = os.stat(
                        "local",
                        dir_fd=staged_app_fd,
                        follow_symlinks=False,
                    )
                    destination_local_fd = open_verified_directory(
                        "local",
                        staged_app_fd,
                        destination_local_stat,
                        "staged TA local directory",
                    )
                    try:
                        copy_local_tree(source_local_fd, destination_local_fd)
                        os.fchmod(
                            destination_local_fd,
                            stat.S_IMODE(local_stat.st_mode) & 0o777,
                        )
                    finally:
                        os.close(destination_local_fd)
                finally:
                    os.close(source_local_fd)
        else:
            app_owner = os.fstat(target_fd)
            if os.geteuid() != 0 and os.geteuid() != app_owner.st_uid:
                raise SystemExit(
                    "ERROR: TA staging must run as root or target owner uid %s"
                    % app_owner.st_uid
                )

        if os.geteuid() == 0:
            chown_tree(staged_app_fd, app_owner.st_uid, app_owner.st_gid, app_root)

        if final_fd >= 0:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            backup_parent_fd = os.open(target.parent, DIRECTORY_FLAGS)
            backup_root_name = ".splunk-otel-backups"
            backup_created = False
            try:
                os.mkdir(backup_root_name, 0o700, dir_fd=backup_parent_fd)
                backup_created = True
            except FileExistsError:
                pass
            try:
                backup_root_fd = os.open(
                    backup_root_name,
                    DIRECTORY_FLAGS,
                    dir_fd=backup_parent_fd,
                )
            except OSError as exc:
                raise SystemExit(
                    "ERROR: TA backup root must be a real non-symlink directory"
                ) from exc
            backup_root_stat = os.fstat(backup_root_fd)
            if backup_created and os.geteuid() == 0:
                os.fchown(backup_root_fd, app_owner.st_uid, app_owner.st_gid)
                backup_root_stat = os.fstat(backup_root_fd)
            if backup_root_stat.st_uid != app_owner.st_uid:
                raise SystemExit(
                    "ERROR: TA backup root owner uid %s does not match app owner uid %s"
                    % (backup_root_stat.st_uid, app_owner.st_uid)
                )
            os.fchmod(backup_root_fd, 0o700)
            verify_directory_binding(
                backup_parent_fd,
                backup_root_name,
                backup_root_fd,
                "TA backup root",
            )
            backup_name = "%s.backup-%s-%s" % (
                app_root,
                stamp,
                secrets.token_hex(8),
            )
            try:
                os.stat(backup_name, dir_fd=backup_root_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise SystemExit("ERROR: generated TA backup path already exists")
            verify_directory_binding(
                target_fd,
                app_root,
                final_fd,
                "existing TA app directory",
            )
            os.replace(
                app_root,
                backup_name,
                src_dir_fd=target_fd,
                dst_dir_fd=backup_root_fd,
            )
            backup_moved = True

        try:
            if backup_moved:
                verify_directory_binding(
                    backup_parent_fd,
                    backup_root_name,
                    backup_root_fd,
                    "TA backup root",
                )
            verify_directory_binding(
                staging_fd,
                app_root,
                staged_app_fd,
                "staged TA app directory",
            )
            os.replace(
                app_root,
                app_root,
                src_dir_fd=staging_fd,
                dst_dir_fd=target_fd,
            )
        except BaseException:
            if backup_moved:
                try:
                    os.replace(
                        backup_name,
                        app_root,
                        src_dir_fd=backup_root_fd,
                        dst_dir_fd=target_fd,
                    )
                except Exception as rollback_error:
                    raise RuntimeError(
                        "TA staging failed and automatic rollback failed; original app remains in backup %s"
                        % backup_name
                    ) from rollback_error
            raise
    finally:
        if final_fd >= 0:
            os.close(final_fd)
        if backup_root_fd >= 0:
            os.close(backup_root_fd)
        if backup_parent_fd >= 0:
            os.close(backup_parent_fd)
        os.close(staged_app_fd)
        os.close(staging_fd)
        os.close(target_fd)
except tarfile.TarError as exc:
    raise SystemExit(f"ERROR: unreadable TA package archive: {{package}}: {{exc}}") from exc
finally:
    archive_handle.close()
    shutil.rmtree(staging, ignore_errors=True)
PY
done
echo "Staged Splunk_TA_otel package(s) into ${{target_base}}"
""",
        executable=True,
    )
    write_text(
        ta_dir / "manage-backups.py",
        f"""#!/usr/bin/env python3
from pathlib import Path
import argparse
import os
import re
import stat
import sys

SUPPORTED_ROOTS = {TA_SUPPORTED_ROOTS!r}
BACKUP_ROOT_NAME = ".splunk-otel-backups"
MAX_ENTRIES = 200000
MAX_DEPTH = 128
entry_count = [0]

if sys.version_info < (3, 6):
    raise SystemExit("ERROR: TA backup management requires Python 3.6 or newer")
if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
    raise SystemExit("ERROR: TA backup management requires O_NOFOLLOW and O_DIRECTORY support")
DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def fail(message):
    raise SystemExit("ERROR: " + message)


def same_inode(left, right):
    return left.st_dev == right.st_dev and left.st_ino == right.st_ino


def open_verified_directory(name, parent_fd, expected, label):
    try:
        descriptor = os.open(name, DIRECTORY_FLAGS, dir_fd=parent_fd)
    except OSError as exc:
        fail("%s must be a real non-symlink directory: %s" % (label, exc))
    opened = os.fstat(descriptor)
    if not stat.S_ISDIR(opened.st_mode) or not same_inode(expected, opened):
        os.close(descriptor)
        fail("%s changed while backup management was running" % label)
    return descriptor


def backup_app_root(name):
    for app_root in SUPPORTED_ROOTS:
        prefix = app_root + ".backup-"
        suffix = name[len(prefix):] if name.startswith(prefix) else ""
        if suffix and re.fullmatch(r"[A-Za-z0-9._-]+", suffix):
            return app_root
    return ""


def is_secret_candidate(parts):
    joined = "/".join(parts)
    return joined.endswith("local/inputs.conf") or joined.endswith("local/access_token")


def inspect_tree(directory_fd, filesystem_device, parts=(), depth=0):
    if depth > MAX_DEPTH:
        fail("backup tree exceeds %s directory levels" % MAX_DEPTH)
    result = {{"files": 0, "bytes": 0, "symlinks": 0, "special": 0, "secret_candidates": 0}}
    for name in sorted(os.listdir(directory_fd)):
        entry_count[0] += 1
        if entry_count[0] > MAX_ENTRIES:
            fail("backup inventory exceeds %s entries" % MAX_ENTRIES)
        entry = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        child_parts = parts + (name,)
        if stat.S_ISDIR(entry.st_mode):
            if entry.st_dev != filesystem_device:
                fail("backup contains a cross-filesystem directory: %s" % "/".join(child_parts))
            child_fd = open_verified_directory(
                name,
                directory_fd,
                entry,
                "backup directory %s" % "/".join(child_parts),
            )
            try:
                child = inspect_tree(child_fd, filesystem_device, child_parts, depth + 1)
            finally:
                os.close(child_fd)
            for key, value in child.items():
                result[key] += value
        elif stat.S_ISREG(entry.st_mode):
            result["files"] += 1
            result["bytes"] += entry.st_size
            if is_secret_candidate(child_parts):
                result["secret_candidates"] += 1
        elif stat.S_ISLNK(entry.st_mode):
            result["symlinks"] += 1
            if is_secret_candidate(child_parts):
                result["secret_candidates"] += 1
        else:
            result["special"] += 1
    return result


def remove_tree_at(parent_fd, name, expected, filesystem_device, display_name, depth=0):
    if depth > MAX_DEPTH:
        fail("backup tree exceeds %s directory levels" % MAX_DEPTH)
    directory_fd = open_verified_directory(name, parent_fd, expected, display_name)
    try:
        for child_name in sorted(os.listdir(directory_fd)):
            child = os.stat(child_name, dir_fd=directory_fd, follow_symlinks=False)
            child_display = "%s/%s" % (display_name, child_name)
            if stat.S_ISDIR(child.st_mode):
                if child.st_dev != filesystem_device:
                    fail("refusing to prune cross-filesystem directory: %s" % child_display)
                remove_tree_at(
                    directory_fd,
                    child_name,
                    child,
                    filesystem_device,
                    child_display,
                    depth + 1,
                )
            else:
                os.unlink(child_name, dir_fd=directory_fd)
    finally:
        os.close(directory_fd)
    current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if not same_inode(expected, current) or not stat.S_ISDIR(current.st_mode):
        fail("backup changed before removal: %s" % display_name)
    os.rmdir(name, dir_fd=parent_fd)


parser = argparse.ArgumentParser(description="Inventory or securely prune retained TA backups")
parser.add_argument("action", choices=("inventory", "prune"))
parser.add_argument("--target-base", required=True)
parser.add_argument("--retain", type=int, default=3)
args = parser.parse_args()
if args.retain < 0 or args.retain > 1000:
    fail("--retain must be from 0 through 1000")
if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
    fail("secure backup management requires O_NOFOLLOW and O_DIRECTORY support")

target_base = Path(args.target_base).expanduser().resolve()
backup_parent = target_base.parent
parent_fd = os.open(backup_parent, DIRECTORY_FLAGS)
backup_root_fd = -1
try:
    try:
        backup_root_stat = os.stat(BACKUP_ROOT_NAME, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        print("No retained TA backup root: %s" % (backup_parent / BACKUP_ROOT_NAME))
        raise SystemExit(0)
    backup_root_fd = open_verified_directory(
        BACKUP_ROOT_NAME,
        parent_fd,
        backup_root_stat,
        "TA backup root",
    )
    opened_root = os.fstat(backup_root_fd)
    if os.geteuid() not in (0, opened_root.st_uid):
        fail("backup management must run as root or backup-root owner uid %s" % opened_root.st_uid)
    if stat.S_IMODE(opened_root.st_mode) != 0o700:
        fail("TA backup root mode must be 700")

    backups = []
    unexpected = []
    for name in sorted(os.listdir(backup_root_fd)):
        entry = os.stat(name, dir_fd=backup_root_fd, follow_symlinks=False)
        app_root = backup_app_root(name)
        if (
            not app_root
            or not stat.S_ISDIR(entry.st_mode)
            or entry.st_dev != opened_root.st_dev
        ):
            unexpected.append(name)
            continue
        child_fd = open_verified_directory(name, backup_root_fd, entry, "TA backup %s" % name)
        try:
            details = inspect_tree(child_fd, entry.st_dev, (name,))
        finally:
            os.close(child_fd)
        backups.append((app_root, name, entry, details))
    if unexpected:
        fail("TA backup root contains unmanaged or unsafe entries: %s" % ", ".join(unexpected))

    print("TA backup root: %s" % (backup_parent / BACKUP_ROOT_NAME))
    if not backups:
        print("No retained TA backups.")
    for app_root, name, _, details in backups:
        print(
            "BACKUP\\t%s\\tapp=%s\\tfiles=%s\\tbytes=%s\\tsymlinks=%s\\tspecial=%s\\tsecret_candidates=%s"
            % (
                name,
                app_root,
                details["files"],
                details["bytes"],
                details["symlinks"],
                details["special"],
                details["secret_candidates"],
            )
        )

    if args.action == "prune":
        grouped = {{app_root: [] for app_root in SUPPORTED_ROOTS}}
        for backup in backups:
            grouped[backup[0]].append(backup)
        for app_root, app_backups in grouped.items():
            app_backups.sort(key=lambda item: item[1], reverse=True)
            for _, name, entry, _ in app_backups[args.retain:]:
                root_now = os.stat(BACKUP_ROOT_NAME, dir_fd=parent_fd, follow_symlinks=False)
                if not same_inode(root_now, opened_root):
                    fail("TA backup root changed before prune")
                remove_tree_at(
                    backup_root_fd,
                    name,
                    entry,
                    entry.st_dev,
                    "TA backup %s" % name,
                )
                print("PRUNED\\t%s" % name)
finally:
    if backup_root_fd >= 0:
        os.close(backup_root_fd)
    os.close(parent_fd)
""",
        executable=True,
    )
    write_text(
        ta_dir / "inventory-backups.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
target_base={target_expr}
python3 "${{script_dir}}/manage-backups.py" inventory --target-base "${{target_base}}"
""",
        executable=True,
    )
    write_text(
        ta_dir / "prune-backups.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail

[[ "${{SPLUNK_OTEL_CONFIRM_BACKUP_PRUNE:-}}" == "yes" ]] || {{
    echo "ERROR: Set SPLUNK_OTEL_CONFIRM_BACKUP_PRUNE=yes after reviewing inventory-backups.sh output." >&2
    exit 1
}}
retain="${{SPLUNK_OTEL_TA_BACKUP_RETAIN:-3}}"
[[ "${{retain}}" =~ ^[0-9]+$ && "${{#retain}}" -le 4 ]] || {{
    echo "ERROR: SPLUNK_OTEL_TA_BACKUP_RETAIN must be an integer from 0 through 1000." >&2
    exit 1
}}
(( 10#${{retain}} <= 1000 )) || {{
    echo "ERROR: SPLUNK_OTEL_TA_BACKUP_RETAIN must be an integer from 0 through 1000." >&2
    exit 1
}}
script_dir="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
target_base={target_expr}
python3 "${{script_dir}}/manage-backups.py" prune \
    --target-base "${{target_base}}" \
    --retain "${{retain}}"
""",
        executable=True,
    )
    deployment_target_expr = '"${SPLUNK_DEPLOYMENT_APPS:-${SPLUNK_HOME:-/opt/splunk}/etc/deployment-apps}"'
    write_text(
        ta_dir / "apply-deployment-server.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail

{render_ta_overlay_function(args, packages, deployment_target_expr, template_hashes, gateway_hashes)}
echo "Applied TA local overlays under ${{target_base}}."
echo "Render server classes with: bash agent-management/render-serverclass-handoff.sh"
echo "Reload and inspect deployment server with splunk-deployment-server-setup after review."
""",
        executable=True,
    )
    local_splunk_home = "/opt/splunk" if args.ta_target == "heavy-forwarder" else "/opt/splunkforwarder"
    uf_target_expr = f'"${{SPLUNK_APPS_DIR:-${{SPLUNK_HOME:-{local_splunk_home}}}/etc/apps}}"'
    write_text(
        ta_dir / "apply-local-uf.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail

{render_ta_overlay_function(args, packages, uf_target_expr, template_hashes, gateway_hashes)}
echo "Applied TA local overlays under ${{target_base}}."
echo "Restart and validate the selected {args.ta_target} runtime after reviewing the overlay."
""",
        executable=True,
    )
    if args.ta_target == "deployment-server":
        status_script = f"""#!/usr/bin/env bash
set -euo pipefail

{render_ta_shell_array("app_roots", app_roots)}
target_base="${{SPLUNK_DEPLOYMENT_APPS:-${{SPLUNK_HOME:-/opt/splunk}}/etc/deployment-apps}}"
failures=0
for app_root in "${{app_roots[@]}}"; do
    for required in default/app.conf default/inputs.conf README/inputs.conf.spec local/inputs.conf; do
        if [[ ! -f "${{target_base}}/${{app_root}}/${{required}}" ]]; then
            echo "ERROR: missing deployment-app file: ${{app_root}}/${{required}}" >&2
            failures=1
        fi
    done
done
(( failures == 0 )) || exit 1
echo "Deployment-app package and local overlay checks passed. Validate server-class delivery on each client before declaring completion."
"""
    else:
        status_script = f"""#!/usr/bin/env bash
set -euo pipefail
umask 077

{render_ta_shell_array("app_roots", app_roots)}

SPLUNK_HOME="${{SPLUNK_HOME:-{local_splunk_home}}}"
if [[ -x "${{SPLUNK_HOME}}/bin/splunk" ]]; then
    failures=0
    work="$(mktemp -d)"
    cleanup() {{ rm -rf "${{work}}"; }}
    trap cleanup EXIT
    if [[ "${{#app_roots[@]}}" -eq 0 ]]; then
        app_roots=(Splunk_TA_otel)
    fi
    for index in "${{!app_roots[@]}}"; do
        app_root="${{app_roots[$index]}}"
        btool_output="${{work}}/btool-${{index}}.txt"
        if ! "${{SPLUNK_HOME}}/bin/splunk" btool inputs list --app="${{app_root}}" --debug >"${{btool_output}}" 2>&1; then
            echo "ERROR: btool could not read inputs for ${{app_root}}" >&2
            failures=1
        elif ! grep -Fq "${{app_root}}" "${{btool_output}}"; then
            echo "ERROR: btool output did not contain the expected ${{app_root}} input." >&2
            failures=1
        fi
        if ! "${{SPLUNK_HOME}}/bin/splunk" display app "${{app_root}}"; then
            echo "ERROR: Splunk did not report installed app ${{app_root}}" >&2
            failures=1
        fi
    done
    (( failures == 0 )) || exit 1
else
    echo "ERROR: ${{SPLUNK_HOME}}/bin/splunk is not executable; set SPLUNK_HOME and rerun." >&2
    exit 2
fi
"""
    write_text(
        ta_dir / "status-ta.sh",
        status_script,
        executable=True,
    )
    agent_dir = ta_dir / "agent-management"
    agent_setup = Path(__file__).resolve().parents[3] / "skills/splunk-agent-management-setup/scripts/setup.sh"
    handoff_lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        'script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"',
        'deployment_apps="${SPLUNK_DEPLOYMENT_APPS:-${SPLUNK_HOME:-/opt/splunk}/etc/deployment-apps}"',
        "",
    ]
    for package in packages:
        if not package["path"]:
            continue
        app_root = str(package["app_root"])
        serverclass_name = re.sub(r"[^A-Za-z0-9_]+", "_", f"splunk_otel_{app_root}")
        machine_filter = ""
        if package["package_flavor"] in ("linux-x86-64", "windows-x86-64"):
            machine_filter = str(package["package_flavor"]).replace("-x86-64", "-x86_64")
        whitelist = args.ta_serverclass_whitelist or "__REVIEW_REQUIRED_NO_MATCH__"
        handoff_lines.extend(
            [
                f"bash {shell_quote(str(agent_setup))} \\",
                "  --mode agent-manager \\",
                "  --phase render \\",
                f"  --serverclass-name {shell_quote(serverclass_name)} \\",
                f"  --deployment-app-name {shell_quote(app_root)} \\",
                f"  --app-source-dir \"${{deployment_apps}}/{app_root}\" \\",
                f"  --whitelist {shell_quote(whitelist)} \\",
                f"  --machine-types-filter {shell_quote(machine_filter)} \\",
                "  --restart-splunkd true \\",
                f"  --output-dir \"${{script_dir}}/rendered-{app_root}\"",
                "",
            ]
        )
    write_text(agent_dir / "render-serverclass-handoff.sh", "\n".join(handoff_lines), executable=True)


def render_ta(args: argparse.Namespace, output_dir: Path) -> None:
    ta_dir = output_dir / "ta"
    if ta_dir.exists():
        shutil.rmtree(ta_dir)
    ta_dir.mkdir(parents=True, exist_ok=True)
    local_dir = ta_dir / "local"
    local_dir.mkdir(parents=True, exist_ok=True)

    packages = inspect_ta_packages(args)
    for index, package in enumerate(packages):
        template = render_ta_inputs_conf_template(args, package)
        app_root = str(package["app_root"])
        package_local = local_dir / app_root
        package_local.mkdir(parents=True, exist_ok=True)
        write_text(package_local / "inputs.conf.template", template)
        if index == 0:
            write_text(local_dir / "inputs.conf.template", template)
        if args.ta_mode == "agent-to-gateway":
            write_text(package_local / "agent_to_gateway_config.yaml", render_agent_to_gateway_config(args))
            if index == 0:
                write_text(local_dir / "agent_to_gateway_config.yaml", render_agent_to_gateway_config(args))

    render_ta_scripts(args, ta_dir, packages)
    write_text(ta_dir / "package-audit.md", ta_package_audit_md(args, packages))
    write_text(ta_dir / "metadata.json", json.dumps(ta_metadata(args, packages), indent=2, sort_keys=True) + "\n")
    if args.ta_fips_required or args.ta_fedramp_required:
        write_text(
            ta_dir / "regulated-environment-warning.md",
            f"""# Regulated Environment Warning

The audited Splunkbase TA artifact metadata marks FIPS compatibility false; Splunkbase
does not document a FedRAMP validation field for this package. This packet was
rendered only because
`--accept-ta-regulated-override` was supplied.

- FIPS required: `{str(args.ta_fips_required).lower()}`
- FedRAMP required: `{str(args.ta_fedramp_required).lower()}`
- Override accepted: `{str(args.accept_ta_regulated_override).lower()}`
""",
        )
    concrete_packages = [package for package in packages if package["path"]]
    if args.ta_secret_mode == "placeholder" or not concrete_packages:
        ta_apply_guidance = """This is a render-only review packet. It cannot be staged or applied until you
re-render with a package and an actionable secret mode (`inputs-conf`,
`legacy-file`, or `environment`).
"""
    elif args.ta_target == "deployment-server":
        ta_apply_guidance = """Apply after review:

```bash
bash preflight-ta.sh
bash stage-ta-package.sh
bash apply-deployment-server.sh
bash agent-management/render-serverclass-handoff.sh
```

Validate deployment-server reload/health and delivery on every client.
"""
    else:
        ta_apply_guidance = f"""Apply to the local `{args.ta_target}` after review:

```bash
bash preflight-ta.sh
bash stage-ta-package.sh
bash apply-local-uf.sh
bash status-ta.sh
```

Restart the selected Splunk runtime through its normal change workflow.
"""
    write_text(
        ta_dir / "README.md",
        f"""# Splunk Add-On for OpenTelemetry Collector

This folder renders reviewable assets for Splunkbase apps `7125`, `8698`, and
`8699`; `package-audit.md` identifies the supplied artifact exactly.

Rendered target: `{args.ta_target}`
Rendered mode: `{args.ta_mode}`
Rendered secret mode: `{args.ta_secret_mode}`

Review `package-audit.md`, `metadata.json`, and `local/inputs.conf.template`.

{ta_apply_guidance}
After the new app is validated, inventory retained rollback copies before
applying a retention policy:

```bash
bash inventory-backups.sh
SPLUNK_OTEL_CONFIRM_BACKUP_PRUNE=yes \
  SPLUNK_OTEL_TA_BACKUP_RETAIN=3 \
  bash prune-backups.sh
```

Backups can contain historical `local/inputs.conf` or `local/access_token`
secrets. Rotate superseded tokens and prune obsolete backups through this
confirmation-gated workflow; never delete the backup root through a
path-following recursive command.

Use `splunk-deployment-server-setup` for deployment-server reload/health,
`splunk-universal-forwarder-setup` for UF install/enrollment, and the standard
Splunk Enterprise service workflow for a heavy forwarder. Use
`splunk-hec-service-setup` only when overriding `SPLUNK_HEC_URL` or
`SPLUNK_HEC_TOKEN` for Splunk Platform HEC logs; otherwise this TA keeps the
current Observability log-ingest defaults.
""",
    )


def metadata(args: argparse.Namespace, output_dir: Path) -> dict[str, object]:
    k8s_supply_chain_digests: dict[str, str] = {}
    for relative in (
        "fetch-chart.sh",
        "k8s-image-post-renderer.py",
        "helm-plugins/splunk-audited-image-pin/plugin.yaml",
        "helm-plugins/splunk-audited-image-pin/run.sh",
        "redact-stream.py",
        "verify-overlay.py",
        "verify-secret-revision.py",
        "helm-release-guard.py",
        "k8s-object-preconditions.py",
        "add-secret-ownership.py",
        "verify-overlays.sh",
        "validate-secrets.sh",
        "instrumentation-lifecycle.py",
        "verify-supply-chain.sh",
    ):
        candidate = output_dir / "k8s" / relative
        if candidate.is_file() and not candidate.is_symlink():
            k8s_supply_chain_digests[relative] = sha256_file(candidate)
    result: dict[str, object] = {
        "skill": "splunk-observability-otel-collector-setup",
        "realm": args.realm,
        "audited_versions": {
            "linux_collector": COLLECTOR_AUDITED_VERSION,
            "linux_auto_instrumentation": INSTRUMENTATION_AUDITED_VERSION,
            "linux_obi": OBI_AUDITED_VERSION,
            "linux_obi_archive_sha256": OBI_ARCHIVE_SHA256,
            "linux_obi_binary_sha256": OBI_BINARY_SHA256,
            "kubernetes_collector_image": CHART_AUDITED_VERSION,
            "helm_chart": CHART_AUDITED_VERSION,
            "helm_chart_archive_sha256": CHART_ARCHIVE_SHA256,
            "kubernetes_collector_standard_image": COLLECTOR_STANDARD_IMAGE,
            "kubernetes_collector_fips_image": COLLECTOR_FIPS_IMAGE,
            "kubernetes_collector_windows_image": COLLECTOR_WINDOWS_IMAGE,
            "eks_fargate_node_discoverer_image": FARGATE_NODE_DISCOVERER_IMAGE,
            "splunkbase_7125": TA_LATEST_VERSION,
            "splunkbase_8698": TA_LATEST_VERSION,
            "splunkbase_8699": TA_LATEST_VERSION,
        },
        "kubernetes": {
            "rendered": args.render_k8s,
            "namespace": args.namespace,
            "release_name": args.release_name,
            "cluster_name": args.cluster_name,
            "distribution": args.distribution,
            "cloud_provider": args.cloud_provider,
            "chart_version": args.chart_version,
            "chart_archive": {
                "name": CHART_ARCHIVE_NAME,
                "url": CHART_ARCHIVE_URL,
                "sha256": CHART_ARCHIVE_SHA256,
                "cache_path": f"k8s/cache/{CHART_ARCHIVE_NAME}",
            },
            "image_supply_chain": {
                "post_renderer": "k8s/k8s-image-post-renderer.py",
                "helm4_plugin": "k8s/helm-plugins/splunk-audited-image-pin/plugin.yaml",
                "support_asset_sha256": k8s_supply_chain_digests,
                "collector_pins": {
                    COLLECTOR_STANDARD_SOURCE_IMAGE: COLLECTOR_STANDARD_IMAGE,
                    COLLECTOR_FIPS_SOURCE_IMAGE: COLLECTOR_FIPS_IMAGE,
                    COLLECTOR_WINDOWS_SOURCE_IMAGE: COLLECTOR_WINDOWS_IMAGE,
                },
                "auxiliary_pins": {
                    FARGATE_NODE_DISCOVERER_SOURCE_IMAGE: FARGATE_NODE_DISCOVERER_IMAGE,
                    **K8S_AUXILIARY_IMAGE_PINS,
                },
                "custom_image_policy": "digest_only",
                "runtime_pod_spec_validation": True,
            },
            "fargate_image_pin": {
                "enabled": args.distribution == "eks/fargate",
                "source_image": FARGATE_NODE_DISCOVERER_SOURCE_IMAGE,
                "release_tag": FARGATE_NODE_DISCOVERER_RELEASE_TAG,
                "image": FARGATE_NODE_DISCOVERER_IMAGE,
                "manifest_list_digest": FARGATE_NODE_DISCOVERER_INDEX_DIGEST,
                "platform_digests": FARGATE_NODE_DISCOVERER_PLATFORM_DIGESTS,
                "audited_at": FARGATE_NODE_DISCOVERER_AUDITED_AT,
                "post_renderer": (
                    "k8s/k8s-image-post-renderer.py"
                    if args.distribution == "eks/fargate"
                    else ""
                ),
                "expected_rewrites": (
                    1
                    if args.distribution == "eks/fargate"
                    and effective_cluster_receiver_enabled(args)
                    else 0
                ),
            },
            "agent_enabled": str_bool(args.agent_enabled) and args.distribution != "eks/fargate",
            "agent_host_network_requested": str_bool(args.agent_host_network),
            "agent_host_network": effective_agent_host_network(args),
            "windows_nodes": str_bool(args.windows_nodes),
            "cluster_receiver_requested": str_bool(args.cluster_receiver_enabled),
            "cluster_receiver_enabled": effective_cluster_receiver_enabled(args),
            "operator_crds_install": str_bool(args.enable_operator_crds)
            and str_bool(args.enable_autoinstrumentation),
            "operator_enabled": str_bool(args.enable_autoinstrumentation),
            "instrumentation_installation_job": str_bool(args.enable_autoinstrumentation)
            and str_bool(args.instrumentation_installation_job),
            "instrumentation_kubectl_image_tag": args.instrumentation_kubectl_image_tag,
            "certmanager_enabled": str_bool(args.enable_certmanager),
            "priority_class_name": args.priority_class_name,
            "gateway_enabled": effective_gateway_enabled(args),
            "gateway_replicas": int(args.gateway_replicas),
            "network_explorer_enabled": str_bool(args.network_explorer_enabled),
            "network_explorer_handoff": (
                "k8s/network-explorer-handoff.md"
                if str_bool(args.network_explorer_enabled)
                else ""
            ),
            "fips_enabled": str_bool(args.fips_enabled),
            "target_allocator_enabled": str_bool(args.target_allocator_enabled),
            "obi_enabled": str_bool(args.enable_obi),
            "discovery_enabled": str_bool(args.enable_discovery),
            "prometheus_autodetect_enabled": str_bool(args.enable_prometheus_autodetect),
            "istio_autodetect_enabled": str_bool(args.enable_istio_autodetect),
            "events_enabled": str_bool(args.enable_events),
            "events_to_observability": str_bool(args.enable_events)
            and observability_destination_enabled(args),
            "events_to_platform": str_bool(args.enable_events) and platform_logs_enabled(args),
            "k8s_objects": args.k8s_objects,
            "cluster_wide_object_rbac_accepted": args.accept_cluster_wide_object_rbac,
            "objects_to_observability": bool(args.k8s_objects)
            and observability_destination_enabled(args),
            "objects_to_platform": bool(args.k8s_objects) and platform_logs_enabled(args),
            "secure_app_enabled": str_bool(args.enable_secure_app),
            "k8s_entities_enabled": str_bool(args.k8s_entities_enabled),
            "entity_events_enabled": str_bool(args.entity_events_enabled),
            "platform_logs_requested": platform_logs_requested(args),
            "platform_logs_pipeline_explicit": str_bool(args.platform_logs_enabled),
            "platform_logs_enabled": platform_logs_enabled(args),
            "container_logs_enabled": str_bool(args.enable_logs)
            and platform_logs_enabled(args),
            "journald_enabled": str_bool(args.enable_journald)
            and platform_logs_enabled(args),
            "platform_log_transport": (
                "otlp" if platform_otlp_logs_enabled(args) else "hec" if platform_hec_logs_enabled(args) else "disabled"
            ),
            "platform_metrics_enabled": platform_metrics_enabled(args),
            "platform_traces_enabled_experimental": platform_traces_enabled(args),
            "platform_persistent_queue_enabled": str_bool(
                args.platform_persistent_queue_enabled
            ),
            "platform_persistent_queue_path": args.platform_persistent_queue_path,
            "platform_fsync_enabled": str_bool(args.platform_fsync_enabled),
            "observability_destination_enabled": observability_destination_enabled(args),
            "platform_only": platform_destination_enabled(args)
            and not observability_destination_enabled(args),
            "collector_image_version": args.chart_version,
            "observability_signals": {
                "metrics": str_bool(args.enable_metrics),
                "traces": str_bool(args.enable_traces),
                "profiling": str_bool(args.enable_profiling),
            },
            "platform_tls": {
                "hec_custom_ca": bool(args.platform_hec_ca_file),
                "hec_mtls": bool(args.platform_hec_client_cert_file),
                "otlp_custom_ca": bool(args.platform_otlp_ca_file),
                "otlp_mtls": bool(args.platform_otlp_client_cert_file),
            },
            "secret_name": secret_name(args.release_name),
        },
        "platform_hec": {
            "helper_rendered": args.render_platform_hec_helper,
            "platform": args.hec_platform,
            "token_name": args.hec_token_name,
            "default_index": hec_default_index(args),
            "allowed_indexes": hec_allowed_indexes(args),
            "token_file": platform_hec_token_path(args, output_dir)
            if platform_hec_token_configured(args)
            else "",
        },
        "linux": {
            "rendered": args.render_linux,
            "execution": args.execution,
            "linux_mode": args.linux_mode,
            "collector_version": args.collector_version,
            "effective_listen_interface": linux_effective_listen_interface(args),
            "health_endpoint": linux_effective_health_endpoint(args),
            "installer_url": args.installer_url,
            "installer_sha256": args.installer_sha256.lower(),
            "instrumentation_mode": args.instrumentation_mode,
            "instrumentation_version": args.instrumentation_version,
            "autoinstrumentation_enabled": str_bool(args.enable_autoinstrumentation),
            "discovery_enabled": str_bool(args.enable_discovery),
            "obi_binary_install_requested": str_bool(args.enable_obi),
            "obi_binary_version": (
                effective_obi_version(args) if str_bool(args.enable_obi) else ""
            ),
            "obi_binary_sha256_by_arch": (
                OBI_BINARY_SHA256 if str_bool(args.enable_obi) else {}
            ),
            "obi_runtime_configured": False,
            "profiling_enabled": str_bool(args.enable_profiling)
            and str_bool(args.enable_autoinstrumentation),
            "memory_profiling_enabled": str_bool(args.enable_memory_profiling)
            and str_bool(args.enable_autoinstrumentation),
            "collector_config": args.collector_config,
            "pipeline_contract": (
                "operator-supplied-unverified"
                if args.collector_config
                else f"upstream-{args.linux_mode}-default"
            ),
            "default_config_pipelines": (
                "operator-defined"
                if args.collector_config
                else ["traces", "metrics", "metrics/internal", "logs"]
            ),
            "sdk_signal_controls": {
                "active": str_bool(args.enable_autoinstrumentation),
                "metrics": (
                    str_bool(args.enable_metrics)
                    if str_bool(args.enable_autoinstrumentation)
                    else "not-applicable"
                ),
                "logs": (
                    str_bool(args.enable_logs)
                    if str_bool(args.enable_autoinstrumentation)
                    else "not-applicable"
                ),
                "traces": (
                    "always-enabled-by-installer"
                    if str_bool(args.enable_autoinstrumentation)
                    else "not-applicable"
                ),
                "cpu_profiling": (
                    str_bool(args.enable_profiling)
                    if str_bool(args.enable_autoinstrumentation)
                    else "not-applicable"
                ),
                "memory_profiling": (
                    str_bool(args.enable_memory_profiling)
                    if str_bool(args.enable_autoinstrumentation)
                    else "not-applicable"
                ),
            },
            "repo_channel": args.repo_channel,
            "skip_collector_repo": str_bool(args.skip_collector_repo),
            "ssh_doctor_and_support_bundle": args.execution == "ssh",
        },
        "signals": {
            "semantics": "requested-product-validation-scope; inspect target-specific effective state",
            "metrics": str_bool(args.enable_metrics),
            "traces": str_bool(args.enable_traces),
            "logs": str_bool(args.enable_logs),
            "journald": str_bool(args.enable_journald),
            "platform_logs_pipeline": str_bool(args.platform_logs_enabled),
            "profiling": str_bool(args.enable_profiling),
            "memory_profiling": str_bool(args.enable_memory_profiling),
            "events": str_bool(args.enable_events),
            "discovery": str_bool(args.enable_discovery),
            "autoinstrumentation": str_bool(args.enable_autoinstrumentation),
            "obi": str_bool(args.enable_obi),
        },
        "warnings": warnings(args),
    }
    if args.render_ta:
        ta_metadata_path = output_dir / "ta" / "metadata.json"
        if ta_metadata_path.is_file():
            result["technical_addon"] = json.loads(ta_metadata_path.read_text(encoding="utf-8"))
        else:
            result["technical_addon"] = {
                "splunkbase": TA_SPLUNKBASE_METADATA,
                "target": args.ta_target,
                "mode": args.ta_mode,
                "secret_mode": args.ta_secret_mode,
            }
    return result


def prepare_managed_secret_directory(args: argparse.Namespace, output_dir: Path) -> None:
    """Protect the non-generated secret directory and migrate the legacy HEC token."""

    secrets_dir = output_dir / ".secrets"
    canonical_token = secrets_dir / "splunk_platform_hec_token"
    legacy_token = output_dir / "platform-hec" / ".splunk_platform_hec_token"
    configured = Path(args.platform_hec_token_file).expanduser() if args.platform_hec_token_file else None
    uses_managed_token = bool(
        args.render_platform_hec_helper
        and (configured is None or configured.resolve() == canonical_token.resolve())
    )
    if not uses_managed_token and not legacy_token.is_file():
        return
    if secrets_dir.is_symlink() or (secrets_dir.exists() and not secrets_dir.is_dir()):
        raise SystemExit(f"managed secret path must be a real directory, not a symlink/file: {secrets_dir}")
    secrets_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    secrets_dir.chmod(0o700)
    if canonical_token.is_symlink():
        raise SystemExit(f"managed HEC token path must not be a symlink: {canonical_token}")
    if legacy_token.is_file() and not legacy_token.is_symlink():
        destination = canonical_token
        if destination.exists():
            digest = sha256_file(legacy_token)[:12]
            destination = secrets_dir / f"splunk_platform_hec_token.legacy-{digest}"
        if not destination.exists():
            legacy_token.replace(destination)
            destination.chmod(0o600)


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)

    if args.dry_run:
        plan = rendered_plan(args)
        if args.json:
            print(json.dumps(plan, indent=2, sort_keys=True))
        else:
            print("Splunk Observability OTel Collector render plan")
            print(f"Output directory: {plan['output_dir']}")
            for warning in plan["warnings"]:
                print(f"Warning: {warning}")
            for command in plan["preparation_commands"]:
                print(f"Preparation command: {command}")
            for command in plan["apply_commands"]:
                print(f"Apply command: {command}")
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    prepare_managed_secret_directory(args, output_dir)
    # This directory is a derived packet produced by platform-hec/*.sh.  A
    # root rerender invalidates its captured settings even when the helper is
    # selected again, so never leave an older actionable packet behind.
    derived_hec_dir = output_dir / "platform-hec-service-rendered"
    if derived_hec_dir.exists():
        shutil.rmtree(derived_hec_dir)
    for directory, enabled in (
        (output_dir / "k8s", args.render_k8s),
        (output_dir / "linux", args.render_linux),
        (output_dir / "ta", args.render_ta),
        (output_dir / "platform-hec", args.render_platform_hec_helper),
    ):
        if not enabled and directory.exists():
            shutil.rmtree(directory)
    if args.render_platform_hec_helper:
        render_platform_hec_helper(args, output_dir)
    if args.render_k8s:
        render_k8s(args, output_dir)
    if args.render_linux:
        render_linux(args, output_dir)
    if args.render_ta:
        render_ta(args, output_dir)
    write_text(output_dir / "metadata.json", json.dumps(metadata(args, output_dir), indent=2, sort_keys=True) + "\n")
    print(f"Rendered Splunk Observability OTel Collector assets to {output_dir}")
    for warning in warnings(args):
        print(f"Warning: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

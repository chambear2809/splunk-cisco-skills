#!/usr/bin/env python3
"""Target-bound, gated Luna Studio Helm lifecycle."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import hmac
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from render_bundle import (  # noqa: E402
    fail,
    load_yaml_or_json,
    mapping,
    origin,
    secure_read,
    validate_bundle,
)

UTC = dt.timezone.utc
RUNTIME_ENV: dict[str, str] | None = None
KUBECONFIG_SNAPSHOT: str | None = None
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
PINNED_IMAGE = re.compile(r"^\S+@(?P<digest>sha256:[0-9a-f]{64})$")
URL_LITERAL = re.compile(
    r"(?i)\b(?:https?|grpcs?|wss?|postgres(?:ql)?|redis|rediss|amqp|amqps|smtp|smtps|s3)://[^\s\"'<>]+"
)
ENDPOINT_KEY = re.compile(
    r"(?i)(?:(?:^|[_-])(?:url|uri|dsn|endpoint|host|hostname|server|address)(?:$|[_-])|(?:url|uri|dsn|endpoint|host|hostname|server|address)$)"
)
HOSTPORT = re.compile(
    r"^(?:\[[0-9a-fA-F:]+\]|[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?)(?::[0-9]{1,5})?$"
)
CREDENTIAL_VALUE = re.compile(
    r"(?i)(?:bearer\s+\S+|(?:password|passwd|token|api[_-]?key|secret|credential)\s*[:=]\s*\S+|-----BEGIN [A-Z ]*PRIVATE KEY-----|https?://[^/@\s:]+:[^/@\s]+@)"
)
KUBERNETES_ARCHITECTURES = {"amd64", "arm64", "ppc64le", "s390x"}
SECRET_PATH_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def absolute(raw: str) -> Path:
    return Path(os.path.abspath(Path(raw).expanduser()))


def timestamp(value: object) -> dt.datetime:
    if not isinstance(value, str):
        fail("timestamp must be a string")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        fail("timestamp is not ISO-8601")
    if parsed.tzinfo is None:
        fail("timestamp requires timezone")
    return parsed.astimezone(UTC)


def private_json_bound(raw: str, label: str):
    artifact = secure_read(raw, label, private=True, limit=1024 * 1024)

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict:
        result: dict = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(artifact.data, object_pairs_hook=reject_duplicates)
    except (json.JSONDecodeError, ValueError):
        fail(f"{label} is not duplicate-free JSON")
    if not isinstance(value, dict):
        fail(f"{label} must be an object")
    return value, artifact


def private_json(raw: str, label: str) -> dict:
    value, artifact = private_json_bound(raw, label)
    if artifact.data != (json.dumps(value, indent=2, sort_keys=True) + "\n").encode():
        fail(f"{label} must be canonical JSON")
    return value


def require_approval_preflight_binding(
    approval: dict, evidence: dict, evidence_sha256: str
) -> None:
    if (
        not re.fullmatch(r"[0-9a-f]{64}", evidence_sha256)
        or approval.get("preflight_sha256") != evidence_sha256
        or timestamp(approval.get("issued_at")) < timestamp(evidence.get("created_at"))
    ):
        fail("approval is stale or does not bind the exact fresh preflight")


def assert_preflight_unchanged(raw: str, expected_sha256: str) -> dict:
    value, artifact = private_json_bound(raw, "preflight evidence")
    if (
        artifact.sha256 != expected_sha256
        or artifact.data
        != (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    ):
        fail("preflight evidence changed after approval")
    return value


def exact_fields(value: dict, expected: set[str], label: str) -> None:
    if set(value) != expected:
        fail(f"{label} fields differ from the exact contract")


def exact_value(actual: object, expected: object) -> bool:
    """Compare evidence without Python's bool/int or loose container equality."""
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return set(actual) == set(expected) and all(
            exact_value(actual[key], value) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            exact_value(left, right) for left, right in zip(actual, expected)
        )
    return actual == expected


def safe_human_text(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 512
        or CREDENTIAL_VALUE.search(value)
    ):
        fail(f"{label} must be nonempty credential-free text")
    return value.strip()


def reject_credential_values(value: object, label: str) -> None:
    """Reject credential-shaped text anywhere in an attestation object."""
    if isinstance(value, dict):
        for key, item in value.items():
            reject_credential_values(item, f"{label}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            reject_credential_values(item, f"{label}[{index}]")
    elif isinstance(value, str) and CREDENTIAL_VALUE.search(value):
        fail(f"{label} contains credential-shaped text")


def command_env() -> dict[str, str]:
    if RUNTIME_ENV is None:
        fail("private command runtime is not initialized")
    return dict(RUNTIME_ENV)


def prepare_runtime(raw: str) -> tempfile.TemporaryDirectory[str]:
    global KUBECONFIG_SNAPSHOT, RUNTIME_ENV
    source = secure_read(raw, "kubeconfig", private=True, limit=4 * 1024 * 1024)
    holder = tempfile.TemporaryDirectory(prefix="galileo-kube-")
    root = Path(holder.name)
    root.chmod(0o700)
    for name in (
        "config",
        "cache",
        "data",
        "runtime",
        "helm-config",
        "helm-cache",
        "helm-data",
    ):
        (root / name).mkdir(mode=0o700)
    snapshot = root / "kubeconfig"
    descriptor = os.open(
        snapshot,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        view = memoryview(source.data)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    KUBECONFIG_SNAPSHOT = str(snapshot)
    RUNTIME_ENV = {
        "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin",
        "XDG_CONFIG_HOME": str(root / "config"),
        "XDG_CACHE_HOME": str(root / "cache"),
        "XDG_DATA_HOME": str(root / "data"),
        "XDG_RUNTIME_DIR": str(root / "runtime"),
        "HELM_CONFIG_HOME": str(root / "helm-config"),
        "HELM_CACHE_HOME": str(root / "helm-cache"),
        "HELM_DATA_HOME": str(root / "helm-data"),
        "KUBECONFIG": str(snapshot),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
    }
    for key in ("SSL_CERT_FILE", "SSL_CERT_DIR"):
        if key in os.environ:
            RUNTIME_ENV[key] = os.environ[key]
    return holder


def run(
    argv: list[str], allow_failure: bool = False
) -> subprocess.CompletedProcess[str]:
    if KUBECONFIG_SNAPSHOT is None:
        fail("private kubeconfig snapshot is not initialized")
    if Path(argv[0]).name in {"kubectl", "helm"} and "--kubeconfig" not in argv:
        argv = [argv[0], "--kubeconfig", KUBECONFIG_SNAPSHOT, *argv[1:]]
    try:
        result = subprocess.run(
            argv,
            env=command_env(),
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        fail(f"required command could not run: {argv[0]}")
    if result.returncode and not allow_failure:
        fail(
            f"{Path(argv[0]).name} operation failed; use an approved redacted diagnostic workflow"
        )
    return result


def tools() -> None:
    missing = [
        x
        for x in ("kubectl", "helm")
        if shutil.which(x, path=command_env()["PATH"]) is None
    ]
    if missing:
        fail("missing required executable(s): " + ", ".join(missing))


def validate_kubeconfig_user_auth(auth: object) -> None:
    if not isinstance(auth, dict):
        fail("kubeconfig user authentication must be a mapping")
    if "exec" in auth or "auth-provider" in auth:
        fail(
            "exec/auth-provider kubeconfig authentication is not supported in the "
            "isolated lifecycle; generate a short-lived mode-0600 static kubeconfig "
            "with embedded credential material out of band"
        )
    if (
        auth.get("client-certificate")
        or auth.get("client-key")
        or auth.get("tokenFile")
    ):
        fail(
            "kubeconfig authentication file references are forbidden; embed credentials"
        )


def target(context: str, namespace: str) -> dict:
    tools()
    if KUBECONFIG_SNAPSHOT is None:
        fail("kubeconfig snapshot is unavailable")
    cfg = mapping(
        secure_read(
            KUBECONFIG_SNAPSHOT,
            "kubeconfig snapshot",
            private=True,
            limit=4 * 1024 * 1024,
        )
    )
    contexts = cfg.get("contexts", [])
    clusters = cfg.get("clusters", [])
    matches = [
        item
        for item in contexts
        if isinstance(item, dict) and item.get("name") == context
    ]
    if len(matches) != 1:
        fail("explicit kube context is missing or duplicated")
    cluster_name = matches[0].get("context", {}).get("cluster")
    cluster_matches = [
        item
        for item in clusters
        if isinstance(item, dict) and item.get("name") == cluster_name
    ]
    if len(cluster_matches) != 1:
        fail("explicit kube context does not resolve one cluster")
    cluster = cluster_matches[0].get("cluster", {})
    user_name = matches[0].get("context", {}).get("user")
    users = cfg.get("users", [])
    user_matches = [
        item
        for item in users
        if isinstance(item, dict) and item.get("name") == user_name
    ]
    if user_name and len(user_matches) != 1:
        fail("explicit kube context does not resolve one user")
    if user_matches:
        validate_kubeconfig_user_auth(user_matches[0].get("user", {}))
    server = cluster.get("server")
    parsed_server = urlsplit(server) if isinstance(server, str) else None
    try:
        server_port = parsed_server.port if parsed_server else None
    except ValueError:
        server_port = -1
    if (
        not isinstance(server, str)
        or parsed_server is None
        or parsed_server.scheme != "https"
        or not parsed_server.hostname
        or parsed_server.username
        or parsed_server.password
        or parsed_server.path not in {"", "/"}
        or parsed_server.query
        or parsed_server.fragment
        or server_port == -1
        or (server_port is not None and server_port < 1)
        or (
            "insecure-skip-tls-verify" in cluster
            and cluster.get("insecure-skip-tls-verify") is not False
        )
    ):
        fail("Kubernetes target must use verified HTTPS")
    ca_data = cluster.get("certificate-authority-data")
    if (
        cluster.get("certificate-authority")
        or not isinstance(ca_data, str)
        or not ca_data
    ):
        fail("kubeconfig must embed certificate-authority-data")
    try:
        ca = base64.b64decode(ca_data, validate=True)
    except (ValueError, base64.binascii.Error):
        fail("certificate-authority-data is invalid base64")
    if not ca:
        fail("Kubernetes CA data is empty")
    system_uid = run(
        [
            "kubectl",
            "--context",
            context,
            "get",
            "namespace",
            "kube-system",
            "-o",
            "jsonpath={.metadata.uid}",
        ]
    ).stdout.strip()
    namespace_uid = (
        run(
            [
                "kubectl",
                "--context",
                context,
                "get",
                "namespace",
                namespace,
                "--ignore-not-found",
                "-o",
                "jsonpath={.metadata.uid}",
            ]
        ).stdout.strip()
        or "ABSENT"
    )
    if not system_uid:
        fail("kube-system UID is unavailable")
    return {
        "context": context,
        "api_server": server,
        "ca_sha256": hashlib.sha256(ca).hexdigest(),
        "kube_system_uid": system_uid,
        "namespace_uid": namespace_uid,
    }


def release(context: str, namespace: str, name: str) -> dict | None:
    result = run(
        [
            "helm",
            "--kube-context",
            context,
            "list",
            "--all",
            "--namespace",
            namespace,
            "--filter",
            f"^{re.escape(name)}$",
            "--output",
            "json",
        ]
    )
    try:
        items = json.loads(result.stdout)
    except json.JSONDecodeError:
        fail("Helm returned invalid release inventory")
    if not items:
        return None
    if len(items) != 1 or items[0].get("name") != name:
        fail("release inventory is ambiguous")
    return {
        key: items[0].get(key)
        for key in (
            "name",
            "namespace",
            "revision",
            "updated",
            "status",
            "chart",
            "app_version",
        )
    }


def release_identity(state: dict | None, metadata: dict) -> None:
    if state is None:
        fail("expected Luna release is absent")
    chart = metadata.get("chart")
    if (
        not isinstance(chart, dict)
        or state.get("namespace") != metadata["namespace"]
        or state.get("chart") != f"luna-studio-{chart['version']}"
        or str(state.get("app_version", "")) != str(chart["app_version"])
    ):
        fail("existing Luna release does not match the immutable chart/version")


def validate_observed_release_ownership(state: dict | None, metadata: dict) -> None:
    if state is None:
        return
    if metadata["ownership"] == "umbrella-overlay":
        fail(
            "umbrella-owned Luna Studio conflicts with a standalone luna-studio "
            "Helm release"
        )
    release_identity(state, metadata)


def state_version(state: dict, chart_name: str) -> str:
    value = state.get("chart")
    prefix = chart_name + "-"
    if (
        not isinstance(value, str)
        or not value.startswith(prefix)
        or not SEMVER.fullmatch(value[len(prefix) :])
    ):
        fail("existing release chart/version cannot be parsed safely")
    return value[len(prefix) :]


def semver(value: str) -> tuple[int, int, int]:
    match = SEMVER.fullmatch(value)
    if not match:
        fail("chart version is not semantic versioning")
    return tuple(map(int, match.groups()))


def require_parent_release(context: str, metadata: dict) -> dict:
    parent = metadata["parent_stack"]
    state = release(context, metadata["namespace"], parent["release"])
    if (
        state is None
        or state.get("namespace") != metadata["namespace"]
        or state.get("chart") != f"galileo-stack-{parent['chart']['version']}"
    ):
        fail("live parent Stack release/chart/version does not match its contract")
    return state


def secret_keys(context: str, namespace: str, name: str) -> set[str]:
    template = '{{range $key, $value := .data}}{{printf "%s\\n" $key}}{{end}}'
    result = run(
        [
            "kubectl",
            "--context",
            context,
            "--namespace",
            namespace,
            "get",
            "secret",
            name,
            "--output",
            f"go-template={template}",
        ],
        allow_failure=True,
    )
    if result.returncode:
        fail(f"required Kubernetes Secret is missing: {name}")
    return set(result.stdout.splitlines())


def redacted_secret_input_contract(data: bytes) -> dict:
    """Describe secret input influence without persisting a content verifier."""
    try:
        document = load_yaml_or_json(data.decode("utf-8"), source="secret-values")
    except UnicodeDecodeError:
        fail("secret-values file is not UTF-8")
    if not isinstance(document, dict) or not document:
        fail("secret-values file must contain a non-empty mapping")
    leaves: list[dict] = []

    def walk(value: object, parts: list[str]) -> None:
        if isinstance(value, dict):
            if not value:
                leaves.append({"path": "/" + "/".join(parts), "shape": "object"})
                return
            for key in sorted(value):
                if not isinstance(key, str) or not SECRET_PATH_SEGMENT.fullmatch(key):
                    fail("secret-values key path is outside the safe allowlist")
                walk(value[key], [*parts, key])
            return
        if isinstance(value, list):
            if not value:
                leaves.append({"path": "/" + "/".join(parts), "shape": "list"})
                return
            for index, item in enumerate(value):
                walk(item, [*parts, str(index)])
            return
        if value is None:
            shape = "null"
        elif isinstance(value, bool):
            shape = "boolean"
        elif isinstance(value, int) and not isinstance(value, bool):
            shape = "integer"
        elif isinstance(value, float):
            shape = "number"
        elif isinstance(value, str):
            shape = "string"
        else:
            fail("secret-values file contains an unsupported scalar type")
        leaves.append({"path": "/" + "/".join(parts), "shape": shape})

    walk(document, [])
    return {
        "schema": "galileo-on-prem-redacted-secret-input-contract/v1",
        "path_policy": "safe-helm-values-paths/v1",
        "leaves": [
            {
                **leaf,
                "influence": ["helm-template", "kubernetes-server-dry-run"],
            }
            for leaf in sorted(leaves, key=lambda item: item["path"])
        ],
    }


def snapshot_secret_input(
    artifact,
) -> tuple[tempfile.TemporaryDirectory[str], Path, dict]:
    """Copy a private input once and verify the copy with a process-local HMAC."""
    contract = redacted_secret_input_contract(artifact.data)
    holder = tempfile.TemporaryDirectory(prefix="galileo-secret-input-")
    root = Path(holder.name)
    root.chmod(0o700)
    path = root / "secret-values.yaml"
    key = os.urandom(32)
    expected = hmac.digest(key, artifact.data, "sha256")
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        view = memoryview(artifact.data)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    copied = secure_read(
        path, "secret-values snapshot", private=True, limit=16 * 1024 * 1024
    )
    observed = hmac.digest(key, copied.data, "sha256")
    if not hmac.compare_digest(expected, observed):
        holder.cleanup()
        fail("secret-values snapshot changed during private input capture")
    if redacted_secret_input_contract(copied.data) != contract:
        holder.cleanup()
        fail("secret-values redacted contract changed during input capture")
    return holder, path, contract


def rendered_documents(payload: bytes) -> list[dict]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        fail("Helm rendered non-UTF-8 resources")
    documents: list[dict] = []
    for index, chunk in enumerate(re.split(r"(?m)^---[ \t]*(?:#.*)?$", text)):
        if not chunk.strip() or all(
            not line.strip() or line.lstrip().startswith("#")
            for line in chunk.splitlines()
        ):
            continue
        try:
            document = load_yaml_or_json(chunk, source=f"Helm render document {index}")
        except ValueError:
            fail("Helm rendered malformed YAML")
        if isinstance(document, dict) and document.get("kind") == "List":
            items = document.get("items")
            if not isinstance(items, list) or any(
                not isinstance(item, dict) for item in items
            ):
                fail("Helm rendered a malformed Kubernetes List")
            documents.extend(items)
        elif isinstance(document, dict):
            documents.append(document)
    if not documents:
        fail("Helm rendered no Kubernetes resources")
    return documents


def redacted_render_sha256(documents: list[dict]) -> str:
    """Hash manifest structure while making every scalar value unrecoverable."""

    def redact(value: object) -> object:
        if isinstance(value, dict):
            return {key: redact(value[key]) for key in sorted(value)}
        if isinstance(value, list):
            return [redact(item) for item in value]
        if value is None:
            return {"$redacted": "null"}
        if isinstance(value, bool):
            return {"$redacted": "boolean"}
        if isinstance(value, int) and not isinstance(value, bool):
            return {"$redacted": "integer"}
        if isinstance(value, float):
            return {"$redacted": "number"}
        if isinstance(value, str):
            return {"$redacted": "string"}
        fail("render contains an unsupported scalar type")

    payload = redact(documents)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def object_name(document: dict) -> str:
    metadata = document.get("metadata")
    return str(metadata.get("name", "")) if isinstance(metadata, dict) else ""


def strings(node: object) -> set[str]:
    result: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            result.add(str(key))
            result.update(strings(value))
    elif isinstance(node, list):
        for value in node:
            result.update(strings(value))
    elif isinstance(node, (str, int, float, bool)):
        result.add(str(node))
    return result


def exact_ingress_tls(
    document: dict, expected_host: str, expected_secret: str, label: str
) -> None:
    spec = document.get("spec")
    if not isinstance(spec, dict):
        fail(f"{label} has no structured spec")
    rules = spec.get("rules")
    tls = spec.get("tls")
    if not isinstance(rules, list) or not isinstance(tls, list):
        fail(f"{label} lacks explicit rules/TLS")
    if "defaultBackend" in spec:
        fail(f"{label} must not expose a hostless default backend")
    metadata = document.get("metadata", {})
    annotations = metadata.get("annotations", {}) if isinstance(metadata, dict) else {}
    if not isinstance(annotations, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in annotations.items()
    ):
        fail(f"{label} annotations are malformed")
    forbidden_annotation_fragments = (
        "server-alias",
        "server-snippet",
        "configuration-snippet",
        "router.rule",
        "host-regex",
    )
    if any(
        any(fragment in key.lower() for fragment in forbidden_annotation_fragments)
        for key in annotations
    ):
        fail(f"{label} annotations may not override the exact reviewed hostname")
    rule_hosts = [item.get("host") for item in rules if isinstance(item, dict)]
    if len(rule_hosts) != len(rules) or rule_hosts != [expected_host]:
        fail(f"{label} must bind the one exact reviewed host without wildcards")
    if len(tls) != 1 or not isinstance(tls[0], dict):
        fail(f"{label} must carry one exact TLS binding")
    tls_hosts = tls[0].get("hosts")
    if (
        tls[0].get("secretName") != expected_secret
        or not isinstance(tls_hosts, list)
        or tls_hosts != [expected_host]
    ):
        fail(f"{label} TLS Secret/host set differs from the reviewed contract")


def exact_http_route_host(document: dict, expected_host: str, label: str) -> None:
    spec = document.get("spec")
    hostnames = spec.get("hostnames") if isinstance(spec, dict) else None
    if not isinstance(hostnames, list) or hostnames != [expected_host]:
        fail(f"{label} must bind the one exact reviewed hostname without wildcards")
    metadata = document.get("metadata", {})
    annotations = metadata.get("annotations", {}) if isinstance(metadata, dict) else {}
    if not isinstance(annotations, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in annotations.items()
    ):
        fail(f"{label} annotations are malformed")
    if any(
        any(
            fragment in key.lower()
            for fragment in ("server-alias", "router.rule", "host-regex")
        )
        for key in annotations
    ):
        fail(f"{label} annotations may not override the exact reviewed hostname")


def exact_single_route(routes: list[dict], expected_kind: str, label: str) -> dict:
    if (
        len(routes) != 1
        or not isinstance(routes[0], dict)
        or routes[0].get("kind") != expected_kind
    ):
        fail(f"{label} must render only one exact {expected_kind}")
    return routes[0]


def pod_specs(documents: list[dict]) -> list[tuple[str, dict]]:
    result: list[tuple[str, dict]] = []
    for document in documents:
        kind = str(document.get("kind", ""))
        name = object_name(document)
        spec = document.get("spec", {})
        if kind in {"Deployment", "StatefulSet", "DaemonSet", "ReplicaSet"}:
            pod = spec.get("template", {}).get("spec")
        elif kind == "Job":
            pod = spec.get("template", {}).get("spec")
        elif kind == "CronJob":
            pod = (
                spec.get("jobTemplate", {})
                .get("spec", {})
                .get("template", {})
                .get("spec")
            )
        elif kind == "Pod":
            pod = spec
        else:
            continue
        if isinstance(pod, dict):
            result.append((f"{kind}/{name}", pod))
    return result


def live_nodes(context: str) -> list[dict]:
    try:
        document = json.loads(
            run(["kubectl", "--context", context, "get", "nodes", "-o", "json"]).stdout
        )
    except json.JSONDecodeError:
        fail("Kubernetes returned invalid node inventory")
    items = document.get("items") if isinstance(document, dict) else None
    if (
        not isinstance(items, list)
        or not items
        or any(not isinstance(item, dict) for item in items)
    ):
        fail("Kubernetes node inventory is empty or malformed")
    return items


def tolerates_node(pod: dict, node: dict) -> bool:
    tolerations = pod.get("tolerations", [])
    node_spec = node.get("spec")
    if not isinstance(node_spec, dict):
        fail("pod/node scheduling constraints are malformed")
    taints = node_spec.get("taints", [])
    if not isinstance(tolerations, list) or not isinstance(taints, list):
        fail("pod/node scheduling constraints are malformed")
    for taint in taints:
        if (
            not isinstance(taint, dict)
            or not isinstance(taint.get("key"), str)
            or not taint["key"]
            or ("value" in taint and not isinstance(taint["value"], str))
            or taint.get("effect")
            not in {"NoSchedule", "NoExecute", "PreferNoSchedule"}
        ):
            fail("node taint has an unsupported or missing effect")
        if taint["effect"] == "PreferNoSchedule":
            continue
        matched = False
        for toleration in tolerations:
            if not isinstance(toleration, dict):
                fail("pod toleration is malformed")
            effect = toleration.get("effect", "")
            if effect not in {"", taint["effect"]}:
                continue
            operator = toleration.get("operator", "Equal")
            key = toleration.get("key", "")
            value = toleration.get("value", "")
            if (
                not isinstance(key, str)
                or not isinstance(value, str)
                or not isinstance(effect, str)
            ):
                fail("pod toleration is malformed")
            if (operator == "Exists" and value) or (operator == "Equal" and not key):
                fail("pod toleration uses an invalid key/value contract")
            if operator == "Exists" and (not key or key == taint.get("key")):
                matched = True
            elif (
                operator == "Equal"
                and key == taint.get("key")
                and value == taint.get("value", "")
            ):
                matched = True
            elif operator not in {"Exists", "Equal"}:
                fail("pod toleration uses an unsupported operator")
        if not matched:
            return False
    return True


def node_term_matches(term: dict, labels: dict, node_name: str) -> bool:
    has_expression = False
    for field, source in (("matchExpressions", labels), ("matchFields", None)):
        expressions = term.get(field, [])
        if not isinstance(expressions, list):
            fail("required node affinity is malformed")
        for expression in expressions:
            has_expression = True
            if not isinstance(expression, dict):
                fail("required node affinity expression is malformed")
            key = expression.get("key")
            operator = expression.get("operator")
            values = expression.get("values", [])
            if (
                not isinstance(key, str)
                or operator not in {"In", "NotIn", "Exists", "DoesNotExist", "Gt", "Lt"}
                or not isinstance(values, list)
                or any(not isinstance(value, str) for value in values)
                or (operator in {"In", "NotIn"} and not values)
                or (operator in {"Exists", "DoesNotExist"} and values)
            ):
                fail("required node affinity expression is unsupported")
            if source is None:
                if key != "metadata.name" or operator not in {"In", "NotIn"}:
                    fail("required node matchFields expression is unsupported")
                observed = node_name
            else:
                observed = source.get(key)
            if operator == "In" and (observed is None or observed not in values):
                return False
            if operator == "NotIn" and observed is not None and observed in values:
                return False
            if operator == "Exists" and observed is None:
                return False
            if operator == "DoesNotExist" and observed is not None:
                return False
            if operator in {"Gt", "Lt"}:
                if (
                    len(values) != 1
                    or not str(observed).lstrip("-").isdigit()
                    or not values[0].lstrip("-").isdigit()
                ):
                    fail("numeric node affinity expression is invalid")
                if operator == "Gt" and int(str(observed)) <= int(values[0]):
                    return False
                if operator == "Lt" and int(str(observed)) >= int(values[0]):
                    return False
    return has_expression


def eligible_architectures(
    pod: dict, nodes: list[dict], source_object: str
) -> list[str]:
    if pod.get("schedulerName", "default-scheduler") != "default-scheduler":
        fail(f"{source_object} uses an unprovable custom scheduler")
    if pod.get("runtimeClassName") not in {None, ""}:
        fail(f"{source_object} uses an unprovable RuntimeClass scheduler overlay")
    selector = pod.get("nodeSelector", {})
    if not isinstance(selector, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in selector.items()
    ):
        fail(f"{source_object} nodeSelector is malformed")
    node_name = pod.get("nodeName")
    if node_name is not None and (not isinstance(node_name, str) or not node_name):
        fail(f"{source_object} nodeName is malformed")
    affinity = pod.get("affinity", {})
    if not isinstance(affinity, dict):
        fail(f"{source_object} affinity is malformed")
    node_affinity = affinity.get("nodeAffinity", {})
    if not isinstance(node_affinity, dict):
        fail(f"{source_object} node affinity is malformed")
    required = node_affinity.get("requiredDuringSchedulingIgnoredDuringExecution")
    terms = required.get("nodeSelectorTerms") if isinstance(required, dict) else None
    if required is not None and (not isinstance(terms, list) or not terms):
        fail(f"{source_object} required node affinity is malformed")
    if terms is not None and any(not isinstance(term, dict) for term in terms):
        fail(f"{source_object} required node affinity is malformed")
    architectures: set[str] = set()
    for node in nodes:
        metadata = node.get("metadata", {})
        node_spec = node.get("spec", {})
        labels = metadata.get("labels", {}) if isinstance(metadata, dict) else {}
        name = metadata.get("name") if isinstance(metadata, dict) else None
        if (
            not isinstance(metadata, dict)
            or not isinstance(labels, dict)
            or not isinstance(name, str)
            or not isinstance(node_spec, dict)
            or (
                "unschedulable" in node_spec
                and not isinstance(node_spec["unschedulable"], bool)
            )
        ):
            fail("Kubernetes node scheduling evidence is malformed")
        if (
            node_spec.get("unschedulable") is True
            or (node_name is not None and node_name != name)
            or any(labels.get(key) != value for key, value in selector.items())
            or not tolerates_node(pod, node)
        ):
            continue
        if terms is not None and not any(
            node_term_matches(term, labels, name) for term in terms
        ):
            continue
        architecture = labels.get("kubernetes.io/arch")
        if architecture not in KUBERNETES_ARCHITECTURES:
            fail(f"eligible node for {source_object} has an unsupported architecture")
        architectures.add(architecture)
    if not architectures:
        fail(f"{source_object} has no eligible live node architecture")
    return sorted(architectures)


def rendered_image_items(
    documents: list[dict], release_name: str, nodes: list[dict]
) -> list[dict]:
    """Return exact digest-pinned images for workloads, hooks, init, jobs, and tests."""
    items: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for source_object, pod in pod_specs(documents):
        workload_architectures = eligible_architectures(pod, nodes, source_object)
        for field, container_type in (
            ("containers", "container"),
            ("initContainers", "initContainer"),
            ("ephemeralContainers", "ephemeralContainer"),
        ):
            containers = pod.get(field, [])
            if not isinstance(containers, list):
                fail(f"{source_object} has malformed {field}")
            for container in containers:
                if not isinstance(container, dict):
                    fail(f"{source_object} has a malformed container")
                name = container.get("name")
                image = container.get("image")
                match = (
                    PINNED_IMAGE.fullmatch(image) if isinstance(image, str) else None
                )
                if not isinstance(name, str) or not name or match is None:
                    fail(
                        f"{source_object} image evidence requires named, digest-pinned containers"
                    )
                identity = (source_object, container_type, name)
                if identity in seen:
                    fail(
                        "rendered image evidence contains a duplicate container identity"
                    )
                seen.add(identity)
                items.append(
                    {
                        "release": release_name,
                        "source_object": source_object,
                        "container_type": container_type,
                        "container": name,
                        "image": image,
                        "digest": match.group("digest"),
                        "eligible_architectures": workload_architectures,
                    }
                )
    if not items:
        fail("rendered image evidence contains no workload images")
    return sorted(
        items,
        key=lambda item: (
            item["source_object"],
            item["container_type"],
            item["container"],
            item["image"],
        ),
    )


def normalized_endpoint_host(raw: str) -> str | None:
    """Reduce a URL/host literal to a credential-free lowercase host[:port]."""
    candidate = raw.strip().rstrip(",.;)}]")
    if not candidate or "{{" in candidate or "${" in candidate:
        return None
    parsed = urlsplit(candidate if "://" in candidate else "//" + candidate)
    try:
        port = parsed.port
    except ValueError:
        return None
    if not parsed.hostname or (port is not None and not 1 <= port <= 65535):
        return None
    host = parsed.hostname.lower().rstrip(".")
    hostport = f"[{host}]" if ":" in host else host
    if port is not None:
        hostport += f":{port}"
    return hostport if HOSTPORT.fullmatch(hostport) else None


def _endpoint_candidates(raw: str, key_hint: str) -> list[str]:
    candidates = URL_LITERAL.findall(raw)
    if ENDPOINT_KEY.search(key_hint):
        candidates.append(raw)
    return candidates


def _collect_endpoint_node(
    node: object,
    *,
    source: str,
    path: str = "$",
    key_hint: str = "",
) -> set[tuple[str, str, str]]:
    found: set[tuple[str, str, str]] = set()
    if isinstance(node, dict):
        env_name = node.get("name")
        env_value = node.get("value")
        if (
            isinstance(env_name, str)
            and isinstance(env_value, str)
            and ENDPOINT_KEY.search(env_name)
        ):
            for candidate in _endpoint_candidates(env_value, env_name):
                host = normalized_endpoint_host(candidate)
                if host:
                    found.add((host, env_name.lower()[:128], f"{source}:{path}"))
        for key, value in node.items():
            found.update(
                _collect_endpoint_node(
                    value,
                    source=source,
                    path=f"{path}.{key}",
                    key_hint=str(key),
                )
            )
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.update(
                _collect_endpoint_node(
                    value,
                    source=source,
                    path=f"{path}[{index}]",
                    key_hint=key_hint,
                )
            )
    elif isinstance(node, str):
        for candidate in _endpoint_candidates(node, key_hint):
            host = normalized_endpoint_host(candidate)
            if host:
                purpose = key_hint.lower()[:128] or "url-literal"
                found.add((host, purpose, f"{source}:{path}"))
    return found


def _chart_endpoint_literals(chart: Path) -> set[tuple[str, str, str]]:
    artifact = secure_read(chart, "endpoint-evidence chart")
    found: set[tuple[str, str, str]] = set()
    try:
        with tarfile.open(fileobj=io.BytesIO(artifact.data), mode="r:*") as archive:
            for member in archive.getmembers():
                name = member.name.replace("\\", "/")
                lowered = name.lower()
                if (
                    not member.isfile()
                    or member.size > 4 * 1024 * 1024
                    or not (
                        "/templates/" in lowered
                        or lowered.endswith("/values.yaml")
                        or lowered.endswith("/values.yml")
                    )
                ):
                    continue
                handle = archive.extractfile(member)
                if handle is None:
                    fail("endpoint-evidence chart member could not be read")
                try:
                    text = handle.read().decode("utf-8")
                except UnicodeDecodeError:
                    continue
                for candidate in URL_LITERAL.findall(text):
                    host = normalized_endpoint_host(candidate)
                    if host:
                        found.add((host, "chart-url-literal", f"chart:{name}"))
                setting = re.compile(
                    r"(?im)\b(url|uri|dsn|endpoint|host|hostname|server|address)\b\s*[:=]\s*['\"]?([^\s'\"#,}]+)"
                )
                for key, value in setting.findall(text):
                    host = normalized_endpoint_host(value)
                    if host:
                        found.add((host, key.lower(), f"chart:{name}"))
    except (tarfile.TarError, OSError):
        fail("endpoint-evidence chart is not a readable Helm archive")
    return found


def rendered_endpoint_items(
    documents: list[dict],
    chart: Path,
    nonsecret_values: list[Path],
    secret_values: Path,
) -> list[dict]:
    """Derive exact host-only endpoint evidence from render and immutable inputs."""
    found = _chart_endpoint_literals(chart)
    for value_path in nonsecret_values:
        value = mapping(secure_read(value_path, "endpoint-evidence values"))
        found.update(
            _collect_endpoint_node(
                value, source=f"values:{value_path.name}", key_hint=""
            )
        )
    private_values = mapping(
        secure_read(
            secret_values,
            "endpoint-evidence secret values",
            private=True,
            limit=16 * 1024 * 1024,
        )
    )
    private_findings = _collect_endpoint_node(
        private_values, source="private-input", key_hint=""
    )
    found.update(
        (host, "secret-derived-endpoint", "private-input")
        for host, _purpose, _source in private_findings
    )
    for document in documents:
        kind = str(document.get("kind", "unknown"))
        name = object_name(document) or "unnamed"
        if kind == "Secret":
            for field in ("data", "stringData"):
                values = document.get(field, {})
                if not isinstance(values, dict):
                    fail("rendered Secret endpoint data is malformed")
                for value in values.values():
                    if not isinstance(value, str):
                        fail("rendered Secret endpoint value is malformed")
                    decoded = value
                    if field == "data":
                        try:
                            decoded = base64.b64decode(value, validate=True).decode(
                                "utf-8"
                            )
                        except (ValueError, UnicodeDecodeError):
                            continue
                    private_findings = _collect_endpoint_node(
                        decoded, source="rendered-secret", key_hint="endpoint"
                    )
                    found.update(
                        (host, "secret-derived-endpoint", "rendered-secret")
                        for host, _purpose, _source in private_findings
                    )
            continue
        found.update(
            _collect_endpoint_node(
                document, source=f"rendered:{kind}/{name}", key_hint=""
            )
        )
    return [
        {"host": host, "purpose": purpose, "source": source}
        for host, purpose, source in sorted(found)
    ]


def luna_render_inventory(documents: list[dict], metadata: dict) -> dict:
    by_kind: dict[str, list[dict]] = {}
    for document in documents:
        kind = str(document.get("kind", ""))
        name = object_name(document)
        if not kind or not name:
            fail("Helm rendered a resource without kind/metadata.name")
        by_kind.setdefault(kind, []).append(document)
    backends = [
        item
        for item in by_kind.get("Deployment", [])
        if object_name(item) == "luna-studio-backend"
    ]
    uis = [
        item
        for item in by_kind.get("Deployment", [])
        if object_name(item) == "luna-studio"
    ]
    services = {object_name(item): item for item in by_kind.get("Service", [])}
    if (
        len(backends) != 1
        or len(uis) != 1
        or not {
            "luna-studio-backend",
            "luna-studio",
        }
        <= set(services)
    ):
        fail("Luna must render one backend/UI Deployment and both Services")
    for name in ("luna-studio-backend", "luna-studio"):
        ports = services[name].get("spec", {}).get("ports", [])
        if not isinstance(ports, list) or not any(
            isinstance(port, dict)
            and (port.get("port") == 80 or port.get("targetPort") == 80)
            for port in ports
        ):
            fail(f"Luna Service {name} must expose port 80")
    all_strings = strings(documents)
    for name, contract in metadata["secret_contracts"].items():
        if contract and contract["name"] not in all_strings:
            fail(f"Luna rendered resources omit Secret reference {name}")
    for required in (
        metadata["object_store"]["provider"],
        metadata["object_store"]["bucket"],
        metadata["routing"]["public_url"].rstrip("/"),
        metadata["training"]["provider"],
    ):
        if required not in all_strings:
            fail(f"Luna rendered resources omit reviewed value: {required}")
    resilience = metadata["resilience"]
    hpas = by_kind.get("HorizontalPodAutoscaler", [])
    pdbs = by_kind.get("PodDisruptionBudget", [])
    policies = by_kind.get("NetworkPolicy", [])
    for enabled, observed, label in (
        (resilience["hpa"], hpas, "HPA"),
        (resilience["pdb"], pdbs, "PDB"),
        (resilience["network_policy"], policies, "NetworkPolicy"),
    ):
        if enabled != bool(observed):
            fail(f"Luna rendered {label} outcome differs from reviewed values")
    route = metadata["routing"]
    routes = [
        item
        for kind in ("Ingress", "HTTPRoute", "VirtualService")
        for item in by_kind.get(kind, [])
    ]
    if route["mode"] == "customer" and routes:
        fail("customer-managed Luna routing unexpectedly rendered a chart route")
    expected_host = urlsplit(route["public_url"]).hostname
    if not expected_host:
        fail("Luna public URL has no hostname")
    if route["mode"] == "ingress":
        ingress = exact_single_route(routes, "Ingress", "Luna ingress mode")
        exact_ingress_tls(
            ingress, expected_host, route["tls_secret_name"], "Luna Ingress"
        )
    if route["mode"] == "gateway":
        http_route = exact_single_route(routes, "HTTPRoute", "Luna Gateway mode")
        exact_http_route_host(http_route, expected_host, "Luna HTTPRoute")
    training = metadata["training"]
    gpu_resource = training["gpu"]["resource"]
    gpu_pods = 0
    job_capable = 0
    for identity, pod in pod_specs(documents):
        containers = list(pod.get("initContainers", [])) + list(
            pod.get("containers", [])
        )
        requested_gpu = False
        for container in containers:
            resources = (
                container.get("resources", {}) if isinstance(container, dict) else {}
            )
            requests = (
                resources.get("requests", {}) if isinstance(resources, dict) else {}
            )
            limits = resources.get("limits", {}) if isinstance(resources, dict) else {}
            requested = requests.get(gpu_resource)
            limited = limits.get(gpu_resource)
            if requested is not None or limited is not None:
                if str(requested) != str(limited) or not str(requested).isdigit():
                    fail(f"{identity} GPU requests and limits must match")
                requested_gpu = int(str(requested)) > 0
        if identity.startswith(("Job/", "CronJob/")):
            job_capable += 1
        if requested_gpu:
            gpu_pods += 1
            if pod.get("nodeSelector") != training["gpu"]["node_selector"]:
                fail(f"{identity} GPU selector differs from reviewed values")
            if pod.get("tolerations", []) != training["gpu"]["tolerations"]:
                fail(f"{identity} GPU tolerations differ from reviewed values")
        elif identity in {"Deployment/luna-studio", "Deployment/luna-studio-backend"}:
            continue
    if training["provider"] == "kubernetes" and job_capable < 1:
        # Some releases generate Jobs dynamically; their controller/RBAC/config
        # must still contain the exact Job API identity.
        if not ({"jobs", "batch"} <= all_strings):
            fail("Kubernetes Luna training rendered no Job template/RBAC contract")
    if training["gpu"]["enabled"] != bool(gpu_pods):
        fail("Luna rendered GPU workload count differs from reviewed training mode")
    if not training["gpu"]["enabled"] and any(
        gpu_resource
        in {
            key
            for _, pod in pod_specs(documents)
            for container in list(pod.get("containers", []))
            if isinstance(container, dict)
            for section in ("requests", "limits")
            for key in container.get("resources", {}).get(section, {})
        }
        for _ in (0,)
    ):
        fail("CPU Luna profile rendered a GPU resource")
    resources = sorted(
        {f"{document.get('kind')}/{object_name(document)}" for document in documents}
    )
    return {
        "schema": "galileo-on-prem-luna-render-inventory/v1",
        "resources": resources,
        "backend": "Deployment/luna-studio-backend",
        "ui": "Deployment/luna-studio",
        "hpa": len(hpas),
        "pdb": len(pdbs),
        "network_policy": len(policies),
        "route_mode": route["mode"],
        "route_resources": sorted(
            f"{item.get('kind')}/{object_name(item)}" for item in routes
        ),
        "secret_names": sorted(
            contract["name"]
            for contract in metadata["secret_contracts"].values()
            if contract
        ),
        "training_provider": training["provider"],
        "gpu_workloads": gpu_pods,
    }


def server_dry_run(
    args: argparse.Namespace,
    metadata: dict,
    bundle: Path,
    secret_values: Path,
    chart_path: Path | None = None,
    value_paths: list[Path] | None = None,
) -> tuple[str, str, list[dict]]:
    if KUBECONFIG_SNAPSHOT is None:
        fail("kubeconfig snapshot is unavailable")
    helm = shutil.which("helm", path=command_env()["PATH"])
    kubectl = shutil.which("kubectl", path=command_env()["PATH"])
    if not helm or not kubectl:
        fail("Helm and kubectl are required")
    values = value_paths or [
        bundle / "values" / "base-values.yaml",
        bundle / "values" / "luna-studio-overlay.yaml",
        secret_values,
    ]
    chart_path = chart_path or bundle / "artifacts" / "luna-studio.tgz"
    helm_cmd = [
        helm,
        "--kubeconfig",
        KUBECONFIG_SNAPSHOT,
        "template",
        metadata["release_name"],
        str(chart_path),
        "--namespace",
        metadata["namespace"],
    ]
    if args.for_action != "install":
        helm_cmd.append("--is-upgrade")
    for value in values:
        helm_cmd += ["--values", str(value)]
    kubectl_cmd = [
        kubectl,
        "--kubeconfig",
        KUBECONFIG_SNAPSHOT,
        "--context",
        args.kube_context,
        "--namespace",
        metadata["namespace"],
        "apply",
        "--dry-run=server",
        "--validate=strict",
        "--output=yaml",
        "-f",
        "-",
    ]
    try:
        producer = subprocess.run(
            helm_cmd,
            env=command_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=900,
            check=False,
        )
        if producer.returncode or len(producer.stdout) > 128 * 1024 * 1024:
            fail("Helm template rejected the reviewed release or exceeded 128 MiB")
        consumer = subprocess.run(
            kubectl_cmd,
            env=command_env(),
            input=producer.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=900,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        fail("server-side rendered-resource preflight could not complete")
    if consumer.returncode:
        fail("Kubernetes server dry-run rejected the reviewed release")
    if len(consumer.stdout) > 128 * 1024 * 1024:
        fail("Kubernetes server dry-run output exceeded 128 MiB")
    # Bind evidence to the API-server/defaulting/admission result, not merely
    # Helm's client render.  The dry-run response remains in memory and every
    # scalar is redacted before its structural digest is persisted.
    documents = rendered_documents(consumer.stdout)
    inventory = luna_render_inventory(documents, metadata)
    inventory_sha256 = hashlib.sha256(
        json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return inventory_sha256, redacted_render_sha256(documents), documents


def write_new(raw: str, value: object) -> None:
    path = absolute(raw)
    if os.path.lexists(path):
        fail("evidence/plan path already exists")
    parent = path.parent
    if not parent.exists():
        if not parent.parent.is_dir() or parent.parent.is_symlink():
            fail("evidence parent cannot be created safely")
        try:
            os.mkdir(parent, 0o700)
        except OSError:
            fail("evidence parent cannot be created safely")
    info = os.lstat(parent)
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        fail("evidence parent must be current-user-owned mode 0700")
    cursor = parent
    while True:
        ancestor = os.lstat(cursor)
        if stat.S_ISLNK(ancestor.st_mode) or not stat.S_ISDIR(ancestor.st_mode):
            fail("evidence path has a symlink/non-directory ancestor")
        if cursor.parent == cursor:
            break
        cursor = cursor.parent
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0), 0o600
    )
    with os.fdopen(descriptor, "w") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def recent_evidence(
    raw: str, schema: str, metadata: dict, fields: dict[str, object]
) -> dict:
    evidence = private_json(raw, schema)
    exact_fields(
        evidence,
        {"schema", "bundle_sha256", "target", "tested_at", *fields},
        schema,
    )
    reject_credential_values(evidence, schema)
    if (
        evidence.get("schema") != schema
        or evidence.get("bundle_sha256") != metadata["bundle_sha256"]
        or not exact_value(evidence.get("target"), metadata["parent_stack"]["target"])
    ):
        fail(f"{schema} is not bound to this bundle/target")
    tested = timestamp(evidence.get("tested_at"))
    age = dt.datetime.now(UTC) - tested
    if age < dt.timedelta(minutes=-1) or age > dt.timedelta(hours=24):
        fail(f"{schema} is future-dated or older than 24 hours")
    for key, expected in fields.items():
        if not exact_value(evidence.get(key), expected):
            fail(f"{schema} does not prove {key}")
    return evidence


def tolerates(taint: dict, tolerations: list[dict]) -> bool:
    for item in tolerations:
        if item.get("key") != taint.get("key") or item.get("effect", "") not in {
            "",
            taint.get("effect"),
        }:
            continue
        if item.get("operator", "Equal") == "Exists" or item.get(
            "value", ""
        ) == taint.get("value", ""):
            return True
    return False


def gpu_target(context: str, namespace: str, training: dict) -> None:
    result = run(["kubectl", "--context", context, "get", "nodes", "-o", "json"])
    try:
        nodes = json.loads(result.stdout).get("items", [])
    except json.JSONDecodeError:
        fail("Kubernetes returned invalid node inventory")
    gpu = training["gpu"]
    selector = gpu["node_selector"]
    tolerations = gpu["tolerations"]
    for node in nodes:
        labels = node.get("metadata", {}).get("labels", {})
        alloc = node.get("status", {}).get("allocatable", {})
        ready = any(
            item.get("type") == "Ready" and item.get("status") == "True"
            for item in node.get("status", {}).get("conditions", [])
        )
        if not ready or any(labels.get(k) != v for k, v in selector.items()):
            continue
        try:
            capacity = int(alloc.get(gpu["resource"], "0"))
        except ValueError:
            capacity = 0
        taints = [
            x
            for x in node.get("spec", {}).get("taints", [])
            if x.get("effect") in {"NoSchedule", "NoExecute"}
        ]
        if capacity >= gpu["count"] and all(
            tolerates(item, tolerations) for item in taints
        ):
            return
    fail("no Ready node satisfies Luna GPU capacity, selector, and tolerations")


def preflight(args: argparse.Namespace, metadata: dict, bundle: Path) -> None:
    if metadata["ownership"] != "standalone":
        fail(
            "umbrella-overlay bundles must be applied only by the parent Stack executor"
        )
    live = target(args.kube_context, metadata["namespace"])
    if live != metadata["parent_stack"]["target"]:
        fail("live target differs from parent stack release contract")
    state = release(args.kube_context, metadata["namespace"], metadata["release_name"])
    if args.for_action == "install" and state is not None:
        fail("install requires an absent release")
    if args.for_action in {"rollback", "uninstall"}:
        release_identity(state, metadata)
    if args.for_action == "upgrade":
        current_version = state_version(state, "luna-studio")
        if semver(metadata["chart"]["version"]) <= semver(current_version):
            fail(
                "upgrade target must be newer than the live release; use rollback for downgrade"
            )
    if live["namespace_uid"] == "ABSENT":
        fail("parent stack namespace is absent")
    parent_state = require_parent_release(args.kube_context, metadata)
    for contract in metadata["secret_contracts"].values():
        if contract and set(contract["keys"]) - secret_keys(
            args.kube_context, metadata["namespace"], contract["name"]
        ):
            fail(f"Secret {contract['name']} is missing required keys")
    api = run(
        [
            "kubectl",
            "--context",
            args.kube_context,
            "--namespace",
            metadata["namespace"],
            "get",
            "deployment",
            "api",
            "-o",
            "jsonpath={.status.availableReplicas}",
        ],
        allow_failure=True,
    )
    if api.returncode or not api.stdout.strip() or int(api.stdout) < 1:
        fail("parent API deployment is unavailable")
    recent_evidence(
        args.database_evidence_file,
        "galileo-luna-database-evidence/v1",
        metadata,
        {
            "database_secret_name": metadata["secret_contracts"]["database"]["name"],
            "connected": True,
            "asyncpg": True,
            "migration_permissions": True,
        },
    )
    recent_evidence(
        args.storage_evidence_file,
        "galileo-luna-storage-evidence/v1",
        metadata,
        {
            "provider": metadata["object_store"]["provider"],
            "bucket": metadata["object_store"]["bucket"],
            "write_read_delete": True,
        },
    )
    training = metadata["training"]
    if training["provider"] == "vertex_ai":
        recent_evidence(
            args.vertex_evidence_file,
            "galileo-luna-vertex-evidence/v1",
            metadata,
            {
                "project_id": training["vertex_ai"]["project_id"],
                "pipeline_root": training["vertex_ai"]["pipeline_root"],
                "iam_and_egress_ready": True,
            },
        )
    else:
        gpu_context = (
            args.remote_kube_context if training["remote"] else args.kube_context
        )
        if training["remote"]:
            if not gpu_context:
                fail("remote training requires --remote-kube-context")
            remote_target = target(gpu_context, training["remote"]["namespace"])
            expected_remote = {
                key: training["remote"][key]
                for key in (
                    "api_server",
                    "ca_sha256",
                    "kube_system_uid",
                    "namespace_uid",
                )
            }
            actual_remote = {key: remote_target[key] for key in expected_remote}
            if (
                actual_remote != expected_remote
                or remote_target["namespace_uid"] == "ABSENT"
            ):
                fail(
                    "remote training target does not match its exact API/CA/cluster/namespace identity"
                )
            can_i = run(
                [
                    "kubectl",
                    "--context",
                    gpu_context,
                    "auth",
                    "can-i",
                    "create",
                    "jobs",
                    "--namespace",
                    training["remote"]["namespace"],
                ]
            )
            if can_i.stdout.strip() != "yes":
                fail("remote context cannot create training Jobs")
        else:
            can_i = run(
                [
                    "kubectl",
                    "--context",
                    gpu_context,
                    "auth",
                    "can-i",
                    "create",
                    "jobs",
                    "--namespace",
                    metadata["namespace"],
                ]
            )
            if can_i.stdout.strip() != "yes":
                fail("deployment context cannot create Luna training Jobs")
        if training["gpu"]["enabled"]:
            gpu_target(
                gpu_context,
                training["remote"]["namespace"]
                if training["remote"]
                else metadata["namespace"],
                training,
            )
    secret_values = secure_read(
        args.secret_values_file,
        "secret-values file",
        private=True,
        limit=16 * 1024 * 1024,
    )
    _secret_holder, secret_values_path, secret_input_contract = snapshot_secret_input(
        secret_values
    )
    selected = bundle
    previous_digest = None
    if args.for_action == "rollback":
        if not args.previous_bundle:
            fail("rollback preflight requires --previous-bundle")
        selected = absolute(args.previous_bundle)
        prior = validate_bundle(selected)
        if (
            prior["ownership"] != "standalone"
            or prior["namespace"] != metadata["namespace"]
            or prior["release_name"] != metadata["release_name"]
            or prior["parent_stack"]["target"] != metadata["parent_stack"]["target"]
            or prior["secret_contracts"] != metadata["secret_contracts"]
        ):
            fail(
                "previous bundle does not target the exact release/cluster/Secret contracts"
            )
        previous_digest = prior["bundle_sha256"]
    if args.for_action == "uninstall":
        render_inventory_digest = None
        redacted_render_digest = None
        rendered_images_digest = None
        image_evidence_digest = None
        rendered_endpoints_digest = None
        endpoint_evidence_digest = None
    else:
        selected_metadata = validate_bundle(selected)
        (
            render_inventory_digest,
            redacted_render_digest,
            rendered_documents_value,
        ) = server_dry_run(args, selected_metadata, selected, secret_values_path)
    now = dt.datetime.now(UTC).replace(microsecond=0)
    if args.for_action != "uninstall" and args.image_evidence_file:
        rendered_images = rendered_image_items(
            rendered_documents_value,
            selected_metadata["release_name"],
            live_nodes(args.kube_context),
        )
        rendered_images_digest = hashlib.sha256(
            json.dumps(rendered_images, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        image_payload = {
            "schema": "galileo-on-prem-child-rendered-image-inventory/v1",
            "generated_by": "galileo-on-prem-luna-studio-setup",
            "component": "luna-studio",
            "source_bundle_sha256": selected_metadata["bundle_sha256"],
            "parent_stack_bundle_sha256": selected_metadata["parent_stack"][
                "bundle_sha256"
            ],
            "chart": {
                "name": selected_metadata["chart"]["name"],
                "release": selected_metadata["release_name"],
                "version": selected_metadata["chart"]["version"],
                "sha256": selected_metadata["chart"]["sha256"],
            },
            "inputs": {
                "base_values_sha256": selected_metadata["base_values_sha256"],
                "overlay_values_sha256": secure_read(
                    selected / "values" / "luna-studio-overlay.yaml",
                    "Luna Studio overlay",
                ).sha256,
                "secret_input_contract": secret_input_contract,
            },
            "render_inventory_sha256": render_inventory_digest,
            "redacted_render_sha256": redacted_render_digest,
            "target": live,
            "created_at": now.isoformat().replace("+00:00", "Z"),
            "items": rendered_images,
        }
        image_evidence_bytes = (
            json.dumps(image_payload, indent=2, sort_keys=True) + "\n"
        ).encode()
        image_evidence_digest = hashlib.sha256(image_evidence_bytes).hexdigest()
        write_new(args.image_evidence_file, image_payload)
    elif args.for_action != "uninstall":
        rendered_images_digest = None
        image_evidence_digest = None
    if args.for_action != "uninstall" and args.endpoint_evidence_file:
        rendered_endpoints = rendered_endpoint_items(
            rendered_documents_value,
            selected / "artifacts" / "luna-studio.tgz",
            [
                selected / "values" / "base-values.yaml",
                selected / "values" / "luna-studio-overlay.yaml",
            ],
            secret_values_path,
        )
        rendered_endpoints_digest = hashlib.sha256(
            json.dumps(
                rendered_endpoints, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        endpoint_payload = {
            "schema": "galileo-on-prem-child-rendered-endpoint-inventory/v1",
            "generated_by": "galileo-on-prem-luna-studio-setup",
            "component": "luna-studio",
            "source_bundle_sha256": selected_metadata["bundle_sha256"],
            "parent_stack_bundle_sha256": selected_metadata["parent_stack"][
                "bundle_sha256"
            ],
            "chart": {
                "name": selected_metadata["chart"]["name"],
                "release": selected_metadata["release_name"],
                "version": selected_metadata["chart"]["version"],
                "sha256": selected_metadata["chart"]["sha256"],
            },
            "inputs": {
                "base_values_sha256": selected_metadata["base_values_sha256"],
                "overlay_values_sha256": secure_read(
                    selected / "values" / "luna-studio-overlay.yaml",
                    "Luna Studio overlay",
                ).sha256,
                "secret_input_contract": secret_input_contract,
            },
            "render_inventory_sha256": render_inventory_digest,
            "redacted_render_sha256": redacted_render_digest,
            "target": live,
            "created_at": now.isoformat().replace("+00:00", "Z"),
            "items": rendered_endpoints,
        }
        endpoint_evidence_digest = hashlib.sha256(
            (json.dumps(endpoint_payload, indent=2, sort_keys=True) + "\n").encode()
        ).hexdigest()
        write_new(args.endpoint_evidence_file, endpoint_payload)
    elif args.for_action != "uninstall":
        rendered_endpoints_digest = None
        endpoint_evidence_digest = None
    payload = {
        "schema": "galileo-on-prem-preflight-evidence/v1",
        "component": "luna-studio",
        "action": args.for_action,
        "bundle_sha256": metadata["bundle_sha256"],
        "target": live,
        "release": metadata["release_name"],
        "namespace": metadata["namespace"],
        "release_state": state,
        "parent_release_state": parent_state,
        "secret_input_contract": secret_input_contract,
        "render_inventory_sha256": render_inventory_digest,
        "redacted_render_sha256": redacted_render_digest,
        "rendered_images_sha256": rendered_images_digest,
        "image_evidence_sha256": image_evidence_digest,
        "rendered_endpoints_sha256": rendered_endpoints_digest,
        "endpoint_evidence_sha256": endpoint_evidence_digest,
        "previous_bundle_sha256": previous_digest,
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": (now + dt.timedelta(minutes=args.ttl_minutes))
        .isoformat()
        .replace("+00:00", "Z"),
    }
    write_new(args.evidence_file, payload)
    print(
        json.dumps(
            {
                "status": "preflight-passed",
                "action": args.for_action,
                "evidence_file": args.evidence_file,
            },
            sort_keys=True,
        )
    )


def gates(
    args: argparse.Namespace, metadata: dict, mode: str
) -> tuple[dict, Path, dict, str]:
    evidence, evidence_artifact = private_json_bound(
        args.evidence_file, "preflight evidence"
    )
    if (
        evidence_artifact.data
        != (json.dumps(evidence, indent=2, sort_keys=True) + "\n").encode()
    ):
        fail("preflight evidence is not canonical JSON")
    evidence_sha256 = evidence_artifact.sha256
    action = mode.removeprefix("apply-")
    exact_fields(
        evidence,
        {
            "schema",
            "component",
            "action",
            "bundle_sha256",
            "target",
            "release",
            "namespace",
            "release_state",
            "parent_release_state",
            "secret_input_contract",
            "render_inventory_sha256",
            "redacted_render_sha256",
            "rendered_images_sha256",
            "image_evidence_sha256",
            "rendered_endpoints_sha256",
            "endpoint_evidence_sha256",
            "previous_bundle_sha256",
            "created_at",
            "expires_at",
        },
        "preflight evidence",
    )
    if (
        evidence.get("schema") != "galileo-on-prem-preflight-evidence/v1"
        or evidence.get("component") != "luna-studio"
        or evidence.get("action") != action
        or evidence.get("bundle_sha256") != metadata["bundle_sha256"]
    ):
        fail("preflight evidence is for another action/bundle")
    created = timestamp(evidence.get("created_at"))
    expires = timestamp(evidence.get("expires_at"))
    now = dt.datetime.now(UTC)
    if (
        evidence.get("release") != metadata["release_name"]
        or evidence.get("namespace") != metadata["namespace"]
        or created > now + dt.timedelta(minutes=1)
        or expires <= now
        or expires - created > dt.timedelta(minutes=30)
        or not exact_value(
            evidence.get("target"), target(args.kube_context, metadata["namespace"])
        )
        or not exact_value(evidence.get("target"), metadata["parent_stack"]["target"])
    ):
        fail("preflight lifetime/target/release binding is invalid")
    secret_values = secure_read(
        args.secret_values_file,
        "secret-values file",
        private=True,
        limit=16 * 1024 * 1024,
    )
    if not exact_value(
        evidence.get("secret_input_contract"),
        redacted_secret_input_contract(secret_values.data),
    ):
        fail("secret-values redacted input contract drifted")
    live_parent = require_parent_release(args.kube_context, metadata)
    if not exact_value(evidence.get("parent_release_state"), live_parent):
        fail("parent Stack release changed or preflight evidence names another object")
    live_release = release(
        args.kube_context, metadata["namespace"], metadata["release_name"]
    )
    if not exact_value(evidence.get("release_state"), live_release):
        fail("child release changed or preflight evidence names another object")
    if action == "install" and live_release is not None:
        fail("install preflight no longer describes an absent release")
    if action != "install" and live_release is None:
        fail(f"{action} preflight no longer describes an existing release")
    if action == "rollback":
        if not args.previous_bundle:
            fail("rollback requires --previous-bundle")
        prior_path = absolute(args.previous_bundle)
        prior = validate_bundle(prior_path)
        if evidence.get("previous_bundle_sha256") != prior["bundle_sha256"]:
            fail("rollback preflight is not bound to the selected previous bundle")
    if action != "rollback" and evidence.get("previous_bundle_sha256") is not None:
        fail("non-rollback preflight contains a previous-bundle binding")
    inventory_digest = evidence.get("render_inventory_sha256")
    if action != "uninstall" and (
        not isinstance(inventory_digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", inventory_digest)
    ):
        fail("preflight rendered-resource inventory binding is invalid")
    if action == "uninstall" and inventory_digest is not None:
        fail("uninstall evidence unexpectedly contains a render inventory")
    redacted_render_digest = evidence.get("redacted_render_sha256")
    if action != "uninstall" and (
        not isinstance(redacted_render_digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", redacted_render_digest)
    ):
        fail("preflight redacted render binding is invalid")
    if action == "uninstall" and redacted_render_digest is not None:
        fail("uninstall evidence unexpectedly contains a redacted render binding")
    for key in (
        "rendered_images_sha256",
        "image_evidence_sha256",
        "rendered_endpoints_sha256",
        "endpoint_evidence_sha256",
    ):
        value = evidence.get(key)
        if value is not None and (
            not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
        ):
            fail(f"preflight {key} binding is invalid")
    if (evidence.get("rendered_images_sha256") is None) != (
        evidence.get("image_evidence_sha256") is None
    ):
        fail("preflight child image-evidence bindings are incomplete")
    if (evidence.get("rendered_endpoints_sha256") is None) != (
        evidence.get("endpoint_evidence_sha256") is None
    ):
        fail("preflight child endpoint-evidence bindings are incomplete")
    if action != "uninstall" and evidence.get("rendered_images_sha256") is None:
        fail("preflight lacks mandatory child image-evidence bindings")
    if action != "uninstall" and evidence.get("rendered_endpoints_sha256") is None:
        fail("preflight lacks mandatory child endpoint-evidence bindings")
    approval = private_json(args.approval_file, "approval attestation")
    approval_fields = {
        "schema",
        "component",
        "action",
        "bundle_sha256",
        "release",
        "namespace",
        "target",
        "issued_at",
        "expires_at",
        "approver",
        "reference",
        "preflight_sha256",
    }
    if action in {"upgrade", "rollback", "uninstall"}:
        approval_fields.update({"backup_reference", "release_notes_reference"})
    if action == "upgrade":
        approval_fields.update({"from_version", "to_version"})
    if action == "rollback":
        approval_fields.update({"previous_bundle_sha256", "migration_compatible"})
    if metadata["environment"] == "production":
        approval_fields.update(
            {"cse_approved", "joint_session_confirmed", "cse_reference"}
        )
    exact_fields(approval, approval_fields, "approval attestation")
    expected = {
        "schema": "galileo-on-prem-approval/v1",
        "component": "luna-studio",
        "action": action,
        "bundle_sha256": metadata["bundle_sha256"],
        "release": metadata["release_name"],
        "namespace": metadata["namespace"],
        "target": evidence["target"],
    }
    for key, value in expected.items():
        if approval.get(key) != value:
            fail(f"approval does not bind {key}")
    require_approval_preflight_binding(approval, evidence, evidence_sha256)
    if timestamp(approval.get("expires_at")) <= dt.datetime.now(UTC):
        fail("approval expired")
    issued = timestamp(approval.get("issued_at"))
    expires = timestamp(approval.get("expires_at"))
    now = dt.datetime.now(UTC)
    if (
        issued > now + dt.timedelta(minutes=1)
        or expires <= now
        or expires - issued > dt.timedelta(hours=4)
    ):
        fail("approval lifetime is invalid")
    for key in ("approver", "reference"):
        safe_human_text(approval.get(key), f"approval.{key}")
    if action in {"upgrade", "rollback", "uninstall"}:
        for key in ("backup_reference", "release_notes_reference"):
            safe_human_text(approval.get(key), f"approval.{key}")
    if action == "upgrade":
        current_state = evidence.get("release_state")
        if not isinstance(current_state, dict):
            fail("upgrade evidence lacks current release")
        if (
            approval.get("from_version") != state_version(current_state, "luna-studio")
            or approval.get("to_version") != metadata["chart"]["version"]
        ):
            fail("upgrade approval must bind exact from_version and to_version")
    if metadata["environment"] == "production":
        if (
            approval.get("cse_approved") is not True
            or approval.get("joint_session_confirmed") is not True
            or approval.get("cse_reference") != metadata["cse_reference"]
        ):
            fail(
                "production approval requires exact Galileo CSE approval and confirmed joint session"
            )
    return approval, secret_values.path, evidence, evidence_sha256


def helm_environment() -> tuple[dict[str, str], tempfile.TemporaryDirectory[str]]:
    holder = tempfile.TemporaryDirectory(prefix="galileo-helm-action-")
    return command_env(), holder


def snapshot_inputs(
    selected: Path, secret_values: Path
) -> tuple[tempfile.TemporaryDirectory[str], Path, list[Path]]:
    holder = tempfile.TemporaryDirectory(prefix="galileo-luna-action-inputs-")
    root = Path(holder.name)
    root.chmod(0o700)
    sources = [
        selected / "artifacts" / "luna-studio.tgz",
        selected / "values" / "base-values.yaml",
        selected / "values" / "luna-studio-overlay.yaml",
        secret_values,
    ]
    destinations = [
        root / "chart.tgz",
        root / "base-values.yaml",
        root / "overlay.yaml",
        root / "secret-values.yaml",
    ]
    for source, destination in zip(sources, destinations, strict=True):
        artifact = secure_read(
            source,
            "action input",
            private=source == secret_values,
            limit=512 * 1024 * 1024,
        )
        descriptor = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        try:
            view = memoryview(artifact.data)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    return holder, destinations[0], destinations[1:]


def apply(args: argparse.Namespace, metadata: dict, bundle: Path, mode: str) -> None:
    fail(
        f"{mode} is handoff-only: this skill performs no Helm or Kubernetes "
        "mutation; use the exact immutable bundle, lifecycle.json, and fresh "
        "preflight/image/endpoint evidence in a Galileo/CSE joint session"
    )


def plan(args: argparse.Namespace, metadata: dict, kind: str) -> None:
    value = {
        "schema": f"galileo-on-prem-{kind}-plan/v1",
        "component": "luna-studio",
        "bundle_sha256": metadata["bundle_sha256"],
        "release": metadata["release_name"],
        "namespace": metadata["namespace"],
        "target": metadata["parent_stack"]["target"],
        "automatic": False,
        "requirements": (
            [
                "previous bundle",
                "database backup",
                "object-store retention",
                "migration compatibility",
                "release notes",
                "approval",
            ]
            if kind == "rollback"
            else [
                "database backup",
                "object-store retention",
                "typed confirmation",
                "approval",
            ]
        ),
    }
    if kind == "uninstall":
        value["blocked_by_chart_delete_risk"] = metadata["chart_has_delete_risk"]
    write_new(args.plan_file, value)
    print(
        json.dumps(
            {"status": "planned", "action": kind, "plan_file": args.plan_file},
            sort_keys=True,
        )
    )


def uninstall(args: argparse.Namespace, metadata: dict) -> None:
    fail(
        "automated Luna Studio uninstall is disabled because chart/CR/finalizer deletion side effects cannot be proven safe; use the retention-first manual plan with Galileo"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Gated Luna Studio lifecycle")
    modes = parser.add_mutually_exclusive_group(required=True)
    names = (
        "preflight",
        "apply-install",
        "apply-upgrade",
        "status",
        "plan-rollback",
        "apply-rollback",
        "plan-uninstall",
        "apply-uninstall",
    )
    for name in names:
        modes.add_argument(f"--{name}", action="store_true")
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--kube-context", required=True)
    parser.add_argument("--kubeconfig", required=True)
    parser.add_argument(
        "--galileo-console-url",
        required=True,
        help="Exact Galileo instance console URL bound to bundle",
    )
    parser.add_argument(
        "--for-action", choices=("install", "upgrade", "rollback", "uninstall")
    )
    parser.add_argument("--evidence-file")
    parser.add_argument(
        "--image-evidence-file",
        help="New private canonical digest-pinned image evidence for air-gap handoff",
    )
    parser.add_argument(
        "--endpoint-evidence-file",
        help="New private canonical host-only endpoint evidence for air-gap handoff",
    )
    parser.add_argument("--ttl-minutes", type=int, default=30)
    parser.add_argument("--secret-values-file")
    parser.add_argument("--approval-file")
    parser.add_argument("--database-evidence-file")
    parser.add_argument("--storage-evidence-file")
    parser.add_argument("--vertex-evidence-file")
    parser.add_argument("--remote-kube-context")
    parser.add_argument("--previous-bundle")
    parser.add_argument("--plan-file")
    parser.add_argument("--retention-file")
    parser.add_argument("--confirm-target")
    parser.add_argument("--accept-luna-studio-install", action="store_true")
    parser.add_argument("--accept-luna-studio-upgrade", action="store_true")
    parser.add_argument("--accept-luna-studio-rollback", action="store_true")
    parser.add_argument("--accept-luna-studio-uninstall", action="store_true")
    args = parser.parse_args()
    mode = next(name for name in names if getattr(args, name.replace("-", "_")))
    if mode.startswith("apply-"):
        fail(
            f"{mode} is handoff-only: this skill performs no Helm or Kubernetes "
            "mutation; use the exact immutable bundle, lifecycle.json, and fresh "
            "preflight/image/endpoint evidence in a Galileo/CSE joint session"
        )
    runtime = prepare_runtime(args.kubeconfig)
    bundle = absolute(args.bundle)
    metadata = validate_bundle(bundle)
    if origin(args.galileo_console_url) != metadata["galileo_console_url"]:
        fail("Galileo instance console URL does not match the bundle")
    if mode == "preflight":
        required = [
            args.for_action,
            args.evidence_file,
            args.secret_values_file,
            args.database_evidence_file,
            args.storage_evidence_file,
        ]
        if not all(required):
            fail(
                "preflight requires action, evidence, secret-values, database-evidence, and storage-evidence files"
            )
        if args.for_action != "uninstall" and not args.image_evidence_file:
            fail("non-uninstall preflight requires --image-evidence-file")
        if args.for_action != "uninstall" and not args.endpoint_evidence_file:
            fail("non-uninstall preflight requires --endpoint-evidence-file")
        if (
            metadata["training"]["provider"] == "vertex_ai"
            and not args.vertex_evidence_file
        ):
            fail("Vertex AI preflight requires --vertex-evidence-file")
        if not 1 <= args.ttl_minutes <= 30:
            fail("preflight TTL must be 1-30 minutes")
        preflight(args, metadata, bundle)
    elif mode == "status":
        if (
            target(args.kube_context, metadata["namespace"])
            != metadata["parent_stack"]["target"]
        ):
            fail("status target does not match the bundle")
        require_parent_release(args.kube_context, metadata)
        state = release(
            args.kube_context, metadata["namespace"], metadata["release_name"]
        )
        validate_observed_release_ownership(state, metadata)
        print(
            json.dumps({"status": "observed", "release_state": state}, sort_keys=True)
        )
    elif mode in {"plan-rollback", "plan-uninstall"}:
        if not args.plan_file:
            fail(f"{mode} requires --plan-file")
        plan(args, metadata, mode.removeprefix("plan-"))
    elif mode == "apply-uninstall":
        if not all(
            (
                args.evidence_file,
                args.secret_values_file,
                args.approval_file,
                args.retention_file,
                args.confirm_target,
            )
        ):
            fail("apply-uninstall is missing a required gate")
        uninstall(args, metadata)
    else:
        if not all((args.evidence_file, args.secret_values_file, args.approval_file)):
            fail(f"{mode} is missing evidence/approval inputs")
        apply(args, metadata, bundle, mode)
    runtime.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

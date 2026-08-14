#!/usr/bin/env python3
"""Gated Agent Control lifecycle executor; never emits Helm or Secret bodies."""
# ruff: noqa: E402

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
from render_bundle import (
    fail,
    load_yaml_or_json,
    mapping_from_input,
    secure_read,
    validate_bundle,
    validate_url,
)  # noqa: E402

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
KUBERNETES_ARCHITECTURES = {"amd64", "arm64", "ppc64le", "s390x"}
SECRET_PATH_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def absolute(raw: str) -> Path:
    return Path(os.path.abspath(Path(raw).expanduser()))


def parse_time(value: object) -> dt.datetime:
    if not isinstance(value, str):
        fail("attestation timestamp must be a string")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        fail("attestation timestamp is not ISO-8601")
    if parsed.tzinfo is None:
        fail("attestation timestamp requires a timezone")
    return parsed.astimezone(UTC)


def private_json_bound(raw: str, label: str):
    artifact = secure_read(raw, label, private=True, max_bytes=1024 * 1024)

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
        fail(f"{label} is not valid duplicate-free JSON")
    if not isinstance(value, dict):
        fail(f"{label} must contain an object")
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
        or parse_time(approval.get("issued_at"))
        < parse_time(evidence.get("created_at"))
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
        or re.search(
            r"(?i)(?:bearer\s+\S+|(?:password|passwd|token|api[_-]?key|secret|credential)\s*[:=]\s*\S+|-----BEGIN [A-Z ]*PRIVATE KEY-----|https?://[^/@\s:]+:[^/@\s]+@)",
            value,
        )
    ):
        fail(f"{label} must be nonempty credential-free text")
    return value.strip()


def command_env() -> dict[str, str]:
    if RUNTIME_ENV is None:
        fail("private command runtime is not initialized")
    return dict(RUNTIME_ENV)


def prepare_runtime(raw: str) -> tempfile.TemporaryDirectory[str]:
    global KUBECONFIG_SNAPSHOT, RUNTIME_ENV
    source = secure_read(raw, "kubeconfig", private=True, max_bytes=4 * 1024 * 1024)
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
            f"{Path(argv[0]).name} operation failed; use an approved redacted support workflow for details"
        )
    return result


def tools() -> None:
    missing = [
        name
        for name in ("kubectl", "helm")
        if shutil.which(name, path=command_env()["PATH"]) is None
    ]
    if missing:
        fail("missing required executable(s): " + ", ".join(missing))


def target(context: str, namespace: str) -> dict:
    tools()
    if KUBECONFIG_SNAPSHOT is None:
        fail("kubeconfig snapshot is unavailable")
    config = mapping_from_input(
        secure_read(
            KUBECONFIG_SNAPSHOT,
            "kubeconfig snapshot",
            private=True,
            max_bytes=4 * 1024 * 1024,
        )
    )
    contexts = config.get("contexts", [])
    clusters = config.get("clusters", [])
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
    users = config.get("users", [])
    user_matches = [
        item
        for item in users
        if isinstance(item, dict) and item.get("name") == user_name
    ]
    if user_name and len(user_matches) != 1:
        fail("explicit kube context does not resolve one user")
    if user_matches:
        auth = user_matches[0].get("user", {})
        if (
            auth.get("client-certificate")
            or auth.get("client-key")
            or auth.get("tokenFile")
        ):
            fail(
                "kubeconfig authentication file references are forbidden; embed the credential material"
            )
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
    ):
        fail("Kubernetes API server must use HTTPS")
    if (
        "insecure-skip-tls-verify" in cluster
        and cluster.get("insecure-skip-tls-verify") is not False
    ):
        fail("insecure Kubernetes TLS is forbidden")
    ca_data = cluster.get("certificate-authority-data")
    if (
        cluster.get("certificate-authority")
        or not isinstance(ca_data, str)
        or not ca_data
    ):
        fail(
            "kubeconfig must embed certificate-authority-data; path references are forbidden"
        )
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
    ns_uid = (
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
        "namespace_uid": ns_uid,
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


def require_release_identity(state: dict | None, metadata: dict) -> None:
    if state is None:
        fail("expected release does not exist")
    chart = metadata.get("chart")
    if not isinstance(chart, dict):
        fail("standalone bundle has no chart identity")
    if (
        state.get("namespace") != metadata["namespace"]
        or state.get("chart") != f"agent-control-{chart['version']}"
        or str(state.get("app_version", "")) != str(chart["app_version"])
    ):
        fail("existing release chart/version does not match the immutable bundle")


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
    return {line for line in result.stdout.splitlines() if line}


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
        path, "secret-values snapshot", private=True, max_bytes=16 * 1024 * 1024
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
    """Return the exact digest-pinned workload, hook, init, job, and test images."""
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
    if not HOSTPORT.fullmatch(hostport):
        return None
    return hostport


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
            child_path = f"{path}.{key}"
            found.update(
                _collect_endpoint_node(
                    value,
                    source=source,
                    path=child_path,
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
        value = mapping_from_input(secure_read(value_path, "endpoint-evidence values"))
        found.update(
            _collect_endpoint_node(
                value, source=f"values:{value_path.name}", key_hint=""
            )
        )
    private_values = mapping_from_input(
        secure_read(
            secret_values,
            "endpoint-evidence secret values",
            private=True,
            max_bytes=16 * 1024 * 1024,
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
                        decoded,
                        source="rendered-secret",
                        key_hint="endpoint",
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


def agent_control_render_inventory(documents: list[dict], metadata: dict) -> dict:
    by_kind: dict[str, list[dict]] = {}
    for document in documents:
        kind = str(document.get("kind", ""))
        name = object_name(document)
        if not kind or not name:
            fail("Helm rendered a resource without kind/metadata.name")
        by_kind.setdefault(kind, []).append(document)
    deployments = [
        item
        for item in by_kind.get("Deployment", [])
        if object_name(item) == "agent-control"
    ]
    services = [
        item
        for item in by_kind.get("Service", [])
        if object_name(item) == "agent-control"
    ]
    if len(deployments) != 1 or len(services) != 1:
        fail("Agent Control must render one exact Deployment and Service")
    deployment = deployments[0]
    pod = deployment.get("spec", {}).get("template", {}).get("spec", {})
    containers = pod.get("containers", []) if isinstance(pod, dict) else []
    if not isinstance(containers, list) or not containers:
        fail("Agent Control Deployment rendered no containers")
    service_ports = services[0].get("spec", {}).get("ports", [])
    if not isinstance(service_ports, list) or not any(
        isinstance(port, dict)
        and (port.get("port") == 8000 or port.get("targetPort") == 8000)
        for port in service_ports
    ):
        fail("Agent Control Service must expose port 8000")
    resilience = metadata["resilience"]
    hpas = [
        item
        for item in by_kind.get("HorizontalPodAutoscaler", [])
        if item.get("spec", {}).get("scaleTargetRef", {}).get("name") == "agent-control"
    ]
    pdbs = [
        item
        for item in by_kind.get("PodDisruptionBudget", [])
        if "agent-control" in object_name(item)
    ]
    policies = [
        item
        for item in by_kind.get("NetworkPolicy", [])
        if "agent-control" in object_name(item)
    ]
    for enabled, observed, label in (
        (resilience["hpa"], hpas, "HPA"),
        (resilience["pdb"], pdbs, "PDB"),
        (resilience["network_policy"], policies, "NetworkPolicy"),
    ):
        if enabled != bool(observed):
            fail(f"Agent Control rendered {label} outcome differs from reviewed values")
    replicas = deployment.get("spec", {}).get("replicas", 1)
    if not isinstance(replicas, int) or replicas < 1:
        fail("Agent Control Deployment replicas must be a positive integer")
    if metadata["environment"] == "production":
        if not all(
            isinstance(container, dict)
            and all(
                isinstance(container.get("resources", {}).get(section), dict)
                and all(
                    key in container["resources"][section] for key in ("cpu", "memory")
                )
                for section in ("requests", "limits")
            )
            for container in containers
        ):
            fail(
                "production Agent Control containers require CPU/memory requests and limits"
            )
        minimum = min(
            [replicas]
            + [
                item.get("spec", {}).get("minReplicas", 1)
                for item in hpas
                if isinstance(item.get("spec", {}).get("minReplicas", 1), int)
            ]
        )
        if minimum < 2:
            fail("production Agent Control requires at least two replicas/minReplicas")
    routing = metadata["routing"]
    routes = [
        item
        for kind in ("Ingress", "HTTPRoute", "VirtualService")
        for item in by_kind.get(kind, [])
    ]
    if routing["mode"] in {"none", "customer"} and routes:
        fail("Agent Control rendered an in-chart route for an external/no-route mode")
    if routing["mode"] == "nginx":
        ingress = exact_single_route(routes, "Ingress", "NGINX Agent Control mode")
        expected_host = urlsplit(routing["external_url"]).hostname
        if not expected_host:
            fail("Agent Control external URL has no hostname")
        exact_ingress_tls(
            ingress, expected_host, routing["tls_secret_name"], "Agent Control Ingress"
        )
    if routing["mode"] == "gateway":
        route = exact_single_route(routes, "HTTPRoute", "Agent Control Gateway mode")
        expected_host = urlsplit(routing["external_url"]).hostname
        if not expected_host:
            fail("Agent Control external URL has no hostname")
        exact_http_route_host(route, expected_host, "Agent Control HTTPRoute")
    all_strings = strings(documents)
    if (
        metadata["feature_flag"]["source"] == "helm-env"
        and not {
            "GALILEO_FEATURE_FLAG_AGENT_CONTROL",
            "enabled",
        }
        <= all_strings
    ):
        fail("Helm-env Agent Control feature flag did not render")
    resources = sorted(
        {f"{document.get('kind')}/{object_name(document)}" for document in documents}
    )
    return {
        "schema": "galileo-on-prem-agent-control-render-inventory/v1",
        "resources": resources,
        "deployment": "Deployment/agent-control",
        "service": "Service/agent-control:8000",
        "replicas": replicas,
        "hpa": len(hpas),
        "pdb": len(pdbs),
        "network_policy": len(policies),
        "route_mode": routing["mode"],
        "route_resources": sorted(
            f"{item.get('kind')}/{object_name(item)}" for item in routes
        ),
        "feature_flag_source": metadata["feature_flag"]["source"],
        "ui_proxy_handoff_required": metadata["routing"]["ui_proxy_enabled"],
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
        bundle / "values" / "agent-control-overlay.yaml",
        secret_values,
    ]
    chart_path = chart_path or bundle / "artifacts" / "agent-control.tgz"
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
    inventory = agent_control_render_inventory(documents, metadata)
    inventory_sha256 = hashlib.sha256(
        json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return inventory_sha256, redacted_render_sha256(documents), documents


def new_private_json(raw: str, payload: object) -> None:
    path = absolute(raw)
    if os.path.lexists(path):
        fail("evidence/plan path already exists")
    parent = path.parent
    if not parent.exists():
        grandparent = parent.parent
        if not grandparent.is_dir() or grandparent.is_symlink():
            fail("evidence parent cannot be created safely")
        try:
            os.mkdir(parent, 0o700)
        except OSError:
            fail("evidence parent could not be created safely")
    info = os.lstat(parent)
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        fail("evidence parent must be a current-user-owned real directory mode 0700")
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
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def do_preflight(args: argparse.Namespace, metadata: dict, bundle: Path) -> None:
    action = args.for_action
    if metadata["ownership"] != "standalone":
        fail(
            "umbrella-overlay bundles must be applied only by the parent Stack executor"
        )
    target_id = target(args.kube_context, metadata["namespace"])
    if target_id != metadata["parent_stack"]["target"]:
        fail(
            "live Kubernetes identity does not match the parent stack release contract"
        )
    state = release(args.kube_context, metadata["namespace"], metadata["release_name"])
    if action == "install" and state is not None:
        fail("install requires an absent release")
    if action != "install" and state is None:
        fail(f"{action} requires an existing release")
    if action in {"rollback", "uninstall"}:
        require_release_identity(state, metadata)
    if action == "upgrade":
        current_version = state_version(state, "agent-control")
        target_version = metadata["chart"]["version"]
        if semver(target_version) <= semver(current_version):
            fail(
                "upgrade target must be newer than the live release; use rollback for a downgrade"
            )
    if target_id["namespace_uid"] == "ABSENT":
        fail("the parent stack namespace must already exist")
    parent_state = require_parent_release(args.kube_context, metadata)
    contract = metadata["secret_contract"]
    postgres = contract["postgres"]
    if {postgres["user_key"], postgres["password_key"]} - secret_keys(
        args.kube_context, metadata["namespace"], postgres["name"]
    ):
        fail("PostgreSQL Secret is missing required keys")
    if contract["runtime_auth_enabled"]:
        api = contract["api"]
        if api["key"] not in secret_keys(
            args.kube_context, metadata["namespace"], api["name"]
        ):
            fail("API Secret is missing its required key")
    for name in ("api", "authz"):
        probe = run(
            [
                "kubectl",
                "--context",
                args.kube_context,
                "--namespace",
                metadata["namespace"],
                "get",
                "deployment",
                name,
                "-o",
                "jsonpath={.status.availableReplicas}",
            ],
            allow_failure=True,
        )
        try:
            available = int(probe.stdout.strip()) if probe.returncode == 0 else 0
        except ValueError:
            available = 0
        if available < 1:
            fail(f"required parent deployment is unavailable: {name}")
    secret_values = secure_read(
        args.secret_values_file,
        "secret-values file",
        private=True,
        max_bytes=16 * 1024 * 1024,
    )
    _secret_holder, secret_values_path, secret_input_contract = snapshot_secret_input(
        secret_values
    )
    selected = bundle
    previous_digest = None
    if action == "rollback":
        if not args.previous_bundle:
            fail("rollback preflight requires --previous-bundle")
        selected = absolute(args.previous_bundle)
        prior = validate_bundle(selected)
        if (
            prior["ownership"] != "standalone"
            or prior["namespace"] != metadata["namespace"]
            or prior["release_name"] != metadata["release_name"]
            or prior["parent_stack"]["target"] != metadata["parent_stack"]["target"]
            or prior["secret_contract"] != metadata["secret_contract"]
        ):
            fail(
                "previous bundle does not target the exact release/cluster/Secret contracts"
            )
        previous_digest = prior["bundle_sha256"]
    if action == "uninstall":
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
    if action != "uninstall" and args.image_evidence_file:
        rendered_images = rendered_image_items(
            rendered_documents_value,
            metadata["release_name"],
            live_nodes(args.kube_context),
        )
        rendered_images_digest = hashlib.sha256(
            json.dumps(rendered_images, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        image_payload = {
            "schema": "galileo-on-prem-child-rendered-image-inventory/v1",
            "generated_by": "galileo-on-prem-agent-control-setup",
            "component": "agent-control",
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
                    selected / "values" / "agent-control-overlay.yaml",
                    "Agent Control overlay",
                ).sha256,
                "secret_input_contract": secret_input_contract,
            },
            "render_inventory_sha256": render_inventory_digest,
            "redacted_render_sha256": redacted_render_digest,
            "target": target_id,
            "created_at": now.isoformat().replace("+00:00", "Z"),
            "items": rendered_images,
        }
        image_evidence_bytes = (
            json.dumps(image_payload, indent=2, sort_keys=True) + "\n"
        ).encode()
        image_evidence_digest = hashlib.sha256(image_evidence_bytes).hexdigest()
        new_private_json(args.image_evidence_file, image_payload)
    elif action != "uninstall":
        rendered_images_digest = None
        image_evidence_digest = None
    if action != "uninstall" and args.endpoint_evidence_file:
        rendered_endpoints = rendered_endpoint_items(
            rendered_documents_value,
            selected / "artifacts" / "agent-control.tgz",
            [
                selected / "values" / "base-values.yaml",
                selected / "values" / "agent-control-overlay.yaml",
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
            "generated_by": "galileo-on-prem-agent-control-setup",
            "component": "agent-control",
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
                    selected / "values" / "agent-control-overlay.yaml",
                    "Agent Control overlay",
                ).sha256,
                "secret_input_contract": secret_input_contract,
            },
            "render_inventory_sha256": render_inventory_digest,
            "redacted_render_sha256": redacted_render_digest,
            "target": target_id,
            "created_at": now.isoformat().replace("+00:00", "Z"),
            "items": rendered_endpoints,
        }
        endpoint_evidence_digest = hashlib.sha256(
            (json.dumps(endpoint_payload, indent=2, sort_keys=True) + "\n").encode()
        ).hexdigest()
        new_private_json(args.endpoint_evidence_file, endpoint_payload)
    elif action != "uninstall":
        rendered_endpoints_digest = None
        endpoint_evidence_digest = None
    payload = {
        "schema": "galileo-on-prem-preflight-evidence/v1",
        "component": "agent-control",
        "action": action,
        "bundle_sha256": metadata["bundle_sha256"],
        "target": target_id,
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
    new_private_json(args.evidence_file, payload)
    print(
        json.dumps(
            {
                "status": "preflight-passed",
                "action": action,
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
        or evidence.get("component") != "agent-control"
        or evidence.get("action") != action
        or evidence.get("bundle_sha256") != metadata["bundle_sha256"]
    ):
        fail("preflight evidence is for a different component/action/bundle")
    if (
        evidence.get("release") != metadata["release_name"]
        or evidence.get("namespace") != metadata["namespace"]
    ):
        fail("preflight evidence targets another release")
    created = parse_time(evidence.get("created_at"))
    expires = parse_time(evidence.get("expires_at"))
    now = dt.datetime.now(UTC)
    if (
        created > now + dt.timedelta(minutes=1)
        or expires <= now
        or expires - created > dt.timedelta(minutes=30)
    ):
        fail("preflight evidence is expired or has an invalid lifetime")
    live_target = target(args.kube_context, metadata["namespace"])
    if not exact_value(evidence.get("target"), live_target):
        fail("Kubernetes target identity drifted")
    if not exact_value(evidence.get("target"), metadata["parent_stack"]["target"]):
        fail("parent stack target binding drifted")
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
    secret_values = secure_read(
        args.secret_values_file,
        "secret-values file",
        private=True,
        max_bytes=16 * 1024 * 1024,
    )
    if not exact_value(
        evidence.get("secret_input_contract"),
        redacted_secret_input_contract(secret_values.data),
    ):
        fail("secret-values redacted input contract drifted")
    selected = (
        absolute(args.previous_bundle)
        if action == "rollback" and args.previous_bundle
        else Path()
    )
    if action == "rollback":
        prior = validate_bundle(selected)
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
        "component": "agent-control",
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
    if parse_time(approval.get("expires_at")) <= dt.datetime.now(UTC):
        fail("approval expired")
    issued = parse_time(approval.get("issued_at"))
    expires = parse_time(approval.get("expires_at"))
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
            fail("upgrade evidence lacks the current release")
        if (
            approval.get("from_version")
            != state_version(current_state, "agent-control")
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


def helm_env() -> tuple[dict[str, str], tempfile.TemporaryDirectory[str]]:
    holder = tempfile.TemporaryDirectory(prefix="galileo-helm-action-")
    return command_env(), holder


def snapshot_inputs(
    selected: Path, secret_values: Path
) -> tuple[tempfile.TemporaryDirectory[str], Path, list[Path]]:
    holder = tempfile.TemporaryDirectory(prefix="galileo-action-inputs-")
    root = Path(holder.name)
    root.chmod(0o700)
    sources = [
        selected / "artifacts" / "agent-control.tgz",
        selected / "values" / "base-values.yaml",
        selected / "values" / "agent-control-overlay.yaml",
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
            max_bytes=512 * 1024 * 1024,
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


def apply_release(
    args: argparse.Namespace, metadata: dict, bundle: Path, mode: str
) -> None:
    fail(
        f"{mode} is handoff-only: this skill performs no Helm or Kubernetes "
        "mutation; use the exact immutable bundle, lifecycle.json, and fresh "
        "preflight/image/endpoint evidence in a Galileo/CSE joint session"
    )


def do_plan(args: argparse.Namespace, metadata: dict, kind: str) -> None:
    payload = {
        "schema": f"galileo-on-prem-{kind}-plan/v1",
        "component": "agent-control",
        "bundle_sha256": metadata["bundle_sha256"],
        "release": metadata["release_name"],
        "namespace": metadata["namespace"],
        "target": metadata["parent_stack"]["target"],
        "automatic": False,
    }
    if kind == "rollback":
        payload["requirements"] = [
            "previous immutable bundle",
            "migration compatibility",
            "recent backup",
            "release notes",
            "approval",
        ]
    else:
        payload["requirements"] = [
            "recent backup",
            "retention attestation",
            "typed release/namespace confirmation",
            "approval",
        ]
        payload["blocked_by_chart_delete_risk"] = metadata["chart_has_delete_risk"]
    new_private_json(args.plan_file, payload)
    print(
        json.dumps(
            {"status": "planned", "action": kind, "plan_file": args.plan_file},
            sort_keys=True,
        )
    )


def uninstall(args: argparse.Namespace, metadata: dict) -> None:
    fail(
        "automated Agent Control uninstall is disabled because Helm/CR/finalizer deletion side effects cannot be proven safe; use the retention-first manual plan with Galileo"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gated Galileo Agent Control lifecycle"
    )
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
        help="Exact Galileo instance console URL bound to the bundle",
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
    parser.add_argument("--previous-bundle")
    parser.add_argument("--plan-file")
    parser.add_argument("--retention-file")
    parser.add_argument("--confirm-target")
    parser.add_argument("--accept-agent-control-install", action="store_true")
    parser.add_argument("--accept-agent-control-upgrade", action="store_true")
    parser.add_argument("--accept-agent-control-rollback", action="store_true")
    parser.add_argument("--accept-agent-control-uninstall", action="store_true")
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
    if validate_url(args.galileo_console_url) != metadata["galileo_console_url"]:
        fail("Galileo instance console URL does not match the bundle")
    if mode == "preflight":
        if (
            not args.for_action
            or not args.evidence_file
            or (args.for_action != "uninstall" and not args.image_evidence_file)
            or (args.for_action != "uninstall" and not args.endpoint_evidence_file)
            or not args.secret_values_file
        ):
            fail(
                "preflight requires action, private Secret values, image evidence, and endpoint evidence files except for uninstall"
            )
        if not 1 <= args.ttl_minutes <= 30:
            fail("preflight TTL must be 1-30 minutes")
        do_preflight(args, metadata, bundle)
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
        if state is not None and metadata["ownership"] == "standalone":
            require_release_identity(state, metadata)
        print(
            json.dumps({"status": "observed", "release_state": state}, sort_keys=True)
        )
    elif mode in {"plan-rollback", "plan-uninstall"}:
        if not args.plan_file:
            fail(f"{mode} requires --plan-file")
        do_plan(args, metadata, mode.removeprefix("plan-"))
    elif mode == "apply-uninstall":
        for field in (
            "evidence_file",
            "secret_values_file",
            "approval_file",
            "retention_file",
            "confirm_target",
        ):
            if not getattr(args, field):
                fail(f"{mode} requires --{field.replace('_', '-')}")
        uninstall(args, metadata)
    else:
        for field in ("evidence_file", "secret_values_file", "approval_file"):
            if not getattr(args, field):
                fail(f"{mode} requires --{field.replace('_', '-')}")
        apply_release(args, metadata, bundle, mode)
    runtime.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

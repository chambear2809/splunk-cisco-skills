#!/usr/bin/env python3
"""Fail-closed audit of rendered Kubernetes auto-instrumentation targets."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


MANAGED_PREFIX = "instrumentation.opentelemetry.io/"
LANGUAGE_SPEC_KEYS = {
    "java": "java",
    "nodejs": "nodejs",
    "python": "python",
    "dotnet": "dotnet",
    "go": "go",
    "apache-httpd": "apacheHttpd",
    "nginx": "nginx",
}
LANGUAGE_INIT_NAMES = {
    "java": {"opentelemetry-auto-instrumentation-java"},
    "nodejs": {"opentelemetry-auto-instrumentation-nodejs"},
    "python": {"opentelemetry-auto-instrumentation-python"},
    "dotnet": {"opentelemetry-auto-instrumentation-dotnet"},
    "apache-httpd": {"otel-agent-source-container-clone", "otel-agent-attach-apache"},
    "nginx": {"otel-agent-source-container-clone", "otel-agent-attach-nginx"},
}
LANGUAGE_IMAGE_INIT_NAME = {
    "java": "opentelemetry-auto-instrumentation-java",
    "nodejs": "opentelemetry-auto-instrumentation-nodejs",
    "python": "opentelemetry-auto-instrumentation-python",
    "dotnet": "opentelemetry-auto-instrumentation-dotnet",
    "apache-httpd": "otel-agent-attach-apache",
    "nginx": "otel-agent-attach-nginx",
}
ALL_INJECTED_INIT_NAMES = set().union(*LANGUAGE_INIT_NAMES.values())
DIGEST_IMAGE_RE = re.compile(r"^\S+@sha256:[0-9a-f]{64}$")


class AuditFailure(RuntimeError):
    """A validation condition was not proven."""


def fail(message: str) -> None:
    raise AuditFailure(message)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--target", action="append", default=[])
    parser.add_argument("--target-all", action="store_true")
    parser.add_argument("--kubectl-bin", default="kubectl")
    parser.add_argument("--kube-context", default="")
    parser.add_argument("--allow-current-context", action="store_true")
    return parser.parse_args()


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot parse {label}: {exc}")
    if not isinstance(value, dict):
        fail(f"{label} is not a JSON object")
    return value


def kubectl_command(args: argparse.Namespace) -> list[str]:
    command = [args.kubectl_bin]
    if args.kube_context:
        command.extend(["--context", args.kube_context])
    return command


def get_json(kube: list[str], arguments: list[str], context: str) -> dict[str, Any]:
    try:
        result = subprocess.run(
            [*kube, *arguments],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        fail(f"{context} could not execute kubectl: {exc}")
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        fail(f"{context} failed: {detail}")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        fail(f"{context} returned invalid JSON: {exc}")
    if not isinstance(value, dict):
        fail(f"{context} returned a non-object JSON value")
    return value


def managed_annotations(resource: Any) -> dict[str, str]:
    if not isinstance(resource, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in resource.items()
        if str(key).startswith(MANAGED_PREFIX)
    }


def env_value(container: dict[str, Any], name: str, context: str) -> str:
    matches = [
        item
        for item in (container.get("env") or [])
        if isinstance(item, dict) and item.get("name") == name
    ]
    if len(matches) != 1 or matches[0].get("valueFrom") is not None:
        fail(f"{context} does not have one literal {name} environment value")
    value = matches[0].get("value")
    if not isinstance(value, str) or not value:
        fail(f"{context} has an empty or non-literal {name} environment value")
    return value


def selected_containers(
    pod_spec: dict[str, Any], expected_annotations: dict[str, str], context: str
) -> list[dict[str, Any]]:
    regular = [
        container
        for container in (pod_spec.get("containers") or [])
        if isinstance(container, dict)
        and container.get("name") != "opentelemetry-auto-instrumentation"
    ]
    original_init = [
        container
        for container in (pod_spec.get("initContainers") or [])
        if isinstance(container, dict)
        and container.get("name") not in ALL_INJECTED_INIT_NAMES
    ]
    configured = str(expected_annotations.get(f"{MANAGED_PREFIX}container-names") or "")
    if configured:
        names = [name.strip() for name in configured.split(",") if name.strip()]
        if not names or len(names) != len(set(names)):
            fail(f"{context} has invalid rendered container-names annotation")
        by_name = {
            str(container.get("name") or ""): container
            for container in [*regular, *original_init]
        }
        missing = [name for name in names if name not in by_name]
        if missing:
            fail(f"{context} is missing annotated target container(s): {', '.join(missing)}")
        return [by_name[name] for name in names]
    if not regular:
        fail(f"{context} has no application container to validate")
    return [regular[0]]


def volume_mount_names(container: dict[str, Any]) -> set[str]:
    return {
        str(item.get("name") or "")
        for item in (container.get("volumeMounts") or [])
        if isinstance(item, dict)
    }


def selector_matches(selector: dict[str, Any], labels: dict[str, Any]) -> bool:
    for key, value in (selector.get("matchLabels") or {}).items():
        if str(labels.get(key, "")) != str(value):
            return False
    for expression in selector.get("matchExpressions") or []:
        if not isinstance(expression, dict):
            return False
        key = str(expression.get("key") or "")
        operator = str(expression.get("operator") or "")
        values = {str(value) for value in (expression.get("values") or [])}
        present = key in labels
        actual = str(labels.get(key, ""))
        if operator == "In" and (not present or actual not in values):
            return False
        if operator == "NotIn" and present and actual in values:
            return False
        if operator == "Exists" and not present:
            return False
        if operator == "DoesNotExist" and present:
            return False
        if operator not in {"In", "NotIn", "Exists", "DoesNotExist"}:
            return False
    return True


def nonnegative_int(value: Any, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        fail(f"{context} is not a nonnegative integer")
    return value


def verify_workload_current(workload: dict[str, Any], kind: str, context: str) -> None:
    metadata = workload.get("metadata") or {}
    spec = workload.get("spec") or {}
    status = workload.get("status") or {}
    generation = nonnegative_int(metadata.get("generation"), f"{context} metadata.generation")
    observed = nonnegative_int(
        status.get("observedGeneration"), f"{context} status.observedGeneration"
    )
    if observed != generation:
        fail(f"{context} controller has not observed the current workload generation")
    if kind in {"Deployment", "StatefulSet"}:
        desired = nonnegative_int(spec.get("replicas", 1), f"{context} spec.replicas")
        fields = ["replicas", "readyReplicas", "updatedReplicas"]
        if kind == "Deployment":
            fields.append("availableReplicas")
        else:
            fields.append("currentReplicas")
            if not status.get("currentRevision") or status.get("currentRevision") != status.get(
                "updateRevision"
            ):
                fail(f"{context} StatefulSet revisions are not current")
        for field in fields:
            if nonnegative_int(status.get(field, 0), f"{context} status.{field}") != desired:
                fail(f"{context} status.{field} does not match desired replicas")
    elif kind == "DaemonSet":
        desired = nonnegative_int(
            status.get("desiredNumberScheduled"),
            f"{context} status.desiredNumberScheduled",
        )
        for field in (
            "currentNumberScheduled",
            "updatedNumberScheduled",
            "numberReady",
            "numberAvailable",
        ):
            if nonnegative_int(status.get(field, 0), f"{context} status.{field}") != desired:
                fail(f"{context} status.{field} does not match desired scheduling")
    else:  # Metadata already restricts kinds, but fail closed on packet tampering.
        fail(f"{context} has unsupported workload kind {kind!r}")


def verify_pod_ready(pod: dict[str, Any], context: str) -> None:
    status = pod.get("status") or {}
    if status.get("phase") != "Running":
        fail(f"{context} is not Running")
    ready = any(
        isinstance(condition, dict)
        and condition.get("type") == "Ready"
        and condition.get("status") == "True"
        for condition in (status.get("conditions") or [])
    )
    if not ready:
        fail(f"{context} is not Ready")


def cr_catalog(metadata_packet: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    documents = metadata_packet.get("instrumentation_documents") or []
    if not isinstance(documents, list) or any(
        not isinstance(document, dict) for document in documents
    ):
        fail("metadata.json instrumentation_documents is not a list of objects")
    catalog: dict[tuple[str, str], dict[str, Any]] = {}
    for document in documents:
        metadata = document.get("metadata") or {}
        identity = (
            str(metadata.get("namespace") or ""),
            str(metadata.get("name") or ""),
        )
        if not all(identity) or identity in catalog:
            fail("metadata.json has missing or duplicate Instrumentation CR identities")
        catalog[identity] = document
    if not catalog:
        fail("metadata.json contains no Instrumentation CR documents")
    return catalog


def expected_language_block(
    row: dict[str, Any],
    expected_annotations: dict[str, str],
    catalog: dict[tuple[str, str], dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    language = str(row["language"])
    inject_key = f"{MANAGED_PREFIX}inject-{language}"
    binding = str(expected_annotations.get(inject_key) or "")
    if binding == "false":
        return {}, ""
    if binding == "true":
        candidates = [
            document
            for (namespace, _), document in catalog.items()
            if namespace == str(row["namespace"])
            and LANGUAGE_SPEC_KEYS[language] in (document.get("spec") or {})
        ]
    elif binding.count("/") == 1:
        namespace, name = binding.split("/", 1)
        document = catalog.get((namespace, name))
        candidates = [document] if document is not None else []
    else:
        fail(f"{row['target']} has invalid rendered {inject_key} value {binding!r}")
    if len(candidates) != 1:
        fail(f"{row['target']} does not resolve exactly one rendered {language} Instrumentation CR")
    document = candidates[0]
    block = (document.get("spec") or {}).get(LANGUAGE_SPEC_KEYS[language]) or {}
    if not isinstance(block, dict):
        fail(f"{row['target']} rendered {language} Instrumentation CR block is invalid")
    image = str(block.get("image") or "")
    if not DIGEST_IMAGE_RE.fullmatch(image):
        fail(f"{row['target']} rendered {language} Instrumentation image is not @sha256 pinned")
    language_env = {
        str(item.get("name") or ""): str(item.get("value") or "")
        for item in (block.get("env") or [])
        if isinstance(item, dict)
    }
    endpoint = language_env.get("OTEL_EXPORTER_OTLP_ENDPOINT") or str(
        (((document.get("spec") or {}).get("exporter") or {}).get("endpoint") or "")
    )
    if not endpoint:
        fail(f"{row['target']} rendered {language} Instrumentation CR has no OTLP endpoint")
    return block, endpoint


def require_endpoint(container: dict[str, Any], endpoint: str, context: str) -> None:
    if env_value(container, "OTEL_EXPORTER_OTLP_ENDPOINT", context) != endpoint:
        fail(f"{context} OTEL_EXPORTER_OTLP_ENDPOINT does not match the rendered Instrumentation CR")


def verify_language_evidence(
    row: dict[str, Any],
    pod: dict[str, Any],
    expected_annotations: dict[str, str],
    catalog: dict[tuple[str, str], dict[str, Any]],
) -> None:
    language = str(row["language"])
    pod_name = str((pod.get("metadata") or {}).get("name") or "<unknown>")
    context = f"pod {row['namespace']}/{pod_name} for {row['kind']}/{row['name']}"
    pod_spec = pod.get("spec") or {}
    init_names = {
        str(container.get("name") or "")
        for container in (pod_spec.get("initContainers") or [])
        if isinstance(container, dict)
    }
    inject_key = f"{MANAGED_PREFIX}inject-{language}"
    enabled = expected_annotations.get(inject_key) != "false"
    required_init = LANGUAGE_INIT_NAMES.get(language, set())
    if not enabled:
        stale = sorted(required_init & init_names)
        if language == "go" and any(
            isinstance(container, dict)
            and container.get("name") == "opentelemetry-auto-instrumentation"
            for container in (pod_spec.get("containers") or [])
        ):
            stale.append("opentelemetry-auto-instrumentation")
        all_containers = [
            container
            for container in [
                *(pod_spec.get("containers") or []),
                *(pod_spec.get("initContainers") or []),
            ]
            if isinstance(container, dict)
        ]
        for container in all_containers:
            env = {
                str(item.get("name") or ""): str(item.get("value") or "")
                for item in (container.get("env") or [])
                if isinstance(item, dict) and item.get("valueFrom") is None
            }
            mounts = volume_mount_names(container)
            if language == "java" and "/otel-auto-instrumentation-java" in env.get(
                "JAVA_TOOL_OPTIONS", ""
            ):
                stale.append("JAVA_TOOL_OPTIONS")
            elif language == "nodejs" and "/otel-auto-instrumentation-nodejs" in env.get(
                "NODE_OPTIONS", ""
            ):
                stale.append("NODE_OPTIONS")
            elif language == "python" and "/otel-auto-instrumentation-python" in env.get(
                "PYTHONPATH", ""
            ):
                stale.append("PYTHONPATH")
            elif language == "dotnet" and any(
                name in env
                for name in (
                    "OTEL_DOTNET_AUTO_HOME",
                    "CORECLR_PROFILER",
                    "CORECLR_PROFILER_PATH",
                )
            ):
                stale.append(".NET profiler environment")
            elif language == "apache-httpd" and {
                "otel-apache-agent",
                "otel-apache-conf-dir",
            } & mounts:
                stale.append("Apache auto-instrumentation mount")
            elif language == "nginx" and (
                {"otel-nginx-agent", "otel-nginx-conf-dir"} & mounts
                or "/opt/opentelemetry-webserver/agent/sdk_lib/lib"
                in env.get("LD_LIBRARY_PATH", "")
            ):
                stale.append("Nginx auto-instrumentation artifact")
        if stale:
            fail(
                f"{context} retains disabled {language} injection artifacts: "
                f"{', '.join(sorted(set(stale)))}"
            )
        return

    language_block, endpoint = expected_language_block(row, expected_annotations, catalog)
    expected_image = str(language_block.get("image") or "")
    if language == "go":
        selected = selected_containers(pod_spec, expected_annotations, context)
        if len(selected) != 1:
            fail(f"{context} Go injection must target exactly one application container")
        sidecars = [
            container
            for container in (pod_spec.get("containers") or [])
            if isinstance(container, dict)
            and container.get("name") == "opentelemetry-auto-instrumentation"
        ]
        if len(sidecars) != 1:
            fail(f"{context} does not have exactly one Go auto-instrumentation sidecar")
        sidecar = sidecars[0]
        if sidecar.get("image") != expected_image:
            fail(f"{context} Go sidecar image does not match the rendered @sha256 image")
        if pod_spec.get("shareProcessNamespace") is not True:
            fail(f"{context} Go injection does not enable shareProcessNamespace")
        security = sidecar.get("securityContext") or {}
        if security.get("privileged") is not True or security.get("runAsUser") != 0:
            fail(f"{context} Go sidecar lacks the rendered Operator privilege evidence")
        expected_executable = str(
            expected_annotations.get(f"{MANAGED_PREFIX}otel-go-auto-target-exe") or ""
        )
        if env_value(sidecar, "OTEL_GO_AUTO_TARGET_EXE", context) != expected_executable:
            fail(f"{context} Go target executable does not match the rendered annotation")
        require_endpoint(sidecar, endpoint, context)
        return

    missing_init = sorted(required_init - init_names)
    if missing_init:
        fail(f"{context} lacks exact {language} init container(s): {', '.join(missing_init)}")
    image_init_name = LANGUAGE_IMAGE_INIT_NAME[language]
    image_init = [
        container
        for container in (pod_spec.get("initContainers") or [])
        if isinstance(container, dict) and container.get("name") == image_init_name
    ]
    if len(image_init) != 1 or image_init[0].get("image") != expected_image:
        fail(
            f"{context} {language} injected init image does not exactly match the rendered @sha256 image"
        )

    for container in selected_containers(pod_spec, expected_annotations, context):
        container_name = str(container.get("name") or "<unknown>")
        container_context = f"{context} container {container_name}"
        require_endpoint(container, endpoint, container_context)
        if language == "java":
            value = env_value(container, "JAVA_TOOL_OPTIONS", container_context)
            expected_agent = f"-javaagent:/otel-auto-instrumentation-java-{container_name}/javaagent.jar"
            if expected_agent not in value.split():
                fail(f"{container_context} lacks the exact Java agent option {expected_agent}")
        elif language == "nodejs":
            value = env_value(container, "NODE_OPTIONS", container_context)
            if "--require /otel-auto-instrumentation-nodejs/autoinstrumentation.js" not in value:
                fail(f"{container_context} lacks the OpenTelemetry Node.js require hook")
        elif language == "python":
            value = env_value(container, "PYTHONPATH", container_context)
            required_paths = {
                "/otel-auto-instrumentation-python/opentelemetry/instrumentation/auto_instrumentation",
                "/otel-auto-instrumentation-python",
            }
            if not required_paths.issubset(set(value.split(":"))):
                fail(f"{container_context} lacks the OpenTelemetry Python paths")
        elif language == "dotnet":
            expected_values = {
                "CORECLR_ENABLE_PROFILING": "1",
                "CORECLR_PROFILER": "{918728DD-259F-4A6A-AC2B-B85E1B658318}",
                "OTEL_DOTNET_AUTO_HOME": "/otel-auto-instrumentation-dotnet",
            }
            for name, expected in expected_values.items():
                if env_value(container, name, container_context) != expected:
                    fail(f"{container_context} has unexpected {name}")
            runtime = str(
                expected_annotations.get(f"{MANAGED_PREFIX}otel-dotnet-auto-runtime")
                or "linux-x64"
            )
            library_dir = "linux-musl-x64" if runtime == "linux-musl-x64" else "linux-x64"
            expected_path = (
                f"/otel-auto-instrumentation-dotnet/{library_dir}/"
                "OpenTelemetry.AutoInstrumentation.Native.so"
            )
            if env_value(container, "CORECLR_PROFILER_PATH", container_context) != expected_path:
                fail(f"{container_context} CORECLR_PROFILER_PATH does not match {runtime}")
        elif language == "apache-httpd":
            if not {"otel-apache-agent", "otel-apache-conf-dir"}.issubset(
                volume_mount_names(container)
            ):
                fail(f"{container_context} lacks exact Apache agent/config volume mounts")
        elif language == "nginx":
            if not {"otel-nginx-agent", "otel-nginx-conf-dir"}.issubset(
                volume_mount_names(container)
            ):
                fail(f"{container_context} lacks exact Nginx agent/config volume mounts")
            library_path = env_value(container, "LD_LIBRARY_PATH", container_context)
            if "/opt/opentelemetry-webserver/agent/sdk_lib/lib" not in library_path.split(":"):
                fail(f"{container_context} lacks the OpenTelemetry Nginx library path")


def selected_targets(
    metadata: dict[str, Any], args: argparse.Namespace
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if args.target_all and args.target:
        fail("--target and --target-all are mutually exclusive")
    if not args.target_all and not args.target:
        fail("pass --target Kind/namespace/name or --target-all")
    rows = metadata.get("targets") or []
    namespace_rows = metadata.get("namespace_targets") or []
    if not isinstance(rows, list) or not isinstance(namespace_rows, list):
        fail("metadata.json target catalogs must be lists")
    if any(not isinstance(row, dict) for row in rows):
        fail("metadata.json contains a non-object workload target")
    if any(not isinstance(row, dict) for row in namespace_rows):
        fail("metadata.json contains a non-object namespace target")
    if not rows and not namespace_rows:
        fail("metadata.json contains no workload or namespace targets for injection validation")
    workload_identities = [
        (str(row.get("target") or ""), str(row.get("language") or "")) for row in rows
    ]
    namespace_identities = [str(row.get("target") or "") for row in namespace_rows]
    available = {
        target for target, _ in workload_identities
    } | set(namespace_identities)
    if (
        "" in available
        or any(not language for _, language in workload_identities)
        or len(workload_identities) != len(set(workload_identities))
        or len(namespace_identities) != len(set(namespace_identities))
        or ({target for target, _ in workload_identities} & set(namespace_identities))
    ):
        fail("metadata.json contains missing, duplicate, or conflicting injection target identities")
    requested = set(args.target)
    missing = sorted(requested - available)
    if missing:
        fail(f"requested target(s) are absent from metadata.json: {', '.join(missing)}")
    if args.target_all:
        return rows, namespace_rows
    return (
        [row for row in rows if row.get("target") in requested],
        [row for row in namespace_rows if row.get("target") in requested],
    )


def audit_namespace_target(
    row: dict[str, Any],
    kube: list[str],
    catalog: dict[tuple[str, str], dict[str, Any]],
) -> None:
    namespace = str(row.get("namespace") or "")
    target = str(row.get("target") or "")
    languages = row.get("languages")
    expected_annotations = row.get("annotations")
    if target != f"Namespace/{namespace}" or not namespace:
        fail("metadata.json contains an invalid namespace target identity")
    if (
        not isinstance(languages, list)
        or not languages
        or any(not isinstance(language, str) for language in languages)
        or len(languages) != len(set(str(language) for language in languages))
        or any(str(language) not in LANGUAGE_SPEC_KEYS for language in languages)
    ):
        fail(f"{target} has an invalid language catalog")
    if not isinstance(expected_annotations, dict) or not expected_annotations:
        fail(f"{target} has no rendered managed annotations")
    expected_annotations = {
        str(key): str(value) for key, value in expected_annotations.items()
    }
    expected_inject_keys = {
        f"{MANAGED_PREFIX}inject-{language}" for language in languages
    }
    if set(expected_annotations) != expected_inject_keys:
        fail(f"{target} managed annotations do not exactly match its languages")
    for language in languages:
        binding = expected_annotations[f"{MANAGED_PREFIX}inject-{language}"]
        if binding in {"", "true", "false"} or binding.count("/") != 1:
            fail(f"{target} does not use an explicit CR binding for {language}")

    namespace_object = get_json(
        kube,
        ["get", "namespace", namespace, "-o", "json"],
        f"{target} lookup",
    )
    metadata = namespace_object.get("metadata") or {}
    if namespace_object.get("kind") != "Namespace" or metadata.get("name") != namespace:
        fail(f"{target} lookup returned a different Kubernetes resource")
    live_annotations = managed_annotations(metadata.get("annotations") or {})
    if live_annotations != expected_annotations:
        fail(f"{target} managed annotations drifted from metadata.json")

    pod_list = get_json(
        kube,
        ["-n", namespace, "get", "pods", "-o", "json"],
        f"pod lookup for {target}",
    )
    pod_items = pod_list.get("items")
    if not isinstance(pod_items, list):
        fail(f"pod lookup for {target} returned no items list")
    active_pods: list[dict[str, Any]] = []
    excluded = 0
    for pod in pod_items:
        if not isinstance(pod, dict):
            fail(f"pod lookup for {target} contains a non-object item")
        pod_metadata = pod.get("metadata") or {}
        phase = str((pod.get("status") or {}).get("phase") or "")
        if pod_metadata.get("deletionTimestamp") or phase in {"Succeeded", "Failed"}:
            excluded += 1
            continue
        active_pods.append(pod)
    if not active_pods:
        fail(f"{target} has no active pods to prove namespace-level injection")

    opt_outs = 0
    for pod in active_pods:
        pod_metadata = pod.get("metadata") or {}
        pod_name = str(pod_metadata.get("name") or "")
        pod_namespace = str(pod_metadata.get("namespace") or "")
        if not pod_name or pod_namespace != namespace:
            fail(f"{target} pod list contains an invalid or cross-namespace identity")
        verify_pod_ready(pod, f"pod {namespace}/{pod_name}")
        pod_annotations = managed_annotations(pod_metadata.get("annotations") or {})
        effective_annotations = dict(expected_annotations)
        # Pod-template annotations deterministically override namespace
        # injection. `false` is the only exclusion; another explicit CR value
        # remains in scope and is validated against that rendered CR.
        for key, value in pod_annotations.items():
            if key in expected_inject_keys or key in {
                f"{MANAGED_PREFIX}container-names",
                f"{MANAGED_PREFIX}otel-dotnet-auto-runtime",
                f"{MANAGED_PREFIX}otel-go-auto-target-exe",
            }:
                effective_annotations[key] = value
        for language in languages:
            inject_key = f"{MANAGED_PREFIX}inject-{language}"
            if effective_annotations[inject_key] == "false":
                opt_outs += 1
            audit_row = {
                "target": target,
                "kind": "Namespace",
                "namespace": namespace,
                "name": namespace,
                "language": language,
            }
            verify_language_evidence(audit_row, pod, effective_annotations, catalog)
    language_text = ",".join(sorted(str(language) for language in languages))
    print(
        f"  {target}: exact {language_text} namespace binding on "
        f"{len(active_pods)} active pod(s); {opt_outs} explicit pod-language "
        f"opt-out(s), {excluded} terminal/deleting pod(s) excluded"
    )


def audit(args: argparse.Namespace) -> None:
    if args.kube_context and args.allow_current_context:
        fail("--kube-context conflicts with --allow-current-context")
    if not args.kube_context and not args.allow_current_context:
        fail("pass --kube-context CTX or explicitly acknowledge --allow-current-context")
    root = Path(args.output_dir).expanduser().resolve()
    metadata = load_json(root / "metadata.json", "metadata.json")
    if metadata.get("skill") != "splunk-observability-k8s-auto-instrumentation-setup":
        fail("metadata.json has the wrong skill identity")
    preflight = metadata.get("preflight") or {}
    if not isinstance(preflight, dict) or preflight.get("errors"):
        fail("metadata.json contains unresolved or malformed preflight errors")
    catalog = cr_catalog(metadata)
    targets, namespace_targets = selected_targets(metadata, args)
    kube = kubectl_command(args)

    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in targets:
        language = str(row.get("language") or "")
        if language not in LANGUAGE_SPEC_KEYS:
            fail(f"metadata.json contains unsupported target language {language!r}")
        identity = (
            str(row.get("kind") or ""),
            str(row.get("namespace") or ""),
            str(row.get("name") or ""),
        )
        if not all(identity) or str(row.get("target") or "") != "/".join(identity):
            fail("metadata.json contains a target with an incomplete or inconsistent identity")
        expected = row.get("annotations") or {}
        if not isinstance(expected, dict) or not expected:
            fail(f"{row['target']} has no rendered annotations in metadata.json")
        if any(not str(key).startswith(MANAGED_PREFIX) for key in expected):
            fail(f"{row['target']} metadata contains an unmanaged annotation")
        group = grouped.setdefault(identity, {"annotations": {}, "rows": []})
        for raw_key, raw_value in expected.items():
            key, value = str(raw_key), str(raw_value)
            if key in group["annotations"] and group["annotations"][key] != value:
                fail(f"{'/'.join(identity)} has conflicting rendered annotation values")
            group["annotations"][key] = value
        group["rows"].append(row)

    for (kind, namespace, name), group in grouped.items():
        expected_annotations = group["annotations"]
        workload = get_json(
            kube,
            ["-n", namespace, "get", kind.lower(), name, "-o", "json"],
            f"{kind}/{namespace}/{name} lookup",
        )
        verify_workload_current(workload, kind, f"{kind}/{namespace}/{name}")
        template_annotations = managed_annotations(
            (((workload.get("spec") or {}).get("template") or {}).get("metadata") or {}).get(
                "annotations"
            )
            or {}
        )
        if template_annotations != expected_annotations:
            fail(f"{kind}/{namespace}/{name} managed pod-template annotations drifted from metadata.json")
        selector = (workload.get("spec") or {}).get("selector") or {}
        if not selector.get("matchLabels") and not selector.get("matchExpressions"):
            fail(f"{kind}/{namespace}/{name} has no usable pod selector")
        pod_list = get_json(
            kube,
            ["-n", namespace, "get", "pods", "-o", "json"],
            f"pod lookup for {kind}/{namespace}/{name}",
        )
        pod_items = pod_list.get("items") or []
        if not isinstance(pod_items, list):
            fail(f"pod lookup for {kind}/{namespace}/{name} returned no items list")
        pods = [
            pod
            for pod in pod_items
            if isinstance(pod, dict)
            and not (pod.get("metadata") or {}).get("deletionTimestamp")
            and selector_matches(selector, (pod.get("metadata") or {}).get("labels") or {})
        ]
        if not pods:
            fail(f"{kind}/{namespace}/{name} has no active pods matching its selector")
        for pod in pods:
            pod_name = str((pod.get("metadata") or {}).get("name") or "<unknown>")
            verify_pod_ready(pod, f"pod {namespace}/{pod_name}")
            pod_annotations = managed_annotations((pod.get("metadata") or {}).get("annotations") or {})
            if pod_annotations != expected_annotations:
                fail(f"pod {namespace}/{pod_name} managed annotations drifted from metadata.json")
            for row in group["rows"]:
                verify_language_evidence(row, pod, expected_annotations, catalog)
        languages = ",".join(sorted(str(row["language"]) for row in group["rows"]))
        print(
            f"  {kind}/{namespace}/{name}: exact managed annotations and {languages} evidence "
            f"on {len(pods)} pod(s)"
        )

    for row in namespace_targets:
        audit_namespace_target(row, kube, catalog)


def main() -> int:
    try:
        audit(parse_args())
    except AuditFailure as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Validate or safely purge the rendered Splunk OBI Kubernetes contract."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path
from typing import Any


SKILL = "splunk-observability-k8s-auto-instrumentation-setup"
FATAL_LOG_PATTERNS = (
    re.compile(r"(?i)(?:^|\b)(?:panic|fatal)(?:\b|:)"),
    re.compile(r"(?i)permission denied"),
    re.compile(r"(?i)bpf.{0,80}(?:attach|load).{0,80}(?:fail|error)"),
    re.compile(r"(?i)(?:attach|load).{0,80}bpf.{0,80}(?:fail|error)"),
    re.compile(r"(?i)export.{0,80}(?:fail|error)"),
)
MAX_LOG_BYTES = 1024 * 1024


class ObiError(RuntimeError):
    """An OBI ownership or health invariant could not be proven."""


def fail(message: str) -> None:
    raise ObiError(message)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("validate", "purge"), required=True)
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--kubectl-bin", default="kubectl")
    parser.add_argument("--kube-context", default="")
    return parser.parse_args()


def load_metadata(path: str) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        metadata = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot parse metadata.json: {exc}")
    if not isinstance(metadata, dict) or metadata.get("skill") != SKILL:
        fail("metadata.json has the wrong skill identity")
    contract = metadata.get("obi_contract")
    if not isinstance(contract, dict) or contract.get("enabled") is not True:
        fail("metadata.json does not enable an OBI contract")
    documents = contract.get("documents")
    scc_documents = contract.get("scc_documents")
    if (
        not isinstance(documents, list)
        or len(documents) != 2
        or not isinstance(scc_documents, list)
    ):
        fail("metadata.json has a malformed OBI document contract")
    return metadata, contract


def kube_command(args: argparse.Namespace) -> list[str]:
    command = [args.kubectl_bin]
    if args.kube_context:
        command.extend(["--context", args.kube_context])
    return command


def run(
    kube: list[str],
    arguments: list[str],
    *,
    expect_json: bool = False,
    stdin: str | None = None,
    suppress_failure_output: bool = False,
) -> Any:
    try:
        result = subprocess.run(
            [*kube, *arguments],
            input=stdin,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        fail(f"kubectl {' '.join(arguments)} failed to execute: {exc}")
    if result.returncode != 0:
        if suppress_failure_output:
            fail(f"kubectl {' '.join(arguments)} failed; command output suppressed")
        detail = (
            result.stderr.strip()
            or result.stdout.strip()
            or f"exit {result.returncode}"
        )
        fail(f"kubectl {' '.join(arguments)} failed: {detail}")
    if not expect_json:
        return result.stdout
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        fail(f"kubectl {' '.join(arguments)} returned invalid JSON: {exc}")
    if not isinstance(value, dict):
        fail(f"kubectl {' '.join(arguments)} returned a non-object JSON value")
    return value


def expected_documents(contract: dict[str, Any]) -> list[dict[str, Any]]:
    documents = [*contract["documents"], *contract["scc_documents"]]
    if any(not isinstance(document, dict) for document in documents):
        fail("metadata.json OBI contract contains a non-object document")
    return documents


def identity(document: dict[str, Any]) -> tuple[str, str, str]:
    metadata = document.get("metadata") or {}
    return (
        str(document.get("kind") or ""),
        str(metadata.get("namespace") or ""),
        str(metadata.get("name") or ""),
    )


def projected_live(live: Any, expected: Any, path: str = "resource") -> Any:
    if isinstance(expected, dict):
        if not isinstance(live, dict):
            fail(f"{path} is not an object")
        return {
            key: projected_live(live.get(key), value, f"{path}.{key}")
            for key, value in expected.items()
        }
    if isinstance(expected, list):
        if not isinstance(live, list) or len(live) != len(expected):
            fail(f"{path} list length drifted")
        return [
            projected_live(actual, wanted, f"{path}[{index}]")
            for index, (actual, wanted) in enumerate(zip(live, expected))
        ]
    return live


def fetch_owned(
    kube: list[str], documents: list[dict[str, Any]]
) -> dict[tuple[str, str, str], dict[str, Any]]:
    live_documents: dict[tuple[str, str, str], dict[str, Any]] = {}
    for expected in documents:
        kind, namespace, name = identity(expected)
        if not kind or not name:
            fail("metadata.json OBI contract contains an incomplete resource identity")
        arguments = []
        if namespace:
            arguments.extend(["-n", namespace])
        arguments.extend(["get", kind.lower(), name, "-o", "json"])
        live = run(kube, arguments, expect_json=True)
        if identity(live) != (kind, namespace, name):
            fail(f"{kind}/{namespace}/{name} lookup returned a different resource")
        if projected_live(live, expected, f"{kind}/{namespace}/{name}") != expected:
            fail(
                f"{kind}/{namespace}/{name} managed configuration drifted from metadata.json"
            )
        labels = (live.get("metadata") or {}).get("labels") or {}
        if (
            labels.get("app.kubernetes.io/name") != "splunk-obi"
            or labels.get("app.kubernetes.io/managed-by") != SKILL
        ):
            fail(f"{kind}/{namespace}/{name} is not owned by {SKILL}")
        live_documents[(kind, namespace, name)] = live
    return live_documents


def nonnegative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        fail(f"{label} is not a nonnegative integer")
    return value


def version_tuple(value: str) -> tuple[int, int, int]:
    match = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?", value)
    if not match:
        fail(f"cannot parse node kernel version {value!r}")
    return tuple(int(part or "0") for part in match.groups())


def validate_health(
    kube: list[str],
    contract: dict[str, Any],
    live: dict[tuple[str, str, str], dict[str, Any]],
) -> None:
    namespace = str(contract.get("namespace") or "")
    daemonset = live.get(("DaemonSet", namespace, "splunk-obi"))
    if daemonset is None:
        fail("live OBI contract has no DaemonSet")
    metadata = daemonset.get("metadata") or {}
    status = daemonset.get("status") or {}
    generation = nonnegative_int(metadata.get("generation"), "OBI DaemonSet generation")
    observed = nonnegative_int(
        status.get("observedGeneration"), "OBI DaemonSet observedGeneration"
    )
    if observed != generation:
        fail("OBI DaemonSet controller has not observed the current generation")
    desired = nonnegative_int(
        status.get("desiredNumberScheduled"), "OBI desiredNumberScheduled"
    )
    if desired < 1:
        fail("OBI DaemonSet has no desired nodes")
    for field in (
        "currentNumberScheduled",
        "updatedNumberScheduled",
        "numberReady",
        "numberAvailable",
    ):
        if nonnegative_int(status.get(field, 0), f"OBI {field}") != desired:
            fail(f"OBI DaemonSet {field} does not match desiredNumberScheduled")

    node_list = run(kube, ["get", "nodes", "-o", "json"], expect_json=True)
    items = node_list.get("items")
    if not isinstance(items, list):
        fail("Kubernetes node list has no items array")
    supported_arches = set(
        str(value) for value in contract.get("supported_architectures") or []
    )
    minimum_kernel = version_tuple(str(contract.get("minimum_kernel") or ""))
    eligible: set[str] = set()
    for node in items:
        if not isinstance(node, dict):
            fail("Kubernetes node list contains a non-object item")
        node_metadata = node.get("metadata") or {}
        node_spec = node.get("spec") or {}
        node_status = node.get("status") or {}
        labels = node_metadata.get("labels") or {}
        info = node_status.get("nodeInfo") or {}
        ready = any(
            condition.get("type") == "Ready" and condition.get("status") == "True"
            for condition in (node_status.get("conditions") or [])
            if isinstance(condition, dict)
        )
        os_name = str(
            labels.get("kubernetes.io/os") or info.get("operatingSystem") or ""
        )
        if not ready or node_spec.get("unschedulable") is True or os_name != "linux":
            continue
        name = str(node_metadata.get("name") or "")
        arch = str(labels.get("kubernetes.io/arch") or info.get("architecture") or "")
        kernel = str(info.get("kernelVersion") or "")
        if not name or arch not in supported_arches:
            fail(
                f"eligible OBI node {name or '<unknown>'} has unsupported architecture {arch!r}"
            )
        if version_tuple(kernel) < minimum_kernel:
            fail(
                f"eligible OBI node {name} kernel {kernel!r} is below {contract['minimum_kernel']}"
            )
        eligible.add(name)
    if len(eligible) != desired:
        fail(
            f"OBI DaemonSet desires {desired} node(s), but {len(eligible)} Ready schedulable Linux node(s) are supported"
        )

    pod_list = run(
        kube,
        [
            "-n",
            namespace,
            "get",
            "pods",
            "-l",
            "app.kubernetes.io/name=splunk-obi",
            "-o",
            "json",
        ],
        expect_json=True,
    )
    pods = pod_list.get("items")
    if not isinstance(pods, list) or len(pods) != desired:
        fail("OBI pod count does not match DaemonSet desiredNumberScheduled")
    expected_image = str(
        (((daemonset.get("spec") or {}).get("template") or {}).get("spec") or {})
        .get("containers", [{}])[0]
        .get("image")
        or ""
    )
    covered: set[str] = set()
    total_log_bytes = 0
    for pod in pods:
        pod_metadata = pod.get("metadata") or {}
        pod_spec = pod.get("spec") or {}
        pod_status = pod.get("status") or {}
        pod_name = str(pod_metadata.get("name") or "")
        node_name = str(pod_spec.get("nodeName") or "")
        ready = any(
            condition.get("type") == "Ready" and condition.get("status") == "True"
            for condition in (pod_status.get("conditions") or [])
            if isinstance(condition, dict)
        )
        containers = pod_spec.get("containers") or []
        if (
            not pod_name
            or node_name not in eligible
            or node_name in covered
            or pod_status.get("phase") != "Running"
            or not ready
            or len(containers) != 1
            or containers[0].get("name") != "obi"
            or containers[0].get("image") != expected_image
        ):
            fail(
                f"OBI pod {namespace}/{pod_name or '<unknown>'} does not prove exact ready node/image coverage"
            )
        covered.add(node_name)
        logs = run(
            kube,
            [
                "-n",
                namespace,
                "logs",
                pod_name,
                "--all-containers=true",
                "--since=10m",
                "--tail=200",
                "--timestamps=true",
            ],
            suppress_failure_output=True,
        )
        total_log_bytes += len(logs.encode("utf-8"))
        if total_log_bytes > MAX_LOG_BYTES:
            fail("bounded OBI recent-log evidence exceeded 1 MiB")
        for line in logs.splitlines():
            if any(pattern.search(line) for pattern in FATAL_LOG_PATTERNS):
                fail(
                    f"OBI pod {namespace}/{pod_name} recent logs match a fatal health rule"
                )
    if covered != eligible:
        fail("OBI pods do not cover every supported Ready schedulable Linux node")


def raw_resource_path(document: dict[str, Any]) -> str:
    api_version = str(document.get("apiVersion") or "")
    kind, namespace, name = identity(document)
    resources = {
        ("apps/v1", "DaemonSet"): ("daemonsets", True),
        ("v1", "ServiceAccount"): ("serviceaccounts", True),
        ("security.openshift.io/v1", "SecurityContextConstraints"): (
            "securitycontextconstraints",
            False,
        ),
    }
    try:
        plural, namespaced = resources[(api_version, kind)]
    except KeyError:
        fail(f"cannot derive a race-safe delete path for {api_version}/{kind}")
    prefix = "/api/v1" if api_version == "v1" else f"/apis/{api_version}"
    if namespaced:
        return (
            f"{prefix}/namespaces/{urllib.parse.quote(namespace, safe='')}/"
            f"{plural}/{urllib.parse.quote(name, safe='')}"
        )
    return f"{prefix}/{plural}/{urllib.parse.quote(name, safe='')}"


def purge(
    kube: list[str],
    documents: list[dict[str, Any]],
    live: dict[tuple[str, str, str], dict[str, Any]],
) -> None:
    order = {"DaemonSet": 0, "SecurityContextConstraints": 1, "ServiceAccount": 2}
    for document in sorted(
        documents, key=lambda item: order.get(identity(item)[0], 99)
    ):
        resource_identity = identity(document)
        metadata = (live.get(resource_identity) or {}).get("metadata") or {}
        uid = str(metadata.get("uid") or "")
        resource_version = str(metadata.get("resourceVersion") or "")
        if not uid or not resource_version:
            fail(
                f"{resource_identity[0]}/{resource_identity[1]}/{resource_identity[2]} "
                "lacks UID/resourceVersion delete preconditions"
            )
        options = {
            "apiVersion": "v1",
            "kind": "DeleteOptions",
            "preconditions": {"uid": uid, "resourceVersion": resource_version},
            "propagationPolicy": "Foreground",
        }
        run(
            kube,
            ["delete", "--raw", raw_resource_path(document), "-f", "-"],
            stdin=json.dumps(options, separators=(",", ":")),
            suppress_failure_output=True,
        )


def main() -> int:
    args = parse_args()
    try:
        _, contract = load_metadata(args.metadata)
        documents = expected_documents(contract)
        kube = kube_command(args)
        live = fetch_owned(kube, documents)
        if args.mode == "validate":
            validate_health(kube, contract, live)
            print(
                "OBI ownership, digest/config identity, rollout, node coverage, and bounded logs: OK"
            )
        else:
            purge(kube, documents, live)
            print("Purged owned OBI DaemonSet, optional SCC, and ServiceAccount.")
    except ObiError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

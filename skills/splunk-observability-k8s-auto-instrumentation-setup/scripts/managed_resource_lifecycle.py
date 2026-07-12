#!/usr/bin/env python3
"""Race-safe create, replace, and delete for rendered owned Kubernetes objects."""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError as exc:  # pragma: no cover - environment guard
    raise SystemExit("ERROR: PyYAML is required for managed resource lifecycle operations.") from exc


SKILL = "splunk-observability-k8s-auto-instrumentation-setup"
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
RESOURCE_TYPES = {
    ("opentelemetry.io/v1alpha1", "Instrumentation"): (
        "instrumentations.opentelemetry.io",
        "instrumentations",
        True,
    ),
    ("v1", "ServiceAccount"): ("serviceaccounts", "serviceaccounts", True),
    ("apps/v1", "DaemonSet"): ("daemonsets.apps", "daemonsets", True),
    ("security.openshift.io/v1", "SecurityContextConstraints"): (
        "securitycontextconstraints.security.openshift.io",
        "securitycontextconstraints",
        False,
    ),
}


class LifecycleError(RuntimeError):
    """A managed-resource ownership or race-safety invariant failed."""


def fail(message: str) -> None:
    raise LifecycleError(message)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("apply", "delete"), required=True)
    parser.add_argument("--manifest", action="append", required=True)
    parser.add_argument("--kubectl-bin", default="kubectl")
    parser.add_argument("--kube-context", default="")
    return parser.parse_args()


def kube_command(args: argparse.Namespace) -> list[str]:
    command = [args.kubectl_bin]
    if args.kube_context:
        command.extend(["--context", args.kube_context])
    return command


def run(
    kube: list[str],
    arguments: list[str],
    *,
    stdin: str | None = None,
    allow_empty: bool = False,
) -> str:
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
        fail(f"kubectl operation failed to execute: {type(exc).__name__}")
    if result.returncode != 0:
        fail("kubectl operation failed; command output suppressed")
    if len(result.stdout.encode("utf-8", "replace")) > MAX_RESPONSE_BYTES:
        fail("kubectl response exceeded the validation limit")
    if not allow_empty and not result.stdout.strip():
        fail("kubectl operation returned an empty response")
    return result.stdout


def load_documents(paths: list[str]) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for raw_path in paths:
        path = Path(raw_path)
        try:
            if path.is_symlink() or not path.is_file():
                fail("managed manifest must be a regular, non-symlink file")
            loaded = [item for item in yaml.safe_load_all(path.read_text(encoding="utf-8")) if item]
        except (OSError, yaml.YAMLError) as exc:
            fail(f"managed manifest could not be parsed: {type(exc).__name__}")
        if not loaded or any(not isinstance(item, dict) for item in loaded):
            fail("managed manifest contains no objects or a non-object document")
        documents.extend(loaded)
    identities = [identity(document) for document in documents]
    if len(identities) != len(set(identities)):
        fail("managed manifests contain duplicate resource identities")
    return documents


def resource_type(document: dict[str, Any]) -> tuple[str, str, bool]:
    key = (str(document.get("apiVersion") or ""), str(document.get("kind") or ""))
    if key not in RESOURCE_TYPES:
        fail(f"unsupported managed Kubernetes resource type {key[0]}/{key[1]}")
    return RESOURCE_TYPES[key]


def identity(document: dict[str, Any]) -> tuple[str, str, str, str]:
    metadata = document.get("metadata") or {}
    api_version = str(document.get("apiVersion") or "")
    kind = str(document.get("kind") or "")
    namespace = str(metadata.get("namespace") or "")
    name = str(metadata.get("name") or "")
    _, _, namespaced = resource_type(document)
    if not api_version or not kind or not name or (namespaced and not namespace) or (not namespaced and namespace):
        fail("managed manifest contains an incomplete or invalid resource identity")
    labels = metadata.get("labels") or {}
    if (
        not isinstance(labels, dict)
        or not labels.get("app.kubernetes.io/name")
        or labels.get("app.kubernetes.io/managed-by") != SKILL
    ):
        fail(f"{kind}/{namespace}/{name} is missing exact ownership labels")
    return api_version, kind, namespace, name


def lookup_arguments(document: dict[str, Any]) -> list[str]:
    _, kind, namespace, name = identity(document)
    lookup_name, _, namespaced = resource_type(document)
    arguments: list[str] = []
    if namespaced:
        arguments.extend(["-n", namespace])
    arguments.extend(["get", lookup_name, name, "-o", "json", "--ignore-not-found"])
    return arguments


def fetch(kube: list[str], desired: dict[str, Any]) -> dict[str, Any] | None:
    output = run(kube, lookup_arguments(desired), allow_empty=True)
    if not output.strip():
        return None
    try:
        live = json.loads(output)
    except json.JSONDecodeError:
        fail("kubectl lookup returned invalid JSON")
    if not isinstance(live, dict) or identity(live) != identity(desired):
        fail("kubectl lookup returned a different managed resource")
    desired_labels = (desired.get("metadata") or {}).get("labels") or {}
    live_labels = (live.get("metadata") or {}).get("labels") or {}
    for key in ("app.kubernetes.io/name", "app.kubernetes.io/managed-by"):
        if live_labels.get(key) != desired_labels.get(key):
            _, kind, namespace, name = identity(desired)
            fail(f"{kind}/{namespace}/{name} is foreign or has ambiguous ownership")
    live_metadata = live.get("metadata") or {}
    if not live_metadata.get("uid") or not live_metadata.get("resourceVersion"):
        fail("live managed resource lacks UID/resourceVersion preconditions")
    return live


def preflight(
    kube: list[str], documents: list[dict[str, Any]]
) -> list[tuple[dict[str, Any], dict[str, Any] | None]]:
    # Inspect every identity before the first mutation so a later foreign object
    # cannot leave an earlier object partially updated.
    return [(document, fetch(kube, document)) for document in documents]


def apply_resources(
    kube: list[str], states: list[tuple[dict[str, Any], dict[str, Any] | None]]
) -> None:
    for desired, live in states:
        payload = copy.deepcopy(desired)
        if live is None:
            run(
                kube,
                ["create", "-f", "-"],
                stdin=json.dumps(payload, separators=(",", ":")),
                allow_empty=True,
            )
            continue
        live_metadata = live["metadata"]
        payload_metadata = payload.setdefault("metadata", {})
        payload_metadata["uid"] = live_metadata["uid"]
        payload_metadata["resourceVersion"] = live_metadata["resourceVersion"]
        run(
            kube,
            ["replace", "-f", "-"],
            stdin=json.dumps(payload, separators=(",", ":")),
            allow_empty=True,
        )


def raw_resource_path(document: dict[str, Any]) -> str:
    api_version, _, namespace, name = identity(document)
    _, plural, namespaced = resource_type(document)
    encoded_name = urllib.parse.quote(name, safe="")
    if api_version == "v1":
        prefix = "/api/v1"
    else:
        prefix = "/apis/" + urllib.parse.quote(api_version, safe="/")
    if namespaced:
        return (
            f"{prefix}/namespaces/{urllib.parse.quote(namespace, safe='')}/"
            f"{plural}/{encoded_name}"
        )
    return f"{prefix}/{plural}/{encoded_name}"


def delete_resources(
    kube: list[str], states: list[tuple[dict[str, Any], dict[str, Any] | None]]
) -> None:
    for desired, live in reversed(states):
        if live is None:
            continue
        metadata = live["metadata"]
        options = {
            "apiVersion": "v1",
            "kind": "DeleteOptions",
            "preconditions": {
                "uid": metadata["uid"],
                "resourceVersion": metadata["resourceVersion"],
            },
            "propagationPolicy": "Foreground",
        }
        run(
            kube,
            ["delete", "--raw", raw_resource_path(desired), "-f", "-"],
            stdin=json.dumps(options, separators=(",", ":")),
            allow_empty=True,
        )

    for desired, live in states:
        if live is None:
            continue
        for _ in range(30):
            if fetch(kube, desired) is None:
                break
            time.sleep(1)
        else:
            _, kind, namespace, name = identity(desired)
            fail(f"{kind}/{namespace}/{name} did not complete deletion")


def main() -> int:
    args = parse_args()
    try:
        documents = load_documents(args.manifest)
        kube = kube_command(args)
        states = preflight(kube, documents)
        if args.mode == "apply":
            apply_resources(kube, states)
            print(f"Applied {len(states)} preflighted owned Kubernetes resource(s).")
        else:
            delete_resources(kube, states)
            print(f"Deleted {sum(live is not None for _, live in states)} preflighted owned Kubernetes resource(s).")
    except LifecycleError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

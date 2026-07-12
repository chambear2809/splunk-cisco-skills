#!/usr/bin/env python3
"""Transactional, fail-closed annotation snapshot and restore planner."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.parse
from pathlib import Path
from typing import Any


SKILL = "splunk-observability-k8s-auto-instrumentation-setup"
SNAPSHOT_VERSION = f"{SKILL}/annotation-snapshot/v1"
MANAGED_PREFIX = "instrumentation.opentelemetry.io/"
EXPECTED_LABELS = {
    "app.kubernetes.io/name": "splunk-otel-auto-instrumentation",
    "app.kubernetes.io/managed-by": SKILL,
    "splunk.com/ttl": "7d",
}


class BackupError(RuntimeError):
    """A transactional backup invariant could not be proven."""


def fail(message: str) -> None:
    raise BackupError(message)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("apply-plan", "capture", "restore-plan", "verify", "purge"),
        required=True,
    )
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--target", action="append", default=[])
    parser.add_argument("--target-all", action="store_true")
    parser.add_argument("--kubectl-bin", default="kubectl")
    parser.add_argument("--kube-context", default="")
    return parser.parse_args()


def read_metadata(path: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot parse metadata.json: {exc}")
    if not isinstance(value, dict) or value.get("skill") != SKILL:
        fail("metadata.json has the wrong skill identity")
    preflight = value.get("preflight")
    if not isinstance(preflight, dict) or preflight.get("errors"):
        fail("metadata.json contains malformed or unresolved preflight errors")
    return value


def selected_groups(
    metadata: dict[str, Any], args: argparse.Namespace
) -> list[dict[str, Any]]:
    if args.target and args.target_all:
        fail("--target and --target-all are mutually exclusive")
    if not args.target and not args.target_all:
        fail("pass --target Kind/namespace/name or --target-all")
    rows = metadata.get("targets")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        fail("metadata.json targets must be a list of objects")
    available = {str(row.get("target") or "") for row in rows}
    if "" in available:
        fail("metadata.json contains a target without an identity")
    requested = set(args.target)
    missing = sorted(requested - available)
    if missing:
        fail("requested target(s) are absent from metadata.json: " + ", ".join(missing))
    chosen = (
        rows
        if args.target_all
        else [row for row in rows if row.get("target") in requested]
    )
    if not chosen:
        fail("target selection resolved to no rendered workloads")

    grouped: dict[str, dict[str, Any]] = {}
    for row in chosen:
        target = str(row.get("target") or "")
        identity = (
            str(row.get("kind") or ""),
            str(row.get("namespace") or ""),
            str(row.get("name") or ""),
        )
        if not all(identity) or target != "/".join(identity):
            fail(f"metadata target {target!r} has an inconsistent identity")
        key = str(row.get("key") or "")
        annotations = row.get("annotations")
        if not key or not isinstance(annotations, dict) or not annotations:
            fail(f"metadata target {target} has no backup key or managed annotations")
        if any(not str(name).startswith(MANAGED_PREFIX) for name in annotations):
            fail(f"metadata target {target} contains an unmanaged annotation")
        group = grouped.setdefault(
            target,
            {
                "target": target,
                "kind": identity[0],
                "namespace": identity[1],
                "name": identity[2],
                "key": key,
                "annotations": {},
            },
        )
        if group["key"] != key:
            fail(f"metadata target {target} has conflicting backup keys")
        for raw_name, raw_value in annotations.items():
            name, value = str(raw_name), str(raw_value)
            if name in group["annotations"] and group["annotations"][name] != value:
                fail(
                    f"metadata target {target} has conflicting managed annotation values"
                )
            group["annotations"][name] = value
    keys = [group["key"] for group in grouped.values()]
    if len(keys) != len(set(keys)):
        fail("metadata target backup keys collide")
    return list(grouped.values())


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
        )
    except OSError as exc:
        fail(f"could not execute kubectl: {exc}")
    if result.returncode != 0:
        detail = (
            result.stderr.strip()
            or result.stdout.strip()
            or f"exit {result.returncode}"
        )
        fail(f"kubectl {' '.join(arguments)} failed: {detail}")
    if not allow_empty and not result.stdout.strip():
        fail(f"kubectl {' '.join(arguments)} returned an empty response")
    return result.stdout


def parse_object(text: str, *, context: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        fail(f"{context} returned invalid JSON: {exc}")
    if not isinstance(value, dict):
        fail(f"{context} returned a non-object JSON value")
    return value


def current_managed_values(
    kube: list[str], group: dict[str, Any]
) -> tuple[dict[str, str], str]:
    text = run(
        kube,
        [
            "-n",
            group["namespace"],
            "get",
            group["kind"].lower(),
            group["name"],
            "-o",
            "json",
        ],
    )
    workload = parse_object(text, context=group["target"])
    metadata = workload.get("metadata") or {}
    if (
        workload.get("kind") != group["kind"]
        or metadata.get("namespace") != group["namespace"]
        or metadata.get("name") != group["name"]
    ):
        fail(f"{group['target']} lookup returned a different resource")
    resource_version = str(metadata.get("resourceVersion") or "")
    if not resource_version:
        fail(
            f"{group['target']} has no resourceVersion for an optimistic patch precondition"
        )
    annotations = (
        ((workload.get("spec") or {}).get("template") or {}).get("metadata") or {}
    ).get("annotations") or {}
    if not isinstance(annotations, dict):
        fail(f"{group['target']} pod-template annotations are not an object")
    result: dict[str, str] = {}
    for key in group["annotations"]:
        if key in annotations:
            value = annotations[key]
            if not isinstance(value, str):
                fail(f"{group['target']} annotation {key} is not a string")
            result[key] = value
    return result, resource_version


def configmap_identity(metadata: dict[str, Any]) -> tuple[str, str]:
    namespace = str(metadata.get("namespace") or "")
    name = str(metadata.get("backup_configmap") or "")
    if not namespace or not name:
        fail("metadata.json has no backup ConfigMap identity")
    return namespace, name


def get_configmap(
    kube: list[str], metadata: dict[str, Any], *, optional: bool
) -> dict[str, Any] | None:
    namespace, name = configmap_identity(metadata)
    output = run(
        kube,
        ["-n", namespace, "get", "configmap", name, "-o", "json", "--ignore-not-found"],
        allow_empty=optional,
    )
    if not output.strip():
        return None
    obj = parse_object(output, context=f"backup ConfigMap {namespace}/{name}")
    resource_metadata = obj.get("metadata") or {}
    labels = resource_metadata.get("labels") or {}
    if (
        obj.get("apiVersion") != "v1"
        or obj.get("kind") != "ConfigMap"
        or resource_metadata.get("namespace") != namespace
        or resource_metadata.get("name") != name
        or any(labels.get(key) != value for key, value in EXPECTED_LABELS.items())
    ):
        fail(f"backup ConfigMap {namespace}/{name} is not owned by {SKILL}")
    data = obj.get("data", {})
    if not isinstance(data, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in data.items()
    ):
        fail(f"backup ConfigMap {namespace}/{name} data is malformed")
    return obj


def decode_snapshot(raw: str, group: dict[str, Any]) -> dict[str, Any]:
    try:
        snapshot = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        fail(f"backup snapshot {group['key']} is invalid JSON: {exc}")
    expected_keys = sorted(group["annotations"])
    if (
        not isinstance(snapshot, dict)
        or snapshot.get("apiVersion") != SNAPSHOT_VERSION
        or snapshot.get("target") != group["target"]
    ):
        fail(f"backup snapshot {group['key']} has the wrong version or target identity")
    managed_keys = snapshot.get("managedKeys")
    values = snapshot.get("values")
    if (
        managed_keys != expected_keys
        or not isinstance(values, dict)
        or any(
            key not in expected_keys or not isinstance(value, str)
            for key, value in values.items()
        )
    ):
        fail(f"backup snapshot {group['key']} is corrupt or incomplete")
    return snapshot


def encode_snapshot(group: dict[str, Any], values: dict[str, str]) -> str:
    return json.dumps(
        {
            "apiVersion": SNAPSHOT_VERSION,
            "target": group["target"],
            "managedKeys": sorted(group["annotations"]),
            "values": values,
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def apply_plan(
    groups: list[dict[str, Any]], resource_versions: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    return [
        {
            "target": group["target"],
            "kind": group["kind"],
            "namespace": group["namespace"],
            "name": group["name"],
            "patch": {
                **(
                    {
                        "metadata": {
                            "resourceVersion": resource_versions[group["target"]]
                        }
                    }
                    if resource_versions is not None
                    else {}
                ),
                "spec": {
                    "template": {"metadata": {"annotations": group["annotations"]}}
                },
            },
        }
        for group in groups
    ]


def capture(
    metadata: dict[str, Any], groups: list[dict[str, Any]], kube: list[str]
) -> list[dict[str, Any]]:
    # Read and validate every workload before any ConfigMap write.
    current = {group["target"]: current_managed_values(kube, group) for group in groups}
    existing = get_configmap(kube, metadata, optional=True)
    namespace, name = configmap_identity(metadata)
    if existing is None:
        data: dict[str, str] = {}
        resource_version = ""
    else:
        data = dict(existing.get("data") or {})
        resource_version = str(
            (existing.get("metadata") or {}).get("resourceVersion") or ""
        )
        if not resource_version:
            fail(f"backup ConfigMap {namespace}/{name} has no resourceVersion")

    for group in groups:
        raw = data.get(group["key"])
        if raw is None:
            data[group["key"]] = encode_snapshot(group, current[group["target"]][0])
            continue
        try:
            snapshot = json.loads(raw)
        except json.JSONDecodeError as exc:
            fail(f"backup snapshot {group['key']} is invalid JSON: {exc}")
        # Permit a controlled extension when a later render adds another
        # managed annotation to the same workload. Existing original values
        # remain immutable; only newly managed keys are captured now.
        if (
            not isinstance(snapshot, dict)
            or snapshot.get("apiVersion") != SNAPSHOT_VERSION
            or snapshot.get("target") != group["target"]
        ):
            fail(
                f"backup snapshot {group['key']} has the wrong version or target identity"
            )
        old_keys = snapshot.get("managedKeys")
        old_values = snapshot.get("values")
        if (
            not isinstance(old_keys, list)
            or len(old_keys) != len(set(old_keys))
            or not isinstance(old_values, dict)
        ):
            fail(f"backup snapshot {group['key']} is corrupt")
        if any(
            key not in old_keys or not isinstance(value, str)
            for key, value in old_values.items()
        ):
            fail(f"backup snapshot {group['key']} is corrupt")
        expected_keys = sorted(group["annotations"])
        if not set(old_keys).issubset(expected_keys):
            fail(
                f"backup snapshot {group['key']} contains stale managed keys; restore before shrinking the target"
            )
        for key in set(expected_keys) - set(old_keys):
            if key in current[group["target"]][0]:
                old_values[key] = current[group["target"]][0][key]
        data[group["key"]] = encode_snapshot(group, old_values)

    cm: dict[str, Any] = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": name, "namespace": namespace, "labels": EXPECTED_LABELS},
        "data": data,
    }
    payload = json.dumps(cm, separators=(",", ":"))
    if existing is None:
        run(kube, ["create", "-f", "-"], stdin=payload, allow_empty=True)
    else:
        cm["metadata"]["resourceVersion"] = resource_version
        run(
            kube,
            ["replace", "-f", "-"],
            stdin=json.dumps(cm, separators=(",", ":")),
            allow_empty=True,
        )

    verified = get_configmap(kube, metadata, optional=False)
    assert verified is not None
    verified_data = verified.get("data") or {}
    for group in groups:
        decode_snapshot(verified_data.get(group["key"]), group)
        if verified_data.get(group["key"]) != data[group["key"]]:
            fail(
                f"backup snapshot {group['key']} changed during transactional verification"
            )
    return apply_plan(
        groups,
        {target: state[1] for target, state in current.items()},
    )


def restore_plan(
    metadata: dict[str, Any], groups: list[dict[str, Any]], kube: list[str]
) -> list[dict[str, Any]]:
    # Validate every workload and every selected snapshot before returning the
    # first patch. The caller therefore cannot partially restore due to a late
    # missing/corrupt snapshot.
    current = {group["target"]: current_managed_values(kube, group) for group in groups}
    configmap = get_configmap(kube, metadata, optional=False)
    if configmap is None:
        namespace, name = configmap_identity(metadata)
        fail(f"backup ConfigMap {namespace}/{name} is missing")
    data = configmap.get("data") or {}
    plan = []
    for group in groups:
        if group["key"] not in data:
            fail(f"backup snapshot for {group['target']} is missing")
        snapshot = decode_snapshot(data[group["key"]], group)
        prior = snapshot["values"]
        annotations = {
            key: prior[key] if key in prior else None for key in snapshot["managedKeys"]
        }
        plan.append(
            {
                "target": group["target"],
                "kind": group["kind"],
                "namespace": group["namespace"],
                "name": group["name"],
                "patch": {
                    "metadata": {"resourceVersion": current[group["target"]][1]},
                    "spec": {"template": {"metadata": {"annotations": annotations}}},
                },
            }
        )
    return plan


def verify(
    metadata: dict[str, Any], groups: list[dict[str, Any]], kube: list[str]
) -> None:
    configmap = get_configmap(kube, metadata, optional=False)
    if configmap is None:
        namespace, name = configmap_identity(metadata)
        fail(f"backup ConfigMap {namespace}/{name} is missing")
    data = configmap.get("data") or {}
    for group in groups:
        if group["key"] not in data:
            fail(f"backup snapshot for {group['target']} is missing")
        decode_snapshot(data[group["key"]], group)


def purge_backup(
    metadata: dict[str, Any],
    groups: list[dict[str, Any]],
    kube: list[str],
    *,
    target_all: bool,
) -> None:
    if not target_all:
        fail("backup purge requires --target-all")
    configmap = get_configmap(kube, metadata, optional=False)
    if configmap is None:
        namespace, name = configmap_identity(metadata)
        fail(f"backup ConfigMap {namespace}/{name} is missing")
    data = configmap.get("data") or {}
    expected_keys = {group["key"] for group in groups}
    if set(data) != expected_keys:
        fail("backup ConfigMap key coverage differs from metadata.json; refusing destructive purge")
    for group in groups:
        decode_snapshot(data[group["key"]], group)
    namespace, name = configmap_identity(metadata)
    resource_metadata = configmap.get("metadata") or {}
    uid = str(resource_metadata.get("uid") or "")
    resource_version = str(resource_metadata.get("resourceVersion") or "")
    if not uid or not resource_version:
        fail("backup ConfigMap lacks UID/resourceVersion delete preconditions")
    path = (
        f"/api/v1/namespaces/{urllib.parse.quote(namespace, safe='')}/"
        f"configmaps/{urllib.parse.quote(name, safe='')}"
    )
    options = {
        "apiVersion": "v1",
        "kind": "DeleteOptions",
        "preconditions": {"uid": uid, "resourceVersion": resource_version},
        "propagationPolicy": "Foreground",
    }
    run(
        kube,
        ["delete", "--raw", path, "-f", "-"],
        stdin=json.dumps(options, separators=(",", ":")),
        allow_empty=True,
    )


def main() -> int:
    args = parse_args()
    try:
        metadata = read_metadata(args.metadata)
        groups = selected_groups(metadata, args)
        if args.mode == "apply-plan":
            print(json.dumps(apply_plan(groups), separators=(",", ":")))
            return 0
        kube = kube_command(args)
        if args.mode == "capture":
            print(json.dumps(capture(metadata, groups, kube), separators=(",", ":")))
        elif args.mode == "restore-plan":
            print(
                json.dumps(restore_plan(metadata, groups, kube), separators=(",", ":"))
            )
        elif args.mode == "verify":
            verify(metadata, groups, kube)
            print(f"Verified {len(groups)} annotation snapshot(s).")
        else:
            purge_backup(metadata, groups, kube, target_all=args.target_all)
            print(f"Purged verified backup ConfigMap for {len(groups)} workload(s).")
    except BackupError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

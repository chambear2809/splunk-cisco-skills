#!/usr/bin/env python3
"""Validate rendered Collector workloads without reading Helm release Secrets."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


class ValidationError(RuntimeError):
    """A read-only Kubernetes validation failed."""


def bounded_name(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value.rstrip("-")
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return f"{value[: limit - len(digest) - 1].rstrip('-')}-{digest}"


def collector_name(release: str) -> str:
    chart = "splunk-otel-collector"
    value = release if chart in release else f"{release}-{chart}"
    return value[:63].rstrip("-")


def expected_controllers(metadata: dict[str, Any]) -> list[tuple[str, str]]:
    k8s = metadata.get("kubernetes") or {}
    release = str(k8s.get("release_name") or "")
    collector = collector_name(release)
    expected: list[tuple[str, str]] = []
    if k8s.get("agent_enabled"):
        expected.append(("DaemonSet", f"{collector}-agent"))
    if k8s.get("gateway_enabled"):
        expected.append(("Deployment", collector))
    if k8s.get("cluster_receiver_enabled"):
        receiver = f"{collector}-k8s-cluster-receiver"
        limit = 52 if k8s.get("distribution") == "eks/fargate" else 63
        kind = "StatefulSet" if k8s.get("distribution") == "eks/fargate" else "Deployment"
        expected.append((kind, receiver[:limit].rstrip("-")))
    if k8s.get("operator_enabled"):
        raw = release if "operator" in release else f"{release}-operator"
        expected.append(("Deployment", bounded_name(raw, 31)))
    if k8s.get("target_allocator_enabled"):
        raw = release if "targetallocator" in release else f"{release}-targetallocator"
        expected.append(("Deployment", f"{bounded_name(raw, 60)}-ta"))
    if k8s.get("obi_enabled"):
        raw = release if "obi" in release else f"{release}-obi"
        expected.append(("DaemonSet", bounded_name(raw, 63)))
    return expected


def command(kubectl: list[str], args: list[str]) -> dict[str, Any]:
    proc = subprocess.run(
        kubectl + args,
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"
        raise ValidationError(f"kubectl {' '.join(args[:5])} failed: {detail}")
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"kubectl returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValidationError("kubectl returned a non-object JSON payload")
    return payload


def controller_ready(obj: dict[str, Any]) -> None:
    kind = str(obj.get("kind") or "")
    meta = obj.get("metadata") or {}
    spec = obj.get("spec") or {}
    status = obj.get("status") or {}
    identity = f"{kind}/{meta.get('namespace', '')}/{meta.get('name', '')}"
    generation = int(meta.get("generation") or 0)
    observed = int(status.get("observedGeneration") or 0)
    if generation and observed < generation:
        raise ValidationError(f"{identity} has not observed its latest generation")
    if kind == "DaemonSet":
        desired = int(status.get("desiredNumberScheduled") or 0)
        ready = int(status.get("numberReady") or 0)
        updated = int(status.get("updatedNumberScheduled") or 0)
        unavailable = int(status.get("numberUnavailable") or 0)
        healthy = desired > 0 and ready == desired and updated == desired and unavailable == 0
    else:
        desired = int(spec.get("replicas", 1))
        ready = int(status.get("readyReplicas") or 0)
        updated = int(status.get("updatedReplicas") or 0)
        healthy = desired > 0 and ready == desired and updated == desired
        if kind == "Deployment":
            healthy = healthy and int(status.get("availableReplicas") or 0) == desired
        elif kind == "StatefulSet":
            healthy = healthy and int(status.get("currentReplicas") or 0) == desired
    if not healthy:
        raise ValidationError(f"{identity} is not fully rolled out and Ready")


def pods_ready(payload: dict[str, Any], namespace: str, release: str) -> int:
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise ValidationError(
            f"no Collector pods found in {namespace} for app.kubernetes.io/instance={release}"
        )
    active = 0
    for pod in items:
        meta = pod.get("metadata") or {}
        status = pod.get("status") or {}
        name = str(meta.get("name") or "<unknown>")
        phase = str(status.get("phase") or "")
        if phase == "Succeeded":
            continue
        active += 1
        ready = any(
            row.get("type") == "Ready" and row.get("status") == "True"
            for row in (status.get("conditions") or [])
        )
        if phase != "Running" or not ready or meta.get("deletionTimestamp"):
            raise ValidationError(f"Pod/{namespace}/{name} is not active, Running, and Ready")
    if active == 0:
        raise ValidationError("Collector pod query returned only completed Job pods")
    return active


def verify_images(verifier: Path, payload: dict[str, Any]) -> None:
    if not verifier.is_file() or verifier.is_symlink():
        raise ValidationError(f"image verifier is missing or a symlink: {verifier}")
    proc = subprocess.run(
        [sys.executable, str(verifier), "--verify-object-list-json"],
        input=json.dumps(payload),
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise ValidationError(proc.stderr.strip() or proc.stdout.strip() or "live image validation failed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--image-verifier", required=True)
    parser.add_argument("--kube-context", default="")
    parser.add_argument("--kubectl-bin", default="kubectl", help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        metadata = json.loads(Path(args.metadata).read_text(encoding="utf-8"))
        k8s = metadata.get("kubernetes") or {}
        if not k8s.get("rendered"):
            raise ValidationError("metadata does not describe a rendered Kubernetes packet")
        namespace = str(k8s.get("namespace") or "")
        release = str(k8s.get("release_name") or "")
        if not namespace or not release:
            raise ValidationError("metadata is missing Kubernetes namespace or release_name")
        expected = expected_controllers(metadata)
        if not expected:
            raise ValidationError("metadata enables no Kubernetes workload controllers")

        kubectl = [args.kubectl_bin]
        if args.kube_context:
            kubectl += ["--context", args.kube_context]
        for kind, name in expected:
            obj = command(
                kubectl,
                ["-n", namespace, "get", kind.lower(), name, "-o", "json", "--request-timeout=30s"],
            )
            if obj.get("kind") != kind or (obj.get("metadata") or {}).get("name") != name:
                raise ValidationError(f"Kubernetes returned the wrong object for {kind}/{name}")
            controller_ready(obj)
            print(f"  {kind}/{namespace}/{name}: Ready")

        pods = command(
            kubectl,
            [
                "-n",
                namespace,
                "get",
                "pods",
                "-l",
                f"app.kubernetes.io/instance={release}",
                "-o",
                "json",
                "--request-timeout=30s",
            ],
        )
        count = pods_ready(pods, namespace, release)
        verify_images(Path(args.image_verifier), pods)
        print(f"  {count} active Collector pod(s): Ready with audited image digests")

        if k8s.get("operator_enabled"):
            name = collector_name(release)
            obj = command(
                kubectl,
                ["-n", namespace, "get", "instrumentation", name, "-o", "json", "--request-timeout=30s"],
            )
            if obj.get("kind") != "Instrumentation" or (obj.get("metadata") or {}).get("name") != name:
                raise ValidationError(f"Kubernetes returned the wrong Instrumentation/{name} object")
            verify_images(Path(args.image_verifier), {"items": [obj]})
            print(f"  Instrumentation/{namespace}/{name}: present with audited image digests")
    except (OSError, ValueError, ValidationError, subprocess.TimeoutExpired) as exc:
        print(f"ERROR: secret-free Kubernetes workload validation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

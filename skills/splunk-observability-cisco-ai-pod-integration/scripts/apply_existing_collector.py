#!/usr/bin/env python3
"""Apply the AI Pod overlay to an existing Splunk OTel Collector Helm release.

This is intentionally owned by the AI Pod umbrella skill instead of the
generated handoff. Live validation found two drift hazards that generic
``helm --reuse-values`` cannot correct safely:

* stale ``receiver_creator/nvidia`` values survive chart upgrades and collide
  with the Cisco-safe ``receiver_creator/dcgm-cisco`` receiver;
* Intersight requires the OTLP receiver to be wired into the metrics pipeline,
  otherwise the collector can answer gRPC without implementing MetricsService.

The script reads the current Helm values, removes inline token material before
writing a temporary values file, merges the rendered skill overlay, sanitizes
known drift, upgrades the existing release, and restarts the collector plus the
Intersight workload so validation observes fresh logs.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


def load_yaml_module():
    try:
        import yaml  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "ERROR: PyYAML is required. Install with 'python3 -m pip install -r requirements-agent.txt'."
        ) from exc
    return yaml


yaml = load_yaml_module()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--release", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--chart-ref", required=True)
    parser.add_argument("--o11y-token-file", required=True)
    parser.add_argument("--timeout", default="5m")
    return parser.parse_args()


def run(cmd: list[str], *, capture: bool = False, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        check=False,
    )
    if check and result.returncode != 0:
        if capture:
            if result.stdout:
                print(result.stdout, end="")
            if result.stderr:
                print(result.stderr, end="", file=sys.stderr)
        raise SystemExit(f"ERROR: command failed ({result.returncode}): {' '.join(cmd)}")
    return result


def command_supports(cmd: list[str], flag: str) -> bool:
    result = run(cmd, capture=True, check=False)
    return result.returncode == 0 and flag in ((result.stdout or "") + (result.stderr or ""))


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        elif isinstance(value, list) and isinstance(result.get(key), list):
            seen: set[str] = set()
            merged: list[Any] = []
            for item in result[key] + value:
                fingerprint = json.dumps(item, sort_keys=True) if isinstance(item, (dict, list)) else str(item)
                if fingerprint not in seen:
                    seen.add(fingerprint)
                    merged.append(item)
            result[key] = merged
        else:
            result[key] = value
    return result


def ensure_path(root: dict[str, Any], *keys: str) -> dict[str, Any]:
    cursor: dict[str, Any] = root
    for key in keys:
        value = cursor.setdefault(key, {})
        if not isinstance(value, dict):
            value = {}
            cursor[key] = value
        cursor = value
    return cursor


def remove_inline_tokens(values: dict[str, Any]) -> None:
    observability = values.get("splunkObservability")
    if isinstance(observability, dict):
        observability.pop("accessToken", None)
        observability.pop("access_token", None)


def remove_receiver_from_pipelines(values: dict[str, Any], receiver_name: str) -> int:
    removed = 0
    pipelines = (
        values.get("agent", {})
        .get("config", {})
        .get("service", {})
        .get("pipelines", {})
    )
    if not isinstance(pipelines, dict):
        return removed
    for pipeline in pipelines.values():
        if not isinstance(pipeline, dict):
            continue
        receivers = pipeline.get("receivers")
        if not isinstance(receivers, list):
            continue
        next_receivers = [receiver for receiver in receivers if receiver != receiver_name]
        removed += len(receivers) - len(next_receivers)
        pipeline["receivers"] = next_receivers
    return removed


def overlay_pipeline(values: dict[str, Any], overlay: dict[str, Any], pipeline_name: str) -> None:
    overlay_pipeline_value = (
        overlay.get("agent", {})
        .get("config", {})
        .get("service", {})
        .get("pipelines", {})
        .get(pipeline_name)
    )
    if isinstance(overlay_pipeline_value, dict):
        pipelines = ensure_path(values, "agent", "config", "service", "pipelines")
        pipelines[pipeline_name] = overlay_pipeline_value


def nested_contains(value: Any, needle: str) -> bool:
    if isinstance(value, dict):
        return any(nested_contains(item, needle) for item in value.values())
    if isinstance(value, list):
        return any(nested_contains(item, needle) for item in value)
    return value == needle


def secret_exists(cli: str, namespace: str, name: str) -> bool:
    return run([cli, "-n", namespace, "get", "secret", name], capture=True, check=False).returncode == 0


def prune_nexus_without_secret(values: dict[str, Any], cli: str | None, namespace: str) -> int:
    cluster_receiver = values.get("clusterReceiver")
    if not isinstance(cluster_receiver, dict):
        return 0
    if not nested_contains(cluster_receiver, "cisco-nexus-ssh"):
        return 0
    if cli and secret_exists(cli, namespace, "cisco-nexus-ssh"):
        return 0
    # The Nexus child render intentionally references this Secret, but an
    # existing-collector Intersight fix should not wedge the chart rollout when
    # Nexus credentials have not been provisioned. Removing the explicit
    # clusterReceiver overlay lets the chart fall back to its existing defaults.
    values.pop("clusterReceiver", None)
    return 1


def sanitize(values: dict[str, Any], overlay: dict[str, Any], cli: str | None, namespace: str) -> dict[str, int]:
    counters = {
        "removed_receiver_creator_nvidia": 0,
        "removed_pipeline_refs": 0,
        "added_otlp_metrics": 0,
        "pruned_nexus_without_secret": 0,
    }

    receivers = ensure_path(values, "agent", "config", "receivers")
    if "receiver_creator/nvidia" in receivers:
        del receivers["receiver_creator/nvidia"]
        counters["removed_receiver_creator_nvidia"] += 1

    receivers.setdefault(
        "otlp",
        {
            "protocols": {
                "grpc": {"endpoint": "0.0.0.0:4317"},
                "http": {"endpoint": "0.0.0.0:4318"},
            }
        },
    )

    counters["removed_pipeline_refs"] += remove_receiver_from_pipelines(values, "receiver_creator/nvidia")

    for pipeline_name in (
        "metrics/cisco-ai-pods",
        "metrics/nvidia-metrics",
        "metrics/nvidianim-metrics",
    ):
        overlay_pipeline(values, overlay, pipeline_name)

    metrics = ensure_path(values, "agent", "config", "service", "pipelines", "metrics")
    metrics_receivers = metrics.setdefault("receivers", [])
    if not isinstance(metrics_receivers, list):
        metrics_receivers = []
        metrics["receivers"] = metrics_receivers
    if "otlp" not in metrics_receivers:
        metrics_receivers.insert(0, "otlp")
        counters["added_otlp_metrics"] += 1

    counters["pruned_nexus_without_secret"] += prune_nexus_without_secret(values, cli, namespace)
    return counters


def kube_cli() -> str | None:
    return shutil.which("oc") or shutil.which("kubectl")


def rollout_status(cli: str, namespace: str, resource: str, timeout: str) -> None:
    run([cli, "-n", namespace, "rollout", "status", resource, f"--timeout={timeout}"])


def restart_matching_daemonsets(cli: str, namespace: str, release: str, timeout: str) -> None:
    labels = f"app=splunk-otel-collector,component=otel-collector-agent,release={release}"
    result = run(
        [
            cli,
            "-n",
            namespace,
            "get",
            "daemonset",
            "-l",
            labels,
            "-o",
            "jsonpath={range .items[*]}{.metadata.name}{'\\n'}{end}",
        ],
        capture=True,
    )
    names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not names:
        print(f"WARN: no Splunk OTel agent DaemonSet found with labels {labels}")
        return
    for name in names:
        resource = f"daemonset/{name}"
        print(f"Restarting {namespace}/{resource} so the collector process reloads the corrected config...")
        run([cli, "-n", namespace, "rollout", "restart", resource])
        rollout_status(cli, namespace, resource, timeout)


def restart_intersight_if_present(cli: str, timeout: str) -> None:
    result = run(
        [cli, "-n", "intersight-otel", "get", "deployment", "intersight-otel"],
        capture=True,
        check=False,
    )
    if result.returncode != 0:
        print("WARN: intersight-otel deployment not found; skipping Intersight restart.")
        return
    print("Restarting intersight-otel/deployment/intersight-otel for a fresh export attempt...")
    run([cli, "-n", "intersight-otel", "rollout", "restart", "deployment/intersight-otel"])
    rollout_status(cli, "intersight-otel", "deployment/intersight-otel", timeout)


def newest_running_pod(cli: str, namespace: str, label_selector: str) -> str:
    result = run(
        [
            cli,
            "-n",
            namespace,
            "get",
            "pods",
            "-l",
            label_selector,
            "-o",
            "json",
        ],
        capture=True,
        check=False,
    )
    if result.returncode != 0:
        return ""
    payload = json.loads(result.stdout or "{}")
    candidates = []
    for item in payload.get("items", []):
        metadata = item.get("metadata", {})
        status = item.get("status", {})
        if metadata.get("deletionTimestamp") or status.get("phase") != "Running":
            continue
        candidates.append((metadata.get("creationTimestamp", ""), metadata.get("name", "")))
    candidates.sort()
    return candidates[-1][1] if candidates else ""


def wait_for_clean_intersight_logs(cli: str, timeout_seconds: int = 240) -> None:
    deadline = time.time() + timeout_seconds
    last_sample = ""
    while time.time() < deadline:
        pod = newest_running_pod(cli, "intersight-otel", "app=intersight-otel")
        target = ["pod", pod] if pod else ["deployment", "intersight-otel"]
        result = run(
            [
                cli,
                "-n",
                "intersight-otel",
                "logs",
                "/".join(target),
                "--since=90s",
                "--tail=200",
            ],
            capture=True,
            check=False,
        )
        logs = (result.stdout or "") + (result.stderr or "")
        last_sample = logs
        if "unknown service opentelemetry.proto.collector.metrics.v1.MetricsService" in logs:
            raise SystemExit("ERROR: Intersight still reaches an endpoint without OTLP MetricsService.")
        if "Error sending metrics:" in logs:
            time.sleep(10)
            continue
        if "Received resouce metrics" in logs or "Received resource metrics" in logs:
            print("Intersight produced fresh metrics without OTLP export errors.")
            return
        time.sleep(10)
    if "Error sending metrics:" in last_sample:
        raise SystemExit("ERROR: Intersight is still failing to export metrics after collector correction.")
    print("WARN: no fresh Intersight metric batch observed before timeout; live validate will still check errors.")
    if last_sample.strip():
        print(last_sample[-2000:])


def main() -> int:
    args = parse_args()
    token_file = Path(args.o11y_token_file).expanduser().resolve()
    if not token_file.is_file():
        print(f"ERROR: token file not found: {token_file}", file=sys.stderr)
        return 1

    overlay_path = Path(args.output_dir) / "splunk-otel-overlay" / "values.overlay.yaml"
    if not overlay_path.is_file():
        print(f"ERROR: rendered overlay not found: {overlay_path}", file=sys.stderr)
        return 1

    current_result = run(["helm", "get", "values", args.release, "-n", args.namespace, "-o", "json"], capture=True)
    current_values = json.loads(current_result.stdout or "{}") or {}
    if not isinstance(current_values, dict):
        current_values = {}
    remove_inline_tokens(current_values)

    overlay = yaml.safe_load(overlay_path.read_text(encoding="utf-8")) or {}
    if not isinstance(overlay, dict):
        print(f"ERROR: overlay did not parse to a mapping: {overlay_path}", file=sys.stderr)
        return 1

    cli = kube_cli()
    merged = deep_merge(current_values, overlay)
    counters = sanitize(merged, overlay, cli, args.namespace)
    remove_inline_tokens(merged)

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", prefix="ai-pod-existing-collector-values-", suffix=".yaml", delete=False) as handle:
        yaml.safe_dump(merged, handle, sort_keys=True, default_flow_style=False)
        merged_path = Path(handle.name)

    try:
        print(f"Applying AI Pod overlay to existing Helm release {args.namespace}/{args.release}...")
        print(
            "Sanitized collector drift: "
            f"removed receiver_creator/nvidia={counters['removed_receiver_creator_nvidia']}, "
            f"removed pipeline refs={counters['removed_pipeline_refs']}, "
            f"added otlp metrics receiver={counters['added_otlp_metrics']}, "
            f"pruned nexus without secret={counters['pruned_nexus_without_secret']}"
        )
        helm_cmd = [
            "helm",
            "upgrade",
            "--install",
            args.release,
            args.chart_ref,
            "-n",
            args.namespace,
            "--create-namespace",
            "-f",
            str(merged_path),
            "--set-file",
            f"splunkObservability.accessToken={token_file}",
            "--wait",
            f"--timeout={args.timeout}",
        ]
        if command_supports(["helm", "upgrade", "--help"], "--force-conflicts"):
            # Helm v4 can preserve server-side apply from prior releases. If a
            # ConfigMap was edited manually, SSA may reject the chart-owned
            # relay config unless Helm is allowed to reclaim that field.
            helm_cmd.append("--force-conflicts")
        run(helm_cmd)
    finally:
        try:
            merged_path.unlink()
        except OSError:
            pass

    if cli:
        restart_matching_daemonsets(cli, args.namespace, args.release, args.timeout)
        restart_intersight_if_present(cli, args.timeout)
        wait_for_clean_intersight_logs(cli)
    else:
        print("WARN: oc/kubectl not found; skipping rollout restart and live log wait.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

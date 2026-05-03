"""Render the NVIDIA GPU (DCGM) -> Splunk Observability Cloud overlay + helpers.

Outputs:
  - splunk-otel-overlay/values.overlay.yaml  (receiver_creator/dcgm-cisco + metrics/nvidia-metrics pipeline)
  - dcgm-pod-labels-patch/<files>            (only when --enable-dcgm-pod-labels)
  - dashboards/<name>.signalflow.yaml
  - detectors/<name>.yaml
  - scripts/handoff-base-collector.sh
  - scripts/handoff-dashboards.sh
  - scripts/handoff-detectors.sh
  - scripts/apply-dcgm-pod-labels-patch.sh   (only when --enable-dcgm-pod-labels)
  - metadata.json
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


SKILL_NAME = "splunk-observability-nvidia-gpu-integration"

# Canonical signalfx allow-list for DCGM_FI_* series (when --filter strict).
# Sourced from signalfx/splunk-opentelemetry-examples/collector/cisco-ai-ready-pods values.
STRICT_DCGM_METRICS = [
    "DCGM_FI_DEV_FB_FREE",
    "DCGM_FI_DEV_FB_USED",
    "DCGM_FI_DEV_GPU_TEMP",
    "DCGM_FI_DEV_GPU_UTIL",
    "DCGM_FI_DEV_MEM_CLOCK",
    "DCGM_FI_DEV_MEM_COPY_UTIL",
    "DCGM_FI_DEV_MEMORY_TEMP",
    "DCGM_FI_DEV_POWER_USAGE",
    "DCGM_FI_DEV_SM_CLOCK",
    "DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION",
    "DCGM_FI_PROF_DRAM_ACTIVE",
    "DCGM_FI_PROF_GR_ENGINE_ACTIVE",
    "DCGM_FI_PROF_PCIE_RX_BYTES",
    "DCGM_FI_PROF_PCIE_TX_BYTES",
    "DCGM_FI_PROF_PIPE_TENSOR_ACTIVE",
]

VALID_FILTER_MODES = {"none", "strict"}


def _load_yaml_module():
    try:
        import yaml  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:
        raise SpecError(
            "PyYAML is required. Install with 'python3 -m pip install -r requirements-agent.txt' "
            "or pass a JSON spec."
        ) from exc
    return yaml


class SpecError(ValueError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--realm", default="")
    parser.add_argument("--cluster-name", default="")
    parser.add_argument("--distribution", default="")
    parser.add_argument("--receiver-creator-name", default="")
    parser.add_argument("--filter-mode", default="")
    parser.add_argument("--enable-dcgm-pod-labels", default="false")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def bool_flag(value: str) -> bool:
    return str(value).lower() == "true"


def load_spec(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    try:
        if suffix == ".json":
            data = json.loads(text)
        else:
            yaml = _load_yaml_module()
            try:
                data = yaml.safe_load(text)
            except yaml.YAMLError:
                data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SpecError(f"Failed to parse spec {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SpecError(f"Spec {path} did not parse to a mapping.")
    if data.get("api_version") != f"{SKILL_NAME}/v1":
        raise SpecError(
            f"Spec api_version must be '{SKILL_NAME}/v1'; got {data.get('api_version')!r}"
        )
    return data


def write_text(path: Path, content: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(0o755)


def write_yaml(path: Path, payload: Any) -> None:
    yaml = _load_yaml_module()
    write_text(path, yaml.safe_dump(payload, sort_keys=True, default_flow_style=False))


def write_json(path: Path, payload: Any) -> None:
    write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def overlay_values(spec: dict[str, Any], receiver_creator_name: str, filter_mode: str, cluster_name: str, distribution: str) -> dict[str, Any]:
    """Build the OTel collector overlay.

    Critical: the receiver_creator name is parameterized to avoid the chart
    autodetect receiver_creator/nvidia collision. The discovery rule matches
    both label conventions.
    """
    if receiver_creator_name == "nvidia":
        raise SpecError(
            "receiver_creator_name must NOT be 'nvidia' -- that collides with the Splunk OTel chart's "
            "autodetect receiver_creator when autodetect.prometheus=true. Use 'dcgm-cisco' (default) or another name."
        )
    if not re.fullmatch(r"[a-z0-9-]+", receiver_creator_name):
        raise SpecError(f"Invalid receiver_creator_name {receiver_creator_name!r} (must be lowercase alphanumeric + hyphen).")

    dcgm = spec.get("dcgm") or {}
    port = int(dcgm.get("port", 9400))
    scrape_interval = int(dcgm.get("scrape_interval_seconds", 10))
    metrics_path = dcgm.get("metrics_path", "/metrics")

    receiver_creator_key = f"receiver_creator/{receiver_creator_name}"
    prometheus_child_key = f"prometheus/{receiver_creator_name}"

    # Discovery rule: match BOTH label conventions. Newer GPU Operator deployments
    # use app.kubernetes.io/name; older standalone deployments use the bare app label.
    discovery_rule = (
        'type == "pod" && '
        '(labels["app"] == "nvidia-dcgm-exporter" || '
        'labels["app.kubernetes.io/name"] == "nvidia-dcgm-exporter")'
    )

    receiver_creator_block = {
        "watch_observers": ["k8s_observer"],
        "receivers": {
            prometheus_child_key: {
                "rule": discovery_rule,
                "config": {
                    "config": {
                        "scrape_configs": [
                            {
                                "job_name": "gpu-metrics",
                                "scrape_interval": f"{scrape_interval}s",
                                "metrics_path": metrics_path,
                                "static_configs": [
                                    {"targets": ["`endpoint`:" + str(port)]}
                                ],
                            }
                        ]
                    }
                },
            }
        },
    }

    processors: list[str] = ["memory_limiter", "batch", "resourcedetection", "resource"]
    processors_block: dict[str, Any] = {
        "memory_limiter": {"check_interval": "2s", "limit_mib": 200},
        "batch": {},
        "resourcedetection": {"detectors": ["system"], "system": {"hostname_sources": ["os"]}},
        "resource": {"attributes": [{"action": "upsert", "key": "k8s.cluster.name", "value": cluster_name}]},
    }

    if filter_mode == "strict":
        filter_block = (spec.get("filter") or {})
        extras = filter_block.get("extra_metrics") or []
        metrics = list(STRICT_DCGM_METRICS)
        for name in extras:
            if name not in metrics:
                metrics.append(name)
        processors_block["filter/dcgm_strict"] = {
            "metrics": {
                "include": {"match_type": "strict", "metric_names": metrics}
            }
        }
        processors.insert(2, "filter/dcgm_strict")  # after batch, before resourcedetection

    overlay: dict[str, Any] = {
        "clusterName": cluster_name or "lab-cluster",
        "distribution": distribution or "kubernetes",
        "agent": {
            "config": {
                "extensions": {
                    "k8s_observer": {"auth_type": "serviceAccount", "observe_pods": True},
                },
                "receivers": {receiver_creator_key: receiver_creator_block},
                "processors": processors_block,
                "service": {
                    "pipelines": {
                        "metrics/nvidia-metrics": {
                            "exporters": ["signalfx"],
                            "processors": processors,
                            "receivers": [receiver_creator_key],
                        }
                    }
                },
            }
        },
    }
    return overlay


def dcgm_pod_labels_patch(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Render the Kubernetes patch for the DCGM Exporter pod-label gap.

    The patch:
    1. Sets DCGM_EXPORTER_KUBERNETES_ENABLE_POD_LABELS=true and
       DCGM_EXPORTER_KUBERNETES_ENABLE_POD_UID=true via DaemonSet env-var
       patch (operator users patch the GPU Operator's ClusterPolicy instead).
    2. Creates a ClusterRole + ClusterRoleBinding for the DCGM
       ServiceAccount granting list/get on pods and namespaces.
    3. Adds an AutoMount ServiceAccountToken patch on the SA.
    4. Documents the kubelet-path volume mount (the actual mount must be
       added to the DaemonSet via the GPU Operator's ClusterPolicy or a
       separate patch).
    """
    namespace = spec.get("dcgm_namespace", "nvidia-gpu-operator")
    sa = spec.get("dcgm_service_account", "nvidia-dcgm-exporter")
    cluster_role = {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": "ClusterRole",
        "metadata": {"name": "dcgm-exporter-pod-label-reader"},
        "rules": [
            {
                "apiGroups": [""],
                "resources": ["pods", "namespaces"],
                "verbs": ["get", "list", "watch"],
            }
        ],
    }
    cluster_role_binding = {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": "ClusterRoleBinding",
        "metadata": {"name": "dcgm-exporter-pod-label-reader"},
        "roleRef": {
            "apiGroup": "rbac.authorization.k8s.io",
            "kind": "ClusterRole",
            "name": "dcgm-exporter-pod-label-reader",
        },
        "subjects": [
            {"kind": "ServiceAccount", "name": sa, "namespace": namespace}
        ],
    }
    sa_patch = {
        "apiVersion": "v1",
        "kind": "ServiceAccount",
        "metadata": {"name": sa, "namespace": namespace},
        "automountServiceAccountToken": True,
    }
    daemonset_env_patch = {
        "spec": {
            "template": {
                "spec": {
                    "containers": [
                        {
                            "name": "nvidia-dcgm-exporter",
                            "env": [
                                {"name": "DCGM_EXPORTER_KUBERNETES_ENABLE_POD_LABELS", "value": "true"},
                                {"name": "DCGM_EXPORTER_KUBERNETES_ENABLE_POD_UID", "value": "true"},
                            ],
                        }
                    ]
                }
            }
        }
    }
    return {
        "01-cluster-role": cluster_role,
        "02-cluster-role-binding": cluster_role_binding,
        "03-service-account-automount": sa_patch,
        "04-daemonset-env-patch": daemonset_env_patch,
    }


def dashboard_specs(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if not (spec.get("dashboards") or {}).get("enabled", True):
        return {}
    return {
        "nvidia-gpu-overview": {
            "name": "NVIDIA GPU Overview",
            "description": "Per-GPU utilization, memory, temp, power, clocks, PCIe, energy, profiling",
            "charts": [
                _chart("GPU utilization", "DCGM_FI_DEV_GPU_UTIL"),
                _chart("Memory copy utilization", "DCGM_FI_DEV_MEM_COPY_UTIL"),
                _chart("FB used", "DCGM_FI_DEV_FB_USED"),
                _chart("FB free", "DCGM_FI_DEV_FB_FREE"),
                _chart("GPU temperature", "DCGM_FI_DEV_GPU_TEMP"),
                _chart("Memory temperature", "DCGM_FI_DEV_MEMORY_TEMP"),
                _chart("Power usage", "DCGM_FI_DEV_POWER_USAGE"),
                _chart("Total energy consumption", "DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION"),
                _chart("SM clock", "DCGM_FI_DEV_SM_CLOCK"),
                _chart("Memory clock", "DCGM_FI_DEV_MEM_CLOCK"),
                _chart("PCIe RX bytes", "DCGM_FI_PROF_PCIE_RX_BYTES"),
                _chart("PCIe TX bytes", "DCGM_FI_PROF_PCIE_TX_BYTES"),
                _chart("Tensor pipe active", "DCGM_FI_PROF_PIPE_TENSOR_ACTIVE"),
                _chart("DRAM active", "DCGM_FI_PROF_DRAM_ACTIVE"),
                _chart("Graphics engine active", "DCGM_FI_PROF_GR_ENGINE_ACTIVE"),
            ],
            "filters": [{"property": "k8s.cluster.name", "value": "${CLUSTER_NAME}"}],
        }
    }


def _chart(name: str, metric: str) -> dict[str, Any]:
    return {
        "name": name,
        "description": f"{metric} from DCGM Exporter",
        "program_text": f"data('{metric}', filter=filter('k8s.cluster.name', '${{CLUSTER_NAME}}')).publish(label='{metric}')",
        "publish_label": metric,
    }


def detector_specs(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    block = spec.get("detectors") or {}
    if not block.get("enabled", True):
        return {}
    thresholds = block.get("thresholds") or {}
    detectors = {
        "gpu-temp-ceiling": {
            "test_type": "nvidia-gpu",
            "detectors": [
                {
                    "name": "GPU temperature ceiling",
                    "metric": "DCGM_FI_DEV_GPU_TEMP",
                    "direction": "above",
                    "threshold": thresholds.get("gpu_temp_ceiling_celsius", 85),
                    "severity": "Major",
                    "aggregation": "max",
                }
            ],
        },
        "gpu-power-floor": {
            "test_type": "nvidia-gpu",
            "detectors": [
                {
                    "name": "GPU power floor (unexpected power loss)",
                    "metric": "DCGM_FI_DEV_POWER_USAGE",
                    "direction": "below",
                    "threshold": thresholds.get("gpu_power_floor_watts", 50),
                    "severity": "Warning",
                    "aggregation": "min",
                }
            ],
        },
        "gpu-utilization-low": {
            "test_type": "nvidia-gpu",
            "detectors": [
                {
                    "name": "GPU utilization regression (cost optimization)",
                    "metric": "DCGM_FI_DEV_GPU_UTIL",
                    "direction": "below",
                    "threshold": thresholds.get("gpu_utilization_pct_floor", 10),
                    "severity": "Info",
                    "aggregation": "mean",
                }
            ],
        },
    }
    if thresholds.get("energy_consumption_joules_anomaly", 0) > 0:
        detectors["energy-anomaly"] = {
            "test_type": "nvidia-gpu",
            "detectors": [
                {
                    "name": "GPU energy consumption anomaly",
                    "metric": "DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION",
                    "direction": "above",
                    "threshold": thresholds["energy_consumption_joules_anomaly"],
                    "severity": "Info",
                    "aggregation": "delta",
                }
            ],
        }
    return detectors


def render_handoffs(spec: dict[str, Any], realm: str, cluster_name: str, distribution: str) -> dict[str, str]:
    handoffs = spec.get("handoffs") or {}
    helpers: dict[str, str] = {}
    if handoffs.get("base_collector", True):
        helpers["handoff-base-collector.sh"] = (
            f"""#!/usr/bin/env bash
set -euo pipefail

if ! command -v yq >/dev/null 2>&1; then
    echo 'ERROR: yq required for overlay merge.' >&2
    exit 1
fi

OVERLAY="$(cd "$(dirname "${{BASH_SOURCE[0]}}")/.." && pwd)/splunk-otel-overlay/values.overlay.yaml"
BASE_OUTPUT_DIR="${{BASE_OUTPUT_DIR:-/tmp/splunk-observability-otel-rendered}}"

echo "Step 1: Render base collector values."
echo "    bash skills/splunk-observability-otel-collector-setup/scripts/setup.sh \\\\"
echo "      --render-k8s --realm {realm} --cluster-name {cluster_name} --distribution {distribution} \\\\"
echo "      --output-dir ${{BASE_OUTPUT_DIR}}"
echo
echo "Step 2: Merge overlay."
echo "    yq eval-all '. as \\$item ireduce ({{}}; . * \\$item)' \\\\"
echo "      ${{BASE_OUTPUT_DIR}}/k8s/values.yaml \\\\"
echo "      ${{OVERLAY}} \\\\"
echo "      > /tmp/merged-values.yaml"
echo
echo "Step 3: Apply via helm."
echo "    helm upgrade --install splunk-otel-collector splunk-otel-collector-chart/splunk-otel-collector \\\\"
echo "      -n splunk-otel --create-namespace --reuse-values \\\\"
echo "      -f /tmp/merged-values.yaml \\\\"
echo '      --set splunkObservability.accessToken="$(cat $O11Y_TOKEN_FILE)"'
"""
        )
    if handoffs.get("dashboard_builder", True):
        helpers["handoff-dashboards.sh"] = (
            f"""#!/usr/bin/env bash
set -euo pipefail
DASHBOARDS_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")/.." && pwd)/dashboards"
echo "Import dashboards via splunk-observability-dashboard-builder:"
echo "    for spec in ${{DASHBOARDS_DIR}}/*.signalflow.yaml; do"
echo "      bash skills/splunk-observability-dashboard-builder/scripts/setup.sh \\\\"
echo "        --render --apply --realm {realm} --spec \\$spec --token-file \\$O11Y_API_TOKEN_FILE"
echo "    done"
"""
        )
    if handoffs.get("native_ops", True):
        helpers["handoff-detectors.sh"] = (
            f"""#!/usr/bin/env bash
set -euo pipefail
DETECTORS_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")/.." && pwd)/detectors"
echo "Apply detectors via splunk-observability-native-ops:"
echo "    bash skills/splunk-observability-native-ops/scripts/setup.sh \\\\"
echo "      --render --apply --realm {realm} --spec ${{DETECTORS_DIR}}/<detector>.yaml --token-file \\$O11Y_API_TOKEN_FILE"
"""
        )
    return helpers


def render_metadata(spec: dict[str, Any], realm: str, cluster_name: str, receiver_creator_name: str, filter_mode: str, dcgm_pod_labels_enabled: bool) -> dict[str, Any]:
    return {
        "skill": SKILL_NAME,
        "realm": realm,
        "cluster_name": cluster_name,
        "receiver_creator_name": receiver_creator_name,
        "filter_mode": filter_mode,
        "dcgm_pod_labels_enabled": dcgm_pod_labels_enabled,
        "warnings": warnings(spec, receiver_creator_name, filter_mode, dcgm_pod_labels_enabled),
    }


def warnings(spec: dict[str, Any], receiver_creator_name: str, filter_mode: str, dcgm_pod_labels_enabled: bool) -> list[str]:
    items: list[str] = []
    if filter_mode == "none":
        items.append(
            "filter_mode=none: all DCGM_FI_* series flow to Splunk Observability Cloud. "
            "Switch to --filter strict to limit cardinality."
        )
    if not dcgm_pod_labels_enabled:
        items.append(
            "DCGM pod-label gap: GPU Operator does NOT expose pod/namespace labels in DCGM_FI_* metrics by default. "
            "Pass --enable-dcgm-pod-labels to render the patch (env vars + RBAC + SA token + kubelet mount)."
        )
    return items


def main() -> int:
    args = parse_args()
    spec_path = Path(args.spec)
    if not spec_path.is_file():
        print(f"ERROR: spec not found: {spec_path}", file=__import__("sys").stderr)
        return 1
    try:
        spec = load_spec(spec_path)
    except SpecError as exc:
        print(f"ERROR: {exc}", file=__import__("sys").stderr)
        return 1

    realm = args.realm or spec.get("realm", "us0")
    cluster_name = args.cluster_name or spec.get("cluster_name", "lab-cluster")
    distribution = args.distribution or spec.get("distribution", "kubernetes")
    receiver_creator_name = args.receiver_creator_name or spec.get("receiver_creator_name", "dcgm-cisco")
    filter_mode = args.filter_mode or (spec.get("filter") or {}).get("mode", "none")
    if filter_mode not in VALID_FILTER_MODES:
        print(f"ERROR: filter_mode must be one of {sorted(VALID_FILTER_MODES)}; got {filter_mode!r}", file=__import__("sys").stderr)
        return 1
    dcgm_pod_labels_enabled = bool_flag(args.enable_dcgm_pod_labels) or bool(spec.get("enable_dcgm_pod_labels", False))

    plan = {
        "skill": SKILL_NAME,
        "output_dir": str(Path(args.output_dir).resolve()),
        "realm": realm,
        "cluster_name": cluster_name,
        "distribution": distribution,
        "receiver_creator_name": receiver_creator_name,
        "filter_mode": filter_mode,
        "dcgm_pod_labels_enabled": dcgm_pod_labels_enabled,
        "warnings": warnings(spec, receiver_creator_name, filter_mode, dcgm_pod_labels_enabled),
    }

    if args.dry_run:
        if args.json:
            print(json.dumps(plan, indent=2, sort_keys=True))
        else:
            print("NVIDIA GPU Integration render plan")
            for key, value in plan.items():
                print(f"  {key}: {value}")
        return 0

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    try:
        overlay = overlay_values(spec, receiver_creator_name, filter_mode, cluster_name, distribution)
    except SpecError as exc:
        print(f"ERROR: {exc}", file=__import__("sys").stderr)
        return 1
    write_yaml(out / "splunk-otel-overlay/values.overlay.yaml", overlay)

    if dcgm_pod_labels_enabled:
        for name, payload in dcgm_pod_labels_patch(spec).items():
            write_yaml(out / f"dcgm-pod-labels-patch/{name}.yaml", payload)
        write_text(
            out / "scripts/apply-dcgm-pod-labels-patch.sh",
            (
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n\n"
                "# Apply the DCGM pod-label patch (env vars + RBAC + SA + DaemonSet env patch).\n"
                "# Note: GPU Operator users should patch the ClusterPolicy instead -- the\n"
                "# DaemonSet env patch in this output may be overridden by the operator on\n"
                "# next reconcile. See references/dcgm-pod-labels.md for details.\n"
                "PATCH_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")/..\" && pwd)/dcgm-pod-labels-patch\"\n"
                "kubectl apply -f \"${PATCH_DIR}/01-cluster-role.yaml\"\n"
                "kubectl apply -f \"${PATCH_DIR}/02-cluster-role-binding.yaml\"\n"
                "kubectl apply -f \"${PATCH_DIR}/03-service-account-automount.yaml\"\n"
                "echo 'NOTE: 04-daemonset-env-patch.yaml is a strategic merge patch.'\n"
                "echo 'Apply with: kubectl -n nvidia-gpu-operator patch daemonset nvidia-dcgm-exporter --patch-file ${PATCH_DIR}/04-daemonset-env-patch.yaml'\n"
            ),
            executable=True,
        )

    for name, payload in dashboard_specs(spec).items():
        write_yaml(out / f"dashboards/{name}.signalflow.yaml", payload)
    for name, payload in detector_specs(spec).items():
        write_yaml(out / f"detectors/{name}.yaml", payload)

    for name, body in render_handoffs(spec, realm, cluster_name, distribution).items():
        write_text(out / f"scripts/{name}", body, executable=True)

    write_json(out / "metadata.json", render_metadata(spec, realm, cluster_name, receiver_creator_name, filter_mode, dcgm_pod_labels_enabled))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

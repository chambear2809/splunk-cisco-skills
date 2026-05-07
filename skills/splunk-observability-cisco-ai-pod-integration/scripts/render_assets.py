"""Render the AI Pod umbrella overlay + AI-Pod-specific additions.

Composition strategy:
  - Each child skill's render_assets.py is invoked as a subprocess into a
    sub-directory under the umbrella's output dir.
  - The child overlays are merged via a Python deep-merge (we don't shell
    out to yq at render time so the renderer works without yq installed;
    operators still need yq at apply time to merge with the base collector
    values).
  - AI-Pod-specific blocks (NIM/vLLM/Milvus/storage/Redfish, dual-pipeline
    filtering, k8s_attributes/nim, OpenShift defaults, RBAC patch) are
    layered on top of the merged child overlays.

Outputs:
  - splunk-otel-overlay/values.overlay.yaml         (composed + AI-Pod additions)
  - child-renders/<skill>/...                       (each child's full render)
  - intersight-integration/                         (passed through from Intersight child)
  - secrets/cisco-nexus-ssh-secret.yaml             (passed through from Nexus child)
  - dcgm-pod-labels-patch/...                       (passed through from GPU child when enabled)
  - openshift/scc.sh
  - workshop/multi-tenant.sh                        (when --workshop-mode)
  - dashboards/<name>.signalflow.yaml               (AI-Pod-specific)
  - detectors/<name>.yaml                           (AI-Pod-specific)
  - scripts/handoff-base-collector.sh
  - scripts/handoff-hec-token.sh
  - scripts/handoff-dashboards.sh
  - scripts/handoff-detectors.sh
  - scripts/explain-composition.sh
  - metadata.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


SKILL_NAME = "splunk-observability-cisco-ai-pod-integration"
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = SKILL_DIR.parent.parent

CHILD_SKILLS = {
    "nexus": "splunk-observability-cisco-nexus-integration",
    "intersight": "splunk-observability-cisco-intersight-integration",
    "nvidia_gpu": "splunk-observability-nvidia-gpu-integration",
}

VALID_NIM_SCRAPE_MODES = {"receiver_creator", "endpoints"}


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
    parser.add_argument("--nim-scrape-mode", default="")
    parser.add_argument("--enable-dcgm-pod-labels", default="false")
    parser.add_argument("--workshop-mode", default="false")
    parser.add_argument("--collector-release", default="")
    parser.add_argument("--collector-namespace", default="")
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


def deep_merge(base: dict, overlay: dict) -> dict:
    """Recursive deep-merge. Right-biased on conflicts.

    Lists are concatenated then de-duplicated by string conversion (preserves
    order). This is a sane default for OTel collector pipelines/receivers
    lists where we want both base and overlay entries.
    """
    result = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        elif isinstance(value, list) and isinstance(result.get(key), list):
            seen = set()
            merged_list = []
            for item in result[key] + value:
                key_str = json.dumps(item, sort_keys=True) if isinstance(item, (dict, list)) else str(item)
                if key_str not in seen:
                    seen.add(key_str)
                    merged_list.append(item)
            result[key] = merged_list
        else:
            result[key] = value
    return result


def invoke_child(child_skill: str, *, output_dir: Path, common_args: dict[str, str], extra_args: list[str]) -> int:
    """Run a child skill's setup.sh --render into a sub-directory."""
    setup = PROJECT_ROOT / "skills" / child_skill / "scripts" / "setup.sh"
    if not setup.is_file():
        raise SpecError(f"Child skill setup.sh not found: {setup}")
    args = ["bash", str(setup), "--render", "--output-dir", str(output_dir)]
    for key, value in common_args.items():
        if value:
            args += [key, value]
    args += extra_args
    print(f"  -> Invoking child skill: {child_skill}")
    result = subprocess.run(args, cwd=PROJECT_ROOT, check=False)
    if result.returncode != 0:
        raise SpecError(f"Child skill {child_skill} render failed (exit {result.returncode}).")
    return result.returncode


def load_child_overlay(child_output_dir: Path) -> dict[str, Any]:
    """Deep-merge every splunk-otel-overlay/*.yaml file from a child render.

    Children may emit multiple overlay files (e.g. the Intersight child writes
    both a values.overlay.yaml-style block AND an intersight-pipeline.yaml).
    The umbrella must merge them all so no piece is silently dropped.
    """
    overlay_dir = child_output_dir / "splunk-otel-overlay"
    if not overlay_dir.is_dir():
        return {}
    yaml = _load_yaml_module()
    merged: dict[str, Any] = {}
    for overlay_path in sorted(overlay_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(overlay_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise SpecError(f"Failed to parse child overlay {overlay_path}: {exc}") from exc
        if not isinstance(data, dict):
            continue
        merged = deep_merge(merged, data)
    return merged


def ai_pod_overlay_additions(spec: dict[str, Any], cluster_name: str, distribution: str, nim_scrape_mode: str) -> dict[str, Any]:
    """Build the AI-Pod-specific block layered on top of the composed children's overlays."""
    additions: dict[str, Any] = {
        "clusterName": cluster_name,
        "distribution": distribution,
    }

    if distribution == "openshift":
        # OpenShift defaults validated in atl-ocp2 production.
        additions.setdefault("agent", {}).setdefault("config", {}).setdefault("receivers", {}).setdefault(
            "kubeletstats", {"collection_interval": "30s", "insecure_skip_verify": True}
        )
        additions["certmanager"] = {"enabled": False}
        additions["cloudProvider"] = ""
        additions["operator"] = {"enabled": False}
        additions["operatorcrds"] = {"installed": False}
        additions["gateway"] = {"enabled": False}

    receivers: dict[str, Any] = {}
    pipeline_receivers: dict[str, list[str]] = {
        "metrics/cisco-ai-pods": [],          # unfiltered DCGM
        "metrics/nvidianim-metrics": [],      # unfiltered NIM/vLLM/Milvus
    }

    nim_block = spec.get("nim") or {}
    if nim_block.get("enabled", True):
        if nim_scrape_mode == "receiver_creator":
            # Per-model receiver_creator children; the GPU child's
            # receiver_creator/dcgm-cisco is reused via composition.
            for model in nim_block.get("models", []):
                key = f"receiver_creator/nim-{model}"
                receivers[key] = {
                    "watch_observers": ["k8s_observer"],
                    "receivers": {
                        f"prometheus/nim-{model}": {
                            "rule": (
                                f'type == "pod" && (labels["app"] == "{model}" || '
                                f'labels["app.kubernetes.io/name"] == "{model}")'
                            ),
                            "config": {
                                "config": {
                                    "scrape_configs": [
                                        {
                                            "job_name": f"nim-{model}",
                                            "scrape_interval": "10s",
                                            "metrics_path": nim_block.get("metrics_path", "/v1/metrics"),
                                            "static_configs": [
                                                {"targets": [f"`endpoint`:{nim_block.get('port', 8000)}"]}
                                            ],
                                        }
                                    ]
                                }
                            },
                        }
                    },
                }
                pipeline_receivers["metrics/nvidianim-metrics"].append(key)
        else:
            # endpoints mode: requires the rbac.customRules patch.
            namespaces = nim_block.get("endpoints_namespaces", [])
            service_regex = nim_block.get("endpoints_service_regex", "")
            port_regex = nim_block.get("endpoints_port_regex", "api|http")
            relabel_configs: list[dict[str, Any]] = []
            if service_regex:
                relabel_configs.append({
                    "source_labels": ["__meta_kubernetes_service_name"],
                    "action": "keep",
                    "regex": service_regex,
                })
            relabel_configs.append({
                "source_labels": ["__meta_kubernetes_endpoint_port_name"],
                "action": "keep",
                "regex": port_regex,
            })
            receivers["prometheus/nim"] = {
                "config": {
                    "scrape_configs": [
                        {
                            "job_name": "nim-for-llm-metrics",
                            "scrape_interval": "10s",
                            "metrics_path": nim_block.get("metrics_path", "/v1/metrics"),
                            "kubernetes_sd_configs": [
                                {"role": "endpoints", "namespaces": {"names": namespaces}}
                            ],
                            "relabel_configs": relabel_configs,
                        }
                    ]
                }
            }
            pipeline_receivers["metrics/nvidianim-metrics"].append("prometheus/nim")

    vllm_block = spec.get("vllm") or {}
    if vllm_block.get("enabled", True):
        receivers["receiver_creator/vllm-cisco"] = {
            "watch_observers": ["k8s_observer"],
            "receivers": {
                "prometheus/vllm-cisco": {
                    "rule": (
                        f'type == "pod" && (labels["app"] == "{vllm_block.get("pod_label", "vllm")}" || '
                        f'labels["app.kubernetes.io/name"] == "{vllm_block.get("pod_label", "vllm")}")'
                    ),
                    "config": {
                        "config": {
                            "scrape_configs": [
                                {
                                    "job_name": "vllm-metrics",
                                    "scrape_interval": "10s",
                                    "metrics_path": vllm_block.get("metrics_path", "/metrics"),
                                    "static_configs": [
                                        {"targets": [f"`endpoint`:{vllm_block.get('port', 8000)}"]}
                                    ],
                                }
                            ]
                        }
                    },
                }
            },
        }
        pipeline_receivers["metrics/nvidianim-metrics"].append("receiver_creator/vllm-cisco")

    milvus_block = spec.get("milvus") or {}
    if milvus_block.get("enabled", True):
        receivers["receiver_creator/milvus-cisco"] = {
            "watch_observers": ["k8s_observer"],
            "receivers": {
                "prometheus/milvus-cisco": {
                    "rule": f'type == "pod" && labels["app.kubernetes.io/name"] == "{milvus_block.get("pod_label", "milvus")}"',
                    "config": {
                        "config": {
                            "scrape_configs": [
                                {
                                    "job_name": "milvus-metrics",
                                    "static_configs": [
                                        {"targets": [f"`endpoint`:{milvus_block.get('port', 9091)}"]}
                                    ],
                                }
                            ]
                        }
                    },
                }
            },
        }
        pipeline_receivers["metrics/nvidianim-metrics"].append("receiver_creator/milvus-cisco")

    storage_block = spec.get("storage") or {}
    trident = storage_block.get("trident") or {}
    if trident.get("enabled", True):
        receivers["receiver_creator/trident-cisco"] = {
            "watch_observers": ["k8s_observer"],
            "receivers": {
                "prometheus/trident-cisco": {
                    "rule": f'type == "pod" && labels["app"] == "{trident.get("pod_label", "controller.csi.trident.netapp.io")}"',
                    "config": {
                        "config": {
                            "scrape_configs": [
                                {
                                    "job_name": "trident-metrics",
                                    "scrape_interval": "10s",
                                    "metrics_path": "/metrics",
                                    "static_configs": [
                                        {"targets": [f"`endpoint`:{trident.get('port', 8001)}"]}
                                    ],
                                }
                            ]
                        }
                    },
                }
            },
        }
        pipeline_receivers["metrics/nvidianim-metrics"].append("receiver_creator/trident-cisco")
    portworx = storage_block.get("portworx") or {}
    if portworx.get("enabled", True):
        receivers["receiver_creator/portworx-cisco"] = {
            "watch_observers": ["k8s_observer"],
            "receivers": {
                "prometheus/portworx-cisco": {
                    "rule": f'type == "pod" && labels["name"] == "{portworx.get("pod_label", "portworx")}"',
                    "config": {
                        "config": {
                            "scrape_configs": [
                                {
                                    "job_name": "portworx-metrics",
                                    "static_configs": [
                                        {"targets": [f"`endpoint`:{port}" for port in portworx.get("ports", [17001, 17018])]}
                                    ],
                                }
                            ]
                        }
                    },
                }
            },
        }
        pipeline_receivers["metrics/nvidianim-metrics"].append("receiver_creator/portworx-cisco")

    redfish = spec.get("redfish") or {}
    if redfish.get("enabled", True):
        for path_suffix in redfish.get("paths", ["/health", "/performance"]):
            slug = path_suffix.strip("/").replace("/", "-")
            receivers[f"receiver_creator/redfish-{slug}-cisco"] = {
                "watch_observers": ["k8s_observer"],
                "receivers": {
                    f"prometheus/redfish-{slug}-cisco": {
                        "rule": f'type == "pod" && labels["app"] == "{redfish.get("pod_label", "redfish-exporter")}"',
                        "config": {
                            "config": {
                                "scrape_configs": [
                                    {
                                        "job_name": f"redfish-{slug}-metrics",
                                        "scrape_interval": f"{redfish.get('scrape_intervals_seconds', {}).get(slug.replace('-', '_'), 60)}s",
                                        "metrics_path": path_suffix,
                                        "static_configs": [
                                            {"targets": [f"`endpoint`:{redfish.get('port', 9210)}"]}
                                        ],
                                    }
                                ]
                            }
                        },
                    }
                },
            }
            pipeline_receivers["metrics/cisco-ai-pods"].append(f"receiver_creator/redfish-{slug}-cisco")

    # k8s_attributes/nim processor for model_name extraction.
    processors = {
        "k8s_attributes/nim": {
            "auth_type": "serviceAccount",
            "extract": {
                "labels": [
                    {"from": "pod", "key": "app", "tag_name": "model_name"},
                ],
                "metadata": [
                    "k8s.namespace.name",
                    "k8s.pod.name",
                    "k8s.pod.uid",
                    "k8s.deployment.name",
                    "k8s.node.name",
                    "k8s.pod.start_time",
                ],
            },
            "passthrough": False,
            "pod_association": [
                {"sources": [{"from": "resource_attribute", "name": "k8s.pod.ip"}]},
                {"sources": [{"from": "connection"}]},
            ],
        }
    }

    # Wire up agent.config additions
    additions.setdefault("agent", {}).setdefault("config", {}).setdefault("receivers", {}).update(receivers)
    additions["agent"]["config"].setdefault("processors", {}).update(processors)
    additions["agent"]["config"].setdefault("exporters", {}).setdefault("signalfx", {"send_otlp_histograms": True})

    # Pipeline additions: dual-pipeline filtering pattern.
    if spec.get("dual_pipeline_filtering", True):
        pipelines = additions["agent"]["config"].setdefault("service", {}).setdefault("pipelines", {})
        if pipeline_receivers["metrics/nvidianim-metrics"]:
            pipelines["metrics/nvidianim-metrics"] = {
                "exporters": ["signalfx"],
                "processors": ["memory_limiter", "k8s_attributes/nim", "batch", "resourcedetection", "resource"],
                "receivers": pipeline_receivers["metrics/nvidianim-metrics"],
            }
        if pipeline_receivers["metrics/cisco-ai-pods"]:
            pipelines["metrics/cisco-ai-pods"] = {
                "exporters": ["signalfx"],
                "processors": ["memory_limiter", "batch", "resourcedetection", "resource"],
                "receivers": pipeline_receivers["metrics/cisco-ai-pods"],
            }

    # Critical RBAC patch when endpoint-SD scrape is used.
    if nim_scrape_mode == "endpoints":
        additions["rbac"] = {
            "customRules": [
                {"apiGroups": [""], "resources": ["endpoints"], "verbs": ["get", "list", "watch"]},
                {"apiGroups": ["discovery.k8s.io"], "resources": ["endpointslices"], "verbs": ["get", "list", "watch"]},
            ]
        }

    return additions


def openshift_scc_script(release: str = "splunk-otel-collector", namespace: str = "splunk-otel") -> str:
    return (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n\n"
        "# OpenShift SCC helper: grant anyuid to the Splunk OTel collector ServiceAccount.\n"
        "# Required for cisco-ai-pod-integration on OpenShift (kubelet TLS + hostPath access).\n"
        f'NAMESPACE="${{1:-{namespace}}}"\n'
        f'RELEASE="${{2:-{release}}}"\n'
        f'oc adm policy add-scc-to-user anyuid -z "${{RELEASE}}" -n "${{NAMESPACE}}"\n'
        f'oc adm policy add-scc-to-user privileged -z "${{RELEASE}}" -n "${{NAMESPACE}}"\n'
        f'echo "SCC granted: anyuid + privileged for ${{RELEASE}} ServiceAccount in ${{NAMESPACE}}."\n'
    )


def workshop_multi_tenant_script(spec: dict[str, Any]) -> str:
    block = spec.get("workshop_mode") or {}
    prefix = block.get("participant_namespace_prefix", "workshop-participant")
    count = int(block.get("participant_count", 30))
    return (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n\n"
        "# Workshop multi-tenant: per-namespace SA + ClusterRoleBinding + SCC for shared cluster-receiver.\n"
        "# Mirrors the Splunk Workshop AI Pod path (splunk.github.io/observability-workshop/.../14-cisco-ai-pods/).\n"
        f'PREFIX="${{1:-{prefix}}}"\n'
        f'COUNT="${{2:-{count}}}"\n'
        '\n'
        'for i in $(seq 1 "${COUNT}"); do\n'
        '    ns="${PREFIX}-${i}"\n'
        '    oc get ns "${ns}" >/dev/null 2>&1 || continue\n'
        '    oc -n "${ns}" create sa splunk-otel-collector 2>/dev/null || true\n'
        '\n'
        '    oc apply -f - <<EOF\n'
        'apiVersion: rbac.authorization.k8s.io/v1\n'
        'kind: ClusterRoleBinding\n'
        'metadata:\n'
        '  name: splunk-otel-collector-${ns}\n'
        'roleRef:\n'
        '  apiGroup: rbac.authorization.k8s.io\n'
        '  kind: ClusterRole\n'
        '  name: splunk-otel-collector\n'
        'subjects:\n'
        '- kind: ServiceAccount\n'
        '  name: splunk-otel-collector\n'
        '  namespace: ${ns}\n'
        'EOF\n'
        '\n'
        '    oc -n "${ns}" adm policy add-scc-to-user splunk-otel-collector -z splunk-otel-collector\n'
        'done\n'
    )


def ai_pod_dashboard_specs(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        "ai-pod-llm-inference": {
            "name": "AI Pod LLM Inference",
            "description": "NIM + vLLM inference latency / throughput / cache",
            "charts": [
                _chart("Active requests (NIM)", "num_requests_running"),
                _chart("Waiting requests", "num_requests_waiting"),
                _chart("TTFT (NIM)", "time_to_first_token_seconds"),
                _chart("Time per output token", "time_per_output_token_seconds"),
                _chart("E2E request latency", "e2e_request_latency_seconds"),
                _chart("Prompt tokens", "prompt_tokens_total"),
                _chart("Generation tokens", "generation_tokens_total"),
                _chart("vLLM E2E latency", "vllm:e2e_request_latency_seconds"),
                _chart("vLLM KV cache usage", "vllm:kv_cache_usage_perc"),
                _chart("vLLM request failures", "vllm:request_failure_total"),
                _chart("vLLM request successes", "vllm:request_success_total"),
                _chart("Request finish total", "request_finish_total"),
            ],
            "filters": [{"property": "k8s.cluster.name", "value": "${CLUSTER_NAME}"}],
        },
        "ai-pod-vector-db": {
            "name": "AI Pod Vector DB (Milvus)",
            "description": "Milvus query/proxy/rootcoord performance",
            "charts": [
                _chart("Proxy cache hit", "milvus_proxy_cache_hit_count"),
                _chart("Proxy req count", "milvus_proxy_req_count"),
                _chart("QueryCoord collections", "milvus_querycoord_collection_num"),
                _chart("RootCoord DDL req", "milvus_rootcoord_ddl_req_count"),
                _chart("RootCoord DML channels", "milvus_rootcoord_dml_channel_num"),
                _chart("Proxy req queue latency", "milvus_proxy_req_in_queue_latency"),
            ],
            "filters": [{"property": "k8s.cluster.name", "value": "${CLUSTER_NAME}"}],
        },
        "ai-pod-storage": {
            "name": "AI Pod Storage (Trident + Portworx)",
            "description": "NetApp Trident + Pure Portworx volume + cluster health",
            "charts": [
                _chart("Trident volume count", "trident_volume_count"),
                _chart("Trident volume allocated bytes", "trident_volume_allocated_bytes"),
                _chart("Trident operation duration (count)", "trident_operation_duration_milliseconds_count"),
                _chart("Portworx CPU %", "px_cluster_cpu_percent"),
                _chart("Portworx nodes online", "px_cluster_status_nodes_online"),
                _chart("Portworx nodes offline", "px_cluster_status_nodes_offline"),
                _chart("Portworx volume read latency", "px_volume_read_latency_seconds"),
                _chart("Portworx volume write latency", "px_volume_write_latency_seconds"),
            ],
            "filters": [{"property": "k8s.cluster.name", "value": "${CLUSTER_NAME}"}],
        },
    }


def _chart(name: str, metric: str) -> dict[str, Any]:
    return {
        "name": name,
        "description": f"{metric}",
        "program_text": f"data('{metric}', filter=filter('k8s.cluster.name', '${{CLUSTER_NAME}}')).publish(label='{metric}')",
        "publish_label": metric,
    }


def ai_pod_detector_specs(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        "vllm-error-rate": {
            "test_type": "ai-pod-vllm",
            "detectors": [
                {
                    "name": "vLLM error rate spike",
                    "metric": "vllm:request_failure_total",
                    "direction": "above",
                    "threshold": 5,
                    "severity": "Major",
                    "aggregation": "rate",
                }
            ],
        },
        "nim-ttft-regression": {
            "test_type": "ai-pod-nim",
            "detectors": [
                {
                    "name": "NIM time-to-first-token regression",
                    "metric": "time_to_first_token_seconds",
                    "direction": "above",
                    "threshold": 1.0,
                    "severity": "Warning",
                    "aggregation": "p95",
                }
            ],
        },
        "milvus-query-latency": {
            "test_type": "ai-pod-milvus",
            "detectors": [
                {
                    "name": "Milvus proxy req queue latency anomaly",
                    "metric": "milvus_proxy_req_in_queue_latency",
                    "direction": "above",
                    "threshold": 1000,  # ms
                    "severity": "Major",
                    "aggregation": "p95",
                }
            ],
        },
        "portworx-node-offline": {
            "test_type": "ai-pod-portworx",
            "detectors": [
                {
                    "name": "Portworx node offline",
                    "metric": "px_cluster_status_nodes_offline",
                    "direction": "above",
                    "threshold": 0,
                    "severity": "Critical",
                    "aggregation": "max",
                }
            ],
        },
        "trident-allocation-pressure": {
            "test_type": "ai-pod-trident",
            "detectors": [
                {
                    "name": "NetApp Trident volume allocation pressure",
                    "metric": "trident_volume_allocated_bytes",
                    "direction": "above",
                    "threshold": 0,  # Set baseline; no default
                    "severity": "Info",
                    "aggregation": "delta",
                }
            ],
        },
    }


def render_handoffs(spec: dict[str, Any], realm: str, cluster_name: str, distribution: str, hec_enabled: bool) -> dict[str, str]:
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
echo "Step 2: Apply child manifests (Intersight namespace + manifests, optional DCGM patch)."
echo "    bash $(dirname \\${{BASH_SOURCE[0]}})/../child-renders/splunk-observability-cisco-intersight-integration/scripts/apply-intersight-manifests.sh"
echo "    # If DCGM patch enabled:"
echo "    bash $(dirname \\${{BASH_SOURCE[0]}})/../child-renders/splunk-observability-nvidia-gpu-integration/scripts/apply-dcgm-pod-labels-patch.sh"
echo
echo "Step 3: Merge overlay."
echo "    yq eval-all '. as \\$item ireduce ({{}}; . * \\$item)' \\\\"
echo "      ${{BASE_OUTPUT_DIR}}/k8s/values.yaml \\\\"
echo "      ${{OVERLAY}} \\\\"
echo "      > /tmp/merged-values.yaml"
echo
echo "Step 4: Apply via helm using --reuse-values --set token pattern."
echo "    helm upgrade --install splunk-otel-collector splunk-otel-collector-chart/splunk-otel-collector \\\\"
echo "      -n splunk-otel --create-namespace --reuse-values \\\\"
echo "      -f /tmp/merged-values.yaml \\\\"
echo '      --set splunkObservability.accessToken="$(cat $O11Y_TOKEN_FILE)"'
echo
echo "Step 5: OpenShift SCC (if applicable)."
echo "    bash $(dirname \\${{BASH_SOURCE[0]}})/../openshift/scc.sh"
echo
echo "For an existing Splunk OTel release, prefer the skill-owned apply path:"
echo "    bash skills/splunk-observability-cisco-ai-pod-integration/scripts/setup.sh \\\\"
echo "      --render --apply-existing-collector --validate --live \\\\"
echo "      --realm {realm} --cluster-name {cluster_name} --distribution {distribution} \\\\"
echo "      --collector-release splunk-otel-collector --collector-namespace splunk-otel \\\\"
echo '      --o11y-token-file "$O11Y_TOKEN_FILE"'
echo "This removes stale receiver_creator/nvidia values and wires OTLP metrics before Helm upgrade."
"""
        )
    if handoffs.get("hec_service", True) and hec_enabled:
        platform_logs = spec.get("splunk_platform_logs") or {}
        # splunk-hec-service-setup uses --token-name (not --hec-token-name) and
        # requires --platform enterprise|cloud. Defaults assume Splunk Cloud
        # (Cisco AI Pod is typically deployed on OpenShift talking to a Splunk
        # Cloud stack); operators on Splunk Enterprise should set PLATFORM=enterprise.
        helpers["handoff-hec-token.sh"] = (
            f"""#!/usr/bin/env bash
set -euo pipefail

# Provision the K8s container logs HEC token via splunk-hec-service-setup.
# Set PLATFORM=enterprise or PLATFORM=cloud before running.
PLATFORM="${{PLATFORM:-cloud}}"
echo "Run:"
echo "    bash skills/splunk-hec-service-setup/scripts/setup.sh \\\\"
echo "      --platform ${{PLATFORM}} --phase render \\\\"
echo "      --token-name {platform_logs.get('hec_token_name', 'splunk_otel_ai_pod_logs')} \\\\"
echo "      --default-index {platform_logs.get('hec_index', 'cisco_ai_pod')} \\\\"
echo "      --allowed-indexes {platform_logs.get('hec_index', 'cisco_ai_pod')}"
"""
        )
    if handoffs.get("dashboard_builder", True):
        helpers["handoff-dashboards.sh"] = (
            f"""#!/usr/bin/env bash
set -euo pipefail
DASHBOARDS_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")/.." && pwd)/dashboards"
CHILD_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")/.." && pwd)/child-renders"
echo "Import dashboards via splunk-observability-dashboard-builder:"
echo "    # Component dashboards:"
echo "    bash \\${{CHILD_DIR}}/splunk-observability-cisco-nexus-integration/scripts/handoff-dashboards.sh"
echo "    bash \\${{CHILD_DIR}}/splunk-observability-cisco-intersight-integration/scripts/handoff-dashboards.sh"
echo "    bash \\${{CHILD_DIR}}/splunk-observability-nvidia-gpu-integration/scripts/handoff-dashboards.sh"
echo "    # AI-Pod-specific dashboards:"
echo "    for spec in \\${{DASHBOARDS_DIR}}/*.signalflow.yaml; do"
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
CHILD_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")/.." && pwd)/child-renders"
echo "Apply detectors via splunk-observability-native-ops:"
echo "    # Component detectors:"
echo "    bash \\${{CHILD_DIR}}/splunk-observability-cisco-nexus-integration/scripts/handoff-detectors.sh"
echo "    bash \\${{CHILD_DIR}}/splunk-observability-cisco-intersight-integration/scripts/handoff-detectors.sh"
echo "    bash \\${{CHILD_DIR}}/splunk-observability-nvidia-gpu-integration/scripts/handoff-detectors.sh"
echo "    # AI-Pod-specific detectors:"
echo "    for spec in \\${{DETECTORS_DIR}}/*.yaml; do"
echo "      bash skills/splunk-observability-native-ops/scripts/setup.sh \\\\"
echo "        --render --apply --realm {realm} --spec \\$spec --token-file \\$O11Y_API_TOKEN_FILE"
echo "    done"
"""
        )
    return helpers


def explain_composition_script(child_results: dict[str, str]) -> str:
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        "# Composition summary: which child skills contributed to this render.",
        'cat <<EOF',
        "AI Pod umbrella composition:",
        "",
    ]
    for child_key, status in child_results.items():
        lines.append(f"  {CHILD_SKILLS[child_key]}: {status}")
    lines.append("")
    lines.append("AI-Pod-specific additions:")
    lines.append("  - Dual-pipeline filtering pattern")
    lines.append("  - k8s_attributes/nim processor (model_name extraction)")
    lines.append("  - NIM / vLLM / Milvus / Trident / Portworx / Redfish scrapes")
    lines.append("  - rbac.customRules (when --nim-scrape-mode endpoints)")
    lines.append("  - OpenShift defaults (when --distribution openshift)")
    lines.append("  - signalfx.send_otlp_histograms: true")
    lines.append("EOF")
    return "\n".join(lines) + "\n"


def render_metadata(spec: dict[str, Any], realm: str, cluster_name: str, distribution: str, nim_scrape_mode: str, dcgm_pod_labels: bool, workshop: bool, child_results: dict[str, str]) -> dict[str, Any]:
    return {
        "skill": SKILL_NAME,
        "realm": realm,
        "cluster_name": cluster_name,
        "distribution": distribution,
        "nim_scrape_mode": nim_scrape_mode,
        "dcgm_pod_labels": dcgm_pod_labels,
        "workshop_mode": workshop,
        "children": child_results,
        "warnings": warnings(spec, distribution, nim_scrape_mode, dcgm_pod_labels),
    }


def warnings(spec: dict[str, Any], distribution: str, nim_scrape_mode: str, dcgm_pod_labels: bool) -> list[str]:
    items: list[str] = []
    if nim_scrape_mode == "endpoints":
        items.append(
            "NIM scrape mode 'endpoints' requires the rbac.customRules block (endpoints + endpointslices). "
            "The umbrella renders this automatically. Without it, scrapes fail with 'endpoints is forbidden'."
        )
    if not dcgm_pod_labels:
        items.append(
            "DCGM pod-label gap: pod/namespace labels are NOT exposed in DCGM_FI_* metrics by default. "
            "Pass --enable-dcgm-pod-labels to render the GPU child's patch."
        )
    if distribution == "openshift":
        items.append(
            "OpenShift defaults applied: kubeletstats.insecure_skip_verify=true (REQUIRED), certmanager.enabled=false, "
            "cloudProvider='', operator/operatorcrds disabled, gateway disabled. SCC helper rendered."
        )
    return items


def main() -> int:
    args = parse_args()
    spec_path = Path(args.spec)
    if not spec_path.is_file():
        print(f"ERROR: spec not found: {spec_path}", file=sys.stderr)
        return 1
    try:
        spec = load_spec(spec_path)
    except SpecError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    realm = args.realm or spec.get("realm", "us0")
    cluster_name = args.cluster_name or spec.get("cluster_name", "atl-ai-pod")
    distribution = args.distribution or spec.get("distribution", "openshift")
    nim_scrape_mode = args.nim_scrape_mode or (spec.get("nim") or {}).get("scrape_mode", "receiver_creator")
    if nim_scrape_mode not in VALID_NIM_SCRAPE_MODES:
        print(f"ERROR: nim_scrape_mode must be one of {sorted(VALID_NIM_SCRAPE_MODES)}; got {nim_scrape_mode!r}", file=sys.stderr)
        return 1
    dcgm_pod_labels = bool_flag(args.enable_dcgm_pod_labels) or bool(spec.get("enable_dcgm_pod_labels", False))
    workshop = bool_flag(args.workshop_mode) or bool((spec.get("workshop_mode") or {}).get("enabled", False))

    plan = {
        "skill": SKILL_NAME,
        "output_dir": str(Path(args.output_dir).resolve()),
        "realm": realm,
        "cluster_name": cluster_name,
        "distribution": distribution,
        "nim_scrape_mode": nim_scrape_mode,
        "dcgm_pod_labels": dcgm_pod_labels,
        "workshop_mode": workshop,
        "warnings": warnings(spec, distribution, nim_scrape_mode, dcgm_pod_labels),
    }

    if args.dry_run:
        if args.json:
            print(json.dumps(plan, indent=2, sort_keys=True))
        else:
            print("Cisco AI Pod Integration (umbrella) render plan")
            for key, value in plan.items():
                print(f"  {key}: {value}")
        return 0

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    child_results: dict[str, str] = {}

    # Invoke child skills.
    children_block = spec.get("children") or {}
    common_args = {
        "--realm": realm,
        "--cluster-name": cluster_name,
        "--distribution": distribution,
    }
    composed_overlay: dict[str, Any] = {}
    for child_key, child_skill in CHILD_SKILLS.items():
        child_block = children_block.get(child_key) or {}
        if not child_block.get("enabled", True):
            child_results[child_key] = "skipped (children." + child_key + ".enabled = false)"
            continue
        child_dir = out / "child-renders" / child_skill
        child_dir.mkdir(parents=True, exist_ok=True)
        spec_override = child_block.get("spec_override", "")
        extra: list[str] = []
        if spec_override:
            extra += ["--spec", spec_override]
        # Pass child-specific flags.
        if child_key == "nvidia_gpu" and dcgm_pod_labels:
            extra += ["--enable-dcgm-pod-labels"]
        if child_key == "intersight":
            if args.collector_release:
                extra += ["--collector-release", args.collector_release]
            if args.collector_namespace:
                extra += ["--collector-namespace", args.collector_namespace]
        try:
            invoke_child(child_skill, output_dir=child_dir, common_args=common_args, extra_args=extra)
            child_results[child_key] = "rendered"
            child_overlay = load_child_overlay(child_dir)
            composed_overlay = deep_merge(composed_overlay, child_overlay)
            # Pass through child manifests.
            if child_key == "intersight":
                src = child_dir / "intersight-integration"
                if src.is_dir():
                    dst = out / "intersight-integration"
                    if dst.exists():
                        shutil.rmtree(dst)
                    shutil.copytree(src, dst)
            if child_key == "nexus":
                src = child_dir / "secrets"
                if src.is_dir():
                    dst = out / "secrets"
                    dst.mkdir(parents=True, exist_ok=True)
                    for f in src.glob("*"):
                        if f.is_file():
                            shutil.copy2(f, dst / f.name)
            if child_key == "nvidia_gpu":
                src = child_dir / "dcgm-pod-labels-patch"
                if src.is_dir():
                    dst = out / "dcgm-pod-labels-patch"
                    if dst.exists():
                        shutil.rmtree(dst)
                    shutil.copytree(src, dst)
        except SpecError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    # Layer AI-Pod-specific additions on top.
    additions = ai_pod_overlay_additions(spec, cluster_name, distribution, nim_scrape_mode)
    final_overlay = deep_merge(composed_overlay, additions)
    write_yaml(out / "splunk-otel-overlay/values.overlay.yaml", final_overlay)

    # OpenShift SCC + workshop multi-tenant scripts.
    write_text(out / "openshift/scc.sh", openshift_scc_script(), executable=True)
    if workshop:
        write_text(out / "workshop/multi-tenant.sh", workshop_multi_tenant_script(spec), executable=True)

    # AI-Pod-specific dashboards + detectors.
    for name, payload in ai_pod_dashboard_specs(spec).items():
        write_yaml(out / f"dashboards/{name}.signalflow.yaml", payload)
    for name, payload in ai_pod_detector_specs(spec).items():
        write_yaml(out / f"detectors/{name}.yaml", payload)

    # Hand-off scripts.
    hec_enabled = (spec.get("splunk_platform_logs") or {}).get("enabled", False)
    for name, body in render_handoffs(spec, realm, cluster_name, distribution, hec_enabled).items():
        write_text(out / f"scripts/{name}", body, executable=True)
    write_text(out / "scripts/explain-composition.sh", explain_composition_script(child_results), executable=True)

    write_json(out / "metadata.json", render_metadata(spec, realm, cluster_name, distribution, nim_scrape_mode, dcgm_pod_labels, workshop, child_results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

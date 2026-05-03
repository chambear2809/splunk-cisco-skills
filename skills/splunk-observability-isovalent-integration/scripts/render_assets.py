"""Render the Splunk Observability Isovalent Integration overlay + helpers.

Composes a Splunk OTel collector agent.config overlay with seven Prometheus
scrape jobs for Cilium / Hubble / Envoy / Cilium operator / Tetragon agent
+ operator (and optional cilium-dnsproxy), a strict filter/includemetrics
allow-list, and the file-based Splunk Platform logs path
(extraFileLogs.filelog/tetragon + agent.extraVolumes hostPath mount). The
overlay is designed to merge with the base values produced by
splunk-observability-otel-collector-setup via yq deep-merge.

Outputs:
  - splunk-otel-overlay/values.overlay.yaml
  - dashboards/<name>.json   (token-scrubbed re-exports when --dashboards-source is set)
  - detectors/<name>.yaml
  - scripts/handoff-base-collector.sh
  - scripts/handoff-hec-token.sh
  - scripts/handoff-cisco-security-cloud.sh
  - scripts/handoff-dashboards.sh
  - scripts/handoff-detectors.sh
  - scripts/scrub-tokens.py
  - metadata.json
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Any


SKILL_NAME = "splunk-observability-isovalent-integration"
DEFAULT_TETRAGON_HOST_PATH = "/var/run/cilium/tetragon"
DEFAULT_TETRAGON_FILENAME_PATTERN = "*.log"

# Default metric allow-list. Curated from the production Gruve atl-ocp2
# deployment values + the Isovalent_Splunk_o11y reference repo. The goal:
# enough series to power the standard cilium/hubble/tetragon dashboards
# without flooding O11y with high-cardinality kernel-level event noise.
DEFAULT_METRIC_ALLOWLIST = [
    # Cilium
    "cilium_api_limiter_processed_requests_total",
    "cilium_bpf_map_ops_total",
    "cilium_endpoint_state",
    "cilium_errors_warnings_total",
    "cilium_ip_addresses",
    "cilium_ipam_capacity",
    "cilium_kubernetes_events_total",
    "cilium_policy_l7_total",
    "cilium_proxy_upstream_reply_seconds_bucket",
    # Hubble
    "hubble_dns_queries_total",
    "hubble_dns_responses_total",
    "hubble_drop_total",
    "hubble_flows_processed_total",
    "hubble_http_request_duration_seconds_bucket",
    "hubble_http_requests_total",
    "hubble_icmp_total",
    "hubble_policy_verdicts_total",
    "hubble_tcp_flags_total",
    # Tetragon
    "tetragon_events_total",
    "tetragon_dns_total",
    "tetragon_http_response_total",
    "tetragon_socket_stats_retransmitsegs_total",
    "tetragon_socket_stats_rxbytes_total",
    "tetragon_socket_stats_txbytes_total",
    "tetragon_socket_stats_udp_rxbytes_total",
    "tetragon_socket_stats_udp_txbytes_total",
    "tetragon_network_connect_total",
    "tetragon_network_close_total",
    # Host
    "system.cpu.utilization",
    "system.memory.utilization",
    "system.network.io",
    "system.network.errors",
    # Kubernetes
    "k8s.node.cpu.utilization",
    "k8s.node.memory.usage",
    "k8s.pod.cpu.utilization",
    "k8s.pod.memory.usage",
    "k8s.namespace.phase",
]


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
    parser.add_argument("--export-mode", default="")
    parser.add_argument("--legacy-fluentd-hec", default="false")
    parser.add_argument("--platform-hec-url", default="")
    parser.add_argument("--platform-hec-token-file", default="")
    parser.add_argument("--render-platform-hec-helper", default="false")
    parser.add_argument("--o11y-token-file", default="")
    parser.add_argument("--dashboards-source", default="")
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


def overlay_values(
    spec: dict[str, Any],
    *,
    cluster_name: str,
    distribution: str,
    export_mode: str,
    legacy_fluentd: bool,
    platform_hec_url: str,
) -> dict[str, Any]:
    scrape = spec.get("scrape") or {}
    metric_allowlist = list(DEFAULT_METRIC_ALLOWLIST)
    extras = (spec.get("metric_allowlist") or {}).get("extra") or []
    for name in extras:
        if name not in metric_allowlist:
            metric_allowlist.append(name)

    receivers: dict[str, Any] = {}
    pipeline_receivers: list[str] = ["hostmetrics", "kubeletstats", "otlp"]
    if scrape.get("cilium_agent_9962", True):
        receivers["prometheus/isovalent_cilium"] = _scrape_job(
            "cilium_metrics_9962", "cilium", 9962, "k8s_app"
        )
        pipeline_receivers.append("prometheus/isovalent_cilium")
    if scrape.get("hubble_metrics_9965", True):
        receivers["prometheus/isovalent_hubble"] = _scrape_job(
            "hubble_metrics_9965", "cilium", 9965, "k8s_app"
        )
        pipeline_receivers.append("prometheus/isovalent_hubble")
    if scrape.get("cilium_envoy_9964", True):
        receivers["prometheus/isovalent_envoy"] = _scrape_job(
            "envoy_metrics_9964", "cilium-envoy", 9964, "k8s_app"
        )
        pipeline_receivers.append("prometheus/isovalent_envoy")
    if scrape.get("cilium_operator_9963", True):
        receivers["prometheus/isovalent_operator"] = _scrape_job_operator(
            "cilium_operator_metrics_9963", 9963
        )
        pipeline_receivers.append("prometheus/isovalent_operator")
    if scrape.get("tetragon_2112", True):
        receivers["prometheus/isovalent_tetragon"] = _scrape_job_tetragon(
            "tetragon_metrics_2112", 2112
        )
        pipeline_receivers.append("prometheus/isovalent_tetragon")
    if scrape.get("tetragon_operator_2113", True):
        receivers["prometheus/isovalent_tetragon_operator"] = _scrape_job_tetragon_operator(
            "tetragon_operator_metrics_2113", 2113
        )
        pipeline_receivers.append("prometheus/isovalent_tetragon_operator")
    if scrape.get("cilium_dnsproxy", False):
        receivers["prometheus/isovalent_dnsproxy"] = _scrape_job(
            "cilium_dnsproxy_metrics", "cilium-dnsproxy", 9967, "k8s_app"
        )
        pipeline_receivers.append("prometheus/isovalent_dnsproxy")

    overlay: dict[str, Any] = {
        "clusterName": cluster_name or "lab-cluster",
        "distribution": distribution or "kubernetes",
        # Subtractive overrides for the Isovalent profile: we typically want
        # the gateway off (collector pushes direct to O11y) and operator off
        # (Isovalent uses its own CRDs; the OTel operator would conflict).
        "operator": {"enabled": False},
        "operatorcrds": {"installed": False},
        "gateway": {"enabled": False},
        # OpenShift requires kubeletstats to skip TLS verify (self-signed kubelet
        # certs). Other distributions accept this default safely.
        "agent": {
            "config": {
                "extensions": {
                    "k8s_observer": {"auth_type": "serviceAccount", "observe_pods": True},
                },
                "receivers": dict(receivers, **{
                    "kubeletstats": {"collection_interval": "30s", "insecure_skip_verify": True},
                }),
                "processors": {
                    "filter/includemetrics": {
                        "metrics": {
                            "include": {
                                "match_type": "strict",
                                "metric_names": metric_allowlist,
                            }
                        }
                    },
                    "resourcedetection": {"detectors": ["system"], "system": {"hostname_sources": ["os"]}},
                },
                "service": {
                    "pipelines": {
                        "metrics": {
                            "exporters": ["signalfx"],
                            "receivers": pipeline_receivers,
                            "processors": [
                                "memory_limiter",
                                "batch",
                                "filter/includemetrics",
                                "resourcedetection",
                                "resource",
                            ],
                        }
                    }
                },
            }
        },
    }

    splunk_block = spec.get("splunk_platform") or {}
    if splunk_block.get("enabled", True) and export_mode == "file" and not legacy_fluentd:
        host_path = (spec.get("tetragon_export") or {}).get("host_path", DEFAULT_TETRAGON_HOST_PATH)
        filename_pattern = (spec.get("tetragon_export") or {}).get("filename_pattern", DEFAULT_TETRAGON_FILENAME_PATTERN)
        index = splunk_block.get("index", "cisco_isovalent")
        sourcetype = splunk_block.get("sourcetype", "cisco:isovalent")
        # The hostPath mount + extraFileLogs.filelog/tetragon block is the
        # production-validated path (see references/tetragon-hostpath-coordination.md).
        overlay["agent"]["extraVolumes"] = [{"name": "tetragon", "hostPath": {"path": host_path}}]
        overlay["agent"]["extraVolumeMounts"] = [{"name": "tetragon", "mountPath": host_path}]
        overlay["splunkPlatform"] = {
            "logsEnabled": True,
        }
        if platform_hec_url:
            overlay["splunkPlatform"]["endpoint"] = platform_hec_url
        if splunk_block.get("insecure_skip_verify"):
            overlay["splunkPlatform"]["insecureSkipVerify"] = True
        overlay["logsCollection"] = {
            "containers": {"useSplunkIncludeAnnotation": True},
            "extraFileLogs": {
                "filelog/tetragon": {
                    "include": [f"{host_path}/{filename_pattern}"],
                    "start_at": "beginning",
                    "include_file_path": True,
                    "include_file_name": False,
                    "resource": {
                        "com.splunk.index": index,
                        "com.splunk.source": f"{host_path}/",
                        "host.name": "EXPR(env(\"K8S_NODE_NAME\"))",
                        "com.splunk.sourcetype": sourcetype,
                    },
                }
            },
        }
    elif splunk_block.get("enabled", True) and export_mode == "stdout" and not legacy_fluentd:
        # stdout mode: rely on Splunk OTel collector's container log collection.
        # Tetragon's stdout already flows through the standard logsCollection
        # pipeline; we just need to enable splunkPlatform.logsEnabled.
        overlay["splunkPlatform"] = {"logsEnabled": True}
        if platform_hec_url:
            overlay["splunkPlatform"]["endpoint"] = platform_hec_url
    elif legacy_fluentd:
        # Legacy fluentd path renders nothing in the overlay -- the Tetragon
        # Helm values already include the fluentd config (see
        # cisco-isovalent-platform-setup --export-mode fluentd). We still
        # leave splunkPlatform.logsEnabled false because the legacy path
        # doesn't use the OTel splunkhec exporter.
        pass

    return overlay


def _scrape_job(name: str, app_label: str, port: int, label_key: str) -> dict[str, Any]:
    return {
        "config": {
            "scrape_configs": [
                {
                    "job_name": name,
                    "scrape_interval": "30s",
                    "metrics_path": "/metrics",
                    "kubernetes_sd_configs": [{"role": "pod"}],
                    "relabel_configs": [
                        {
                            "source_labels": [f"__meta_kubernetes_pod_label_{label_key}"],
                            "action": "keep",
                            "regex": app_label,
                        },
                        {
                            "source_labels": ["__meta_kubernetes_pod_ip"],
                            "target_label": "__address__",
                            "replacement": "${__meta_kubernetes_pod_ip}:" + str(port),
                        },
                        {"target_label": "job", "replacement": name},
                    ],
                }
            ]
        }
    }


def _scrape_job_operator(name: str, port: int) -> dict[str, Any]:
    """Cilium operator pods use the io_cilium_app=operator label.

    Note: the operator runs in its own Deployment, not the cilium DaemonSet,
    so the pod IP differs. The relabel approach still works via
    __meta_kubernetes_pod_ip.
    """
    return {
        "config": {
            "scrape_configs": [
                {
                    "job_name": name,
                    "scrape_interval": "30s",
                    "metrics_path": "/metrics",
                    "kubernetes_sd_configs": [{"role": "pod"}],
                    "relabel_configs": [
                        {
                            "source_labels": ["__meta_kubernetes_pod_label_io_cilium_app"],
                            "action": "keep",
                            "regex": "operator",
                        },
                        {
                            "source_labels": ["__meta_kubernetes_pod_ip"],
                            "target_label": "__address__",
                            "replacement": "${__meta_kubernetes_pod_ip}:" + str(port),
                        },
                        {"target_label": "job", "replacement": name},
                    ],
                }
            ]
        }
    }


def _scrape_job_tetragon(name: str, port: int) -> dict[str, Any]:
    """Tetragon DaemonSet pods use app.kubernetes.io/name=tetragon."""
    return {
        "config": {
            "scrape_configs": [
                {
                    "job_name": name,
                    "scrape_interval": "30s",
                    "metrics_path": "/metrics",
                    "kubernetes_sd_configs": [{"role": "pod"}],
                    "relabel_configs": [
                        {
                            "source_labels": ["__meta_kubernetes_pod_label_app_kubernetes_io_name"],
                            "action": "keep",
                            "regex": "tetragon",
                        },
                        {
                            "source_labels": ["__meta_kubernetes_pod_ip"],
                            "target_label": "__address__",
                            "replacement": "${__meta_kubernetes_pod_ip}:" + str(port),
                        },
                        {"target_label": "job", "replacement": name},
                    ],
                }
            ]
        }
    }


def _scrape_job_tetragon_operator(name: str, port: int) -> dict[str, Any]:
    """Tetragon operator metrics on port 2113."""
    return {
        "config": {
            "scrape_configs": [
                {
                    "job_name": name,
                    "scrape_interval": "30s",
                    "metrics_path": "/metrics",
                    "kubernetes_sd_configs": [{"role": "pod"}],
                    "relabel_configs": [
                        {
                            "source_labels": ["__meta_kubernetes_pod_label_app_kubernetes_io_name"],
                            "action": "keep",
                            "regex": "tetragon-operator",
                        },
                        {
                            "source_labels": ["__meta_kubernetes_pod_ip"],
                            "target_label": "__address__",
                            "replacement": "${__meta_kubernetes_pod_ip}:" + str(port),
                        },
                        {"target_label": "job", "replacement": name},
                    ],
                }
            ]
        }
    }


SCRUB_TOKEN_PY = '''#!/usr/bin/env python3
"""Token scrubber for dashboard JSON re-exports.

Walks a JSON document and rewrites any value under access-token-shaped keys
to a placeholder. Refuses to write the output if the input contained a
plausibly-real token.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


SECRET_KEYS = {"accesstoken", "access_token", "apitoken", "api_token", "x_sf_token", "xsftoken"}
PLACEHOLDER = "${REDACTED}"
REAL_TOKEN_RE = re.compile(r"[A-Za-z0-9._-]{20,}")


def walk(node):
    if isinstance(node, dict):
        return {k: _scrub(k, v) for k, v in node.items()}
    if isinstance(node, list):
        return [walk(item) for item in node]
    return node


def _scrub(key, value):
    normalized = "".join(c for c in str(key).lower() if c.isalnum() or c == "_")
    if normalized in SECRET_KEYS:
        if isinstance(value, str) and value and REAL_TOKEN_RE.fullmatch(value):
            return PLACEHOLDER
    return walk(value)


def main(argv):
    if len(argv) != 3:
        print(f"Usage: {argv[0]} <input.json> <output.json>", file=sys.stderr)
        return 1
    src = Path(argv[1])
    dst = Path(argv[2])
    raw = json.loads(src.read_text(encoding="utf-8"))
    scrubbed = walk(raw)
    # Defense in depth: re-scan the scrubbed text for any remaining patterns
    # that look like a Bearer or X-SF-Token value.
    text = json.dumps(scrubbed, indent=2, sort_keys=True)
    leak_scan = re.compile(r'"(?:accessToken|access_token|X-SF-Token|apiToken)"\\s*:\\s*"[A-Za-z0-9._-]{20,}"')
    if leak_scan.search(text):
        print("ERROR: scrubbed JSON still contains a token-shaped value.", file=sys.stderr)
        return 1
    dst.write_text(text + "\\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
'''


def render_handoffs(args: argparse.Namespace, spec: dict[str, Any], realm: str, cluster_name: str, distribution: str) -> dict[str, str]:
    handoffs = spec.get("handoffs") or {}
    helpers: dict[str, str] = {}

    if handoffs.get("base_collector", True):
        helpers["handoff-base-collector.sh"] = (
            f"""#!/usr/bin/env bash
set -euo pipefail

# Render the base Splunk OTel collector values, then merge our overlay.
# Requires yq (https://github.com/mikefarah/yq) for the deep-merge step.
if ! command -v yq >/dev/null 2>&1; then
    echo 'ERROR: yq required for overlay merge (https://github.com/mikefarah/yq).' >&2
    exit 1
fi

OVERLAY="$(cd "$(dirname "${{BASH_SOURCE[0]}}")/.." && pwd)/splunk-otel-overlay/values.overlay.yaml"
BASE_OUTPUT_DIR="${{BASE_OUTPUT_DIR:-/tmp/splunk-observability-otel-rendered}}"

echo "Step 1: Render the base Splunk OTel collector values."
echo "  Run:"
echo "    bash skills/splunk-observability-otel-collector-setup/scripts/setup.sh \\\\"
echo "      --render-k8s --realm {realm} \\\\"
echo "      --cluster-name {cluster_name} --distribution {distribution} \\\\"
echo "      --output-dir ${{BASE_OUTPUT_DIR}}"
echo
echo "Step 2: Merge this skill's overlay into the base values."
echo "  Run:"
echo "    yq eval-all '. as \\$item ireduce ({{}}; . * \\$item)' \\\\"
echo "      ${{BASE_OUTPUT_DIR}}/k8s/values.yaml \\\\"
echo "      ${{OVERLAY}} \\\\"
echo "      > /tmp/merged-values.yaml"
echo
echo "Step 3: Apply the merged values via helm (token via --set --reuse-values)."
echo "  Run:"
echo "    helm upgrade --install splunk-otel-collector splunk-otel-collector-chart/splunk-otel-collector \\\\"
echo "      -n splunk-otel --create-namespace --reuse-values \\\\"
echo "      -f /tmp/merged-values.yaml \\\\"
echo '      --set splunkObservability.accessToken="$(cat $O11Y_TOKEN_FILE)"'
"""
        )

    if handoffs.get("hec_service", True):
        # splunk-hec-service-setup uses --token-name (not --hec-token-name) per
        # its setup.sh. Pin the platform to enterprise|cloud as required by
        # that skill's --platform flag.
        index = (spec.get("splunk_platform") or {}).get("index", "cisco_isovalent")
        helpers["handoff-hec-token.sh"] = (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n\n"
            "# Provision a Splunk Platform HEC token via splunk-hec-service-setup.\n"
            "# Set PLATFORM=enterprise or PLATFORM=cloud before running.\n"
            'PLATFORM="${PLATFORM:-enterprise}"\n'
            'echo "Run:"\n'
            'echo "  bash skills/splunk-hec-service-setup/scripts/setup.sh \\\\"\n'
            'echo "    --platform ${PLATFORM} --phase render \\\\"\n'
            'echo "    --token-name isovalent_tetragon \\\\"\n'
            f'echo "    --default-index {index} \\\\"\n'
            f'echo "    --allowed-indexes {index}"\n'
        )

    if handoffs.get("cisco_security_cloud", True):
        # cisco-security-cloud-setup uses configure_input.sh (not --product flag).
        # The Isovalent Runtime Security input type is sbg_isovalent_input per
        # skills/cisco-security-cloud-setup/products.json lines 200-219.
        helpers["handoff-cisco-security-cloud.sh"] = (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n\n"
            "# Configure the Splunk Platform Cisco Security Cloud App input for\n"
            "# Isovalent Runtime Security (sourcetype cisco:isovalent:processExec,\n"
            "# index cisco_isovalent). The app provides field aliases on the\n"
            "# specific sourcetype for Splunk Threat Research Team detections.\n"
            'echo "Step 1: Install the Cisco Security Cloud App if not already installed:"\n'
            'echo "  bash skills/cisco-security-cloud-setup/scripts/setup.sh --install"\n'
            "echo\n"
            'echo "Step 2: Configure the Isovalent Runtime Security input:"\n'
            'echo "  bash skills/cisco-security-cloud-setup/scripts/configure_input.sh \\\\"\n'
            'echo "    --input-type sbg_isovalent_input \\\\"\n'
            'echo "    --name Isovalent_Default \\\\"\n'
            'echo "    --set index cisco_isovalent \\\\"\n'
            'echo "    --set interval 300"\n'
            "echo\n"
            'echo "(Optional) For the edge-processor variant, repeat with --input-type sbg_isovalent_edge_processor_input."\n'
        )

    if handoffs.get("dashboard_builder", True):
        # splunk-observability-dashboard-builder uses --spec (not --import-json)
        # per its setup.sh lines 35-39 + 76-79.
        helpers["handoff-dashboards.sh"] = (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n\n"
            "# Import the bundled token-scrubbed dashboards via splunk-observability-dashboard-builder.\n"
            'DASHBOARDS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/dashboards"\n'
            'echo "Run for each dashboard JSON in ${DASHBOARDS_DIR}:"\n'
            'echo "  for spec in ${DASHBOARDS_DIR}/*.json; do"\n'
            'echo "    bash skills/splunk-observability-dashboard-builder/scripts/setup.sh \\\\"\n'
            'echo "      --render --apply --realm \\$REALM \\\\"\n'
            'echo "      --spec \\$spec \\\\"\n'
            'echo "      --token-file \\$O11Y_API_TOKEN_FILE"\n'
            'echo "  done"\n'
        )

    if handoffs.get("native_ops", True):
        helpers["handoff-detectors.sh"] = (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n\n"
            "# Apply starter detectors via splunk-observability-native-ops.\n"
            'DETECTORS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/detectors"\n'
            'echo "Run for each detector spec in ${DETECTORS_DIR}:"\n'
            'echo "  for spec in ${DETECTORS_DIR}/*.yaml; do"\n'
            'echo "    bash skills/splunk-observability-native-ops/scripts/setup.sh \\\\"\n'
            'echo "      --render --apply --realm \\$REALM \\\\"\n'
            'echo "      --spec \\$spec \\\\"\n'
            'echo "      --token-file \\$O11Y_API_TOKEN_FILE"\n'
            'echo "  done"\n'
        )

    return helpers


def render_detectors(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    block = spec.get("detectors") or {}
    if not block.get("enabled", True):
        return {}
    thresholds = block.get("thresholds") or {}
    detectors = {
        "cilium-drop-rate": {
            "test_type": "isovalent",
            "detectors": [
                {
                    "name": "Cilium drop rate",
                    "metric": "hubble_drop_total",
                    "direction": "above",
                    "threshold": thresholds.get("cilium_drop_rate_per_s", 100),
                    "severity": "Major",
                    "aggregation": "rate",
                }
            ],
        },
        "hubble-dns-failures": {
            "test_type": "isovalent",
            "detectors": [
                {
                    "name": "Hubble DNS failure rate",
                    "metric": "hubble_dns_responses_total",
                    "direction": "above",
                    "threshold": thresholds.get("hubble_dns_failure_rate", 0.05),
                    "severity": "Warning",
                    "aggregation": "ratio",
                }
            ],
        },
        "tetragon-event-rate": {
            "test_type": "isovalent",
            "detectors": [
                {
                    "name": "Tetragon event rate",
                    "metric": "tetragon_events_total",
                    "direction": "above",
                    "threshold": thresholds.get("tetragon_event_rate_per_s", 1000),
                    "severity": "Info",
                    "aggregation": "rate",
                }
            ],
        },
    }
    return detectors


def render_metadata(args: argparse.Namespace, spec: dict[str, Any]) -> dict[str, Any]:
    splunk_block = spec.get("splunk_platform") or {}
    return {
        "skill": SKILL_NAME,
        "realm": args.realm or spec.get("realm", ""),
        "cluster_name": args.cluster_name or spec.get("cluster_name", ""),
        "distribution": args.distribution or spec.get("distribution", ""),
        "export_mode": args.export_mode or (spec.get("tetragon_export") or {}).get("mode", "file"),
        "splunk_platform_enabled": splunk_block.get("enabled", True),
        "splunk_platform_index": splunk_block.get("index", "cisco_isovalent"),
        "splunk_platform_sourcetype": splunk_block.get("sourcetype", "cisco:isovalent"),
        "scrape_jobs": [k for k, v in (spec.get("scrape") or {}).items() if v],
        "warnings": warnings(args, spec),
    }


def warnings(args: argparse.Namespace, spec: dict[str, Any]) -> list[str]:
    items: list[str] = []
    if bool_flag(args.legacy_fluentd_hec):
        items.append(
            "DEPRECATED: --legacy-fluentd-hec uses fluent-plugin-splunk-hec which "
            "was archived 2025-06-24. Plan to migrate to the file-based path "
            "(default --export-mode file)."
        )
    distribution = args.distribution or spec.get("distribution", "")
    if distribution == "openshift":
        items.append(
            "OpenShift detected: the overlay enables kubeletstats.insecure_skip_verify=true "
            "(required for kubelet self-signed certs) and disables certmanager."
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
    export_mode = args.export_mode or (spec.get("tetragon_export") or {}).get("mode", "file")
    legacy_fluentd = bool_flag(args.legacy_fluentd_hec)

    plan = {
        "skill": SKILL_NAME,
        "output_dir": str(Path(args.output_dir).resolve()),
        "realm": realm,
        "cluster_name": cluster_name,
        "distribution": distribution,
        "export_mode": export_mode,
        "legacy_fluentd_hec": legacy_fluentd,
        "warnings": warnings(args, spec),
    }

    if args.dry_run:
        if args.json:
            print(json.dumps(plan, indent=2, sort_keys=True))
        else:
            print("Splunk Observability Isovalent Integration render plan")
            for key, value in plan.items():
                print(f"  {key}: {value}")
        return 0

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    overlay = overlay_values(
        spec,
        cluster_name=cluster_name,
        distribution=distribution,
        export_mode=export_mode,
        legacy_fluentd=legacy_fluentd,
        platform_hec_url=args.platform_hec_url,
    )
    write_yaml(out / "splunk-otel-overlay/values.overlay.yaml", overlay)

    write_text(out / "scripts/scrub-tokens.py", SCRUB_TOKEN_PY, executable=True)

    # Dashboards: copy + scrub when --dashboards-source is provided. Otherwise
    # write a placeholder README explaining how to drop in the upstream JSONs.
    dashboards_block = spec.get("dashboards") or {}
    source_dir = args.dashboards_source or dashboards_block.get("source_dir", "")
    dashboards_out = out / "dashboards"
    if dashboards_block.get("enabled", True) and source_dir:
        src = Path(source_dir)
        if not src.is_dir():
            print(f"ERROR: --dashboards-source {source_dir} is not a directory.", file=__import__("sys").stderr)
            return 1
        for json_file in sorted(src.glob("*.json")):
            target = dashboards_out / json_file.name
            target.parent.mkdir(parents=True, exist_ok=True)
            # Use the rendered scrub-tokens.py script so the same logic that
            # validate.sh exercises also runs at render time.
            scrubber = out / "scripts" / "scrub-tokens.py"
            import subprocess
            result = subprocess.run(
                ["python3", str(scrubber), str(json_file), str(target)],
                check=False,
            )
            if result.returncode != 0:
                print(f"ERROR: scrub-tokens refused {json_file}; remove the inline tokens before re-rendering.", file=__import__("sys").stderr)
                return 1
    elif dashboards_block.get("enabled", True):
        write_text(
            dashboards_out / "README.md",
            "# Dashboards\n\n"
            "Drop the upstream Cilium / Hubble dashboard JSON exports into this directory\n"
            "(or re-run the renderer with --dashboards-source <dir>) and they will be\n"
            "token-scrubbed via scripts/scrub-tokens.py.\n\n"
            "Reference dashboards are available at\n"
            "/Users/alecchamberlain/Documents/GitHub/Isovalent_Splunk_o11y/examples/*.json.\n"
            "Do NOT copy from values/*.yaml in that repo -- those files have been observed\n"
            "to contain plaintext access tokens.\n",
        )

    detectors = render_detectors(spec)
    for name, payload in detectors.items():
        write_yaml(out / f"detectors/{name}.yaml", payload)

    helpers = render_handoffs(args, spec, realm, cluster_name, distribution)
    for name, body in helpers.items():
        write_text(out / f"scripts/{name}", body, executable=True)

    write_json(out / "metadata.json", render_metadata(args, spec))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

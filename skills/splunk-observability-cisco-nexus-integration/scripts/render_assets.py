"""Render the Cisco Nexus -> Splunk Observability Cloud overlay + helpers.

Outputs:
  - splunk-otel-overlay/values.overlay.yaml  (clusterReceiver.config.receivers.cisco_os
                                              + metrics/cisco-os-metrics pipeline)
  - secrets/cisco-nexus-ssh-secret.yaml      (manifest stub; placeholders only)
  - dashboards/<name>.signalflow.yaml
  - detectors/<name>.yaml
  - scripts/handoff-base-collector.sh
  - scripts/handoff-dashboards.sh
  - scripts/handoff-detectors.sh
  - metadata.json
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
from pathlib import Path
from typing import Any


SKILL_NAME = "splunk-observability-cisco-nexus-integration"


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
    parser.add_argument("--nexus-device", action="append", default=[],
                        help="Override device list. Format: name:host[:port]. May be repeated.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


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


def parse_cli_devices(devices: list[str]) -> list[dict[str, Any]]:
    """Parse `name:host[:port]` device strings from --nexus-device."""
    parsed: list[dict[str, Any]] = []
    for entry in devices:
        parts = entry.split(":")
        if len(parts) < 2:
            raise SpecError(f"Invalid --nexus-device {entry!r}; expected name:host[:port]")
        name = parts[0].strip()
        host = parts[1].strip()
        port = int(parts[2]) if len(parts) > 2 else 22
        if not name or not host:
            raise SpecError(f"Invalid --nexus-device {entry!r}; name and host required")
        parsed.append({"name": name, "host": host, "port": port})
    return parsed


def merged_devices(spec: dict[str, Any], cli_devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if cli_devices:
        return cli_devices
    return spec.get("devices") or []


def cisco_os_receiver(spec: dict[str, Any], devices: list[dict[str, Any]], ssh_secret: dict[str, Any]) -> dict[str, Any]:
    """Render the cisco_os receiver block in the multi-device + global-scrapers format.

    Per PR #45562 (merged Feb 2026, available v0.149.0+), the receiver
    accepts a top-level `devices:` list and a top-level `scrapers:` block
    that applies globally to all devices unless overridden per-device.
    Auth references the K8s Secret via env-var substitutions; the actual
    credentials are mounted via the chart's `agent.extraEnvs` block (rendered
    elsewhere) so the values file never sees the secret.
    """
    if not devices:
        raise SpecError("No Nexus devices configured. Use spec.devices[] or --nexus-device.")
    scrapers_block = spec.get("scrapers") or {}
    auth = {
        "username": "${env:CISCO_NEXUS_SSH_USERNAME}",
    }
    if ssh_secret.get("key_file_key"):
        auth["key_file"] = "/etc/cisco-nexus-ssh/key"
    else:
        auth["password"] = "${env:CISCO_NEXUS_SSH_PASSWORD}"
    receiver: dict[str, Any] = {
        "collection_interval": f"{spec.get('collection_interval', 60)}s",
        "timeout": f"{spec.get('timeout', 30)}s",
        "devices": [
            {
                "name": d["name"],
                "host": d["host"],
                "port": int(d.get("port", 22)),
                "auth": dict(auth),
            }
            for d in devices
        ],
        "scrapers": _scrapers_block(scrapers_block),
    }
    return receiver


def _scrapers_block(scrapers_block: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    system_block = scrapers_block.get("system") or {"enabled": True}
    if system_block.get("enabled", True):
        metrics = system_block.get("metrics") or {}
        out["system"] = {
            "metrics": {
                "cisco.device.up": {"enabled": metrics.get("cisco_device_up", True)},
                "system.cpu.utilization": {"enabled": metrics.get("system_cpu_utilization", True)},
                "system.memory.utilization": {"enabled": metrics.get("system_memory_utilization", True)},
            }
        }
    interfaces_block = scrapers_block.get("interfaces") or {"enabled": True}
    if interfaces_block.get("enabled", True):
        metrics = interfaces_block.get("metrics") or {}
        out["interfaces"] = {
            "metrics": {
                "system.network.io": {"enabled": metrics.get("system_network_io", True)},
                "system.network.errors": {"enabled": metrics.get("system_network_errors", True)},
                "system.network.packet.dropped": {"enabled": metrics.get("system_network_packet_dropped", True)},
                "system.network.packet.count": {"enabled": metrics.get("system_network_packet_count", True)},
                "system.network.interface.status": {"enabled": metrics.get("system_network_interface_status", True)},
            }
        }
    return out


def overlay_values(spec: dict[str, Any], receiver: dict[str, Any], ssh_secret: dict[str, Any], cluster_name: str, distribution: str) -> dict[str, Any]:
    """Build the OTel collector overlay.

    cisco_os runs in the clusterReceiver (one-instance) so we don't double-scrape
    the same Nexus device from every node. The receiver pulls SSH creds from
    env vars populated by clusterReceiver.extraEnvs referencing the K8s Secret.
    """
    extra_envs = [
        {
            "name": "CISCO_NEXUS_SSH_USERNAME",
            "valueFrom": {
                "secretKeyRef": {
                    "name": ssh_secret.get("name", "cisco-nexus-ssh"),
                    "key": ssh_secret.get("username_key", "username"),
                }
            },
        }
    ]
    if ssh_secret.get("key_file_key"):
        extra_envs.append(
            {
                "name": "CISCO_NEXUS_SSH_KEY_FILE",
                "value": "/etc/cisco-nexus-ssh/key",
            }
        )
    else:
        extra_envs.append(
            {
                "name": "CISCO_NEXUS_SSH_PASSWORD",
                "valueFrom": {
                    "secretKeyRef": {
                        "name": ssh_secret.get("name", "cisco-nexus-ssh"),
                        "key": ssh_secret.get("password_key", "password"),
                    }
                },
            }
        )
    overlay: dict[str, Any] = {
        "clusterName": cluster_name or "lab-cluster",
        "distribution": distribution or "kubernetes",
        "clusterReceiver": {
            "enabled": True,
            "extraEnvs": extra_envs,
            "config": {
                "receivers": {"cisco_os": receiver},
                "processors": {
                    "memory_limiter": {"check_interval": "2s", "limit_mib": 200},
                    "batch": {},
                    "resourcedetection": {"detectors": ["system"], "system": {"hostname_sources": ["os"]}},
                    "resource": {"attributes": [{"action": "upsert", "key": "k8s.cluster.name", "value": cluster_name}]},
                },
                "service": {
                    "pipelines": {
                        "metrics/cisco-os-metrics": {
                            "exporters": ["signalfx"],
                            "processors": ["memory_limiter", "batch", "resourcedetection", "resource"],
                            "receivers": ["cisco_os"],
                        }
                    }
                },
            },
        },
    }
    if ssh_secret.get("key_file_key"):
        # Mount the SSH key into clusterReceiver via extraVolumes/Mounts.
        overlay["clusterReceiver"]["extraVolumes"] = [
            {
                "name": "cisco-nexus-ssh-key",
                "secret": {
                    "secretName": ssh_secret.get("name", "cisco-nexus-ssh"),
                    "items": [{"key": ssh_secret["key_file_key"], "path": "key"}],
                    "defaultMode": 0o400,
                },
            }
        ]
        overlay["clusterReceiver"]["extraVolumeMounts"] = [
            {"name": "cisco-nexus-ssh-key", "mountPath": "/etc/cisco-nexus-ssh", "readOnly": True}
        ]
    return overlay


def secret_manifest_stub(ssh_secret: dict[str, Any]) -> str:
    name = ssh_secret.get("name", "cisco-nexus-ssh")
    namespace = ssh_secret.get("namespace", "splunk-otel")
    if ssh_secret.get("key_file_key"):
        return (
            "# Cisco Nexus SSH credentials (key auth)\n"
            f"# Create with:\n"
            f"#   kubectl create secret generic {name} -n {namespace} \\\n"
            f"#     --from-literal=username=splunk-otel \\\n"
            f"#     --from-file={ssh_secret['key_file_key']}=/path/to/ssh/key\n"
            "#\n"
            "# Manifest stub (DO NOT apply with placeholder values):\n"
            "apiVersion: v1\n"
            "kind: Secret\n"
            "metadata:\n"
            f"  name: {name}\n"
            f"  namespace: {namespace}\n"
            "type: Opaque\n"
            "stringData:\n"
            f"  {ssh_secret.get('username_key', 'username')}: PLACEHOLDER_USERNAME\n"
            f"  {ssh_secret['key_file_key']}: |\n"
            "    -----BEGIN OPENSSH PRIVATE KEY-----\n"
            "    PLACEHOLDER_PRIVATE_KEY_PEM_CONTENT\n"
            "    -----END OPENSSH PRIVATE KEY-----\n"
        )
    return (
        "# Cisco Nexus SSH credentials (password auth)\n"
        f"# Create with:\n"
        f"#   kubectl create secret generic {name} -n {namespace} \\\n"
        f"#     --from-literal=username=splunk-otel \\\n"
        f"#     --from-file=password=/tmp/nexus_password\n"
        "#\n"
        "# Or via this manifest after replacing placeholders:\n"
        "apiVersion: v1\n"
        "kind: Secret\n"
        "metadata:\n"
        f"  name: {name}\n"
        f"  namespace: {namespace}\n"
        "type: Opaque\n"
        "stringData:\n"
        f"  {ssh_secret.get('username_key', 'username')}: PLACEHOLDER_USERNAME\n"
        f"  {ssh_secret.get('password_key', 'password')}: PLACEHOLDER_PASSWORD\n"
    )


def dashboard_specs(
    spec: dict[str, Any], realm: str, cluster_name: str
) -> dict[str, dict[str, Any]]:
    if not (spec.get("dashboards") or {}).get("enabled", True):
        return {}
    charts = [
        ("Device up", "cisco.device.up"),
        ("CPU utilization", "system.cpu.utilization"),
        ("Memory utilization", "system.memory.utilization"),
        ("Interface status", "system.network.interface.status"),
        ("Network throughput", "system.network.io"),
        ("Network errors", "system.network.errors"),
        ("Packet drops", "system.network.packet.dropped"),
    ]
    return {
        "cisco-nexus-overview": {
            "api_version": "splunk-observability-dashboard-builder/v1",
            "mode": "classic-api",
            "realm": realm,
            "dashboard_group": {
                "name": "Cisco Nexus Observability",
                "description": f"Cisco Nexus dashboards for cluster {cluster_name}.",
            },
            "dashboard": {
                "name": "Cisco Nexus Overview",
                "description": "Nexus device + interface health overview",
                "chart_density": "DEFAULT",
                "filters": {
                    "variables": [
                        {
                            "property": "k8s.cluster.name",
                            "alias": "Cluster",
                            "value": [cluster_name],
                            "required": True,
                            "restricted": True,
                        }
                    ]
                },
            },
            "charts": [
                _chart(name, metric, cluster_name, position)
                for position, (name, metric) in enumerate(charts)
            ],
        }
    }


def _chart(name: str, metric: str, cluster_name: str, position: int) -> dict[str, Any]:
    metric_literal = json.dumps(metric)
    cluster_literal = json.dumps(cluster_name)
    return {
        "id": re.sub(r"[^a-z0-9]+", "-", metric.lower()).strip("-") or "metric",
        "name": name,
        "description": f"{metric} from cisco_os receiver",
        "type": "TimeSeriesChart",
        "plot_type": "LineChart",
        "row": position // 2,
        "column": 0 if position % 2 == 0 else 6,
        "width": 6,
        "height": 1,
        "program_text": (
            f"data({metric_literal}, filter=filter('k8s.cluster.name', {cluster_literal}))"
            f".publish(label={metric_literal})"
        ),
        "publish_label": metric,
    }


def _detector_spec(
    *,
    realm: str,
    cluster_name: str,
    name: str,
    metric: str,
    direction: str,
    threshold: int | float,
    severity: str,
    aggregation: str,
    detect_label: str,
) -> dict[str, Any]:
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise SpecError(f"Detector threshold for {name!r} must be numeric.")
    transformations = {
        "min": ".min()",
        "rate": ".rate()",
        "mean": ".mean()",
    }
    comparators = {"above": ">", "below": "<", "at_or_below": "<="}
    direction_text = {
        "above": "above",
        "below": "below",
        "at_or_below": "at or below",
    }
    if aggregation not in transformations or direction not in comparators:
        raise SpecError(
            f"Unsupported detector aggregation/direction: {aggregation!r}/{direction!r}"
        )
    stream = (
        f"data({json.dumps(metric)}, "
        f"filter=filter('k8s.cluster.name', {json.dumps(cluster_name)}))"
    )
    signal_label = f"{detect_label}_signal"
    program_text = (
        f"signal = {stream}{transformations[aggregation]}"
        f".publish(label={json.dumps(signal_label)})\n"
        f"detect(when(signal {comparators[direction]} threshold({json.dumps(threshold)})))"
        f".publish({json.dumps(detect_label)})"
    )
    return {
        "api_version": "splunk-observability-native-ops/v1",
        "realm": realm,
        "detectors": [
            {
                "name": name,
                "description": f"Cisco Nexus {aggregation} detector for {metric}.",
                "program_text": program_text,
                "tags": ["cisco-nexus", aggregation],
                "rules": [
                    {
                        "detect_label": detect_label,
                        "severity": severity,
                        "description": (
                            f"{metric} is {direction_text[direction]} threshold {threshold}."
                        ),
                        "notifications": [],
                    }
                ],
            }
        ],
    }


def detector_specs(
    spec: dict[str, Any], realm: str, cluster_name: str
) -> dict[str, dict[str, Any]]:
    block = spec.get("detectors") or {}
    if not block.get("enabled", True):
        return {}
    thresholds = block.get("thresholds") or {}
    definitions = {
        "interface-status-down": {
            "name": "Cisco Nexus interface down",
            "metric": "system.network.interface.status",
            "direction": "at_or_below",
            "threshold": thresholds.get("interface_status_down_count_max", 0),
            "severity": "Critical",
            "aggregation": "min",
            "detect_label": "cisco_nexus_interface_down",
        },
        "packet-drops": {
            "name": "Cisco Nexus packet drop rate",
            "metric": "system.network.packet.dropped",
            "direction": "above",
            "threshold": thresholds.get("packet_drop_rate_per_min_max", 100),
            "severity": "Major",
            "aggregation": "rate",
            "detect_label": "cisco_nexus_packet_drops",
        },
        "cpu-pressure": {
            "name": "Cisco Nexus CPU pressure",
            "metric": "system.cpu.utilization",
            "direction": "above",
            "threshold": thresholds.get("cpu_utilization_pct_max", 85),
            "severity": "Warning",
            "aggregation": "mean",
            "detect_label": "cisco_nexus_cpu_pressure",
        },
        "memory-pressure": {
            "name": "Cisco Nexus memory pressure",
            "metric": "system.memory.utilization",
            "direction": "above",
            "threshold": thresholds.get("memory_utilization_pct_max", 85),
            "severity": "Warning",
            "aggregation": "mean",
            "detect_label": "cisco_nexus_memory_pressure",
        },
    }
    return {
        key: _detector_spec(realm=realm, cluster_name=cluster_name, **definition)
        for key, definition in definitions.items()
    }


def render_apply_overlay_script(spec: dict[str, Any]) -> str:
    collector = spec.get("collector") or {}
    release = collector.get("release", "splunk-otel-collector")
    namespace = collector.get("namespace", "splunk-otel")
    chart_ref = collector.get("chart_ref", "splunk-otel-collector-chart/splunk-otel-collector")
    return (
        f"""#!/usr/bin/env bash
set -euo pipefail

# Apply the Cisco Nexus overlay to an existing Splunk OTel Collector helm release
# by merging this overlay onto the existing values and running helm upgrade.
# Honors K8S_APPLY_DRY_RUN=true (helm --dry-run, no mutation).
#
# Required env: O11Y_TOKEN_FILE (path to the Org access token, chmod 600).
# Required tooling: helm, kubectl, yq.

if ! command -v helm >/dev/null 2>&1; then echo 'ERROR: helm required.' >&2; exit 1; fi
if ! command -v kubectl >/dev/null 2>&1; then echo 'ERROR: kubectl required.' >&2; exit 1; fi
if ! command -v yq >/dev/null 2>&1; then echo 'ERROR: yq required for overlay merge.' >&2; exit 1; fi

if [[ -z "${{O11Y_TOKEN_FILE:-}}" || ! -r "${{O11Y_TOKEN_FILE}}" ]]; then
    echo 'ERROR: O11Y_TOKEN_FILE must point to a readable token file (chmod 600).' >&2
    exit 1
fi

DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")/.." && pwd)"
OVERLAY="${{DIR}}/splunk-otel-overlay/values.overlay.yaml"

RELEASE="{release}"
NAMESPACE="{namespace}"
CHART_REF="{chart_ref}"

# Confirm the SSH Secret exists; we never auto-create it from the placeholder stub.
if ! kubectl -n "${{NAMESPACE}}" get secret cisco-nexus-ssh >/dev/null 2>&1; then
    echo "ERROR: Secret 'cisco-nexus-ssh' not found in namespace ${{NAMESPACE}}." >&2
    echo "       Create it from your real SSH credentials (see secrets/cisco-nexus-ssh-secret.yaml stub)." >&2
    exit 1
fi

# Pull current release values + merge overlay deterministically.
TMPDIR_LOCAL="$(mktemp -d)"
trap 'rm -rf "${{TMPDIR_LOCAL}}"' EXIT
helm get values "${{RELEASE}}" -n "${{NAMESPACE}}" -o yaml > "${{TMPDIR_LOCAL}}/current-values.yaml"
yq eval-all '. as $i ireduce ({{}}; . * $i)' "${{TMPDIR_LOCAL}}/current-values.yaml" "${{OVERLAY}}" > "${{TMPDIR_LOCAL}}/merged.yaml"

DRY_RUN_FLAG=()
if [[ "${{K8S_APPLY_DRY_RUN:-false}}" == "true" ]]; then
    DRY_RUN_FLAG=(--dry-run)
    echo "DRY-RUN MODE: passing --dry-run to helm"
fi

helm upgrade --install "${{RELEASE}}" "${{CHART_REF}}" \\
    --namespace "${{NAMESPACE}}" \\
    --values "${{TMPDIR_LOCAL}}/merged.yaml" \\
    --set-file "splunkObservability.accessToken=${{O11Y_TOKEN_FILE}}" \\
    --atomic \\
    --timeout 5m \\
    "${{DRY_RUN_FLAG[@]}}"

if [[ "${{K8S_APPLY_DRY_RUN:-false}}" != "true" ]]; then
    # Helm fullname collapses to the release name when it already contains the
    # chart name (the common "splunk-otel-collector" release), otherwise it is
    # "<release>-splunk-otel-collector-*". Try both forms.
    wait_for_rollout() {{
        local kind="$1"; shift
        local name
        for name in "$@"; do
            if kubectl -n "${{NAMESPACE}}" get "${{kind}}/${{name}}" >/dev/null 2>&1; then
                kubectl -n "${{NAMESPACE}}" rollout status "${{kind}}/${{name}}" --timeout=180s
                return
            fi
        done
        echo "ERROR: no expected ${{kind}} workload was found for release ${{RELEASE}}." >&2
        return 1
    }}
    wait_for_rollout daemonset \
        "${{RELEASE}}-agent" "${{RELEASE}}-splunk-otel-collector-agent"
    wait_for_rollout deployment \
        "${{RELEASE}}-k8s-cluster-receiver" \
        "${{RELEASE}}-splunk-otel-collector-k8s-cluster-receiver"
fi
"""
    )


def render_handoffs(
    spec: dict[str, Any], realm: str, cluster_name: str, distribution: str
) -> dict[str, str]:
    handoffs = spec.get("handoffs") or {}
    helpers: dict[str, str] = {}
    realm_q = shlex.quote(str(realm))
    cluster_name_q = shlex.quote(str(cluster_name))
    distribution_q = shlex.quote(str(distribution))
    if handoffs.get("base_collector", True):
        helpers["handoff-base-collector.sh"] = (
            f"""#!/usr/bin/env bash
set -euo pipefail

# Render the base Splunk OTel collector values, then merge our overlay.
if ! command -v yq >/dev/null 2>&1; then
    echo 'ERROR: yq required for overlay merge.' >&2
    exit 1
fi

BUNDLE_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")/.." && pwd)"
OVERLAY="$BUNDLE_DIR/splunk-otel-overlay/values.overlay.yaml"
BASE_OUTPUT_DIR="${{BASE_OUTPUT_DIR:-/tmp/splunk-observability-otel-rendered}}"
REALM={realm_q}
CLUSTER_NAME={cluster_name_q}
DISTRIBUTION={distribution_q}
printf -v BASE_OUTPUT_DIR_Q '%q' "$BASE_OUTPUT_DIR"
printf -v OVERLAY_Q '%q' "$OVERLAY"
printf -v REALM_Q '%q' "$REALM"
printf -v CLUSTER_NAME_Q '%q' "$CLUSTER_NAME"
printf -v DISTRIBUTION_Q '%q' "$DISTRIBUTION"

echo "Step 1: Render base collector values."
echo "    bash skills/splunk-observability-otel-collector-setup/scripts/setup.sh \\\\"
echo "      --render-k8s --realm ${{REALM_Q}} --cluster-name ${{CLUSTER_NAME_Q}} --distribution ${{DISTRIBUTION_Q}} \\\\"
echo "      --output-dir ${{BASE_OUTPUT_DIR_Q}}"
echo
echo "Step 2: Merge overlay."
echo "    yq eval-all '. as \\$item ireduce ({{}}; . * \\$item)' \\\\"
echo "      ${{BASE_OUTPUT_DIR_Q}}/k8s/values.yaml \\\\"
echo "      ${{OVERLAY_Q}} \\\\"
echo "      > /tmp/merged-values.yaml"
echo
echo "Step 3: Apply via helm."
echo "    helm upgrade --install splunk-otel-collector splunk-otel-collector-chart/splunk-otel-collector \\\\"
echo "      -n splunk-otel --create-namespace --reuse-values \\\\"
echo "      -f /tmp/merged-values.yaml \\\\"
echo '      --set-file splunkObservability.accessToken="$O11Y_TOKEN_FILE"'
"""
        )
    if handoffs.get("dashboard_builder", True):
        helpers["handoff-dashboards.sh"] = (
            f"""#!/usr/bin/env bash
set -euo pipefail

DASHBOARDS_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")/.." && pwd)/dashboards"
REALM={realm_q}
printf -v DASHBOARDS_DIR_Q '%q' "$DASHBOARDS_DIR"
printf -v REALM_Q '%q' "$REALM"
echo "Import dashboards via splunk-observability-dashboard-builder:"
echo "    for spec in ${{DASHBOARDS_DIR_Q}}/*.signalflow.yaml; do"
echo "      bash skills/splunk-observability-dashboard-builder/scripts/setup.sh \\\\"
echo "        --render --apply --realm ${{REALM_Q}} \\\\"
echo "        --spec \\\"\\$spec\\\" \\\\"
echo "        --token-file \\\"\\$O11Y_API_TOKEN_FILE\\\""
echo "    done"
"""
        )
    if handoffs.get("native_ops", True):
        helpers["handoff-detectors.sh"] = (
            f"""#!/usr/bin/env bash
set -euo pipefail

DETECTORS_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")/.." && pwd)/detectors"
REALM={realm_q}
printf -v DETECTORS_DIR_Q '%q' "$DETECTORS_DIR"
printf -v REALM_Q '%q' "$REALM"
echo "Apply detectors via splunk-observability-native-ops:"
echo "    for spec in ${{DETECTORS_DIR_Q}}/*.yaml; do"
echo "      bash skills/splunk-observability-native-ops/scripts/setup.sh \\\\"
echo "        --render --apply --realm ${{REALM_Q}} \\\\"
echo "        --spec \\\"\\$spec\\\" \\\\"
echo "        --token-file \\\"\\$O11Y_API_TOKEN_FILE\\\""
echo "    done"
"""
        )
    return helpers


def warnings(devices: list[dict[str, Any]]) -> list[str]:
    items: list[str] = []
    if len(devices) > 50:
        items.append(
            f"{len(devices)} Nexus devices configured. Increase clusterReceiver memory_limiter "
            "and consider raising collection_interval to reduce per-device CPU load on the switches."
        )
    return items


def render_metadata(spec: dict[str, Any], realm: str, cluster_name: str, devices: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "skill": SKILL_NAME,
        "realm": realm,
        "cluster_name": cluster_name,
        "device_count": len(devices),
        "warnings": warnings(devices),
    }


def main() -> int:
    args = parse_args()
    spec_path = Path(args.spec)
    if not spec_path.is_file():
        print(f"ERROR: spec not found: {spec_path}", file=__import__("sys").stderr)
        return 1
    try:
        spec = load_spec(spec_path)
        cli_devices = parse_cli_devices(args.nexus_device)
        devices = merged_devices(spec, cli_devices)
        if not devices:
            raise SpecError("No devices specified. Provide spec.devices[] or --nexus-device.")
    except SpecError as exc:
        print(f"ERROR: {exc}", file=__import__("sys").stderr)
        return 1

    realm = args.realm or spec.get("realm", "us0")
    cluster_name = args.cluster_name or spec.get("cluster_name", "lab-cluster")
    distribution = args.distribution or spec.get("distribution", "kubernetes")
    ssh_secret = spec.get("ssh_secret") or {}

    plan = {
        "skill": SKILL_NAME,
        "output_dir": str(Path(args.output_dir).resolve()),
        "realm": realm,
        "cluster_name": cluster_name,
        "distribution": distribution,
        "device_count": len(devices),
        "warnings": warnings(devices),
    }

    if args.dry_run:
        if args.json:
            print(json.dumps(plan, indent=2, sort_keys=True))
        else:
            print("Cisco Nexus Integration render plan")
            for key, value in plan.items():
                print(f"  {key}: {value}")
        return 0

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    receiver = cisco_os_receiver(spec, devices, ssh_secret)
    overlay = overlay_values(spec, receiver, ssh_secret, cluster_name, distribution)
    write_yaml(out / "splunk-otel-overlay/values.overlay.yaml", overlay)
    write_text(out / "secrets/cisco-nexus-ssh-secret.yaml", secret_manifest_stub(ssh_secret))

    for name, payload in dashboard_specs(spec, realm, cluster_name).items():
        write_yaml(out / f"dashboards/{name}.signalflow.yaml", payload)
    for name, payload in detector_specs(spec, realm, cluster_name).items():
        write_yaml(out / f"detectors/{name}.yaml", payload)

    for name, body in render_handoffs(spec, realm, cluster_name, distribution).items():
        write_text(out / f"scripts/{name}", body, executable=True)

    write_text(
        out / "scripts/apply-nexus-overlay.sh",
        render_apply_overlay_script(spec),
        executable=True,
    )

    write_json(out / "metadata.json", render_metadata(spec, realm, cluster_name, devices))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

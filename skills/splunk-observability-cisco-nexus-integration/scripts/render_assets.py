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


def dashboard_specs(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if not (spec.get("dashboards") or {}).get("enabled", True):
        return {}
    return {
        "cisco-nexus-overview": {
            "name": "Cisco Nexus Overview",
            "description": "Nexus device + interface health overview",
            "charts": [
                _chart("Device up", "cisco.device.up"),
                _chart("CPU utilization", "system.cpu.utilization"),
                _chart("Memory utilization", "system.memory.utilization"),
                _chart("Interface status", "system.network.interface.status"),
                _chart("Network throughput", "system.network.io"),
                _chart("Network errors", "system.network.errors"),
                _chart("Packet drops", "system.network.packet.dropped"),
            ],
            "filters": [{"property": "k8s.cluster.name", "value": "${CLUSTER_NAME}"}],
        }
    }


def _chart(name: str, metric: str) -> dict[str, Any]:
    return {
        "name": name,
        "description": f"{metric} from cisco_os receiver",
        "program_text": f"data('{metric}', filter=filter('k8s.cluster.name', '${{CLUSTER_NAME}}')).publish(label='{metric}')",
        "publish_label": metric,
    }


def detector_specs(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    block = spec.get("detectors") or {}
    if not block.get("enabled", True):
        return {}
    thresholds = block.get("thresholds") or {}
    detectors = {
        "interface-status-down": {
            "test_type": "cisco-nexus",
            "detectors": [
                {
                    "name": "Cisco Nexus interface down",
                    "metric": "system.network.interface.status",
                    "direction": "below",
                    "threshold": thresholds.get("interface_status_down_count_max", 0),
                    "severity": "Critical",
                    "aggregation": "min",
                }
            ],
        },
        "packet-drops": {
            "test_type": "cisco-nexus",
            "detectors": [
                {
                    "name": "Cisco Nexus packet drop rate",
                    "metric": "system.network.packet.dropped",
                    "direction": "above",
                    "threshold": thresholds.get("packet_drop_rate_per_min_max", 100),
                    "severity": "Major",
                    "aggregation": "rate",
                }
            ],
        },
        "cpu-pressure": {
            "test_type": "cisco-nexus",
            "detectors": [
                {
                    "name": "Cisco Nexus CPU pressure",
                    "metric": "system.cpu.utilization",
                    "direction": "above",
                    "threshold": thresholds.get("cpu_utilization_pct_max", 85),
                    "severity": "Warning",
                    "aggregation": "mean",
                }
            ],
        },
        "memory-pressure": {
            "test_type": "cisco-nexus",
            "detectors": [
                {
                    "name": "Cisco Nexus memory pressure",
                    "metric": "system.memory.utilization",
                    "direction": "above",
                    "threshold": thresholds.get("memory_utilization_pct_max", 85),
                    "severity": "Warning",
                    "aggregation": "mean",
                }
            ],
        },
    }
    return detectors


def render_handoffs(spec: dict[str, Any], realm: str, cluster_name: str, distribution: str) -> dict[str, str]:
    handoffs = spec.get("handoffs") or {}
    helpers: dict[str, str] = {}
    if handoffs.get("base_collector", True):
        helpers["handoff-base-collector.sh"] = (
            f"""#!/usr/bin/env bash
set -euo pipefail

# Render the base Splunk OTel collector values, then merge our overlay.
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
echo "        --render --apply --realm {realm} \\\\"
echo "        --spec \\$spec \\\\"
echo "        --token-file \\$O11Y_API_TOKEN_FILE"
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
echo "      --render --apply --realm {realm} \\\\"
echo "      --spec ${{DETECTORS_DIR}}/<detector>.yaml \\\\"
echo "      --token-file \\$O11Y_API_TOKEN_FILE"
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

    for name, payload in dashboard_specs(spec).items():
        write_yaml(out / f"dashboards/{name}.signalflow.yaml", payload)
    for name, payload in detector_specs(spec).items():
        write_yaml(out / f"detectors/{name}.yaml", payload)

    for name, body in render_handoffs(spec, realm, cluster_name, distribution).items():
        write_text(out / f"scripts/{name}", body, executable=True)

    write_json(out / "metadata.json", render_metadata(spec, realm, cluster_name, devices))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

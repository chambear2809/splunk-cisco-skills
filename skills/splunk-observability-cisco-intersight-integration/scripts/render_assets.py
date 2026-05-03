"""Render the Cisco Intersight -> Splunk Observability Cloud manifests + helpers.

Outputs:
  - intersight-integration/intersight-otel-namespace.yaml
  - intersight-integration/intersight-credentials-secret.yaml      (manifest stub)
  - intersight-integration/intersight-otel-deployment.yaml         (Deployment + ConfigMap)
  - intersight-integration/intersight-otel-config.yaml             (intersight-otel.toml ConfigMap)
  - splunk-otel-overlay/intersight-pipeline.yaml                   (collector overlay)
  - dashboards/intersight-overview.signalflow.yaml
  - detectors/<name>.yaml
  - scripts/apply-intersight-manifests.sh
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


SKILL_NAME = "splunk-observability-cisco-intersight-integration"


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
    parser.add_argument("--collector-release", default="")
    parser.add_argument("--collector-namespace", default="")
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


def namespace_manifest(ns: str) -> dict[str, Any]:
    return {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": ns}}


def secret_stub(intersight_otel: dict[str, Any]) -> str:
    name = intersight_otel.get("secret_name", "intersight-api-credentials")
    namespace = intersight_otel.get("namespace", "intersight-otel")
    key_id_key = intersight_otel.get("key_id_secret_key", "intersight-key-id")
    key_pem_key = intersight_otel.get("key_pem_secret_key", "intersight-key")
    return (
        "# Intersight API credentials (DO NOT apply this manifest with placeholder values).\n"
        f"# Create the actual Secret out-of-band:\n"
        f"#   kubectl create namespace {namespace}\n"
        f"#   kubectl create secret generic {name} -n {namespace} \\\n"
        f"#     --from-file={key_id_key}=/tmp/intersight_key_id \\\n"
        f"#     --from-file={key_pem_key}=/tmp/intersight_private_key.pem\n"
        "#\n"
        "apiVersion: v1\n"
        "kind: Secret\n"
        "metadata:\n"
        f"  name: {name}\n"
        f"  namespace: {namespace}\n"
        "type: Opaque\n"
        "stringData:\n"
        f"  {key_id_key}: PLACEHOLDER_INTERSIGHT_KEY_ID\n"
        f"  {key_pem_key}: |\n"
        "    -----BEGIN PRIVATE KEY-----\n"
        "    PLACEHOLDER_PRIVATE_KEY_PEM_CONTENT\n"
        "    -----END PRIVATE KEY-----\n"
    )


def configmap_manifest(intersight_otel: dict[str, Any], collector: dict[str, Any]) -> dict[str, Any]:
    ns = intersight_otel.get("namespace", "intersight-otel")
    release = collector.get("release", "splunk-otel-collector")
    collector_ns = collector.get("namespace", "splunk-otel")
    otlp_port = int(collector.get("otlp_port", 4317))
    interval = int((intersight_otel.get("collection_interval") or {}).get("seconds", 60)) if isinstance(intersight_otel.get("collection_interval"), dict) else 60
    # The collector endpoint follows the Splunk OTel chart's standard service
    # naming: <release>-splunk-otel-collector-agent.<ns>.svc.cluster.local:<port>
    endpoint = f"http://{release}-splunk-otel-collector-agent.{collector_ns}.svc.cluster.local:{otlp_port}"
    toml_content = (
        "# intersight-otel.toml\n"
        "# Generated by splunk-observability-cisco-intersight-integration.\n"
        "\n"
        f'otel_collector_endpoint = "{endpoint}"\n'
        f"collection_interval_seconds = {interval}\n"
    )
    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": "intersight-otel-config", "namespace": ns},
        "data": {"intersight-otel.toml": toml_content},
    }


def deployment_manifest(intersight_otel: dict[str, Any], collector: dict[str, Any], cluster_name: str) -> dict[str, Any]:
    ns = intersight_otel.get("namespace", "intersight-otel")
    secret_name = intersight_otel.get("secret_name", "intersight-api-credentials")
    image = intersight_otel.get("image", "ghcr.io/intersight/intersight-otel:latest")
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": "intersight-otel", "namespace": ns, "labels": {"app": "intersight-otel"}},
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": {"app": "intersight-otel"}},
            "template": {
                "metadata": {"labels": {"app": "intersight-otel"}},
                "spec": {
                    "containers": [
                        {
                            "name": "intersight-otel",
                            "image": image,
                            "env": [
                                {"name": "K8S_CLUSTER_NAME", "value": cluster_name},
                                {
                                    "name": "INTERSIGHT_KEY_ID",
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": secret_name,
                                            "key": intersight_otel.get("key_id_secret_key", "intersight-key-id"),
                                        }
                                    },
                                },
                            ],
                            "volumeMounts": [
                                {"name": "intersight-key", "mountPath": "/etc/intersight", "readOnly": True},
                                {"name": "config", "mountPath": "/etc/intersight-otel", "readOnly": True},
                            ],
                            "resources": {
                                "limits": {"cpu": "200m", "memory": "256Mi"},
                                "requests": {"cpu": "100m", "memory": "128Mi"},
                            },
                        }
                    ],
                    "volumes": [
                        {
                            "name": "intersight-key",
                            "secret": {
                                "secretName": secret_name,
                                "items": [
                                    {
                                        "key": intersight_otel.get("key_pem_secret_key", "intersight-key"),
                                        "path": "intersight.pem",
                                    }
                                ],
                                "defaultMode": 0o400,
                            },
                        },
                        {
                            "name": "config",
                            "configMap": {"name": "intersight-otel-config"},
                        },
                    ],
                },
            },
        },
    }


def overlay_pipeline(collector: dict[str, Any]) -> dict[str, Any]:
    """Optional collector overlay snippet that adds Intersight to the metrics pipeline.

    The base collector chart already enables OTLP receivers by default, so this
    overlay just confirms the metrics pipeline includes `otlp` (which it does
    out of the box). We render it as a no-op overlay to make the contract
    explicit and to give the AI Pod umbrella something to merge.
    """
    return {
        "agent": {
            "config": {
                "service": {
                    "pipelines": {
                        "metrics": {
                            "receivers": ["otlp"],
                        }
                    }
                }
            }
        }
    }


def dashboard_specs(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if not (spec.get("dashboards") or {}).get("enabled", True):
        return {}
    return {
        "intersight-overview": {
            "name": "Cisco Intersight Overview",
            "description": "UCS power, thermal, fan, network, alarms, advisories",
            "charts": [
                _chart("Host power", "intersight.ucs.host.power"),
                _chart("Host temperature", "intersight.ucs.host.temperature"),
                _chart("Fan speed", "intersight.ucs.fan.speed"),
                _chart("Network receive rate", "intersight.ucs.network.receive.rate"),
                _chart("Network transmit rate", "intersight.ucs.network.transmit.rate"),
                _chart("Network utilization (avg)", "intersight.ucs.network.utilization.average"),
                _chart("Active alarms", "intersight.alarms.count"),
                _chart("Security advisories", "intersight.advisories.security.count"),
                _chart("Non-security advisories (affected objects)", "intersight.advisories.nonsecurity.affected_objects"),
                _chart("VM inventory count", "intersight.vm_count"),
            ],
            "filters": [{"property": "k8s.cluster.name", "value": "${CLUSTER_NAME}"}],
        }
    }


def _chart(name: str, metric: str) -> dict[str, Any]:
    return {
        "name": name,
        "description": f"{metric} from Intersight OTel",
        "program_text": f"data('{metric}', filter=filter('k8s.cluster.name', '${{CLUSTER_NAME}}')).publish(label='{metric}')",
        "publish_label": metric,
    }


def detector_specs(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    block = spec.get("detectors") or {}
    if not block.get("enabled", True):
        return {}
    thresholds = block.get("thresholds") or {}
    return {
        "alarm-count-spike": {
            "test_type": "intersight",
            "detectors": [
                {
                    "name": "Intersight alarm count spike",
                    "metric": "intersight.alarms.count",
                    "direction": "above",
                    "threshold": thresholds.get("alarm_count_delta_per_5m_max", 5),
                    "severity": "Critical",
                    "aggregation": "delta",
                }
            ],
        },
        "security-advisory-delta": {
            "test_type": "intersight",
            "detectors": [
                {
                    "name": "Intersight new security advisory",
                    "metric": "intersight.advisories.security.count",
                    "direction": "above",
                    "threshold": thresholds.get("security_advisory_delta_per_24h_max", 0),
                    "severity": "Major",
                    "aggregation": "delta",
                }
            ],
        },
        "host-temp-ceiling": {
            "test_type": "intersight",
            "detectors": [
                {
                    "name": "Intersight host temperature ceiling",
                    "metric": "intersight.ucs.host.temperature",
                    "direction": "above",
                    "threshold": thresholds.get("host_temp_ceiling_celsius", 80),
                    "severity": "Major",
                    "aggregation": "max",
                }
            ],
        },
        "host-power-floor": {
            "test_type": "intersight",
            "detectors": [
                {
                    "name": "Intersight host power floor (unexpected power loss)",
                    "metric": "intersight.ucs.host.power",
                    "direction": "below",
                    "threshold": thresholds.get("host_power_floor_watts", 50),
                    "severity": "Warning",
                    "aggregation": "min",
                }
            ],
        },
        "fan-speed-floor": {
            "test_type": "intersight",
            "detectors": [
                {
                    "name": "Intersight fan speed floor (failure indicator)",
                    "metric": "intersight.ucs.fan.speed",
                    "direction": "below",
                    "threshold": thresholds.get("fan_speed_floor_rpm", 1000),
                    "severity": "Warning",
                    "aggregation": "min",
                }
            ],
        },
    }


def render_apply_manifests_script(intersight_otel: dict[str, Any]) -> str:
    ns = intersight_otel.get("namespace", "intersight-otel")
    return (
        f"""#!/usr/bin/env bash
set -euo pipefail

# Apply the Intersight OTel namespace, ConfigMap, and Deployment.
# The Secret must be created out-of-band (this script does NOT create it).

if ! command -v kubectl >/dev/null 2>&1; then
    echo 'ERROR: kubectl required.' >&2
    exit 1
fi

DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")/.." && pwd)/intersight-integration"

echo "Applying Namespace..."
kubectl apply -f "${{DIR}}/intersight-otel-namespace.yaml"

echo "Confirming Intersight credentials Secret exists in {ns}..."
if ! kubectl get secret intersight-api-credentials -n {ns} >/dev/null 2>&1; then
    echo "ERROR: Secret 'intersight-api-credentials' not found in namespace {ns}." >&2
    echo "       Create it with:" >&2
    echo "         kubectl create secret generic intersight-api-credentials -n {ns} \\\\" >&2
    echo "           --from-file=intersight-key-id=/tmp/intersight_key_id \\\\" >&2
    echo "           --from-file=intersight-key=/tmp/intersight_private_key.pem" >&2
    exit 1
fi

echo "Applying ConfigMap..."
kubectl apply -f "${{DIR}}/intersight-otel-config.yaml"

echo "Applying Deployment..."
kubectl apply -f "${{DIR}}/intersight-otel-deployment.yaml"

echo "Waiting for rollout..."
kubectl -n {ns} rollout status deployment/intersight-otel --timeout=180s
"""
    )


def render_handoffs(spec: dict[str, Any], realm: str, cluster_name: str, distribution: str) -> dict[str, str]:
    handoffs = spec.get("handoffs") or {}
    helpers: dict[str, str] = {}
    if handoffs.get("base_collector", True):
        helpers["handoff-base-collector.sh"] = (
            f"""#!/usr/bin/env bash
set -euo pipefail

OVERLAY="$(cd "$(dirname "${{BASH_SOURCE[0]}}")/.." && pwd)/splunk-otel-overlay/intersight-pipeline.yaml"
BASE_OUTPUT_DIR="${{BASE_OUTPUT_DIR:-/tmp/splunk-observability-otel-rendered}}"

echo "Step 1: Render base collector values."
echo "    bash skills/splunk-observability-otel-collector-setup/scripts/setup.sh \\\\"
echo "      --render-k8s --realm {realm} --cluster-name {cluster_name} --distribution {distribution} \\\\"
echo "      --output-dir ${{BASE_OUTPUT_DIR}}"
echo
echo "Step 2: Confirm OTLP receiver enabled (it is by default in the chart)."
echo "    grep -A 3 'receivers:' ${{BASE_OUTPUT_DIR}}/k8s/values.yaml | head"
echo
echo "Step 3 (optional): Merge intersight pipeline overlay if you customized the collector pipeline."
echo "    yq eval-all '. as \\$item ireduce ({{}}; . * \\$item)' \\\\"
echo "      ${{BASE_OUTPUT_DIR}}/k8s/values.yaml \\\\"
echo "      ${{OVERLAY}} > /tmp/merged-values.yaml"
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


def render_metadata(spec: dict[str, Any], realm: str, cluster_name: str) -> dict[str, Any]:
    intersight_otel = spec.get("intersight_otel") or {}
    return {
        "skill": SKILL_NAME,
        "realm": realm,
        "cluster_name": cluster_name,
        "intersight_namespace": intersight_otel.get("namespace", "intersight-otel"),
        "secret_name": intersight_otel.get("secret_name", "intersight-api-credentials"),
        "warnings": [],
    }


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
    intersight_otel = spec.get("intersight_otel") or {}
    collector = dict(spec.get("collector") or {})
    if args.collector_release:
        collector["release"] = args.collector_release
    if args.collector_namespace:
        collector["namespace"] = args.collector_namespace

    plan = {
        "skill": SKILL_NAME,
        "output_dir": str(Path(args.output_dir).resolve()),
        "realm": realm,
        "cluster_name": cluster_name,
        "distribution": distribution,
        "intersight_namespace": intersight_otel.get("namespace", "intersight-otel"),
        "warnings": [],
    }

    if args.dry_run:
        if args.json:
            print(json.dumps(plan, indent=2, sort_keys=True))
        else:
            print("Cisco Intersight Integration render plan")
            for key, value in plan.items():
                print(f"  {key}: {value}")
        return 0

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    write_yaml(
        out / "intersight-integration/intersight-otel-namespace.yaml",
        namespace_manifest(intersight_otel.get("namespace", "intersight-otel")),
    )
    write_text(
        out / "intersight-integration/intersight-credentials-secret.yaml",
        secret_stub(intersight_otel),
    )
    write_yaml(
        out / "intersight-integration/intersight-otel-config.yaml",
        configmap_manifest(intersight_otel, collector),
    )
    write_yaml(
        out / "intersight-integration/intersight-otel-deployment.yaml",
        deployment_manifest(intersight_otel, collector, cluster_name),
    )
    write_yaml(out / "splunk-otel-overlay/intersight-pipeline.yaml", overlay_pipeline(collector))

    for name, payload in dashboard_specs(spec).items():
        write_yaml(out / f"dashboards/{name}.signalflow.yaml", payload)
    for name, payload in detector_specs(spec).items():
        write_yaml(out / f"detectors/{name}.yaml", payload)

    write_text(
        out / "scripts/apply-intersight-manifests.sh",
        render_apply_manifests_script(intersight_otel),
        executable=True,
    )
    for name, body in render_handoffs(spec, realm, cluster_name, distribution).items():
        write_text(out / f"scripts/{name}", body, executable=True)

    write_json(out / "metadata.json", render_metadata(spec, realm, cluster_name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

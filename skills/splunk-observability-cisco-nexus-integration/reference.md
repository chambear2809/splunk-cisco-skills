# Splunk Observability Cisco Nexus Integration Reference

## Source guidance

- cisco_os receiver: `github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/receiver/ciscoosreceiver`. Multi-device + global-scrapers format added in PR #45562 (merged Feb 2026), available v0.149.0+.
- Splunk Observability Cloud OTel chart: `splunk-otel-collector-chart/splunk-otel-collector` (the same chart used by `splunk-observability-otel-collector-setup`).

## Rendered layout

By default, assets are written under `splunk-observability-cisco-nexus-rendered/`:

- `splunk-otel-overlay/values.overlay.yaml` — clusterReceiver overlay with cisco_os receiver, extraEnvs for the SSH credentials, and the metrics/cisco-os-metrics pipeline.
- `secrets/cisco-nexus-ssh-secret.yaml` — K8s Secret manifest stub (placeholders only).
- `dashboards/cisco-nexus-overview.signalflow.yaml` — starter dashboard.
- `detectors/<name>.yaml` — interface down, packet drops, CPU pressure, memory pressure.
- `scripts/handoff-base-collector.sh`, `handoff-dashboards.sh`, `handoff-detectors.sh`.
- `metadata.json`.

## Setup modes

- `--render` (default), `--validate`, `--dry-run`, `--json`, `--explain`.
- Device list comes from `spec.devices[]` or `--nexus-device name:host[:port]` (repeatable).

## SSH credentials

The renderer never reads the SSH password or key. The collector reads credentials from a K8s Secret you create out-of-band:

```bash
# Password auth:
kubectl create secret generic cisco-nexus-ssh \
  --from-literal=username=splunk-otel \
  --from-file=password=/tmp/nexus_password \
  -n splunk-otel

# Key auth:
kubectl create secret generic cisco-nexus-ssh \
  --from-literal=username=splunk-otel \
  --from-file=key=/path/to/ssh/key \
  -n splunk-otel
```

For key auth, set `spec.ssh_secret.key_file_key: key` (and clear `password_key`). The overlay then mounts the Secret as a volume at `/etc/cisco-nexus-ssh/key` instead of using a password env var.

## Why clusterReceiver

cisco_os runs in the **clusterReceiver** (one-instance Deployment) so each Nexus device is scraped exactly once per collection_interval, regardless of cluster node count. Putting it in the agent (DaemonSet) would multiply the scrape load by the number of nodes — bad for the switches.

## Hand-offs

- Splunk OTel Collector base install: [splunk-observability-otel-collector-setup](../splunk-observability-otel-collector-setup/SKILL.md).
- Dashboards: [splunk-observability-dashboard-builder](../splunk-observability-dashboard-builder/SKILL.md).
- Detectors: [splunk-observability-native-ops](../splunk-observability-native-ops/SKILL.md).

## Companion skill

[cisco-dc-networking-setup](../cisco-dc-networking-setup/SKILL.md) handles the Splunk Platform TA path for Nexus / ACI / Nexus Dashboard. Different layer (Splunk Platform side); coordinate the two skills when you want both Nexus metrics in O11y and Nexus events/syslog in Splunk Platform.

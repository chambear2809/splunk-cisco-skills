# Splunk Observability Cisco Intersight Integration Reference

## Source guidance

- Cisco AI Pod Configuration Guide for Splunk Observability (May 2026 PDF) — Intersight integration steps, page 2.
- Splunk Observability Cloud signalfx exporter and OTLP receiver: standard Splunk OTel chart components.
- Splunk Workshop AI Pod scenario: `splunk.github.io/observability-workshop/en/ninja-workshops/14-cisco-ai-pods/`.

## Rendered layout

By default, assets are written under `splunk-observability-cisco-intersight-rendered/`:

- `intersight-integration/intersight-otel-namespace.yaml` — Namespace.
- `intersight-integration/intersight-credentials-secret.yaml` — Secret manifest stub (placeholders only).
- `intersight-integration/intersight-otel-config.yaml` — ConfigMap with `intersight-otel.toml`.
- `intersight-integration/intersight-otel-deployment.yaml` — Deployment that mounts the Secret + ConfigMap.
- `splunk-otel-overlay/intersight-pipeline.yaml` — overlay snippet confirming OTLP receiver is in the metrics pipeline.
- `dashboards/intersight-overview.signalflow.yaml` — UCS power/thermal/fan/network/alarms dashboard.
- `detectors/<name>.yaml` — alarm spike, security advisory delta, host temp, host power floor, fan speed floor.
- `scripts/apply-intersight-manifests.sh` — applies Namespace + ConfigMap + Deployment (refuses if Secret is missing).
- `scripts/handoff-base-collector.sh`, `handoff-dashboards.sh`, `handoff-detectors.sh`.
- `metadata.json`.

## Setup modes

- `--render` (default), `--validate`, `--dry-run`, `--json`, `--explain`.

## Intersight credentials

The renderer never reads the key ID or private key. Create the K8s Secret out-of-band:

```bash
kubectl create namespace intersight-otel
kubectl create secret generic intersight-api-credentials -n intersight-otel \
  --from-file=intersight-key-id=/tmp/intersight_key_id \
  --from-file=intersight-key=/tmp/intersight_private_key.pem
```

The Deployment mounts the Secret at `/etc/intersight/intersight.pem` (private key) and reads the key ID via env var.

## Required Intersight permissions

The Intersight API key must have:

- Account Administrator OR Server Administrator role.
- Read access to all the metric namespaces the integration scrapes (host, fan, network, alarms, advisories).

For least privilege, create a dedicated read-only API key tied to a service-account user.

## OTLP endpoint coordination

The ConfigMap's `otel_collector_endpoint` defaults to:

```
http://<release>-splunk-otel-collector-agent.<ns>.svc.cluster.local:4317
```

Where `<release>` and `<ns>` come from `spec.collector.release` and `spec.collector.namespace`. Override with `--collector-release` / `--collector-namespace` to match your actual Splunk OTel chart deployment.

## Hand-offs

- Splunk OTel Collector base install: [splunk-observability-otel-collector-setup](../splunk-observability-otel-collector-setup/SKILL.md).
- Dashboards: [splunk-observability-dashboard-builder](../splunk-observability-dashboard-builder/SKILL.md).
- Detectors: [splunk-observability-native-ops](../splunk-observability-native-ops/SKILL.md).

## Companion skill

[cisco-intersight-setup](../cisco-intersight-setup/SKILL.md) handles the Splunk Platform TA path (`Splunk_TA_Cisco_Intersight`). Different layer; coordinate when you want both Intersight metrics in O11y and Intersight events in Splunk Platform.

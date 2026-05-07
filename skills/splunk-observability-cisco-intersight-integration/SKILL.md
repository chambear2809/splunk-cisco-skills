---
name: splunk-observability-cisco-intersight-integration
description: >-
  Standalone reusable skill for sending Cisco Intersight (UCS management
  plane) metrics to Splunk Observability Cloud via the Intersight OTel
  integration. Renders a separate intersight-otel namespace + K8s Secret
  manifest stub for intersight-key-id/intersight-key + Deployment manifest
  pointing at the Splunk OTel collector agent's OTLP gRPC endpoint
  (port 4317) + ConfigMap for the intersight-otel.toml endpoint override.
  Renders signalfx-pipeline metric series for intersight.* (alarms,
  advisories, UCS host power/temp/fan, network, vm count). Hands off base
  collector to splunk-observability-otel-collector-setup, dashboards to
  splunk-observability-dashboard-builder, detectors to
  splunk-observability-native-ops. Independent of Cisco AI Pod -- useful
  for any UCS deployment. Companion to cisco-intersight-setup (Splunk
  Platform TA Splunk_TA_Cisco_Intersight). Use when the user asks to send
  Cisco Intersight, UCS, HyperFlex, or UCS-X compute infrastructure metrics
  to Splunk Observability Cloud, configure the cisco_intersight OTel receiver,
  or render dashboards/detectors for UCS chassis health.
---

# Splunk Observability Cisco Intersight Integration

This is a **standalone reusable skill** for Cisco Intersight (UCS management plane) metrics in Splunk Observability Cloud. It is **independent of the AI Pod** umbrella — useful for any UCS deployment. The AI Pod skill composes this skill via subprocess + yq deep-merge.

The Splunk Platform TA path (`Splunk_TA_Cisco_Intersight`) lives in [cisco-intersight-setup](../cisco-intersight-setup/SKILL.md). That's a different layer (Splunk Platform side); this skill is the O11y side.

## What it renders

- `intersight-integration/intersight-otel-deployment.yaml` — Deployment in a separate `intersight-otel` namespace, points at `http://<release>-splunk-otel-collector-agent.<ns>.svc.cluster.local:4317` (configurable).
- `intersight-integration/intersight-credentials-secret.yaml` — K8s Secret manifest stub for `intersight-key-id` and `intersight-key` (placeholders only; renderer never reads the key files).
- `intersight-integration/intersight-otel-config.yaml` — ConfigMap for `intersight-otel.toml` (lets the user override the OTLP collector endpoint when their collector ns/release differs).
- `intersight-integration/intersight-otel-namespace.yaml` — Namespace manifest.
- `splunk-otel-overlay/intersight-pipeline.yaml` — pipeline addition that admits Intersight OTLP traffic on the agent.
- `dashboards/intersight-overview.signalflow.yaml` — UCS power/thermal, fan speed, network throughput, alarms, advisories, VM inventory.
- `detectors/<name>.yaml` — alarm count delta, security advisory delta, host temp ceiling, host power floor.
- `scripts/setup.sh`, `render_assets.py`, `validate.sh`, `handoff-base-collector.sh`, `handoff-dashboards.sh`, `handoff-detectors.sh`, `apply-intersight-manifests.sh`.
- `metadata.json`.

## Safety Rules

- Never ask for the Intersight API key ID or private key in conversation.
- Use `--intersight-key-id-file` (chmod 600 enforced) for the key ID and `--intersight-key-file` (chmod 600 enforced) for the private key. The renderer never reads either file; the K8s Secret is created out-of-band.
- Reject `--intersight-key-id`, `--intersight-key`, `--api-key`, `--client-secret`.
- O11y token via `--o11y-token-file` (passed through to base collector). Reject `--o11y-token`, `--access-token`, `--token`, `--bearer-token`, `--api-token`, `--sf-token`.

## Primary Workflow

1. Generate or locate your Intersight API key (Account Settings -> API Keys in the Intersight UI). Save the key ID and private key to chmod-600 files.

2. Render:

   ```bash
   bash skills/splunk-observability-cisco-intersight-integration/scripts/setup.sh \
     --render --validate \
     --realm us0 \
     --cluster-name lab-cluster \
     --collector-release splunk-otel-collector \
     --collector-namespace splunk-otel \
     --output-dir splunk-observability-cisco-intersight-rendered
   ```

3. Create the Intersight credentials Secret out-of-band:

   ```bash
   kubectl create namespace intersight-otel
   kubectl create secret generic intersight-api-credentials -n intersight-otel \
     --from-file=intersight-key-id=/tmp/intersight_key_id \
     --from-file=intersight-key=/tmp/intersight_private_key.pem
   ```

4. Apply the manifests + handoffs:

   ```bash
   bash splunk-observability-cisco-intersight-rendered/scripts/apply-intersight-manifests.sh
   bash splunk-observability-cisco-intersight-rendered/scripts/handoff-base-collector.sh
   bash splunk-observability-cisco-intersight-rendered/scripts/handoff-dashboards.sh
   bash splunk-observability-cisco-intersight-rendered/scripts/handoff-detectors.sh
   ```

## Hand-offs

- Splunk OTel Collector base install: [splunk-observability-otel-collector-setup](../splunk-observability-otel-collector-setup/SKILL.md).
- Dashboards: [splunk-observability-dashboard-builder](../splunk-observability-dashboard-builder/SKILL.md).
- Detectors: [splunk-observability-native-ops](../splunk-observability-native-ops/SKILL.md).

## Out of scope (companion skill)

- Splunk Platform TA path (`Splunk_TA_Cisco_Intersight`): [cisco-intersight-setup](../cisco-intersight-setup/SKILL.md).

## Validation

```bash
bash skills/splunk-observability-cisco-intersight-integration/scripts/validate.sh
```

Static checks: manifest validity, no inline credentials, OTLP endpoint shape. With `--live`: prefers `oc` and falls back to `kubectl`, probes the `intersight-otel` namespace, checks the live OTLP target service/config, and fails if the pod logs show OTLP metrics export errors such as `unknown service opentelemetry.proto.collector.metrics.v1.MetricsService`.

See `reference.md` and `references/intersight-deployment.md`, `intersight-secrets.md`, `dashboards-catalog.md`, `troubleshooting.md` for details.

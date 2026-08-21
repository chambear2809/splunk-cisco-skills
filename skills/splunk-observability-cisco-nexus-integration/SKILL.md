---
name: splunk-observability-cisco-nexus-integration
description: "Use when the user asks to send Cisco Nexus, NX-OS, IOS-XE, or IOS-XR device metrics to Splunk
  Observability Cloud, configure the cisco_os receiver, set up multi-device Nexus telemetry, or render
  dashboards/detectors for Cisco data center fabric. Standalone reusable skill for sending Cisco Nexus
  9000 metrics to Splunk Observability Cloud via the OTel cisco_os receiver (multi-device + global
  scrapers format, PR #45562, currently at v0.149.0+ in upstream contrib). Renders the clusterReceiver
  overlay, K8s Secret manifest stub for SSH credentials, dashboards and starter detectors. Hands off base
  collector to splunk-observability-otel-collector-setup, dashboards to splunk-observability-dashboard-
  builder, detectors to splunk-observability-native-ops. Independent of Cisco AI Pod -- useful for any
  data center with Nexus fabric. Companion to cisco-dc-networking-setup (Splunk Platform TA for Nexus /
  ACI / Nexus Dashboard)."
compatibility: "No direct Splunk Platform runtime dependency. This workflow can be used alongside Splunk Cloud Platform 10.5.2605 through its documented external APIs or handoffs."
metadata:
  splunk_cloud_10_5: "not-applicable"
  compatibility_verified: "2026-08-20"
---

# Splunk Observability Cisco Nexus Integration

## Prerequisites

| Tool or access | Purpose | Verify |
|---|---|---|
| Bash and Python 3 | Run bundled setup and validation helpers | `bash --version && python3 --version` |
| Required product/platform access | Inspect or configure the selected target | Complete the documented preflight |
| Credential files for live modes | Keep secrets out of chat | Verify paths only |

## Workflow Overview

```text
┌───────────┐   ┌───────────────┐   ┌───────────────┐   ┌─────────────────┐
│ Preflight │ → │ Render/review │ → │ Apply/handoff │ → │ Validate evidence │
└───────────┘   └───────────────┘   └───────────────┘   └─────────────────┘
```

## When to Activate

- Send Cisco Nexus, NX-OS, IOS-XE, or IOS-XR device metrics to Splunk Observability Cloud, configure the cisco_os
  receiver, set up multi-device Nexus telemetry, or render dashboards/detectors for Cisco data center fabric.
- Preview and review the splunk observability cisco nexus integration workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-observability-cisco-nexus-integration/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-observability-cisco-nexus-integration/scripts/validate.sh --help
```

Expected output: offline, live, and completion options are displayed when the
skill supports them; help exits without mutation.

## Troubleshooting

| Issue | Cause | Resolution |
|---|---|---|
| Preflight fails | A required tool or access path is missing | Resolve it before rendering or applying |
| Rendered assets are incomplete | Required non-secret inputs are absent | Complete intake and render again |
| Apply is blocked | Review, credentials, or explicit acceptance is missing | Use the documented handoff |
| Validation is incomplete | Live evidence is unavailable | Record the gap and keep completion open |

This is a **standalone reusable skill** for Cisco Nexus 9000 (and any cisco_os-receiver-supported device) metrics in Splunk Observability Cloud. It is **independent of the AI Pod** umbrella — useful for any data center with Nexus fabric. The AI Pod skill composes this skill via subprocess + yq deep-merge.

The Splunk Platform TA path for Nexus / ACI / Nexus Dashboard lives in [cisco-dc-networking-setup](../cisco-dc-networking-setup/SKILL.md). That's a different layer (Splunk Platform side); this skill is the O11y side.

## What it renders

- `splunk-otel-overlay/values.overlay.yaml` — `clusterReceiver.config.receivers.cisco_os` block in the new multi-device + global-scrapers format (cisco_os receiver in upstream contrib v0.149.0+). Devices reference K8s Secret-mounted creds; supports `password` or `key_file` per device. Scrapers: `system` (`cisco.device.up`, `system.cpu.utilization`, `system.memory.utilization`) and `interfaces` (`system.network.io`, `system.network.errors`, `system.network.packet.dropped|count`, `system.network.interface.status`).
- `splunk-otel-overlay/cisco-os-pipeline.yaml` — `metrics/cisco-os-metrics` pipeline with `signalfx` exporter and `memory_limiter|batch|resourcedetection|resource` processors.
- `secrets/cisco-nexus-ssh-secret.yaml` — K8s Secret manifest stub (rendered with placeholders; user creates with `kubectl create secret generic --from-file=...`). Renderer never reads SSH passwords.
- `dashboards/<name>.signalflow.yaml` — Nexus port utilization, packet errors, drop rates, system CPU/memory, interface status.
- `detectors/<name>.yaml` — interface down, packet drop rate threshold, memory pressure.
- `scripts/setup.sh`, `render_assets.py`, `validate.sh`, `handoff-base-collector.sh`, `handoff-dashboards.sh`, `handoff-detectors.sh`.
- `metadata.json`.

## Safety Rules

- Never ask for Cisco Nexus SSH passwords or SSH keys in conversation.
- The renderer writes a K8s Secret manifest stub with placeholder values; the operator creates the actual Secret out-of-band with `kubectl create secret generic --from-file=...`.
- `--o11y-token-file` flag is for the Splunk Observability Org access token (passed through to base collector). Reject `--o11y-token`, `--access-token`, `--token`, `--bearer-token`, `--api-token`, `--sf-token`.
- Token files must be `chmod 600`; `--allow-loose-token-perms` overrides with WARN.

## Primary Workflow

1. Identify your Nexus devices (hostnames or management IPs) and gather per-device SSH credentials (out-of-band).

2. Render:

   ```bash
   bash skills/splunk-observability-cisco-nexus-integration/scripts/setup.sh \
     --render --validate \
     --realm us0 \
     --cluster-name lab-cluster \
     --nexus-device "core-switch-01:192.168.1.10" \
     --nexus-device "core-switch-02:192.168.1.11" \
     --output-dir splunk-observability-cisco-nexus-rendered
   ```

3. Review `splunk-observability-cisco-nexus-rendered/` and create the SSH credentials Secret:

   ```bash
   kubectl create secret generic cisco-nexus-ssh \
     --from-literal=username=splunk-otel \
     --from-file=password=/tmp/nexus_password \
     -n splunk-otel
   ```

4. Apply directly via the skill (recommended). This merges the rendered
   overlay onto the existing Splunk OTel collector helm release values and
   runs `helm upgrade --atomic`. Refuses without `--accept-k8s-apply`,
   refuses if the `cisco-nexus-ssh` Secret from step 3 is missing, and
   prints the active kube-context first:

   ```bash
   bash skills/splunk-observability-cisco-nexus-integration/scripts/setup.sh \
     --apply --accept-k8s-apply \
     --realm us0 --cluster-name lab-cluster \
     --nexus-device "core-switch-01:192.168.1.10" \
     --nexus-device "core-switch-02:192.168.1.11"
   ```

   `--apply --accept-k8s-apply --dry-run` runs `helm upgrade --dry-run`
   without mutating the cluster.

   For dashboards / detectors, the rendered handoff scripts call into the
   owning skills:

   ```bash
   bash splunk-observability-cisco-nexus-rendered/scripts/handoff-dashboards.sh
   bash splunk-observability-cisco-nexus-rendered/scripts/handoff-detectors.sh
   ```

## Hand-offs

- Splunk OTel Collector base install: [splunk-observability-otel-collector-setup](../splunk-observability-otel-collector-setup/SKILL.md).
- Dashboards: [splunk-observability-dashboard-builder](../splunk-observability-dashboard-builder/SKILL.md).
- Detectors: [splunk-observability-native-ops](../splunk-observability-native-ops/SKILL.md).

## Out of scope (companion skills)

- Splunk Platform TA path for Nexus / ACI / Nexus Dashboard: [cisco-dc-networking-setup](../cisco-dc-networking-setup/SKILL.md).
- Cisco Catalyst Center / ISE / SD-WAN / Cyber Vision: [cisco-catalyst-ta-setup](../cisco-catalyst-ta-setup/SKILL.md).

## Validation

```bash
bash skills/splunk-observability-cisco-nexus-integration/scripts/validate.sh
```

Static checks: overlay shape, Secret manifest placeholder validity, no inline credentials. With `--live`: `helm status`, OTel collector pod logs grep for `cisco_os` scrape errors.

See `reference.md` and the `references/` annexes for the cisco_os receiver schema, multi-device config, SSH secrets, dashboards catalog, and troubleshooting.

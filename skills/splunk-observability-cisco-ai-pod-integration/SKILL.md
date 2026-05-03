---
name: splunk-observability-cisco-ai-pod-integration
description: >-
  Umbrella skill that composes splunk-observability-cisco-nexus-integration +
  splunk-observability-cisco-intersight-integration +
  splunk-observability-nvidia-gpu-integration AND adds AI-Pod-specific
  bits (NIM / vLLM / Milvus / NetApp Trident / Pure Portworx / Redfish
  exporter, OpenShift SCC helper, workshop multi-tenant pattern). Mirrors
  canonical signalfx/splunk-opentelemetry-examples/collector/cisco-ai-ready-pods
  values + production-validated otel-gruve/6-splunk-otel-collector-values.yaml
  (atl-ocp2 OpenShift). Encodes critical production lessons: rbac.customRules
  block when endpoint-SD scrapes are used (base chart's ClusterRole grants
  only pods+services), receiver_creator/dcgm-cisco custom name (NOT
  receiver_creator/nvidia), DCGM dual-label discovery, dual-pipeline
  filtering pattern (filtered metrics + unfiltered metrics/cisco-ai-pods +
  metrics/nvidianim-metrics + metrics/cisco-os-metrics), k8s_attributes/nim
  processor with model_name extraction, NIM scrape via TWO modes
  (--nim-scrape-mode receiver_creator|endpoints), OpenShift defaults
  (kubeletstats.insecure_skip_verify, certmanager off, cloudProvider
  empty), helm --reuse-values --set token pattern. Hands off composed
  render to splunk-observability-otel-collector-setup with --distribution,
  HEC for K8s container logs to splunk-hec-service-setup, dashboards to
  splunk-observability-dashboard-builder, detectors to
  splunk-observability-native-ops. Use when deploying Splunk Observability
  Cloud for a Cisco AI Pod (UCS + Nexus + NVIDIA GPUs + NIM/vLLM
  inference + storage).
---

# Splunk Observability Cisco AI Pod Integration (Umbrella)

This is the **AI Pod umbrella** that ties together every component skill needed for end-to-end Cisco AI Pod observability in Splunk Observability Cloud. It composes:

1. [splunk-observability-cisco-nexus-integration](../splunk-observability-cisco-nexus-integration/SKILL.md) for Cisco Nexus 9000 fabric metrics (cisco_os receiver).
2. [splunk-observability-cisco-intersight-integration](../splunk-observability-cisco-intersight-integration/SKILL.md) for Cisco UCS metrics via Intersight OTel deployment.
3. [splunk-observability-nvidia-gpu-integration](../splunk-observability-nvidia-gpu-integration/SKILL.md) for NVIDIA GPU telemetry via DCGM Exporter.

And adds **AI-Pod-specific bits** documented in the configuration guide and production-validated by the atl-ocp2 OpenShift cluster:

- NIM scrapes (multi-job: llm/embedqa/rerankqa, port 8000 `/v1/metrics`).
- vLLM scrape (port 8000 `/metrics`).
- Milvus vector DB scrape (port 9091).
- NetApp Trident storage scrape (port 8001 `/metrics`).
- Pure Portworx storage scrape (ports 17001 + 17018).
- Redfish exporter (user-supplied) on port 9210.
- Cisco AI PODs Splunk Observability dashboard pipeline (`metrics/cisco-ai-pods`, unfiltered).
- NIM dashboard pipeline (`metrics/nvidianim-metrics`, unfiltered).
- `k8s_attributes/nim` processor for `app -> model_name` extraction.
- OpenShift SCC helper, workshop-multi-tenant.sh, dual-pipeline filtering pattern.

## Critical production lessons encoded

These are the **silent failure traps** the umbrella prevents:

1. **RBAC gap**: base chart's ClusterRole grants only `pods` and `services`. Any `kubernetes_sd_configs.role: endpoints` scrape (e.g. NIM in endpoint mode) silently fails with `endpoints is forbidden`. The umbrella emits the `rbac.customRules` block with `endpoints` + `discovery.k8s.io/endpointslices` get/list/watch when needed.
2. **receiver_creator naming**: `receiver_creator/dcgm-cisco`, NOT `receiver_creator/nvidia` (collision with chart autodetect). Inherited from the GPU child skill.
3. **DCGM dual-label discovery**: matches both `app` and `app.kubernetes.io/name`. Inherited from the GPU child skill.
4. **Dual-pipeline filtering**: filtered standard pipeline + unfiltered specialized pipelines for AI Pod dashboards. Smarter than the canonical single-pipeline pattern.
5. **OpenShift defaults**: `kubeletstats.insecure_skip_verify: true` (REQUIRED), `certmanager.enabled: false`, `cloudProvider: ""`.
6. **Helm token pattern**: apply scripts use `helm upgrade --install --reuse-values --set splunkObservability.accessToken="$(cat $TOKEN_FILE)"` so the token is never written to a tracked values file.

## Composition model

When you run `--render`, the umbrella:

1. Invokes each child skill's renderer to produce its overlay under a sub-directory.
2. Merges the child overlays into a unified `splunk-otel-overlay/values.overlay.yaml` via `yq` deep-merge.
3. Adds AI-Pod-specific blocks on top of the merged overlay.
4. Renders unified handoff scripts.

When you run `--apply [SECTION]`, the umbrella forwards to the appropriate child skill's apply or runs its own AI-Pod-specific apply.

## What it renders (composed + AI-Pod-specific)

- `splunk-otel-overlay/values.overlay.yaml` — composed overlay (Nexus + Intersight + GPU children + AI-Pod additions).
- `child-renders/<skill>/` — each child skill's full rendered output (preserved for debugging the merge).
- `intersight-integration/` — from the Intersight child.
- `secrets/cisco-nexus-ssh-secret.yaml` — from the Nexus child.
- `dcgm-pod-labels-patch/` — from the GPU child when `--enable-dcgm-pod-labels`.
- `nim-vllm-milvus-scrapes/` — AI-Pod-specific scrape configs for NIM, vLLM, Milvus.
- `storage-scrapes/` — Trident + Portworx scrape configs.
- `redfish-scrape/` — Redfish exporter scrape config.
- `openshift/scc.sh` — OpenShift SCC helper script.
- `workshop/multi-tenant.sh` — Workshop multi-tenant deploy script (when `--workshop-mode`).
- `dashboards/` — AI-Pod-specific dashboards (NIM/vLLM inference, Milvus, storage allocation, RAG pipeline trace).
- `detectors/` — AI-Pod-specific detectors (vLLM error rate, NIM TTFT regression, Milvus query latency, Portworx node offline, Trident volume allocation).
- `scripts/handoff-base-collector.sh` — emits the base collector + merge command with `--distribution openshift` (default).
- `scripts/handoff-hec-token.sh` — for K8s container log shipping to Splunk Platform.
- `scripts/handoff-dashboards.sh`, `handoff-detectors.sh` — composed dashboard + detector application across all four skills.
- `scripts/explain-composition.sh` — prints the per-child contribution summary.
- `metadata.json`.

## Safety Rules

- File-backed token flags only:
  - `--o11y-token-file` (Splunk Observability Org access token; passed through to all child skills + base collector).
  - `--platform-hec-token-file` (optional; for K8s container logs to Splunk Platform).
  - `--intersight-key-id-file` and `--intersight-key-file` (passed through to the Intersight child).
- Reject every direct token / key flag.
- Token files must be `chmod 600`; `--allow-loose-token-perms` overrides with WARN.
- Cisco Nexus SSH credentials handled by the Nexus child (K8s Secret stub; user creates the Secret out-of-band).

## Primary Workflow

1. Confirm prerequisites are installed: NVIDIA GPU Operator (or standalone DCGM Exporter), NIM/vLLM with the standard pod labels, Milvus, NetApp Trident, Pure Portworx, Redfish exporter, Cisco Intersight account + API key.

2. Render the composed overlay:

   ```bash
   bash skills/splunk-observability-cisco-ai-pod-integration/scripts/setup.sh \
     --render --validate \
     --realm us0 \
     --cluster-name atl-ai-pod \
     --distribution openshift \
     --nim-scrape-mode endpoints \
     --enable-dcgm-pod-labels \
     --output-dir splunk-observability-cisco-ai-pod-rendered
   ```

3. Apply child manifests (Intersight, optional DCGM patch) + merge overlay + apply via base collector:

   ```bash
   bash splunk-observability-cisco-ai-pod-rendered/scripts/handoff-base-collector.sh
   bash splunk-observability-cisco-ai-pod-rendered/scripts/handoff-dashboards.sh
   bash splunk-observability-cisco-ai-pod-rendered/scripts/handoff-detectors.sh
   ```

## Hand-offs

- Splunk OTel Collector base install: [splunk-observability-otel-collector-setup](../splunk-observability-otel-collector-setup/SKILL.md) with `--distribution openshift` (default; configurable).
- HEC for K8s container logs: [splunk-hec-service-setup](../splunk-hec-service-setup/SKILL.md).
- Dashboards: [splunk-observability-dashboard-builder](../splunk-observability-dashboard-builder/SKILL.md).
- Detectors: [splunk-observability-native-ops](../splunk-observability-native-ops/SKILL.md).
- Component skills (composed): Nexus / Intersight / GPU child skills.

## Out of scope

- All children's out-of-scope items (NVIDIA GPU Operator install, DCGM Exporter install, NIM/vLLM/Milvus/Trident/Portworx/Redfish exporter deployment, OpenShift cluster bootstrap, Cisco Intersight account creation).

## Validation

```bash
bash skills/splunk-observability-cisco-ai-pod-integration/scripts/validate.sh
```

Runs each child skill's `validate.sh` recursively, then adds AI-Pod-specific checks: `oc get deployment -n intersight-otel`, log tail for `<release>-splunk-otel-collector-k8s-cluster-receiver`, RBAC patch presence when endpoint-SD is used, optional SignalFlow probes for `num_requests_running`, `milvus_proxy_req_count`, `vllm:e2e_request_latency_seconds`.

See `reference.md` and `references/composition-and-overlay-merge.md`, `nim-vllm-scrape-catalog.md`, `milvus-storage-redfish.md`, `openshift-scc.md`, `workshop-multi-tenant.md`, `ai-pod-dashboards-catalog.md`, `endpoints-rbac-patch.md`, `dual-pipeline-filtering.md`, `nim-scrape-modes.md`, `production-troubleshooting-atl-ocp2.md`, `troubleshooting.md` for the full annexes.

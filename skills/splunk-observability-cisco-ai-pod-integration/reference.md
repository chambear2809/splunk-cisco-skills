# Splunk Observability Cisco AI Pod Integration (Umbrella) Reference

## Sources of truth

- `/Users/alecchamberlain/Downloads/Configuration Guide Splunk Observability for Cisco AI Pods - Updated 2026-05-01.pdf` — the operator-facing guide.
- `signalfx/splunk-opentelemetry-examples/collector/cisco-ai-ready-pods/otel-collector/values.yaml` — the canonical signalfx example.
- `/Users/alecchamberlain/Documents/GitHub/otel-gruve/6-splunk-otel-collector-values.yaml` — production-validated atl-ocp2 OpenShift cluster (Splunk OTel chart v0.147.1).
- Splunk Observability Workshop AI Pod scenario: `splunk.github.io/observability-workshop/en/ninja-workshops/14-cisco-ai-pods/`.

## Composition model

The umbrella invokes each child skill's `setup.sh --render` as a subprocess into a sub-directory under the umbrella's output dir. The child overlays are merged via Python deep-merge (right-biased, list de-duplication) into a unified overlay. AI-Pod-specific blocks are layered on top.

Children:

1. [splunk-observability-cisco-nexus-integration](../splunk-observability-cisco-nexus-integration/SKILL.md) — Cisco Nexus 9000 fabric metrics via cisco_os receiver.
2. [splunk-observability-cisco-intersight-integration](../splunk-observability-cisco-intersight-integration/SKILL.md) — Cisco UCS metrics via Intersight OTel deployment.
3. [splunk-observability-nvidia-gpu-integration](../splunk-observability-nvidia-gpu-integration/SKILL.md) — NVIDIA GPU telemetry via DCGM Exporter.

## Rendered layout

By default, assets are written under `splunk-observability-cisco-ai-pod-rendered/`:

- `splunk-otel-overlay/values.overlay.yaml` — composed overlay (children + AI-Pod additions).
- `child-renders/<skill>/...` — each child's full render (preserved for debugging).
- `intersight-integration/` — passed through from Intersight child.
- `secrets/cisco-nexus-ssh-secret.yaml` — passed through from Nexus child.
- `dcgm-pod-labels-patch/` — passed through from GPU child when `--enable-dcgm-pod-labels`.
- `openshift/scc.sh` — OpenShift SCC helper (anyuid + privileged for the Splunk OTel collector ServiceAccount).
- `workshop/multi-tenant.sh` — workshop multi-tenant deploy script (when `--workshop-mode`).
- `dashboards/ai-pod-llm-inference.signalflow.yaml`, `ai-pod-vector-db.signalflow.yaml`, `ai-pod-storage.signalflow.yaml` — AI-Pod-specific dashboards.
- `detectors/<name>.yaml` — vLLM error rate, NIM TTFT regression, Milvus query latency, Portworx node offline, Trident allocation pressure.
- `scripts/handoff-base-collector.sh`, `handoff-hec-token.sh`, `handoff-dashboards.sh`, `handoff-detectors.sh`, `explain-composition.sh`.
- `metadata.json`.

## AI-Pod-specific additions on top of children

- **NIM scrape**: `--nim-scrape-mode receiver_creator|endpoints`. Receiver_creator (default) uses per-model `receiver_creator/nim-<model>` blocks. Endpoints mode uses `kubernetes_sd_configs.role: endpoints` with namespace + service-name regex; **requires the rbac.customRules patch**.
- **vLLM scrape**: `receiver_creator/vllm-cisco` matching `app=vllm` (or `app.kubernetes.io/name=vllm`).
- **Milvus scrape**: `receiver_creator/milvus-cisco` matching `app.kubernetes.io/name=milvus` on port 9091.
- **Storage scrapes**: Trident (`controller.csi.trident.netapp.io` on port 8001), Portworx (`name=portworx` on ports 17001 + 17018).
- **Redfish exporter** (user-supplied): per-path scrapes (`/health`, `/performance`) on port 9210, matching `app=redfish-exporter`.
- **Dual-pipeline filtering**: `metrics/nvidianim-metrics` and `metrics/cisco-ai-pods` pipelines (unfiltered) on top of the children's filtered standard pipeline.
- **`k8s_attributes/nim`** processor with `app -> model_name` extraction for model-aware dashboards.
- **`signalfx.send_otlp_histograms: true`**.
- **OpenShift defaults** when `--distribution openshift`: `kubeletstats.insecure_skip_verify: true`, `certmanager.enabled: false`, `cloudProvider: ""`, `operator/operatorcrds/gateway` disabled.
- **rbac.customRules** when `--nim-scrape-mode endpoints`.
- **Workshop multi-tenant** when `--workshop-mode`.

## Setup modes

- `--render` (default), `--validate`, `--dry-run`, `--json`, `--explain`.

## Critical production lessons (silent failure traps the umbrella prevents)

1. **RBAC gap**: base chart's ClusterRole grants only `pods` and `services`. Endpoint-SD scrapes silently fail with `endpoints is forbidden`. The umbrella emits `rbac.customRules` automatically when `--nim-scrape-mode endpoints`.
2. **receiver_creator naming**: the GPU child uses `receiver_creator/dcgm-cisco`, NOT `receiver_creator/nvidia`. The umbrella's validate.sh fails if `receiver_creator/nvidia` shows up in the composed overlay.
3. **DCGM dual-label discovery**: the GPU child's discovery rule matches both `app` and `app.kubernetes.io/name`.
4. **Dual-pipeline filtering**: smarter than the canonical single-pipeline pattern.
5. **OpenShift requirements**: kubeletstats TLS skip, no certmanager, empty cloudProvider.
6. **Helm token pattern**: `--reuse-values --set splunkObservability.accessToken="$(cat $TOKEN_FILE)"` so the token never lands in a tracked values file.

## Hand-offs

- Splunk OTel Collector base install: [splunk-observability-otel-collector-setup](../splunk-observability-otel-collector-setup/SKILL.md) with `--distribution openshift` (default).
- HEC for K8s container logs: [splunk-hec-service-setup](../splunk-hec-service-setup/SKILL.md).
- Dashboards: [splunk-observability-dashboard-builder](../splunk-observability-dashboard-builder/SKILL.md).
- Detectors: [splunk-observability-native-ops](../splunk-observability-native-ops/SKILL.md).
- All component skills (composed): Nexus / Intersight / GPU children.

See `references/composition-and-overlay-merge.md`, `nim-vllm-scrape-catalog.md`, `milvus-storage-redfish.md`, `openshift-scc.md`, `workshop-multi-tenant.md`, `ai-pod-dashboards-catalog.md`, `endpoints-rbac-patch.md`, `dual-pipeline-filtering.md`, `nim-scrape-modes.md`, `production-troubleshooting-atl-ocp2.md`, `troubleshooting.md` for the full annexes.

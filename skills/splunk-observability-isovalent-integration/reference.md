# Splunk Observability Isovalent Integration Reference

## Sources of truth

- Reference implementation: [/Users/alecchamberlain/Documents/GitHub/Isovalent_Splunk_o11y](https://github.com/) — `examples/splunk-otel-isovalent.yaml`, `examples/Cilium by Isovalent.json`, `examples/Hubble by Isovalent.json`. **Do NOT** copy from `values/*.yaml` in that repo; the explore subagent confirmed those files have contained plaintext access tokens.
- Production-validated overlay: `/Users/alecchamberlain/Documents/GitHub/otel-gruve/6-splunk-otel-collector-values.yaml` (atl-ocp2 OpenShift cluster, Splunk OTel chart v0.147.1).
- Splunk Workshop: `splunk.github.io/observability-workshop/en/scenarios/isovalent-cilium-integration/`.
- Splunk blog: `splunk.com/en_us/blog/security/splunking-isovalent-data.html` (Splunk Threat Research Team, 2026-02-02).
- Splunk Platform sourcetype: `cisco:isovalent` (broad), `cisco:isovalent:processExec` (specific to Tetragon process exec events).

## Rendered layout

By default, assets are written under `splunk-observability-isovalent-rendered/`:

- `splunk-otel-overlay/values.overlay.yaml` — overlay for the base collector values.
- `dashboards/<name>.json` — token-scrubbed re-exports (when `--dashboards-source` is set; otherwise a README placeholder).
- `dashboards/README.md` — placeholder when no source provided.
- `detectors/<name>.yaml` — starter detector specs for `splunk-observability-native-ops`.
- `scripts/handoff-base-collector.sh` — emits the `splunk-observability-otel-collector-setup` invocation + the `yq` deep-merge command.
- `scripts/handoff-hec-token.sh` — emits the `splunk-hec-service-setup` invocation.
- `scripts/handoff-cisco-security-cloud.sh` — emits the `cisco-security-cloud-setup` invocation with `PRODUCT=isovalent`.
- `scripts/handoff-dashboards.sh` — emits the `splunk-observability-dashboard-builder` invocation.
- `scripts/handoff-detectors.sh` — emits the `splunk-observability-native-ops` invocation.
- `scripts/scrub-tokens.py` — token-scrub helper used both at render time and validation time.
- `metadata.json` — non-secret plan summary.

## Setup modes

- `--render` — render overlay + handoff scripts (default).
- `--validate` — run static validation against an already-rendered output directory.
- `--dry-run` — show the plan without writing.
- `--json` — emit JSON dry-run output.
- `--explain` — print plan in plain English.

## Required values

`--spec PATH` (defaults to `template.example`).

`--realm`, `--cluster-name`, `--distribution` can be supplied either via the spec (preferred) or on the command line (override).

## OTel collector overlay

Seven Prometheus scrape jobs (toggle each via spec.scrape):

| Job name | Pod label | Port |
|----------|-----------|------|
| `prometheus/isovalent_cilium` | `k8s-app=cilium` | 9962 |
| `prometheus/isovalent_hubble` | `k8s-app=cilium` (same pod) | 9965 |
| `prometheus/isovalent_envoy` | `k8s-app=cilium-envoy` | 9964 |
| `prometheus/isovalent_operator` | `io.cilium/app=operator` | 9963 |
| `prometheus/isovalent_tetragon` | `app.kubernetes.io/name=tetragon` | 2112 |
| `prometheus/isovalent_tetragon_operator` | `app.kubernetes.io/name=tetragon-operator` | 2113 |
| `prometheus/isovalent_dnsproxy` (optional) | `k8s-app=cilium-dnsproxy` | 9967 |

Plus `kubeletstats` (with `insecure_skip_verify: true` for OpenShift), `hostmetrics`, `otlp`.

The metrics pipeline applies the `filter/includemetrics` strict allow-list — only series in the list are forwarded to Splunk Observability Cloud. Extend the allow-list via `spec.metric_allowlist.extra`.

## Splunk Platform logs path

Default: file-based via OTel filelog receiver. Renders three coordinated blocks (per `references/tetragon-hostpath-coordination.md`):

1. `agent.extraVolumes` + `agent.extraVolumeMounts` mounting `/var/run/cilium/tetragon` from the host.
2. `logsCollection.extraFileLogs.filelog/tetragon` reading `/var/run/cilium/tetragon/*.log` with sourcetype `cisco:isovalent`, index `cisco_isovalent`.
3. `splunkPlatform.logsEnabled: true` and HEC endpoint plumbing.

Alternatives:

- `--export-mode stdout` — Tetragon stdout + container log collection. Useful when SCC/PSP blocks hostPath mounts.
- `--legacy-fluentd-hec` — fluentd `splunk_hec` block. **DEPRECATED** (`fluent-plugin-splunk-hec` archived 2025-06-24). Prominent warning in the rendered metadata.

## Secret handling

- `--o11y-token-file` — Splunk Observability Org access token (passed through to base collector at apply time; never written into the overlay).
- `--platform-hec-token-file` — Splunk Platform HEC token (or `--render-platform-hec-helper` to delegate provisioning to `splunk-hec-service-setup`).

Rejected direct flags: `--access-token`, `--token`, `--bearer-token`, `--api-token`, `--o11y-token`, `--sf-token`, `--platform-hec-token`, `--hec-token`. Each error message points at the matching `--*-file` flag.

## Hand-offs

- Splunk OTel Collector base install: [splunk-observability-otel-collector-setup](../splunk-observability-otel-collector-setup/SKILL.md) (rendered command in `handoff-base-collector.sh`).
- Splunk Platform HEC token: [splunk-hec-service-setup](../splunk-hec-service-setup/SKILL.md) (rendered command in `handoff-hec-token.sh`).
- Splunk Platform Tetragon log ingestion: [cisco-security-cloud-setup](../cisco-security-cloud-setup/SKILL.md) with `PRODUCT=isovalent`.
- Dashboards: [splunk-observability-dashboard-builder](../splunk-observability-dashboard-builder/SKILL.md).
- Detectors: [splunk-observability-native-ops](../splunk-observability-native-ops/SKILL.md).

See `references/collector-overlay.md`, `splunk-platform-paths.md`, `tetragon-hostpath-coordination.md`, `sourcetypes.md`, `dashboards-catalog.md`, and `troubleshooting.md` for the deep-dive annexes.

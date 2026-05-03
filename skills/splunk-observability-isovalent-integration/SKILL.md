---
name: splunk-observability-isovalent-integration
description: >-
  Wire an installed Isovalent stack (Cilium, Hubble, Tetragon, optionally
  Hubble Enterprise / cilium-dnsproxy) to Splunk Observability Cloud and
  Splunk Platform. Renders the Splunk OpenTelemetry Collector agent.config
  overlay with seven prometheus scrape jobs (cilium 9962, hubble 9965,
  envoy 9964, operator 9963, tetragon 2112, tetragon-operator 2113,
  optional cilium-dnsproxy) and a filter/includemetrics allow-list. The
  Splunk Platform logs path defaults to the production-validated file-based
  flow (OTel filelog receiver reading /var/run/cilium/tetragon/*.log via
  agent.extraVolumes hostPath mount, ships through the splunkhec exporter
  with sourcetype cisco:isovalent / index cisco_isovalent). Alternative
  paths: --export-mode stdout, --legacy-fluentd-hec (deprecated, plugin
  archived 2025-06-24). Hands off base collector to
  splunk-observability-otel-collector-setup, HEC token to
  splunk-hec-service-setup, Splunk Platform Tetragon log ingestion to
  cisco-security-cloud-setup (PRODUCT=isovalent), dashboards to
  splunk-observability-dashboard-builder, detectors to
  splunk-observability-native-ops. Use when wiring Cilium / Tetragon /
  Hubble metrics into Splunk Observability Cloud or piping Tetragon logs
  to Splunk Platform.
---

# Splunk Observability Isovalent Integration

This skill wires an installed Isovalent stack to Splunk Observability Cloud and Splunk Platform. It **depends on** the platform install completed by [cisco-isovalent-platform-setup](../cisco-isovalent-platform-setup/SKILL.md). Run that first, then this.

## What it renders

- `splunk-otel-overlay/values.overlay.yaml` — Splunk OTel collector agent.config overlay with seven Prometheus scrape jobs and the `filter/includemetrics` allow-list. Designed to merge with the base values produced by [splunk-observability-otel-collector-setup](../splunk-observability-otel-collector-setup/SKILL.md) via `yq` deep-merge.
- Splunk Platform logs path (DEFAULT — file-based via OTel filelog receiver):
  - `agent.extraVolumes` + `agent.extraVolumeMounts` hostPath mount of `/var/run/cilium/tetragon`.
  - `logsCollection.extraFileLogs.filelog/tetragon` block with sourcetype `cisco:isovalent`, index `cisco_isovalent`.
  - `splunkPlatform.logsEnabled: true`.
  - Coordinates with `cisco-isovalent-platform-setup`'s default Tetragon `export.mode: file` + `exportDirectory: /var/run/cilium/tetragon`.
- Alternative paths (behind explicit flags):
  - `--export-mode stdout` — Tetragon stdout + container log collection (no hostPath mount; useful when SCC/PSP blocks).
  - `--legacy-fluentd-hec` — fluentd `splunk_hec` block. **DEPRECATED** (`fluent-plugin-splunk-hec` archived 2025-06-24).
- `dashboards/cilium-by-isovalent.json` and `dashboards/hubble-by-isovalent.json` — token-scrubbed re-exports (sourced from the Isovalent_Splunk_o11y reference repo's `examples/*.json` only after `scripts/scrub-tokens.py` confirms zero `accessToken` material).
- `detectors/*.yaml` — starter detectors for `cilium_*`, `hubble_*`, `tetragon_*` series.
- `scripts/setup.sh`, `render_assets.py`, `validate.sh`, `handoff-base-collector.sh`, `handoff-hec-token.sh`, `handoff-cisco-security-cloud.sh`, `handoff-dashboards.sh`, `handoff-detectors.sh`, `scrub-tokens.py`.
- `metadata.json`.

## Safety Rules

- Never ask for the Splunk Observability ingest token or Splunk Platform HEC token in conversation.
- File-backed token flags only:
  - `--o11y-token-file` (Splunk Observability Org access token; passed through to base collector).
  - `--platform-hec-token-file` (Splunk Platform HEC token; or `--render-platform-hec-helper` to delegate to `splunk-hec-service-setup`).
- Reject direct token flags (`--access-token`, `--token`, `--bearer-token`, `--api-token`, `--o11y-token`, `--sf-token`, `--platform-hec-token`, `--hec-token`).
- Token files must be `chmod 600`; the wrapper aborts otherwise (override with `--allow-loose-token-perms`, emits WARN). The actual apply happens via the rendered handoff-*.sh scripts, which inherit the same chmod 600 enforcement when they re-invoke the base collector / HEC / dashboard / native-ops setups.
- The renderer scrubs every dashboard JSON it ships against an `accessToken` regex before writing. Render aborts if the source JSON contains plaintext token material.

## Primary Workflow

1. Confirm the Isovalent stack is installed (run `cisco-isovalent-platform-setup` first).

2. Render:

   ```bash
   bash skills/splunk-observability-isovalent-integration/scripts/setup.sh \
     --render \
     --validate \
     --realm us0 \
     --cluster-name lab-cluster \
     --output-dir splunk-observability-isovalent-rendered
   ```

3. Review `splunk-observability-isovalent-rendered/`:
   - `splunk-otel-overlay/values.overlay.yaml` — the overlay; merge into the base collector values.
   - `dashboards/*.json` — token-scrubbed dashboard exports.
   - `detectors/*.yaml` — starter detectors.
   - `scripts/handoff-*.sh` — hand-off drivers for the four downstream skills.

4. Apply the base collector with the overlay merged, then provision HEC, then route Tetragon logs to Splunk Platform via Cisco Security Cloud:

   ```bash
   bash splunk-observability-isovalent-rendered/scripts/handoff-base-collector.sh
   bash splunk-observability-isovalent-rendered/scripts/handoff-hec-token.sh
   bash splunk-observability-isovalent-rendered/scripts/handoff-cisco-security-cloud.sh
   bash splunk-observability-isovalent-rendered/scripts/handoff-dashboards.sh
   bash splunk-observability-isovalent-rendered/scripts/handoff-detectors.sh
   ```

## Hand-offs

- Splunk OTel Collector base install: [splunk-observability-otel-collector-setup](../splunk-observability-otel-collector-setup/SKILL.md). Render the base values, then merge our overlay via `yq` deep-merge.
- Splunk Platform HEC token: [splunk-hec-service-setup](../splunk-hec-service-setup/SKILL.md).
- Splunk Platform Tetragon log ingestion: [cisco-security-cloud-setup](../cisco-security-cloud-setup/SKILL.md) with `PRODUCT=isovalent` (sourcetype `cisco:isovalent:processExec`, index `cisco_isovalent`); confirmed in [skills/cisco-security-cloud-setup/products.json](../cisco-security-cloud-setup/products.json) lines 200-219.
- Dashboards: [splunk-observability-dashboard-builder](../splunk-observability-dashboard-builder/SKILL.md).
- Detectors: [splunk-observability-native-ops](../splunk-observability-native-ops/SKILL.md).

## Out of scope

- Cilium / Tetragon / Hubble install lifecycle — handled by [cisco-isovalent-platform-setup](../cisco-isovalent-platform-setup/SKILL.md).
- Splunk OTel collector base install — handled by [splunk-observability-otel-collector-setup](../splunk-observability-otel-collector-setup/SKILL.md).

## Validation

```bash
bash skills/splunk-observability-isovalent-integration/scripts/validate.sh
```

Static checks: overlay shape, token-scrub assertion, dashboard JSON validity, sourcetype/index match. With `--live`:

- `helm status` for the OTel collector release.
- Pod-IP scrape probes for the seven Prometheus ports (uses `kubectl get --raw` for Tetragon, NOT `kubectl exec`).
- Optional SignalFlow probe for `cilium_*`, `hubble_*`, `tetragon_*` series presence.
- Optional Splunk Platform search check: `index=cisco_isovalent sourcetype=cisco:isovalent` returns events.

See `reference.md` and the `references/` annexes for collector-overlay details, Splunk Platform paths, Tetragon hostPath coordination, sourcetype reference, dashboards catalog, and troubleshooting.

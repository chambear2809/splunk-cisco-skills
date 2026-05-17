---
name: splunk-edge-processor-setup
description: >-
  Render, preflight, apply, and validate the full Splunk Edge Processor
  lifecycle for both Splunk Cloud Platform tenants and Splunk Enterprise
  10.0+ data management control planes. Adds the EP control-plane object
  with TLS / mTLS, installs Edge Processor instances on Linux (systemd or
  no-systemd, plus optional Docker container), scales out to multi-instance
  with DNS-driven forwarder outputs.conf, manages source types, destinations
  (Splunk S2S, Splunk HEC, Amazon S3, syslog), SPL2 pipelines (with
  shared splunk-spl2-pipeline-kit templates and PCRE2 linting), applies pipelines to Edge Processors
  via the operator-supplied control-plane API base, enforces the
  default-destination guard, runs sizing preflight, and emits an ACS
  allowlist hand-off stub for Splunk Cloud destinations. Use when the user
  asks to install Splunk Edge Processor, manage EP pipelines, configure EP
  destinations or source types, scale out an EP, or migrate forwarders to
  send through an Edge Processor.
---

# Splunk Edge Processor Setup

This skill covers the full Edge Processor surface: control-plane object
management plus Linux instance install plus pipeline / destination /
source-type lifecycle, all from one render-first workflow.

## Architecture First

- **Two control planes**: Splunk Cloud Platform tenant
  (`<tenant>.scs.splunk.com`) AND Splunk Enterprise 10.0+ data management
  node. Choose with `--ep-control-plane cloud|enterprise`.
- **Control-plane API base is operator-supplied**: Splunk has not published
  a stable public REST API base path for EP control-plane objects (source
  types, destinations, pipelines). The skill renders the JSON payloads as a
  source of truth and provides an `apply-objects.sh` that can either (a)
  apply them via REST when `EP_API_BASE` is set, or (b) print a manual UI
  checklist when it is not. The same applies to `validate.sh`.
- **Default destination is critical** — without one, unprocessed data is
  silently dropped. The renderer refuses to render a plan with destinations
  but no default destination, and `validate.sh` re-checks at runtime.
- **EP instance install command is operator-supplied** — Splunk's Manage
  instances UI generates a one-shot install command containing a join token.
  Stage it via `write_secret_file.sh` and reference it through
  `EP_INSTALL_CMD_FILE`; the rendered host scripts execute it under the
  service user without ever placing the token in argv.
- **Multi-instance** — multiple EP instances behind a DNS record let
  forwarders route via a single hostname.
- **Shared SPL2 kit** — use `splunk-spl2-pipeline-kit` for complex SPL2
  authoring, SPL-to-SPL2 review, and PCRE2 migration lint before previewing
  pipelines in the Edge Processor UI.
- **FIPS mode** — pass `--ep-fips-mode enabled` only for non-containerized EP
  instances. FIPS mode is not supported for Docker/containerized EP.

## Agent Behavior — Credentials

Never paste EP API tokens, install command bodies, or HEC tokens into chat.

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/ep_api_token
bash skills/shared/scripts/write_secret_file.sh /tmp/ep_install_cmd.sh
bash skills/shared/scripts/write_secret_file.sh /tmp/ep_hec_token
```

The rendered scripts read tokens via `--*-token-file` flags and never embed
the value in rendered output.

## Quick Start

Render a single-instance Edge Processor in a Splunk Cloud tenant with one
S2S destination and one filtering pipeline:

```bash
bash skills/splunk-edge-processor-setup/scripts/setup.sh \
  --phase render \
  --ep-control-plane cloud \
  --ep-tenant-url https://example.scs.splunk.com \
  --ep-name prod-ep \
  --ep-instances "ep01.example.com=systemd" \
  --ep-target-daily-gb 50 \
  --ep-source-types "syslog_router" \
  --ep-destinations "primary=type=s2s;host=idx-cluster.example.com;port=9997;index_routing=specify_for_no_index:summary" \
  --ep-default-destination primary \
  --ep-pipelines "filter_dev=partition=Keep;sourcetype=app:dev;spl2_file=pipelines/filter_dev.spl2;destination=primary"
```

Apply to the control plane (REST when `EP_API_BASE` is set; otherwise emits
a manual UI checklist):

```bash
EP_API_BASE=https://<tenant-api-base> EP_API_TOKEN_FILE=/tmp/ep_api_token \
bash skills/splunk-edge-processor-setup/scripts/setup.sh --phase apply --ep-tenant-url https://example.scs.splunk.com
```

Install an instance on Linux (systemd):

```bash
EP_INSTALL_CMD_FILE=/tmp/ep_install_cmd.sh \
bash skills/splunk-edge-processor-setup/scripts/setup.sh --phase install-instance \
  --ep-tenant-url https://example.scs.splunk.com --ep-instances "ep01.example.com=systemd"
```

Validate rendered assets (structural check only — fast, no network):

```bash
bash skills/splunk-edge-processor-setup/scripts/validate.sh
```

Validate live against the control plane REST (requires `--ep-api-base`,
`--ep-api-token-file`, and `--ep-name`; `--ep-tenant-url` is used for handoff
messages):

```bash
bash skills/splunk-edge-processor-setup/scripts/validate.sh \
  --live \
  --ep-tenant-url https://example.scs.splunk.com \
  --ep-name prod-ep \
  --ep-api-base https://api.us-east-1.splunkcloud.com/<tenant>/edge-processor/v1 \
  --ep-api-token-file /tmp/ep_api_token
```

## What It Renders

Under `splunk-edge-processor-rendered/`:

- `control-plane/edge-processors/<name>.json` — EP control-plane object
  (TLS settings).
- `control-plane/source-types/<name>.json`.
- `control-plane/destinations/<name>.json`.
- `control-plane/pipelines/<name>.spl2` (SPL2 source-of-truth) and
  `pipelines/<name>.json` (API payload).
- `control-plane/apply-objects.sh` — orchestrates POST/PUT/DELETE in
  dependency order when `EP_API_BASE` is set; prints a manual UI checklist
  otherwise.
- `host/<host>/install-with-systemd.sh` — `cgroup` + service user, splunk-edge service unit; consumes the operator-supplied install command via `EP_INSTALL_CMD_FILE`.
- `host/<host>/install-without-systemd.sh` — direct nohup install.
- `host/<host>/install-docker.sh` — Docker compose skeleton (image + env are operator-supplied from the tenant install command).
- `host/<host>/uninstall.sh`.
- `forwarder-templates/outputs.conf` — DNS-driven forwarder outputs.
- `pipelines/templates/*.spl2` — shared SPL2 starters from
  `splunk-spl2-pipeline-kit` for the `edgeProcessor` profile.
- `validate.sh` — control-plane health, default-destination guard, sizing check.
- `handoffs/acs-allowlist.json` — ACS allowlist plan stub for `s2s` + `hec` features.

## Out of Scope

- Live automated SPL→SPL2 conversion (use Splunk's in-product tool; this repo
  renders compatibility lint and review guidance only).
- Multi-tenant org management on Splunk Cloud.
- Destinations not yet documented in Splunk's public EP destination catalog
  (Kafka, Azure Event Hubs).
- RBAC management on the EP control plane.
- Automatic resolution of the EP control-plane REST API base — the operator
  supplies `EP_API_BASE` when applying via REST.
- Containerized FIPS mode.

## References

- [reference.md](reference.md) for full source-type / destination /
  pipeline syntax, the systemd unit template, the sizing-preflight table,
  and the ACS allowlist hand-off contract.
- [template.example](template.example) for the non-secret intake worksheet.

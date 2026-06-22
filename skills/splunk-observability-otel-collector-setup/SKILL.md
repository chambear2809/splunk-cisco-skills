---
name: splunk-observability-otel-collector-setup
description: Use when telemetry pipeline management needs Splunk OTel Collector pre-ingest filtering, attribute cleanup, receiver/exporter changes, or collector-side data control instead of native Metrics Pipeline Management rules; also use when deploying the Splunk Distribution of OpenTelemetry Collector for Splunk Observability Cloud to Kubernetes clusters, individual Linux hosts, or Universal Forwarder fleets through Splunkbase app 7125 with render-first, file-based-secret workflows.
---

# Splunk Observability OTel Collector Setup

## TA Completion Gate

For every TA/add-on or dashboard companion run, satisfy the shared
[TA completion gate](../shared/ta_completion_gate.md): configure and enable the
data ingest path owned by this skill or its required companion, validate events
or metrics in the target indexes/source types, and verify any
pre-built/package-shipped dashboards are visible, macro-aligned, and returning
data. If the package ships no dashboards, record that evidence explicitly and
hand off dashboard use to the consuming app, ES/ITSI/ARI content, or readiness
doctor.

## Overview

Use this skill to render, review, and optionally apply Splunk Distribution of OpenTelemetry Collector deployments for Kubernetes, Linux hosts, and Splunkbase app `7125` (Splunk Add-On for OpenTelemetry Collector) on Universal Forwarders.

When a user says telemetry pipeline management, first disambiguate scope. Native
Splunk Observability **Metrics Pipeline Management (MPM)** is owned by
`splunk-observability-deep-native-workflows`; this OTel skill owns collector-side
pre-ingest control, including receivers, processors, exporters, filtering,
attribute cleanup, batching, gateway topology, and Splunk Platform HEC log
handoffs.

The workflow is render-first by default. Live changes only happen when the user explicitly asks for `--apply-k8s`, `--apply-linux`, or `--apply-ta`.

## Safety Rules

- Never ask for Splunk Observability access tokens or Splunk Platform HEC tokens in conversation.
- Never pass tokens on the command line or as environment-variable prefixes.
- For Splunkbase app `7125`, reject direct token flags such as `--ta-access-token`, `--splunk-access-token`, and `--otel-ta-access-token`.
- Require file-based secrets with `--o11y-token-file` and, when Kubernetes container logs are sent to Splunk Platform HEC, `--platform-hec-token-file` or the local-only token file rendered by `--render-platform-hec-helper`.
- Prefer `SPLUNK_O11Y_REALM` and `SPLUNK_O11Y_TOKEN_FILE` from the repo `credentials` file when present; these store only the realm and token-file path, not the token value.
- Reject direct token flags such as `--access-token`, `--o11y-token`, `--token`, `--api-token`, `--sf-token`, `--hec-token`, and `--platform-hec-token`.
- Use `bash skills/shared/scripts/write_secret_file.sh /tmp/splunk_o11y_token` when the user needs to create a local token file without shell history exposure.
- Token files must be `chmod 600`. Apply runs preflight-check token-file
  permissions and abort with a `chmod 600 <path>` hint when they are looser.
  Pass `--allow-loose-token-perms` to override (use only for short-lived
  scratch tokens; the override emits a WARN).
- When `--kube-context` is set during apply, the rendered `status.sh` carries
  the same context to `helm status` and `kubectl`, so post-install verification
  always targets the cluster the install ran against.
- Splunkbase app `7125` is cloud-compatible but is not FIPS-compatible and is
  not FedRAMP validated in the audited metadata. Refuse `--ta-fips-required` or
  `--ta-fedramp-required` unless `--accept-ta-regulated-override` is supplied;
  the override renders a warning packet.

## Primary Workflow

1. Collect non-secret deployment values:
   - Splunk Observability realm, such as `us0`.
   - Kubernetes namespace, Helm release name, and cluster name, unless the chart distribution can auto-detect the cluster name.
   - Optional Splunk Platform HEC URL for Kubernetes container logs.
   - Linux host, SSH user, and execution mode when applying to a remote Linux host.
   - Optional HEC token name, default index, and Splunk Platform target when the user wants this skill to render the HEC setup handoff.

2. Render assets:

   ```bash
   bash skills/splunk-observability-otel-collector-setup/scripts/setup.sh \
     --render-k8s \
     --render-linux \
     --realm us0 \
     --namespace splunk-otel \
     --release-name splunk-otel-collector \
     --cluster-name demo-cluster \
     --o11y-token-file /tmp/splunk_o11y_token
   ```

3. Review `splunk-observability-otel-rendered/`.

4. If Kubernetes container logs need a new Splunk Platform HEC token, render the handoff helper:

   ```bash
   bash skills/splunk-observability-otel-collector-setup/scripts/setup.sh \
     --render-platform-hec-helper \
     --render-k8s \
     --realm us0 \
     --cluster-name demo-cluster \
     --platform-hec-url https://splunk.example.com:8088/services/collector \
     --hec-platform cloud \
     --hec-token-name splunk_otel_k8s_logs \
     --hec-default-index k8s_logs
   ```

   Then run `splunk-observability-otel-rendered/platform-hec/apply-hec-service.sh` before Kubernetes apply. The helper delegates token creation to `splunk-hec-service-setup` and writes or reads only the local token file used by `--platform-hec-token-file`.

5. Apply only when explicitly requested:

   ```bash
   bash skills/splunk-observability-otel-collector-setup/scripts/setup.sh \
     --apply-k8s \
     --apply-linux \
     --execution ssh \
     --linux-host otel-host.example.com \
     --ssh-user ec2-user \
     --realm us0 \
     --namespace splunk-otel \
     --release-name splunk-otel-collector \
     --cluster-name demo-cluster \
     --o11y-token-file /tmp/splunk_o11y_token
   ```

6. To render the Splunk Add-On for OpenTelemetry Collector for a UF fleet:

   ```bash
   bash skills/splunk-observability-otel-collector-setup/scripts/setup.sh \
     --render-ta \
     --realm us0 \
     --ta-package-path ./Splunk_TA_otel-0.153.0.tgz \
     --ta-target deployment-server \
     --ta-mode agent
   ```

   Review `splunk-observability-otel-rendered/ta/`, then stage the package and
   use the rendered `agent-management/render-serverclass-handoff.sh` handoff for
   `serverclass.conf`. Use `splunk-deployment-server-setup` for deployment
   server reload and runtime health checks.

## Kubernetes Behavior

The renderer creates Helm values and helper scripts for the official `splunk-otel-collector` Helm chart. Observability metrics, traces, and profiling use Splunk Observability Cloud. Kubernetes events can be sent to Observability with the chart feature gate.

Container logs require Splunk Platform HEC. When `--platform-hec-url` is paired with either `--platform-hec-token-file` or `--render-platform-hec-helper`, the rendered values enable `splunkPlatform.logsEnabled` and the rendered Kubernetes secret includes `splunk_platform_hec_token`.

When the token does not exist yet, use `--render-platform-hec-helper`. This renders `platform-hec/render-hec-service.sh`, `platform-hec/apply-hec-service.sh`, and `platform-hec/status-hec-service.sh`. The scripts call `splunk-hec-service-setup` for Splunk Cloud ACS or Splunk Enterprise `inputs.conf` workflows, so HEC token creation stays in the shared HEC skill while the OTel skill gives users the exact handoff command.

Kubernetes coverage includes Operator CRDs for auto-instrumentation, optional cert-manager support, OBI, Secure Application, Windows-node chart values, EKS/Fargate gateway mode, GKE Autopilot priority-class helpers, cluster receiver control, agent host networking, Splunk Platform persistent queues, and Observability ingest/API URL overrides.

## Linux Behavior

The renderer creates local and SSH install wrappers around the official Linux installer. The wrappers feed the Observability token through stdin from `--o11y-token-file`, set `VERIFY_ACCESS_TOKEN=false` to avoid token-bearing verification commands, and never place token values on argv.

Linux render options include host metrics, profiling, discovery, auto-instrumentation, deployment environment, listen interface, memory limit, endpoint overrides, service user/group, repo channel, custom collector config, OTLP endpoint/exporter settings, npm path, instrumentation package version, GODEBUG, and optional OBI flags.

## Splunkbase 7125 TA Behavior

TA support is opt-in with `--render-ta` or `--apply-ta`; the default Kubernetes
and Linux behavior is unchanged. The renderer inspects supplied `.tgz` packages,
supports app roots `Splunk_TA_otel`, `Splunk_TA_otel_linux_x86_64`, and
`Splunk_TA_otel_windows_x86_64`, and audits required files, config files, OS
binaries, version, package flavor, token field style, and default stanza shape.

The audited Splunkbase baseline is app `7125` version `0.153.0`, published
May 27, 2026, compatible with Splunk `8.0` through `10.4` (default target
`10.4`; older Enterprise and Cloud trains remain supported), cloud-compatible,
not FIPS-compatible, and not FedRAMP validated.

Current `0.152.x` packages use `splunk_access_token`; older docs and legacy
packages may use `splunk_access_token_file`, which is supported only through
`--ta-secret-mode legacy-file`.

TA render options include deployment-server or local UF targets, multi-OS or
platform-specific packages, `agent`, `gateway`, and generated
`agent-to-gateway` modes, collector log level, collector environment variables,
collector command arguments, and the `--ta-enable-opamp` feature gate.
Rendered staging scripts re-check package path safety before extraction and
reject unexpected top-level archive payloads.

Secret modes are explicit:

- `placeholder` renders no token value.
- `inputs-conf` renders `__SPLUNK_O11Y_ACCESS_TOKEN__`; apply requires both
  `--accept-ta-token-in-conf` and a readable `--o11y-token-file`.
- `legacy-file` supports packages with `splunk_access_token_file` and writes
  `local/access_token` during apply with mode `600`.
- `environment` renders an environment placeholder and expects runtime secret
  injection outside Splunk conf.

Do not pass tokens through `--ta-collector-env` or `--ta-collector-cmd-arg`;
the renderer rejects secret-like keys and assignments because those values would
land in rendered Splunk conf or process arguments.

## Validation

Use the validation script for static checks, or add `--live` after applying:

```bash
bash skills/splunk-observability-otel-collector-setup/scripts/validate.sh --check-k8s --check-linux
bash skills/splunk-observability-otel-collector-setup/scripts/validate.sh --check-ta
```

See `reference.md` for option details, rendered file layout, and implementation notes.

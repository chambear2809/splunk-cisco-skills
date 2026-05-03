---
name: splunk-observability-otel-collector-setup
description: Use when deploying the Splunk Distribution of OpenTelemetry Collector for Splunk Observability Cloud to Kubernetes clusters or individual Linux hosts with render-first, file-based-secret workflows.
---

# Splunk Observability OTel Collector Setup

## Overview

Use this skill to render, review, and optionally apply Splunk Distribution of OpenTelemetry Collector deployments for Kubernetes and Linux hosts.

The workflow is render-first by default. Live changes only happen when the user explicitly asks for `--apply-k8s` or `--apply-linux`.

## Safety Rules

- Never ask for Splunk Observability access tokens or Splunk Platform HEC tokens in conversation.
- Never pass tokens on the command line or as environment-variable prefixes.
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

## Kubernetes Behavior

The renderer creates Helm values and helper scripts for the official `splunk-otel-collector` Helm chart. Observability metrics, traces, and profiling use Splunk Observability Cloud. Kubernetes events can be sent to Observability with the chart feature gate.

Container logs require Splunk Platform HEC. When `--platform-hec-url` is paired with either `--platform-hec-token-file` or `--render-platform-hec-helper`, the rendered values enable `splunkPlatform.logsEnabled` and the rendered Kubernetes secret includes `splunk_platform_hec_token`.

When the token does not exist yet, use `--render-platform-hec-helper`. This renders `platform-hec/render-hec-service.sh`, `platform-hec/apply-hec-service.sh`, and `platform-hec/status-hec-service.sh`. The scripts call `splunk-hec-service-setup` for Splunk Cloud ACS or Splunk Enterprise `inputs.conf` workflows, so HEC token creation stays in the shared HEC skill while the OTel skill gives users the exact handoff command.

Kubernetes coverage includes Operator CRDs for auto-instrumentation, optional cert-manager support, OBI, Secure Application, Windows-node chart values, EKS/Fargate gateway mode, GKE Autopilot priority-class helpers, cluster receiver control, agent host networking, Splunk Platform persistent queues, and Observability ingest/API URL overrides.

## Linux Behavior

The renderer creates local and SSH install wrappers around the official Linux installer. The wrappers feed the Observability token through stdin from `--o11y-token-file`, set `VERIFY_ACCESS_TOKEN=false` to avoid token-bearing verification commands, and never place token values on argv.

Linux render options include host metrics, profiling, discovery, auto-instrumentation, deployment environment, listen interface, memory limit, endpoint overrides, service user/group, repo channel, custom collector config, OTLP endpoint/exporter settings, npm path, instrumentation package version, GODEBUG, and optional OBI flags.

## Validation

Use the validation script for static checks, or add `--live` after applying:

```bash
bash skills/splunk-observability-otel-collector-setup/scripts/validate.sh --check-k8s --check-linux
```

See `reference.md` for option details, rendered file layout, and implementation notes.

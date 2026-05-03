# Splunk Observability OTel Collector Reference

## Source Guidance

This skill follows the Splunk Kubernetes Helm installation workflow, the official `splunk-otel-collector` Helm values, advanced chart configuration notes, the Linux installer script workflow, and Splunk HEC exporter guidance.

## Rendered Layout

By default, assets are written under `splunk-observability-otel-rendered/`:

- `k8s/values.yaml` - Helm values for the Splunk OTel Collector chart.
- `k8s/create-secret.sh` - creates a Kubernetes Secret from token files.
- `k8s/helm-install.sh` - installs or upgrades the official Helm chart.
- `k8s/status.sh` - basic Helm and Kubernetes rollout checks.
- `platform-hec/render-hec-service.sh` - optional handoff script that renders reusable HEC service assets through `splunk-hec-service-setup`.
- `platform-hec/apply-hec-service.sh` - optional handoff script that creates or updates the HEC token through Cloud ACS or Enterprise `inputs.conf` workflows.
- `platform-hec/status-hec-service.sh` - optional HEC service status helper.
- `platform-hec/README.md` - HEC handoff instructions and token-file path.
- `linux/install-local.sh` - installs on the current Linux host.
- `linux/install-ssh.sh` - copies the token file to one SSH host, installs, and removes the remote token file.
- `linux/status-local.sh` and `linux/status-ssh.sh` - service checks.
- `metadata.json` - non-secret plan details and warnings.

## Setup Modes

`setup.sh` supports these mode flags:

- `--render-k8s` - render Kubernetes assets.
- `--render-linux` - render Linux assets.
- `--apply-k8s` - render then run Kubernetes helper scripts.
- `--apply-linux` - render then run the selected Linux helper script.
- `--render-platform-hec-helper` - render Splunk Platform HEC helper scripts without applying them.
- `--dry-run` - show the plan without writing files or applying changes.
- `--json` - emit JSON dry-run output.

If no render or apply mode is supplied and other flags are present, the setup script renders both Kubernetes and Linux assets.

## Required Values

`--realm` is always required for render or apply. Kubernetes rendering also needs `--namespace`, `--release-name`, and `--cluster-name`, unless `--distribution` is one of the chart distributions that can auto-detect the cluster name, such as `eks`, `eks/auto-mode`, `gke`, `gke/autopilot`, or `openshift`.

Default Kubernetes values:

- Namespace: `splunk-otel`
- Release name: `splunk-otel-collector`
- Secret name: `<release-name>-splunk`

Default Linux values:

- Execution: `local`
- Mode: `agent`
- Memory: `512`
- Listen interface: `0.0.0.0`
- Installer URL: `https://dl.observability.splunkcloud.com/splunk-otel-collector.sh`

## Secret Handling

Supported secret-file flags:

- `--o11y-token-file`
- `--platform-hec-token-file`

Rejected direct-secret flags:

- `--access-token`
- `--hec-token`
- `--o11y-token`
- `--platform-hec-token`

The renderer never reads token files. Rendered Kubernetes secret creation uses `kubectl create secret --from-file=...`, and Linux installers redirect stdin from the token file.

When `--render-platform-hec-helper` is supplied without `--platform-hec-token-file`, the OTel renderer uses `splunk-observability-otel-rendered/platform-hec/.splunk_platform_hec_token` as the local-only handoff path. The Cloud helper passes that path as `--write-token-file` so ACS can write the returned token locally. The Enterprise helper passes the same path as `--token-file` so `splunk-hec-service-setup` can read or create a GUID token before writing `inputs.conf`.

## All-Signal Defaults

Metrics, traces, profiling, Kubernetes events, discovery, and auto-instrumentation are enabled by default. OBI is available through `--enable-obi` because it has elevated runtime requirements.

Kubernetes container logs are enabled only when `--platform-hec-url` is paired with either `--platform-hec-token-file` or `--render-platform-hec-helper`. Without those values, the renderer preserves the rest of the all-signal setup and records a warning that Kubernetes container logs need Splunk Platform HEC.

If the token has not been created, add `--render-platform-hec-helper`. The helper supports:

- `--hec-platform cloud|enterprise`
- `--hec-token-name`
- `--hec-description`
- `--hec-default-index`
- `--hec-allowed-indexes`
- `--hec-source`
- `--hec-sourcetype`
- `--hec-use-ack`
- `--hec-port`
- `--hec-enable-ssl`
- `--hec-splunk-home`
- `--hec-app-name`
- `--hec-restart-splunk`
- `--hec-s2s-indexes-validation`

The helper does not duplicate HEC token creation logic. It renders exact wrapper scripts that call `skills/splunk-hec-service-setup/scripts/setup.sh` with the matching platform, token name, index restrictions, and file-based token path.

Kubernetes auto-instrumentation renders `operator.enabled=true` and `operatorcrds.install=true` by default. Use `--skip-operator-crds` only when CRDs are installed separately. Use `--enable-certmanager` only for clusters that require cert-manager, because the chart now prefers operator-generated certificates.

Additional Kubernetes coverage:

- `--windows-nodes` renders the official Windows image and probe settings.
- `--disable-cluster-receiver` supports split Linux/Windows installs without duplicate cluster metrics.
- `--distribution eks/fargate` renders `gateway.enabled=true`, because Fargate does not support the agent DaemonSet.
- `--priority-class-name` and `--render-priority-class` cover GKE Autopilot scheduling guidance.
- `--enable-platform-persistent-queue`, `--platform-persistent-queue-path`, and `--enable-platform-fsync` cover Splunk Platform exporter queue durability.
- `--o11y-ingest-url`, `--o11y-api-url`, and `--enable-secure-app` cover Observability endpoint and Secure Application options.

Additional Linux coverage:

- `--api-url`, `--ingest-url`, `--trace-url`, and `--hec-url` override installer-derived endpoints.
- `--collector-config`, `--service-user`, `--service-group`, `--skip-collector-repo`, and `--repo-channel` control package and service installation.
- `--otlp-endpoint`, `--otlp-endpoint-protocol`, `--metrics-exporter`, `--logs-exporter`, `--npm-path`, and `--instrumentation-version` control zero-code instrumentation behavior.
- `--godebug`, `--obi-version`, and `--obi-install-dir` expose current installer knobs without putting secrets on argv.

## Apply Notes

Kubernetes apply runs:

1. Optional `k8s/eks-update-kubeconfig.sh`, when EKS cluster and region values are supplied.
2. `k8s/create-secret.sh`.
3. `k8s/helm-install.sh`.

If `platform-hec/` is rendered and the HEC token file does not already exist, run `platform-hec/apply-hec-service.sh` before Kubernetes apply. The OTel setup script intentionally does not run that helper automatically, because it may create or update Splunk Platform HEC admin objects.

Linux apply runs either `linux/install-local.sh` or `linux/install-ssh.sh` based on `--execution local|ssh`.

## Validation Notes

`validate.sh` defaults to static checks for whichever rendered directories exist. Use `--check-k8s` or `--check-linux` to force a specific target. Use `--live` only after apply, because it calls Helm, kubectl, systemctl, or SSH service checks.

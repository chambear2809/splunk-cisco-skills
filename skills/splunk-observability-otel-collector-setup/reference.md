# Splunk Observability OTel Collector Reference

## Source Guidance

This skill follows the Splunk Kubernetes Helm installation workflow, the official `splunk-otel-collector` Helm values, advanced chart configuration notes, the Linux installer script workflow, Splunk HEC exporter guidance, Splunkbase app `7125`, the Splunk Add-On for OpenTelemetry Collector docs, and upstream `signalfx/splunk-otel-collector` `v0.153.0` TA packaging.

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
- `ta/README.md` - Splunkbase app `7125` TA workflow summary.
- `ta/metadata.json` - non-secret app metadata, package inspection, and selected options.
- `ta/package-audit.md` - per-package audit report.
- `ta/local/inputs.conf.template` - generated modular input stanza from `inputs.conf.spec`.
- `ta/local/<app-root>/inputs.conf.template` - per-package local overlay template.
- `ta/local/<app-root>/agent_to_gateway_config.yaml` - generated fallback config when `--ta-mode agent-to-gateway` is selected.
- `ta/preflight-ta.sh` - validates supplied package archives.
- `ta/stage-ta-package.sh` - extracts TA packages into deployment apps or local UF apps.
- `ta/apply-deployment-server.sh` - overlays local TA config under deployment apps.
- `ta/apply-local-uf.sh` - overlays local TA config under a UF app directory.
- `ta/status-ta.sh` - basic Splunk btool/app status checks.
- `ta/agent-management/render-serverclass-handoff.sh` - handoff to `splunk-agent-management-setup`.
- `ta/regulated-environment-warning.md` - rendered only when regulated override is accepted.
- `metadata.json` - non-secret plan details and warnings.

## Setup Modes

`setup.sh` supports these mode flags:

- `--render-k8s` - render Kubernetes assets.
- `--render-linux` - render Linux assets.
- `--render-ta` - render Splunkbase app `7125` TA assets.
- `--apply-k8s` - render then run Kubernetes helper scripts.
- `--apply-linux` - render then run the selected Linux helper script.
- `--apply-ta` - render then run TA package preflight, staging, and target overlay scripts.
- `--render-platform-hec-helper` - render Splunk Platform HEC helper scripts without applying them.
- `--dry-run` - show the plan without writing files or applying changes.
- `--json` - emit JSON dry-run output.

If no render or apply mode is supplied and other flags are present, the setup script renders both Kubernetes and Linux assets. TA assets are rendered only when `--render-ta` or `--apply-ta` is supplied.

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

Default TA values:

- Target: `deployment-server`
- Package flavor: `auto`
- Mode: `agent`
- Listen interface: `localhost` for `agent` and `agent-to-gateway`, `0.0.0.0` for `gateway`
- Collector log level: `error`
- Secret mode: `placeholder`

## Secret Handling

Supported secret-file flags:

- `--o11y-token-file`
- `--platform-hec-token-file`

Rejected direct-secret flags:

- `--access-token`
- `--hec-token`
- `--o11y-token`
- `--platform-hec-token`
- `--ta-access-token`
- `--splunk-access-token`
- `--otel-ta-access-token`

The renderer never reads token files. Rendered Kubernetes secret creation uses `kubectl create secret --from-file=...`, and Linux installers redirect stdin from the token file.

TA rendering also never reads token files. For current app `7125` packages using
`splunk_access_token`, `--ta-secret-mode inputs-conf` renders only
`__SPLUNK_O11Y_ACCESS_TOKEN__`; `--apply-ta` requires
`--accept-ta-token-in-conf` and a readable `--o11y-token-file` before the
rendered apply script replaces the placeholder in `local/inputs.conf`.
Legacy packages using `splunk_access_token_file` are supported with
`--ta-secret-mode legacy-file`, which writes `local/access_token` during apply
and chmods it to `600`.

TA collector environment variables and command arguments are rendered into
Splunk conf, so secret-like keys or assignments are rejected there as well.
Use `--ta-secret-mode environment` for runtime token injection rather than
passing token material through `--ta-collector-env` or
`--ta-collector-cmd-arg`.

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

## Splunkbase 7125 TA Coverage

The TA path targets Universal Forwarder deployment through a deployment server
or a local UF app directory. It is not enabled by default and does not change the
Kubernetes Helm or standalone Linux installer paths.

Audited app metadata:

- Splunkbase app id: `7125`
- Latest audited release: `0.153.0`
- Published: `2026-05-27`
- Splunk compatibility: `8.0` through `10.4`
- Splunk Cloud compatible: `true`
- FIPS-compatible: `false`
- FedRAMP validated: `false`

Package inspection supports these app roots:

- `Splunk_TA_otel`
- `Splunk_TA_otel_linux_x86_64`
- `Splunk_TA_otel_windows_x86_64`

Each supplied `.tgz` is inspected for:

- `default/app.conf`
- `default/inputs.conf`
- `README/inputs.conf.spec`
- `configs/agent_config.yaml`
- `configs/gateway_config.yaml`
- `linux_x86_64/bin/Splunk_TA_otel` when Linux is expected
- `windows_x86_64/bin/Splunk_TA_otel.exe` when Windows is expected

The renderer records version, package flavor, supported OS, token field style,
config presence, platform binaries, packaged default stanza, spec stanza, and
whether the rendered modular input stanza differs from packaged defaults. Any
token-like package field values are redacted from `metadata.json`. For current
`0.152.x` packages, the supported current token field is
`splunk_access_token`; older docs and packages may mention
`splunk_access_token_file`, which this skill handles only with
`--ta-secret-mode legacy-file`.

The staged package helper re-validates tar members at execution time and rejects
absolute paths, `..` traversal, symlinks, hardlinks, unsupported tar member
types, and unexpected top-level package members before extraction. This guards
against package replacement after render.

TA mode options:

- `--ta-mode agent` points `splunk_config` at `configs/agent_config.yaml`.
- `--ta-mode gateway` points `splunk_config` at `configs/gateway_config.yaml`.
- `--ta-mode agent-to-gateway` requires `--ta-gateway-url HOST:PORT` and emits
  a generated `local/agent_to_gateway_config.yaml` fallback.
- `--ta-collector-cmd-arg` may be repeated; arguments are shell-quoted into
  `splunk_collector_cmd_args` so the TA's shlex parsing preserves spaces.

TA handoffs:

- `splunk-agent-management-setup` owns `serverclass.conf` authoring.
- `splunk-deployment-server-setup` owns deployment-server reload and runtime health.
- `splunk-universal-forwarder-setup` owns UF installation and enrollment.
- `splunk-hec-service-setup` is used only when overriding `SPLUNK_HEC_URL` or
  `SPLUNK_HEC_TOKEN` for Splunk Platform HEC logs; otherwise current
  Observability log-ingest defaults are documented but not changed.

## Apply Notes

Kubernetes apply runs:

1. Optional `k8s/eks-update-kubeconfig.sh`, when EKS cluster and region values are supplied.
2. `k8s/create-secret.sh`.
3. `k8s/helm-install.sh`.

If `platform-hec/` is rendered and the HEC token file does not already exist, run `platform-hec/apply-hec-service.sh` before Kubernetes apply. The OTel setup script intentionally does not run that helper automatically, because it may create or update Splunk Platform HEC admin objects.

Linux apply runs either `linux/install-local.sh` or `linux/install-ssh.sh` based on `--execution local|ssh`.

TA apply runs:

1. `ta/preflight-ta.sh`
2. `ta/stage-ta-package.sh`
3. `ta/apply-deployment-server.sh` for deployment-server targets, or
   `ta/apply-local-uf.sh` for local UF targets.

TA apply does not automatically reload deployment server or restart UFs. Use
the rendered handoff scripts and the owning skills after review.

## Validation Notes

`validate.sh` defaults to static checks for whichever rendered directories exist. Use `--check-k8s`, `--check-linux`, or `--check-ta` to force a specific target. Use `--live` only after apply, because it calls Helm, kubectl, systemctl, SSH, or Splunk status checks.

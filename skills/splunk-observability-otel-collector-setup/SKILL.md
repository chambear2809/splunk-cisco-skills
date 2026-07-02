---
name: splunk-observability-otel-collector-setup
description: Use when rendering, preflighting, applying, validating, diagnosing, and removing the Splunk Distribution of OpenTelemetry Collector for Kubernetes and Linux; audit and stage Splunkbase apps 7125, 8698, and 8699 through deployment servers, Linux heavy forwarders, or Linux Universal Forwarders; configure guarded Splunk Platform HEC or Splunk Connect for OTLP destinations; and route specialized Observability products to their owning skills.
---

# Splunk Observability OTel Collector Setup

## Audited baseline

This workflow is pinned and tested against:

- Linux Collector and auto-instrumentation packages `0.154.2`.
- `splunk-otel-collector` Helm chart `0.154.0`, fetched as the exact GitHub
  release archive with SHA-256
  `613f788d786bf741be770512c7c297c4b70d3ab5426ac337b0416209e66bc7b0`.
- Chart-selected Collector and auxiliary images are rewritten to the audited
  manifest digests recorded in `references/sources.md`; unknown custom images
  are accepted only when already pinned with `@sha256:<64 lowercase hex>`.
- Splunkbase apps `7125`, `8698`, and `8699`, version `0.154.2`, published
  June 17, 2026 and rechecked July 2, 2026. App `7125` is the multi-OS/root
  artifact; `8698` and `8699` are the Linux and Windows x86_64 split artifacts.
- Splunk Platform versions explicitly listed for this TA release: `9.0`
  through `10.4`. When the caller supplies `--splunk-version`, a `10.5` value is
  rejected until the package listings certify that train. Omitting
  `--splunk-version` skips that optional compatibility assertion; it allows
  package audit/rendering but does not certify the package for `10.5`.

Treat a newer release as unaudited until `--check-upstream`, the regression
suite, and the source ledger in `references/sources.md` have been updated.
Linux rendering always emits executable apply packets, so Collector,
auto-instrumentation, and OBI versions other than these reviewed pins fail
closed rather than producing an unaudited installer.

The workstation or automation host running `setup.sh`/`render_assets.py`
requires Python 3.9+. Set `PYTHON` to an appropriate executable when the system
default is older. Generated Linux target packets have a separate Python 3.6+
minimum and preflight it before token verification or network access. Generated
Kubernetes packets require Helm `3.9+` or Helm `4` and Python `3.8+`; Helm 4 uses
the rendered local `postrenderer/v1` subprocess plugin.

## What this skill owns

The implemented paths are:

1. Official Kubernetes Helm deployments, including agent, cluster receiver,
   gateway, Windows releases, FIPS image selection, Operator
   auto-instrumentation, OBI, Target Allocator, Kubernetes entities/events,
   container and Linux-node journald collection, Platform HEC or Splunk Connect
   for OTLP log routing, TLS/mTLS file handoff, preflight, rollout checks, and
   uninstall.
2. Official Linux package-repository installer deployments in agent or gateway
   mode, with a pinned installer checksum, local or SSH execution, loopback-safe
   agent defaults, stdin token transport, health checks, doctor output, support
   bundle, and confirmation-gated uninstall.
3. Splunk Add-On for OpenTelemetry Collector (`7125`, `8698`, `8699`) package
   audit and staging for deployment servers, Linux heavy forwarders, or Linux
   Universal Forwarders, with per-artifact digest pinning, archive hardening,
   no-follow `local/` preservation, atomic replacement, a private
   out-of-app-tree backup, confirmation-gated backup retention, ownership
   preservation, and dashboard/no-dashboard evidence. Windows-only `8699`
   uses deployment-server and Agent Management delivery because local apply
   assets are Bash/Python.
4. Collector-side custom configuration through a reviewed Linux
   `--collector-config` or guarded Helm `--extra-values-file`. The skill does not
   pretend that an opaque overlay is a fully typed pipeline authoring model.

Native Splunk Observability Metrics Pipeline Management is owned by
`splunk-observability-metrics-pipeline-setup`; it is downstream aggregation and
routing, not collector pre-ingest processing.

## Product routing

Installing a Collector is not the same as proving a product is ready. Route and
validate each requested product explicitly:

| Product or signal | Base-skill responsibility | Required completion evidence |
|---|---|---|
| Infrastructure Monitoring | Host/Kubernetes metrics, metadata, internal health | Collector healthy and host/cluster visible in Observability |
| APM | OTLP trace receiver/export, optional gateway | Instrumented workload plus a trace visible in APM |
| AlwaysOn Profiling | Explicit opt-in and supported language agent | Profile data visible for the intended service |
| Secure Application | Chart destination only; workload instrumentation still required | Supported workload annotated/instrumented and security trace visible |
| Kubernetes container/journald/extra-file logs | Separate typed Platform pipeline plus HEC `/services/collector/event` or Splunk Connect for OTLP | Target index receives expected source types and fields; source scope is reviewed |
| Kubernetes events/entities | Explicit experimental gates | Event/entity visible; maturity warning recorded |
| Fleet Management / OpAMP | TA feature-gate handoff only | Account entitlement and managed Collector visible in Fleet Management |
| Kubernetes zero-code instrumentation | Delegate to `splunk-observability-k8s-auto-instrumentation-setup` | Child-skill workload rollout and trace evidence |
| Database Monitoring | Delegate to `splunk-observability-database-monitoring-setup` | DBMon receiver and UI evidence |
| AI Agent / AI Infrastructure Monitoring | Delegate to `splunk-observability-ai-agent-monitoring-setup` | Instrumented AI workload, evaluation/metric evidence |
| AI Security Monitoring | Delegate Cisco AI Defense instrumentation to `splunk-observability-ai-agent-monitoring-setup` | Security span correlation, licensed integration, and risk UI evidence |
| Browser RUM / Session Replay | Delegate general setup to `splunk-observability-browser-rum-setup`; use `splunk-observability-k8s-frontend-rum-setup` only for Kubernetes frontend injection | Browser beacon and UI evidence |
| Mobile RUM | Delegate to `splunk-observability-mobile-rum-setup`; mobile beacons bypass this Collector | Mobile session/beacon and UI evidence |
| Synthetics | Delegate to `splunk-observability-synthetics-setup` | Test run, result, and detector evidence |
| SLOs | Delegate to `splunk-observability-slo-setup` | SLI data, SLO calculation, and alert evidence |
| Dashboards and detectors | Delegate to `splunk-observability-dashboard-builder` and `splunk-observability-native-ops` | Dashboard population and detector state |
| DXA, AI Assistant, Observability Mobile, Related Content, and deep product UI | Delegate to `splunk-observability-deep-native-workflows` | Product-specific navigation and populated UI evidence |
| SignalFlow and data tools | Delegate native operations to `splunk-observability-native-ops` / `splunk-observability-deep-native-workflows` | Executed analytics or metadata workflow evidence |
| ITSI / ITE Work / App for Content Packs | Separate Splunk Platform workflows: `splunk-itsi-setup` and `splunk-itsi-config` | Platform app/content-pack and ITSI object evidence |
| Metrics Pipeline Management | Delegate to `splunk-observability-metrics-pipeline-setup` | Rule-set and post-rule metric evidence |
| AWS Lambda APM | Delegate to `splunk-observability-aws-lambda-apm-setup` | Instrumented invocation and trace evidence |
| Coding agents | Delegate to `splunk-observability-coding-agent-instrumentation-setup` | Agent telemetry at every requested destination |
| ThousandEyes | Delegate to `splunk-observability-thousandeyes-integration` | Linked test/metric and dashboard evidence |
| Splunk Connect for OTLP | Delegate receiver-side setup to `splunk-connect-for-otlp-setup` | OTLP receiver health and target-index evidence |
| Network Explorer | `--enable-network-explorer` enforces the supported one-replica gateway profile and renders the separate upstream eBPF-chart handoff | eBPF DaemonSet, representative `tcp.*`/`udp.*`/`dns.*`/`http.*` metrics, and populated Network Explorer UI evidence |

See `references/coverage.md` for deployment-method and feature classification.

## Non-negotiable safety rules

- Never request or render a token value. Accept only paths to token files.
- Reject direct and `--flag=value` token arguments without echoing their value.
- Token and private-key files must be single-link, non-symlink regular files,
  nonempty, mode `600`, and contain no NUL, newline, or whitespace. Tokens are
  capped at 16 KiB and use only the environment/config-safe
  `A-Za-z0-9._~+/=-` alphabet, which includes the documented base64 token
  characters. Linux reads one no-follow descriptor into memory and never
  rereads the source path or creates a temporary token file.
- Rendered base values and copied overlays are integrity-bound. The only mutable
  values overlay is a schema-constrained Secret revision annotation.
- Generated files, including root `metadata.json`, are published through
  same-directory atomic replacement and refuse an existing final-component
  symlink. A render never follows that symlink into an arbitrary target.
- Existing Kubernetes Secrets and PriorityClasses are mutated or deleted only
  when exact skill/release/namespace ownership annotations match. Create uses
  an atomic create, updates use UID/resourceVersion-bound replace, and deletes
  use UID/resourceVersion preconditions so a concurrent replacement cannot be
  adopted or removed. Secret and PriorityClass cleanup each require a separate
  confirmation variable.
- Keep `secret.create=false`; create the Kubernetes Secret from files. Guarded
  extra values may not override secret creation or contain inline secret keys.
- Pin the chart, Collector, Linux installer URL, and Linux installer SHA-256.
  A Linux installer mirror may change the HTTPS URL, but executable packets
  still require the exact audited digest; no arbitrary digest override exists.
- Download the chart archive once into the packet cache, verify it before every
  use, and pass that same local archive to preflight and install. The
  integrity-bound post-renderer must replace every audited mutable image with
  its digest, reject unknown tags/digests in audited repositories, and reject
  any unpinned custom image. Status rechecks live workload, Instrumentation,
  and pod specs so an admission-time image rewrite fails validation.
- Before Helm preflight, install, status, or uninstall, inspect the exact-name
  release across all common Helm 3/4 statuses and require the rendered
  namespace plus a `splunk-otel-collector-*` chart identity. Installation
  accepts only an absent or deployed owned release; uninstall accepts only an
  owned deployed/failed release. Never replace or delete a foreign same-name
  chart.
- When the chart installation Job owns the Instrumentation CR, refuse foreign
  ownership, snapshot an existing owned CR and Helm revision before mutation,
  and require the post-install revision to be exactly the expected successor.
  If ownership validation fails, roll an existing release back to the captured
  revision or uninstall a new release, then restore the CR. A concurrent Helm
  revision refuses automatic rollback and retains the recovery snapshot.
  Repeat ownership checks before status or post-Helm-uninstall cleanup.
- The audited installation Job uses kubectl `v1.35.1`, so its executable
  compatibility gate covers Kubernetes server minors `1.34` through `1.36`.
  Outside that range, audit and pin a matching image in a future skill update.
  Disabling the Job selects upstream resource mode; Helm 4 first install is
  rejected and must use the upstream two-step operator/webhook-ready handoff.
- The Linux agent binds to `127.0.0.1` unless the operator explicitly chooses a
  broader interface. Gateway mode uses the upstream `0.0.0.0` default.
- Do not generate removed `--trace-url` or deprecated `--hec-url` installer
  flags. The tagged installer exposes native-host Platform flags, but its token
  option is argv-based; this workflow refuses to put a HEC token on argv and
  routes native-host Platform data through a reviewed custom config or UF/TA
  handoff.
- SSH install streams the token over stdin and never copies it to a remote file.
- Linux local/SSH preflight requires Bash, curl, Python 3.6+, tar, a SHA-256
  tool, active systemd, the pinned installer's system-account utilities, the
  matching `apt-get`, `yum`/`dnf`, or `zypper` package tools, and root or
  passwordless noninteractive sudo. It enforces the tagged installer's exact
  distro/version and `amd64`/`arm64` matrix. OBI additionally requires
  `sha256sum` and `gzip` to already exist so preflight never installs a package.
  It rejects an existing install and proves custom-config
  traversal/readability before package mutation.
- Linux OBI install and status re-hash the extracted `v0.6.0` executable
  against the independently audited `amd64` or `arm64` binary digest after the
  upstream release-archive checksum succeeds.
- Linux status, doctor, and support-bundle helpers hash-verify the generated
  redactor and fail closed when privileged collection or redaction fails.
  Doctor results distinguish complete/healthy (`0`), complete/unhealthy (`1`),
  and diagnostics-incomplete (`2`) with a matching final completion marker.
  Support bundles publish complete evidence for both healthy and unhealthy
  results, but refuse incomplete or marker-mismatched diagnostics. Bundles
  record `diagnostic-state.txt`, use a private staging directory, mode `600`,
  atomic no-replace publication, and reject existing or symlink output paths.
- Linux uninstall requires a second explicit confirmation before allowing the
  upstream uninstaller to remove detected auto-instrumentation, deletes only the
  installer-generated token-bearing environment files, and still requires token
  revocation as a separate operating step.
- `--apply-ta` must not use `placeholder` secret mode. Placeholder templates are
  disabled and render-only.
- TA preflight, staging, local-overlay apply, and backup management require an
  external Python `3.6` or newer interpreter with `os.O_NOFOLLOW` and
  `os.O_DIRECTORY`; preflight proves this before package work begins.
- Splunkbase marks the audited TA artifacts FIPS-incompatible. FedRAMP status
  is not a Splunkbase metadata field; report it as not documented, not as a
  validated false claim.
- `--fips-enabled` selects and verifies the audited Kubernetes FIPS image; it
  does not certify a FedRAMP deployment. Splunk's previously indexed FedRAMP
  draft included hosting, agent, instrumentation, and integration limits, but
  its dedicated public Help URL currently returns `404` and contained
  contradictory authorization wording. Verify the live FedRAMP Marketplace
  package, order/contract, hosting boundary, and supported-feature list with
  Splunk and the compliance owner instead of treating this packet as evidence.
- Do not enable Splunk Platform traces without
  `--accept-experimental-platform-traces`; chart capability and product support
  documentation currently conflict.

## Workflow

1. Determine the target and requested products/signals. Do not use
   `--all-signals` as a substitute for product discovery.
2. Collect only non-secret inputs: realm, topology, cluster/host identity,
   destination endpoints/indexes, and secret-file paths.
3. Render first.
4. Review `metadata.json`, warnings, values/config, package audit, and exact
   apply commands.
5. Run static validation. Use `--check-upstream` when network access is
   available.
6. Apply only after explicit authorization.
7. Run the rendered status/doctor workflow and prove backend telemetry for each
   enabled product. Record `configured`, `instrumented`, `telemetry observed`,
   and `product UI verified` separately.

## Safe defaults

- Kubernetes: metrics and traces on; container logs, journald, profiling, events, discovery,
  Operator auto-instrumentation, OBI, Secure Application, entities, and Target
  Allocator off. Agent and cluster receiver on. Gateway off; when enabled, three
  replicas.
- Linux: agent mode, `512` MiB, loopback bind, no discovery, no
  auto-instrumentation, no profiling, no SDK metric/log exporter overrides, and
  no OBI.
- TA: render only, deployment-server target, agent mode, placeholder secret
  mode, official digest required for actionable output, and a no-match
  server-class whitelist until the operator supplies a reviewed client filter.

## Render examples

Kubernetes:

```bash
bash skills/splunk-observability-otel-collector-setup/scripts/setup.sh \
  --render-k8s \
  --realm us0 \
  --cluster-name production-cluster \
  --chart-version 0.154.0 \
  --o11y-token-file /secure/splunk_o11y_token
```

Kubernetes logs through HEC:

```bash
bash skills/splunk-observability-otel-collector-setup/scripts/setup.sh \
  --render-k8s \
  --realm us0 \
  --cluster-name production-cluster \
  --enable-logs \
  --platform-hec-url https://splunk.example.com:8088/services/collector/event \
  --platform-hec-index k8s_logs \
  --platform-hec-token-file /secure/splunk_hec_token \
  --o11y-token-file /secure/splunk_o11y_token
```

Platform-only Kubernetes logs through Splunk Connect for OTLP:

```bash
bash skills/splunk-observability-otel-collector-setup/scripts/setup.sh \
  --render-k8s \
  --cluster-name production-cluster \
  --disable-metrics --disable-traces \
  --enable-logs \
  --platform-otlp-endpoint splunk-otlp.example.com:4317
```

Linux:

```bash
bash skills/splunk-observability-otel-collector-setup/scripts/setup.sh \
  --render-linux \
  --realm us0 \
  --o11y-token-file /secure/splunk_o11y_token
```

TA package audit (use the matching 7125/8698/8699 filename):

```bash
bash skills/splunk-observability-otel-collector-setup/scripts/setup.sh \
  --render-ta \
  --realm us0 \
  --ta-package-path ./splunk-add-on-for-opentelemetry-collector_01542.tgz \
  --ta-target deployment-server \
  --ta-serverclass-whitelist 'otel-uf-*'
```

`template.example` is a manual intake worksheet, not an executable spec. Map
reviewed values to CLI flags; never assume the setup script reads
`template.local`.

## Validation

```bash
bash skills/splunk-observability-otel-collector-setup/scripts/validate.sh \
  --check-k8s --check-linux --output-dir splunk-observability-otel-rendered

bash skills/splunk-observability-otel-collector-setup/scripts/validate.sh \
  --check-k8s --check-linux --check-upstream \
  --output-dir splunk-observability-otel-rendered
```

## TA Completion Gate

For TA/add-on work, also follow
[`../shared/ta_completion_gate.md`](../shared/ta_completion_gate.md). The
data ingest path must be configured and validated. Discover any
pre-built/package-shipped dashboards, then prove they are visible,
macro-aligned, and returning data. If the package ships no dashboards, record
that explicit package evidence. The currently audited TA source/package family
records no shipped `data/ui/views`; completion therefore depends on `_internal`
diagnostics and Observability/Platform telemetry rather than a nonexistent
packaged dashboard.

Read `reference.md` for the option contract, lifecycle behavior, known product
documentation conflicts, and explicit handoffs.

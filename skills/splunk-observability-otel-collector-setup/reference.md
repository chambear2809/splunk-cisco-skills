# Splunk Observability OTel Collector Reference

## Release contract

| Artifact | Audited version | Supply-chain control |
|---|---:|---|
| Linux Splunk Distribution of OpenTelemetry Collector | `0.154.2` | Installer package version pinned |
| Linux Splunk OTel auto-instrumentation | `0.154.2` | Explicit installer argument; empty and `latest` are rejected |
| Linux-host standalone OBI binary | `v0.6.0` | Exact version; upstream archive checksum plus audited architecture-specific extracted-binary SHA-256; runtime remains a handoff |
| Linux installer | `v0.154.2` tagged script | HTTPS plus SHA-256 `16f2c34ad1a91bf0817f5675eca3d705af5385377e87fda23537808efd5f7e29` |
| Kubernetes Helm chart | `0.154.0` | Exact release archive SHA-256; one verified local cache is reused by preflight and install |
| Kubernetes chart images | chart `0.154.0` image set | Helm post-renderer rewrites the audited image map to manifest digests; unknown custom images must already use `@sha256` |
| Splunkbase apps `7125`, `8698`, and `8699` | `0.154.2` | Artifact-specific filename, app root, SHA-256, OS, and Cloud-compatibility audit |

The executable tagged installer and chart schema are authoritative for emitted
flags/values. Product-support claims use the stricter current product
documentation when the chart and Help disagree.
An alternate HTTPS mirror URL may be used for the Linux installer only when it
serves the exact bytes identified by the audited SHA-256 above. A different
operator-supplied digest is rejected and cannot create an executable packet.

## Rendered layout

`k8s/` contains:

- `values.yaml`: guarded chart values with no secret values.
- `fetch-chart.sh`: downloads the official `0.154.0` release archive with
  HTTPS/TLS restrictions, verifies its fixed SHA-256, and reuses only that
  non-symlink cached file. Helm never resolves this packet through a repository.
- `k8s-image-post-renderer.py` and
  `helm-plugins/splunk-audited-image-pin/`: one image policy for Helm 3's
  executable post-renderer and Helm 4's local `postrenderer/v1` subprocess
  plugin. Helm `3.9+` or `4` and Python `3.8+` are required.
- `verify-supply-chain.sh`: integrity-checks the chart fetcher, post-renderer,
  Helm 4 plugin, redactor, overlay/Secret validators, and ownership helpers
  before create, preflight, install, status, or uninstall phases that use them.
- `helm-release-guard.py`: parses bounded `helm list --output json`, then
  validates current `helm get all --template` metadata so the release name,
  namespace, revision, status, and chart metadata name are unambiguous. It
  rejects unsafe states and enforces an expected revision during automatic
  rollback. The query uses explicit status flags common to Helm 3 and Helm 4;
  it does not use Helm 3-only `helm list --all` or expose release values.
- `verify-overlays.sh`: checks the rendered base-values digest and immutable
  copied-overlay digests before template or apply; it also validates the exact
  schema of the mutable Secret-revision annotation overlay.
- `preflight.sh`: tool check, same-name Helm release ownership/state check,
  pinned `helm template`, cluster connectivity, authorization, external-secret
  RBAC, and enabled-feature prerequisites.
- `validate-secrets.sh`: validates every required token, certificate, and key
  before the first Kubernetes mutation.
- `priority-class.sh` and `cleanup-priority-class.sh`: optional cluster-scoped
  PriorityClass atomic create/resource-version-bound update and
  confirmation-gated UID/resourceVersion-bound cleanup.
- `create-secret.sh`: creates or rotates the retained external Secret from
  validated private snapshots, refuses to adopt a Secret without exact
  skill/release/namespace ownership, uses create-or-conditional-replace rather
  than an adoption-prone apply, and emits a Secret-revision values overlay.
- `cleanup-secret.sh`: separately confirmation-gated cleanup that deletes only
  the exact owned Secret through UID/resourceVersion API preconditions after
  printing the active Kubernetes context.
- `helm-install.sh`: atomic, waiting, timeout-bound Helm upgrade/install. When
  the chart Job manages Instrumentation, it captures the exact owned prestate
  and prior Helm revision. A failed post-install ownership check rolls back only
  the exact expected successor revision (or uninstalls revision 1), then restores
  the CR. A concurrent revision fails closed and leaves a mode-600 recovery
  snapshot instead of rolling back another operator's change.
- `status.sh`: exact agent/gateway/cluster-receiver rollout checks, pod readiness,
  optional Operator/Instrumentation/Target Allocator/OBI checks, and a redacted
  recent fatal/export error scan.
- `uninstall.sh`: requires `SPLUNK_OTEL_CONFIRM_K8S_UNINSTALL=yes`, proves the
  target context and owned chart identity, and verifies Instrumentation and
  hook-Job ownership before mutation. It removes the Helm release first, then
  re-reads and conditionally deletes only owned auxiliary leftovers with
  UID/resourceVersion preconditions. A failed Helm uninstall therefore leaves
  those objects intact. The external Secret, operator CRDs, and any separately
  rendered PriorityClass remain retained.
  Use each dedicated confirmation-gated cleanup helper only after proving the
  retained object is no longer needed or shared.

`linux/` contains:

Rendering these assets requires Python 3.9+ on the orchestration host; an
explicit `PYTHON` environment value takes precedence over the repository
virtual environment. The generated target-side assets intentionally use a
separate Python 3.6+ floor for older supported Linux distributions.

- `preflight-local.sh`: exact tagged-installer distro/version and architecture,
  active-systemd, package/system-account command, checksum tool,
  existing-install, Python 3.6+, noninteractive privilege, and custom-config
  readability checks. SSH install runs the same preflight on the remote host
  before token verification, network download, or package mutation.
- `install-local.sh` and `install-ssh.sh`: checksum-verified installer wrappers.
- `status-local.sh` and `status-ssh.sh`: service, recent-error, and configured
  health-endpoint checks.
- `doctor-local.sh` and `doctor-ssh.sh`: complete privileged, read-only
  package/service/listener/config-digest diagnostics through a hash-verified
  Python-3.6-compatible redactor. Exit `0` plus the final
  `SPLUNK_OTEL_DIAGNOSTIC_RESULT=complete_healthy` marker means collection and
  redaction completed with no unhealthy finding. Exit `1` plus
  `complete_unhealthy` means the evidence is complete but the package, service,
  health endpoint, requested OBI binary, config, or recent fatal/error evidence
  is unhealthy. Exit `2` means diagnostics are incomplete; privilege, required
  tool, collection, or redaction failures always take precedence over health
  findings and never emit a complete marker.
- `support-bundle-local.sh` and `support-bundle-ssh.sh`: publish for exact,
  marker-matched doctor results `0` and `1`, so a stopped or missing Collector
  still produces a complete redacted evidence bundle. Any missing/mismatched
  marker, exit `2`, journal collection failure, redactor failure, or archive
  failure refuses publication. Bundles include `diagnostic-state.txt`, use
  private staging, mode-600 output, and atomic no-replace publication. Existing
  files and symlinks are rejected; review every bundle before sharing because
  application data can still be sensitive.
- `uninstall-local.sh` and `uninstall-ssh.sh`: confirmation-gated removal; an
  enabled custom OBI directory is carried into uninstall. A second explicit
  confirmation is required before the upstream uninstaller may remove detected
  auto-instrumentation packages or artifacts.

`ta/` contains package audit/metadata for apps `7125`, `8698`, and `8699`,
disabled or configured inputs templates, digest-pinned preflight, atomic staging
with backup, target-specific status, and an Agent Management handoff. Targets
are a deployment server, a local Linux heavy forwarder, or a local Linux
Universal Forwarder. Existing `local/` configuration is preserved when the
package-owned files are atomically replaced. Preservation accepts real
directories and single-link regular files only; symlinks, hard links, special
files, unsafe backup roots, and concurrent source changes fail closed.
These local Bash workflows use an external `python3`; `preflight-ta.sh` requires
Python 3.6 or newer plus `os.O_NOFOLLOW` and `os.O_DIRECTORY` before inspecting
or staging any package. `manage-backups.py` repeats the runtime capability gate
when invoked independently.

`platform-hec/` delegates HEC token/index work to
`splunk-hec-service-setup`; this skill does not duplicate HEC administration.
Its managed token file lives outside the regenerated helper directory under
`OUTPUT_DIR/.secrets/`, whose directory and token modes are `700` and `600`.

## Kubernetes option model

Core identity/topology:

- `--namespace`, `--release-name`, `--cluster-name`, `--distribution`, and
  `--cloud-provider` map to official chart values.
- `--chart-version` defaults to audited `0.154.0`.
- `--agent-enabled false`, `--disable-cluster-receiver`, and `--gateway` select
  topology. The renderer rejects a zero-workload release.
- Gateway replica default is `3`, matching the chart. Stateful gateway is not a
  chart `0.154.0` feature and is classified as an external/custom deployment.
- `--enable-network-explorer` is the exception to that default: it enables the
  gateway and forces exactly one replica because Network Explorer cannot send
  to multiple gateway replicas. It renders `network-explorer-handoff.md` for
  the separate upstream eBPF chart, which is outside Splunk support coverage.
- EKS Fargate forces the agent off and gateway on; the cluster receiver is a
  StatefulSet. Container log collection is rejected because Fargate has no
  DaemonSet log reader.
- EKS Auto Mode uses host networking for IMDS-backed resource detection. A
  gateway requires EKS Pod Identity, and disabling agent or cluster-receiver
  host networking also requires Pod Identity for the EKS detector.
- Windows nodes normally use the tagged chart's Windows repository. With
  `--fips-enabled`, the tagged FIPS repository takes precedence and supplies a
  Windows `amd64` image as well as Linux `amd64`/`arm64` images. A Windows
  release must remain separate when a Linux release owns the cluster receiver.

Observability signals:

- Metrics and traces default on.
- Profiling, Secure Application, discovery, auto-instrumentation, OBI, events,
  Kubernetes entities, and entity-event property updates are explicit opt-ins.
- Events, entities, Operator auto-instrumentation, and OBI retain their upstream
  maturity/privilege warnings. Product UI readiness still requires workload
  instrumentation and observed telemetry.
- Chart `0.154.0` requires every Splunk Observability destination to enable at
  least one of metrics, traces, profiling, or Secure Application. Kubernetes
  events, object collection, and entity emission are secondary features, not
  standalone Observability destinations. Events and objects may instead use a
  Platform-only release when the Platform logs pipeline is enabled.
- `--enable-certmanager` means use an existing cert-manager installation. The
  deprecated bundled subchart stays off; preflight requires certificate and
  issuer CRDs. Without it, the Operator's chart-managed certificate is used.
- Auto-instrumentation uses `instrumentation.installationJob.enabled=true` by
  default to avoid the Helm v4 first-install webhook/CR race. Preflight refuses
  to adopt a colliding Instrumentation CR unless its Helm release name,
  namespace, managed-by label, and instance label all match. Install snapshots
  owned prestate for rollback; uninstall repeats the check before deletion.
  The audited kubectl `v1.35.1` Job image is accepted only with Kubernetes
  server minors `1.34`-`1.36`. With the Job explicitly disabled, Helm 3 resource
  mode remains available for review, while a Helm 4 first install fails closed
  and points to the upstream two-step operator/webhook-readiness workflow.
- Target Allocator requires the agent metrics pipeline and existing
  `ServiceMonitor` and `PodMonitor` CRDs; status verifies its exact Deployment.
- Kubernetes OBI requires the Linux agent DaemonSet with host networking,
  Kubernetes 1.24 or newer, `amd64` or `arm64`, and kernel 5.8+ (or a supported
  RHEL-family 4.18+ kernel) on every Linux node it can schedule onto. It is
  rejected on EKS Fargate and GKE Autopilot. OpenShift OBI/SCC work is delegated
  to `splunk-observability-k8s-auto-instrumentation-setup`.
- The Kubernetes FIPS image cannot be combined with discovery/Smart Agent
  receivers or OBI. Windows mode also rejects discovery, OBI, and ownership of
  Operator auto-instrumentation.

Splunk Platform destinations:

- `--platform-logs-enabled` enables the Platform export pipeline independently
  of a built-in source. Use it for cluster-receiver events/objects or a reviewed
  `logsCollection.extraFileLogs` overlay. It does not enable the agent,
  container file collection, or journald by itself.
- `--enable-logs` remains the typed Kubernetes container-log source (and the
  Linux SDK-log intent); it also requests the Platform logs pipeline. Direct
  HEC export requires an endpoint ending in `/services/collector/event`, a
  target event index, and a file-backed HEC token or rendered HEC helper.
- Splunk Connect for OTLP logs require `--platform-logs-enabled`,
  `--enable-logs`, or `--enable-journald` and `--platform-otlp-endpoint`;
  configure the receiver with
  `splunk-connect-for-otlp-setup` first.
- Linux-node journald collection is a separate `--enable-journald` opt-in. It
  requires an effective Linux agent DaemonSet and the same Platform HEC or OTLP
  log destination. It is rejected for Windows, EKS Fargate, GKE Autopilot, and
  agent-disabled topologies. Journal directory, unit selection, host
  `journalctl` mounts, and optional index remain reviewed extra-values fields.
- Platform metrics require an HEC URL/token and `--platform-metrics-index` plus
  `--platform-metrics-enabled`.
- Platform traces fail closed unless all destination values and
  `--accept-experimental-platform-traces` are present. This records the current
  chart/product-documentation conflict rather than claiming support. Chart
  `0.154.0` also rejects a traces-only Platform destination, so a reviewed
  Platform metrics or logs pipeline must be enabled in the same release.
- HEC and OTLP client certificate/private-key files must be paired. Every PEM
  certificate in a CA bundle is parsed and checked for expiry, client
  certificate expiry is checked, and certificate/private-key public keys must
  match. Validation is repeated against the exact private snapshots loaded into
  the external Secret; key files must be mode `600`. Certificates expiring
  within 30 days produce a warning, while expired material fails closed.
- `--platform-otlp-insecure true` is an explicit plaintext opt-in. HTTP endpoints
  require an `http://` or `https://` URL; gRPC endpoints require `HOST:PORT`.
- Persistent queue and fsync settings are available for the Platform exporter
  only with Platform logs on a non-Autopilot Linux agent DaemonSet when the
  gateway is disabled. Chart `0.154.0` does not mount or wire persistent queue
  storage into the gateway; the operator remains responsible for storage sizing
  and lifecycle.

The rendered `values.yaml` and extra Helm overlays are content-hashed. Extra
overlays are copied into the render output and parsed as YAML/JSON; apply verifies
the immutable snapshots rather than trusting original source paths. Rerender to
change these files. Only `secret-revision-values.yaml` may change in place, and
its validator accepts exactly the three Collector pod-annotation maps with one
identical, format-constrained revision value. Inline token/password/private-key fields,
secret-like command arguments, unsafe environment references, and
`secret.create=true` are rejected, including flow-style YAML and aliases
resolved by the parser. The pinned upstream Helm template remains the final
schema gate.

Within `splunkPlatform`, reviewed overlays may tune official non-sensitive
exporter fields such as source/sourcetype conventions, connection and timeout
settings, retry policy, field-name conventions, and the in-memory sending queue.
Destination endpoint/token/indexes, signal gates, TLS/OTLP settings, persistent
queue/fsync settings, and all renderer-owned topology fields remain protected.
The deprecated `splunkObservability.infrastructureMonitoringEventsEnabled`
toggle is also protected; use typed `--enable-events` and current correlated
event routing instead.

All token and private-key inputs must be readable, nonempty, single-link,
non-symlink regular files with mode `600`. Token files are capped at 16 KiB and
may not contain NUL, newline, or whitespace; TLS files are capped at 4 MiB.
Tokens are restricted to the
environment/config-safe alphabet `A-Z`, `a-z`, `0-9`, `.`, `_`, `~`, `+`, `/`,
`=`, and `-`, covering Splunk's documented base64 access tokens while excluding
quotes, backslashes, whitespace, and line breaks that could alter persisted
configuration syntax.
Linux wrappers load the token once through an `O_NOFOLLOW` descriptor, verify
the single-link/type/mode/size/alphabet contract on that descriptor, and retain
only an in-memory shell snapshot for verification and installer stdin. They do
not reread the source path or create a temporary token file.
Kubernetes Secrets are always externally created from securely opened private
snapshots and are retained on Helm uninstall. Create/rotate refuses an existing
Secret without exact ownership annotations. Cleanup requires
`SPLUNK_OTEL_CONFIRM_SECRET_DELETE=yes` and repeats the ownership check. No
command-line token-value option or permission bypass exists.

## Linux option model

Defaults match the current installer rather than the historical skill defaults:

- Agent receiver bind: `127.0.0.1`; gateway bind: `0.0.0.0`.
- Discovery, preload/systemd auto-instrumentation, instrumentation metrics,
  SDK log export, AlwaysOn Profiling, memory profiling, and OBI are off.
- Deployment environment and service name are unset.
- Before package mutation, the wrapper performs the pinned installer's exact
  token-verification request and requires HTTP `200`. It disables user curl
  configuration, streams a curl config through stdin so the token is absent
  from argv and temporary files, and then narrowly disables only the
  installer's duplicate argv-unsafe verification.

`--enable-metrics`, `--enable-logs`, `--enable-profiling` (CPU), and
`--enable-memory-profiling` affect activated auto-instrumentation SDK settings
only on Linux; CPU and memory profiling are independently selectable. The upstream agent and gateway
configs already contain traces, metrics, and logs pipelines; these switches do
not remove them. Therefore `--disable-metrics` or `--disable-traces` is
rejected for the upstream default config and requires an explicit reviewed
`--collector-config`. Auto-instrumented traces cannot be disabled independently
even with a custom Collector config because the installer has no SDK switch.
Rendered metadata distinguishes requested product scope, upstream default
pipelines, and SDK controls instead of claiming that one flag controls all
three layers.

Supported installer controls include package version/repository channel,
service user/group, memory, mode/listen interface, Observability API/ingest URL,
custom collector configuration, instrumentation mode/SDK/version, SDK OTLP
endpoint/protocol, SDK metric/log exporters, GODEBUG, and OBI.

- Linux Collector and Linux auto-instrumentation are independently restricted
  to the audited `0.154.2` executable pin. Auto-instrumentation requires
  `preload` or `systemd`; an empty, moving, or different exact version is
  rejected. OBI is likewise restricted to audited `v0.6.0` (the equivalent
  `0.6.0` spelling is accepted). Upgrade or downgrade planning uses the
  package-manager/upstream handoff until the source ledger, checksums, and
  regression suite have been reviewed for a new release.
- Repository channels are `primary` and `beta`; the upstream `test` channel is
  rejected because that path disables package-signature verification.
- A custom `--collector-config` requires an explicit credential-free
  `--linux-health-endpoint`, because the custom config can move or disable the
  default `http://127.0.0.1:13133/` health extension. Target preflight rejects
  symlinked/hard-linked paths and validates projected service-user read and
  parent-directory traversal before mutation. Local and SSH status and doctor
  helpers use the effective endpoint.
- Local and SSH apply require Bash, curl, Python 3.6+, tar, a SHA-256 tool, and
  root or passwordless noninteractive sudo. Before token verification or
  download, preflight enforces the tagged installer's supported Ubuntu, Debian,
  Amazon Linux, SLES/openSUSE, CentOS, Oracle Linux, RHEL, and Rocky Linux
  releases; `amd64`/`x86_64` or `arm64`/`aarch64`; active systemd; its
  system-account tools; and the distro's `apt-get`, `yum`/`dnf`, or `zypper`
  path. OBI requires `sha256sum` and `gzip` specifically; both must exist before
  apply so upstream preflight cannot install `gzip` implicitly. Protected
  custom configs are inspected through passwordless sudo with no-follow file
  descriptors, then checked against the projected service-user access model.
  Status, doctor, and support bundles use the same privilege contract so
  journal and service visibility are complete rather than best-effort.
- SSH install, status, doctor, support-bundle, and uninstall helpers validate
  host, user, port, optional mode-600 key, and remote temporary paths. Install
  streams the access token over stdin and does not copy it to the remote host.
- Native Linux OBI uses the verified `0.154.2` installer to download and
  checksum an exact standalone binary; empty input resolves to the audited
  `v0.6.0`, while ranges and moving tags are rejected. The installer does not
  configure or run an OBI service, so configuration, privileges, startup, and
  telemetry validation remain a runtime handoff. An optional install directory
  is passed to both install and confirmation-gated uninstall.

Removed/deprecated controls:

- `--trace-url` is not accepted by installer `0.154.2` and is rejected.
- `--hec-url` is deprecated upstream with announced removal in September 2026
  and is rejected. Use a reviewed custom Collector config for Observability log
  endpoint overrides.
- Native-host Splunk Platform output flags exist in the installer while current
  product documentation still recommends Universal Forwarder and describes the
  path inconsistently. This skill routes it to a reviewed custom config or UF
  workflow rather than silently enabling it.

The official installer persists the access token in the protected Collector
environment file under `/etc/otel/collector`; file-backed input protects
transport and render output, not installed-state storage. Secure the directory,
encrypt the host volume where required, and include token rotation in operations.
The rendered uninstall wrapper removes the installer-generated
`splunk-otel-collector.conf` and legacy `splunk_env` files after a successful
package uninstall, but it cannot revoke a token already issued by Splunk.

The verified installer is a fresh-install path: its `ensure_not_installed()`
guard refuses an existing Collector. Package-manager upgrade/downgrade and
configuration migration remain a reviewed handoff; this skill does not claim
that rerunning `install-local.sh` or `install-ssh.sh` performs an upgrade.

## TA `7125` / `8698` / `8699` contract

Current audited metadata, rechecked July 2, 2026:

- Version `0.154.2`, June 17, 2026.
- Exact listed Splunk versions `9.0` through `10.4`. If
  `--splunk-version 10.5` is supplied, the renderer rejects it until apps
  `7125`, `8698`, and `8699` list that train. When `--splunk-version` is
  omitted, the renderer does not run the optional platform compatibility
  assertion; successful package audit/rendering is not evidence of `10.5`
  support.
- App `7125`, root `Splunk_TA_otel`: multi-OS package, Splunk Cloud compatible.
- App `8698`, root `Splunk_TA_otel_linux_x86_64`: Linux `x86_64` package,
  Splunk Cloud compatibility metadata false.
- App `8699`, root `Splunk_TA_otel_windows_x86_64`: Windows `x86_64` package,
  Splunk Cloud compatibility metadata false.
- The audited TA contract reports FIPS compatibility false.
- FedRAMP package status: not documented by Splunkbase metadata.
- Audited packages have no `data/ui/views` content; each package audit records
  explicit no-dashboard evidence.

The package audit rejects path traversal, absolute paths, links/special files,
duplicate members, multiple app roots, unexpected top-level content, missing
required files/binaries, excessive member count, single-file size, or expanded
size. It records archive SHA-256, size, member count, app version, OS flavor,
config/binary presence, token field style, modular-input stanza, and dashboard
inventory.

Preflight and staging recheck the render-time digest and required contract. The
package is extracted into a private same-filesystem staging directory; an
existing app is backed up, its `local/` directory is preserved, and the new app
is atomically renamed into place. Source traversal, backup creation, ownership
updates, replacement, and rollback use no-follow directory handles rather than
path-following recursion. A failed replacement restores the backup before
returning an error.

Package hashing, archive inspection, and extraction share one no-follow file
descriptor and verify the inode metadata again after extraction. Generated
inputs and gateway overlays are SHA-256-bound into their apply scripts and are
reopened without following links. `inventory-backups.sh` reports retained
copies, sizes, link/special-file counts, and possible secret files without
reading their contents. `prune-backups.sh` requires
`SPLUNK_OTEL_CONFIRM_BACKUP_PRUNE=yes` and retains three newest copies per TA
app root by default; override the count with
`SPLUNK_OTEL_TA_BACKUP_RETAIN=0..1000`. Because backups can retain historical
tokens, rotate superseded credentials and prune only after rollout validation.

Secret modes:

- `placeholder`: render-only, disabled stanza, apply rejected.
- `inputs-conf`: apply requires explicit acceptance and a validated token file;
  resulting `inputs.conf` is mode `600`.
- `legacy-file`: only for a package whose spec uses the legacy token-file field.
- `environment`: requires `SPLUNK_ACCESS_TOKEN` in the Splunk service
  environment; a one-shot shell variable is not sufficient for a restart.

All three audited packages ship Collector configs with metrics, traces, and
logs pipelines. Explicit signal enables are recorded as intent; explicit
`--disable-metrics`, `--disable-traces`, or `--disable-logs` fails closed
because the TA renderer cannot truthfully remove those packaged pipelines.

Agent-to-gateway mode uses TLS with system trust, memory limiting, resource
detection, batching, and health check. The endpoint must be `HOST:PORT`; an
insecure generated gateway transport is intentionally unavailable.

The Agent Management handoff sets `restartSplunkd=true`, applies OS machine
filters to platform-specific packages, and defaults to a no-match whitelist.
Supply `--ta-serverclass-whitelist` only after reviewing fleet scope.

A deployment server may stage multiple non-overlapping OS packages. Local
heavy-forwarder or Universal-Forwarder apply accepts exactly one Linux-capable
package; Windows-only `8699` is routed through a deployment server and Agent
Management. Local HF staging defaults to `/opt/splunk/etc/apps`; local UF
staging defaults to `/opt/splunkforwarder/etc/apps`. Actionable rendering
requires an exact audited digest unless `--accept-unaudited-ta-package` is
explicitly accepted after structural audit.

## Apply sequence and rollback

Kubernetes apply:

1. Optional EKS kubeconfig helper.
2. Local/chart/cluster preflight.
3. Local token/certificate/key validation.
4. Optional PriorityClass.
5. External Secret creation or rotation.
6. Atomic, waiting Helm upgrade/install.
7. Exact rollout/status checks.

Helm `--atomic` rolls back a failed Helm command. For the installation-Job path,
the wrapper also captures the prior deployed revision; if Helm succeeds but the
subsequent Instrumentation ownership check fails, it compare-and-swaps against
the expected next revision before rolling back/uninstalling and restoring the
CR. A foreign chart, unsafe prior status, or concurrent revision fails closed.
Back up reviewed values and read the chart `UPGRADING.md` before upgrades. Helm
does not own CRD upgrade or deletion; handle CRDs as a separate reviewed
lifecycle action.

Linux apply performs a fresh install through the verified installer and then
runs service/health status. An existing installation fails closed. Capture
package/config state and use the distribution package manager plus the upstream
upgrade guide for a reviewed upgrade/downgrade handoff. Uninstall is
confirmation-gated. If Splunk auto-instrumentation is present, the upstream
uninstaller removes it too, so the rendered wrapper fails unless
`SPLUNK_OTEL_CONFIRM_REMOVE_AUTO_INSTRUMENTATION=yes` is supplied as a second
confirmation. The local and SSH wrappers remove installer-generated
token-bearing Collector environment files after successful uninstall; revoke
the backend token separately. Uninstall does not prove that downstream telemetry
or separately managed application instrumentation has been removed.

TA apply audits, stages atomically, applies the local overlay, and runs the
target-specific status check. Deployment-server distribution, client restart,
and per-client telemetry validation remain explicit Agent Management / runtime
completion steps; local HF and UF service restarts follow their normal change
workflows.

## Success criteria

Static success means syntax, YAML parsing, secret invariants, package audit, and
pinned upstream schema/installer contracts pass. Runtime success additionally
requires:

- Every enabled Collector workload is ready.
- Health endpoint responds and recent logs have no fatal/permanent export error.
- Each requested signal reaches its intended backend/index.
- Workload instrumentation is verified separately from destination setup.
- Each requested product UI is checked, not inferred.
- TA dashboard evidence is recorded; where no dashboard ships, `_internal` and
  backend telemetry evidence replace the dashboard check.

Use `validate.sh --check-upstream` for the networked artifact contract and
`validate.sh --live` only after a reviewed apply.

## Known official-source conflicts

- The chart exposes Platform trace values while current product support text is
  stricter; the skill fails closed by default.
- The Linux installer exposes native-host Platform flags while main product
  guidance still points to Universal Forwarder; the skill uses the stricter
  support interpretation.
- Windows mode normally selects the dedicated Windows repository. The audited
  `0.154.0` FIPS manifest also contains Windows `amd64`, so FIPS mode correctly
  selects the FIPS repository for Windows instead of the normal Windows image.
  This Kubernetes image capability does not make TA apps FIPS-compatible.
- EKS Fargate cluster-name guidance differs between Help and tagged chart paths;
  executable rendering follows the tagged chart schema.
- The previously indexed FedRAMP Help draft contained both broad compliance
  language and wording that authorization was still in process; its dedicated
  public URL returned `404` during this audit. FIPS selection is therefore a
  technical control, never certification. Verify the live Marketplace package,
  order/contract, hosting boundary, and supported features with Splunk and the
  compliance owner.

See `references/sources.md` for the audited primary-source ledger and
`references/coverage.md` for the complete classification matrix.

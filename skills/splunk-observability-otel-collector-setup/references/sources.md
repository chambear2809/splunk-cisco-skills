# Primary-source and version ledger

Last audited: **2026-07-02**.

## Executable release sources

- Collector `0.158.0` release:
  <https://github.com/signalfx/splunk-otel-collector/releases/tag/v0.158.0>
- Tagged Linux installer:
  <https://github.com/signalfx/splunk-otel-collector/blob/v0.158.0/packaging/installer/install.sh>
- Tagged Linux auto-instrumentation source:
  <https://github.com/signalfx/splunk-otel-collector/tree/v0.158.0/instrumentation>
- Audited Linux-host OBI release `v0.6.0`:
  <https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/releases/tag/v0.6.0>
- Tagged Collector component catalog:
  <https://github.com/signalfx/splunk-otel-collector/blob/v0.158.0/docs/components.md>
- Tagged agent configuration:
  <https://github.com/signalfx/splunk-otel-collector/blob/v0.158.0/cmd/otelcol/config/collector/agent_config.yaml>
- Helm chart `0.158.0` release:
  <https://github.com/signalfx/splunk-otel-collector-chart/releases/tag/splunk-otel-collector-0.158.0>
- Exact chart release asset:
  <https://github.com/signalfx/splunk-otel-collector-chart/releases/download/splunk-otel-collector-0.158.0/splunk-otel-collector-0.158.0.tgz>
- GitHub release API record carrying the asset digest:
  <https://api.github.com/repos/signalfx/splunk-otel-collector-chart/releases/tags/splunk-otel-collector-0.158.0>
- Tagged chart values/schema source:
  <https://github.com/signalfx/splunk-otel-collector-chart/blob/splunk-otel-collector-0.158.0/helm-charts/splunk-otel-collector/values.yaml>
- Tagged chart upgrade guide:
  <https://github.com/signalfx/splunk-otel-collector-chart/blob/splunk-otel-collector-0.158.0/UPGRADING.md>
- Tagged auto-instrumentation installation guide:
  <https://github.com/signalfx/splunk-otel-collector-chart/blob/splunk-otel-collector-0.158.0/docs/auto-instrumentation-install.md>
- Operator maturity. Two vendor statements apply at different layers and the
  rendered advisory deliberately states both; `OPERATOR_MATURITY_ADVISORY` is
  duplicated verbatim in
  `splunk-observability-k8s-auto-instrumentation-setup/scripts/render_assets.py`
  because that overlay uses the Operator this chart deploys, and the two skills
  are required to agree.
  - Packaging layer, alpha/experimental. `values.yaml` says Operator-related
    features "should be considered to have an alpha maturity level and be
    experimental. There may be breaking changes or Operator features may be
    replaced entirely with a better alternative in the future." Present
    unchanged in charts 0.152.0 and 0.154.0 (line 993) and 0.158.0 (line 1060).
    Note this notice is in `values.yaml` and *not* in the installation guide
    above, which mentions "alpha" only as the `opentelemetry.io/v1alpha1` CRD
    apiVersion — checking only that guide is what produced the earlier
    incorrect finding that the claim was a `v1alpha1` misreading:
    <https://github.com/signalfx/splunk-otel-collector-chart/blob/splunk-otel-collector-0.158.0/helm-charts/splunk-otel-collector/values.yaml>
  - Chart layer, production tested. The chart README "Current Status" says the
    chart "is production tested; it is in use by a number of customers in their
    production environments" and that customers "can receive direct help from
    official Splunk support within SLA's". Scope this precisely: the statement
    is about the chart, and the adjacent bullet scopes stability to "metrics,
    traces and logs collection", which does not name auto-instrumentation:
    <https://github.com/signalfx/splunk-otel-collector-chart/blob/splunk-otel-collector-0.158.0/README.md>
  - Actionable risk and mitigation. The same README's "Versioning and breaking
    changes" section warns that bundled subcharts "such as the OpenTelemetry
    Operator (and its CRDs)" can on upgrade "change operator behavior or
    injected auto-instrumentation even when your chart values are unchanged",
    and that a minor version bump can contain breaking changes. This is the
    source for the advisory's pin-exactly / review-subchart-notes / diff-
    rendered-manifests guidance:
    <https://github.com/signalfx/splunk-otel-collector-chart/blob/splunk-otel-collector-0.158.0/README.md>
  - Product documentation. Splunk's zero-code Kubernetes page documents the
    capability as a normal supported feature and carries no maturity qualifier
    of any kind, so it is cited as corroborating support status rather than as
    a source for the phrase "production tested". It also records the
    Operator-free alternative the advisory points at, deploying zero-code
    instrumentation per language runtime independently of the Collector:
    <https://help.splunk.com/en/splunk-observability-cloud/manage-data/splunk-distribution-of-the-opentelemetry-collector/get-started-with-the-splunk-distribution-of-the-opentelemetry-collector/automatic-discovery-of-apps-and-services/kubernetes/language-runtimes>
- Tagged OBI guide:
  <https://github.com/signalfx/splunk-otel-collector-chart/blob/splunk-otel-collector-0.158.0/docs/zero-code-ebpf-instrumentation.md>
- FIPS Collector image tag and manifest:
  <https://quay.io/repository/signalfx/splunk-otel-collector-fips?tab=tags&tag=0.158.0>
- Helm 4 post-renderer migration and plugin contract:
  <https://helm.sh/docs/plugins/migrate/>,
  <https://helm.sh/docs/plugins/developer/tutorial-postrenderer-plugin/>
- Helm 3 and Helm 4 release-list state/filter contracts:
  <https://helm.sh/docs/v3/helm/helm_list/>,
  <https://helm.sh/docs/helm/helm_list/>
- Helm 3 and Helm 4 exact release metadata template contract:
  <https://helm.sh/docs/v3/helm/helm_get_all/>,
  <https://helm.sh/docs/helm/helm_get_all/>
- Helm rollback revision, cleanup, wait, and history contracts:
  <https://helm.sh/docs/v3/helm/helm_rollback/>,
  <https://helm.sh/docs/helm/helm_rollback/>
- Amazon Linux 2023 Public ECR image catalog:
  <https://gallery.ecr.aws/amazonlinux/amazonlinux>

## Product documentation

- Current Observability Cloud product/feature overview:
  <https://help.splunk.com/en/splunk-observability-cloud>
- Observability Cloud suite overview:
  <https://help.splunk.com/en/splunk-observability-cloud/get-started/splunk-observability-cloud-overview/splunk-observability-cloud-overview>
- Linux installation:
  <https://help.splunk.com/en/splunk-observability-cloud/manage-data/splunk-distribution-of-the-opentelemetry-collector/get-started-with-the-splunk-distribution-of-the-opentelemetry-collector/collector-for-linux/install-the-collector-for-linux-script>
- Windows MSI installation:
  <https://help.splunk.com/en/splunk-observability-cloud/manage-data/splunk-distribution-of-the-opentelemetry-collector/get-started-with-the-splunk-distribution-of-the-opentelemetry-collector/collector-for-windows/install-the-collector-for-windows-msi>
- Kubernetes installation:
  <https://help.splunk.com/en/splunk-observability-cloud/manage-data/splunk-distribution-of-the-opentelemetry-collector/get-started-with-the-splunk-distribution-of-the-opentelemetry-collector/collector-for-kubernetes>
- Tagged Kubernetes advanced configuration, including EKS Auto Mode and Fargate:
  <https://github.com/signalfx/splunk-otel-collector-chart/blob/splunk-otel-collector-0.158.0/docs/advanced-configuration.md>
- Collector deployment modes:
  <https://help.splunk.com/splunk-observability-cloud/manage-data/splunk-distribution-of-the-opentelemetry-collector/get-started-with-the-splunk-distribution-of-the-opentelemetry-collector/get-started-understand-and-use-the-collector/deployment-modes>
- Other deployment tools (ECS, EC2, Fargate, Nomad, PCF):
  <https://help.splunk.com/en/splunk-observability-cloud/manage-data/splunk-distribution-of-the-opentelemetry-collector/get-started-with-the-splunk-distribution-of-the-opentelemetry-collector/other-deployment-tools-ecs-ec2-fargate-nomad-pcf>
- Security guidelines:
  <https://help.splunk.com/en/splunk-observability-cloud/manage-data/manage-sensitive-data/security-guidelines-permissions-and-dependencies>
- Current operating-system, architecture, language, and runtime compatibility:
  <https://help.splunk.com/en/splunk-observability-cloud/manage-data/compatibility-requirements/compatibility-and-requirements-for-splunk-observability-cloud>
- Public FedRAMP status references (authorization must still be verified for the
  specific order at deployment time):
  <https://www.splunk.com/en_us/blog/industries/splunks-path-towards-achieving-fedramp-moderate-authorization-for-splunk-observability.html>,
  <https://www.fedramp.gov/marketplace/>
- Fleet Management / OpAMP:
  <https://help.splunk.com/en/splunk-observability-cloud/manage-data/manage-otel-agents-and-collectors/manage-opentelemetry-agents-and-collectors/configure-opentelemetry-fleet-management>
- AI Security Monitoring / Cisco AI Defense:
  <https://help.splunk.com/en/splunk-observability-cloud/observability-for-ai/splunk-ai-security-monitoring>
- Network Explorer Kubernetes setup and its one-gateway-replica contract:
  <https://help.splunk.com/splunk-observability-cloud/monitor-infrastructure/network-explorer/set-up-network-explorer-in-kubernetes>
- Network Explorer metric families:
  <https://help.splunk.com/en/splunk-observability-cloud/monitor-infrastructure/network-explorer/network-telemetry-metrics>

## Splunkbase / TA sources

- Splunk Add-On for OpenTelemetry Collector, app `7125`:
  <https://splunkbase.splunk.com/app/7125>
- Splunk Add-On for OpenTelemetry Collector for Linux `x86_64`, app `8698`:
  <https://splunkbase.splunk.com/app/8698>
- Splunk Add-On for OpenTelemetry Collector for Windows `x86_64`, app `8699`:
  <https://splunkbase.splunk.com/app/8699>
- Tagged TA source:
  <https://github.com/signalfx/splunk-otel-collector/tree/v0.158.0/packaging/ta-v2>
- TA installation documentation:
  <https://help.splunk.com/en/splunk-observability-cloud/manage-data/splunk-distribution-of-the-opentelemetry-collector/get-started-with-the-splunk-distribution-of-the-opentelemetry-collector/splunk-add-on-for-opentelemetry-collector/install-the-technical-add-on>

## Audited facts

- Linux installer SHA-256:
  `cea51eefdf12a906e45db06ea0943931903df1328d9779a4dbfa7d17c0bb4b1b`.
- Chart release archive SHA-256:
  `088a93ebbcfbecf8e6f7ef3651747b65bbad443f0823489768bd4901cce0a274`
  (162,326 bytes). The renderer binds the URL, filename, and digest and does
  not combine this local archive with Helm `--version` resolution.
- Audited Collector manifest-list pins are standard Linux
  `sha256:27a458cd6873d6fef7d3d88fe0a266dffe83d5fe222df738f1937593d8c43357`,
  FIPS multi-platform
  `sha256:e60b7721a2be509cd71d6594387d437ce4996dba1804c6ff774fbb4e7ef3ba8d`,
  and Windows
  `sha256:5d1cb3cf0c7608b8ac6f25444c3e23d49096f39e35e466a345025a7f3054952c`.
  Every digest above is resolved independently from the `quay.io` registry for
  the exact repository and tag rather than copied from GitHub release text: the
  `v0.154.0` release notes previously misreported the FIPS digest against the
  standard repository, so release-note lines are not treated as authoritative.
- The chart's mutable Fargate node-discoverer source
  `public.ecr.aws/amazonlinux/amazonlinux:latest` was resolved on 2026-07-02 to
  immutable AL2023 release `2023.12.20260629.0` and manifest-list digest
  `sha256:336b735f8f0aa1d591802beb01d2ef85c6a4a3f411ea4ffa35cad8ba5db282af`;
  its Linux `amd64` and `arm64/v8` child digests are respectively
  `sha256:9874a0629e48491e1da97b2966202f83cd3a7915002bffa42a0bdf88417c755d`
  and `sha256:eda490c9c952ae0cf099a44e749d43e3ea50e89481fa4ab4f99fc297a2c50aa2`.
- The remaining chart sources are allowlisted and rewritten as follows:
  UBI9 `sha256:8bf0e8f20737e9c8a68c8a498299e9504ab397b1b1f2837acb2fef12ec698f0e`,
  BusyBox `sha256:fd8d9aa63ba2f0982b5304e1ee8d3b90a210bc1ffb5314d980eb6962f1a9715d`,
  OTel Operator `sha256:e6f4503cade002bc2797b937e51801e1013abafb734933f35b67168448659dfe`,
  kubectl `sha256:c93e4fb811b3217ef69ee7a79a9a15fb277887cd1c3002fbe154e676037a274a`,
  Go instrumentation `sha256:664715c04cb854ffdbb920ea1289a86b0717f39e46b18e6584caa9e1f2e4d83f`,
  Apache instrumentation `sha256:a86df0699bf53228588d8e08dbd95e763b7bb377a02fe1d9e68806ef954d04f8`,
  .NET `sha256:1b8d96528c8138ef40a20fa0a58db423d653a9bcb7e1fa0fa5ecb83293b8e5bc`,
  Java `sha256:812ad3b45675ef90043020c10e9ed21a3f11ba0903a848e78e3fe71654ae622c`,
  Java CSA `sha256:8b7e4f33254915fd657d1cc8a18288b6fbdd6392fac2912cb27d60df4fc383ea`,
  JavaScript `sha256:55f93be18e545d98a981bba124fe94a02fdbbb88f1fc471aa08793f7ccba4d78`,
  Python `sha256:d488c507e0cacc64b81423b96f6e53b30f2602a0e4bcc614658182f6aa13d5b4`,
  Secure Application Python `sha256:db4c6d848af4b46c89f48584b18030f00677495a0f0f26f13de67f84fc758191`,
  OBI `sha256:9c66cdb920202b9502e6f1b8e9b238757848eded40a0aad262976d6ebea23b02`,
  and Target Allocator
  `sha256:feeedb038f075d2e29e420ccbd9329c72396f44d28aefae859a19f07ee4a31a4`.
- Upstream re-pushed the mutable Apache instrumentation tag `1.0.4` between
  chart `0.154.0` and `0.158.0`. Chart `0.158.0` still declares `1.0.4`, so the
  audited digest advanced from `sha256:c519018e…` to `sha256:a86df069…`; the
  superseded digest remains pullable, so already-applied deployments are
  unaffected. This is exactly the substitution that digest pinning exists to
  make visible.
- Linux Collector, Linux auto-instrumentation, the Kubernetes Helm chart, and
  the chart's default/FIPS/Windows Collector image tag all land on `0.158.0`.
  Chart `0.158.0` sets `appVersion: 0.158.0`, so the chart and Collector version
  lines coincide at this release; they were split at `0.154.x` (installer
  `0.154.2` against chart/`appVersion` `0.154.0`) and must not be assumed equal
  in future bumps.
- The tagged Linux installer's `ensure_not_installed()` guard rejects an
  existing Collector. The generated installer wrappers are fresh-install
  paths, not package upgrade/downgrade automation.
- The tagged installer defaults Linux-host OBI to `v0.6.0`, validates host
  prerequisites, downloads and checksum-verifies the standalone binary, and
  installs it. It does not configure or start an OBI service; runtime ownership
  remains a handoff.
- OBI `v0.6.0` audited release archive SHA-256 values from the release
  `SHA256SUMS` asset are
  `da5f3501a4ae1de67930fa8dca2c822138417796c40266193af0d36effa20b95`
  for Linux `amd64` and
  `4b31902024f3e98dd93f3a28efd45a07c189f1943bb36d75a2c34dc1e0aff249`
  for Linux `arm64`. Independently extracted `obi` binary SHA-256 values are
  `3667f3a040b9125eeac88c8a8f2fab67e45f48ade259461d30a09dc9f4ea839e`
  (`amd64`) and
  `72903f7dda88d9ad70263d7c749064ede26aaa8040490807c518c62dc581aa6b`
  (`arm64`). Generated install and status helpers enforce the extracted-binary
  digest for the live architecture after the upstream archive verification.
- App `7125` `0.158.0` package filename:
  `splunk-add-on-for-opentelemetry-collector_01580.tgz`.
- App `7125` package SHA-256:
  `b50a495b44577f7a4b80f9a300fce8ea2b9e0711e074d5b1be01c5c8395a44b5`.
- App `8698` `0.158.0` package filename and SHA-256:
  `splunk-add-on-for-opentelemetry-collector-for-linux-x86_64_01580.tgz`,
  `6fb7e34553f59b803bf1e01d3b191e6314a431f2a6a640a50080012b100575ba`.
- App `8699` `0.158.0` package filename and SHA-256:
  `splunk-add-on-for-opentelemetry-collector-for-windows-x86_64_01580.tgz`,
  `b9100e0171558bd12d8cc244569fcd5709013aac438113f92ee7397da60a822c`.
- App roots are `Splunk_TA_otel`, `Splunk_TA_otel_linux_x86_64`, and
  `Splunk_TA_otel_windows_x86_64`. App `7125` is Cloud-compatible; the audited
  metadata for split apps `8698` and `8699` reports Cloud compatibility false.
- The audited TA source/package variants have no `data/ui/views` directory and
  do not ship pre-built Splunk dashboards; the renderer records this per
  supplied package rather than inferring dashboard completion from install.
- The `quay.io/signalfx/splunk-otel-collector-fips:0.158.0` manifest contains
  Linux `amd64`, Linux `arm64`, and two Windows `amd64` variants (Windows Server
  `10.0.17763` and `10.0.20348` base images). This Kubernetes image fact is
  separate from the TA FIPS-compatibility metadata.
- Splunk documents its Collector container images as signed. This workflow
  pins and verifies every rendered and live workload image by digest;
  organization signature or admission-policy enforcement remains a separate
  cluster-security handoff.
- FIPS image selection is necessary but not sufficient evidence for a FedRAMP
  deployment. A Splunk Help draft indexed in January 2026 described AWS
  GovCloud, FIPS Collector, Smart Agent, instrumentation, and integration
  limits, while also containing contradictory compliance and "in process"
  wording. Its dedicated public URL returned `404` during this July 2026 audit.
  This workflow therefore encodes no authorization or hosting claim: verify the
  live Marketplace package, order/contract, and complete boundary with Splunk
  and the compliance owner at deployment time.
- The installer has no `--trace-url` option. `--hec-url` is deprecated and the
  installer announces removal in September 2026.
- Chart `0.158.0` accepts `gateway.mode` values `deployment` and `statefulset`
  and rejects anything else; chart `0.154.0` had no `gateway.mode` key at all and
  rejected the field outright. Chart `0.155.0` added StatefulSet gateway mode
  alongside `gateway.statefulsetSpec` and `gateway.headlessService.enabled`. This
  workflow still renders only the Deployment gateway with its default of three
  replicas; StatefulSet gateway mode is an unrendered chart capability.

## Refresh procedure

1. Check current Collector, chart, and Splunkbase releases.
2. Download tagged artifacts and record digests.
3. Diff installer `--help`, chart values/schema, changelog, and upgrade guide.
4. Run the full render matrix and `validate.sh --check-upstream`.
5. Update constants, this ledger, compatibility tests, and docs in the same
   change. Do not float production apply to an unaudited release.

# Primary-source and version ledger

Last audited: **2026-07-02**.

## Executable release sources

- Collector `0.154.2` release:
  <https://github.com/signalfx/splunk-otel-collector/releases/tag/v0.154.2>
- Tagged Linux installer:
  <https://github.com/signalfx/splunk-otel-collector/blob/v0.154.2/packaging/installer/install.sh>
- Tagged Linux auto-instrumentation source:
  <https://github.com/signalfx/splunk-otel-collector/tree/v0.154.2/instrumentation>
- Audited Linux-host OBI release `v0.6.0`:
  <https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation/releases/tag/v0.6.0>
- Tagged Collector component catalog:
  <https://github.com/signalfx/splunk-otel-collector/blob/v0.154.2/docs/components.md>
- Tagged agent configuration:
  <https://github.com/signalfx/splunk-otel-collector/blob/v0.154.2/cmd/otelcol/config/collector/agent_config.yaml>
- Helm chart `0.154.0` release:
  <https://github.com/signalfx/splunk-otel-collector-chart/releases/tag/splunk-otel-collector-0.154.0>
- Exact chart release asset:
  <https://github.com/signalfx/splunk-otel-collector-chart/releases/download/splunk-otel-collector-0.154.0/splunk-otel-collector-0.154.0.tgz>
- GitHub release API record carrying the asset digest:
  <https://api.github.com/repos/signalfx/splunk-otel-collector-chart/releases/tags/splunk-otel-collector-0.154.0>
- Tagged chart values/schema source:
  <https://github.com/signalfx/splunk-otel-collector-chart/blob/splunk-otel-collector-0.154.0/helm-charts/splunk-otel-collector/values.yaml>
- Tagged chart upgrade guide:
  <https://github.com/signalfx/splunk-otel-collector-chart/blob/splunk-otel-collector-0.154.0/UPGRADING.md>
- Tagged auto-instrumentation installation guide:
  <https://github.com/signalfx/splunk-otel-collector-chart/blob/splunk-otel-collector-0.154.0/docs/auto-instrumentation-install.md>
- Tagged OBI guide:
  <https://github.com/signalfx/splunk-otel-collector-chart/blob/splunk-otel-collector-0.154.0/docs/zero-code-ebpf-instrumentation.md>
- FIPS Collector image tag and manifest:
  <https://quay.io/repository/signalfx/splunk-otel-collector-fips?tab=tags&tag=0.154.0>
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
  <https://github.com/signalfx/splunk-otel-collector-chart/blob/splunk-otel-collector-0.154.0/docs/advanced-configuration.md>
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
  <https://github.com/signalfx/splunk-otel-collector/tree/v0.154.2/packaging/ta-v2>
- TA installation documentation:
  <https://help.splunk.com/en/splunk-observability-cloud/manage-data/splunk-distribution-of-the-opentelemetry-collector/get-started-with-the-splunk-distribution-of-the-opentelemetry-collector/splunk-add-on-for-opentelemetry-collector/install-the-technical-add-on>

## Audited facts

- Linux installer SHA-256:
  `16f2c34ad1a91bf0817f5675eca3d705af5385377e87fda23537808efd5f7e29`.
- Chart release archive SHA-256:
  `613f788d786bf741be770512c7c297c4b70d3ab5426ac337b0416209e66bc7b0`
  (296,029 bytes). The renderer binds the URL, filename, and digest and does
  not combine this local archive with Helm `--version` resolution.
- Audited Collector manifest-list pins are standard Linux
  `sha256:b37160d858a5ad3344301424fba8cdb4d7cc12430383616e0ebc5fb39ad33410`,
  FIPS multi-platform
  `sha256:b11a6e592248a2281cf95a765d30660a9951f04b0935f91d9ae93db5839b3b52`,
  and Windows
  `sha256:aedfa35fcbff3dcf92bbcc195e9631ed2648d83e836ee2f9f0a2536d3a1a1e9a`.
  The Collector `v0.154.0` GitHub release text reports the FIPS `b11a…` digest
  for the standard repository, but the standard Quay tag currently resolves to
  `b371…` and the standard repository does not serve `b11a…`; the renderer uses
  the independently resolved repository/tag digest and records this discrepancy
  rather than silently trusting the release-note line.
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
  OTel Operator `sha256:71c80734e698e0a38039aeb5a6fad7129ca68eaa31eb262752c1e5015b319a24`,
  kubectl `sha256:c93e4fb811b3217ef69ee7a79a9a15fb277887cd1c3002fbe154e676037a274a`,
  Go instrumentation `sha256:664715c04cb854ffdbb920ea1289a86b0717f39e46b18e6584caa9e1f2e4d83f`,
  Apache instrumentation `sha256:c519018eb569926a44d5e078f1dcc301aa6cf8c6f35afe809b67f4eb37d0458d`,
  .NET `sha256:dea496508f6d94d417bc3f26d0bd0a4dd3a16049b6a2a5753c2a21a8035be910`,
  Java `sha256:8c3092572c4a433cb4fc258655880215d4c3dd0bf090d31fa0343a865180bfa9`,
  Java CSA `sha256:6c2c1d95c3753a4bcd9ea51c27498a242ea3de9a72345bb64d7c836fcf1c2abb`,
  JavaScript `sha256:97f0536ba942e110e3e8a493d265e11c26064c502614ad0b67069f429431484a`,
  Python `sha256:d488c507e0cacc64b81423b96f6e53b30f2602a0e4bcc614658182f6aa13d5b4`,
  Secure Application Python `sha256:f47a8f0f7362da98f0e0ac0f5ac83492555b495c6c37c411680bb055bd1f2dbe`,
  OBI `sha256:26f82b148dfe8cb0530561ab72a3cb5490b3ae5df556a33c27984af2e28542cf`,
  and Target Allocator
  `sha256:85a08d334a480c33aff1f0e9d9e432202c1e0bf23f58f8bd11aececa5506a4c6`.
- Linux Collector and Linux auto-instrumentation are independently pinned to
  `0.154.2`. The Kubernetes Helm chart and its default/FIPS/Windows Collector
  image tag are pinned to `0.154.0`; these version lines must not be conflated.
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
- App `7125` `0.154.2` package filename:
  `splunk-add-on-for-opentelemetry-collector_01542.tgz`.
- App `7125` package SHA-256:
  `928e66efb5591c3e9c07e2eae2008b605aa7cf10ae9cc48acff88f417811a7da`.
- App `8698` `0.154.2` package filename and SHA-256:
  `splunk-add-on-for-opentelemetry-collector-for-linux-x86_64_01542.tgz`,
  `efd048ae1c30fa81adbe05f9e3de0dced90cfe8a89dc750b116ca812bb3471de`.
- App `8699` `0.154.2` package filename and SHA-256:
  `splunk-add-on-for-opentelemetry-collector-for-windows-x86_64_01542.tgz`,
  `c66825ef1020c53237767d643953a8e6033c51cda92aad875a54fefcf51aea63`.
- App roots are `Splunk_TA_otel`, `Splunk_TA_otel_linux_x86_64`, and
  `Splunk_TA_otel_windows_x86_64`. App `7125` is Cloud-compatible; the audited
  metadata for split apps `8698` and `8699` reports Cloud compatibility false.
- The audited TA source/package variants have no `data/ui/views` directory and
  do not ship pre-built Splunk dashboards; the renderer records this per
  supplied package rather than inferring dashboard completion from install.
- The `quay.io/signalfx/splunk-otel-collector-fips:0.154.0` manifest contains
  Linux `amd64`, Linux `arm64`, and Windows `amd64` variants. This Kubernetes
  image fact is separate from the TA FIPS-compatibility metadata.
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
- Chart `0.154.0` rejects an unknown `gateway.mode` value; its gateway is a
  Deployment with a default of three replicas.

## Refresh procedure

1. Check current Collector, chart, and Splunkbase releases.
2. Download tagged artifacts and record digests.
3. Diff installer `--help`, chart values/schema, changelog, and upgrade guide.
4. Run the full render matrix and `validate.sh --check-upstream`.
5. Update constants, this ledger, compatibility tests, and docs in the same
   change. Do not float production apply to an unaudited release.

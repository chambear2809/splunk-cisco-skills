# Content-Pack Workflow

For a first-time ITSI setup, start with `templates/beginner.content-pack.yaml`
and keep only one profile enabled until preview and validation are clean. Use
`references/beginner_quickstart.md` to translate the user's product/domain into
the right profile and required index or macro values.

Before catalog lookup, the workflow refreshes Content Library discovery through:

- `POST /servicesNS/nobody/DA-ITSI-ContentLibrary/content_library/discovery`

For the ITSI content-pack API itself, the workflow probes these route families in order and uses whichever the host exposes:

- `/servicesNS/nobody/SA-ITOA/itoa_interface/vLatest/content_pack`
- `/servicesNS/nobody/SA-ITOA/itoa_interface/content_pack`

Preview and install use the matching route family with the same suffixes:

- `/<id>/<version>/preview`
- `/<id>/<version>/install`

## Supported Spec Shape

```yaml
connection:
  base_url: https://splunk.example.com:8089
  session_key_env: SPLUNK_SESSION_KEY
  verify_ssl: false
  platform: enterprise

itsi:
  require_present: true
  install_if_missing: true
  source: splunkbase
  app_id: "1841"

content_library:
  require_present: true
  install_if_missing: true
  source: splunkbase
  app_id: "5391"

packs:
  - profile: aws
    summary_indexes:
      - summary

  - profile: cisco_data_center
    resolution: skip
    enabled: false
    saved_search_action: disable
    install_all: true
    backfill: false
    prefix: ""

  - profile: cisco_thousandeyes
    index_macro_value: index="thousandeyes"

  - profile: linux
    event_indexes:
      - os

  - profile: splunk_appdynamics
    index_macro_value: index="appdynamics"

  - profile: splunk_observability_cloud
    metrics_indexes:
      - sim_metrics
      - sim_metrics_custom
    custom_subdomain: acme-observability

  - profile: vmware
    metrics_indexes:
      - vmware-perf-metrics

  - profile: windows
    event_indexes:
      - windows
      - perfmon
    metrics_indexes:
      - itsi_im_metrics
```

## Supported Profiles

## Workflow Notes

- On `--apply`, if `SA-ITOA` is missing and `itsi.install_if_missing` is left at its default `true`, the workflow bootstraps Splunk IT Service Intelligence by delegating to the generic app-install path described in `../splunk-itsi-setup/SKILL.md`.
- The default ITSI bootstrap source is Splunkbase app `1841`.
- If the `1841` package is rejected by the REST app-install endpoint because it is a multi-app archive, the workflow falls back to a CLI-based install on the target Splunk host.
- On Splunk Enterprise `--apply`, if `DA-ITSI-ContentLibrary` is missing and `content_library.install_if_missing` is left at its default `true`, the workflow bootstraps the Splunk App for Content Packs by calling the shared installer in `../splunk-app-install/scripts/install_app.sh`.
- The default bootstrap source is Splunkbase app `5391`.
- If the `5391` package is rejected by the REST app-install endpoint because it is a multi-app archive, the workflow falls back to a CLI-based install on the target Splunk host.
- After ITSI bootstrap or validation, the workflow checks the bundled ITSI app set (`SA-ITOA`, `itsi`, `SA-UserAccess`, `SA-ITSI-Licensechecker`) plus KV Store readiness and key ITSI collections.
- The CLI wrappers return a nonzero exit code when those prerequisite checks report errors, even if the pack-specific checks are otherwise clean.
- For offline or pre-staged installs, set:

```yaml
itsi:
  require_present: true
  install_if_missing: true
  source: local
  local_file: /absolute/path/to/itsi_package.spl

content_library:
  require_present: true
  install_if_missing: true
  source: local
  local_file: /absolute/path/to/splunk_app_for_content_packs.spl
```

- Preview and validate do not install prerequisites. They fail with guidance to rerun the same spec under `bash scripts/setup.sh --workflow content-packs --spec <path> --apply`.
- `content_library.local_file` and `itsi.local_file` can point at either `.spl` or `.tgz` archives, as long as they are valid Splunk app bundles.
- Pack validation resolves the live bundled pack app from profile-specific candidate app names, so bundle app names like `DA-ITSI-CP-vmware`, `DA-ITSI-CP-thousandeyes`, `DA-ITSI-CP-nix`, and `DA-ITSI-CP-appdynamics` are handled correctly even when the catalog ID differs.

### `aws`

- Resolves by exact live catalog title and accepts both `Amazon Web Services Dashboards and Reports` and `AWS Dashboards and Reports`
- Requires `Splunk_TA_aws`
- Validates the AWS summary-index macros `aws-account-summary` and `aws-sourcetype-index-summary`
- Warns if no local AWS inputs are visible on the search head because collection might run elsewhere
- Guides the operator through summary-index setup, Addon Synchronization, entity-search enablement, data-model acceleration, and optional PSC or billing follow-up

### `cisco_data_center`

- Requires `cisco_dc_networking_app_for_splunk`
- If the Nexus Dashboard input families are missing, also checks whether a Nexus Dashboard account is configured in the app
- Checks required Nexus Dashboard input families: advisories, anomalies, fabrics, switches
- Guides the operator through Nexus Dashboard service import, sandbox publish, service enablement, entity discovery enablement, and alerts integration

### `cisco_enterprise_networks`

- Requires `TA_cisco_catalyst` and `Splunk_TA_cisco_meraki`
- If Catalyst or Meraki input families are missing, also checks whether the underlying Catalyst Center or Meraki account is configured
- Checks Catalyst and Meraki input readiness
- Validates the Catalyst and Meraki macro alignment used by the content pack, and explains when the Catalyst macro cannot be inferred because no enabled source inputs exist yet
- Guides the operator through Catalyst Center and Meraki import, sandbox publish, service enablement, entity discovery enablement, and alerts integration

### `cisco_thousandeyes`

- Requires `ta_cisco_thousandeyes`
- Validates a live ThousandEyes index macro by either the supplied macro name or content-pack macro discovery
- Fails if the discovered target indexes look metrics-only because the pack supports event indexes only
- Guides the operator through service enablement and entity discovery enablement

### `linux`

- Resolves to the exact catalog title `Monitoring Unix and Linux`
- Requires `Splunk_TA_nix`
- Validates the `itsi-cp-nix-indexes` macro against `event_indexes`
- If the search head sees non-default Unix and Linux indexes, require `event_indexes` in the spec so validation does not assume the default `os` index
- Warns if no local Unix and Linux inputs are visible on the search head because collection often runs on forwarders
- Guides the operator through OS-module macro alignment, entity discovery, service-template linkage, and wrapper-macro tuning for non-metrics ingestion

### `splunk_appdynamics`

- Requires `Splunk_TA_AppDynamics`
- Checks status-input readiness by live modular input type, not just the stanza label
- Validates `itsi_cp_appdynamics_index` against the add-on index configuration
- Guides the operator through AppDynamics application import, sandbox publish, and entity-search enablement

### `splunk_observability_cloud`

- Requires the Splunk Infrastructure Monitoring add-on
- Checks for enabled non-sample inputs
- Validates `itsi-cp-observability-indexes` against `metrics_indexes`
- Records `custom_subdomain` for manual navigation updates
- Guides the operator through entity-search enablement and optional business-workflow saved-search enablement

### `vmware`

- Resolves to the exact catalog title `VMware Monitoring`
- Requires the Splunk Add-on for VMware Metrics components to be visible on the search head
- Validates `cp_vmware_perf_metrics_index` against `metrics_indexes`
- Guides the operator through KPI base-search tuning, threshold review, service-template use, and service-topology expansion

### `windows`

- Resolves to the exact catalog title `Monitoring Microsoft Windows`
- Requires `Splunk_TA_windows`
- Validates `itsi-cp-windows-indexes` and `itsi-cp-windows-metrics-indexes`
- If the search head sees non-default Windows indexes, require `event_indexes` and/or `metrics_indexes` in the spec so validation does not assume the default indexes
- If local Windows inputs are visible on the search head, checks for the required WinHostMon and perfmon stanza families
- Guides the operator through entity discovery, service-template linkage, and wrapper-macro tuning for non-default ingestion modes

## Report

Every content-pack execution writes:

- `reports/<timestamp>/content-pack-summary.md`

The report includes:

- resolved catalog pack and version
- preview summary
- install payload or install result
- unmet prerequisites
- pack-specific validation findings
- next manual steps

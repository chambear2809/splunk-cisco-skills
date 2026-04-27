# Content-Pack Workflow

For a first-time ITSI setup, start with `templates/beginner.content-pack.yaml`
and keep only one pack enabled until preview and validation are clean. Use
`references/beginner_quickstart.md` to translate the user's product/domain into
the right profile, exact catalog title, pack ID, and required index or macro
values.

Before catalog lookup, the workflow refreshes Content Library discovery through:

- `POST /servicesNS/nobody/DA-ITSI-ContentLibrary/content_library/discovery`

For the ITSI content-pack API itself, the workflow probes these route families in order and uses whichever the host exposes:

- `/servicesNS/nobody/SA-ITOA/itoa_interface/vLatest/content_pack`
- `/servicesNS/nobody/SA-ITOA/itoa_interface/content_pack`

Preview and install use the matching route family with the same suffixes:

- `/<id>/<version>/preview`
- `/<id>/<version>/install`
- `/status`
- `/<id>/<version>`
- `/refresh`

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
  refresh_catalog: true

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

  # Any live Content Library pack can also be managed without a named profile.
  # Use an exact catalog title or pack_id from the live catalog.
  - title: Microsoft 365
    resolution: skip
    enabled: false
    saved_search_action: disable
    install_all: true
    backfill: false
    prefix: ""
    configured_outcome:
      macros:
        - app: DA-ITSI-CP-microsoft-365
          name: itsi-cp-microsoft-365-indexes
          definition: index="o365"
      saved_searches:
        - app: DA-ITSI-CP-microsoft-365
          name: Microsoft 365 Entity Discovery
          enabled: false

  - pack_id: DA-ITSI-CP-third-party-apm
    version: 1.4.0
    resolution: skip
    enabled: false
    saved_search_action: disable
    install_all: true
    backfill: false
    prefix: ""
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
- Any live Content Library pack can be declared by `title`, `catalog_title`, or `pack_id` without a named profile. Generic catalog entries automate catalog resolution, preview, install, installed-version validation, and app visibility checks when the app name is discoverable from the catalog ID. They emit `automation_scope`, `follow_up_required`, and `follow_up_steps` in the JSON result and generated report.
- Generic catalog validation is intentionally conservative. It reports pack-specific data, macro, service-import, sandbox, dashboard, and entity-discovery work as follow-up steps unless the pack uses one of the richer named profiles below or the spec defines a `configured_outcome`.
- `configured_outcome` can preview/apply/validate post-install configuration that has a safe declarative shape. Supported outcome blocks are `native`, `macros` / `macro_updates`, and `saved_searches` / `entity_discovery_searches`. Use this for service imports already represented as native objects, entity-discovery saved-search enablement, pack macro tuning, and other deterministic handoff tasks. Unsupported post-install task blocks such as `lookup_updates`, `data_model_accelerations`, `kpi_backfills`, `service_imports`, `service_discovery`, `alert_integrations`, `dashboards`, `navigation_updates`, or `sandbox_publish` are emitted as warning steps so operators can distinguish manual follow-up from automated outcome work.
- Content Library discovery refresh status is captured in the JSON/report output. A discovery warning does not hide the catalog lookup result, but it tells the operator that a stale catalog or Content Library endpoint issue may be behind unresolved packs.

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

## Catalog-Generic Profiles

These documented Content Packs 2.5 catalog entries have named profile keys for
convenience and can also be declared by exact `title` or `pack_id`:

- `citrix`
- `example_glass_tables`
- `ite_work_alert_routing`
- `itsi_monitoring_and_alerting`
- `microsoft_365`
- `microsoft_exchange`
- `netapp_data_ontap_dashboards_reports`
- `pivotal_cloud_foundry`
- `servicenow`
- `shared_it_infrastructure`
- `soar_system_logs`
- `splunk_as_a_service`
- `splunk_synthetic_monitoring`
- `third_party_apm`
- `unix_dashboards_reports`
- `vmware_dashboards_reports`
- `windows_dashboards_reports`

These profiles resolve and install the live catalog pack, validate installed
version and pack app visibility, and report pack-specific module work as
follow-up steps. Add richer app/input/macro checks to the profile metadata when
the repository needs deeper validation for one of these domains.

## Report

Every content-pack execution writes:

- `reports/<timestamp>/content-pack-summary.md`

The report includes:

- resolved catalog pack and version
- preview summary
- install payload or install result
- unmet prerequisites
- pack-specific validation findings
- `automation_scope`
- `follow_up_required`
- `follow_up_steps`

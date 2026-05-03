# Coverage Matrix

Per-section support boundary for the Splunk Platform <-> Splunk Observability
Cloud integration. Every spec section emits one of the coverage values below.

## Coverage Values

- `api_apply` — a documented public API supports create / update / delete or
  validate; the skill renders the request and applies it under `--apply`.
- `api_validate` — a documented public API supports read-only / validate
  operations; the skill calls it during `--validate --live` and `--doctor`.
- `deeplink` — UI-only; the skill renders a deterministic Splunk or
  Observability UI link.
- `handoff` — cross-skill orchestration; the skill emits a script that
  delegates to another skill (`splunk-app-install`,
  `splunk-cloud-acs-allowlist-setup`, `splunk-itsi-config`, ...).
- `install_apply` — the skill installs or configures a Splunk-side companion
  app or saved search via Splunkbase + REST.
- `not_applicable` — the section does not apply to the chosen target (UID on
  Splunk Enterprise, Discover-app Configurations on SCP < 10.1.2507, etc.).

## Cloud Target Coverage

| Section                          | Coverage           | Notes                                                                              |
| -------------------------------- | ------------------ | ---------------------------------------------------------------------------------- |
| `prerequisites`                  | `api_validate`     | ACS read for stack metadata, version, and FedRAMP/GovCloud detection.              |
| `token_auth`                     | `api_apply`        | `POST /services/admin/token-auth/tokens_auth -d disabled=false`.                   |
| `pairing` (UID)                  | `api_apply`        | `acs observability pair` + `POST /adminconfig/v2/observability/sso-pairing`.       |
| `pairing` (SA)                   | `api_apply`        | Discover-app Access tokens REST tab write.                                         |
| `pairing` multi-org default      | `deeplink`         | No public API; Discover app > Configurations > 3-dot menu > Make Default.          |
| `centralized_rbac.capabilities`  | `api_apply`        | `acs observability enable-capabilities`.                                           |
| `centralized_rbac.cutover`       | `api_apply`        | `acs observability enable-centralized-rbac` (guarded by --i-accept-rbac-cutover).  |
| `centralized_rbac.o11y_access`   | `api_apply`        | Splunk authorize REST role create + assign.                                        |
| `related_content_capabilities`   | `api_apply`        | Splunk authorize REST capability assignments.                                      |
| `discover_app.related_discovery` | `api_apply`        | Discover app setup REST (Related Content discovery toggle).                        |
| `discover_app.test`              | `deeplink`         | "Test now" UI button only.                                                         |
| `discover_app.field_aliasing`    | `api_apply`        | Discover app setup REST (Auto Field Mapping toggle + alias write).                 |
| `discover_app.ui_updates`        | `api_apply`        | Discover app setup REST (Automatic UI updates toggle).                             |
| `discover_app.access_tokens`    | `api_apply`        | Discover app setup REST (Realm + token write).                                     |
| `discover_app.read_permission`  | `api_apply`        | Splunk apps REST (`/services/apps/local/<app>/permissions`).                       |
| `log_observer_connect.user`     | `api_apply`        | Splunk users REST (create + role assign).                                          |
| `log_observer_connect.role`     | `api_apply`        | Splunk authorize REST (role create with caps + indexes + limits).                  |
| `log_observer_connect.workload` | `api_apply`        | Splunk workload-management REST (workload rule create).                            |
| `log_observer_connect.allowlist` | `handoff`          | Delegates to `splunk-cloud-acs-allowlist-setup --features search-api`.             |
| `log_observer_connect.wizard`   | `deeplink`         | O11y > Settings > Log Observer connections > Add new connection.                   |
| `dashboard_studio_o11y.default` | `api_validate`     | Discover app + Splunk REST read of default-connection state.                       |
| `dashboard_studio_o11y.sample`  | `api_apply`        | Splunk Dashboard Studio dashboard create REST.                                     |
| `sim_addon.install`             | `handoff`          | Delegates to `splunk-app-install --source splunkbase --app-id 5247`.               |
| `sim_addon.index`               | `api_apply`        | Splunk indexes REST (or ACS indexes on Cloud).                                     |
| `sim_addon.account`             | `api_apply`        | SIM Add-on UCC custom REST handler (account create + check connection + enable).   |
| `sim_addon.modular_inputs`      | `api_apply`        | SIM Add-on UCC custom REST handler (modular input create with curated SignalFlow). |
| `sim_addon.victoria_hec`        | `handoff`          | Delegates to `splunk-cloud-acs-allowlist-setup --features hec`.                    |
| `sim_addon.itsi_pack`           | `handoff`          | Delegates to `splunk-itsi-config` for the Content Pack for Splunk Observability.   |

## Enterprise Target Coverage

| Section                          | Coverage           | Notes                                                                              |
| -------------------------------- | ------------------ | ---------------------------------------------------------------------------------- |
| `prerequisites`                  | `api_validate`     | Splunk REST for version + role checks.                                             |
| `token_auth`                     | `api_apply`        | Same REST flip as Cloud.                                                           |
| `pairing` (UID)                  | `not_applicable`   | UID requires Splunk Cloud Platform.                                                |
| `pairing` (SA)                   | `api_apply`        | Discover-app Access tokens REST tab write — when the Discover app is installed.   |
| `pairing` multi-org default      | `deeplink`         | Discover app UI only.                                                              |
| `centralized_rbac.*`             | `not_applicable`   | ACS observability commands not available on Enterprise.                            |
| `related_content_capabilities`   | `api_apply`        | Splunk authorize REST capability assignments work on Enterprise.                   |
| `discover_app.*`                 | `not_applicable`   | Configurations REST surface is Splunk Cloud Platform only (10.1.2507+).            |
| `log_observer_connect.user`     | `api_apply`        | Same Splunk users REST as Cloud.                                                   |
| `log_observer_connect.role`     | `api_apply`        | Same Splunk authorize REST as Cloud.                                               |
| `log_observer_connect.workload` | `api_apply`        | Same workload-management REST as Cloud.                                            |
| `log_observer_connect.allowlist` | `handoff`          | Render-only IP-list reminder; SE customers manage their own firewall rules.        |
| `log_observer_connect.tls_cert` | `handoff`          | SE TLS-certificate extraction helper (first cert in chain) + paste deeplink.       |
| `dashboard_studio_o11y.default` | `api_validate`     | Splunk REST read of default-connection state.                                      |
| `dashboard_studio_o11y.sample`  | `api_apply`        | Splunk Dashboard Studio dashboard create REST.                                     |
| `sim_addon.install`             | `handoff`          | Delegates to `splunk-app-install --source splunkbase --app-id 5247`.               |
| `sim_addon.index`               | `api_apply`        | Splunk indexes REST.                                                               |
| `sim_addon.account`             | `api_apply`        | SIM Add-on UCC custom REST handler.                                                |
| `sim_addon.modular_inputs`      | `api_apply`        | SIM Add-on UCC custom REST handler.                                                |
| `sim_addon.victoria_hec`        | `not_applicable`   | Victoria-stack carve-out is Splunk Cloud Platform only.                            |
| `sim_addon.itsi_pack`           | `handoff`          | Delegates to `splunk-itsi-config`.                                                 |

## Out of Scope

These adjacent surfaces are intentionally NOT in this skill:

- Splunk Add-on for OpenTelemetry Collector (Splunkbase 7125) — handled by
  `splunk-observability-otel-collector-setup`. That skill manages OTel
  collector deployment on Kubernetes / Linux; this skill only orchestrates
  the platform-side pairing and SIM streaming.
- Splunk Synthetic Monitoring Add-on (Splunkbase 5608) — archived since 2022;
  replaced by SIM Add-on streams. Marked `deprecated: true` in
  `skills/shared/app_registry.json` for honesty.
- Splunk On-Call wiring — handled by `splunk-oncall-setup`. That skill owns
  the API-id / X-VO-Api-Key flow, REST endpoint integration, and the
  Splunk-side Splunkbase 3546 / 4886 / 5863 apps.
- ITSI Content Pack content management (services, KPIs, entities) — handled
  by `splunk-itsi-config`. This skill only renders the install handoff.
- Splunk Observability Cloud dashboards / detectors / Synthetics tests / RUM
  workflows / Log Observer queries — handled by
  `splunk-observability-dashboard-builder` and
  `splunk-observability-native-ops`. This skill only renders the in-platform
  navigation surfaces (Discover app + Related Content + Dashboard Studio
  metrics + sim SPL).
- AppDynamics Log Observer Connect — separate AppDynamics SaaS workflow;
  outside the scope of the Splunk Platform <-> O11y pairing.
- Splunk Cloud Platform IP allowlist administration — handled by
  `splunk-cloud-acs-allowlist-setup`. This skill renders the deltas it
  needs (LOC realm IPs and Victoria-stack HEC) and hands off there.

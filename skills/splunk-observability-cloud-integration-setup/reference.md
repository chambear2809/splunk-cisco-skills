# Splunk Observability Cloud Integration Reference

## Research Basis

This skill follows current Splunk Observability Cloud, Splunk Cloud Platform,
and Splunk Enterprise documentation:

- Unified Identity (UID) integrates Splunk Cloud Platform and Splunk
  Observability Cloud through Splunk Cloud Platform as the SAML Identity
  Provider; users access both products with a single SSO login.
- Pairing the two products uses Admin Config Service (ACS) commands or the
  ACS REST API at `https://admin.splunk.com/{stack}/adminconfig/v2/observability/sso-pairing`.
- ACS observability subcommands (as of acs-cli 2.14.0) are exactly:
  `acs observability`, `acs observability pair`, `acs observability
  pairing-status-by-id`, `acs observability enable-capabilities`,
  `acs observability enable-centralized-rbac`. There is no public API for
  unpair, list, or make-default — those are UI actions in the Discover
  Splunk Observability Cloud app's Configurations tab.
- Centralized RBAC (C-RBAC) lets Splunk Cloud Platform act as the role-based
  access control store for Splunk Observability Cloud. After
  `enable-capabilities` provisions `o11y_admin / o11y_power / o11y_read_only
  / o11y_usage` (around 30 minute propagation), `enable-centralized-rbac`
  is the destructive cutover; UID-mapped users without an `o11y_*` role get
  the "No access to Splunk Observability Cloud" error.
- The `o11y_access` custom role is the gate role that every UID user must
  hold to access the Observability product.
- Real Time Metrics in Splunk Cloud Platform require the `read_o11y_content`
  and `write_o11y_content` capabilities; Related Content previews in
  Search & Reporting require additionally `EXECUTE_SIGNAL_FLOW`,
  `READ_APM_DATA`, `READ_BASIC_UI_ACCESS`, and `READ_EVENT`.
- The "Discover Splunk Observability Cloud" app ships with Splunk Cloud
  Platform 10.1.2507+ and exposes five Configurations tabs: Related Content
  discovery, Test related content, Field aliasing (Auto Field Mapping
  toggle), Automatic UI updates, and Access tokens.
- Field aliasing maps about thirty alternative names (`host`, `host_id`,
  `host.id`, `hostname`, `hostid`, `host_name`, `application`, `app`,
  `app_name`, `service`, `serviceid`, `service.id`, `service_name`, `trace`,
  `traceid`, `trace.id`, ...) to the canonical Splunk Observability Cloud
  Related Content keys `host.name`, `service.name`, and `trace_id`.
- Log Observer Connect is available in AWS realms us0/us1/eu0/eu1/eu2/jp0/
  au0/sg0 and the GCP realm us2; it requires Splunk Cloud Platform 9.0.2209+
  or Splunk Enterprise 9.0.1+. It is not available on Splunk Cloud Platform
  trials. The service-account role needs `edit_tokens_own` and `search`,
  must NOT have `indexes_list_all`, and gets a Standard search limit of
  `4 * concurrent_users`, a 30-day window, a 90-day earliest event time,
  and 1000 MB of disk space.
- The Workload Rule predicate `user=<svc> AND runtime>5m -> Abort search`
  keeps Log Observer Connect searches under 5 minutes per the Splunk
  product documentation.
- Splunk Cloud Platform Log Observer Connect realm IP set (must be added to
  the `search-api` allowlist):
  - us0: `34.199.200.84/32, 52.20.177.252/32, 52.201.67.203/32, 54.89.1.85/32`
  - us1: `44.230.152.35/32, 44.231.27.66/32, 44.225.234.52/32, 44.230.82.104/32`
  - eu0: `108.128.26.145/32, 34.250.243.212/32, 54.171.237.247/32`
  - eu1: `3.73.240.7/32, 18.196.129.64/32, 3.126.181.171/32`
  - eu2: `13.41.86.83/32, 52.56.124.93/32, 35.177.204.133/32`
  - jp0: `35.78.47.79/32, 35.77.252.198/32, 35.75.200.181/32`
  - au0: `13.54.193.47/32, 13.55.9.109/32, 54.153.190.59/32`
  - sg0: `3.0.226.159/32, 18.136.255.76/32, 52.220.199.72/32`
  - us2 (GCP): `35.247.113.38/32, 35.247.32.72/32, 35.247.86.219/32`
- The Splunk Infrastructure Monitoring Add-on (`Splunk_TA_sim`, Splunkbase
  app id 5247) runs SignalFlow programs from a Splunk modular input and
  writes results to the `sim_metrics` metrics index. The `sim` SPL search
  command queries Splunk Observability Cloud directly without indexing.
- The SIM Add-on enforces a hard cap of 250,000 metric time series per
  computation, and a per-data-block metadata cap of 10,000 MTS by default
  (30,000 MTS for enterprise subscriptions). Modular inputs with the
  `SAMPLE_` prefix never run unless renamed, so the renderer always strips
  the `SAMPLE_` prefix when cloning catalog programs.
- Splunk Cloud Platform Victoria stacks require the search-head IP to be
  added to the `hec` allowlist before the SIM Add-on account can connect to
  the HEC receiver — the renderer hands this off to
  `splunk-cloud-acs-allowlist-setup`.
- ACS observability commands accept an optional `--o11y-realm` flag for
  paired non-default realms. The pairing token must be a Splunk
  Observability Cloud admin token; the SIM Add-on org token can be a
  non-admin organization access token scoped to API token authorization.
- The `acs observability pair` REST equivalent is:
  `POST /adminconfig/v2/observability/sso-pairing` with
  `Authorization: Bearer <SCP-admin-JWT>` and
  `o11y-access-token: <O11y-admin-token>` headers.
- The pair call returns a `{"id": "<pairing-id>"}` payload; the
  `pairing-status-by-id` call polls `GET .../sso-pairing/{pairing-id}` for
  `SUCCESS|FAILED|IN_PROGRESS`.
- The Splunk Cloud Platform <-> Splunk Observability Cloud realm-to-region
  map is fixed:
  `us-east-1 <-> us0`, `us-west-2 <-> us1`, `eu-west-1 <-> eu0`,
  `eu-central-1 <-> eu1`, `eu-west-2 <-> eu2`, `ap-southeast-2 <-> au0`,
  `ap-northeast-1 <-> jp0`, `ap-southeast-1 <-> sg0`.
  Cross-region pairing requires Splunk Account team approval.
- Token authentication is off by default on the Splunk platform and is a
  hard precondition for UID. The flip is
  `POST /services/admin/token-auth/tokens_auth -d disabled=false` on the
  search head; it requires the `edit_tokens_settings` capability and does
  not require a Splunk restart.

## Official References

- Unified Identity: https://help.splunk.com/en/splunk-observability-cloud/administer/splunk-platform-users/unified-identity
- Connect multiple Splunk Observability Cloud organizations: https://help.splunk.com/en/splunk-observability-cloud/administer/splunk-platform-users/connect-multiple-splunk-observability-cloud-organizations
- Centralized user and role management: https://help.splunk.com/splunk-observability-cloud/administer/splunk-platform-users/centralized-user-and-role-management
- Set the default organization: https://help.splunk.com/en/splunk-observability-cloud/administer/splunk-platform-users/set-the-default-organization-for-a-splunk-observability-cloud-multi-org-environment
- ACS API endpoint reference: https://docs.splunk.com/Documentation/SplunkCloud/latest/Config/ACSREF
- ACS CLI: https://docs.splunk.com/Documentation/SplunkCloud/latest/Config/ACSCLI
- ACS CLI release notes (acs-cli 2.14.0 added observability subcommands): https://github.com/splunk/acs-cli/releases
- Splunk Observability Cloud previews (Splunk Cloud Platform): https://docs.splunk.com/Documentation/SplunkCloud/latest/Search/setupobservabilitypreviews
- Observability Related Content previews: https://docs.splunk.com/Documentation/SplunkCloud/latest/Search/observabilitypreviews
- Splunk Observability Cloud previews (Splunk Enterprise): https://help.splunk.com/en/splunk-enterprise/search/search-manual/10.0/observability/splunk-observability-cloud-previews
- Set up Log Observer Connect for Splunk Cloud Platform: https://docs.splunk.com/observability/logs/scp.html
- Set up Log Observer Connect for Splunk Enterprise: https://docs.splunk.com/observability/logs/set-up-logconnect.html
- Configure and install certificates in Splunk Enterprise for Splunk Log Observer Connect: https://docs.splunk.com/Documentation/Splunk/9.2.1/Security/ConfigureandinstallcertificatesforLogObserver
- Splunk Infrastructure Monitoring Add-on (Splunkbase 5247): https://splunkbase.splunk.com/app/5247
- Configure Splunk Infrastructure Monitoring Add-on: https://help.splunk.com/en/splunk-it-service-intelligence/extend-itsi-and-ite-work/splunk-infrastructure-monitoring-add-on/1.3/install-and-configure/configure-splunk-infrastructure-monitoring-add-on
- Configure inputs in Splunk Infrastructure Monitoring Add-on: https://docs.splunk.com/Documentation/SIMAddon/latest/Install/ModInput
- About the sim command: https://docs.splunk.com/Documentation/SIMAddon/latest/Install/Commands
- Install and configure the Content Pack for Splunk Observability Cloud (handed off to `splunk-itsi-config`): https://docs.splunk.com/Documentation/CPObservability/3.4.0/CP/Install
- Enable or disable token authentication: https://docs.splunk.com/Documentation/SplunkCloud/latest/Security/EnableTokenAuth
- Splunk Observability Cloud and the Splunk platform overview: https://help.splunk.com/en/splunk-observability-cloud/administer/splunk-platform-users/splunk-observability-cloud-and-the-splunk-platform

## Spec Schema (high level)

Specs use `api_version: splunk-observability-cloud-integration-setup/v1` and
include the section blocks documented in
[references/coverage.md](references/coverage.md). The non-secret worksheet is
[template.example](template.example).

## CLI Surface

| Flag                                       | Purpose                                                                                       |
| ------------------------------------------ | --------------------------------------------------------------------------------------------- |
| `--render` (default)                       | Produce the numbered plan tree under `--output-dir`.                                          |
| `--apply [SECTIONS]`                       | Apply (idempotent). Without args runs all sections; CSV picks specific sections.              |
| `--validate`                               | Static checks of a rendered tree; pair with `--live` for API-side checks.                     |
| `--doctor`                                 | Run the twenty-check diagnostic catalog and emit a prioritized fix list.                      |
| `--discover`                               | Read-only sweep that polls live state and writes `current-state.json`.                        |
| `--quickstart`                             | Single-shot greenfield SCP + UID + Discover + SIM scenario.                                   |
| `--quickstart-enterprise`                  | Splunk Enterprise fast path (SA + SIM + Related Content + LOC TLS path).                      |
| `--explain`                                | Print apply plan in plain English; no API calls.                                              |
| `--enable-token-auth`                      | Flip token authentication on (auto-rendered as a doctor fix).                                 |
| `--i-accept-rbac-cutover`                  | Required guard for `--apply rbac` to actually run `enable-centralized-rbac`.                  |
| `--rollback <section>`                     | Render reverse commands for a previously applied section.                                     |
| `--list-sim-templates`                     | Show the curated SignalFlow modular-input catalog.                                            |
| `--render-sim-templates a,b,c`             | Render only the named SignalFlow templates from the catalog.                                  |
| `--make-default-deeplink`                  | Emit the multi-org "Make Default" UI deeplink for the named realm.                            |
| `--spec PATH`                              | Spec file (YAML or JSON); defaults to `template.example`.                                     |
| `--output-dir DIR`                         | Output directory; defaults to `splunk-observability-cloud-integration-rendered`.              |
| `--realm REALM`                            | Splunk Observability Cloud realm; falls back to `SPLUNK_O11Y_REALM`.                          |
| `--token-file PATH`                        | Splunk Observability Cloud user/dashboard API token (chmod 600).                              |
| `--admin-token-file PATH`                  | Splunk Observability Cloud admin token for UID + RBAC (chmod 600).                            |
| `--org-token-file PATH`                    | Splunk Observability Cloud org access token for the SIM Add-on account (chmod 600).           |
| `--service-account-password-file PATH`     | Log Observer Connect service-account password (chmod 600).                                    |
| `--allow-loose-token-perms`                | Override the chmod-600 token-file requirement (emits WARN).                                   |
| `--target cloud\|enterprise`               | Override `target` in the spec.                                                                |
| `--json` / `--summary`                     | `--validate` and `--doctor` output modes for CI vs human consumption.                         |
| `--dry-run`                                | Skip live API calls (apply scaffolding stays render-only).                                    |

## Rejected Direct-Secret Flags

The following are rejected with an explicit error message that points to the
file-based equivalent:

`--token`, `--access-token`, `--api-token`, `--o11y-token`, `--admin-token`,
`--org-token`, `--sf-token`, `--service-account-password`, `--password`.

## Rendered Tree

```
splunk-observability-cloud-integration-rendered/
  README.md
  architecture.mmd
  00-prerequisites.md
  01-token-auth.md
  02-pairing.md
  03-rbac.md
  04-discover-app.md
  05-related-content.md
  06-log-observer-connect.md
  07-dashboard-studio.md
  08-sim-addon.md
  09-handoff.md
  coverage-report.json
  apply-plan.json
  current-state.json   (only when --discover)
  doctor-report.md     (only when --doctor)
  payloads/
  scripts/
  state/
  support-tickets/
  sim-addon/
```

See [references/coverage.md](references/coverage.md) for the full per-section
support boundary matrix and [references/error-catalog.md](references/error-catalog.md)
for the catalog of known errors and the exact next-step commands the skill
emits in response.

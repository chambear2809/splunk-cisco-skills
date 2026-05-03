# Splunk-side companion apps

All conf-file shapes below were verified by extracting each Splunkbase
package and reading its `default/` and `README/*.spec` files.

## Splunkbase 3546 — Splunk On-Call (VictorOps) alert action

- App folder name: **`victorops_app`** (the package retained the legacy id;
  the skill must reference this exact id for `passwords.conf`, ACS install,
  and `is_configured` checks).
- Splunkbase v1.0.42 (2026-01-28). Splunk Enterprise / Splunk Cloud 8.0–10.3.
  Requires Python 3.13.
- Install target: search head, or SHC deployer for SHC deployments.

### Alert action stanza

`default/alert_actions.conf`:

```
[victorops]
is_custom = 1
label = VictorOps
description = Send a customized message to VictorOps on a triggered alert action in Splunk.
icon_path = alert_victorops.png
python.version = python3
python.required = 3.13
payload_format = json
param.api_endpoint = https://alert.victorops.com/integrations/generic/20131114/alert
param.message_type = CRITICAL
param.monitoring_tool =
param.entity_id =
param.entity_display_name =
param.state_message =
param.record_id =
param.routing_key_override =
param.enable_recovery =
param.poll_interval =
param.inactive_polls =
param.ea_mgr_host =
param.ea_role =
```

Verified parameter set (from `default/alert_actions.conf` plus
`README/alert_actions.conf.spec`):

| Parameter | Notes |
|-----------|-------|
| `api_endpoint` | Defaults to `https://alert.victorops.com/integrations/generic/20131114/alert`. |
| `message_type` | Default `CRITICAL`. |
| `monitoring_tool` | Source label; drives the timeline logo. |
| `entity_id` | Incident identity. |
| `entity_display_name` | Human summary. |
| `state_message` | Verbose body. |
| `record_id` | Internal — references the stored API + routing-key pair in the `mycollection` KV-store. |
| `routing_key` | Selects the destination team. |
| `routing_key_override` | Per-alert routing override. |
| `enable_recovery` | `true|false|0|1` — turns on the auto-recovery path. |
| `poll_interval` | Seconds between recovery polls. |
| `inactive_polls` | Number of consecutive empty polls before sending RECOVERY. |
| `ea_mgr_host` | ITSI hybrid-action manager host. |
| `ea_role` | `executor` or `manager` for ITSI hybrid-action installations. |

### Auto-recovery (`recovery_polling`)

`default/savedsearches.conf` ships:

```
[victorops-alert-recovery]
cron_schedule = */5 * * * *
description = Search to perform victorops alert recovery
dispatch.earliest_time = 0
dispatch.latest_time = now
enableSched = 1
schedule_window = 60
search = | recoveralerts
```

The custom search command `recoveralerts` (`default/commands.conf` →
`bin/recoverAlerts.py`) scans the `mycollection` and `activealerts` KV-store
collections and posts a `RECOVERY` for any open alert whose original Splunk
search no longer fires. The skill's `recovery_polling` spec section toggles
both the `enable_recovery` parameter on the alert action and the saved
search.

### KV-store collections

`default/collections.conf`:

| Collection | Use |
|------------|-----|
| `mycollection` | API + routing keys. |
| `proxyconfig` | Outbound proxy configuration. |
| `activealerts` | Open alerts pending recovery. |
| `deployment` | Deployment details (org slug, deployment name). |

The skill seeds `mycollection` and `deployment` through the Splunk REST API
endpoint
`/servicesNS/<user>/victorops_app/storage/collections/data/<collection>`.
It **never** drops the API key into a conf file or `passwords.conf`-style
plaintext.

### Custom REST endpoint

`default/restmap.conf` exposes `/recover_alert` with handler
`custom_endpoint_recover_alert.Recover` for third-party recovery flows.

### Custom search commands

| Command | Purpose |
|---------|---------|
| `recoveralerts` | Scan KV-store for alerts whose underlying Splunk search no longer fires; send RECOVERY. |
| `retrieveroutingkeys` | Pull the org's routing-key list from On-Call. |
| `settestresult` | Mark an alert as test-only. |
| `setorganization` | Update the stored org slug. |

These commands are documented for operators who want to compose SPL
automations on the Splunk side.

### Org slug

`organization = <slug>` is stored under `[ui]` in `app.conf`. It is
non-secret. The skill's `splunk_side` spec section accepts `org_slug` and
writes it via the REST API.

## Splunkbase 4886 — Splunk Add-on for On-Call (VictorOps)

- App folder name: **`TA-splunk-add-on-for-victorops`**.
- Splunkbase v2.0.0. Splunk Enterprise / Splunk Cloud 8.0–10.3.
- Install target: **heavy forwarder** (the Add-on calls the public API and
  produces JSON events that flow into Splunk indexes).

### Modular inputs

Verified from `default/inputs.conf` and `README/inputs.conf.spec`. Each
input takes `api_id`, `api_key`, `index`, `interval`, and `organization_id`:

| Input | Endpoint |
|-------|----------|
| `victorops_user` | `GET /api-public/v1/user` plus per-user contact methods and policies. |
| `victorops_oncall` | `GET /api-public/v1/oncall/current`. |
| `victorops_teams` | `GET /api-public/v1/team` plus members and policies. |
| `victorops_incidents` | `GET /api-public/v1/incidents`. |

### Sourcetypes

Verified from `default/props.conf`:

- `splunk:victorops:users:json`
- `splunk:victorops:teams:json`
- `splunk:victorops:oncall:json`
- `splunk:victorops:incidents:json`

### Required indexes

Verified from `default/macros.conf`:

- `victorops_users`
- `victorops_teams`
- `victorops_oncall`
- `victorops_incidents`

The skill's `splunk_side` spec section pre-creates these indexes (Cloud via
ACS, Enterprise via the indexer cluster bundle) before enabling inputs.

### Pre-built dashboards

The Add-on ships 10 dashboards. The skill validates that they exist after
install:

`vo_team_oncall_calendar`, `vo_user_oncall_calendar`, `vo_teams`,
`vo_oncall`, `vo_incidents`, `vo_incidents_analysis`, `vo_noc`, `vo_sla`,
`vo_sla_config`, `vo_proxy`.

### Conference Bridges

`bin/getConferenceBridges.py` confirms a public-API path exists for
conference bridges, even though it is not prominently documented. The skill
defers full coverage to a future revision; for now the
`integrations.conference_bridges` block remains a UI handoff with a note
that the path is reachable.

## Splunkbase 5863 — Splunk On-Call SOAR connector

- App folder name: **`splunkoncall`** (package: `phantom_splunkoncall`,
  `appid: 623de41b-eac0-4a4a-970c-974e8d7ac2cb`).
- Splunkbase v2.2.4 (2025-08-01). Splunk SOAR 5.1.0+. Python 3.9 / 3.13.
  **FIPS-compliant.**

### Asset configuration

Verified from `splunkoncall.json`:

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `api_id` | string | yes | The X-VO-Api-Id header value. |
| `api_key` | password | yes | The X-VO-Api-Key header value. |
| `integration_url` | string | no | Required only for create/update/resolve incident actions; format `https://alert.victorops.com/integrations/generic/20131114/alert/<key>`. |

### Action set (9 actions)

| Action | Type | Notes |
|--------|------|-------|
| `test_connectivity` | test | Validates asset config. |
| `list_teams` | investigate | `GET /api-public/v1/team`. |
| `list_users` | investigate | `GET /api-public/v1/user`. |
| `list_incidents` | investigate | `GET /api-public/v1/incidents`. Returns `currentPhase` and `entityState`. |
| `create_incident` | generic | POSTs to `integration_url`. Params: `routing_key`, `message_type` ∈ `CRITICAL | WARNING`, `entity_id`, `entity_display_name`, `state_message`, `state_start_time`. |
| `list_oncalls` | investigate | `GET /api-public/v1/oncall/current`. |
| `list_policies` | investigate | `GET /api-public/v1/policies`. |
| `list_routing` | investigate | `GET /api-public/v1/org/routing-keys`. |
| `update_incident` | generic | POSTs to `integration_url`. Params: `routing_key`, `message_type` ∈ `INFO | RECOVERY`, `entity_id`, `entity_display_name`, `state_message`. |

The skill renders a SOAR asset-config JSON stub plus a per-action smoke-test
plan and mirrors the same `currentPhase` and `entityState` enums in its own
`incidents` validator.

## ITSI hybrid actions

When the spec sets `ea_role: manager | executor` and
`ea_mgr_host: <hostname>`, the renderer emits matching `[victorops]`
overrides for ITSI hybrid-action deployments. These parameters were lifted
directly from the alert action's `alert_actions.conf.spec`.

## ES Adaptive Response

The skill renders an ES Adaptive Response action stub backed by `[victorops]`
in the operator's notable event correlation searches.

## Splunk Observability detector recipient

The skill renders a deeplink + handoff that adds On-Call as a Splunk
Observability detector recipient. The actual mutation lives in
`splunk-observability-native-ops` via deeplink only.

# Recovery Polling

The Splunk On-Call alert action (Splunkbase 3546, `victorops_app`) ships a
built-in auto-recovery path that automatically resolves On-Call incidents
once the underlying Splunk search no longer fires. The `recovery_polling`
spec section toggles this end-to-end: the alert-action's per-alert
parameters, the scheduled saved search, and the KV-store collections that
back them.

## Components verified by extraction

### Alert action parameters

`default/alert_actions.conf` exposes:

| Parameter | Notes |
|-----------|-------|
| `enable_recovery` | `true | false | 0 | 1` — enables auto-recovery for the alert. |
| `poll_interval` | Seconds between Splunk-search re-runs (default 300). |
| `inactive_polls` | Consecutive empty polls before sending RECOVERY (default 1). |

### Scheduled saved search

`default/savedsearches.conf`:

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

The cron runs every five minutes by default. The skill's `recovery_polling`
section can override the cron and the `schedule_window`.

### Custom search command `recoveralerts`

`default/commands.conf` → `bin/recoverAlerts.py`. The command:

1. Reads open alerts from the `mycollection` and `activealerts` KV-store
   collections.
2. For each open alert, re-runs the original Splunk search at the configured
   `poll_interval`.
3. After `inactive_polls` consecutive empty results, posts a `RECOVERY`
   message to the configured REST endpoint with the original `entity_id`.

### Custom REST endpoint `/recover_alert`

`default/restmap.conf` registers `/recover_alert` with handler
`custom_endpoint_recover_alert.Recover`. Third-party recovery flows can post
to this endpoint to resolve an alert without re-running the Splunk search.

## Spec shape

```yaml
recovery_polling:
  enabled: true
  alert_actions:
    - alert_name: "Critically Low Disk Space"
      enable_recovery: true
      poll_interval: 300
      inactive_polls: 2
  scheduled_search:
    cron_schedule: "*/5 * * * *"
    schedule_window: 60
    enabled: true
```

## Operator workflow

The skill's `splunk_side_install.sh` does the following when the
`recovery_polling` section is non-empty:

1. Verify `victorops_app` is installed (Splunkbase 3546).
2. Use the Splunk REST API to set the `enable_recovery`, `poll_interval`,
   and `inactive_polls` parameters on each named saved search via
   `/servicesNS/<user>/victorops_app/saved/searches/<name>`.
3. Toggle the `victorops-alert-recovery` saved search itself via
   `/servicesNS/<user>/victorops_app/saved/searches/victorops-alert-recovery`,
   updating `enableSched`, `cron_schedule`, and `schedule_window`.
4. Validate the schedule by calling the saved search's `/dispatch?status=1`
   endpoint.

The skill never edits `savedsearches.conf` on disk — Splunk Cloud doesn't
allow it, and on Splunk Enterprise REST is the supported path.

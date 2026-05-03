# Dashboards catalog

The skill ships one starter SignalFlow dashboard at `dashboards/cisco-intersight-overview.signalflow.yaml`. This annex documents what's in it and how to extend.

## Default dashboard: Cisco Intersight Overview

| Chart | Metric | Aggregation |
|-------|--------|-------------|
| Server power state | `intersight.server.power_state` | min over time |
| Server CPU temperature | `intersight.server.temperature.cpu` | mean over time |
| Server inlet temperature | `intersight.server.temperature.inlet` | mean over time |
| Disk health | `intersight.disk.health` | min over time (0 = critical) |
| Memory health | `intersight.memory.health` | min over time |
| Fan health | `intersight.fan.health` | min over time |
| Power supply health | `intersight.psu.health` | min over time |

All charts filter by `intersight.org.id=${ORG_ID}` so multi-org Intersight tenants can create one dashboard per org.

## Per-server vs per-rack views

The Intersight receiver emits metrics at the **server** granularity (one set per chassis-mount). For per-rack rollups, group by `intersight.rack.id`:

```python
data('intersight.server.power_state')
  .sum_by(['intersight.rack.id'])
  .publish('rack_power')
```

For per-domain rollups (Intersight Domain == UCS domain), group by `intersight.domain.id`.

## Common per-fabric extensions

### Hardware lifecycle dashboard

Track `intersight.server.lifecycle_state` to surface servers that are in `decommissioned`, `pending_decommission`, or `unsupported` states:

```python
data('intersight.server.lifecycle_state')
  .filter(filter('intersight.org.id', '${ORG_ID}'))
  .top(n=20)
  .publish('lifecycle_states')
```

### Firmware drift

Group `intersight.server.firmware_version` by `intersight.firmware.target_version` and alert when count of mismatches exceeds threshold.

### Compute capacity

Sum `intersight.server.cpu.cores_total` across all servers in the org to track total compute capacity. Useful for capacity planning.

## Adding charts

Drop a new YAML file under `dashboards/<name>.signalflow.yaml`. The handoff-dashboards.sh script picks up every `*.signalflow.yaml` and feeds it to `splunk-observability-dashboard-builder`.

## Coordination with cisco-intersight-setup

The companion skill `cisco-intersight-setup` ingests Intersight audit + alarm + inventory events into Splunk Platform. For a complete observability story:

- This skill (`splunk-observability-cisco-intersight-integration`) for **time-series metrics** in O11y dashboards/detectors.
- `cisco-intersight-setup` for **events, audit, alarms, inventory** in Splunk Platform searches.

Cross-link: the Splunk O11y dashboards can deeplink into Splunk Platform searches (e.g. when an alarm fires, link the rendered chart to a search by `event.subject=<server-id>`).

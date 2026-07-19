# Dashboards catalog

The skill ships one starter SignalFlow dashboard at `dashboards/cisco-intersight-overview.signalflow.yaml`. This annex documents what's in it and how to extend.

## Default dashboard: Cisco Intersight Overview

| Chart | Metric |
|-------|--------|
| Host power | `intersight.ucs.host.power` |
| Host temperature | `intersight.ucs.host.temperature` |
| Fan speed | `intersight.ucs.fan.speed` |
| Network receive rate | `intersight.ucs.network.receive.rate` |
| Network transmit rate | `intersight.ucs.network.transmit.rate` |
| Network utilization | `intersight.ucs.network.utilization.average` |
| Active alarms | `intersight.alarms.count` |
| Security advisories | `intersight.advisories.security.count` |
| Non-security advisory objects | `intersight.advisories.nonsecurity.affected_objects` |
| VM inventory | `intersight.vm_count` |

The renderer writes a complete
`splunk-observability-dashboard-builder/v1` spec. Every chart filters on the
concrete `k8s.cluster.name` selected during render, and the dashboard includes
the same value as a restricted cluster variable.

## Per-server vs per-rack views

If live metric metadata confirms a rack dimension, create a reviewed copy and
group a known emitted metric by that dimension. Do not assume an
`intersight.rack.id` dimension without discovery.

```python
data('intersight.ucs.host.power')
  .sum_by(['intersight.rack.id'])
  .publish('rack_power')
```

## Common per-fabric extensions

### Hardware lifecycle dashboard

Lifecycle, firmware, and capacity extensions require metrics or dimensions
confirmed through live metadata discovery. They are not emitted or claimed by
the starter dashboard.

```python
data('verified.lifecycle.metric')
  .top(n=20)
  .publish('lifecycle_states')
```

### Firmware drift

After discovery, group a verified firmware metric by its documented target
dimension and alert on mismatches.

### Compute capacity

After discovery, sum a verified CPU-capacity metric for capacity planning.

## Adding charts

Start from the rendered v1 spec or the Dashboard Builder example, preserve the
required group/dashboard/chart structure, and use a non-overlapping chart
layout. The handoff script includes every `*.signalflow.yaml` in the directory.

## Coordination with cisco-intersight-setup

The companion skill `cisco-intersight-setup` ingests Intersight audit + alarm + inventory events into Splunk Platform. For a complete observability story:

- This skill (`splunk-observability-cisco-intersight-integration`) for **time-series metrics** in O11y dashboards/detectors.
- `cisco-intersight-setup` for **events, audit, alarms, inventory** in Splunk Platform searches.

Cross-product deep links require a separately reviewed dashboard capability;
the current classic Dashboard Builder renderer does not accept a generic chart
link field.

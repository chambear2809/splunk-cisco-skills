# Dashboards catalog

The skill ships one starter SignalFlow dashboard spec at `dashboards/cisco-nexus-overview.signalflow.yaml`. This annex documents the chart catalog and how to extend it.

## Default dashboard: Cisco Nexus Overview

| Chart | Metric |
|-------|--------|
| Device up | `cisco.device.up` |
| CPU utilization | `system.cpu.utilization` |
| Memory utilization | `system.memory.utilization` |
| Interface status | `system.network.interface.status` |
| Network throughput | `system.network.io` |
| Network errors | `system.network.errors` |
| Packet drops | `system.network.packet.dropped` |

The renderer writes a complete
`splunk-observability-dashboard-builder/v1` spec. Every chart contains a
SignalFlow filter for the concrete `cluster_name` selected at render time, and
the dashboard includes the same value as a restricted cluster variable. To
restrict a copy to a specific device, add a verified device dimension to the
SignalFlow programs and dashboard variables.

## Common per-fabric extensions

### Spine vs leaf dashboards

If your fabric has a clear spine/leaf split, render two separate dashboards by adding a `device_role` resource attribute via the OTel collector's `resource` processor and filtering each dashboard by it. Sample patch:

```yaml
clusterReceiver:
  config:
    processors:
      resource/role:
        attributes:
          - { action: insert, key: device.role, value: "spine" }
```

This requires a per-device pipeline (separate `metrics/cisco-os-spine` and `metrics/cisco-os-leaf` pipelines), which the skill does not render by default; hand-edit the overlay.

### Packet drop trend with anomaly

For SignalFlow anomaly detection on packet drops:

```python
data('system.network.packet.dropped')
  .rate('1m')
  .timeshift('1d')
  .publish('drops_baseline')

data('system.network.packet.dropped')
  .rate('1m')
  .publish('drops_now')

(drops_now - drops_baseline).publish('drops_anomaly')
```

Add this as a custom chart via dashboard-builder.

### Top-N talkers

```python
data('system.network.io', filter=filter('direction', 'transmit'))
  .top(n=10)
  .publish('top_talkers')
```

## Cross-referencing alarms

The starter detector spec at `detectors/interface-status-down.yaml` triggers
Critical when the minimum interface status is at or below zero. Dashboard and
detector objects are separate; the skill does not create an automatic
chart-to-detector link.

## Adding charts

Start from the rendered v1 spec or the Dashboard Builder's
`templates/dashboard.example.yaml`, preserve the required `api_version`,
`dashboard_group`, `dashboard`, and `charts` mappings, and add a chart with a
non-overlapping row/column layout. The handoff script includes every
`*.signalflow.yaml` under `dashboards/`.

## Coordinating with cisco-dc-networking-setup

The companion skill `cisco-dc-networking-setup` ingests Nexus / ACI / Nexus Dashboard events and configuration into Splunk Platform. For a complete observability story:

- Use this skill (`splunk-observability-cisco-nexus-integration`) for **time-series metrics** in O11y dashboards/detectors.
- Use `cisco-dc-networking-setup` for **events / config / syslog** in Splunk Platform searches.

Cross-product deep links require a separately reviewed dashboard capability;
the current classic Dashboard Builder renderer does not accept a generic
`link` field on chart specs.

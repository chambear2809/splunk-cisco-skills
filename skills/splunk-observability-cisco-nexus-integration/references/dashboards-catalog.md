# Dashboards catalog

The skill ships one starter SignalFlow dashboard spec at `dashboards/cisco-nexus-overview.signalflow.yaml`. This annex documents the chart catalog and how to extend it.

## Default dashboard: Cisco Nexus Overview

| Chart | Metric | Aggregation |
|-------|--------|-------------|
| Device up | `cisco.device.up` | min over time |
| CPU utilization | `system.cpu.utilization` | mean over time |
| Memory utilization | `system.memory.utilization` | mean over time |
| Interface status | `system.network.interface.status` | min over time (0 = down) |
| Network throughput | `system.network.io` | rate per interface |
| Network errors | `system.network.errors` | rate per interface |
| Packet drops | `system.network.packet.dropped` | rate per interface |

All charts filter by `k8s.cluster.name=${CLUSTER_NAME}` so the dashboard scopes cleanly across multi-cluster O11y orgs. To restrict to a specific Nexus device, add a `device.name` filter via the dashboard-builder skill.

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

The starter detector spec at `detectors/interface-status-down.yaml` triggers Critical when any interface status drops to 0. The dashboard shows the status chart; clicking the chart in O11y UI navigates to the related detector.

## Adding charts

Drop a custom YAML file under `dashboards/<name>.signalflow.yaml`:

```yaml
name: "Custom chart name"
description: "..."
charts:
  - name: "Chart title"
    description: "..."
    program_text: |
      data('metric.name', filter=filter('k8s.cluster.name', '${CLUSTER_NAME}'))
        .publish(label='metric.name')
    publish_label: metric.name
filters:
  - property: k8s.cluster.name
    value: ${CLUSTER_NAME}
```

The handoff-dashboards.sh script picks up every `*.signalflow.yaml` under `dashboards/` and feeds it to `splunk-observability-dashboard-builder`.

## Coordinating with cisco-dc-networking-setup

The companion skill `cisco-dc-networking-setup` ingests Nexus / ACI / Nexus Dashboard events and configuration into Splunk Platform. For a complete observability story:

- Use this skill (`splunk-observability-cisco-nexus-integration`) for **time-series metrics** in O11y dashboards/detectors.
- Use `cisco-dc-networking-setup` for **events / config / syslog** in Splunk Platform searches.

Cross-link: the Splunk O11y dashboards can deeplink into Splunk Platform searches by adding a `link` field to the chart spec.

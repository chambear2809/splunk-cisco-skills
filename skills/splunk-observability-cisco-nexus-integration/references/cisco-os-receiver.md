# cisco_os receiver

The cisco_os receiver lives in upstream `opentelemetry-collector-contrib` and connects to Cisco network devices over SSH to scrape system + interface metrics. The skill targets receiver version **v0.149.0+** (multi-device + global-scrapers format from PR #45562, merged Feb 2026).

## Where it lives in the OTel collector

The receiver runs in the **clusterReceiver** (one-instance Deployment), not the agent (DaemonSet). This matters because:

- A DaemonSet would scrape each Nexus device once per cluster node, multiplying SSH load by the node count and likely tripping Nexus rate-limits.
- The clusterReceiver scrapes each device exactly once per `collection_interval`.

The skill emits the receiver under `clusterReceiver.config.receivers.cisco_os` and adds a dedicated `metrics/cisco-os-metrics` pipeline so the receiver's output flows independently of the chart's standard k8s metric pipeline.

## Scrapers

The receiver ships two scrapers (PR #45562):

### `system`

| Metric | Description | Stability |
|--------|-------------|-----------|
| `cisco.device.up` | 1 if device is reachable via SSH, 0 otherwise | development |
| `system.cpu.utilization` | CPU utilization percentage | development |
| `system.memory.utilization` | Memory utilization percentage | development |

### `interfaces`

| Metric | Description | Stability |
|--------|-------------|-----------|
| `system.network.io` | Bytes transmitted/received per interface | development |
| `system.network.errors` | Per-interface error count | development |
| `system.network.packet.dropped` | Per-interface dropped packet count | development |
| `system.network.packet.count` | Per-interface packet count | development |
| `system.network.interface.status` | 1 if interface up, 0 if down | development |

All metrics are at **"development"** stability per the receiver's metadata.yaml. The Splunk Observability Cloud signalfx exporter accepts them without complaint, but expect occasional metric renames as the receiver matures. The skill's `reference.md` notes this; pin the chart to a known-good cisco_os version when you commit to a long-term setup.

## Per-device or per-scraper overrides

The PR #45562 multi-device format supports per-device scraper toggles:

```yaml
cisco_os:
  collection_interval: 60s
  timeout: 30s
  devices:
    - name: edge-switch-01
      host: 10.0.1.10
      port: 22
      auth: { username: ..., password: ... }
      scrapers:                     # per-device override
        system: {}                  # only system scraper for this device
  scrapers:                          # global default for all other devices
    system: { metrics: { cisco.device.up: { enabled: true } } }
    interfaces: { metrics: { system.network.io: { enabled: true } } }
```

The skill's renderer applies global scrapers (no per-device overrides) by default. Operators who need per-device scraper differences should hand-edit the rendered overlay before merging.

## Supported Cisco OS variants

Per the upstream contrib README, the receiver works against:

- Cisco NX-OS (Nexus 9000, Nexus 7000, Nexus 5000, etc.)
- Cisco IOS-XE (Catalyst 9000 series)
- Cisco IOS-XR (Cisco 8000, ASR 9000 series)

The skill's name says "nexus" because that's the most common AI Pod use case, but the receiver also works against Catalyst and IOS-XR fabrics. The same overlay applies; only the device hostnames change.

## SSH connectivity requirements

- Reachability: cluster-receiver pod must reach the Nexus management IP. Confirm with `kubectl exec -n splunk-otel deployment/<release>-splunk-otel-collector-k8s-cluster-receiver -- nc -zv <nexus-ip> 22`.
- Permissions: the SSH user needs `show` privileges (`feature` line vty config plus appropriate role assignment). For dedicated read-only telemetry users, role `network-operator` typically suffices.
- Key auth: use `key_file` + `key_passphrase` if your security policy bans password auth. Set `spec.ssh_secret.key_file_key` and the renderer mounts the key as `/etc/cisco-nexus-ssh/key` instead of using a password env var.

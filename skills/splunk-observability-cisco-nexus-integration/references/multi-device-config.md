# Multi-device configuration (PR #45562)

The cisco_os receiver moved from a single-device per-receiver-instance model to a multi-device + global-scrapers model in upstream contrib **PR #45562** (merged Feb 2026, available v0.149.0+). The skill renders the new format exclusively.

## Old format (pre-PR #45562, do NOT use)

```yaml
cisco_os/edge-switch-01:
  collection_interval: 60s
  host: 10.0.1.10
  username: splunk-otel
  password: ${env:CISCO_NEXUS_SSH_PASSWORD}
  scrapers:
    system: {}
    interfaces: {}

cisco_os/edge-switch-02:
  collection_interval: 60s
  host: 10.0.1.11
  username: splunk-otel
  password: ${env:CISCO_NEXUS_SSH_PASSWORD}
  scrapers:
    system: {}
    interfaces: {}
```

Drawbacks: one receiver instance per device. Doesn't scale; the chart's pipeline list grows linearly; metric attribution is per-receiver-instance instead of per-device-attribute.

## New format (PR #45562, what the skill renders)

```yaml
cisco_os:
  collection_interval: 60s
  timeout: 30s
  devices:
    - name: edge-switch-01
      host: 10.0.1.10
      port: 22
      auth:
        username: ${env:CISCO_NEXUS_SSH_USERNAME}
        password: ${env:CISCO_NEXUS_SSH_PASSWORD}
    - name: edge-switch-02
      host: 10.0.1.11
      port: 22
      auth:
        username: ${env:CISCO_NEXUS_SSH_USERNAME}
        password: ${env:CISCO_NEXUS_SSH_PASSWORD}
  scrapers:                  # global defaults for all devices
    system: { metrics: { cisco.device.up: { enabled: true } } }
    interfaces: { metrics: { system.network.io: { enabled: true } } }
```

Benefits:

- Single receiver instance handles all devices.
- `device.name` lands as a metric attribute automatically; SignalFlow filters by it.
- `scrapers:` block at the top level applies globally; per-device overrides are optional.

## Authentication

The auth block per device supports either password or key file:

```yaml
# Password (default)
auth:
  username: splunk-otel
  password: ${env:CISCO_NEXUS_SSH_PASSWORD}

# Key file
auth:
  username: splunk-otel
  key_file: /etc/cisco-nexus-ssh/key
  key_passphrase: ${env:CISCO_NEXUS_SSH_KEY_PASSPHRASE}   # optional
```

The skill's renderer picks one based on `spec.ssh_secret.password_key` vs `spec.ssh_secret.key_file_key`. If both are set, key file wins.

## Common per-device overrides

If you have a mix of NX-OS and IOS-XE in one fabric, you may want different scrapers per device:

```yaml
devices:
  - name: nexus-spine-01
    host: 10.0.1.1
    auth: { ... }
    # No per-device override -> uses global scrapers below.
  - name: catalyst-edge-01
    host: 10.0.2.1
    auth: { ... }
    scrapers:
      system: {}                     # IOS-XE supports system scraper
      # Skip interfaces on this device because the IOS-XE interfaces scraper is
      # not stable yet (per upstream contrib v0.149.0 metadata.yaml).
scrapers:
  system: {}
  interfaces: {}                     # global default: scrape interfaces too
```

The skill does not currently render per-device overrides; hand-edit the rendered overlay if you need them.

## Performance notes

- `collection_interval: 60s` is conservative. Cisco fabrics with hundreds of interfaces per device may need 90s or 120s to avoid overlapping scrape cycles.
- `timeout: 30s` is generous. Most Nexus devices respond within 5s; lower the timeout to 10s for faster failure detection if your fabric is healthy.
- Each device opens one SSH session per scrape. Persistent SSH (`use_persistent_session: true`, when supported by a future receiver version) will reduce session-setup overhead.

## Observability of the receiver itself

The cisco_os receiver emits its own metrics under the `otelcol_*` namespace inside the collector. Useful indicators:

- `otelcol_receiver_accepted_metric_points{receiver="cisco_os"}` — total metric points accepted from cisco_os.
- `otelcol_receiver_refused_metric_points{receiver="cisco_os"}` — refused (usually due to memory_limiter back-pressure).

Add a SignalFlow chart over these series to confirm the receiver is healthy after a deploy.

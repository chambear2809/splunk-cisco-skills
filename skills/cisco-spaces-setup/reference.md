# Cisco Spaces TA — Input and Account Reference

Complete catalog of account fields, input types, REST endpoints, and
deployment-specific notes for the **Cisco Spaces Add-on for Splunk**
(`ta_cisco_spaces`).

## Meta Stream Account Fields

Configured via the custom REST handler at
`/servicesNS/nobody/ta_cisco_spaces/ta_cisco_spaces_stream`.

| Field | Required | Encrypted | Description |
|-------|----------|-----------|-------------|
| `name` | Yes | No | Stream stanza name / identifier |
| `activation_token` | Yes | Yes | Cisco Spaces activation token (encrypted at rest) |
| `region` | Yes | No | `io`, `eu`, or `sg` |
| `location_updates_status` | No | No | `1` to record device location updates (default: off) |

### Region to API Endpoint Mapping

| Region | Firehose API Base |
|--------|-------------------|
| `io` | `https://partners.dnaspaces.io` |
| `eu` | `https://partners.dnaspaces.eu` |
| `sg` | `https://partners.dnaspaces.sg` |

Firehose events are fetched from:
```
https://partners.dnaspaces.<region>/api/partners/v1/firehose/events
```

## Input Types

| Input Stanza | Sourcetype | Description |
|---|---|---|
| `cisco_spaces_firehose://<name>` | `cisco:spaces:firehose`; current releases may also emit `cisco:spaces:firehose:health` | Streaming SSE connection to Cisco Spaces Firehose API |

The firehose input is a long-lived SSE (Server-Sent Events) connection. The
`interval` field (default 300s) controls the retry wait time when the
connection drops — it is **not** a polling interval.

### Input Fields

| Field | Required | Description |
|-------|----------|-------------|
| `stream` | Yes | Meta stream name (references a stream stanza) |
| `index` | Yes | Target index (default: `cisco_spaces`) |
| `interval` | No | Retry wait in seconds on connection drop (default: 300) |

## Indexes

| Index | Purpose | Max Size |
|-------|---------|----------|
| `cisco_spaces` | All Cisco Spaces firehose events | 512 GB |

## Sourcetypes

| Sourcetype | Content |
|---|---|
| `cisco:spaces:firehose` | Device presence, location updates, IoT telemetry, and contextual data from Cisco Spaces Firehose API |
| `cisco:spaces:firehose:health` | Firehose connection and collector-health events |
| `cisco:spaces:log` | Add-on internal collector logs |

Package `2.0.1` is the first release to ship `props.conf`, and it defines all
three source types. The `1.0.7` package shipped no `props.conf` at all, so
health events are absent there. Treat health-event presence as version-bound
evidence; do not fail an otherwise complete `1.0.7` onboarding solely because it
is missing. The single `cisco_spaces_firehose` modular input is unchanged
between `1.0.7` and `2.0.1`.

## REST API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/servicesNS/nobody/ta_cisco_spaces/ta_cisco_spaces_stream` | Create meta stream |
| GET | `/servicesNS/nobody/ta_cisco_spaces/ta_cisco_spaces_stream` | List meta streams |
| POST | `/servicesNS/nobody/ta_cisco_spaces/ta_cisco_spaces_stream/<name>` | Update meta stream |
| DELETE | `/servicesNS/nobody/ta_cisco_spaces/ta_cisco_spaces_stream/<name>` | Delete meta stream |
| GET/POST | `/servicesNS/nobody/ta_cisco_spaces/ta_cisco_spaces_settings` | Global settings |
| GET/POST | `/servicesNS/nobody/ta_cisco_spaces/data/inputs/cisco_spaces_firehose` | Manage firehose inputs |

## Global Settings

Configured in `local/ta_cisco_spaces_settings.conf`:

| Setting | Default | Description |
|---------|---------|-------------|
| `loglevel` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `proxy_enabled` | `0` | Enable HTTP proxy for outbound connections |
| `proxy_url` | (empty) | Proxy URL |
| `proxy_port` | (empty) | Proxy port |
| `proxy_username` | (empty) | Proxy username |
| `proxy_password` | (encrypted) | Proxy password |

## SHC Replication

`server.conf` includes `ta_cisco_spaces_settings` and `ta_cisco_spaces_stream`
in SHC conf replication so stream configuration propagates across all SHC
members automatically.

## Dashboard Notes

This TA does not ship its own dashboards. Use the data in `cisco_spaces` with
ad-hoc search or with a companion visualization app. Use
`cisco:spaces:firehose` plus `event_type` for product events. Keep
`cisco:spaces:firehose:health` separate when a current package emits collector
health so operational events do not distort product-event panels.

## Platform Notes

| Platform | Index Creation | App Install | Stream Config |
|---|---|---|---|
| Splunk Enterprise | REST (`/services/data/indexes`) or auto | Direct REST or SSH stage | Search-tier REST |
| Splunk Cloud | ACS (`acs indexes create`) | ACS Splunkbase or private app | Search-tier REST |

On Splunk Cloud, the `ta_cisco_spaces` app must be installed before configuring
streams. ACS handles installation; streams are configured over search-tier REST
after installation completes.

## Completion Validation

`validate.sh --completion`/`--strict` exits nonzero for missing stream, enabled
input, index, event, or primary `cisco:spaces:firehose` evidence. It reports
the version-bound health sourcetype separately. No-flag validation is
diagnostic. This TA ships no pre-built dashboards.

# Splunk Stream — Reference

Reference for the Splunk Stream stack: management app, forwarder add-on, and
wire-data knowledge objects.

## Package Identity

| App | Package Name | Splunkbase ID | Local Fallback Archive |
|-----|-------------|--------------|----------------------|
| Splunk App for Stream | `splunk_app_stream` | `1809` | `splunk-app-for-stream_816.tgz` |
| Splunk Add-on for Stream Forwarders | `Splunk_TA_stream` | `5238` | `splunk-add-on-for-stream-forwarders_816.tgz` |
| Splunk Add-on for Stream Wire Data | `Splunk_TA_stream_wire_data` | `5234` | `splunk-add-on-for-stream-wire-data_816.tgz` |

## Deployment Roles

| Role | Apps Installed | Notes |
|------|---------------|-------|
| `search-tier` | `splunk_app_stream`, `Splunk_TA_stream_wire_data` | Stream UI, REST API, CIM knowledge objects |
| `heavy-forwarder` | `Splunk_TA_stream` | Runs `streamfwd` binary, captures/receives traffic |
| `indexer` | `Splunk_TA_stream_wire_data` | Transforms and field extractions at index time |
| `universal-forwarder` | `Splunk_TA_stream` | Lightweight capture; limited protocol support |

In Splunk Cloud hybrid deployments, the search-tier apps go through ACS; the
forwarder add-on is installed on a customer-controlled HF/UF.

## Indexes

| Index | Purpose | Default Max Size |
|-------|---------|------------------|
| `netflow` | NetFlow/IPFIX and sFlow data | 512 GB |
| `stream` | Captured protocol stream events | 512 GB |

## Ports

| Port | Protocol | Purpose |
|------|----------|---------|
| 8889 | TCP | `streamfwd` API port (management) |
| 9995 | UDP | Default NetFlow/IPFIX receiver |

## Configuration Files

### streamfwd.conf (Splunk_TA_stream)

| Stanza/Key | Purpose |
|-----------|---------|
| `[streamfwd]` | Main forwarder configuration |
| `ipAddr` | IP address `streamfwd` listens on |
| `port` | API port (default `8889`) |
| `httpEventCollectorToken` | HEC token for HEC-based forwarding |
| `netflowReceiver.0.port` | NetFlow/IPFIX receiver port |
| `netflowReceiver.0.decoder` | Decoder type (e.g., `netflow`) |

### Stream Definitions (splunk_app_stream)

Protocol streams are defined and managed through the Stream app REST API at
`/servicesNS/nobody/splunk_app_stream/streams`.

## Templates

| Directory | Purpose |
|-----------|---------|
| `templates/splunk-cloud-hf-netflow-any/` | HF overlay for Cloud hybrid NetFlow |

## Validation Checklist

- `splunk_app_stream` installed on search tier (or standalone)
- `Splunk_TA_stream` installed on forwarder-side host
- `Splunk_TA_stream_wire_data` installed on search tier and/or indexers
- `stream` and `netflow` indexes exist
- `streamfwd` process running and listening on configured port
- NetFlow receiver port open if NetFlow ingestion is expected
- Protocol streams enabled for desired protocols

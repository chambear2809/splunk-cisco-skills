# Cisco Catalyst Enhanced Netflow Add-on — Reference

Reference for the optional Cisco HSL/IPFIX mapping add-on used with Cisco
Enterprise Networking NetFlow dashboards.

## Package Identity

| Property | Value |
|---|---|
| App name | `splunk_app_stream_ipfix_cisco_hsl` |
| Splunkbase ID | `6872` |
| Latest packaged version in repo | `2.1.0` |
| Local package pattern | `cisco-catalyst-enhanced-netflow-add-on-for-splunk_*` |
| Vendor package | `splunk-ta/cisco-catalyst-enhanced-netflow-add-on-for-splunk_210.tgz` |

## Deployment Model

The bundled `app.manifest` declares:

| Field | Value |
|---|---|
| `supportedDeployments` | `_standalone`, `_distributed`, `_search_head_clustering` |
| `targetWorkloads` | `_forwarders` |
| `dependencies` | none declared |

Practical meaning:

- Install on a standalone Splunk instance if that same host receives and parses NetFlow/IPFIX.
- In distributed deployments, install on the heavy forwarder or forwarder-side Splunk instance that owns the NetFlow/IPFIX receiver path.
- Do not treat this as a normal Splunk Cloud search-tier app.

## Packaged Files

| File | Purpose |
|---|---|
| `README.md` | Vendor overview and topology notes |
| `default/app.conf` | App metadata; install requires restart |
| `default/ipfixmap.conf` | Static IPFIX element-to-term mappings |
| `default/cisco.hsl.json` | Cisco HSL field catalog for Stream integration |
| `default/cisco.hsl.xml` | XML representation of the HSL field metadata |
| `default/server.conf` | Includes `ipfixmap` in SHC replication |

## What It Configures

This add-on contributes static knowledge and parsing metadata only:

- IPFIX element mappings in `ipfixmap.conf`
- Cisco HSL field definitions in `cisco.hsl.json` and `cisco.hsl.xml`

It does **not** provide:

- account configuration
- credential storage
- custom REST handlers
- data inputs
- index creation

## Related Apps

| App | Role |
|---|---|
| `TA_cisco_catalyst` | Base Cisco Catalyst data collection |
| `Splunk_TA_stream` | Typical forwarder-side NetFlow/IPFIX receiver path |
| `splunk_app_stream` | Search-tier Stream management/UI in standalone or hybrid Stream deployments |
| `cisco-catalyst-app` | Optional dashboard consumer for the extra NetFlow mappings |

## Validation Checklist

- `splunk_app_stream_ipfix_cisco_hsl` is installed on the parsing target
- if the target uses `Splunk_TA_stream`, `streamfwd.conf` exists
- if the target should receive NetFlow/IPFIX, `netflowReceiver.0.port` is set
- optional consumer apps (`TA_cisco_catalyst`, `cisco-catalyst-app`) are installed where expected

## Restart Behavior

The vendor package sets:

```ini
[install]
state_change_requires_restart = true
```

Plan for a restart after installation unless the shared installer already
handled it.

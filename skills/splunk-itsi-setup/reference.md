# Splunk ITSI Reference

## Core Apps

ITSI installs as a bundle of several apps from a single Splunkbase package
(ID `1841`):

| App | Purpose |
|-----|---------|
| `SA-ITOA` | Core engine: service definitions, KPIs, glass tables, event management |
| `itsi` | UI layer: service analyzer, deep dives, glass tables |
| `SA-UserAccess` | Role-based access control for ITSI objects |
| `SA-ITSI-Licensechecker` | License validation and enforcement |

## Prerequisites

- Valid ITSI license applied to the target Splunk instance
- Healthy KVStore (ITSI stores service, KPI, and episode state there)
- Splunk Enterprise 9.x+ or a compatible Splunk Cloud stack

## Validation Checks

The `validate.sh` script verifies:

| Check | What it confirms |
|-------|------------------|
| Core apps installed | `SA-ITOA`, `itsi`, `SA-UserAccess`, `SA-ITSI-Licensechecker` presence and versions |
| KVStore health | KVStore status endpoint returns a ready state |
| KVStore collections | `itsi_services`, `itsi_kpi_template`, `itsi_notable_event_group` are accessible |
| Integration readiness | Detects `ta_cisco_thousandeyes` and reports ThousandEyes-ITSI availability |

## Integration With ThousandEyes

When `ta_cisco_thousandeyes` is installed alongside ITSI, the ThousandEyes app
registers additional objects:

| Object | Role |
|--------|------|
| `thousandeyes_forward_splunk_events` alert action | Forwards ITSI notable events to ThousandEyes |
| `itsi_episodes` KVStore collection | Episode state tracking for ThousandEyes correlation |
| Event sampling configuration | Controlled forwarding rate to ThousandEyes |

The ThousandEyes validator automatically detects ITSI and reports integration
readiness.

## Known Constraints

1. ITSI is a premium product; installation succeeds but features require a
   license
2. Cloud availability may depend on stack type and Splunk Cloud support
   coordination
3. KVStore must be healthy before and after install; check
   `/services/kvstore/status` if validation fails
4. Always requires a Splunk restart after installation

# Splunk Cloud ACS Admin Reference

## Research Basis

This skill follows current Splunk Cloud ACS documentation and the local
`acs` CLI help output from ACS CLI 2.22.0.

For Splunk Cloud Platform `10.4.2604`, review
`../shared/splunk_10_4_enterprise_deployment_notes.md`. ACS admin plans must
stay within ACS-supported APIs for allowlists, HEC tokens, indexes, roles,
limits, outbound ports, maintenance windows, and restarts; filesystem or
host-level Enterprise assumptions do not apply to Cloud stacks.

Official references:

- ACS overview:
  <https://help.splunk.com/en/splunk-cloud-platform/administer/admin-config-service-manual/10.4.2604/using-the-admin-config-service-acs--api/admin-config-service-acs-requirements-and-compatibility-matrix>
- ACS API endpoint reference:
  <https://help.splunk.com/en/splunk-cloud-platform/administer/admin-config-service-manual/10.4.2604/admin-config-service-acs-api-endpoint-reference/admin-config-service-acs-api-endpoint-reference>
- ACS CLI:
  <https://help.splunk.com/en/splunk-cloud-platform/administer/admin-config-service-manual/10.4.2604/administer-splunk-cloud-platform-using-the-admin-config-service-acs-cli/administer-splunk-cloud-platform-using-the-acs-cli>
- IP allow lists:
  <https://help.splunk.com/en/splunk-cloud-platform/administer/admin-config-service-manual/10.4.2604/administer-splunk-cloud-platform-using-the-admin-config-service-acs-api/configure-ip-allow-lists-for-splunk-cloud-platform>
- Outbound ports:
  <https://help.splunk.com/en/splunk-cloud-platform/administer/admin-config-service-manual/10.4.2604/administer-splunk-cloud-platform-using-the-admin-config-service-acs-api/configure-outbound-ports-for-splunk-cloud-platform>
- Private connectivity:
  <https://docs.splunk.com/Documentation/SplunkCloud/latest/Security/Privateconnectivityenable>
- Limits:
  <https://docs.splunk.com/Documentation/SplunkCloud/latest/Config/ManageLimits>
- ACS release notes:
  <https://docs.splunk.com/Documentation/SplunkCloud/latest/ReleaseNotes/AdminConfigurationService>
- Splunk Cloud Platform Terraform Provider (`splunk/scp`):
  <https://registry.terraform.io/providers/splunk/scp/latest>

## ACS Surface Matrix

| Module | CLI / API surface | Automation stance |
|--------|-------------------|-------------------|
| IP allowlists | `acs ip-allowlist`, `acs ip-allowlist-v6` | Full render, preflight, apply, audit for all seven features |
| Indexes | `acs indexes` | Guarded create/update; DDSS and DDAA fields supported |
| DDSS self-storage | `acs indexes self-storage-locations` | Guarded create; policy/prefix/service-account reads through inventory |
| HEC tokens | `acs hec-token` | Guarded create/update without direct token values |
| Users | `acs users` | Inventory and reviewed handoff only when password material is involved |
| Roles | `acs roles` | Guarded create/update with `fsh_manage` acknowledgement validation |
| Capabilities | `acs capabilities list` | Inventory/read-only |
| App permissions | `acs permissions apps` | Guarded update; bulk update remains a reviewed handoff |
| Private connectivity | `/private-connectivity/eligibility`, `/private-connectivity/endpoints` | REST helper; API-only in some CLI releases |
| Outbound ports | `acs outbound-port`, `acs outbound-port-v6` | Guarded create for IPv4/IPv6 destinations |
| Limits | `acs limits` | Guarded set, read-only list |
| Maintenance windows | `acs maintenance-windows schedules`, `acs maintenance-windows preferences` | Read schedules/audit; guarded preferences update by JSON file |
| Restarts | `acs restart` | Guarded restart-current-stack or restart-if-required |
| Apps | `acs apps` | Inventory/read-only here; installs remain in `splunk-app-install` |
| Auth tokens | `acs token` | Inventory/read-only here; token creation remains operator-driven |
| Deployment tasks | `acs deployment` | Status/retry visibility; retry remains operator-driven |
| License | `acs license` | Inventory/read-only |
| Observability pairing | `acs observability` | Command-surface check and handoff to `splunk-observability-cloud-integration-setup` for Unified Identity / centralized RBAC guardrails |

## Admin Plan JSON

The optional `--admin-plan-file` is JSON, not YAML. Keep credentials and token
values out of it. Supported top-level keys:

```json
{
  "indexes": [
    {
      "name": "cisco_netops",
      "datatype": "event",
      "searchableDays": 90,
      "maxDataSizeMB": 0,
      "selfStorageBucketPath": "s3://bucket/prefix",
      "splunkArchivalRetentionDays": 365
    }
  ],
  "hec_tokens": [
    {
      "name": "cisco_netops_hec",
      "defaultIndex": "cisco_netops",
      "allowedIndexes": ["cisco_netops"],
      "defaultSourceType": "cisco:test",
      "useAck": false,
      "disabled": false
    }
  ],
  "roles": [
    {
      "name": "cisco_netops_role",
      "capabilities": ["search"],
      "srchIndexesAllowed": ["cisco_netops"],
      "srchIndexesDefault": ["cisco_netops"]
    }
  ],
  "users": [
    {
      "name": "cisco_netops_user",
      "roles": ["cisco_netops_role"],
      "passwordFile": "/path/to/local/password-file"
    }
  ],
  "app_permissions": [
    {
      "name": "search",
      "read": ["user", "power", "admin"],
      "write": ["admin"]
    }
  ],
  "outbound_ports": [
    {
      "port": 8089,
      "family": "ipv4",
      "subnets": ["198.51.100.10/32"]
    }
  ],
  "ddss_self_storage_locations": [
    {
      "bucketName": "bucket",
      "title": "Production DDSS archive",
      "folder": "splunk"
    }
  ],
  "limits": [
    {
      "stanza": "subsearch",
      "settings": {
        "maxout": "50000"
      }
    }
  ],
  "maintenance_windows": {
    "preferencesFile": "/path/to/change-freezes.json"
  },
  "private_connectivity": [
    {
      "customerAccountIds": ["112233445566"],
      "features": ["ingest", "search"]
    }
  ],
  "restarts": {
    "restartIfRequired": true
  }
}
```

## Allowlist Feature Surface

| Feature | Port | IPv4 default | Notes |
|---------|------|--------------|-------|
| `acs` | n/a | open (`0.0.0.0/0`) | Restrict carefully; controls ACS API, CLI, and Terraform provider access |
| `search-api` | 8089 | closed | REST/SDK access to search heads |
| `hec` | 443 | open | HTTP Event Collector data ingestion |
| `s2s` | 9997 | open | Splunk-to-Splunk forwarder traffic |
| `search-ui` | 80/443 | open, except regulated stacks can be closed | Search head web UI |
| `idm-api` | 8089 | open | Inputs Data Manager API on Classic/legacy IDM stacks only; not present on Victoria |
| `idm-ui` | 443 | open | Inputs Data Manager UI on Classic/legacy IDM stacks only; not present on Victoria |

AWS deployments enforce 200 subnets per feature and a 230-subnet cap for each
allowlist group. GCP deployments enforce 200 subnets per feature. The renderer
counts IPv4 and IPv6 together for these guards.

For Splunk Cloud Platform 10.4.2604, determine the stack experience before
planning allowlists and HEC/IDM handoffs. Victoria stacks have no IDM, do not
support Hybrid Search, and Classic-to-Victoria migrations move IDM apps and
configuration to the search tier; IDM-era allowlists must be reviewed against
search head or SHC member IPs. The renderer requires
`--cloud-experience classic` for IDM features/subnets, rejects them for
`--cloud-experience victoria`, and fails closed when the experience is
`unknown` unless `--accept-unknown-cloud-experience` is passed after explicit
operator review.

## Private Connectivity Notes

The ACS API exposes private connectivity eligibility and endpoint creation at:

- `GET /{stack}/adminconfig/v2/private-connectivity/eligibility`
- `POST /{stack}/adminconfig/v2/private-connectivity/endpoints`

The POST body includes `customerAccountIds` and the `feature` array, where
supported features are `ingest` and `search`; an empty list enables both
features per Splunk documentation. The rendered
`private-connectivity-rest.sh` uses `STACK_TOKEN` as a bearer token and stores
request bodies in temporary files so tokens do not appear in process argv.

FedRAMP Moderate customers need a Splunk Support case for the documented
private-connectivity enablement steps. FedRAMP High allowlist administration is
also support-managed.

## Out of Scope

- Splunkbase app installation and private app upload workflows. Use
  [`splunk-app-install`](../splunk-app-install/SKILL.md).
- End-to-end HEC service design for Enterprise and Cloud. Use
  [`splunk-hec-service-setup`](../splunk-hec-service-setup/SKILL.md).
- Non-Cloud restarts and cluster-aware Enterprise restarts. Use
  [`splunk-platform-restart-orchestrator`](../splunk-platform-restart-orchestrator/SKILL.md).
- End-to-end Observability Cloud pairing, Unified Identity, and centralized
  RBAC setup. Use
  [`splunk-observability-cloud-integration-setup`](../splunk-observability-cloud-integration-setup/SKILL.md).

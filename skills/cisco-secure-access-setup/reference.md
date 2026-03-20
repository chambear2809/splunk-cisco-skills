# Cisco Secure Access — Reference

Reference for the local Cisco Secure Access App for Splunk package.

## Package Identity

| Property | Value |
|---|---|
| App name | `cisco-cloud-security` |
| Splunkbase ID | `5558` |
| Local package pattern | `cisco-secure-access-app-for-splunk_*` |
| Local package in repo | `splunk-ta/cisco-secure-access-app-for-splunk_1053.tgz` |
| Packaged version inspected | `1.0.53` |

## Important Note

The local package in this repo is the **Cisco Secure Access App for Splunk**,
not the separate “Cisco Secure Access Add-on for Splunk” listing on Splunkbase.

## Core Automation Endpoint

The package’s main setup surface is the custom REST endpoint:

```text
/servicesNS/nobody/cisco-cloud-security/org_accounts
```

Supported actions identified in the package code:

- `POST /org_accounts` — create an org account
- `GET /org_accounts?orgId=<id>&fields=all` — fetch one org account
- `PUT /org_accounts?orgId=<id>` — update an org account
- `DELETE /org_accounts?orgId=<id>` — delete an org account
- `POST /org_accounts?action=get_orgId` — discover `orgId` from credentials

## Core Account Fields

| Field | Required | Notes |
|---|---|---|
| `apiKey` | yes | secret |
| `apiSecret` | yes | secret |
| `baseURL` | yes | Secure Access API base URL |
| `orgId` | yes for create/update | can be discovered with `action=get_orgId` |
| `timezone` | yes | org setting |
| `storageRegion` | yes | org setting |
| `investigate_index` | optional | registers investigate settings |
| `privateapp_index` | optional | registers Private Apps index and modular input |
| `appdiscovery_index` | optional | registers App Discovery index and modular input |

## Related Settings Surface

The package also exposes a custom `/update_settings` endpoint backed by KV store
collections such as:

- `cloudlock_settings`
- `selected_destination_lists`
- `dashboard_settings`
- `refresh_rate`
- `s3_indexes`

The repo automation now covers these settings through
`scripts/configure_settings.sh`.

## Dashboard-Ready Settings Payload

The frontend posts settings in this shape:

```json
{
  "data": {
    "Dashboard": { "search_interval": "12" },
    "cloudlock": {
      "userName": "splunk-user",
      "createdDate": "2026/03/20 01:23:45",
      "configName": "Cloudlock_Default",
      "url": "https://example",
      "token": "secret",
      "showIncidentDetails": "false",
      "showUEBA": "false",
      "cloudlock_start_date": "20/03/2026"
    },
    "selected_destination_lists": [
      {
        "dest_list_id": "123",
        "dest_list_name": "Important list",
        "role": "cs_admin"
      }
    ],
    "s3_indexes": {
      "dns": "cisco_secure_access_dns",
      "proxy": "cisco_secure_access_proxy",
      "createdDate": "2026/03/20 01:23:45"
    },
    "refresh_rate": "0",
    "orgId": "example-org-id"
  }
}
```

The script writes the same structure to `/update_settings`.

That path is broader than the initial skill scope; the first automation pass
focuses on `org_accounts`.

## Modular Inputs

The package ships these modular input kinds in `inputs.conf.spec`:

- `cloudlock://<name>`
- `cloudlock_health_check://<name>`
- `destination_lists_health_check://<name>`
- `investigate_health_check://<name>`
- `app_discovery://<name>`
- `private_apps://<name>`

The `org_accounts` endpoint provisions the app discovery and private app inputs
for you when the corresponding indexes are supplied.

## Validation Checklist

- `cisco-cloud-security` is installed
- at least one org account exists, or the expected `orgId` can be fetched
- optional `investigate_index`, `privateapp_index`, and `appdiscovery_index`
  fields are present when requested
- terms acceptance exists in `cloudlock-v2-tos`
- `dashboard_settings` and `refresh_rate` are initialized when dashboard defaults are desired
- optional `cloudlock_settings`, `selected_destination_lists`, and `s3_indexes`
  are present when those dashboard features are in scope


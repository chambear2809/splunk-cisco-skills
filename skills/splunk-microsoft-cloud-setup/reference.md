# Microsoft Cloud Add-ons Reference

Grounded in two real packages:

- `splunk_ta_o365` (Splunkbase `4055`, verified `6.0.2`)
- `Splunk_TA_microsoft-cloudservices` (Splunkbase `3110`, verified `6.1.3`)

Note the exact app folder names: the Office 365 add-on installs as the
lowercase `splunk_ta_o365`, and the Microsoft Cloud Services add-on installs as
`Splunk_TA_microsoft-cloudservices` (with a hyphen).

## Office 365 add-on (`splunk_ta_o365`)

Modular inputs: `splunk_ta_o365_management_activity`,
`splunk_ta_o365_service_status`, `splunk_ta_o365_service_message`,
`splunk_ta_o365_cloud_app_security`, `splunk_ta_o365_graph_api`,
`splunk_ta_o365_message_trace`, `splunk_ta_o365_microsoft_entra_id_metadata`.

Management Activity `content_type` values: `Audit.AzureActiveDirectory`,
`Audit.Exchange`, `Audit.SharePoint`, `Audit.General`, `DLP.All`.

Tenant config endpoint: `/servicesNS/nobody/splunk_ta_o365/splunk_ta_o365_tenants`
(`tenant_id`, `client_id`, `client_secret`, `endpoint` WorldWide/USGovGCCHigh,
or certificate auth via `cert_thumbprint` / `cert_private_key`).

Source types: `o365:management:activity`, `o365:metadata` (Entra ID metadata
input), `o365:graph:api`, `o365:graph:messagetrace`, `o365:service:status`,
`o365:service:message`, `o365:cas:api`.

## Microsoft Cloud Services add-on (`Splunk_TA_microsoft-cloudservices`)

Modular inputs: `mscs_storage_table`, `mscs_storage_blob`, `mscs_azure_resource`,
`mscs_azure_audit`, `mscs_azure_event_hub`, `mscs_azure_kql`, `mscs_azure_metrics`,
`mscs_azure_consumption`.

`mscs_azure_audit` fields: `account`, `subscription_id`, `start_time`,
`interval`, `index`. Source type `mscs:azure:audit`.

Azure app account endpoint:
`/servicesNS/nobody/Splunk_TA_microsoft-cloudservices/splunk_ta_mscs_azureaccount`
(`tenant_id`, `client_id`, `client_secret`, `account_name`). Storage account
endpoint: `splunk_ta_mscs_storageaccount`.

## Index Model

| Index | Purpose | Default |
| --- | --- | --- |
| O365 index | Office 365 audit, Graph, service status | `o365` |
| Azure index | MSCS Azure/Entra audit | `azure` |

## CIM Coverage

| Source type | CIM data models |
| --- | --- |
| `o365:management:activity` (Audit.AzureActiveDirectory) | Authentication, Change |
| `o365:management:activity` (Audit.Exchange/SharePoint) | Change |
| `o365:metadata` (Entra metadata) | Identity / Inventory |
| `mscs:azure:audit` | Change |

## Entra / Azure AD Path Selection

- Modern audit + sign-in: prefer the Office 365 add-on Management Activity
  `Audit.AzureActiveDirectory` content type plus the Entra ID metadata Graph
  input.
- Azure subscription management events: use the MSCS `mscs_azure_audit` input.
- Pick one path per data set to avoid duplicate ingestion.

## Account Model (shared)

Both add-ons authenticate with an Entra ID app registration (service principal):

1. Azure portal > Entra ID > App registrations > New registration; record the
   tenant ID and application (client) ID.
2. Add a client secret (or certificate).
3. Grant API permissions:
   - Office 365 Management APIs: `ActivityFeed.Read`, `ActivityFeed.ReadDlp`.
   - Microsoft Graph (Entra metadata): `Directory.Read.All`, `AuditLog.Read.All`
     (application permissions, admin-consented).
4. Register the tenant/account in each add-on Configuration tab; secrets are
   stored encrypted in `storage/passwords`.

## Placement Guardrails

- Run on the search tier or a dedicated heavy forwarder; both add-ons need the
  full Splunk Python runtime and are not Universal-Forwarder safe.
- Store the client secret only via the add-on account, never in conf or argv.

## Handoffs

- `splunk-app-install` installs each package from Splunkbase (`4055`, `3110`).
- `splunk-data-source-readiness-doctor` scores readiness with the
  `microsoft_o365_management_activity` and `microsoft_entra_id` source packs.
- `splunk-observability-azure-integration` covers Azure Monitor **metrics** into
  Splunk Observability Cloud (a different product surface).

## Sources

- https://splunkbase.splunk.com/app/4055
- https://splunkbase.splunk.com/app/3110
- https://help.splunk.com/en/splunk-cloud-platform/get-data-in/splunk-supported-add-ons/microsoft-office-365
- https://help.splunk.com/en/splunk-cloud-platform/get-data-in/splunk-supported-add-ons/microsoft-cloud-services

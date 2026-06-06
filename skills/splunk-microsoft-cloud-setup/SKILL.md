---
name: splunk-microsoft-cloud-setup
description: >-
  Install, render, configure, and validate the Splunk add-ons for Microsoft
  cloud telemetry: the Splunk Add-on for Microsoft Office 365 (splunk_ta_o365,
  Splunkbase 4055) and the Splunk Add-on for Microsoft Cloud Services
  (Splunk_TA_microsoft-cloudservices, Splunkbase 3110). Renders real
  inputs.conf stanzas for Office 365 Management Activity (Entra/Azure AD,
  Exchange, SharePoint, General, DLP), Microsoft Graph Entra ID metadata, and
  Azure audit, emits an Entra app-registration account runbook, creates the
  o365 and azure indexes, maps source types to CIM, and validates ingestion.
  Use when the user asks about Splunk_TA_o365, Office 365, Microsoft 365, Entra
  ID, Azure AD audit/sign-in, Microsoft Graph, Splunk Add-on for Microsoft
  Cloud Services, or Microsoft cloud log onboarding in Splunk.
---

# Microsoft Cloud Add-ons Setup (Office 365, Entra ID, Graph)

Render-first automation for Microsoft cloud log onboarding through two real
Splunk-supported add-ons:

- **Splunk Add-on for Microsoft Office 365** (`splunk_ta_o365`, Splunkbase
  `4055`) - Office 365 Management Activity (including `Audit.AzureActiveDirectory`),
  Microsoft Graph, Entra ID metadata, service status, and message trace.
- **Splunk Add-on for Microsoft Cloud Services** (`Splunk_TA_microsoft-cloudservices`,
  Splunkbase `3110`) - Azure audit, storage, Event Hub, and resource data.

Both authenticate to Microsoft Entra ID (Azure AD) with an app registration.
The add-ons run on the search tier or a dedicated heavy forwarder; they are not
Universal-Forwarder safe.

## Feeds

| Feed | Add-on | Modular input | Source type |
| --- | --- | --- | --- |
| O365 audit (incl. Entra) | `splunk_ta_o365` | `splunk_ta_o365_management_activity` | `o365:management:activity` |
| Entra ID metadata (Graph) | `splunk_ta_o365` | `splunk_ta_o365_microsoft_entra_id_metadata` | `o365:metadata` |
| O365 service status | `splunk_ta_o365` | `splunk_ta_o365_service_status` | `o365:service:status` |
| Azure/Entra audit | `Splunk_TA_microsoft-cloudservices` | `mscs_azure_audit` | `mscs:azure:audit` |

## Credentials

Never paste the Entra client secret in chat or argv. Create an Azure app
registration, then write the client secret to a local file and register it in
each add-on's Configuration tab:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/msentra_client_secret
```

See the rendered `account-setup.md` for the full app-registration runbook,
required Graph / Office 365 Management API permissions, and the exact REST
endpoints.

## Workflow

1. Render reviewable assets (offline):

```bash
bash skills/splunk-microsoft-cloud-setup/scripts/setup.sh --render \
  --o365-index o365 --azure-index azure --tenant-name contoso
```

2. Install the add-ons and create indexes:

```bash
bash skills/splunk-microsoft-cloud-setup/scripts/setup.sh --install --create-index
```

3. Configure the Entra app registration (`account-setup.md`) and enable inputs.

4. Validate:

```bash
bash skills/splunk-microsoft-cloud-setup/scripts/validate.sh
```

5. Score post-ingest readiness:

```bash
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh \
  --phase collect --source-pack microsoft_o365_management_activity
```

Use `--products o365` or `--products mscs` to act on a single add-on. See
`reference.md` for the full input/account model, source types, CIM mapping, and
the Entra/Azure AD path-selection guidance.

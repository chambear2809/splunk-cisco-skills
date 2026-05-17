# AppDynamics ThousandEyes Integration Reference

## Official Surfaces

| Surface | Support boundary | Apply model |
| --- | --- | --- |
| AppDynamics ThousandEyes token | SaaS, On-Premises, Virtual Appliance | AppDynamics UI runbook |
| Dash Studio ThousandEyes widgets | SaaS, On-Premises, Virtual Appliance | AppDynamics UI/runbook |
| EUM ThousandEyes network metrics | SaaS-supported by docs; validate UI elsewhere | AppDynamics UI/runbook |
| ThousandEyes native AppDynamics integration | UI-documented; test recommendations are cSaaS-only | UI runbook unless API is documented |
| TE tests, labels, tags, alert rules, dashboards, templates | ThousandEyes API v7 | Delegated gated apply |
| TE custom webhook fallback | ThousandEyes Integrations API v7 | Gated API plan |
| AppDynamics custom events | AppDynamics Events API | Dry-run probe unless explicitly enabled |

## ThousandEyes API Creation

The skill can create the API-backed pieces in ThousandEyes:

- `POST /v7/connectors/generic` creates a generic connector for the AppDynamics Controller.
- `POST /v7/operations/webhooks` creates the alert webhook operation.
- `PUT /v7/operations/webhooks/{id}/connectors` assigns the connector to the operation.
- `POST /v7/alerts/rules` can create alert rules with `thirdParty` AppDynamics or `customWebhook` notifications when the relevant integration ID exists.
- Tests, labels, tags, dashboards, and templates are delegated to `splunk-observability-thousandeyes-integration`.

The native ThousandEyes AppDynamics integration itself is rendered as a UI
runbook because the public docs describe the setup through `Manage >
Integrations > + New integration > AppDynamics`, not a creation endpoint.

## AppDynamics Custom Event Fallback

The custom webhook fallback targets the documented AppDynamics Events API:

- Method: `POST`
- Path: `/controller/rest/applications/{application_id_or_name}/events`
- Required query values: `summary`, `severity`, `eventtype=CUSTOM`
- Optional custom type: `customeventtype=ThousandEyesAlert`
- Permission: Create Events on the target application

Use OAuth client credentials or another approved AppDynamics API identity.
Secrets must be provided through chmod-600 files at execution time.

## Validation Notes

- For on-premises and Virtual Appliance alert delivery, ThousandEyes cloud must
  reach the Controller URL over trusted TLS.
- For self-signed or private CA lab Controllers, set `APPD_CA_CERT` when running
  the AppDynamics custom event probe.
- For ThousandEyes for Government, do not use Webhook Operations API automation.
- When a native AppDynamics integration ID is known, merge the generated
  `native_appd` notification fragment into alert rules.
- When a custom webhook operation ID is known, merge the generated
  `custom_webhook` notification fragment into alert rules.

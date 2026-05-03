# Integrations 2.0 — Splunk Observability APM connector

Source: TE docs (`Manage > Integrations > Integrations 2.0`) plus the in-repo reference implementation at `/Users/alecchamberlain/Documents/GitHub/network-streaming-app/scripts/thousandeyes/sync-o11y-apm-integration.py`.

## What this is

The Splunk Observability APM operation links ThousandEyes test results into the Splunk APM trace viewer. When a TE synthetic test detects an issue against a target instrumented with Splunk APM, the operator can pivot directly from the TE waterfall view into the matching APM trace.

This is **separate** from the Integration 1.0 OpenTelemetry stream, which sends TE metrics to Splunk Observability Cloud. APM trace linking does not move telemetry — it sets up the cross-product navigation.

## API surface

1. **Generic Connector**: `POST /v7/connectors/generic` with:
   ```json
   {
     "type": "generic",
     "name": "Splunk Observability APM",
     "target": "https://api.us0.signalfx.com",
     "headers": [{"name": "X-SF-Token", "value": "<O11Y_API_TOKEN>"}]
   }
   ```
   The response includes the new connector's `id`.

2. **APM Operation Assignment**: `PUT /v7/operations/splunk-observability-apm/<connector_id>` with:
   ```json
   {
     "type": "splunk-observability-apm",
     "name": "Splunk Observability APM",
     "enabled": true,
     "connectorId": "<connector_id_from_step_1>"
   }
   ```

The skill's `apply-apm-connector.sh` runs both calls in sequence and substitutes the placeholder `${O11Y_API_TOKEN}` from the file referenced by `--o11y-api-token-file`.

## Required Splunk Observability token scope

This connector is used for admin-scoped REST calls (read APM topology, fetch trace details). Per `help.splunk.com/.../authentication-tokens/`, the matching token type is **User API access token** (created by an O11y admin, not Org access token which is ingest-only). Pass it via `--o11y-api-token-file`.

## Why "Integrations 2.0" vs "Integration 1.0"

ThousandEyes uses two parallel integration surfaces. From the TE UI:

- **Manage > Integration > Integration 1.0** — older surface; hosts the OpenTelemetry stream config.
- **Manage > Integrations > Integrations 2.0** — newer surface; hosts the generic connector + per-product operations (including `splunk-observability-apm`).

Both APIs are versioned `v7`. They serve different use cases (telemetry export vs cross-product navigation), so this skill renders both when both are enabled in the spec.

## Validating the link

After `apply-apm-connector.sh` succeeds:

1. In the TE UI, navigate to a recent HTTP-server or transaction test result.
2. Click the "View in Splunk APM" link in the waterfall view (appears after the operation enables).
3. Confirm the link opens the matching APM trace in `https://app.<realm>.signalfx.com`.

If the link is missing:

- Confirm the connector was created: `bash scripts/list-templates.sh` (templates list lives in the same Integrations 2.0 surface) or check `/tmp/te-connector-response.json` for the connector ID.
- Confirm the operation is enabled: GET `/v7/operations/splunk-observability-apm/<connector_id>` should return `enabled: true`.
- Confirm the target URL matches the operator's realm exactly (e.g. `api.us0.signalfx.com`, not `api.us1.signalfx.com`).
- Confirm the token has the right scope (User API access token, not Org access token).

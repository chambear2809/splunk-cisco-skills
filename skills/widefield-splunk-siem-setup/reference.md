# WideField Splunk SIEM Reference

## Public Sources

- Splunk HEC overview: https://help.splunk.com/en?resourceId=Splunk_Data_UsetheHTTPEventCollector
- Splunk HEC REST endpoints: https://help.splunk.com/en/splunk-cloud-platform/get-started/get-data-in/10.2.2510/get-data-with-http-event-collector/http-event-collector-rest-api-endpoints
- Splunk REST API reference overview: https://help.splunk.com/en/splunk-cloud-platform/rest-api-reference
- WideField platform page: https://www.widefield.ai/

## Data Contract

Defaults:

- Index: `widefield`
- Sourcetype: `widefield:security`
- Source: `widefield`
- HEC token name: `widefield_security_hec`

The renderer uses schema-light `spath` searches because WideField event payloads
can evolve. Do not hard-code narrow JSON paths until sample customer events are
available.

The rendered SPL includes coverage checks for identity posture, non-human
identity ownership, human MFA posture, connected application permission risk,
AI identity access, and authentication/session analysis. These searches are
intentionally schema-light and should be tightened only after customer sample
events confirm exact field names.

## Supported Live Actions

With `--apply --accept-apply`, this skill may:

- Create the Splunk index through documented Splunk REST/ACS helpers.
- Delegate HEC token creation to `splunk-hec-service-setup`.
- Install a search-tier macro, saved search, and starter XML dashboard in the
  `search` app.

HEC token values must be file-backed.

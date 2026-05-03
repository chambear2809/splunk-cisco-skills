# REST Endpoint Integration Reference

The REST Endpoint Integration is the **preferred** alert ingestion path for
Splunk On-Call. It accepts JSON HTTPS POSTs from any source and triggers,
acknowledges, or resolves incidents based on the `message_type` field.

## Endpoint URL

```
https://alert.victorops.com/integrations/generic/20131114/alert/{INTEGRATION_KEY}/{ROUTING_KEY}
```

- `{INTEGRATION_KEY}` is generated when the **REST - Generic** integration
  is enabled in Splunk On-Call (Integrations → 3rd Party Integrations →
  REST - Generic). It is sensitive — anyone with this key can create
  incidents. Store it in a chmod-600 file and supply it through
  `--integration-key-file`.
- `{ROUTING_KEY}` selects the destination team via the routing-key database.
  Use a per-team or per-service routing key, never the catch-all default for
  production.

## Required field

| Field | Required | Notes |
|-------|----------|-------|
| `message_type` | yes | One of `CRITICAL`, `WARNING`, `INFO`, `ACKNOWLEDGEMENT`, `RECOVERY` (alias `OK`). Unrecognized values are treated as `INFO`. |

## Recommended fields (incident-fields glossary)

| Field | Notes |
|-------|-------|
| `entity_id` | Incident identity. Reuse across CRITICAL → ACKNOWLEDGEMENT → RECOVERY for the same incident. Defaults to a random string when absent. |
| `entity_display_name` | Human-friendly summary shown in UI and notifications. |
| `state_message` | Verbose body. URLs render as clickable links in email notifications. |
| `routing_key` | Override the URL routing key inside the payload (rarely needed; prefer the URL form). |
| `hostname` | Affected host. |
| `monitoring_tool` | Source label. Drives the logo on the timeline. Manual incidents and REST-API ingestion appear without a logo. |
| `state_start_time` | Linux epoch seconds. Defaults to alert receipt time. |

Any additional fields are passed through to the timeline.

## Annotations

Add up to three annotation types per alert. Keys take the form
`vo_annotate.{u|s|i}.<title>`:

- `vo_annotate.u.<title>` — URL annotation (clickable link).
- `vo_annotate.s.<title>` — Note annotation (plain text).
- `vo_annotate.i.<title>` — Image annotation (image URL).

Each annotation value has a **1,124-character limit** (enforced by the
validator). Annotations are attached to the most recent alert that matches
the open incident's `entity_id`.

## `message_type` semantics

| Value | Behaviour |
|-------|-----------|
| `CRITICAL` | Opens a new incident, runs the routing key's escalation policy, pages users. Subsequent CRITICAL with the same `entity_id` rolls up under the open incident. |
| `WARNING` | May open a new incident depending on team settings. Otherwise posts to the timeline only. |
| `INFO` | Posts to the timeline. Never opens an incident or pages. Useful for context-only events and self-tests. |
| `ACKNOWLEDGEMENT` | Transitions an incident from `UNACKED` to `ACKED` and stops paging. |
| `RECOVERY` (alias `OK`) | Resolves the incident matching `entity_id` and stops escalation. |

## Sample alerts

Trigger:

```json
{
  "message_type": "CRITICAL",
  "entity_id": "disk_space/db01",
  "entity_display_name": "Critically Low Disk Space on DB01",
  "state_message": "The disk is full. Free space is 1%.",
  "monitoring_tool": "splunk",
  "vo_annotate.u.Runbook": "https://runbooks.example.com/disk-space",
  "vo_annotate.s.Note": "Auto-resolves once free space recovers above 10%."
}
```

Acknowledge:

```json
{
  "message_type": "ACKNOWLEDGEMENT",
  "entity_id": "disk_space/db01",
  "state_message": "Investigating from runbook step 2."
}
```

Resolve:

```json
{
  "message_type": "RECOVERY",
  "entity_id": "disk_space/db01",
  "state_message": "Disk space restored to 32% via log rotation."
}
```

## Self-test

`scripts/setup.sh --send-alert --self-test` fires an `INFO` followed by a
`RECOVERY` against the configured integration key without ever creating a
real incident. Use this to verify connectivity and routing-key wiring.

## Generic Email Endpoint Integration

The email endpoint is a separate ingestion path that accepts emails sent to
`<key>+$routing_key@alert.victorops.com`. The skill's `email_alerts`
spec section renders the documented address pattern, a self-test body, and
the matching create / acknowledge / resolve subject-line conventions for
LogEntries, Google Voice, Mailhop, and any monitoring tool restricted to
email.

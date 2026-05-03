# Generic Email Endpoint Integration Reference

The Generic Email Endpoint Integration is a parallel alert ingestion path
that complements the REST Endpoint Integration. It accepts emails sent to a
specially crafted address and creates, acknowledges, or resolves incidents
based on the subject line and body. Use this path when a monitoring tool
cannot speak HTTPS but can send email.

## Address pattern

```
<INTEGRATION_KEY>+<ROUTING_KEY>@alert.victorops.com
```

- `<INTEGRATION_KEY>` is generated when the **Email - Generic** integration
  is enabled in Splunk On-Call (Integrations → 3rd Party Integrations →
  Email - Generic). It is sensitive — anyone with this address can create
  incidents.
- `<ROUTING_KEY>` selects the destination team via the routing-key database.

## Subject-line conventions

| Subject prefix | Behaviour |
|----------------|-----------|
| (default) | Creates a `CRITICAL` incident with the email body as `state_message`. |
| `ACK ` | Acknowledges an existing incident referenced by the email subject's `entity_id` token. |
| `RESOLVE ` or `RECOVERY ` | Resolves the existing incident. |

The first line of the email body is treated as `entity_display_name`; the
remainder becomes `state_message`. Include an explicit `entity_id: <id>` line
in the body to control deduplication.

## When to use it

- **LogEntries** — sends tagged Logentries alerts via this endpoint.
- **Google Voice** — forwards voicemail transcriptions as incidents.
- **Mailhop** — generic mail forwarder for legacy monitoring tools.
- Any SMTP-capable monitoring system that cannot make HTTPS POSTs.

## Skill behaviour

The skill renders the address pattern as a `handoff` with operator steps to:

1. Enable the Email - Generic integration in the On-Call UI.
2. Copy the integration key (treat it as a secret; chmod 600).
3. Configure the source monitoring tool with
   `<key>+<routing-key>@alert.victorops.com`.
4. Send a self-test by emailing a `Subject: TEST` body and verifying the
   timeline.

The skill **never** sends email itself — sending email programmatically with
the integration key would expose the key in mail headers. The handoff
documents the integration but defers sending to the configured monitoring
tool.

## Source

- https://docs.splunk.com/observability/sp-oncall/spoc-integrations/generic-email-endpoint.html

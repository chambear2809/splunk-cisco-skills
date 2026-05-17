# ThousandEyes Alert Rules

Source: `developer.cisco.com/docs/thousandeyes/alertruleconfigurationtemplate`.

The skill renders alert rules as standalone `te-payloads/alert-rules/<slug>.json` payloads ready for `POST /v7/alerts/rules`. Each rule is also embeddable inside a TE Template (see `te-templates.md`).

## Spec shape

```yaml
alert_rules:
  - name: "agent-to-server latency p95"
    test_type: agent-to-server
    expression: "((avgLatency > 200 ms))"
    severity: major             # info | minor | major | critical | unknown
    min_sources: 1              # how many agents must violate
    rounds_violating_required: 3
    rounds_violating_out_of: 5
    notifications: {}           # TE v7 notification object (see below)
```

The renderer rejects the older synthetic `threshold` and `window_seconds` fields. ThousandEyes v7 alert rules are expression based, so encode the metric, comparator, and unit in `expression`.

## Notification objects

TE supports several notification destinations:

- `email` — `{ "email": { "recipients": ["alerts@example.com"] } }`
- `customWebhook` — `{ "customWebhook": [{ "integrationId": "op-id", "integrationType": "custom-webhook", "integrationName": "AppDynamics custom events" }] }`
- `thirdParty` — `{ "thirdParty": [{ "integrationId": "integration-id", "integrationType": "app-dynamics" }] }`
- `webhook` — legacy webhook notification entries for older webhook integrations
- `splunkOnCall` (formerly VictorOps) — preferred for on-call routing; coordinate with `splunk-oncall-setup` if you also need the matching Splunk On-Call escalation policy

For convenience, the spec also accepts a list of shorthand entries with `type: email`, `type: custom-webhook`, `type: webhook`, `type: app-dynamics`, `type: pager-duty`, `type: service-now`, or `type: slack`; the renderer converts them into the v7 notification object.

## Severity → SignalFlow detector mapping

The skill ships starter detectors per test type; the severity in `alert_rules[]` is intentionally separate from the severity rendered in `detectors/<test_type>.yaml` because:

- TE alert rules trigger inside the ThousandEyes platform (TE notifications, dashboard alerts).
- O11y detectors trigger inside Splunk Observability Cloud (Splunk On-Call routing, SignalFlow detectors, native O11y notifications).

For a fully aligned alert posture, define both — the TE alert rule for in-product visibility and the O11y detector for the broader observability stack — at matching severities.

## Avoiding alert duplication

If you wire both the TE alert rule and the matching O11y detector to the same on-call destination, you'll get duplicate pages. Pick one of:

- **TE alert rule routes to TE-side dashboard only**; O11y detector routes to on-call. (Recommended for Splunk-centric orgs.)
- **TE alert rule routes to on-call**; O11y detector is render-only / dashboard-only.
- **Different severities**: TE alert at Warning, O11y detector at Critical, with on-call paged on Critical only.

Document the chosen pattern in your spec's `description` fields.

# ThousandEyes Alert Rules

Source: `developer.cisco.com/docs/thousandeyes/alertruleconfigurationtemplate`.

The skill renders alert rules as standalone `te-payloads/alert-rules/<slug>.json` payloads ready for `POST /v7/alerts/rules`. Each rule is also embeddable inside a TE Template (see `te-templates.md`).

## Spec shape

```yaml
alert_rules:
  - name: "agent-to-server latency p95"
    test_type: agent-to-server
    severity: Warning           # Info | Warning | Major | Critical
    direction: increase         # increase | decrease
    threshold: 200              # numeric value (units depend on metric)
    window_seconds: 120
    min_sources: 1              # how many agents must violate
    rounds_violating_required: 3
    rounds_violating_out_of: 5
    notifications: []           # TE notification objects (see below)
```

## Notification objects

TE supports several notification destinations:

- `email` — `{ "type": "email", "recipients": ["alerts@example.com"] }`
- `webhook` — `{ "type": "webhook", "url": "https://...", "auth": { ... } }`
- `pagerduty`, `servicenow`, `slack`, etc. via Integrations 1.0 / 2.0
- `splunkOnCall` (formerly VictorOps) — preferred for on-call routing; coordinate with `splunk-oncall-setup` if you also need the matching Splunk On-Call escalation policy

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

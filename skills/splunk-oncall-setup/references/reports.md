# Splunk On-Call Reports

Splunk On-Call reports are read-only views in the UI. The skill renders
deterministic deeplinks; there is no public API write surface.

## Available reports

| Report | UI path | Description |
|--------|---------|-------------|
| Post-Incident Review (PIR) | Reports → Post-Incident Review | Build a chronological narrative of an incident with timeline events, transitions, and notes. |
| On-Call Review | Reports → On-Call Review | Summary of on-call shifts, paging volume per user/team, and override frequency. |
| MTTA / MTTR | Reports → MTTA-MTTR | Mean time to acknowledge and resolve, sliced by team and routing key. |
| Team Dashboard | Teams → \<team\> | Live view of incidents, paging targets, and the on-call schedule. Also exposes `Create Incident` for manual incidents and the UI-only `snooze` and `add responder` actions. |
| Similar Incidents | Incident detail → Similar Incidents tab | NLP-based grouping of related incidents (active and historical). |

## Spec shape

```yaml
reports:
  - kind: post_incident_review
    incident_number: 12345
  - kind: on_call_review
    team: Checkout SRE
    days: 14
  - kind: mtta_mttr
    team: Checkout SRE
    days: 30
  - kind: team_dashboard
    team: Checkout SRE
  - kind: similar_incidents
    incident_number: 12345
```

The renderer emits one entry per `kind` in `deeplinks.json` and a matching
checklist line in `handoff.md`. No data is fetched from the public API.

## Programmatic equivalents

- `/api-reporting/v1/team/{team}/oncall/log` — shift change log (use the
  `reporting` spec section for this, not `reports`).
- `/api-reporting/v2/incidents` — incident history (use the `reporting`
  spec section; rate-limited at 1 call/minute).
- The Splunk Add-on for On-Call (Splunkbase 4886) ships pre-built dashboards
  (`vo_incidents`, `vo_oncall`, `vo_sla`, etc.) that can replicate most of
  these reports inside Splunk once the four `victorops_*` indexes are
  populated.

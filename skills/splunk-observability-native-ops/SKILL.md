---
name: splunk-observability-native-ops
description: Use when configuring native Splunk Observability Cloud operations beyond collection and classic dashboards, including detectors, alert routing, On-Call handoffs, APM service maps and traces, RUM session workflows, Synthetic tests and waterfall artifacts, and modern logs chart handoffs.
---

# Splunk Observability Native Ops

Use this skill for native Splunk Observability Cloud operations that are not
covered by the OTel Collector deployment skill or the classic dashboard builder.

The workflow is render-first by default. Live API changes only happen when the
user explicitly asks for `--apply`.

## Coverage Model

Every rendered object gets an explicit coverage status:

- `api_apply`: a documented public API supports create, update, delete, or validate.
- `api_validate`: a documented public API supports read or validation only.
- `deeplink`: the skill renders a deterministic Observability UI link and validates
  referenced data where an API allows.
- `handoff`: the skill renders deterministic operator steps for UI-only or app-side
  workflows.

Do not mark UI-only workflows as `api_apply`.

## Safety Rules

- Never ask for Splunk Observability tokens, passwords, or client secrets in
  conversation.
- Never pass tokens or API keys on the command line or as environment-variable
  prefixes.
- Use `--token-file` for Splunk Observability API tokens.
- Prefer `SPLUNK_O11Y_REALM` and `SPLUNK_O11Y_TOKEN_FILE` from the repo
  `credentials` file when present.
- Reject direct secret flags such as `--token`, `--access-token`, `--api-token`,
  and `--sf-token`.

Splunk On-Call API actions, the REST endpoint integration, the generic email
endpoint, and the Splunk-side companion apps (Splunkbase 3546, 4886, 5863) all
live in the dedicated `splunk-oncall-setup` skill. This skill renders only a
deeplink-only handoff for the `on_call` section.

## Primary Workflow

1. Collect non-secret values: realm, detector names, team names, service names,
   environment filters, test IDs, trace IDs, Log Observer query text, and On-Call
   schedule names.
2. Create or update a JSON/YAML spec using
   `templates/native-ops.example.yaml` as the starting point.
3. Render and validate:

   ```bash
   bash skills/splunk-observability-native-ops/scripts/setup.sh \
     --render \
     --validate \
     --spec skills/splunk-observability-native-ops/templates/native-ops.example.yaml \
     --output-dir splunk-observability-native-rendered \
     --realm us0
   ```

4. Review `coverage-report.json`, `apply-plan.json`, `deeplinks.json`, and
   `handoff.md`.
5. Apply only when explicitly requested. Point `--spec` at the same file you
   rendered and validated (an absolute path, a repo-relative path like
   `skills/splunk-observability-native-ops/templates/native-ops.example.yaml`,
   or a working copy you maintain alongside your credentials):

   ```bash
   bash skills/splunk-observability-native-ops/scripts/setup.sh \
     --apply \
     --spec skills/splunk-observability-native-ops/templates/native-ops.example.yaml \
     --realm us0 \
     --token-file /tmp/splunk_o11y_token
   ```

## Supported Sections

Specs use `api_version: splunk-observability-native-ops/v1` and can include:

- `teams`: Observability teams and notification policy payloads.
- `detectors`: SignalFlow detector definitions, rules, notifications, teams,
  runbook URLs, tags, and min/max delay.
- `alert_routing`: integrations, detector-recipient updates, team notification
  policy updates, and handoffs for external routing.
- `muting_rules`: alert muting rules.
- `slo_links`: SLO payloads or links to existing SLOs.
- `synthetics`: Synthetic browser, API, HTTP, SSL, and port tests; locations;
  downtime windows; variables; run-now requests; run/artifact retrieval plans.
- `apm`: service topology, service-map deeplinks, trace download plans, Trace
  Analyzer deeplinks, and business workflow handoffs.
- `rum`: session search deeplinks, replay setup handoffs, and RUM/APM links.
- `logs`: modern logs-chart intent handoffs using SPL1, SPL2, or JSON query specs.
- `on_call`: deeplink-only handoff that points operators to the dedicated
  `splunk-oncall-setup` skill. Use that skill for teams, users, rotations,
  escalation policies, routing keys, paging policies, alert rules, maintenance
  mode, incidents, REST endpoint alerts, and Splunk-side companion app
  installs (Splunkbase 3546, 4886, 5863).

For API endpoint details and current support boundaries, read
`references/coverage.md` when the request touches a new or ambiguous surface.

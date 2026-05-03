---
name: splunk-observability-dashboard-builder
description: Use when creating, planning, rendering, validating, or applying Splunk Observability Cloud dashboards from natural-language dashboard requests, JSON or YAML dashboard specs, SignalFlow chart definitions, or Observability dashboard-as-code workflows. Supports native classic Observability dashboard/chart APIs with render-first safety; treats modern dashboard sections, logs charts, service maps, and Dashboard Studio as advisory/secondary paths unless a verified API is available.
---

# Splunk Observability Dashboard Builder

## Overview

Use this skill to turn a user's natural-language dashboard idea into a reviewed Splunk Observability Cloud dashboard specification, rendered API payloads, and optionally an applied native Observability dashboard.

The default path is **classic-api**: create custom dashboard groups, charts, and dashboards through the documented `/v2/dashboardgroup`, `/v2/chart`, and `/v2/dashboard` APIs. Modern dashboard features are documented as UI/advisory unless a public API is verified before use.

## Safety Rules

- Never ask for Splunk Observability API tokens, org access tokens, session tokens, passwords, or client secrets in conversation.
- Never pass tokens on the command line or as environment-variable prefixes.
- Require `--token-file` for live API operations.
- Reject direct token flags such as `--token`, `--access-token`, `--api-token`, `--o11y-token`, and `--sf-token`.
- Prefer `SPLUNK_O11Y_REALM` and `SPLUNK_O11Y_TOKEN_FILE` from the repo `credentials` file when present; these store only the realm and token-file path, not the token value.
- Render and validate before apply. Apply only when the user explicitly requests it.
- Create new custom dashboards by default. Do not update existing charts or dashboards unless the user explicitly asks and the current object is fetched first.

## Primary Workflow

1. Interpret the request:
   - Identify audience, decision workflow, services or infrastructure scope, time range, dashboard group, filters, and desired visuals.
   - Ask only for missing non-secret values: realm, dashboard group name or ID, service/environment/cluster names, preferred dimensions, and target time range.
   - For vague requests, produce a starter dashboard and mark assumptions in the spec comments or final explanation.

2. Ground the dashboard in live metadata when possible:
   - Use `scripts/setup.sh --discover-metrics --realm <realm> --token-file <file> --query <term>` to discover metric names. Omit realm/token flags when `SPLUNK_O11Y_REALM` and `SPLUNK_O11Y_TOKEN_FILE` are configured in `credentials`. Simple bare terms such as `latency` are converted to `sf_metric:*latency*`.
   - Use metric and dimension names returned by the API instead of inventing names.
   - If live metadata is unavailable, render a reviewable draft and clearly mark metric names as assumptions.

3. Write or update a JSON or YAML spec:
   - Start from `templates/dashboard.example.json` for a dependency-free example, or `templates/dashboard.example.yaml` when PyYAML is installed.
   - Keep `mode: classic-api` for renderable native Observability dashboards.
   - Use `mode: modern-ui-advisory` or `mode: dashboard-studio-advisory` only to document UI/manual work.

4. Validate and render:

   ```bash
   bash skills/splunk-observability-dashboard-builder/scripts/setup.sh \
     --render \
     --spec skills/splunk-observability-dashboard-builder/templates/dashboard.example.json \
     --output-dir splunk-observability-dashboard-rendered
   ```

5. Review the rendered plan:
   - `metadata.json` summarizes coverage, assumptions, and warnings.
   - `charts/*.json` contains chart API payloads.
   - `dashboard.json` contains the dashboard API payload with chart placeholders.
   - `apply-plan.json` records the creation sequence without secrets.

6. Apply only when explicitly requested:

   ```bash
   bash skills/splunk-observability-dashboard-builder/scripts/setup.sh \
     --apply \
     --spec my-dashboard.json \
     --realm us0 \
     --token-file /tmp/splunk_o11y_api_token
   ```

   > **WARNING: `--apply` always CREATES new dashboard groups, charts, and
   > dashboards in this version.** It does not GET-then-PUT to update
   > existing objects, so re-running `--apply` against the same spec will
   > produce duplicate dashboards in Splunk Observability Cloud. To update
   > an existing dashboard, follow the manual fetch-modify-PUT workflow in
   > the **Update Existing Objects** section below, or wait for the v2
   > reconciler that supports id-based updates.
   >
   > `--dry-run` is non-destructive and skips both the API calls and the
   > readable-token-file requirement, so CI preview-only jobs do not need
   > a real token path on disk. Live `--apply` retries 429/502/503/504
   > automatically with exponential backoff (cap: 4 attempts; honors
   > `Retry-After` when present).

## Coverage Rules

- **Fully renderable through classic-api**: custom dashboard groups, custom dashboards, TimeSeriesChart, SingleValue, List, TableChart, Heatmap, Text charts, event overlays, dashboard filters/variables, chart time ranges, units, legends, thresholds, and detector links represented by chart properties.
- **Documented but not currently API-rendered by this skill**: pie/donut charts and event feed charts. Current product docs list them, but this renderer needs a verified classic `/v2/chart` schema before applying them. Use `modern-ui-advisory` or Text/link notes for now.
- **Metric-derived coverage**: Infrastructure Monitoring, Kubernetes/cloud infrastructure, Database Monitoring, APM service RED metrics, RUM Browser/Mobile metrics, Synthetic Monitoring metrics, Log Observer Connect metrics/log links, custom business metrics, AI Infrastructure Monitoring, and AI Agent/APM metrics when the required metrics are present.
- **Advisory/link-only coverage**: trace waterfalls, RUM sessions and session replay, synthetic waterfall detail, database explain plans, alerts/detector management, On-Call workflows, Observability Cloud for Mobile app workflows, product-native navigators, modern dashboard sections/subsections, service maps, and modern logs charts. Do not claim API rendering for these without verifying a public API first.
- **Dashboard Studio**: keep as a secondary path. It has Splunk platform version, realm, capability, trial, Unified Identity, and import limitations. Do not mix it into the native Observability apply path.

Read `references/coverage.md` for the full product coverage matrix and `references/classic-api.md` for API field guidance.

YAML specs require PyYAML in the Python interpreter used by `scripts/setup.sh`. Install repo dependencies with `python3 -m pip install -r requirements-agent.txt`, or use JSON specs.

## Spec Guidance

- Prefer one dashboard per operational question. Put broad estate overviews and incident drilldowns in separate dashboards.
- Use dashboard variables for common drilldowns such as `sf_environment`, `service.name`, `k8s.cluster.name`, `k8s.namespace.name`, `host.name`, `cloud.region`, and `deployment.environment`.
- Choose chart types intentionally:
  - TimeSeriesChart for trends, rates, latency, throughput, saturation.
  - SingleValue for current health, active alerts, SLO/error-budget snapshots, latest values.
  - List or TableChart for top-N entities and inventory/status summaries.
  - Heatmap for distributions and dense population comparisons.
  - Text for operator notes, runbook links, and assumptions.
- Use `modern-ui-advisory` for pie/donut, event feed, logs, service map, section/tab, or other modern-only visualizations until the public API schema is verified.
- Every non-text chart must include SignalFlow with at least one `publish()` output.
- Keep layouts within a 12-column grid. The validator rejects collisions and out-of-range chart positions.

## Update Existing Objects

For existing charts or dashboards, use fetch-modify-put semantics:

1. Fetch the existing object with the API.
2. Modify only the intended properties.
3. PUT the complete object back.

Do not create partial PUT payloads. The Observability chart API can null or remove writable properties omitted from updates.

## Scripts

- `scripts/setup.sh` - shell entrypoint for render, validate, discover, and apply.
- `scripts/render_dashboard.py` - validates specs and renders classic API payloads.
- `scripts/validate_dashboard.py` - static validation for specs or rendered payloads.
- `scripts/o11y_dashboard_api.py` - live API client using token files only.

## Useful Commands

Validate a draft spec:

```bash
bash skills/splunk-observability-dashboard-builder/scripts/setup.sh \
  --validate \
  --spec skills/splunk-observability-dashboard-builder/templates/dashboard.example.json
```

Render without applying:

```bash
bash skills/splunk-observability-dashboard-builder/scripts/setup.sh \
  --render \
  --spec skills/splunk-observability-dashboard-builder/templates/dashboard.example.json \
  --output-dir splunk-observability-dashboard-rendered
```

Discover metrics before writing SignalFlow:

   ```bash
   bash skills/splunk-observability-dashboard-builder/scripts/setup.sh \
     --discover-metrics \
     --query latency
   ```

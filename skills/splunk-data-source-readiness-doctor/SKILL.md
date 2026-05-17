---
name: splunk-data-source-readiness-doctor
description: >-
  Diagnose whether onboarded Splunk data sources are usable by Enterprise
  Security, ITSI, Asset and Risk Intelligence, CIM, OCSF, and dashboards.
  Use when the user asks for data-source readiness, ES/ITSI/ARI readiness
  scoring, CIM or OCSF validation, data-model acceleration checks, dashboard
  population checks, ingest pipeline health, knowledge-object enrichment,
  federated data usability, ITSI summary health, or fix handoffs after
  app/input setup.
---

# Splunk Data Source Readiness Doctor

This skill proves that already-onboarded data is usable by the consumers that
matter after installation: **ES**, **ITSI**, **ARI**, **CIM**, **OCSF**, and
dashboards. It does not install apps or mutate Splunk. It consumes evidence from
live searches, the shared app registry, expected index/sourcetype/macro
contracts, sample-event summaries, CIM tags/eventtypes, data model acceleration
state, OCSF transform status, and product-specific readiness signals.
It also applies bundled source-specific packs for common sources such as AWS
CloudTrail, Amazon Security Lake OCSF, Cisco ASA, Cisco Secure Firewall, Cisco
Secure Access, Kubernetes Audit, Linux secure/auditd, Microsoft 365 management
activity, Windows Security events, Okta, Microsoft Entra ID, Google Workspace,
CrowdStrike, Palo Alto Networks, Zscaler, AWS VPC Flow Logs, AWS Security
Hub/GuardDuty, Duo, GitHub audit logs, and Fortinet FortiGate.
Those readiness signals include ES correlation/content activation, SSE data
inventory and CIM compliance outputs, ITSI KPI threshold/entity-split/runtime
state, ITSI Event Analytics, metrics/mstats readiness, ES risk/threat/ESCU
readiness, Dashboard Studio data-source health, ARI
relevant-event/key-field/event-search evidence, ingest pipeline and latency
evidence, lookup/field-alias/calculated-field enrichment, federated/remote
dataset usability, ITSI summary-index health, scheduled content execution, and
retention/lookback coverage. Live collection can now synthesize source evidence
and a dashboard/content dependency graph from read-only REST export results.

## Agent Behavior

Never ask for passwords, session keys, API keys, HEC tokens, or bearer tokens in
chat. Keep all credentials in local files and pass only file paths to the
underlying collection workflows.

Use this doctor after an input/app setup skill says ingestion is configured, or
when dashboards, ES detections, ITSI services, ARI inventories, or CIM/OCSF
content are not producing useful results.

Safety model:

- `doctor`, `fix-plan`, `validate`, `status`, `source-packs`, `collect`, and
  `synthesize` are read-only.
- `collect` renders a collector manifest and can optionally run read-only
  Splunk REST export searches when given `--splunk-uri` and a local
  `--session-key-file`.
- `synthesize` consumes `live-collector-results.redacted.json` or
  `--collector-results-file`, writes synthesized evidence, and reruns scoring
  without querying Splunk.
- `apply` renders local handoff/support packets for selected finding IDs only.
- The doctor does not create indexes, alter macros, enable searches, rebuild
  data models, install apps, activate ARI data sources, import ITSI objects, or
  change ES configuration.
- Remediation routes to mature skills such as `splunk-enterprise-security-config`,
  `splunk-itsi-config`, `splunk-asset-risk-intelligence-setup`,
  `splunk-hec-service-setup`, `splunk-app-install`, and product setup skills.

## Quick Start

Validate catalog coverage:

```bash
bash skills/splunk-data-source-readiness-doctor/scripts/validate.sh
```

Render a readiness report from evidence:

```bash
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh \
  --phase doctor \
  --evidence-file skills/splunk-data-source-readiness-doctor/fixtures/comprehensive_unready.json
```

List source-specific packs:

```bash
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh \
  --phase source-packs \
  --json
```

Render a source-specific collection manifest without live credentials:

```bash
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh \
  --phase collect \
  --source-pack aws_cloudtrail \
  --evidence-file evidence.json
```

Synthesize live collector rows into evidence and refreshed scoring:

```bash
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh \
  --phase synthesize \
  --evidence-file evidence.json \
  --collector-results-file splunk-data-source-readiness-doctor-rendered/live-collector-results.redacted.json \
  --json
```

Preview selected handoff packets:

```bash
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh \
  --phase apply \
  --evidence-file skills/splunk-data-source-readiness-doctor/fixtures/comprehensive_unready.json \
  --fixes DSRD-CIM-TAG-EVENTTYPE-GAP,DSRD-DM-ACCELERATION-GAP \
  --dry-run \
  --json
```

## Outputs

The default output directory is `splunk-data-source-readiness-doctor-rendered/`:

- `readiness-report.md` and `readiness-report.json`
- `fix-plan.md` and `fix-plan.json`
- `coverage-report.json`
- `registry-projection.json`
- `source-pack-catalog.json`
- `source-pack-report.json`
- `collector-manifest.json`
- `collection-searches.spl`
- `live-collector-results.redacted.json` from `collect`
- `evidence/live-evidence.synthesized.json` from `collect` or `synthesize`
- `dashboard-dependency-graph.json`
- `synthesis-report.json`
- `evidence/input-evidence.redacted.json`
- `handoffs/*.md` for delegated or direct fix packets
- `support-tickets/*.md` for manual/support packets

Read `reference.md` before changing rule coverage, target scoring, evidence
shape, registry consumption, or apply behavior.

---
name: splunk-admin-doctor
description: >-
  Diagnose Splunk Cloud Platform and Splunk Enterprise administration health,
  render full-coverage doctor reports, and create selected safe fix packets.
  Use when the user asks for a Splunk admin doctor, health audit, full feature
  coverage check, production-safe remediation plan, Cloud/Enterprise admin
  troubleshooting, or routing to existing Splunk admin skills.
compatibility: "Splunk Cloud Platform 10.5.2605: supported. Self-managed paths retain the verified public 10.4 baseline where applicable."
metadata:
  splunk_cloud_10_5: "supported"
  compatibility_verified: "2026-07-02"
---

# Splunk Admin Doctor

This skill diagnoses major Splunk administration domains and renders a
conservative fix plan. It supports Splunk Cloud Platform and self-managed
Splunk Enterprise, classifying every domain as `direct_fix`, `delegated_fix`,
`manual_support`, `diagnose_only`, or `not_applicable`.

Coverage and health are deliberately separate:

- `remediation_coverage` says whether the repository has a safe route for a
  feature.
- `assessment` says `healthy`, `finding`, `partial`, `unknown`, or
  `not_applicable` from the supplied evidence.
- `evidence_status` says whether every applicable rule was actually assessed.
- `SAD-EVIDENCE-INCOMPLETE` prevents missing evidence from appearing healthy.
- Optional/unlicensed capabilities can be explicitly excluded through boolean
  `applicability.rules` or `applicability.domains` evidence maps; omission alone
  never implies not applicable.

The catalog also resolves detected product footprints to exact Security, ITSI,
SOAR, Observability, On-Call, AppDynamics, Cisco, AI/ML, MCP, WideField, and
Galileo routers. Catalog validation fails when any repository skill lacks an
explicit disposition or a delegated handoff no longer exists.

## Agent Behavior

Never ask for passwords, tokens, API keys, or other secrets in chat. Do not pass
secret values on the command line. Use existing repo credentials files and
secret-file paths only.

The doctor is intentionally conservative:

- `doctor` and `fix-plan` are read-only with respect to Splunk; they write
  local report artifacts and remain conservatively mutation-gated by MCP.
- `apply` requires explicit `--fixes FIX_ID[,FIX_ID]`.
- `apply --dry-run` previews only.
- `--require-complete-evidence` exits `3` when any applicable rule remains
  unassessed; `--strict` exits `2` for high/critical findings.
- v1 does not run restarts, deletions, certificate rotations, cluster
  operations, user/role deletion, KV Store cleanup, or backup uploads.
- Specialized work is routed to existing mature skills such as ACS allowlists,
  HEC, Monitoring Console, Agent Management, Workload Management, SmartStore,
  PKI, public exposure hardening, license manager, app install, and indexer
  cluster setup.

## Quick Start

Run an Enterprise doctor report:

```bash
bash skills/splunk-admin-doctor/scripts/setup.sh \
  --phase doctor \
  --platform enterprise \
  --splunk-home /opt/splunk
```

Render a fix plan from saved evidence:

```bash
bash skills/splunk-admin-doctor/scripts/setup.sh \
  --phase fix-plan \
  --evidence-file skills/splunk-admin-doctor/fixtures/enterprise_unhealthy.json
```

Preview selected fix packets:

```bash
bash skills/splunk-admin-doctor/scripts/setup.sh \
  --phase apply \
  --fixes SAD-CONNECTIVITY-REST-DENIED \
  --dry-run \
  --json
```

Run the continuous live validation loop against the canonical on-prem profile:

```bash
python3 skills/splunk-admin-doctor/scripts/live_validate_all.py \
  --profile onprem_2535 \
  --allow-apply \
  --watch \
  --watch-interval-seconds 1800
```

The live runner's `--allow-apply` mode is currently limited to rendering a
local doctor fix plan. Previous remote MC/HEC/WLM and Observability mutation
smokes are disabled until target-bound snapshots, cleanup-in-finally behavior,
and byte-for-byte rollback are implemented and tested.

## Outputs

The default output directory is `splunk-admin-doctor-rendered/`:

- `doctor-report.md` and `doctor-report.json`
- `fix-plan.md` and `fix-plan.json`
- `coverage-report.json`
- `evidence/input-evidence.redacted.json`
- `handoffs/*.md` for direct and delegated fix packets
- `support-tickets/*.md` for manual/support packets

The live validation runner writes checkpointed, sanitized evidence under
`splunk-live-validation-runs/`:

- `checkpoint.json` for resume-safe apply steps
- `runs/<timestamp>/ledger.jsonl` with one row per command
- `runs/<timestamp>/evidence/*.redacted.json`
- `runs/<timestamp>/final-report.json` and `.md`

One-shot and bounded/watch exits reflect the final completed sweep: if its
totals contain any hard failures, the runner exits nonzero.

`coverage-report.json` includes domain assessments, expected and unassessed
evidence paths, product routes, and the exhaustive repository-skill
disposition map. A supported feature with missing evidence is `unknown`, never
implicitly healthy.

Read `reference.md` before changing rule coverage, adding a new fix kind, or
expanding apply behavior.

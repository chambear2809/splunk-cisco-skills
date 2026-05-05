---
name: splunk-admin-doctor
description: >-
  Diagnose Splunk Cloud Platform and Splunk Enterprise administration health,
  render full-coverage doctor reports, and create selected safe fix packets.
  Use when the user asks for a Splunk admin doctor, health audit, full feature
  coverage check, production-safe remediation plan, Cloud/Enterprise admin
  troubleshooting, or routing to existing Splunk admin skills.
---

# Splunk Admin Doctor

This skill diagnoses major Splunk administration domains and renders a
conservative fix plan. It supports Splunk Cloud Platform and self-managed
Splunk Enterprise, classifying every domain as `direct_fix`, `delegated_fix`,
`manual_support`, `diagnose_only`, or `not_applicable`.

## Agent Behavior

Never ask for passwords, tokens, API keys, or other secrets in chat. Do not pass
secret values on the command line. Use existing repo credentials files and
secret-file paths only.

The doctor is intentionally conservative:

- `doctor` and `fix-plan` are read-only report phases.
- `apply` requires explicit `--fixes FIX_ID[,FIX_ID]`.
- `apply --dry-run` previews only.
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

Read `reference.md` before changing rule coverage, adding a new fix kind, or
expanding apply behavior.

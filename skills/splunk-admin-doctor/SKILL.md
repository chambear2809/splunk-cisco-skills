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
  never implies not applicable. Baseline health domains and rules cannot be
  excluded through these maps.

The catalog also resolves detected product footprints to exact Security, ITSI,
SOAR, Observability, On-Call, AppDynamics, Cisco, AI/ML, MCP, WideField, and
Galileo routers. Catalog validation fails when any repository skill lacks an
explicit disposition or a delegated handoff no longer exists.

## Agent Behavior

Never ask for passwords, tokens, API keys, or other secrets in chat. Do not pass
secret values on the command line. Use existing repo credentials files and
secret-file paths only. Evidence and generated artifacts reject symlink and
hardlink destinations, use bounded reads and writes, and are rendered
owner-only.

Platform and target identity fail closed. Supply `--platform cloud` or
`--platform enterprise` for normal operation. `--platform auto` is accepted
only when the evidence JSON declares `platform` or a strict HTTPS management
hostname ends in `.splunkcloud.com`; every other ambiguous case fails instead
of silently defaulting to Enterprise. If `--splunk-uri` is supplied, it must be
a credential-free HTTPS management origin with a valid hostname and optional
numeric port. Userinfo, non-root paths, query strings, and fragments are
rejected before collection or rendering.

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
  --platform enterprise \
  --evidence-file skills/splunk-admin-doctor/fixtures/enterprise_unhealthy.json
```

Preview selected fix packets:

```bash
bash skills/splunk-admin-doctor/scripts/setup.sh \
  --phase apply \
  --platform cloud \
  --evidence-file skills/splunk-admin-doctor/fixtures/cloud_acs_rest_denied.json \
  --fixes SAD-CONNECTIVITY-REST-DENIED \
  --dry-run \
  --json
```

Preview a live sweep against the canonical named on-prem profile before making
any request:

```bash
python3 skills/splunk-admin-doctor/scripts/live_validate_all.py \
  --profile onprem_2535 \
  --platform enterprise \
  --max-retained-runs 50 \
  --plan-only
```

After reviewing the plan, run one bounded validation sweep:

```bash
python3 skills/splunk-admin-doctor/scripts/live_validate_all.py \
  --profile onprem_2535 \
  --platform enterprise \
  --max-retained-runs 50 \
  --once
```

The live runner's `--allow-apply` mode is currently limited to rendering a
local doctor fix plan. Previous remote MC/HEC/WLM and Observability mutation
smokes are disabled until target-bound snapshots, cleanup-in-finally behavior,
and byte-for-byte rollback are implemented and tested.

Before any live request, the runner requires an existing named profile, an
unambiguous Cloud/Enterprise platform resolved from the request or profile, a
credential-free HTTPS management origin, and TLS verification. Conflicts fail
before REST or SSH probes. Legacy flat credential files are rejected unless the
operator explicitly adds `--allow-flat-credentials`; that compatibility flag
must not be used when a named profile can be created. One bounded evidence
sweep feeds the doctor and baseline gate; the runner does not repeat the same
REST/SSH probes as separate validation steps.

Child-skill validation defaults to checked-in `--help` interface checks. Add
`--allow-offline-smoke` only to run checked-in offline smoke entrypoints.
Source-discovered live phases are rejected until the repository has an audited,
checked-in command safety manifest; a source-text match is not proof that a
phase is mutation-free. Interface-only success is reported as
`interface-pass`, never as feature validation.

`template.example` is a non-secret human worksheet, not a CLI spec file. Pass
its values through the documented flags and supply machine evidence as JSON
with `--evidence-file`.

## Outputs

The default output directory is `splunk-admin-doctor-rendered/`:

- `doctor-report.md` and `doctor-report.json`
- `fix-plan.md` and `fix-plan.json`
- `coverage-report.json`
- `artifact-manifest.json` with the committed bundle's artifact hashes
- `evidence/normalized-evidence.redacted.json`
- `evidence/collection-notes.md` with source provenance and redacted collector notes
- `handoffs/*.md` for direct and delegated fix packets
- `support-tickets/*.md` for manual/support packets

The normalized evidence artifact contains the redacted, validated evidence
used for rule evaluation, including documented derived fields. It is not a
byte-for-byte copy of an operator's source file. A non-blocking output lock
serializes the whole bundle, and status verifies the integrity manifest before
trusting any report. The obsolete `evidence/input-evidence.redacted.json` name
is removed on the next committed render; consumers must use the normalized
filename.

The live validation runner writes bounded, sanitized evidence under
`splunk-live-validation-runs/`:

- `checkpoint.json` for bounded audit history; it is not an execution cache
- `runs/<unique-run-id>/ledger.jsonl` with one row per planned or executed step
- `runs/<unique-run-id>/evidence/*.redacted.json`
- `runs/<unique-run-id>/final-report.json` and `.md`

The output namespace is protected by a non-blocking process lock. Run IDs
include time, iteration, process ID, and randomness. Checkpoint history is
private, bounded, and schema-checked, but every current-run apply render is
regenerated; prior step results and artifacts are never reused as current-run
success. The runner retains at most 50 recognized run directories in total by
default, always preserving the current run; stale or incomplete non-current
runs count toward the bound, and the oldest are pruned at safe lifecycle
points. Change the positive bound with `--max-retained-runs`.
Command output and REST bodies are bounded, stdin is disabled, and
timeout/interrupt handling terminates the whole child process group before
finalizing the report.

One-shot and bounded/watch exits reflect the final completed sweep: if its
totals contain any hard failures, the runner exits nonzero.

`--phase status` separates report validity from deployment health. A readable,
schema-valid report can still contain findings or incomplete evidence.
`report_valid` is the schema/readability result; deprecated `ok` is only its
alias. `healthy`, `evidence_complete`, `severity_counts`, and `health_status`
carry the assessment. `health_status` is one of `healthy`, `findings`,
`incomplete`, or `findings_and_incomplete`; never treat `report_valid` or `ok`
alone as a healthy deployment. `strict_ready` mirrors the complete-evidence
plus high/critical-finding gate used for strict automation, and
`integrity_verified` confirms the committed artifact bundle matched its
manifest. Status exits `0` for any valid bundle, including an unhealthy one;
automation must gate on the assessment fields rather than the process exit
alone.

`coverage-report.json` includes domain assessments, expected and unassessed
evidence paths, product routes, and the exhaustive repository-skill
disposition map. A supported feature with missing evidence is `unknown`, never
implicitly healthy.

Read `reference.md` before changing rule coverage, adding a new fix kind, or
expanding apply behavior.

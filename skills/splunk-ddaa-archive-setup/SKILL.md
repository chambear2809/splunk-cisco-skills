---
name: splunk-ddaa-archive-setup
description: "Use when the user asks to archive expired Splunk Cloud index data to the Splunk-managed archive, set or
  change DDAA archival retention, restore archived data, or move an index onto Splunk Archive. Not for
  DDSS self-storage or generic index administration, which live in splunk-cloud-acs-admin-setup. Render,
  validate, and apply Splunk Cloud Platform Dynamic Data Active Archive (DDAA): per-index archival
  retention via the ACS index splunkArchivalRetentionDays setting, retention math validation, and restore
  and disable runbooks for the Splunk Web-only operations."
compatibility: "Splunk Cloud Platform 10.5.2605: conditional. Follow documented package, entitlement, topology, and customer-managed runtime guardrails; self-managed paths remain on the public 10.4 baseline."
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-07-02"
---

# Splunk Cloud DDAA Archive Setup

## Prerequisites

| Tool or access | Purpose | Verify |
|---|---|---|
| Bash and Python 3 | Run bundled setup and validation helpers | `bash --version && python3 --version` |
| Required product/platform access | Inspect or configure the selected target | Complete the documented preflight |
| Credential files for live modes | Keep secrets out of chat | Verify paths only |

## Workflow Overview

```text
┌───────────┐   ┌───────────────┐   ┌───────────────┐   ┌─────────────────┐
│ Preflight │ → │ Render/review │ → │ Apply/handoff │ → │ Validate evidence │
└───────────┘   └───────────────┘   └───────────────┘   └─────────────────┘
```

## When to Activate

- Archive expired Splunk Cloud index data to the Splunk-managed archive, set or change DDAA archival retention,
  restore archived data, or move an index onto Splunk Archive. Not for DDSS self-storage or generic index
  administration, which.
- Preview and review the splunk ddaa archive setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-ddaa-archive-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-ddaa-archive-setup/scripts/validate.sh --help
```

Expected output: offline, live, and completion options are displayed when the
skill supports them; help exits without mutation.

## Troubleshooting

| Issue | Cause | Resolution |
|---|---|---|
| Preflight fails | A required tool or access path is missing | Resolve it before rendering or applying |
| Rendered assets are incomplete | Required non-secret inputs are absent | Complete intake and render again |
| Apply is blocked | Review, credentials, or explicit acceptance is missing | Use the documented handoff |
| Validation is incomplete | Live evidence is unavailable | Record the gap and keep completion open |

This skill renders and applies Dynamic Data Active Archive policy for Splunk
Cloud indexes. It is render-first because archival retention is a durable
storage policy counted from index creation.

## Agent Behavior

Never ask for secrets; ACS auth uses the project `credentials` file and the
configured stack. Applying archival retention refuses to run without
`--accept-archive-retention`. Restore and disable have no ACS API and are
emitted as Splunk Web runbooks.

## Quick Start

Render a DDAA policy (90 searchable days, 365 total):

```bash
bash skills/splunk-ddaa-archive-setup/scripts/setup.sh --index netfw --searchable-days 90 --archival-retention-days 365
```

Apply it via ACS (gated):

```bash
bash skills/splunk-ddaa-archive-setup/scripts/setup.sh --phase apply \
  --index netfw --searchable-days 90 --archival-retention-days 365 --accept-archive-retention
```

## What It Renders

- `acs-payload.json` - ACS index body with `splunkArchivalRetentionDays`
- `restore-runbook.md` - Splunk Web restore steps (30-day searchable copy, <=10% DDAS)
- `disable-runbook.md` - Splunk Web disable steps (no API)
- `status.sh` - `acs indexes describe <index>`

## Rules

- `splunkArchivalRetentionDays` is the TOTAL retention including the searchable
  period, counted from index creation, and must exceed searchable days and be
  <= 3650 days (10 years).
- DDAA must be enabled for the stack; if Splunk Archive is greyed out, contact
  your Splunk account team.
- Generic index CRUD and DDSS self-storage are handled by
  `splunk-cloud-acs-admin-setup`.

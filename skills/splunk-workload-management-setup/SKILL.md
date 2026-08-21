---
name: splunk-workload-management-setup
description: "Use when the user asks to reserve search or ingest resources, configure workload_pools.conf,
  workload_rules.conf, workload_policy.conf, cgroups prerequisites, long-running search guardrails, or
  admission control for expensive searches. Render, preflight, apply, and validate Splunk Enterprise
  Workload Management pools, workload rules, and admission rules."
compatibility: "Splunk Cloud Platform 10.5.2605: not applicable. This self-managed runtime workflow remains on the public Splunk Enterprise or Universal Forwarder 10.4 baseline."
metadata:
  splunk_cloud_10_5: "self-managed-10.4"
  compatibility_verified: "2026-08-20"
---

# Splunk Workload Management Setup

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

- Reserve search or ingest resources, configure workload_pools.conf, workload_rules.conf, workload_policy.conf,
  cgroups prerequisites, long-running search guardrails, or admission control for expensive searches.
- Preview and review the splunk workload management setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-workload-management-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-workload-management-setup/scripts/validate.sh --help
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

This skill renders Splunk Enterprise Workload Management configuration for
Linux-based Splunk Enterprise deployments. It is not a Splunk Cloud workflow.

## Agent Behavior

Never ask for secrets in chat. This workflow manages configuration files and
local Splunk CLI commands; it does not need credentials in normal local use.

Before enabling workload management, confirm the target host meets the Linux
cgroups requirements and review all predicates.

## Quick Start

Render a balanced policy:

```bash
bash skills/splunk-workload-management-setup/scripts/setup.sh \
  --profile balanced \
  --critical-role admin
```

Render and enable workload management plus admission rules:

```bash
bash skills/splunk-workload-management-setup/scripts/setup.sh \
  --phase apply \
  --profile ingest-protect \
  --enable-workload-management \
  --enable-admission-rules
```

## What It Renders

- `workload_pools.conf` with search, ingest, and misc categories
- `workload_rules.conf` with placement, monitoring, and optional admission rules
- `workload_policy.conf` with admission control enablement
- helper scripts for preflight, apply, and status

Admission rules are rendered as `[search_filter_rule:<name>]` stanzas in
`workload_rules.conf`, matching Splunk's documented storage model.

Read `reference.md` before applying in distributed deployments.

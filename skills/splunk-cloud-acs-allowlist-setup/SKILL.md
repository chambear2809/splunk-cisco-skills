---
name: splunk-cloud-acs-allowlist-setup
description: "Use when an existing handoff or slash command still references splunk-cloud-acs-allowlist-setup.
  Compatibility alias for the older Splunk Cloud ACS IP allowlist workflow. Use splunk-cloud-acs-admin-
  setup for new ACS work, including allowlists, indexes, HEC tokens, users, roles, capabilities, app
  permissions, private connectivity, outbound ports, DDSS self-storage, limits, maintenance windows, and
  restarts."
compatibility: "Splunk Cloud Platform 10.5.2605: conditional. Follow documented package, entitlement, topology, and customer-managed runtime guardrails; self-managed paths remain on the public 10.4 baseline."
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-08-20"
---

# Splunk Cloud ACS Allowlist Setup

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

- An existing handoff or slash command still references splunk-cloud-acs-allowlist-setup.
- Preview and review the splunk cloud acs allowlist setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-cloud-acs-allowlist-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-cloud-acs-allowlist-setup/scripts/validate.sh --help
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

This skill remains as a compatibility path for existing allowlist-only handoffs.
New work should use
[`splunk-cloud-acs-admin-setup`](../splunk-cloud-acs-admin-setup/SKILL.md),
which preserves the allowlist safety model and adds broader ACS administration.

The scripts in this directory still render and apply the original allowlist
workflow for all seven ACS allowlist features (`acs`, `search-api`, `hec`,
`s2s`, `search-ui`, `idm-api`, `idm-ui`) with IPv4 and IPv6 coverage.

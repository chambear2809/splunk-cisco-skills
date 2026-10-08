---
name: splunk-security-essentials-setup
description: "Use when a user asks to set up SSE, Security Essentials, MITRE/Kill Chain content exploration, Security
  Content recommendations, or starter security posture dashboards. Install, configure readiness, and
  validate Splunk Security Essentials (`Splunk_Security_Essentials`, Splunkbase app 3435) on Splunk Cloud
  or Splunk Enterprise."
compatibility: "Splunk Cloud Platform 10.5.2605: conditional. Follow documented package, entitlement, topology, and customer-managed runtime guardrails; self-managed paths use the separate Enterprise 10.6 compatibility contract."
metadata:
  splunk_enterprise_10_6: "supported"
  enterprise_compatibility_verified: "2026-10-07"
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-08-20"
---

# Splunk Security Essentials Setup

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

- A user asks to set up SSE, Security Essentials, MITRE/Kill Chain content exploration, Security Content
  recommendations, or starter security posture dashboards.
- Preview and review the splunk security essentials setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-security-essentials-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-security-essentials-setup/scripts/validate.sh --help
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

## Shared add-on completion gate

Whenever this workflow installs, configures, or hands off SSE, follow the
[shared completion gate](../shared/ta_completion_gate.md). Package delivery
alone is not success; validate security-data prerequisites and shipped
dashboards against data.

Use this skill to install and validate Splunk Security Essentials (SSE).

## Primary Commands

Preview:

```bash
bash skills/splunk-security-essentials-setup/scripts/setup.sh --dry-run
```

Machine-readable preview (emits a single JSON object; useful for agents):

```bash
bash skills/splunk-security-essentials-setup/scripts/setup.sh --dry-run --json
```

Install and validate:

```bash
bash skills/splunk-security-essentials-setup/scripts/setup.sh
```

Validate only:

```bash
bash skills/splunk-security-essentials-setup/scripts/validate.sh
```

## Agent Behavior

- Install `Splunk_Security_Essentials` from Splunkbase app `3435`, or use
  `--file` for an already-downloaded package.
- Keep SSE on the search tier or search head cluster deployer path.
- Do not treat SSE as an Enterprise Security replacement. It can safely coexist
  with ES and includes content references from ES, ES Content Update, and UBA.
- The official Splunkbase listing currently identifies release `3.8.3` (January
  21, 2026) as compatible with Splunk Enterprise platform `10.6`. The
  self-managed Enterprise `10.6` qualification was checked against that
  listing on October 7, 2026. Keep the Cloud route conditional under the
  compatibility declaration above; Enterprise compatibility does not certify
  a Cloud stack or its tenant-specific entitlements.
- Source: https://splunkbase.splunk.com/app/3435/ and the release API
  `https://splunkbase.splunk.com/api/v1/app/3435/release/` (checked October 7,
  2026).
- After install, guide operators through the setup checklist: Data Inventory
  Introspection, Content Mapping, app configuration review, and optional
  posture dashboards.

Read `reference.md` for compatibility notes and source links.

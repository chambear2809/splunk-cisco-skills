---
name: splunk-security-content-update-setup
description: "Use when the user asks to install, upgrade, review, or validate ESCU or Splunk security content. Render,
  install, and validate Splunk Enterprise Security Content Update readiness for DA-ESS-ContentUpdate, ES
  search-head placement, package delivery, Analytic Story Detail navigation, content inventory checks,
  correlation-search activation review, and ES configuration handoff."
compatibility: "Splunk Cloud Platform 10.5.2605: conditional. Follow documented package, entitlement, topology, and customer-managed runtime guardrails; self-managed paths remain on the public 10.4 baseline."
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-07-02"
---

# Splunk Security Content Update Setup

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

- Install, upgrade, review, or validate ESCU or Splunk security content.
- Preview and review the splunk security content update setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-security-content-update-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-security-content-update-setup/scripts/validate.sh --help
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

Whenever this workflow installs, configures, or hands off ESCU, follow the
[shared completion gate](../shared/ta_completion_gate.md). Package delivery
alone is not success; validate content prerequisites, enabled searches, and
shipped views against data.

Render-first workflow for `DA-ESS-ContentUpdate` (ESCU). It produces a
reviewable install/upgrade plan, ES placement checks, analytic-story inventory
SPL, correlation-search activation review, and handoffs to ES configuration.
Its explicit `--install` and `--all` modes install the ESCU package; search
enablement and content mutation remain outside this skill.

## Package Verification Boundary

The repository's reviewed ESCU baseline is `6.0.0`. The current public release
is `6.1.0` and advertises Splunk 10.5 support, but its analytic-story and
correlation-search contents have not been package-verified here. The shared
installer defaults to verified `6.0.0`; only `--accept-unverified-release`
follows public `6.1.0`. After that explicit override, inventory its shipped
content and repeat the activation review before enabling anything.

## Workflow

```bash
bash skills/splunk-security-content-update-setup/scripts/setup.sh --render \
  --platform auto --es-app SplunkEnterpriseSecuritySuite
```

## Execute

Preview the package-install plan:

```bash
bash skills/splunk-security-content-update-setup/scripts/setup.sh --all \
  --dry-run --json
```

Install ESCU and run validation:

```bash
bash skills/splunk-security-content-update-setup/scripts/setup.sh --all --live
```

This installs the app package only. Correlation-search enablement and ES content
changes remain delegated to `splunk-enterprise-security-config`.

```bash
bash skills/splunk-security-content-update-setup/scripts/validate.sh \
  --rendered-dir splunk-security-content-update-rendered --live
```

See `reference.md` for ESCU placement and activation-review guardrails.

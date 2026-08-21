---
name: widefield-security-setup
description: "Use when the user asks to onboard WideField Security, plan identity threat detection and response,
  connect WideField to identity/SIEM/SOAR/governance tools, or coordinate WideField child skill execution
  without using undocumented WideField APIs. Render, route, validate, and optionally delegate a WideField
  Security adoption workflow across Okta, Saviynt, Splunk SIEM, Google SecOps, and identity-threat doctor
  skills."
compatibility: "Splunk Cloud Platform 10.5.2605: delegated. Compatibility is determined by the canonical replacement or selected child skill; this compatibility alias or router does not own a runtime or package."
metadata:
  splunk_cloud_10_5: "delegated"
  compatibility_verified: "2026-08-20"
---

# WideField Security Setup

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

- Onboard WideField Security, plan identity threat detection and response, connect WideField to
  identity/SIEM/SOAR/governance tools, or coordinate WideField child skill execution without using undocumented
  WideField APIs.
- Preview and review the widefield security setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/widefield-security-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/widefield-security-setup/scripts/validate.sh --help
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

Render a source-backed WideField Security adoption packet and delegate target
work to the child skill that owns each system.

## Workflow

1. Read `reference.md` for source boundaries and unsupported API rules.
2. Copy `template.example` to a local-only spec if the user has many non-secret
   values to track.
3. Render the parent packet:

```bash
bash skills/widefield-security-setup/scripts/setup.sh --render
```

4. Delegate child render/validate execution with the router only after review:

```bash
bash skills/widefield-security-setup/scripts/setup.sh --apply --accept-apply \
  --children okta,splunk,doctor
```

Saviynt and Google SecOps child validation is evidence-gated. To include either
child, pass `--evidence-file` containing its required marker. A combined JSON
file may be used when routing both children, but it must contain both a Saviynt
remediation outcome marker and Google SecOps log type `WIDEFIELD_SECURITY`:

```bash
bash skills/widefield-security-setup/scripts/setup.sh --apply --accept-apply \
  --children saviynt,google \
  --evidence-file ./widefield-cross-system-evidence.local.json
```

The parent never calls private or undocumented WideField APIs. Parent apply is
limited to child render/validate orchestration. Live mutation is limited to
child skills that explicitly document supported public API paths and are run
directly with their required file-backed credentials.

## Guardrails

- Keep secrets in files; reject raw token, password, API key, and client secret
  arguments.
- Treat WideField platform configuration as a provider/customer handoff unless
  public API coverage is added to `reference.md`.
- Run `validate.sh --dry-run` before target-specific validation.
- Parent delegation forwards optional target values only when they were
  explicitly supplied; it never synthesizes empty child arguments.

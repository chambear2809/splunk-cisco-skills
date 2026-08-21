---
name: widefield-identity-threat-doctor
description: "Use when the user asks to investigate WideField findings, audit identity threat coverage, build
  remediation packets, or validate OAuth/NHI/AI-agent identity risks without destructive remediation.
  Diagnose WideField identity threat coverage for OAuth token abuse, rogue or over-privileged apps, non-
  human identity ownership, MFA and credential posture, AI-agent identities, and anomalous sessions using
  read-only Splunk, Okta, and evidence checks."
compatibility: "No direct Splunk Platform runtime dependency. This workflow can be used alongside Splunk Cloud Platform 10.5.2605 through its documented external APIs or handoffs."
metadata:
  splunk_cloud_10_5: "not-applicable"
  compatibility_verified: "2026-08-20"
---

# WideField Identity Threat Doctor

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

- Investigate WideField findings, audit identity threat coverage, build remediation packets, or validate
  OAuth/NHI/AI-agent identity risks without destructive remediation.
- Preview and review the widefield identity threat doctor workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/widefield-identity-threat-doctor/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/widefield-identity-threat-doctor/scripts/validate.sh --help
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

Run read-only coverage checks and render gated remediation packets for
WideField identity threats across identity posture, connected apps, NHI
ownership, AI access, and sessions.

## Workflow

```bash
bash skills/widefield-identity-threat-doctor/scripts/setup.sh --render
bash skills/widefield-identity-threat-doctor/scripts/validate.sh --dry-run
```

When Splunk or Okta credentials are available in files, validation can check
WideField events and Okta System Log reachability:

```bash
bash skills/widefield-identity-threat-doctor/scripts/validate.sh \
  --okta-org-url https://example.okta.com \
  --okta-token-file /secure/okta/api_token
```

## Remediation Gate

Doctor mode is read-only by default. Destructive actions such as revoking
sessions, removing app grants, resetting passwords, or changing governance
policy must be executed by the target owner skill with explicit
target-specific acceptance and documented runbooks.

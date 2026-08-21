---
name: splunk-observability-slo-setup
description: "Use when the user asks to create, validate, or operationalize Splunk Observability SLOs. Render and
  validate focused Splunk Observability Cloud service-level objective setup plans, including SLI source
  selection, objective/target placeholders, SLO API payload intent, /slo/validate handoffs, deeplinks,
  detector follow-up, and deep-native-workflow delegated specs."
compatibility: "No direct Splunk Platform runtime dependency. This workflow can be used alongside Splunk Cloud Platform 10.5.2605 through its documented external APIs or handoffs."
metadata:
  splunk_cloud_10_5: "not-applicable"
  compatibility_verified: "2026-08-20"
---

# Splunk Observability SLO Setup

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

- Create, validate, or operationalize Splunk Observability SLOs.
- Preview and review the splunk observability slo setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-observability-slo-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-observability-slo-setup/scripts/validate.sh --help
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

Focused SLO wrapper over `splunk-observability-deep-native-workflows`. It
renders SLO intent, validation notes, and a downstream workflow spec without
duplicating the existing API coverage logic.

```bash
bash skills/splunk-observability-slo-setup/scripts/setup.sh --render \
  --name "Checkout availability SLO" \
  --service checkoutservice \
  --environment prod \
  --target 99.9 \
  --realm us1
```

Review `deep-native-workflow-spec.json`, then run
`delegate-deep-native-workflows.sh` for downstream rendering or API apply.
The wrapper emits an API-ready request-based payload for `apm_service` only
when `--service` is concrete; other SLI sources fail closed to a completion
handoff.

```bash
bash splunk-observability-slo-rendered/delegate-deep-native-workflows.sh \
  --apply --dry-run
bash splunk-observability-slo-rendered/delegate-deep-native-workflows.sh \
  --apply --token-file /path/to/chmod-600-o11y-token
```

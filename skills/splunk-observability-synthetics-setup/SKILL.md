---
name: splunk-observability-synthetics-setup
description: "Use when the user asks to create, configure, validate, or operate Splunk Synthetic Monitoring tests
  without loading the broader native-ops workflow first. Render and validate focused Splunk Observability
  Cloud Synthetic Monitoring setup plans, including browser, API, HTTP/uptime, SSL, and port tests,
  locations, frequency, run-now and waterfall artifact handoffs, native-ops delegated specs, and
  dashboard/detector follow-ups."
compatibility: "No direct Splunk Platform runtime dependency. This workflow can be used alongside Splunk Cloud Platform 10.5.2605 through its documented external APIs or handoffs."
metadata:
  splunk_cloud_10_5: "not-applicable"
  compatibility_verified: "2026-08-20"
---

# Splunk Observability Synthetics Setup

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

- Create, configure, validate, or operate Splunk Synthetic Monitoring tests without loading the broader native-ops
  workflow first.
- Preview and review the splunk observability synthetics setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-observability-synthetics-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-observability-synthetics-setup/scripts/validate.sh --help
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

Focused wrapper for Synthetic Monitoring. It renders a native-ops compatible
spec and operator handoffs; API-backed create/update and run retrieval remain
owned by `splunk-observability-native-ops`.

## Workflow

```bash
bash skills/splunk-observability-synthetics-setup/scripts/setup.sh --render \
  --name "Checkout browser journey" \
  --kind browser \
  --url https://shop.example.com/checkout \
  --realm us1 \
  --location aws-us-east-1
```

Review `native-ops-spec.json`, then delegate render/apply through:

```bash
bash splunk-observability-synthetics-rendered/delegate-native-ops.sh --render

# Preview the exact API sequence, or apply with a file-backed token:
bash splunk-observability-synthetics-rendered/delegate-native-ops.sh --apply --dry-run
bash splunk-observability-synthetics-rendered/delegate-native-ops.sh \
  --apply --token-file /path/to/chmod-600-o11y-token
```

Use this skill for discoverability and focused planning. Use
`splunk-observability-native-ops` directly when the user already has a complete
multi-surface Observability spec.

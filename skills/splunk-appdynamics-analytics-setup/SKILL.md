---
name: splunk-appdynamics-analytics-setup
description: "Use when the user asks for AppDynamics Analytics, ADQL, Analytics Events API, custom event publishing,
  analytics schemas, transaction analytics, log analytics, browser or mobile analytics, synthetic
  analytics, IoT analytics, connected device analytics, Business Journeys, XLM, SLA, or experience-level
  reporting. Render, validate, and gate Splunk AppDynamics Analytics workflows for Transaction Analytics,
  Log Analytics, Browser Analytics, Mobile Analytics, Synthetic Analytics, IoT Analytics, Connected
  Devices Analytics, Business Journeys, Experience Level Management (XLM), ADQL, Analytics Events API
  schemas, event publishing, and query validation."
compatibility: "No direct Splunk Platform runtime dependency. This workflow can be used alongside Splunk Cloud Platform 10.5.2605 through its documented external APIs or handoffs."
metadata:
  splunk_cloud_10_5: "not-applicable"
  compatibility_verified: "2026-08-20"
---

# Splunk AppDynamics Analytics Setup

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

- The user asks for AppDynamics Analytics, ADQL, Analytics Events API, custom event publishing, analytics schemas,
  transaction analytics, log analytics, browser or mobile analytics, synthetic analytics, IoT analytics, connected
  device.
- Preview and review the splunk appdynamics analytics setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-appdynamics-analytics-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-appdynamics-analytics-setup/scripts/validate.sh --help
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

Custom event publishing is the executable action path. It is gated by
`--accept-analytics-event-publish`, uses a chmod-600 Events API key file, rejects
empty event arrays, and fails on HTTP errors. Other Analytics assets remain
operator runbooks.

```bash
bash skills/splunk-appdynamics-analytics-setup/scripts/setup.sh --render
bash skills/splunk-appdynamics-analytics-setup/scripts/validate.sh
bash skills/splunk-appdynamics-analytics-setup/scripts/setup.sh \
  --apply events --accept-analytics-event-publish --spec path/to/analytics.yaml
```

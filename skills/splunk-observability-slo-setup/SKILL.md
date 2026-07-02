---
name: splunk-observability-slo-setup
description: >-
  Render and validate focused Splunk Observability Cloud service-level objective
  setup plans, including SLI source selection, objective/target placeholders,
  SLO API payload intent, /slo/validate handoffs, deeplinks, detector follow-up,
  and deep-native-workflow delegated specs. Use when the user asks to create,
  validate, or operationalize Splunk Observability SLOs.
compatibility: "No direct Splunk Platform runtime dependency. This workflow can be used alongside Splunk Cloud Platform 10.5.2605 through its documented external APIs or handoffs."
metadata:
  splunk_cloud_10_5: "not-applicable"
  compatibility_verified: "2026-07-02"
---

# Splunk Observability SLO Setup

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

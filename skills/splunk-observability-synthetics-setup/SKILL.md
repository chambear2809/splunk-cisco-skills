---
name: splunk-observability-synthetics-setup
description: >-
  Render and validate focused Splunk Observability Cloud Synthetic Monitoring
  setup plans, including browser, API, HTTP/uptime, SSL, and port tests,
  locations, frequency, run-now and waterfall artifact handoffs, native-ops
  delegated specs, and dashboard/detector follow-ups. Use when the user asks
  to create, configure, validate, or operate Splunk Synthetic Monitoring tests
  without loading the broader native-ops workflow first.
---

# Splunk Observability Synthetics Setup

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

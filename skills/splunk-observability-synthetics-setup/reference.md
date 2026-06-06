# Splunk Observability Synthetics Setup Reference

This skill creates a narrow Synthetics entry point over the broader
`splunk-observability-native-ops` implementation.

## Supported Test Kinds

- `browser`: browser journey or page availability test.
- `api`: API test payload.
- `http`: HTTP/uptime check.
- `ssl`: certificate expiry and TLS reachability check.
- `port`: TCP port reachability check.

## Rendered Assets

- `synthetics-plan.md`: operator plan and safety notes.
- `native-ops-spec.json`: compatible with `splunk-observability-native-ops`.
- `delegate-native-ops.sh`: command wrapper for downstream render/apply.
- `waterfall-handoff.md`: run and artifact lookup guidance.
- `metadata.json`: machine-readable summary.

## Source Anchors

- https://help.splunk.com/en/splunk-observability-cloud/monitor-end-user-experience/synthetic-monitoring
- https://help.splunk.com/en/splunk-observability-cloud/monitor-end-user-experience/synthetic-monitoring/browser-tests-for-webpages/set-up-a-browser-test
- https://dev.splunk.com/observability/reference/api/synthetics_tests/latest

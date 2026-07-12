# Validation ladder

Validation is cumulative; do not skip directly to the backend.

1. **Source**: Lemonade is healthy, both semantic conventions are enabled, the
   three hide flags match policy, and the loopback-only `/internal/config`
   snapshot reports the intended endpoint (omit `telemetry.otlp.headers` from
   all output).
   Exercise one non-sensitive failure and confirm `status.message` is redacted;
   native Lemonade v10.10 hide flags do not cover that error field.
2. **Receiver**: the collector is bound only to the intended loopback address
   and its accepted trace count increases after a canary.
   Preserve the live resource-detection component and its detector list; do
   not rename it or replace cloud detectors during Lemonade setup. Splunk OTel
   Collector v0.156 deployments can expose either `resourcedetection` (the
   official packaged template) or `resource_detection`; preserve the live
   component ID. The explicit legacy migration removes only the prior
   skill's recognized shared `resource/lemonade` shape with exactly one final
   processor entry in each selected trace and log pipeline; reordering,
   duplicates, or any other reference topology are a hard failure.
3. **Pipeline**: processors run without errors and the existing Splunk trace
   exporter sent count increases.
4. **Failure signals**: use the exact v0.156 accepted/failed/refused,
   sent/send-failed/enqueue-failed, queue size/capacity, and in-flight metrics.
   Do not claim generic retry/drop counters that the target does not expose.
5. **Splunk readback**: use the canary's `TRACE_ID`, `TRACE_NAME`,
   `CREATED_AFTER`, and `CREATED_BEFORE` with the protected API readback below.
   Bind the request to the expected realm and organization ID, retrieve every
   persisted segment, and verify service, operation, time, model/provider,
   duration, and GenAI/OpenInference fields.
6. **Real request**: make a non-sensitive Lemonade chat request, consume a
   stream fully when testing streaming, flush telemetry, and repeat readback.
7. **Cleanup**: remove any temporary debug exporter and validate/restart again.

The collector's accepted/sent counters prove an attempt, not backend
acceptance. A successful validation always includes backend readback.
Retain `OTLP_PARTIAL_SUCCESS_PRESENT=true` if the canary reports it: the
receiver returned zero rejected spans and no warning, but explicitly populated
the OTLP partial-success field. Any rejected span or warning remains a failure.

Capture a sanitized baseline and delta using exact labels observed in the
target collector:

```bash
python3 skills/lemonade-splunk-otel/scripts/collector_evidence.py \
  --receiver-label otlp \
  --exporter-label otlp_http > /tmp/lemonade-before.json

python3 skills/lemonade-splunk-otel/scripts/collector_evidence.py \
  --receiver-label otlp \
  --exporter-label otlp_http \
  --before /tmp/lemonade-before.json > /tmp/lemonade-after.json
```

The helper accepts only loopback health/metrics URLs, bypasses ambient proxies,
rejects redirects, bounds responses, and omits exporter destinations.

## Protected Splunk APM readback

Use a dedicated organization token with **API** scope and the `read_only` role
for durable-delivery checks. The Collector's ingest token cannot call the API.
Discover the realm and organization ID in the signed-in UI under
Settings, user name, Organizations; do not infer an organization from its
realm. Materialize the API token from Keychain using
[keychain.md](keychain.md) into a current-user-owned, single-link `0600` file.

Run readback from a current-user-owned `0700` directory. Use separate protected
files for any synthetic prompt or output sentinels; their contents never
belong on argv:

```bash
python3 skills/lemonade-splunk-otel/scripts/splunk_trace_readback.py \
  --realm "$SPLUNK_REALM" \
  --expected-organization-id "$SPLUNK_ORG_ID" \
  --api-token-file "$READBACK_DIR/splunk-api-token" \
  --trace-id "$TRACE_ID" \
  --expected-service lemonade-otel-canary \
  --expected-operation "$TRACE_NAME" \
  --created-after "$CREATED_AFTER" \
  --created-before "$CREATED_BEFORE" \
  --expected-environment "$DEPLOYMENT_ENVIRONMENT" \
  --expected-model lemonade-privacy-canary \
  --expected-provider lemonade \
  --output "$READBACK_DIR/sanitized-evidence.json"
```

The helper uses only the exact modern Splunk API origin, disables ambient
proxies and redirects, enforces one deadline and bounded bodies, verifies
`GET /v2/organization`, retrieves a stable `/segments` index and every segment,
deadline-polls while that index is temporarily HTTP 200 `[]`, keeps raw trace
JSON in memory, and writes only sanitized `0600` evidence. A
trace cannot be deleted through the download API and remains until retention,
so every canary and sentinel must be non-sensitive.

Lemonade v10.10 native telemetry emits traces, not OTLP metrics. Setting the
SignalFx exporter option `send_otlp_histograms: true` is necessary to forward
histograms but does not synthesize them from spans. If AI Agent Monitoring
overview pages are a deliverable, use a separately reviewed companion GenAI
instrumentation path that emits at least the required
`gen_ai.client.operation.duration` and `gen_ai.client.token.usage` histogram
metrics, route its OTLP metrics through the Collector metrics pipeline, and
require both backend metric evidence and the signed-in UI before reporting the
experience as populated. APM trace persistence or the exporter setting alone
is not sufficient evidence.

The fixed-ID OTLP canary proves Collector-to-Splunk persistence. It does not
prove Lemonade's hide flags because its content is redacted before sending;
its evidence therefore reports `content_privacy=not_evaluated`. For source
privacy, make exactly one non-sensitive Lemonade request inside a recorded time
window, consume streaming fully, flush telemetry, and locate its generated
trace ID in APM Trace Analyzer with sample ratio 1:1. Lemonade does not accept
caller W3C trace context, so its trace ID cannot be preselected. Repeat
readback for that trace and add one `--forbidden-content-file` per protected
synthetic input or output sentinel. Those files must meet the same private-file
contract as the API token; a successful scan reports
`content_privacy=verified` without echoing their values.

Routine `read_only` API readback can be unable to reveal AI conversation
content because Splunk gates inputs, outputs, and system prompts behind
`read_apm_ai_conversation`. Treat content absence under that role as
inconclusive. Perform the initial backend privacy attestation in the signed-in
AI trace data UI with a user holding both read access and `ai_monitoring` (or
admin), and confirm the synthetic sentinels are absent or redacted. APM trace
readback also does not by itself prove that AI Agent Monitoring pages are
populated; validate the required GenAI histogram metrics and the AI trace data
or AI overview UI before making that claim.

Primary sources:

- https://dev.splunk.com/observability/reference/api/trace_id/latest
- https://dev.splunk.com/observability/reference/api/organizations/latest/
- https://help.splunk.com/en/splunk-observability-cloud/administer/authentication-and-security/authentication-tokens/org-access-tokens
- https://help.splunk.com/en/splunk-observability-cloud/administer/org-reference-info/view-your-realm-api-endpoints-and-organization
- https://help.splunk.com/en/splunk-observability-cloud/observability-for-ai/splunk-ai-agent-monitoring/set-up-ai-agent-monitoring

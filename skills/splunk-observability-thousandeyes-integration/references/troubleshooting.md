# Troubleshooting

This annex covers the most common failure modes for the ThousandEyes -> Splunk Observability Cloud integration. For type-specific signal questions see `test-types-catalog.md`; for SignalFlow chart issues see `signalflow-validation.md`; for APM trace linking see `integrations-2-apm.md`.

## No ThousandEyes metrics in Splunk Observability Cloud

### Step 1: confirm the Stream object exists

```bash
TE_CURL_CONFIG="$(mktemp)"
chmod 600 "$TE_CURL_CONFIG"
{ printf 'header = "Authorization: Bearer '; tr -d '\r\n' < "$TE_TOKEN_FILE"; printf '"\n'; } > "$TE_CURL_CONFIG"
trap 'rm -f "$TE_CURL_CONFIG"' EXIT

curl -sS -K "$TE_CURL_CONFIG" \
  "https://api.thousandeyes.com/v7/streams?aid=${ACCOUNT_GROUP_ID}" | jq
```

You should see one (or more) Stream objects with `type: opentelemetry`, `signal: metric`, and `streamEndpointUrl: https://ingest.<realm>.signalfx.com/v2/datapoint/otlp`. If no Stream is listed, the apply-stream.sh handoff was never executed.

### Step 2: confirm the Stream is enabled and healthy

```bash
curl -sS -K "$TE_CURL_CONFIG" \
  "https://api.thousandeyes.com/v7/streams/${STREAM_ID}?aid=${ACCOUNT_GROUP_ID}" | jq '.enabled, .lastStatus'
```

`.enabled` should be `true`. `.lastStatus` should be `OK` or `STREAMING`. If it's `AUTH_FAILED`, the X-SF-Token in `customHeaders` is wrong (rotated O11y token, mistyped, etc.). Re-render with the correct token file and re-apply.

### Step 3: confirm matched tests are running

```bash
curl -sS -K "$TE_CURL_CONFIG" \
  "https://api.thousandeyes.com/v7/tests?aid=${ACCOUNT_GROUP_ID}" | jq '.tests[] | select(.testId == TEST_ID)'
```

Confirm the test is `enabled: true` and the `interval` is non-zero. Stopped or disabled tests don't produce metrics, so the Stream has nothing to forward.

### Step 4: confirm O11y is receiving

In O11y UI, run a SignalFlow query:

```python
data('network.latency', filter=filter('thousandeyes.account.id', '${ACCOUNT_GROUP_ID}')).count().publish()
```

If the count is 0, the Stream is forwarding but O11y is not ingesting. Common causes:

- Wrong realm in `streamEndpointUrl` (e.g. `us0` vs `us1`).
- O11y org access token revoked / rotated.
- O11y org MTS quota exceeded (very unusual for TE volumes).

## Stream creation fails with 401/403

```bash
curl -sS -K "$TE_CURL_CONFIG" -X POST \
  "https://api.thousandeyes.com/v7/streams?aid=${ACCOUNT_GROUP_ID}" \
  -H "Content-Type: application/json" \
  --data @te-payloads/stream.json
# Returns: {"errorMessage": "..."}
```

- **401 Unauthorized**: TE OAuth token expired or wrong. Re-issue from `https://app.thousandeyes.com/settings/account` -> User API Tokens.
- **403 Forbidden**: token's user account doesn't have **Account Settings** -> **Streaming** privilege. Have an account admin grant it via Role Management.
- **403 with body containing `account-group`**: the `aid` query parameter doesn't match a group the token user belongs to. Use `list-account-groups.sh` (rendered helper) to enumerate accessible groups.

## Stream creation fails with 400 / `dataModelVersion`

If you get `400 Bad Request` mentioning `dataModelVersion`, your TE org may not be entitled to data model v2 yet. Contact ThousandEyes support to enable the entitlement, or temporarily switch to `dataModelVersion: v1` in the spec (lossy; the renderer warns).

## APM connector apply fails

```bash
bash apply-apm-connector.sh
# Returns 400: "X-SF-Token must be a valid Splunk Observability API token"
```

The connector requires a **User API access token** (admin scope), NOT an Org access token (ingest scope). Confirm via:

```bash
O11Y_CURL_CONFIG="$(mktemp)"
chmod 600 "$O11Y_CURL_CONFIG"
{ printf 'header = "X-SF-Token: '; tr -d '\r\n' < "$O11Y_API_TOKEN_FILE"; printf '"\n'; } > "$O11Y_CURL_CONFIG"
trap 'rm -f "${TE_CURL_CONFIG:-}" "$O11Y_CURL_CONFIG"' EXIT

curl -sS -K "$O11Y_CURL_CONFIG" \
  "https://api.us0.signalfx.com/v2/credential" | jq
```

If you get 401, the token is invalid or has wrong scope. Issue a new User API token from the O11y UI -> Settings -> Access Tokens and re-render.

## Test creation fails

The renderer ships per-type test specs under `te-payloads/tests/<test-id>.json`. Apply them via `apply-tests.sh`. Common errors:

- **404 on POST**: the test type endpoint is wrong. The renderer maps `http-server` to `/v7/tests/http-server`, `dns-server` to `/v7/tests/dns-server`, etc. If TE adds a new test type, the renderer needs an update; flag it.
- **422 unprocessable**: the test spec has a missing required field (e.g. `agents[]` or `targetUrl`). Per-type required fields are documented in `references/test-types-catalog.md`.

## Templates apply fails with `credentials must be Handlebars`

ThousandEyes Templates require credentials embedded as Handlebars expressions, not literal token values. The renderer enforces this for any field that looks token-shaped. For example:

```bash
ERROR: templates field template_body.customHeaders.X-SF-Token must be a Handlebars placeholder, not a literal credential.
```

Replace the spec value with a declared reference such as `{{te_credentials.api_key}}`. The renderer validates placeholders; it never derives or substitutes one from a token file. Never hand-edit rendered JSON to inline a token.

## Metric-catalog probe errors

If `validate-signalflow.sh` reports an HTTP, authentication, or JSON error, verify the realm and User API token. The helper is only a read-only `/v2/metric` reachability probe; it does not compile the rendered SignalFlow programs.

```
curl: (22) The requested URL returned error: 401
```

Use the WebSocket handoff in `signalflow-validation.md` or the downstream dashboard-builder's validation to test actual SignalFlow programs.

## Per-test-type filter doesn't match

`stream.filters.testTypes[]` accepts the canonical TE OTel v2 type IDs:

```
http-server, page-load, web-transactions, api, agent-to-server,
agent-to-agent, bgp, dns-server, dns-trace, dnssec, sip-server,
voice, ftp-server
```

If you specify a type that's not in this list, TE silently drops the filter and forwards ALL types. Verify your filter via:

```bash
curl -sS -K "$TE_CURL_CONFIG" \
  "https://api.thousandeyes.com/v7/streams/${STREAM_ID}?aid=${ACCOUNT_GROUP_ID}" | jq '.filters'
```

## Stream is forwarding but only some test types appear

If you see `network.latency` but not an expected metric such as `http.client.request.duration`, verify that the test type supports it in TE OTel data model v2. See `test-types-catalog.md` for the per-type metric matrix.

## High MTS cost

TE OTel data model v2 emits ~12-30 metrics per test per interval. Default test interval is 60s. For 100 tests over 30 days, this is roughly:

- 100 tests * 20 metrics * 1 sample/min = 2000 datapoints/min = 86.4M datapoints/month.

Compare the result with your organization's current entitlement. If you have hundreds of tests, consider:

- Filtering to only critical test types via `stream.filters.testTypes[]`.
- Increasing test intervals (TE Web Transactions at 5min vs 1min reduces by 5x).

## Coordination with cisco-thousandeyes-setup

If you've ALSO run `cisco-thousandeyes-setup` (the Splunk Platform TA path for raw test events), no overlap with this skill. The TA ingests raw test events into Splunk Platform; this skill ingests aggregated metrics into Splunk Observability Cloud. Use the least-privilege token scope required by each workflow; live asset apply requires mutation privileges.

## Coordination with cisco-thousandeyes-mcp-setup

The MCP setup skill exposes TE asset management as MCP tools to your AI assistant (Cursor, Claude, etc.). After you've stood up this integration skill, you can use the MCP server to investigate test metadata, create tests, and tweak alert rules without leaving your IDE. See `cisco-thousandeyes-mcp-setup` SKILL.md for client wiring.

# SignalFlow validation

The skill ships `scripts/validate-signalflow.sh` for a quick REST probe of `api.<realm>.signalfx.com`. For a deeper end-to-end validation that confirms TE data is actually flowing into Splunk Observability Cloud, use a SignalFlow WebSocket query.

## REST probe (scripts/validate-signalflow.sh)

The shipped helper uses `curl` against `/v2/metric` to confirm:

- The realm endpoint is reachable.
- The User API access token authenticates successfully.
- At least one `thousandeyes.*` metric is registered (no time-series query, just metadata).

This is a "smoke" check. It does not confirm a specific test is actively pushing data points.

## WebSocket SignalFlow query (deeper validation)

The TE reference implementation at `/Users/alecchamberlain/Documents/GitHub/network-streaming-app/scripts/thousandeyes/validate-signalflow-metrics.js` opens a WebSocket against `wss://stream.<realm>.signalfx.com/v2/signalflow/connect` and runs SignalFlow programs to assert:

- Recent time series exist for each `(test_type, test_id)` pair.
- Values fall within expected SLO bands.
- The stream has at least N data points in the last K hours.

To adapt that pattern:

```javascript
const WebSocket = require('ws');
const ws = new WebSocket('wss://stream.us0.signalfx.com/v2/signalflow/connect');

ws.on('open', () => {
  ws.send(JSON.stringify({
    type: 'authenticate',
    token: process.env.O11Y_API_TOKEN,  // read from a chmod-600 file in the wrapper
  }));
  ws.send(JSON.stringify({
    type: 'execute',
    channel: 'check-1',
    program: "data('network.latency', filter=filter('thousandeyes.account.id', '1234')).count().publish('count')",
    start: Date.now() - 3600 * 1000,
    stop: Date.now(),
    immediate: true,
  }));
});
```

The validation should:

1. Wait up to N seconds for `data` messages.
2. Assert at least one data point arrived.
3. Optionally assert the value fell within an expected band (e.g. `count > 0` for traffic, `network.loss < 0.01` for SLO-pass).

## Why WebSocket over REST

The REST `/v2/metric` and `/v2/datapoint/series` endpoints work for one-off queries but require polling. WebSocket SignalFlow is the canonical way to subscribe to a continuous stream, which is what you actually want for an "is the integration working right now?" probe.

## Running against multiple realms

The TE OTel stream goes to one realm at a time; the apply path validates against `${REALM}`. If you have multi-org TE setups streaming to multiple Splunk Observability orgs, run the validation per realm:

```bash
for realm in us0 us1 eu0; do
  REALM=$realm O11Y_API_TOKEN_FILE=/tmp/sfx_${realm}_api_token \
    bash splunk-observability-thousandeyes-rendered/scripts/validate-signalflow.sh
done
```

This is one of the situations where a per-realm User API access token is preferable to a shared token (per Splunk Observability token taxonomy).

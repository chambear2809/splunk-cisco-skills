# TE OpenTelemetry Data Model v2 — test type & metric catalog

Source of truth: `docs.thousandeyes.com/product-documentation/integration-guides/opentelemetry/data-model/data-model-v2/metrics`. The list below mirrors the public catalog at the time of authoring; if the canonical doc adds or renames metrics, update `PER_TYPE_METRICS` in `scripts/render_assets.py`.

## Network tests

### `agent-to-server`

- `network.latency`
- `network.loss`
- `network.jitter`

Also supports basic transport tests (TCP/UDP) when configured via the agent-to-server endpoint.

### `agent-to-agent` (uni-directional or bi-directional)

- `network.latency`
- `network.loss`
- `network.jitter`

### `bgp`

- `bgp.path_changes.count`
- `bgp.reachability`
- `bgp.updates.count`

## Web / application tests

### `http-server`

- `http.server.request.availability`
- `http.server.throughput`
- `http.client.request.duration`

### `page-load`

- `web.page_load.duration`
- `web.page_load.completion`

### `web-transactions` (multi-step transaction tests)

- `web.transaction.duration`
- `web.transaction.errors.count`
- `web.transaction.completion`

### `api`

- `api.duration`
- `api.completion`

### `api-step` (per-step within a multi-step API test)

- `api.step.duration`
- `api.step.completion`

## DNS tests

### `dns-server`

- `dns.lookup.availability`
- `dns.lookup.duration`

### `dns-trace`

- `dns.lookup.availability`
- `dns.lookup.duration`

### `dnssec`

- `dns.lookup.validity`

## Voice / media tests

### `voice` (RTP-stream)

- `rtp.client.request.mos`
- `rtp.client.request.loss`
- `rtp.client.request.discards`
- `rtp.client.request.duration`
- `rtp.client.request.pdv`

### `sip-server`

- `sip.server.request.availability`
- `sip.client.request.duration`
- `sip.client.request.total_time`

## File transfer tests

### `ftp-server`

- `ftp.server.request.availability`
- `ftp.client.request.duration`
- `ftp.server.throughput`

## Endpoint Experience tests

Endpoint Experience (`domain=endpoint`) tests reuse a subset of the Cloud + Enterprise Agent (`domain=cea`) test types — primarily `http-server` (scheduled HTTP) and `agent-to-server`. The Endpoint Agent additionally emits local-network metrics that are scoped to the agent host (Wi-Fi, cellular, network adapter) and are not part of this skill's per-type chart catalog.

## Test-type identity in OTel attributes

Every metric carries the following resource attributes:

- `thousandeyes.account.id` — TE account group ID.
- `thousandeyes.test.id` — TE test ID.
- `thousandeyes.agent.id` — agent that produced the data point.
- `thousandeyes.test.type` — canonical type name (matches the values above).

The skill's SignalFlow specs filter charts by `thousandeyes.account.id` and `thousandeyes.test.id`; you can add `thousandeyes.agent.id` filters in the dashboard-builder skill if you want per-agent breakdowns.

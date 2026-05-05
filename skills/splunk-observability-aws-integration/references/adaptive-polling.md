# Adaptive Polling

Adaptive polling reduces CloudWatch costs by polling **inactive** metrics less
frequently than **active** ones. **Default ON** as of February 2026.

## How it works

- A metric is **active** if it has been accessed (UI view, API query, alert,
  dashboard render) within the last **~3 hours**.
- Active metrics use the configured `pollRate` (canonical seconds; 60-600 s
  range; default 300 s).
- Inactive metrics use the `inactiveMetricsPollRate` (canonical seconds;
  60-3600 s range; default 1200 s = 20 min).
- A metric warms up to active within **~5 minutes** of the next view / API
  touch.

## Spec controls

```yaml
connection:
  poll_rate_seconds: 300                # 60-600 s
  metadata_poll_rate_seconds: 900       # metadata refresh
  adaptive_polling:
    enabled: true                       # default true
    inactive_seconds: 1200              # 60-3600 s; default 1200
```

The renderer multiplies these by 1000 when serializing to the raw REST API
payload (`pollRate` and `inactiveMetricsPollRate` use **milliseconds**).

## Opt-out

Set `connection.adaptive_polling.enabled: false`. The renderer omits
`inactiveMetricsPollRate` from the REST payload; the integration polls every
metric at the regular `pollRate` interval.

## Cost impact

- 5-minute polling (default) is usually cheapest for non-urgent metrics.
- 1-minute polling generally exceeds Metric Streams' cost.
- Adaptive polling targets a middle ground: fast for active metrics, slow for
  the long tail.

## Splunk's automation example

Splunk publishes `signalfx/splunk-aws-adaptive-polling` as a reference script
for tuning across many integrations.

## Sources

- [Adaptive polling](https://help.splunk.com/en/splunk-observability-cloud/manage-data/connect-to-your-cloud-service-provider/connect-to-aws/adaptive-polling)
- [Connect via polling](https://help.splunk.com/en/splunk-observability-cloud/manage-data/connect-to-your-cloud-service-provider/connect-to-aws/connect-via-polling)
- [Connect AWS overview](https://help.splunk.com/en/splunk-observability-cloud/manage-data/connect-to-your-cloud-service-provider/connect-to-aws)

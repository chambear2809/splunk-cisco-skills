# Splunk HEC Service Reference

## Research Basis

This skill follows Splunk's current HTTP Event Collector documentation:

- Splunk Enterprise `inputs.conf` 10.2 reference documents the `[http]` global
  stanza and `[http://name]` token stanza, including `token`, `disabled`,
  `index`, `indexes`, `source`, `sourcetype`, `useACK`, and
  `s2s_indexes_validation`.
- Splunk Enterprise HEC configuration-file guidance says HEC settings are stored
  under `$SPLUNK_HOME/etc/apps/splunk_httpinput/local/inputs.conf` and that HEC
  tokens must be GUID values.
- Splunk Enterprise HEC REST API documentation identifies
  `data/inputs/http` and `data/inputs/http/{name}` as HEC token management
  endpoints.
- Splunk Cloud ACS documentation supports programmatic HEC token create, list,
  describe, update, and delete operations through ACS HEC token APIs and the ACS
  CLI.
- Splunk Cloud ACS documentation exposes `allowedIndexes`, `defaultIndex`,
  `defaultSource`, `defaultSourcetype`, `disabled`, `name`, and `useACK` in the
  HEC token spec. It also notes that Cloud indexer acknowledgement support is
  constrained to supported ingest paths such as AWS Kinesis Firehose.

Official references:

- Enterprise `inputs.conf` reference:
  <https://help.splunk.com/en/splunk-enterprise/administer/admin-manual/10.2/configuration-file-reference/10.2.0-configuration-file-reference/inputs.conf>
- HEC token GUID and request format:
  <https://help.splunk.com/en/data-management/collect-http-event-data/use-hec-in-splunk-cloud-platform/format-events-for-http-event-collector>
- Enterprise HEC REST endpoints:
  <https://help.splunk.com/en/splunk-enterprise/get-started/get-data-in/10.2/get-data-with-http-event-collector/http-event-collector-rest-api-endpoints>
- Splunk Cloud ACS HEC token management:
  <https://help.splunk.com/en/splunk-cloud-platform/administer/admin-config-service-manual/10.3.2512/administer-splunk-cloud-platform-using-the-admin-config-service-acs-api/manage-http-event-collector-hec-tokens-in-splunk-cloud-platform>

## Enterprise Design

The Enterprise path renders `inputs.conf.template` and applies it to
`$SPLUNK_HOME/etc/apps/<app-name>/local/inputs.conf`. The default app name is
`splunk_httpinput` because Splunk documents that location for HEC configuration.

Token values are never rendered. `apply-enterprise-files.sh` reads an existing
`--token-file` or generates a GUID into a local-only file, then substitutes the
placeholder into `inputs.conf` on the target host. If an operator supplies a
token file, the apply script verifies that it contains a GUID before writing
`inputs.conf`. The generated script does not pass token values as command-line
arguments.

`--restart-splunk true` is the default because Splunk's HEC configuration-file
workflow requires a restart for changes to take effect. Operators can render or
apply with `--restart-splunk false` when they need to coordinate restarts
manually.

For clustered indexer or heavy forwarder tiers, distribute the rendered
configuration through the normal cluster-manager, deployer, or host-management
path instead of independently editing every peer by hand.

## Splunk Cloud Design

Splunk Cloud does not expose filesystem access to `inputs.conf`. The Cloud path
renders ACS JSON payloads and an ACS helper script:

- `acs-hec-token.json` is the single-token ACS API shape.
- `acs-hec-token-bulk.json` is shaped for ACS CLI bulk HEC token workflows.
- `apply-cloud-acs.sh` uses the repo's ACS helper functions and supports both
  current `hec-token` and older `http-event-collectors` ACS command groups.

The generated Cloud apply script lets ACS generate the token value. If ACS
returns the token value and `--write-token-file` was supplied, the script writes
that value to a chmod 600 local file and does not print it.

## Index Restrictions

Use `--allowed-indexes` to constrain where clients can write. The
`--default-index` value must be one of the allowed indexes. For Enterprise, this
renders both `index = <default>` and `indexes = <csv>`. For Cloud, the same
values are emitted as `defaultIndex` and `allowedIndexes`.

Validate that all allowed indexes already exist before enabling producers. ACS
and Splunk can accept a token that points at an index that does not exist, but
events sent there can be lost or rejected depending on platform behavior.

## Indexer Acknowledgement

Use `--use-ack true` only for senders that implement the HEC acknowledgement
protocol correctly. ACK changes producer behavior because clients must query
`/services/collector/ack` and track channel state until events are indexed.

For Splunk Cloud, confirm the ingest path supports ACK before enabling it. ACS
can represent the setting, but Cloud support is limited for general HEC clients.

## Validation

Static validation checks rendered file presence and verifies that
`inputs.conf.template` still contains the token placeholder.

Live validation runs the rendered status script:

```bash
bash skills/splunk-hec-service-setup/scripts/validate.sh --platform enterprise --live
```

```bash
bash skills/splunk-hec-service-setup/scripts/validate.sh --platform cloud --live
```

# Splunk Index Lifecycle / SmartStore Reference

## Research Basis

This skill follows current Splunk SmartStore documentation:

- SmartStore settings live primarily in `indexes.conf`, with cache-manager
  settings in `server.conf` and low-level bucket localization settings in
  `limits.conf`.
- SmartStore can be enabled globally with `[default] remotePath = ...` or
  per-index with `remotePath` under individual index stanzas.
- Remote volumes use `[volume:<name>]`, `storageType = remote`, and a provider
  URI in `path`, such as `s3://...`, `gs://...`, or `azure://...`.
- For indexer clusters, `indexes.conf` and peer-side SmartStore `server.conf`
  settings must be distributed through the cluster-manager configuration bundle.
- SmartStore indexes in indexer clusters require `repFactor = auto`.
- SmartStore index stanzas still require `homePath`, `coldPath`, and
  `thawedPath`. `coldPath` and `thawedPath` are ignored for normal SmartStore
  operation but remain required settings.
- Remote volume paths must be unique to a single running standalone indexer or
  indexer cluster. Do not point two running deployments at the same remote
  volume.
- SmartStore freezing uses `maxGlobalDataSizeMB`,
  `maxGlobalRawDataSizeMB`, and `frozenTimePeriodInSecs`; old non-SmartStore
  size settings such as `maxTotalDataSizeMB` are not the right control surface.
- Certain settings must stay at defaults for SmartStore, including
  `enableTsidxReduction = false` and `maxDataSize = auto`.
- Common `server.conf` cache-manager controls include `eviction_policy`,
  `max_cache_size`, `eviction_padding`, `hotlist_recency_secs`, and
  `hotlist_bloom_filter_recency_hours`.
- Low-level `limits.conf` remote storage settings such as
  `bucket_localize_max_timeout_sec` should only be changed with a clear
  operational reason.

## Scope Choice

Use `--scope per-index` when only selected indexes should use SmartStore or
when a deployment mixes local and remote storage. This is the default.

Use `--scope global` only when every index that inherits `[default]` should use
the rendered remote volume. Global scope is powerful but broad.

## Remote Store Choice

Supported render targets:

- `--remote-provider s3` with `--remote-path s3://bucket/path`
- `--remote-provider gcs` with `--remote-path gs://bucket/path`
- `--remote-provider azure` with `--remote-path azure://path`

For S3, prefer IAM role access from the indexers. If static keys are unavoidable,
use `--s3-access-key-file` and `--s3-secret-key-file`; the rendered template
contains placeholders and the apply script substitutes the key values locally.
The renderer also covers S3 region, signature version, tsidx compression,
server-side encryption, KMS key metadata, and TLS verification settings.

For GCS and Azure, this v1 renderer emits reference settings such as credential
file, endpoint, and container names. It does not embed credential contents.

## Cluster Apply Path

For indexer clusters, apply on the cluster manager:

1. Render and review `indexes.conf.template`, `server.conf`, and `limits.conf`.
2. Copy into `$SPLUNK_HOME/etc/manager-apps/<app>/local`.
3. Run `splunk apply cluster-bundle --answer-yes` when ready.
4. Check `splunk show cluster-bundle-status`.

The generated apply script copies the files and only applies the bundle when
rendered with `--apply-cluster-bundle true`.

## Retention And Freezing

Review retention settings before applying. SmartStore freezing can delete data
from the remote store when limits are reached. Configure retention explicitly
for production indexes so defaults do not cause surprise freezing behavior.

## Validation

Static validation checks rendered file presence and confirms a remote volume is
present in `indexes.conf.template`. Live validation runs the rendered `status.sh`
and redacts obvious remote credential key output.

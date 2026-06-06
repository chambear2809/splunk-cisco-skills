# Splunk Platform Sizing - Reference

This reference documents the sizing model used by
`scripts/size_engine.py`. The constants are deliberately conservative planning
defaults derived from Splunk Validated Architectures (SVA), the Splunk
reference-hardware guidance, and common field practice. They are **planning
estimates only** and are not a substitute for a Splunk Professional Services
sizing engagement, the Splunk Storage Sizing tool, or a proof-of-value test
with the customer's real data and search workload.

## Sizing Model

### 1. Effective ingest

```
effective_ingest = daily_ingest_gb * (1 + growth_pct / 100)
```

Growth headroom defaults to 15%. Increase it for fast-growing estates or to
reserve burst capacity.

### 2. Indexer count

Each indexer serves a bounded daily ingest volume while still meeting search
SLAs. The ceiling depends on the workload profile and the search density:

```
per_indexer_ceiling = profile_ceiling * density_multiplier
indexers_for_ingest = ceil(effective_ingest / per_indexer_ceiling)
```

| Workload profile | Per-indexer ceiling (GB/day) | Rationale |
| --- | --- | --- |
| `core` | 250 | Splunk core, moderate search. |
| `es` | 100 | Enterprise Security: heavy data-model acceleration. |
| `itsi` | 150 | ITSI: KPI/summary search load. |
| `es_itsi` | 80 | Both premium apps on the same data. |

| Search density | Multiplier | Meaning |
| --- | --- | --- |
| `light` | 1.2 | Mostly ingest, few concurrent searches. |
| `medium` | 1.0 | Balanced ingest and search (default). |
| `dense` | 0.7 | Heavy ad-hoc + scheduled concurrency. |

When high availability is requested, the indexer count is floored to the
clustering minimum:

```
indexer_count = max(indexers_for_ingest, replication_factor, 3)
```

### 3. Replication and search factor

| Mode | Replication factor | Search factor |
| --- | --- | --- |
| Non-HA (standalone / single indexer) | 1 | 1 |
| Clustered (`--ha`, default) | 3 | 2 |

Override with `--replication-factor` / `--search-factor`. Search factor is
clamped to be no greater than replication factor. Higher RF improves
resiliency but multiplies storage.

### 4. Search head count

```
concurrent_searches = explicit value
                    or round(concurrent_users * 0.5)
                    or 12 (default)
search_heads = ceil(concurrent_searches / 24)
```

A reference search head sustains roughly 24 concurrent historical searches.
The deployment is promoted to a **search head cluster** (minimum 3 members)
when more than one search head is needed or when HA is requested. Premium apps
add **dedicated search heads** because Enterprise Security and ITSI are
typically deployed on their own search tier.

### 5. Storage

```
indexed_per_day = effective_ingest * 0.5      # rawdata + tsidx
cluster_storage = indexed_per_day * retention_days * replication_factor
per_indexer_storage = cluster_storage / indexer_count
```

The 50% compression factor is the standard rule of thumb (~15% compressed raw
journal + ~35% tsidx index files). With SmartStore, the engine reports a local
cache estimate (~30% of per-indexer storage) and notes that the remote object
store holds the full retention.

### 6. All-In-One eligibility

Standalone (single-server, All-In-One) is recommended only when **all** of the
following hold:

- effective ingest <= 300 GB/day,
- no high-availability requirement,
- a single indexer covers the ingest,
- concurrent searches fit a single instance (~24).

When `--deployment-target standalone` is requested but the use case fails the
gate, the engine exits non-zero and lists the reasons. With `auto`, it falls
back to a distributed recommendation.

## Reference Hardware

Per-role planning specs (vCPU / RAM / data-disk IOPS):

| Role | vCPU | RAM (GB) | IOPS |
| --- | --- | --- | --- |
| Indexer (core) | 16 | 32 | 800 |
| Indexer (premium ES/ITSI) | 32 | 64 | 1200 |
| Search head (core) | 16 | 32 | 200 |
| Search head (premium) | 16 | 64 | 200 |
| Cluster manager | 16 | 32 | 200 |
| Deployer | 8 | 16 | 200 |
| Support (LM / MC / DS) | 8 | 16 | 200 |
| All-In-One (core) | 16 | 32 | 800 |
| All-In-One (premium) | 32 | 64 | 1200 |

Indexer data disks should be low-latency (NVMe/SSD class) to sustain the listed
IOPS. At small scale the cluster manager, license manager, Monitoring Console,
and deployment server can be co-located on a single support node.

## Splunk Validated Architecture Mapping

| Condition | SVA category |
| --- | --- |
| All-In-One eligible | S1 (single-server) |
| Single search head + indexer cluster | C1 |
| Search head cluster + indexer cluster | C3 |
| Multisite (geo) cluster | M-series (e.g., M4) |

## Splunk on Kubernetes Mapping

**Splunk Operator (SOK)** architecture selection:

| Condition | SOK architecture |
| --- | --- |
| All-In-One eligible, single site | `s1` (Standalone CR) |
| Single site, clustered | `c3` |
| Multisite | `m4` |

The SOK target reports indexer replicas (per site for `m4`), search-head
replicas (minimum 3 for clustered), and the per-indexer `var` PVC size. Hand
these to `splunk-enterprise-kubernetes-setup`.

**Splunk POD** profile selection by indexer count:

| Indexers | POD profile |
| --- | --- |
| <= 3 | `pod-small` |
| 4-6 | `pod-medium` |
| > 6 | `pod-large` |

## Splunk Cloud Mapping

Splunk Cloud Platform is Splunk-managed: customers do not provision indexers
or search heads directly. Sizing reduces to the **ingest volume** plus the
**workload (SVC) tier** (core vs premium). The engine reports the effective
ingest and workload class; the indexer/search-head numbers are shown for
capacity reference only. Use `splunk-cloud-acs-admin-setup` for index and
stack configuration.

## Output Files

`scripts/size.sh` writes to `./splunk-platform-sizing-rendered/` (gitignored)
unless `--output-dir` is given:

- `sizing-report.md` - human-readable recommendation.
- `sizing.json` - machine-readable result (`schema_version`, `inputs`,
  `computed`, `recommendation`, `targets`, `handoffs`).

## Caveats

- Real per-indexer throughput varies widely with sourcetype, parsing cost,
  data-model acceleration, and search concurrency; validate with a PoV.
- Premium-app sizing (especially Enterprise Security with many enabled
  correlation searches and accelerated data models) can require more indexers
  than the conservative ceilings here.
- This skill does not size forwarders, HEC throughput, ingest pipelines, or
  license quotas; see the related skills listed in `SKILL.md`.

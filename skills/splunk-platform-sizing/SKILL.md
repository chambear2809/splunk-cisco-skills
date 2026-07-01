---
name: splunk-platform-sizing
description: >-
  Size a Splunk deployment from a use case (daily ingest, retention, search
  load, premium apps, high availability) and render a sizing recommendation
  report plus machine-readable sizing.json. Covers All-In-One single-server
  standalone, distributed Splunk Validated Architectures (C/M series), Splunk
  on Kubernetes (SOK and Splunk POD), and Splunk Cloud, with Enterprise
  Security and ITSI workload multipliers. Use when the user asks to size a
  Splunk cluster, decide how many indexers or search heads they need, plan
  reference hardware, evaluate an All-In-One vs distributed deployment, size
  Splunk on Kubernetes, or estimate storage for a retention requirement.
---

# Splunk Platform Sizing

This skill turns a stated use case into a concrete Splunk sizing across four
deployment families:

1. **All-In-One (S1)** single-server standalone.
2. **Distributed** Splunk Validated Architectures (C1 / C3 / M-series).
3. **Splunk on Kubernetes** - Splunk Operator (`s1`/`c3`/`m4`) and Splunk POD
   (`pod-small`/`pod-medium`/`pod-large`).
4. **Splunk Cloud** (ingest + workload guidance; Splunk-managed).

The skill is **offline and advisory**: it needs no Splunk connection and no
credentials. It renders a Markdown report and a `sizing.json` to a gitignored
directory. All numbers are planning estimates, not a substitute for a Splunk
Professional Services sizing.

## How To Use It

Collect the use case, then run the calculator. Ask only for non-secret
planning values: daily ingest (GB/day), searchable retention (days), search
load (concurrent searches or users), whether premium apps (Enterprise
Security, ITSI) are in scope, and whether high availability is required.

Render a sizing (writes `sizing-report.md` + `sizing.json`):

```bash
bash skills/splunk-platform-sizing/scripts/setup.sh \
  --daily-ingest-gb 500 \
  --retention-days 90 \
  --workload-profile es \
  --concurrent-searches 24 \
  --ha
```

All-In-One check for a small, low-search shop:

```bash
bash skills/splunk-platform-sizing/scripts/setup.sh \
  --daily-ingest-gb 80 \
  --retention-days 30 \
  --deployment-target standalone
```

Size for Splunk on Kubernetes with SmartStore:

```bash
bash skills/splunk-platform-sizing/scripts/setup.sh \
  --daily-ingest-gb 1200 \
  --workload-profile es_itsi \
  --ha \
  --smartstore \
  --deployment-target sok
```

Print the JSON without writing files (good for piping):

```bash
bash skills/splunk-platform-sizing/scripts/setup.sh \
  --daily-ingest-gb 300 --deployment-target cloud --dry-run --json
```

## Inputs

| Flag | Meaning |
| --- | --- |
| `--daily-ingest-gb` | Daily ingest volume (required). |
| `--retention-days` | Searchable retention in days (default 90). |
| `--workload-profile` | `core`, `es`, `itsi`, or `es_itsi` (premium multipliers). |
| `--search-density` | `light`, `medium`, `dense` search concurrency. |
| `--concurrent-searches` / `--concurrent-users` | Search load. |
| `--ha` | Require high availability (indexer/search-head clustering). |
| `--replication-factor` / `--search-factor` | Override clustered RF/SF. |
| `--multisite` / `--sites` | Multisite (geo) cluster and site count. |
| `--smartstore` | Plan for SmartStore remote object storage. |
| `--growth-pct` | Growth headroom percent (default 15). |
| `--deployment-target` | `auto`, `standalone`, `distributed`, `sok`, `pod`, `cloud`. |

With `--deployment-target auto` (the default) the engine recommends standalone
when the use case is All-In-One eligible, otherwise distributed.
RF or SF greater than one automatically implies HA. SF greater than RF is
rejected. Multisite SOK replica counts are rounded up per site so uneven totals
are not under-provisioned.

## What It Computes

- **Indexer count** from `effective_ingest / per-indexer ceiling`, where the
  ceiling depends on the workload profile and search density. Floored to the
  clustering minimum when HA is requested.
- **Search head count** from concurrent searches, promoting to a search head
  cluster when more than one is needed or HA is requested. Premium apps
  (Enterprise Security, ITSI) add dedicated search heads.
- **Storage** = ingest x compression (~50%) x retention x replication factor,
  split across indexers, with a SmartStore local-cache note when enabled.
- **Reference hardware** per role (vCPU / RAM / IOPS).
- **All-In-One eligibility** gate with explicit reasons when standalone is not
  viable.

It then maps the result onto each deployment target (SVA category, SOK
architecture, POD profile, Cloud workload tier) and emits hand-offs.

## Hand-off Contracts

The report ends with hand-offs to the skills that actually deploy what was
sized:

- Standalone or distributed install ->
  [`splunk-enterprise-host-setup`](../splunk-enterprise-host-setup/SKILL.md)
- Indexer cluster ->
  [`splunk-indexer-cluster-setup`](../splunk-indexer-cluster-setup/SKILL.md)
- Search head cluster ->
  [`splunk-search-head-cluster-setup`](../splunk-search-head-cluster-setup/SKILL.md)
- Splunk on Kubernetes (SOK / POD) ->
  [`splunk-enterprise-kubernetes-setup`](../splunk-enterprise-kubernetes-setup/SKILL.md)
- Retention / SmartStore indexes.conf ->
  [`splunk-index-lifecycle-smartstore-setup`](../splunk-index-lifecycle-smartstore-setup/SKILL.md)
- Splunk Cloud indexes and stack ->
  [`splunk-cloud-acs-admin-setup`](../splunk-cloud-acs-admin-setup/SKILL.md)

## Out of Scope

- Live ingest discovery from the Monitoring Console (bring the GB/day figure).
- License sizing/quotas (use `splunk-license-manager-setup`).
- Forwarder fleet sizing (use `splunk-deployment-server-setup` /
  `splunk-agent-management-setup`).
- Exact Splunk Cloud SVC pricing; the Cloud output is workload guidance only.

## References

- [reference.md](reference.md) for the full sizing model, constants, SVA and
  reference-hardware tables, premium multipliers, and the SOK/POD/Cloud
  mapping rules.
- [template.example](template.example) for the non-secret intake worksheet.

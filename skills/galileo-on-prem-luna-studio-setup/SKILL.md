---
name: galileo-on-prem-luna-studio-setup
description: >-
  Render, preflight, validate, observe, and prepare Galileo/CSE joint-session
  install, upgrade, rollback, and retirement handoffs for Galileo
  Luna Studio on Kubernetes with dedicated PostgreSQL, object storage, backend
  and UI, routing, four out-of-band Secrets, GPU Jobs, Vertex AI, and remote or
  hybrid training. Use when operating Luna Studio for Galileo On-Prem or when an
  exact umbrella package requires a reviewed Luna overlay instead of its
  standalone release.
compatibility: "No direct Splunk Platform runtime dependency. This workflow can be used alongside Splunk Cloud Platform 10.5.2605 through its documented external APIs or handoffs."
metadata:
  splunk_cloud_10_5: "not-applicable"
  compatibility_verified: "2026-07-02"
---

# Galileo On-Prem Luna Studio Setup

## Prerequisites

- Obtain the CSE-approved `luna-studio` package, pinned images, questionnaire
  values, and parent Galileo stack release contract.
- Provision an empty dedicated PostgreSQL database and dedicated object-storage
  bucket/container. Luna Studio does not bootstrap its database.
- Create the four required Kubernetes Secrets out of band before preflight.
- Select `kubernetes` or `vertex_ai` training and document any remote cluster.

## Workflow Overview

```text
+-- Intake + topology --+ -> +-- Immutable bundle --+ -> +-- Secret/storage/GPU + render preflight --+
                                                               -> +-- Joint-session handoff --+
```

## When to Activate

- Prepare or review a Galileo/CSE handoff for a standalone Luna Studio install
  or upgrade.
- Configure GCS, S3, Azure Blob, or MinIO-compatible storage authentication.
- Configure in-cluster GPU Jobs, Vertex AI, or a remote training cluster.
- Produce an overlay when the exact umbrella package proves it owns Luna.
- Diagnose database migration, NextAuth/CORS, route, GPU, or storage failures.

## Required Intake

Ask for the Galileo instance console URL and record the exact value, for example
`https://console.demo-v2.galileocloud.io/`. Pass it with
`--galileo-console-url`; do not infer a SaaS hostname for on-prem.

Collect the namespace and release, unique ownership mode, exact chart or
umbrella evidence hashes, parent release contract, approved non-secret values,
the four Secret name/key contracts, asyncpg database readiness, storage
provider/auth/bucket, public hostname, DNS/TLS/CORS/NextAuth alignment, backend
and UI images, training platform/images, GPU scheduling, remote-cluster token
reference, NetworkPolicy/HPA/PDB choices, and approvals. Never record values.

## Ownership and Safety Rules

1. Default to the standalone `luna-studio` release. Use `umbrella-overlay` only
   when the exact pinned umbrella proves ownership; reject dual ownership.
2. Require the four mandatory Secret references: JWT, admin, asyncpg database,
   and NextAuth. Galileo API integration and cloud/remote credentials are
   optional only when their features are disabled.
3. Bind `frontend_url`, CORS origins, UI public URL, DNS, route host, and TLS SAN
   to the same HTTPS origin.
4. Treat startup `alembic upgrade head` as a database migration. Upgrades and
   rollback require backup, release-note, and compatibility evidence.
5. Keep backend/UI on standard nodes. Request `nvidia.com/gpu` only for
   Kubernetes training Jobs, with matching node selector and tolerations.
6. Do not claim live GPU validation from a CPU-only environment.
7. Never run a generic `helm upgrade --install`, automatic rollback, or data
   purge. Preserve failed state for diagnosis.

Read [reference.md](reference.md), [training-and-storage.md](references/training-and-storage.md),
[lifecycle-contract.md](references/lifecycle-contract.md), and
[source-ledger.md](references/source-ledger.md) for production review.

## Commands

```bash
bash skills/galileo-on-prem-luna-studio-setup/scripts/setup.sh --help
```

```bash
bash skills/galileo-on-prem-luna-studio-setup/scripts/setup.sh \
  --render --spec ./luna-studio.local.yaml \
  --galileo-console-url "https://console.demo-v2.galileocloud.io/" \
  --output-dir ./galileo-on-prem-rendered/luna-studio
```

```bash
bash skills/galileo-on-prem-luna-studio-setup/scripts/validate.sh \
  --output-dir ./galileo-on-prem-rendered/luna-studio
```

Use the distinct `--preflight`, `--status`, `--plan-rollback`, and
`--plan-uninstall` modes with the evidence gates printed by `--help`. Every non-uninstall
preflight requires new private `--image-evidence-file` and
`--endpoint-evidence-file` outputs. They bind backend, UI, training, init, hook,
Job, and test image digests plus exact chart, inputs, parent target, Helm render,
and a credential-free host[:port] inventory derived in memory from non-secret
and Secret-backed settings. All historical `--apply-*` modes are permanent
fail-closed sentinels and touch neither the bundle nor Kubernetes. Use the
immutable `lifecycle.json` packet and fresh preflight/image/endpoint evidence in
a Galileo/CSE joint session. Umbrella mode always stops at a parent-stack overlay
handoff.

## Completion Gate

Completion requires unique ownership, four exact Secret/key contracts, an
asyncpg connection and successful migrations, storage write/read/delete
evidence, healthy backend `/health` and UI `/api/health`, working login,
route/DNS/TLS/CORS alignment, training image resolution, and either a successful
training run or an explicit unvalidated capability record. GPU and remote
training remain open until tested on their real targets.

## Troubleshooting

| Symptom | Likely cause | Resolution |
|---|---|---|
| Chart render fails | One of four Secret names is absent | Create it out of band and reference its exact name |
| Database startup fails | Wrong driver or migration grants | Use `postgresql+asyncpg://` and grant schema DDL |
| Sign-in loops | NextAuth/public URL mismatch | Align route, DNS, SAN, frontend, CORS, and UI URL |
| Training Job is pending | GPU selector, taint, resource, or plugin mismatch | Verify all scheduling evidence on the training target |
| Vertex pipeline is missing | Image, location, IAM, or outbound path is wrong | Validate pinned images, pipeline root, IAM, and egress |
| Direct mutation rejected | Exact package selected umbrella ownership | Submit the overlay through the parent stack lifecycle |

---
name: galileo-on-prem-agent-control-setup
description: >-
  Render, validate, preflight, observe, and prepare Galileo/CSE joint-session
  install, upgrade, rollback, and retirement handoffs for the packaged Galileo Agent Control Kubernetes
  lifecycle, including database policy, migrations, routing, UI proxy wiring,
  feature flags, resilience, and immutable chart or umbrella-overlay evidence.
  Use when deploying or upgrading Agent Control as part of Galileo On-Prem;
  use galileo-agent-control-setup instead for runtime controls and Splunk sinks.
compatibility: "No direct Splunk Platform runtime dependency. This workflow can be used alongside Splunk Cloud Platform 10.5.2605 through its documented external APIs or handoffs."
metadata:
  splunk_cloud_10_5: "not-applicable"
  compatibility_verified: "2026-08-20"
---

# Galileo On-Prem Agent Control Setup

## Prerequisites

- Obtain the exact CSE-approved Agent Control or umbrella package and non-secret
  questionnaire values. Never infer proprietary defaults.
- Complete the parent `galileo-on-prem-kubernetes-setup` contract and establish
  that `api` and `authz` are healthy.
- Create the chart-required PostgreSQL and API Kubernetes Secrets out of band.
- Use Bash, Python 3, and a private render destination.

## Workflow Overview

```text
+-- Intake + ownership proof --+ -> +-- Immutable render --+ -> +-- Bound preflight --+
                                                               -> +-- Joint-session handoff --+
```

## When to Activate

- Add the packaged `agent-control` service to an on-prem Galileo deployment.
- Review a new chart, database-bootstrap choice, route, feature flag, or UI
  integration before an install or upgrade.
- Produce a stack overlay when the exact umbrella package owns Agent Control.
- Diagnose missing ownership, Secret-reference, or deployment-order evidence.

Do not activate this skill for creating controls, targets, or Splunk event
sinks; those belong to `galileo-agent-control-setup` after the service is healthy.

## Required Intake

Ask for the Galileo instance console URL and record the exact value, for example
`https://console.demo-v2.galileocloud.io/`. Pass it with
`--galileo-console-url`; never assume a Galileo Cloud hostname for on-prem.

Also collect the Kubernetes namespace/release, exact ownership mode, chart or
umbrella evidence hashes, parent stack contract, database policy, existing
Secret names/keys, routing mode, UI-proxy choice, feature-flag source, and CSE
approval reference. Secrets themselves never belong in the spec.

## Ownership and Lifecycle Rules

1. Default to `standalone`. Require a local `agent-control` chart archive whose
   version and SHA-256 match the spec.
2. Select `umbrella-overlay` only when a hash-bound artifact from the exact
   umbrella package proves ownership. Emit an overlay contract; never install a
   second release.
3. Reject specifications that contain both ownership paths.
4. Preserve the required order: healthy `api` and `authz`, Agent Control,
   optional direct route, then `ui` upgrade/restart and validation.
5. Treat database bootstrap as a privileged migration choice. Prefer a
   pre-provisioned database for production and air-gapped deployments.
6. Keep the Controls UI same-origin proxy enabled. A direct route is optional
   for SDKs, health checks, docs, or a customer-managed load balancer.
7. Never set a per-customer image version unless the approved chart package and
   exception explicitly require it; chart `appVersion` is the default source.

Read [reference.md](reference.md),
[lifecycle-contract.md](references/lifecycle-contract.md), and
[source-ledger.md](references/source-ledger.md) before reviewing a production
bundle.

## Commands

Inspect the safe interface:

```bash
bash skills/galileo-on-prem-agent-control-setup/scripts/setup.sh --help
```

Render a standalone or overlay bundle from reviewed input:

```bash
bash skills/galileo-on-prem-agent-control-setup/scripts/setup.sh \
  --render \
  --spec ./agent-control.local.yaml \
  --galileo-console-url "https://console.demo-v2.galileocloud.io/" \
  --output-dir ./galileo-on-prem-rendered/agent-control
```

Validate the immutable output without contacting Kubernetes:

```bash
bash skills/galileo-on-prem-agent-control-setup/scripts/validate.sh \
  --output-dir ./galileo-on-prem-rendered/agent-control
```

Standalone mode owns its distinct preflight, status, and lifecycle handoff
phases. Preflight/status require `--kubeconfig`, the exact console URL, and the
gates printed by `--help`. Every non-uninstall preflight also requires a
new private `--image-evidence-file` and `--endpoint-evidence-file`; they bind
the exact bundle, parent target, chart, non-secret value hashes, a value-free
Secret path/type influence contract, an all-scalar-redacted render hash,
digest-pinned containers, and a credential-free host[:port] inventory derived
in memory from non-secret and Secret-backed settings. All historical
`--apply-*` modes are permanent fail-closed sentinels and touch neither the
bundle nor Kubernetes. Use the immutable `lifecycle.json` packet and fresh
preflight/image/endpoint evidence in a Galileo/CSE joint session. Umbrella mode
emits an overlay only and never mutates a second release.

## Completion Gate

Keep completion open until the ownership mode is unique, every non-secret chart/evidence
hash matches, required Secret names and keys exist, database migration policy is
approved, routing/DNS/TLS are aligned, `/health` succeeds, UI proxying works,
and the `agent_control` feature flag is verified at its declared precedence.

## Troubleshooting

| Symptom | Likely cause | Resolution |
|---|---|---|
| Dual-ownership rejection | Standalone chart and umbrella proof were both supplied | Choose the single owner proved by the exact package |
| Chart identity mismatch | Archive is not the approved `agent-control` release | Obtain the correct package and digest from Galileo |
| Database bootstrap blocked | Production/air-gap policy lacks an exception | Pre-create the database and grants; disable bootstrap |
| Controls UI is absent | UI proxy/flag was not reconciled | Upgrade or restart UI after enabling the flag |
| Direct route fails | DNS, route host, or TLS SAN differs | Make all three names identical; never use insecure TLS |

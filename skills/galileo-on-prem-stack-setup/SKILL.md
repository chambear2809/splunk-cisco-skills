---
name: galileo-on-prem-stack-setup
description: "Inspect, render, connected-preflight, and observe a pinned Galileo On-Prem galileo-stack deployment on Kubernetes; produce secret-safe evidence and Galileo/CSE joint-session handoffs for every install, upgrade, rollback, uninstall, CRD, galileoctl, GPU, air-gap, and lab-bootstrap change. Use when planning reusable Galileo On-Prem Kubernetes deployment work without unattended mutation."
compatibility: "No direct Splunk Platform runtime dependency. This workflow can be used alongside Splunk Cloud Platform 10.5.2605 through its documented external APIs or handoffs."
metadata:
  splunk_cloud_10_5: "not-applicable"
  compatibility_verified: "2026-08-20"
---

# Galileo On-Prem Stack Setup

This skill is render-first and handoff-only. It never invokes a mutating Helm,
Kubernetes, MicroK8s, CRD, node-label, rollback, or uninstall command. The
historical `--apply-*` flags are permanent fail-closed sentinels.

## When to Activate

Use this skill when a Galileo On-Prem Kubernetes deployment needs entitled
chart inspection, immutable render evidence, target-bound read-only preflight,
status observation, or a Galileo/CSE joint-session handoff. Do not activate it
to execute Helm, kubectl, MicroK8s, CRD, upgrade, rollback, or uninstall
mutations.

## Prerequisites

| Requirement | Why it is required |
|---|---|
| Entitled local `galileo-stack` chart archive, exact version, and SHA-256 | The chart is proprietary and release-specific; never infer its values |
| Version-matched CSE questionnaire and values contract | Product topology and secret paths must come from Galileo, not invented defaults |
| Runtime-only secret values file, mode `0600` or stricter | Secret material is inspected in memory and never copied into the bundle |
| Named kube context, exact API/CA/cluster/namespace identity | Connected evidence must bind one reviewed target |
| Helm 3, `kubectl`, Python 3, and PyYAML | Required for local render and read-only connected inspection |
| External Galileo/CSE change authorization | This local skill does not authenticate or replace change approval |

## Required Intake

Ask for the Galileo instance console URL and record it exactly, for example
`https://console.demo-v2.galileocloud.io/`. Pass it with
`--galileo-console-url`; never assume a Galileo Cloud hostname for on-prem.

Never ask for or repeat passwords in chat. Never put credentials, tokens,
private keys, Secret payloads, or credential-bearing URLs in the spec, command
line, bundle, plans, evidence, logs, or support output.

## Supported Outcomes

- Safely inspect a pinned umbrella chart and every nested chart for exact
  dependencies, values/schema flags, images, hooks/migrations, CRDs, API kinds,
  cluster-scoped objects, routes, and persistence surfaces.
- Render a content-addressed private bundle containing only non-secret inputs,
  the exact chart archive, normalized spec, and derived inventories.
- Run a connected, read-only preflight that binds the target, release state,
  active CRDs, API discovery, runtime Secret influence, rendered manifests,
  images, endpoints, storage, routing, monitoring, data services, node pools,
  Wizard/GPU intent, and air-gap handoff evidence.
- Observe live status without claiming health or provenance that was not
  proven. `production_ready` always remains false in this release.
- Prepare canonical pre-approval handoff candidates for all lifecycle changes,
  including official installation methods, upgrades, rollback, retirement,
  galileoctl, dedicated CRDs, GPU/local inference, air-gap, and MicroK8s lab
  bootstrap.

The current Installation Guide defines four methods: galileoctl (Method A),
umbrella Helm CLI (Method B), deployment script (Method C), and step-by-step
(Method D). The galileoctl UI is identified for first install and its CLI is a
workstation/CI alternative. This skill recognizes all four methods and can
inspect pinned Method A/B chart artifacts. Method C remains incomplete without
the exact script/config hashes and static review; Method D remains incomplete
without the ordered chart/release/dependency contract. It executes none of the
methods. Do not call the raw Helm path vendor-recommended.

Do not use this skill for Galileo projects, datasets, scorers, model-provider
configuration, Agent Control ownership, or standalone Luna Studio; route those
through their dedicated Galileo skills.

## Workflow Overview

```text
┌───────────────────────────────────────────┐
│ Pinned artifacts + closed review inputs   │
└───────────────────────────────────────────┘
                     ▼
          inspect -> render -> validate
                     ▼
           read-only connected preflight
                     ▼
 unauthorized candidate -> external Galileo/CSE session
                     ▼
            read-only status observation
```

## Required Workflow

1. Read [reference.md](reference.md),
   [references/lifecycle-contract.md](references/lifecycle-contract.md), and
   [references/coverage-and-safety.md](references/coverage-and-safety.md).
2. Run `--inspect-chart`. It emits only a runtime inventory and
   `coverage-review.yaml`; it does not create a deployable bundle.
3. Copy every exact reviewed ID into `spec.coverage`, then run `--render`.
4. Run offline validation on the immutable bundle.
5. Run `--preflight --for-action <action>` against the exact target with the
   runtime secret file. Preflight is read-only; server-side dry-run admission
   checks are non-persisting and are reported separately from observer access.
6. Give the bundle, canonical redacted evidence, unresolved gates, and exact
   target/release inventory to the Galileo/CSE operator. The operator executes
   the vendor-approved command in the jointly controlled session. The emitted
   `handoff-candidate.json` is `authorized:false`; it is not a final approval.
7. Run `--status` for retryable read-only observation. Without independently
   authenticated adoption/provenance evidence it reports an unverified state,
   never successful production completion.

## Commands

```bash
bash skills/galileo-on-prem-stack-setup/scripts/setup.sh --help
bash skills/galileo-on-prem-stack-setup/scripts/validate.sh --help

bash skills/galileo-on-prem-stack-setup/scripts/setup.sh \
  --inspect-chart \
  --spec ./galileo-stack-deployment.yaml \
  --galileo-console-url "$GALILEO_CONSOLE_URL" \
  --output-dir ./galileo-on-prem-rendered

bash skills/galileo-on-prem-stack-setup/scripts/setup.sh \
  --render \
  --spec ./galileo-stack-deployment.yaml \
  --galileo-console-url "$GALILEO_CONSOLE_URL" \
  --output-dir ./galileo-on-prem-rendered

bash skills/galileo-on-prem-stack-setup/scripts/validate.sh \
  --bundle ./galileo-on-prem-rendered/acme/<bundle-sha>

bash skills/galileo-on-prem-stack-setup/scripts/setup.sh \
  --preflight \
  --for-action install \
  --bundle ./galileo-on-prem-rendered/acme/<bundle-sha> \
  --secret-values-file /secure/runtime/secret-values.yaml \
  --galileo-console-url "$GALILEO_CONSOLE_URL"

bash skills/galileo-on-prem-stack-setup/scripts/setup.sh \
  --status \
  --bundle ./galileo-on-prem-rendered/acme/<bundle-sha> \
  --galileo-console-url "$GALILEO_CONSOLE_URL" \
  --json
```

`--apply-install`, `--apply-upgrade`, `--apply-rollback`,
`--apply-uninstall`, and `--apply-lab-bootstrap` reject before reading a bundle,
opening a kubeconfig, resolving a binary, writing state, or running a
subprocess. Planning flags emit manual handoffs only.

## Hard Safety Rules

- Require exact local archives and hashes; never fetch `latest` or switch
  installation ownership mid-lifecycle.
- Keep non-secret and runtime-secret values separate. Reject duplicate YAML
  keys, aliases, merge keys, unknown spec fields, populated secret-like
  non-secret fields, and unsafe runtime override paths. Until a version/hash-
  bound closed CSE values/questionnaire contract is supplied, keep
  `cse_values_contract_missing` open even when chart inspection succeeds.
- Never persist raw Secret bodies or unredacted Helm output. Runtime secret
  leaves must independently influence only classified Secret payload fields.
- Shared CRDs must already exist and be semantically exact. Dedicated CRDs are
  a handoff. Never create, patch, replace, or delete a CRD here.
- Treat hooks, migrations, operator-created claims, cluster-scoped resources,
  RBAC, routing/TLS, monitoring, external services, GPU/model artifacts, and
  air-gap mirrors as review surfaces, not implicit approval.
- Never delete or alter namespaces, PVCs, PVs, buckets, databases, nodes,
  labels, load-balancer pools, or release history.
- A syntactically valid render is not production readiness. Keep explicit gaps
  such as `entitled_chart_integration_unvalidated`,
  `cse_values_contract_missing`, and `live_readonly_integration_unvalidated`
  open until exact artifacts and connected evidence exist.

## Troubleshooting

| Symptom | Safe response |
|---|---|
| Bundle validation fails | Preserve the bundle and render a new one; never edit or rehash it |
| Runtime inventory drifts | Review every new ID and rerender |
| Shared CRD differs | Stop and coordinate with the cluster CRD owner and Galileo/CSE |
| Routing, storage, data-service, monitoring, or GPU proof is incomplete | Keep the gate open in the handoff; do not convert an attestation into a pass |
| An apply flag is rejected | This is expected; execute only through the reviewed Galileo/CSE joint session |

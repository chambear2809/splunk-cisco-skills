---
name: galileo-on-prem-kubernetes-setup
description: "Use when planning, reviewing, doctoring, or checking full deployment coverage for Galileo On-Prem on Kubernetes. Render a non-mutating, immutable orchestration packet for the Galileo Stack, galileoctl, packaged Agent Control, Luna Studio, Wizard GPU/local inference, air-gapped supply chains, and production-readiness handoffs. Route implementation to the owning child skill; reject install, upgrade, rollback, uninstall, registry writes, and all other live mutations."
compatibility: "No direct Splunk Platform runtime dependency. This workflow can be used alongside Splunk Cloud Platform 10.5.2605 through its documented external APIs or handoffs."
metadata:
  splunk_cloud_10_5: "not-applicable"
  compatibility_verified: "2026-08-20"
---

# Galileo On-Prem Kubernetes Setup

## Prerequisites

| Requirement | Purpose | Guardrail |
| --- | --- | --- |
| Bash and Python 3 | Run deterministic render and validation helpers | No third-party Python package is required for the JSON example spec |
| Galileo CSE questionnaire output | Supply version-specific, non-secret values | Never invent proprietary defaults |
| Pinned chart archives and checksums | Bind the plan to reviewed artifacts | Tags, unpinned repositories, and mutable URLs are insufficient |
| Kubernetes target identity | Bind later child preflights | Record context, API endpoint, CA hash, and cluster UID |
| Secret-file paths | Describe later child inputs | Never put secret values in chat, argv, specs, or rendered output |

This parent does not require Kubernetes credentials and never calls the target.

## Workflow Overview

```text
┌─────────────────────────┐   ┌─────────────────────────┐   ┌──────────────────────┐
│ Intake + pinned sources │ → │ Render immutable packet │ → │ Coverage doctor/gaps │
└─────────────────────────┘   └─────────────────────────┘   └──────────┬───────────┘
                                                                      │
                                                                      ▼
       Air-gap → Stack → Agent Control/Luna → running-platform handoffs
          (each child owns read-only evidence and joint-session gates)
```

## When to Activate

- Plan or assess a new Galileo On-Prem Kubernetes deployment.
- Resolve whether Galileo Stack, Agent Control, Luna Studio, Wizard GPU, or
  air-gap work belongs to a deployment child.
- Check product/feature coverage or production-readiness gaps.
- Review an existing parent packet without querying or changing the cluster.
- Do not use this parent to configure an already-running Galileo tenant; use
  `galileo-platform-setup` for application objects and product workflows.

## Required Intake

Collect the non-secret fields in `template.example`. Always ask for the
**Galileo instance console URL**, for example
`https://console.demo-v2.galileocloud.io/`, and pass the confirmed value as
`--galileo-console-url`. For on-premises use, this normally resolves to the
customer-controlled TLS hostname. Its hostname must exactly match
`routing.public_hosts.console`; a configured API URL must likewise match the
API route host, and every route host must be the declared Galileo domain or a
subdomain of it.

Require explicit target context, namespace, release names, environment class,
installation method, CRD ownership, routing/TLS mode, storage and node-pool
intent, optional-product topology, air-gap intent, backup/DR posture, and the
paths and SHA-256 digests of entitled artifacts. Empty evidence becomes a
doctor gap; contradictory topology, unknown fields, inline secrets, insecure
URLs, mismatched hosts, placeholders, and unsupported enum values fail
rendering. Secret-looking assignments, bearer values, private-key material,
and credential-bearing URLs are rejected in every spec and runtime-inventory
string, not only fields whose names appear sensitive.

## Ownership Decision

Read `references/deployment-feature-matrix.json` when reviewing scope or
changing a route. Read `references/source-ledger.md` before updating a product,
version, support, or default claim.

| Work | Canonical owner |
| --- | --- |
| Intake, topology, coverage, consolidated status | This parent (read-only) |
| Core Stack, galileoctl, CRDs, data plane, monitoring, Wizard/GPU | `galileo-on-prem-stack-setup` |
| Packaged Agent Control deployment | `galileo-on-prem-agent-control-setup` |
| Luna Studio deployment and training infrastructure | `galileo-on-prem-luna-studio-setup` |
| Offline charts/images/models and registry-copy handoff | `galileo-on-prem-air-gap-setup` |
| Running-tenant features and model/trace completion | `galileo-platform-setup` |
| Galileo MCP client/server integration | `galileo-mcp-server-setup` |
| Agent Control runtime and Splunk sink workflows | `galileo-agent-control-setup` |
| Lemonade instrumentation | `galileo-lemonade-instrumentation-setup` |

Agent Control and Luna Studio have exactly one deployment owner. When the
pinned package proves umbrella ownership, their deployment children emit a
reviewed overlay for the Stack child; they must not install a second release.

The current Installation Guide defines four platform methods: recommended
galileoctl UI/CLI (Method A), direct umbrella Helm (Method B), the vendor
deployment script (Method C), and ordered charts (Method D). Both Method A
interfaces apply the umbrella chart, and the current guide requires the UI for
the first install. This repository uses direct pinned Helm as the deterministic
inspection and rendering path and represents the other methods as reviewed,
source-backed handoffs without claiming they ran. It is not an executable
automation path; every live change remains a Galileo/CSE joint-session
handoff.

## Examples or Commands

Inspect the complete non-mutating CLI:

```bash
bash skills/galileo-on-prem-kubernetes-setup/scripts/setup.sh --help
```

Render and validate a hash-addressed packet:

```bash
bash skills/galileo-on-prem-kubernetes-setup/scripts/setup.sh \
  --render --validate \
  --spec skills/galileo-on-prem-kubernetes-setup/template.example \
  --galileo-console-url https://console.demo-v2.galileocloud.io/ \
  --output-dir galileo-on-prem-rendered
```

Run the doctor or print static plus chart-runtime coverage status:

```bash
bash skills/galileo-on-prem-kubernetes-setup/scripts/setup.sh \
  --doctor \
  --spec skills/galileo-on-prem-kubernetes-setup/template.example \
  --output-dir galileo-on-prem-rendered

bash skills/galileo-on-prem-kubernetes-setup/scripts/setup.sh \
  --coverage \
  --spec skills/galileo-on-prem-kubernetes-setup/template.example \
  --output-dir galileo-on-prem-rendered --json
```

Inspect an existing immutable bundle:

```bash
bash skills/galileo-on-prem-kubernetes-setup/scripts/setup.sh \
  --status --output-dir galileo-on-prem-rendered --json
```

The output root contains `<deployment-id>/<bundle-sha>/`. If multiple bundles
exist, pass the exact bundle directory to `--status` or `validate.sh`.

## Non-Mutating Contract

The only workflow modes are `--render`, `--doctor`, `--coverage`, and
`--status`; `--validate` is an offline artifact-check modifier. Rendering only
writes the local output directory. The parent never executes emitted handoffs.

Reject `--apply`, `--install`, `--upgrade`, `--rollback`, `--uninstall`,
`--execute`, registry pushes, namespace creation, deletion, inline credentials,
and unknown options before any output is written. Never call Helm, kubectl,
SSH, cloud APIs, registries, child scripts, or the Galileo API from this skill.

A coverage result is complete only when `uncovered`, `unowned`,
`duplicate_mutation_owners`, and `unclassified_runtime_inventory` are empty.
Static documentation coverage can pass while the runtime inventory remains
blocked until a pinned Stack child report is supplied. Do not label a
deployment installed, healthy, production-ready, or GPU-live-validated from a
parent render.

## Validation

```bash
bash skills/galileo-on-prem-kubernetes-setup/scripts/validate.sh \
  --output-dir /exact/path/to/bundle

python3 -m py_compile \
  skills/galileo-on-prem-kubernetes-setup/scripts/render_router.py

PYTHONDONTWRITEBYTECODE=1 python3 \
  skills/galileo-on-prem-kubernetes-setup/scripts/self_test.py
```

Validation regenerates the complete JSON and Markdown packet from the
normalized specification, normalized runtime inventory, current reviewed
matrix, and referenced local artifact evidence. Updating a changed report and
its ordinary manifest hash does not make that report valid.

Read `reference.md` for the deployment-spec, bundle, coverage, state, and
handoff contracts.

## Troubleshooting

| Symptom | Meaning | Resolution |
| --- | --- | --- |
| Unknown or mutation option rejected | The parent is intentionally read-only | Invoke the owning child and satisfy its gates |
| Placeholder or inline secret rejected | Intake is not reviewable or safe | Use exact non-secret values and file paths only |
| `runtime.inventory.pending` | No pinned chart-derived inventory was supplied | Run the Stack child's render/inspection path and reference its report |
| Optional product ownership conflict | Standalone and umbrella ownership overlap | Select one topology supported by the exact package and CSE review |
| Multiple bundles found | Status/validation target is ambiguous | Pass the exact hash-addressed bundle directory |
| Production readiness remains blocked | Required artifacts, infrastructure, approval, evidence, or soak is absent | Review `gap-register.md` and complete the named child handoffs |

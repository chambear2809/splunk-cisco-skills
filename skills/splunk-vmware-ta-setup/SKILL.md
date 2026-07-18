---
name: splunk-vmware-ta-setup
description: "Use when the user asks about VMware, vCenter, ESXi logs, VMware metrics, VMware indexes, VMware
  extractions, or making VMware data ready for Splunk ITSI, Enterprise Security, Monitoring Console, or
  infrastructure dashboards. Install, render, configure, and validate Splunk Supported Add-on coverage for
  VMware, including the VMware app/add-on family, vCenter collection planning, ESXi syslog handoffs, event
  and metric index templates, deployment role placement, ITSI readiness, and post-ingest validation."
compatibility: "Splunk Cloud Platform 10.5.2605: conditional. Follow documented package, entitlement, topology, and customer-managed runtime guardrails; self-managed paths remain on the public 10.4 baseline."
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-07-02"
---

# Splunk VMware TA Setup

## Prerequisites

| Tool or access | Purpose | Verify |
|---|---|---|
| Bash and Python 3 | Run bundled setup and validation helpers | `bash --version && python3 --version` |
| Required product/platform access | Inspect or configure the selected target | Complete the documented preflight |
| Credential files for live modes | Keep secrets out of chat | Verify paths only |

## Workflow Overview

```text
┌───────────┐   ┌───────────────┐   ┌───────────────┐   ┌─────────────────┐
│ Preflight │ → │ Render/review │ → │ Apply/handoff │ → │ Validate evidence │
└───────────┘   └───────────────┘   └───────────────┘   └─────────────────┘
```

## When to Activate

- VMware, vCenter, ESXi logs, VMware metrics, VMware indexes, VMware extractions, or making VMware data ready for
  Splunk ITSI, Enterprise Security, Monitoring Console, or infrastructure dashboards.
- Preview and review the splunk vmware ta setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-vmware-ta-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-vmware-ta-setup/scripts/validate.sh --help
```

Expected output: offline, live, and completion options are displayed when the
skill supports them; help exits without mutation.

## Troubleshooting

| Issue | Cause | Resolution |
|---|---|---|
| Preflight fails | A required tool or access path is missing | Resolve it before rendering or applying |
| Rendered assets are incomplete | Required non-secret inputs are absent | Complete intake and render again |
| Apply is blocked | Review, credentials, or explicit acceptance is missing | Use the documented handoff |
| Validation is incomplete | Live evidence is unavailable | Record the gap and keep completion open |

## TA Completion Gate

For every TA/add-on or dashboard companion run, satisfy the shared
[TA completion gate](../shared/ta_completion_gate.md): configure and enable the
data ingest path owned by this skill or its required companion, validate events
or metrics in the target indexes/source types, and verify any
pre-built/package-shipped dashboards are visible, macro-aligned, and returning
data. If the package ships no dashboards, record that evidence explicitly and
hand off dashboard use to the consuming app, ES/ITSI/ARI content, or readiness
doctor.

Render-first workflow for VMware data onboarding through Splunk Supported
Add-ons. VMware coverage spans multiple glossary entries: VMware, vCenter Logs,
ESXi Logs, VMware Extractions, VMware Indexes, VMware Metrics, and VMware
Metrics Indexes. Treat them as one deployment plan so index placement,
collection ownership, search-time knowledge, and ITSI readiness stay aligned.

## Safety Rules

- Never ask for or pass vCenter passwords, appliance credentials, or Splunk
  secrets in chat, argv, or environment-variable prefixes.
- Use local secret files for credentials, then configure accounts through the
  owning add-on UI or REST handler.
- Do not deploy credential-bearing VMware collection apps broadly through
  Deployment Server. Run each vCenter/DCN collection path on an explicit owner
  to avoid duplicate inventory, task, event, and performance collection.
- Splunk Cloud search-tier package install is separate from customer-managed
  data collection nodes, heavy forwarders, Universal Forwarders, and syslog
  collectors.

## Workflow

1. Render the VMware package:

```bash
bash skills/splunk-vmware-ta-setup/scripts/setup.sh --render \
  --event-index vmware \
  --metrics-index vmware_metrics \
  --esxi-index vmware_esxi \
  --vcenter-account vc_prod
```

2. Review `vmware-plan.md`, `indexes.conf.template`,
   `vcenter-account-runbook.md`, `esxi-syslog-runbook.md`, and
   `itsi-readiness.md`.

3. Install VMware packages through `splunk-app-install` or a customer-approved
   package source. If package files are available locally:

```bash
bash skills/splunk-vmware-ta-setup/scripts/setup.sh --install-package /path/to/package.spl
```

4. Configure vCenter/DCN collection on one owner, configure ESXi syslog to the
   selected syslog path, then run validation:

```bash
bash skills/splunk-vmware-ta-setup/scripts/validate.sh --rendered-dir splunk-vmware-ta-rendered
```

Use `splunk-supported-addons-setup` for glossary resolution and package
handoff, `splunk-data-source-readiness-doctor` after data lands, and
`splunk-itsi-config` for service/entity/KPI modeling.

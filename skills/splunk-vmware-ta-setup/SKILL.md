---
name: splunk-vmware-ta-setup
description: >-
  Install, render, configure, and validate Splunk Supported Add-on coverage for
  VMware, including the VMware app/add-on family, vCenter collection planning,
  ESXi syslog handoffs, event and metric index templates, deployment role
  placement, ITSI readiness, and post-ingest validation. Use when the user asks
  about VMware, vCenter, ESXi logs, VMware metrics, VMware indexes, VMware
  extractions, or making VMware data ready for Splunk ITSI, Enterprise Security,
  Monitoring Console, or infrastructure dashboards.
---

# Splunk VMware TA Setup

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

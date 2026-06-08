---
name: splunk-netapp-ontap-ta-setup
description: >-
  Render, install, and validate package-verified NetApp ONTAP supported add-ons:
  Splunk_TA_ontap, TA-ONTAP-FieldExtractions, and SA-ONTAPIndex. Covers
  scheduler/worker placement, ontap index creation, ontap:* and Hydra source
  type validation, troubleshooting checks, and ITSI storage handoffs. Use when
  the user asks to onboard or validate NetApp Data ONTAP, ONTAP extractions, or
  ONTAP indexes in Splunk.
---

# NetApp ONTAP Supported Add-ons Setup

## TA Completion Gate

For every TA/add-on or dashboard companion run, satisfy the shared
[TA completion gate](../shared/ta_completion_gate.md): configure and enable the
data ingest path owned by this skill or its required companion, validate events
or metrics in the target indexes/source types, and verify any
pre-built/package-shipped dashboards are visible, macro-aligned, and returning
data. If the package ships no dashboards, record that evidence explicitly and
hand off dashboard use to the consuming app, ES/ITSI/ARI content, or readiness
doctor.

Render-first workflow for verified ONTAP packages:

- `Splunk_TA_ontap` `3.2.0`, Splunkbase `3418`
- `TA-ONTAP-FieldExtractions` `3.0.3`, Splunkbase `5615`
- `SA-ONTAPIndex` `3.0.3`, Splunkbase `5616`

## Workflow

```bash
bash skills/splunk-netapp-ontap-ta-setup/scripts/setup.sh --phase render \
  --products ontap,extractions,indexes --index ontap
```

Review `scheduler-worker-placement.md`, install commands, and validation SPL.

```bash
bash skills/splunk-netapp-ontap-ta-setup/scripts/setup.sh --install --create-index \
  --index ontap --no-restart
```

```bash
bash skills/splunk-netapp-ontap-ta-setup/scripts/validate.sh --index ontap
```

Readiness handoff:

```bash
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh \
  --phase collect --source-pack netapp_ontap
```

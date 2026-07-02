---
name: splunk-security-essentials-setup
description: >-
  Install, configure readiness, and validate Splunk Security Essentials
  (`Splunk_Security_Essentials`, Splunkbase app 3435) on Splunk Cloud or
  Splunk Enterprise. Use when a user asks to set up SSE, Security Essentials,
  MITRE/Kill Chain content exploration, Security Content recommendations, or
  starter security posture dashboards.
compatibility: "Splunk Cloud Platform 10.5.2605: conditional. Follow documented package, entitlement, topology, and customer-managed runtime guardrails; self-managed paths remain on the public 10.4 baseline."
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-07-02"
---

# Splunk Security Essentials Setup

## Shared add-on completion gate

Whenever this workflow installs, configures, or hands off SSE, follow the
[shared completion gate](../shared/ta_completion_gate.md). Package delivery
alone is not success; validate security-data prerequisites and shipped
dashboards against data.

Use this skill to install and validate Splunk Security Essentials (SSE).

## Primary Commands

Preview:

```bash
bash skills/splunk-security-essentials-setup/scripts/setup.sh --dry-run
```

Machine-readable preview (emits a single JSON object; useful for agents):

```bash
bash skills/splunk-security-essentials-setup/scripts/setup.sh --dry-run --json
```

Install and validate:

```bash
bash skills/splunk-security-essentials-setup/scripts/setup.sh
```

Validate only:

```bash
bash skills/splunk-security-essentials-setup/scripts/validate.sh
```

## Agent Behavior

- Install `Splunk_Security_Essentials` from Splunkbase app `3435`, or use
  `--file` for an already-downloaded package.
- Keep SSE on the search tier or search head cluster deployer path.
- Do not treat SSE as an Enterprise Security replacement. It can safely coexist
  with ES and includes content references from ES, ES Content Update, and UBA.
- Splunkbase lists SSE through platform `10.5`. Treat that entry as the
  repository's Splunk Cloud compatibility target; it does not change the
  self-managed Enterprise default from `10.4.0` or certify Enterprise `10.5`.
- After install, guide operators through the setup checklist: Data Inventory
  Introspection, Content Mapping, app configuration review, and optional
  posture dashboards.

Read `reference.md` for compatibility notes and source links.

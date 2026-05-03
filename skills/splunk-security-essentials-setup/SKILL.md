---
name: splunk-security-essentials-setup
description: >-
  Install, configure readiness, and validate Splunk Security Essentials
  (`Splunk_Security_Essentials`, Splunkbase app 3435) on Splunk Cloud or
  Splunk Enterprise. Use when a user asks to set up SSE, Security Essentials,
  MITRE/Kill Chain content exploration, Security Content recommendations, or
  starter security posture dashboards.
---

# Splunk Security Essentials Setup

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
- After install, guide operators through the setup checklist: Data Inventory
  Introspection, Content Mapping, app configuration review, and optional
  posture dashboards.

Read `reference.md` for compatibility notes and source links.

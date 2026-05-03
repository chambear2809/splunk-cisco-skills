---
name: splunk-attack-analyzer-setup
description: >-
  Install, configure readiness, and validate Splunk Attack Analyzer platform
  integration using Splunk Add-on for Splunk Attack Analyzer
  (`Splunk_TA_SAA`, app 6999) and Splunk App for Splunk Attack Analyzer
  (`Splunk_App_SAA`, app 7000). Use when a user asks for Attack Analyzer, SAA,
  phishing and malware analysis data ingestion, the `saa` index, `saa_indexes`
  macro, or Enterprise Security adaptive response readiness.
---

# Splunk Attack Analyzer Setup

Use this skill for the Splunk platform side of Splunk Attack Analyzer.

## Primary Commands

Preview:

```bash
bash skills/splunk-attack-analyzer-setup/scripts/setup.sh --dry-run --json
```

Install app/add-on, prepare `saa`, configure the dashboard macro, and validate:

```bash
bash skills/splunk-attack-analyzer-setup/scripts/setup.sh
```

Validate only:

```bash
bash skills/splunk-attack-analyzer-setup/scripts/validate.sh
```

## Agent Behavior

- Install both `Splunk_TA_SAA` and `Splunk_App_SAA` by default.
- Create or validate the events index, defaulting to `saa`.
- Configure the app macro `saa_indexes` to the selected index.
- Never ask for or pass the Attack Analyzer API key in chat or argv; use
  `--api-key-file` only for readiness checks and operator handoff.
- Treat tenant connection and input creation as a licensed tenant workflow
  unless a supported app REST contract is verified in the target deployment.

Read `reference.md` for source links, app IDs, and handoff notes.

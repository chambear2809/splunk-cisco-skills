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

## Prerequisites

- A Splunk credentials file readable by the shared credential helper. If not
  yet configured, run
  `bash skills/shared/scripts/setup_credentials.sh`
  or copy `credentials.example` and edit it (`chmod 600 credentials`).
- Both Splunkbase apps come from the
  [`splunk-app-install`](../splunk-app-install/SKILL.md) skill via
  `skills/splunk-app-install/scripts/install_app.sh`. This wrapper handles
  Splunkbase auth, ACS upload, and version pinning so the Attack Analyzer
  setup never embeds those flows.

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

- Install both `Splunk_TA_SAA` and `Splunk_App_SAA` by default. The add-on is
  installed first; if it fails the dashboard app is **not** attempted, and if
  the dashboard install fails after the add-on succeeded the script prints a
  rollback hint pointing at
  `skills/splunk-app-install/scripts/uninstall_app.sh`.
- Create or validate the events index, defaulting to `saa`.
- Configure the app macro `saa_indexes` to the selected index.
- Never ask for or pass the Attack Analyzer API key in chat or argv; use
  `--api-key-file` only for readiness checks and operator handoff.
- Treat tenant connection and input creation as a licensed tenant workflow
  unless a supported app REST contract is verified in the target deployment.

Read `reference.md` for source links, app IDs, and handoff notes.

## MCP Tools

This skill includes checked-in, read-only Splunk MCP custom tools generated
from `mcp_tools.source.yaml`.

Validate or regenerate the tool artifact:

```bash
python3 skills/shared/scripts/mcp_tools.py validate skills/splunk-attack-analyzer-setup
python3 skills/shared/scripts/mcp_tools.py generate skills/splunk-attack-analyzer-setup
```

Load the tools into Splunk MCP Server:

```bash
bash skills/splunk-attack-analyzer-setup/scripts/load_mcp_tools.sh
```

The loader uses the supported `/mcp_tools` REST batch endpoint by default. Use
`--allow-legacy-kv` only for older MCP Server app versions that lack that
endpoint.

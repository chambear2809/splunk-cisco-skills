---
name: splunk-itsi-setup
description: >-
  Install and validate Splunk IT Service Intelligence (ITSI) on Splunk Cloud or
  Splunk Enterprise. Handles installation from Splunkbase with local fallback,
  validates core ITSI components, and checks integration readiness for apps
  like Cisco ThousandEyes. Use when the user asks about ITSI, IT Service
  Intelligence, AIOps, service monitoring, SA-ITOA, or event analytics.
---

# Splunk ITSI Setup Automation

Automates installation and validation of **Splunk IT Service Intelligence**
(`SA-ITOA`).

## About ITSI

ITSI is a premium Splunk product for AI-powered IT operations monitoring. It
provides service-level visibility, ML-based anomaly detection, event
correlation, and glass table dashboards. ITSI is also a dependency for
bidirectional integrations in apps like Cisco ThousandEyes.

ITSI requires a valid Splunk ITSI license. The install skill handles package
delivery but does not manage licensing.

## Package Model

**Pull from Splunkbase first (latest version), fall back to `splunk-ta/`.**
Use `splunk-app-install` with `--source splunkbase --app-id 1841` to get the
latest release. If Splunkbase is unavailable, fall back to the local package
in `splunk-ta/`. This applies to both Splunk Cloud (ACS) and Splunk Enterprise.

After installation, use this skill to validate the deployment and check
integration readiness for dependent apps (e.g., ThousandEyes).

## Agent Behavior — Credentials

**The agent must NEVER ask for passwords or secrets in chat.**

Splunk and Splunkbase credentials are read automatically from the project-root
`credentials` file (falls back to `~/.splunk/credentials`). If neither exists,
guide the user to create it:

```bash
bash skills/shared/scripts/setup_credentials.sh
```

ITSI does not require additional device credentials or API keys beyond the
standard Splunk authentication.

## Environment

| Item | Value |
|------|-------|
| Search-tier API | `SPLUNK_SEARCH_API_URI` env var (legacy alias: `SPLUNK_URI`) |
| Cloud stack | `SPLUNK_CLOUD_STACK` for Cloud installs |
| App name | `SA-ITOA` (also installs `itsi` and supporting apps) |
| Splunkbase ID | 1841 |
| Credentials | Project-root `credentials` file (falls back to `~/.splunk/credentials`) |
| Skill scripts | `skills/splunk-itsi-setup/scripts/` (relative to repo root) |

### Remote Splunk Connection

```bash
export SPLUNK_SEARCH_API_URI="https://splunk-host:8089"
```

## Setup Workflow

### Step 1: Install ITSI

```bash
bash skills/splunk-app-install/scripts/install_app.sh \
  --source splunkbase --app-id 1841
```

If Splunkbase is unavailable, fall back to a local package:

```bash
bash skills/splunk-app-install/scripts/install_app.sh \
  --source local --file splunk-ta/itsi_package.spl
```

ITSI installs multiple apps including `SA-ITOA`, `itsi`, `SA-UserAccess`, and
supporting components. The Splunkbase package bundles all of them.

### Step 2: Restart If Required

On Splunk Enterprise, restart Splunk after installation.
On Splunk Cloud, check `acs status current-stack` and only run
`acs restart current-stack` when ACS reports `restartRequired=true`.

### Step 3: Validate

```bash
bash skills/splunk-itsi-setup/scripts/validate.sh
```

Checks: core ITSI apps installed, KVStore collections available, ITSI
navigation accessible, and integration readiness for dependent apps.

## ITSI Core Apps

| App | Purpose |
|-----|---------|
| `SA-ITOA` | ITSI core engine — service definitions, KPIs, event management |
| `itsi` | ITSI UI — glass tables, service analyzer, deep dives |
| `SA-UserAccess` | Role-based access control for ITSI |
| `SA-ITSI-Licensechecker` | ITSI license validation |

## Integration Points

### Cisco ThousandEyes

When ITSI is installed alongside the ThousandEyes app (`ta_cisco_thousandeyes`),
the following integrations become available:

- **Alert action**: `thousandeyes_forward_splunk_events` forwards ITSI notable
  events to ThousandEyes
- **Event sampling**: Controlled event forwarding rate to ThousandEyes
- **KVStore**: `itsi_episodes` tracks episode state for ThousandEyes correlation

The ThousandEyes validate script automatically detects ITSI presence and
reports integration readiness.

## Key Learnings / Known Issues

1. **License required**: ITSI is a premium product. Installation will succeed
   but full functionality requires a valid ITSI license applied to the Splunk
   instance.
2. **Multiple apps**: ITSI installs as a bundle of several apps. `SA-ITOA` is
   the primary app to check for when verifying installation.
3. **Cloud considerations**: On Splunk Cloud, ITSI installation may require
   coordination with Splunk Cloud support depending on your stack type.
4. **KVStore dependency**: ITSI relies heavily on KVStore. Ensure KVStore is
   healthy before and after installation.
5. **Restart required**: ITSI always requires a Splunk restart after
   installation.

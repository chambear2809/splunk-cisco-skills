---
name: splunk-ai-assistant-setup
description: >-
  Install, validate, and help complete Splunk AI Assistant for SPL
  (`Splunk_AI_Assistant_Cloud`) setup on Splunk Cloud or Splunk Enterprise.
  Handles Splunkbase installation with the shared app installer, checks
  post-install health, and supports Enterprise cloud-connected onboarding,
  activation, and proxy configuration. Use when the user asks about
  splunk-ai-assistant, Splunk AI Assistant for SPL, AI Assistant for SPL, or
  the `Splunk_AI_Assistant_Cloud` app.
---

# Splunk AI Assistant for SPL Setup

Automates installation, validation, and Enterprise setup assistance for
**Splunk AI Assistant for SPL** (`Splunk_AI_Assistant_Cloud`).

## What This Skill Covers

This skill handles three operator tasks:

1. Install or update the app from Splunkbase with the shared installer
2. Validate that the app is present, reachable, and in a usable setup state
3. Drive the Enterprise cloud-connected onboarding, activation, and proxy flow

The install path is intentionally thin. It delegates package delivery to
`splunk-app-install` and only adds the product-specific rules that matter for
this app.

## Package Model

- Primary path: Splunkbase app ID `7245`
- Internal app name: `Splunk_AI_Assistant_Cloud`
- Install on search heads only
- Prefer the latest compatible release by omitting `--app-version`
- Do not model this as a private-app upload on Splunk Cloud

For Splunk Cloud, the shared installer uses ACS Splunkbase install behavior.
For Splunk Enterprise, the shared installer downloads from Splunkbase and
installs through the management API.

## Agent Behavior — Credentials

**The agent must NEVER ask for passwords, tokens, or other secrets in chat.**

Splunk and Splunkbase credentials are read automatically from the project-root
`credentials` file (falls back to `~/.splunk/credentials`). If neither exists,
guide the user to create it:

```bash
bash skills/shared/scripts/setup_credentials.sh
```

The agent may ask only for non-secret values such as:
- whether the user wants a pinned app version
- onboarding email, region, company name, or tenant name
- whether the Enterprise target is standalone or part of a search head cluster

Activation codes and proxy passwords must come from local files, not from chat.

## Environment

| Item | Value |
|------|-------|
| Search-tier API | `SPLUNK_SEARCH_API_URI` env var (legacy alias: `SPLUNK_URI`) |
| Cloud stack | `SPLUNK_CLOUD_STACK` for Splunk Cloud installs |
| App name | `Splunk_AI_Assistant_Cloud` |
| Splunkbase ID | `7245` |
| Credentials | Project-root `credentials` file (falls back to `~/.splunk/credentials`) |
| Skill scripts | `skills/splunk-ai-assistant-setup/scripts/` |

### Remote Splunk Connection

```bash
export SPLUNK_SEARCH_API_URI="https://splunk-host:8089"
```

## Setup Workflow

### Step 1: Install Or Update The App

```bash
bash skills/splunk-ai-assistant-setup/scripts/setup.sh --install
```

To pin a specific release:

```bash
bash skills/splunk-ai-assistant-setup/scripts/setup.sh \
  --install \
  --app-version X.Y.Z
```

When no flags are passed, the setup script performs install plus validation.

### Step 2: Complete Platform-Specific Onboarding

**Splunk Cloud**

- The app must be installed from the public Splunkbase listing, not as a
  private upload of a downloaded archive.
- Splunk Cloud self-service installs are supported only on eligible commercial
  stacks and supported regions.
- This skill does not automate Cloud-side onboarding because the Enterprise
  cloud-connected flow does not apply there.

**Splunk Enterprise (cloud connected)**

- The search head must be able to reach `*.scs.splunk.com` on `443`
- Optional: configure the outbound proxy first if the search head needs one:

```bash
bash skills/splunk-ai-assistant-setup/scripts/setup.sh \
  --set-proxy \
  --proxy-url https://proxy.example.com:8443
```

- Submit the onboarding form through the app backend:

```bash
bash skills/splunk-ai-assistant-setup/scripts/setup.sh \
  --submit-onboarding-form \
  --email ops@example.com \
  --region usa \
  --company-name Example \
  --tenant-name example-prod
```

- Use the app's region token here. The current US commercial token is `usa`,
  and the script normalizes common aliases such as `us` to `usa`
- After the form is submitted, the setup script reruns validation so the
  operator can see the expected pending-activation state immediately
- Save the activation code/token to a local file, then complete activation:

```bash
bash skills/splunk-ai-assistant-setup/scripts/setup.sh \
  --complete-onboarding \
  --activation-code-file /tmp/saia_activation_code
```

- If the target is a search head cluster and deployer-target credentials are
  configured, the shared installer can deliver through the Deployer bundle path
- Activation still uses Splunk-managed cloud services and may require an
  activation token obtained from the Splunk onboarding flow
- The remaining blocker after form submission is the Splunk-issued activation
  code/token, which may not be available immediately
- Proxy credentials and activation codes are read from local files only

### Step 3: Validate

```bash
bash skills/splunk-ai-assistant-setup/scripts/validate.sh
```

Checks:
- app installed and visible
- app configured state and app-owned REST reachability
- Splunk API authentication works
- KV Store health is readable
- Enterprise onboarding state: not started, submitted, or fully onboarded
- Enterprise proxy state

Optional automation assertions:

```bash
bash skills/splunk-ai-assistant-setup/scripts/validate.sh \
  --expect-configured true \
  --expect-onboarded true
```

## Notes

- Chat data for the assistant is stored in the local KV Store on the customer
  stack, so KV Store readiness matters for validation.
- The validator intentionally avoids the app's `/config` and
  `/get_feature_flags` endpoints for readiness checks because they can error
  before onboarding is complete.
- SHC delivery depends on the shared installer and deployer-target credentials,
  not on app-specific SHC logic in this skill.

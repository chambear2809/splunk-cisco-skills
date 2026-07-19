---
name: cisco-webex-setup
description: Use when configuring Webex OAuth, meetings, audit, calling, quality, or Contact Center data in Splunk.
compatibility: >-
  Splunk Cloud Platform 10.5.2605: conditional. Follow documented package,
  entitlement, topology, and customer-managed runtime guardrails; self-managed
  paths remain on the public 10.4 baseline.
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-07-02"
---

# Cisco Webex Setup

## Prerequisites

| Tool or access | Purpose | Verify |
|---|---|---|
| Bash, `curl`, and `jq` | Run setup and REST configuration helpers | `command -v bash curl jq` |
| Splunk administrative access | Install the add-on/app and configure inputs | Confirm search-tier REST access |
| Webex OAuth application | Authorize selected organizations and endpoints | Store client material in protected files |

## Workflow Overview

```text
┌───────────┐   ┌────────────────┐   ┌──────────────────┐   ┌────────────────────┐
│ Preflight │ → │ Install add-on │ → │ Configure inputs │ → │ Validate dashboards │
└───────────┘   └────────────────┘   └──────────────────┘   └────────────────────┘
```

## When to Activate

- Onboard Webex Meetings, administrative audit, quality, or calling data.
- Configure generic Webex REST or Contact Center search inputs.
- Diagnose OAuth, index, source-type, macro, or dashboard failures.

## Scope

This skill configures documented Webex collection and dashboard prerequisites.
It does not create OAuth applications, expose tokens in chat, or enable every
endpoint without reviewing scope, privacy, rate limits, and event volume.

## Examples

Install the Webex add-on and companion app:

```bash
bash skills/cisco-webex-setup/scripts/setup.sh --install
```

Expected output: required packages and index/macro prerequisites are installed
or a topology-specific manual handoff is emitted.

Run strict completion checks after configuring selected inputs:

```bash
bash skills/cisco-webex-setup/scripts/validate.sh --completion
```

Expected output: package, OAuth account, enabled input, event, macro, and
dashboard evidence report `[PASS]`; incomplete coverage exits nonzero.

## Troubleshooting

| Issue | Cause | Resolution |
|---|---|---|
| OAuth returns 401/403 | Grant/scope is wrong | Correct app and credential files |
| API returns 429 | Input scope or interval exceeds rate limits | Reduce endpoints or increase polling intervals |
| One dataset is absent | Its dedicated input is disabled or unauthorized | Validate each selected input independently |
| Empty dashboards | Macro/source type is wrong | Validate events before dashboards |

## TA Completion Gate

For every TA/add-on or dashboard companion run, satisfy the shared
[TA completion gate](../shared/ta_completion_gate.md): configure and enable the
data ingest path owned by this skill or its required companion, validate events
or metrics in the target indexes/source types, and verify any
pre-built/package-shipped dashboards are visible, macro-aligned, and returning
data. If the package ships no dashboards, record that evidence explicitly and
hand off dashboard use to the consuming app, ES/ITSI/ARI content, or readiness
doctor.

Automates the Webex Add-on for Splunk (`ta_cisco_webex_add_on_for_splunk`,
Splunkbase `8365`) and the companion Webex App dashboards
(`cisco_webex_meetings_app_for_splunk`, Splunkbase `4992`).

## Package Model

Install public Splunkbase packages through `splunk-app-install` first. The
normal workflow installs both the add-on and app, then this skill creates the
dashboard indexes/macros and configures Webex REST accounts/inputs over Splunk
REST.

Package-derived defaults:

| Area | Default |
|------|---------|
| Meetings / audit / quality reports index | `wx` |
| Detailed call history index | `wxc` |
| Contact Center index | `wxcc` |
| Account endpoint | `webexapis.com` |
| Timestamp format | `YYYY-MM-DDTHH:MM:SSZ` |

## Credentials

Never ask for Webex client secrets, access tokens, or refresh tokens in chat.
Proxy passwords must use the same local secret-file pattern. Use local secret
files:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/webex_client_secret
```

Splunk credentials are read from the project-root `credentials` file or
`~/.splunk/credentials`.

## Workflow

1. Install packages and configure indexes/macros:

```bash
bash skills/cisco-webex-setup/scripts/setup.sh --install
```

2. Configure the Webex OAuth account:

```bash
bash skills/cisco-webex-setup/scripts/configure_account.sh \
  --name WEBEX_PROD \
  --client-id "client-id" \
  --client-secret-file /tmp/webex_client_secret \
  --scope "meeting:admin_schedule_read spark-admin:people_read" \
  --redirect-url "https://example.splunkcloud.com/en-US/app/ta_cisco_webex_add_on_for_splunk/oauth_redirect"
```

3. Create inputs as needed:

```bash
bash skills/cisco-webex-setup/scripts/configure_inputs.sh \
  --account WEBEX_PROD \
  --input-type core \
  --start-time "2026-05-01T00:00:00Z" \
  --site-url "https://yoursite.webex.com"
```

`--site-url` is required for the `core` batch because it includes the
`meetings_summary_report` input. Omitting it makes the `core` run fail when it
reaches that input.

4. Validate:

```bash
bash skills/cisco-webex-setup/scripts/validate.sh --completion
```

## Input Coverage

Use `configure_inputs.sh --input-type` with one of:

- `core`: scheduled meetings, admin audit, security audit, meeting qualities,
  meeting summary reports, detailed call history.
- `meetings`, `meetings_summary_report`, `admin_audit_events`,
  `security_audit_events`, `meeting_qualities`, `detailed_call_history`.
- `generic_endpoint`: requires `--webex-endpoint`; do not include a leading `/`.
  Use `--webex-base-url` when the endpoint needs a host other than
  `webexapis.com`.
- `contact_center_search`: requires `--org-id` and
  `--webex-contact-center-region`; templates are `AAR`, `ASR`, `CAR`, `CSR`.

Detailed call history accepts `--account-region` and `--locations`, but the
packaged REST handler has a narrow `locations` validator. Prefer omitting
`--locations` unless the installed package has been verified for the intended
value format.

See `reference.md` for the package-derived sourcetypes, scopes, and timing
guardrails.

## Validation Modes

Run `scripts/validate.sh` for diagnostics. Use `--completion` (alias `--strict`)
to require the Webex add-on and dashboard app, dashboard macros/views, an OAuth
account, an enabled input, and event data in the Webex indexes.

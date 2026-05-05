---
name: cisco-webex-setup
description: >-
  Install, configure, and validate the Webex Add-on for Splunk and companion
  Webex App dashboards. Covers Webex REST OAuth accounts, meetings, admin and
  security audit, meeting qualities, detailed call history, generic endpoints,
  and Webex Contact Center search inputs. Use when the user asks about Cisco
  Webex, Webex Meetings, Webex Calling, Webex Contact Center, or Webex Splunk
  dashboard readiness.
---

# Cisco Webex Setup

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
  --start-time "2026-05-01T00:00:00Z"
```

4. Validate:

```bash
bash skills/cisco-webex-setup/scripts/validate.sh
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

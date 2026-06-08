---
name: splunk-okta-ta-setup
description: >-
  Install, render, configure, and validate the Splunk Add-on for Okta Identity
  Cloud (Splunk_TA_okta_identity_cloud, Splunkbase 6553). Renders real
  inputs.conf stanzas for the okta_identity_cloud modular input across the log,
  user, group, app, groupUser, and appUser metrics (OktaIM2:* source types),
  emits an OAuth 2.0 client-credentials or API-token account runbook, creates
  the okta index, maps source types to CIM, and validates ingestion. Use when
  the user asks about Splunk_TA_okta_identity_cloud, the Splunk Add-on for Okta
  Identity Cloud, Okta System Log, OktaIM2, Okta Universal Directory, or Okta
  authentication onboarding in Splunk.
---

# Splunk Add-on for Okta Identity Cloud Setup

## TA Completion Gate

For every TA/add-on or dashboard companion run, satisfy the shared
[TA completion gate](../shared/ta_completion_gate.md): configure and enable the
data ingest path owned by this skill or its required companion, validate events
or metrics in the target indexes/source types, and verify any
pre-built/package-shipped dashboards are visible, macro-aligned, and returning
data. If the package ships no dashboards, record that evidence explicitly and
hand off dashboard use to the consuming app, ES/ITSI/ARI content, or readiness
doctor.

Render-first automation for the **Splunk Add-on for Okta Identity Cloud**
(`Splunk_TA_okta_identity_cloud`, Splunkbase `6553`). The add-on ingests Okta
System Log events and Universal Directory state (users, groups, apps) through
Okta's REST API, with full CIM coverage for Enterprise Security.

The add-on runs on the search tier or a heavy forwarder (no indexer or
Universal Forwarder role). Run inputs on a single node to avoid duplicates.

## Metrics And Source Types

A single modular input `okta_identity_cloud` collects one data type per stanza,
selected by `metric`:

| `metric` | Source type | Notes |
| --- | --- | --- |
| `log` | `OktaIM2:log` | System Log events (primary security feed) |
| `user` | `OktaIM2:user` | Universal Directory users (state) |
| `group` | `OktaIM2:group` | Universal Directory groups |
| `app` | `OktaIM2:app` | Universal Directory applications |
| `groupUser` | `OktaIM2:groupUser` | Group membership |
| `appUser` | `OktaIM2:appUser` | App assignment |

## Credentials

Never paste an Okta API token or client secret in chat or argv. Prefer **OAuth
2.0 client credentials**. Write the secret to a local file and configure the
account in the add-on Configuration tab:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/okta_client_secret
```

See the rendered `account-setup.md` for both the OAuth and API-token modes and
the required Okta scopes.

## Workflow

1. Render reviewable assets (offline):

```bash
bash skills/splunk-okta-ta-setup/scripts/setup.sh --render \
  --index okta --account-name okta_prod --metrics log,user,group,app
```

2. Install the add-on and create the index:

```bash
bash skills/splunk-okta-ta-setup/scripts/setup.sh --install --create-index --index okta
```

3. Configure the account (`account-setup.md`) and enable the rendered inputs.

4. Validate:

```bash
bash skills/splunk-okta-ta-setup/scripts/validate.sh --index okta
```

5. Score post-ingest readiness:

```bash
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh \
  --phase collect --source-pack okta_identity_cloud
```

See `reference.md` for the full input/account model, source types, CIM mapping,
and placement guardrails.

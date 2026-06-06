---
name: splunk-microsoft-exchange-ta-setup
description: >-
  Render, install, and validate the package-verified Microsoft Exchange
  supported add-on bundle and Exchange Indexes package. Covers
  TA-Exchange-ClientAccess, TA-Exchange-Mailbox, TA-SMTP-Reputation,
  TA-Windows-Exchange-IIS, SA-ExchangeIndex, package-derived source types,
  Windows collection placement, msexchange/perfmon/windows/wineventlog/msad
  index readiness, and readiness-doctor handoffs. Use when the user asks for
  Splunk Supported Add-on for Microsoft Exchange onboarding and validation.
---

# Microsoft Exchange Supported Add-on Setup

Render-first workflow for the verified Microsoft Exchange packages:

- Exchange bundle `4.1.0`, Splunkbase `3225`
- Exchange Indexes `SA-ExchangeIndex` `4.0.4`, Splunkbase `5663`

## Workflow

```bash
bash skills/splunk-microsoft-exchange-ta-setup/scripts/setup.sh --phase render \
  --index msexchange --windows-index windows --perfmon-index perfmon
```

Review `collection-placement.md`, `inputs.local.conf.template`,
`install-commands.sh`, and `validation-searches.spl`.

```bash
bash skills/splunk-microsoft-exchange-ta-setup/scripts/setup.sh --install --no-restart
```

```bash
bash skills/splunk-microsoft-exchange-ta-setup/scripts/validate.sh --index msexchange
```

Readiness handoff:

```bash
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh \
  --phase collect --source-pack microsoft_exchange
```

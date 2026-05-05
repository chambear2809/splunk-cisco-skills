---
name: cisco-ucs-ta-setup
description: >-
  Install, configure, and validate the Splunk Add-on for Cisco UCS
  (Splunk_TA_cisco-ucs). Covers UCS Manager server records, encrypted
  passwords, default/custom templates, cisco_ucs_task inputs, indexes, and
  cisco:ucs data validation. Use when the user asks about Cisco UCS, UCS
  Manager, Fabric Interconnects, Splunk_TA_cisco-ucs, or cisco:ucs telemetry.
---

# Cisco UCS TA Setup

Automates the Splunk Add-on for Cisco UCS (`Splunk_TA_cisco-ucs`, Splunkbase
`2731`) using the package's REST handlers and configuration model.

## Package Model

Install with `splunk-app-install --source splunkbase --app-id 2731`. This
skill then creates the `cisco_ucs` index, configures default class-ID
templates, creates UCS Manager server records, and enables `cisco_ucs_task`
inputs.

## Credentials

Never ask for UCS passwords in chat. Ask the user to create a local secret file:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/ucs_password
```

Then pass `--password-file /tmp/ucs_password`.

## Workflow

1. Install and initialize:

```bash
bash skills/cisco-ucs-ta-setup/scripts/setup.sh --install
```

2. Configure one UCS Manager:

```bash
bash skills/cisco-ucs-ta-setup/scripts/configure_server.sh \
  --name UCS_PROD \
  --server-url ucs-manager.example.com \
  --account-name splunk \
  --password-file /tmp/ucs_password
```

3. Configure an input task:

```bash
bash skills/cisco-ucs-ta-setup/scripts/configure_task.sh \
  --name UCS_PROD_all \
  --servers UCS_PROD \
  --templates UCS_Fault,UCS_Inventory,UCS_Performance \
  --index cisco_ucs
```

4. Validate:

```bash
bash skills/cisco-ucs-ta-setup/scripts/validate.sh
```

See `reference.md` for default templates and package-derived CIM/source details.

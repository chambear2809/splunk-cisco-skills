---
name: cisco-security-cloud-setup
description: >-
  Install and configure Cisco Security Cloud (CiscoSecurityCloud). Supports
  Cisco Duo, XDR, Secure Endpoint, Secure Firewall, ETD, Secure Network
  Analytics, CII, Secure Workload, and other Cisco Security Cloud inputs. Use
  when the user asks about Cisco Security Cloud, app ID 7404, or CiscoSecurityCloud.
---

# Cisco Security Cloud Setup

Automates installation and input configuration of **Cisco Security Cloud**
(`CiscoSecurityCloud`).

## Package Model

**Pull from Splunkbase first (latest version), fall back to `splunk-ta/`.**
Use the setup script with `--install` to install app ID `7404`. The script uses
the shared installer and falls back to the local package
`cisco-security-cloud_*.tar.gz` when needed.

This package is a multi-input Cisco Security app. It supports many product
integrations through app-managed custom REST handlers rather than simple flat
conf-file edits.

## Agent Behavior — Credentials

**The agent must NEVER ask for passwords, API keys, client secrets, refresh
tokens, certificates, or other secrets in chat.**

Splunk credentials are read from the project-root `credentials` file (falls
back to `~/.splunk/credentials`). If neither exists, guide the user to create
it:

```bash
bash skills/shared/scripts/setup_credentials.sh
```

For product secrets, instruct the user to write them to temporary files:

```bash
printf '%s' "the_secret_value" > /tmp/secret.txt && chmod 600 /tmp/secret.txt
```

Then pass those files with `--secret-file FIELD /tmp/secret.txt` to the
configuration script.

## Environment

This app supports standalone, distributed, and search head clustering
deployments. It can be installed on Splunk Enterprise or Splunk Cloud.

| Item | Value |
|------|-------|
| Search-tier API | `SPLUNK_SEARCH_API_URI` env var (legacy alias: `SPLUNK_URI`) |
| Cloud stack | `SPLUNK_CLOUD_STACK` for Cloud installs |
| App name | `CiscoSecurityCloud` |
| Splunkbase ID | `7404` |
| Credentials | Project-root `credentials` file (falls back to `~/.splunk/credentials`) |
| Skill scripts | `skills/cisco-security-cloud-setup/scripts/` |

## Setup Workflow

### Step 1: Install The App

```bash
bash skills/cisco-security-cloud-setup/scripts/setup.sh --install
```

### Step 2: Optionally Set Logging

```bash
bash skills/cisco-security-cloud-setup/scripts/setup.sh --set-log-level INFO
```

### Step 3: Configure One Product Flow

Use `configure_product.sh` for the user-facing flow. It maps a product name to
the correct `CiscoSecurityCloud_*` handler, fills in product defaults, and then
delegates to the shared input engine.

List the supported product keys:

```bash
bash skills/cisco-security-cloud-setup/scripts/configure_product.sh --list-products
```

Example: Cisco XDR

```bash
bash skills/cisco-security-cloud-setup/scripts/configure_product.sh \
  --product xdr \
  --set region us \
  --set auth_method client_id \
  --set client_id example-client-id \
  --set xdr_import_time_range "7 days ago" \
  --secret-file refresh_token /tmp/xdr_refresh_token
```

Example: Cisco Secure Endpoint

```bash
bash skills/cisco-security-cloud-setup/scripts/configure_product.sh \
  --product secure_endpoint \
  --set api_host api.amp.cisco.com \
  --set client_id example-client-id \
  --set se_import_time_range "7 days ago" \
  --set event_types "event,group" \
  --set groups "group-guid" \
  --secret-file api_key /tmp/secure_endpoint_api_key
```

The wrapper applies product defaults such as index, interval, and sourcetype
when the package exposes them. Use `configure_input.sh` only for advanced or
unsupported edge cases.

### Step 4: Validate

```bash
bash skills/cisco-security-cloud-setup/scripts/validate.sh
```

To validate one specific product flow:

```bash
bash skills/cisco-security-cloud-setup/scripts/validate.sh \
  --product xdr \
  --name XDR_Default
```

## Supported Product Flows

The product-specific wrapper currently covers all packaged Cisco Security Cloud
integrations:

- `duo`
- `secure_malware_analytics`
- `xdr`
- `secure_firewall_syslog`
- `secure_firewall_asa_syslog`
- `secure_firewall_estreamer`
- `secure_firewall_api`
- `multicloud_defense`
- `email_threat_defense`
- `secure_network_analytics`
- `secure_endpoint`
- `vulnerability_intelligence`
- `cii_webhook`
- `cii_aws_s3`
- `ai_defense`
- `isovalent`
- `isovalent_edge_processor`
- `secure_client_nvm`
- `secure_workload`

See [reference.md](reference.md) for the product matrix with defaults, required
fields, and secret fields. Use [template.example](template.example) to collect
non-secret values before running the configuration script.

## Key Learnings / Known Issues

1. **Custom handler model**: This app uses app-specific admin handlers rather
   than simple manual conf edits for most inputs.
2. **Many integrations, one app**: Use the product-specific wrapper and only
   configure the Cisco product inputs the user actually needs.
3. **Secrets belong in temp files**: API keys, passwords, tokens, and certs
   should be passed through `--secret-file`, never pasted into chat.
4. **Index choice is per input**: Most integrations have product-specific
   default indexes, but you can override them when appropriate.

## Additional Resources

- [reference.md](reference.md) — product matrix and endpoint details
- [products.json](products.json) — product-to-handler metadata used by the wrapper
- [template.example](template.example) — non-secret intake worksheet

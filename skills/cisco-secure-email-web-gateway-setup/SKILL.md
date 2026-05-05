---
name: cisco-secure-email-web-gateway-setup
description: >-
  Install, configure, and validate the Splunk-supported Cisco ESA and WSA
  add-ons. Covers ESA/WSA indexes, macros, parser placement, SC4S/file-monitor
  ingestion handoffs, source/sourcetype coverage, and CIM validation. Use when
  the user asks about Cisco Secure Email Gateway, ESA, WSA, IronPort, email
  security, web security, or Cisco ESA/WSA Splunk add-ons.
---

# Cisco Secure Email/Web Gateway Setup

Automates Splunk-side setup for:

- Cisco Email Security Appliance add-on (`Splunk_TA_cisco-esa`, Splunkbase
  `1761`)
- Cisco Web Security Appliance add-on (`Splunk_TA_cisco-wsa`, Splunkbase
  `1747`)

These packages are parser/search-time add-ons. They do not contain device API
inputs, credentials, or custom REST account handlers. Collection is handled by
ESA/WSA syslog export, SC4S, or file-monitor deployment.

## Workflow

Install and configure one or both products:

```bash
bash skills/cisco-secure-email-web-gateway-setup/scripts/setup.sh \
  --product both \
  --install
```

Render collector handoff assets:

```bash
bash skills/cisco-secure-email-web-gateway-setup/scripts/render_ingestion_assets.sh \
  --product both \
  --output-dir ./cisco-secure-email-web-gateway-rendered
```

Validate Splunk-side readiness:

```bash
bash skills/cisco-secure-email-web-gateway-setup/scripts/validate.sh --product both
```

## Defaults

| Product | App | Index | Macro |
|---|---|---|---|
| ESA | `Splunk_TA_cisco-esa` | `email` | `Cisco_ESA_Index` |
| WSA | `Splunk_TA_cisco-wsa` | `netproxy` | `Cisco_WSA_Index` |

Use `splunk-connect-for-syslog-setup` for SC4S runtime deployment. This skill
only prepares the Splunk-side add-ons, indexes, macros, and rendered handoff
snippets.

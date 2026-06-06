# Splunk_TA_github Reference

Package source of truth: `splunk-ta/_unpacked/Splunk_TA_github-3.3.0/Splunk_TA_github`.

## Inputs

| Input | Source type |
| --- | --- |
| `github_audit_input://<name>` | `github:cloud:audit` |
| `github_user_input://<name>` | `github:cloud:user` |
| `github_alerts_input://<name>` with `alert_type=code_scanning_alerts` | `github:cloud:code:scanning:alerts` |
| `github_alerts_input://<name>` with `alert_type=dependabot_alerts` | `github:cloud:dependabot:scanning:alerts` |
| `github_alerts_input://<name>` with `alert_type=secret_scanning_alerts` | `github:cloud:secret:scanning:alerts` |

The package props also cover `github:enterprise:audit`.

## Guardrails

- Configure PAT or GitHub App token only through the add-on account
  `Splunk_TA_github_account`.
- Use `splunk-hec-service-setup` for HEC token creation and constrain generic
  `httpevent` audit streaming by `source=http:github`.
- Use SC4S/syslog handoffs for GitHub Enterprise Server audit logs where
  appropriate.
- Use package-shipped knowledge objects only; no custom dashboards are
  generated.

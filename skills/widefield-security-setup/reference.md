# WideField Security Setup Reference

## Source Boundaries

- WideField public platform page: https://www.widefield.ai/
- Okta OIN listing for WideField Security - Detect and Remediate: https://www.okta.com/integrations/widefield-security-detect-and-remediate/
- Okta shared-signal receiver documentation: https://help.okta.com/oie/en-us/content/topics/itp/configure-shared-signal-provider.htm
- Saviynt WideField exchange listing: https://exchange.saviynt.com/products/widefield-security
- Google SecOps default parser list: https://docs.cloud.google.com/chronicle/docs/ingestion/parser-list/supported-default-parsers
- Cisco Investments announcement: https://www.businesswire.com/news/home/20260319154962/en/WideField-Announces-Participation-from-Cisco-Investments-in-Series-A-Round-as-Company-Launches-AI-Agent-Identity-Monitoring
- Cisco intent to acquire WideField: https://blogs.cisco.com/news/cisco-announces-intent-to-acquire-widefield-security
- Cisco Investments WideField portfolio: https://www.ciscoinvestments.com/portfolio/widefield-security
- WideField demo room capability surface: https://www.widefield.ai/demo-room

## Action Model

Use this parent skill as a router. It can render and delegate to child skills,
but it must not call private or undocumented WideField APIs.

Delegated children:

- `widefield-okta-integration-setup`
- `widefield-saviynt-integration-setup`
- `widefield-splunk-siem-setup`
- `widefield-google-secops-setup`
- `widefield-identity-threat-doctor`

Live mutation is allowed only in child skills that identify a documented public
API path and require `--accept-apply`.

Parent `--apply --accept-apply` is intentionally limited to child
render/validate orchestration with non-secret target context. Run child skills
directly when a documented live mutation is required.

## Capability Coverage

Every render emits `capability-coverage.md`, `okta-oin-coverage.md`, and
`readiness-evidence-template.json` entries for:

- Identity visibility and posture management.
- Non-human identity discovery, ownership inference, attestation, and orphaned
  account risk.
- Human identity posture, including MFA enforcement, weak factors, and
  privileged-account risk.
- Connected application and permission risk, including OAuth grants, third-party
  apps, over-privileged apps, usage, and SaaS supply-chain exposure.
- AI identity access monitoring, including AI application discovery, shadow AI,
  ChatGPT/Copilot-style integrations, and AI permission visibility.
- Authentication and session analysis, including MFA bypass, policy escape,
  session duration, and high-frequency login detection.

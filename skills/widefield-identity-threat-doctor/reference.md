# WideField Identity Threat Doctor Reference

## Public Sources

- WideField platform page: https://www.widefield.ai/
- WideField demo room: https://www.widefield.ai/demo-room
- WideField OpenClaw identity research: https://www.widefield.ai/blog/openclaw-beyond-endpoint-detection-think-identity-security
- WideField OAuth compromise analysis: https://www.widefield.ai/blog/more-salesloft-drift-compromise-expanding-to-more-apps-than-salesforce
- Cisco Investments AI Agent Identity Monitoring announcement: https://www.businesswire.com/news/home/20260319154962/en/WideField-Announces-Participation-from-Cisco-Investments-in-Series-A-Round-as-Company-Launches-AI-Agent-Identity-Monitoring
- Cisco intent to acquire WideField: https://blogs.cisco.com/news/cisco-announces-intent-to-acquire-widefield-security
- Okta shared-signal receiver documentation: https://help.okta.com/oie/en-us/content/topics/itp/configure-shared-signal-provider.htm

## Read-Only Checks

Use available evidence to look for:

- OAuth token abuse.
- Rogue OAuth or SaaS applications.
- Non-human identity anomalies.
- AI-agent identity anomalies.
- Session anomalies after authentication.
- Credential exposure and long-lived credential risk.
- Human MFA posture issues, including admins without MFA and weak factors.
- Connected application permissions, third-party app consent, and
  over-privileged app grants.
- Non-human identity ownership, attestation, and orphaned-account risk.
- Authentication policy escape, MFA bypass, high-frequency login, and long
  session duration.

Preferred evidence sources are WideField events in Splunk, Okta System Log
events, Google SecOps `WIDEFIELD_SECURITY` evidence, and Saviynt remediation
records.

## Remediation Boundary

Doctor mode renders remediation packets but does not revoke sessions, remove
app grants, reset passwords, or change governance policy. Those actions require
target-specific acceptance and owner skills with documented APIs or operator
handoffs.

Rendered `remediation-packets.md` must be treated as a review packet. It is not
an executable runbook for destructive identity actions.

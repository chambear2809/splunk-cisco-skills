---
name: widefield-identity-threat-doctor
description: >-
  Diagnose WideField identity threat coverage for OAuth token abuse, rogue or
  over-privileged apps, non-human identity ownership, MFA and credential
  posture, AI-agent identities, and anomalous sessions using read-only Splunk,
  Okta, and evidence checks. Use when the user asks to investigate WideField
  findings, audit identity threat coverage, build remediation packets, or
  validate OAuth/NHI/AI-agent identity risks without destructive remediation.
---

# WideField Identity Threat Doctor

Run read-only coverage checks and render gated remediation packets for
WideField identity threats across identity posture, connected apps, NHI
ownership, AI access, and sessions.

## Workflow

```bash
bash skills/widefield-identity-threat-doctor/scripts/setup.sh --render
bash skills/widefield-identity-threat-doctor/scripts/validate.sh --dry-run
```

When Splunk or Okta credentials are available in files, validation can check
WideField events and Okta System Log reachability:

```bash
bash skills/widefield-identity-threat-doctor/scripts/validate.sh \
  --okta-org-url https://example.okta.com \
  --okta-token-file /secure/okta/api_token
```

## Remediation Gate

Doctor mode is read-only by default. Destructive actions such as revoking
sessions, removing app grants, resetting passwords, or changing governance
policy must be executed by the target owner skill with explicit
target-specific acceptance and documented runbooks.

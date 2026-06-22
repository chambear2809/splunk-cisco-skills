---
name: widefield-saviynt-integration-setup
description: >-
  Render and validate Saviynt Identity Cloud remediation mappings for
  WideField Security findings, including access revocation, password reset,
  and micro-certification handoffs. Use when the user asks to connect
  WideField Security to Saviynt, map WideField detections to Saviynt
  remediation policies, or collect Saviynt evidence while failing closed for
  unsupported live Saviynt mutation.
---

# WideField Saviynt Integration Setup

Render Saviynt remediation maps for WideField findings. Live Saviynt mutation
is disabled until official Saviynt or customer-provided API documentation is
added to `reference.md`.

## Workflow

```bash
bash skills/widefield-saviynt-integration-setup/scripts/setup.sh --render \
  --saviynt-tenant-url https://example.saviyntcloud.com
```

Validate customer-supplied remediation evidence:

```bash
bash skills/widefield-saviynt-integration-setup/scripts/validate.sh \
  --evidence-file ./widefield-saviynt-evidence.local.json
```

## Remediation Map

- Compromised identity: revoke access.
- Weak or stale credential: password reset.
- Anomalous entitlement/session: micro-certification.

Do not infer or call Saviynt write APIs from examples or assumptions.

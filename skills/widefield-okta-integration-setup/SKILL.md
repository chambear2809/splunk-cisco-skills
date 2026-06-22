---
name: widefield-okta-integration-setup
description: >-
  Render, validate, and safely apply the Okta side of a WideField Security
  integration, including OIN handoffs, Shared Signals receiver evidence, and
  documented Okta event hook creation, update, verification, or deactivation.
  Use when the user asks to connect WideField Security to Okta, configure
  Okta event hooks for WideField, validate shared-signal risk events, or build
  Okta evidence for WideField detect-and-remediate workflows.
---

# WideField Okta Integration Setup

Prepare Okta integration assets for WideField Security. Live apply is limited
to documented Okta Event Hooks Management API operations.

## Workflow

1. Read `reference.md` before any live action.
2. Render the Okta packet:

```bash
bash skills/widefield-okta-integration-setup/scripts/setup.sh --render \
  --okta-org-url https://example.okta.com \
  --receiver-url https://widefield.example.com/okta/events
```

3. Apply only documented event hook actions with file-backed credentials:

```bash
bash skills/widefield-okta-integration-setup/scripts/setup.sh --apply --accept-apply \
  --okta-org-url https://example.okta.com \
  --okta-token-file /secure/okta/api_token \
  --receiver-url https://widefield.example.com/okta/events
```

4. Validate event hook and System Log reachability:

```bash
bash skills/widefield-okta-integration-setup/scripts/validate.sh \
  --okta-org-url https://example.okta.com \
  --okta-token-file /secure/okta/api_token
```

The renderer emits `okta-oin-coverage.md` for the full OIN feature surface.
OIN assignment, shared-signal provider setup, federation, logout, workflow,
and provisioning features remain UI/provider handoffs unless public API
coverage is added to `reference.md`.

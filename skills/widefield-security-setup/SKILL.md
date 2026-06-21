---
name: widefield-security-setup
description: >-
  Render, route, validate, and optionally delegate a WideField Security
  adoption workflow across Okta, Saviynt, Splunk SIEM, Google SecOps, and
  identity-threat doctor skills. Use when the user asks to onboard WideField
  Security, plan identity threat detection and response, connect WideField to
  identity/SIEM/SOAR/governance tools, or coordinate WideField child skill
  execution without using undocumented WideField APIs.
---

# WideField Security Setup

Render a source-backed WideField Security adoption packet and delegate target
work to the child skill that owns each system.

## Workflow

1. Read `reference.md` for source boundaries and unsupported API rules.
2. Copy `template.example` to a local-only spec if the user has many non-secret
   values to track.
3. Render the parent packet:

```bash
bash skills/widefield-security-setup/scripts/setup.sh --render
```

4. Delegate child render/validate execution with the router only after review:

```bash
bash skills/widefield-security-setup/scripts/setup.sh --apply --accept-apply \
  --children okta,saviynt,splunk,google,doctor
```

The parent never calls private or undocumented WideField APIs. Parent apply is
limited to child render/validate orchestration. Live mutation is limited to
child skills that explicitly document supported public API paths and are run
directly with their required file-backed credentials.

## Guardrails

- Keep secrets in files; reject raw token, password, API key, and client secret
  arguments.
- Treat WideField platform configuration as a provider/customer handoff unless
  public API coverage is added to `reference.md`.
- Run `validate.sh --dry-run` before target-specific validation.

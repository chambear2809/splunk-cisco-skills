---
name: cisco-meraki-aam-thousandeyes-setup
description: >-
  Render, capture, validate, and safely operate Cisco Meraki Active Application
  Monitoring with ThousandEyes. Use when the user asks to link Meraki Dashboard
  to ThousandEyes, deploy ThousandEyes Enterprise Agents on supported Meraki MX
  networks, claim or use Meraki AAM free tests, create ThousandEyes tests from
  Meraki Insight / Active Application Monitoring, monitor an application from
  agents inside Meraki networks, inspect or summarize Meraki Dashboard HAR/POST
  requests for the AAM wizard, or validate the resulting ThousandEyes agents,
  tests, and results.
---

# Cisco Meraki AAM ThousandEyes Setup

## Overview

Use this skill for the Meraki Dashboard side of the Meraki + ThousandEyes
Active Application Monitoring (AAM) workflow. It is not the Splunk Meraki TA
installer; use `cisco-meraki-ta-setup` for `Splunk_TA_cisco_meraki` and
`cisco-thousandeyes-setup` for the Splunk Platform ThousandEyes app.

The Meraki AAM wizard is the supported control plane for provisioning MX-hosted
ThousandEyes agents. Public Meraki documentation says Dashboard API agent
provisioning is not available, so treat Meraki Dashboard POSTs as private,
volatile implementation details. Capture and summarize them for evidence or
diagnosis; do not replay them unless the user explicitly asks for private API
replay and confirms the exact destination, payload, and side effect.

## Safe Workflow

Start with a local intake file and render reviewable artifacts:

```bash
cp skills/cisco-meraki-aam-thousandeyes-setup/template.example \
  skills/cisco-meraki-aam-thousandeyes-setup/template.local

bash skills/cisco-meraki-aam-thousandeyes-setup/scripts/setup.sh \
  --render \
  --spec skills/cisco-meraki-aam-thousandeyes-setup/template.local \
  --output-dir meraki-aam-thousandeyes-rendered
```

If the user exported a browser HAR from the Meraki Dashboard AAM wizard:

```bash
bash skills/cisco-meraki-aam-thousandeyes-setup/scripts/setup.sh \
  --render \
  --spec skills/cisco-meraki-aam-thousandeyes-setup/template.local \
  --har ~/Downloads/meraki-aam.har \
  --output-dir meraki-aam-thousandeyes-rendered
```

The raw HAR can contain cookies, CSRF tokens, org identifiers, and URLs. Never
paste raw HAR content into chat. Use the summarizer output instead.

## Agent Behavior

- Never ask for Meraki passwords, ThousandEyes passwords, API keys, OAuth
  tokens, cookies, CSRF values, or HAR files in chat.
- If a user pastes a Meraki API key, ThousandEyes token, cookie, or other
  credential into chat, do not use it. Tell the user to revoke/rotate it and
  write the replacement to a chmod-600 local secret file.
- Use browser login flows for account linking. Confirm before clicking
  `Start monitoring`, creating tests, unlinking accounts, disconnecting an
  account, deleting agents, deleting tests, or claiming free tests.
- Prefer the Meraki AAM UI for agent deployment. Use ThousandEyes public APIs
  only after agents exist and only with a token read from a chmod-600 file.
- Use the Meraki public Dashboard API only for read-only preflight validation
  such as organizations, networks, and assigned MX devices.
- Do not describe private Meraki Dashboard endpoints as stable or supported.
  If a captured POST is needed, record method, path, redacted payload shape,
  response code, and UI step.
- When Chrome access is unavailable, continue with the manual HAR capture
  workflow in `references/har-capture.md`.

## Workflow

1. Collect non-secret inputs in `template.local`: Meraki organization, region,
   target application, desired test profile, network names/IDs, MX serials,
   and any non-secret ThousandEyes account group ID.
2. Read `reference.md` for current product boundaries, prerequisites, and
   source-backed limitations. Read `references/har-capture.md` before
   inspecting browser requests or exported HAR files.
3. Preflight eligibility:
   - Meraki account has at least two full organization admins.
   - ThousandEyes user is an Account Admin and can use local auth for linking.
   - Meraki and ThousandEyes account regions are compatible.
   - Target networks use supported MX models, MX 18.104 or later, NAT mode,
     and working HTTPS reachability to ThousandEyes plus
     `registry.meraki-applications.com`.
   - Licensing supports the intended action: SD-WAN+ for agent installation
     and test deployment; Advanced Security for agent installation only unless
     ThousandEyes units are purchased separately.
4. Render the plan with `scripts/setup.sh --render` and review:
   - `meraki-aam-plan.md` for the UI deployment sequence.
   - `browser-capture-checklist.md` for request-capture steps.
   - `thousandeyes-validation.md` for post-deployment validation.
   - `handoff-thousandeyes-api-tests.yaml` if direct ThousandEyes API test
     creation is preferred after MX-hosted agents exist.
5. Operate the Meraki Dashboard UI:
   - Go to `Insight > Active Application Monitoring`.
   - Start the ThousandEyes onboarding flow (`Try it`, `Get started`, or
     equivalent current UI).
   - Link the ThousandEyes account and select the account group if prompted.
   - Select a verified application template or custom application target.
   - Select eligible Meraki networks where the MX-hosted agents will run.
   - Stop before the final side-effecting button and confirm the action with
     the user before submitting.
6. Validate after deployment. Meraki docs say reports can take up to 15 minutes
   to appear after agent configuration.

Read-only Meraki API preflight with a rotated key file:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/meraki_api_key

bash skills/cisco-meraki-aam-thousandeyes-setup/scripts/validate.sh \
  --meraki-api-key-file /tmp/meraki_api_key \
  --meraki-org-id "123456" \
  --network-filter "Branch 001" \
  --output-dir meraki-aam-thousandeyes-rendered/live-validation
```

ThousandEyes validation after the Meraki wizard starts monitoring:

```bash
bash skills/cisco-meraki-aam-thousandeyes-setup/scripts/validate.sh \
  --te-token-file /path/to/te_token \
  --account-group-id "1234" \
  --agent-filter "branch-or-mx-name" \
  --test-filter "application-name" \
  --output-dir meraki-aam-thousandeyes-rendered/live-validation
```

## Creating Tests

For the Meraki AAM experience, create tests through the Meraki wizard when the
requested test is represented by the UI template or custom target flow. Capture
POSTs only to understand what the UI did.

For public ThousandEyes API test lifecycle after the Meraki MX agents exist,
hand off `handoff-thousandeyes-api-tests.yaml` to
`splunk-observability-thousandeyes-integration` or use the official
ThousandEyes Tests API directly. The rendered handoff intentionally leaves agent
IDs as `TODO_REPLACE_WITH_MERAKI_AGENT_IDS` until validation confirms the
correct MX-hosted Enterprise Agents.

## Resources

- `template.example` - local intake worksheet for non-secret AAM inputs.
- `scripts/setup.sh` - renders reviewable AAM runbooks and optional HAR
  summaries.
- `scripts/summarize_har.py` - redacts and summarizes exported HAR files.
- `scripts/validate.sh` - validates Meraki organizations/networks/MX devices
  and ThousandEyes agents/tests through public API calls using secret files.
- `reference.md` - source-backed Meraki/ThousandEyes requirements and API
  boundaries.
- `references/har-capture.md` - browser capture and redaction protocol.

## Hand-offs

- Splunk Platform ThousandEyes ingestion and dashboards:
  `cisco-thousandeyes-setup`.
- Splunk Platform Meraki telemetry ingestion: `cisco-meraki-ta-setup`.
- ThousandEyes MCP registration: `cisco-thousandeyes-mcp-setup`.
- TE API-backed tests, alert rules, streams, and Splunk Observability handoffs:
  `splunk-observability-thousandeyes-integration`.

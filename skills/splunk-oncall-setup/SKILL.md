---
name: splunk-oncall-setup
description: Render, validate, and apply the full Splunk On-Call (formerly VictorOps) lifecycle — teams, users + contact methods, rotations, escalation policies, routing keys, scheduled overrides, personal paging policies, alert rules / Rules Engine, maintenance mode, incidents, notes, chat, stakeholder messages, REST endpoint and generic email alert payloads — plus Splunk-side companions (Splunkbase 3546 alert action, 4886 Add-on, 5863 SOAR connector, ITSI NEAP, ES Adaptive Response). Use when the user asks about Splunk On-Call, VictorOps, on-call schedules, escalation, paging, X-VO-Api-Id/X-VO-Api-Key, the alert.victorops.com REST endpoint, or victorops_app.
---

# Splunk On-Call Setup

Use this skill for **all** Splunk On-Call operations: SaaS object management
through the public API, the REST Endpoint Integration alert path, the Generic
Email Endpoint Integration, and Splunk-side companion apps.

The workflow is render-first by default. Live API changes only happen when the
user explicitly asks for `--apply`, `--send-alert`, `--install-splunk-app`, or
`--uninstall`.

## Coverage Model

Every rendered object gets an explicit coverage status:

- `api_apply`: a documented public API supports create, update, delete, or
  validate.
- `api_validate`: a documented public API supports read or validation only.
- `deeplink`: the skill renders a deterministic Splunk On-Call UI link and
  validates referenced data where an API allows.
- `handoff`: the skill renders deterministic operator steps for UI-only,
  Support-driven, or app-side workflows.
- `install_apply`: the skill installs or configures a Splunk-side companion
  app or saved search via Splunkbase + REST (Splunkbase 3546, 4886, 5863).

Do not mark UI-only workflows as `api_apply`.

## Safety Rules

- Never ask for Splunk On-Call API keys, REST endpoint integration keys,
  passwords, or client secrets in conversation.
- Never pass keys, integration URLs, or any secret on the command line or as
  an environment-variable prefix.
- Use `--api-key-file` for the Splunk On-Call API key (`X-VO-Api-Key`).
- Use `--integration-key-file` for the REST Endpoint Integration key.
- Prefer `SPLUNK_ONCALL_API_ID`, `SPLUNK_ONCALL_API_KEY_FILE`, and
  `SPLUNK_ONCALL_REST_INTEGRATION_KEY_FILE` from the repo `credentials` file
  when present.
- Reject direct secret flags such as `--api-key`, `--vo-api-key`,
  `--x-vo-api-key`, `--integration-key`, `--rest-key`, `--token`, and
  `--password`.
- Refuse zero-byte or world/group-readable secret files.
- Strip every secret from `apply-plan.json`, `payloads/`, and any rendered
  artifact on disk.

## Primary Workflow

1. Collect non-secret values: organization slug, API ID, team / user / policy
   names, rotation members, routing keys, alert-rule match patterns,
   maintenance routing-key list, REST integration default routing key, etc.
2. Create or update a JSON/YAML spec using
   `templates/oncall.example.yaml` as the starting point.
3. Render and validate:

   ```bash
   bash skills/splunk-oncall-setup/scripts/setup.sh \
     --render \
     --validate \
     --spec skills/splunk-oncall-setup/templates/oncall.example.yaml \
     --output-dir splunk-oncall-rendered
   ```

4. Review `coverage-report.json`, `apply-plan.json`, `deeplinks.json`, and
   `handoff.md`.
5. Apply only when explicitly requested:

   ```bash
   bash skills/splunk-oncall-setup/scripts/setup.sh \
     --apply \
     --spec skills/splunk-oncall-setup/templates/oncall.example.yaml \
     --api-id "$SPLUNK_ONCALL_API_ID" \
     --api-key-file /tmp/splunk_oncall_api_key
   ```

6. To send a single REST endpoint alert (after extracting the integration key
   from the On-Call UI Integrations > 3rd Party Integrations > REST Generic
   page):

   ```bash
   bash skills/splunk-oncall-setup/scripts/setup.sh \
     --send-alert \
     --rest-alert-spec skills/splunk-oncall-setup/templates/rest-alert.example.yaml \
     --integration-key-file /tmp/splunk_oncall_rest_key \
     --routing-key database
   ```

7. To install or refresh the Splunk-side companion apps:

   ```bash
   bash skills/splunk-oncall-setup/scripts/setup.sh \
     --install-splunk-app \
     --splunk-side-spec skills/splunk-oncall-setup/templates/splunk-side.example.yaml \
     --api-id "$SPLUNK_ONCALL_API_ID" \
     --api-key-file /tmp/splunk_oncall_api_key
   ```

## Supported Sections

Specs use `api_version: splunk-oncall-setup/v1` and can include:

- `users` — users + contact methods (devices, emails, phones), with `role` ∈
  `global_admin | alert_admin | team_admin | user | stakeholder`.
- `teams` — teams plus members and admins.
- `rotations` — per-team rotation groups and shifts.
- `escalation_policies` — ordered steps with timeouts and `User`,
  `Team`, `EscalationPolicy`, or `RotationGroup` targets.
- `routing_keys` — routing-key to escalation-policy maps.
- `paging_policies` — `personal` (full CRUD) and `team` (read/validate only).
- `scheduled_overrides` — single overrides with per-policy assignments.
- `alert_rules` — Rules Engine rules with `matchType` ∈ `WILDCARD | REGEX`,
  `rank`, `stopFlag`, `routeKey`, multi-rule annotations (URL / note / image),
  and rules-engine variable expansion (e.g. `${{fieldName}}`).
- `maintenance_mode` — start, end, and status checks.
- `incidents` — explicit-apply create / ack / resolve / reroute / by-user
  variants. Supports `isMultiResponder` and `state_start_time`. UI-only
  `snooze` and `add responder` actions are rendered as Team Dashboard
  deeplinks.
- `notes` — per-incident note CRUD.
- `chat_messages` — `/v1/chat` posts (explicit-apply).
- `stakeholder_messages` — `/v1/stakeholders/sendMessage` posts.
- `webhooks` — read-only inventory plus rendered outbound-webhook drop-in
  objects for the documented event types (`Any-Incident`,
  `Incident-Triggered`, `Incident-Acknowledged`, `Incident-Resolved`,
  `Incident-Chats`, `All-Chats`, `Any-On-Call`, `On-Call`, `Off-Call`,
  `Any-Paging`, `Paging-Start`, `Paging-Stop`). Outbound webhook *creation*
  remains a `handoff` because the public API only exposes `GET /v1/webhooks`,
  and the feature requires an Enterprise plan.
- `reporting` — `api-reporting/v1/team/{team}/oncall/log` (shift changes) and
  `api-reporting/v2/incidents` (incident history; rate-limited at 1
  call/minute).
- `schedules` — `GET /api-public/v2/team/{team}/oncall/schedule?daysForward=N`
  and `GET /api-public/v2/user/{user}/oncall/schedule`.
- `rest_alerts` — REST endpoint alert payloads (all `message_type` values,
  canonical incident fields glossary, URL/note/image annotations).
- `email_alerts` — Generic Email Endpoint Integration handoff for email-only
  monitoring tools.
- `integrations` — UI-only handoffs for Slack, Microsoft Teams, Webex Teams,
  ServiceNow (bidirectional), Statuspage, Twilio Live Call Routing, and
  Conference Bridges (Enterprise tier).
- `sso` — UI/Support handoff that renders the SP-initiated URL pattern
  `https://portal.victorops.com/auth/sso/<companyId>` and the Splunk Support
  ticket template.
- `reports` — deeplinks for Post-Incident Review (PIR), On-Call Review,
  MTTA/MTTR, Team Dashboard, and Similar Incidents (NLP grouping).
- `calendars` — iCal feed export handoff for team and personal calendars.
- `mobile` — per-user mobile app setup checklist (iOS Critical Alerts,
  Android 13+ requirement).
- `recovery_polling` — toggles the Splunkbase 3546 `victorops-alert-recovery`
  scheduled saved search and the alert action's `enable_recovery`,
  `poll_interval`, and `inactive_polls` parameters so a Splunk-driven
  CRITICAL incident is auto-resolved on the On-Call side once the underlying
  search no longer fires.
- `splunk_side` — Splunkbase 3546 alert-action install on a search head or
  SHC deployer, Splunkbase 4886 Add-on placement on a heavy forwarder with
  the four required indexes (`victorops_users`, `victorops_teams`,
  `victorops_oncall`, `victorops_incidents`) pre-created, ITSI NEAP wiring,
  ES Adaptive Response wiring, Splunkbase 5863 SOAR connector readiness, and
  Splunk Observability detector recipient deeplink.

For API endpoint details, rate limits, and current support boundaries, read
`references/coverage.md`, `references/rate-limits.md`,
`references/splunk-side-apps.md`, and `references/recovery-polling.md` when
the request touches a new or ambiguous surface.

## Out of Scope

- On-Call mobile-app push enrollment (UI-only; the skill only renders the
  per-user setup checklist).
- Billing, subscription, or trial provisioning changes.
- Slack / Microsoft Teams / Webex Teams chat-app *installation* on the chat
  side (rendered as deeplink handoffs only). The chat sender via `/v1/chat`
  and the stakeholder sender via `/v1/stakeholders/sendMessage` are in scope.
- ServiceNow bidirectional, Statuspage, and Twilio Live Call Routing setup
  steps (rendered as deeplink handoffs).
- Conference Bridges feature requires Enterprise tier; the skill renders a
  handoff but does not gate on tier.
- SAML SSO activation is completed by Splunk On-Call Support — the skill
  renders the SP-initiated URL pattern, IdP metadata XML drop-off steps, and
  a Splunk Support ticket template, but cannot turn SSO on via API.
- Reports (Post-Incident Review, On-Call Review, MTTA/MTTR, Team Dashboard,
  Similar Incidents) are rendered as deeplinks; no API write surface exists.
- Outbound webhook *creation* is rendered as inventory + handoff because the
  public API only exposes `GET /v1/webhooks`.

## Compliance and Security Baseline

Splunk On-Call enforces TLS 1.2+ in transit and AES-256 at rest, and partner
clouds are FedRAMP / PCI-DSS / ISO 27001:2013 certified; HIPAA usage is
supported via a Business Associate Agreement (BAA).

**FedRAMP / IL5 caveat:** Splunk Cloud Platform itself is FedRAMP Moderate
authorized and DoD IL5 provisionally authorized, but Splunk On-Call is not
separately listed in the public FedRAMP/IL5 docs as of this skill's authoring.
The skill renders an explicit warning when a US public-sector spec is
detected and links to Splunk Cloud Platform IL5 documentation for
parallel-stack guidance.

The skill never asks for nor logs secret material, refuses any direct secret
CLI flag, and redacts all `X-VO-Api-Key`, integration-key, and rendered
payload secrets from artifacts on disk.

## MCP Tools

This skill includes checked-in, read-only Splunk MCP custom tools generated
from `mcp_tools.source.yaml`.

Validate or regenerate the tool artifact:

```bash
python3 skills/shared/scripts/mcp_tools.py validate skills/splunk-oncall-setup
python3 skills/shared/scripts/mcp_tools.py generate skills/splunk-oncall-setup
```

Load the tools into Splunk MCP Server:

```bash
bash skills/splunk-oncall-setup/scripts/load_mcp_tools.sh
```

The loader uses the supported `/mcp_tools` REST batch endpoint by default. Use
`--allow-legacy-kv` only for older MCP Server app versions that lack that
endpoint.

# Splunk On-Call Coverage Reference

This skill is the canonical home for **all** Splunk On-Call (formerly
VictorOps) operations. The narrow `on_call` block in
`splunk-observability-native-ops` defers here for everything beyond a
deeplink-only handoff for Observability detector recipients.

## API hosts

- Public Management API: `https://api.victorops.com/api-public/v{1,2}` —
  authenticated with `X-VO-Api-Id` and `X-VO-Api-Key` headers; the API key
  must be supplied through a chmod-600 file (`--api-key-file`).
- Reporting API: `https://api.victorops.com/api-reporting/v{1,2}` — same
  auth.
- REST Endpoint Integration (alert ingestion):
  `https://alert.victorops.com/integrations/generic/20131114/alert/{INTEGRATION_KEY}/{ROUTING_KEY}`
  — the integration key is sensitive and must be supplied through
  `--integration-key-file`.

Splunk On-Call uses a single global host. Provide `--api-base` to override
only when an internal mirror or test fixture requires it.

## Public API surfaces (`api_apply` unless noted)

### On-Call schedules
- `GET /api-public/v2/user/{user}/oncall/schedule` — `api_validate` (read)
- `GET /api-public/v2/team/{team}/oncall/schedule?daysForward=N` —
  `api_validate` (read; default `daysForward=90`, the Add-on uses `123`)
- `GET /api-public/v1/oncall/current` — `api_validate` (read)
- `PATCH /api-public/v1/policies/{policy}/oncall/user` — `api_apply`
  (override on-call user)

### Incidents
- `GET /api-public/v1/incidents`
- `GET /api-public/v1/incidents/{incidentNumber}`
- `POST /api-public/v1/incidents` — supports `isMultiResponder=true` and
  `targets[]` of `User | Team | EscalationPolicy | RotationGroup`.
- `PATCH /api-public/v1/incidents/ack`
- `PATCH /api-public/v1/incidents/resolve`
- `POST /api-public/v1/incidents/reroute`
- `PATCH /api-public/v1/incidents/byUser/ack`
- `PATCH /api-public/v1/incidents/byUser/resolve`

Authoritative incident enums (verified from the Splunkbase 5863 SOAR
connector schema):

- `currentPhase` ∈ `UNACKED | ACKED | RESOLVED`
- `entityState` ∈ `CRITICAL | WARNING | INFO`

UI-only incident actions — `snooze` and `add responder` — are rendered as
Team Dashboard deeplinks only (`handoff` coverage). The public API has no
mirror.

### Notes (per incident)
- `GET /api-public/v1/incidents/{incidentNumber}/notes`
- `POST /api-public/v1/incidents/{incidentNumber}/notes`
- `PUT /api-public/v1/incidents/{incidentNumber}/notes/{noteName}`
- `DELETE /api-public/v1/incidents/{incidentNumber}/notes/{noteName}`

### Alerts
- `GET /api-public/v1/alerts/{uuid}` — `api_validate`

### Reporting
- `GET /api-reporting/v1/team/{team}/oncall/log` — shift change log,
  `api_validate`.
- `GET /api-reporting/v2/incidents` — incident history, `api_validate`,
  rate-limited at **1 call / minute** (see `rate-limits.md`).

### Users (full CRUD)
- `GET /api-public/v1/user`, `GET /api-public/v2/user`
- `POST /api-public/v1/user`, `POST /api-public/v1/user/batch`
- `GET /api-public/v1/user/{user}`, `PUT /api-public/v1/user/{user}`,
  `DELETE /api-public/v1/user/{user}`
- `GET /api-public/v1/user/{user}/teams`

The five user roles (verified in product docs):
`global_admin | alert_admin | team_admin | user | stakeholder`. Stakeholders
are read-only paging-only and cannot be placed in on-call schedules. The
validator enforces the role allow-list and refuses mass `global_admin`
assignment.

### User contact methods
- Devices: `GET / DELETE / PUT
  /api-public/v1/user/{user}/contact-methods/devices[/{contactId}]`
- Emails: `GET / POST / DELETE
  /api-public/v1/user/{user}/contact-methods/emails[/{contactId}]`
- Phones: `GET / POST / DELETE
  /api-public/v1/user/{user}/contact-methods/phones[/{contactId}]`

### Personal paging policies
- `GET /api-public/v1/user/{user}/policies` — `api_validate`
- `GET /api-public/v2/profile/{username}/policies`,
  `GET /api-public/v1/profile/{username}/policies` (V1 read is
  rate-limited at 1 call/sec)
- `POST /api-public/v1/profile/{username}/policies` — create step
- `GET / POST / PUT /api-public/v1/profile/{username}/policies/{step}`
- `GET / PUT / DELETE
  /api-public/v1/profile/{username}/policies/{step}/{rule}`

Type catalogs (`api_validate`):

- `GET /api-public/v1/policies/types/notifications`
- `GET /api-public/v1/policies/types/contacts`
- `GET /api-public/v1/policies/types/timeouts`

### Teams
- `GET / POST /api-public/v1/team`
- `GET / PUT / DELETE /api-public/v1/team/{team}`
- `GET /api-public/v1/team/{team}/admins`
- `GET / POST /api-public/v1/team/{team}/members`,
  `DELETE /api-public/v1/team/{team}/members/{user}`
- `GET /api-public/v1/team/{team}/policies` — `api_validate` for the
  team's escalation policy summary.

### Escalation policies
- `GET / POST /api-public/v1/policies`
- `GET / DELETE /api-public/v1/policies/{policy}`

The public API does not expose `PUT`; updates are modelled as
delete + recreate.

### Routing keys
- `GET / POST /api-public/v1/org/routing-keys`

### Scheduled overrides
- `GET / POST /api-public/v1/overrides`
- `GET / DELETE /api-public/v1/overrides/{publicId}`
- `GET /api-public/v1/overrides/{publicId}/assignments`
- `GET / PUT / DELETE
  /api-public/v1/overrides/{publicId}/assignments/{policySlug}`

### Rotations
- `GET /api-public/v1/teams/{team}/rotations`
- `POST /api-public/v1/teams/{team}/rotations`
- `DELETE /api-public/v1/teams/{team}/rotations/{groupId}`
- `GET / PUT
  /api-public/v1/teams/{team}/rotations/{groupId}/{shiftId}/scheduled`
- `GET /api-public/v2/team/{team}/rotations`

### Webhooks
- `GET /api-public/v1/webhooks` — `api_validate` only. Outbound webhook
  *creation* lives in the UI (Settings → Alert Behavior → Integrations →
  Outgoing Webhooks) and requires an Enterprise plan + admin credentials.
  The skill renders the planned object with one of the 11 documented event
  types so an operator can drop it in.

Documented outbound webhook event types:

- Incidents: `Any-Incident`, `Incident-Triggered`, `Incident-Acknowledged`,
  `Incident-Resolved`, `Incident-Chats`
- Chat: `All-Chats`
- On-Call: `Any-On-Call`, `On-Call`, `Off-Call`
- Paging: `Any-Paging`, `Paging-Start`, `Paging-Stop`

HTTP method ∈ `GET | POST | PUT | DELETE | PATCH`.

### Chat and stakeholder messaging
- `POST /api-public/v1/chat` — explicit-apply.
- `POST /api-public/v1/stakeholders/sendMessage` — explicit-apply.

### Alert rules (Rules Engine)
- `GET / POST /api-public/v1/alertRules`
- `GET / PUT / DELETE /api-public/v1/alertRules/{ruleId}`

Rules support `matchType` ∈ `WILDCARD | REGEX`, `rank`, `stopFlag`,
`routeKey`, multi-rule `annotations[]` (URL / note / image), and
rules-engine variable expansion (e.g. `${{fieldName}}`) in transformations.

### Maintenance mode
- `GET /api-public/v1/maintenancemode`
- `POST /api-public/v1/maintenancemode/start`
- `PUT /api-public/v1/maintenancemode/{maintenancemodeid}/end`

## Handoff and deeplink surfaces

- `email_alerts` — Generic Email Endpoint Integration. Renders the
  documented address pattern `<key>+$routing_key@alert.victorops.com` and a
  self-test message body for monitoring tools that can only send email
  (LogEntries, Google Voice, Mailhop).
- `integrations` — Slack, Microsoft Teams, Webex Teams, ServiceNow
  (bidirectional), Statuspage, Twilio Live Call Routing, Conference Bridges
  (Enterprise tier).
- `sso` — Splunk Support ticket template, IdP metadata XML drop-off steps,
  and the SP-initiated URL `https://portal.victorops.com/auth/sso/<companyId>`.
- `reports` — Post-Incident Review (PIR), On-Call Review, MTTA/MTTR,
  Team Dashboard, Similar Incidents.
- `calendars` — iCal feed export for team and personal calendars.
- `mobile` — per-user mobile-app setup checklist.

## Splunk-side install paths (`install_apply`)

See `splunk-side-apps.md` for the full conf-file shapes verified by
extracting each Splunkbase package:

- Splunkbase **3546** alert-action app (`victorops_app`).
- Splunkbase **4886** Splunk Add-on for On-Call
  (`TA-splunk-add-on-for-victorops`).
- Splunkbase **5863** SOAR connector (`splunkoncall`).

## Source anchors

- https://docs.splunk.com/observability/sp-oncall/admin/get-started/api.html
- https://portal.victorops.com/public/api-docs.html
- https://help.splunk.com/en/splunk-enterprise/alert-and-respond/splunk-on-call/integrations-with-splunk-on-call/rest-endpoint-integration-for-splunk-on-call
- https://docs.splunk.com/observability/sp-oncall/spoc-integrations/generic-email-endpoint.html
- https://help.splunk.com/en/splunk-enterprise/alert-and-respond/splunk-on-call/user-management/manage-splunk-on-call-users
- https://help.splunk.com/en/splunk-enterprise/alert-and-respond/splunk-on-call/incidents/multi-responder-incidents
- https://splunkbase.splunk.com/app/3546
- https://splunkbase.splunk.com/app/4886
- https://splunkbase.splunk.com/app/5863

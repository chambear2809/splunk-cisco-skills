# WideField Okta Integration Reference

## Public Sources

- Okta OIN listing: https://www.okta.com/integrations/widefield-security-detect-and-remediate/
- Okta shared-signal receiver: https://help.okta.com/oie/en-us/content/topics/itp/configure-shared-signal-provider.htm
- Okta event hook concepts: https://developer.okta.com/docs/concepts/event-hooks/
- Okta Event Hooks Management API: https://developer.okta.com/docs/api/openapi/okta-management/management/tags/eventhook

## Supported Live Actions

With `--apply --accept-apply`, this skill may call documented Okta event hook
operations only:

- `POST /api/v1/eventHooks`
- `PUT /api/v1/eventHooks/{eventHookId}`
- `POST /api/v1/eventHooks/{eventHookId}/lifecycle/verify`
- `POST /api/v1/eventHooks/{eventHookId}/lifecycle/deactivate`
- `GET /api/v1/eventHooks` and `GET /api/v1/logs` for validation

The Okta API token must be read from `--okta-token-file`.

## Handoffs

The Okta OIN app assignment, Shared Signals provider details, SSF/CAEP stream
metadata, and WideField-side receiver ownership are rendered as handoffs unless
public API coverage is added here.

Expected System Log evidence:

- `security.events.provider.receive_event`
- `user.risk.detect`

## OIN Feature Coverage

The public Okta Integration Network listing exposes a broad feature surface.
This skill renders `okta-oin-coverage.md` for all known listing features and
only mutates documented Event Hooks API objects.

Live-supported by this skill:

- Event Hooks: create, update, verify, deactivate, and validate.

Rendered as handoffs/evidence:

- API, Entitlement Management, Identity Security & Posture Management,
  Inbound Federation, Inline Hooks, Outbound Federation, Partial Universal
  Logout, Universal Logout, Workflows, SAML, SWA, WS-Federation, OIDC, SCIM,
  Brokered Consent, Cross App Access, and Privileged Access Management.
- Provisioning features: Create Users, Update User Attributes, Attribute
  Sourcing, Deactivate Users, Sync Password, Group Push, Group Linking, User
  Schema Discovery, and Attribute Writeback.

Do not infer write coverage for OIN assignment, shared-signal provider objects,
federation, logout, workflow, or provisioning objects from the OIN listing.

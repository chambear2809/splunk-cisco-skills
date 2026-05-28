---
name: splunk-appdynamics-controller-admin-setup
description: >-
  Render, validate, and optionally apply API-backed Splunk AppDynamics
  Controller administration workflows, including SaaS and on-prem account
  checks, API clients, OAuth token-file flow, users, groups, roles, SAML, LDAP,
  account permissions, licensing, license rules, sensitive data collection
  controls, privacy settings, audit readiness, and data collection dashboards. Use when the user asks for
  AppDynamics Controller administration, API clients, OAuth, RBAC, SAML, LDAP,
  user/group/role management, account permissions, licensing, license rules,
  sensitive data controls, SQL/log masking, environment variable filtering, or
  privacy validation.
---

# Splunk AppDynamics Controller Admin Setup

Controller administration uses documented APIs where available and renders
runbooks for IdP-side, tenant-side, or UI-only operations.

```bash
bash skills/splunk-appdynamics-controller-admin-setup/scripts/setup.sh --render
bash skills/splunk-appdynamics-controller-admin-setup/scripts/validate.sh
bash skills/splunk-appdynamics-controller-admin-setup/scripts/license_usage_report.sh \
  --controller-url "$APPD_CONTROLLER_URL" \
  --account-name "$APPD_ACCOUNT_NAME" \
  --account-id "$APPD_ACCOUNT_ID" \
  --api-client-name "$APPD_API_CLIENT_NAME" \
  --client-secret-file "$APPD_OAUTH_CLIENT_SECRET_FILE" \
  --deep \
  --output-dir ./appd-license-report
```

Secrets such as OAuth client secrets and passwords must be referenced by
chmod-600 files.

The license usage reporter is read-only. It polls documented Controller License
API endpoints and writes a customer-facing Markdown consumption report plus
complete JSON and CSV exports for timestamp-level analysis.

Live validation notes:

- `APPD_ACCOUNT_ID` is the numeric License API account ID, not the account name,
  tenant key, or GUID-like `acctId`/`tntId` claim in an OAuth token.
- `APPD_OAUTH_CLIENT_SECRET_FILE` and `APPD_OAUTH_TOKEN_FILE` must be paths to
  chmod-600 local files, not inline secret values.
- API Client role assignments are separate from user role assignments. If
  license endpoints return 403 for `ACCOUNT_LICENSE`, `LICENSE_USAGE`, or
  `LICENSE_RULE`, assign and save a role on Administration > API Clients.
- OAuth JWT role or account-permission claim counts are diagnostic only; some
  SaaS tokens omit effective API Client permissions even when License API
  readbacks succeed.
- AppDynamics SaaS controllers can require the vendor JSON `Accept` media type;
  the reporter sends that header for OAuth and License API requests.
- Deep mode falls back to application inventory when grouped application usage
  returns an empty `items` object, and host usage degrades cleanly when no host
  IDs are available.

# Controller Admin Reference

Primary sources:

- https://help.splunk.com/appdynamics-saas
- https://help.splunk.com/en/appdynamics-saas/extend-splunk-appdynamics/26.4.0/extend-splunk-appdynamics/splunk-appdynamics-apis/platform-api-index
- https://help.splunk.com/en/appdynamics-saas/extend-splunk-appdynamics/26.4.0/extend-splunk-appdynamics/splunk-appdynamics-apis/api-clients
- https://help.splunk.com/en/appdynamics-on-premises/extend-appdynamics/26.4.0/extend-splunk-appdynamics/splunk-appdynamics-apis/license-api
- https://help.splunk.com/en/appdynamics-saas/appdynamics-saas-administration
- https://help.splunk.com/appdynamics-saas/licensing
- https://help.splunk.com/en/appdynamics-saas/get-started/26.4.0/sensitive-data-collection-and-security

The skill covers API clients, OAuth, users, groups, roles, permissions, SAML,
LDAP, licensing, license rules, sensitive data controls, SQL/log masking,
environment variable filtering, and privacy validation. It renders API payloads
and validation steps; IdP-side and UI-only changes remain runbooks.

For licensing usage asks, use `scripts/license_usage_report.sh` to authenticate
with an API Client secret file or OAuth token file, poll account license info,
account usage, optional allocation/grouped usage, and license rule readbacks,
then emit a customer-ready Markdown report with executive summary and
consumption highlights, plus complete JSON and CSV exports.

Live SaaS validation lessons incorporated in the reporter and rendered assets:

- Use a numeric License API `accountId` for `APPD_ACCOUNT_ID`. The OAuth token
  `acctId` or `tntId` claims can be GUID-like tenant identifiers and are not
  accepted by `/controller/licensing/v1/account/{accountId}/...`.
- Store the OAuth client secret or reusable token in a chmod-600 file. A durable
  path such as `$HOME/.appd-secrets/<controller>-client-secret` is safer than
  `/tmp`; never pass the secret value as `--client-secret-file`.
- API Clients have their own role assignments. User roles shown in
  Administration > Users do not grant API Client permissions. Check
  Administration > API Clients, assign the role, and save it there.
- Treat OAuth JWT role and account-permission claim counts as diagnostics, not
  the authority. Live SaaS tokens can expose zero role/account permission claims
  while saved API Client role assignments still allow License API readbacks.
- Permission symptoms map directly to the License API surfaces:
  `ACCOUNT_LICENSE` for account info and grouped usage, `LICENSE_USAGE` for
  account/allocation usage, and `LICENSE_RULE` for allocation and license-rule
  readbacks.
- SaaS OAuth can return HTTP 406 when called with plain `Accept:
  application/json`; the live reporter sends the AppDynamics vendor JSON media
  type plus JSON fallback.
- Some controllers return an empty grouped application usage `items` object even
  when application inventory is visible. The deep report falls back to
  `/controller/rest/applications` for application context and records a host-id
  warning when host expansion is not possible.

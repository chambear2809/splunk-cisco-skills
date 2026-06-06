# Splunk Add-on for Okta Identity Cloud Reference

Grounded in the `Splunk_TA_okta_identity_cloud` package (Splunkbase app `6553`,
verified version `5.0.2`).

## Package Model

- App / package id: `Splunk_TA_okta_identity_cloud`
- Splunkbase ID: `6553`
- Single modular input: `okta_identity_cloud`. Key fields (from
  `inputs.conf.spec`): `global_account`, `metric`, `index`, `interval`,
  `query_window_size`, `logs_delay`, `start_date`, `end_date`,
  `use_existing_checkpoint`, `collect_uris` (apps), `fetch_stats` (groups).
- Account endpoints (`restmap.conf`): `Splunk_TA_okta_identity_cloud_account`
  and `Splunk_TA_okta_identity_cloud_oauth`.
- Source types: `OktaIM2:log`, `OktaIM2:user`, `OktaIM2:group`, `OktaIM2:app`,
  `OktaIM2:groupUser`, `OktaIM2:appUser`.

## Metrics

| `metric` | Source type | Time-series | CIM |
| --- | --- | --- | --- |
| `log` | `OktaIM2:log` | yes | Authentication, Change |
| `user` | `OktaIM2:user` | no (state) | Identity / Inventory |
| `group` | `OktaIM2:group` | no (state) | Identity / Inventory |
| `app` | `OktaIM2:app` | no (state) | Inventory |
| `groupUser` | `OktaIM2:groupUser` | no (state) | Identity |
| `appUser` | `OktaIM2:appUser` | no (state) | Identity |

The System Log (`metric = log`) is the primary security feed and maps to the
Authentication data model for Enterprise Security. Universal Directory metrics
are periodic state snapshots, not time-series events.

## Account Model

Account fields (`splunk_ta_okta_identity_cloud_account.conf.spec`): `domain`
(`yourorg.okta.com`), `auth_type` (`Basic` or `OAuth2`), `password` (API token,
Basic), `client_id_oauth_credentials` + `client_secret_oauth_credentials`
(OAuth2), and `endpoint_url`.

- **OAuth 2.0 client credentials (recommended):** create an Okta API Services
  app with the client-credentials grant; grant `okta.logs.read` plus
  `okta.users.read`, `okta.groups.read`, `okta.apps.read` as needed.
- **API token (Basic):** create a Security > API token; it is stored as the
  encrypted `password`.

Secrets are stored encrypted in `storage/passwords`. Configure the account in
the add-on Configuration tab; this skill never transmits secrets.

## Index Model

| Index | Purpose | Default |
| --- | --- | --- |
| Event index | OktaIM2:log and Universal Directory state | `okta` |

## Placement Guardrails

- Install on all search heads where Okta knowledge management is required.
- Run inputs on the search tier OR one heavy forwarder, not both, to avoid
  duplicate System Log ingestion.
- Not Universal-Forwarder or indexer scoped.
- Prefer OAuth 2.0 client credentials over a long-lived API token.

## Handoffs

- `splunk-app-install` installs the package from Splunkbase (`6553`).
- `splunk-data-source-readiness-doctor` scores readiness with the
  `okta_identity_cloud` source pack.
- `splunk-enterprise-security-config` consumes `OktaIM2:log` through the
  Authentication data model.

## Sources

- https://splunkbase.splunk.com/app/6553
- https://splunk.github.io/splunk-add-on-for-okta-identity-cloud/

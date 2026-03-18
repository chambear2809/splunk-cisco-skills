# Cisco ThousandEyes App — Reference

Detailed technical reference for the Cisco ThousandEyes App for Splunk
(`ta_cisco_thousandeyes` v0.6.0).

## OAuth 2.0 Device Code Flow

The app authenticates via RFC 8628 (Device Authorization Grant).

| Step | Endpoint | Method |
|------|----------|--------|
| Initiate | `https://api.thousandeyes.com/v7/oauth2/device/authorization` | POST |
| Token exchange | `https://api.thousandeyes.com/v7/oauth2/token` | POST |
| User lookup | `https://api.thousandeyes.com/v7/users/current` | GET |
| Token refresh | `https://api.thousandeyes.com/v7/oauth2/token` (grant_type=refresh_token) | POST |

**Client ID**: `0oalgciz1dyS1Uonr697` (hardcoded in the app)

**Scopes**: `organization:read offline_access tests:read endpoint-tests:read
streams:manage alerts:manage tags:read integrations:manage`

### Account Fields (ta_cisco_thousandeyes_account.conf)

| Field | Encrypted | Purpose |
|-------|-----------|---------|
| stanza name | No | User email address |
| `access_token` | Yes | OAuth bearer token |
| `refresh_token` | Yes | OAuth refresh token |
| `device_code` | Yes | Transient — used during authorization |
| `user_code` | No | Transient — displayed to user |
| `verification_url` | No | Transient — displayed to user |

## Splunk REST Handlers

### Account Management

| Endpoint | Handler | Purpose |
|----------|---------|---------|
| `ta_cisco_thousandeyes_account` | UCC admin handler | Account CRUD |
| `/authorize` (script handler) | `thousandeyes_rh_authorize.py` | Initiate OAuth flow |
| `/getToken` (script handler) | `thousandeyes_rh_get_token.py` | Exchange device code for tokens |

### Input Management

| Endpoint | Input Type |
|----------|------------|
| `ta_cisco_thousandeyes_test_metrics_stream` | Metrics stream |
| `ta_cisco_thousandeyes_test_traces_stream` | Traces stream |
| `ta_cisco_thousandeyes_event` | Event polling |
| `ta_cisco_thousandeyes_activity_logs_stream` | Activity log stream |
| `ta_cisco_thousandeyes_alerts_stream` | Alerts webhook |

### Lookup Handlers (read-only)

| Endpoint | Purpose |
|----------|---------|
| `thousandeyes_acc_group` | List ThousandEyes account groups |
| `thousandeyes_tests` | List ThousandEyes tests |
| `thousandeyes_hec_token` | List Splunk HEC tokens |
| `thousandeyes_hec_indexes` | List Splunk event indexes |
| `thousandeyes_hec_targets` | Auto-detect HEC target URLs |
| `thousandeyes_alert_rules` | List ThousandEyes alert rules |
| `thousandeyes_tags` | List ThousandEyes tags |

## Input Types

### Test Metrics Stream

- **Delivery**: ThousandEyes Streaming API pushes to Splunk HEC
- **Sourcetype**: `cisco:thousandeyes:metric`
- **Fields**: `thousandeyes_user`, `thousandeyes_acc_group`, `tags`,
  `cea_tests`, `endpoint_tests`, `hec_target`, `hec_token`, `test_index`,
  `thousandeyes_stream_id`, `related_paths` (checkbox), `index` (path data),
  `interval` (path data, 180-31622400s)
- **Path visualization**: When `related_paths` is checked, the app also polls
  test results for path visualization data at the configured interval

### Test Traces Stream

- **Delivery**: ThousandEyes Streaming API pushes to Splunk HEC
- **Sourcetype**: `cisco:thousandeyes:trace`
- **Fields**: `thousandeyes_user`, `thousandeyes_acc_group`, `tags`,
  `cea_tests`, `hec_target`, `hec_token`, `test_index`,
  `thousandeyes_stream_id`
- **Eligible tests**: page-load, web-transactions, api

### Events

- **Delivery**: API polling
- **Sourcetype**: `cisco:thousandeyes:event`
- **Fields**: `thousandeyes_user`, `thousandeyes_acc_group`, `index`,
  `interval` (180-31622400s, default 3600s)

### Activity Logs Stream

- **Delivery**: ThousandEyes Streaming API pushes to Splunk HEC
- **Sourcetype**: `cisco:thousandeyes:activity`
- **Fields**: `thousandeyes_user`, `thousandeyes_acc_group`, `hec_target`,
  `hec_token`, `activity_index`, `thousandeyes_stream_id`

### Alerts Stream

- **Delivery**: ThousandEyes webhooks push to Splunk HEC
- **Sourcetype**: `cisco:thousandeyes:alerts`
- **Fields**: `thousandeyes_user`, `thousandeyes_acc_group`, `alert_rules`,
  `hec_target`, `hec_token`, `alerts_index`, `webhook_operation_id` (auto),
  `webhook_connector_id` (auto)

### Token Refresh (internal)

- **Modular input**: `thousandeyes_refresh_tokens`
- **Interval**: 604800s (weekly)
- **Purpose**: Regenerates OAuth tokens for all accounts
- **Retry**: 3 attempts with 600s wait between retries

## HEC Configuration

### Splunk Cloud

- **Target URL**: `https://http-inputs-{stack}.splunkcloud.com:443/services/collector/event`
- **Management**: ACS `hec-token` commands
- **Default token name**: `thousandeyes`

### Splunk Enterprise

- **Target URL**: `https://{host}:{hec_port}/services/collector/event`
- **Management**: REST `/services/data/inputs/http`
- **Default HEC port**: 8088
- **Default token name**: `thousandeyes`

## ThousandEyes API Endpoints

Base URL: `https://api.thousandeyes.com/v7`

| Endpoint | Purpose |
|----------|---------|
| `/account-groups` | List account groups |
| `/tests` | List CEA tests |
| `/endpoint/tests/scheduled-tests` | List scheduled endpoint tests |
| `/endpoint/tests/dynamic-tests/agent-to-server` | List dynamic endpoint tests |
| `/stream` | Create/update/delete streams |
| `/test-results/{id}/path-vis` | Path visualization data |
| `/events` | Get events |
| `/audit-user-events` | Get activity logs |
| `/alerts/rules` | Get/update alert rules |
| `/operations/webhooks` | Webhook operations CRUD |
| `/connectors/generic` | Webhook connectors CRUD |
| `/tags` | Get tags |

## CEA Test Types

agent-to-agent, agent-to-server, bgp, http-server, page-load,
web-transactions, ftp-server, dns-server, dns-trace, dns-dnssec,
sip-server, voice, api

## KVStore Collections

| Collection | Purpose |
|------------|---------|
| `thousandeyes_account_group` | Cached account group metadata |
| `ta_cisco_thousandeyes_checkpointer` | Input checkpoint state |
| `itsi_episodes` | ITSI episode tracking (optional) |

## ITSI Integration

Requires `SA-ITOA` to be installed.

- **Alert action**: `thousandeyes_forward_splunk_events` forwards ITSI notable
  events to ThousandEyes
- **Sampling**: `thousandeyes_itsi_sampling.py` controls event sampling rate
- **Event sender**: `thousandeyes_send_itsi_event.py` maps test IDs to accounts
- **KVStore**: `itsi_episodes` tracks episode state

## Dashboards

| Dashboard | Content |
|-----------|---------|
| Network Overview | Network test results and health |
| Application Overview | Application test results |
| Voice Overview | Voice/SIP test results |
| Alerts | ThousandEyes alert history |
| Events | ThousandEyes event timeline |
| Activity Logs | Audit/activity log viewer |
| Traces | Test trace visualization |
| Configuration Status | Input and account configuration state |

## Data Model

- **Name**: `Cisco_ThousandEyes`
- **Acceleration**: Configurable via saved searches

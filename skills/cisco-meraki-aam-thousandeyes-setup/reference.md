# Meraki AAM + ThousandEyes Reference

Use this reference when planning or validating Cisco Meraki Active Application
Monitoring (AAM) with ThousandEyes. It summarizes current public documentation
as of 2026-06-22 and gives links to primary sources.

## Product Boundary

Meraki AAM uses the Meraki Dashboard UI to link a Meraki organization to
ThousandEyes, activate MX-hosted ThousandEyes Enterprise Agents, select
applications/templates, select eligible networks, and start monitoring.

Important public API boundary: Meraki's MX ThousandEyes configuration guide FAQ
says agent provisioning is not available via Dashboard API at this time. Do not
claim a supported public Meraki API for the AAM agent deployment wizard. If a
browser HAR reveals internal Dashboard endpoints, treat them as private,
version-sensitive implementation details.

Sources:
- https://documentation.meraki.com/SASE_and_SD-WAN/MX/Integrations/MI_-_Meraki_Insight/Product_Information_and_Configuration/Meraki_MX_ThousandEyes_Configuration_Guide
- https://documentation.meraki.com/SASE_and_SD-WAN/MX/Integrations/MI_-_Meraki_Insight/Troubleshooting/Meraki_and_ThousandEyes_Integration_Troubleshooting
- https://docs.thousandeyes.com/product-documentation/global-vantage-points/enterprise-agents/installing/cisco-devices/meraki

## Supported MX Agent Preconditions

Meraki and ThousandEyes public docs describe these key constraints:

- Supported MX families include MX67/MX68 variants, MX75, MX85, MX95, MX105,
  MX250, MX450, and supported C8xxx-G2 appliances listed in Meraki docs.
- Minimum MX firmware is 18.104; Meraki recommends 18.107.2 or later.
- MX must be in NAT mode. Concentrator mode and vMX are not supported.
- HA is supported, but the ThousandEyes agent runs on the primary MX; failover
  makes the old agent appear down until the spare becomes active.
- The MX must reach ThousandEyes cloud infrastructure and
  `registry.meraki-applications.com` over HTTPS.
- Transaction and page load tests are not supported on Meraki MX agents.
- A Meraki organization can be associated with only one ThousandEyes account.

## Licensing And Account Preconditions

- SD-WAN+ supports agent installation and test deployment from the Meraki flow.
- Advanced Security supports agent installation only unless ThousandEyes units
  are purchased separately.
- Meraki SD-WAN+ customers can claim free 5-minute Web Server HTTP tests, with
  the count based on supported licensed device count and capped at 50.
- Free tests are not available in every cloud/geography; Meraki and
  ThousandEyes account regions must be compatible.
- The Meraki organization needs at least two full organization admins.
- ThousandEyes Account Admin users with local auth can link accounts.

Region guidance from public docs:

| Meraki region | ThousandEyes region |
| --- | --- |
| North America | North America |
| Europe, Middle East and Africa | Europe, Middle East and Africa |
| Asia Pacific and Japan | North America |

## Meraki UI Flow

The public troubleshooting guide outlines the UI sequence:

1. Go to `Insight > Active Monitoring` or `Insight > Active Application Monitoring`.
2. If the organization is not linked, continue from the marketing or get-started page.
3. Log in with ThousandEyes or start a trial.
4. Select the application to monitor. The flow uses ThousandEyes Verified Test
   Templates; some templates require a tenant or subdomain.
5. Select eligible networks. Networks appear only when they meet hardware and
   firmware requirements.
6. Start monitoring. The flow finishes at an Agent List or Monitored Networks
   page where agents can be maintained.

## Topology Notes

- Direct Internet Access is the simplest path; default route points to WAN.
- AutoVPN split tunnel can monitor custom applications reached over overlay,
  but DNS can be tricky because the agent uses DNS servers from MX WAN
  interfaces.
- Full-tunnel AutoVPN or Secure Connect/Umbrella paths require upstream
  firewall and HTTPS inspection exclusions for Meraki and ThousandEyes traffic.
- For AutoVPN destinations, test traffic follows the MX routing table.

## ThousandEyes Public API Validation

Once Meraki has provisioned the agents, public ThousandEyes API v7 can validate
and manage ThousandEyes-side assets:

- List Cloud and Enterprise Agents: `GET /v7/agents`
- Create HTTP Server tests: `POST /v7/tests/http-server`
- Create Agent to Server tests: `POST /v7/tests/agent-to-server`
- Deploy templates: `POST /v7/tests/templates/{id}/deploy`
- Retrieve tests: `GET /v7/tests`

The Tests API requires Account Admin permissions for create/update/delete
operations. The Agents API returns Enterprise Agent details such as agent ID,
agent name, state, private/public IP details, serial number when available,
utilization, and assigned tests.

Sources:
- https://developer.cisco.com/docs/thousandeyes/list-cloud-and-enterprise-agents/
- https://developer.cisco.com/docs/thousandeyes/create-http-server-test/
- https://developer.cisco.com/docs/thousandeyes/create-agent-to-server-test/
- https://developer.cisco.com/docs/thousandeyes/deploy-template/
- https://docs.thousandeyes.com/product-documentation/tests/http-server-tests
- https://docs.thousandeyes.com/product-documentation/tests/templates

## Meraki Public API Preflight

Use only documented read-only Meraki Dashboard API v1 endpoints for preflight:

- List accessible organizations: `GET /api/v1/organizations`
- List networks in an organization:
  `GET /api/v1/organizations/{organizationId}/networks`
- List devices assigned to networks in an organization:
  `GET /api/v1/organizations/{organizationId}/devices`

These endpoints can confirm that the key has access to the expected
organization, that target networks exist, and that assigned MX/C8 devices are
in the public supported model families. They do not deploy the ThousandEyes
agent.

Sources:
- https://developer.cisco.com/meraki/api-v1/get-organizations/
- https://developer.cisco.com/meraki/api-v1/get-organization-networks/
- https://developer.cisco.com/meraki/api-v1/get-organization-devices/

## Validation Evidence

Collect these after a deployment:

- Meraki AAM Monitored Networks or Agent List page showing selected networks.
- ThousandEyes agents from `GET /v7/agents` with `agentState=online` and names
  matching the Meraki networks or MX devices.
- ThousandEyes tests from `GET /v7/tests` assigned to the expected agent IDs.
- First test result or UI result screenshot after the documented propagation
  window, which can be up to 15 minutes after agent configuration.
- If Splunk visibility is in scope, hand off to `cisco-thousandeyes-setup` for
  HEC/API ingestion and dashboard validation.

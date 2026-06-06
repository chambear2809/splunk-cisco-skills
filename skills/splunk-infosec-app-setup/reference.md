# InfoSec App Reference

Primary app: InfoSec App for Splunk (Splunkbase `4240`).

## Prerequisite Domains

- Authentication and identity
- Endpoint and malware
- Network traffic and firewall
- VPN/proxy/web
- Vulnerability and asset context

## Guardrails

- Install and configure CIM-compatible source TAs before relying on dashboard
  population.
- For Splunk Cloud Classic deployments that need IDM collection or parsing,
  route the request through Splunk Support rather than this renderer.
- Maintain lookup content through Lookup File Editing or knowledge-object
  governance workflows.

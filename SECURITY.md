# Security Policy

## Reporting A Vulnerability

Do not open a public issue for vulnerabilities, leaked credentials, tokens, or
customer-specific deployment details.

Use GitHub private vulnerability reporting for this repository if it is enabled.
If private reporting is not available, contact the repository maintainers through
your private organization channel and include only the minimum detail needed to
triage the issue.

## Secret Handling

This repository must not contain real credentials, API keys, bearer tokens,
private keys, Splunk session keys, HEC tokens, Splunkbase passwords, or customer
deployment secrets.

Local secret files are intentionally ignored:

- `credentials`
- `template.local`
- rendered SC4S, SC4SNMP, and Splunk MCP output directories
- `splunk-mcp-rendered/.env.splunk-mcp`

Use `skills/shared/scripts/write_secret_file.sh` to create temporary secret
files without putting secret values in shell history.

## Supported Branches

Security fixes are prepared against `main` unless a maintainer documents a
supported release branch.

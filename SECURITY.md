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

## Local Skill MCP Server

The repo-local `splunk-cisco-skills` MCP server (`agent/run-splunk-cisco-skills-mcp.py`)
is a development assistant for trusted, single-operator use. Its security model is:

- It executes only allowlisted scripts from this repo's `skills/` tree, with
  arguments validated against per-product schemas in `cisco-product-setup/catalog.json`.
- Direct secret-on-argv flags (`--password`, `--api-key`, `--token`, etc.) are
  blocked. Secrets must be passed through `--*-file` flags whose paths point at
  files created with `skills/shared/scripts/write_secret_file.sh`.
- All execution is two-stage: a `plan_*` tool produces a hash, and an
  `execute_*` tool requires the hash plus `confirm=true`. Plans are single-use
  and consumed on execution.
- Mutating scripts are gated by the server-wide environment variable
  `SPLUNK_SKILLS_MCP_ALLOW_MUTATION=1`. With the variable unset, execution
  of mutating plans is refused. Read-only plans (which do not require the
  mutation gate) are limited to: any `validate.sh`, `list_apps.sh`, or
  `resolve_product.sh` invocation; any script invoked with `--help`; and
  `cisco-product-setup`'s `setup.sh` invoked with `--dry-run` or
  `--list-products`. Anything else is treated as mutating.
- Subprocess stdout/stderr are bounded by the server before being returned to
  the client; very large output is truncated.

This server is not a sandbox. Do not expose it to untrusted clients, do not
run it inside a multi-tenant context, and do not mark it `read_only` for
scripts that are not in the explicit allowlist.

## Supported Branches

Security fixes are prepared against `main` unless a maintainer documents a
supported release branch.

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
- rendered deployment output directories, including SC4S, SC4SNMP, Splunk MCP,
  Splunk Enterprise Security indexer bundles, Splunk OTel Collector assets, and
  Splunk Observability dashboard payloads
- `splunk-mcp-rendered/.env.splunk-mcp`

Use `skills/shared/scripts/write_secret_file.sh` to create temporary secret
files without putting secret values in shell history.

Credential-bearing Splunk management REST calls require an explicit
`https://` URI. Disabling certificate verification does not authorize
plaintext HTTP. `SPLUNK_ALLOW_INSECURE_HTTP=true` is a warned escape hatch for
an isolated, short-lived lab only and must never be enabled on a routed or
shared network.

Credential-bearing API clients and package downloads ignore user curl
configuration, constrain protocols and redirects, and verify TLS by default.
`SPLUNK_VERIFY_SSL=false` does not weaken package-download TLS. Use
`APP_DOWNLOAD_CA_CERT` for an internal mirror CA; the separate
`APP_DOWNLOAD_ALLOW_HTTP=true` escape hatch is lab-only and can expose both
package contents and supplied Basic credentials.

Password-based SSH and SCP bootstrap operations require an operator-reviewed
`SPLUNK_SSH_KNOWN_HOSTS_FILE` or an out-of-band verified
`SPLUNK_SSH_HOST_KEY_FINGERPRINT`. Passwords are supplied to `sshpass` through
an inherited file descriptor, not a temporary file or command argument.
`SPLUNK_SSH_ALLOW_TOFU=true` restores `accept-new` behavior only for an
isolated, disposable lab and leaves the first connection vulnerable to
interception.

## Local Skill MCP Server

The repo-local `splunk-cisco-skills` MCP server (`agent/run-splunk-cisco-skills-mcp.py`)
is a development assistant for trusted, single-operator use. It starts in
discovery-and-plan-only mode. Its security model is:

- Every local subprocess requires the server process to start with
  `SPLUNK_SKILLS_MCP_ENABLE_EXECUTION=1`. Client confirmation alone cannot
  enable execution.
- Every generic `plan_skill_script` plan is classified as mutating, regardless
  of its script name or arguments. Executing one additionally requires
  `SPLUNK_SKILLS_MCP_ALLOW_MUTATION=1`; only typed, schema-backed workflows may
  receive a narrower read-only classification.
- Tool schemas are strict: unknown properties are rejected, enum values are
  constrained, and text, list, argument, and timeout sizes are bounded.
- Direct secret-on-argv flags (`--password`, `--api-key`, `--token`, etc.) are
  blocked. Secrets must be passed through `--*-file` flags whose paths point at
  files created with `skills/shared/scripts/write_secret_file.sh`.
- Execution is two-stage. A `plan_*` tool returns a random 256-bit,
  64-character `plan_hash`; the matching `execute_*` tool requires that value
  plus `confirm=true`. Plans expire, are single-use, and are bound to the
  planned executable's SHA-256 digest and a snapshot of every file below
  `skills/`. The snapshot is revalidated after acquiring the execution lock,
  so changed entrypoints, shared helpers, catalogs, policies, or delegated
  scripts invalidate the plan.
- Subprocesses are serialized. Their runtime and stdout/stderr are bounded,
  cancellation escalates from process-group termination to forced kill, and
  returned output is truncated and redacted.

This server is not a sandbox. Do not expose it to untrusted clients, do not
run it inside a multi-tenant context, and do not treat a plan or client-side
confirmation as a substitute for operator review.

## Splunk MCP Server Package And Bridge

The `splunk-mcp-server-setup` skill targets the official Splunk MCP Server
1.2.1 package from [Splunkbase app 7931](https://splunkbase.splunk.com/app/7931).
The default local archive must have SHA-256
`f325418ddd8617eaef26e60b11b67183b62a5641e61654335b13d67a9a0d89db`;
the setup script verifies both the package version and this checksum before
installing from any path.

The tracked package manifest currently marks 1.2.1 as not production-approved
because security and protocol findings require vendor code changes. Local app
mutation or client activation and completion validation fail closed. The
explicit nonproduction override is for isolated evaluation only.

Rendered clients require HTTPS for remote endpoints. Plain HTTP and
`--client-insecure-tls` are restricted to explicit loopback targets. The bridge
uses a preinstalled, operator-vetted `mcp-remote@0.1.38` and has no dynamic
`npx` download fallback. Keep the rendered `.env.splunk-mcp` file local with
mode `0600`.

## Supported Branches

Security fixes are prepared against `main` unless a maintainer documents a
supported release branch.

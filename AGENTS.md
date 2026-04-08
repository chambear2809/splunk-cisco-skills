# Agent Instructions

This file is the entry point for AI coding agents (Cursor, Codex, etc.)
operating in this repository.

## Quick Start

1. Read the skill file for the target product: `skills/<skill>/SKILL.md`
2. If the product is unknown, start with `skills/cisco-product-setup/SKILL.md`
   to resolve it against the catalog.
3. Run scripts under `skills/<skill>/scripts/` as documented in each SKILL.md.

## Credential Policy

**Read and follow `rules/credential-handling.mdc` before every interaction.**

Key rules:

- NEVER ask for passwords, API keys, tokens, or secrets in conversation.
- NEVER pass secrets as environment variable prefixes or bare CLI arguments.
- Direct users to configure `credentials` (project root) or
  `~/.splunk/credentials` via `bash skills/shared/scripts/setup_credentials.sh`.
- For device secrets, instruct users to write to a temp file and pass
  `--password-file /path/to/file`.

## Repository Structure

| Path | Purpose |
|------|---------|
| `skills/<skill>/SKILL.md` | Agent-facing instructions per skill |
| `skills/<skill>/reference.md` | Extended product reference (where present) |
| `skills/<skill>/scripts/` | Shell automation for setup, configure, validate |
| `skills/shared/lib/` | Shared helper libraries sourced by all scripts |
| `skills/shared/app_registry.json` | Splunkbase IDs, role support, capabilities |
| `rules/credential-handling.mdc` | Credential handling policy for agents |
| `credentials.example` | Template for the local credentials file |

## Shared Libraries

All scripts source `skills/shared/lib/credential_helpers.sh`, which loads:

- `credentials.sh` -- credential file parsing and profile resolution
- `credential_platform_helpers.sh` -- Cloud vs Enterprise detection
- `credential_role_helpers.sh` -- deployment role resolution
- `rest_helpers.sh` -- Splunk REST API wrappers
- `acs_helpers.sh` -- Splunk Cloud ACS CLI integration
- `deployment_helpers.sh` -- bundle/cluster delivery plane
- `host_bootstrap_helpers.sh` -- SSH, staging, host install
- `registry_helpers.sh` -- app registry lookups
- `splunkbase_helpers.sh` -- Splunkbase auth and downloads
- `configure_account_helpers.sh` -- TA account create/update
- `mcp_helpers.sh` -- MCP KV store tool upload
- `shell_helpers.py` -- Python helpers for URL encoding and response sanitization

## Testing

Run the full check suite with `make check-all`, or individual targets:

```
make test-python    # pytest with coverage
make test-bats      # Bats shell unit tests
make lint           # ruff check
make shellcheck     # ShellCheck
```

See `CONTRIBUTING.md` for the full development workflow.

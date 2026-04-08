# Contributing

## Development setup

1. Clone the repository and copy the example credentials file:

   ```bash
   cp credentials.example credentials
   chmod 600 credentials
   ```

2. Install test dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Install shell tooling (macOS example):

   ```bash
   brew install shellcheck bats-core
   ```

## Running tests

The quickest way to run the full CI check suite locally is:

```bash
make check-all
```

Individual targets are also available:

```bash
make test-python          # Python regression tests with coverage
make test-bats            # Bats shell unit tests
make lint                 # ruff check
make format               # ruff format --check
make syntax-check         # bash -n on all shell scripts
make shellcheck           # ShellCheck on all shell scripts
make help                 # list all targets
```

Or run the tools directly:

```bash
pytest tests/ -v          # Python regression tests
bats tests/*.bats         # Bats shell unit tests
find skills -name '*.sh' -exec bash -n {} +
shellcheck --severity=warning skills/**/*.sh
ruff check tests/ skills/
ruff format --check tests/ skills/
```

## Adding a new skill

1. Create a directory under `skills/` following the naming convention `<vendor>-<product>-setup/`.

2. Add the required files:

   | File | Purpose |
   |------|---------|
   | `SKILL.md` | Agent-facing skill description, parameters, and examples |
   | `scripts/setup.sh` | Main setup entrypoint |
   | `scripts/validate.sh` | Validation with PASS/WARN/FAIL output |

3. Optional files:

   | File | Purpose |
   |------|---------|
   | `scripts/configure_account.sh` | Device/service account configuration |
   | `template.example` | Non-secret intake worksheet for operators |
   | `reference.md` | Extended reference documentation |
   | `mcp_tools.json` | MCP tool definitions for Splunk MCP Server |
   | `scripts/load_mcp_tools.sh` | MCP KV loader (use `mcp_load_tools` from shared helpers) |

4. Source shared helpers in every script:

   ```bash
   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
   source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"
   ```

5. Register the app in `skills/shared/app_registry.json` with Splunkbase ID, role support, and capabilities.

6. Add regression tests in `tests/` covering at minimum:
   - `--help` exits 0
   - Unknown flags are rejected
   - Core setup/validate flow with mock environment

## Credential handling rules

- Never accept secrets as CLI arguments without a `--*-file` alternative.
- Never log or print secrets. Use `sanitize_response` for API error bodies.
- Use `read_secret_file` for device/API secrets.
- Splunk credentials come from the `credentials` file, not from env vars or CLI args.
- See `rules/credential-handling.mdc` for the full policy.

## Shared libraries

All shared code lives under `skills/shared/lib/`:

| Module | Responsibility |
|--------|---------------|
| `credential_helpers.sh` | Sourcing shim that loads all modules |
| `credentials.sh` | Credential file parsing, profile resolution, connection settings |
| `credential_platform_helpers.sh` | Platform detection, cloud/staging helpers |
| `credential_role_helpers.sh` | Deployment role resolution |
| `rest_helpers.sh` | Splunk REST API wrappers, TLS, session management |
| `acs_helpers.sh` | Splunk Cloud ACS CLI integration |
| `deployment_helpers.sh` | Enterprise bundle/cluster deployment |
| `host_bootstrap_helpers.sh` | Enterprise host download, install, SSH |
| `registry_helpers.sh` | App registry lookups and role warnings |
| `splunkbase_helpers.sh` | Splunkbase authentication and downloads |
| `configure_account_helpers.sh` | Generic TA account create/update |
| `mcp_helpers.sh` | MCP KV store tool upload |
| `shell_helpers.py` | Python helpers for URL encoding, response sanitization, package validation |

## CI checks

Every push and PR runs: Python tests, Bats tests, `bash -n` syntax check, ShellCheck, `ruff check`, and `ruff format --check`. All must pass before merge.

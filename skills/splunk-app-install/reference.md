# Splunk App Install — Reference

Reference for the generic Splunk app installer, covering install sources,
platform behaviors, and CLI flags.

## Scripts

| Script | Purpose |
|--------|---------|
| `install_app.sh` | Install or update a Splunk app from Splunkbase, local file, or URL |
| `list_apps.sh` | List installed apps with version, status, and label |
| `uninstall_app.sh` | Remove an installed app |

## Install Sources

| Source | Flag | Behavior |
|--------|------|----------|
| Splunkbase | `--source splunkbase --app-id ID` | Uses the registry's repo-verified version for known apps; use `--app-version` for another reviewed release |
| Local | `--source local --file PATH` | Installs from a `.tgz` or `.spl` file |
| Remote URL | `--source remote --url URL` | Downloads then installs |

## Platform Behavior

### Splunk Enterprise

| Operation | Mechanism |
|-----------|-----------|
| Install (local) | REST API `POST /services/apps/local` with `filename=true` |
| Install (Splunkbase) | Download to `splunk-ta/`, then REST API install |
| Install (remote host) | SSH staging via `scp`, then REST API with staged path |
| Restart | Automatic via REST; waits for management API recovery |
| Deployer bundle | Used when `SPLUNK_TARGET_ROLE=deployer` for SHC targets |

### Splunk Cloud

| Operation | Mechanism |
|-----------|-----------|
| Install (Splunkbase) | ACS `apps install splunkbase --splunkbase-id ID` |
| Install (private app) | ACS `apps install private --app-package PATH` |
| Targeted Victoria install | Victoria `10.2.2510+` (including `10.5.2605`): set an app-scoped `SPLUNK_CLOUD_SEARCH_HEAD`; ACS selects `--target-sh` and install/uninstall uses `--scope local` (operator-verified ACS CLI 2.20+) |
| Restart | ACS restart check; only restarts when `restartRequired=true` |

## Registry Integration

The installer resolves Cisco app metadata from
`skills/shared/app_registry.json`:

- Splunkbase ID and license acknowledgment URL
- target-minor compatibility from `platform_versions`
- repo-verified and current public release versions
- `install_requires` dependencies (auto-installed first)
- `role_support` for deployment role warnings
- `package_patterns` for local file matching

## CLI Flags (install_app.sh)

| Flag | Purpose |
|------|---------|
| `--source local\|remote\|splunkbase` | Installation source |
| `--file PATH` | Local file path |
| `--url URL` | Remote download URL |
| `--app-id ID` | Splunkbase app ID |
| `--app-version VER` | Pin a specific reviewed Splunkbase version |
| `--target-splunk-version VER` | Override the shared compatibility target (`MAJOR.MINOR[.PATCH]`) |
| `--accept-unsupported-platform` | Override a known listing gap only with documented vendor/operator approval |
| `--accept-unverified-release` | Request public latest rather than the repo-verified version; does not certify it |
| `--expected-sha256 HEX` | Required publisher SHA-256 for a remote URL package |
| `--license-ack-url URL` | Third-party license acknowledgment URL for ACS |
| `--pre-vetted` | Skip ACS private-app inspection only after external review |
| `--update` | Upgrade an existing app |
| `--no-update` | Fresh install only |
| `--no-restart` | Skip automatic restart after install |

Source fallback is caller-controlled: a failed Splunkbase attempt exits
nonzero, and the caller may then explicitly rerun `--source local --file PATH`.
Cloud uninstall likewise exits nonzero when ACS accepted the request but final
absence cannot be verified.
Cloud install also requires a recognizable post-operation app record; known
failure/in-progress statuses and pinned-version mismatches are incomplete and
return nonzero with a verification handoff.

## Credentials

| Variable | Source | Purpose |
|----------|--------|---------|
| `SPLUNK_USER` / `SPLUNK_PASS` | `credentials` file | Splunk REST authentication |
| `SB_USER` / `SB_PASS` | `credentials` file | Splunkbase download authentication |
| `SPLUNK_SSH_HOST` / `SPLUNK_SSH_USER` / `SPLUNK_SSH_PASS` | `credentials` file | Remote Enterprise host staging |
| `SPLUNK_CLOUD_STACK` | `credentials` file | ACS target stack |
| `SPLUNK_CLOUD_SEARCH_HEAD` | Prefer an app-scoped environment override; a dedicated `credentials` profile also works | Optional Victoria search-head/SHC prefix for targeted local-scope app operations. The shared ACS context affects every Cloud workflow, so clear it after app work. |

The helper does not discover Victoria eligibility or enforce the ACS CLI
version. Before a targeted operation, confirm the stack supports the feature,
the operator has `sc_admin`, and `acs version` is 2.20 or newer.

## Validation

After install, use `list_apps.sh` to verify the app is present with the
expected version. Product-specific configuration (indexes, accounts, inputs)
is handled by the corresponding setup skill.

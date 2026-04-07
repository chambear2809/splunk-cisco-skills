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
| Splunkbase | `--source splunkbase --app-id ID` | Downloads latest (or `--app-version`) from Splunkbase |
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
| Restart | ACS restart check; only restarts when `restartRequired=true` |

## Registry Integration

The installer resolves Cisco app metadata from
`skills/shared/app_registry.json`:

- Splunkbase ID and license acknowledgment URL
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
| `--app-version VER` | Pin a specific Splunkbase version (omit for latest) |
| `--update` | Upgrade an existing app |
| `--no-update` | Fresh install only |
| `--no-restart` | Skip automatic restart after install |

## Credentials

| Variable | Source | Purpose |
|----------|--------|---------|
| `SPLUNK_USER` / `SPLUNK_PASS` | `credentials` file | Splunk REST authentication |
| `SB_USER` / `SB_PASS` | `credentials` file | Splunkbase download authentication |
| `SPLUNK_SSH_HOST` / `SPLUNK_SSH_USER` / `SPLUNK_SSH_PASS` | `credentials` file | Remote Enterprise host staging |
| `SPLUNK_CLOUD_STACK` | `credentials` file | ACS target stack |

## Validation

After install, use `list_apps.sh` to verify the app is present with the
expected version. Product-specific configuration (indexes, accounts, inputs)
is handled by the corresponding setup skill.

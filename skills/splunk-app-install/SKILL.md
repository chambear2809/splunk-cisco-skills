---
name: splunk-app-install
description: >-
  Install, update, and manage Splunk apps and add-ons (TAs). Supports installing
  locally from .tgz/.spl files, remotely from a URL, or from Splunkbase. Can also
  list installed apps and uninstall apps. Use when the user asks to install a
  Splunk app, TA, add-on, download from Splunkbase, deploy an app package, or
  manage installed apps.
---

# Splunk App Install

Automates installation, update, and management of Splunk apps and add-ons.

## Agent Behavior — Credentials & Prompting

**The agent must NEVER ask for passwords or secrets in chat.**

Splunk and Splunkbase credentials are read automatically from the project-root
`credentials` file (falls back to `~/.splunk/credentials`).
If neither file exists, guide the user to create it:

```bash
bash skills/shared/scripts/setup_credentials.sh
```

The agent should still ask the user for non-secret values:
- **Installation source** — Local, Remote, or Splunkbase
- **Source-specific details** — file path, remote URL, or Splunkbase app ID and version
- **Whether this is an upgrade** of an existing app

## Environment

All scripts operate entirely via the Splunk REST API and can run from any host with
network access to the Splunk management port (8089). No local Splunk installation is
required.

| Item | Value |
|------|-------|
| Management API | `SPLUNK_URI` env var (default: `https://localhost:8089`) |
| TA app name | varies (installs any app) |
| Credentials | Project-root `credentials` file (fallback: `~/.splunk/credentials`) |
| Skill scripts | `skills/splunk-app-install/scripts/` (relative to repo root) |

### Remote Splunk Connection

To run against a remote Splunk instance:

```bash
export SPLUNK_URI="https://splunk-host:8089"
```

## Scripts

All scripts are fully interactive — they prompt for every value not already
supplied via flags. They can also be driven entirely by flags for non-interactive use.
Credentials are read from the project-root `credentials` file (falls back to `~/.splunk/credentials`).

### install_app.sh

Installs a Splunk app from one of three sources.

```bash
bash skills/splunk-app-install/scripts/install_app.sh
```

Prompts for: source type (Local/Remote/Splunkbase), file/URL/app-ID, version, upgrade y/n. Credentials
are read from the project-root `credentials` file (falls back to `~/.splunk/credentials`).

For remote Splunk hosts, local package installs try a direct REST upload first.
If the target does not support upload, the script falls back to SSH staging using
`SPLUNK_SSH_HOST`, `SPLUNK_SSH_PORT`, `SPLUNK_SSH_USER`, and `SPLUNK_SSH_PASS`
from the credentials file.

To skip prompts, supply values via flags:

```bash
bash scripts/install_app.sh \
  --source local --file splunk-ta/my_app.tgz --update
```

| Flag | Purpose |
|------|---------|
| `--source local\|remote\|splunkbase` | Installation source |
| `--file PATH` | Local file path |
| `--url URL` | Remote download URL |
| `--app-id ID` | Splunkbase app ID |
| `--app-version VER` | Splunkbase version (blank = latest) |
| `--update` | Upgrade an existing app |
| `--no-update` | Fresh install (skip upgrade prompt) |

Credentials (Splunk and Splunkbase) are read automatically from the project-root `credentials` file (falls back to `~/.splunk/credentials`).

For local installs the script lists available `.tgz`/`.spl` files in the
project's `splunk-ta/` directory first, then the configured `TA_CACHE`
directory when it differs, so the user can pick by number.

Downloaded files (Remote and Splunkbase) are saved to the project's
`splunk-ta/` directory by default. You can override this with `TA_CACHE`, but
the project-local package directory is the preferred location for shared,
version-controlled TA packages.

### list_apps.sh

Lists installed Splunk apps with version, status, and label.

```bash
bash skills/splunk-app-install/scripts/list_apps.sh
```

Prompts for: optional name filter. Credentials are read from the project-root `credentials` file (falls back to `~/.splunk/credentials`).

### uninstall_app.sh

Removes a Splunk app. Lists all installed apps so the user can pick by number.
Asks for confirmation before removing.

```bash
bash skills/splunk-app-install/scripts/uninstall_app.sh
```

Prompts for: app selection and confirmation. Credentials are read from the project-root `credentials` file (falls back to `~/.splunk/credentials`).

## Workflow

1. **Determine the operation** — install, list, or uninstall.
2. **Ask the user** for all required information (source, details).
3. **Run the script** with gathered values as flags.
4. **Verify** — run `list_apps.sh` after install to confirm.
5. **Restart if needed** — Restart Splunk via the UI, CLI on the server, or REST API.

## Post-Install Notes

- Some apps require a Splunk restart to activate.
- If the app has a setup page, the user configures it via Splunk Web or a
  dedicated setup skill (e.g., `cisco-catalyst-ta-setup`).
- Downloaded files are cached locally (path varies by environment) for reuse.


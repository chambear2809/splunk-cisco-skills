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

## Package Model

**Pull from Splunkbase first, then fall back to local packages in `splunk-ta/`.**
This applies to both Splunk Cloud and Splunk Enterprise targets.

- Primary path: `--source splunkbase --app-id <ID>` pulls the latest
  compatible release from Splunkbase. Omit `--app-version` to get the latest.
- Fallback path: if Splunkbase is unavailable (no credentials, download
  failure, private app), use `--source local` and the installer will look for
  matching packages in `splunk-ta/`.
- Cloud: ACS fetches the release directly from Splunkbase.
- Enterprise: the installer downloads the package, caches it in `splunk-ta/`,
  and installs it through the management API. For remote hosts, local packages
  are staged over SSH first.
- For known Cisco packages, the installer auto-resolves the Splunkbase ID and
  license-ack URL from `skills/shared/app_registry.json`.
- `_unpacked` app directories are for review only and are not part of the
  normal install workflow.

## Agent Behavior — Credentials

**The agent must NEVER ask for passwords or secrets in chat.**

Splunk and Splunkbase credentials are read automatically from the project-root
`credentials` file (falls back to `~/.splunk/credentials`).
If neither file exists, guide the user to create it:

```bash
bash skills/shared/scripts/setup_credentials.sh
```

The agent should always try Splunkbase first (latest version), then fall back
to local packages in `splunk-ta/` if Splunkbase is not available. Ask the user
only for:
- **Splunkbase app ID** — if not already known from the skill's registry entry
- **Whether this is an upgrade** of an existing app

Do not prompt for source type or version unless the user specifically requests
a pinned version or a remote URL. The default flow is:
1. Try `--source splunkbase --app-id <ID>` (latest version).
2. If that fails, retry with `--source local` to pick from `splunk-ta/`.

## Environment

The installer supports two target modes:

- **Splunk Enterprise**: install and remove apps through the Splunk REST API on
  port `8089`, with SSH staging for remote local-package delivery.
- **Splunk Cloud**: install and remove apps through the Admin Config Service
  (ACS) CLI. Search-tier REST access on port `8089` is optional and is used by
  other setup skills, not by the generic install/uninstall operations.

| Item | Value |
|------|-------|
| Optional override | `SPLUNK_PLATFORM=enterprise|cloud` when a hybrid credentials file makes a run ambiguous |
| Enterprise search-tier REST API | `SPLUNK_SEARCH_API_URI` env var (legacy alias: `SPLUNK_URI`) |
| Cloud stack | `SPLUNK_CLOUD_STACK` in `credentials` |
| TA app name | varies (installs any app) |
| Credentials | Project-root `credentials` file (fallback: `~/.splunk/credentials`) |
| Skill scripts | `skills/splunk-app-install/scripts/` (relative to repo root) |

### Remote Splunk Connection

To run against a remote Splunk instance:

```bash
export SPLUNK_SEARCH_API_URI="https://splunk-host:8089"
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

Prompts for: source type (Local/Remote/Splunkbase), file/URL/app-ID, upgrade y/n. Credentials
are read from the project-root `credentials` file (falls back to `~/.splunk/credentials`).
After a successful install, the script either:

- restarts Splunk automatically on Enterprise and waits for the management API
  to return, or
- checks `acs status current-stack` on Splunk Cloud and only restarts the stack
  if ACS reports `restartRequired=true`.

Use `--no-restart` only when batching changes.

For remote Enterprise hosts, local package installs stage the package over SSH
using `SPLUNK_SSH_HOST`, `SPLUNK_SSH_PORT`, `SPLUNK_SSH_USER`, and
`SPLUNK_SSH_PASS` from the credentials file, then install the staged
server-local path through the management API with `filename=true`.

For Splunk Cloud:

- local and downloaded packages that map to known Splunkbase apps are installed
  through ACS Splunkbase commands
- remaining local and downloaded packages are installed as private apps via ACS
- Splunkbase apps are installed or updated via ACS
- the ACS CLI must be installed and configured for the target stack

To skip prompts, supply values via flags:

```bash
bash skills/splunk-app-install/scripts/install_app.sh \
  --source local --file splunk-ta/my_app.tgz --update
```

| Flag | Purpose |
|------|---------|
| `--source local\|remote\|splunkbase` | Installation source |
| `--file PATH` | Local file path |
| `--url URL` | Remote download URL |
| `--app-id ID` | Splunkbase app ID |
| `--app-version VER` | Pin a specific Splunkbase version; omit for latest |
| `--update` | Upgrade an existing app |
| `--no-update` | Fresh install (skip upgrade prompt) |
| `--no-restart` | Skip the automatic restart after install |

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
Asks for confirmation before removing, then restarts Splunk automatically and
waits for the management API to return. Use `--no-restart` only when batching
changes.

```bash
bash skills/splunk-app-install/scripts/uninstall_app.sh
```

Prompts for: app selection and confirmation. Credentials are read from the project-root `credentials` file (falls back to `~/.splunk/credentials`).

## Workflow

1. **Determine the operation** — install, list, or uninstall.
2. **Look up the app ID** from `skills/shared/app_registry.json` when
   available. Only ask the user for the app ID if it is not already known.
3. **Try Splunkbase first**: run with `--source splunkbase --app-id <ID>`
   to pull the latest version.
4. **Fall back to local**: if Splunkbase fails (no creds, download error,
   private app), retry with `--source local` to install from `splunk-ta/`.
5. **Enterprise**: wait for the automatic restart and management API recovery.
6. **Cloud**: let ACS finish the operation, then restart only if
   `restartRequired=true`.
7. **Verify** — run `list_apps.sh` after install to confirm.

## Post-Install Notes

- `install_app.sh` installs the package only. It does not create indexes,
  macros, accounts, inputs, saved searches, or custom dashboard state beyond
  the app content already bundled in the package.
- For Cisco apps/TAs, follow the product-specific setup skill after install to
  configure accounts, enable inputs, and wire any dashboard macros.
- The install and uninstall scripts restart Splunk automatically by default on
  Enterprise, and perform an ACS restart check by default on Splunk Cloud.
- Use `--no-restart` only when intentionally batching multiple changes before a single final restart.
- If the app has a setup page, the user configures it via Splunk Web or a
  dedicated setup skill (e.g., `cisco-catalyst-ta-setup`).
- Downloaded files are cached locally (path varies by environment) for reuse.

## Additional Resources

- [reference.md](reference.md) — CLI flags, platform behaviors, registry integration

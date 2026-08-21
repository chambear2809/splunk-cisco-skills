---
name: splunk-app-install
description: "Use when the user asks to install a Splunk app, TA, add-on, download from Splunkbase, deploy an app
  package, or manage installed apps. Install, update, and manage Splunk apps and add-ons (TAs). Supports
  installing locally from .tgz/.spl files, remotely from a URL, or from Splunkbase. Can also list
  installed apps and uninstall apps."
compatibility: "Splunk Cloud Platform 10.5.2605: conditional. Follow documented package, entitlement, topology, and customer-managed runtime guardrails; self-managed paths remain on the public 10.4 baseline."
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-08-20"
---

# Splunk App Install

## Prerequisites

| Tool or access | Purpose | Verify |
|---|---|---|
| Bash and Python 3 | Run bundled setup and validation helpers | `bash --version && python3 --version` |
| Required product/platform access | Inspect or configure the selected target | Complete the documented preflight |
| Credential files for live modes | Keep secrets out of chat | Verify paths only |

## Workflow Overview

```text
┌───────────┐   ┌───────────────┐   ┌───────────────┐   ┌─────────────────┐
│ Preflight │ → │ Render/review │ → │ Apply/handoff │ → │ Validate evidence │
└───────────┘   └───────────────┘   └───────────────┘   └─────────────────┘
```

## When to Activate

- Install a Splunk app, TA, add-on, download from Splunkbase, deploy an app package, or manage installed apps.
- Preview and review the splunk app install workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-app-install/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-app-install/scripts/validate.sh --help
```

Expected output: offline, live, and completion options are displayed when the
skill supports them; help exits without mutation.

## Troubleshooting

| Issue | Cause | Resolution |
|---|---|---|
| Preflight fails | A required tool or access path is missing | Resolve it before rendering or applying |
| Rendered assets are incomplete | Required non-secret inputs are absent | Complete intake and render again |
| Apply is blocked | Review, credentials, or explicit acceptance is missing | Use the documented handoff |
| Validation is incomplete | Live evidence is unavailable | Record the gap and keep completion open |

## Shared add-on completion gate

This skill completes package delivery only. For every TA, add-on, or dashboard
companion, continue through the owning skill and the
[shared completion gate](../shared/ta_completion_gate.md). Never report a
package install as complete setup without applicable ingest and dashboard
evidence, or explicit package evidence that no dashboards ship.

Automates installation, update, and management of Splunk apps and add-ons.

## Package Model

**Pull from Splunkbase first, then explicitly retry with a reviewed local
package in `splunk-ta/` when needed.**
This applies to both Splunk Cloud and Splunk Enterprise targets.

- Primary path: `--source splunkbase --app-id <ID>` pins a known app to the
  registry's repo-verified release. `--app-version` selects another exact,
  operator-reviewed release, but an unregistered version has no reusable
  compatibility evidence and fails closed without a documented
  `--accept-unsupported-platform` exception. `--accept-unverified-release`
  pins the registry-recorded `latest_release_version`; it never leaves ACS or
  the downloader on a moving `latest`. Unknown numeric IDs additionally require
  an explicit `--app-version` plus both release and platform acknowledgements.
- Fallback path: if Splunkbase is unavailable (no credentials, download
  failure, private app), the caller must rerun with `--source local`; in
  interactive mode the installer lists packages in `splunk-ta/`. It does not
  silently switch sources after a failed Splunkbase operation.
- Cloud: ACS fetches the release directly from Splunkbase.
- Enterprise: the installer downloads the exact package into `splunk-ta/` and
  installs it through the management API. Cached Splunkbase bytes are reused
  only when `--expected-sha256` matches; without an operator/publisher digest,
  the exact release is redownloaded over authenticated HTTPS. Before upload,
  archive paths, top-level app identity, `[package] id`, and `[launcher] version`
  are inspected and the resolved exact version is compatibility-checked again.
  For remote hosts, local packages are staged over SSH first.
- For known Cisco packages, the installer auto-resolves the Splunkbase ID and
  license-ack URL from `skills/shared/app_registry.json`.
- Known registry packages are checked against the target Splunk minor before
  any ACS/REST install call. The check follows the selected release: a
  repo-verified pin uses `verified_platform_versions`, while
  `--accept-unverified-release` evaluates the current public release against
  `platform_versions`. Cloud defaults to `10.5`; missing evidence for the
  selected release fails closed unless `--accept-unsupported-platform` is
  explicitly supplied with documented vendor/operator approval.
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

The agent should always try Splunkbase first (repo-verified version), then fall back
to local packages in `splunk-ta/` if Splunkbase is not available. Ask the user
only for:
- **Splunkbase app ID** — if not already known from the skill's registry entry
- **Whether this is an upgrade** of an existing app

Do not prompt for source type or version unless the user specifically requests
a pinned version or a remote URL. The default flow is:
1. Try `--source splunkbase --app-id <ID>` (repo-verified version).
2. If that fails, retry with `--source local` to pick from `splunk-ta/`.

## Environment

The installer supports two target modes:

- **Splunk Enterprise**: install and remove apps through the Splunk REST API on
  port `8089`, with SSH staging for remote local-package delivery.
- **Splunk Cloud**: install and remove apps through the Admin Config Service
  (ACS) CLI. Search-tier REST access on port `8089` is optional and is used by
  other setup skills, not by the generic install/uninstall operations.

Targeted app installation is available on Victoria stacks from `10.2.2510`
onward, including `10.5.2605`. For an app-scoped operation, export
`SPLUNK_CLOUD_SEARCH_HEAD` as the standalone search-head or SHC prefix; the
shared ACS context selects that target and install/uninstall commands add
`--scope local`. Leave it unset when the app should apply to every search head.
Before using this path, verify that the stack is eligible, the operator has the
`sc_admin` role, and `acs version` reports ACS CLI 2.20 or newer; the helper does
not infer stack eligibility or enforce the CLI version. Because the shared ACS
context is used by every Cloud workflow, prefer an app-scoped shell export (or
a dedicated credentials profile) over a global target value, and clear it
after the app operation.

| Item | Value |
|------|-------|
| Optional override | `SPLUNK_PLATFORM=enterprise|cloud` when a hybrid credentials file makes a run ambiguous |
| Enterprise search-tier REST API | `SPLUNK_SEARCH_API_URI` env var (legacy alias: `SPLUNK_URI`) |
| Cloud stack | `SPLUNK_CLOUD_STACK` in `credentials` |
| Optional Cloud app target | App-scoped `SPLUNK_CLOUD_SEARCH_HEAD` environment override; a dedicated `credentials` profile is also supported |
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

### setup.sh

Dispatches to the install, list, or uninstall helpers while preserving the
original helper flags.

```bash
bash skills/splunk-app-install/scripts/setup.sh --help
bash skills/splunk-app-install/scripts/setup.sh --install --source splunkbase --app-id 7421
bash skills/splunk-app-install/scripts/setup.sh --list --filter cisco
bash skills/splunk-app-install/scripts/setup.sh --uninstall
```

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
- a non-empty `SPLUNK_CLOUD_SEARCH_HEAD` selects Victoria targeted app
  installation and forces local scope instead of deployment to all search heads
- completion is read back with `acs apps describe`; failed or still-pending
  states, unresolved app names, and pinned-version mismatches return nonzero

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
| `--app-version VER` | Select an exact operator-reviewed release; unregistered release evidence fails closed |
| `--target-splunk-version VER` | Override the shared Cloud/Enterprise compatibility target |
| `--accept-unsupported-platform` | Explicitly override a known platform-listing gap with documented approval |
| `--accept-unverified-release` | Pin the registry-recorded public latest instead of the repo-verified version; unknown IDs also require `--app-version` |
| `--expected-sha256 HEX` | Required for URL downloads and for reuse of cached Splunkbase package bytes |
| `--license-ack-url URL` | Third-party license acknowledgment URL for ACS installs |
| `--pre-vetted` | Skip ACS inspection only for an already reviewed private app |
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

On Cloud, `uninstall_app.sh` delegates to the same hardened state machine as
`cloud_batch_uninstall.sh`. An ACS-accepted request is never completion:
bounded verification must obtain definitive ACS absence. A search-tier REST
404 alone cannot prove removal, and any channel that still reports the app
present (including ACS/REST disagreement) forces a nonzero result.
Enterprise and bundle removals also read back `/services/apps/local` after the
activation path and return nonzero unless the app is absent.

```bash
bash skills/splunk-app-install/scripts/uninstall_app.sh
```

Prompts for: app selection and confirmation. Credentials are read from the project-root `credentials` file (falls back to `~/.splunk/credentials`).

### cloud_batch_install.sh

Batch install expands registry dependencies in dependency-first order, resolves
an exact version for every app, and snapshots ACS list/describe state before the
first mutation. `--version` is accepted for exactly one requested root; expanded
dependencies keep their own registry pins. Each ACS operation must converge to
the exact expected version and a recognized terminal status through bounded
list/describe polling. HTTP 409 is accepted only after that exact state is
proven.

The batch stops at the first failure and never restarts partial state. Apps that
were absent in the initial snapshot and whose successful install is attributable
to this batch are uninstalled in reverse order, with ACS absence verification.
If compensation or verification is incomplete, the script exits nonzero and
retains a mode-0600 JSONL recovery journal under `${SPLUNK_BATCH_RECOVERY_DIR}`
(or the system temporary directory). A successful fully verified batch removes
the transient journal.

### cloud_batch_uninstall.sh

Safely removes multiple Splunk Cloud apps through ACS. The batch helper rejects
unsafe/ambiguous app names, preflights ACS existence and current version for
every target before the first mutation, prints the exact removal plan, and
requires `--yes` in non-interactive use. It revalidates the exact planned
state/version immediately before each ACS or direct REST mutation. An ACS rc=0
is only request acceptance; every app must reach definitive bounded ACS
absence. REST-only 404, transport/authentication errors, malformed responses,
and 5xx responses never count as absence. If either channel reports the app
present, or ACS and REST disagree, the run fails unless a separately authorized
fallback safely reconciles the state and final ACS absence is then proved.

```bash
bash skills/shared/scripts/cloud_batch_uninstall.sh --yes \
  Splunk_TA_Cisco_Intersight Splunk_TA_cisco_meraki
```

Direct search-tier REST DELETE is not an automatic fallback. It requires the
separate `--accept-rest-fallback` acknowledgement because it can bypass ACS
ownership, desynchronize a search head cluster, or affect only the contacted
member. Partial/ambiguous outcomes stop later mutations, exit nonzero, and
write a private JSON evidence file with per-app versions, request outcomes,
final verification, and exact recovery guidance. Use `--evidence-file PATH` to
select its location.

The single-app wrapper accepts the same Cloud-only `--accept-rest-fallback`,
`--verify-attempts`, `--verify-interval`, and `--evidence-file` flags and passes
them to the batch state machine. `--yes` confirms only the named app; direct
REST mutation still requires `--accept-rest-fallback` independently.

## Workflow

1. **Determine the operation** — install, list, or uninstall.
2. **Look up the app ID** from `skills/shared/app_registry.json` when
   available. Only ask the user for the app ID if it is not already known.
3. **Try Splunkbase first**: run with `--source splunkbase --app-id <ID>`
   to pull the repo-verified version (or the exact registry-recorded public
   latest only when explicitly requested with `--accept-unverified-release`).
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

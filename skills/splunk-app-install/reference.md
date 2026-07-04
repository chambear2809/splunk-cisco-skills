# Splunk App Install — Reference

Reference for the generic Splunk app installer, covering install sources,
platform behaviors, and CLI flags.

## Scripts

| Script | Purpose |
|--------|---------|
| `install_app.sh` | Install or update a Splunk app from Splunkbase, local file, or URL |
| `list_apps.sh` | List installed apps with version, status, and label |
| `uninstall_app.sh` | Remove an installed app |
| `skills/shared/scripts/cloud_batch_uninstall.sh` | Preflight and remove multiple Cloud apps with verified absence |

## Install Sources

| Source | Flag | Behavior |
|--------|------|----------|
| Splunkbase | `--source splunkbase --app-id ID` | Uses the registry's repo-verified version for known apps; an exact `--app-version` without registry evidence fails closed unless explicitly approved |
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
- selected-release target-minor compatibility from
  `verified_platform_versions` for the repo-verified pin or
  `platform_versions` for the current public release
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
| `--app-version VER` | Select an exact operator-reviewed release; unregistered compatibility evidence fails closed |
| `--target-splunk-version VER` | Override the shared compatibility target (`MAJOR.MINOR[.PATCH]`) |
| `--accept-unsupported-platform` | Override a known listing gap only with documented vendor/operator approval |
| `--accept-unverified-release` | Pin the registry-recorded public latest rather than the repo-verified version; unknown IDs also require an exact `--app-version` |
| `--expected-sha256 HEX` | Required for URL downloads and before cached Splunkbase package bytes may be reused |
| `--license-ack-url URL` | Third-party license acknowledgment URL for ACS |
| `--pre-vetted` | Skip ACS private-app inspection only after external review |
| `--update` | Upgrade an existing app |
| `--no-update` | Fresh install only |
| `--no-restart` | Skip automatic restart after install |

Source fallback is caller-controlled: a failed Splunkbase attempt exits
nonzero, and the caller may then explicitly rerun `--source local --file PATH`.
Cloud uninstall likewise exits nonzero when ACS accepted the request but final
absence cannot be verified.
Cloud install requires a recognizable terminal post-operation app record and an
exact version match through bounded ACS describe polling. Missing/unknown status,
unavailable state, and version mismatches return nonzero.

Compatibility is release-specific. The default repo-verified pin is checked
against its own `verified_platform_versions` evidence. Passing
`--accept-unverified-release` selects and pins the registry-recorded current
public release; it does not transfer compatibility evidence from either release
to the other. The registry evidence authenticates public listing/release
metadata, not downloaded package bytes or a publisher checksum.

Enterprise package uploads are inspected before mutation: unsafe archive paths,
multiple top-level app directories, mismatched `[package] id`, missing or
mismatched `[launcher] version`, and an operator SHA-256 mismatch all fail
closed. Without `--expected-sha256`, an existing Splunkbase cache entry is never
silently reused; the exact release is downloaded again over authenticated HTTPS.

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

## Cloud Batch Uninstall Safety

`cloud_batch_uninstall.sh` requires concrete 1-128 character app identifiers,
preflights every requested app and its authoritative ACS version before
mutation, and prints one exact plan. Each target is checked again against that
exact version immediately before its ACS mutation; direct REST fallback targets
receive the same immediate state/version check. Non-interactive runs require
`--yes`. Verification is bounded with `--verify-attempts` and
`--verify-interval`; absent, present, unavailable, ambiguous, and disagreement
responses are distinguished. Success requires definitive ACS absence. A REST
404 by itself is never sufficient, and transport/authentication failures,
malformed responses, or HTTP 5xx remain ambiguous rather than absent. Any
channel still reporting the app present wins and returns nonzero.

`--accept-rest-fallback` is independent from `--yes`. Without it, an app that
persists after ACS is retained with a nonzero result and recovery handoff. With
it, direct REST DELETE may run only after bounded verification and a fresh exact
pre-mutation check show the expected app/version still present on the contacted
search tier. The flag acknowledges that a member REST mutation can bypass
ACS/SHC topology ownership. Final success still requires ACS absence. Results
are written mode 600 to `--evidence-file` or a printed private temporary path.

Cloud operations requested through `uninstall_app.sh` delegate to this batch
state machine. The wrapper exposes `--accept-rest-fallback`,
`--verify-attempts`, `--verify-interval`, and `--evidence-file`; none of these
weakens the independent `--yes` destructive confirmation gate.

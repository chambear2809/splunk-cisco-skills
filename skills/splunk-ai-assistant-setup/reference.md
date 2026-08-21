# Splunk AI Assistant — Reference

Operational reference for the install, validate, and Enterprise onboarding
flow exposed by [`SKILL.md`](SKILL.md).

## Product Identity

| Property | Value |
|---|---|
| Product name | Splunk AI Assistant (formerly: Splunk AI Assistant for SPL / AI Assistant in Splunk) |
| Splunkbase listing | [App ID 7245](https://splunkbase.splunk.com/app/7245) |
| Verified release | `2.2.0` (July 22, 2026; also current public, lists Splunk 10.5) |
| Prior reviewed pin | `2.0.0` (April 9, 2026; withdrawn from the public release API) |
| Internal app name | `Splunk_AI_Assistant_Cloud` |
| Package family | `splunk-ai-assistant-for-splunk_*.tgz` |
| Deployment placement | Search head only |
| Cloud connectivity | Search head must reach `*.scs.splunk.com:443` for Enterprise cloud-connected mode |

Refer to Splunk Docs for canonical references:

- [Splunk AI Assistant release notes](https://help.splunk.com/en/splunk-cloud-platform/search/splunk-ai-assistant/2.2.0/release-notes/whats-new-in-splunk-ai-assistant)
- [Splunk AI Assistant Cloud install](https://help.splunk.com/en/splunk-cloud-platform/search/splunk-ai-assistant/2.2.0/install-and-configure-splunk-ai-assistant/install-splunk-ai-assistant-for-splunk-cloud-customers)
- [Splunk AI Assistant Enterprise Cloud Connected install](https://help.splunk.com/en/splunk-cloud-platform/search/splunk-ai-assistant/2.2.0/install-and-configure-splunk-ai-assistant/install-splunk-ai-assistant-for-splunk-enterprise-customers-with-cloud-connected)

## Verified 2.2.0 Release Notes

- The repository-reviewed app ID `7245` baseline is `2.2.0`, which is also the
  current public release, with compatibility for Splunk Cloud and Splunk
  Enterprise `9.3+`. The prior reviewed pin `2.0.0` (April 9, 2026) is no longer
  published in the release API.
- The product name is now **Splunk AI Assistant**. Older docs and customer
  language may still say **Splunk AI Assistant for SPL**.
- Agent Mode arrived in `2.0.0` for Splunk Cloud Platform in supported AWS
  regions, extended to Splunk Enterprise through Cloud Connected in `2.1.0`,
  and gained additional AWS regions in `2.2.0`. Confirm the specific region
  rather than assuming Cloud-only availability.
- `2.2.0` adds an ITSI subagent that requires both Splunk ITSI `5.0.0+` and
  Splunk MCP Server `1.2.1+`.
- `2.2.0` adds a Cloud feature preview for natural-language search over
  federated data (SPL2 and Federated Data Context) in supported regions.
- Personalization is now **Context**, with more granular administrative
  controls for which context data the assistant uses.
- Model Runtime is on by default for both new installs and upgrades from
  `2.0.0` onward.
- Splunk AI Assistant has limited IL2 FedRAMP support. The FedRAMP edition does
  not include Agent Mode, data for training/fine-tuning defaults off, and Model
  Runtime is fixed to Splunk-hosted models.

## Verified 2.2.0 Package

`2.2.0` is the current public release, advertises Splunk 10.5, and is the
verified pin. Its package was downloaded, unpacked, and inspected here. The
collection and REST surface this skill drives is identical to `2.0.0`:

- Modular inputs: `saia_field_summary`, `saia_knowledge_object_summary`,
  `saia_macros_dms_modinput`, `saia_async_jobs`, `saia_mdc_federated_datasets`.
  All are disabled by default except `saia_async_jobs`, which the app drives
  itself; this skill does not create or enable `saia_*` inputs.
- Handlers used by `setup.sh` and `validate.sh`: `/submitonboardingform`,
  `/completeonboarding`, `/version`, `/cloudconnectedproxysettings`. All four are
  still declared in `restmap.conf`.

The release-note bullets above were reviewed against the `2.2.0` documentation,
so the linked release notes and install pages match the verified pin. Splunkbase
no longer publishes `2.0.0` in its release API, so that pin cannot be fetched at
all; there is no reason to prefer it.

## Topology Placement

| Role | Place AI Assistant here? |
|---|---|
| Standalone search head | Yes |
| SHC member | Yes — push from the deployer |
| SHC deployer | Stage only |
| Indexer | No |
| Heavy forwarder | No |
| Splunk Cloud Victoria | Self-service install for eligible AWS/Azure commercial regions |
| Splunk Cloud Classic | Self-service install is supported; use Splunk Support if tenant gates block install |
| Splunk Cloud FedRAMP IL2 | Limited support since `2.0.0`; no Agent Mode |

## Splunk Cloud vs Enterprise Differences

| Aspect | Splunk Enterprise (cloud connected) | Splunk Cloud |
|---|---|---|
| Install path | Splunkbase → REST `/services/apps/local`, deployer for SHC | ACS Splunkbase install |
| Onboarding | Submit form via app backend, then complete with activation code | Performed by Splunk-managed onboarding for the stack |
| Outbound reach | Search head must reach `*.scs.splunk.com:443` directly or via configured proxy | Stack-managed |
| Proxy configuration | `setup.sh --set-proxy` writes `proxy_url` into the app config | Stack-managed |
| Restart | Required after install on Enterprise | ACS reports `restartRequired`; only restart when set |
| Agent Mode | Not enabled by this skill; available through Cloud Connected in a supported AWS region since `2.1.0` | Available for supported AWS commercial Cloud regions, expanded in `2.2.0` |
| Context / Model Runtime | Configure in app UI after install/onboarding | Configure in app UI after install/onboarding |

## CLI Surface (provided by `setup.sh`)

| Flag | Purpose |
|---|---|
| `--install` | Install or update via the shared installer (Splunkbase first) |
| `--app-version X.Y.Z` | Pin a specific release |
| `--set-proxy --proxy-url ...` | Configure outbound proxy for cloud-connected mode |
| `--proxy-password-file PATH` | Optional file-backed proxy password |
| `--submit-onboarding-form --email ... --region ... --company-name ... --tenant-name ...` | Enterprise onboarding |
| `--complete-onboarding --activation-code-file PATH` | Activation step (file-backed token only) |
| `--validate` | Run validate.sh after install/onboarding actions |

## Region Tokens

The current US commercial token is `usa`. The setup script normalizes common
aliases (e.g. `us` → `usa`). Always pass the app's documented region token,
not a marketing region label.

## REST / KV Surface Validated by `validate.sh`

| Endpoint | Purpose |
|---|---|
| `GET /services/apps/local/Splunk_AI_Assistant_Cloud` | App installed/enabled, plus the configured/`is_configured` state read from the app entry's `configured` field |
| `GET /servicesNS/nobody/Splunk_AI_Assistant_Cloud/storage/collections/config` | KV Store reachable for AI Assistant namespace |
| `GET /services/server/info` | Splunk REST + auth health |

Onboarding state is derived from app-owned settings rather than the app's
`/config` or `/get_feature_flags` endpoints, which can error out before
onboarding has completed.

## Onboarding State Machine

```
not_started ──submit-onboarding-form──▶ submitted ──complete-onboarding──▶ onboarded
```

`validate.sh` reports the current state. With `--expect-configured` and
`--expect-onboarded` it asserts a specific state for CI / smoke runs.

## Operational Caveats

1. **Search head only.** Do not push to indexers or heavy forwarders.
2. **Public Splunkbase only on Cloud.** Do not perform a private upload of a
   downloaded archive. Splunk Cloud installs must come from the public
   Splunkbase listing, served through ACS.
3. **Verified baseline is the public release.** Default installs pin verified
   `2.2.0`, which is the current public release, so no unverified-release
   override is required. The withdrawn `2.0.0` pin cannot be reinstalled from
   Splunkbase.
4. **Agent Mode constraints.** Agent Mode requires a supported AWS commercial
   region and Splunk platform `10.1+`. It reached Splunk Enterprise through
   Cloud Connected in `2.1.0`, so confirm the region rather than ruling
   Enterprise out.
5. **FedRAMP IL2 constraints.** The FedRAMP edition omits Agent Mode, defaults
   training/fine-tuning data off, and uses only Splunk-hosted models.
6. **Activation code timing.** The Splunk-issued activation code may not
   appear immediately after onboarding-form submission. Re-run `validate.sh`
   periodically. Do not retry `--complete-onboarding` until the code is in
   hand and saved to a chmod 600 file.
7. **Proxy passwords are file-backed.** `--proxy-password-file` only; never
   pass the password as a CLI value.
8. **KV Store dependency.** Chat data persists in the local KV Store on the
   customer stack. KV Store must be healthy for the app to function.

## Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| App installed but `is_configured = false` | Onboarding not completed | Run `--submit-onboarding-form`, wait for code, run `--complete-onboarding` |
| `submit-onboarding-form` fails with HTTP 4xx | Wrong region token or non-eligible stack | Verify region token and stack eligibility |
| `complete-onboarding` rejects token | Activation code not yet issued by Splunk | Wait and retry; check Splunk onboarding email |
| Outbound HTTP errors after onboarding | Proxy not configured or proxy password expired | `--set-proxy` with current credentials in a chmod 600 file |
| Validate reports KV Store down | KV Store outage or membership unstable on SHC | Resolve KV Store health before retrying onboarding |

## Related Skills

- [`splunk-app-install`](../splunk-app-install/SKILL.md) — performs the
  package delivery used by this skill.
- [`splunk-mcp-server-setup`](../splunk-mcp-server-setup/SKILL.md) —
  complementary search-tier AI surface for agent integrations.

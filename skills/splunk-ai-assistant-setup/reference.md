# Splunk AI Assistant — Reference

Operational reference for the install, validate, and Enterprise onboarding
flow exposed by [`SKILL.md`](SKILL.md).

## Product Identity

| Property | Value |
|---|---|
| Product name | Splunk AI Assistant (formerly: Splunk AI Assistant for SPL / AI Assistant in Splunk) |
| Splunkbase listing | [App ID 7245](https://splunkbase.splunk.com/app/7245) |
| Latest verified release | `2.0.0` (April 9, 2026) |
| Internal app name | `Splunk_AI_Assistant_Cloud` |
| Package family | `splunk-ai-assistant-for-splunk_*.tgz` |
| Deployment placement | Search head only |
| Cloud connectivity | Search head must reach `*.scs.splunk.com:443` for Enterprise cloud-connected mode |

Refer to Splunk Docs for canonical references:

- [Splunk AI Assistant release notes](https://help.splunk.com/en/splunk-cloud-platform/search/splunk-ai-assistant/2.0.0/release-notes/whats-new-in-splunk-ai-assistant)
- [Splunk AI Assistant Cloud install](https://help.splunk.com/en/splunk-cloud-platform/search/splunk-ai-assistant/2.0.0/install-and-configure-splunk-ai-assistant/install-splunk-ai-assistant-for-splunk-cloud-customers)
- [Splunk AI Assistant Enterprise Cloud Connected install](https://help.splunk.com/en/splunk-cloud-platform/search/splunk-ai-assistant/2.0.0/install-and-configure-splunk-ai-assistant/install-splunk-ai-assistant-for-splunk-enterprise-customers-with-cloud-connected)

## Current 2.0.0 Release Notes

- Splunkbase shows app ID `7245` latest version `2.0.0`, published April 9,
  2026, with compatibility for Splunk Cloud and Splunk Enterprise `9.3+`.
- The product name is now **Splunk AI Assistant**. Older docs and customer
  language may still say **Splunk AI Assistant for SPL**.
- Agent Mode is new in `2.0.0` and is limited to Splunk Cloud Platform
  customers in supported AWS regions.
- Personalization is now **Context**, with more granular administrative
  controls for which context data the assistant uses.
- Model Runtime is on by default for both new installs and upgrades to
  `2.0.0`.
- Splunk AI Assistant has limited IL2 FedRAMP support. The FedRAMP edition does
  not include Agent Mode, data for training/fine-tuning defaults off, and Model
  Runtime is fixed to Splunk-hosted models.

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
| Splunk Cloud FedRAMP IL2 | Limited support in `2.0.0`; no Agent Mode |

## Splunk Cloud vs Enterprise Differences

| Aspect | Splunk Enterprise (cloud connected) | Splunk Cloud |
|---|---|---|
| Install path | Splunkbase → REST `/services/apps/local`, deployer for SHC | ACS Splunkbase install |
| Onboarding | Submit form via app backend, then complete with activation code | Performed by Splunk-managed onboarding for the stack |
| Outbound reach | Search head must reach `*.scs.splunk.com:443` directly or via configured proxy | Stack-managed |
| Proxy configuration | `setup.sh --set-proxy` writes `proxy_url` into the app config | Stack-managed |
| Restart | Required after install on Enterprise | ACS reports `restartRequired`; only restart when set |
| Agent Mode | Not enabled by this skill; Cloud Connected app setup only | Available only for supported AWS commercial Cloud regions in `2.0.0` |
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
| `GET /services/apps/local/Splunk_AI_Assistant_Cloud` | App installed and enabled |
| `GET /servicesNS/nobody/Splunk_AI_Assistant_Cloud/configs/conf-app/install` | App-side configured/`is_configured` state |
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
3. **Latest-version baseline.** Default installs track the current Splunkbase
   release. As of `2.0.0`, use Enterprise `9.3+` for the latest app unless you
   intentionally pin an older release for a documented compatibility reason.
4. **Agent Mode constraints.** Agent Mode is a `2.0.0` Cloud feature for
   supported AWS commercial regions and requires Splunk platform `10.1+`.
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

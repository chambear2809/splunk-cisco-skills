# Splunk TA Skills

This repository is a working library of Cursor agent skills and shell scripts for
installing, configuring, and validating Splunk apps and Technology Add-ons on
self-managed Splunk Enterprise and Splunk Cloud deployments.

The repo is designed for two use cases:

- **Agent-driven work in Cursor**: the agent reads the skill metadata in
  `skills/*/SKILL.md` and runs the matching scripts for you.
- **Direct shell use**: you can run the scripts under each skill manually if you
  prefer to operate outside the agent.

The automation now supports two administration paths:

- **Splunk Enterprise**: direct Splunk REST API access on port `8089`, with SSH
  staging as a fallback for remote app package installs.
- **Splunk Cloud**: Admin Config Service (ACS) for app installs, index
  management, and restarts, plus search-tier REST API access on port `8089` for
  TA-specific account/input configuration after the app is installed.

For Splunk Cloud, the search-tier REST API requires the `search-api` allow list
to include your source IP. App installation, index creation, and restart
operations do **not** use the search-tier REST API in cloud mode.

## What This Repository Covers

At a high level, the repo gives you three layers of automation:

1. **Package delivery**: download apps from Splunkbase, fetch them from a URL,
   or install them from local `.tgz` or `.spl` files. In Splunk Cloud, installs
   are executed through ACS instead of direct `/services/apps/local` calls.
2. **App-specific setup**: create indexes, configure accounts, enable inputs,
   update macros, and apply dashboard settings. In Splunk Cloud, index creation
   uses ACS and the app-specific REST configuration uses the search tier.
3. **Validation**: confirm the app is installed, the expected objects exist, and
   Splunk is actually receiving data.

Most of the repo follows the same pattern:

- `SKILL.md` explains when to use the skill and what values the agent may ask
  for.
- `reference.md` contains vendor-specific details such as input families,
  account fields, or app behavior.
- `scripts/` contains the actual shell automation.
- `mcp_tools.json` is present for skills that expose search tooling through MCP.

This `README.md` is now the main overview document, while each `SKILL.md` and `reference.md` carries the
skill-specific details.

## Supported Skills

| Skill | Target | Main purpose |
|-------|--------|--------------|
| `cisco-catalyst-ta-setup` | `TA_cisco_catalyst` | Configure Catalyst Center, ISE, SD-WAN, and Cyber Vision inputs |
| `cisco-dc-networking-setup` | `cisco_dc_networking_app_for_splunk` | Configure ACI, Nexus Dashboard, and Nexus 9K data collection |
| `cisco-intersight-setup` | `Splunk_TA_Cisco_Intersight` | Configure Cisco Intersight account, index, and inputs |
| `cisco-meraki-ta-setup` | `Splunk_TA_cisco_meraki` | Configure Meraki organization account, index, and polling inputs |
| `cisco-enterprise-networking-setup` | `cisco-catalyst-app` | Configure the visualization app’s macros and related app settings |
| `cisco-thousandeyes-setup` | `ta_cisco_thousandeyes` | Configure ThousandEyes OAuth, HEC, streaming/polling inputs, and dashboards |
| `splunk-itsi-setup` | `SA-ITOA` | Install and validate Splunk ITSI; integration readiness for ThousandEyes |
| `splunk-app-install` | Any app or TA | Install, list, or uninstall Splunk apps |
| `splunk-stream-setup` | Splunk Stream stack | Install and configure Splunk Stream components |

## Vendor Package Policy

This repo now treats `splunk-ta/` as the local package cache and review cache,
not as the only cloud deployment source.

- **Enterprise install path**: install the original `.tgz`, `.tar.gz`, or `.spl`
  archive from `splunk-ta/`, a remote URL, or Splunkbase.
- **Cloud install path**: for apps published on Splunkbase, prefer ACS
  Splunkbase installs and let ACS fetch the latest compatible release. Use
  private package uploads only for genuinely private or pre-vetted apps that do
  not have a public Splunkbase install path.
- **Known Cisco cloud installs**: the cloud installer now prefers ACS
  Splunkbase installs for the Cisco Catalyst, Cisco DC Networking, Cisco
  Enterprise Networking, Cisco Intersight, and Cisco Meraki packages shipped in
  this repo.
- **No extract/repack required**: unpacked app trees are not part of the normal
  deployment workflow.
- **Review-only unpacked copies**: anything under `splunk-ta/_unpacked/` is for
  static review and risk analysis only.
- **Vendor package constraints**: if a package is not Splunk Cloud-compatible as
  shipped, that is treated as a vendor/package limitation rather than something
  this repo silently fixes at install time.

See `CLOUD_DEPLOYMENT_MATRIX.md` for the per-TA deployment model.

## How To Use This Repo

The normal workflow is:

1. Configure credentials once.
2. Install the app or TA from Splunkbase (latest version). If Splunkbase is
   unavailable, fall back to local packages in `splunk-ta/`.
3. Run the skill-specific setup script.
4. Validate the deployment.
5. Restart Splunk if the setup script tells you to. The generic install/uninstall
   scripts already restart Splunk automatically unless you explicitly skip it.

### 1. Configure Credentials

All scripts load deployment settings from a project-root `credentials` file
first, fall back to `~/.splunk/credentials` if the project file does not exist,
and honor `SPLUNK_CREDENTIALS_FILE` when you want to point a run at an
alternate credentials file entirely.

The simplest setup path is:

```bash
bash skills/shared/scripts/setup_credentials.sh
```

Or copy the template and edit it yourself:

```bash
cp credentials.example credentials
chmod 600 credentials
```

The project-level `credentials` file is gitignored and intended only for local
use.

If one file needs to represent multiple targets, the helper also supports named
profiles. Keep the flat keys for the default target, or define
`PROFILE_<name>__KEY="value"` entries and select them with `SPLUNK_PROFILE`.

Example:

```bash
SPLUNK_PROFILE="cloud"

PROFILE_cloud__SPLUNK_PLATFORM="cloud"
PROFILE_cloud__SPLUNK_SEARCH_API_URI="https://my-stack.stg.splunkcloud.com:8089"
PROFILE_cloud__SPLUNK_CLOUD_STACK="my-stack"
PROFILE_cloud__ACS_SERVER="https://staging.admin.splunk.com"

PROFILE_hf__SPLUNK_PLATFORM="enterprise"
PROFILE_hf__SPLUNK_SEARCH_API_URI="https://hf.example.com:8089"

PROFILE_onprem__SPLUNK_PLATFORM="enterprise"
PROFILE_onprem__SPLUNK_SEARCH_API_URI="https://onprem.example.com:8089"
```

This lets one `credentials` file cover:

- a Splunk Cloud stack/search tier
- a heavy forwarder or intermediate Enterprise node
- a separate on-prem search head or lab deployment

If one workflow needs two targets at once, keep `SPLUNK_PROFILE` on the primary
platform target and set `SPLUNK_SEARCH_PROFILE` for the paired search-tier REST
target.

Example:

```bash
SPLUNK_PROFILE="cloud"
SPLUNK_SEARCH_PROFILE="hf"
```

In that mode:

- Cloud keeps `SPLUNK_PLATFORM`, ACS, stack, and token settings
- HF overrides only search-tier REST and SSH settings such as
  `SPLUNK_SEARCH_API_URI`, `SPLUNK_URI`, `SPLUNK_USER`, `SPLUNK_PASS`, and
  `SPLUNK_SSH_*`

For Enterprise targets, that same file can also include connection and SSH
staging settings:

```bash
SPLUNK_HOST="10.110.253.20"
SPLUNK_MGMT_PORT="8089"
SPLUNK_SEARCH_API_URI="https://10.110.253.20:8089"
# Legacy alias kept for backward compatibility
SPLUNK_URI="${SPLUNK_SEARCH_API_URI}"
SPLUNK_SSH_HOST="10.110.253.20"
SPLUNK_SSH_PORT="22"
SPLUNK_SSH_USER="splunk"
SPLUNK_SSH_PASS=""
```

For Splunk Cloud, the credentials file can also include:

```bash
SPLUNK_SEARCH_API_URI="https://your-stack.stg.splunkcloud.com:8089"
SPLUNK_CLOUD_STACK="your-stack-name"
SPLUNK_CLOUD_SEARCH_HEAD=""
ACS_SERVER="https://admin.splunk.com"
STACK_TOKEN=""
STACK_USERNAME=""
STACK_PASSWORD=""
STACK_TOKEN_USER=""
```

`SPLUNK_PLATFORM` is optional. In normal use, scripts infer the target from the
current operation plus your Cloud/REST settings. If one credentials file
contains both Cloud and Enterprise/HF targets, interactive runs will prompt
when a command is ambiguous.

Use `SPLUNK_SEARCH_API_URI="https://<deployment>.splunkcloud.com:8089"` only
when you also need search-tier REST API access for app-specific configuration or
validation. The helper prefers `SPLUNK_SEARCH_API_URI` and falls back to the
legacy alias `SPLUNK_URI`. These values are stored as strings in the
`credentials` file; the helper supports simple `${OTHER_KEY}` references there,
but does not execute arbitrary shell expressions.

### 2. Install Apps Or TAs

The default installation path is **Splunkbase first, local fallback**. Pull
the latest version from Splunkbase:

```bash
bash skills/splunk-app-install/scripts/install_app.sh \
  --source splunkbase \
  --app-id 5580
```

If Splunkbase is unavailable (no credentials, download failure, or a private
app), fall back to a local package in `splunk-ta/`:

```bash
bash skills/splunk-app-install/scripts/install_app.sh \
  --source local \
  --file splunk-ta/my_app.tgz
```

The `splunk-ta/` directory is the local package cache. Splunkbase downloads
are saved there automatically, `--source local` looks there when listing
available packages, and the binaries are intentionally ignored by Git.

When the target platform is **Splunk Enterprise**, the installer will:

1. try a direct REST upload first
2. fall back to SSH staging when the target does not support that upload path

When the target platform is **Splunk Cloud**, the installer uses ACS:

1. known Splunkbase-backed apps are installed or updated with ACS Splunkbase commands
2. private apps are vetted and installed with `acs apps install private`
3. restart requirements are checked through `acs status current-stack`

After a successful install or uninstall, the generic app-management scripts
restart Splunk automatically on Enterprise or trigger an ACS restart only when
Splunk Cloud reports `restartRequired=true`. Use `--no-restart` only when
batching multiple changes before a single final restart.

### 3. Run A Skill-Specific Setup

After installation, use the matching setup skill.

Examples:

```text
Set up the Cisco Catalyst TA for my Catalyst Center at 10.100.0.60
```

```text
Configure the Cisco Intersight TA for my account
```

```text
Install and configure Splunk Stream
```

The agent is expected to ask only for **non-secret** values in conversation,
such as:

- hostnames
- IP addresses
- account names
- organization IDs
- index names
- regions
- feature toggles

Secrets should come from the `credentials` file or from temporary files passed
to `--password-file`, `--api-token-file`, or similar flags.

### 4. Validate The Deployment

Each skill provides a validation script under its own `scripts/` directory.

Examples:

```bash
bash skills/cisco-catalyst-ta-setup/scripts/validate.sh
```

```bash
bash skills/cisco-meraki-ta-setup/scripts/validate.sh
```

```bash
bash skills/splunk-stream-setup/scripts/validate.sh
```

The validation scripts generally check:

- app installation state
- indexes and macros
- account or input configuration
- data presence in the expected indexes

## Splunk Cloud Notes

Splunk Cloud support in this repo follows the documented platform split:

- **ACS-managed actions**: app install, app uninstall, index creation, and
  restarts.
- **Search-tier REST actions**: TA-specific account setup, input enablement,
  macro updates, saved search toggles, KV Store access, and validation.
- **Forwarder-managed actions**: on Splunk Cloud, data inputs still run on
  forwarders or infrastructure under your control. The repo does not attempt to
  turn the cloud search tier into a local collector.

For example, the Cisco TA skills can configure their app objects on the Cloud
search tier over REST once the app is installed, while the generic installer and
index creation logic use ACS.

## Working With Remote Splunk Hosts

To target a remote Splunk instance instead of localhost:

```bash
export SPLUNK_SEARCH_API_URI="https://splunk-host:8089"
```

### SSL Verification

By default, the scripts skip TLS certificate verification (`curl -k`) because
on-prem Splunk deployments typically use self-signed certificates. To enable
strict certificate verification (recommended for Splunk Cloud or any
environment with trusted certs), set:

```bash
export SPLUNK_VERIFY_SSL="true"
```

You can also add this to your `credentials` file. When enabled, curl will
reject untrusted or expired certificates instead of silently ignoring them.

You can also define `SPLUNK_SEARCH_API_URI` in the `credentials` file so you do
not have to export it each session. The helper still accepts `SPLUNK_URI` as a
legacy alias.

Remote workflows matter most in two places:

- **app installation**: Enterprise local files may need SSH staging, while
  Splunk Cloud installs use ACS
- **validation/setup**: all search-tier REST operations must be able to reach
  the remote management port

## Secure Credential Handling

This repo is opinionated about secret handling.

Rules of thumb:

- Do **not** paste passwords, API keys, tokens, or client secrets into chat.
- Do **not** pass secrets directly as shell arguments when a file-based option
  exists.
- Do **not** hardcode secrets in scripts.

Safe patterns used in this repo:

- Splunk credentials live in `credentials` or `~/.splunk/credentials`.
- Splunk auth is sent to the REST API through stdin or helper wrappers rather
  than exposed in process listings.
- Device or vendor secrets should be provided through temporary files.

Example:

```bash
echo "device_secret_here" > /tmp/device_secret
chmod 600 /tmp/device_secret

bash skills/cisco-catalyst-ta-setup/scripts/configure_account.sh \
  --type catalyst_center \
  --name my_catc \
  --host https://10.100.0.60 \
  --username myuser \
  --password-file /tmp/device_secret

rm -f /tmp/device_secret
```

The repository rule file that defines this behavior is:

```text
rules/credential-handling.mdc
```

## Repository Layout

```text
splunk-cloud-skills/
├── .github/
│   └── workflows/
│       └── ci.yml              # shell/unit test checks for first-party scripts
├── README.md
├── ARCHITECTURE.md
├── CLOUD_DEPLOYMENT_MATRIX.md
├── DEMO_SCRIPTS.md
├── credentials.example
├── credentials                  # local only, gitignored
├── .shellcheckrc
├── splunk-ta/                   # local package cache; binaries ignored by git
│   └── _unpacked/              # review-only extracted copies
├── skills/
│   ├── shared/
│   │   ├── app_registry.json   # single source of truth for Splunkbase IDs
│   │   ├── lib/
│   │   │   ├── credential_helpers.sh    # shim that sources all modules
│   │   │   ├── credentials.sh           # profile resolution and loading
│   │   │   ├── rest_helpers.sh          # Splunk REST API wrappers
│   │   │   ├── acs_helpers.sh           # ACS CLI wrappers
│   │   │   ├── splunkbase_helpers.sh    # Splunkbase auth and downloads
│   │   │   └── configure_account_helpers.sh  # create-or-update pattern
│   │   └── scripts/
│   │       ├── setup_credentials.sh
│   │       ├── cloud_batch_install.sh
│   │       └── cloud_batch_uninstall.sh
│   ├── splunk-app-install/
│   ├── cisco-catalyst-ta-setup/
│   ├── cisco-dc-networking-setup/
│   ├── cisco-intersight-setup/
│   ├── cisco-meraki-ta-setup/
│   ├── cisco-enterprise-networking-setup/
│   └── splunk-stream-setup/
├── tests/                       # bats and Python test suites
├── plans/                       # design notes and implementation plans
└── rules/
    └── credential-handling.mdc
```

## What To Read For Detail

If you want to understand a specific skill, read these files in order:

1. `skills/<skill>/SKILL.md`
2. `skills/<skill>/reference.md` if present
3. `skills/<skill>/scripts/*.sh`

That is where the real behavior lives.

## Requirements

Minimum expected environment:

- Splunk Enterprise with REST API access on `8089`, or Splunk Cloud with ACS
  access and optional search-tier REST API access on `8089`
- `bash`
- `curl`
- `python3`
- Cursor IDE if you want the agent-driven workflow
- a `splunk.com` account for Splunkbase downloads

For Splunk Cloud workflows, you should also install the ACS CLI:

```bash
brew install acs
```

Depending on the workflow, you may also need:

- SSH access to the target Splunk host for remote local-package installs
- vendor credentials or tokens supplied through files for account setup scripts
- `search-api` allow-list access for Cloud search-tier REST operations

## Current Scope

This repo focuses on vendor TAs/apps that can be configured through REST and
shell automation on **self-managed Splunk Enterprise** and on **Splunk Cloud
search tiers with ACS plus allowlisted REST API access**.

The biggest Cloud-specific limitation is hybrid collection architectures. For
example, Splunk Stream on Splunk Cloud uses a cloud-hosted `splunk_app_stream`
plus forwarders you control; this repo therefore treats Stream as a special
case rather than a pure single-target install.

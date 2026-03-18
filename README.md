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
| `splunk-app-install` | Any app or TA | Install, list, or uninstall Splunk apps |
| `splunk-stream-setup` | Splunk Stream stack | Install and configure Splunk Stream components |

## Vendor Package Policy

This repo now treats the vendor-provided app archives in `splunk-ta/` as the
deployment source of truth.

- **Install as-is**: for both Splunk Enterprise and Splunk Cloud, the normal
  workflow installs the original `.tgz`, `.tar.gz`, or `.spl` archive from
  `splunk-ta/`.
- **Cloud install path**: use ACS to install the original package, then use the
  skill-specific REST/API automation to configure the installed app.
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
2. Put app packages in `splunk-ta/` or download them from Splunkbase.
3. Install the app or TA.
4. Run the skill-specific setup script.
5. Validate the deployment.
6. Restart Splunk if the setup script tells you to. The generic install/uninstall
   scripts already restart Splunk automatically unless you explicitly skip it.

### 1. Configure Credentials

All scripts load deployment settings from a project-root `credentials` file
first, and fall back to `~/.splunk/credentials` if the project file does not
exist.

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

For Enterprise targets, that same file can also include connection and SSH
staging settings:

```bash
SPLUNK_HOST="10.110.253.20"
SPLUNK_MGMT_PORT="8089"
SPLUNK_URI="https://10.110.253.20:8089"
SPLUNK_SSH_HOST="10.110.253.20"
SPLUNK_SSH_PORT="22"
SPLUNK_SSH_USER="splunk"
SPLUNK_SSH_PASS=""
```

For Splunk Cloud, the credentials file can also include:

```bash
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

Use `SPLUNK_URI="https://<deployment>.splunkcloud.com:8089"` only when you also
need search-tier REST API access for app-specific configuration or validation.
These values are stored as literal strings in the `credentials` file. Do not use
shell expressions there.

### 2. Use `splunk-ta/` As The Local Package Cache

The repository’s `splunk-ta/` directory is the canonical local package cache.

That means:

- Splunkbase downloads are saved there by default.
- URL-based downloads are saved there by default.
- `--source local` looks there first when listing available packages.
- The package binaries are intentionally ignored by Git.

This makes `splunk-ta/` the shared working directory for app packages without
polluting version control history.

### 3. Install Apps Or TAs

The generic installer is:

```bash
bash skills/splunk-app-install/scripts/install_app.sh
```

You can run it interactively, or pass flags.

Examples:

**Install from Splunkbase**

```bash
bash skills/splunk-app-install/scripts/install_app.sh \
  --source splunkbase \
  --app-id 5580
```

**Install from a local package**

```bash
bash skills/splunk-app-install/scripts/install_app.sh \
  --source local \
  --file splunk-ta/my_app.tgz
```

**Install from a remote URL**

```bash
bash skills/splunk-app-install/scripts/install_app.sh \
  --source remote \
  --url https://example.com/path/to/app.tgz
```

When the target platform is **Splunk Enterprise**, the installer will:

1. try a direct REST upload first
2. fall back to SSH staging when the target does not support that upload path

When the target platform is **Splunk Cloud**, the installer uses ACS:

1. private apps are vetted and installed with `acs apps install private`
2. Splunkbase apps are installed or updated with ACS app-management commands
3. restart requirements are checked through `acs status current-stack`

After a successful install or uninstall, the generic app-management scripts
restart Splunk automatically on Enterprise or trigger an ACS restart only when
Splunk Cloud reports `restartRequired=true`. Use `--no-restart` only when
batching multiple changes before a single final restart.

### 4. Run A Skill-Specific Setup

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

### 5. Validate The Deployment

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
export SPLUNK_URI="https://splunk-host:8089"
```

You can also define `SPLUNK_URI` in the `credentials` file so you do not have to
export it each session.

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
splunk-ta-skills/
├── README.md
├── credentials.example
├── credentials                  # local only, gitignored
├── splunk-ta/                   # local package cache; binaries ignored by git
├── skills/
│   ├── shared/
│   │   ├── lib/
│   │   │   └── credential_helpers.sh
│   │   └── scripts/
│   │       └── setup_credentials.sh
│   ├── splunk-app-install/
│   ├── cisco-catalyst-ta-setup/
│   ├── cisco-dc-networking-setup/
│   ├── cisco-intersight-setup/
│   ├── cisco-meraki-ta-setup/
│   ├── cisco-enterprise-networking-setup/
│   └── splunk-stream-setup/
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

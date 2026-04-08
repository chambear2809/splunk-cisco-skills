# Repository and Deployment Architecture

How this repo is organized, and how the shared automation adapts to Splunk
Cloud, Enterprise (on-prem), hybrid deployments, and the runtime roles inside
those topologies.

## Repository Architecture

This document complements `README.md`: the README is the operator-facing
overview, while this file focuses on the architectural boundaries inside the
repo and the runtime deployment models those scripts target.

### Core Building Blocks

| Path | Role |
|------|------|
| `skills/<skill>/` | Skill-specific docs and automation for install, setup, validation, and optional MCP loading |
| `skills/shared/lib/` | Shared platform layer for credentials, ACS, REST, Splunkbase, account helpers, and host bootstrap helpers |
| `skills/shared/scripts/` | Shared operational entrypoints such as credential setup and cloud batch install/uninstall |
| `skills/shared/app_registry.json` | Single source of truth for Splunkbase IDs, package patterns, app names, license-ack metadata, and role placement |
| `splunk-ta/` | Local package cache for downloaded or manually staged `.tgz`, `.tar.gz`, `.rpm`, `.deb`, or `.spl` archives |
| `splunk-ta/_unpacked/` | Review-only extracted copies, not the normal deployment path |
| `tests/` and `.github/workflows/ci.yml` | Regression coverage for helper libraries and first-party shell scripts |

### Shared Helper Modules

All skill scripts source `skills/shared/lib/credential_helpers.sh`, which is a
compatibility shim over the focused shared modules:

| Module | Responsibility |
|--------|----------------|
| `credential_helpers.sh` | Sources the shared modules and locates the active credentials file |
| `credentials.sh` | Loads credential files, resolves profiles, and detects Cloud vs Enterprise vs hybrid targets |
| `credential_platform_helpers.sh` | URI/host parsing, Splunk Cloud vs Enterprise detection, staging helpers |
| `credential_role_helpers.sh` | Deployment role normalization and resolution for primary/search/ingest profiles |
| `rest_helpers.sh` | Search-tier REST wrappers for apps, configs, inputs, saved searches, HEC, and validation |
| `acs_helpers.sh` | ACS login/context, current search-head resolution, `search-api` allowlisting, and Cloud index/restart helpers |
| `splunkbase_helpers.sh` | Splunkbase authentication and package download helpers |
| `configure_account_helpers.sh` | Shared create-or-update flow for TA account endpoints |
| `host_bootstrap_helpers.sh` | Shared SSH, package staging, checksum, and remote file helpers for first-install host automation |
| `deployment_helpers.sh` | Deployment plane selection (REST vs bundle), SHC/IDXC paths, conf merge, and HEC token helpers |
| `registry_helpers.sh` | App registry lookups for role support, capabilities, pairing, and deployment metadata |
| `mcp_helpers.sh` | MCP KV store tool upload for Splunk MCP Server integration |
| `shell_helpers.py` | Python helpers for URL encoding, response sanitization, and package validation |

### Skill Composition Pattern

Most skills follow the same layout, even if some omit optional files:

| File / directory | Purpose |
|------------------|---------|
| `SKILL.md` | Agent-facing instructions and expected workflow |
| `reference.md` | Product-specific notes such as input families, field mappings, or behavioral caveats |
| `scripts/setup.sh` | Default setup workflow |
| `scripts/validate.sh` | Post-deployment verification |
| `scripts/load_mcp_tools.sh` + `mcp_tools.json` | Optional search tooling loaded into `Splunk_MCP_Server` |

### Installer And Package Flow

- `skills/splunk-app-install/scripts/install_app.sh` is the generic app-delivery
  entrypoint used across the repo.
- On Splunk Enterprise, the installer installs local server paths directly and
  stages remote local-package installs over SSH before calling the management
  API with `filename=true`.
- On Splunk Cloud, the installer uses ACS and consults
  `skills/shared/app_registry.json` to map known package files to Splunkbase app
  installs, license acknowledgements, and expected app names.
- `skills/shared/scripts/cloud_batch_install.sh` batches ACS installs and
  performs a post-install identity check to catch corrupted or mis-mapped app
  deployments.

### Platform And Deployment Role

This repo separates **platform selection** from **deployment role**:

- Platform selection decides whether the helpers are using Splunk Cloud or
  self-managed Splunk Enterprise APIs.
- Deployment role describes where a package or end-to-end skill belongs inside
  the topology.

The role model uses five names:

- `search-tier`
- `indexer`
- `heavy-forwarder`
- `universal-forwarder`
- `external-collector`

Use `DEPLOYMENT_ROLE_MATRIX.md` for the role placement truth for each package
and skill. Use `CLOUD_DEPLOYMENT_MATRIX.md` when the question is specifically
about Cloud install or configuration behavior.

At runtime, the warning layer can consume `SPLUNK_TARGET_ROLE` and
`SPLUNK_SEARCH_TARGET_ROLE` to describe what the active management endpoint
represents and what paired runtime may exist alongside it. These are
deployment-role hints, not delivery-plane selectors. Per-run environment values
override the selected profile's role metadata.

### Skill Roles

The current skills fall into four architectural roles:

- **Collector/setup skills** — install apps, create indexes, configure accounts,
  and enable inputs. Examples: AppDynamics, Catalyst, DC Networking,
  Intersight, Meraki, Security Cloud, Secure Access, and ThousandEyes.
- **Parser/mapping skills** — install supporting add-ons that contribute field
  mappings or search-time parsing context but rely on a separate ingestion path.
  Example: `cisco-catalyst-enhanced-netflow-setup`.
- **Search-time / visualization skills** — configure macros, saved searches, or
  data model behavior on top of data collected elsewhere. Example:
  `cisco-enterprise-networking-setup`.
- **Platform/package skills** — manage generic app delivery or multi-component
  app stacks. Examples: `splunk-app-install`, `splunk-stream-setup`,
  `splunk-connect-for-syslog-setup`, `splunk-connect-for-snmp-setup`,
  `splunk-enterprise-host-setup`, `splunk-itsi-setup`,
  `splunk-ai-assistant-setup`, and `splunk-mcp-server-setup`.

### CI And Validation

The repo treats the shared shell libraries as first-party code with regression
coverage. `.github/workflows/ci.yml` runs:

- `ruff` for Python linting and format checks
- `pytest` for Python tests
- `bats` for shell behavior tests
- `bash -n` for shell syntax checks
- `shellcheck` for static shell linting

## Deployment Models

### Splunk Cloud

All infrastructure is managed by Splunk. The repo interacts through two API
surfaces: ACS for platform operations and the search-tier REST API on port 8089
for app-specific configuration.

```mermaid
flowchart TB
  subgraph users [Users]
    SplunkUser["Analysts / Operators"]
    Admin["Splunk Admin"]
  end

  subgraph userMachine [Automation Machine]
    Scripts[Skill Scripts]
    ACSCLI[ACS CLI]
  end

  subgraph splunkCloud [Splunk Cloud]
    subgraph acsLayer [ACS Control Plane -- admin.splunk.com]
      ACSApps[App Install / Uninstall]
      ACSIndexes[Index Management]
      ACSHEC[HEC Token Management]
      ACSRestart[Stack Restart]
      ACSAllowlist[IP Allowlist]
    end

    subgraph searchTier [Search Tier]
      SplunkWeb["Splunk Web -- :443\n(dashboards, search, app UI)"]
      RESTAPI["REST API -- :8089\n(app config, inputs, search jobs)"]
      SHCluster["Search Head Cluster"]
    end

    subgraph indexTier [Index Tier]
      HECEndpoint["HEC Endpoint -- :443"]
      Indexers[Indexers]
    end
  end

  SplunkUser -->|"Browser :443\n(search-ui allowlist)"| SplunkWeb
  Admin -->|"Browser :443"| SplunkWeb
  Scripts --> ACSCLI
  ACSCLI -->|"HTTPS"| acsLayer
  Scripts -->|"REST :8089\n(search-api allowlist)"| RESTAPI
  SplunkWeb --> SHCluster
  RESTAPI --> SHCluster
  SHCluster --> Indexers
  HECEndpoint --> Indexers
```

**Credential flow**: ACS uses `STACK_TOKEN` or `STACK_USERNAME/PASSWORD` plus
`SPLUNK_USERNAME/PASSWORD` for Splunkbase operations. Search-tier REST uses
`SPLUNK_USER/PASS` (defaulting to `STACK_USERNAME/PASSWORD` on Cloud).

**Automatic behaviors**:
- Direct search-head resolution via ACS to bypass SHC propagation delays
- Public IP auto-added to search-api allowlist
- Stack-local credentials swapped in for 8089 auth

### ACS Deployment Caveats

ACS app installs are generally reliable but have several edge cases that the
scripts defend against:

**App content corruption** — When multiple Splunkbase apps are installed in
rapid succession (especially after uninstall/reinstall cycles), ACS can
occasionally deploy the wrong app's files into another app's directory. This
corrupts the affected app: its custom REST handlers return 404, modular input
types do not register, and `app.conf` shows metadata from a different app. The
`cloud_batch_install.sh` script includes a post-install verification pass that
queries each app's `configs/conf-app/package` endpoint to confirm the `id`
field matches the expected app name. If a mismatch is detected, uninstall the
affected app and reinstall it individually.

**Visibility defaults to false** — TAs installed via ACS may have
`visible=false` in their app settings, making them invisible in Splunk Web. The
skill-specific `setup.sh` scripts auto-fix this by POSTing `visible=true` to
`/services/apps/local/{app}` during the default setup flow.

**409 on reinstall** — If ACS believes an app is already installed, a fresh
`apps install splunkbase` returns HTTP 409. The batch installer treats this as a
skip rather than a failure. To force a re-deployment, uninstall first via
`acs apps uninstall`, wait for the stack to settle, then install again.

### Enterprise (On-Prem)

A single Splunk instance or a distributed deployment under your control. All
operations go through the REST API on port 8089. ACS is not involved.

```mermaid
flowchart TB
  subgraph users [Users]
    SplunkUser["Analysts / Operators"]
    Admin["Splunk Admin"]
  end

  subgraph userMachine [Automation Machine]
    Scripts[Skill Scripts]
  end

  subgraph splunkEnterprise [Splunk Enterprise]
    subgraph searchHead [Search Head]
      SplunkWeb["Splunk Web -- :443"]
      RESTAPI["REST API -- :8089"]
      AppREST["App REST Handlers\n(accounts, inputs, conf)"]
    end

    subgraph indexer [Indexer Layer]
      HECEndpoint["HEC Endpoint -- :8088"]
      Indexers[Indexers]
    end
  end

  SplunkUser -->|"Browser :443"| SplunkWeb
  Admin -->|"Browser :443"| SplunkWeb
  Scripts -->|"REST :8089"| RESTAPI
  Scripts -.->|"SSH staging\n(fallback for app install)"| searchHead
  RESTAPI --> AppREST
  SplunkWeb --> AppREST
  HECEndpoint --> Indexers
  searchHead --> Indexers
```

**Credential flow**: `SPLUNK_USER/PASS` for REST API access. `SPLUNK_SSH_*` for
remote local-package staging when the Splunk host cannot read the package from
the local workstation path.

**App install paths**:
1. Local Splunk host: install the server-local package path through `/services/apps/local` with `filename=true`
2. Remote Splunk host: stage the package to `/tmp` over SSH, then install that staged server-local path through `/services/apps/local` with `filename=true`

### Hybrid (Cloud + Heavy Forwarder)

The most common production pattern for data collection TAs on Splunk Cloud.
The search tier runs in Splunk Cloud, but data collection happens on a
customer-controlled heavy forwarder (HF) or universal forwarder (UF).

```mermaid
flowchart TB
  subgraph users [Users]
    SplunkUser["Analysts / Operators"]
    Admin["Splunk Admin"]
  end

  subgraph userMachine [Automation Machine]
    Scripts[Skill Scripts]
    ACSCLI[ACS CLI]
  end

  subgraph splunkCloud [Splunk Cloud]
    subgraph acsLayer [ACS Control Plane]
      ACSApps[App Install]
      ACSIndexes[Indexes]
      ACSHEC[HEC Tokens]
      ACSRestart[Restart]
    end

    subgraph searchTier [Search Tier]
      SplunkWeb["Splunk Web -- :443"]
      RESTAPI["REST API -- :8089"]
      SHCluster[Search Head Cluster]
    end

    subgraph indexTier [Index Tier]
      HECEndpoint["HEC -- :443"]
      S2SEndpoint["S2S -- :9997"]
      Indexers[Indexers]
    end
  end

  subgraph customerInfra [Customer Infrastructure]
    HF["Heavy Forwarder"]
    DataSources["Data Sources\n(network devices, APIs, agents)"]
  end

  SplunkUser -->|"Browser :443"| SplunkWeb
  Admin -->|"Browser :443"| SplunkWeb
  Scripts --> ACSCLI
  ACSCLI --> acsLayer
  Scripts -->|"REST :8089"| RESTAPI
  Scripts -->|"SSH / REST :8089"| HF

  SplunkWeb --> SHCluster
  RESTAPI --> SHCluster
  DataSources --> HF
  HF -->|"S2S :9997"| S2SEndpoint
  HF -->|"HEC :443"| HECEndpoint
  S2SEndpoint --> Indexers
  HECEndpoint --> Indexers
  SHCluster --> Indexers
```

**Credential flow**: The `credentials` file contains both Cloud (ACS/stack)
settings and Enterprise (HF) settings. The repo supports two resolution
strategies:

1. **Profile-based** -- `SPLUNK_PROFILE=cloud` and
   `SPLUNK_SEARCH_PROFILE=hf` in the credentials file. Cloud keeps
   platform/ACS settings while HF overrides search-tier REST and SSH settings.
   Add `SPLUNK_TARGET_ROLE=search-tier` and
   `SPLUNK_SEARCH_TARGET_ROLE=heavy-forwarder` when you want warning-only role
   checks to follow that split.
2. **Platform override** -- `SPLUNK_PLATFORM=cloud` or
   `SPLUNK_PLATFORM=enterprise` per command to select the target explicitly.

When ambiguous, interactive scripts prompt the user to choose.

**Typical hybrid operations**:

| Operation | Target | API Surface |
|-----------|--------|-------------|
| App install on search tier | Cloud | ACS |
| Index creation | Cloud | ACS |
| TA account config on search tier | Cloud search head | REST :8089 |
| App install on HF | HF | REST :8089 or SSH |
| Input config on HF | HF | REST :8089 |
| Forwarder output config | HF | Host-level config |

Runtime role and delivery plane stay separate in this model. A package can be
classified as `search-tier` while still being delivered through ACS on Cloud or
through a deployer/cluster-manager path in Enterprise.

## How Scripts Select the Target

```mermaid
flowchart TB
  Start[Script sources credential_helpers.sh] --> LoadFile[Load credentials file]
  LoadFile --> ResolveProfile{Profile set?}
  ResolveProfile -->|Yes| UseProfile[Apply profile values]
  ResolveProfile -->|No| UseFlatKeys[Apply flat key values]
  UseProfile --> DetectPlatform
  UseFlatKeys --> DetectPlatform

  DetectPlatform{Detect platform}
  DetectPlatform -->|"SPLUNK_PLATFORM set"| UseExplicit[Use explicit platform]
  DetectPlatform -->|"URI contains .splunkcloud.com"| IsCloud[Cloud]
  DetectPlatform -->|"Cloud config + localhost URI"| IsCloud
  DetectPlatform -->|"Cloud config + non-Cloud URI"| IsHybrid{Hybrid -- prompt or error}
  DetectPlatform -->|"No Cloud config"| IsEnterprise[Enterprise]

  IsCloud --> CloudSetup[Auto-resolve search head\nAuto-allowlist IP\nSwap to stack credentials]
  IsEnterprise --> EnterpriseSetup[Use SPLUNK_URI as-is]
  IsHybrid -->|Interactive| PromptUser[User selects target]
  IsHybrid -->|Non-interactive| ErrorOut[Error: set SPLUNK_PLATFORM]
  PromptUser --> CloudSetup
  PromptUser --> EnterpriseSetup
```

## Port Usage Summary

| Port | Service | Used By | Allowlist Feature |
|------|---------|---------|-------------------|
| 443 | Splunk Web (UI) | Browser access | `search-ui` |
| 443 | HEC ingestion | ThousandEyes streams, webhook alerts | `hec` |
| 8089 | Search-tier REST API | All TA configuration and validation | `search-api` |
| 8089 | IDM API | Add-on data ingestion | `idm-api` |
| 8088 | HEC (Enterprise) | Enterprise HEC ingestion | N/A (local) |
| 9997 | S2S forwarding | HF/UF to Cloud indexers | `s2s` |
| 22 | SSH | Enterprise app staging fallback | N/A (local) |

## Data Flow by TA Type

### Polling And App-Managed API TAs (AppDynamics, Catalyst, Meraki, Intersight, DC Networking)

```mermaid
flowchart LR
  VendorAPI["Vendor API / SaaS\n(AppDynamics, Catalyst Center, Meraki Dashboard,\nIntersight, DCNM/NDFC)"]
  SplunkInput["Splunk Modular Input or\napp-managed collector\n(runs on search tier or HF)"]
  Index[Splunk Index]

  VendorAPI -->|"API poll"| SplunkInput
  SplunkInput -->|"index locally or\nforward via S2S"| Index
```

`cisco-security-cloud-setup` and `cisco-secure-access-setup` fit the same
collector/setup role, but they lean more heavily on app-specific REST handlers,
product wrappers, and packaged defaults than the simplified modular-input flow
shown above.

### HEC Push TAs (ThousandEyes)

```mermaid
flowchart LR
  TEStreaming["ThousandEyes\nStreaming API"]
  TEWebhook["ThousandEyes\nWebhook"]
  TEPolling["ThousandEyes\nEvents API"]
  HEC["Splunk HEC\n(:443 Cloud / :8088 Enterprise)"]
  SplunkInput["Splunk Modular Input\n(polling only)"]
  Index[Splunk Index]

  TEStreaming -->|"HEC push"| HEC
  TEWebhook -->|"HEC push"| HEC
  TEPolling -->|"API poll"| SplunkInput
  HEC --> Index
  SplunkInput --> Index
```

### Passive Capture (Splunk Stream)

```mermaid
flowchart LR
  Network["Network Traffic"]
  StreamTA["Stream TA\n(on HF/UF)"]
  StreamApp["Stream App\n(on search tier)"]
  Index[Splunk Index]

  Network -->|"packet capture"| StreamTA
  StreamTA -->|"S2S forward"| Index
  StreamApp -->|"search-time\nknowledge"| Index
```

**Implementation guardrail**: in Splunk Cloud, `splunk-stream-setup` only
supports index creation against the Cloud stack. Installing Stream apps and
configuring `Splunk_TA_stream` must target the forwarder or Enterprise
management endpoint, because Stream remains a hybrid deployment.

### External Syslog Collector (SC4S)

```mermaid
flowchart LR
  SyslogSources["Network / Security devices"]
  SC4S["SC4S container\n(host or Kubernetes)"]
  SplunkPrep["Repo skill\n(indexes, HEC, render assets)"]
  HEC["Splunk HEC\n(:443 Cloud / :8088 Enterprise)"]
  Index["Splunk Indexes"]

  SplunkPrep -->|"prepare HEC + indexes"| HEC
  SyslogSources -->|"syslog"| SC4S
  SC4S -->|"HEC events"| HEC
  HEC --> Index
```

**Implementation guardrail**: `splunk-connect-for-syslog-setup` does not deploy
SC4S onto the Splunk Cloud search tier. The skill prepares the Splunk-side
objects and renders runtime assets for customer-managed Docker/Podman/systemd
or Kubernetes infrastructure.

### External SNMP Collector (SC4SNMP)

```mermaid
flowchart LR
  Devices["Network / Infrastructure devices"]
  Poller["SC4SNMP poller"]
  Trap["SC4SNMP trap listener"]
  SplunkPrep["Repo skill\n(indexes, HEC, render assets)"]
  HEC["Splunk HEC\n(:443 Cloud / :8088 Enterprise)"]
  Index["Splunk event + metric indexes"]

  SplunkPrep -->|"prepare HEC + indexes"| HEC
  Devices -->|"SNMP poll"| Poller
  Devices -->|"SNMP traps"| Trap
  Poller -->|"events + metrics"| HEC
  Trap -->|"trap events"| HEC
  HEC --> Index
```

**Implementation guardrail**: `splunk-connect-for-snmp-setup` does not deploy
SC4SNMP onto the Splunk Cloud search tier. The skill prepares the Splunk-side
objects and renders runtime assets for customer-managed Docker Compose or
Kubernetes infrastructure.

### Search-Time And Premium Apps

Some skills do not own the collection path at all. They sit on top of existing
indexes and configure search-time knowledge objects, dashboards, or premium app
features.

```mermaid
flowchart LR
  IndexedData["Existing indexed data"] --> SearchApp["Search-time app\n(macros, saved searches,\ndata models, dashboards)"]
  SearchApp --> Users["Analysts / Operators"]
```

**Examples**:
- `cisco-enterprise-networking-setup` updates macros, enables saved searches,
  and can enable data model acceleration for the visualization app.
- `splunk-itsi-setup` installs and validates the premium app layer that other
  skills may integrate with.

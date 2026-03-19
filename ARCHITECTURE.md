# Deployment Architecture

How the scripts in this repo adapt to Splunk Cloud, Enterprise (on-prem), and
hybrid deployments.

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
remote file staging when REST upload is unavailable.

**App install paths** (tried in order):
1. REST upload via `/services/apps/local`
2. SSH staging to `$SPLUNK_HOME/etc/apps/`

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

### Polling TAs (Catalyst, Meraki, Intersight, DC Networking)

```mermaid
flowchart LR
  VendorAPI["Vendor API\n(Catalyst Center, Meraki Dashboard,\nIntersight, DCNM/NDFC)"]
  SplunkInput["Splunk Modular Input\n(runs on search tier or HF)"]
  Index[Splunk Index]

  VendorAPI -->|"API poll"| SplunkInput
  SplunkInput -->|"index locally or\nforward via S2S"| Index
```

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

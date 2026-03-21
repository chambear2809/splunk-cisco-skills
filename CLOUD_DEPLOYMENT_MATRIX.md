# Cloud Deployment Matrix

_Generated from `skills/shared/app_registry.json` by `skills/shared/scripts/generate_deployment_docs.py`; do not edit manually._

This document defines the normal Splunk Cloud deployment model for the
repo's cloud-supported apps and workflows.

For cross-platform placement across search tiers, indexers, forwarders, and
external collectors, see
[`DEPLOYMENT_ROLE_MATRIX.md`](DEPLOYMENT_ROLE_MATRIX.md).

## Default Rule

- For apps published on Splunkbase, prefer **ACS Splunkbase installs** and let
  ACS fetch the latest compatible release. Use `--source splunkbase` with the
  app's Splunkbase ID.
- Use private package uploads (`acs apps install private`) only for genuinely
  private or pre-vetted apps that do not have a public Splunkbase listing.
- Keep vendor archives in `splunk-ta/` as the local cache and review copy.
- Use **ACS** for Splunk Cloud app installation, index management, and restarts.
- Use **search-tier REST** for post-install app configuration when the
  `search-api` allow list permits it.
- Do **not** require extract/repack as part of the normal workflow.
- Treat anything under `splunk-ta/_unpacked/` as review-only.

## App And Workflow Matrix

| Skill | Splunkbase ID | Cloud install path | Cloud config path | Notes |
| --- | --- | --- | --- | --- |
| `cisco-catalyst-ta-setup` | 7538 | ACS Splunkbase | REST via custom account/input handlers | Cisco EULA license-ack required. |
| `cisco-catalyst-enhanced-netflow-setup` | 6872 | Manual install on HF/UF you control | No app-local config; validate the NetFlow/IPFIX receiver path on the same target | Cisco EULA license-ack required. Optional forwarder-side mappings for extra Enterprise Networking NetFlow dashboards. |
| `cisco-appdynamics-setup` | 3471 | ACS Splunkbase | REST via custom account/input handlers | Configure the AppDynamics controller account and data inputs after install. |
| `cisco-security-cloud-setup` | 7404 | ACS Splunkbase | REST via CiscoSecurityCloud custom admin handlers | Cisco EULA license-ack required. Multi-product Cisco Security integration app with product-specific setup flows for each packaged integration. |
| `cisco-secure-access-setup` | 5558 | ACS Splunkbase | REST via `org_accounts`, `update_settings`, and related app APIs | Cisco EULA license-ack required. The local package is the Secure Access app (`cisco-cloud-security`), not the separate add-on listing. Covers org onboarding plus dashboard settings/bootstrap. |
| `cisco-meraki-ta-setup` | 5580 | ACS Splunkbase | REST via custom account/input handlers | Cisco EULA license-ack required. Dashboard macro alignment after install. |
| `cisco-intersight-setup` | 7828 | ACS Splunkbase | REST via custom account/input handlers | Cisco EULA license-ack required. Index creation uses ACS. |
| `cisco-dc-networking-setup` | 7777 | ACS Splunkbase | REST via custom account/input handlers | Cisco EULA license-ack required. Index creation uses ACS. |
| `cisco-enterprise-networking-setup` | 7539 | ACS Splunkbase | REST for macros/saved searches/datamodel settings | Cisco EULA license-ack required. Visualization app only; installer auto-adds required TA `7538` when missing. Optional Enhanced Netflow add-on `6872` should be offered separately when users want extra NetFlow dashboards. |
| `cisco-thousandeyes-setup` | 7719 | ACS Splunkbase | REST for OAuth account, HEC-based streaming inputs, polling inputs | Requires HEC token. OAuth device code flow for auth. ITSI integration optional. |
| `splunk-itsi-setup` | 1841 | ACS Splunkbase | No post-install REST config needed | Premium product; requires ITSI license. Enables ThousandEyes ITSI integration. |
| `splunk-stream-setup` search-tier app | 1809 | ACS or Splunk Cloud support workflow | Stream UI / REST on search tier | Cloud deployment is hybrid, not single-target. |
| `splunk-stream-setup` wire-data add-on | 5234 | ACS or bundled with Stream deployment | No special post-install config in normal flow | Knowledge-object support for Stream search content. |
| `splunk-stream-setup` forwarder add-on | 5238 | Manual install on HF/UF you control | Local HF files plus host forwarding config | This package runs on the heavy/universal forwarder, not the Cloud search tier. |
| `splunk-connect-for-syslog-setup` | N/A | No Splunk Cloud app install; SC4S runtime is rendered for customer-managed hosts or Kubernetes | ACS for indexes/HEC where available, search-tier REST for validation, rendered host/Helm assets for runtime | External syslog-ng collector pattern. Modeled as a workflow row rather than a Splunk app package. |

## Stream Heavy Forwarder Model

For Splunk Stream on Splunk Cloud:

- install `splunk_app_stream` on the Splunk Cloud search tier
- install `Splunk_TA_stream` on a customer-controlled HF/UF
- use the local overlay template in:
  `skills/splunk-stream-setup/templates/splunk-cloud-hf-netflow-any/`
- configure HF forwarding to Splunk Cloud at the host layer

## SC4S External Collector Model

For Splunk Connect for Syslog on Splunk Cloud:

- create or validate indexes and HEC tokens against the Cloud stack
- run the SC4S syslog-ng container on infrastructure you control
- send SC4S output directly to Splunk Cloud HEC on `443`
- keep SC4S runtime files, token material, and local archive/disk-buffer storage
  on the customer-managed host or Kubernetes cluster

## Cloud Access Architecture

Splunk Cloud exposes two distinct API surfaces. The scripts in this repo use
both depending on the operation.

### ACS vs Search-Tier REST (8089)

| Operation | ACS (no 8089 needed) | REST 8089 required |
| --- | --- | --- |
| App install / uninstall | Yes | -- |
| Index create / check | Yes | -- |
| HEC token management | Yes | -- |
| Stack restart | Yes | -- |
| IP allowlist management | Yes | -- |
| TA account setup (OAuth, API keys) | -- | Yes |
| Input enablement / configuration | -- | Yes |
| Conf / macro updates | -- | Yes |
| Saved search toggles | -- | Yes |
| Validation (app state, data flow) | -- | Yes |
| Oneshot search | -- | Yes |

Port 443 on Splunk Cloud serves Splunk Web (the browser UI). The full REST API
(`/servicesNS/...`, `/services/...`) is documented exclusively on port 8089.
ACS does not expose app-specific custom REST handlers.

### Automatic Search-API Access

When a script detects a Cloud target, the shared helpers automatically:

1. **Resolve the current search head** via `acs config current-stack` and
   build a direct search-head REST URL (`https://sh-i-*.stack.splunkcloud.com:8089`).
2. **Switch to stack-local credentials** (`STACK_USERNAME` / `STACK_PASSWORD`)
   for 8089 authentication.
3. **Add the current public IP to the search-api allowlist** via
   `acs ip-allowlist create search-api --subnets <ip>/32` if it is not already
   listed.

This means a user with valid ACS credentials can run any skill against Splunk
Cloud without manually configuring the search-api IP allowlist or knowing the
direct search-head hostname.

To disable the automatic allowlist management (for example, in environments
where IP allowlists are controlled externally), set:

```bash
export SPLUNK_SKIP_ALLOWLIST="true"
```

### Why Direct Search Heads?

After an ACS app install, the load-balanced stack hostname
(`stack.splunkcloud.com:8089`) can take time to reflect the new app across all
search-head cluster members. The direct search-head URL bypasses this
propagation delay and sees the installed app immediately.

## What `_unpacked` Means

The `_unpacked` trees exist only so we can:

- inspect package internals
- identify Cloud compatibility risks
- document vendor package limitations

They are not the normal installation source for this repo's Cloud workflow.

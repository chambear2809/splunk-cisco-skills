# Splunk AI Assistant for SPL Reference

## App Identity

| Field | Value |
|-------|-------|
| Splunkbase ID | `7245` |
| Internal app name | `Splunk_AI_Assistant_Cloud` |
| Deployment target | Search heads only |
| Splunk Cloud eligible | Yes (commercial stacks, supported regions) |

## Enterprise Onboarding Flow

Enterprise cloud-connected deployments follow a multi-step flow:

1. **Install** the app from Splunkbase
2. **Configure proxy** (optional) if the search head requires an outbound proxy
   to reach `*.scs.splunk.com:443`
3. **Submit onboarding form** with email, region, company name, and tenant name
4. **Wait** for the Splunk-issued activation code/token
5. **Complete activation** by passing the activation code file

### Region Tokens

| Token | Region |
|-------|--------|
| `usa` | US commercial |

The setup script normalizes common aliases (e.g., `us` to `usa`).

### Onboarding REST Handlers

| Handler path | Purpose |
|--------------|---------|
| `/servicesNS/nobody/Splunk_AI_Assistant_Cloud/submitonboardingform` | Submit the onboarding form (email, region, company, tenant) |
| `/servicesNS/nobody/Splunk_AI_Assistant_Cloud/completeonboarding` | Complete activation with the Splunk-issued activation code |
| `/servicesNS/nobody/Splunk_AI_Assistant_Cloud/cloudconnectedproxysettings` | Configure or remove the outbound proxy |
| `/servicesNS/nobody/Splunk_AI_Assistant_Cloud/version` | Read the app's internal API version |
| `/servicesNS/nobody/Splunk_AI_Assistant_Cloud/storage/collections/data/cloud_connected_configurations` | KVStore collection for onboarding state and tenant config |

## Validation Checks

The `validate.sh` script verifies:

| Check | What it confirms |
|-------|------------------|
| App installed | `Splunk_AI_Assistant_Cloud` present and visible |
| API auth | Splunk REST authentication succeeds |
| KVStore health | KVStore status is ready (chat data is stored there) |
| Onboarding state | Reports not-started, submitted, or fully onboarded |
| Proxy state | Reports proxy configured or not |

### Optional Assertions

Pass `--expect-configured true` or `--expect-onboarded true` to make
validation fail when those states are not met.

## Known Constraints

1. Splunk Cloud installs must use the public Splunkbase listing, not a private
   upload of a downloaded archive
2. Enterprise onboarding requires outbound HTTPS to `*.scs.splunk.com`
3. The activation code/token may not be available immediately after form
   submission
4. Proxy credentials and activation codes must be provided via local files,
   never in chat
5. SHC delivery depends on the shared installer and deployer-target credentials
6. The validator avoids `/config` and `/get_feature_flags` endpoints because
   they can error before onboarding completes

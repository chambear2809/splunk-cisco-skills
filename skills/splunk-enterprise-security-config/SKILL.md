---
name: splunk-enterprise-security-config
description: >-
  Configure and validate Splunk Enterprise Security (ES) after installation,
  including ES indexes, Splunk_TA_ForIndexers readiness, users and roles,
  managed custom roles, CIM data models, data model acceleration, assets and
  identities, threat intelligence, detections, risk-based alerting, Mission
  Control, exposure analytics, UEBA, SOAR integrations, and configuration
  health checks. Use when the user asks to configure, tune, validate, or
  operationalize Splunk Enterprise Security.
---

# Splunk Enterprise Security Config

Configures and validates **Splunk Enterprise Security** after
`SplunkEnterpriseSecuritySuite` has been installed and post-install setup has
run.

## Agent Behavior

Never ask for secrets in chat. Splunk credentials are read from the project-root
`credentials` file, falling back to `~/.splunk/credentials`. If neither exists,
guide the user to run:

```bash
bash skills/shared/scripts/setup_credentials.sh
```

Before applying changes, identify the deployment shape:

- Standalone search head
- Dedicated distributed search head
- Search head cluster deployer
- Splunk Cloud Platform
- Hybrid on-prem ES search head searching remote indexers

Use this skill for ES configuration. Use
`splunk-enterprise-security-install` first if ES is not installed.

## Quick Start

Validate current ES configuration:

```bash
bash skills/splunk-enterprise-security-config/scripts/validate.sh
```

Preview a full declarative ES configuration plan:

```bash
bash skills/splunk-enterprise-security-config/scripts/setup.sh \
  --spec skills/splunk-enterprise-security-config/templates/es-config.example.yaml
```

Apply an explicit ES configuration spec:

```bash
bash skills/splunk-enterprise-security-config/scripts/setup.sh \
  --spec es-config.yaml \
  --apply \
  --validate
```

Apply low-risk baseline settings on an on-prem search tier:

```bash
bash skills/splunk-enterprise-security-config/scripts/setup.sh \
  --set-lookup-order \
  --set-managed-roles ess_analyst,ess_user \
  --validate
```

Create ES indexes on the target index tier or standalone instance:

```bash
bash skills/splunk-enterprise-security-config/scripts/setup.sh \
  --create-core-indexes \
  --create-mission-control-indexes \
  --create-exposure-indexes \
  --max-size-mb 512000 \
  --validate
```

## Configuration Workflow

1. **Read the reference**:

   ```text
   skills/splunk-enterprise-security-config/reference.md
   ```

2. **Validate install state** with the install skill:

   ```bash
   bash skills/splunk-enterprise-security-install/scripts/validate.sh
   ```

3. **Deploy technology add-ons**:
   - Keep ES framework apps (`SA-` and `DA-ESS-`) enabled.
   - Deploy data-source TAs to forwarders and indexers based on each TA's docs.
   - For clustered on-prem indexers, generate and redeploy
     `Splunk_TA_ForIndexers` after each ES release or TA change.

4. **Configure indexes and role search scope**:
   - Create ES and TA indexes on the index tier for distributed deployments.
   - Add security data indexes to `ess_user`, `ess_analyst`, and admin/sc_admin
     search scope. Do not include summary indexes as default searched indexes.

5. **Configure CIM and data models**:
   - Constrain CIM data models to relevant indexes for performance.
   - Review acceleration storage and retention.
   - Keep ES acceleration enforcement enabled for required models unless there
     is an explicit performance plan.

6. **Configure SOC enrichment**:
   - Assets and identities
   - Native threat intelligence or Threat Intelligence Management (Cloud)
   - Detections, finding-based detections, risk-based alerting, and MITRE
     annotations
   - Analyst queue/Mission Control queues and response workflows
   - SOAR, Attack Analyzer, UEBA, exposure analytics, and Splunk Cloud Connect
     where licensed and supported

7. **Validate and iterate**:

   ```bash
   bash skills/splunk-enterprise-security-config/scripts/validate.sh
   ```

## Declarative Configuration

Prefer the repo-local YAML/JSON workflow for full ES coverage:

```bash
bash skills/splunk-enterprise-security-config/scripts/setup.sh \
  --spec skills/splunk-enterprise-security-config/templates/es-config.example.yaml \
  --mode preview
```

Supported modes:

- `preview`: render the normalized spec, actions, diagnostics, and handoff items.
- `apply`: perform only supported writes. This mode requires `--apply`.
- `validate`: compare planned objects against live Splunk state and execute
  declarative `validation.searches` through read-only search export.
- `inventory`: collect current ES app, index, content, and integration state.
- `export`: emit a starter brownfield spec from live inventory.

The spec supports these top-level sections:

- `baseline` - lookup-order, managed roles, optional all-index creation
- `indexes` - core/UEBA/PCI/exposure/Mission Control/DLX/custom indexes
- `roles` - ES roles with allowed/default indexes and capabilities
- `data_models` - ES acceleration + CIM constraint macros
- `assets`, `identities` - lookup definitions, optional guarded local lookup
  uploads, ACL metadata, explicit builder-style scheduled searches, and
  identity-manager inputs
- `threat_intel` - native `threatlist://` feeds, guarded CSV/STIX/OpenIOC
  uploads, TIM Cloud readiness
- `detections` - existing tuning, custom detections with explicit SPL, optional
  `correlation_metadata` writes to `correlationsearches.conf`, drilldown fields,
  plus optional `acl` / `permissions` that POST to `/saved/searches/<name>/acl`
  with `sharing`, `owner`, and perms
- `risk` - risk factors and risk-rule saved searches
- `urgency` - `urgency.conf` severity-priority matrix
- `adaptive_response` - `alert_actions.conf` defaults for `notable`, `risk`,
  `finding`, `rba`, `sendalert`, `email`, `webhook`
- `notable_suppressions` - `notable_suppressions.conf` stanzas
- `log_review` - legacy spec keys for statuses / dispositions / settings. ES 8.x
  routes both statuses and dispositions to `reviewstatuses.conf` under
  `SA-ThreatIntelligence`, and `log_review.conf [incident_review]` settings to
  the same app
- `review_statuses` - modern ES 8.x entry point for notable and investigation
  review-status stanzas in `reviewstatuses.conf`
- `use_cases` - ES Use Case library / navigator entries
- `governance` - regulatory frameworks such as PCI, NIST, CIS
- `macros` - arbitrary `macros.conf` entries (beyond CIM constraints)
- `eventtypes` - `savedsearches.conf` eventtypes with tag lists
- `tags` - Splunk `fvtags` for field-value tagging
- `navigation` - app navigation XML (`data/ui/nav`)
- `glass_tables` - Glass Tables / ES dashboards as `data/ui/views`; XML that
  looks like it contains secret material auto-downgrades to a handoff action
- `workflow_actions` - analyst right-click actions (`data/ui/workflow-actions`)
- `kv_collections` - custom KV Store collections with field types, accelerated
  fields, and replication flags
- `findings` - `findings.conf [intermediate_findings]` settings
- `intelligence_management` - TIM Cloud subscription (`intelligence_management.conf`)
  plus handoff for tenant pairing
- `es_ai_settings` - ES 8.5 AI assistant and triage settings under Mission Control
- `dlx_settings` - `dlx-app` detection lifecycle tunables
- `exposure_analytics` - safe toggles for entity-discovery processing searches
  and A&I population saved searches/macros; source and enrichment-rule objects
  are create-only guarded when a documented endpoint, `conflict_policy:
  create_only`, and explicit `apply: true` are provided
- `content_library` - Splunk ES Content Update (`DA-ESS-ContentUpdate`) install
  via Splunkbase app `3449` on Enterprise apply, optional app-id overrides,
  ESCU subscription, story/detection enablement, content-pack toggles
- `mission_control`, `integrations`, `ta_for_indexers`, `content_governance`,
  `package_conf_coverage`, `validation`

Writes require `--apply`; preview, inventory, export, and validate are read-only.
Custom detections require explicit SPL and default to disabled unless
`enabled: true` is present. Mission Control API writes require `apply: true` on
the individual object. Secret-dependent integrations produce handoff steps and
must use file-path-only inputs such as `secret_file`, `password_file`,
`token_file`, or `cert_bundle_file` rather than inline secrets. Integration
`preflight: true` validates non-secret fields, app readiness, Splunk REST
endpoint availability, and secret-file existence/permissions without reading
secret contents. OAuth exchange and tenant pairing remain handoffs with
required inputs and safe next commands. Glass Table XML that contains literal
password/api_key/private-key markers is rejected as a handoff item even without
an explicit `secret_file` reference.

For `content_library.install: true`, `SA-ContentLibrary` is treated as
bundled/presence-checked unless `content_library.app_ids` provides an explicit
supported app id. Splunk Cloud content-library installation remains a handoff.
For lookup and threat-intel uploads, the spec must opt in with `apply: true`
and a local file path; export includes only metadata and ACLs, never file
contents. `Splunk_TA_ForIndexers` deployment is read-only planning by default
and overwrite requires explicit deploy intent plus `replace_existing: true` or
an overwrite policy, `backup_export`, clean conflict checks, and the
preview-generated `confirm_id`. Content rollback/delete and private Mission
Control overrides use the same two-phase confirmation pattern.
Asset and Identity Builder-style LDAP or cloud-provider sources require an
explicit `generating_search.search` SPL that writes the declared lookup with
`outputlookup`; otherwise the engine emits a handoff so directory profiles,
cloud credentials, and generated SPL stay reviewable.
Mission Control `search.workload_pool` maps to `mc_search.conf [aq_sid_caching]`
for analyst queue searches; create the workload pool with the workload
management skill before applying that setting. Optional Mission Control RBAC
lockdown is guarded behind `rbac_lockdown.apply: true`.
Private Mission Control internals are inventory/export-first. Only the
documented safe allowlist, currently `mc_search.conf [aq_sid_caching]
workload_pool`, is applied directly; other `private_overrides` require
`private_override: true`, `apply: true`, `backup_export`, and a matching
preview `confirm_id`.
For Splunk Cloud, `connection.cloud_support.evidence_package: true` creates a
Support-ready evidence package for app/index inventory, requested settings,
missing prerequisites, and ACS-supported readiness. Unsupported Cloud REST
writes and Support-only ES setup are not attempted.
Use `package_conf_coverage` for inventory/export-only coverage of every `.conf`
family shipped in the local ES package, including internal Mission Control,
analytic-story, managed-configuration, app-permission, dashboard-mapping, and
package-registration files. It does not create write actions.

## Scripts

### setup.sh

Applies repeatable ES configuration primitives and runs the declarative engine.

| Flag | Purpose |
|------|---------|
| `--spec PATH` | Run the YAML/JSON ES configuration-as-code workflow |
| `--mode preview\|apply\|validate\|inventory\|export` | Select declarative workflow mode |
| `--apply` | Required guard for declarative writes |
| `--output PATH` | Write declarative JSON output to a file |
| `--stop-on-error` | Halt the apply loop on the first failed action. Remaining actions are reported as `skipped`; there is **no rollback** of earlier successful actions. |
| `--strict` | Fail fast when the spec contains unknown top-level sections (typo guard for `valdation:`, `detentions:`, etc.) |
| `--baseline` | Convenience shortcut for lookup order, managed roles, all ES indexes, and validation |
| `--all-indexes` | Convenience shortcut for core, UEBA, PCI, exposure, Mission Control, and DLX indexes |
| `--set-lookup-order` | Set `limits.conf [lookup] enforce_auto_lookup_order=true` |
| `--set-managed-roles ROLES` | Set App Permissions Manager managed roles |
| `--create-core-indexes` | Create core ES indexes through the platform index helper |
| `--create-ueba-indexes` | Create UEBA indexes through the platform index helper |
| `--create-pci-indexes` | Create PCI indexes through the platform index helper |
| `--create-exposure-indexes` | Create exposure analytics indexes |
| `--create-mission-control-indexes` | Create Mission Control indexes bundled with ES 8.x |
| `--create-dlx-indexes` | Create detection lifecycle/confidence indexes |
| `--max-size-mb N` | `maxTotalDataSizeMB` for newly created indexes |
| `--enable-dm NAME` | Enable an ES `dm_accel_settings://NAME` stanza |
| `--disable-dm NAME` | Disable acceleration for an ES data model stanza |
| `--validate` | Run validation after changes |

No flags means validate only.

#### Combining declarative and imperative phases

When `--spec`, `--mode`, `--apply`, or `--output` is set together with imperative
shortcuts (`--baseline`, `--create-core-indexes`, `--set-lookup-order`, etc.),
the script runs the declarative phase first, then runs the imperative phase in
the same invocation. Earlier versions silently dropped the imperative phase.
Validation, when requested, runs once at the end of both phases.

#### Validation searches

`validation.searches` entries accept `expect_rows` (default `true`) and
`min_event_count` (default `1`). A search that returns fewer events than the
minimum is reported as `ok: false` with a `reason`. Set `expect_rows: false`
for "did the saved search even run?" smoke tests that should pass on zero
results.

#### Correlation metadata app discovery

`detections[].correlation_metadata.app` is now optional. When omitted, the
engine probes a documented list of SA-* and DA-ESS-* apps at apply time and
POSTs to the first app where the correlation rule resolves. Override the
search order via `correlation_metadata.app_search_order`.

### validate.sh

Read-only checks for:

- ES app availability and KV Store
- Core, UEBA, PCI, exposure analytics, Mission Control, and detection lifecycle index presence
- `enforce_auto_lookup_order`
- App Permissions Manager managed roles
- Data model acceleration enforcement stanzas
- Asset/identity and threat intelligence KV Store collections
- Detection, notable, risk, and threat activity smoke searches

## Additional Resources

- [reference.md](reference.md) — configuration coverage map, official source
  links, index checklist, and validation searches.

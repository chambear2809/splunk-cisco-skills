# Splunk Enterprise Security Config Reference

Use this after `splunk-enterprise-security-install` has installed and
post-installed ES.

## Official Sources

- Configure and deploy indexes:
  `https://help.splunk.com/?resourceId=ES_Install_ConfigureIndexes`
- Deploy technology add-ons:
  `https://help.splunk.com/en/splunk-enterprise-security-8/install/8.5/installation/deploy-technology-add-ons-to-splunk-enterprise-security`
- Users and roles:
  `https://help.splunk.com/en/splunk-enterprise-security-8/install/8.5/installation/users-and-roles-for-splunk-enterprise-security`
- Add custom roles and manage capabilities:
  `https://help.splunk.com/en/splunk-enterprise-security-8/install/8.5/installation/add-custom-roles-and-manage-capabilities-in-splunk-enterprise-security`
- Configure data models:
  `https://help.splunk.com/en/splunk-enterprise-security-8/install/8.5/installation/configure-data-models-for-splunk-enterprise-security`
- Asset and identity management:
  `https://help.splunk.com/en/splunk-enterprise-security-8/administer/8.5/asset-and-identity-management/add-asset-and-identity-data-to-splunk-enterprise-security`
- Threat intelligence overview:
  `https://help.splunk.com/en/splunk-enterprise-security-8/administer/8.5/threat-intelligence/overview-of-threat-intelligence-in-splunk-enterprise-security`
- Finding-based detections:
  `https://help.splunk.com/en/splunk-enterprise-security-8/administer/8.5/detections/create-finding-based-detections-in-splunk-enterprise-security`

## Declarative Configuration Coverage

The full configuration workflow is implemented by:

```bash
bash skills/splunk-enterprise-security-config/scripts/setup.sh --spec es-config.yaml --mode preview
```

The example spec is:

```text
skills/splunk-enterprise-security-config/templates/es-config.example.yaml
```

Modes:

- `preview` is read-only and renders normalized configuration, planned actions,
  diagnostics, and handoff items.
- `apply` performs only supported writes and requires `--apply`.
- `validate` is read-only and checks planned objects against live ES state,
  including declared `validation.searches` through search export.
- `inventory` is read-only and collects current apps, indexes, detections, and
  integration readiness signals.
- `export` is read-only and emits a starter spec from live inventory.

Top-level spec sections map to the documented coverage areas:

| Spec section | Coverage | REST surface |
|--------------|----------|-------------|
| `baseline` | Lookup ordering, App Permissions Manager managed roles, optional all-index creation | `conf-limits/lookup`, `conf-inputs/app_permissions_manager://...` |
| `indexes` | Core ES, UEBA, PCI, exposure analytics, Mission Control, DLX, and custom indexes | `/services/data/indexes` (via the platform index helper so ACS, bundle, or direct REST is selected from context) |
| `roles` | Role allowed/default indexes, imported roles, capabilities, and search quotas | `/services/admin/roles/<name>` |
| `data_models` | ES acceleration stanzas plus explicit CIM macro/index constraints | `conf-inputs/dm_accel_settings://<model>`, `admin/macros/<macro>` |
| `assets` / `identities` | Lookup definitions, optional guarded lookup-file upload/ACLs, explicit builder-style scheduled searches, identity manager inputs | `data/lookup-table-files`, lookup ACL endpoints, `conf-transforms/<lookup>`, `/saved/searches/<name>`, `conf-inputs/identity_manager://<name>` |
| `threat_intel` | Native `threatlist://` sources, guarded CSV/STIX/OpenIOC uploads, TIM Cloud readiness | `conf-inputs/threatlist://<name>`, `/data/threat_intel/upload` when supported |
| `detections` | Existing tuning and explicit custom SPL detections with optional drilldown fields | `/saved/searches/<name>` |
| `detections.*.correlation_metadata` | `correlationsearches.conf` extended fields (`security_domain`, `severity`, `nes_fields`, drilldown metadata) | `/admin/correlationsearches/<name>` |
| `detections.*.acl` / `detections.*.permissions` | Splunk ACL for the saved search (`sharing`, `owner`, perms.read / perms.write) | `/servicesNS/<owner>/<app>/saved/searches/<name>/acl` |
| `risk` | Risk factors and risk-rule saved searches | `conf-risk_factors/<name>`, `/saved/searches/<name>` |
| `urgency` | `urgency.conf` severity-priority matrix | `conf-urgency/<priority>\|<severity>` |
| `adaptive_response` | Default params for `notable`, `risk`, `finding`, `rba`, `sendalert`, `email`, `webhook` stanzas | `conf-alert_actions/<stanza>` |
| `notable_suppressions` | `notable_suppressions.conf` modular input stanzas | `conf-notable_suppressions/notable_suppression://<name>` |
| `log_review` (legacy spec keys) / `review_statuses` | ES 8.x review statuses and dispositions in `reviewstatuses.conf`; global incident-review settings in `log_review.conf [incident_review]` | `SA-ThreatIntelligence/configs/conf-reviewstatuses/<id>`, `SA-ThreatIntelligence/configs/conf-log_review/incident_review` |
| `use_cases` | ES Use Case navigator entries (`use_cases.conf`) | `conf-use_cases/<name>` in `SA-Utils` |
| `governance` | Compliance framework mapping (`governance.conf`) | `conf-governance/<name>` in `SA-AuditAndDataProtection` |
| `macros` | Arbitrary `macros.conf` entries | `/admin/macros/<name>` |
| `eventtypes` | Saved eventtypes with tags, descriptions, priority | `/saved/eventtypes/<name>` |
| `tags` | Splunk `fvtags` for `field=value` tagging | `/saved/fvtags/<field=value>` |
| `navigation` | ES app navigation XML | `/data/ui/nav/default` |
| `glass_tables` | Glass Table views via `eai:data` XML; secret-like XML auto-handoffs | `/data/ui/views/<name>` |
| `workflow_actions` | Analyst right-click actions (display location, fields, link uri/method/target, search navigation) | `/servicesNS/nobody/<app>/data/ui/workflow-actions/<name>` |
| `kv_collections` | Custom KV Store collections with typed fields, accelerated indexes, replicate/enforceTypes flags | `/servicesNS/nobody/<app>/storage/collections/config/<name>` |
| `findings` | `findings.conf [intermediate_findings]` settings (e.g. `use_current_time`) | `SA-ThreatIntelligence/configs/conf-findings/intermediate_findings` |
| `intelligence_management` | TIM Cloud subscription (`subscribed`, `enclave_ids`, `im_scs_url`, `is_talos_query_enabled`) plus handoff for tenant pairing | `missioncontrol/configs/conf-intelligence_management/im` |
| `es_ai_settings` | ES 8.5 AI assistant / triage settings (`settings`, `ai_triage_detections`, `triage_agent_dispatch_settings` stanzas) | `missioncontrol/configs/conf-es_ai_settings/<stanza>` |
| `dlx_settings` | Detection lifecycle tuning (`api_config`, `scheduler`, `worker`, `detection_sync`, `search`) | `dlx-app/configs/conf-dlx_settings/<stanza>` |
| `exposure_analytics` | Entity-discovery processing searches, A&I population saved searches/macros, source/enrichment inventory, and create-only guarded source/enrichment applies | `exposure-analytics/saved/searches/<name>`, `exposure-analytics/admin/macros/<name>`, documented `exposure-analytics` REST endpoints supplied in the spec |
| `content_library` | Enterprise apply can install `DA-ESS-ContentUpdate` from Splunkbase app `3449`; `SA-ContentLibrary` is bundled/presence-checked unless an explicit app id override is supplied; supports ESCU subscription, story/detection enablement, and content-pack toggles | `install_app.sh --source splunkbase --app-id 3449 --update`, `conf-escu_subscription/subscription`, `/saved/searches/<story\|detection>`, `conf-content_packs/<pack>` |
| `mission_control` | Queue, response-template, response-plan inventory, analyst queue workload pool, optional RBAC lockdown, API support validation, guarded API writes, and confirm-gated private overrides | `/servicesNS/nobody/missioncontrol/*`, `conf-mc_search/aq_sid_caching`, `conf-inputs/lock_unlock_resources://default`, private `conf-*` only with confirmation |
| `integrations` | SOAR, Attack Analyzer, TIM Cloud, BA/UEBA, Splunk Cloud Connect readiness, file-only secret preflight, Cloud Support evidence, plus stable local config | `conf-cloud_integrations/<name>` (when declared), read-only preflight endpoints |
| `ta_for_indexers` | Package/version/deployment readiness, conflict-aware generation, and two-phase guarded overwrite/deploy handoff | Uses the ES install skill helper; overwrite requires `replace_existing`, `backup_export`, clean conflict checks, and preview `confirm_id` |
| `content_governance` | `SA-ContentVersioning`, `SA-TestModeControl`, `SA-Detections`, `ess_content_importer`, safe production/test toggles, and two-phase rollback/delete handoffs | `conf-inputs/test_mode`, `conf-inputs/ess_content_importer://content_importer`, guarded `SA-ContentVersioning` toggles and explicit destructive endpoints |
| `package_conf_coverage` | Inventory/export-only manifest for every `.conf` family shipped in the local ES package, including internal and package-owned files | Local package scan plus optional live `/configs/conf-*` sampling |
| `validation` | Read-only SPL checks such as `tstats`, `get_asset`, and `get_identity4events` smoke tests | `/services/search/jobs/export` |

Safety defaults:

- New custom detections default to disabled unless `enabled: true`.
- Mission Control API writes require `apply: true` on each object; validate
  mode reports whether the public endpoints are present.
- Lookup-file uploads and threat-intel uploads require explicit apply intent,
  local file paths, and supported endpoints; exports never include file contents.
- Integration secrets must be declared only as file paths (`secret_file`,
  `password_file`, `token_file`, `cert_bundle_file`, or `client_secret_file`).
  Preflight checks stat the files and report permissions, but do not read them.
- OAuth/token exchange, tenant pairing, and Splunk Cloud Support-managed setup
  remain executable evidence/handoff workflows. In Cloud mode,
  `connection.cloud_support.evidence_package: true` adds requested apps,
  settings, live inventory, missing prerequisites, and ACS-supported readiness
  notes to preview/export output.
- Private Mission Control overrides outside the allowlist are blocked unless
  the spec includes `private_override: true`, `apply: true`, `backup_export`,
  and the exact preview-generated `confirm_id`.
- Exposure Analytics source and enrichment-rule objects are applyable only as
  `create_only_safe` objects with a documented endpoint and
  `conflict_policy: create_only`; updates, deletes, missing endpoints, and
  schema mismatches stay handoff-only.
- Content rollback/delete/conflict resolution and `Splunk_TA_ForIndexers`
  overwrite use two-phase confirmation with backup evidence and a matching
  preview `confirm_id`; exported specs default these fields to non-applying.
- `package_conf_coverage` never writes. It classifies shipped `.conf` families
  as first-class managed, inventory-only/internal, platform-owned, package-owned,
  or forbidden secret storage.
- Splunk ES Content Update (`DA-ESS-ContentUpdate`, ESCU) defaults to
  Splunkbase app `3449`; Cloud app installation remains a handoff unless a
  supported Cloud path is handled outside this workflow.
- Unknown live fields are preserved on update; v1 does not prune unmanaged
  settings or delete objects.
- Specs must not contain passwords, tokens, session keys, OAuth secrets, or API
  keys. Splunk login still uses the repo credentials file.

## Coverage Map

### Add-ons

- `SA-` and `DA-ESS-` apps are ES framework apps. Do not disable them.
- Technology-specific `TA-` apps are data-source integrations. Deploy them to
  search heads, indexers, heavy forwarders, or universal forwarders according to
  the TA documentation.
- On on-prem clustered indexers, use Distributed Configuration Management to
  generate `Splunk_TA_ForIndexers`, then deploy it through the cluster manager.
- Rebuild and redeploy `Splunk_TA_ForIndexers` after every ES release and after
  adding or updating relevant TAs.
- Splunk Cloud customers work with Splunk Support for indexer-side TA
  installation.

### Indexes

Create indexes on the actual index tier in distributed deployments. The setup
script uses the repository platform helpers so ACS, indexer-cluster bundle
profiles, or direct REST index management are selected from the credentials and
deployment context.

Core ES index checklist:

- `audit_summary`
- `ba_test`
- `cim_modactions`
- `cms_main`
- `endpoint_summary`
- `gia_summary`
- `ioc`
- `notable`
- `notable_summary`
- `risk`
- `sequenced_events`
- `threat_activity`
- `whois`

UEBA and behavioral analytics:

- `ers`
- `ueba_summaries`
- `ubaroute`
- `ueba`

PCI:

- `pci`
- `pci_posture_summary`
- `pci_summary`

Exposure analytics:

- `ea_sources` with recommended short retention such as 30 days
- `ea_discovery` with recommended retention of at least 1 year
- `ea_analytics` with recommended retention of at least 1 year

Note: the current Splunk documentation lists `es_discovery`, while the local
ES 8.5.1 package under `splunk-ta/` defines `ea_discovery`. Follow the shipped
package for this repository unless your deployed package differs.

Exposure Analytics can populate ES Asset and Identity lookups through the
shipped `ea_gen_es_lookup_assets` and `ea_gen_es_lookup_identities` saved
searches. The `exposure_analytics.asset_identity_population` section toggles
those searches and their documented filter/max/field macros. Entity-discovery
source onboarding, validation previews, and enrichment-rule conflict handling
remain handoff actions unless the spec declares concrete saved-search or macro
fields.

Mission Control:

- `mc_aux_incidents`
- `mc_artifacts`
- `mc_investigations`
- `mc_events`
- `mc_incidents_backup`
- `kvcollection_retention_archive`

Detection lifecycle and confidence indexes:

- `dlx_confidence`
- `dlx_kpi`

### Users, Roles, and Capabilities

- `ess_user`: security director/read-focused ES user.
- `ess_analyst`: analyst role for findings and investigations.
- `admin` or `sc_admin`: ES administrator.
- `ess_admin` is a capability container and must not be assigned directly to
  users.
- ES expects an `admin` user to exist for saved-search ownership. If deleting or
  renaming that user, reassign ES knowledge objects first.
- Add custom roles to the App Permissions Manager input
  `app_permissions_manager://enforce_es_permissions`; otherwise ACL updates for
  ES content do not happen.
- Add relevant security data indexes to ES roles. Do not add summary indexes as
  default searched indexes, or searches can loop through summary data.

### CIM and Data Models

- ES uses `Splunk_SA_CIM` plus ES-specific data models.
- Data model acceleration is enforced through
  `dm_accel_settings://<Data_Model>` modular input stanzas.
- Constrain CIM data model searches to relevant indexes for performance.
- Splunk platform 9.0 and higher can run up to three simultaneous
  summarization searches per data model per index.
- Estimate accelerated data model storage using:

  ```text
  accelerated storage per year = daily ES data volume * 3.4
  ```

- Manage summary storage with `indexes.conf tstatsHomePath` and `[volume:]`
  stanzas when summary storage must be separate from hot/warm/cold paths.

### Assets and Identities

- Asset and identity data enriches events at search time.
- Configure lookup table files, lookup definitions, and permissions so the ES
  identity manager can merge data into expanded lookups.
- Asset key fields include `ip`, `mac`, `nt_host`, and `dns`; at least one key
  field is required.
- Recommended asset fields include `owner`, `priority`, business context, and
  location.
- LDAP and cloud-provider builder workflows are automated only when the spec
  supplies explicit `generating_search.search` SPL that writes the lookup with
  `outputlookup`; otherwise the engine returns a handoff with the inputs needed
  to review and declare the generated search.
- Validate with examples such as:

  ```spl
  | makeresults | eval src="1.2.3.4" | `get_asset(src)`
  | makeresults | eval user="alice" | `get_identity4events(user)`
  ```

### Threat Intelligence

ES 8.5 supports native threat intelligence and Threat Intelligence Management
(Cloud). The configuration differs:

- Native threat intelligence stores data in ES KV Store collections and can use
  URL, TAXII 1.0/1.1, STIX/OpenIOC, custom CSV, custom lookups, or Splunk event
  sources.
- Threat Intelligence Management (Cloud) activates cloud-hosted intelligence
  sources, threat lists, and safelist libraries.
- TIM Cloud investigation enrichment is distinct from native KV Store
  intelligence.
- Configure proxy and parser settings for native feeds when internet access or
  field parsing needs adjustment.
- Verify feed health in Threat Intelligence audit and confirm indicators exist
  in Threat artifacts.

### Detections, Findings, and Risk

- ES 8.x uses findings and Mission Control-style analyst workflows.
- Finding-based detections can group findings and intermediate findings around
  common entities and risk criteria.
- Risk-based alerting uses risk events and finding-based detections to reduce
  alert fatigue.
- Preserve MITRE ATT&CK and other annotations in detection metadata.
- Test detections in production mode carefully to estimate alert volume without
  disrupting analyst workflows.
- Use `risk`, `notable`, `notable_summary`, and `threat_activity` indexes to
  smoke-test detection output.

### Integrations

- Mission Control is part of ES 8.x and must remain enabled.
- Analyst queue workload-pool tuning uses `mc_search.conf [aq_sid_caching]
  workload_pool`; define the pool first with the workload management skill.
- RBAC lockdown uses the shipped `lock_unlock_resources://default` modular input
  and is guarded behind explicit `mission_control.rbac_lockdown.apply: true`.
- Configure SOAR apps, Attack Analyzer, UEBA, exposure analytics, and Splunk
  Cloud Connect only when licensed and supported for the deployment.
- Behavioral Analytics forwarding searches are disabled by default in the local
  package and should only be enabled as part of a deliberate BA/UEBA plan.

## Validation Searches

Run these from Search and Reporting or REST as needed:

```spl
| tstats count where index=notable
| tstats count where index=risk
| tstats count from datamodel=Risk.All_Risk
| tstats count from datamodel=Authentication.Authentication
| inputlookup append=T es_notable_events | stats count
| rest splunk_server=local /services/configs/conf-inputs | search title="dm_accel_settings://*"
| rest splunk_server=local /services/apps/local | search title IN ("SplunkEnterpriseSecuritySuite","missioncontrol","Splunk_SA_CIM")
```

## When Not To Automate

- Do not blindly enable all detections. Tune by data source, false-positive
  behavior, urgency, risk modifiers, and SOC process.
- Do not configure asset/identity CSV headers without inspecting source data.
- Do not deploy `Splunk_TA_ForIndexers` if indexers already have conflicting
  app versions.
- Do not assign `ess_admin` directly to users.
- Do not include summary indexes in role defaults.

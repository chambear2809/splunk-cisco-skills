# Deprecated Skill Alias Migration Guide

_Generated from `skills/catalog.yaml` (schema 1, SHA-256 `9f416a41b581fd1e0172ab8c3e77bd4a97555bb46b7515282bf7ee15e047fbc5`) by `skills/shared/scripts/generate_skill_catalog.py`; do not edit manually._

Deprecated names are help-only compatibility aliases. Their setup, validation,
and renderer entrypoints fail closed and name the canonical replacement.

| Deprecated name | Canonical replacement | Migration / omission boundary |
| --- | --- | --- |
| `splunk-kvstore-admin` | `splunk-kvstore-admin-setup` | Use splunk-kvstore-admin-setup for backup, restore, clean, migration, upgrade, maintenance mode, and collection/lookup governance. Legacy SHC member resync is not implemented by the canonical skill; use a reviewed Splunk SHC recovery procedure or another verified live workflow. |
| `splunk-cim-data-model` | `splunk-cim-data-model-setup` | Invoke splunk-cim-data-model-setup once per data model for acceleration, index constraints, eventtype/tag mapping, and tstats validation. Legacy multi-model batches, rebuild/backfill helpers, and broad compliance audits are not forwarded; use explicit per-model review and splunk-data-source-readiness-doctor where applicable. |
| `splunk-knowledge-objects` | `splunk-knowledge-objects-setup` | Use splunk-knowledge-objects-setup for one savedsearch, macro, lookup, eventtype, or tag per invocation, including automatic lookup binding and fixed ACL paths. Legacy bulk inventory/audit, multiple object types, local.meta/SHC bundles, and arbitrary --acl-endpoint reassignment are not forwarded. |
| `splunk-ingest-actions` | `splunk-ingest-actions-setup` | Use splunk-ingest-actions-setup for one ruleset/source invocation: eval, mask, and drop can apply; route-s3 stages only the RFS destination and requires a Splunk Web/rulesets-API handoff. Legacy multi-rule bundles, filesystem/format/compression/batch/partition/upload-error knobs, and btool preview are not forwarded. |
| `splunk-ddaa-archive` | `splunk-ddaa-archive-setup` | Use splunk-ddaa-archive-setup for ACS retention render/apply/status and the Splunk Web restore/disable runbooks. Legacy --max-data-size, dbinspect/archive audit, direct-token transport, and the direct restore shell are not forwarded; restore is now an operator-reviewed Splunk Web runbook. |
| `splunk-secure-gateway` | `splunk-secure-gateway-setup` | Use splunk-secure-gateway-setup for the one live canonical operation, Enterprise app enable/disable, and for only the resolved Enterprise egress check plus endpoint/instance-ID skeleton and MDM/registration operator runbooks. Retired regional endpoint health checks, direct registration, and independent MDM artifacts are not forwarded; Cloud is render/support-only with no local probe or live REST. |
| `splunk-dashboard-studio` | `splunk-dashboard-studio-setup` | Use splunk-dashboard-studio-setup --definition-file with a complete version 2 Studio JSON definition. Repeatable --panel/--panels-file and default-time-range synthesis are not forwarded; canonical wrapper preflight/apply/status replaces generated apply.sh/status.sh and uses the shared tested REST transport. |

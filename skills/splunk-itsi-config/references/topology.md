# Topology Workflow

For users who are new to ITSI, this is usually the safest starter workflow:
they can describe services and dependencies in plain language, and the skill
turns that into services, KPIs, and dependency edges. Start with
`templates/beginner.topology.yaml` and `references/beginner_quickstart.md` before
using exported or advanced ITSI payloads.

The target must already have licensed, healthy ITSI. When packs are referenced,
a compatible live Content Library API and all prerequisite apps must already
exist. This workflow does not install apps or restart Splunk.

The topology workflow combines the existing native and content-pack flows with a
top-level service-tree DSL:

- `bash skills/splunk-itsi-config/scripts/setup.sh --workflow topology --spec <path> --mode lint`
- `bash skills/splunk-itsi-config/scripts/setup.sh --workflow topology --spec <path>`
- `bash skills/splunk-itsi-config/scripts/setup.sh --workflow topology --spec <path> --apply`
- `bash skills/splunk-itsi-config/scripts/validate.sh --workflow topology --spec <path> --completion`
- `bash skills/splunk-itsi-config/scripts/setup.sh --workflow topology --spec <path> --mode prune-plan --output topology-prune-plan.json`
- `bash skills/splunk-itsi-config/scripts/setup.sh --workflow topology --spec <path> --mode cleanup-apply --backup-output cleanup-backup.native.yaml`
- `python3 skills/splunk-itsi-config/scripts/topology_glass_table.py --spec-json <path> --output topology-glass.native.yaml --output-format yaml`

Lint is offline. Normal preview and validation are GET-only. Catalog refresh is
an apply-only opt-in, and apply requires explicit `--apply` approval.

Topology specs can include native sections from `references/native_itsi.md`.
Core service/KPI/dependency fields are typed. Extended ITSI objects such as
teams, entity types, KPI templates, correlation searches, maintenance, backup,
glass tables, deep dives, and home views remain experimental passthroughs unless
`product_coverage.md` says otherwise.

Use `topology_glass_table.py` to generate a starter native `glass_tables` section from `topology.roots`. The generated payload is intentionally a reviewable starter layout, not a replacement for the ITSI visual editor.

## Supported Spec Shape

```yaml
schema_version: 1
metadata:
  template: true

connection:
  base_url: https://splunk.example.com:8089
  session_key_env: SPLUNK_SESSION_KEY
  verify_ssl: true
  platform: enterprise

itsi:
  require_present: true

content_library:
  require_present: true
  refresh_catalog: false

defaults:
  sec_grp: default_itsi_security_group

packs:
  - profile: vmware
    prefix: "Demo - "
    metrics_indexes:
      - vmware-perf-metrics

services:
  - title: Business Platform
    kpis:
      - title: Platform Availability
        threshold_field: availability

topology:
  roots:
    - id: business_platform
      service_ref: Business Platform
      children:
        - id: vmware_cluster
          service:
            title: Demo - VMware Cluster Health
          from_template:
            profile: vmware
            title: ESXi Hypervisor
          children:
            - id: shared_db
              service:
                title: Shared Database
                kpis:
                  - title: Availability
                    threshold_field: availability
        - id: reporting_api
          service:
            title: Reporting API
            kpis:
              - title: Error Rate
                threshold_field: error_rate
          children:
            - ref: shared_db
              kpis:
                - Availability
```

## Node Rules

- A node must declare exactly one of `service_ref` or `service`.
- `service_ref` can be either:
  - a plain live title string, or
  - `{ profile: <pack profile>, title: <logical pack service title> }`
- `service` creates or updates a concrete service instance by title.
- `from_template` is only valid with `service` and must use:
  - `{ profile: <pack profile>, title: <logical pack template title> }`
- Child edges can optionally declare `kpis`; if omitted, the parent depends on all child KPIs.
- Shared services are reused with `{ ref: <id> }`.

## Resolution Rules

- Pack-relative names honor the pack `prefix` when resolving live ITSI services and service templates.
- Preview resolves pack-relative services and service templates from the content-pack `preview` response if they are not live yet.
- Apply and validate use live ITSI objects for service, KPI, and template linkage checks.
- Existing services that declare `from_template` are relinked through the ITSI `service/<_key>/base_service_template` REST endpoint.
- The link route used by this skill has append-only entity-rule semantics. Use
  the ITSI UI for replace or keep-existing choices.

## Validation Rules

- Missing node ids, duplicate ids, missing `ref` targets, self-dependencies, and cycles fail immediately.
- Explicit `kpis` on an edge must match live KPI titles on the child service for apply and validate.
- Normal preview/apply/validate only adds or updates managed services, template links, and dependencies.
- `prune-plan` and guarded `cleanup-apply` reuse the native cleanup model. The topology workflow expands `topology.roots` into desired service titles first, including pack-prefix candidates for `service_ref` nodes, so topology-only services are not reported as unmanaged just because they are absent from the top-level `services` section.
- A generated glass-table payload is a review starter, not evidence that the
  target version accepted the layout or that its searches return data.

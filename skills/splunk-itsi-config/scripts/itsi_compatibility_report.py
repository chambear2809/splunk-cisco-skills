#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


REST_REFERENCE_URL = "https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/leverage-rest-apis/4.21/itsi-rest-api-reference/itsi-rest-api-reference"
REST_SCHEMA_URL = "https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/leverage-rest-apis/4.21/itsi-rest-api-schema/itsi-rest-api-schema"

COMPATIBILITY_ROWS = [
    {
        "area": "Native config upserts",
        "status": "supported",
        "coverage": "team, entity, entity_type, entity_management_policies, entity_management_rules, data_integration_template, service, base_service_template, kpi_base_search, kpi_template, kpi_threshold_template, custom_threshold_windows, notable_event_aggregation_policy, event_management_state, correlation_search, notable_event_email_template, maintenance_calendar, backup_restore, deep_dive, glass_table, home_view, kpi_entity_threshold, refresh_queue_job, sandbox, sandbox_service, sandbox_sync_log, upgrade_readiness_prechecks, summarization, summarization_feedback, user_preference",
        "notes": "Additive preview/apply/validate plus read-only export/inventory/prune-plan. Export and prune-plan skip optional route families that are unavailable on a live host and report warnings. Core entity/service/KPI objects accept typed fields plus top-level schema passthrough and payload; newer route families use the same passthrough model, and deep-dive updates preserve required owner fields.",
    },
    {
        "area": "Special route families",
        "status": "supported",
        "coverage": "event_management_interface, maintenance_services_interface, backup_restore_interface, content_pack_authorship, icon_collection",
        "notes": "The client uses route-specific lookup parameters and write methods; correlation searches, email templates, and NEAPs use Event Management filter_data while event_management_state uses the core object route on tested ITSI 4.21.2 hosts. Generic keyed updates use is_partial_data=1 where the route family supports it.",
    },
    {
        "area": "Custom threshold links",
        "status": "supported",
        "coverage": "custom_threshold_windows/linked_kpis and custom_threshold_windows/<id>/associate_service_kpi",
        "notes": "Links are additive and preserve unmanaged existing service/KPI associations.",
    },
    {
        "area": "Content-pack installation",
        "status": "supported",
        "coverage": "content_pack catalog, preview, install, refresh, app/bootstrap checks",
        "notes": "Install remains conservative: preview first, no destructive resolution defaults, post-install module work is reported as guided handoff.",
    },
    {
        "area": "Drift and readiness reporting",
        "status": "supported",
        "coverage": "field-level validation diffs, KPI/correlation-search SPL preflight warnings, read-only app/object/KV Store inventory, supported-object/alias/notable-action discovery, Event Management counts, maintenance-window status checks, offline native smoke harness",
        "notes": "Diagnostics remain non-destructive. SPL checks are heuristic preflight warnings, not full Splunk parser validation. Inventory uses discovery/count/maintenance helpers when available. The smoke harness uses an in-memory client and exercises cleanup without connecting to Splunk.",
    },
    {
        "area": "Topology visualization",
        "status": "supported",
        "coverage": "starter native glass-table spec generation from topology.roots",
        "notes": "The generator emits a reviewable starter payload; operators should review visual layout before applying it to ITSI.",
    },
    {
        "area": "Operational helper actions",
        "status": "guarded",
        "coverage": "entity retire/restore/retire_retirable, custom threshold stop/disconnect, KPI/entity threshold recommendation application, bulk time-offset shift, notable-event-group update, notable-event action execution, ticket link/unlink, episode export",
        "notes": "Available only through operational_actions and blocked unless allow_operational_action: true is present on each action. Higher-risk calls require second guards such as disconnect_all, retire_all_retirable, allow_episode_field_change, allow_notable_event_action_execute, or allow_ticket_unlink.",
    },
    {
        "area": "Episode records and actions",
        "status": "guarded",
        "coverage": "notable_event_group update, notable_event_actions execution, ticketing, episode_export; notable_event and notable_event_comment remain read/append manual workflows",
        "notes": "Episode interactions are modeled only as explicit operational actions or read-only inventory discovery, not declarative config upserts.",
    },
    {
        "area": "Deletes and destructive transitions",
        "status": "guarded",
        "coverage": "bulk/single DELETE endpoints, content_pack submit/download, icon delete, kpi_entity_threshold delete",
        "notes": "cleanup-apply deletes only supported candidates from a matching current prune-plan after explicit allow_destroy, confirmation text, max_deletes, candidate_ids, and a CLI backup export. Keyless objects and known default/shipped ITSI objects remain manual-review only unless protected system cleanup is explicitly allowed. Content-pack authorship objects, glass-table icons, and KPI entity thresholds require the separate high-risk confirmation plus high_risk_candidate_ids.",
    },
    {
        "area": "Unused or discovery/helper APIs",
        "status": "excluded",
        "coverage": "entity_filter_rule, entity_relationship, entity_relationship_rule, and entity discovery-search helpers",
        "notes": "Supported-object, alias, and notable-action discovery helpers enrich inventory. Splunk documents relationship/filter-rule object types as unused, so they remain outside the managed model.",
    },
]


def render_markdown() -> str:
    lines = [
        "# ITSI Compatibility Report",
        "",
        "This report summarizes the Splunk ITSI REST API areas covered by `splunk-itsi-config` without requiring a live ITSI run.",
        "",
        "Sources:",
        f"- ITSI REST API reference: {REST_REFERENCE_URL}",
        f"- ITSI REST API schema: {REST_SCHEMA_URL}",
        "",
        "| Area | Status | Coverage | Notes |",
        "| --- | --- | --- | --- |",
    ]
    for row in COMPATIBILITY_ROWS:
        lines.append(f"| {row['area']} | {row['status']} | {row['coverage']} | {row['notes']} |")
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the offline ITSI compatibility report.")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--output", help="Optional output path. Defaults to stdout.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.format == "json":
        content = json.dumps(
            {
                "sources": [REST_REFERENCE_URL, REST_SCHEMA_URL],
                "rows": COMPATIBILITY_ROWS,
            },
            indent=2,
            sort_keys=True,
        ) + "\n"
    else:
        content = render_markdown()
    if args.output:
        Path(args.output).write_text(content, encoding="utf-8")
    else:
        print(content, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

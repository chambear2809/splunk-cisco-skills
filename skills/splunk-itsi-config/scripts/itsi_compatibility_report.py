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
        "coverage": "team, entity, entity_type, service, base_service_template, kpi_base_search, kpi_template, kpi_threshold_template, custom_threshold_windows, notable_event_aggregation_policy, event_management_state, correlation_search, notable_event_email_template, maintenance_calendar, backup_restore, deep_dive, glass_table, home_view, kpi_entity_threshold",
        "notes": "Additive preview/apply/validate plus read-only export/inventory/prune-plan. Export and prune-plan skip optional route families that are unavailable on a live host and report warnings. Core entity/service/KPI objects accept typed fields plus top-level schema passthrough and payload; deep-dive updates preserve required owner fields.",
    },
    {
        "area": "Special route families",
        "status": "supported",
        "coverage": "event_management_interface, maintenance_services_interface, backup_restore_interface, content_pack_authorship, icon_collection",
        "notes": "The client uses route-specific lookup parameters and write methods; Event Management lookups use filter_data and creates use the documented data envelope. Generic keyed updates use is_partial_data=1 where the route family supports it.",
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
        "coverage": "field-level validation diffs, KPI/correlation-search SPL preflight warnings, read-only app/object/KV Store inventory, offline native smoke harness",
        "notes": "Diagnostics remain non-destructive. SPL checks are heuristic preflight warnings, not full Splunk parser validation. The smoke harness uses an in-memory client and exercises cleanup without connecting to Splunk.",
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
        "coverage": "entity retire/restore/retire_retirable, custom threshold stop/disconnect, KPI/entity threshold recommendation application, bulk time-offset shift",
        "notes": "Available only through operational_actions and blocked unless allow_operational_action: true is present on each action. Custom-threshold disconnect also requires disconnect_all: true because the documented endpoint has no selective payload; retire_retirable also requires retire_all_retirable: true.",
    },
    {
        "area": "Episode records and actions",
        "status": "excluded",
        "coverage": "notable_event, notable_event_group, notable_event_comment, notable_event_actions, ticket/action execution",
        "notes": "These are operational event records or action execution APIs, not declarative config upserts.",
    },
    {
        "area": "Deletes and destructive transitions",
        "status": "guarded",
        "coverage": "bulk/single DELETE endpoints, content_pack submit/download, icon delete, kpi_entity_threshold delete",
        "notes": "cleanup-apply deletes only supported candidates from a matching current prune-plan after explicit allow_destroy, confirmation text, max_deletes, candidate_ids, and a CLI backup export. Content-pack authorship objects, glass-table icons, and KPI entity thresholds remain manual-review only.",
    },
    {
        "area": "Unused or discovery/helper APIs",
        "status": "excluded",
        "coverage": "entity_filter_rule, entity_relationship, entity_relationship_rule, entity discovery-search helpers, count-only/list-only helpers",
        "notes": "Splunk documents relationship/filter-rule object types as unused; list/count helpers are covered indirectly by lookup and validation paths where needed.",
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

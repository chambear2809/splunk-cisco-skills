#!/usr/bin/env python3
"""Render an offline inventory of the ITSI configuration skill's coverage.

This report is deliberately static. It records implementation evidence and
documented product boundaries; it does not probe a Splunk instance and must not
be interpreted as certification of a particular live ITSI deployment.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REST_REFERENCE_URL = "https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/leverage-rest-apis/5.0/itsi-rest-api-reference/itsi-rest-api-reference"
REST_SCHEMA_URL = "https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/leverage-rest-apis/5.0/itsi-rest-api-schema/itsi-rest-api-schema"
BASELINE_REST_REFERENCE_URL = "https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/leverage-rest-apis/4.21/itsi-rest-api-reference/itsi-rest-api-reference"
BASELINE_REST_SCHEMA_URL = "https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/leverage-rest-apis/4.21/itsi-rest-api-schema/itsi-rest-api-schema"


STATUS_ORDER = (
    "typed-tested",
    "guarded-operational",
    "passthrough-experimental",
    "read-only/handoff",
    "excluded/version-gated",
)

STATUS_TAXONOMY = {
    "typed-tested": (
        "The skill has typed handling or route-aware normalization and local automated test coverage. "
        "This is implementation evidence, not live certification against every ITSI maintenance release."
    ),
    "guarded-operational": (
        "The action is non-idempotent, destructive, or stateful and is exposed only with explicit operator guards."
    ),
    "passthrough-experimental": (
        "The skill can carry an exported/raw payload or optional route, but does not have a complete documented, "
        "versioned schema contract. Production support is not claimed."
    ),
    "read-only/handoff": (
        "The skill inventories, validates, or explains the feature, while mutation remains a UI, product workflow, "
        "or other-skill handoff."
    ),
    "excluded/version-gated": (
        "The feature is out of configuration scope, deprecated, unsupported on some targets, or blocked until the "
        "detected ITSI version and official compatibility contract allow it."
    ),
}


SOURCES = [
    {
        "id": "itsi-5.0-rest-reference",
        "title": "ITSI 5.0 REST API reference",
        "version": "5.0",
        "url": REST_REFERENCE_URL,
    },
    {
        "id": "itsi-5.0-rest-schema",
        "title": "ITSI 5.0 REST API schema",
        "version": "5.0",
        "url": REST_SCHEMA_URL,
    },
    {
        "id": "itsi-5.0-new-features",
        "title": "New features in Splunk IT Service Intelligence 5.0",
        "version": "5.0",
        "url": "https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/release-notes-and-resources/5.0/release-notes/new-features-in-splunk-it-service-intelligence",
    },
    {
        "id": "itsi-5.0-known-issues",
        "title": "Known issues in Splunk IT Service Intelligence 5.0",
        "version": "5.0",
        "url": "https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/release-notes-and-resources/5.0/release-notes/known-issues-in-splunk-it-service-intelligence",
    },
    {
        "id": "itsi-5.0-removed-features",
        "title": "Removed and deprecated features in Splunk IT Service Intelligence 5.0",
        "version": "5.0",
        "url": "https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/release-notes-and-resources/5.0/release-notes/removed-features-in-splunk-it-service-intelligence",
    },
    {
        "id": "itsi-4.21-rest-reference",
        "title": "ITSI 4.21 REST API reference baseline",
        "version": "4.21",
        "url": BASELINE_REST_REFERENCE_URL,
    },
    {
        "id": "itsi-4.21-rest-schema",
        "title": "ITSI 4.21 REST API schema baseline",
        "version": "4.21",
        "url": BASELINE_REST_SCHEMA_URL,
    },
    {
        "id": "itsi-5.0-service-tags",
        "title": "Add tags to a service in ITSI",
        "version": "5.0",
        "url": "https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/visualize-and-assess-service-health/5.0/create-services/add-tags-to-a-service-in-itsi",
    },
    {
        "id": "itsi-5.0-teams",
        "title": "Create teams in ITSI",
        "version": "5.0",
        "url": "https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/administer/5.0/teams/create-teams-in-itsi",
    },
    {
        "id": "itsi-5.0-maintenance",
        "title": "Schedule maintenance downtime in ITSI",
        "version": "5.0",
        "url": "https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/administer/5.0/maintenance-windows/schedule-maintenance-downtime-in-itsi",
    },
    {
        "id": "itsi-5.0-neap-priority",
        "title": "Configure priority for aggregation policies in ITSI",
        "version": "5.0",
        "url": "https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/detect-and-act-on-notable-events/5.0/event-aggregation/configure-priority-for-aggregation-policies-in-itsi",
    },
    {
        "id": "itsi-5.0-enrichment",
        "title": "Overview of enrichment policies in ITSI",
        "version": "5.0",
        "url": "https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/detect-and-act-on-notable-events/5.0/third-party-alerting/overview-of-enrichment-policies-in-itsi",
    },
    {
        "id": "content-packs-2.5-compatibility",
        "title": "Splunk App for Content Packs 2.5 compatibility",
        "version": "2.5",
        "url": "https://help.splunk.com/en/splunk-it-service-intelligence/content-packs-for-itsi-and-ite/splunk-app-for-content-pack/2.5/overview-of-the-splunk-app-for-content-packs",
    },
    {
        "id": "itsi-4.20-predictive-analytics",
        "title": "Set up predictive analytics in ITSI",
        "version": "4.20",
        "url": "https://help.splunk.com/en/splunk-it-service-intelligence/splunk-it-service-intelligence/visualize-and-assess-service-health/4.20/predictive-analytics/set-up-predictive-analytics-in-itsi",
    },
]


COMPATIBILITY_ROWS = [
    {
        "id": "core-service-model",
        "area": "Core service model",
        "status": "typed-tested",
        "versions": ["4.21 baseline", "5.0 documented API"],
        "coverage": (
            "Typed entities, services, embedded KPIs, canonical entity-rule groups, dependency graphs, service-template "
            "links, custom-threshold-window links, preview, apply preflight, validation, and export."
        ),
        "notes": (
            "Teams, entity types/filters, KPI base searches/templates, threshold templates, and window object bodies are "
            "export-shaped passthroughs rather than typed product schemas. Apply still requires live version, capability, "
            "object-reference, and ambiguity preflight; this row is not blanket ITSI 5.0 certification."
        ),
        "source_ids": ["itsi-5.0-rest-reference", "itsi-5.0-rest-schema", "itsi-4.21-rest-reference", "itsi-4.21-rest-schema"],
    },
    {
        "id": "documented-event-management-config",
        "area": "Documented Event Management configuration",
        "status": "passthrough-experimental",
        "versions": ["4.21 baseline", "5.0 documented API"],
        "coverage": (
            "Event management state, notable event aggregation policies, correlation searches, notable event email "
            "templates, route-specific filter_data handling, and managed/default NEAP protection."
        ),
        "notes": (
            "Route selection, title identity, and managed/default NEAP protection have local tests, but advanced policy, "
            "correlation-search, email-template, and state payloads remain export-shaped. Version-specific 5.0 priority "
            "and team-sharing fields are assessed separately and are not implied by this row."
        ),
        "source_ids": ["itsi-5.0-rest-reference", "itsi-5.0-rest-schema", "itsi-4.21-rest-reference"],
    },
    {
        "id": "basic-maintenance-calendar",
        "area": "Basic maintenance calendar",
        "status": "passthrough-experimental",
        "versions": ["4.21 baseline", "5.0 legacy-compatible shape"],
        "coverage": (
            "Documented maintenance_services_interface routing, explicit service/entity targets, one-time start/end "
            "payloads, object-window status reads, inventory, and drift comparison."
        ),
        "notes": (
            "The route and inventory helpers are tested, but the object body is a same-version exported payload, not a "
            "typed maintenance DSL. This does not claim support for 5.0 recurrence, rule targeting, external CIs, outage "
            "ingestion, or ServiceNow synchronization."
        ),
        "source_ids": ["itsi-5.0-rest-reference", "itsi-5.0-rest-schema", "itsi-5.0-maintenance", "itsi-4.21-rest-reference"],
    },
    {
        "id": "inventory-export-and-topology",
        "area": "Inventory, export, drift, and topology",
        "status": "typed-tested",
        "versions": ["4.21 baseline", "5.0 feature-aware inventory"],
        "coverage": (
            "Read-only app/object/KV health inventory, supported-object discovery, export, field-level drift, prune plans, "
            "service-tree materialization from dependencies, and starter glass-table generation."
        ),
        "notes": (
            "SPL checks are heuristic and a generated glass table is a reviewable starter, not proof of search results or "
            "visual correctness on a live target."
        ),
        "source_ids": ["itsi-5.0-rest-reference", "itsi-4.21-rest-reference"],
    },
    {
        "id": "operational-helper-actions",
        "area": "Operational helper actions",
        "status": "guarded-operational",
        "versions": ["Endpoint-dependent"],
        "coverage": (
            "Entity retire/restore, retirable-entity transitions, custom-threshold stop/disconnect, threshold "
            "recommendation apply, time-offset shift, bulk update, templatize, custom content-pack submit/download, "
            "episode actions, ticket links, and episode exports."
        ),
        "notes": (
            "Every mutation requires allow_operational_action and higher-risk actions require a second purpose-specific "
            "guard. These calls are not declarative drift reconciliation."
        ),
        "source_ids": ["itsi-5.0-rest-reference", "itsi-4.21-rest-reference"],
    },
    {
        "id": "cleanup-and-deletes",
        "area": "Cleanup and destructive transitions",
        "status": "guarded-operational",
        "versions": ["Endpoint-dependent"],
        "coverage": (
            "Fresh prune-plan verification, pre-delete export, explicit candidate IDs, maximum delete count, protected "
            "system/content-pack objects, and extra confirmation for icons, custom packs, and entity thresholds."
        ),
        "notes": (
            "The ITSI REST reference warns that POST and DELETE operations are irreversible. Cleanup remains opt-in and "
            "does not make keyless or undocumented objects safe to delete."
        ),
        "source_ids": ["itsi-5.0-rest-reference", "itsi-4.21-rest-reference"],
    },
    {
        "id": "content-pack-lifecycle",
        "area": "Content-pack object lifecycle",
        "status": "guarded-operational",
        "versions": ["ITSI 4.20.x", "ITSI 4.21.x"],
        "coverage": (
            "Catalog/status/detail reads, preview, guarded import/install, conflict-resolution controls, configured-outcome "
            "tasks, and post-import validation."
        ),
        "notes": (
            "The official Splunk App for Content Packs 2.5 matrix lists ITSI 4.20.x and 4.21.x, not 5.0. Block 2.5 "
            "automation on ITSI 5.0 unless a newer official compatibility contract is detected. Installing ITSI itself "
            "is outside this configuration skill."
        ),
        "source_ids": ["content-packs-2.5-compatibility", "itsi-5.0-new-features"],
    },
    {
        "id": "event-iq-summary-records",
        "area": "Event iQ summary and feedback records",
        "status": "read-only/handoff",
        "versions": ["ITSI 5.0"],
        "coverage": "Inventory and validation can inspect summarization and summarization_feedback payload families.",
        "notes": (
            "These are non-idempotent operational records, not ordinary titled declarative configuration: summarization "
            "represents an asynchronous episode-summary request/result, and feedback is per-user append-style data that "
            "can conflict on duplicates. Declarative apply is blocked; operate them only through a separately reviewed "
            "product or operational workflow."
        ),
        "source_ids": ["itsi-5.0-rest-reference", "itsi-5.0-rest-schema", "itsi-5.0-new-features"],
    },
    {
        "id": "undocumented-passthrough-families",
        "area": "Undocumented or internal-looking object families",
        "status": "passthrough-experimental",
        "versions": ["Runtime-discovered only"],
        "coverage": (
            "Entity-management policies/rules, data-integration templates, refresh-queue jobs, sandbox records and sync "
            "logs, upgrade-readiness prechecks, and user preferences."
        ),
        "notes": (
            "These families are not in the official generic ITOA object list. Exported payload passthrough and optional "
            "route probing are implementation conveniences, not a supported CRUD contract. Prefer inventory/handoff and "
            "fail closed when a route is absent."
        ),
        "source_ids": ["itsi-5.0-rest-reference", "itsi-5.0-rest-schema", "itsi-4.21-rest-reference"],
    },
    {
        "id": "visualization-payloads",
        "area": "Deep dives, glass tables, icons, and home views",
        "status": "passthrough-experimental",
        "versions": ["4.21 baseline", "5.0 documented objects"],
        "coverage": "Exported payload round-trip, owner preservation, starter glass-table generation, and icon routing.",
        "notes": (
            "The skill does not provide complete typed schemas for every visualization element and cannot certify visual "
            "layout or panel search results offline. Render and live validation remain required."
        ),
        "source_ids": ["itsi-5.0-rest-reference", "itsi-5.0-rest-schema", "itsi-4.21-rest-schema"],
    },
    {
        "id": "backup-restore-jobs",
        "area": "Backup and restore jobs",
        "status": "passthrough-experimental",
        "versions": ["Route-dependent"],
        "coverage": "backup_restore_interface payload passthrough and object inventory.",
        "notes": (
            "A complete production workflow still needs typed full/partial job creation, status polling, artifact handling, "
            "restore compatibility checks, explicit restore confirmation, and post-restore outcome validation. Generic job "
            "upsert must not be presented as full backup/restore coverage."
        ),
        "source_ids": ["itsi-5.0-rest-reference", "itsi-4.21-rest-reference"],
    },
    {
        "id": "itsi-5.0-neap-priority",
        "area": "ITSI 5.0 NEAP priority",
        "status": "passthrough-experimental",
        "versions": ["ITSI 5.0"],
        "coverage": "An exported 5.0 NEAP payload may carry its priority field through generic payload passthrough.",
        "notes": (
            "Offline lint enforces an integer from 0 through 999 and managed/default policy protection prevents normal "
            "updates. The field still travels in an export-shaped NEAP payload; live 5.0 validation must confirm match "
            "ordering, tied policies, and the immutable default policy."
        ),
        "source_ids": ["itsi-5.0-neap-priority", "itsi-5.0-new-features", "itsi-5.0-rest-reference"],
    },
    {
        "id": "event-iq-detect-and-enrichment",
        "area": "Event iQ Detect and alert enrichment",
        "status": "read-only/handoff",
        "versions": ["ITSI 5.0"],
        "coverage": "Feature awareness, prerequisite/readiness reporting, and UI/product-workflow handoff.",
        "notes": (
            "The official generic REST object lists do not establish a supported CRUD contract for Event iQ Detect "
            "recommendation generation or enrichment policies. Do not invent routes or field names; use documented UI "
            "workflows until an official mutation contract is available."
        ),
        "source_ids": ["itsi-5.0-new-features", "itsi-5.0-enrichment", "itsi-5.0-rest-reference"],
    },
    {
        "id": "predictive-analytics",
        "area": "Predictive analytics",
        "status": "read-only/handoff",
        "versions": ["ITSI 4.20+ product workflow"],
        "coverage": "Prerequisite/model inventory, MLTK and PSC readiness, and training/retraining guidance.",
        "notes": (
            "No documented ITSI REST endpoint provides a complete predictive-model training workflow. Model training and "
            "acceptance remain an ITSI/MLTK UI handoff; the skill must not claim automated predictive configuration."
        ),
        "source_ids": ["itsi-4.20-predictive-analytics", "itsi-5.0-rest-reference"],
    },
    {
        "id": "outcome-validation",
        "area": "Live outcome validation",
        "status": "read-only/handoff",
        "versions": ["All supported targets"],
        "coverage": (
            "Offline drift and heuristic SPL checks, plus read-only hooks for object counts, maintenance status, episodes, "
            "tickets, exports, and health inventory."
        ),
        "notes": (
            "Offline equality does not prove current KPI summaries, health scores, entity matching, successful searches, "
            "episode grouping, maintenance activation, or dashboard results. A live validate phase is required before a "
            "deployment can be called complete."
        ),
        "source_ids": ["itsi-5.0-rest-reference", "itsi-5.0-known-issues"],
    },
    {
        "id": "event-iq-summarization-rules",
        "area": "Event iQ Diagnose summarization rules",
        "status": "passthrough-experimental",
        "versions": ["ITSI 5.0"],
        "coverage": (
            "A dedicated summarization_rules section maps exported payloads to the documented "
            "itoa_interface/summarization_rule object."
        ),
        "notes": (
            "This is ITSI 5.0-only payload passthrough, not a typed Diagnose-rule schema. Rule data sources, attached NEAP "
            "IDs, trigger conditions, and update side effects must come from a reviewed target export and pass live "
            "round-trip validation. The 5.0 reference contains copy/paste errors in examples, so examples alone are "
            "insufficient."
        ),
        "source_ids": ["itsi-5.0-rest-reference", "itsi-5.0-rest-schema", "itsi-5.0-new-features"],
    },
    {
        "id": "itsi-5.0-structured-tags",
        "area": "ITSI 5.0 structured service tags",
        "status": "excluded/version-gated",
        "versions": ["ITSI 5.0"],
        "coverage": "Legacy service_tags payload awareness; no typed 5.0 key-value tag contract.",
        "notes": (
            "ITSI 5.0 stores structured tags in itsi_tags and adds validation, limits, migration, and template-sync behavior. "
            "The current legacy-style passthrough cannot be called full 5.0 tag support."
        ),
        "source_ids": ["itsi-5.0-service-tags", "itsi-5.0-new-features", "itsi-5.0-rest-schema"],
    },
    {
        "id": "itsi-5.0-rbac-sharing",
        "area": "ITSI 5.0 service and episode RBAC",
        "status": "excluded/version-gated",
        "versions": ["ITSI 5.0"],
        "coverage": "Baseline team/sec_grp payloads and role-aware REST errors only.",
        "notes": (
            "Typed owner/shared teams, read-only service sharing, cross-team dependency preflight, NEAP episode sharing, "
            "and the new granular episode action capabilities are not implemented as a complete 5.0 workflow. Duplicate "
            "team names also make title-only identity unsafe."
        ),
        "source_ids": ["itsi-5.0-teams", "itsi-5.0-new-features", "itsi-5.0-rest-reference"],
    },
    {
        "id": "itsi-5.0-advanced-maintenance",
        "area": "ITSI 5.0 advanced maintenance",
        "status": "excluded/version-gated",
        "versions": ["ITSI 5.0"],
        "coverage": "No typed support beyond the basic explicit-object maintenance shape.",
        "notes": (
            "Recurring and multi-day schedules, tag/info/advanced target rules, external CIs, outage imports, and ServiceNow "
            "synchronization require exported/runtime-verified 5.0 schemas or a product UI handoff. A raw recurrence flag "
            "does not establish feature coverage."
        ),
        "source_ids": ["itsi-5.0-maintenance", "itsi-5.0-new-features", "itsi-5.0-rest-reference", "itsi-5.0-rest-schema"],
    },
    {
        "id": "entity-ai-threshold-version-gate",
        "area": "Entity-level AI thresholds",
        "status": "excluded/version-gated",
        "versions": ["ITSI 4.21+ only when endpoint is present"],
        "coverage": "Documented PUT/delete routing and guarded recommendation application.",
        "notes": (
            "The endpoint is version-sensitive. Apply and cleanup must first verify the target supports "
            "kpi_entity_threshold and must never infer support from an older target's generic object behavior."
        ),
        "source_ids": ["itsi-5.0-rest-reference", "itsi-5.0-rest-schema", "itsi-4.21-rest-reference"],
    },
    {
        "id": "metric-anomaly-detection",
        "area": "Metric anomaly detection",
        "status": "excluded/version-gated",
        "versions": ["Deprecated since ITSI 4.20"],
        "coverage": "Inventory and migration guidance only.",
        "notes": (
            "Do not create or advertise new metric anomaly-detection configuration. Splunk directs users toward adaptive "
            "thresholding with outlier detection; existing configurations should be surfaced for migration."
        ),
        "source_ids": ["itsi-5.0-removed-features"],
    },
    {
        "id": "installation-boundary",
        "area": "ITSI installation, upgrade, and package lifecycle",
        "status": "excluded/version-gated",
        "versions": ["All versions"],
        "coverage": "Prerequisite detection and handoff only.",
        "notes": (
            "splunk-itsi-config configures an existing ITSI environment. Installing or upgrading SA-ITOA, installing the "
            "Splunk App for Content Packs, and platform restart orchestration belong to installation/platform workflows."
        ),
        "source_ids": ["itsi-5.0-new-features", "content-packs-2.5-compatibility"],
    },
    {
        "id": "unused-relationship-types",
        "area": "Unused relationship object types",
        "status": "excluded/version-gated",
        "versions": ["4.21", "5.0"],
        "coverage": "entity_relationship and entity_relationship_rule are intentionally unmanaged.",
        "notes": (
            "They can appear in supported-object discovery, but Splunk's schema documents them as unused. Service trees "
            "are modeled through service dependencies instead."
        ),
        "source_ids": ["itsi-5.0-rest-schema", "itsi-4.21-rest-schema"],
    },
]


REPORT_METADATA = {
    "report_version": 2,
    "scope": "Offline implementation coverage for splunk-itsi-config; configuration only, not installation certification.",
    "product_baseline": ["ITSI 4.21", "ITSI 5.0"],
    "report_generation_requires_network": False,
    "report_generation_requires_live_itsi": False,
    "live_preflight_and_validation_required_before_completion": True,
}


def report_payload() -> dict[str, Any]:
    """Return the deterministic, JSON-serializable report payload."""

    return {
        "metadata": REPORT_METADATA,
        "status_taxonomy": {status: STATUS_TAXONOMY[status] for status in STATUS_ORDER},
        "sources": SOURCES,
        "rows": COMPATIBILITY_ROWS,
    }


def _markdown_cell(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        text = ", ".join(str(item) for item in value)
    else:
        text = str(value)
    return " ".join(text.split()).replace("|", "\\|")


def render_markdown() -> str:
    lines = [
        "# ITSI Compatibility Report",
        "",
        REPORT_METADATA["scope"],
        "",
        "This deterministic report requires no network or live ITSI connection. A typed-tested row records local",
        "implementation evidence; it does not certify a live target or remove the need for version/capability preflight.",
        "",
        "## Status taxonomy",
        "",
    ]
    for status in STATUS_ORDER:
        lines.append(f"- **{status}**: {STATUS_TAXONOMY[status]}")

    lines.extend(["", "## Official sources", ""])
    for source in SOURCES:
        lines.append(f"- [{source['title']}]({source['url']}) (`{source['id']}`)")

    lines.extend(
        [
            "",
            "## Coverage inventory",
            "",
            "| Area | Status | Versions | Coverage | Limitations and caveats | Sources |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in COMPATIBILITY_ROWS:
        lines.append(
            "| "
            + " | ".join(
                [
                    _markdown_cell(row["area"]),
                    _markdown_cell(row["status"]),
                    _markdown_cell(row["versions"]),
                    _markdown_cell(row["coverage"]),
                    _markdown_cell(row["notes"]),
                    _markdown_cell(row["source_ids"]),
                ]
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines)


def render_json() -> str:
    return json.dumps(report_payload(), indent=2, sort_keys=True) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the offline ITSI compatibility report.")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--output", help="Optional output path. Defaults to stdout.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    content = render_json() if args.format == "json" else render_markdown()
    if args.output:
        Path(args.output).write_text(content, encoding="utf-8")
    else:
        print(content, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

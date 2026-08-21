---
name: cisco-data-fabric-setup
description: "Use when users need Cisco Data Fabric architecture, feature or product coverage, readiness assessments,
  gap analysis, machine-data activation, federation targets, storage tiering, AI-ready data, or AgenticOps
  data foundation requests. Distinguish this architecture from a single product, package, entitlement, or
  direct API. Research, map, render, doctor, validate, and safely delegate complete Cisco Data Fabric
  adoption plans across Splunk data management, Edge Processor, Ingest Processor, SPL2, Federated Search,
  Machine Data Lake, Data Catalog, Splunk indexes and external stores, AI Toolkit and hosted models, Agent
  Builder, MCP Server, AI Canvas, context, governance, and cross-domain consumers."
compatibility: "Splunk Cloud Platform 10.5.2605: conditional. Follow documented package, entitlement, topology, and customer-managed runtime guardrails; self-managed paths remain on the public 10.4 baseline."
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-08-20"
---

# Cisco Data Fabric Setup

## Prerequisites

| Tool or access | Purpose | Verify |
|---|---|---|
| Bash and Python 3 | Run bundled setup and validation helpers | `bash --version && python3 --version` |
| Required product/platform access | Inspect or configure the selected target | Complete the documented preflight |
| Credential files for live modes | Keep secrets out of chat | Verify paths only |

## Workflow Overview

```text
┌───────────┐   ┌───────────────┐   ┌───────────────┐   ┌─────────────────┐
│ Preflight │ → │ Render/review │ → │ Apply/handoff │ → │ Validate evidence │
└───────────┘   └───────────────┘   └───────────────┘   └─────────────────┘
```

## When to Activate

- Users need Cisco Data Fabric architecture, feature or product coverage, readiness assessments, gap analysis,
  machine-data activation, federation targets, storage tiering, AI-ready data, or AgenticOps data foundation
  requests. Distinguish.
- Preview and review the cisco data fabric setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/cisco-data-fabric-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/cisco-data-fabric-setup/scripts/validate.sh --help
```

Expected output: offline, live, and completion options are displayed when the
skill supports them; help exits without mutation.

## Troubleshooting

| Issue | Cause | Resolution |
|---|---|---|
| Preflight fails | A required tool or access path is missing | Resolve it before rendering or applying |
| Rendered assets are incomplete | Required non-secret inputs are absent | Complete intake and render again |
| Apply is blocked | Review, credentials, or explicit acceptance is missing | Use the documented handoff |
| Validation is incomplete | Live evidence is unavailable | Record the gap and keep completion open |

Treat Cisco Data Fabric as the architecture powered by the Splunk Platform,
not as a single installer, SKU, API, or storage product. Render a complete
coverage packet first, then execute only reviewed child-skill plans whose
public contracts and required non-secret inputs are available.

## Decision Workflow

1. Read `references/feature-matrix.md` for the architecture, feature stages,
   product owners, and boundaries.
2. Read `references/research-ledger.md` before changing availability claims,
   federation targets, model status, or product naming.
3. Collect a non-secret intake from `template.example`.
4. Render and validate the packet.
5. Review `gap-register.md`, `doctor-report.md`, and the product and federation
   matrices before executing delegated renders.
6. Apply or validate state through the owning child skill, never through a
   fabricated Cisco Data Fabric API.

## Architecture Lanes

1. **Data access and management**: collect, inspect, filter, shape, redact,
   route, tier, and monitor machine data with supported Splunk ingestion,
   Edge Processor, Ingest Processor, SPL2, and Ingest Monitoring workflows.
2. **Federation**: route Splunk-to-Splunk and current Splunk Cloud Data
   Management connection/dataset work to `splunk-federated-search-setup`.
   Track Amazon S3, Microsoft Azure, Azure Databricks, Snowflake, DDSS, and
   Amazon Security Lake separately; do not infer equal stage or entitlement.
   Product lifecycle and tenant access are separate fields: for example,
   Amazon S3 federation and Federated Analytics can be GA while still requiring
   sales activation, scan entitlement, a premium add-on, or topology gates.
3. **Storage and catalog**: distinguish the real-time Splunk index, external
   stores, DDSS/DDAA/SmartStore adjacencies, and the alpha Machine Data Lake.
   Built-in Data Catalog and Machine Data Lake remain readiness handoffs until
   stable public administration contracts exist.
4. **Context and governance**: cover schema and catalog metadata, knowledge
   objects, CIM/OCSF, ITSI/business context, RBAC, lineage, audit, human
   approval, and downstream data-readiness evidence.
5. **AI activation and action**: delegate AI Toolkit/PSC/DSDL, hosted-model
   readiness, and MCP Server. Distinguish the available open Cisco Time Series
   Model 1.0 from the GA hosted Cisco Deep Time Series Model integration, keep Agent
   Launchpad at its documented GA boundary with its region, egress, connection,
   and enabled-agent gates, and keep AI Canvas at its CA boundary.
6. **Cross-domain experience**: represent SecOps, ITOps, Engineering/DevOps,
   NetOps, Splunk Enterprise Security, ITSI, Observability Cloud, Cisco Cloud
   Control, AI Canvas, and Cisco product telemetry as consumers or handoffs,
   not as interchangeable Data Fabric components.

## Safe First Command

```bash
bash skills/cisco-data-fabric-setup/scripts/setup.sh --help
```

## Primary Workflow

Render and validate the complete evidence-backed packet:

```bash
bash skills/cisco-data-fabric-setup/scripts/setup.sh \
  --render --validate \
  --spec skills/cisco-data-fabric-setup/template.example \
  --output-dir cisco-data-fabric-rendered
```

Run the gap/readiness doctor:

```bash
bash skills/cisco-data-fabric-setup/scripts/setup.sh \
  --doctor \
  --spec skills/cisco-data-fabric-setup/template.example \
  --output-dir cisco-data-fabric-rendered
```

Preview delegated commands without writing or executing:

```bash
bash skills/cisco-data-fabric-setup/scripts/setup.sh \
  --execute data-management,federation,ai-activation,context-governance \
  --dry-run --json \
  --spec skills/cisco-data-fabric-setup/template.example
```

Execute only reviewed delegated render/doctor commands:

```bash
bash skills/cisco-data-fabric-setup/scripts/setup.sh \
  --execute data-management,ai-activation \
  --accept-execute \
  --spec skills/cisco-data-fabric-setup/template.example \
  --output-dir cisco-data-fabric-rendered
```

## CLI Contract

`setup.sh` supports `--render`, `--validate`, `--doctor`,
`--execute SECTION[,SECTION]`, `--accept-execute`, `--dry-run`, `--json`,
`--spec PATH`, and `--output-dir DIR`.

Delegated sections:

- `data-management`
- `federation`
- `ai-activation`
- `context-governance`

Handoff-only sections, which refuse explicit execution:

- `storage-catalog`
- `experience`

Child commands are render, doctor, or plan operations. Applying their output
requires the child skill's own explicit approval gates. A missing child spec,
tenant URL, MCP URL, entitlement, or public API is reported as a gap rather
than silently converted into a successful apply.

Non-dry-run delegation fails before any child command when `gap-register.json`
contains an `error`, a selected section is handoff-only, or any selected
executable section has no reviewed command. This prevents partial execution
when a later lane is missing required intake.

## Non-Negotiable Boundaries

- Do not claim a direct Cisco Data Fabric management API.
- Do not call Machine Data Lake or its built-in Data Catalog GA; current
  public material identifies Machine Data Lake as alpha.
- Do not collapse store-specific federation stage, region, role, catalog, and
  entitlement requirements into a generic "Federated Search is GA" claim.
- Do not use `activation_required` as a product lifecycle. Record lifecycle in
  `product_stage` and tenant/commercial gates in `access_requirement`.
- Do not create new legacy Amazon S3 federated providers on Splunk Cloud
  10.5; the old provider/index path is deprecated and migrated to the Data
  Management connection/dataset model.
- Do not promote announcement dates to current availability. Cisco Time Series
  Model 1.0 is published as an open Apache-2.0 model and the hosted Cisco Deep
  Time Series Model integration is generally available since AI Toolkit `6.0.0`,
  but they remain separately governed layers and neither one settles the other.
- Do not pair AI Toolkit `6.0.2` with a PSC release below `4.3.4`. The audited
  baseline is `6.0.2` with PSC `4.3.4` on Python `3.13`; PSC `4.3.2` only
  applies back at AI Toolkit `5.7.4`.
- Do not describe Splunk AI Toolkit Agent Launchpad as alpha, private preview,
  or a Fall 2026 GA target. Current AI Toolkit documentation makes it generally
  available since `6.0.0`. Report it as unreachable only when a readiness gate
  actually fails: an unsupported AWS region or a missing region egress IP in
  the stack `apiAllowlistIP`, no supported LLM connection, or no enabled agent.
  Splunk Enterprise reaches it through the Splunk Cloud Connect app rather than
  being unsupported.
- Do not treat Cisco Security Analytics and Logging (SAL) as Splunk Machine
  Data Lake or as an automatically configured federation target.
- For AI Canvas with Splunk, require Cloud Control enablement, Splunk Cloud
  `10.5.2605.3`, current AI Assistant and MCP Server, and
  `mcp_tool_execute`; retain the 100-row-per-card and forbidden-SPL-command
  limitations in the production handoff.
- Never accept raw tokens, passwords, API keys, client secrets, or private
  keys in chat, argv, specs, or rendered artifacts.

## Validation

```bash
bash skills/cisco-data-fabric-setup/scripts/validate.sh \
  --output-dir cisco-data-fabric-rendered

python3 -m py_compile \
  skills/cisco-data-fabric-setup/scripts/render_assets.py
```

Read `reference.md` for the rendered artifact contract and delegated owner
map.

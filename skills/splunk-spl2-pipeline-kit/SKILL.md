---
name: splunk-spl2-pipeline-kit
description: "Use when the user needs SPL2 pipeline authoring, conversion review, compatibility linting, or shared
  templates for Ingest Processor or Edge Processor workflows, including Cisco Data Fabric or telemetry
  pipeline management requests that need reusable SPL2 pipeline logic. Render and lint reusable SPL2
  pipeline templates for Cisco Data Fabric, Splunk Ingest Processor, and Edge Processor, including
  routing, redaction, sampling, lookups, metrics, OCSF, decrypt, stats, custom templates, SPL-to-SPL2
  compatibility, and PCRE2 migration checks."
compatibility: "No direct Splunk Platform runtime dependency. This workflow can be used alongside Splunk Cloud Platform 10.5.2605 through its documented external APIs or handoffs."
metadata:
  splunk_cloud_10_5: "not-applicable"
  compatibility_verified: "2026-07-02"
---

# Splunk SPL2 Pipeline Kit

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

- The user needs SPL2 pipeline authoring, conversion review, compatibility linting, or shared templates for Ingest
  Processor or Edge Processor workflows, including Cisco Data Fabric or telemetry pipeline management requests that
  need.
- Preview and review the splunk spl2 pipeline kit workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-spl2-pipeline-kit/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-spl2-pipeline-kit/scripts/validate.sh --help
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

This skill is the shared SPL2 authoring and validation surface for
`splunk-ingest-processor-setup` and `splunk-edge-processor-setup`. It is
offline-only: it renders starter SPL2, lints pipeline files, and reports
profile compatibility issues without calling Splunk APIs.

For newer Cisco Data Fabric wording, this is the reusable SPL2 authoring route.
Native Observability Metrics Pipeline Management remains a separate UI workflow
covered by `splunk-observability-deep-native-workflows`.

## Agent Behavior

- Use `ingestProcessor` for Splunk-hosted Ingest Processor pipelines.
- Use `edgeProcessor` for Edge Processor pipelines.
- Keep real samples, private keys, HEC tokens, Observability tokens, and lookup
  contents out of chat and rendered files. Render placeholders and file-path
  handoffs only.
- Treat SPL-to-SPL2 conversion as review assistance. Splunk's in-product
  conversion tool remains the authoritative conversion workflow.
- Read `reference.md` before changing supported commands, templates, or lint
  rules.

## Quick Start

Render every template and lint the rendered output:

```bash
bash skills/splunk-spl2-pipeline-kit/scripts/setup.sh --phase all --profile both
```

Lint a user-provided pipeline:

```bash
bash skills/splunk-spl2-pipeline-kit/scripts/setup.sh \
  --phase lint \
  --profile ingestProcessor \
  --pipeline-file pipelines/my_pipeline.spl2
```

`--phase lint` and `--phase validate` require at least one explicit
`--pipeline-file` or previously rendered template under the output directory.
An empty target set is a hard `SPL2-NO-TARGETS` failure, not a pass.
Render/all replaces only an empty directory or one carrying this kit's
ownership marker/legacy README; unrelated nonempty directories are never
recursively deleted.

Run the offline smoke test:

```bash
bash skills/splunk-spl2-pipeline-kit/scripts/smoke_offline.sh
```

## Outputs

The default output directory is `splunk-spl2-pipeline-kit-rendered/`:

- `templates/<profile>/*.spl2` - route, branch, redact, sample, lookup,
  extract, timestamp, JSON/XML, OCSF, decrypt, metrics, stats, S3, and
  compatibility starters where supported.
- `custom-template-app/default/data/spl2/*.spl2` - SPL2 custom template module
  examples using `@template` and runtime profile metadata.
- `lint-report.json` and `lint-report.md`.
- `coverage-report.json`.

## Guardrails

- `logs_to_metrics` requires an `import logs_to_metrics from
  /splunk.ingest.commands` style import and is Ingest Processor-only.
- `decrypt` is Ingest Processor-only and must be treated as a private-key
  lookup handoff. Do not render private-key material.
- `stats` linting rejects `avg()` because Ingest Processor documents
  `sum()/count()` as the supported average pattern. Edge Processor `stats` is
  supported and includes newer state-window behavior on current EP versions.
- `object_to_array()` is deprecated in SPL2 release notes; use
  `json_entries()`.
- Regex guidance is PCRE2-oriented. Prefer named captures like
  `(?P<fieldName>...)`.
- Edge Processor-only and Ingest Processor-only differences are reported in
  the lint output rather than hidden in comments.

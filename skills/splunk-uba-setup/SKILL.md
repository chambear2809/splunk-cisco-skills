---
name: splunk-uba-setup
description: "Use when validating Splunk UBA / UEBA readiness, optional UBA Kafka ingestion app placement, and
  migration guidance to Splunk Enterprise Security Premier UEBA without installing standalone UBA servers."
compatibility: "Splunk Cloud Platform 10.5.2605: conditional. Follow documented package, entitlement, topology, and customer-managed runtime guardrails; self-managed paths remain on the public 10.4 baseline."
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-07-02"
---

# Splunk UBA Setup

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

- Validating Splunk UBA / UEBA readiness, optional UBA Kafka ingestion app placement, and migration guidance to
  Splunk Enterprise Security Premier UEBA without installing standalone UBA servers.
- Preview and review the splunk uba setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-uba-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-uba-setup/scripts/validate.sh --help
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

## Shared add-on completion gate

Whenever this workflow installs, validates, or hands off a UBA support app or
Kafka add-on, follow the
[shared completion gate](../shared/ta_completion_gate.md). Package delivery
alone is not success; validate applicable ingest and consuming views, or record
explicit package evidence that no dashboards ship.

Use this skill when the user asks for **Splunk User Behavior Analytics (UBA)** or
UEBA readiness. Standalone Splunk UBA is end-of-sale and this repo must not
pretend to automate a supported UBA server installation. This skill provides:

- Existing UBA/UEBA support-app and index validation
- Optional Splunk UBA Kafka Ingestion App install (`Splunk-UBA-SA-Kafka`,
  Splunkbase `4147`)
- Explicit end-of-sale/end-of-support reporting
- Migration guidance toward Splunk Enterprise Security Premier UEBA

## Workflow

1. Read this file and `reference.md`.
2. Start with a dry run:

   ```bash
   bash skills/splunk-uba-setup/scripts/setup.sh --dry-run --json
   ```

3. Validate an existing UBA/UEBA integration:

   ```bash
   bash skills/splunk-uba-setup/scripts/validate.sh
   ```

4. Install the UBA Kafka ingestion app only when the deployment still requires
   it and the package is available:

   ```bash
   bash skills/splunk-uba-setup/scripts/setup.sh --install-kafka-app
   ```

5. Use local package install for restricted or pre-downloaded packages:

   ```bash
   bash skills/splunk-uba-setup/scripts/setup.sh \
     --install-kafka-app \
     --source local \
     --file /path/to/splunk-uba-kafka-ingestion-app.tgz
   ```

## Guardrails

- Do not install standalone UBA servers from this skill.
- Do not claim that UBA is newly purchasable. Report the published standalone
  UBA end-of-sale and end-of-support dates.
- Prefer ES Premier UEBA migration guidance for new work.
- Treat Kafka app installation as optional and legacy/readiness-focused.
- Splunkbase app `4147` version `1.4.6` currently advertises `9.2` through
  `10.2` on selected release trains and does not advertise `10.5`. For the
  repository's Splunk Cloud `10.5` target, the shared installer refuses the
  known-incompatible package before mutation. Only
  `--accept-unsupported-platform`, backed by documented vendor approval for
  this exact legacy package and stack, can override the refusal; the override
  is not compatibility certification.

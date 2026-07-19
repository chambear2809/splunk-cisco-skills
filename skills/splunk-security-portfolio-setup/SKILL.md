---
name: splunk-security-portfolio-setup
description: "Use when a user asks for total Splunk security portfolio coverage, product gap analysis, or which Splunk
  security skill handles ES, ES 8.x native SOAR, Security AI Assistant / AI Assistant in Security,
  Federated Analytics, SOAR, Security Essentials, UBA, Attack Analyzer, ARI, Mission Control, PCI,
  InfoSec, CIM, or related security apps. Resolve Splunk security products and associated security
  offerings to the correct local setup skill, install-only path, ES bundled workflow, or manual handoff."
compatibility: "Splunk Cloud Platform 10.5.2605: delegated. Compatibility is determined by the canonical replacement or selected child skill; this compatibility alias or router does not own a runtime or package."
metadata:
  splunk_cloud_10_5: "delegated"
  compatibility_verified: "2026-07-02"
---

# Splunk Security Portfolio Setup

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

- A user asks for total Splunk security portfolio coverage, product gap analysis, or which Splunk security skill
  handles ES, ES 8.x native SOAR, Security AI Assistant / AI Assistant in Security, Federated Analytics, SOAR,
  Security.
- Preview and review the splunk security portfolio setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-security-portfolio-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-security-portfolio-setup/scripts/validate.sh --help
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

When the selected product resolves to a Splunk app, add-on, or dashboard
companion, the owning child workflow must satisfy the
[shared completion gate](../shared/ta_completion_gate.md). An install-only
route is package delivery, not completed setup.

Use this skill as the security portfolio router before choosing a product
specific setup skill.

## What It Does

- Resolves a security product, capability, or related app name against the
  static security coverage catalog.
- Classifies coverage as `first_class`, `existing_skill`, `install_only`,
  `partial`, `bundled_es`, or `manual_gap`.
- Routes first-class products to the product setup skills in this repo.
- Makes associated offerings explicit so a missing product is not hidden by
  generic app install coverage.
- Preserves legacy names such as Phantom, UBA, Mission Control, and ES while
  making current ES 8.x capability names resolve directly.

## Primary Commands

List the coverage matrix:

```bash
bash skills/splunk-security-portfolio-setup/scripts/setup.sh --list-products
```

Resolve a product and preview the route:

```bash
bash skills/splunk-security-portfolio-setup/scripts/setup.sh \
  --product "Splunk Attack Analyzer" \
  --dry-run
```

Execute the resolved setup/install workflow:

```bash
bash skills/splunk-security-portfolio-setup/scripts/setup.sh \
  --product "Splunk Attack Analyzer" \
  --execute
```

Preview the exact routed action without changing Splunk:

```bash
bash skills/splunk-security-portfolio-setup/scripts/setup.sh \
  --product "Splunk Attack Analyzer" \
  --execute \
  --dry-run \
  --json
```

Emit machine-readable coverage:

```bash
bash skills/splunk-security-portfolio-setup/scripts/setup.sh \
  --product "SOAR" \
  --dry-run \
  --json
```

## Agent Behavior

- Prefer the resolved product skill for `first_class` and `existing_skill`
  results.
- Use `splunk-app-install` for `install_only` apps unless a future product
  skill is added.
- Treat `bundled_es` results as Enterprise Security configuration scope.
- For ES 8.x native SOAR, route through ES configuration first, then use
  `splunk-soar-setup` for SOAR runtime, Cloud onboarding, Automation Broker,
  and Splunk-side SOAR apps.
- For Security AI Assistant / AI Assistant in Security, keep the ES
  configuration route authoritative and use `splunk-ai-assistant-setup` only
  for the generic `Splunk_AI_Assistant_Cloud` app workflow.
- For Federated Analytics, route the provider/index setup through
  the dedicated handoff-only `aws_lake` identity in
  `splunk-federated-search-setup`; never substitute generic `aws_s3`. Return
  to ES configuration for ASL, OCSF, ESCU, and detection-readiness handoffs.
- Treat `manual_gap` and `partial` results as handoff/readiness workflows and
  do not imply full automation.

Read `reference.md` when you need the full coverage table and source links.

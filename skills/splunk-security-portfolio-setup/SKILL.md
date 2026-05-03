---
name: splunk-security-portfolio-setup
description: >-
  Resolve Splunk security products and associated security offerings to the
  correct local setup skill, install-only path, ES bundled workflow, or manual
  handoff. Use when a user asks for total Splunk security portfolio coverage,
  product gap analysis, or which Splunk security skill handles ES, SOAR,
  Security Essentials, UBA, Attack Analyzer, ARI, Mission Control, PCI,
  InfoSec, CIM, or related security apps.
---

# Splunk Security Portfolio Setup

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
- Treat `manual_gap` and `partial` results as handoff/readiness workflows and
  do not imply full automation.

Read `reference.md` when you need the full coverage table and source links.

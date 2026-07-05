# Product and feature coverage contract

This repository treats product coverage as a production contract, not a naming
claim. A skill is production-ready only when it has a discoverable owner,
safe-first execution path, validation path, explicit automation boundary, and a
handoff for product surfaces that cannot be safely automated.

## Coverage levels

| Level | Required evidence |
| --- | --- |
| Skill catalog | Every `skills/<name>/SKILL.md` appears in `AGENTS.md`, `CLAUDE.md`, `SKILL_REQUIREMENTS.md`, and `SKILL_UX_CATALOG.md`. |
| App/package routing | Every `skills/shared/app_registry.json` entry routes to an on-disk skill. Numeric Splunkbase entries must be covered by the registry evidence snapshot. |
| Product routers | Parent/router skills must keep a feature or product matrix that names the owner skill or marks the boundary as validation, handoff, unsupported, or UI/operator-owned. |
| Feature families | Child skills must expose `scripts/setup.sh`, `scripts/validate.sh`, `reference.md`, and `agents/openai.yaml`, with strict shell mode on shell entry points. |
| Production safety | Unsupported, private-API, UI-only, topology-unsafe, or entitlement-gated actions must fail closed or render an explicit handoff; they must not report rendering as a successful live apply. |

## Router coverage owners

| Product area | Router/reference |
| --- | --- |
| Cisco product catalog and SCAN routes | `skills/cisco-product-setup/reference.md` |
| Cisco Data Fabric and Cisco/Splunk experience layers | `skills/cisco-data-fabric-setup/reference.md` |
| AppDynamics suite feature families | `skills/splunk-appdynamics-setup/reference.md` |
| Splunk security portfolio | `skills/splunk-security-portfolio-setup/reference.md` |
| Splunk Observability native surfaces | `skills/splunk-observability-deep-native-workflows/reference.md` |
| Splunk supported add-ons and package families | `skills/splunk-supported-addons-setup/reference.md` |

## Audit command

Run this before claiming full product or feature coverage:

```bash
python3 skills/shared/scripts/audit_product_feature_coverage.py
```

Use `--json` for machine-readable output. The audit is intentionally offline:
it checks the tracked contracts and provenance pointers without contacting
Splunk, Cisco, Splunkbase, or tenant APIs.

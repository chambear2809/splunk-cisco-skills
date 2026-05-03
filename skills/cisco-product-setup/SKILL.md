---
name: cisco-product-setup
description: >-
  Resolve a Cisco product name from the SCAN catalog and route installation,
  configuration, and validation through the correct existing setup skill. Use
  when the user asks to set up Splunk for a Cisco product such as ACI, Nexus
  9000, Duo, Meraki, or ThousandEyes.
---

# Cisco Product Setup

Provides one product-aware entrypoint for Cisco setup requests.

## What It Does

- Resolves a product name, alias, or keyword against the packaged SCAN catalog.
- Classifies the product as `automated`, `manual_gap`,
  `unsupported_legacy`, or `unsupported_roadmap`.
- For automated products, delegates to the existing family skill already in
  this repo.
- Uses the relevant family `template.example` file to show which non-secret
  values are required before configuration.

## Primary Commands

List products:

```bash
bash skills/cisco-product-setup/scripts/resolve_product.sh --list-products
```

Preview a product route:

```bash
bash skills/cisco-product-setup/scripts/setup.sh \
  --product "Cisco ACI" \
  --dry-run
```

Run the default workflow:

```bash
bash skills/cisco-product-setup/scripts/setup.sh \
  --product "Cisco ACI" \
  --set name ACI_PROD \
  --set hostname apic1.example.local,apic2.example.local \
  --set username splunk-api \
  --secret-file password /tmp/aci_password
```

## Agent Behavior

The agent must never ask for secrets in chat. Use the routed family skill's
secret-file pattern instead.

For non-secret intake, prefer the family `template.example` that the dry-run
output lists for the resolved product.

## Product Coverage

- Automated products use the existing Cisco family skills already in this repo.
- Active products without a local route return `manual_gap`.
- Deprecated and retired products return `unsupported_legacy`.
- Roadmap products return `unsupported_roadmap`.

## Catalog Files

- `catalog_overrides.json` defines local routing overrides.
- `catalog.json` is the generated runtime catalog.
- `scripts/build_catalog.py --check` verifies that `catalog.json` matches the
  current SCAN package and overrides.
- `scripts/build_catalog.py --write` regenerates `catalog.json` after editing
  `catalog_overrides.json` or refreshing the SCAN package in `splunk-ta/`.
  Without a mode flag the script prints the catalog to stdout instead of
  writing it.

---
name: splunk-cloud-acs-allowlist-setup
description: >-
  Render, preflight, apply, audit, and validate Splunk Cloud Admin Config
  Service (ACS) IP allowlists for all seven ACS features (acs, search-api, hec,
  s2s, search-ui, idm-api, idm-ui) with IPv4 and IPv6, AWS and GCP subnet limit
  enforcement, ACS lock-out protection, drift detection, and optional Terraform
  emission. Use when the user asks to manage ACS IP allowlists, search-api
  allowlist, HEC IP allowlist, s2s subnet allowlist, ACS access subnets,
  acs ip-allowlist, ipallowlists endpoint, ipallowlists-v6, or to audit current
  Splunk Cloud allowlist state.
---

# Splunk Cloud ACS Allowlist Setup

This skill is the explicit, user-driven counterpart to the auto-add behavior
already embedded in
[`skills/shared/lib/acs_helpers.sh`](../../skills/shared/lib/acs_helpers.sh)
(`acs_ensure_search_api_access` adds the operator's own public IP to the
`search-api` allowlist on demand). It manages the full IP allowlist surface for
every ACS feature, IPv4 and IPv6, with safety preflights so users never
accidentally lock themselves out.

## Agent Behavior

Never paste subnet lists, JWT tokens, or stack identifiers into chat. The skill
reads everything it needs from `template.example` plus the project credentials
file (`STACK_TOKEN`, `STACK_TOKEN_USER`, `SPLUNK_CLOUD_STACK`, `ACS_SERVER`).

## Quick Start

Render a plan from your local worksheet, then preview the diff:

```bash
bash skills/splunk-cloud-acs-allowlist-setup/scripts/setup.sh \
  --phase render \
  --features search-api,s2s,hec \
  --search-api-subnets 198.51.100.0/24 \
  --s2s-subnets 198.51.100.0/24,203.0.113.0/24 \
  --hec-subnets 203.0.113.0/24
```

Audit live state, write timestamped JSON snapshots, and emit a diff against the
rendered plan:

```bash
bash skills/splunk-cloud-acs-allowlist-setup/scripts/setup.sh --phase audit
```

Apply the rendered plan (mutates Splunk Cloud allowlists; prints lock-out
warnings before any destructive change):

```bash
bash skills/splunk-cloud-acs-allowlist-setup/scripts/setup.sh --phase apply
```

Wait until ACS reports `Ready` after the apply:

```bash
bash skills/splunk-cloud-acs-allowlist-setup/scripts/setup.sh --phase status
```

Validate that live state matches the plan:

```bash
bash skills/splunk-cloud-acs-allowlist-setup/scripts/validate.sh
```

## What It Renders

Under `splunk-cloud-acs-allowlist-rendered/allowlist/`:

- `plan.json` — desired state per feature, IPv4 and IPv6.
- `preflight.sh` — runs FedRAMP / capability / lock-out / subnet-limit checks
  before any apply.
- `apply-ipv4.sh` and `apply-ipv6.sh` — converge live state to the plan via the
  `acs ip-allowlist` CLI.
- `wait-for-ready.sh` — polls `GET /adminconfig/v2/status` until `Ready`.
- `audit.sh` — re-snapshots and verifies plan vs. live equality.
- `terraform-snippets.tf` — optional `splunk/scp` provider blocks (only when
  `--emit-terraform true`).
- `README.md` — lock-out protection rationale, AWS/GCP subnet-limit math,
  PrivateLink note, FedRAMP carve-out, drift-detection instructions.

## Safety Defaults

- `STRICT_DRIFT=true` (the default) refuses to apply if live state has drifted
  from the previously rendered plan. Pass `--force` to override.
- The first time you add the `acs` feature allowlist, preflight requires the
  operator's current public IP to be present (or `--allow-acs-lockout`), per
  the documented lock-out warning.
- Preflight enforces AWS limits (200 subnets per feature, 230 per allow-list
  group) and GCP limits (200 per feature) up front so apply never gets a 4xx
  surprise.

## References

- [reference.md](reference.md) for full per-feature semantics, default
  behaviors (PCI/HIPAA carve-outs), VPN/bastion patterns, and the IPv6 DELETE
  syntax.
- [template.example](template.example) for the non-secret intake worksheet.

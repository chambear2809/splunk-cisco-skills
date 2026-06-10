---
name: splunk-cloud-acs-admin-setup
description: >-
  Render, preflight, inventory, apply, audit, and validate Splunk Cloud Admin
  Config Service (ACS) administration across IP allowlists, indexes, HEC tokens,
  users, roles, capabilities, app permissions, private connectivity, outbound
  ports, DDSS self-storage, limits.conf settings, maintenance windows, restarts,
  apps, authentication tokens, deployment task status, license state, and
  Observability pairing handoffs. Use when the user asks to manage Splunk Cloud
  ACS, acs admin, ACS indexes, ACS HEC tokens, ACS users and roles, app
  permissions, private connectivity, outbound ports, DDSS, ACS limits,
  maintenance windows, restart current-stack, ACS license state, Observability
  pairing, or to audit Splunk Cloud control-plane configuration.
---

# Splunk Cloud ACS Admin Setup

This skill is the broad Splunk Cloud Admin Config Service workflow. It replaces
the older allowlist-only workflow while preserving the proven IPv4/IPv6
allowlist convergence logic and lock-out protection.

Doc links and examples in this skill default to Cloud stack train
**10.4.2603**. Stacks still on **10.3.2512** can substitute that train in help
URLs; ACS API behavior is unchanged between those trains.

## Agent Behavior

Never paste subnet lists, JWT tokens, stack identifiers, passwords, or HEC token
values into chat. The skill reads stack context from the project credentials
file (`STACK_TOKEN`, `STACK_TOKEN_USER`, `SPLUNK_CLOUD_STACK`, `ACS_SERVER`) and
reads non-secret desired state from CLI flags or a local JSON admin plan.

Prefer `--phase render` or `--phase preflight` first. Only run `--phase apply`
after the operator has reviewed rendered assets. Broad ACS admin mutations are
guarded inside `apply-admin-plan.sh` and require
`ACCEPT_ACS_ADMIN_MUTATION=true`.

## Quick Start

Render a full ACS admin packet and allowlist plan:

```bash
bash skills/splunk-cloud-acs-admin-setup/scripts/setup.sh \
  --phase render \
  --admin-plan-file acs-admin-plan.json \
  --features search-api,s2s,hec \
  --search-api-subnets 198.51.100.0/24 \
  --s2s-subnets 198.51.100.0/24,203.0.113.0/24 \
  --hec-subnets 203.0.113.0/24
```

Render an inventory-only packet for the broader ACS surface:

```bash
bash skills/splunk-cloud-acs-admin-setup/scripts/setup.sh \
  --phase render \
  --modules indexes,hec-tokens,users,roles,capabilities,app-permissions,outbound-ports,ddss,limits,maintenance-windows,restarts,license,observability
```

Audit live allowlist state against the rendered plan:

```bash
bash skills/splunk-cloud-acs-admin-setup/scripts/setup.sh --phase audit
```

Apply reviewed allowlist and admin operations:

```bash
ACCEPT_ACS_ADMIN_MUTATION=true \
bash skills/splunk-cloud-acs-admin-setup/scripts/setup.sh \
  --phase apply \
  --admin-plan-file acs-admin-plan.json
```

Validate rendered assets without live mutation:

```bash
bash skills/splunk-cloud-acs-admin-setup/scripts/validate.sh
```

## What It Renders

Under `splunk-cloud-acs-admin-rendered/acs-admin/`:

- `plan.json` - desired allowlist state plus reviewed ACS admin operations.
- `preflight.sh` - ACS context, command-surface, capability, FedRAMP, lock-out,
  subnet-limit, and drift checks.
- `inventory.sh` - read-only live inventory across the selected ACS modules.
- `apply-ipv4.sh` and `apply-ipv6.sh` - converge IP allowlists.
- `apply-admin-plan.sh` - guarded executor for non-secret admin operations.
- `admin-commands.sh` - review-only command catalog for every planned operation.
- `private-connectivity-rest.sh` - REST helper for ACS private connectivity,
  which is API-only in some ACS CLI releases.
- `wait-for-ready.sh` - polls ACS status until the stack reports `Ready`.
- `audit.sh` - snapshots allowlists and verifies live state matches the plan.
- `terraform-snippets.tf` - optional `splunk/scp` provider snippets for IPv4
  allowlists when `--emit-terraform true`.

## Safety Defaults

- `STRICT_DRIFT=true` refuses allowlist apply if live state drifted from the
  rendered plan. Pass `--force` only after reviewing the diff.
- The `acs` allowlist feature requires operator IP coverage unless
  `--allow-acs-lockout true` is explicitly set.
- User password operations and custom HEC token values are blocked from
  automation because the current ACS CLI takes those values as argv. Use a
  file-backed handoff instead.
- Private connectivity uses ACS REST endpoints (`private-connectivity/eligibility`
  and `private-connectivity/endpoints`) because the local ACS CLI might not
  expose a matching command group.

## References

- [reference.md](reference.md) for the ACS module matrix, admin plan schema,
  compatibility notes, and source links.
- [template.example](template.example) for a non-secret intake worksheet.

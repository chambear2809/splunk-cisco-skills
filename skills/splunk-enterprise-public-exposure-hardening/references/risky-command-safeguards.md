# Risky Command Safeguards Reference

## What it is

Splunk's "Risky Command Safeguards" feature (introduced in 9.0+) marks
SPL commands that can mutate state, run external code, or send data
out of the platform as `is_risky = 1` in `commands.conf`. Splunk Web
then prompts the user before executing them.

## Commands the renderer marks risky

```
collect, delete, dump, map, mcollect, meventcollect, outputcsv,
outputlookup, run, runshellscript, script, sendalert, sendemail,
tscollect
```

## Capability gating

Marking a command risky is not a security boundary by itself — Splunk
Web prompts the user, but a user with the necessary capability can
still execute it. The renderer's `authorize.conf` removes these
capabilities from `role_public_reader`:

- `run_collect` — `collect` / `mcollect` / `meventcollect`
- `run_dump` — `dump`
- `run_sendalert` — `sendalert`, `sendemail`, alert actions
- `run_custom_command` — any custom external command in `commands.conf`
- `delete_by_keyword` — `delete`
- `run_msearch` — `map`
- `run_debug_commands` — internal debug commands

## Bypass advisories

Multiple Splunk Vulnerability Disclosures (SVDs) have documented
bypasses to the Risky Command Safeguard feature. The skill cannot
patch these — upgrade is the only durable mitigation. Capability
gating (above) is the mandatory defense in depth.

Notable bypasses (track upstream):

- SVD-2025-1102 — risky command safeguard bypass via REST `services/streams/search` and character encoding in the path. Fixed in 10.0.1, 9.4.5, 9.3.7, 9.2.9.

The renderer's preflight refuses to apply on Splunk versions below the
SVD floor; this transitively closes most known bypasses.

## How to check the current state

```spl
| rest /services/configs/conf-commands
| search disabled=0
| eval risky=if(is_risky="1", "risky", "ok")
| stats count by risky, command
```

## How to mark additional commands risky

If your apps install third-party SPL commands that touch external
systems, add them to `commands.conf`:

```
[my_external_command]
is_risky = 1
```

The renderer cannot do this for unknown apps — operator-driven.

## Splunk Web prompt UX

When a user runs a risky command, Splunk Web shows a dialog:

> "This search contains a risky command. Are you sure you want to
> proceed?"

The user must explicitly confirm. This is helpful against accidental
misuse but will NOT stop a determined attacker who already has the
capability.

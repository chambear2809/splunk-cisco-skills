# Role and Capability Hardening Reference

The renderer creates a custom `role_public_reader` from zero (it does
NOT inherit from `user`) and explicitly disables every high-risk
capability. This document explains why each capability is on the
removed list.

## High-risk capabilities removed from non-admin roles

| Capability | Risk on a public surface |
|---|---|
| `edit_cmd` | SVD-2026-0302 RCE driver. Lets non-admin users define new external commands. |
| `edit_cmd_internal` | Variant of `edit_cmd` for internal commands. |
| `edit_scripted` | SVD-2025-0702 RCE. Lets non-admin users define scripted inputs. |
| `rest_apps_management` | Mutate app catalog via REST. |
| `rest_apps_install` | Install Splunkbase apps via REST. |
| `rest_properties_set` | Mutate any conf via REST. |
| `run_collect` | `| collect` writes index data; can pollute indexes. |
| `run_mcollect` | Same for metrics. |
| `run_debug_commands` | Internal debug SPL surface. |
| `run_msearch` | Map-search; resource-amplifying. |
| `run_sendalert` | Alert actions can spawn arbitrary scripts. |
| `run_dump` | `| dump` writes to disk. |
| `run_custom_command` | Custom external commands gated here. |
| `embed_report` | Lets the user create unauthenticated dashboard embeds. |
| `change_authentication` | Self-service password change without admin. |
| `delete_by_keyword` | `| delete`; can destroy data. |
| `accelerate_search` | Lets users create accelerated data models. |
| `dispatch_rest_to_indexers` | Search heads forwarding REST to indexers. |
| `import_apps` / `install_apps` | Same risk as `rest_apps_install`. |
| `edit_authentication` | Alter `authentication.conf`. |
| `edit_user` | Self-service user edit. |
| `edit_roles` | Privilege escalation via role edit. |
| `edit_token_*` | Token issuance / revocation. |
| `edit_indexer_*` | Indexer mutation. |
| `edit_input_*` | Input mutation. |
| `edit_modinput_*` | Modular input mutation (RCE class). |
| `edit_search_scheduler` | Schedule searches that the role wouldn't otherwise. |
| `edit_remote_apps_management` | Mutate apps on remote peers. |
| `pattern_detect` | Resource-amplifying ML command. |
| `request_pstacks` | Request internal stack traces (info disclosure). |
| `request_remote_tok` | Issue tokens for remote search heads. |

## Default Splunk roles and their inheritance

- `admin` — full access. Two break-glass admins; rename / disable
  stock `admin`.
- `power` — has `schedule_search`, `edit_user`, `edit_search_scheduler`.
  Should NOT be used for public-facing accounts.
- `user` — has `change_authentication`, `embed_report`,
  `change_own_password`. Inheriting from `user` would import
  capabilities the public reader should not have, hence
  `role_public_reader` is built from zero.
- `can_delete` — has `delete_by_keyword`. Never on a public-facing role.

## Search-time guardrails (per role)

| Setting | Default | Hardened | Note |
|---|---|---|---|
| `srchTimeWin` | unlimited | 86400 (24h) | Max time-range per search |
| `srchDiskQuota` | 100 MB | 100 MB | Per-user disk for search artifacts |
| `srchJobsQuota` | 3 | 3 | Concurrent searches |
| `rtSrchJobsQuota` | 6 | 0 | Real-time searches (turn off) |
| `cumulativeSrchJobsQuota` | 50 | 50 | Across searches |
| `cumulativeRTSrchJobsQuota` | 100 | 0 | Across RT searches |
| `srchMaxTime` | 1800s | 300s | Per-search runtime |
| `srchIndexesAllowed` | `*` | explicit list | Sigma-restricted |
| `srchIndexesDisallowed` | unset | `_audit;_internal;_introspection;_telemetry` | Hide platform indexes |
| `srchIndexesDefault` | `*` | first allowed index | Default search target |

## `[role_admin] never_lockout = disabled`

Splunk ships `role_admin` with `never_lockout = enabled`. This is
unacceptable for any public surface — it means the most-targeted
account has no per-user lockout protection.

The renderer's `authorize.conf` overrides:

```
[role_admin]
never_lockout = disabled
```

After applying, validate via `preflight.sh` (which fails closed if it
sees `never_lockout = enabled`).

## SPL package upload surface

There is no `enable_install_apps` toggle in any released Splunk
version (this is a common misconception). The skill closes the upload
surface in two layers:

- Capability layer (`authorize.conf`): `install_apps`,
  `import_apps`, `rest_apps_install`, `rest_apps_management`, and
  `edit_remote_apps_management` are all `disabled` on
  `role_public_reader`.
- Reverse-proxy layer: the rendered nginx and HAProxy templates deny
  `/services/apps/local`, `/services/apps/appinstall`, and
  `/services/apps/remote` at the edge regardless of authentication
  state.

For SHC deployments, app rollouts go through the deployer's
`shcluster/apps/` directory and the SHC bundle apply — not through
Splunk Web upload.

## Authentication tokens vs SSO

Splunk authentication tokens (JWT) bypass SSO. The public reader role
should NOT have `edit_token_*`. Tokens for automation should be issued
to dedicated service accounts with scoped capabilities.

## Capability-check validation

`validate.sh` and `preflight.sh` query
`/services/authorization/capabilities` and refuse the deployment if any
of the high-risk capabilities are enabled on a non-admin role.

## Related files

- The renderer's `authorize.conf` overlay (in
  `splunk/apps/000_public_exposure_hardening/default/authorize.conf`).
- `commands.conf` marks risky SPL commands as `is_risky = 1` so Splunk
  Web prompts the user — see [risky-command-safeguards.md](risky-command-safeguards.md).
- `default.meta` / `local.meta` enforce the per-app ACL (read-only for
  `role_public_reader`).

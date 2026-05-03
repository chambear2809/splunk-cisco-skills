# Error Catalog and Doctor Matrix

Every check the `--doctor` mode runs, with severity (FAIL / WARN / INFO)
and the exact remediation command the skill renders. Operators see a
prioritized fix list — no raw API errors.

## Doctor Matrix

| #   | Check                                                                                                | Severity    | Fix command rendered                                                                                                      |
| --- | ---------------------------------------------------------------------------------------------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------- |
| 1   | Splunk Cloud Platform version is `9.x+`; Discover-app Configurations UI requires `10.1.2507+`        | FAIL / WARN | `support-tickets/cross-region-pairing.md` template (rendered) for upgrade request                                         |
| 2   | `sc_admin` (SCP) or `admin_all_objects` (SE) role present on the operator user                       | FAIL        | "Assign sc_admin to your operator user" deeplink                                                                          |
| 3   | `edit_tokens_settings` capability present                                                            | FAIL        | `setup.sh --enable-token-auth`                                                                                            |
| 4   | Token authentication enabled (`disabled=false`)                                                      | FAIL        | `setup.sh --enable-token-auth`                                                                                            |
| 5   | Realm <-> region match (using fixed AWS region map)                                                  | FAIL / WARN | "Cross-region pairing requires Splunk Account team — see `<rendered>/support-tickets/cross-region-pairing.md`"            |
| 6   | FedRAMP / GovCloud / GCP gating for UID                                                              | FAIL        | "UID not supported in this region — use Service Account pairing; `setup.sh --apply pairing --pairing.mode service_account`" |
| 7   | Pairing exists for target realm                                                                      | INFO        | (no fix needed; idempotency handles re-apply)                                                                             |
| 8   | Pairing status is `SUCCESS` (poll `GET .../sso-pairing/{id}`)                                        | FAIL        | `setup.sh --apply pairing --resume`                                                                                       |
| 9   | `o11y_access` custom role exists and is assigned                                                     | FAIL        | `setup.sh --apply centralized_rbac`                                                                                       |
| 10  | All UID-mapped users have an `o11y_*` role (precondition for `enable-centralized-rbac`)              | FAIL        | "Assign `o11y_*` role to: user1, user2 ... before `--i-accept-rbac-cutover`"                                              |
| 11  | `read_o11y_content` / `write_o11y_content` capabilities assigned to required roles                   | WARN        | `setup.sh --apply related_content`                                                                                        |
| 12  | Discover Splunk Observability Cloud app installed and accessible                                     | FAIL        | "Splunk Cloud upgrade required: 10.1.2507+" or "Open Apps > Manage Apps" deeplink                                         |
| 13  | LOC realm IPs present in `search-api` allowlist                                                      | FAIL        | `setup.sh --apply log_observer_connect` (delegates to `splunk-cloud-acs-allowlist-setup`)                                 |
| 14  | LOC service-account user + role + workload rule exist                                                | FAIL        | `setup.sh --apply log_observer_connect`                                                                                   |
| 15  | `Splunk_TA_sim` (Splunkbase 5247) installed on search heads                                          | FAIL        | `setup.sh --apply sim_addon`                                                                                              |
| 16  | SIM Add-on account exists, default flag set, `Check Connection` passes                               | FAIL / WARN | `setup.sh --apply sim_addon`                                                                                              |
| 17  | Splunk Cloud Victoria-stack search-head HEC allowlist contains the search-head IP                    | FAIL        | `setup.sh --apply sim_addon` (delegates to `splunk-cloud-acs-allowlist-setup --features hec`)                             |
| 18  | SIM modular inputs are running, no `ANALYTICS_JOB_MTS_LIMIT_HIT` errors, MTS-per-input under 250,000 | FAIL / WARN | "Reduce SignalFlow scope or split modular input — see `<rendered>/sim-addon/mts-sizing.md`"                               |
| 19  | Multi-org default-org set in Discover app Configurations                                             | INFO        | "Open Discover app Configurations > 3-dot menu > Make Default — see `<rendered>/04-discover-app.md`"                      |
| 20  | `uBlock Origin` browser extension warning surface (informational)                                    | INFO        | docs link                                                                                                                 |

## Common Errors and Their Sources

| Error string seen by user                                           | Likely cause                                                       | Fix                                                       |
| ------------------------------------------------------------------- | ------------------------------------------------------------------ | --------------------------------------------------------- |
| `You do not have access to Splunk Observability Cloud`              | Missing `o11y_access` custom role                                  | `setup.sh --apply centralized_rbac`                       |
| `Token authentication is currently disabled`                        | Token auth not enabled on Splunk platform                          | `setup.sh --enable-token-auth`                            |
| `pairingId.status: FAILED`                                          | Realm <-> region mismatch, missing token auth, expired admin token | `setup.sh --doctor` then run the rendered fix             |
| `ANALYTICS_JOB_MTS_LIMIT_HIT`                                       | SignalFlow modular input exceeds 250,000 MTS                       | Split the modular input or narrow the SignalFlow filter   |
| `INVALID_TOKEN`                                                     | O11y access token expired or revoked                               | Mint a fresh token; update the file referenced by --token-file |
| `Connection failed` in Add new connection wizard                    | LOC realm IPs not in `search-api` allowlist                        | `setup.sh --apply log_observer_connect`                   |
| `Permission denied: edit_tokens_settings`                           | Operator lacks the capability                                      | "Assign sc_admin or grant `edit_tokens_settings`"          |
| `Splunk Cloud maintenance window in progress`                       | Cloud maintenance disrupts UID logins (2-5 min)                    | Wait for maintenance window to end                        |
| `int_user1234 appears in my org`                                    | Splunk Support troubleshooting account                             | See `support-tickets/int-user-explanation.md`             |
| Programs with `SAMPLE_` prefix never run                            | SIM Add-on convention; sample programs require manual enable      | Rename via `--render-sim-templates` (skill auto-strips `SAMPLE_`) |

## Support-Ticket Templates

The renderer emits these templates under `<rendered>/support-tickets/`
when the operator's situation requires Splunk Customer Support:

- `cross-region-pairing.md` — requested when realm <-> region mismatch
  is detected.
- `fedramp-il5-readiness.md` — requested when FedRAMP / GovCloud is
  detected and UID is requested.
- `deactivate-local-login.md` — requested when the operator wants
  UID-only enforcement (only Splunk Support can deactivate non-UID local
  login on the O11y org).
- `loc-ip-allowlist-on-fedramp.md` — requested when LOC is requested on
  a FedRAMP stack (ACS allowlist edits go through Support there).
- `int-user-explanation.md` — explainer for `int_*` users that appear
  during Splunk Support troubleshooting.

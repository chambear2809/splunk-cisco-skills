# Splunk Platform Restart Orchestrator Reference

## Source-backed Rules

- Splunk systemd mode maps `splunk start|stop|restart` to `systemctl`; non-root
  users need sudo or polkit for single-node start/stop/restart.
- Systemd-managed indexer cluster and SHC rolling commands do not need sudo.
- REST `/services/server/control/restart` is documented as equivalent to
  `splunk restart`, but live validation showed it can leave a systemd-managed
  host partially shut down. Use it only as explicit fallback.
- Splunk Cloud restart is ACS-owned. Check stack status and restart only when
  `restartRequired=true`; ACS rolling restart is not searchable rolling restart.
- Deployment server changes normally require `splunk reload deploy-server`, not a
  full platform restart.
- App reload avoidance depends on `app.conf [triggers]`; manual `app.conf`
  changes require restart.

## Decision Table

| Target | Preferred action |
| --- | --- |
| Splunk Cloud | ACS restart if `restartRequired=true` |
| Standalone Enterprise, systemd | `sudo -n $SPLUNK_HOME/bin/splunk restart` when privilege is available |
| Standalone Enterprise, non-systemd | `$SPLUNK_HOME/bin/splunk restart` |
| Remote Enterprise with no SSH/service path | Handoff unless explicit REST fallback is requested |
| Indexer cluster bundle | Validate with `validate_bundle check-restart=true`; let bundle apply reload or roll peers |
| Single indexer peer | Splunk Web or `splunk offline` then privileged start |
| SHC eligible restart | `splunk rolling-restart shcluster-members -searchable true` or captain restart endpoint |
| SHC `[shclustering]` config | Simultaneous member restart handoff |
| Deployment server config | `splunk reload deploy-server` |
| Workload management pools/rules | Workload `_reload` endpoints |

## Partial Shutdown Detection

Report a partial shutdown when the restart request was accepted but:

- management API does not come back before timeout,
- old PID is still alive while `8089` is closed,
- systemd reports active but `splunk status` disagrees,
- expected listener ports do not return after management API recovery.

Do not auto-kill or force-start. Render handoff commands only.

## Repo Audit Categories

- `direct_rest_restart`: calls `/services/server/control/restart`.
- `raw_splunk_restart`: rendered or live `splunk restart` calls.
- `reload_only`: `_reload`, `reload deploy-server`, or workload reload paths.
- `cluster_safe`: rolling restart or cluster bundle operations.
- `cloud_acs`: ACS restart/status flows.
- `out_of_scope`: non-Splunk daemons such as SC4S, nginx, Kubernetes rollouts,
  Edge Processor services, or container restart policy.

## Acceptance

Before considering a restart handled:

- the chosen path matches topology,
- no secret appears in command arguments or output,
- management API is reachable again,
- the post-restart condition was validated,
- any expected ports or product-specific probes passed.

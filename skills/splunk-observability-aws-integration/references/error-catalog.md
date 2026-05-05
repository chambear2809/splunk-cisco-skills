# Error Catalog

Known error -> fix-command map for `bash setup.sh`.

| Error | Where it surfaces | Fix command |
|-------|-------------------|-------------|
| `FAIL: refusing direct-secret flag --token` | setup.sh wrapper / aws_integration_api.py | Use `--token-file PATH` (chmod 600) |
| `FAIL: <path> has loose permissions (<mode>)` | secret-file pre-flight | `chmod 600 <path>` (or pass `--allow-loose-token-perms` for short-lived scratch tokens) |
| `FAIL: regions cannot be empty` | render_assets.py spec validation | Enumerate AWS regions explicitly in `regions:` |
| `FAIL: realm us2-gcp is GCP-hosted` | render_assets.py spec validation | Pick an AWS-hosted realm: `us0/us1/us2/us3/au0/eu0/eu1/eu2/jp0/sg0` |
| `FAIL: services.explicit and services.namespace_sync_rules conflict` | render_assets.py spec validation | Pick one (canonical schema makes them mutually exclusive) |
| `FAIL: custom_namespaces.simple_list and custom_namespaces.sync_rules conflict` | render_assets.py spec validation | Pick one (mutually exclusive) |
| `FAIL: metric_streams.managed_externally=true requires use_metric_streams_sync=true` | render_assets.py spec validation | Set both true |
| `FAIL: GovCloud / China regions require authentication.mode=security_token` | render_assets.py spec validation | Set `authentication.mode: security_token`; pass `--aws-access-key-id-file` + `--aws-secret-access-key-file` |
| `FAIL: enableLogsSync (enable_logs_sync) is deprecated and rejected` | render_assets.py spec validation | Hand off logs to `splunk-app-install` (Splunkbase 1876) |
| `FAIL: refusing to write <file>: secret-looking content matched ...` | renderer pre-write secret scan | A spec value or upstream input contains a secret-looking blob; remove or move to a `--token-file` |
| `FAIL: spec file not found` | render_assets.py CLI | Check `--spec PATH` |
| `FAIL: <method> <url> -> HTTP <code>: ...` | aws_integration_api.py | Inspect the body; common: 400 IAM gap, 401 token type wrong, 403 admin scope missing, 404 wrong realm, 429 retry storm |
| `FAIL: secret file is missing or empty: /tmp/...` | _apply_state.read_secret_file | Confirm the file exists and has content; recreate with `bash skills/shared/scripts/write_secret_file.sh` |
| `WARN: ... has loose permissions ... proceeding under --allow-loose-token-perms` | secret-file pre-flight | Acceptable for short-lived scratch tokens only |
| `Validate summary: failures=N` | validate.sh `--summary` | Re-render to fix; the renderer now mirrors the canonical conflict matrix |
| `metricStreamsSyncState=CANCELLATION_FAILED` | discover output | Open Splunk Support; usually requires fresh CFN stack |
| `largeVolume=true` in discover output | discover output | Integration was auto-disabled by the 100k-metric guard; reduce scope or set `enable_check_large_volume: false` |

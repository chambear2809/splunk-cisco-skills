# Galileo Lemonade Instrumentation Reference

| Need | Load |
|---|---|
| Architecture, mode decision, compatibility gaps | `references/architecture.md` |
| OpenInference, Galileo wrapper, Agents, manual logging | `references/application-instrumentation.md` |
| Key-file wrapper and systemd service wiring | `references/runtime-credentials.md` |
| Destination-fingerprinted queue transaction | `references/queue-directory-transaction.md` |
| Dedicated tinyproxy package/file/unit transaction | `references/proxy-bundle-transaction.md` |
| Atomic five-file Collector runtime transaction | `references/runtime-bundle-transaction.md` |
| Canary, counters, API/Console readback, rollback | `references/validation.md` |
| Primary-source inventory and pinned research baseline | `references/sources.md` |

Packaged automation:

- `scripts/render_collector_config.py`: deterministic mode renderer.
- `scripts/validate_collector_config.py`: structural/privacy validation.
- `scripts/send_galileo_canary.py`: content-free agent/tool/LLM OTLP canary.
- `scripts/galileo_readback.py`: bounded, secret-file-backed trace search.
- `scripts/galileo_target_discovery.py`: read-only project/Log stream ID inventory.
- `scripts/galileo_bootstrap_transaction.py`: locked, crash-durable target,
  project-scoped runtime-key, cutover-evidence, finalize, and exact rollback
  state machine. It never accepts a raw secret in argv or environment values.
- `scripts/collector_runtime_wrapper.py`: protected-key collector exec wrapper.
- `scripts/transactional_queue_directory.py`: locked, identity-bound queue
  creation plus fail-safe restore/quarantine helper.
- `scripts/transactional_proxy_bundle.py`: locked package/file/unit apply and
  exact prior-state restore for the dedicated egress proxy.
- `scripts/transactional_runtime_bundle.py`: locked, crash-durable, exact-path
  Collector runtime-file apply and restore helper.
- `scripts/render_tinyproxy_filter.py`: exact-host filter renderer.
- `scripts/render_tinyproxy_evidence.py`: protected binary/config/filter
  provenance renderer for the installed proxy assets.
- `assets/galileo-tinyproxy.conf`: dedicated loopback deny-by-default config.
- `assets/galileo-tinyproxy.service`: dedicated, sandboxed systemd unit pinned
  to the reviewed proxy config path.
- `assets/galileo-tinyproxy.filter.example`: demo-v2 example only; production
  filters must come from the exact endpoint-aware filter renderer.
- `assets/galileo-tinyproxy-evidence.example.json`: non-secret exact proxy
  identity schema; replace every provenance placeholder from installed files.
- `assets/galileo-bootstrap-cutover-evidence.example.json`: fail-closed
  schema-v2 finalize evidence template; every mandatory proof starts `false`.
- `assets/lemonade_openinference_client.py`: caller-side reference client.
- `assets/lemonade_openinference_client.requirements.txt`: reviewed lock-style
  dependency baseline for an isolated application environment.
- `$lemonade-splunk-otel` `collector_evidence.py` and
  `config_change_summary.py`: sanitized counter deltas and value-free review.
- `$lemonade-splunk-otel` `transactional_apply.py`: SHA-gated collector config
  apply and retained-manifest restore after all production gates pass.

Compose with `$lemonade-splunk-otel` for host/collector baseline and
`$galileo-platform-setup` for tenant/project/Log stream lifecycle. Do not use
the personal skill path or copy a standalone collector fragment over the live
configuration.

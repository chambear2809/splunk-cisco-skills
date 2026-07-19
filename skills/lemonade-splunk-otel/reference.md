# Lemonade Splunk OpenTelemetry Reference

| Need | Load |
|---|---|
| Debian/Ryzen AI discovery, upgrade, rollback | `references/debian-runbook.md` |
| macOS Keychain to protected runtime file | `references/keychain.md` |
| Source-to-backend validation ladder | `references/validation.md` |

Packaged assets:

- `assets/lemonade-trixie-backports.sources`: example Debian backports source.
- `assets/splunk-otel-collector.list`: example Splunk collector APT source.
- `scripts/render_collector_config.py`: deterministic full-config renderer.
- `scripts/validate.sh`: strict static validation and optional exact-binary
  production validation.
- `scripts/send_genai_canary.py`: privacy-safe OpenInference/GenAI canary.
- `scripts/splunk_trace_readback.py`: exact-realm and organization-bound Splunk
  APM trace readback with all-segment validation and sanitized evidence.
- `scripts/collector_evidence.py`: sanitized loopback health/counter snapshots
  and before/after deltas for exact v0.156 metrics.
- `scripts/config_change_summary.py`: value-free semantic YAML change paths for
  reviewing normalized generated configs without exposing literal values.
- `scripts/transactional_apply.py`: Linux/root-only schema-v2 transaction with
  current-generation ownership, durable phase recovery, host/package/binary/
  unit provenance, exact systemd-state proof, config-only recovery on runtime
  drift, exact metadata preservation, and resumable restore.
- `scripts/transactional_splunk_token.py`: root-only Splunk ingest-token
  cutover preflight that permits only one environment-file value to change,
  requires private files and protected ancestry, and delegates to the
  crash-durable apply/restore transaction with an exact live-file hash.

Source baseline researched on 2026-07-11: Lemonade v10.10.0. Re-run source
and installed-version discovery before acting because package and telemetry
behavior can change.

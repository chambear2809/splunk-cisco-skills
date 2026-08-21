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

## Reviewed collector binary pin

Exec mode requires both `GALILEO_COLLECTOR_BINARY` and
`GALILEO_COLLECTOR_BINARY_SHA256` in the protected runtime environment.
`collector_runtime_wrapper.py` validates them in
`open_pinned_collector_command` on the line immediately before it reads
`GALILEO_API_KEY_FILE`, so every failure below exits non-zero as
`ERROR: <reason>` while the Galileo key is still unread on disk. `--check` and
`--print-destination-fingerprint` skip the pin entirely; neither execs a
collector, and both remain available on any platform.

Exec mode requires Linux and refuses to run elsewhere with
`ERROR: collector exec requires Linux`. The root-owned path proof below can
only be made on Linux, so the wrapper fails closed rather than executing a
collector with that proof skipped. This is the first gate in
`open_pinned_collector_command`, ahead of every check that follows.

Enforced on `GALILEO_COLLECTOR_BINARY`:

- Non-empty with no leading or trailing whitespace, else
  `GALILEO_COLLECTOR_BINARY is required`.
- Absolute and already canonical: the literal string must equal its
  `os.path.normpath`, so `.`, `..`, and doubled separators are rejected rather
  than normalized.
- Link-free. `Path.resolve(strict=True)` must return the same path, and on
  Linux each component is `lstat`-ed in turn, so a symlink anywhere in the
  chain fails with `reviewed collector binary path must not contain links`.
- Every component from `/` down to the binary must be owned by uid 0 and carry
  neither group-write nor other-write (`mode & 0o022 == 0`). The binary itself
  is held to the same rule. Both checks are implemented for Linux, which is why
  exec mode refuses on other platforms instead of skipping them.
- The first element of the collector command must equal this path exactly, else
  `collector command does not match the reviewed binary`.
- Opened `O_RDONLY|O_NOFOLLOW|O_CLOEXEC` and required to be a regular file with
  `st_nlink == 1`, at least one execute bit, a size of 1 byte to 1 GiB, and the
  same device and inode as an `lstat` of the same path.

Enforced on `GALILEO_COLLECTOR_BINARY_SHA256`:

- Exactly 64 lowercase hex characters (`^[0-9a-f]{64}$`). Uppercase hex, a
  `sha256:` prefix, or a pasted full `sha256sum` line each fail with
  `GALILEO_COLLECTOR_BINARY_SHA256 must be a lowercase SHA-256 digest`.
- Must equal the digest the wrapper computes from the opened descriptor.
- Device, inode, size, and `mtime_ns` are re-checked after hashing; a change
  mid-read fails with `reviewed collector binary changed while being hashed`.

The wrapper then execs the already-open, already-hashed descriptor instead of
re-opening the path, so the verified bytes are the executed bytes. Exec mode
therefore also requires descriptor exec support (`os.execve` accepting an fd,
`os.fexecve`, or Linux `/proc/self/fd`) and refuses to run without it.

Take the digest from the installed file, never from a vendor download page, and
confirm the path chain the wrapper will require:

```bash
sha256sum /usr/bin/otelcol
namei -l /usr/bin/otelcol
```

Then record both values in the protected runtime environment file, replacing
the placeholder with the exact 64-character digest `sha256sum` printed:

```
GALILEO_COLLECTOR_BINARY=/usr/bin/otelcol
GALILEO_COLLECTOR_BINARY_SHA256=REPLACE_WITH_REVIEWED_64_HEX_SHA256
```

`transactional_runtime_bundle.py` narrows this further. The routing environment
must carry both keys, `GALILEO_COLLECTOR_BINARY` must be exactly
`/usr/bin/otelcol`, and both values must match the reviewed
`provenance.collector_binary` and `provenance.collector_binary_sha256` in the
transaction request. A hand-managed environment file may name any path that
satisfies the wrapper's trust rules above; a bundle-installed one may not.

Recompute the digest and re-apply the runtime bundle after every collector
package upgrade. A stale digest fails closed at start, so an unreviewed upgrade
stops the collector instead of silently running unverified bytes.

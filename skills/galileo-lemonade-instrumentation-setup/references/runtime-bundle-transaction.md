# Collector runtime-bundle transaction

## Contents

- [Boundary](#boundary)
- [Staging contract](#staging-contract)
- [Request schema](#request-schema)
- [Apply and restore](#apply-and-restore)
- [Composition with Collector YAML](#composition-with-collector-yaml)
- [Recovery](#recovery)

## Boundary

Use `scripts/transactional_runtime_bundle.py` only for the Collector-side
Galileo runtime bundle. It manages exactly these five roles:

1. `routing_env`
2. `protected_evidence`
3. `runtime_wrapper`
4. `galileo_key`
5. `collector_dropin`

It never installs packages, changes tinyproxy configuration, manages the
dedicated tinyproxy unit, or edits Collector YAML. Keep the tinyproxy
package/config/filter/unit/evidence-generation transaction separate. The
`protected_evidence` role is only the already-rendered identity evidence file
consumed by the Collector wrapper.

The helper is Linux/root/systemd-only and accepts only
`splunk-otel-collector.service`. It pins the machine identity, exact
`splunk-otel-collector` package version, Collector binary identity, protected
baseline Collector config, main unit, unit enablement, and service user/group
before mutation and at every file or service action boundary. The Collector
must initially be active. Unmanaged drop-ins are rejected; after reload the
effective drop-in inventory, `ExecStart`, `Wants`, and `After` must prove the
exact managed wrapper and proxy dependency.

## Staging contract

Create every target parent before apply. Parents, the request, staged files,
state root, and their ancestors must be canonical, nonlinked, root-controlled,
and not group/other-writable. Staged and existing targets must be bounded,
single-link regular files. Declare and satisfy the exact source SHA-256, UID,
GID, and mode. Staged sources must carry no extended attributes, so a hidden
ACL, file capability, or staging-directory security label cannot be copied into
the runtime target. Original target extended attributes are still backed up and
restored exactly.

Create `/etc/splunk-otel-collector/secrets` as
`root:<collector-primary-group>` mode `0750`. This is the only accepted parent
for `galileo_api_key`: root retains control while the Collector identity can
traverse to its service-owned key. A root-only `0700` parent is rejected as
unreadable, and no direct-child key-path alternative is accepted.

The five install metadata contracts are fixed:

| Role | Owner/group | Mode | Reason |
|---|---|---:|---|
| `routing_env` | `root:root` | `0600` | systemd reads it before service privilege drop |
| `protected_evidence` | `root:<collector-primary-group>` | `0440` | wrapper must read it, while the service cannot modify it |
| `runtime_wrapper` | `root:root` | `0755` | service executes a root-controlled wrapper |
| `galileo_key` | `<collector-user>:<collector-primary-group>` | `0600` | wrapper reads the key as the service identity |
| `collector_dropin` | `root:root` | `0644` | standard protected systemd drop-in |

The helper resolves the Collector UID/GID from the loaded unit and rejects an
unreadable `root:root 0400` evidence file. The key staging file must contain
exactly one nonempty UTF-8 line. Never place its value in the request or argv.

Before building the request, discover and review the exact active full
Splunk-only Collector config. Atomically copy those reviewed bytes to the
dedicated baseline `/etc/splunk-otel-collector/lemonade-agent-config.yaml`.
Do not assume the distribution default `/etc/otel/collector/agent_config.yaml`:
for example, the validated Ryzen host used
`/etc/otel/collector/lemonade-agent-config.yaml`. Its parent must be
root-controlled; the baseline must be `root:root` mode `0644`. Require the
target to be absent on first creation, stage in the same directory, then
rename:

```bash
sudo test ! -e /etc/splunk-otel-collector/lemonade-agent-config.yaml
SPLUNK_ONLY_SOURCE=/etc/otel/collector/REVIEWED_ACTIVE_FULL_CONFIG.yaml
sudo install -o root -g root -m 0644 \
  "$SPLUNK_ONLY_SOURCE" \
  /etc/splunk-otel-collector/.lemonade-agent-config.yaml.new
sudo mv -T \
  /etc/splunk-otel-collector/.lemonade-agent-config.yaml.new \
  /etc/splunk-otel-collector/lemonade-agent-config.yaml
sudo sha256sum /etc/splunk-otel-collector/lemonade-agent-config.yaml
```

Review that SHA-256 and put it in `collector_config_sha256`. The helper safely
reopens and hashes this exact config at every action boundary. It compares
bytes, owner, group, mode, and size but deliberately does not bind inode or
mtime: the separate YAML transaction restores the same reviewed baseline by
atomic replacement before runtime restore.

The staged routing environment is strict data, not general systemd syntax. It
must be ASCII `KEY=value` assignments with one final newline, no blank lines,
comments, quotes, escapes, whitespace, duplicates, inline key, `PATH`, loader,
or non-Galileo variables. It contains exactly the seven fixed keys below plus
one complete ID pair (shown) or one complete name pair. The helper derives and
checks the endpoint/origin and destination fingerprint, requires the packaged
loopback proxy, binds key/evidence paths to this request, and requires the queue
to be `/var/lib/splunk-otel-collector/galileo-queue/<fingerprint>`:

```text
GALILEO_OTLP_TRACES_ENDPOINT=https://api.example.invalid/otel/v1/traces
GALILEO_EXPECTED_ORIGIN=https://api.example.invalid
GALILEO_API_KEY_FILE=/etc/splunk-otel-collector/secrets/galileo_api_key
GALILEO_PROXY_URL=http://127.0.0.1:18888
GALILEO_TINYPROXY_EVIDENCE_FILE=/etc/splunk-otel-collector/galileo-evidence.json
GALILEO_DESTINATION_FINGERPRINT=REVIEWED_64_HEX_SHA256
GALILEO_QUEUE_STORAGE_DIRECTORY=/var/lib/splunk-otel-collector/galileo-queue/REVIEWED_64_HEX_SHA256
GALILEO_PROJECT_ID=REVIEWED_PROJECT_ID
GALILEO_LOG_STREAM_ID=REVIEWED_LOG_STREAM_ID
```

## Request schema

Store the request as a root-owned `0600` JSON file. Use absolute canonical
paths. The target allowlists are direct children of
`/etc/splunk-otel-collector` (including its exact `secrets/galileo_api_key`
contract), `/usr/local/libexec`, and
`/etc/systemd/system/<service>.d` with role-appropriate suffixes.

```json
{
  "schema_version": "galileo-runtime-bundle-request/v1",
  "state_root": "/var/lib/galileo-runtime-bundle-transactions",
  "service": {
    "name": "splunk-otel-collector.service",
    "health_url": "http://127.0.0.1:13133/",
    "health_timeout_seconds": 15
  },
  "provenance": {
    "package_name": "splunk-otel-collector",
    "package_version": "REVIEWED_EXACT_VERSION",
    "collector_binary": "/usr/bin/otelcol",
    "collector_binary_sha256": "REVIEWED_64_HEX_SHA256",
    "collector_config_sha256": "REVIEWED_64_HEX_SHA256",
    "unit_fragment_sha256": "REVIEWED_64_HEX_SHA256"
  },
  "files": [
    {
      "role": "routing_env",
      "action": "install",
      "source": "/root/galileo-stage/galileo-routing.env",
      "target": "/etc/splunk-otel-collector/galileo-routing.env",
      "sha256": "REVIEWED_64_HEX_SHA256",
      "uid": 0,
      "gid": 0,
      "mode": "0600"
    },
    {
      "role": "protected_evidence",
      "action": "install",
      "source": "/root/galileo-stage/galileo-evidence.json",
      "target": "/etc/splunk-otel-collector/galileo-evidence.json",
      "sha256": "REVIEWED_64_HEX_SHA256",
      "uid": 0,
      "gid": 1234,
      "mode": "0440"
    },
    {
      "role": "runtime_wrapper",
      "action": "install",
      "source": "/root/galileo-stage/collector_runtime_wrapper.py",
      "target": "/usr/local/libexec/collector_runtime_wrapper.py",
      "sha256": "REVIEWED_64_HEX_SHA256",
      "uid": 0,
      "gid": 0,
      "mode": "0755"
    },
    {
      "role": "galileo_key",
      "action": "install",
      "source": "/root/galileo-stage/galileo_api_key",
      "target": "/etc/splunk-otel-collector/secrets/galileo_api_key",
      "sha256": "REVIEWED_64_HEX_SHA256",
      "uid": 1234,
      "gid": 1234,
      "mode": "0600"
    },
    {
      "role": "collector_dropin",
      "action": "install",
      "source": "/root/galileo-stage/90-galileo-runtime.conf",
      "target": "/etc/systemd/system/splunk-otel-collector.service.d/90-galileo-runtime.conf",
      "sha256": "REVIEWED_64_HEX_SHA256",
      "uid": 0,
      "gid": 0,
      "mode": "0644"
    }
  ]
}
```

Use `{"role": "...", "action": "remove", "target": "/absolute/path"}`
for a role whose desired state is absence. Declare every role exactly once;
mixed install/remove requests are allowed. Source and target paths must be
distinct and outside the state root.

When `collector_dropin` is installed, its staged bytes must be exactly the
following unit, including one final newline and no comments, duplicate
environment entry, extra section, directive, or argument:

```ini
[Unit]
Wants=galileo-tinyproxy.service
After=galileo-tinyproxy.service

[Service]
EnvironmentFile=/etc/splunk-otel-collector/galileo-routing.env
ExecStart=
ExecStart=/usr/bin/python3 /usr/local/libexec/collector_runtime_wrapper.py -- /usr/bin/otelcol --config=/etc/splunk-otel-collector/lemonade-agent-config.yaml
```

The exact `Wants=` and `After=` pair prevents a boot-time race with the
dedicated proxy. The helper derives the environment path from the `routing_env`
target and the wrapper path from the `runtime_wrapper` target, then binds the
absolute Python interpreter, binary, and Collector config to the exact paths
shown. Both referenced roles must be installed in the same bundle. The empty
`ExecStart=` is the one required systemd reset; any additional `ExecStart` is
rejected. Post-reload readback must show this as the one effective command and
the managed file as the only loaded drop-in.

## Apply and restore

Apply only after reviewing all hashes and metadata:

```bash
sudo python3 skills/galileo-lemonade-instrumentation-setup/scripts/transactional_runtime_bundle.py \
  apply --request /root/galileo-stage/runtime-bundle-request.json
```

The sanitized result reports a generation identifier. Its protected restore
manifest is
`<state_root>/generation-<generation>/manifest.json`. The helper writes a
durable intent before each mutation, installs the Collector drop-in last,
runs `daemon-reload`, restarts the Collector, and requires the configured
loopback health endpoint. It keeps the successful generation current so a
second apply cannot overlap it.

Restore with the retained manifest:

```bash
sudo python3 skills/galileo-lemonade-instrumentation-setup/scripts/transactional_runtime_bundle.py \
  restore --manifest /var/lib/galileo-runtime-bundle-transactions/generation-REVIEWED_GENERATION/manifest.json
```

Restore reinstalls exact prior bytes, ownership, mode, and supported extended
attributes. It deletes files that were absent before apply, then performs
`daemon-reload`, restart, and loopback health validation. A completed restore
releases current-generation ownership; retained state remains root-private
evidence until its reviewed retention period ends.

## Composition with Collector YAML

Treat queue, proxy, runtime, and Collector YAML as four independent
transactions with separate state roots, locks, manifests, and
current-generation pointers:

1. Create and hash the protected Splunk-only baseline config described above,
   then apply `transactional_queue_directory.py`.
2. Apply `transactional_proxy_bundle.py`, require its live allow/deny checks,
   and render fresh inode-bound proxy evidence from the installed assets.
3. Apply this runtime bundle. Run the wrapper's `--check` as the Collector
   identity.
4. Validate the rendered Collector YAML statically and with the exact pinned
   Collector binary under the Collector UID/GID and supplementary groups. A
   root invocation is invalid evidence because protected proxy evidence and
   the persistent queue are intentionally bound to the service identity.
5. Apply Collector YAML with `transactional_apply.py`, using
   `/etc/splunk-otel-collector/lemonade-agent-config.yaml` as its live path,
   then validate Splunk plus Galileo readback.

If YAML apply or backend validation fails, restore the Collector YAML
transaction first, then the runtime bundle, then the proxy bundle, and finally
the queue transaction. Do not remove runtime/proxy files while live YAML still
references them, and never remove or rename the queue while the Collector may
hold its database open.

For planned Galileo removal, restore the current Collector YAML manifest to the
exact pinned Splunk-only baseline. Then restore this runtime bundle's current
manifest; the restored config bytes satisfy its provenance even though the YAML
helper used a new inode. Restore the proxy manifest only after the original
Collector command is healthy and Splunk readback remains intact. Restore the
queue manifest last; a nonempty queue is retained as deterministic quarantine
for review. A successful generation owns its `current.json`, so a second apply
cannot replace it without first restoring that current generation.

## Recovery

Apply automatically attempts a complete rollback after file, provenance,
daemon-reload, restart, or health failure. A crash after a side effect but
before its completion checkpoint is safe: explicit restore accepts only the
current generation's desired or original state and repeats the idempotent
action.

If output reports `recovery_required`, reconcile the pinned package, binary,
unit, unmanaged drop-ins, and target drift without deleting transaction state,
then rerun `restore` with the same manifest. Never edit the manifest, journal,
backups, or `current.json`. Output and errors omit file contents, paths,
subprocess output, and credentials.

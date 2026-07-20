# Collector runtime credentials

## Contents

- [Bootstrap-to-runtime key transaction](#bootstrap-to-runtime-key-transaction)
- [Runtime contract](#runtime-contract)
- [Destination changes and queued data](#destination-changes-and-queued-data)

## Bootstrap-to-runtime key transaction

Use `scripts/galileo_bootstrap_transaction.py` when an existing broad key must
create or explicitly adopt the target, create one project-scoped runtime key,
and then be retired safely. This is a resumable transaction, not a one-shot
rotation script:

| Phase | Meaning |
|---|---|
| `PRECHECKED` | The protected bootstrap value matches the exact old key ID and operator user. |
| `TARGET_CREATED` | The exact project and Log stream were created or explicitly adopted and journaled by immutable ID. |
| `RUNTIME_KEY_CREATED` | A one-time project-scoped candidate key was written with `O_EXCL` mode `0600` and proved against live project visibility, `log_data`, and Log-stream lookup. The old key still works. |
| `HOST_CUTOVER_VALIDATED` | Fresh protected evidence is bound to this transaction, target, runtime-key ID, host cutover, Galileo API trace/hierarchy and privacy readback, and unchanged Splunk backend readback. |
| `OLD_KEY_REVOKED` | A separate finalize invocation used a distinct reviewed unscoped revoker, reconciled exact target absence through full inventory, and proved the old key returns 401 Unauthorized from both `GET /v2/current_user` and `GET /v2/token`. |
| `FINALIZED` | The runtime key and exact target were revalidated after old-key revocation. |

The state directory must be an absolute caller-owned `0700` path with trusted
ancestry. The bootstrap file must be an absolute current-user-owned,
single-link regular file with no group/other access and exactly one non-empty
line. The runtime output parent must already exist with trusted ancestry; the
output itself must not exist. Do not put either secret in argv, an environment
variable, shell substitution, logs, or the journal. For a macOS Keychain
source, use `$lemonade-splunk-otel`'s `references/keychain.md` materialization
pattern and keep its cleanup trap active.

Run bootstrap with absolute paths and the exact old key ID. Names are exact and
case-sensitive. To adopt existing objects, add both the immutable ID and its
matching `--adopt-*` flag; omit those flags to create a missing exact name:

```bash
python3 skills/galileo-lemonade-instrumentation-setup/scripts/galileo_bootstrap_transaction.py \
  bootstrap \
  --state-dir "$HOME/.local/state/galileo-lemonade/rotation-001" \
  --api-base "https://api.example.invalid" \
  --bootstrap-key-file "$HOME/.config/galileo/bootstrap.key" \
  --old-key-id "OLD_KEY_UUID" \
  --project-name "lemonade-production" \
  --log-stream-name "ryzen-agent" \
  --runtime-description "lemonade-runtime" \
  --runtime-role annotator \
  --runtime-key-expires-at "YYYY-MM-DDTHH:MM:SSZ" \
  --runtime-key-output "$HOME/.config/galileo/lemonade-runtime.key"
```

For adoption, append `--project-id PROJECT_UUID --adopt-project` and
`--log-stream-id LOG_STREAM_UUID --adopt-log-stream`. The command returns only
the transaction ID, phase, and immutable object/key IDs. It stops at
`RUNTIME_KEY_CREATED`; it cannot revoke the old key.

The default candidate role is `annotator`, but role labels alone do not prove
least privilege. The transaction requires the runtime key to see exactly one
project, that exact project to grant `log_data`, and the exact Log stream to be
readable. If `annotator` fails, retain the journal, run `rollback`, verify exact
cleanup, then start a new state directory and output path before explicitly
trying `editor`. Never change arguments while resuming the same journal.

Every POST has an intent journaled before mutation. A normal rerun reconciles a
unique committed response without duplicating objects. If a transport outcome
is uncertain and the full paginated inventory remains empty, wait through the
tenant's consistency window and rerun the exact bootstrap command with
`--retry-uncertain`. Do not use that flag to bypass duplicate, identity,
creator, or scope errors. Inspect sanitized progress at any time:

```bash
python3 skills/galileo-lemonade-instrumentation-setup/scripts/galileo_bootstrap_transaction.py \
  status --state-dir "$HOME/.local/state/galileo-lemonade/rotation-001"
```

After deploying the runtime file and completing the validation workflow, copy
`assets/galileo-bootstrap-cutover-evidence.example.json` to a new protected
`0600` file. Bind the exact transaction/API/project/Log-stream/runtime-key IDs
and a current timestamp. Change a required proof from `false` to `true` only
when its actual sanitized evidence exists. The mandatory Galileo proof is an
OTLP write plus API trace readback, API hierarchy proof, and privacy assertions.
Console review is not inferred; omit `console_review` or keep
`{"status":"not_observed"}`. A real signed-in browser review belongs in a
separate attested artifact and does not replace API proof.

Record evidence and finalize in separate invocations. Evidence may be at most
one hour old (the default gate is 15 minutes). Finalize requires a surviving,
unscoped revoker credential whose exact key ID differs from both the old and
runtime key IDs. A project-scoped runtime key is not a revoker:

```bash
python3 skills/galileo-lemonade-instrumentation-setup/scripts/galileo_bootstrap_transaction.py \
  record-cutover-evidence \
  --state-dir "$HOME/.local/state/galileo-lemonade/rotation-001" \
  --evidence-file "$HOME/.local/state/galileo-lemonade/rotation-001/cutover-evidence.json" \
  --maximum-age-seconds 900

python3 skills/galileo-lemonade-instrumentation-setup/scripts/galileo_bootstrap_transaction.py \
  finalize \
  --state-dir "$HOME/.local/state/galileo-lemonade/rotation-001" \
  --api-base "https://api.example.invalid" \
  --bootstrap-key-file "$HOME/.config/galileo/bootstrap.key" \
  --revoker-key-file "$HOME/.config/galileo/revoker.key" \
  --revoker-key-id "REVOKER_KEY_UUID" \
  --evidence-file "$HOME/.local/state/galileo-lemonade/rotation-001/cutover-evidence.json" \
  --maximum-age-seconds 900
```

Finalize proves the revoker file against its exact ID and truncated display,
rejects a project-scoped revoker, uses only that distinct credential for
DELETE, follows the complete owner-key inventory until the exact old ID is
absent, and requires direct HTTP 401 responses from the old credential on both
authentication routes. DELETE success, DELETE 401/404 on a retry, or inventory
absence alone never closes the journal. Retries are bounded and remain bound
to the one immutable old-key ID.

Freshness is mandatory before the old-key delete attempt is journaled. If a
crash or uncertain response occurs after that irreversible boundary, resume
`finalize` with the same unchanged evidence file. Resume still verifies its
path, inode, size, hash, timestamp, schema, and exact bindings, but does not let
age alone strand reconciliation after deletion may have started.

### Narrow recovery for the historical self-delete journal

`reconcile-legacy-revocation` exists only for the retired six-field legacy
self-delete intent schema. It cannot create an intent and contains no DELETE
path. It requires `HOST_CUTOVER_VALIDATED`, `delete_started=true`, the exact
recorded evidence hash and old-key ID, and a protected old-key file whose
mtime, ctime, and birth time (when available) all predate `PRECHECKED`. It then
revalidates immutable evidence and the deployed runtime key and requires fresh
HTTP 401 responses from that exact old credential on both `GET
/v2/current_user` and `GET /v2/token` before recording reconciliation and
re-proving the runtime key. The exact old-key ID must be repeated as an
operator confirmation:

```bash
python3 skills/galileo-lemonade-instrumentation-setup/scripts/galileo_bootstrap_transaction.py \
  reconcile-legacy-revocation \
  --state-dir "$HOME/.local/state/galileo-lemonade/rotation-001" \
  --api-base "https://api.example.invalid" \
  --bootstrap-key-file "$HOME/.config/galileo/bootstrap.key" \
  --confirm-old-key-id "OLD_KEY_UUID" \
  --evidence-file "$HOME/.local/state/galileo-lemonade/rotation-001/cutover-evidence.json" \
  --maximum-age-seconds 900
```

Do not use or generalize this recovery command for a fresh transaction, a
legacy intent whose fields differ, a credential file changed after precheck,
or a response other than exact 401 on either route. Fresh finalization always
uses the distinct-revoker policy above.

Before `OLD_KEY_REVOKED`, a separate `rollback` invocation reconciles pending
responses and deletes only exact transaction-owned runtime-key, Log-stream, and
project IDs; adopted objects remain. It also removes the exact owned runtime
output by recorded device/inode. Rollback is forbidden after revocation or
after an old-key delete attempt has started, because an uncertain DELETE may
already have committed:

```bash
python3 skills/galileo-lemonade-instrumentation-setup/scripts/galileo_bootstrap_transaction.py \
  rollback \
  --state-dir "$HOME/.local/state/galileo-lemonade/rotation-001" \
  --api-base "https://api.example.invalid" \
  --bootstrap-key-file "$HOME/.config/galileo/bootstrap.key"
```

After `FINALIZED`, remove the now-revoked bootstrap file through the same
protected credential-cleanup process, retain the sanitized journal/evidence per
policy, and keep only the deployed runtime key. After `ROLLED_BACK`, remove the
retained journal only after its sanitized status and external inventories prove
that every exact owned object is absent.

## Runtime contract

The collector exporter needs `GALILEO_API_KEY`, but repository policy keeps the
secret in a separate file. `scripts/collector_runtime_wrapper.py` validates the
exact HTTPS endpoint, selector pair, file ownership/mode, and the root-owned
`GALILEO_COLLECTOR_BINARY` plus `GALILEO_COLLECTOR_BINARY_SHA256` contract. It
then executes only the verified collector descriptor with the key in its child
environment.

The wrapper pins the exporter to a separately discovered
`GALILEO_EXPECTED_ORIGIN`, derives a destination SHA-256 from the canonical
endpoint plus selector kind/project/Log stream, and requires
`GALILEO_DESTINATION_FINGERPRINT` to match. Obtain the digest safely after
setting the non-secret endpoint/origin/selectors:

```bash
python3 skills/galileo-lemonade-instrumentation-setup/scripts/collector_runtime_wrapper.py \
  --print-destination-fingerprint
```

The command prints only the digest. A different endpoint, selector kind,
project, or Log stream produces a different fingerprint.

Stock Collector v0.156 follows redirects and may copy `Galileo-API-Key`.
The managed exporter therefore has a literal top-level `proxy_url` pointing to
one dedicated IPv4 loopback tinyproxy. This is exporter-local configuration,
not `HTTPS_PROXY`; every ambient proxy and bypass variable is removed from the
collector child, so existing Splunk exporters remain direct.

Tinyproxy must bind only `127.0.0.1`, allow only local clients, allow CONNECT
only to port 443, and use `FilterDefaultDeny Yes`. Its filter is exactly one
anchored POSIX ERE for the lowercase host derived from the separately pinned
Galileo HTTPS endpoint. It contains no wildcard, alternate host, comment, or
second rule. `scripts/render_tinyproxy_filter.py` derives this non-secret rule:

```bash
python3 skills/galileo-lemonade-instrumentation-setup/scripts/render_tinyproxy_filter.py \
  --galileo-traces-endpoint "$GALILEO_OTLP_TRACES_ENDPOINT" \
  --output /tmp/galileo.filter
```

Install the reviewed `assets/galileo-tinyproxy.conf` as
`/etc/tinyproxy/galileo.conf` and the staged filter at the exact path named by
its `Filter` directive. Both and their complete Linux ancestor chains must be
canonical, root-owned, and not group/other-writable. Run a dedicated tinyproxy
unit whose exact command is `/usr/bin/tinyproxy -d -c
/etc/tinyproxy/galileo.conf`; do not reuse a general-purpose proxy. The
packaged config uses a dedicated PID path and syslog. Its unit must create
`RuntimeDirectory=tinyproxy-galileo`; capture and restore the prior unit
enablement/state as part of the runtime transaction.

The packaged unit and config deliberately repeat `User tinyproxy` and `Group
tinyproxy`. Systemd establishes that identity before `ExecStart`; Tinyproxy
1.11.1 detects that it is already non-root and does not attempt another
UID/GID transition. The same identity owns the systemd-created runtime
directory, so Tinyproxy can create its mode-`0600` PID file even with
`ProtectSystem=strict` and `UMask=0077`. `Syslog On` uses a local Unix socket,
which is included in the unit's address-family allowlist; it does not expose
the Galileo key because the proxy sees only an HTTPS CONNECT tunnel and the
collector loads the key in its own child process. The unprivileged port also
means the empty capability sets are intentional. Validate these assumptions on
the target's installed Tinyproxy/systemd versions before enabling the unit.

Install the stricter packaged `assets/galileo-tinyproxy.service` as
root-owned mode `0644` at
`/etc/systemd/system/galileo-tinyproxy.service`. Disable the package's generic
`tinyproxy.service`, verify the packaged unit with `systemd-analyze verify`,
then enable only this dedicated unit. The abbreviated shape below highlights
the required identity and runtime directory; do not replace the packaged
sandboxing directives with this excerpt.

```ini
[Unit]
Description=Dedicated exact-origin proxy for Galileo OTLP
After=network-online.target

[Service]
Type=simple
User=tinyproxy
Group=tinyproxy
RuntimeDirectory=tinyproxy-galileo
RuntimeDirectoryMode=0755
ExecStart=/usr/bin/tinyproxy -d -c /etc/tinyproxy/galileo.conf
Restart=on-failure
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict

[Install]
WantedBy=multi-user.target
```

After installing the exact binary/config/filter, render their protected
identity record:

```bash
sudo python3 skills/galileo-lemonade-instrumentation-setup/scripts/render_tinyproxy_evidence.py \
  --binary /usr/bin/tinyproxy \
  --config /etc/tinyproxy/galileo.conf \
  --filter /etc/tinyproxy/galileo.filter \
  --proxy-url http://127.0.0.1:18888 \
  --galileo-traces-endpoint "$GALILEO_OTLP_TRACES_ENDPOINT" \
  --collector-group "$COLLECTOR_GROUP" \
  --output /etc/splunk-otel-collector/galileo-tinyproxy-evidence.json
```

`COLLECTOR_GROUP` is the exact group from `systemctl show -p Group`; when that
property is empty, resolve the configured service user's primary group with
`id -gn`. Do not guess it. Omitting `--collector-group` creates only a staged
mode-`0440` artifact and is not a production install. The installed evidence is
root-owned, grouped to that collector
service, mode `0440`, single-link bounded JSON outside a service-writable
directory. Mode `0400` is not usable by a non-root collector wrapper; mode
`0444` is too broad. The evidence binds the exact allowed host and proxy URL to
the canonical path, device, inode, size, modification time, owner, mode, and
SHA-256 of all three installed assets. The wrapper compares all fields on every
start and then performs two bounded CONNECT probes without loading or sending
the Galileo key: an unlisted reserved host must return HTTP 403 and the exact
Galileo host must return 2xx. Config/filter/binary replacement, proxy failure,
an overly broad filter, or an origin change therefore fails closed.

The numbered shape below explains the underlying files and manual discovery.
For production apply/restore, use
[`runtime-bundle-transaction.md`](runtime-bundle-transaction.md); its exact
comment-free routing file, absolute Python `ExecStart`, protected baseline
config path, and proxy dependency supersede the illustrative snippets here.
Do not mix the two drop-in shapes.

1. Discover the service identity and exact command first:

   ```bash
   systemctl show -p User -p Group -p ExecStart splunk-otel-collector.service
   systemctl cat splunk-otel-collector.service
   ```

2. Install the key as a single-line regular file owned by that service user,
   mode `0600`. Use root ownership only if the collector actually runs as root.
3. Install and start the dedicated tinyproxy contract above. Confirm the unit's
   `ExecStart`, render the evidence only after the final files are installed,
   and regenerate it after every reviewed tinyproxy package/config/filter
   update. Never edit identity fields by hand.
4. Use `galileo-collector.env.example` only as a placeholder checklist. Render
   the strict routing file required by the runtime transaction with
   the confirmed endpoint, separately confirmed expected origin, literal
   `GALILEO_PROXY_URL`, tinyproxy evidence path, destination fingerprint, queue
   directory, and exactly one complete ID or name pair. Prefer IDs in
   production; never install unresolved placeholders.
5. For the production persistent queue, create a new configured directory whose
   final path component is the destination fingerprint, as the service identity
   and mode `0700`, and include it in disk-capacity monitoring.
   The rendered extension explicitly creates a `compaction` child under this
   directory; verify both paths remain owned by the service identity and mode
   `0700` after the first start. The runtime preflight rejects noncanonical or
   linked paths, untrusted writable ancestors, wrong ownership/modes, linked or
   non-`0600` database files, and less than one GiB free capacity.
6. Install the wrapper in a root-owned executable location such as
   `/usr/local/libexec/collector_runtime_wrapper.py`.
7. Add a systemd drop-in. Copy the original collector executable and every
   argument from `systemctl cat`; the example paths below are not universal:

   ```ini
   [Service]
   EnvironmentFile=/etc/splunk-otel-collector/galileo-routing.env
   ExecStart=
   ExecStart=/usr/bin/python3 /usr/local/libexec/collector_runtime_wrapper.py -- /usr/bin/otelcol --config=/etc/otel/collector/agent_config.yaml
   ```

8. Run the wrapper's `--check` under the service identity. This performs both
   live proxy probes before reading the key. Then daemon-reload,
   validate the staged collector config, and restart transactionally. Never
   enable shell tracing during credential operations.

Treat the queue, proxy bundle, five-file runtime bundle, and Collector YAML as
four coordinated transactions. Capture hashes/ownership/modes, unit
enablement, and the original Collector `ExecStart`; back up every pre-existing
file, record which files are new, and use the transaction helpers' atomic
replacements. Only after the queue exists, the proxy probes pass, and the
wrapper `--check` passes under the service identity should the SHA-gated
Collector YAML transaction apply and restart. If validation, restart, Splunk
readback, or Galileo readback fails, restore YAML, runtime, proxy, and queue in
that order, daemon-reload as performed by the helpers, and prove the original
Splunk path again. Never leave only part of the coordinated cutover installed.

## Destination changes and queued data

Never point an existing queue directory at a new target. Before changing the
endpoint/project/Log stream, stop new sends, prove the old exporter queue is
zero, and retain the old config/environment for rollback. Compute the new
fingerprint and create a new empty directory. If the old queue cannot drain,
keep it quarantined with its old routing environment for an explicit operator
decision; do not copy, rename, or replay its database under the new target.

For syntax-only collector validation, export the reviewed **non-secret**
endpoint/selectors (a systemd EnvironmentFile does this automatically). The
skill's `validate.sh` supplies an internal non-secret dummy API key; it does not
read or expose the production key.

# Dedicated tinyproxy bundle transaction

## Contents

- [Boundary](#boundary)
- [Request contract](#request-contract)
- [Apply and restore](#apply-and-restore)
- [Composition and rollback](#composition-and-rollback)
- [Recovery](#recovery)

## Boundary

Use `scripts/transactional_proxy_bundle.py` only after the reviewed Debian
packages are installed. The helper never installs, upgrades, removes, or
downgrades a package. It verifies the exact `tinyproxy` package version, the
package that owns `/usr/bin/tinyproxy` (normally `tinyproxy-bin`), that owning
package's exact version, the binary SHA-256 and protected identity, and the
unprivileged `tinyproxy:tinyproxy` UID/GID before every mutation boundary.

The transaction manages exactly these files:

1. `/etc/tinyproxy/galileo.filter`
2. `/etc/tinyproxy/galileo.conf`
3. `/etc/systemd/system/galileo-tinyproxy.service`

All three install as `root:root` mode `0644`. Staged sources must have the same
metadata, no extended attributes, a reviewed SHA-256, and canonical protected
ancestry. Existing targets may be absent. Existing bytes, ownership, mode, and
supported extended attributes are backed up and restored exactly.

The helper also captures the exact enabled/disabled and active/inactive state
of `tinyproxy.service` and the enabled/disabled/not-found plus active/inactive
state of `galileo-tinyproxy.service`. Transitional, failed, masked, static,
runtime-only, linked, or ambiguous states fail preflight instead of being
approximated during restore.

## Request contract

Put the request in a canonical root-owned mode-`0600` file. Create all target
parents first as root-controlled directories that are not group/other-writable.
Use a separate root-owned mode-`0700` state root. Do not place either under a
target or staging directory.

```json
{
  "schema_version": "galileo-proxy-bundle-request/v1",
  "state_root": "/var/lib/galileo-proxy-bundle-transactions",
  "provenance": {
    "package_name": "tinyproxy",
    "package_version": "REVIEWED_EXACT_VERSION",
    "binary_package_name": "tinyproxy-bin",
    "binary_package_version": "REVIEWED_EXACT_VERSION",
    "binary_path": "/usr/bin/tinyproxy",
    "binary_sha256": "REVIEWED_64_HEX_SHA256",
    "user": "tinyproxy",
    "group": "tinyproxy"
  },
  "proxy": {
    "listen_host": "127.0.0.1",
    "listen_port": 18888,
    "allowed_connect_host": "api.reviewed-galileo.example",
    "denied_connect_host": "example.invalid",
    "probe_timeout_seconds": 5
  },
  "files": [
    {
      "role": "proxy_filter",
      "source": "/root/galileo-stage/galileo.filter",
      "target": "/etc/tinyproxy/galileo.filter",
      "sha256": "REVIEWED_64_HEX_SHA256",
      "uid": 0,
      "gid": 0,
      "mode": "0644"
    },
    {
      "role": "proxy_config",
      "source": "/root/galileo-stage/galileo.conf",
      "target": "/etc/tinyproxy/galileo.conf",
      "sha256": "REVIEWED_64_HEX_SHA256",
      "uid": 0,
      "gid": 0,
      "mode": "0644"
    },
    {
      "role": "proxy_unit",
      "source": "/root/galileo-stage/galileo-tinyproxy.service",
      "target": "/etc/systemd/system/galileo-tinyproxy.service",
      "sha256": "REVIEWED_64_HEX_SHA256",
      "uid": 0,
      "gid": 0,
      "mode": "0644"
    }
  ]
}
```

The filter must be the one anchored, escaped, lowercase DNS host in
`allowed_connect_host`. The config and unit must satisfy the packaged exact
policy, including loopback-only port 18888, default-deny filtering, the fixed
filter/config paths, unprivileged identity, and sandboxed unit.

## Apply and restore

Review every value and hash, then apply:

```bash
sudo python3 skills/galileo-lemonade-instrumentation-setup/scripts/transactional_proxy_bundle.py \
  apply --request /root/galileo-stage/proxy-bundle-request.json
```

Apply durably journals intent before every file or systemd action. It installs
the filter, config, and unit atomically; runs `systemd-analyze verify`;
daemon-reloads; disables and stops `tinyproxy.service`; enables and restarts
`galileo-tinyproxy.service` (so a previously active process must load the new
generation); and verifies both exact unit states. It then
requires one and only one TCP listener at `127.0.0.1:18888`, an HTTP 403 from a
credential-free CONNECT to `example.invalid:443`, and a 2xx CONNECT response
for the exact reviewed Galileo host. Neither probe loads or transmits a
Galileo credential.

The sanitized result includes a generation. Retain the protected manifest at
`<state_root>/generation-<generation>/manifest.json`, then restore with:

```bash
sudo python3 skills/galileo-lemonade-instrumentation-setup/scripts/transactional_proxy_bundle.py \
  restore --manifest /var/lib/galileo-proxy-bundle-transactions/generation-REVIEWED_GENERATION/manifest.json
```

Restore quiesces the dedicated and generic units, restores/removes all three
files, daemon-reloads, and recreates the exact original enablement and active
state of both units. It does not touch packages.

## Composition and rollback

Use four independent transactions and state roots:

1. Apply `transactional_queue_directory.py` for the destination fingerprint.
2. Apply this proxy bundle and require its live probes.
3. Apply `transactional_runtime_bundle.py` and require the Collector wrapper
   check while the proxy remains healthy.
4. Apply the Collector YAML with `$lemonade-splunk-otel`'s
   `transactional_apply.py`, then run Splunk and Galileo backend readback.

On any cutover or backend-validation failure, reverse dependencies in this
fixed order: restore the Collector YAML first, restore the Collector runtime
bundle second, restore the proxy bundle third, and restore/quarantine the queue
last. Do not stop or restore the proxy while a live Collector YAML/runtime
generation still references it, and do not mutate an open queue.

For planned Galileo removal, first apply and validate Splunk-only Collector
YAML, then restore/remove the Collector runtime bundle, restore this proxy
bundle, and restore the queue transaction last. Prove the original Splunk
backend path after every rollback drill.

## Recovery

An apply failure automatically attempts full restore. A durable intent is
written before each side effect, so a crash after a rename or systemd action
but before its completion checkpoint is recoverable. Rerun `restore` with the
same protected manifest. File recovery accepts only the exact desired or exact
original state; all other drift fails closed.

If output reports `recovery_required`, do not edit or delete the state root,
manifest, backups, journal, or `current.json`. Reconcile only the pinned
package/binary identity or external file drift, then rerun the same restore.
CLI output and errors omit paths, hostnames, file contents, subprocess output,
and credentials.

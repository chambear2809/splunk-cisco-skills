# Debian and Ryzen AI runbook

## Contents

- [Discovery](#discovery)
- [Upgrade transaction](#upgrade-transaction)
- [Collector config transaction](#collector-config-transaction)
- [Native telemetry facts](#native-telemetry-facts)

## Discovery

Run read-only checks first:

```bash
uname -a
. /etc/os-release && printf '%s %s\n' "$ID" "$VERSION_CODENAME"
df -h / /var /tmp
apt-mark showhold
systemctl status lemond.service --no-pager
systemctl cat lemond.service
systemctl is-active lemond.service splunk-otel-collector.service
systemctl is-enabled lemond.service splunk-otel-collector.service
systemctl show -p User -p Group -p ExecStart -p EnvironmentFiles \
  lemond.service splunk-otel-collector.service
systemctl status splunk-otel-collector.service --no-pager
systemctl cat splunk-otel-collector.service
ss -lntp
apt-cache policy lemonade-server splunk-otel-collector
dpkg-query -W -f='${Package} ${Version}\n' lemonade-server splunk-otel-collector
/usr/bin/otelcol --version
```

Locate the active Lemonade config and collector `--config` path from the unit,
not from a remembered default. Probe the announced health URL and `/live`
first; use `/api/v1/health` or `/v1/health` only when the installed release
documents one of those routes. Confirm the OpenAI-compatible API base from the
live service before choosing it.

After discovering each real config path, capture only metadata and hashes (do
not print secret environment files):

```bash
stat -c '%n %U:%G %a %s %y' "$LEMONADE_CONFIG" "$COLLECTOR_CONFIG"
sha256sum "$LEMONADE_CONFIG" "$COLLECTOR_CONFIG"
apt-get --simulate install --only-upgrade lemonade-server
```

## Upgrade transaction

1. Record package versions, APT origins, holds, service state, config paths,
   ownership, modes, and checksums.
2. Copy configs to a timestamped root-only backup directory.
3. Refresh package metadata and inspect the candidate without installing it.
4. Install only the intended Lemonade package and capture package-manager
   output. Do not perform an unrelated full distribution upgrade.
5. Verify version, service health, model availability, and one real completion.
6. If validation fails, restore configs and downgrade to the recorded package
   version while preserving the package cache or repository source needed for
   rollback.

Before upgrading, prove that `apt-cache policy` or a retained `.deb` can supply
the exact recorded version. The rollback form is:

```bash
apt-get install --allow-downgrades "lemonade-server=$PREVIOUS_VERSION"
systemctl restart lemond.service
curl --fail --max-time 5 "$LEMONADE_ORIGIN/live"
```

Never assume the example port; derive `LEMONADE_ORIGIN` from the active service.
On v10.10, configure telemetry through `lemonade config set`, verify a sanitized
`/internal/config` snapshot, and force a bounded flush with:

```bash
curl --fail --max-time 10 --request POST \
  "$LEMONADE_ORIGIN/internal/telemetry/flush"
```

The packaged backports source is an example only. Confirm the host's Debian
codename and the vendor's current installation guidance before using it.

## Collector config transaction

After static and exact-binary validation, use `scripts/transactional_apply.py`
for the collector config rather than an unguarded copy/restart. Pass the exact
staged SHA-256, exact collector binary path and SHA-256, and the collector's
discovered loopback health endpoint. Keep the returned `0600` schema-v2
manifest, journal, metadata snapshot, and backup inside its `0700` state
directory. The state root also contains a `0600` `current.json` generation
pointer. Do not delete or edit these files while a transaction is current.
Schema-v1 manifests do not contain the required ownership and provenance
evidence and are intentionally rejected by the v2 helper.

The helper preserves the existing live bytes, ownership, mode, ACL, SELinux
label, extended attributes, and prior active/enabled service state. Apply and
explicit restore require `systemctl show` to resolve the exact requested unit
ID with `LoadState=loaded`. Production support is deliberately limited to
`ActiveState=active|inactive` and `UnitFileState=enabled|disabled`; the active
state must agree with `systemctl is-active`. Reject `failed`, transitional,
`enabled-runtime`, static, alias, linked, indirect, or masked units instead of
collapsing them to booleans. The manifest records only a sanitized machine-ID
hash, package versions, binary path/device/inode/hash, and a hash of systemd
unit/drop-in paths and bytes; it never records unit or environment contents.

Apply revalidates exact package versions, binary identity/hash, unit
fingerprint, and service state before config install, around restart and
health, and before its terminal checkpoint. If runtime provenance changes
after config replacement, the helper restores the verified prior config
without daemon-reload, enable/disable, restart, or stop. It records
`recovery_required` and leaves the generation incomplete. Restore the recorded
runtime provenance, then retry that manifest; a new apply remains blocked.

Explicit restore accepts the exact staged config or an already-restored exact
backup, so retry the same command after interruption. It rejects an unknown
live hash, a non-current generation, or any host/package/binary/unit drift.
An incomplete journal blocks a new apply. Reconcile the recorded runtime and
retry restore; there is intentionally no force override. SIGINT and SIGTERM
trigger in-process recovery where possible. The durable current pointer and
phase journal provide the recovery path after SIGKILL or power loss.

Require the live config and every ancestor of the live path and state root to
be root-owned and not group/other-writable. The staged file may be
operator-owned, but the helper rechecks its inode and hash immediately before
replacement. If extended metadata cannot be reproduced exactly, apply fails
before rename rather than silently dropping it.

The helper intentionally does not mutate packages, Lemonade configuration,
systemd drop-ins, or environment files. Capture and restore those in their own
reviewed transaction when the change includes them.

## Native telemetry facts

- Endpoint and protocol come from `telemetry.otlp.*`.
- Lemonade reads generic `OTEL_EXPORTER_OTLP_HEADERS`, not the standard
  per-signal endpoint/protocol variables.
- Native export supports OTLP/HTTP protobuf or JSON, one endpoint, and traces.
- Every request is a root SERVER span; incoming trace context is not consumed.
- Streaming spans finish only after the stream is drained.

# Destination-bound queue directory transaction

## Boundary

Use `scripts/transactional_queue_directory.py` to create and later retire the
single persistent queue directory used by `file_storage/galileo_lemonade`.
This helper manages only the final destination-fingerprinted directory. It
does not install the Collector, change Collector YAML, configure tinyproxy, or
move queued records to a different destination.

The fixed paths are:

- approved queue root:
  `/var/lib/splunk-otel-collector/galileo-queue`;
- root-only quarantine root:
  `/var/lib/splunk-otel-collector/galileo-queue-quarantine`;
- protected transaction state:
  `/var/lib/galileo-queue-transactions`.

The queue and quarantine roots must already exist on the same filesystem with
canonical, nonlinked, root-controlled ancestry. Use `root:root 0755` or a
reviewed root-owned `0750` queue root that the Collector can traverse. The
quarantine root must be `root:root 0700`. The helper creates only
`<queue-root>/<destination-fingerprint>` as the exact Collector service UID and
primary GID, mode `0700`.

The `0750` form is accepted only when its group is the exact Collector service
GID; other protected-looking modes such as `0700` are rejected. Every queue
ancestor must grant traversal to the Collector identity. Queue creation,
quarantine rename, and quarantine protection reopen the two roots with
`O_DIRECTORY|O_NOFOLLOW` and bind their file descriptors to the recorded
device/inode/owner/mode. A quarantined entry on a different device is rejected
as a mount-boundary collision before ownership or mode is changed.
Final empty-directory removal uses the bound quarantine-root descriptor and
rechecks the exact child descriptor, name, inode, ownership, mode, and
emptiness before `rmdir`.

The helper is Linux/root/systemd-only. It records a domain-separated machine
fingerprint, exact `splunk-otel-collector` package version, loaded active
service name/user/group/UID/GID, unit enablement, stable main-unit/drop-in
content fingerprint, support-root device/inode/owner/mode, and the created
queue device/inode/owner/mode/fingerprint. Unit inode and modification time are
deliberately excluded from the stable unit fingerprint because the separate
runtime-bundle transaction restores exact unit bytes by atomic replacement.

## Prepare the support roots

Resolve the Collector service identity first. Do not guess its group:

```bash
systemctl show -p User -p Group -- splunk-otel-collector.service
```

Create the two fixed support roots before the queue transaction. A typical
root-owned world-traversable queue root is:

```bash
sudo install -d -o root -g root -m 0755 \
  /var/lib/splunk-otel-collector/galileo-queue
sudo install -d -o root -g root -m 0700 \
  /var/lib/splunk-otel-collector/galileo-queue-quarantine
```

If policy uses `0750`, group the queue root to the exact Collector primary
group. Never make either root group- or other-writable. Do not pre-create the
fingerprinted child: an existing child fails before a transaction generation
is created and is never adopted, removed, or moved.

## Apply

Use the lowercase digest emitted by
`collector_runtime_wrapper.py --print-destination-fingerprint` and the exact
installed package version:

```bash
COLLECTOR_VERSION="$(dpkg-query -W -f='${Version}' splunk-otel-collector)"
sudo python3 \
  skills/galileo-lemonade-instrumentation-setup/scripts/transactional_queue_directory.py \
  apply \
  --fingerprint "$GALILEO_DESTINATION_FINGERPRINT" \
  --service splunk-otel-collector.service \
  --expected-package-version "$COLLECTOR_VERSION"
```

Output is fixed-schema sanitized JSON. It contains the non-secret generation
and destination fingerprint, but no filesystem path, file content, subprocess
output, or credential. The protected restore manifest is deterministically:

```text
/var/lib/galileo-queue-transactions/generation-<generation>/manifest.json
```

The helper writes a root-only manifest, intent journal, current-generation
pointer, and lock. A second apply is refused while a generation remains
current.

## Composition and rollback order

Create the queue before any component can reference it:

1. Apply this queue transaction.
2. Apply and validate the dedicated tinyproxy transaction.
3. Apply and validate the Collector runtime bundle and wrapper.
4. Validate and apply the Collector YAML transaction.
5. Perform Collector counters plus Galileo and Splunk backend readback.

Rollback in the reverse dependency order:

1. Restore Collector YAML so no pipeline references the Galileo queue.
2. Restore the Collector runtime bundle and restart the Collector, releasing
   the file-storage database.
3. Restore the tinyproxy transaction.
4. Restore this queue transaction last.

Keeping queue rollback last is intentional. Removing or renaming a queue while
the Collector has its database open can lose the stable pathname guarantee and
make the rollback evidence ambiguous.

## Restore, removal, and quarantine

Restore with the exact retained manifest:

```bash
sudo python3 \
  skills/galileo-lemonade-instrumentation-setup/scripts/transactional_queue_directory.py \
  restore \
  --manifest \
  /var/lib/galileo-queue-transactions/generation-REVIEWED_GENERATION/manifest.json
```

The helper removes the active queue path only when all of these are true:

- this generation durably recorded creating it;
- its destination fingerprint, device, inode, UID, GID, and mode still match;
- it is a real nonlinked directory;
- a descriptor-based check finds it empty and stable;
- machine, package, service, unit, and support-root provenance still match.

Even for that removable case, it first atomically moves the directory behind
the root-only deterministic quarantine pathname and repeats the descriptor-
based exact/empty check there. Only then does it remove the empty directory.
If a crash or concurrent writer intervenes after the rename, the directory is
retained as quarantine instead.

Any nonempty queue, changed mode/owner/inode/type, or queue whose creation
identity was not durably recorded is never deleted. It is atomically renamed
on the same filesystem to the deterministic transaction quarantine:

```text
/var/lib/splunk-otel-collector/galileo-queue-quarantine/
  generation-<generation>-<destination-fingerprint>
```

The quarantine root prevents Collector traversal. The quarantined top-level
entry is changed to root ownership and restrictive mode without reading,
recursing into, replaying, or deleting its contents. The journal records a
sanitized quarantine identity and `disposition=quarantined`. Keep it with the
old endpoint/selectors and transaction evidence for explicit operator review;
never copy, rename, or attach it to another destination fingerprint.

If both the active path and deterministic quarantine exist, restore stops with
`recovery_required` and preserves both. If machine/package/service/root
provenance drifts, restore makes no queue mutation; reconcile the exact
provenance and retry the same manifest.

## Crash recovery

Every create, remove, or quarantine side effect has a durable intent first.
The manifest is immutable and bound by the current-generation pointer. The
journal and its parent directory are fsynced at each checkpoint.

- A crash after creating the child but before its identity checkpoint leaves
  an uncertain queue. Restore quarantines it even when it appears empty.
- A crash after an empty-directory removal resumes as `already_absent`; it
  never deletes another object.
- A crash after atomic quarantine rename resumes from the deterministic
  quarantine and records its protected identity.
- A completed restore is idempotent.

Idempotent restore still revalidates machine/package/service/root provenance,
requires the active queue path to remain absent, and checks the exact recorded
quarantine inode/type/owner/mode when the disposition was `quarantined`. It
fails on post-restore drift instead of replaying a stale success claim.

When output reports `recovery_required`, retain the manifest, journal,
`current.json`, and quarantine. Do not edit transaction state. Correct only the
reported provenance or collision condition and rerun `restore` with the same
manifest.

# macOS Keychain to protected runtime file

Keep credential retrieval on the trusted Mac and transfer only into an
operator-selected secret file owned by the runtime identity that reads it.
Never display or paste the value.

Example pattern (replace the service/account labels after discovering them):

```bash
umask 077
tmp="$(mktemp)"
cleanup() { rm -f -- "$tmp"; }
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
security find-generic-password -w -s "$KEYCHAIN_SERVICE" -a "$KEYCHAIN_ACCOUNT" >"$tmp"
test -s "$tmp"
```

Use a protected transfer channel, install the destination as the dedicated
service user with mode `0600`, and verify metadata without reading the value
back. Use root ownership only if the consuming service runs as root. Prefer a
direct protected stream that does not create a local plaintext file. When a
temporary file is unavoidable, keep the cleanup trap active, explicitly
run `cleanup` after transfer, then run `trap - EXIT HUP INT TERM` and `unset tmp`
to clear the cleanup state. Unlinking is cleanup, not a guarantee that flash
storage was securely erased, so never reuse the
temporary path or leave the value in backups. A collector service drop-in may
read a dedicated environment file; the secret must never appear in the unit
command, collector YAML, shell history, or validation output.

## Splunk scope separation and rotation

Use two distinct Splunk organization access tokens:

- an **Ingest**-scoped token, readable only by the Collector runtime identity;
- an **API**-scoped token with the `read_only` role, readable only by the
  operator running backend validation.

Do not deploy a combined API-and-Ingest token or a user API session token to a
Collector. If an existing combined token must be replaced, an organization
administrator creates both least-privilege replacements, each with a distinct
name and bounded expiry. Securely place the replacement secrets into separate
Keychain items and runtime files, update the Collector and readback path, and
prove Collector acceptance/export plus organization-bound backend readback.
Only then deactivate the old combined token. If either replacement fails,
restore only the previously proven runtime binding; do not deactivate the last
working token.

Rotation changes only the secret of one existing token; it does not split or
change that token's authorization scope, API role, visibility, or identity.
Therefore, do not use rotation to remediate a combined API-and-Ingest token.
Create the two singleton-scope replacements, prove them independently, and
then deactivate the combined token.

For routine renewal of a correctly scoped organization token, Splunk's Rotate
operation creates a new secret and deactivates the previous secret after an
optional grace period. Rotation requires an organization administrator. The
API form is `POST /v2/token/{name}/rotate` and must be authenticated with a
short-lived **user API session token**, not with the organization token being
rotated. A protected API client must read that session token from a private
file, use the exact configured realm and HTTPS origin, disable ambient proxies
and redirects, and bound the response and deadline. Keep the session token out
of the Collector, request URL, argv (including `curl -H`), shell history, YAML,
evidence, and remote storage.

Treat rotation as a bounded transaction:

1. Bind preflight to the exact realm, organization ID, token ID and name,
   active state, singleton scope, API role when applicable, visibility, expiry,
   expiration-alert owner, current runtime binding, and rollback plan without
   recording either secret. Expired tokens cannot be rotated.
2. Set an explicit new expiry beyond the entire change window. Define a
   positive planned grace period as cutover budget plus validation budget plus
   rollback budget plus a clock-skew margin. Do not rely on the API's zero
   default for a planned zero-downtime renewal.
3. Treat a disclosed credential as incident response, not routine renewal.
   Replace and deactivate it as quickly as policy permits; do not give it a
   routine long grace period. A zero grace period can interrupt telemetry if
   the replacement is not deployed immediately.
4. Rotate in the signed-in admin UI or with a protected client using the user
   API session token. Store the new secret through an approved secret channel.
5. Atomically replace the dedicated runtime file, restart the exact consuming
   service, and require health, accepted/sent deltas with no new failed,
   refused, or enqueue-failed deltas, empty exporter queues, and
   organization-bound backend readback. Collector counters alone are not
   sufficient.
6. Update the separate readback credential independently when it is the token
   being rotated. Never make one successful path stand in for the other.
7. After grace expiry or old-token deactivation, require the old secret to be
   rejected and the new secret to remain successful. Inventory state alone is
   insufficient. If the old secret is still accepted, keep the transaction and
   incident open and escalate to the Splunk organization administrator.
8. Remove temporary plaintext files and user API session material. Retain only
   sanitized timestamps, scopes, token names, service state, and validation
   results.

For the Collector's Ingest token, render a complete staged copy of the
discovered service environment file through a protected channel and change
only `SPLUNK_ACCESS_TOKEN`. The packaged wrapper verifies that both files are
root-owned, root-group, single-link mode `0600` files under protected
ancestry, that the reviewed staged SHA-256 matches, and that no other byte or
quoting style changed. It accepts paths and hashes only—never a token value:

```bash
STAGED_SHA256="$(sha256sum /root/splunk-token-stage/collector.env | awk '{print $1}')"
COLLECTOR_SHA256="$(sha256sum /usr/bin/otelcol | awk '{print $1}')"
sudo python3 skills/lemonade-splunk-otel/scripts/transactional_splunk_token.py \
  apply \
  --staged /root/splunk-token-stage/collector.env \
  --live /etc/otel/collector/splunk-otel-collector.conf \
  --service splunk-otel-collector.service \
  --health-url http://127.0.0.1:13133/ \
  --expected-sha256 "$STAGED_SHA256" \
  --collector-binary /usr/bin/otelcol \
  --collector-binary-sha256 "$COLLECTOR_SHA256" \
  --state-root /var/lib/splunk-token-transactions
```

Derive every example path and service from the live unit. The wrapper delegates
to the same current-generation, durable-journal transaction used for Collector
config changes and supplies an exact preflight live-file hash plus private-file
gates (`--expected-live-sha256` and `--private-artifact`) to the underlying
transaction. If restart or loopback health fails, it restores the prior bytes and
service state. Explicit rollback uses the returned manifest:

```bash
sudo python3 skills/lemonade-splunk-otel/scripts/transactional_splunk_token.py \
  restore --manifest /absolute/root-only/transaction/manifest.json
```

The transaction backup contains the old secret. Keep the root-only state only
through the measured grace and rollback window; after the old secret is proven
rejected and rollback is intentionally closed, handle the state through the
organization's credential-evidence retention policy. Do not delete a current
generation ad hoc, because its manifest and journal are the crash-recovery
record.

Splunk documents the scopes, administrator requirement, grace-period behavior,
and user API session token requirement here:

- https://help.splunk.com/en/splunk-observability-cloud/administer/authentication-and-security/authentication-tokens/org-access-tokens
- https://dev.splunk.com/observability/reference/api/org_tokens/latest

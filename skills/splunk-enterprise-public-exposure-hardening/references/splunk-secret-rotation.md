# `splunk.secret` Rotation Procedure

`splunk.secret` is the per-host symmetric key Splunk uses to encrypt
sensitive values in `*.conf` files. Files that depend on it:

- `etc/system/local/server.conf` — `pass4SymmKey`, `sslPassword`
- `etc/system/local/inputs.conf` and per-app — TLS passwords, secrets
- `etc/system/local/outputs.conf` — TLS passwords
- `etc/passwd` — local user password hashes
- `etc/auth/passwd.d/` — additional auth state
- Per-app `*.conf` with `password = $1$...`, `clientSecret = ...`,
  `apikey = ...`, etc.

## When to rotate

- After a credential exposure incident (advisories
  SVD-2026-0207 / SVD-2026-0203 demonstrated `_internal` paths that
  leak it).
- After a change in custodianship (operator handover).
- On a scheduled cadence (annually for high-sensitivity deployments).
- When `splunk.secret` has ever been pulled out of the host (backup
  images, container layers, snapshot copies).

## 10-step procedure

### Step 1 — Contain

Block outbound from the affected host pending forensics. Rotate any
credentials that you cannot undo in step 2 (cloud IAM keys referenced
by Splunk inputs).

### Step 2 — Inventory the encrypted material

```bash
grep -rE '\$1\$|\$7\$' /opt/splunk/etc/ \
  | grep -v -- '--' \
  | tee /tmp/encrypted-credentials.txt
```

Review every line. Anything that looks like an encrypted credential
(`$1$...`, `$7$...`) needs re-encryption after rotation.

### Step 3 — Decrypt with the OLD secret

Before replacing `splunk.secret`, dump every encrypted value to a
temporary plaintext list using the running Splunk:

```bash
splunk show user-passwords        # local user passwords
splunk btool server list general | grep pass4SymmKey
splunk btool inputs list http://* | grep token
# etc.
```

Store the plaintext list in tmpfs ONLY:

```bash
mkdir -p /run/splunk-secret-rotation
chmod 700 /run/splunk-secret-rotation
```

NEVER write the plaintext list to disk outside tmpfs.

### Step 4 — Backup the old `splunk.secret`

```bash
cp -p /opt/splunk/etc/auth/splunk.secret \
   /opt/splunk/etc/auth/splunk.secret.bak.$(date +%Y%m%d%H%M%S)
chmod 0400 /opt/splunk/etc/auth/splunk.secret.bak.*
```

The backup is needed in case rollback is required; delete after
successful re-encryption.

### Step 5 — Generate the new secret

```bash
openssl rand -base64 254 \
  | tr -d '\n' \
  | install -m 0400 -o splunk -g splunk /dev/stdin /tmp/new_splunk_secret
```

(The 254-byte length matches Splunk's default secret length.)

### Step 6 — Replace `splunk.secret` and restart

```bash
bash splunk/rotate-splunk-secret.sh /tmp/new_splunk_secret
```

The rendered helper handles backup + install + restart atomically.

### Step 7 — Re-encrypt every credential

For each credential from step 3, re-set it through Splunk so the new
secret encrypts it:

```bash
splunk edit user breakglass_alice -password 'NEW_PASSWORD' -auth admin:OLD
splunk edit licenser-localpeer -master_uri https://lm.example.com:8089 \
  -auth admin:NEW
splunk edit cluster-config -mode peer -auth-passphrase-file /tmp/new_pass4
# etc.
```

Use file-based password passing wherever the CLI supports it; never
put plaintext passwords on argv.

### Step 8 — Restart the entire deployment

```bash
splunk restart
```

For a SHC, restart the deployer last; the captain coordinates the rolling
restart. For an indexer cluster, use `splunk rolling-restart cluster-peers`.

### Step 9 — Validate

Run the rendered `validate.sh` to confirm:

- Splunk starts without crypto errors.
- `_audit` continues to ingest.
- HEC tokens still authenticate.
- mTLS forwarders still connect.

If anything fails, restore from the backup `splunk.secret`:

```bash
install -m 0400 -o splunk -g splunk \
  /opt/splunk/etc/auth/splunk.secret.bak.<TS> \
  /opt/splunk/etc/auth/splunk.secret
splunk restart
```

### Step 10 — Post-incident

- Audit who had access to the original `splunk.secret`.
- File a security review.
- Rotate any HEC tokens, API keys, and app credentials that were
  re-encrypted.
- Wipe `/run/splunk-secret-rotation` (tmpfs auto-cleared on reboot).
- Document the runbook deltas for next time.

## What `splunk.secret` is NOT

- It is NOT the cluster `pass4SymmKey`. Cluster pass4SymmKey is a
  separate shared secret across cluster members — see
  `rotate-pass4symmkey.sh`.
- It is NOT the SSL key passphrase. That's `[sslConfig] sslPassword`
  in `server.conf` — also separately rotated.
- It is NOT shared across the deployment. Each host has its own
  `splunk.secret`.

## SHC / cluster considerations

In a SHC or indexer cluster, each member has its own `splunk.secret`.
You can rotate them independently as long as the encrypted values in
shared bundles (e.g. cluster bundle apps) are decrypted before the
bundle is pushed. The deployer / cluster-manager re-encrypts during
distribution.

## Why a single per-host secret

Splunk uses per-host secrets so that a compromise of one host does
not auto-decrypt configs on other hosts. The trade-off is that
configurations carrying encrypted values are NOT portable across
hosts without re-encryption.

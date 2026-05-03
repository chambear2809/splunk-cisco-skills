# Key Format and Permissions

Splunk's TLS layer is OpenSSL-based but uses several format
conventions that bite operators who copy keys from one tool to
another.

## PKCS#1 vs PKCS#8

| Header | Format | Where Splunk uses it |
|---|---|---|
| `-----BEGIN RSA PRIVATE KEY-----` | PKCS#1 | Default for splunkd, Web, S2S, HEC, replication-port. Matches Splunk's own `splunk cmd openssl genpkey -aes-256-cbc` example. |
| `-----BEGIN PRIVATE KEY-----` | PKCS#8 (unencrypted) | Required for Edge Processor (per the EP TLS doc) and Splunk DB Connect. |
| `-----BEGIN ENCRYPTED PRIVATE KEY-----` | PKCS#8 encrypted | Acceptable in Splunk; needs `sslPassword`. |

The renderer defaults to PKCS#1 (encrypted) for Splunk core
surfaces. `--key-format pkcs8` switches to PKCS#8 (unencrypted)
for Edge Processor and DB Connect.

## Convert PKCS#1 → PKCS#8

```bash
$SPLUNK_HOME/bin/splunk cmd openssl pkcs8 \
    -topk8 -inform PEM -in pkcs1.key -out pkcs8.key \
    -nocrypt
```

`-nocrypt` strips encryption (required for Edge Processor / DB
Connect). For Splunk core surfaces that want PKCS#8 with
encryption (rare), drop `-nocrypt` and provide
`-passout file:<password file>`.

## Convert PKCS#8 → PKCS#1

```bash
$SPLUNK_HOME/bin/splunk cmd openssl rsa -in pkcs8.key -out pkcs1.key
```

The renderer's `pki/install/prepare-key.sh` performs both
directions and chain concatenation.

## File permissions

The renderer sets explicit perms before Splunk starts:

| File type | Perms | Owner |
|---|---|---|
| Private key (`*.key`, `*.pem` containing key) | 0600 | Splunk service user |
| Cert (`*.pem` cert-only, `*.crt`) | 0644 | Splunk service user |
| CA bundle (`cabundle.pem`) | 0644 | Splunk service user |
| `splunk.secret` | 0600 | Splunk service user |
| Cert directory | 0755 | Splunk service user |

Splunk Enterprise restricts file perms automatically on restart
(per the
[inter-Splunk TLS doc](https://help.splunk.com/en/splunk-enterprise/administer/manage-users-and-security/10.0/secure-splunk-platform-communications-with-transport-layer-security-certificates/configure-tls-certificates-for-inter-splunk-communication)),
"changes the file permissions on the certificates so that only
the user that Splunk Enterprise runs as has full access". Setting
explicit perms BEFORE Splunk starts avoids:

- Race condition where another tool reads the cert while Splunk
  is restarting.
- Permission flap that breaks `splunk` CLI or REST callers
  during the brief restart window.

## Encrypted key passphrase round-trip

Splunk encrypts the plaintext `sslPassword` on first restart using
`splunk.secret`. The encrypted value starts with `$1$` (or `$7$`
for newer Splunk versions).

The skill writes the **plaintext** sslPassword to the per-host
overlay at `$SPLUNK_HOME/etc/system/local/server.conf` (or
`web.conf` / `inputs.conf` / `outputs.conf` depending on
`--target`). It does this only when the operator supplies
`--ssl-password-file PATH`. On first restart, splunkd encrypts the
plaintext with `splunk.secret` and rewrites the file.

This means there is a brief window (between install and first
restart) where the plaintext lives on disk in
`etc/system/local/<conf>` with mode 0644. The window is bounded
by how soon the operator restarts.

If the leaf key is unencrypted (e.g. PKCS#8 nocrypt for Edge
Processor), pass no `--ssl-password-file` and install-leaf.sh
omits `sslPassword` entirely.

To verify the round-trip after install + restart:

```bash
# 1. Install the cert with the operator-supplied passphrase.
bash pki/install/install-leaf.sh \
    --target splunkd \
    --host idx01.example.com \
    --cert /tmp/signed/splunkd-idx01.pem \
    --key  /tmp/signed/splunkd-idx01.key \
    --ca   /tmp/signed/cabundle.pem \
    --ssl-password-file /tmp/pki_leaf_key_password

# install-leaf.sh writes the per-host overlay to
# $SPLUNK_HOME/etc/system/local/server.conf with the marker block:
#
#   ### BEGIN splunk-platform-pki-setup [splunkd]
#   [sslConfig]
#   serverCert  = /opt/splunk/etc/auth/myssl/idx01.example.com/idx01.example.com-splunkd.pem
#   sslPassword = <plaintext from /tmp/pki_leaf_key_password>
#   ### END splunk-platform-pki-setup [splunkd]

# 2. Restart Splunk so it encrypts the password.
$SPLUNK_HOME/bin/splunk restart

# 3. Read the encrypted value (now $1$ form)
$SPLUNK_HOME/bin/splunk cmd btool server list sslConfig | grep sslPassword
# sslPassword = $1$abc123==

# 4. Decrypt and compare against the plaintext file.
$SPLUNK_HOME/bin/splunk show-decrypted --value '$1$abc123=='
# Expected: the plaintext from /tmp/pki_leaf_key_password
```

`pki/install/verify-leaf.sh` performs the chain validation, but
the round-trip check above is operator-driven (it requires Splunk
to have restarted at least once).

## Splunk.secret parity across cluster

Encrypted `sslPassword` only round-trips correctly if every host
that needs to read it has the same `splunk.secret`. For:

- **Indexer cluster**: each peer encrypts its own `sslPassword` on
  restart. Each peer's `splunk.secret` is independent BUT the
  operator typically aligns them so peer migrations work.
- **SHC**: members must share `splunk.secret` (the captain
  replicates encrypted values). The host-setup skill aligns
  these at SHC bootstrap.
- **License Manager**: independent, but if encrypted creds are
  pushed via deployer, the LM must share `splunk.secret` with
  the deployer.
- **Deployment Server / clients**: clients receive deployed apps
  which may contain encrypted creds; mismatch means clients
  cannot decrypt.

The skill's `preflight` phase computes the SHA-256 of
`splunk.secret` on every cluster member and refuses to apply if
it diverges. The fix is the public-exposure-hardening skill's
`rotate-splunk-secret.sh`.

## Chain concatenation

For most Splunk surfaces, `serverCert` should be the leaf only,
and intermediates live in `sslRootCAPath`. Some operators prefer
to bundle the leaf + intermediates into a single chain file:

```bash
cat leaf.pem intermediate.pem > leaf-with-chain.pem
```

This works for Web (HTTPS clients send the chain on connect) and
HEC, but is **NOT** recommended for splunkd because:

- KV Store's `openssl verify -x509_strict` runs against
  `serverCert` separately; a chain in `serverCert` can confuse
  the parser.
- The cluster bundle's `sslRootCAPath` already establishes the
  chain; bundling again duplicates work.

The renderer keeps `serverCert` = leaf, `sslRootCAPath` = full
chain bundle.

## Format conversion cheat sheet

```bash
# DER → PEM
openssl x509 -inform DER -in cert.cer -out cert.pem

# PEM → DER
openssl x509 -outform DER -in cert.pem -out cert.cer

# PKCS#7 (.p7b) → PEM bundle
openssl pkcs7 -inform DER -in chain.p7b -print_certs -out chain.pem

# PKCS#12 (.pfx) → PEM cert + key
openssl pkcs12 -in bundle.pfx -clcerts -nokeys -out cert.pem
openssl pkcs12 -in bundle.pfx -nocerts -out key.pem

# Strip key passphrase
openssl rsa -in encrypted.key -out plain.key

# Add key passphrase
openssl rsa -in plain.key -aes256 -out encrypted.key
```

The renderer's `prepare-key.sh` calls these via
`$SPLUNK_HOME/bin/splunk cmd openssl` so the OpenSSL build that
Splunk uses is the one doing the conversion.

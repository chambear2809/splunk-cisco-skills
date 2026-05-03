# Replication Port TLS

The cluster replication port (default 9887) carries bucket
replication traffic between indexer cluster peers. By default
it's cleartext. This skill encrypts it via the
`[replication_port-ssl://9887]` stanza when
`--encrypt-replication-port=true` is passed.

## Why this is opt-in

Encrypting the replication port:

1. **Requires a full cluster rolling restart** to renegotiate
   the replication channel.
2. **Adds CPU overhead** for replication-heavy clusters (many
   indexers report 5–15 % indexer CPU increase).
3. **Has a one-shot migration risk**: the cleartext stanza and
   the SSL stanza are mutually exclusive, so the cluster bundle
   apply has to land on every peer in one wave or the cluster
   can't replicate during the gap.

Most operators leave it cleartext when the indexer cluster is on
a private network segment. Operators in regulated environments
(FIPS, FedRAMP-moderate+, PCI scope) should turn it on.

## Cleartext stanza (default)

```
[replication_port://9887]
disabled = 0
```

## SSL stanza (mutually exclusive)

```
[replication_port-ssl://9887]
disabled              = 0
rootCA                = /opt/splunk/etc/auth/myssl/cabundle.pem
serverCert            = /opt/splunk/etc/auth/myssl/idx01.example.com/idx01-replication-cert.pem
sslPassword           = <encrypted on first restart>
sslCommonNameToCheck  = idx01.example.com,idx02.example.com,idx03.example.com
sslAltNameToCheck     = idx01.example.com,idx02.example.com,idx03.example.com
requireClientCert     = true
sslVersions           = tls1.2
cipherSuite           = <from --tls-policy>
```

The `requireClientCert = true` setting on the replication port
makes the channel mTLS — every peer must present a valid client
cert when connecting to another peer for bucket replication.

## CSR for the replication leaf

The renderer emits a separate CSR template
`pki/csr-templates/replication-<host>.cnf` because the
replication leaf needs:

- **CN = the peer's FQDN** (matches `sslCommonNameToCheck` on
  the receiving side).
- **SAN = every peer's FQDN** (so any peer can connect to any
  other; the receiving side's `sslCommonNameToCheck` lists all).
- **EKU = serverAuth + clientAuth** (each peer is both server
  and client over the replication channel).

```
[req]
default_bits        = 2048
default_md          = sha256
prompt              = no
distinguished_name  = req_distinguished_name
req_extensions      = v3_req

[req_distinguished_name]
C  = US
O  = Example Corp
CN = idx01.example.com

[v3_req]
basicConstraints   = critical, CA:FALSE
keyUsage           = critical, digitalSignature, keyEncipherment
extendedKeyUsage   = serverAuth, clientAuth
subjectAltName     = @alt_names

[alt_names]
DNS.1 = idx01.example.com
DNS.2 = idx02.example.com
DNS.3 = idx03.example.com
```

## Where the [replication_port-ssl://9887] stanza lives

Critical: this stanza carries a per-host `serverCert` and so it
**does NOT live in the cluster bundle**. The cluster bundle is
shared across every peer; if the bundle contained
`serverCert = .../idx01-replication.pem` then `idx02` and `idx03`
would also try to read that exact file and fail.

The renderer therefore puts the entire `[replication_port-ssl://9887]`
stanza in each peer's `etc/system/local/server.conf` overlay,
written by `install-leaf.sh --target replication`.

Per-peer flow when `--encrypt-replication-port=true`:

```bash
# 1. Generate per-peer replication CSR (or sign privately)
PKI_LEAF_KEY_PASSWORD_FILE=/tmp/leaf-pwd \
    bash pki/csr-templates/generate-csr.sh \
        --config pki/csr-templates/replication-idx01.cnf

# 2. Sign with the Intermediate CA
PKI_LEAF_KEY_PASSWORD_FILE=/tmp/leaf-pwd \
    PKI_INTERMEDIATE_CA_KEY_PASSWORD_FILE=/tmp/int-pwd \
    bash pki/private-ca/sign-server-cert.sh \
        --name idx01-replication --san DNS:idx01,DNS:idx02,DNS:idx03

# 3. Install on the peer (writes the overlay to system/local/server.conf)
REPLICATION_PEER_NAMES="idx01,idx02,idx03" \
    bash pki/install/install-leaf.sh \
        --target replication \
        --host idx01.example.com \
        --cert signed/idx01-replication.pem \
        --key  signed/idx01-replication.key \
        --ca   signed/cabundle.pem \
        --ssl-password-file /tmp/leaf-pwd

# 4. Repeat for idx02, idx03

# 5. Push the cluster bundle (which carries the [sslConfig] policy)
bash skills/splunk-indexer-cluster-setup/scripts/setup.sh --phase bundle-apply ...

# 6. Rolling restart with --percent-peers-to-restart 100 so all peers
#    pick up [replication_port-ssl://9887] in one wave (cleartext stanza
#    is not honoured once the SSL stanza is present in system/local).
```

## Atomic migration helper

`pki/rotate/swap-replication-port-to-ssl.sh` performs the
mutually-exclusive swap as a single bundle edit:

```bash
#!/usr/bin/env bash
# Removes [replication_port://9887] and adds
# [replication_port-ssl://9887] in the cluster bundle so the
# bundle never contains both stanzas active.

set -euo pipefail

BUNDLE="/opt/splunk/etc/master-apps/000_pki_trust/local/server.conf"

# Render the SSL stanza
cat > /tmp/repl-ssl.conf <<EOF
[replication_port-ssl://9887]
disabled              = 0
rootCA                = /opt/splunk/etc/auth/myssl/cabundle.pem
serverCert            = /opt/splunk/etc/auth/myssl/__REPLICATION_LEAF__
sslPassword           = __REPLICATION_PASSWORD__
sslCommonNameToCheck  = __REPLICATION_CN_LIST__
requireClientCert     = true
sslVersions           = tls1.2
EOF

# Atomic swap
{
  grep -v -E '^\[replication_port://9887\]' "$BUNDLE" \
    | grep -v '^disabled = 0' \
    || true
  cat /tmp/repl-ssl.conf
} > "$BUNDLE.new"
mv "$BUNDLE.new" "$BUNDLE"

# Apply the bundle (delegated to splunk-indexer-cluster-setup)
echo "Now run: bash skills/splunk-indexer-cluster-setup/scripts/setup.sh --phase bundle-apply ..."
```

In practice the renderer fills in the placeholders.

## Rolling-restart cadence

After the bundle apply, ALL peers must restart in one wave so the
cleartext-vs-SSL window is as short as possible. Recommended:

```bash
bash skills/splunk-indexer-cluster-setup/scripts/setup.sh \
    --phase rolling-restart \
    --rolling-restart-mode searchable \
    --percent-peers-to-restart 100 \
    --cluster-manager-uri https://cm01.example.com:8089 \
    --admin-password-file /tmp/splunk_admin_password
```

`--percent-peers-to-restart 100` overrides the default 10 % so
all peers restart together. Search availability is preserved by
the `searchable` mode.

## Validation

After the migration:

```bash
# 1. Confirm the SSL port is listening on each peer
for peer in idx01 idx02 idx03; do
  ssh ${peer}.example.com "ss -tlnp | grep ':9887'"
done

# 2. Confirm the cleartext stanza is gone from the live config
$SPLUNK_HOME/bin/splunk cmd btool server list \
  | grep -A2 '\[replication_port'

# 3. Confirm bucket replication is healthy
$SPLUNK_HOME/bin/splunk show cluster-status --verbose \
  | grep -E 'replication_factor|search_factor|status'
```

Replication factor and search factor must remain "Met" after the
migration.

## Rollback

If replication breaks:

1. Edit the cluster bundle to remove `[replication_port-ssl://9887]`
   and re-add `[replication_port://9887]`.
2. `bundle-apply`.
3. `rolling-restart`.

Skip the SSL stanza next time and investigate (cipher mismatch,
SAN mismatch, CN mismatch are the usual culprits).

# Private PKI Workflow

Triggered by `--mode private`. The skill never holds CA private
key material in memory, in argv, or in rendered files; it only
emits scripts that the operator runs locally with file-based
secrets.

## Hierarchy

```
Root CA (offline, 3650 d, RSA-4096 or ECDSA-P-384)
    │
    ▼
Intermediate CA (online, 1825 d, same algo as root)
    │  signs ↓
    ▼
Leaf certs (per-host, 825 d)
    ├── splunkd cert (sslConfig)
    ├── Splunk Web cert (web.conf)
    ├── S2S receiver cert (inputs.conf [SSL])
    ├── HEC cert (inputs.conf [http])
    ├── replication-port cert (server.conf [replication_port-ssl])
    ├── SHC member cert
    ├── DS / DC cert pair
    ├── LM cert
    ├── MC cert
    ├── SAML SP signing cert (separate trust domain)
    └── Edge Processor cert pair (separate trust domain)
```

`--include-intermediate-ca true` is **strongly encouraged** for
production. The Root key stays offline (operator stores it on
removable media or in an HSM); the Intermediate key signs the
day-to-day leaves and can be re-issued without disrupting the
Root.

## Algorithms

| Identity | `--key-algorithm` default | Allowed values |
|---|---|---|
| Root CA | `rsa-4096` | `rsa-2048`, `rsa-4096`, `ecdsa-p256`, `ecdsa-p384` |
| Intermediate CA | inherits Root | same |
| Leaf | `rsa-2048` (KV-Store-friendly) | `rsa-2048`, `rsa-4096`, `ecdsa-p256` |

KV Store accepts both RSA and ECDSA but the EKU check is the
sensitive part; default RSA-2048 maximizes compatibility.

## Cert profiles (extensions)

The renderer emits separate `openssl.cnf` files per profile so the
extensions are baked in at signing time and don't depend on
operator memory.

### Root CA (`openssl-root.cnf` `[v3_ca]`)

```
basicConstraints       = critical, CA:TRUE
keyUsage               = critical, keyCertSign, cRLSign
subjectKeyIdentifier   = hash
```

### Intermediate CA (`openssl-intermediate.cnf` `[v3_intermediate_ca]`)

```
basicConstraints       = critical, CA:TRUE, pathlen:0
keyUsage               = critical, keyCertSign, cRLSign
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid:always, issuer
```

### Server leaf (`openssl-leaf-server.cnf` `[v3_srv]`)

```
basicConstraints       = critical, CA:FALSE
keyUsage               = critical, digitalSignature, keyEncipherment
extendedKeyUsage       = serverAuth, clientAuth
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid:always, issuer
subjectAltName         = @alt_names

[alt_names]
DNS.1 = sh01.example.com
DNS.2 = sh01
IP.1  = 10.0.10.11
```

The dual `serverAuth` + `clientAuth` EKU is **required** for KV
Store 7.0+ (per
[Preparing custom certificates for use with KV store](https://docs.splunk.com/Documentation/Splunk/9.4.2/Admin/CustomCertsKVstore)).
Even pure server certs include both EKUs to keep KV Store happy.

### Client leaf (`openssl-leaf-client.cnf` `[v3_clt]`)

```
basicConstraints       = critical, CA:FALSE
keyUsage               = critical, digitalSignature, keyEncipherment
extendedKeyUsage       = clientAuth
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid:always, issuer
subjectAltName         = @alt_names
```

Used for forwarders / deployment clients when `--enable-mtls`
covers them.

### SAML SP signing (`openssl-leaf-saml.cnf` `[v3_saml]`)

```
basicConstraints       = critical, CA:FALSE
keyUsage               = critical, digitalSignature, nonRepudiation
# no EKU — signing/verifying-only
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid:always, issuer
```

## Operator flow

```bash
# 1. Capture the secrets in chmod-600 files (OUTSIDE shell history).
bash skills/shared/scripts/write_secret_file.sh /tmp/pki_root_ca_key_password
bash skills/shared/scripts/write_secret_file.sh /tmp/pki_intermediate_ca_key_password
bash skills/shared/scripts/write_secret_file.sh /tmp/pki_leaf_key_password

# 2. Render the assets.
bash skills/splunk-platform-pki-setup/scripts/setup.sh \
    --phase render --mode private --target indexer-cluster,shc \
    --cm-fqdn cm01.example.com \
    --peer-hosts idx01.example.com,idx02.example.com,idx03.example.com \
    --shc-deployer-fqdn deployer01.example.com \
    --shc-members sh01.example.com,sh02.example.com,sh03.example.com \
    --include-intermediate-ca true \
    --tls-policy splunk-modern

# 3. Build the CA hierarchy ON A SEPARATE OFFLINE HOST when possible.
cd splunk-platform-pki-rendered/pki/private-ca
PKI_ROOT_CA_KEY_PASSWORD_FILE=/tmp/pki_root_ca_key_password \
    bash create-root-ca.sh

PKI_ROOT_CA_KEY_PASSWORD_FILE=/tmp/pki_root_ca_key_password \
PKI_INTERMEDIATE_CA_KEY_PASSWORD_FILE=/tmp/pki_intermediate_ca_key_password \
    bash create-intermediate-ca.sh

# 4. Sign the per-host leaves.
PKI_INTERMEDIATE_CA_KEY_PASSWORD_FILE=/tmp/pki_intermediate_ca_key_password \
PKI_LEAF_KEY_PASSWORD_FILE=/tmp/pki_leaf_key_password \
    bash sign-server-cert.sh --csr ../csr-templates/splunkd-idx01.example.com.cnf

# 5. Verify before installing.
cd ../install
bash verify-leaf.sh --cert ../signed/splunkd-idx01.example.com.pem \
                    --ca   ../private-ca/cabundle.pem
bash kv-store-eku-check.sh --cert ../signed/splunkd-idx01.example.com.pem \
                           --ca   ../private-ca/cabundle.pem

# 6. Install on the host (operator-driven; staged out-of-band per peer).
scp ../signed/splunkd-idx01.example.com.pem idx01.example.com:/opt/splunk/etc/auth/myssl/
ssh idx01.example.com "bash /tmp/install-leaf.sh ..."

# 7. Push the cluster bundle (delegated).
bash skills/splunk-indexer-cluster-setup/scripts/setup.sh \
    --phase bundle-apply --cluster-manager-uri https://cm01.example.com:8089 \
    --admin-password-file /tmp/splunk_admin_password

# 8. Searchable rolling restart (delegated).
bash skills/splunk-indexer-cluster-setup/scripts/setup.sh \
    --phase rolling-restart --rolling-restart-mode searchable \
    --cluster-manager-uri https://cm01.example.com:8089 \
    --admin-password-file /tmp/splunk_admin_password

# 9. Validate end-to-end.
bash skills/splunk-platform-pki-setup/scripts/validate.sh \
    --target indexer-cluster,shc \
    --admin-password-file /tmp/splunk_admin_password
```

## Backup and restore

The Root CA private key MUST be backed up to two separate offline
locations. If lost, every cert based on this Root must be
regenerated and redistributed — this is multiple days of cluster
downtime.

The renderer's `pki/private-ca/README.md` walks through:

- Burning the Root key + cert to two USB devices kept in separate
  physical locations.
- Encrypting the Intermediate key in a vault accessible only to
  the PKI operator.
- Documenting the passphrase recovery process in the operator
  runbook.

## CRL / OCSP

Out of scope for v1. Splunk does not currently consume CRLs or
OCSP responses for inter-Splunk TLS validation; rotation is the
mitigation when a leaf must be revoked. Public-PKI mode operators
should configure their CA's CRL / OCSP responder externally.

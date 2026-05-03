# Troubleshooting

Common failure modes and their fixes. The skill's `validate.sh`
runs each check listed below; the section header is the error
fingerprint to grep for.

## "Can't read SSL/TLS certificate or key" (splunkd.log)

**Cause** — the cert path in `server.conf [sslConfig] serverCert`
or `web.conf [settings] serverCert` is wrong, or the file perms
deny Splunk's user read access.

**Fix**:

```bash
# 1. Confirm the path Splunk expects
$SPLUNK_HOME/bin/splunk cmd btool server list sslConfig | grep serverCert
$SPLUNK_HOME/bin/splunk cmd btool web list settings | grep -E 'serverCert|privKeyPath'

# 2. Confirm the file exists and is readable by the Splunk user
ls -l <path>
sudo -u splunk cat <path> >/dev/null

# 3. Re-run the install helper so perms get reset
bash pki/install/install-leaf.sh ...
```

## "Sslv3 alert handshake failure" (splunkd.log on either side)

**Cause** — TLS version or cipher mismatch between client and
server.

**Fix**:

```bash
# Server side: confirm sslVersions and cipherSuite
$SPLUNK_HOME/bin/splunk cmd btool server list sslConfig | grep -E 'sslVersions|cipherSuite'

# Client side: confirm sslVersionsForClient
$SPLUNK_HOME/bin/splunk cmd btool server list sslConfig | grep sslVersionsForClient

# Both must agree on at least tls1.2 and at least one common cipher.
# Test from the client side
$SPLUNK_HOME/bin/splunk cmd openssl s_client \
    -connect <host>:8089 \
    -tls1_2 \
    -cipher 'ECDHE-RSA-AES256-GCM-SHA384'
```

If `sslVersions = tls1.2` everywhere but the handshake still
fails, check `--tls-policy` — `fips-140-3` and `stig` exclude
some ciphers that `splunk-modern` allows.

## "self signed certificate in certificate chain" (splunkd.log or openssl verify)

**Cause** — the trust chain is incomplete (the leaf or
intermediate is signed by a CA that's not in `sslRootCAPath`).

**Fix**:

```bash
# Show the cert chain
$SPLUNK_HOME/bin/splunk cmd openssl s_client \
    -connect <host>:8089 \
    -showcerts </dev/null 2>/dev/null \
  | grep -E 'subject|issuer'

# Concatenate the missing intermediates into cabundle.pem
cat returned-intermediate.pem returned-root.pem > pki/install/cabundle.pem

# Rerun verify
bash pki/install/verify-leaf.sh --cert <leaf>.pem --ca pki/install/cabundle.pem
```

## "EKU does not include serverAuth" or "clientAuth" (KV Store startup)

**Cause** — KV Store 7.0+ requires both EKU values. The leaf is
missing one.

**Fix**: re-mint the leaf with both EKUs. The renderer's
`openssl-leaf-server.cnf` has both by default. For Public-PKI
mode, fix the CA's cert profile (AD CS template, EJBCA profile,
Vault role) to include both EKUs and re-issue.

## "x509: certificate is not valid for any names" (curl / browser)

**Cause** — the cert's SAN doesn't match the FQDN the client
connected to.

**Fix**:

```bash
# Show the cert's SAN
$SPLUNK_HOME/bin/splunk cmd openssl x509 -in <leaf>.pem -text -noout \
  | grep -A1 'Subject Alternative Name'

# Re-render the CSR with the right SANs
bash skills/splunk-platform-pki-setup/scripts/setup.sh \
    --phase render \
    --peer-hosts <host>.example.com,<host>,<IP>
```

## "splunk show-decrypted does not match expected"

**Cause** — `splunk.secret` differs across cluster members, so
`sslPassword` re-encryption produces different ciphertext on each
host. KV Store and inter-Splunk TLS both need consistent
`splunk.secret`.

**Fix**: Use the public-exposure-hardening skill's
`rotate-splunk-secret.sh` to align `splunk.secret` across the
cluster. THEN re-run this skill's `apply` phase.

## "FIPS mode error" / "FIPS_mode_set fails"

**Cause** — the Splunk binary was built without FIPS support or
the OS doesn't support FIPS 140-3.

**Fix**: confirm Splunk 10.0+ is installed and the OS is on the
[FIPS 140-3 supported OS list](https://help.splunk.com/?resourceId=Splunk_FIPS_supported_OS).
On RHEL 8 / 9, the OS must be in FIPS mode (`fips-mode-setup
--check`).

## "kvstore did not start" after upgrade to Splunk 9.4 / 10.0

**Cause** — KV Store 7.0+ EKU + chain validation kicked in; the
existing cert no longer satisfies the check.

**Fix**:

```bash
# Run the documented check
$SPLUNK_HOME/bin/splunk cmd openssl verify -verbose -x509_strict \
    -CAfile <sslRootCAPath> <serverCert>

# If it returns anything other than OK, re-run this skill:
bash skills/splunk-platform-pki-setup/scripts/setup.sh \
    --phase apply --target indexer-cluster,shc \
    --accept-pki-rotation \
    --admin-password-file /tmp/splunk_admin_password
```

## "Replication peer connection failed" after `--encrypt-replication-port=true`

**Cause** — the cluster is in a mixed state: some peers are still
on `[replication_port://9887]` (cleartext) while others are on
`[replication_port-ssl://9887]`. The two stanzas are mutually
exclusive at the bundle level but during a rolling restart there
is a window where peers haven't restarted yet.

**Fix**: use the searchable rolling-restart mode (default), and
ensure ALL peers restart in one wave. Check the cluster manager
status:

```bash
$SPLUNK_HOME/bin/splunk show cluster-status --verbose
```

If peers report "search broken" because of replication failure,
roll the slowest peers explicitly with `--phase peer-offline` +
restart.

## "deployment client cannot validate deployment server cert"

**Cause** — `deploymentclient.conf [target-broker:deploymentServer]
sslVerifyServerCert = true` is on but the client doesn't trust
the DS's CA.

**Fix**:

```bash
# Confirm the trust anchor is on the client
ls /opt/splunk/etc/auth/cacert.pem

# If empty/wrong, re-run align-cli-trust.sh
bash pki/install/align-cli-trust.sh ...
```

## SAML SSO breaks after rotating SP signing cert

**Cause** — the IdP doesn't accept the new signing key.

**Fix**: export new SP metadata from Splunk Web (Settings →
Authentication → SAML → Metadata), upload to the IdP, test SSO
with a non-admin account.

## "openssl s_client" connects but Splunk REST returns 401

**Cause** — TLS handshake works but `requireClientCert=true` is
set on splunkd 8089 and the caller didn't present a client cert
matching `sslCommonNameToCheck`.

**Fix**:

```bash
# Test with an explicit client cert
$SPLUNK_HOME/bin/splunk cmd openssl s_client \
    -connect <host>:8089 \
    -cert <client-cert>.pem -key <client-key>.pem
```

If the operator never intended splunkd mTLS, set
`--enable-mtls s2s,hec` (default) instead of `all`.

## Where to look

| Symptom | Log / endpoint |
|---|---|
| TLS handshake | `$SPLUNK_HOME/var/log/splunk/splunkd.log` (grep for `SSL`, `TLS`, `cert`, `verify`) |
| Web TLS | `$SPLUNK_HOME/var/log/splunk/web_service.log` |
| KV Store | `$SPLUNK_HOME/var/log/splunk/mongod.log` |
| Health | `/services/server/health/splunkd` REST + `$SPLUNK_HOME/var/log/health.log` |
| Cert inventory | SSL Certificate Checker (Splunkbase 3172) → `index=ssl_certificate_checker` |
| Cluster status | `$SPLUNK_HOME/bin/splunk show cluster-status --verbose` |
| SHC status | `$SPLUNK_HOME/bin/splunk show shcluster-status --verbose` |

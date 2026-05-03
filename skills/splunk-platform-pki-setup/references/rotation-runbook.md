# Rotation Runbook

The skill renders this as `pki/rotate/plan-rotation.md` with
operator-substituted FQDNs and credentials. This doc is the
canonical narrative.

## Scope

Cert rotation across an indexer cluster + SHC + supporting roles
(LM, DS, MC, HF, UF fleet) requires a coordinated sequence so the
cluster never stops accepting search / ingest. The skill DOES NOT
exec the rolling restart itself — it emits a runbook the operator
runs and delegates to
[`splunk-indexer-cluster-setup`](../../splunk-indexer-cluster-setup/SKILL.md)
for the rolling restart.

This matches the repo precedent set by
`splunk-indexer-cluster-setup`: cluster `pass4SymmKey` rotation is
operator-orchestrated, not skill-orchestrated. Cert rotation
follows the same separation of concerns.

## Prerequisites

- The new cert chain has been minted (Private mode) or returned
  by the CA (Public mode).
- `verify-leaf.sh` returned `OK` for every leaf.
- `kv-store-eku-check.sh` returned `OK` for every server leaf.
- `splunk.secret` is identical (SHA-256 match) across cluster
  members.
- The operator has a rollback PEM directory at
  `pki/install/_backup/`.
- A maintenance window has been communicated.

## Sequence

### 0. Pre-flight

```bash
bash skills/splunk-platform-pki-setup/scripts/setup.sh \
    --phase preflight \
    --target indexer-cluster,shc,license-manager,deployment-server,monitoring-console \
    --cm-fqdn cm01.example.com \
    --admin-password-file /tmp/splunk_admin_password
```

Refuses to continue if any check fails.

### 1. Stage new cluster bundle

The renderer already wrote the bundle drop-in to
`splunk-platform-pki-rendered/pki/distribute/cluster-bundle/`.
Copy it to the cluster manager's `master-apps/`:

```bash
scp -r splunk-platform-pki-rendered/pki/distribute/cluster-bundle/master-apps/000_pki_trust \
    cm01.example.com:/opt/splunk/etc/master-apps/
```

### 2. Stage per-peer leaf certs and write per-host overlay

For each peer host, copy its leaf cert + key + CA bundle and run
the install helper. `install-leaf.sh` does TWO things:

- Copies the PEMs to `$SPLUNK_HOME/etc/auth/myssl/<host>/` with
  correct perms (0600 key, 0644 cert).
- Writes the per-host `[sslConfig] serverCert = ...` overlay to
  `$SPLUNK_HOME/etc/system/local/server.conf` (idempotent, with
  `### BEGIN/END splunk-platform-pki-setup [splunkd]` markers).

```bash
for peer in idx01 idx02 idx03; do
  scp splunk-platform-pki-rendered/pki/signed/splunkd-${peer}.example.com.{pem,key} \
      ${peer}.example.com:/tmp/
  scp splunk-platform-pki-rendered/pki/install/cabundle.pem \
      ${peer}.example.com:/tmp/cabundle.pem
  ssh ${peer}.example.com \
      "bash /tmp/install-leaf.sh \
           --target splunkd \
           --host ${peer}.example.com \
           --cert /tmp/splunkd-${peer}.example.com.pem \
           --key  /tmp/splunkd-${peer}.example.com.key \
           --ca   /tmp/cabundle.pem \
           --ssl-password-file /tmp/leaf-pwd"
done
```

`--ssl-password-file` writes the operator-supplied plaintext to
`sslPassword` in the overlay; on first restart Splunk encrypts it
with `splunk.secret`. Omit when the leaf key is unencrypted
(e.g. PKCS#8 nocrypt for Edge Processor).

When `--encrypt-replication-port=true`, also run:

```bash
for peer in idx01 idx02 idx03; do
  ssh ${peer}.example.com \
      "REPLICATION_PEER_NAMES='idx01,idx02,idx03' \
       bash /tmp/install-leaf.sh \
           --target replication \
           --host ${peer}.example.com \
           --cert /tmp/replication-${peer}.example.com.pem \
           --key  /tmp/replication-${peer}.example.com.key \
           --ca   /tmp/cabundle.pem \
           --ssl-password-file /tmp/leaf-pwd"
done
```

This appends the `[replication_port-ssl://9887]` stanza to each
peer's `etc/system/local/server.conf` overlay (the cluster bundle
deliberately does NOT carry that stanza — it would resolve to the
same literal serverCert path on every peer otherwise).

The install helper also copies the new CA bundle into
`$SPLUNK_HOME/etc/auth/cacert.pem` so the local `splunk` CLI
works after rotation.

### 3. Bundle validate + apply (delegated)

```bash
bash skills/splunk-indexer-cluster-setup/scripts/setup.sh \
    --phase bundle-validate \
    --cluster-manager-uri https://cm01.example.com:8089 \
    --admin-password-file /tmp/splunk_admin_password

bash skills/splunk-indexer-cluster-setup/scripts/setup.sh \
    --phase bundle-apply \
    --cluster-manager-uri https://cm01.example.com:8089 \
    --admin-password-file /tmp/splunk_admin_password
```

`bundle-apply` triggers a peer rolling restart automatically when
the bundle includes restart-required changes (per `[triggers]` in
the bundle's `app.conf`). The skill's `000_pki_trust/default/app.conf`
is set to require restart.

### 4. Searchable rolling restart of the indexer cluster (delegated)

If the bundle apply did not already roll the cluster (e.g. only
trust-anchor changed), force a searchable rolling restart:

```bash
bash skills/splunk-indexer-cluster-setup/scripts/setup.sh \
    --phase rolling-restart --rolling-restart-mode searchable \
    --cluster-manager-uri https://cm01.example.com:8089 \
    --admin-password-file /tmp/splunk_admin_password
```

### 5. Stage non-clustered roles (LM, DS, MC, single SH, HF)

For each non-clustered host:

```bash
scp splunk-platform-pki-rendered/pki/signed/splunkd-${host}.example.com.{pem,key} \
    ${host}.example.com:/opt/splunk/etc/auth/myssl/${host}/
scp -r splunk-platform-pki-rendered/pki/distribute/standalone/000_pki_trust \
    ${host}.example.com:/opt/splunk/etc/apps/
ssh ${host}.example.com "/opt/splunk/bin/splunk restart"
```

### 6. SHC member rotation (deployer push + member rolling restart)

```bash
# Stage on the deployer
scp -r splunk-platform-pki-rendered/pki/distribute/shc-deployer/shcluster/apps/000_pki_trust \
    deployer01.example.com:/opt/splunk/etc/shcluster/apps/

# Stage per-member leaves out of band
for member in sh01 sh02 sh03; do
  scp splunk-platform-pki-rendered/pki/signed/splunkd-${member}.example.com.{pem,key} \
      ${member}.example.com:/opt/splunk/etc/auth/myssl/${member}.example.com/
done

# On the deployer, push the bundle (the captain rolls members one by one)
ssh deployer01.example.com \
    "/opt/splunk/bin/splunk apply shcluster-bundle -target https://captain01.example.com:8089"
```

### 7. Roll the forwarder fleet (delegated)

Use `splunk-agent-management-setup` to push the new
`outputs.conf` overlay (with `clientCert` and updated
`sslVerifyServerName`) and roll the UF fleet.

```bash
bash skills/splunk-agent-management-setup/scripts/setup.sh \
    --phase apply \
    ...
```

### 8. Validate end-to-end

```bash
bash skills/splunk-platform-pki-setup/scripts/validate.sh \
    --target indexer-cluster,shc,license-manager,deployment-server,monitoring-console \
    --admin-password-file /tmp/splunk_admin_password
```

This runs:

- `openssl s_client -connect <host>:8089` per cluster member and
  asserts the new SAN.
- KV Store handshake check against each SHC member.
- `splunk show-decrypted` round-trip on `sslPassword`.
- REST GET `/services/server/info` per host and asserts the
  trust anchor.

## Rollback

If `validate` fails:

1. Restore the backup PEMs:

   ```bash
   for host in idx01 idx02 idx03 sh01 sh02 sh03 ...; do
     ssh ${host}.example.com \
         "cp /opt/splunk/etc/auth/myssl/_backup/* /opt/splunk/etc/auth/myssl/"
   done
   ```

2. Re-run `bundle-rollback`:

   ```bash
   bash skills/splunk-indexer-cluster-setup/scripts/setup.sh \
       --phase bundle-rollback \
       --cluster-manager-uri https://cm01.example.com:8089 \
       --admin-password-file /tmp/splunk_admin_password
   ```

3. Searchable rolling restart back to the previous bundle:

   ```bash
   bash skills/splunk-indexer-cluster-setup/scripts/setup.sh \
       --phase rolling-restart --rolling-restart-mode searchable \
       --cluster-manager-uri https://cm01.example.com:8089 \
       --admin-password-file /tmp/splunk_admin_password
   ```

4. Re-run `validate`.

## Replication-port migration (cleartext → SSL)

When `--encrypt-replication-port=true` is set, the bundle
includes `[replication_port-ssl://9887]` and the
`swap-replication-port-to-ssl.sh` migration helper. This change
**requires a full cluster rolling restart** because the
replication channel is renegotiated. Plan for an extra restart
window beyond the bundle apply.

## SAML SP signing cert rotation

After installing the new SAML SP signing cert, the IdP must be
notified so it accepts the new signing key. Operator-driven:

1. Export the new SP signing cert as part of SP metadata
   (Splunk Web → Settings → Authentication → SAML → Generate
   metadata).
2. Upload the new metadata to the IdP (Okta / Entra / AD FS /
   etc.).
3. Test SSO with a non-admin account before completing rotation.

## Edge Processor cert rotation

Out of band of the indexer cluster rotation. Use the EP UI / REST
to upload the new cert pair, then restart the EP instance:

```bash
bash skills/splunk-edge-processor-setup/scripts/setup.sh \
    --phase apply --ep-fqdn ep01.example.com ...
```

## Splunk Cloud forwarder fleet

UFCP-managed. Re-download the package from Splunk Cloud, push via
`splunk-agent-management-setup`, restart UFs.

## Cadence

| Cert lifetime | Rotation cadence | Notes |
|---|---|---|
| 90 days (Let's Encrypt) | every ~60 days | Automate; never manual |
| 397 days (public CA baseline) | every ~10 months | Automate or schedule |
| 825 days (private CA leaf) | every ~24 months | Schedule |
| 1825 days (Intermediate CA) | every ~5 years | Plan + test |
| 3650 days (Root CA) | every 8-10 years | Major project |

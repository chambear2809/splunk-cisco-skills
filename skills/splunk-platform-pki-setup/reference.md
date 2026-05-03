# Splunk Platform PKI Setup — Reference

Read this before any apply phase. Each section anchors to a Splunk
upstream doc URL kept in
[references/authoritative-sources.md](references/authoritative-sources.md).

## Operating modes

The skill ships two end-to-end modes selected with `--mode`:

- `private` — Operator becomes the certificate authority. The
  renderer emits `pki/private-ca/` scripts that build a Root CA
  (offline, 3650 d) and an optional Intermediate CA (online,
  1825 d). Leaves are signed by the Intermediate when present, else
  by the Root.
- `public` — Operator's third-party CA fulfills CSRs. The renderer
  emits per-host CSRs in `pki/csr-templates/` and a handoff
  Markdown for HashiCorp Vault PKI, ACME / cert-manager, Microsoft
  AD CS, EJBCA, or any commercial CA. The skill installs and
  verifies the returned signed PEMs.

Both modes share the same install / verify / distribute layer, the
same component cert matrix, the same mTLS / hostname-validation /
KV-Store-EKU controls, and the same delegated rotation runbook.

## Why a separate skill from `splunk-enterprise-public-exposure-hardening`

The hardening skill ships
[`splunk/certificates/verify-certs.sh`](../splunk-enterprise-public-exposure-hardening/scripts/render_assets.py)
and `generate-csr-template.sh` and a
`handoff/certificate-procurement.md`, but it is a hardening lens
scoped to the four edge surfaces (Web 8000, HEC 8088, S2S 9997,
splunkd 8089) of one or two SH / HF roles facing the public
internet. PKI lifecycle has a different shape: CA generation,
intermediate hierarchies, per-component identity matrices,
KV-Store EKU constraints, federation client certs,
deployment-server trust pairing, replication-port TLS migration,
SAML SP signing cert separation, and rotation across an entire
cluster. Folding that into the hardening skill would balloon its
scope and confuse its existing public-internet risk gate.

The two skills cross-reference. The hardening skill **consumes**
cert paths the PKI skill provisions; the PKI skill **consumes**
the hardening skill's `--enable-fips` / `--fips-version` semantics
when both run together.

## Component cert matrix

Source for every config knob below: the Splunk admin manual
`server.conf`, `web.conf`, `inputs.conf`, `outputs.conf`,
`authentication.conf`, `deploymentclient.conf` reference, plus the
"Configure TLS certificates for inter-Splunk communication" /
"Configure Splunk Web to use TLS certificates" / "Configure Splunk
indexing and forwarding to use TLS certificates" docs. Frozen in
[references/authoritative-sources.md](references/authoritative-sources.md).

### Splunk Web (8000)

`web.conf [settings]`:

```
enableSplunkWebSSL = true
serverCert         = /opt/splunk/etc/auth/myssl/sh01.example.com/sh01-web-cert.pem
privKeyPath        = /opt/splunk/etc/auth/myssl/sh01.example.com/sh01-web-key.pem
caCertPath         = /opt/splunk/etc/auth/myssl/cabundle.pem
sslPassword        = <encrypted on first restart>
cipherSuite        = <from --tls-policy>
sslVersions        = tls1.2
ecdhCurves         = prime256v1, secp384r1, secp521r1
```

### splunkd REST / inter-Splunk (8089)

`server.conf [sslConfig]`:

```
enableSplunkdSSL          = true
serverCert                = /opt/splunk/etc/auth/myssl/sh01.example.com/sh01-splunkd-cert.pem
sslPassword               = <encrypted on first restart>
sslRootCAPath             = /opt/splunk/etc/auth/myssl/cabundle.pem
caTrustStore              = splunk            # or splunk,os to merge with OS store
caTrustStorePath          = /etc/ssl/certs/ca-certificates.crt   # Linux only
cipherSuite               = <from --tls-policy>
sslVersions               = tls1.2
sslVersionsForClient      = tls1.2            # splunkd-as-client (DC -> DS, peer -> CM)
ecdhCurves                = prime256v1, secp384r1, secp521r1
requireClientCert         = false             # mTLS opt-in via --enable-mtls
sslCommonNameToCheck      = <CSV of CNs>      # only with requireClientCert=true
sslAltNameToCheck         = <CSV of SANs>     # only with requireClientCert=true
```

### S2S receivers (9997)

`inputs.conf`:

```
[splunktcp-ssl:9997]
disabled = 0

[SSL]
serverCert         = /opt/splunk/etc/auth/myssl/idx01.example.com/idx01-s2s-cert.pem
sslPassword        = <encrypted on first restart>
requireClientCert  = true                    # default for --enable-mtls=s2s
sslVersions        = tls1.2
cipherSuite        = <from --tls-policy>
sslCommonNameToCheck = forwarder01.example.com,forwarder02.example.com
```

### S2S forwarders

`outputs.conf`:

```
[tcpout:idxc_main]
server                  = idx01.example.com:9997,idx02.example.com:9997,idx03.example.com:9997
clientCert              = /opt/splunkforwarder/etc/auth/myssl/uf01-s2s-cert.pem
sslPassword             = <encrypted on first restart>
useClientSSLCompression = true
sslVerifyServerCert     = true
sslVerifyServerName     = true
sslCommonNameToCheck    = idx01.example.com,idx02.example.com,idx03.example.com

# per-indexer SAN override (optional, when each indexer presents a different cert)
[tcpout-server://idx01.example.com:9997]
sslCommonNameToCheck = idx01.example.com

[tcpout-server://idx02.example.com:9997]
sslCommonNameToCheck = idx02.example.com
```

### HEC (8088)

`inputs.conf [http]`:

```
[http]
enableSSL              = 1
serverCert             = /opt/splunk/etc/auth/myssl/sh01.example.com/sh01-hec-cert.pem
sslPassword            = <encrypted on first restart>
requireClientCert      = false               # set to true for --enable-mtls=hec
allowSslRenegotiation  = false
allowSslCompression    = false
sslVersions            = tls1.2
cipherSuite            = <from --tls-policy>
```

### KV Store

KV Store consumes the splunkd `[sslConfig]` certs. Per
[Preparing custom certificates for use with KV store](https://docs.splunk.com/Documentation/Splunk/9.4.2/Admin/CustomCertsKVstore),
KV Store 7.0+ enforces a CA verification check at startup. The
renderer:

1. Mints leaves with **dual EKU** (`serverAuth` + `clientAuth`)
   so KV Store accepts them.
2. Runs the documented check before declaring a host ready:

```bash
$SPLUNK_HOME/bin/splunk cmd openssl verify -verbose -x509_strict \
  -CAfile <sslRootCAPath> <serverCert>
# expected exit code 0 and stdout: <serverCert>: OK
```

If the verification returns anything other than `OK`, the renderer
flags the host as not ready and refuses to apply.

### Indexer cluster — bundle distribution

Per-peer leaf certs go through the **cluster bundle**. The
renderer emits:

```
pki/distribute/cluster-bundle/master-apps/000_pki_trust/local/
├── server.conf      # [sslConfig] with sslRootCAPath only (per-peer serverCert is host-specific)
├── inputs.conf      # [splunktcp-ssl:9997] + [SSL] common settings
└── (server.conf may also include [replication_port-ssl://9887] when --encrypt-replication-port=true)
```

Per-peer `serverCert` is staged out-of-band on each peer host
because it is host-specific (the cluster bundle is identical
across peers). The rotation runbook walks the operator through
both steps.

### Indexer cluster — replication port (9887)

Cleartext default: `[replication_port://9887]`. TLS-encrypted
form (mutually exclusive):

```
[replication_port-ssl://9887]
rootCA                = /opt/splunk/etc/auth/myssl/cabundle.pem
serverCert            = /opt/splunk/etc/auth/myssl/idx01.example.com/idx01-replication-cert.pem
sslPassword           = <encrypted on first restart>
sslCommonNameToCheck  = idx01.example.com,idx02.example.com,idx03.example.com
requireClientCert     = true
```

The renderer's `swap-replication-port-to-ssl.sh` migration helper
DELETES `[replication_port://9887]` and ADDS the SSL stanza in the
same edit so the cluster never has both stanzas active. Opt-in via
`--encrypt-replication-port=true` because the migration is
invasive (a full cluster rolling restart is required).

### Search-head cluster (SHC)

Per-member leaf certs go through the **SHC deployer**. The
renderer emits:

```
pki/distribute/shc-deployer/shcluster/apps/000_pki_trust/local/
├── server.conf      # [sslConfig] common settings
├── web.conf         # [settings] Splunk Web TLS for the SHC member
└── inputs.conf      # if HEC runs on SHC members
```

Per-member `serverCert` is staged out-of-band on each member host.
The deployer push is delegated to
[`splunk-agent-management-setup`](../splunk-agent-management-setup/SKILL.md).

`pass4SymmKey` for `[shclustering]` is owned by host-setup /
agent-management, not this skill.

### License Manager / peers

`server.conf [sslConfig]` aligned with the cluster trust store on
both LM and peers. License-peer registration uses the splunkd
8089 channel, so the LM cert needs the same `sslVerifyServerName`
posture as any other inter-Splunk hop.

### Deployment Server / clients

DS exposes splunkd 8089. Clients connect via
`deploymentclient.conf`:

```
[target-broker:deploymentServer]
targetUri               = ds01.example.com:8089
sslVerifyServerCert     = true
sslVerifyServerName     = true
sslCommonNameToCheck    = ds01.example.com
```

When `--enable-mtls splunkd` covers the DS, each client also gets
a `clientCert` / `clientKey` pair. Per
[Secure deployment servers and clients using certificate authentication](https://docs.splunk.com/Documentation/Splunk/latest/Security/Securingyourdeploymentserverandclients).

### Monitoring Console

MC distributes `trusted.pem` to its search peers. The renderer
emits `align-trusted-pem.sh` that copies the new CA bundle to
`$SPLUNK_HOME/etc/auth/distServerKeys/trusted.pem` on each MC
search peer.

### Federated Search

Per-provider client cert + `--cacert` snippet for `splunk` /
`curl` REST calls. Consumed by
[`splunk-federated-search-setup`](../splunk-federated-search-setup/SKILL.md)'s
provider preflight.

### DMZ Heavy Forwarder

Outputs.conf client cert with per-indexer SAN matching, identical
to the UF outputs overlay. Coexists with the public-exposure
skill's DMZ HF pattern.

### Universal Forwarders (Enterprise destination)

Per-fleet `outputs.conf` overlay rendered under
`pki/distribute/forwarder-fleet/<group>/`. Supports indexer
discovery by aligning the cluster manager cert into the UF trust
bundle.

### Universal Forwarders (Splunk Cloud destination)

The skill **refuses** to issue certs and points at the
[Universal Forwarder Credentials Package](https://help.splunk.com/?resourceId=Forwarder_Forwarder_ConfigSCUFCredentials).
The UFCP ships pre-bundled `server.pem`, `cacert.pem`, and
`outputs.conf`; Splunk Cloud owns the trust anchor.

### Splunk REST CLI client trust

After cert rotation, `$SPLUNK_HOME/etc/auth/cacert.pem` (the file
the local `splunk` CLI trusts when calling REST) must align with
the new CA bundle, otherwise local `splunk` invocations break.
The renderer emits `align-cli-trust.sh` that copies the new CA
bundle into place with `chmod 0644`.

### Splunk MCP Server

`mcp.conf [server] ssl_verify=true` consumes the splunkd cert.
Aligned with the new trust anchor; handed off to
[`splunk-mcp-server-setup`](../splunk-mcp-server-setup/SKILL.md).

### Splunk Edge Processor

EP TLS / mTLS uses a separate file naming convention per
[Edge Processor: Obtain TLS certificates](https://help.splunk.com/data-management/transform-and-route-data/use-edge-processors-for-splunk-cloud-platform/10.0.2503/get-data-into-edge-processors/obtain-tls-certificates-for-data-sources-and-edge-processors):

| File | Role |
|---|---|
| `ca_cert.pem` | CA cert uploaded to both EP and the data source |
| `edge_server_cert.pem` | EP server cert (presented to data sources) |
| `edge_server_key.pem` | EP server private key (PKCS#8, no passphrase) |
| `data_source_client_cert.pem` | Data-source client cert (presented to EP) |
| `data_source_client_key.pem` | Data-source client private key (PKCS#8, no passphrase) |

Renderer supports both **RSA-2048** (default) and **ECDSA P-256**
signing paths via `--key-algorithm`. Distribution is via EP UI /
REST upload; the renderer emits placeholders + an
`upload-via-rest.sh.example` and hands off to
[`splunk-edge-processor-setup`](../splunk-edge-processor-setup/SKILL.md).

### SAML SP signing certificate

`authentication.conf [<saml-authSettings>]`:

```
signAuthnRequest               = true
signedAssertion                = true
signatureAlgorithm             = RSA-SHA384
InboundSignatureAlgorithm      = RSA-SHA384;RSA-SHA512
idpCertPath                    = /opt/splunk/etc/auth/idpCerts/azure-idp.crt
```

The SP signing cert is a separate identity from the splunkd TLS
cert and lives in `$SPLUNK_HOME/etc/auth/idpCerts/`. Rotation
requires re-uploading SP metadata at the IdP (operator-driven —
the skill emits `pki/distribute/saml-sp/README.md` walkthrough).

### LDAPS

Splunk reads system OpenLDAP `ldap.conf` for TLS settings:

```
TLS_PROTOCOL_MIN  3.3                 # 3.3 = TLS 1.2
TLS_CIPHER_SUITE  <from --tls-policy>
TLS_CACERT        /opt/splunk/etc/auth/myssl/cabundle.pem
TLS_REQCERT       demand              # require + validate server cert
```

Combined with `authentication.conf`:

```
[<ldap-strategy>]
host        = ldaps.example.com
port        = 636
SSLEnabled  = true
```

Coexists with the public-exposure skill's `--ldap-ssl-enabled`.

## Cross-cutting controls

### TLS protocol policy

`--tls-policy {splunk-modern|fips-140-3|stig}`:

| Preset | Cipher set summary | TLS versions | Key algos | Sig algos | Source |
|---|---|---|---|---|---|
| `splunk-modern` (default) | ECDHE-(EC)DSA/RSA-AES{128,256}-GCM-SHA{256,384} + ECDHE-AES{128,256}-SHA{256,384} fallbacks; ECDH curves prime256v1, secp384r1, secp521r1 | tls1.2 | RSA-2048+, ECDSA P-256+ | RSA-SHA256+, ECDSA-SHA256+ | [About TLS encryption and cipher suites](https://docs.splunk.com/Documentation/Splunk/latest/Security/AboutTLSencryptionandciphersuites) |
| `fips-140-3` | NIST AEAD only (no CBC, no SHA-1, no RSA-1024, no anonymous DH) | tls1.2 | RSA-2048+, ECDSA P-256+ | RSA-SHA256+, ECDSA-SHA256+ | [Secure Splunk Enterprise with FIPS](https://help.splunk.com/en/splunk-enterprise/administer/manage-users-and-security/10.2/establish-and-maintain-compliance-with-fips-and-common-criteria-in-splunk-enterprise/secure-splunk-enterprise-with-fips) |
| `stig` | DISA-STIG-aligned subset of `splunk-modern` | tls1.2 | RSA-2048+, ECDSA P-256+ | RSA-SHA256+ | `splunk-enterprise-public-exposure-hardening/references/disa-stig-cross-reference.md` |

Splunk's [TLS-protocol-version doc](https://help.splunk.com/splunk-enterprise/administer/manage-users-and-security/10.2/secure-splunk-platform-communications-with-transport-layer-security-certificates/configure-tls-protocol-version-support-for-secure-connections-between-splunk-platform-instances)
lists the supported set as `SSLv3` (deprecated), `TLS1.0`
(deprecated, 9.4+), `TLS1.1` (deprecated, 9.4+), `TLS1.2`. **TLS 1.3
is not yet a documented Splunk-supported TLS version.** Pass
`--allow-deprecated-tls` to relax the floor (not recommended).

### FIPS lifecycle

`--fips-mode {none|140-2|140-3}` writes to `splunk-launch.conf`:

```
SPLUNK_FIPS_VERSION = 140-3
```

Splunk 10.0+ ships both modules. Phase 1 (upgrade to 10.0 in
140-2) and Phase 2 (flip to 140-3) per the
[Splunk FIPS upgrade doc](https://help.splunk.com/en/splunk-enterprise/administer/install-and-upgrade/10.2/upgrade-or-migrate-splunk-enterprise/upgrade-and-migrate-your-fips-mode-deployments).
The PKI skill consumes the public-exposure-hardening skill's
`--enable-fips` / `--fips-version` rather than re-defining; refuses
to apply when the cluster is mid-Phase-1 (some peers still on
pre-10 FIPS module). NIST deprecates FIPS 140-2 on
**2026-09-21**, so the default for new deployments is `140-3`.

Phase 2 flip on each host:

```
# Stop Splunk
$SPLUNK_HOME/bin/splunk stop

# Edit splunk-launch.conf
echo "SPLUNK_FIPS_VERSION = 140-3" >> $SPLUNK_HOME/etc/splunk-launch.conf

# Restart
$SPLUNK_HOME/bin/splunk start
```

The renderer's `install-fips-launch-conf.sh` performs this exact
edit idempotently.

### Validity-day caps

| Identity type | Default | Cap (preflight refuses higher) |
|---|---|---|
| Internal Root CA | 3650 d | unlimited (operator-supplied) |
| Internal Intermediate CA | 1825 d | unlimited |
| Server / client leaf (private mode) | 825 d | 825 d |
| Server / client leaf (public mode) | 397 d | warns at 90 d (LE floor), 397 d (CA/B baseline); operator's CA enforces own cap |

Override with `--root-ca-days`, `--intermediate-ca-days`,
`--leaf-days`. Public-mode leaves longer than 397 d are accepted
but generate a warning because most public CAs cap at 397 days per
the CA/Browser Forum baseline.

### Key format and permissions

- Default private key format: encrypted PKCS#1 PEM. Matches
  Splunk's `splunk cmd openssl genpkey -aes-256-cbc` example in
  [How to create and sign your own TLS certificates](https://help.splunk.com/en/splunk-enterprise/administer/manage-users-and-security/10.0/secure-splunk-platform-communications-with-transport-layer-security-certificates/how-to-create-and-sign-your-own-tls-certificates).
- `--key-format pkcs8` switches to PKCS#8 (`BEGIN PRIVATE KEY`),
  required for Edge Processor (EP doc says "private key must be
  decrypted") and Splunk DB Connect.
- `chmod 0600 <key>` and `chmod 0644 <cert>` set explicitly
  before Splunk starts so its restart-time permission flap starts
  from a known baseline.
- `verify-leaf.sh` uses `splunk show-decrypted` to confirm the
  encrypted `sslPassword` (Splunk encrypts `sslPassword` with
  `splunk.secret` on first restart) round-trips back to the
  plaintext the operator supplied via `--leaf-key-password-file`.

### mTLS

`--enable-mtls {none|s2s|hec|splunkd|all}`:

| Surface | When `--enable-mtls` covers it | Knobs flipped |
|---|---|---|
| splunkd 8089 | `splunkd` or `all` | `requireClientCert=true` + `sslCommonNameToCheck` / `sslAltNameToCheck` populated |
| S2S 9997 | `s2s` or `all` | `requireClientCert=true` in `inputs.conf [SSL]`; `clientCert` on every forwarder `outputs.conf` |
| HEC 8088 | `hec` or `all` | `requireClientCert=true` in `inputs.conf [http]`; HEC clients must present cert |

Default is `s2s,hec`. Splunkd mTLS is opt-in because turning it on
breaks operator tooling that does not present a client cert.

### Hostname validation

Default `sslVerifyServerName=true` everywhere supported, with
`sslCommonNameToCheck`/`sslAltNameToCheck` populated from the
per-host SAN list in `template.example`. Per
[Configure TLS certificate host name validation](https://docs.splunk.com/Documentation/Splunk/latest/Security/EnableTLSCertHostnameValidation).

### Default-cert refusal

Preflight reuses the existing
[`references/default-cert-fingerprints.json`](../splunk-enterprise-public-exposure-hardening/references/default-cert-fingerprints.json)
catalogue from the public-exposure-hardening skill and refuses
to declare a host ready while default subject tokens
(`SplunkServerDefaultCert`, `SplunkCommonCA`,
`SplunkWebDefaultCert`) are present in any active cert.

### `splunk.secret` parity

Preflight checks the SHA-256 of `$SPLUNK_HOME/etc/auth/splunk.secret`
across cluster members. Divergent secrets cause `sslPassword`
re-encryption to fail unpredictably on restart. If divergence
detected, refuses to apply and points to the public-exposure
skill's `rotate-splunk-secret.sh` helper.

## Apply guard

`apply` and `all` require `--accept-pki-rotation`. The flag
acknowledges that:

- The new cert chain has been verified (`verify-leaf.sh` returned
  `OK`).
- A rolling restart of the indexer cluster and SHC will follow
  (delegated).
- SAML / LDAPS / Edge Processor / Splunk Cloud handoffs will be
  completed.
- The operator has a rollback plan (the previous PEM directory is
  preserved by the renderer at `pki/install/_backup/`).

The render and preflight phases never need this flag.

## Rotation order (delegated)

The skill emits `pki/rotate/plan-rotation.md` describing the order
of operations. The skill does not exec the rolling restart
itself.

```
1. Stage new trust anchor + per-peer leaves into the cluster bundle
   (already rendered).

2. Bundle validate + apply via splunk-indexer-cluster-setup:
     bash skills/splunk-indexer-cluster-setup/scripts/setup.sh \
         --phase bundle-validate --cluster-manager-uri https://cm01:8089 \
         --admin-password-file /tmp/splunk_admin_password
     bash skills/splunk-indexer-cluster-setup/scripts/setup.sh \
         --phase bundle-apply --cluster-manager-uri https://cm01:8089 \
         --admin-password-file /tmp/splunk_admin_password

3. Searchable rolling restart of the indexer cluster:
     bash skills/splunk-indexer-cluster-setup/scripts/setup.sh \
         --phase rolling-restart --rolling-restart-mode searchable \
         --cluster-manager-uri https://cm01:8089 \
         --admin-password-file /tmp/splunk_admin_password

4. Stage new leaf certs on each non-clustered role (LM, DS, MC,
   single SH, HF) and run `splunk restart`.

5. SHC bundle apply at the deployer + member rolling restart:
     splunk apply shcluster-bundle -target https://captain01.example.com:8089
     # the captain rolls members one by one

6. Roll forwarder fleet via splunk-agent-management-setup.

7. Validate end-to-end:
     bash skills/splunk-platform-pki-setup/scripts/validate.sh \
         --target indexer-cluster,shc,license-manager,deployment-server \
         --admin-password-file /tmp/splunk_admin_password
```

This matches the repo precedent at
[`splunk-indexer-cluster-setup`](../splunk-indexer-cluster-setup/SKILL.md):
"Cluster `pass4SymmKey` rotation… does not orchestrate that
rolling rotation."

## Out of Scope

- Talking to a CA (Public-PKI mode renders CSR + handoff only).
- Rolling restart and cluster bundle apply (delegated).
- Splunk Web HSTS / CSP / browser security headers (owned by
  `splunk-enterprise-public-exposure-hardening`).
- TLS 1.3 (not yet documented as a Splunk-supported TLS version).
- FIPS-validated OpenSSL build (operator owns the FIPS module).
- Splunk Cloud cert issuance (refuses; UFCP handoff for forwarders;
  Splunk Support ticket for HEC custom-domain BYOC).
- Java keystore / truststore (JKS / PKCS#12) for DB Connect.
- CRL / OCSP responder hosting.
- HSM integration for the CA private key (references only).
- Splunk SOAR PKI (separate stack).
- Splunk Mobile / Secure Gateway certs.
- IdP-side configuration (Okta / Entra / AD FS).
- Compliance attestation (PCI / HIPAA / FedRAMP / SOC 2 /
  DISA STIG sign-off). The skill renders STIG-aligned configs and
  cites NIST controls but does not certify.

# Component Cert Matrix

Every TLS surface the skill targets, with the exact config knobs
the renderer writes. Each row anchors to a doc in
[authoritative-sources.md](authoritative-sources.md).

| Surface | Conf file | Stanza | Key knobs | mTLS knob | Default port |
|---|---|---|---|---|---|
| Splunk Web | `web.conf` | `[settings]` | `enableSplunkWebSSL`, `serverCert`, `privKeyPath`, `caCertPath`, `sslPassword`, `cipherSuite`, `sslVersions`, `ecdhCurves` | n/a (browser TLS only) | 8000 |
| splunkd REST | `server.conf` | `[sslConfig]` | `enableSplunkdSSL`, `serverCert`, `sslRootCAPath`, `sslPassword`, `cipherSuite`, `sslVersions`, `sslVersionsForClient`, `ecdhCurves`, `caTrustStore`, `caTrustStorePath` | `requireClientCert`, `sslCommonNameToCheck`, `sslAltNameToCheck` | 8089 |
| KV Store | `server.conf` | `[sslConfig]` (shared with splunkd) | dual-EKU `serverAuth`+`clientAuth` requirement, validated by `splunk cmd openssl verify -x509_strict` | inherits from splunkd | KV uses splunkd's TLS |
| S2S receiver | `inputs.conf` | `[splunktcp-ssl:9997]` + `[SSL]` | `serverCert`, `sslPassword`, `cipherSuite`, `sslVersions` | `requireClientCert`, name checks | 9997 |
| S2S forwarder | `outputs.conf` | `[tcpout:<group>]` + `[tcpout-server://host:port]` | `clientCert`, `sslPassword`, `useClientSSLCompression`, `sslVerifyServerCert`, `sslVerifyServerName`, `sslCommonNameToCheck`, `sslAltNameToCheck` | n/a (always presents client cert when configured) | 9997 (out) |
| HEC | `inputs.conf` | `[http]` + per-token | `enableSSL`, `serverCert`, `sslPassword`, `allowSslRenegotiation`, `allowSslCompression` | `requireClientCert` | 8088 |
| Indexer cluster bundle | `master-apps/000_pki_trust/local/server.conf` | `[sslConfig]` | trust-anchor distribution to peers | inherits | n/a |
| Indexer cluster replication port | `server.conf` | `[replication_port-ssl://9887]` (mutually exclusive with `[replication_port://9887]`) | `rootCA`, `serverCert`, `sslPassword`, `sslCommonNameToCheck` | `requireClientCert` | 9887 |
| SHC deployer push | `shcluster/apps/000_pki_trust/local/{server,web,inputs}.conf` | as above | per-member leaves staged out-of-band | inherits | uses splunkd |
| License Manager / peers | `server.conf` | `[sslConfig]` | aligned with cluster trust | inherits | 8089 |
| Deployment Server | `server.conf` | `[sslConfig]` | aligned with cluster trust | per `[sslConfig] requireClientCert` | 8089 |
| Deployment Client | `deploymentclient.conf` | `[target-broker:deploymentServer]` | `sslVerifyServerCert`, `sslVerifyServerName`, `sslCommonNameToCheck` | `clientCert` (when DS requires it) | 8089 (out) |
| Monitoring Console search peers | `distsearch.conf` + `$SPLUNK_HOME/etc/auth/distServerKeys/trusted.pem` | `[tokenExchKeys]` distribution | `trusted.pem` aligned with cluster trust | inherits | 8089 |
| Federated Search provider/consumer | per `splunk-federated-search-setup` | per-provider | per-provider client cert + `--cacert` | inherits | 8089 |
| DMZ Heavy Forwarder | `outputs.conf` + `inputs.conf` | as forwarder + receiver | client cert + per-indexer SAN | as above | 9997 |
| Universal Forwarders (Enterprise destination) | `outputs.conf` overlay | `[tcpout:<group>]` | per fleet | as forwarder | 9997 (out) |
| Universal Forwarders (Splunk Cloud destination) | (skill refuses) | n/a | UFCP delivers `server.pem`, `cacert.pem`, `outputs.conf` | UFCP-managed | 9997 (out, via SCP-managed broker) |
| Splunk REST CLI client trust | `$SPLUNK_HOME/etc/auth/cacert.pem` | n/a | aligned with new CA bundle | n/a | local file |
| Splunk MCP Server | `mcp.conf` | `[server]` | `ssl_verify=true` | inherits splunkd | 8089 (consumed) |
| Splunk Edge Processor — data source ↔ EP | EP REST upload | `ca_cert.pem`, `edge_server_{cert,key}.pem`, `data_source_client_{cert,key}.pem` | RSA-2048 or ECDSA P-256, PKCS#8 keys | EP requires client cert from data source for mTLS | EP-defined |
| SAML SP signing | `authentication.conf` | `[<saml-authSettings>]` | `signAuthnRequest`, `signedAssertion`, `signatureAlgorithm` (`RSA-SHA384` or `RSA-SHA512`), `idpCertPath`, `InboundSignatureAlgorithm` | n/a (signing, not transport TLS) | n/a |
| LDAPS | `authentication.conf` + system `ldap.conf` | `[<ldap-strategy>]` `SSLEnabled=true`; `ldap.conf TLS_PROTOCOL_MIN 3.3 / TLS_CACERT / TLS_REQCERT demand` | n/a (server-only validation) | 636 |

## Bundle vs per-host overlay split

This is the most important design decision in the skill. Splunk's
cluster bundle and SHC deployer bundle are **shared** across every
peer / member: whatever you put in `local/server.conf` ships
identically to every host. That means **per-host settings cannot
live in the bundle** — `serverCert = .../idx01-cert.pem` would
resolve to the same literal file on `idx02`, `idx03`, etc.

The skill therefore splits TLS settings into two layers:

| Setting | Lives in | Why |
|---|---|---|
| `enableSplunkdSSL`, `sslRootCAPath`, `caTrustStore`, `sslVersions`, `sslVersionsForClient`, `cipherSuite`, `ecdhCurves`, `sslVerifyServerCert`, `sslVerifyServerName`, `requireClientCert`, `sslCommonNameToCheck`, `sslAltNameToCheck`, `enableSplunkWebSSL`, `caCertPath` | **Bundle** (`master-apps/000_pki_trust/local/*.conf`) | Cluster-wide policy, identical on every peer |
| `serverCert`, `privKeyPath`, `sslPassword`, `clientCert`, `[replication_port-ssl://9887]` (full stanza) | **Per-host overlay** (`$SPLUNK_HOME/etc/system/local/*.conf`) | Host-specific paths; `install-leaf.sh` writes these |

`install-leaf.sh` writes the per-host overlay automatically with
idempotent `### BEGIN/END splunk-platform-pki-setup [<target>]`
markers, so re-runs replace the prior block without duplicating it.

`--ssl-password-file PATH` is the operator-supplied plaintext
leaf-key passphrase. install-leaf.sh writes it verbatim to the
overlay's `sslPassword` line; on first restart Splunk encrypts it
with `splunk.secret`. If `--ssl-password-file` is omitted, the
script assumes the leaf key is unencrypted (e.g. PKCS#8 nocrypt
for Edge Processor) and skips `sslPassword` entirely.

## Files the renderer emits per surface

```
splunk-platform-pki-rendered/
└── pki/
    ├── private-ca/                     # only when --mode private
    │   ├── create-root-ca.sh
    │   ├── create-intermediate-ca.sh
    │   ├── sign-server-cert.sh
    │   ├── sign-client-cert.sh
    │   ├── sign-saml-sp.sh
    │   ├── openssl-root.cnf
    │   ├── openssl-intermediate.cnf
    │   ├── openssl-leaf-server.cnf
    │   ├── openssl-leaf-client.cnf
    │   ├── openssl-leaf-saml.cnf
    │   └── README.md
    ├── csr-templates/
    │   ├── splunkd-<host>.cnf
    │   ├── web-<host>.cnf
    │   ├── s2s-<host>.cnf
    │   ├── hec-<host>.cnf
    │   ├── replication-<host>.cnf      # only when --encrypt-replication-port=true
    │   ├── shc-member-<host>.cnf
    │   ├── deployment-server.cnf
    │   ├── deployment-client-<host>.cnf  # only when --enable-mtls splunkd or all
    │   ├── license-manager.cnf
    │   ├── monitoring-console.cnf
    │   ├── saml-sp.cnf                  # only when --saml-sp=true
    │   ├── edge-processor-server.cnf    # only when --include-edge-processor=true
    │   ├── edge-processor-client.cnf    # only when --include-edge-processor=true
    │   └── generate-csr.sh
    ├── install/
    │   ├── install-leaf.sh             # cert install + per-host system/local overlay
    │   ├── verify-leaf.sh
    │   ├── kv-store-eku-check.sh
    │   ├── align-cli-trust.sh
    │   ├── install-fips-launch-conf.sh  # only when --fips-mode != none
    │   └── prepare-key.sh               # PKCS#1 ↔ PKCS#8 + chain concat
    ├── distribute/
    │   ├── cluster-bundle/master-apps/000_pki_trust/local/{server,inputs}.conf       # shared policy only
    │   ├── shc-deployer/shcluster/apps/000_pki_trust/local/{server,web,inputs}.conf  # shared policy only
    │   ├── standalone/000_pki_trust/local/{server,web,inputs,outputs,authentication,deploymentclient,splunk-launch}.conf  # shared policy only
    │   ├── standalone/000_pki_trust/system-files/ldap.conf  # only when --ldaps=true
    │   ├── forwarder-fleet/<group>/{outputs-overlay,server-overlay}.conf
    │   ├── edge-processor/{ca_cert,edge_server_cert,edge_server_key,data_source_client_cert,data_source_client_key}.pem.example
    │   ├── edge-processor/upload-via-rest.sh.example
    │   └── saml-sp/{sp-signing.crt,sp-signing.key.placeholder,README.md}
    ├── rotate/
    │   ├── plan-rotation.md
    │   ├── rotate-leaf-host.sh
    │   ├── swap-trust-anchor.sh
    │   ├── swap-replication-port-to-ssl.sh
    │   └── expire-watch.sh
    └── inventory/                       # only after `inventory` phase runs
        └── <host>.json
```

## Per-host overlay layout (written by `install-leaf.sh`)

```
$SPLUNK_HOME/etc/system/local/
├── server.conf
│   ### BEGIN splunk-platform-pki-setup [splunkd]
│   [sslConfig]
│   serverCert  = /opt/splunk/etc/auth/myssl/<host>/<host>-splunkd.pem
│   sslPassword = <plaintext-from---ssl-password-file>     # or omitted
│   ### END splunk-platform-pki-setup [splunkd]
│
│   ### BEGIN splunk-platform-pki-setup [replication]    # if --encrypt-replication-port
│   [replication_port-ssl://9887]
│   disabled              = 0
│   rootCA                = .../cabundle.pem
│   serverCert            = .../<host>-replication.pem
│   sslCommonNameToCheck  = idx01,idx02,idx03
│   sslAltNameToCheck     = idx01,idx02,idx03
│   requireClientCert     = true
│   sslPassword           = <plaintext>
│   ### END splunk-platform-pki-setup [replication]
├── web.conf
│   ### BEGIN splunk-platform-pki-setup [web]
│   [settings]
│   serverCert  = .../<host>-web.pem
│   privKeyPath = .../<host>-web.key
│   sslPassword = <plaintext>
│   ### END splunk-platform-pki-setup [web]
├── inputs.conf
│   ### BEGIN splunk-platform-pki-setup [s2s]
│   [SSL]
│   serverCert  = .../<host>-s2s.pem
│   sslPassword = <plaintext>
│   ### END splunk-platform-pki-setup [s2s]
│   ### BEGIN splunk-platform-pki-setup [hec]
│   [http]
│   serverCert  = .../<host>-hec.pem
│   sslPassword = <plaintext>
│   ### END splunk-platform-pki-setup [hec]
└── outputs.conf
    ### BEGIN splunk-platform-pki-setup [forwarder]
    [tcpout]
    clientCert  = .../<host>-s2s-client.pem
    sslPassword = <plaintext>
    ### END splunk-platform-pki-setup [forwarder]
```

`install-leaf.sh` is idempotent — re-runs strip the prior block
between matching markers and re-append the new one, so the
operator can rotate per-host without manual editing.

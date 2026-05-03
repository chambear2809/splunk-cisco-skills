# TLS Hardening Reference

Splunk Enterprise's documented baseline (still current in 10.2):

```
sslVersions = tls1.2
cipherSuite = ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:\
              ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:\
              ECDHE-ECDSA-AES256-SHA384:ECDHE-RSA-AES256-SHA384:\
              ECDHE-ECDSA-AES128-SHA256:ECDHE-RSA-AES128-SHA256
ecdhCurves  = prime256v1, secp384r1, secp521r1
```

The renderer applies this in five places, all driven from the same source
of truth in `scripts/render_assets.py`:

| File | Stanza | Note |
|---|---|---|
| `web.conf` | `[settings]` | Splunk Web 8000 |
| `server.conf` | `[sslConfig]` | splunkd 8089 default for all child stanzas |
| `inputs.conf` | `[http]` (HEC) | HEC 8088 |
| `inputs.conf` | `[splunktcp-ssl://9997]` | S2S receiver |
| `outputs.conf` | `[tcpout-server://...]` | Heavy forwarder → indexers |

## TLS 1.3

`--enable-tls13 true --tls-policy tls12_13` emits `sslVersions = tls1.2,
tls1.3`. Use only when:

- Target Splunk Enterprise is 10.x (older versions have inconsistent
  TLS 1.3 ALPN and compatibility issues).
- The platform OpenSSL has TLS 1.3 support.
- All inter-Splunk peers are on the same baseline (mixed-version
  clusters can fail to negotiate).

If unsure, leave at `tls12`. The Splunk-published cipher list above is
TLS 1.2-only — with TLS 1.3 the AEAD suites are added automatically by
OpenSSL and do not require enumeration.

## Defense-in-depth toggles

| Setting | Stanza | Default | Hardened | Why |
|---|---|---|---|---|
| `allowSslCompression` | `[sslConfig]` | `true` | `false` | CRIME mitigation |
| `allowSslRenegotiation` | `[sslConfig]` | `true` | `false` | Where supported |
| `sslVerifyServerCert` | `[sslConfig]` | `false` | `true` | Verifies peer cert |
| `sslCommonNameToCheck` | `[sslConfig]` | unset | populate per peer | Prevents wildcard mis-trust |
| `sslAltNameToCheck` | `[sslConfig]` | unset | populate per peer | SAN validation |
| `requireClientCert` | `[sslConfig]` (10.0+) | `false` | `true` for inter-Splunk mTLS | mTLS |
| `sendStrictTransportSecurityHeader` | `[httpServer]` | `false` | `true` | HSTS for splunkd |
| `includeSubDomains` | `[httpServer]` | `false` | `true` after subdomain audit | HSTS scoping |
| `preload` | `[httpServer]` | `false` | `true` after permanent commitment | HSTS preload |
| `sslPassword` | `[sslConfig]` | `password` (literal!) | non-default via `*-secret-file` | Default is a known-bad |

## Default certificate detection

Splunk ships with these self-signed default certs in
`$SPLUNK_HOME/etc/auth/`:

- `server.pem` — splunkd, subject CN includes `SplunkServerDefaultCert`.
- `cacert.pem` — root, subject CN includes `SplunkCommonCA`.
- `splunkweb/cert.pem` — Splunk Web, subject CN includes
  `SplunkWebDefaultCert`.

The rendered `verify-certs.sh` and `preflight.sh` refuse to mark the
deployment ready while any of these subject-CN tokens is present in the
configured `serverCert`. Hash-based fingerprints are tracked in
`default-cert-fingerprints.json` for additional rigor.

## Certificate hygiene

- Public CA (Let's Encrypt, DigiCert, Sectigo) — preferred.
- Internal CA — acceptable only if the CA root is distributed to every
  client of the public surface (i.e. only forwarders, not browsers).
- Key strength: ≥ 2048-bit RSA or P-256+ ECDSA.
- Signature algorithm: SHA-256 or stronger. SHA-1 / MD5 refused.
- CN/SAN must include `--public-fqdn` and any other operator-supplied
  `--required-sans`.
- CAA records on the FQDN must allowlist the issuing CA only.

## TLS scan tools

The renderer's `validate.sh` does a basic openssl-driven scan. For
deeper testing run:

```bash
testssl.sh --severity HIGH https://splunk.example.com/
```

A passing score requires:

- No TLS 1.0 / TLS 1.1 negotiation.
- No NULL / EXPORT / RC4 / 3DES / weak DH / anonymous ciphers.
- HSTS present and valid.
- OCSP stapling enabled at the proxy.
- ALPN h2 negotiated.
- Certificate chain validates against a public root.

## Post-quantum / hybrid

Splunk Enterprise does NOT support PQC / hybrid TLS as of 10.2. Do not
configure SNTRUP / ML-KEM. Track Splunk release notes for support.

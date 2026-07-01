# Algorithm Presets

Selectable with `--tls-policy {splunk-modern|fips-140-3|stig}`.
The actual values shipped to the renderer live in
[`algorithm-policy.json`](algorithm-policy.json) (machine-readable
companion); this doc is the human-readable narrative.

## `splunk-modern` (default)

Splunk's documented modern set per
[About TLS encryption and cipher suites](https://docs.splunk.com/Documentation/Splunk/latest/Security/AboutTLSencryptionandciphersuites).

| Knob | Value |
|---|---|
| `sslVersions` | `tls1.2,tls1.3` on Splunk 10.4+; `tls1.2` on older versions |
| `sslVersionsForClient` | same version-aware value |
| `[tls1.3] cipherSuite` | `TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:TLS_AES_128_GCM_SHA256` |
| `cipherSuite` | `ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-SHA384:ECDHE-RSA-AES256-SHA384:ECDHE-ECDSA-AES128-SHA256:ECDHE-RSA-AES128-SHA256` |
| `ecdhCurves` | `prime256v1, secp384r1, secp521r1` |
| Allowed key algos | RSA-2048+, ECDSA P-256/P-384/P-521 |
| Allowed sig algos | RSA-SHA256, RSA-SHA384, RSA-SHA512, ECDSA-SHA256, ECDSA-SHA384, ECDSA-SHA512 |
| LDAP cipher | same as splunkd (rendered into `ldap.conf`) |

This matches the `cipher_suite` and `ecdh_curves` constants in
[`splunk-enterprise-public-exposure-hardening/scripts/render_assets.py`](../../splunk-enterprise-public-exposure-hardening/scripts/render_assets.py)
so the two skills agree on the on-the-wire crypto.

## `fips-140-3`

NIST-approved AEAD only per
[Secure Splunk Enterprise with FIPS](https://help.splunk.com/en/splunk-enterprise/administer/manage-users-and-security/10.2/establish-and-maintain-compliance-with-fips-and-common-criteria-in-splunk-enterprise/secure-splunk-enterprise-with-fips).

| Knob | Value |
|---|---|
| `sslVersions` | `tls1.2,tls1.3` on Splunk 10.4+; `tls1.2` on older versions |
| `sslVersionsForClient` | same version-aware value |
| `[tls1.3] cipherSuite` | `TLS_AES_256_GCM_SHA384:TLS_AES_128_GCM_SHA256` |
| `[tls1.3] groups` | `prime256v1, secp384r1` (the groups documented as FIPS 140-3 approved by Splunk) |
| `cipherSuite` | AEAD-only: `ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256` (no CBC, no SHA-1, no anonymous DH) |
| `ecdhCurves` | `prime256v1, secp384r1, secp521r1` |
| Allowed key algos | RSA-2048+, ECDSA P-256/P-384/P-521 |
| Allowed sig algos | RSA-SHA256, RSA-SHA384, RSA-SHA512, ECDSA-SHA256, ECDSA-SHA384, ECDSA-SHA512 (no SHA-1, no MD5) |
| Forbidden | RSA-1024, DSA, MD5, SHA-1, AES-CBC, anonymous DH, NULL ciphers |
| Required env | `SPLUNK_FIPS_VERSION = 140-3` in `splunk-launch.conf` |

Selecting `--tls-policy fips-140-3` does NOT automatically set
`--fips-mode 140-3`; pass both for a complete FIPS posture. The
preset exists separately so an operator can run FIPS-grade ciphers
WITHOUT enabling the full FIPS module (useful during Phase 1 of
the FIPS upgrade).

## `stig`

DISA STIG-aligned subset, cross-referenced by
[`splunk-enterprise-public-exposure-hardening/references/disa-stig-cross-reference.md`](../../splunk-enterprise-public-exposure-hardening/references/disa-stig-cross-reference.md).

| Knob | Value |
|---|---|
| `sslVersions` | `tls1.2,tls1.3` on Splunk 10.4+; `tls1.2` on older versions |
| `sslVersionsForClient` | same version-aware value |
| `[tls1.3] cipherSuite` | `TLS_AES_256_GCM_SHA384:TLS_AES_128_GCM_SHA256` |
| `[tls1.3] groups` | `secp384r1` (P-256 is excluded by this stricter preset; P-521 is not in Splunk's documented FIPS 140-3 TLS 1.3 group set) |
| `cipherSuite` | AEAD-only with explicit forbid list aligned to STIG: `ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256` |
| `ecdhCurves` | `secp384r1, secp521r1` (no `prime256v1` for STIG-high) |
| Allowed key algos | RSA-3072+, ECDSA P-384/P-521 |
| Allowed sig algos | RSA-SHA384, RSA-SHA512, ECDSA-SHA384, ECDSA-SHA512 |
| Forbidden | everything in `fips-140-3` forbidden list, plus RSA-2048, ECDSA P-256, SHA-256-only sig |

The `stig` preset is the strictest. It refuses the default
RSA-2048 leaf algorithm, so the operator must override
`--key-algorithm rsa-3072` or `ecdsa-p384` when picking it.

## Forbidden everywhere (regardless of preset)

The renderer always refuses to emit:

- `sslVersions = ssl3` / `sslVersions = tls1.0` / `sslVersions = tls1.1`
- `cipherSuite` containing NULL, EXPORT, anonymous-DH, or RC4
- Keys with `MD5` or `SHA-1` signatures
- RSA keys < 2048 bits
- ECDSA curves not in NIST suite-B (no Brainpool, no Curve25519
  for TLS — Splunk doesn't yet wire it through OpenSSL FIPS for
  TLS use)

The legacy `--allow-deprecated-tls` option fails closed. This skill no longer
emits SSLv3 / TLS 1.0 / TLS 1.1 under any preset.

## TLS 1.3

Splunk Enterprise 10.4 documents TLS 1.3 and its separate
`server.conf [tls1.3]` cipher/group policy. The renderer enables TLS 1.2 and
TLS 1.3 for the default floor on 10.4+, or TLS 1.3 only when explicitly
requested. `--tls-version-floor tls1.3` is rejected for older versions.

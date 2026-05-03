# DISA STIG Cross-Reference

The DISA Splunk Enterprise 8.x for Linux STIG (V2R2) is the closest
formal hardening benchmark for Splunk Enterprise. The renderer's
configuration maps to the STIG controls in the V-251680..V-251692
series. This document is a cross-reference; it does NOT certify STIG
compliance — your assessor owns that.

## Mapping table

| STIG ID | Title (paraphrased) | Renderer overlay |
|---|---|---|
| V-251680 | Splunk Enterprise must use HTTPS/SSL for UI access | `web.conf [settings] enableSplunkWebSSL = true` plus operator-supplied cert |
| V-251681 | Inputs must use mTLS for inter-Splunk traffic | `inputs.conf [splunktcp-ssl://9997] requireClientCert = true` |
| V-251682 | Splunk Enterprise must verify peer certificates | `server.conf [sslConfig] sslVerifyServerCert = true` plus `sslCommonNameToCheck`/`sslAltNameToCheck` |
| V-251683 | Splunk Enterprise must accept DoD CAC/PKI credentials | `authentication.conf [authentication] authType = SAML` (CAC via SAML/PKI) |
| V-251684 | Admin account must be lockable | `authorize.conf [role_admin] never_lockout = disabled` |
| V-251685 | Password complexity required | `authentication.conf [splunk_auth]` complexity settings |
| V-251686 | Password aging required | `authentication.conf [splunk_auth] expirePasswordDays = 90` |
| V-251687 | Password history enforced | `authentication.conf [splunk_auth] enablePasswordHistory = true` |
| V-251688 | Least-privilege role design | `authorize.conf [role_public_reader]` removed capabilities |
| V-251689 | TLS 1.2+ and SHA-256+ only | `web.conf` + `server.conf` + `inputs.conf` `sslVersions = tls1.2`, SHA-256 cert sig required |
| V-251690 | DoD-approved CAs only | `server.conf [sslConfig] caCertFile = <operator CA>` |
| V-251691 | No verbose login failure messages | `server.conf [httpServer] verboseLoginFailMsg = false` |
| V-251692 | PKI / CAC authentication required | `authentication.conf [saml] signedAssertion = true`, `signAuthnRequest = true` |

## Where the STIG and this skill differ

The STIG is written for an isolated DoD-network deployment. This skill
is written for **public-internet** exposure. The differences:

- The STIG does not explicitly require:
  - A reverse proxy (the skill does).
  - WAF / CDN (the skill does).
  - Per-IP rate limit (the skill does).
  - Splunk-secret rotation procedure (the skill does).
  - SVD floor enforcement (the skill does).
- The STIG mandates DoD-approved CAs only. The skill is more permissive
  — operator-supplied CA bundle, with the recommendation that public
  CAs (Let's Encrypt, DigiCert, Sectigo) are used for browser-facing
  certs.

## How to use this for STIG compliance

1. Run the rendered `validate.sh`. The JSON report names every
   control-tested check.
2. Map each STIG control to the relevant validate-report check.
3. Document any gaps (e.g. STIG mandates additional auditing rules
   that you implement separately).
4. Capture `metadata.json` plus `validate-report.json` as evidence.

## Other benchmarks

- CIS Splunk benchmark — does NOT exist. CIS publishes OS-level
  benchmarks but no Splunk-specific.
- NIST 800-53 — operator-driven mapping; the skill's controls cover
  many CC family items.
- ANSSI / NCSC / ACSC — no Splunk-specific guidance published.

The DISA STIG remains the formal benchmark for now.

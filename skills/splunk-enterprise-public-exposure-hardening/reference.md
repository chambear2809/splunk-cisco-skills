# Splunk Public Exposure Hardening — Reference

This is the single document to read before applying the hardening on a
production Splunk Enterprise deployment. It covers everything that is too
detailed for `SKILL.md` and links into the topical references for the
deepest sub-areas.

## 1. Decision matrix — what to expose

| Surface | Default port | Skill behavior | Who reaches it |
|---|---|---|---|
| Splunk Web (UI / search) | 8000 | Allowed via reverse proxy on `:443` | Authenticated browsers, federated to IdP |
| HEC ingest | 8088 | Allowed via reverse proxy on `:443` (separate vhost) or `:8088` | API clients with HEC token; optional mTLS |
| Splunk-to-Splunk | 9997 | Allowed only via DMZ heavy forwarder; never direct | Authenticated forwarders with mTLS |
| splunkd REST | 8089 | **NEVER** publicly reachable | Internal services + bastion-reached operators only |
| KV store / mongo | 8191 | **NEVER** publicly reachable | SHC members only |
| Replication | 9887 | **NEVER** publicly reachable | Indexer cluster members only |
| App server (loopback) | 8065 | **NEVER** publicly reachable | Splunk Web → splunkd internal only |

## 2. Ports & binding cheatsheet

The renderer will produce `server.conf [httpServer] acceptFrom` and
`web.conf [settings] acceptFrom` overlays that bind every public-listening
port to the proxy CIDR plus loopback, and emit firewall snippets that
reaffirm the boundary. There is no "trustedProxiesList" in Splunk — when
`tools.proxy.on = true`, Splunk will read `X-Forwarded-For` from any IP
that can reach port 8000, so `acceptFrom` is not optional.

For single-host hardening, set `mgmtHostPort = 127.0.0.1:8089`. For SHC /
indexer-cluster hardening, leave `mgmtHostPort = 0.0.0.0:8089` and rely on
`acceptFrom` plus host firewall.

## 3. TLS / cipher policy

Splunk Enterprise's documented baseline (still current in 10.2):

```
sslVersions = tls1.2
cipherSuite = ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:\
              ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:\
              ECDHE-ECDSA-AES256-SHA384:ECDHE-RSA-AES256-SHA384:\
              ECDHE-ECDSA-AES128-SHA256:ECDHE-RSA-AES128-SHA256
ecdhCurves  = prime256v1, secp384r1, secp521r1
```

The renderer emits `tls1.2` by default. Pass `--enable-tls13 true` to
emit `tls1.2,tls1.3`; only safe when target Splunk version is 10.x and
the platform OpenSSL supports it.

Defense-in-depth toggles:

- `[sslConfig] allowSslCompression = false` (CRIME).
- `[sslConfig] allowSslRenegotiation = false` where supported.
- `[sslConfig] sslVerifyServerCert = true` plus
  `sslCommonNameToCheck` / `sslAltNameToCheck` per peer.
- `[httpServer] sendStrictTransportSecurityHeader = true`,
  `includeSubDomains = true` (after subdomain audit), `preload = true`
  (commitment).
- Replace default Splunk shipped certs (`$SPLUNK_HOME/etc/auth/{server,
  splunkweb}/*.pem`). Preflight refuses default certs.
- Replace default `[sslConfig] sslPassword = password` literal. Preflight
  refuses the default.

See [references/tls-hardening.md](references/tls-hardening.md) for the
full per-stanza matrix.

## 4. Browser security headers

Splunk Web has **no** mechanism to add custom HTTP response headers. All
of these MUST come from the reverse proxy:

- `Strict-Transport-Security: max-age=31536000; includeSubDomains`
- `Content-Security-Policy: frame-ancestors 'self'`
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: geolocation=(), microphone=(), camera=()`
- `Cache-Control: no-store` on `/account/login` and authenticated pages.

Splunkd 8089 has its own HSTS knobs in `server.conf [httpServer]`.

## 5. Authentication

- Federate to a SAML IdP. Set `signAuthnRequest = true`,
  `signedAssertion = true`, `signatureAlgorithm = RSA-SHA256`,
  `excludedAutoMappedRoles = admin,sc_admin` (no IdP-mapped admin).
- Enforce MFA at the IdP (Duo Universal Prompt with WebAuthn / passkeys
  is the most phishing-resistant; Okta + WebAuthn or Entra ID + FIDO2
  also work). Splunk Enterprise has no native WebAuthn surface.
- Local password policy (still required for the break-glass admin):
  `minPasswordLength = 14`, all four character classes ≥ 1,
  `expirePasswordDays = 90`, `lockoutAttempts = 5`,
  `lockoutMins = 30`, `enablePasswordHistory = true`,
  `passwordHistoryCount = 24`, `forceWeakPasswordChange = true`.
- **Set `[role_admin] never_lockout = disabled`** in `authorize.conf`.
  Splunk's default is `enabled`, leaving the most-targeted account
  immune to the lockout you just configured.
- Rename or disable the stock `admin` user; create two named
  break-glass admins with strong passwords and IdP-required MFA.

## 6. Roles, capabilities, and risky commands

A custom `role_public_reader` is built from zero (do **not** inherit
from `user`) and explicitly excludes every high-risk capability:
`edit_cmd`, `edit_cmd_internal`, `edit_scripted`, `rest_apps_management`,
`rest_apps_install`, `rest_properties_set`, `run_collect`, `run_mcollect`,
`run_debug_commands`, `run_msearch`, `run_sendalert`, `run_dump`,
`run_custom_command`, `embed_report`, `change_authentication`,
`delete_by_keyword`, `accelerate_search`, `dispatch_rest_to_indexers`,
`import_apps`, `install_apps`, `edit_authentication`, `edit_user`,
`edit_roles`, `edit_token_*`, `edit_indexer_*`, `edit_input_*`,
`edit_modinput_*`, `edit_search_scheduler`, `edit_remote_apps_management`,
`pattern_detect`, `request_pstacks`, `request_remote_tok`.

Search-time guardrails: `srchTimeWin = 86400`, `srchDiskQuota = 100`,
`srchJobsQuota = 3`, `rtSrchJobsQuota = 0`,
`cumulativeSrchJobsQuota = 50`, `cumulativeRTSrchJobsQuota = 0`,
`srchMaxTime = 300`, `srchIndexesAllowed = <explicit>`,
`srchIndexesDisallowed = _audit,_internal,_introspection,_telemetry`.

Risky Command Safeguards: rendered `commands.conf` marks `collect`,
`delete`, `dump`, `map`, `mcollect`, `meventcollect`, `outputcsv`,
`outputlookup`, `run`, `runshellscript`, `script`, `sendalert`,
`sendemail`, `tscollect` as `is_risky = 1`. Multiple bypass advisories
exist (see `references/risky-command-safeguards.md`); upgrade is the
only durable mitigation, capability gating is mandatory defense in
depth.

Note: there is no `enable_install_apps` master switch in any released
Splunk version. The skill closes the SPL-upload surface by:

- Removing `install_apps`, `import_apps`, `rest_apps_install`,
  `rest_apps_management`, and `edit_remote_apps_management` capabilities
  from `role_public_reader` (in `authorize.conf`).
- Denying the upload paths at the reverse proxy:
  `/services/apps/local`, `/services/apps/appinstall`,
  `/services/apps/remote`. See `proxy/nginx/splunk-web.conf`.

## 7. Secrets posture

- `splunk.secret` must be unique per deployment, mode `0400`, owner
  `splunk:splunk`. Preflight refuses the default-fixture hash.
- `pass4SymmKey` rotated and unique across `[general]`, `[clustering]`,
  `[shclustering]`, `[indexer_discovery]`, `[license_master]`. Preflight
  refuses any value of `changeme` or default fixtures.
- `[sslConfig] sslPassword` rotated from the literal `password` default.
- HEC tokens never appear on argv, in chat, or in `metadata.json`.
- IdP signing certs and TLS private keys passed in via file paths only.
- `splunk-secret-rotation.md` documents the 10-step incident-response
  rotation procedure (used after SVD-2026-0207 / SVD-2026-0203 -class
  leaks).

## 8. Reverse proxy duties

The proxy is the only place that can:

- Enforce `Host` integrity and prevent `Host` spoofing.
- Strip `\r`, `\n`, control characters from header values
  (CVE-2025-20384 log injection mitigation).
- Strip attacker-supplied `X-Forwarded-*`, `X-Real-IP`,
  `X-Splunk-Form-Key`, then write its own.
- Sanitize / regex-validate the `return_to` query parameter against
  `^/[a-zA-Z0-9_/\-]+$` (CVE-2025-20379 open-redirect mitigation).
- Apply per-IP rate limit on `POST /en-US/account/login` (Splunk has no
  CAPTCHA; lockout is per-user).
- Add HSTS / CSP / X-Content-Type-Options / Referrer-Policy / Permissions-Policy
  / Cache-Control: no-store.
- Allowlist the `splunkweb_csrf_token_*` cookie (do NOT strip — Splunk
  Web returns "CSRF validation failed" if it goes missing).
- Stream search results without buffering: `proxy_http_version 1.1`,
  `proxy_buffering off`, `proxy_request_buffering off`,
  `proxy_read_timeout 600s`, `proxy_send_timeout 600s`.
- Match HEC body size to `[http_input] max_content_length = 838860800`
  (800 MB default) on the HEC vhost.
- Optionally enable `ssl_verify_client on` for HEC mTLS.
- Allowlist `/services`, `/servicesNS`, `/en-US/manager`,
  `/en-US/account` (except `/login`) to a bastion CIDR.

HAProxy MUST use `option http-server-close` (NEVER `option httpclose`,
which breaks HEC keepalive).

See [references/reverse-proxy-templates.md](references/reverse-proxy-templates.md).

## 9. WAF / CDN handoff

Per platform (`handoff/waf-cloudflare.md`, `handoff/waf-aws.md`,
`handoff/waf-f5-imperva.md`):

- Enable managed rule sets (OWASP CRS or vendor equivalent).
- Rate-based rules on auth endpoints (≤ 5 req / min / IP).
- Credential stuffing list, IP reputation, geo-fence (operator-defined).
- Body-inspection allowance for `/services/collector*` (Cloudflare
  default 128 KB, AWS WAF 8 KB — HEC traffic gets dropped without an
  exemption).
- Bot management allowlist for HEC user-agents (Splunk SDKs, OTel
  exporters, Forwarder UAs) so Cloudflare Bot Fight Mode / AWS WAF Bot
  Control don't block ingestion.
- Cookie scrubbing rules: keep `splunkweb_csrf_token_*`.
- Read-timeout extension: Cloudflare Enterprise Proxy Read Timeout, AWS
  ALB idle timeout (raise above 60 s default), F5 BIG-IP HTTP profile
  request-timeout.

## 10. Network segmentation

- Heavy forwarder in DMZ for S2S ingest from internet-facing UFs.
- DMZ HF terminates `splunktcp-ssl://9997` with `requireClientCert =
  true` and `acceptFrom`.
- Internal indexer cluster receives data from the DMZ HF only, over a
  separate mTLS S2S channel.
- splunkd 8089, KV store 8191, replication 9887, app-server 8065 all
  blocked from the public CIDR.
- Cluster-internal ports allowed only between cluster CIDR.

See [references/dmz-heavy-forwarder-pattern.md](references/dmz-heavy-forwarder-pattern.md).

## 11. SVD floor and threat-intel

The skill refuses to apply on a Splunk version below the floor:

- 10.2.x → 10.2.2
- 10.0.x → 10.0.5
- 9.4.x  → 9.4.10
- 9.3.x  → 9.3.11

A public Metasploit module for CVE-2024-36985 (`splunk_archiver` RCE)
was merged 2026-01-20. Recent Shodan checks find ~133 publicly exposed
Splunk hosts with 17 exposing port 8089 directly. There are zero CISA
KEV entries for Splunk as of catalog v2026.05.01 — this is not a
guarantee, monitor.

See [references/cve-svd-tracking.md](references/cve-svd-tracking.md) and
[references/threat-intel.md](references/threat-intel.md).

## 12. Compliance reality

Splunk Enterprise self-hosted inherits **no** third-party attestations.
Splunk Cloud is FedRAMP High (since 2024-09-13), SOC 2, ISO 27001, PCI
DSS — but those certifications do not transfer to your on-prem
deployment.

The skill provides a DISA STIG cross-reference (V-251680..V-251692) and
a control-mapping handoff but does NOT certify PCI / HIPAA / FedRAMP /
SOC 2.

See [references/compliance-gap-statement.md](references/compliance-gap-statement.md).

## 13. Operator handoff (cannot be automated)

- Procure CA-signed leaf cert (CN/SAN match FQDN, ≥ 2048-bit RSA or
  P-256 ECDSA, SHA-256+).
- Provide IdP SAML metadata + IdP-side MFA enforcement.
- Configure WAF rules, CDN, DDoS protection.
- Configure DNS, DNSSEC, CAA records.
- Submit FQDN to HSTS preload list AFTER subdomain audit.
- Configure SOC alerting on `_audit` and `_internal`.
- Stand up a separate VPN / bastion for `/services` admin paths.
- Subscribe to `https://advisory.splunk.com/` and CISA KEV.
- Configure encrypted backups for `$SPLUNK_HOME/etc` and indexes; test
  restore.
- Document key / secret rotation calendar.
- Decide on Splunk Secure Gateway / Splunk Mobile exposure separately.

See [references/operator-handoff-checklist.md](references/operator-handoff-checklist.md).

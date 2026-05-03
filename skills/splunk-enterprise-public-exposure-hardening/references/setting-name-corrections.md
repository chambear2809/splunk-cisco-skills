# Setting Name Corrections

Several Splunk settings are widely (and incorrectly) referenced in
blog posts, Stack Overflow answers, and ChatGPT outputs. This document
lists the misnames and their real counterparts so downstream consumers
of this skill don't reintroduce errors.

The skill's offline smoke test (`smoke_offline.sh`) verifies that the
rendered `web.conf` does not contain any of these misnames.

## Confirmed misnames (do NOT exist in any released Splunk version)

| Misname (don't use) | Reality |
|---|---|
| `customHttpHeaders` (in `web.conf`) | Does not exist. Splunk Web has no built-in mechanism to add HTTP response headers. Use the reverse proxy. |
| `httpd_protect_login_csrf` | Does not exist. Login CSRF is enforced internally via the `splunkweb_csrf_token_<port>` cookie + `X-Splunk-Form-Key` header — no admin-facing toggle. |
| `cookie_csrf` | Does not exist. Cookie name is `splunkweb_csrf_token_<port>`. |
| `splunkweb.cherrypy.tools.csrf.on` | Does not exist. CherryPy's `tools.csrf` is internal and not configurable via `web.conf`. |
| `tools.proxy.local` | Does not exist. Only `tools.proxy.on` and `tools.proxy.base` are real. |
| `serverRoot` | Does not exist. The setting that mounts Splunk under a sub-path is `root_endpoint` (e.g. `root_endpoint = /splunk`). |
| `splunkdConnectionHost` | Does not exist. The setting that controls Splunk Web → splunkd connection target is `mgmtHostPort`. |
| `trustedProxiesList` | Does not exist. There is NO XFF allowlist in Splunk. Use `acceptFrom` on `web.conf [settings]` AND `server.conf [httpServer]` to lock down the immediate-client IP. |
| `sizeLimit` (camelCase, in LDAP stanza) | Does not exist. The spec spelling is **lowercase `sizelimit`**. Splunk silently ignores camelCase. |
| `bindPassword` (in LDAP stanza) | Does not exist. The spec key is `bindDNpassword` (one word, capital D). |
| `enableTLSLDAP` | Does not exist. LDAP TLS is enabled via `SSLEnabled = 1` in the LDAP strategy stanza, plus `$SPLUNK_HOME/etc/openldap/ldap.conf` for cipher / protocol configuration. |
| `sslVersions` (inside the `[<authSettings-key>]` LDAP stanza) | Does not exist for LDAP. The spec routes LDAP-channel TLS to `$SPLUNK_HOME/etc/openldap/ldap.conf` only. Splunk silently ignores `sslVersions` / `cipherSuite` / `ecdhCurves` inside the LDAP strategy stanza. |
| `cipherSuite` (inside the LDAP stanza) | Same as above — does not apply to LDAP. |
| `ecdhCurves` (inside the LDAP stanza) | Same as above — does not apply to LDAP. |
| `roleMap_LDAP` (without strategy suffix) | Does not exist. The stanza name is `[roleMap_<authSettings-key>]` where `<authSettings-key>` matches the LDAP strategy stanza name (e.g., `[roleMap_ldaphost]` for `[ldaphost]`). |
| `userToRoleMap_<ldap-strategy>` | Does not exist for LDAP. The `[userToRoleMap_*]` stanza is SAML-only. |
| `pass4SymmKey` for federated search | Does NOT cover federation. Federation uses a per-provider native Splunk service-account user+password in `federated.conf [provider://<name>]` on the CONSUMER. The skill's `rotate-pass4symmkey.sh` does not touch federation creds; use `rotate-federation-service-account.sh`. |

## Real settings often confused with each other

| Setting A | Setting B | Difference |
|---|---|---|
| `tools.proxy.on` | `SSOMode` | First enables proxy header reading; second is for SAML SSO |
| `trustedIP` | `acceptFrom` | First is for SSO trust; second is for connection allowlist |
| `enableSplunkWebSSL` | `sendStrictTransportSecurityHeader` | First is TLS for Splunk Web 8000; second is HSTS for splunkd 8089 REST |
| `enableSplunkWebClientNetloc` | `allowedSplunkWebClientNetlocList` | First was deprecated in 10.0 (and triggers SVD-2025-1006 SSRF when true); second is the replacement |
| `mgmtHostPort` | `httpport` | First is splunkd; second is Splunk Web |
| `pass4SymmKey` (general) | `pass4SymmKey` (clustering) | Same key NAME, different stanzas — they are independent secrets |
| `splunk.secret` | `pass4SymmKey` | First is per-host key for `*.conf` encryption; second is shared cluster secret |

## Splunk Web has no `customHttpHeaders` — the alternatives

The misname `customHttpHeaders` shows up in older blog posts. There is
no Splunk Web setting that adds arbitrary HTTP response headers.
Instead:

- HSTS / CSP / X-Content-Type-Options / Referrer-Policy /
  Permissions-Policy / Cache-Control: add at the **reverse proxy**.
  See `proxy/nginx/splunk-web.conf` for the reference template.
- HSTS for splunkd: `server.conf [httpServer] sendStrictTransportSecurityHeader = true`.

## CSRF cookie / header

| Real | What it does |
|---|---|
| Cookie `splunkweb_csrf_token_<port>` (e.g. `splunkweb_csrf_token_443`) | Set by Splunk Web with a multi-year `Max-Age`. Browser sends back on every state-changing request. |
| Header `X-Splunk-Form-Key` | Browser / SDK sends this with the cookie value on POST/PUT/DELETE/PATCH. Splunk verifies the two match before proceeding. |

WAFs / CDNs that scrub cookies will break Splunk Web auth. Allowlist
the cookie name in any cookie-stripping rule.

## Per-stanza settings often confused

| Setting | Stanza | Note |
|---|---|---|
| `acceptFrom` | `web.conf [settings]` | Splunk Web 8000 |
| `acceptFrom` | `server.conf [httpServer]` | splunkd 8089 |
| `acceptFrom` | `inputs.conf [splunktcp-ssl://...]` | S2S receiver |
| `requireClientCert` | `server.conf [sslConfig]` | inter-Splunk mTLS (10.0+) |
| `requireClientCert` | `inputs.conf [http]` | HEC mTLS |
| `requireClientCert` | `inputs.conf [splunktcp-ssl://...]` | S2S mTLS |

These are independent settings; setting one does not propagate to the
others.

## Why this matters

The renderer has a closed `GENERATED_FILES` set and an offline smoke
test that verifies these misnames are NOT present. If you hand-edit the
rendered output, do NOT introduce them — Splunk silently ignores
unknown settings, so the misname will appear to work but provide no
protection. The `smoke_offline.sh` test will catch the misnames at CI
time.

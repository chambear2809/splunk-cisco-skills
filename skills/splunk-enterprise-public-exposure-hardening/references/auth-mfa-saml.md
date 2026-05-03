# Authentication / MFA / SAML Reference

## Native local auth

Acceptable only for two break-glass admins. Everyone else must
authenticate through SAML SSO.

Local password policy applied by the renderer (`authentication.conf
[splunk_auth]`):

```
minPasswordLength       = 14
minPasswordUppercase    = 1
minPasswordLowercase    = 1
minPasswordDigit        = 1
minPasswordSpecial      = 1
expirePasswordDays      = 90
expireAlertDays         = 15
forceWeakPasswordChange = true
lockoutUsers            = true
lockoutAttempts         = 5
lockoutThresholdMins    = 5
lockoutMins             = 30
enablePasswordHistory   = true
passwordHistoryCount    = 24
```

The break-glass admin is named (e.g. `breakglass_alice`), not the stock
`admin`. The stock `admin` is renamed and disabled post-bootstrap.

## SAML SSO

Recommended for all interactive logins. Renderer emits:

```
[authentication]
authType = SAML
authSettings = saml

[saml]
entityId               = https://splunk.example.com/saml
idpMetaDataPath        = /etc/splunk-public-exposure/saml-idp-metadata.xml
signAuthnRequest       = true
signedAssertion        = true
signatureAlgorithm     = RSA-SHA256
excludedAutoMappedRoles = admin,sc_admin
redirectAfterLogoutToUrl = https://splunk.example.com/account/logout
```

## XSW (XML Signature Wrapping) hardening

- Splunk's built-in SAML implementation in 9.4+ is hardened against
  XSW; older versions had known issues.
- Always require `signedAssertion = true`. If only the response is
  signed but the assertion is not, a wrapper attack can swap assertions.
- Validate `Issuer`, `InResponseTo`, `Recipient`, `NotBefore`,
  `NotOnOrAfter`. Splunk does this automatically when `signedAssertion`
  is enforced.
- Use SHA-256 or stronger. `RSA-SHA1` is not acceptable.
- Use a recent IdP — older Active Directory Federation Services
  versions had partial XSW protection.

## MFA

Splunk Enterprise has **no native WebAuthn**. FIDO2 / passkeys are
implemented at the IdP only.

| MFA factor | Acceptable for public exposure |
|---|---|
| WebAuthn / passkeys / security keys at the IdP | YES (preferred) |
| Duo Universal Prompt with security keys | YES |
| Duo Push with biometric verification | acceptable |
| TOTP (Google Authenticator, Authy) | acceptable |
| SMS / voice | NO — phishable |
| Email-based codes | NO — phishable |

## Group → role mapping

In `authentication.conf [authentication]` use `roleMap_*` settings to
map IdP groups to Splunk roles. Rules:

- NEVER map an IdP group to `admin` or `sc_admin`. The renderer's
  `excludedAutoMappedRoles` enforces this server-side.
- Map only to least-privilege roles like `role_public_reader`.
- Break-glass admin is local only and not mapped through the IdP.

## Authentication tokens (Splunk JWT)

Token-based auth (REST endpoints) is independent of SAML. Hardening:

- Enable token expiration: `expirePasswordDays`-equivalent for tokens
  via `[tokens_auth] tokenLength` and `tokenExpiration`.
- Rotate tokens on a schedule.
- Restrict `edit_token_*` capabilities to admin only.
- Audit `_audit` for token issuance and revocation.

## Reverse-proxy SSO (`--auth-mode reverse-proxy-sso`)

When the proxy (Apache mod_auth_mellon, nginx OpenResty) does the SSO
and Splunk just trusts the proxy, set:

- `web.conf [settings] SSOMode = strict`
- `web.conf [settings] trustedIP = <proxy IP>`
- `server.conf [general] trustedIP = <proxy IP>`

The proxy MUST authenticate every request before passing to Splunk;
otherwise `SSOMode = strict` rejects the request.

## Session timeout

`tools.sessions.timeout = 30` (minutes) is the renderer default. For
sensitive deployments, consider 15 minutes. Note that Splunk re-applies
the session counter on user activity, so 15 minutes idle is when the
session expires.

## Logout vs SLO

- `redirectAfterLogoutToUrl` redirects the user but does NOT terminate
  the IdP session. For full logout, configure SLO (Single Log-Out) at
  the IdP.
- Splunk supports IdP-initiated SLO for SAML.

## Best-practice IdP sequence

1. User → `https://splunk.example.com/`
2. Splunk → 302 → IdP `?SAMLRequest=...`
3. IdP authenticates user (with MFA at this step).
4. IdP → 302 → Splunk `/saml/acs?SAMLResponse=...`
5. Splunk validates assertion signature, NotBefore/NotOnOrAfter,
   Recipient, Issuer.
6. Splunk creates session, sets `splunkweb_csrf_token_<port>` cookie.
7. User redirected to original URL.

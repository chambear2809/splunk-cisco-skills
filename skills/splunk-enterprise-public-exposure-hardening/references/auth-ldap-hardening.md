# LDAP Authentication Hardening

Splunk Enterprise's LDAP integration has several defaults and several
common misconceptions that bite when the search head is on the public
internet. This doc captures the v2-research-corrected setting list.

## Where settings actually live

| Setting class | File | Notes |
|---|---|---|
| Splunk-side LDAP strategy (`host`, `bindDN`, `userBaseDN`, etc.) | `etc/system/local/authentication.conf` | Renderer emits this. |
| Role mapping (Splunk role → LDAP groups) | `etc/system/local/authentication.conf` `[roleMap_<strategy>]` stanza | Splunk role on LEFT, semicolon-separated LDAP groups on RIGHT. |
| LDAP-channel TLS (`TLS_REQCERT`, `TLS_CACERT`, `TLS_PROTOCOL_MIN`, `TLS_CIPHER_SUITE`) | `$SPLUNK_HOME/etc/openldap/ldap.conf` | The renderer emits an EXAMPLE at `splunk/apps/000_public_exposure_hardening/default/openldap-ldap.conf.example` that the operator copies into place. |
| LDAP service-account password | Operator local file via `--ldap-bind-password-file`; injected at apply time | Spec does NOT document automatic encryption of `bindDNpassword` for LDAP — it goes through the standard `splunk.secret` pipeline once Splunk reads `local/authentication.conf`. |

## Settings the renderer DOES NOT emit (and why)

The skill explicitly DOES NOT put any of these inside the LDAP strategy
stanza. They are silently ignored by Splunk and are a common source of
"my hardening isn't working" reports:

- `sslVersions = tls1.2`
- `cipherSuite = ECDHE-...`
- `ecdhCurves = prime256v1, ...`

LDAP TLS uses the underlying OpenLDAP client library, configured in
`ldap.conf`. This is per `authentication.conf.spec` line 412-415 ("See
the file `$SPLUNK_HOME/etc/openldap/ldap.conf` for SSL LDAP settings").

## Verified spec citations

| Setting | Spec line | Default | Hardened value |
|---|---|---|---|
| `host` | 406-410 | required | operator-supplied LDAPS hostname |
| `port` | 418-422 | 389 (or 636 if SSL) | `636` (LDAPS) |
| `SSLEnabled` | 412-416 | `0` (cleartext!) | `1` |
| `bindDN` | 424-431 | unset = anonymous | dedicated read-only service-account DN |
| `bindDNpassword` | 433-437 | unset | injected at apply time from local file |
| `userBaseDN` | 439-443 | required | semicolon-separated for multi-tree |
| `userBaseFilter` | 445-454 | empty | recommended (perf + scope) |
| `userNameAttribute` | 456-464 | required | `sAMAccountName` (AD) or `uid` (OpenLDAP) |
| `realNameAttribute` | 466-470 | required | `cn` |
| `emailAttribute` | 472-475 | `mail` | `mail` |
| `groupBaseDN` | 489-504 | required | semicolon-separated for multi-tree |
| `groupBaseFilter` | 506-512 | empty | recommended |
| `groupNameAttribute` | 531-537 | empty (BUG-PRONE) | `cn` |
| `groupMemberAttribute` | 539-547 | empty (BUG-PRONE) | `member` (AD) or `uniqueMember` |
| `groupMappingAttribute` | 477-487 | unset | `dn` |
| `nestedGroups` | 549-554 | varies | `1` only if directory supports `memberof` AND nesting is required |
| `anonymous_referrals` | 565-574 | **`1` (insecure)** | `0` |
| `enableRangeRetrieval` | 597-606 | `false` | enable only if member counts exceed server limit |
| `charset` | 556-563 | empty (UTF-8) | leave empty unless directory is non-UTF-8 |
| `sizelimit` (lowercase!) | 576-583 | `1000` | `1000` (or operator policy) |
| `pagelimit` | 585-595 | `-1` (off) | `-1` |
| `timelimit` | 608-613 | `15` (max 30) | `15` (operator-tunable; cap is hard 30s) |
| `network_timeout` | 615-627 | `20` | must be `> timelimit`, NOT `-1` for public exposure |

## Multi-tree DN separator

Splunk uses **`;`** (semicolon) for multi-tree lists in
`userBaseDN` and `groupBaseDN`, NOT `,` (comma). The reverse is true
for `[authentication] authSettings = name1,name2` which uses commas to
separate strategy names — easy to confuse.

The renderer validates the separator and fails closed on misuse.

## roleMap direction

```
[roleMap_<strategy>]
splunk_role_name = ldap_group1;ldap_group2;ldap_group3
```

- Splunk role on the LEFT.
- Semicolon-separated LDAP group names on the RIGHT.
- Group names are **case-sensitive** (spec line 657).
- There is NO `[userToRoleMap_<strategy>]` for LDAP (that's SAML-only).

## Refusals (skill guards)

The renderer refuses to produce LDAP config in two high-risk default
states unless the operator explicitly acks:

- `--ldap-ssl-enabled false` requires `--allow-cleartext-ldap`.
  Cleartext bind on a public-facing search head leaks the bind
  credential on the wire.
- Empty `--ldap-bind-dn` (anonymous bind) requires
  `--allow-anonymous-ldap-bind`. Anonymous bind only works if the
  directory permits it AND yields entry-retrieval but not user-login;
  it's almost never appropriate for public exposure.

## ldap.conf TLS stub

The rendered `default/openldap-ldap.conf.example` is the operator's
starting point. Copy it to `$SPLUNK_HOME/etc/openldap/ldap.conf` AS-IS,
or merge with the existing file. The hardened settings:

```
TLS_REQCERT       demand
TLS_CACERT        /opt/splunk/etc/auth/cabundle.pem
TLS_PROTOCOL_MIN  3.3
TLS_CIPHER_SUITE  ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:...
```

`TLS_PROTOCOL_MIN 3.3` corresponds to TLS 1.2.

## Group-to-role policy

NEVER map any LDAP group to `admin` or `sc_admin`. The skill's
`role_admin` posture (`never_lockout = disabled`) assumes admin is
local-only with MFA enforced at the IdP. The renderer's
`role_public_reader` is what you map LDAP groups to.

If an operator MUST grant LDAP-mediated admin (rare), it should be
through a third-party MFA layer in front of the LDAP server.

## Bind-password lifecycle

1. Operator writes the password to a local file with restricted perms:
   `bash skills/shared/scripts/write_secret_file.sh /tmp/ldap_bind_pw`
2. Renderer is invoked with `--ldap-bind-password-file /tmp/ldap_bind_pw`.
3. The rendered `apply-search-head.sh` reads the file at apply time
   and writes `local/authentication.conf` with the password (mode
   `0400`).
4. Splunk reads `local/authentication.conf` on next start, encrypts
   the value via `splunk.secret`, and rewrites the file.
5. Operator deletes the local plaintext file.

If `splunk.secret` ever leaks (see `references/splunk-secret-rotation.md`),
the LDAP bind password is one of the credentials that must be rotated.

## What the LDAP renderer DOES NOT do

- It does not connect to the directory.
- It does not generate the directory-side service account.
- It does not configure mutual TLS to the directory.
- It does not configure Kerberos / GSSAPI binds.
- It does not configure SSSD or any host-side LDAP integration.
- It does not validate the rendered `roleMap_*` against actual
  directory contents — preflight does a runtime audit only.

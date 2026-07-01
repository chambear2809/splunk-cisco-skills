# LDAPS Trust

Splunk uses its OpenLDAP client library for LDAP. TLS for
LDAP is configured in two places:

1. `authentication.conf [<ldap-strategy>]` — Splunk-side toggles
   (host, port, `SSLEnabled`).
2. `$SPLUNK_HOME/etc/openldap/ldap.conf` — TLS protocol, cipher, and
   trust-anchor settings. Splunk does not load this policy from the
   OS-global `/etc/openldap` or `/etc/ldap` path.

> Anchor:
> [Secure LDAP authentication with TLS certificates](https://docs.splunk.com/Documentation/Splunk/9.4.1/Security/LDAPwithcertificates).

## `authentication.conf` (Splunk-side)

```
[my-ldap-strategy]
host        = ldaps.example.com
port        = 636
SSLEnabled  = true
```

`SSLEnabled = true` switches to LDAPS (port 636) by default.
`StartTLS` (begin cleartext on 389, then upgrade) is also
supported but not recommended for new deployments — prefer
LDAPS-from-start.

## Splunk `ldap.conf` (TLS settings)

```
TLS_PROTOCOL_MIN  3.3                    # 3.3 = TLS 1.2
TLS_CIPHER_SUITE  ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256
TLS_CACERT        /opt/splunk/etc/auth/myssl/cabundle.pem
TLS_REQCERT       demand                 # require + validate server cert
```

- `TLS_PROTOCOL_MIN 3.3` corresponds to TLS 1.2 and permits TLS 1.3
  when supported. A TLS-1.3-only render uses `3.4`, as documented for
  Splunk Enterprise 10.4. Values below 3.3 are never rendered.
- `TLS_CIPHER_SUITE` mirrors the splunkd cipherSuite.
- `TLS_CACERT` points to the trust anchor that signs the AD /
  LDAP server's cert. For AD this is typically the AD CS Root
  CA cert.
- `TLS_REQCERT demand` makes OpenLDAP refuse to connect if the
  server's cert isn't trusted. Splunk's SSO docs strongly
  recommend `demand`; never `never` or `allow` in production.

## How this skill renders it

When `--ldaps=true`, the renderer emits:

```
splunk-platform-pki-rendered/pki/distribute/standalone/000_pki_trust/system-files/ldap.conf
```

The install helper copies this staged file to Splunk's fixed OpenLDAP path:

```bash
DEST="$SPLUNK_HOME/etc/openldap/ldap.conf"
cp pki/distribute/standalone/000_pki_trust/system-files/ldap.conf "$DEST"
chmod 0644 "$DEST"
```

The renderer's
`install-leaf.sh --target ldaps` backs up the original to
`<dest>.pki-backup`.

## Coexistence with `splunk-enterprise-public-exposure-hardening`

The hardening skill already has `--ldap-ssl-enabled true|false`
and `--ldap-host` / `--ldap-port` flags. When both skills run:

- Hardening skill writes `authentication.conf [<strategy>]
  SSLEnabled = true`.
- PKI skill writes `ldap.conf` with the trust anchor.

The two work together. The PKI skill defers the
`authentication.conf` LDAP wiring to the hardening skill and only
owns the trust-anchor side.

## Troubleshooting

### "Can't contact LDAP server"

Symptom: Splunk Web auth fails; `splunkd.log` shows
`Can't contact LDAP server` or `error -1: Can't contact LDAP
server`.

Causes:

1. `host` in `authentication.conf` doesn't resolve.
2. Port 636 is firewalled.
3. `TLS_REQCERT demand` and the AD server's cert isn't trusted.

Test from the host:

```bash
ldapsearch -x -H ldaps://ldaps.example.com:636 -b "" -s base
```

If this fails before Splunk does, fix the OS-level LDAPS first.

### "TLS: hostname does not match CN in peer certificate"

Symptom: LDAPS connection fails with hostname mismatch.

Cause: AD's cert SAN doesn't include the FQDN Splunk used.

Fix: either re-issue the AD cert with the correct SAN, or add
the AD's actual SAN as the `host` value in
`authentication.conf` (less common).

### "TLS: peer certificate untrusted or revoked"

Symptom: LDAPS connection fails with untrusted-cert error.

Cause: `TLS_CACERT` doesn't point to the AD-CS Root that signed
the AD server cert.

Fix: append the AD-CS Root to `cabundle.pem` and re-run
`install-leaf.sh --target ldaps`.

## What the skill does NOT do

- Configure AD-side cert auto-enrollment for the LDAP servers
  (operator-driven via Group Policy).
- Mint AD server certs (operator-driven; AD CS does it).
- Wire `authentication.conf` LDAP strategy stanzas (delegated to
  `splunk-enterprise-public-exposure-hardening`).
- Manage Kerberos / GSSAPI bind (out of scope; this skill
  targets LDAPS over TLS, not Kerberos).

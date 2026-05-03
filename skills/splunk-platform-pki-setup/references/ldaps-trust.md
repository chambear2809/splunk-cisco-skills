# LDAPS Trust

Splunk uses the system OpenLDAP client library for LDAP. TLS for
LDAP is configured in two places:

1. `authentication.conf [<ldap-strategy>]` — Splunk-side toggles
   (host, port, `SSLEnabled`).
2. System `ldap.conf` (typically `/etc/openldap/ldap.conf` on
   RHEL or `/etc/ldap/ldap.conf` on Debian) — TLS protocol /
   cipher / trust anchor settings.

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

## System `ldap.conf` (TLS settings)

```
TLS_PROTOCOL_MIN  3.3                    # 3.3 = TLS 1.2
TLS_CIPHER_SUITE  ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256
TLS_CACERT        /opt/splunk/etc/auth/myssl/cabundle.pem
TLS_REQCERT       demand                 # require + validate server cert
```

- `TLS_PROTOCOL_MIN 3.3` corresponds to TLS 1.2 (3.1 = TLS 1.0,
  3.2 = TLS 1.1, 3.3 = TLS 1.2). OpenLDAP doesn't yet expose
  TLS 1.3 with the same precision Splunk needs.
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

The install helper copies this file to the OS-appropriate path:

```bash
case "$(uname -s).$(awk -F= '/^ID=/{print $2}' /etc/os-release | tr -d '"')" in
  Linux.rhel|Linux.centos|Linux.almalinux|Linux.rocky|Linux.fedora|Linux.amzn)
    DEST=/etc/openldap/ldap.conf
    ;;
  Linux.ubuntu|Linux.debian)
    DEST=/etc/ldap/ldap.conf
    ;;
  *)
    DEST=/etc/openldap/ldap.conf
    ;;
esac

cp pki/distribute/standalone/000_pki_trust/system-files/ldap.conf "$DEST"
chmod 0644 "$DEST"
```

`ldap.conf` is system-wide. If other applications on the host
also use OpenLDAP, the operator should review the existing
`ldap.conf` before overwriting. The renderer's
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

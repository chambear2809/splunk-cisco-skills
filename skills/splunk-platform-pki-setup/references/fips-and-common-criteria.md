# FIPS and Common Criteria

Anchored to:

- [Secure Splunk Enterprise with FIPS](https://help.splunk.com/en/splunk-enterprise/administer/manage-users-and-security/10.2/establish-and-maintain-compliance-with-fips-and-common-criteria-in-splunk-enterprise/secure-splunk-enterprise-with-fips)
- [Upgrade and migrate your FIPS-mode deployments](https://help.splunk.com/en/splunk-enterprise/administer/install-and-upgrade/10.2/upgrade-or-migrate-splunk-enterprise/upgrade-and-migrate-your-fips-mode-deployments)

## NIST 2026-09-21 FIPS 140-2 deprecation

NIST deprecates FIPS 140-2 on **2026-09-21**. Past that date,
FIPS-regulated environments must run FIPS 140-3. Splunk 10.0+
ships both modules so the operator can migrate in two phases.

The skill defaults `--fips-mode` to `none` for non-regulated
deployments. For regulated deployments:

- New Splunk 10 install → `--fips-mode 140-3` (use the new
  module from the start).
- Existing FIPS 140-2 install upgrading to Splunk 10 →
  `--fips-mode 140-2` initially (Phase 1), then `--fips-mode
  140-3` (Phase 2) per the upgrade doc.

## Phase 1 — upgrade to Splunk 10 in FIPS 140-2

Per the [FIPS upgrade doc](https://help.splunk.com/en/splunk-enterprise/administer/install-and-upgrade/10.2/upgrade-or-migrate-splunk-enterprise/upgrade-and-migrate-your-fips-mode-deployments),
Phase 1 prerequisites:

- Splunk Enterprise must already run in FIPS mode pre-upgrade.
- OS must be on the [FIPS 140-2 supported OS list](https://help.splunk.com/?resourceId=Splunk_FIPS_supported_OS).
- KV Store must be on MongoDB 4.2+.
- All apps must work with Python 3.9.
- All instances must use TLS 1.2.
- CPU must support AVX (Splunk 10 uses AVX instructions).

`--tls-policy fips-140-3` automatically sets `sslVersions=tls1.2`
and forbids non-FIPS algorithms even before the operator flips to
the FIPS 140-3 module.

## Phase 2 — flip to FIPS 140-3

Once Phase 1 is complete (entire deployment on Splunk 10 in
FIPS 140-2), the operator stops Splunk on each host, edits
`splunk-launch.conf`:

```
SPLUNK_FIPS_VERSION = 140-3
```

The renderer's `pki/install/install-fips-launch-conf.sh` performs
this exact edit idempotently. The skill drops it into
`pki/distribute/standalone/000_pki_trust/local/splunk-launch.conf`
when `--fips-mode 140-3` is set.

Phase 2 prerequisites (additional to Phase 1):

- KV Store must run MongoDB 7.0.17+ with OpenSSL 3.0.
- All apps must work with Python 3.9 and OpenSSL 3.0.
- Forwarders must be on Splunk 10.
- Duo (if used) must be on Universal Prompt.

## Refusal during mid-migration

The skill's `preflight` phase walks every Splunk host in the
topology and reads `splunk-launch.conf` + `splunkd` startup logs
to determine the active FIPS module. If the cluster is in a mixed
state (some hosts on 140-2, some on 140-3), the skill refuses to
apply.

This avoids the edge case where the new cert is signed with an
algorithm only one FIPS module accepts (e.g. SHA-1 still works in
140-2 but is forbidden in 140-3).

## FIPS-allowed cryptography

In FIPS 140-3 mode, the OpenSSL FIPS module restricts:

| Category | Allowed | Forbidden |
|---|---|---|
| Symmetric | AES (128/192/256 in CBC, GCM, CCM, XTS) | RC2, RC4, DES, 3DES, Blowfish |
| Hash | SHA-256, SHA-384, SHA-512, SHA-3 family | MD5, SHA-1 (limited use only) |
| Asymmetric | RSA-2048+, ECDSA P-256/P-384/P-521 | RSA-1024, ECDSA P-192/P-224, DSA |
| Key exchange | ECDHE (NIST curves), DHE (FFDHE-3072+) | Anonymous DH, ECDH on non-NIST curves |
| MAC | HMAC-SHA-256+, AES-CMAC, AES-GMAC | HMAC-MD5, HMAC-SHA-1 (limited) |
| RNG | DRBG (NIST SP 800-90A) | non-DRBG, predictable seeds |

The `--tls-policy fips-140-3` preset enforces this matrix on the
Splunk side. The OpenSSL FIPS module is the operator's
responsibility (Splunk ships the module but the operator must run
on a FIPS-validated OS).

## Common Criteria

Splunk Enterprise has historic Common Criteria evaluations (look
for the latest at [Splunk Compliance](https://www.splunk.com/en_us/about-splunk/security-trust.html)).
For CC-evaluated deployments, the FIPS 140-3 settings above plus:

- **`splunkd.log` must be forwarded to a tamper-evident store**
  — out of scope for this skill; use `splunk-monitoring-console-setup`
  or the operator's audit pipeline.
- **No remote root logon** — out of scope; OS hardening.
- **Audit log retention** — operator-driven.

The skill does not attest CC compliance. It renders configurations
that are CC-friendly and cites the relevant NIST controls in
[`splunk-enterprise-public-exposure-hardening/references/disa-stig-cross-reference.md`](../../splunk-enterprise-public-exposure-hardening/references/disa-stig-cross-reference.md).

## Rollback

Per the upgrade doc, rolling back from 140-3 to 140-2 is manual:

1. Stop Splunk on every host.
2. Revert `SPLUNK_FIPS_VERSION` in `splunk-launch.conf` (or
   delete the line — 140-2 is the default).
3. Restart Splunk.

The renderer's `install-fips-launch-conf.sh` is idempotent and
supports both directions.

KV Store specifically: rolling back from 140-3 to 140-2 leaves
MongoDB 7.0.17 + OpenSSL 3.0 running but in 140-2 mode. Test the
rollback in staging before production.

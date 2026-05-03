# FIPS Mode Reference

Splunk Enterprise supports FIPS 140-2 and FIPS 140-3 cryptographic modes
via the `SPLUNK_FIPS` and `SPLUNK_FIPS_VERSION` environment variables in
`splunk-launch.conf`.

## When to enable

- DoD / federal deployments that need FIPS-validated crypto modules.
- Workloads with a FedRAMP boundary that the operator owns.
- Where local policy requires only FIPS-validated cryptographic
  modules.

FIPS mode is **opt-in** in this skill via `--enable-fips true`. The
default is `false` because FIPS narrows the cipher and TLS protocol
matrix and incompatible cluster members will fail to negotiate.

## Splunk-side configuration

Renderer emits `splunk-launch.conf` with:

```
SPLUNK_FIPS=1
SPLUNK_FIPS_VERSION=140-3
```

(Override version with `--fips-version 140-2`.)

### Where the file goes

`splunk-launch.conf` MUST live at `$SPLUNK_HOME/etc/splunk-launch.conf`
— NOT inside an app's `local/`. The rendered `apply-search-head.sh`
copies the file from the rendered app's `default/` to the canonical
location ONLY when `--enable-fips true` was passed at render time.

### When to apply

Set FIPS mode **before the first start** of Splunk on the host. If
Splunk has already started without FIPS, you must:

1. Stop Splunk.
2. Copy the FIPS overlay to `$SPLUNK_HOME/etc/splunk-launch.conf`.
3. Re-encrypt every credential under the new module by re-running
   `splunk edit` for each credential.
4. Cold-start Splunk.

## Host-side requirements

- The host kernel must be in FIPS mode (RHEL: `fips-mode-setup
  --enable`; Ubuntu: `pro enable fips-updates`).
- OpenSSL must be FIPS-validated.
- All cluster members must use the same FIPS version.
- All forwarders connecting to a FIPS-mode indexer must also be in
  FIPS mode.

## Operational impact

- TLS 1.2 with the existing cipher list still works in FIPS 140-3.
- TLS 1.3 with FIPS-approved cipher suites works in FIPS 140-3 (the
  `--enable-tls13` flag remains compatible).
- Some SHA-1 / RSA-PSS combinations are restricted; the renderer's
  RSA-SHA256 SAML signature already complies.
- KV store mongo must use a FIPS-validated build (Splunk ships one
  with the FIPS distribution).

## Mixing FIPS and non-FIPS clusters

Don't. A FIPS-mode search head talking to non-FIPS forwarders will
fail to negotiate TLS unless the non-FIPS side downgrades to a shared
cipher. The skill's preflight does NOT detect mixed mode — the
operator owns this.

## Compliance mapping

- DISA STIG V-251689 (TLS 1.2+ with SHA-2+) — satisfied with or
  without FIPS.
- DISA STIG V-251690 (DoD-approved CAs) — operator-owned regardless
  of FIPS.
- FedRAMP Moderate / High — FIPS 140-2 or 140-3 is required for
  approved cryptographic modules.

## Sources

- [Secure Splunk Enterprise with FIPS](https://help.splunk.com/en/splunk-enterprise/administer/manage-users-and-security/10.2/establish-and-maintain-compliance-with-fips-and-common-criteria-in-splunk-enterprise/secure-splunk-enterprise-with-fips)
- [Upgrade and migrate your FIPS-mode deployments](https://help.splunk.com/en/splunk-enterprise/administer/install-and-upgrade/10.2/upgrade-or-migrate-splunk-enterprise/upgrade-and-migrate-your-fips-mode-deployments)
- `splunk-launch.conf.spec` — `SPLUNK_FIPS` and `SPLUNK_FIPS_VERSION` settings.

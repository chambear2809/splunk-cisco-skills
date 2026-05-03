---
name: splunk-enterprise-public-exposure-hardening
description: >-
  Render, preflight, apply, and validate hardening of an on-prem Splunk
  Enterprise deployment for public-internet exposure across all four edge
  surfaces (Splunk Web on 8000, HEC on 8088, Splunk-to-Splunk on 9997,
  splunkd REST on 8089) plus reference reverse-proxy / WAF / firewall
  templates and a structured operator handoff. Use when the user asks to
  expose Splunk Enterprise on the public internet, harden a Splunk search
  head against internet exposure, configure TLS / HSTS / CSP / mTLS /
  per-IP rate limit / DMZ heavy forwarder, lock down splunkd or the KV
  store, fix splunk.secret / pass4SymmKey defaults, evaluate against the
  latest SVD floor (10.2.2 / 10.0.5 / 9.4.10 / 9.3.11), or render nginx /
  HAProxy / WAF reference configs in front of Splunk.
---

# Splunk Enterprise Public Internet Exposure Hardening

This skill prepares an **on-prem Splunk Enterprise** deployment for
public-internet exposure with **defense in depth across the Splunk node, the
reverse-proxy / WAF tier, and the network**, plus an explicit operator
handoff for parts that cannot be safely automated. It is render-first: the
default phase produces a reviewable directory of `*.conf` overlays,
nginx / HAProxy / firewall templates, and operator handoff Markdown — and
refuses to apply changes until the operator passes `--accept-public-exposure`.

## Read this first — what Splunk does NOT have

Splunk Enterprise is "designed to run on a trusted network." Several
common assumptions about Splunk Web are wrong, and the skill explicitly
guards against them:

- **No `customHttpHeaders` setting in `web.conf`.** Browser security
  headers (`Strict-Transport-Security`, `Content-Security-Policy`,
  `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`,
  `Cache-Control`) come from the **reverse proxy only**.
- **No CAPTCHA / bot challenge** on the login form.
- **No native WebAuthn / FIDO2** in Splunk Web — federate to an IdP
  (Okta, Entra ID, Duo Universal Prompt) for phishing-resistant MFA.
- **`lockoutAttempts` is per-user**, not per-IP. The `admin` role ships
  with `never_lockout = enabled`. The skill flips this to `disabled` and
  the WAF / proxy provides the per-IP rate limit.
- **No XFF / `trustedProxiesList`.** When `tools.proxy.on = true` Splunk
  trusts `X-Forwarded-*` from any immediate client. Combine with
  `acceptFrom` on `web.conf [settings]` AND `server.conf [httpServer]`
  to lock down the trust boundary.
- **Splunkd 8089, the KV store on 8191, `appServerPorts` on 8065, and
  the indexer-cluster replication port on 9887 must NEVER be reachable
  from the public internet.** Preflight and validate fail closed if
  they are.

## Architecture the skill assumes

```
Public Internet
   │
   ▼
CDN / DDoS  (Cloudflare / AWS / Akamai)   ── operator handoff
   │
   ▼
WAF rules   (OWASP CRS, rate limit, geo)  ── operator handoff
   │
   ▼
Reverse proxy (nginx / HAProxy in DMZ)    ── rendered templates
   │  TLS termination + browser headers + return_to / header sanitisation
   ▼
Splunk Search Head + HEC + DMZ Heavy Forwarder
   │  Splunkd / KV / replication NEVER public.
   ▼
Indexer cluster (private)
```

## Agent behavior — credentials

Never paste secrets into chat or pass them on argv. The skill consumes
**file paths** for every secret it needs and never embeds secret values
in rendered output:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/splunk_admin_password
bash skills/shared/scripts/write_secret_file.sh /tmp/splunk_pass4symmkey
bash skills/shared/scripts/write_secret_file.sh /tmp/splunk_ssl_key_password
bash skills/shared/scripts/write_secret_file.sh /tmp/splunk_idp_signing_cert
```

Pass them in via `--admin-password-file`, `--pass4symmkey-file`,
`--ssl-key-password-file`, etc.

For non-secret values (FQDN, IPs, indexes, role names) use
`template.example`.

## Quick start

Render the full hardening bundle for a single search head with proxy in
front, public Splunk Web only:

```bash
bash skills/splunk-enterprise-public-exposure-hardening/scripts/setup.sh \
  --phase render \
  --topology single-search-head \
  --public-fqdn splunk.example.com \
  --proxy-cidr 10.0.10.0/24 \
  --enable-web true \
  --enable-hec false \
  --enable-s2s false
```

Render with HEC and DMZ heavy forwarder for ingest:

```bash
bash skills/splunk-enterprise-public-exposure-hardening/scripts/setup.sh \
  --phase render \
  --topology shc-with-hec-and-hf \
  --public-fqdn splunk.example.com \
  --hec-fqdn hec.example.com \
  --proxy-cidr 10.0.10.0/24 \
  --enable-web true \
  --enable-hec true \
  --enable-s2s true \
  --hec-mtls true \
  --indexer-cluster-cidr 10.0.20.0/24
```

Run preflight against a live host (read-only checks; refuses to apply):

```bash
bash skills/splunk-enterprise-public-exposure-hardening/scripts/setup.sh \
  --phase preflight \
  --public-fqdn splunk.example.com \
  --external-probe-cmd "ssh probe@bastion.example.com nc -zv"
```

Apply the hardening app on a search head (mutates Splunk; requires the
explicit accept flag):

```bash
bash skills/splunk-enterprise-public-exposure-hardening/scripts/setup.sh \
  --phase apply \
  --public-fqdn splunk.example.com \
  --accept-public-exposure \
  --pass4symmkey-file /tmp/splunk_pass4symmkey
```

Validate live state post-apply:

```bash
bash skills/splunk-enterprise-public-exposure-hardening/scripts/validate.sh \
  --public-fqdn splunk.example.com
```

## What it renders

Under the project root in `splunk-public-exposure-rendered/`:

- `splunk/apps/000_public_exposure_hardening/` — Splunk app with
  `app.conf`, `web.conf`, `server.conf`, `inputs.conf`, `outputs.conf`,
  `authentication.conf`, `authorize.conf`, `limits.conf`, `commands.conf`,
  and `metadata/{default,local}.meta`. Drop into
  `$SPLUNK_HOME/etc/apps/` (or the SHC deployer's `shcluster/apps/`).
- `splunk/apply-search-head.sh`, `apply-hec-tier.sh`,
  `apply-s2s-receiver.sh`, `apply-heavy-forwarder.sh`,
  `apply-deployer.sh`, `apply-cluster-manager.sh`,
  `apply-license-manager.sh` — role-aware apply scripts that copy the
  rendered app into place and restart Splunk.
- `splunk/rotate-pass4symmkey.sh`, `rotate-splunk-secret.sh` — secret
  rotation helpers that read keys from local files only.
- `splunk/certificates/verify-certs.sh`,
  `generate-csr-template.sh` — operator-side cert helpers.
- `proxy/nginx/{splunk-web.conf,splunk-hec.conf}` — production nginx
  vhosts with TLS, HSTS, CSP, header sanitisation, return_to allowlist,
  per-IP rate limit, streaming-safe timeouts, WebSocket plumbing.
- `proxy/haproxy/{splunk-web.cfg,splunk-hec.cfg}` — HAProxy equivalents
  using `option http-server-close` (NOT `option httpclose`).
- `proxy/firewall/{iptables.rules,nftables.conf,firewalld.xml,aws-sg.json}`
  — internet-edge firewall snippets that explicitly drop `8089`,
  `8191`, `8065`, `9887`, plus direct `9997` and `8088` from the
  public CIDR.
- `handoff/` — Markdown checklists for WAF (Cloudflare / AWS / F5+Imperva),
  SAML IdP, Duo MFA, certificate procurement, SOC alerting,
  backup-and-restore, splunk.secret incident response, compliance.
- `preflight.sh` and `validate.sh` — fail-closed scripts the operator
  runs from this directory.
- `README.md` and `metadata.json` — full documentation and rendered
  configuration manifest.

## Phases

- `render` (default) — produce the reviewable rendered directory.
- `preflight` — render then run the 20-step preflight against the live
  host (default-cert detection, SVD floor, `splunk.secret` posture,
  `pass4SymmKey` rotation, capability hygiene, firewall reachability,
  TLS scan, header-injection probe, `return_to` redirect probe, cookie
  scrubbing, etc.). Refuses to mark the deployment ready when any check
  fails.
- `apply` — render then run the apply script for the role you specified.
  Requires `--accept-public-exposure` (a single-flag acknowledgement
  that you are about to bind Splunk to a public-facing FQDN).
- `validate` — render then run the live validation probes.
- `all` — render + preflight + apply + validate, gated by
  `--accept-public-exposure`.

## SVD floor (refuses to apply below this)

| Series | Required version | Source |
|---|---|---|
| 10.2.x | 10.2.2 | SVD-2026-0304, SVD-2026-0303 |
| 10.0.x | 10.0.5 | SVD-2026-0303, SVD-2025-1006 |
| 9.4.x  | 9.4.10 | SVD-2025-1006, SVD-2025-1203 |
| 9.3.x  | 9.3.11 | SVD-2025-1006, SVD-2025-1203 |

Floor lives in
[references/cve-svd-floor.json](references/cve-svd-floor.json) and
ships embedded in the renderer; `--svd-floor-file` can override.

## Cross-skill handoff matrix

The skill consumes — does not duplicate — these. When you also use
one of the adjacent skills below, run THIS skill's preflight +
validate against the fronting search head, then layer the adjacent
skill's hardening on top.

| Adjacent skill | What it owns | What this skill provides |
|---|---|---|
| [splunk-platform-pki-setup](../splunk-platform-pki-setup/SKILL.md) | Full TLS / PKI lifecycle (Private CA or Public CSR + handoff to Vault PKI / ACME / AD CS / EJBCA), per-component cert distribution across every Splunk surface, FIPS 140-2/140-3 wiring, three TLS algorithm presets, KV-Store dual-EKU enforcement, replication-port TLS migration, SAML SP signing cert, LDAPS trust, `cacert.pem` alignment, delegated rotation runbook | Consumes the cert paths the PKI skill provisions; this skill's preflight refuses to declare a public-exposed SH ready until PKI verify-leaf has returned `OK`; the PKI skill consumes this skill's `--enable-fips` / `--fips-version` semantics rather than redefining |
| [splunk-hec-service-setup](../splunk-hec-service-setup/SKILL.md) | HEC token lifecycle, allowed indexes, ACS HEC tokens | HEC TLS / mTLS rendering, body-size alignment, proxy vhost, sensitive-path denies |
| [splunk-enterprise-host-setup](../splunk-enterprise-host-setup/SKILL.md) | Splunk host install / cluster bootstrap | Preflight refuses unbootstrapped hosts; SVD floor enforcement |
| [splunk-indexer-cluster-setup](../splunk-indexer-cluster-setup/SKILL.md) | Indexer cluster bundle | `pass4SymmKey` rotation helper + acceptFrom enforcement for cluster CIDR |
| [splunk-agent-management-setup](../splunk-agent-management-setup/SKILL.md) | SHC deployer, server classes | Hardening app drops into `shcluster/apps/`; SHC deployer pass4SymmKey rotation |
| [splunk-license-manager-setup](../splunk-license-manager-setup/SKILL.md) | License manager / peer wiring | License master 8089 acceptFrom + pass4SymmKey rotation |
| [splunk-cloud-acs-allowlist-setup](../splunk-cloud-acs-allowlist-setup/SKILL.md) | Splunk **Cloud** ACS allowlists | Out of scope — this skill is on-prem only |
| [splunk-federated-search-setup](../splunk-federated-search-setup/SKILL.md) | Federation provider/consumer wiring | Provider-side acceptFrom + service-account rotation helper (federation auth is NOT pass4SymmKey) |
| [splunk-monitoring-console-setup](../splunk-monitoring-console-setup/SKILL.md) | Monitoring Console distributed config | MC integration: forward `_audit` and platform alerts on hardening drift |
| [splunk-connect-for-syslog-setup](../splunk-connect-for-syslog-setup/SKILL.md) | SC4S Docker/Helm runtime, syslog TLS listener | If SC4S delivers via HEC, run THIS skill against the HEC-receiving SH first |
| [splunk-connect-for-snmp-setup](../splunk-connect-for-snmp-setup/SKILL.md) | SC4SNMP Docker/Helm runtime | Same as SC4S |
| [splunk-mcp-server-setup](../splunk-mcp-server-setup/SKILL.md) | MCP server install + token issuance | If MCP is exposed publicly, run THIS skill against the SH fronting it; MCP token policy is owned by the MCP skill |
| [splunk-stream-setup](../splunk-stream-setup/SKILL.md) | Wire data capture stack | Stream is internal-only; this skill does not apply |
| [splunk-index-lifecycle-smartstore-setup](../splunk-index-lifecycle-smartstore-setup/SKILL.md) | SmartStore S3/GCS/Azure backend | Outbound-to-storage; this skill does not apply |
| [splunk-enterprise-security-config](../splunk-enterprise-security-config/SKILL.md) (and ES/SOAR/ITSI/UBA/ARI/AA) | Premium apps + additional capabilities | Run THIS skill first; then re-audit `role_public_reader` against the [premium-apps-capability-overlay](references/premium-apps-capability-overlay.md) |

## References

Read [reference.md](reference.md) before any apply. Topical deep dives:

- [references/tls-hardening.md](references/tls-hardening.md)
- [references/reverse-proxy-templates.md](references/reverse-proxy-templates.md)
- [references/waf-cdn-handoff.md](references/waf-cdn-handoff.md)
- [references/auth-mfa-saml.md](references/auth-mfa-saml.md)
- [references/network-segmentation.md](references/network-segmentation.md)
- [references/role-capability-hardening.md](references/role-capability-hardening.md)
- [references/risky-command-safeguards.md](references/risky-command-safeguards.md)
- [references/splunk-secret-rotation.md](references/splunk-secret-rotation.md)
- [references/cve-svd-tracking.md](references/cve-svd-tracking.md)
- [references/threat-intel.md](references/threat-intel.md)
- [references/disa-stig-cross-reference.md](references/disa-stig-cross-reference.md)
- [references/compliance-gap-statement.md](references/compliance-gap-statement.md)
- [references/dmz-heavy-forwarder-pattern.md](references/dmz-heavy-forwarder-pattern.md)
- [references/operator-handoff-checklist.md](references/operator-handoff-checklist.md)
- [references/setting-name-corrections.md](references/setting-name-corrections.md)
- [references/fips-mode.md](references/fips-mode.md)
- [references/auth-ldap-hardening.md](references/auth-ldap-hardening.md)
- [references/premium-apps-capability-overlay.md](references/premium-apps-capability-overlay.md)
  + [premium-apps-capability-overlay.json](references/premium-apps-capability-overlay.json) (machine-readable companion consumed by preflight)
- [references/secure-gateway-handoff.md](references/secure-gateway-handoff.md)
- [references/federated-search-provider-hardening.md](references/federated-search-provider-hardening.md)
- [references/cve-svd-floor.json](references/cve-svd-floor.json) (Splunk core + SG-app per-branch floors)
- [references/default-cert-fingerprints.json](references/default-cert-fingerprints.json) (machine-readable companion to default-cert-fingerprints / verify-certs.sh)

## What this skill does NOT do

- Procure certificates or talk to a CA. (Provides a CSR template +
  `verify-certs.sh`.)
- Push WAF / CDN config to vendor APIs. (Operator-driven via `handoff/`.)
- Bootstrap the Splunk host itself —
  [splunk-enterprise-host-setup](../splunk-enterprise-host-setup/SKILL.md).
- Issue HEC tokens —
  [splunk-hec-service-setup](../splunk-hec-service-setup/SKILL.md).
- Patch / upgrade Splunk — preflight refuses below the SVD floor and the
  operator must upgrade first.
- Implement IdP-side configuration (Okta, Entra, Duo) — handoff docs only.
- Provide compliance attestation. The skill maps controls (DISA STIG
  cross-reference) but does not certify PCI / HIPAA / FedRAMP / SOC 2.
- Configure Splunk Secure Gateway, Splunk Mobile, SC4S, or the Splunk
  MCP Server for public exposure — each needs its own threat model.

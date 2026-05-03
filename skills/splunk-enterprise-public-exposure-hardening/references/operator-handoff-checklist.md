# Operator Handoff Checklist

The rendered `handoff/operator-checklist.md` is the day-of-cutover
checklist. This file is the longer-form version with rationale and
links into the related references.

## Pre-cutover (T-30 days)

- [ ] **Procure CA-signed certificate** from a public CA. RSA ≥ 2048
  or ECDSA P-256+. SHA-256+. Subject CN matches FQDN; SANs include
  every FQDN that will resolve to this proxy (Splunk Web FQDN, HEC
  FQDN if separate). See [tls-hardening.md](tls-hardening.md).
- [ ] **CAA records**: only your CA may issue.
- [ ] **DNS records**: forward + reverse + DNSSEC.
- [ ] **IdP**: configure SAML SP. Require MFA at the IdP. See
  [auth-mfa-saml.md](auth-mfa-saml.md). FIDO2 / passkeys preferred.
- [ ] **WAF / CDN**: enable managed rule sets, per-IP rate limit on
  `/en-US/account/login`, body-inspection allowance for
  `/services/collector*`. See [waf-cdn-handoff.md](waf-cdn-handoff.md).
- [ ] **Reverse proxy**: deploy nginx or HAProxy from the rendered
  templates. Replace certificate paths with operator-supplied paths.
- [ ] **Firewall**: deploy the iptables / nftables / firewalld /
  cloud-SG snippet of choice.
- [ ] **Bastion** for `/services` admin access. VPN-only.

## Pre-cutover (T-7 days)

- [ ] **Splunk version ≥ SVD floor**: see
  [cve-svd-floor.json](cve-svd-floor.json). Upgrade if needed.
- [ ] **`splunk.secret` rotation**: see
  [splunk-secret-rotation.md](splunk-secret-rotation.md). Rotate now if
  the secret has ever left the host.
- [ ] **`pass4SymmKey` rotation** across cluster, SHC, license,
  indexer-discovery, license-master.
- [ ] **`[sslConfig] sslPassword` rotation**.
- [ ] **Default-cert removal**: replace
  `$SPLUNK_HOME/etc/auth/{server,splunkweb}/*.pem`.
- [ ] **Encrypted backups** for `$SPLUNK_HOME/etc` and indexes; test
  restore.
- [ ] **`splunk.secret` backup** stored separately from data.
- [ ] **SOC alerting** wired up. See
  [`handoff/soc-alerting-runbook.md`](operator-handoff-checklist.md)
  (rendered into the output dir).
- [ ] **Run `bash preflight.sh`** — must exit 0.

## Cutover (T-0)

- [ ] DNS cut over.
- [ ] HSTS preload submission (after subdomain audit).
- [ ] Run `bash splunk/apply-search-head.sh` (or the parent setup.sh
  with `--phase apply --accept-public-exposure`).
- [ ] Confirm Splunk Web responds at `https://<fqdn>/`.
- [ ] Run `bash validate.sh` — must exit 0.
- [ ] Confirm SAML SSO flow works end to end.
- [ ] Confirm the first login event appears in `_audit`.
- [ ] Confirm break-glass admin can still log in directly.

## Day-1 verification

- [ ] WAF blocks a known-bad pattern.
- [ ] Per-IP rate limit fires on rapid login attempts.
- [ ] HSTS, CSP, X-Content-Type-Options, Referrer-Policy headers
  present in browser DevTools.
- [ ] HEC `/services/collector/health` returns 200 from outside.
- [ ] HEC POST with a valid token succeeds.
- [ ] Splunkd 8089 NOT reachable from outside (verified with
  `--external-probe-cmd`).
- [ ] KV store 8191 NOT reachable from outside.
- [ ] App-server 8065 NOT reachable from outside.
- [ ] Replication 9887 NOT reachable from outside.

## Ongoing

- [ ] Patch within 30 days of every Splunk advisory; re-run preflight
  after each upgrade.
- [ ] Rotate TLS certs ≤ 30 days before expiry.
- [ ] Rotate IdP signing certs annually.
- [ ] Rotate `pass4SymmKey` annually or on incident.
- [ ] Re-run `validate.sh` at least monthly and on every config
  change.
- [ ] Quarterly backup-restore drill.
- [ ] Annual security review.
- [ ] Decide on Splunk Secure Gateway / Splunk Mobile / SC4S /
  splunk-mcp-server public exposure separately. Each requires its own
  threat model.

## Out-of-band runbooks

- [ ] **`splunk.secret` compromise**: see
  [`handoff/incident-response-splunk-secret.md`](splunk-secret-rotation.md).
- [ ] **Splunk Enterprise CVE released**: subscribe to
  https://advisory.splunk.com/, evaluate within 24 hours.
- [ ] **CISA KEV update**: subscribe to the JSON feed; act within 24
  hours if any Splunk CVE is added.
- [ ] **WAF rule false-positive on legitimate traffic**: have a
  documented 30-minute path to an allowlist exception with
  re-evaluation.

## Cross-skill obligations

- HEC tokens are owned by `splunk-hec-service-setup`. This skill
  hardens the HEC service config but does NOT issue or rotate tokens.
- Indexer cluster bundle, SHC deployer bundle are owned by
  `splunk-indexer-cluster-setup` and `splunk-agent-management-setup`.
  Drop the rendered hardening app under their respective `apps/`
  directories.
- License manager is owned by `splunk-license-manager-setup`.
- Splunk Cloud (ACS) allowlists are out of scope; on-prem only here.

## Compliance

The skill provides the DISA STIG cross-reference and a compliance
gap statement. It does NOT certify PCI / HIPAA / FedRAMP / SOC 2.
The operator owns those mappings.

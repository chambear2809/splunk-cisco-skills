# Threat Intel Reference

Concrete, operator-facing threat intel for an internet-facing Splunk
Enterprise deployment.

## Public exposure is real

Recent Shodan searches find ~133 publicly exposed Splunk Enterprise
hosts, with 17 of those exposing port 8089 (splunkd REST) directly to
the internet. This is the #1 finding to confirm against your own
deployment using `--external-probe-cmd`.

## Public Metasploit module exists

A public Metasploit module for `CVE-2024-36985` (`splunk_archiver` RCE,
fixed in Splunk Enterprise 9.0.10 / 9.1.5 / 9.2.2) was merged into the
Metasploit framework on 2026-01-20. Older Splunk versions are at risk
from opportunistic scanning. The SVD floor in
[cve-svd-floor.json](cve-svd-floor.json) is set high enough to clear
this CVE.

## CISA KEV — currently zero entries

As of catalog version v2026.05.01 (1,587 entries), the CISA Known
Exploited Vulnerabilities catalog contains zero Splunk Enterprise CVEs.
This does NOT mean Splunk is unexploited — only that no Splunk CVE has
been formally added to KEV. Monitor the catalog for changes; if any
Splunk CVE is added, treat as critical.

## Common attack patterns

### Credential stuffing on /en-US/account/login

- Splunk has no CAPTCHA.
- `lockoutAttempts` is per-user, not per-IP.
- The default `[role_admin] never_lockout = enabled` makes the most-
  targeted account immune.
- The skill's mitigation: WAF per-IP rate limit + `[role_admin]
  never_lockout = disabled`.

### Direct splunkd REST access (port 8089)

- 17 of ~133 Shodan-listed Splunk hosts expose 8089. This is by far
  the most dangerous default.
- The skill's mitigation: firewall snippets DROP 8089 from the public
  CIDR; preflight + validate external-probe verify.

### KV store / mongo (port 8191)

- KV store mongo is unauthenticated by default within the SHC
  cluster — anyone reaching the port can query.
- The skill's mitigation: firewall snippets DROP 8191 from the public
  CIDR.

### Default certificates

- Splunk ships with self-signed default certs (`SplunkServerDefaultCert`,
  `SplunkCommonCA`, `SplunkWebDefaultCert`).
- Browsers warn loudly; attackers can MITM if users click through.
- The skill's mitigation: `verify-certs.sh` refuses default subject
  tokens; preflight enforces.

### `pass4SymmKey = changeme`

- Some installs leave the literal `changeme` default in
  `[clustering] pass4SymmKey` and `[shclustering] pass4SymmKey`.
  Cluster authentication is then trivially defeated.
- The skill's mitigation: preflight refuses any `pass4SymmKey =
  changeme`.

### `[sslConfig] sslPassword = password`

- Splunk's default SSL key passphrase is the literal string `password`.
- The skill's mitigation: preflight refuses; rendered apply scripts
  inject the operator-supplied passphrase from a file.

### `splunk.secret` leak in `_internal`

- SVD-2026-0207 / SVD-2026-0203: certain debug paths leaked secret
  material into the `_internal` index.
- The skill's mitigation: SVD floor enforcement (upgrade past those
  versions) and `incident-response-splunk-secret.md` rotation.

### Open redirect via `return_to`

- CVE-2025-20379: crafted `return_to` URL redirects post-login.
- The skill's mitigation: proxy regex-validates `return_to`.

### Log injection via ANSI escape codes (and headers)

- SVD-2025-1203 / CVE-2025-20384: an unauthenticated attacker injects
  ANSI escape codes (e.g. `\x1b[31m`, `\x07`) into the
  `/en-US/static/` web endpoint. The values land in `web_access.log`
  unsanitized, where they can poison terminal output for analysts and
  forge / obfuscate log content. CVSS 5.3, Medium.
- Splunk's documented workaround is to disable Splunk Web entirely.
  This skill keeps Splunk Web available but adds two defenses:
  - Proxy denies any request whose URI or `User-Agent` contains
    `\x1b` (ESC) or `\x07` (BEL); CR/LF is also stripped.
  - SVD floor enforcement upgrades to ≥10.0.1 / 9.4.6 / 9.3.8 / 9.2.10
    where the underlying bug is fixed.

### SSRF via `enableSplunkWebClientNetloc`

- CVE-2025-20371: when `enableSplunkWebClientNetloc = true`, Splunk
  Web becomes an unauthenticated SSRF gateway.
- The skill's mitigation: explicit `enableSplunkWebClientNetloc =
  false` in the rendered `web.conf`.

## Logging and detection

The renderer's `handoff/soc-alerting-runbook.md` lists the SPL queries
the SOC must alert on. Critical detections:

- Three failed logins from one IP within 5 minutes.
- Capability changes on any role.
- App installs / uploads.
- File-integrity-monitor alerts on `$SPLUNK_HOME/etc/auth/splunk.secret`.
- TLS handshake error spikes.

## Subscribing to advisories

- [https://advisory.splunk.com/](https://advisory.splunk.com/) RSS feed.
- [https://www.cisa.gov/known-exploited-vulnerabilities-catalog](https://www.cisa.gov/known-exploited-vulnerabilities-catalog) JSON feed.
- Splunk Trust mailing list (operator-managed).

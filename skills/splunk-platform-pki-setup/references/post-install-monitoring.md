# Post-Install Monitoring

Once the new PKI is in place, the operator needs ongoing
visibility into:

- Cert expiry across the fleet (catch the next rotation in
  advance).
- TLS handshake errors (early warning for cert / chain / cipher
  drift).
- KV Store EKU validation (Splunk 9.4+ broke many existing
  deployments; the validation is non-recoverable without manual
  intervention).
- Drift from the rendered configuration (someone edits
  `server.conf` by hand).

## SSL Certificate Checker (Splunkbase 3172)

Splunk publishes the
[SSL Certificate Checker Add-on](https://splunkbase.splunk.com/app/3172).
It walks the filesystem, finds PEM files, and indexes their
expiry dates + subjects to `index=ssl_certificate_checker`.

```bash
# Install
bash skills/splunk-app-install/scripts/setup.sh \
    --app splunk_ssl_certificate_checker \
    --splunkbase-id 3172

# Configure on each Splunk host (the add-on auto-discovers most
# Splunk paths). Add custom paths if the renderer placed certs
# outside /opt/splunk/etc/auth/.
```

Sample monitoring search:

```spl
index=ssl_certificate_checker
| eval days_to_expire = round((notAfter - now()) / 86400)
| where days_to_expire <= 30
| stats min(days_to_expire) as min_days
        values(host) as hosts by subject
| sort min_days
```

Wire to Splunk On-Call / ITSI / email to alert at 30 / 14 / 7
days before expiry.

## `/services/server/health/splunkd` REST endpoint

Per
[About proactive Splunk component monitoring](https://help.splunk.com/en/splunk-enterprise/administer/monitor/10.2/proactive-splunk-component-monitoring-with-the-splunkd-health-report/about-proactive-splunk-component-monitoring),
splunkd exposes a structured health report at
`/services/server/health/splunkd`. It includes feature health for
`SearchHeadConnectivity`, `KVStoreReplication`, `IndexerCluster`,
and others — many of which surface TLS issues indirectly.

```bash
# JSON output of full health
curl -k -s -u admin:<pw> https://<host>:8089/services/server/health/splunkd | jq .

# Just the failing features
curl -k -s -u admin:<pw> https://<host>:8089/services/server/health/splunkd \
  | jq '.entry[].content.features | to_entries[] | select(.value.health != "green")'
```

The `health.log` file at `$SPLUNK_HOME/var/log/health.log` is the
on-host equivalent.

## CIM Certificates data model

The Splunk
[Common Information Model — Certificates data model](https://help.splunk.com/en/splunk-enterprise/common-information-model/8.5/data-models/certificates)
provides standardized fields for cert lifecycle events:
`cert_subject`, `cert_issuer`, `cert_serial`, `cert_signature`,
`cert_validity_start`, `cert_validity_end`, plus tags `certificate`
and `key`.

The SSL Certificate Checker output is CIM-compliant. ES /
Mission Control / ITSI dashboards can hang off the data model.

## Splunk Health Assistant Add-on

For FIPS migrations and major version upgrades, install the
[Splunk Health Assistant Add-on](https://splunkbase.splunk.com/app/6589)
to discover SSL / TLS issues that would block the upgrade. Run it
in Monitoring Console with the **Security** category and the
`ssl` / `upgrades` tags.

## Drift detection

The skill's `inventory` phase produces
`pki/inventory/<host>.json` with the discovered cert paths,
expiry, and config knobs. Diff against the rendered output to
catch hand-edits:

```bash
bash skills/splunk-platform-pki-setup/scripts/setup.sh --phase inventory \
    --target all \
    --admin-password-file /tmp/splunk_admin_password

diff -u splunk-platform-pki-rendered/pki/inventory/<host>.json \
        splunk-platform-pki-rendered/pki/inventory/<host>.json.expected
```

`<host>.json.expected` is the snapshot the renderer produces at
apply-time so a diff highlights any drift.

## Search head connectivity probes

For continuous TLS handshake monitoring across the cluster:

```spl
| rest /services/server/info splunk_server=*
| stats count by splunk_server, ssl_cipher, ssl_version
```

Catches mismatched cipher suites or TLS versions across the
fleet.

## TLS handshake error detection

```spl
index=_internal sourcetype=splunkd
    ("SSL" OR "TLS" OR "handshake" OR "verify failed" OR "EKU")
    log_level=ERROR
| stats count by host, log_level, message
| sort -count
```

Wire to a saved search alert to catch handshake degradation as
soon as it starts.

## KV Store start failure detection

```spl
index=_internal sourcetype=mongod
    ("OpenSSL" OR "x509" OR "EKU" OR "verify")
    severity=E
| stats count by host, message
```

This catches the KV-Store-7.0 EKU bite that surfaces only at
restart.

## Splunk On-Call integration

Wire all of the above to On-Call routing keys (per
`splunk-oncall-setup`) so the platform team gets paged on cert
expiry and TLS error spikes. Sample routing key hierarchy:

```
splunk-pki/<env>/expiry-warning
splunk-pki/<env>/expiry-critical
splunk-pki/<env>/handshake-failure
splunk-pki/<env>/kvstore-tls-failure
```

## Schedule

| Check | Frequency |
|---|---|
| Cert expiry inventory | every 4 h |
| TLS handshake error count | every 15 min |
| KV Store TLS error | real-time alert |
| `/services/server/health/splunkd` | every 5 min |
| Renderer-output vs live drift | daily |
| Full `inventory` phase | weekly + before any rotation |

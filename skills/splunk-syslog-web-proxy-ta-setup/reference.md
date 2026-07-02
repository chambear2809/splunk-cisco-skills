# Syslog, Web, And Proxy Add-ons Reference

## Profiles

| Selector | App directory | Splunkbase | Verified | Default transport |
| --- | --- | --- | --- | --- |
| `apache` | `Splunk_TA_apache` | `3186` | `3.0.0` | Local file / UF monitor |
| `nginx` | `Splunk_TA_nginx` | `3258` | `3.3.0` | Local file / UF monitor |
| `iis` | `Splunk_TA_microsoft-iis` | `3185` | `2.0.0` | Windows UF / IIS log files |
| `tomcat` | `Splunk_TA_tomcat` | `2911` | `4.0.0` | Local file / UF monitor; optional JMX input |
| `haproxy` | `Splunk_TA_haproxy` | `3135` | `2.0.0` | Local file / UF monitor |
| `squid` | `Splunk_TA_squid` | `2965` | `2.1.0` | SC4S/syslog handoff |
| `bluecoat` | `Splunk_TA_bluecoat-proxysg` | `2758` | `3.9.0` | SC4S/syslog handoff |
| `forcepoint` | `Splunk_TA_websense-cg` | `2966` | `1.1.0` | SC4S/syslog handoff |
| `checkpoint` | `Splunk_TA_checkpoint_log_exporter` | `5478` | `1.2.0` | SC4S/syslog handoff |
| `f5` | `Splunk_TA_f5-bigip` | `2680` | `6.5.1` | SC4S/syslog or package iControl/Telemetry inputs |
| `citrix` | `Splunk_TA_citrix-netscaler` | `2770` | `8.2.3` | SC4S/syslog or NITRO/IPFIX inputs |
| `infoblox` | `Splunk_TA_infoblox` | `2934` | `2.2.0` | SC4S/syslog handoff |

### Tomcat `10.5` compatibility note

The repo-verified Tomcat package remains `4.0.0`. The latest public listing
observed July 2, 2026 was `4.0.1`, with platform versions `9.1` through `10.4`
and no advertised Splunk Cloud `10.5` support. For a `10.5` Cloud target,
surface that warning and require operator/vendor confirmation before production
use. Do not add an installer block; updated listing metadata or separately
reviewed vendor evidence can satisfy the handoff.

## Guardrails

- Do not match broad generic source types such as `syslog`, `_json`,
  `httpevent`, or `access_combined` as product readiness. Use exact package
  source types or constrain by source/product.
- Keep transport ownership explicit in each rendered plan.
- Deploy search-time knowledge objects on the search tier and transport inputs
  on the collection owner: UF, HF/syslog, SC4S, or product-specific API input.

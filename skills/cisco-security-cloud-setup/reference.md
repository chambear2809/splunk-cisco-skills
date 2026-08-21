# Cisco Security Cloud — Reference

Reference for the Cisco Security Cloud package and its configurable input types.

## Package Identity

| Property | Value |
|---|---|
| App name | `CiscoSecurityCloud` |
| Splunkbase ID | `7404` |
| Local package pattern | `cisco-security-cloud_*` |
| Local package in repo | `splunk-ta/cisco-security-cloud_363.tar.gz` |
| Packaged version inspected | `3.6.3` |
| Repo-verified Splunkbase version | `3.6.10` |
| Latest public listing observed August 20, 2026 | `3.6.10` |
| Repo-verified `3.6.10` platforms | `9.1` through `10.5`; Cloud-compatible |
| Superseded `3.6.6` platforms | `9.1` through `10.5`; Cloud-compatible |
| Superseded `3.6.7` platforms | `9.1` through `10.4`; no advertised `10.5` support |

The `10.5` platform gap that previously motivated a `3.6.6` pin was specific to
`3.6.7`. The `3.6.x` line re-advertises `10.5` from `3.6.8` onward, and `3.6.10`
was downloaded, unpacked, and inspected here, so the verified pin and the current
public release are now the same version and no review override is needed.
Splunkbase also publishes a parallel `4.0.x` line, most recently `4.0.2`, which
the listing does not designate as the current release; do not install `4.0.x`
without vendor approval and review.

On Splunk Cloud `10.5`, pin repo-verified `3.6.10`. The setup wrapper delegates
the default install to the shared installer without forcing the public-latest
release. `--target-splunk-version` and optional `--app-version` make the
release contract explicit. Before any post-install mutation it reads the actual
installed version, then refuses an unverified package unless
`--accept-unsupported-platform` is backed by documented vendor approval for
that exact version and stack.

## App-Level Configuration

| Setting | Location | Notes |
|---|---|---|
| Logging level | `ciscosecuritycloud_settings.conf` stanza `logging` | Values: `DEBUG`, `INFO`, `WARN`, `ERROR`, `CRITICAL` |

## Product Matrix

The package ships a UCC `globalConfig.json` that defines the supported inputs.
This repo exposes them through product keys in `products.json` and
`configure_product.sh`.

| Product key | Input type | Title | Required user-supplied fields | Secret fields | Common defaults |
|---|---|---|---|---|---|
| `duo` | `sbg_duo_input` | DUO | `api_host` | `ikey`, `skey`, `proxy_password` | `index=cisco_duo`, `interval=120`, `sourcetype=cisco:duo` |
| `secure_malware_analytics` | `cisco_sma_input` | Cisco Secure Malware Analytics | `api_host`, `after` | `api_key`, `proxy_password` | `index=cisco_sma`, `interval=300`, `sourcetype=cisco:sma:submissions` |
| `xdr` | `sbg_xdr_input` | Cisco XDR | `region`, `auth_method`, `client_id`, `xdr_import_time_range` | `refresh_token`, `access_token`, `password` | `index=cisco_xdr`, `interval=300`, `sourcetype=cisco:xdr:incidents` |
| `secure_firewall_syslog` | `sbg_sfw_syslog_input` | Cisco Secure Firewall Syslog | `type`, `port`, `sourcetype`, `event_types` | none | `index=cisco_sfw_ftd_syslog`, `interval=600` |
| `secure_firewall_asa_syslog` | `sbg_sfw_asa_syslog_input` | Cisco Secure Firewall ASA Syslog | `type`, `port`, `sourcetype`, `event_types` | none | `index=cisco_sfw_ftd_syslog`, `interval=600` |
| `secure_firewall_estreamer` | `sbg_fw_estreamer_input` | Cisco Secure Firewall eStreamer | `fmc_host`, `fmc_port`, `estreamer_import_time_range`, `event_types` | `pkcs_certificate`, `password` | `index=cisco_secure_fw`, `interval=600`, `sourcetype=cisco:sfw:estreamer` |
| `secure_firewall_api` | `sbg_sfw_api_input` | Cisco Secure Firewall API | `fmc_host`, `username` | `password` | `index=cisco_sfw_api`, `interval=300`, `sourcetype=cisco:sfw:policy` |
| `multicloud_defense` | `sbg_multicloud_defense_input` | Cisco Multicloud Defense | none | none | `index=cisco_multicloud_defense`, `interval=300`, `sourcetype=cisco:multicloud:defense`, `port=8088` |
| `email_threat_defense` | `sbg_etd_input` | Email Threat Defense | `client_id`, `etd_region`, `etd_import_time_range` | `etd_api_key`, `client_secret`, `proxy_password` | `index=cisco_etd`, `interval=3600`, `sourcetype=cisco:etd` |
| `secure_network_analytics` | `sbg_sna_input` | Secure Network Analytics | `ip_address`, `domain_id`, `username` | `password` | `index=cisco_sna`, `interval=300`, `sourcetype=cisco:sna` |
| `secure_endpoint` | `sbg_se_input` | Cisco Secure Endpoint | `api_host`, `client_id`, `se_import_time_range`, `event_types`, `groups` | `api_key` | `index=cisco_se`, `interval=300`, `sourcetype=cisco:se` |
| `vulnerability_intelligence` | `sbg_cvi_input` | Cisco Vulnerability Intelligence | `api_host` | `api_key` | `index=cisco_cvi`, `interval=86400`, `sourcetype=cisco:cvi` |
| `cii_webhook` | `sbg_cii_input` | Cisco Identity Intelligence Webhook | `cii_client_id`, `cii_api_url`, `cii_token_url`, `cii_audience`, `integration_method`, `hec_url` | `cii_json_text`, `cii_client_secret`, `aws_access_secret`, `cii_external_id` | `index=cisco_cii`, `interval=300`, `sourcetype=cisco:cii` |
| `cii_aws_s3` | `sbg_cii_aws_s3_input` | Cisco Identity Intelligence AWS S3 | `cii_client_id`, `cii_api_url`, `cii_token_url`, `cii_audience`, `integration_method`, `s3_bucket_url`, `s3_bucket_region` | `cii_json_text`, `cii_client_secret`, `aws_access_secret`, `cii_external_id` | `index=cisco_cii`, `interval=300`, `sourcetype=cisco:cii` |
| `ai_defense` | `sbg_ai_defense_input` | Cisco AI Defense | none | none | `index=cisco_ai_defense`, `interval=300`, `sourcetype=cisco:ai:defense`, `port=8088` |
| `isovalent` | `sbg_isovalent_input` | Isovalent Runtime Security | none | none | `index=cisco_isovalent`, `interval=300`, `port=8088` |
| `isovalent_edge_processor` | `sbg_isovalent_edge_processor_input` | Isovalent Edge Processor Runtime Security | none | none | `index=cisco_isovalent`, `interval=300`, `port=8088` |
| `secure_client_nvm` | `sbg_nvm_input` | Cisco Secure Client NVM | none | none | `index=main`, `interval=300`, `sourcetype=cisco:nvm:*` |
| `secure_workload` | `sbg_sw_input` | Cisco Secure Workload | `type`, `port` | none | `index=cisco_secure_workload`, `interval=60`, `sourcetype=cisco:secure:workload` |

For Multicloud Defense, the correct FQDN-resolution sourcetype is
`cisco:multicloud:defense:fqdn_resolve`. Package `3.6.10` renames the
`props.conf` stanza from the misspelled `cisco:multicloud:defense:fqdn_resoleve`
used through `3.6.6`, confirming the pinned SCAN catalog `2026_08_01_2130`
correction. The misspelling belongs only to older catalog metadata and to
migration notes for stacks still running `3.6.6` or earlier; never use it in new
searches or validation.

Package `3.6.10` also adds `props.conf` coverage for granular Duo sourcetypes
(`cisco:duo:account`, `cisco:duo:activity`, `cisco:duo:administrator`,
`cisco:duo:endpoint`, `cisco:duo:telephony`, `cisco:duo:telephony_v2`,
`cisco:duo:trust_monitor`, `cisco:duo:user`) and for Email Verdict/Message
sourcetypes (`cisco:evm:authentication`, `cisco:evm:dns_activity`,
`cisco:evm:http_activity`). The modular input inventory is unchanged from
`3.6.6`, so no input stanza, parameter, or handler path changes with this
upgrade.

## SCAN August 1, 2026 sourcetype boundary

SCAN catalog `2026_08_01_2130` reflects both current canonical search families
and the separately published Cisco Security Cloud `4.0.x` line. It must not be
used to pretend that every one of those families is emitted by the repo-pinned
`3.6.10` package:

- Duo no longer lists the aggregate `cisco:duo` label, but `3.6.10` still uses
  it as the modular-input ingress value and routes records into the retained
  `cisco:duo:*` family. Preserve existing input stanzas; use the granular
  family for data and dashboard completion checks.
- EVM adds `cisco:evm:authentication`, `cisco:evm:dns_activity`, and
  `cisco:evm:http_activity`. These are parser-backed in `3.6.10`; EVM remains
  an install-and-ingest handoff because the package exposes no EVM modular
  input.
- Isovalent removes the aggregate `cisco:isovalent` and
  `cisco:isovalent:edge_processor` catalog labels while retaining their child
  families, including `cisco:isovalent:alert`,
  `cisco:isovalent:telemetry:network`,
  `cisco:isovalent:edge_processor:alert`, and
  `cisco:isovalent:edge_processor:telemetry:network`. Package `3.6.10` still
  contains the two aggregate parser stanzas, so they remain ingress/version
  compatibility rather than completion targets.
- Multicloud Defense removes the generic `gateway` parser label. That stanza
  can remain in installed packages, but it is not an MCD product-completion
  sourcetype; validate `cisco:multicloud:defense:*` instead.
- Secure Firewall replaces the catalog-level `cisco:ftd:syslog` label with the
  `4.0.x` granular families: `cisco:ftd:adv:conn`, `cisco:ftd:adv:dns`,
  `cisco:ftd:adv:ftp`, `cisco:ftd:adv:http`, `cisco:ftd:adv:notice`,
  `cisco:ftd:adv:weird`, `cisco:ftd:connection`,
  `cisco:ftd:connection:security`, `cisco:ftd:correlation`,
  `cisco:ftd:discovery`, `cisco:ftd:file`, `cisco:ftd:intrusion`,
  `cisco:ftd:intrusionpacket`, `cisco:ftd:malware`, and
  `cisco:ftd:useractivity`. The repo-pinned `3.6.10` line still parses
  `cisco:ftd:syslog`; validate that value on `3.6.x` and require the granular
  families only after an explicitly reviewed `4.0.x` deployment.

## Endpoint Pattern

Each input type is managed through the app’s custom admin handler endpoint:

```text
/servicesNS/nobody/CiscoSecurityCloud/CiscoSecurityCloud_<input_type>
```

Examples:

- `CiscoSecurityCloud_sbg_xdr_input`
- `CiscoSecurityCloud_sbg_se_input`
- `CiscoSecurityCloud_sbg_fw_estreamer_input`

## Validation Notes

- Custom handler stanzas can be enumerated through the same endpoint path.
- Input configuration is app-owned, so use the app handlers instead of editing
  files manually.
- Create the target index before or during input setup if the chosen index does
  not already exist.

## Completion Validation

`validate.sh --completion`/`--strict` requires configured input stanzas,
event-flow evidence for event-capable inputs, and visible views. The no-flag
form remains warning-oriented diagnostics; `--skip-data-flow` is incompatible
with strict completion.

# Splunk Supported Add-ons Reference

Research date: 2026-06-06.

## Unix/Linux Domain Coverage

This skill covers the first supported-addons router domain:

| Profile | Add-on | App folder | Splunkbase | Latest researched |
| --- | --- | --- | --- | --- |
| `unix-linux-os-scripts` | Splunk Add-on for Unix and Linux | `Splunk_TA_nix` | `833` | `10.2.0`, October 8, 2025 |
| `linux-collectd-auditd` | Splunk Add-on for Linux | `Splunk_TA_Linux` | `3412` | `2.1.1`, March 30, 2026 |

`Splunk_TA_nix` is the broader *nix scripted-input and file-monitoring add-on.
`Splunk_TA_Linux` is a separate Linux CollectD/AuditD add-on for HEC, TCP, and
AuditD workflows.

## Router Coverage Boundary

The router tracks all 80 entries currently listed in the official Splunk
Supported Add-ons glossary. Only the Unix/Linux domain is implemented as a
first-class renderer inside this skill:

- `first_class_profile`: `Linux`, `Unix and Linux`
- `handoff_profile`: official entries with an existing local skill that owns the
  domain workflow, such as AppDynamics, selected Cisco add-ons, CrowdStrike FDR,
  VMware, SaaS/security add-ons, shared web/proxy/parser add-ons,
  package-verified database add-ons, Microsoft Exchange, Microsoft SCOM, NetApp
  ONTAP, Carbon Black, Symantec Endpoint Protection, and Asset and Risk
  Intelligence
- `install_only_handoff`: official entries that can safely route package
  delivery to `splunk-app-install` while configuration remains documentation- or
  product-specific. Entries without a more specific local skill use this generic
  handoff instead of failing as gaps.

Use `bash skills/splunk-supported-addons-setup/scripts/setup.sh --phase coverage
--json` to audit this classification before expanding another domain profile.
Use `--phase render --profile "<official add-on name>"` to emit either a
first-class Unix/Linux profile packet or a generic official-add-on handoff
packet.

## Expanded Handoff Families

The router now delegates package-verified SaaS, security, and parser profiles
to first-class setup skills when the workflow is larger than package delivery:

| Supported add-on entries | Owning skill | Readiness packs |
| --- | --- | --- |
| Salesforce | `splunk-salesforce-ta-setup` | `salesforce` |
| Box | `splunk-box-ta-setup` | `box` |
| CyberArk, CyberArk EPM | `splunk-cyberark-ta-setup` | `cyberark_epv_pta`, `cyberark_epm` |
| RSA SecurID, RSA SecurID CAS | `splunk-rsa-securid-ta-setup` | `rsa_securid_am`, `rsa_securid_cas` |
| Apache, NGINX, IIS, Tomcat, HAProxy, Squid, Blue Coat ProxySG, Forcepoint Web Security, Check Point Log Exporter, F5 BIG-IP, Citrix NetScaler, Infoblox | `splunk-syslog-web-proxy-ta-setup` | product-specific web/proxy/parser packs |
| SQL Server, MySQL, Oracle Database | `splunk-database-ta-setup` | `mssql_database`, `mysql_database`, `oracle_database` |
| Microsoft Exchange, Microsoft SCOM | `splunk-microsoft-exchange-ta-setup`, `splunk-microsoft-scom-ta-setup` | `microsoft_exchange`, `microsoft_scom` |
| NetApp Data ONTAP, ONTAP Extractions, ONTAP Indexes | `splunk-netapp-ontap-ta-setup` | `netapp_ontap` |
| Carbon Black, Symantec Endpoint Protection | `splunk-security-appliance-ta-setup` | `carbon_black`, `symantec_endpoint_protection` |

CyberArk EPV/PTA remains explicitly archived/not-supported and parser-only. RSA
DLP remains a generic install-only handoff because it is not covered by the
verified RSA SecurID package set. Imperva, McAfee/Trellix, Sophos, DLP,
Websense DLP, and OSSEC remain generic install-only until exact packages are
extracted and verified.

## Current Research Notes

- The Splunk Supported Add-ons glossary says supported add-ons provide source
  types and, when possible, CIM knowledge. It also states that data defaults to
  `main` unless the administrator configures a different index in the input.
- The Unix and Linux supported-addons page points to Splunk Add-on for Unix and
  Linux and says it can collect data from Unix and Linux hosts through a
  forwarder, and can feed ITSI and Enterprise Security.
- The Splunkbase listing for Splunk Add-on for Unix and Linux shows version
  `10.2.0`, released October 8, 2025, with Splunk Enterprise/Splunk Cloud,
  platform versions `10.4` (default), `10.3`, `10.2`, `10.1`, `10.0`, `9.4`,
  `9.3`, and `9.2`, and CIM `6.x`.
- The Unix and Linux release notes list version `10.2.0` compatibility as
  Splunk platform `9.3.x`, `9.4.x`, and `10.x`, CIM `6.2.0`, and supported
  Unix operating systems. The Splunkbase compatibility table is broader for
  platform `9.2`.
- The Unix and Linux docs require inputs to be enabled after install. The setup
  page is available only on heavy forwarders and full Splunk Enterprise
  instances. Universal Forwarders require configuration files.
- The Unix and Linux docs say to copy only the input stanzas being changed into
  `Splunk_TA_nix/local/inputs.conf`, not the whole default file.
- The Unix and Linux docs require metric indexes before enabling metric source
  types: `cpu_metric`, `df_metric`, `interfaces_metric`, `iostat_metric`,
  `ps_metric`, and `vmstat_metric`.
- The Unix and Linux docs require execute rights for `bin`, and say Splunk must
  run as root for the add-on to work properly.
- For `Splunk_TA_nix` 8.8.0 and later, eventtypes are narrower and the
  `nix_ta_custom_eventtype` escape hatch exists for required local events.
- The Splunkbase listing for Splunk Add-on for Linux shows version `2.1.1`,
  released March 30, 2026, with Splunk Enterprise/Splunk Cloud, platform
  versions `10.4` (default), `10.3`, `10.2`, `10.1`, `10.0`, `9.4`, and `9.3`,
  and CIM `5.x`.
- The Splunk Add-on for Linux GitHub Pages release notes still show an older
  compatibility table for version `2.1.1`. Treat Splunkbase as the current
  install compatibility source and verify before pinning older platforms.
- The Splunk Add-on for Linux source types are `linux:collectd:http:json`,
  `linux:collectd:http:metrics`, `linux:collectd:graphite`, and `linux:audit`.
- The Splunk Add-on for Linux docs say CollectD JSON over HEC maps better to
  ITSI Linux KPIs than Graphite because Graphite splits related measurements.
- The Splunk Add-on for Linux docs state that TCP cannot collect metrics; HEC is
  required for metrics.
- For AuditD in Splunk Add-on for Linux, set `log_format=ENRICHED` for proper
  CIM mapping.
- The Splunk Add-on for Linux docs warn that Deployment Server is supported for
  deploying unconfigured add-ons only; deploying configured add-ons to many
  forwarders can cause duplicate data collection and credential-vault problems.
- The general Splunk Supported Add-ons installation docs recommend turning off
  add-on visibility on search heads, checking search head cluster and indexer
  cluster package validation requirements, using IDM or heavy forwarders for
  Classic Splunk Cloud modular/scripted inputs, and checking each add-on's docs
  for required forwarder placement.
- The troubleshooting docs recommend `_internal` searches scoped to add-on folder
  names, add-on-specific DEBUG logging, visibility checks, conflict checks with
  `btool`, network/firewall validation for external APIs, and stopping collecting
  add-ons before stopping heavy forwarders to reduce data-loss risk.

## Source Links

- Supported Add-ons overview: https://help.splunk.com/en/supported-add-ons/about-the-splunk-supported-add-ons
- Unix and Linux supported-addons page: https://help.splunk.com/en/splunk-cloud-platform/get-data-in/splunk-supported-add-ons/unix-and-linux
- Splunk Add-on for Unix and Linux Splunkbase: https://splunkbase.splunk.com/app/833
- Splunk Add-on for Unix and Linux release notes: https://splunk.github.io/splunk-add-on-for-unix-and-linux/Releasenotes/
- Splunk Add-on for Unix and Linux install: https://splunk.github.io/splunk-add-on-for-unix-and-linux/Install/
- Splunk Add-on for Unix and Linux inputs: https://splunk.github.io/splunk-add-on-for-unix-and-linux/Enabledataandscriptedinputs/
- Splunk Add-on for Unix and Linux source types: https://splunk.github.io/splunk-add-on-for-unix-and-linux/Sourcetypes/
- Linux supported-addons page: https://help.splunk.com/en/splunk-cloud-platform/get-data-in/splunk-supported-add-ons/linux
- Splunk Add-on for Linux Splunkbase: https://splunkbase.splunk.com/app/3412
- Splunk Add-on for Linux overview: https://splunk.github.io/splunk-add-on-for-linux/
- Splunk Add-on for Linux release notes: https://splunk.github.io/splunk-add-on-for-linux/Releasenotes/
- Splunk Add-on for Linux install: https://splunk.github.io/splunk-add-on-for-linux/Install/
- Splunk Add-on for Linux CollectD: https://splunk.github.io/splunk-add-on-for-linux/Configure/
- Splunk Add-on for Linux HEC: https://splunk.github.io/splunk-add-on-for-linux/Configure2/
- Splunk Add-on for Linux TCP: https://splunk.github.io/splunk-add-on-for-linux/Configure3/
- Splunk Add-on for Linux AuditD: https://splunk.github.io/splunk-add-on-for-linux/Configure4/
- Splunk Add-on for Linux source types: https://splunk.github.io/splunk-add-on-for-linux/Sourcetypes/
- Install supported add-ons in distributed Splunk Enterprise: https://help.splunk.com/en/splunk-cloud-platform/get-data-in/splunk-supported-add-ons/about-the-splunk-supported-add-ons/installing-splunk-add-ons/install-an-add-on-in-a-distributed-splunk-enterprise-deployment
- Install supported add-ons in Splunk Cloud Platform: https://help.splunk.com/en/splunk-cloud-platform/get-data-in/splunk-supported-add-ons/about-the-splunk-supported-add-ons/installing-splunk-add-ons/install-an-add-on-in-splunk-cloud-platform
- Supported add-ons troubleshooting: https://help.splunk.com/en/splunk-cloud-platform/get-data-in/splunk-supported-add-ons/about-the-splunk-supported-add-ons/troubleshooting

# Cisco network and data-center package review (2026-11-16)

This review records package evidence for the network/data-center families. Live
listing metadata was read from each Splunkbase app page's structured
`__NEXT_DATA__` release object and cross-checked with the release download
endpoint. Listing pages: [7538](https://splunkbase.splunk.com/app/7538),
[7539](https://splunkbase.splunk.com/app/7539),
[6872](https://splunkbase.splunk.com/app/6872),
[7777](https://splunkbase.splunk.com/app/7777),
[7828](https://splunkbase.splunk.com/app/7828), and
[2731](https://splunkbase.splunk.com/app/2731).

## Downloaded and inspected

| ID | package identity/version | publisher/support | package evidence | contract findings |
|---|---|---|---|---|
| 6872 | `splunk_app_stream_ipfix_cisco_hsl` 4.0.0 | Cisco Systems; production mapping add-on | `/Users/alecchamberlain/Documents/GitHub/splunk-cisco-skills/splunk-ta/cisco-enterprise-networking-netflow-add-on-for-splunk_400.tgz`; SHA-256 `94722579e0f120e0b5c93c9eac2873fb94f4749134b08652f578bb398803fc52` | 24 archive members; HSL/IPFIX maps and one `home` view; no inputs or indexes; targets forwarders and search heads; optional dependency for Enterprise Networking dashboards. |
| 7777 | `cisco_dc_networking_app_for_splunk` 2.0.0 | Cisco Systems; listing marks Beta | `cisco-dc-networking_200.tar.gz`; SHA-256 `297cab257d5b608e2f9aee987eea3f2041b8944c93e2bc5e6a57fd1371fc09a9` | 898 archive members; 7 input groups and 88 views. Specs confirm ACI `apic_*`, Nexus Dashboard `nd_*`, Nexus 9K `nexus_9k_*`, plus Hyperfabric bearer-token and MDS/SAN dataset inputs. Existing wrappers only configure ACI/ND/Nexus9K; Hyperfabric and MDS/SAN remain manual handoff. |
| 7538 | `TA_cisco_catalyst` 4.0.60 | Cisco Systems; production/stable | `cisco-enterprise-networking-add-on-for-splunk_4060.tgz`; SHA-256 `bbf2ace979e3fc9b15fbe5c8c30b212fdf474931a7b428f361219e6c19a1172d` | 43 modular-input stanzas, all shipped disabled, with `python.required = 3.9, 3.13`; adds/retains Catalyst Center, SD-WAN, ISE, Cyber Vision, report, health, interface-stat, and migration/runtime handlers. Existing setup remains pinned to 3.2.44 because its 4.x account/input additions are not yet modeled. |
| 7539 | `cisco-catalyst-app` 4.0.20 | Cisco Systems; production visualization app | `cisco-enterprise-networking-app-for-splunk_4020.tgz`; SHA-256 `0d9a8d85a50a408f6cfd1044425dfea28c4b2cb94d3ab570c073b296f8cc0382` | 36 shipped views plus Studio views; macros remain `cisco_catalyst_app_index`, `cisco_catalyst_sdwan_index`, and the same broad sourcetype allow-list. `summariesonly` defaults to `summariesonly=false allow_old_summaries=true`; retain the 3.2.20 pin until paired TA/app dashboard and acceleration behavior is re-reviewed. |
| 7828 | `Splunk_TA_Cisco_Intersight` 3.2.2 | Cisco Systems, Inc.; listing advertises Enterprise 10.5 and Cloud | `/Users/alecchamberlain/Documents/GitHub/splunk-cisco-skills/splunk-ta/cisco-intersight-add-on-for-splunk_322.spl`; SHA-256 `5046084bbe9d0ce76dcdd442e1b231f9f0a86cc5aef5bb3536d0e73b2c333a5f` | 772 archive members; OAuth account handlers, 4 input families, checkpoint/migration utilities, and 15 views. Sourcetypes include audit records, alarms, metrics, inventory, contracts, licenses, targets, and profiles. |
| 2731 | `Splunk_TA_cisco-ucs` 5.0.0 | Splunk, Inc.; production/stable Splunk-developed add-on | `/Users/alecchamberlain/Documents/GitHub/splunk-cisco-skills/splunk-ta/splunk-add-on-for-cisco-ucs_500.spl`; SHA-256 `dbda2c808b0cd56881e34b43c07ccfb0d6de4ec8623e9ffc6d6356efae181570` | 398 archive members; `cisco_ucs_task` ships disabled (`disabled=1`) with 300-second default and `cisco:ucs`; repository `configure_task.sh` enables an operator-created task by serializing `disabled=0`. Migration utilities cover existing inputs/passwords/templates; ships Monitoring Dashboard, Inputs, and Configuration views. |

## Preserved pins and package boundaries

The public listing defaults observed on 2026-11-16 were 7538 `4.0.60` and
7539 `4.0.20`; both packages were subsequently downloaded and inspected. Their
reviewed pins (`3.2.44` and `3.2.20`) remain unchanged because the 4.x contract
adds inputs and changes acceleration/dashboard behavior that existing wrappers
do not yet model. The same fail-closed boundary applies to future pin advances
until paired TA/app migration tests are complete.

The 6872 package is a mapping add-on rather than a collector: installation does
not replace Stream, SC4S, or another flow receiver. The 7777 2.0 listing is Beta,
so Cloud/Enterprise compatibility declarations do not remove the migration and
dashboard validation gate. Hyperfabric requires `hyperfabric_bearer_token` and
MDS/SAN reuses ND account fields; neither is accepted by the current
`configure_account.sh` type switch, so those families are deliberately
unsupported by automation rather than silently treated as configured.

## Final platform and adoption decision

Intersight 3.2.2 was inspected successfully, but its exact live release record
lists Splunk versions only through 10.5. The shared pin remains 3.1.1, whose
current release evidence includes Enterprise 10.6; Cloud 10.5 support for the
newer package does not establish Enterprise 10.6 support. UCS advances to
5.0.0. DC Networking stays on 1.2.2 while its 2.0.0 Beta migration is qualified.
Enterprise Networking 7538/7539 and optional 6872 stay on their reviewed
3.2.44/3.2.20/2.1.0 set until the coordinated 4.x cutover is qualified.

## Newer parallel Intersight release

Live release metadata also exposes **3.3.1**, published 2026-11-16, while the
listing still designates **3.2.2** as default. Exact 3.3.1 release API ID is
125478; it advertises Enterprise 10.6/10.7 and Cloud. This is distinct from
the listing-default 3.2.2 platform declaration and from selected pin 3.1.1.
The helper downloaded and safely extracted `cisco-intersight-add-on-for-splunk_331.spl`
as `Splunk_TA_Cisco_Intersight` 3.3.1. Binary SHA-256:
`e09739a0aae624b8fc7563badf35f67e8dfa3de171df5c35634e9ee0228b7e12`.

Compared with inspected 3.2.2, `default/inputs.conf`, `restmap.conf`,
`macros.conf`, and the account/settings specs are identical.
`README/inputs.conf.spec` adds `physical_disk_metrics`, with a minimum
30-minute collection interval. `bin/metrics.py` and
`bin/Splunk_TA_Cisco_Intersight_rh_metrics.py` expose that field, and the
account handler creates a separate `_physical_disk_metrics` input at interval
1800. The repository wrapper currently creates device/network metric inputs
without that new disk input. Retain the selected pin until the 3.3.x default
input creation, disk telemetry cadence, upgrade/checkpoint, and dashboard
behavior are qualified as a complete migration. No live runtime test was run.

## Stream collector dependency inspection

The NetFlow path also needs a receiver: mapping package 6872 does not collect
flows. The helper downloaded and safely extracted all three current Stream
8.1.7 archives on 2026-11-16. Exact identities, source URLs, platform metadata,
view IDs and binary hashes are in the machine-readable package evidence.

| ID / identity | 8.1.7 binary SHA-256 |
|---|---|
| 1809 / `splunk_app_stream` | `97bd05dede16195f868f102020676cd640490b05bfc153d2fd30ebc77e78d5af` |
| 5238 / `Splunk_TA_stream` | `455e34ad2ab7012d34e498dbeb2f40e994327ec2504f45b4248bb2402572a146` |
| 5234 / `Splunk_TA_stream_wire_data` | `2734916023b526d49a37977219e2c309cfe60231f4383ebd3a5814abfa904d6e` |

Static inspection of `default/app.conf`, `inputs.conf`, `streamfwd.conf`,
`README/streamfwd.conf.spec`, shipped views and app startup-script declarations
confirms the three identities and their separate deployment roles. The app
ships 19 views; forwarder and wire-data packages ship no views. Wire data owns
normalization/knowledge objects, not capture. The forwarder input is
`streamfwd://streamfwd`, with `splunk_stream_app_location`; management defaults
to loopback `127.0.0.1:8889`. NetFlow receiver fields remain
`netflowReceiver.<N>.ip`, `.port`, `.decoder` (`netflow`/`sflow`), optional
filter/decoding threads/template expiry, and enterprise element mappings.

The 8.1.7 forwarder spec additionally documents management credentials created
by native `streamfwd --setmgmtcreds`: hash/encrypted values plus a protected
`local/streamfwd.secret`, which must not be hand-rendered or edited. The app
ships enabled install/maintenance scripts using Python 3.13, including Stream
TA deployment and vendor-mapping/KV Store checks. None were executed here.
The existing wrapper's input/receiver rendering does not qualify that native
management-credential lifecycle. Keep the selected 8.1.6 components until the
8.1.7 bootstrap, startup behavior, native permissions, Cloud/HF split and
NetFlow field/dashboard results are qualified together. Package compatibility
alone does not turn the Cloud search tier into a capture host.

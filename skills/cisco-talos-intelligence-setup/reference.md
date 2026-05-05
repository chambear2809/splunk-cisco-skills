# Cisco Talos Intelligence Package Reference

Source: Cisco Talos Intelligence for Enterprise Security Cloud `1.0.1` package
inspection and Splunk Enterprise Security Cloud docs.

## App

| Splunkbase ID | App | Workloads |
|---|---|---|
| `7557` | `Splunk_TA_Talos_Intelligence` | `_search_heads`, `_indexers` |

## Package Surfaces

| Object | Value |
|---|---|
| Talos API base URL | `https://es-api.talos.cisco.com` |
| REST endpoint | `/servicesNS/nobody/Splunk_TA_Talos_Intelligence/query_reputation` |
| Capability | `get_talos_enrichment` |
| Default account stanza | `Talos_Intelligence_Service` |
| Legacy migrated account stanza | `Talos_URS_Service` |
| Service account field | encrypted `service_account` certificate + RSA private key |

## Support Guardrails

- Supported posture is Splunk Enterprise Security Cloud `7.3.2+`.
- FedRAMP/GovCloud deployments are not supported.
- The setup script runs a support preflight before installing app `7557`.

## Alert Actions

| Action | Purpose |
|---|---|
| `intelligence_collection_from_talos` | Queries Talos reputation and writes events as `talos:<observable_type>` to the configured index |
| `intelligence_enrichment_with_talos` | Enriches notable-event investigation context through ES incident review when available |

Observable types supported by the package code are URL, IP address, and domain.

## Threatlist

The packaged `threatlist://talos_intelligence_ip_blacklist` is disabled by
default. Its URL is `https://www.talosintelligence.com/documents/ip-blacklist`.
Enable only when the user explicitly wants the blacklist feed.

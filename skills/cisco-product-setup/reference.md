# Cisco Product Router Reference

This skill is a router over the existing Cisco setup skills in this repo.

## Automated Route Families

| Route Type | Backing skill(s) | Typical products |
|---|---|---|
| `security_cloud_product` | `cisco-security-cloud-setup` | Duo, XDR, ETD, Secure Endpoint |
| `security_cloud_variant` | `cisco-security-cloud-setup` | Secure Firewall, Identity Intelligence |
| `secure_access` | `cisco-secure-access-setup` | Secure Access, Umbrella, Cloudlock |
| `dc_networking` | `cisco-dc-networking-setup` | ACI, Nexus Dashboard, Nexus 9K |
| `catalyst_stack` | `cisco-catalyst-ta-setup` + `cisco-enterprise-networking-setup` | Catalyst Center, ISE, SD-WAN, Cyber Vision |
| `meraki` | `cisco-meraki-ta-setup` (+ optional `cisco-enterprise-networking-setup`) | Meraki |
| `intersight` | `cisco-intersight-setup` | Intersight |
| `thousandeyes` | `cisco-thousandeyes-setup` | ThousandEyes |
| `appdynamics` | `cisco-appdynamics-setup` | AppDynamics |
| `spaces` | `cisco-spaces-setup` | Cisco Spaces (meta stream / firehose) |
| `app_install_only` | `splunk-app-install` | Cisco Webex, UCS, ESA, WSA, Talos, EVM/SCA app validation |

## Partial Handoff Routes

| Route Type | Backing skill(s) | Typical products |
|---|---|---|
| `workflow_handoff` | `splunk-connect-for-syslog-setup`, `splunk-connect-for-snmp-setup` | CUCM, Expressway, Meeting Management, Meeting Server, IMC |

## Output States

| State | Meaning |
|---|---|
| `automated` | This repo can install and configure the product flow directly |
| `partial` | This repo can point to a concrete collector or install/validation workflow, but live product-specific configuration is outside this router |
| `manual_gap` | The SCAN catalog entry exists, but no local automation route is defined yet |
| `no_plans_available` | The SCAN catalog entry is not safely actionable from current local repo automation |
| `unsupported_legacy` | The product is retired or deprecated |
| `unsupported_roadmap` | The product is a roadmap / coverage-gap item |

## Notes

- Some SCAN products are visualization views over a shared collector. For those
  products, this skill routes to the shared collector path instead of inventing
  a product-specific collector that does not exist.
- Meraki is a local override: SCAN maps it to the Catalyst visualization stack,
  while this repo also has a dedicated Meraki TA setup flow.
- Optional companions not routed here:
  - `cisco-catalyst-enhanced-netflow-setup` adds the optional NetFlow / IPFIX
    stream mapping app for richer Catalyst NetFlow dashboards. It is a
    forwarder-side install with no per-product router stanza; reach it directly
    or through `cisco-enterprise-networking-setup` when NetFlow dashboards are
    requested.

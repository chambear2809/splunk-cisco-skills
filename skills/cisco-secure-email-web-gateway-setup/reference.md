# Cisco ESA/WSA Package Reference

Sources: Splunk Add-on for Cisco ESA `1.7.0`, Splunk Add-on for Cisco WSA
`5.0.0`, and SC4S Cisco ESA/WSA source documentation.

## Apps

| Splunkbase ID | App | Workloads |
|---|---|---|
| `1761` | `Splunk_TA_cisco-esa` | `_search_heads`, `_indexers`, `_forwarders` |
| `1747` | `Splunk_TA_cisco-wsa` | `_search_heads`, `_indexers`, `_forwarders` |

## ESA

Default macro: `Cisco_ESA_Index = ("default","email")`

Default index: `email`

Sourcetypes:

- `cisco:esa:textmail`
- `cisco:esa:http`
- `cisco:esa:cef`
- `cisco:esa:amp`
- `cisco:esa:authentication`
- `cisco:esa:antispam`
- `cisco:esa:content_scanner`
- `cisco:esa:system_logs`
- `cisco:esa:error_logs`
- `cisco:esa:bounce`
- `cisco:esa:delivery`
- `cisco:esa:legacy`

SC4S product key: `cisco_esa`

## WSA

Default macro: `Cisco_WSA_Index = ("default","netproxy")`

Default index: `netproxy`

Sourcetypes:

- `cisco:wsa:l4tm`
- `cisco:wsa:squid`
- `cisco:wsa:squid:new`
- `cisco:wsa:w3c`
- `cisco:wsa:w3c:recommended`
- `cisco:wsa:syslog`

SC4S product key: `cisco_wsa`

## Collection Notes

- Do not configure ESA/WSA API credentials for these TAs; the packages do not
  define API inputs.
- If SC4S is the only parsing tier, SC4S docs allow the add-on to be installed
  on search heads for users of the data source.
- If Splunk indexers or heavy forwarders parse raw logs directly, install the TA
  on that parsing tier as well as the search tier.

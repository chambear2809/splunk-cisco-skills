# Log Observer Connect Reference

Log Observer Connect lets Splunk Observability Cloud users query Splunk
Cloud Platform or Splunk Enterprise logs directly from the Log Observer
no-code UI. The logs stay in Splunk; LOC does not store or index them.

## Region and Version Compatibility

- AWS realms: us0, us1, eu0, eu1, eu2, jp0, au0, sg0
- GCP realm: us2
- Splunk Cloud Platform 9.0.2209+ (NOT available on Splunk Cloud Platform trials)
- Splunk Enterprise 9.0.1+
- GovCloud is excluded (use global data links instead)

## Splunk Cloud Platform Realm IPs (search-api allowlist)

The skill renders these as `--search-api-subnets` for the
`splunk-cloud-acs-allowlist-setup` handoff. Operators can hand the resulting
ACS allowlist scripts to their Splunk Cloud Platform admin team for change
management.

| Realm  | IPs                                                                 |
| ------ | ------------------------------------------------------------------- |
| us0    | `34.199.200.84/32, 52.20.177.252/32, 52.201.67.203/32, 54.89.1.85/32` |
| us1    | `44.230.152.35/32, 44.231.27.66/32, 44.225.234.52/32, 44.230.82.104/32` |
| eu0    | `108.128.26.145/32, 34.250.243.212/32, 54.171.237.247/32`           |
| eu1    | `3.73.240.7/32, 18.196.129.64/32, 3.126.181.171/32`                 |
| eu2    | `13.41.86.83/32, 52.56.124.93/32, 35.177.204.133/32`                |
| jp0    | `35.78.47.79/32, 35.77.252.198/32, 35.75.200.181/32`                |
| au0    | `13.54.193.47/32, 13.55.9.109/32, 54.153.190.59/32`                 |
| sg0    | `3.0.226.159/32, 18.136.255.76/32, 52.220.199.72/32`                |
| us2 (GCP) | `35.247.113.38/32, 35.247.32.72/32, 35.247.86.219/32`            |

## Splunk Cloud Platform Service Account Configuration

The Log Observer Connect service account is a Splunk user backed by a
dedicated role. The skill renders the role with the following parameters
(matching the Splunk product documentation):

| Setting                              | Value                                          |
| ------------------------------------ | ---------------------------------------------- |
| Base role                            | inherits `user`                                |
| Indexes (Included)                   | per `log_observer_connect.role.indexes` spec   |
| Internal indexes                     | DESELECTED — `*(All internal indexes)` is off  |
| Capability `edit_tokens_own`         | enabled                                        |
| Capability `search`                  | enabled                                        |
| Capability `indexes_list_all`        | DISABLED                                       |
| Standard search limit per role       | `4 * expected_concurrent_users` (e.g., 40 for 10 users) |
| Standard search limit per user       | same as role                                   |
| Real-time search limit (role + user) | 0                                              |
| Custom search time window            | 2592000 seconds (30 days)                      |
| Earliest searchable event time       | 7776000 seconds (90 days)                      |
| Disk space limit (Standard)          | 1000 MB                                        |

## Workload Rule

To prevent runaway Log Observer Connect searches the skill renders a
workload rule with the following predicate:

```
Predicate: user=<service-account-name> AND runtime>5m
Schedule: Always on
Action: Abort search
```

The runtime threshold defaults to 300 seconds; tune via
`log_observer_connect.workload_rule_runtime_seconds`.

## Splunk Cloud Platform Setup Flow

1. Operator renders the skill, reviews `06-log-observer-connect.md`, and
   runs the rendered apply script (or `setup.sh --apply log_observer_connect`).
2. The skill creates the role + user via Splunk REST and the workload rule
   via the workload-management REST.
3. The skill calls `splunk-cloud-acs-allowlist-setup` to add the realm IPs
   to the `search-api` allowlist (operator must approve `--apply` there).
4. The operator opens Splunk Observability Cloud > Settings > Log Observer
   connections > Add new connection > Splunk Cloud Platform; pastes the
   service-account credentials and the Splunk platform URL
   (`https://<stack>.splunkcloud.com:8089`).
5. The operator selects the Splunk Observability Cloud users that get
   access to this connection.

## Splunk Enterprise Setup Flow (TLS-cert path)

Splunk Enterprise customers must paste a TLS certificate into the Splunk
Observability Cloud Add new connection wizard so LOC can verify the
search-head TLS chain. The skill renders a helper that:

1. Connects to the configured Splunk search head and downloads the cert
   chain (typically via `openssl s_client -connect <host>:8089`).
2. Extracts the FIRST certificate in the chain (the leaf cert).
3. Writes the PEM to `<rendered>/06-log-observer-connect/leaf-cert.pem`
   for paste into the Add new connection wizard.

The skill does NOT install certs on the Splunk Enterprise host — that
remains the operator's responsibility (the Splunk product documentation
covers `web.conf` / `server.conf` cert installation).

## Concurrent Search Sizing

Each active Log Observer Connect user generates approximately 4 backend
searches against the service account. With 10 concurrent users, plan for
about 40 backend searches; with 20, about 80. Tune
`log_observer_connect.role.standard_search_limit_per_user` and
`expected_concurrent_users` accordingly.

## Why edit_tokens_own (and not indexes_list_all)?

Log Observer Connect manages the service-account session token internally
via `edit_tokens_own`. The role explicitly does NOT get `indexes_list_all`
because LOC must only see the indexes the operator scoped via the
Included list — leaking the full index inventory would defeat that
scoping.

## Troubleshooting

- "Connection failed" in the Add new connection wizard usually means the
  realm IPs are not yet in the `search-api` allowlist (or, for SE, the
  Splunk Enterprise host firewall is blocking the realm IPs on port 8089).
- "Authorization failed" usually means the service-account user lacks the
  role, or the role lacks `edit_tokens_own`.
- "No indexes available" usually means the role's Included indexes list is
  empty (Internal indexes deselected and no other indexes selected).

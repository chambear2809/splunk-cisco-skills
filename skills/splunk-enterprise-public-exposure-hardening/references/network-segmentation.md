# Network Segmentation Reference

Splunk Enterprise is "designed to run on a trusted network." Public
internet exposure requires that you separate the parts that the
internet is allowed to talk to from the parts that it must NOT.

## Required network zones

```
                          Internet
                              │
                          ┌───▼────┐
                          │  CDN   │ optional but recommended
                          └───┬────┘
                              │
                          ┌───▼────┐
                          │  WAF   │
                          └───┬────┘
                              │
   ┌──────────────────────────▼───────────────────────────┐
   │                          DMZ                          │
   │  - Reverse proxy (nginx / HAProxy) on 443             │
   │  - Heavy forwarder on 9997 mTLS (S2S receiver)        │
   └──────────────────────────┬───────────────────────────┘
                              │ inter-zone firewall
   ┌──────────────────────────▼───────────────────────────┐
   │                       Trusted Net                     │
   │  - Search head (8000 / 8089)                          │
   │  - Indexer cluster (8089 / 8191 / 9887 / 9997)        │
   │  - Cluster manager / SHC deployer / license manager   │
   └───────────────────────────────────────────────────────┘
```

## Port matrix

| Port | Service | Public reachable? | DMZ → Trusted? | Trusted → Trusted? |
|---|---|---|---|---|
| 80 | HTTP redirect at proxy | YES | n/a | n/a |
| 443 | HTTPS at proxy | YES | n/a | n/a |
| 8000 | Splunk Web | NO | YES (proxy → SH) | YES |
| 8088 | HEC | NO direct | YES (proxy → SH or IDX) | YES |
| 8089 | splunkd REST | **NO** | bastion only | YES |
| 8191 | KV store / mongo | **NO** | NO | SHC cluster only |
| 9887 | Indexer cluster replication | **NO** | NO | indexer cluster only |
| 8065 | App server (loopback) | **NO** | NO | localhost only |
| 9997 | S2S | NO direct | DMZ HF accepts; HF → IDX | indexers only |

## DMZ heavy forwarder pattern

For S2S ingest from internet-facing forwarders or other Splunk-to-
Splunk channels:

1. Place a heavy forwarder in the DMZ.
2. Configure `inputs.conf [splunktcp-ssl://9997]` with
   `requireClientCert = true` and `acceptFrom = <forwarder CIDR>`.
3. Configure `outputs.conf [tcpout-server://idx-N:9997]` with full
   TLS verify (`sslVerifyServerCert = true`,
   `sslCommonNameToCheck`, `sslAltNameToCheck`).
4. Internal indexers receive from the DMZ HF only — never from the
   public internet.
5. The DMZ HF runs the rendered hardening app and `apply-heavy-forwarder.sh`.

See [dmz-heavy-forwarder-pattern.md](dmz-heavy-forwarder-pattern.md) for
the full inputs.conf / outputs.conf pair.

## acceptFrom — Splunk's substitute for trustedProxiesList

There is no `trustedProxiesList` in Splunk. When `tools.proxy.on = true`
Splunk reads `X-Forwarded-For` from any IP that can reach the listening
port. The substitute is `acceptFrom`:

- `web.conf [settings] acceptFrom = 127.0.0.1, <proxy CIDR>, <bastion>, !*`
- `server.conf [httpServer] acceptFrom = 127.0.0.1, <proxy CIDR>, <peer/SH IPs>, !*`
- `inputs.conf [splunktcp-ssl://9997] acceptFrom = <forwarder CIDR>, !*`

`!*` denies everything not matched. Without `!*` the rule is allow-only
on top of an implicit allow-all.

## Indexer cluster ports

The cluster CIDR is internal-only. The renderer's firewall snippets
allow `8089`, `8191`, `9887`, `9997` only between the indexer cluster
CIDR and explicitly drop these ports from the public CIDR.

## SHC ports

Search Head Cluster needs:

- `8089` — KV / replication, between SHC members.
- `8191` — KV store mongo, between SHC members.
- `8081` — SHC raft replication, between SHC members.

All of these are internal. The proxy talks to the SHC via the load
balancer's `8000` (Splunk Web).

## License manager port

License master listens on `8089`. License peers connect to it. Both
must be on the trusted network; the public must NEVER reach them.

## Deployment server / agent management

`8089` is also the deployment-server port. Forwarders that update from
the deployment server should be in a managed network — the deployment
server is not designed to be public-internet-exposed.

## SC4S, SC4SNMP, MCP server

These external collectors / servers each have their own public-
exposure threat model. This skill is out of scope for them. See:

- `splunk-connect-for-syslog-setup`
- `splunk-connect-for-snmp-setup`
- `splunk-mcp-server-setup`

## Splunk Secure Gateway / Splunk Mobile

Operate over outbound-only connections from the search head; do not
require inbound public exposure. If you do choose to expose them
publicly (for, e.g., on-call mobile push), they need their own
threat model.

## Validation

`preflight.sh` and `validate.sh` use `--external-probe-cmd` (e.g.
`ssh probe@bastion nc -zv`) to confirm `8089`, `8191`, `8065`, `9887`
are NOT reachable from outside. Without this probe configured the
checks are skipped and the operator is responsible for manual
verification.

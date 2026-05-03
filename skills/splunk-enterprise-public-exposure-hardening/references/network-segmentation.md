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

Splunk Secure Gateway (SG) and Splunk Mobile are **outbound-only**
from the search head:

- SG connects outbound to `prod.spacebridge.spl.mobi:443` (default)
  or `http.<region>.spacebridge.splunkcx.com:443` (regional). Add
  these to the egress firewall allowlist.
- Mobile clients authenticate **end-to-end to the SG app** via ECC
  keypairs (Libsodium ECIES inside TLS 1.2). Spacebridge is an
  encrypted relay that **cannot decrypt** the channel; it is NOT an
  authentication endpoint.
- SG opens NO new inbound ports. The SH-side surfaces (Splunk Web
  `/en-US/app/splunk_secure_gateway/` and splunkd `/services/ssg/`)
  are already covered by this skill's `web.conf` admin-path
  lockdown and `[httpServer] acceptFrom`.
- SG has its own SVD floor (`3.9.10` / `3.8.58` / `3.7.28` —
  preflight step 24 enforces).
- Disabling SG also disables Splunk Mobile, Edge Hub, and Mission
  Control. Spacebridge is NOT FIPS 140-2 / GovCloud / FedRAMP-bound;
  Private Spacebridge (Helm-deployed on-prem relay) is the air-gap
  alternative.

See [secure-gateway-handoff.md](secure-gateway-handoff.md) for the
full handoff.

## Federated search inbound (when this SH is a provider)

If consumer SHs run federated searches against this SH:

- Consumers reach **inbound on `mgmtHostPort` (default 8089)**.
  There is NO separate federation port.
- The existing `[httpServer] acceptFrom` allowlist must include
  consumer SH IPs/CIDR.
- Federation auth is a **native Splunk service-account
  username+password** stored on the **consumer** in
  `federated.conf [provider://<name>]` — NOT `pass4SymmKey`. The
  existing `rotate-pass4symmkey.sh` does NOT cover federation. Use
  the new `rotate-federation-service-account.sh` helper instead.
- mTLS for federation is supported in Splunk Enterprise 10.0+ via
  `[sslConfig] requireClientCert = true` on the provider —
  recommended for public-exposure federation.
- Splunk auto-locks the federation service account after bad
  transparent-mode saves (default 30-minute timeout); pre-validate
  every consumer-side update with a "Test connection" REST call.

See [federated-search-provider-hardening.md](federated-search-provider-hardening.md)
for the full hardening posture and rotation procedure.

Cross-link: [splunk-federated-search-setup](../../splunk-federated-search-setup/SKILL.md)
owns the provider/consumer wiring for the underlying federation
infrastructure.

## Validation

`preflight.sh` and `validate.sh` use `--external-probe-cmd` (e.g.
`ssh probe@bastion nc -zv`) to confirm `8089`, `8191`, `8065`, `9887`
are NOT reachable from outside. Without this probe configured the
checks are skipped and the operator is responsible for manual
verification.

# TLS Protocol Policy

Why this skill keeps TLS 1.2 as the compatibility floor, auto-enables
TLS 1.3 for Splunk 10.4+, and how the dual `sslVersions` /
`sslVersionsForClient` knobs work.

> Anchor:
> [Configure TLS protocol version support for secure connections between Splunk platform instances](https://help.splunk.com/splunk-enterprise/administer/manage-users-and-security/10.4/secure-splunk-platform-communications-with-transport-layer-security-certificates/configure-tls-protocol-version-support-for-secure-connections-between-splunk-platform-instances).

## Splunk's documented supported protocols

The TLS protocol version doc explicitly lists:

| Version | Splunk status |
|---|---|
| SSLv3 | Deprecated; warns in 9.4+ |
| TLS 1.0 | Deprecated; warns in 9.4+ |
| TLS 1.1 | Deprecated; warns in 9.4+ |
| TLS 1.2 | Supported compatibility floor |
| TLS 1.3 | Supported for Splunk 10.4+ plans through `--enable-tls13` |

This skill:

- Defaults to `sslVersions = tls1.2,tls1.3` and
  `sslVersionsForClient = tls1.2,tls1.3` for Splunk 10.4+.
- Falls back to `tls1.2` below Splunk 10.4 when `--enable-tls13=auto`.
- Allows explicit opt-out with `--enable-tls13=false`.
- Allows `--tls-version-floor=tls1.3` only for Splunk 10.4+.
- Warns when the operator passes `--allow-deprecated-tls`, which only relaxes
  the lower bound for legacy clients.

## `sslVersions` syntax

The TLS protocol doc supports several syntax forms:

| Action | Syntax | Example |
|---|---|---|
| Single version | `sslVersions=<version>` | `sslVersions=tls1.2` |
| Restrict single | `sslVersions=-<version>` | `sslVersions=-tls1.0` |
| Multiple versions | `sslVersions=<v1>,<v2>` | `sslVersions=tls1.1,tls1.2` |
| Mix | `sslVersions=<v>,-<v>,...` | `sslVersions=*,-ssl3,-tls1.0,-tls1.1` |
| All TLS | `sslVersions=tls` | (resolves to all TLS versions Splunk supports) |
| All | `sslVersions=*` | (resolves to all SSL/TLS versions Splunk supports) |

The skill emits the most explicit form:

```
sslVersions = tls1.2,tls1.3
```

for Splunk 10.4+ when `--enable-tls13=auto|true`, or:

```
sslVersions = tls1.2
```

when TLS 1.3 is explicitly disabled or the target Splunk version is below 10.4.
Avoiding `sslVersions = *,-ssl3,-tls1.0,-tls1.1` because that
syntax silently picks up new versions Splunk adds later
(potentially breaking the operator's TLS posture without
warning).

## `sslVersions` vs `sslVersionsForClient`

These are TWO separate settings on `server.conf [sslConfig]`:

| Setting | Direction | Example use case |
|---|---|---|
| `sslVersions` | inbound (splunkd as **server**) | a forwarder connecting to splunkd 8089 |
| `sslVersionsForClient` | outbound (splunkd as **client**) | a deployment client connecting to a deployment server, an indexer connecting to a cluster manager |

Most operators only set `sslVersions`. The skill defaults BOTH
to `tls1.2,tls1.3` for Splunk 10.4+ so that:

- A splunkd-as-server inbound connection requires TLS 1.2 or TLS 1.3.
- A splunkd-as-client outbound connection requires TLS 1.2 or TLS 1.3 from
  the receiving end.

For TLS 1.3, Splunk's TLS 1.2 `cipherSuite` setting does not select the TLS 1.3
cipher suites; those are negotiated by the platform OpenSSL TLS 1.3 support.
The renderer still emits `cipherSuite` for TLS 1.2 peers.

## Per-conf `sslVersions` location

`sslVersions` is supported in multiple confs. The skill writes
it everywhere:

| Conf | Stanza | Notes |
|---|---|---|
| `web.conf` | `[settings]` | Browser-facing; needs to support whatever the operator's browsers accept |
| `inputs.conf` | `[SSL]` and `[http]` and per-input stanzas | S2S receivers and HEC |
| `outputs.conf` | `[tcpout]` and `[tcpout:<group>]` | Forwarder client |
| `server.conf` | `[sslConfig]` and `[kvstore]` | Inter-Splunk and KV Store |
| `applicationsManagement.conf` | `[applicationsManagement]` | Splunkbase REST calls |
| `alert_actions.conf` | per action | Alert action HTTPS calls |

The renderer touches all of them when `--target` includes the
relevant role.

## TLS 1.3 Gate

TLS 1.3 is version-gated because enterprise deployments often mix search
heads, indexers, deployment servers, heavy forwarders, and Universal
Forwarders during an upgrade window. Use `--enable-tls13 auto` for normal 10.4
plans, `true` only after confirming every peer supports 10.4-era TLS, and
`false` for mixed-version or legacy-client maintenance windows.

## Deprecation warnings

Splunk 9.4+ logs deprecation warnings when `sslVersions`
includes SSLv3 / TLS 1.0 / TLS 1.1. Search for them:

```spl
index=_internal sourcetype=splunkd
    ("deprecated" AND ("ssl" OR "tls"))
| stats count by host, message
```

The skill's `validate` phase greps for these warnings post-apply
and flags any host still on a deprecated protocol.

## What `--allow-deprecated-tls` does

`--allow-deprecated-tls` is retained for old templates, but the 10.4 renderer
does not accept SSLv3 / TLS 1.0 / TLS 1.1 as supported `sslVersions` floors.
The only 10.4 floors are `tls1.2` and `tls1.3`; the TLS 1.3 gate remains
controlled by `--enable-tls13`.

## FIPS interaction

In FIPS 140-3 mode, the TLS protocol matrix is enforced by the
underlying OpenSSL FIPS module:

- SSLv3 / TLS 1.0 / TLS 1.1 are **always rejected** regardless
  of `sslVersions`.
- TLS 1.2 is **always allowed**.
- TLS 1.3 is allowed in this renderer for Splunk 10.4+ when the operator uses
  `--enable-tls13 auto|true`.

So for FIPS deployments the practical floor is
TLS 1.2.

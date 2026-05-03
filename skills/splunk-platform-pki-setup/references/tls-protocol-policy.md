# TLS Protocol Policy

Why this skill defaults to TLS 1.2 and refuses TLS 1.3 by
default, and how the dual `sslVersions` / `sslVersionsForClient`
knobs work.

> Anchor:
> [Configure TLS protocol version support for secure connections between Splunk platform instances](https://help.splunk.com/splunk-enterprise/administer/manage-users-and-security/10.2/secure-splunk-platform-communications-with-transport-layer-security-certificates/configure-tls-protocol-version-support-for-secure-connections-between-splunk-platform-instances).

## Splunk's documented supported protocols

The TLS protocol version doc explicitly lists:

| Version | Splunk status |
|---|---|
| SSLv3 | Deprecated; warns in 9.4+ |
| TLS 1.0 | Deprecated; warns in 9.4+ |
| TLS 1.1 | Deprecated; warns in 9.4+ |
| TLS 1.2 | Supported (the maximum documented version) |
| TLS 1.3 | **Not in the documented supported set** |

**Splunk's docs do not yet list TLS 1.3 as a supported `sslVersions`
value.** Even though OpenSSL 3.0 (which Splunk 10 uses for FIPS
140-3) supports TLS 1.3 underneath, Splunk's `sslVersions` /
`sslVersionsForClient` settings haven't yet been documented to
accept `tls1.3`.

Until Splunk explicitly documents TLS 1.3 support, this skill:

- Defaults to `sslVersions = tls1.2` and
  `sslVersionsForClient = tls1.2`.
- Refuses `tls1.3` as a value.
- Warns when the operator passes `--allow-deprecated-tls`
  (which only relaxes the lower bound — the upper bound stays
  at TLS 1.2).

When Splunk eventually documents TLS 1.3 support, the
`--tls-version-floor` flag will accept `tls1.3` and the algorithm
presets will gain TLS 1.3 cipher suites.

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
sslVersions = tls1.2
```

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
to `tls1.2` so that:

- A splunkd-as-server inbound connection requires TLS 1.2.
- A splunkd-as-client outbound connection requires TLS 1.2 from
  the receiving end.

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

## Why no TLS 1.3

Reasons Splunk 10.0 / 10.2 hasn't documented TLS 1.3 yet:

1. Some downstream consumers (older Universal Forwarders, custom
   apps using the Splunk SDK) don't yet support TLS 1.3
   handshake.
2. KV Store's MongoDB requires careful TLS 1.3 testing (MongoDB
   supports TLS 1.3 via OpenSSL 3.0 but the interop matrix is
   complex).
3. The Splunk docs team hasn't yet updated `sslVersions` syntax
   examples to include `tls1.3`.

When Splunk publishes a doc update saying "TLS 1.3 supported",
this skill will:

- Add `tls1.3` to the allowed values for `--tls-version-floor`.
- Update `algorithm-policy.json` with TLS 1.3 cipher suites
  (`TLS_AES_256_GCM_SHA384`, `TLS_CHACHA20_POLY1305_SHA256`,
  `TLS_AES_128_GCM_SHA256`).
- Update the `splunk-modern` preset to optionally include
  `tls1.3`.

Until then, TLS 1.2-only is the safe default.

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

`--allow-deprecated-tls` relaxes the lower bound to allow
SSLv3 / TLS 1.0 / TLS 1.1 in `sslVersions`. It does NOT change
the upper bound (still TLS 1.2). Use ONLY when:

- An external TLS client is hard-stuck on a deprecated protocol.
- Replacing the client is in flight but not yet possible.
- The compensating control (network segmentation, cert pinning)
  is in place.

The renderer logs a loud warning and the rendered conf carries a
comment explaining the deprecation acknowledgement.

## FIPS interaction

In FIPS 140-3 mode, the TLS protocol matrix is enforced by the
underlying OpenSSL FIPS module:

- SSLv3 / TLS 1.0 / TLS 1.1 are **always rejected** regardless
  of `sslVersions`.
- TLS 1.2 is **always allowed**.
- TLS 1.3 may be allowed by OpenSSL 3.0 FIPS but Splunk's
  `sslVersions` parser doesn't expose `tls1.3` yet.

So for FIPS deployments the practical floor and ceiling are both
TLS 1.2.

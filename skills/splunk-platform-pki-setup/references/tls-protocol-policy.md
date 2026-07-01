# TLS Protocol Policy

This skill renders an explicit, version-aware TLS policy for both
`sslVersions` and `sslVersionsForClient`.

> Anchor:
> [Configure TLS protocol version support for secure connections between Splunk platform instances](https://help.splunk.com/splunk-enterprise/administer/manage-users-and-security/10.4/secure-splunk-platform-communications-with-transport-layer-security-certificates/configure-tls-protocol-version-support-for-secure-connections-between-splunk-platform-instances).

## Supported versions

| Target version | Default `--tls-version-floor tls1.2` | `--tls-version-floor tls1.3` |
|---|---|---|
| Splunk Enterprise 10.4+ | `tls1.2,tls1.3` | `tls1.3` |
| Older supported versions | `tls1.2` | Rejected |

Splunk Enterprise 10.4 documents TLS 1.2 and TLS 1.3 and no longer
negotiates TLS 1.0 or TLS 1.1 between Splunk platform components. The
renderer therefore adds a `server.conf [tls1.3]` stanza with the selected
preset's TLS 1.3 cipher suites and groups whenever TLS 1.3 is enabled.

The renderer never emits SSLv3, TLS 1.0, or TLS 1.1. The legacy
`--allow-deprecated-tls` flag is retained only to produce an explicit error;
it cannot weaken the generated policy.

## Explicit syntax

Splunk accepts single versions, comma-separated versions, exclusions, `tls`,
and `*`. This skill emits an explicit allowlist:

```ini
# Splunk 10.4+, default floor
sslVersions = tls1.2,tls1.3
sslVersionsForClient = tls1.2,tls1.3

[tls1.3]
cipherSuite = TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:TLS_AES_128_GCM_SHA256
groups = prime256v1, secp384r1, secp521r1
```

It does not use `*` or negative-only expressions because those can silently
admit a newly introduced protocol.

## Inbound and outbound controls

These are distinct settings in `server.conf [sslConfig]`:

| Setting | Direction | Example |
|---|---|---|
| `sslVersions` | splunkd as server | a deployment client connecting to a deployment server |
| `sslVersionsForClient` | splunkd as client | an indexer connecting to a cluster manager |

The skill writes the same version-aware allowlist to both, and also applies it
to Web, HEC, S2S receiver, and forwarding stanzas where supported.

## TLS 1.3-only mode

`--tls-version-floor tls1.3` is an intentional compatibility break. It is
accepted only with `--splunk-version 10.4.0` or newer and renders
`sslVersions = tls1.3`. Before applying it, confirm that every Universal
Forwarder, SDK client, load balancer, proxy, browser, and monitoring probe in
the path supports TLS 1.3.

The live validator probes every enabled protocol explicitly: TLS 1.2 and TLS
1.3 for the default 10.4 policy, or TLS 1.3 alone in TLS-1.3-only mode.

## Deprecated clients

For a client that cannot reach TLS 1.2, render a compensating-control handoff
instead of weakening Splunk's policy. Record network isolation, replacement
owner/date, and a protocol-translation endpoint if one is unavoidable. This
skill deliberately fails rather than presenting an insecure render as a
successful configuration.

## FIPS interaction

FIPS presets use AES-GCM TLS 1.3 cipher suites and omit ChaCha20. The
FIPS 140-3 preset also restricts TLS 1.3 groups to `prime256v1` and
`secp384r1`; the stricter STIG preset uses only `secp384r1`. The
`--fips-mode` switch remains separate from the cipher preset: a complete FIPS
deployment requires both the FIPS-grade policy and the corresponding
`SPLUNK_FIPS` / `SPLUNK_FIPS_VERSION` launch settings.

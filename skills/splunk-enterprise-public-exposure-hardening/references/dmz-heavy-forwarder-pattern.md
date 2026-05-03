# DMZ Heavy Forwarder Pattern

Splunk's documented Validated Architecture for ingesting from the
internet places a **heavy forwarder in the DMZ** that terminates the
S2S receiver. Internal indexers never accept S2S traffic from the
internet directly.

## Architecture

```
Internet UFs / agents
      │
      │ TLS S2S (mTLS recommended)
      ▼
┌──────────────────────────────────┐
│  DMZ Heavy Forwarder              │
│   inputs.conf [splunktcp-ssl:9997]│
│     requireClientCert = true      │
│     acceptFrom = <UF CIDRs>, !*   │
│   outputs.conf [tcpout-server://] │
│     sslVerifyServerCert = true    │
└──────────────┬───────────────────┘
               │ TLS S2S to internal indexers
               ▼
┌──────────────────────────────────┐
│  Indexer cluster (internal)       │
│   inputs.conf [splunktcp-ssl:9997]│
│     acceptFrom = <DMZ HF only>    │
└──────────────────────────────────┘
```

## Why a DMZ HF instead of direct indexer access

- Indexers are on the trusted network. Direct internet access to an
  indexer is unacceptable.
- The DMZ HF can do early-stage filtering (drop bad sourcetypes,
  redact PII, reject oversized events) before data hits the indexer.
- The DMZ HF can fan out to multiple indexer clusters or to S3 archive
  destinations.
- Indexer-cluster replication (port 9887) is internal-only — the DMZ
  HF abstraction shields it.

## Configuration the renderer emits

When `--topology shc-with-hec-and-hf --enable-s2s true --s2s-mtls true
--forwarder-mtls true`, the renderer produces:

### DMZ HF `inputs.conf`

```
[splunktcp-ssl://9997]
requireClientCert        = true
serverCert               = /opt/splunk/etc/auth/splunkweb/cert.pem
caCertFile               = /opt/splunk/etc/auth/cabundle.pem
sslVersions              = tls1.2
cipherSuite              = ECDHE-ECDSA-AES256-GCM-SHA384:...
ecdhCurves               = prime256v1, secp384r1, secp521r1
acceptFrom               = 127.0.0.1, <indexer cluster CIDR>
```

`acceptFrom` matches the operator-supplied CIDR for forwarders. Plus
the indexer CIDR for cluster-internal replication. The public proxy
CIDR is NOT in `acceptFrom` for this stanza.

### DMZ HF `outputs.conf`

```
[tcpout]
defaultGroup            = primary_indexers
useClientSSLCompression = false

[tcpout:primary_indexers]
server = <idx-1>:9997, <idx-2>:9997, <idx-3>:9997

[tcpout-server://<idx-1>:9997]
clientCert              = /opt/splunk/etc/auth/splunkweb/cert.pem
sslRootCAPath           = /opt/splunk/etc/auth/cabundle.pem
sslVerifyServerCert     = true
sslCommonNameToCheck    = idx-1.internal.example.com
sslAltNameToCheck       = idx-1.internal.example.com
sslVersions             = tls1.2
cipherSuite             = ECDHE-ECDSA-AES256-GCM-SHA384:...
ecdhCurves              = prime256v1, secp384r1, secp521r1
```

(Repeat the `[tcpout-server://...]` block per indexer.)

## Public-facing UF configuration (out of scope for this skill)

The public-facing UFs that send to the DMZ HF need:

- A client certificate signed by the same CA that the HF's
  `caCertFile` trusts.
- `outputs.conf [tcpout-server://hf.example.com:9997]` with full TLS
  verify.
- HEC may be a better fit for many ingest cases — TLS-terminated, easier
  to lifecycle-manage than UF certificates.

## Firewall

The renderer's `proxy/firewall/` snippets:

- Drop 9997 from the public CIDR.
- Allow 9997 from the operator-defined forwarder CIDR to the DMZ HF.
- Allow 9997 from the DMZ HF to the indexer cluster CIDR.

## Inputs.conf hardening on the DMZ HF

In addition to TLS / mTLS, the DMZ HF should:

- Drop sourcetypes the operator does not expect (`PROPS:NULL` queue).
- Apply `props.conf` LINE_BREAKER, TRUNCATE, MAX_DAYS_AGO to bound
  parsing.
- Apply `transforms.conf` to redact known PII (email, SSN, credit card)
  on the way in if the indexers should not see them.
- Drop indices the public is not allowed to write — `s2s_indexes_validation
  = enabled_for_all` on the destination HEC stanza if HEC is also on
  this HF.

## Why not just receive S2S on indexers behind the proxy?

Putting indexers behind a reverse proxy works for HEC (HTTP) but NOT
for S2S — S2S is a binary protocol and most reverse proxies cannot
inspect it. A heavy forwarder is a Splunk-native S2S terminator that
can re-emit to indexers over a separate channel.

## What this pattern is NOT

- Not a substitute for a SIEM / SOC; the DMZ HF is a relay, not a
  detection layer.
- Not a load balancer; if you need multiple HFs for capacity, place
  an L4 load balancer in front.
- Not the same as Splunk Edge Processor; EP is a different product
  (see `splunk-edge-processor-setup`).

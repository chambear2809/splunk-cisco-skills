# mTLS and Hostname Validation

Anchored to:

- [Configure mutually authenticated TLS (mTLS) on the Splunk platform](https://help.splunk.com/en/splunk-enterprise/administer/manage-users-and-security/10.2/secure-splunk-platform-communications-with-transport-layer-security-certificates/configure-mutually-authenticated-transport-layer-security-mtls-on-the-splunk-platform)
- [Configure TLS certificate host name validation](https://docs.splunk.com/Documentation/Splunk/latest/Security/EnableTLSCertHostnameValidation)

## mTLS surfaces

Splunk supports mTLS on three surfaces:

| Surface | Receiver knob | Sender knob |
|---|---|---|
| splunkd 8089 | `server.conf [sslConfig] requireClientCert = true` + `sslCommonNameToCheck` / `sslAltNameToCheck` | each splunkd-as-client (e.g. peer → CM, member → captain) presents `serverCert` |
| S2S 9997 | `inputs.conf [SSL] requireClientCert = true` + name checks | `outputs.conf [tcpout:<group>] clientCert = ...` |
| HEC 8088 | `inputs.conf [http] requireClientCert = true` + name checks | HEC client (forwarder, EP, custom app) presents client cert in TLS handshake |

The `--enable-mtls` flag selects the union of surfaces:

| `--enable-mtls` value | splunkd | S2S | HEC |
|---|:---:|:---:|:---:|
| `none` | – | – | – |
| `s2s` | – | ✓ | – |
| `hec` | – | – | ✓ |
| `splunkd` | ✓ | – | – |
| `s2s,hec` (default) | – | ✓ | ✓ |
| `all` | ✓ | ✓ | ✓ |

## Why splunkd mTLS defaults to off

Turning on `requireClientCert` on splunkd 8089 means **every
client** that hits the splunkd REST API must present a valid
client cert with a CN / SAN matching `sslCommonNameToCheck` /
`sslAltNameToCheck`. This breaks:

- Operator `curl` against `/services/...` from a workstation.
- Splunk Add-on UI test buttons that call splunkd from the
  search-head.
- Most monitoring tools that hit `/services/server/info`.

Operators who want splunkd mTLS should:

1. First validate they have a complete inventory of every client
   that calls splunkd on the cluster (the `inventory` phase
   helps).
2. Mint client certs for every operator workstation, monitoring
   tool, and add-on identity.
3. Distribute the new client certs into each tool's TLS config.
4. Then run this skill with `--enable-mtls all`.

## Hostname validation

Splunk supports two complementary checks:

- **`sslVerifyServerCert = true`** — the connecting party
  validates that the receiver's cert is trusted (signed by a CA in
  `sslRootCAPath`). This is the "do you trust this cert?" check.
- **`sslVerifyServerName = true`** — the connecting party
  additionally validates that the cert's CN or SAN matches the
  hostname it connected to. This is the "is this cert for the
  host I think I'm talking to?" check.

The renderer defaults BOTH to `true` everywhere supported. This
prevents a stolen-but-valid cert from one Splunk host being used
to impersonate another.

## CN vs SAN matching

`sslCommonNameToCheck` checks the cert's Subject CN.
`sslAltNameToCheck` checks the cert's `subjectAltName` extension.

Modern PKI **prefers SAN** because:

- Browsers and most TLS libraries have deprecated CN matching
  since 2017 (RFC 6125 §6.4.4).
- SAN supports multiple identities per cert (DNS, IP, URI).
- Cert renewal can change the CN without breaking existing
  clients that pin to a SAN.

The renderer always emits `subjectAltName = @alt_names` in every
leaf cert template. CN is set to the primary FQDN as a fallback
for older clients but operators should rely on SAN.

## Per-indexer SAN matching for forwarders

When each indexer presents a different leaf cert (the common
case), the forwarder must match each indexer's cert against that
indexer's SAN, not against a global CN list. Use
`[tcpout-server://host:port]` per-server stanzas:

```
[tcpout:idxc_main]
server               = idx01:9997, idx02:9997, idx03:9997
clientCert           = /opt/splunkforwarder/etc/auth/uf01-s2s.pem
sslVerifyServerCert  = true
sslVerifyServerName  = true

[tcpout-server://idx01.example.com:9997]
sslCommonNameToCheck = idx01.example.com
sslAltNameToCheck    = idx01.example.com

[tcpout-server://idx02.example.com:9997]
sslCommonNameToCheck = idx02.example.com
sslAltNameToCheck    = idx02.example.com

[tcpout-server://idx03.example.com:9997]
sslCommonNameToCheck = idx03.example.com
sslAltNameToCheck    = idx03.example.com
```

The renderer emits these per-server stanzas automatically when the
operator passes `--peer-hosts` with multiple values.

## Wildcard certs

Permitted but discouraged. A single `*.example.com` cert
simplifies rollout but:

- Concentrates blast radius if compromised.
- Doesn't satisfy `sslCommonNameToCheck` per-host matching unless
  the operator widens the allowlist.
- Doesn't help KV Store at all (KV Store cares about EKU, not
  SAN).

The renderer warns when `--peer-hosts` is paired with a wildcard
SAN.

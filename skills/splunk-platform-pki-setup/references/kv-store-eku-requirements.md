# KV Store EKU Requirements

Anchored to
[Preparing custom certificates for use with KV store](https://docs.splunk.com/Documentation/Splunk/9.4.2/Admin/CustomCertsKVstore).

## What KV Store 7.0+ requires

Starting with **Splunk Enterprise 9.4 / KV Store server 7.0**, the
embedded MongoDB performs a CA verification check at startup. A
host whose certs fail the check **will not start KV Store**, which
breaks search-head functionality (apps, lookups, ITSI services,
etc.).

The verification has two parts:

1. **EKU pair** — every cert that KV Store presents must carry
   both `serverAuth` (`1.3.6.1.5.5.7.3.1`) and `clientAuth`
   (`1.3.6.1.5.5.7.3.2`) X.509v3 Extended Key Usage values.
2. **Chain validation under `-x509_strict`** — the `serverCert`
   must validate cleanly against `sslRootCAPath` (or `caCertFile`,
   deprecated) using OpenSSL's strict mode.

## How the renderer enforces it

### At signing time

The leaf cert profile (`openssl-leaf-server.cnf`) bakes both EKU
values in:

```
extendedKeyUsage = serverAuth, clientAuth
```

This applies to every server leaf the renderer mints, even those
not destined for KV Store hosts, because:

- Many Splunk roles co-host KV Store implicitly (search heads,
  SHC members, single SH).
- Adding `clientAuth` to a server cert costs nothing and
  future-proofs against role changes.

### At install time

`pki/install/kv-store-eku-check.sh` runs the documented
verification before declaring a host ready:

```bash
$SPLUNK_HOME/bin/splunk cmd openssl verify \
    -verbose -x509_strict \
    -CAfile <sslRootCAPath_or_caCertFile> \
    <serverCert>
```

Expected output:

```
<serverCert>: OK
```

Anything else means a CA cert is missing from `sslRootCAPath` or
the chain is malformed. The script appends any missing
intermediate certs from `pki/private-ca/intermediate.pem` to the
trust bundle and re-runs the check until `OK`.

### At preflight

`preflight.sh` walks every Splunk host in the topology and runs:

```bash
$SPLUNK_HOME/bin/splunk cmd btool server list kvstore
$SPLUNK_HOME/bin/splunk cmd btool server list sslConfig
```

then runs the same `openssl verify -x509_strict` against the
discovered `serverCert` and `sslRootCAPath`. Refuses to mark the
host ready unless every check returns `OK`.

## Common failure modes

### "missing CA from `sslRootCAPath`"

The CA file does not contain every cert in the chain (e.g. only
the Root, but the leaf is signed by an Intermediate). Concatenate:

```bash
cat intermediate.pem root.pem > cabundle.pem
```

The renderer's `prepare-key.sh` does this automatically.

### "self-signed certificate in chain"

A self-signed Intermediate is in the chain. Per the
[inter-Splunk TLS doc](https://help.splunk.com/en/splunk-enterprise/administer/manage-users-and-security/10.0/secure-splunk-platform-communications-with-transport-layer-security-certificates/configure-tls-certificates-for-inter-splunk-communication),
"Any certificate or certificate chain that an intermediate CA
self-signs" is **not** a valid configuration. The Intermediate
must be signed by the Root.

### "key usage does not include certificate signing"

The Intermediate cert lacks `keyUsage = critical, keyCertSign,
cRLSign`. Re-mint with `openssl-intermediate.cnf` from the
renderer.

### "EKU does not include `clientAuth`"

The leaf has only `serverAuth`. KV Store requires both. Re-mint
with `openssl-leaf-server.cnf`.

### "FIPS mode enabled but cert uses SHA-1"

In FIPS mode (`SPLUNK_FIPS_VERSION=140-3`), MongoDB rejects SHA-1
signatures. Re-mint with `--tls-policy fips-140-3` so the renderer
forces SHA-256+ and rejects RSA-1024 / DSA / weak curves.

## Splunk Cloud

Not applicable — Splunk owns Splunk Cloud KV Store. The skill
refuses Splunk Cloud cert issuance and points at UFCP for the
forwarder fleet.

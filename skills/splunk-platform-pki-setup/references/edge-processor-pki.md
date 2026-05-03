# Edge Processor PKI

Splunk Edge Processor (EP) uses a separate cert lifecycle from
the rest of the Splunk platform. The data-source-to-EP and
EP-to-destination channels both support TLS / mTLS but the file
naming convention, key format, and distribution method differ.

> Anchor:
> [Edge Processor: Obtain TLS certificates for data sources and Edge Processors](https://help.splunk.com/data-management/transform-and-route-data/use-edge-processors-for-splunk-cloud-platform/10.0.2503/get-data-into-edge-processors/obtain-tls-certificates-for-data-sources-and-edge-processors).

## Trigger

Add `--include-edge-processor=true` to the render command. The
renderer adds an `pki/distribute/edge-processor/` directory with
the EP-specific cert pair templates and a REST upload helper.

## Scope (data plane only)

This skill covers the **data plane** TLS for EP:

- Forwarder / data source → EP (mTLS optional).
- EP → destination (Splunk indexer, S3, syslog, HEC).

It does NOT cover:

- The EP control plane (managed by Splunk Cloud or the EP
  control-plane object on Splunk Enterprise) — owned by
  `splunk-edge-processor-setup`.
- EP HEC TLS (separate doc:
  [Edge Processor: TLS and mTLS support (HEC)](https://help.splunk.com/en/data-management/collect-http-event-data/send-hec-data-to-and-from-edge-processor/send-data-from-edge-processor-with-hec/tls-and-mtls-support)).

## Five-file naming convention

Per the EP doc:

| File | Role |
|---|---|
| `ca_cert.pem` | CA cert. Uploaded to BOTH EP and the data source. |
| `edge_server_cert.pem` | EP's server cert. Presented by EP to data sources. |
| `edge_server_key.pem` | EP's server private key. PKCS#8, **unencrypted**. |
| `data_source_client_cert.pem` | Data source's client cert. Presented to EP. |
| `data_source_client_key.pem` | Data source's client private key. PKCS#8, **unencrypted**. |

The "unencrypted" requirement is from the EP doc: "private key
that must be decrypted." This is a notable difference from
splunkd (which accepts encrypted PEMs and decrypts via
`sslPassword`).

## Algorithm support

EP supports both **RSA** and **ECDSA** signing per its doc.

| `--key-algorithm` | EP cert profile |
|---|---|
| `rsa-2048` (default) | RSA-2048 with SHA-256 signing |
| `rsa-4096` | RSA-4096 with SHA-256 signing |
| `ecdsa-p256` | ECDSA P-256 with SHA-384 signing (per EP doc's ECDSA workflow) |
| `ecdsa-p384` | ECDSA P-384 with SHA-384 signing |

For ECDSA, the renderer's `sign-server-cert.sh --target edge-processor`
runs:

```bash
$SPLUNK_HOME/bin/splunk cmd openssl ecparam \
    -genkey -name prime256v1 -out edge_server_key_sec1.pem
$SPLUNK_HOME/bin/splunk cmd openssl pkcs8 \
    -topk8 -inform PEM -in edge_server_key_sec1.pem \
    -out edge_server_key.pem -nocrypt
$SPLUNK_HOME/bin/splunk cmd openssl req \
    -new -SHA384 -key edge_server_key.pem -nodes \
    -subj "/C=US/O=Example Corp/CN=ep01.example.com" \
    -out edge_server_req.pem
$SPLUNK_HOME/bin/splunk cmd openssl x509 -req -days 825 \
    -SHA384 -set_serial 01 \
    -extfile <(printf "subjectAltName=DNS:ep01.example.com") \
    -in edge_server_req.pem -out edge_server_cert.pem \
    -CA ca_cert.pem -CAkey ca_key.pem
```

For RSA, the workflow uses `genrsa` instead of `ecparam`. Both
end with the same five PEM files.

## Distribution

EP doesn't read certs from the filesystem like splunkd does — it
reads them from its control plane (Splunk Cloud EP UI or the
self-managed EP control-plane object). The renderer emits an
upload helper:

```bash
splunk-platform-pki-rendered/pki/distribute/edge-processor/upload-via-rest.sh.example
```

The helper documents both paths:

### Splunk Cloud EP (upload via UI)

1. Splunk Cloud → **Data Management** → **Edge Processors** →
   pick the EP → **Settings** → **Certificates**.
2. Upload `ca_cert.pem`.
3. Upload `edge_server_cert.pem` + `edge_server_key.pem`.
4. (Optional) Upload `data_source_client_cert.pem` +
   `data_source_client_key.pem` for mTLS data sources.
5. Save and apply.

### Splunk Enterprise EP control plane (upload via REST)

```bash
curl --silent --show-error \
     -k -u admin:"$(cat /tmp/splunk_admin_password)" \
     -X POST \
     "https://ep-control-plane.example.com:8089/services/edge_processor/<ep-id>/certificates" \
     -F ca_cert=@ca_cert.pem \
     -F server_cert=@edge_server_cert.pem \
     -F server_key=@edge_server_key.pem
```

(The exact endpoint shape depends on the EP control-plane
version; the renderer references the upstream EP doc.)

The skill itself **does NOT** automate the upload because:

- EP's REST API is part of the control plane, not the splunkd
  REST.
- Uploading to the EP UI is operator-driven by design (the EP
  team usually wants explicit human approval).

`splunk-edge-processor-setup` handles the upload as a follow-on
step.

## Forwarder-to-EP mTLS

When a data source is a Splunk forwarder sending to EP, the
forwarder's `outputs.conf` carries `clientCert`. Same forwarder
overlay shape as for direct-to-indexer S2S, just pointed at the
EP host.

The renderer emits the forwarder side under
`pki/distribute/forwarder-fleet/<group>/outputs-overlay.conf`
when the operator passes `--ep-fqdn` and the data source is a
Splunk forwarder.

## EP-to-destination

The EP-side outbound cert (EP → Splunk indexer, S3, syslog) is
configured per destination in the EP UI. EP supports:

- **Splunk indexer (S2S)** — TLS or mTLS, EP presents the data
  source client cert.
- **Splunk HEC** — TLS, EP authenticates with HEC token.
- **S3** — TLS, EP authenticates with AWS credentials.
- **Syslog** — TLS optional.

For Splunk-indexer destinations, the EP plays the forwarder
role; the destination indexer's cert is the same as for any S2S
receiver (this skill's `--target indexer-cluster` covers it).

## Validation

```bash
# 1. Verify the cert chain
openssl verify -CAfile ca_cert.pem edge_server_cert.pem
openssl verify -CAfile ca_cert.pem data_source_client_cert.pem

# 2. Confirm key format is PKCS#8 unencrypted
head -1 edge_server_key.pem
# Expected: -----BEGIN PRIVATE KEY-----

# 3. Confirm SAN includes the EP FQDN
openssl x509 -in edge_server_cert.pem -text -noout \
  | grep -A1 'Subject Alternative Name'
```

## Out of scope for the PKI skill

- Uploading to the EP control plane (delegated to
  `splunk-edge-processor-setup`).
- Configuring EP pipelines or destinations.
- Splunk Cloud EP control plane RBAC.
- EP cluster scale-out (multi-instance EP) — the same cert pair
  works across all EP instances in the cluster.

## Rotation

EP cert rotation is independent of the indexer cluster rotation.
Steps:

1. Render new EP cert pair (rerun this skill with same flags).
2. Upload to EP via UI / REST.
3. Restart the EP instance(s) (delegated to
   `splunk-edge-processor-setup`).
4. Update each data source's client cert (delegated).

No splunkd rolling restart is required.

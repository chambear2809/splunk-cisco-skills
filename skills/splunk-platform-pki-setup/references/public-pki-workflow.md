# Public PKI Workflow

Triggered by `--mode public`. The skill never holds CA private
key material in any mode, but in public mode it doesn't even
mint leaves — it generates per-host CSRs with the right
extensions and points the operator at their CA's enrollment
process.

## What "public" means here

"Public" PKI in this skill is shorthand for "**someone else** is
the certificate authority". That can be:

- A commercial public CA (DigiCert, Sectigo, GoDaddy, etc.)
- A free public CA (Let's Encrypt via ACME)
- An internal but managed CA (HashiCorp Vault PKI, Microsoft AD
  CS, EJBCA)
- A managed cloud CA (AWS Private CA, GCP Certificate Authority
  Service)

The renderer doesn't care which. It emits the CSR + a CA-specific
handoff Markdown so the operator follows their CA's documented
enrollment.

## What the renderer emits

```
splunk-platform-pki-rendered/pki/
├── csr-templates/
│   ├── splunkd-<host>.cnf
│   ├── web-<host>.cnf
│   ├── s2s-<host>.cnf
│   ├── hec-<host>.cnf
│   ├── replication-<host>.cnf
│   ├── shc-member-<host>.cnf
│   ├── deployment-server.cnf
│   ├── license-manager.cnf
│   ├── monitoring-console.cnf
│   ├── saml-sp.cnf
│   ├── edge-processor-server.cnf
│   ├── edge-processor-client.cnf
│   └── generate-csr.sh
└── handoff/
    ├── vault-pki.md           # always present
    ├── acme-cert-manager.md   # always present
    ├── microsoft-adcs.md      # always present
    ├── ejbca.md               # always present
    └── operator-checklist.md  # references the CA chosen via --public-ca-name
```

Every CSR template carries:

- `subjectAltName` populated from the operator's per-host SAN
  list (`--peer-hosts`, `--shc-members`, etc.)
- `keyUsage = critical, digitalSignature, keyEncipherment`
- `extendedKeyUsage = serverAuth, clientAuth` (dual EKU for
  KV Store)
- Modern signature alg per `--tls-policy`

## The CSR

Sample `csr-templates/splunkd-idx01.example.com.cnf`:

```
[req]
default_bits        = 2048
default_md          = sha256
prompt              = no
distinguished_name  = req_distinguished_name
req_extensions      = v3_req

[req_distinguished_name]
C  = US
ST = California
L  = San Francisco
O  = Example Corp
OU = Splunk Platform
CN = idx01.example.com

[v3_req]
basicConstraints   = critical, CA:FALSE
keyUsage           = critical, digitalSignature, keyEncipherment
extendedKeyUsage   = serverAuth, clientAuth
subjectAltName     = @alt_names

[alt_names]
DNS.1 = idx01.example.com
DNS.2 = idx01
IP.1  = 10.0.20.11
```

`generate-csr.sh` runs:

```bash
$SPLUNK_HOME/bin/splunk cmd openssl genpkey \
    -algorithm RSA -pkeyopt rsa_keygen_bits:2048 \
    -aes-256-cbc \
    -pass file:"$LEAF_KEY_PASSWORD_FILE" \
    -out signed/splunkd-idx01.example.com.key
$SPLUNK_HOME/bin/splunk cmd openssl req \
    -new -key signed/splunkd-idx01.example.com.key \
    -passin file:"$LEAF_KEY_PASSWORD_FILE" \
    -config csr-templates/splunkd-idx01.example.com.cnf \
    -out signed/splunkd-idx01.example.com.csr
```

## What the operator sends to the CA

For each `*.csr` file:

1. Submit the CSR to the CA's enrollment endpoint (web form,
   REST API, ACME challenge, AD CS Web Enrollment, EJBCA REST,
   etc.).
2. Receive back a signed PEM (the leaf cert).
3. Receive back the CA's intermediate(s) and root.

The operator does NOT submit private keys. Private keys never
leave the host on which they were generated.

## What the operator does with the response

`prepare-key.sh` converts and concatenates as needed:

```bash
# 1. Concatenate the chain (intermediate + root) into the trust bundle.
cat returned-intermediate.pem returned-root.pem > pki/install/cabundle.pem

# 2. (Optional) concatenate the leaf with intermediates for HEC/Web (some
#    deployments expect a single chain file rather than separate cert + chain).
cat returned-leaf.pem returned-intermediate.pem > signed/splunkd-idx01-chain.pem

# 3. Verify the chain (must return OK).
bash pki/install/verify-leaf.sh \
    --cert signed/splunkd-idx01-chain.pem \
    --ca   pki/install/cabundle.pem

# 4. Run KV Store EKU check (must return OK).
bash pki/install/kv-store-eku-check.sh \
    --cert signed/splunkd-idx01-chain.pem \
    --ca   pki/install/cabundle.pem

# 5. Install on the host.
bash pki/install/install-leaf.sh ...
```

## Validity-day caps

Public CAs cap leaf validity:

| CA | Cap |
|---|---|
| Let's Encrypt | 90 days |
| DigiCert / Sectigo / GoDaddy public roots | 397 days (CA/Browser Forum baseline) |
| Vault PKI / AD CS / EJBCA | operator-configured |
| AWS Private CA | operator-configured |

The renderer warns if `--leaf-days` exceeds 397 days in public
mode. If the operator's CA enforces a shorter cap (e.g. Let's
Encrypt 90 days), they'll receive a CA error at signing time.

## Renewal cadence

Short-lived public-CA certs (90 day for Let's Encrypt) require
**automated** rotation. Plan for:

- Trigger rotation 30 days before expiry (`expire-watch.sh`).
- Re-render the CSRs (FQDNs typically don't change, but SANs
  might).
- Re-submit to the CA.
- Re-run install-leaf + verify + KV Store EKU check.
- Run `pki/rotate/plan-rotation.md` to roll the cluster.

For ACME / Vault PKI, the renewal can be cron'd. For commercial
CAs, the renewal is operator-driven.

## Operator handoff Markdown

The renderer always emits all four CA handoffs (Vault PKI, ACME,
AD CS, EJBCA). `--public-ca-name <ca>` only affects which one is
referenced first in `operator-checklist.md` — the other three
are still present for operators who switch CAs later.

See:

- [handoff-vault-pki.md](handoff-vault-pki.md)
- [handoff-acme-cert-manager.md](handoff-acme-cert-manager.md)
- [handoff-microsoft-adcs.md](handoff-microsoft-adcs.md)
- [handoff-ejbca.md](handoff-ejbca.md)

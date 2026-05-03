# Handoff — HashiCorp Vault PKI

Triggered by `--mode public --public-ca-name vault`. The operator
runs Vault PKI; this skill emits the CSRs, this doc walks
through Vault enrollment.

> Vault PKI overview:
> https://developer.hashicorp.com/vault/docs/secrets/pki

## Vault role for Splunk leaves

Configure a Vault PKI role that allows the SANs Splunk needs and
sets the right TTL:

```bash
vault write pki/roles/splunk-leaf \
    allowed_domains="example.com" \
    allow_subdomains=true \
    allow_ip_sans=true \
    enforce_hostnames=true \
    max_ttl=825d \
    key_type=rsa \
    key_bits=2048 \
    server_flag=true \
    client_flag=true \
    use_csr_common_name=true \
    use_csr_sans=true
```

The `server_flag=true` + `client_flag=true` combination makes
Vault include both `serverAuth` and `clientAuth` EKUs, which is
required for KV Store 7.0+.

## Sign each CSR

```bash
for csr in splunk-platform-pki-rendered/pki/signed/*.csr; do
  host="$(basename "$csr" .csr)"
  vault write -format=json pki/sign/splunk-leaf \
      csr=@"$csr" \
      common_name="$host" \
      ttl=825d \
    | jq -r .data.certificate \
    > splunk-platform-pki-rendered/pki/signed/"$host".pem
done

# Pull the issuing CA chain.
vault read -format=json pki/cert/ca_chain \
  | jq -r .data.certificate \
  > splunk-platform-pki-rendered/pki/install/cabundle.pem
```

## Vault PKI External CA (ACME / Let's Encrypt via Vault)

Vault Enterprise 1.20+ supports the
[PKI External CA secrets engine](https://developer.hashicorp.com/vault/docs/secrets/pki-external-ca)
which can act as an ACME client to Let's Encrypt. This is useful
when:

- Splunk Web is internet-facing and needs a publicly trusted cert.
- The operator wants Let's Encrypt's free 90-day cert without
  running cert-manager.

Pair this skill's `--public-ca-name vault` with Vault's ACME
backend so Vault fetches the Let's Encrypt cert and Splunk
consumes it via the same install / verify pipeline.

## Vault PKI SCEP backend

Vault Enterprise 1.20+ also supports
[SCEP](https://developer.hashicorp.com/vault/docs/secrets/pki/scep).
Useful for the operator's broader PKI strategy but the Splunk
skill itself does not consume SCEP directly — the operator
fetches the signed leaf via SCEP, stages it on the Splunk host,
and the install flow takes over.

## Verify before installing

```bash
bash splunk-platform-pki-rendered/pki/install/verify-leaf.sh \
    --cert splunk-platform-pki-rendered/pki/signed/splunkd-idx01.example.com.pem \
    --ca   splunk-platform-pki-rendered/pki/install/cabundle.pem
bash splunk-platform-pki-rendered/pki/install/kv-store-eku-check.sh \
    --cert splunk-platform-pki-rendered/pki/signed/splunkd-idx01.example.com.pem \
    --ca   splunk-platform-pki-rendered/pki/install/cabundle.pem
```

Both should return `OK`.

## Renewal automation

Vault PKI supports **batch tokens** for high-frequency cert
issuance without filling the audit log. Set up the operator's
renewal job (cron / systemd timer / ITSI) to re-issue every
~600 days for `825d` certs (or every 30 days for ACME-backed
90-day certs).

## Splunk-side rotation order

Same as the rest of this skill — see
[rotation-runbook.md](rotation-runbook.md). Vault doesn't change
the rolling-restart cadence; it only changes how the leaves are
obtained.

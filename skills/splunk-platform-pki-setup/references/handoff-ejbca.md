# Handoff — EJBCA

Triggered by `--mode public --public-ca-name ejbca`.
[EJBCA Community / Enterprise](https://www.ejbca.org/) is a popular
open-source CA. This doc walks through enrolling Splunk leaves
via EJBCA's REST API or `cmpclient`.

## EJBCA Certificate Profile for Splunk leaves

In the EJBCA admin web UI:

1. **Certificate Profile** → Add new → name `SplunkServerLeaf`.
2. **Type** → End Entity.
3. **Available bit lengths** → 2048, 4096.
4. **Available key algorithms** → RSA, ECDSA.
5. **ECDSA curves** → `prime256v1, secp384r1, secp521r1`.
6. **Signature algorithm** → SHA256WithRSA, SHA384WithRSA,
   SHA384WithECDSA.
7. **Validity** → 825 days.
8. **X.509v3 extensions**:
   - **Key Usage** → Critical, Digital Signature, Key Encipherment.
   - **Extended Key Usage** → Critical, Server Authentication
     (`1.3.6.1.5.5.7.3.1`), Client Authentication
     (`1.3.6.1.5.5.7.3.2`). ← KV Store dual EKU.
   - **Subject Alternative Name** → Use Subject Alt Name field
     from request.
   - **Basic Constraints** → Critical, CA: false.
9. **End Entity Profile** → Add new → name `SplunkServerLeaf`.
10. **Certificate Profiles** → choose `SplunkServerLeaf`.
11. **Subject DN** → CN required, allow operator-supplied.
12. **Subject Alt Name** → DNS Name + IP Address fields enabled.

## Submit via REST API

EJBCA REST API endpoint: `/ejbca/ejbca-rest-api/v1/certificate/pkcs10enroll`.

```bash
for csr in splunk-platform-pki-rendered/pki/signed/*.csr; do
  host="$(basename "$csr" .csr)"
  encoded_csr="$(base64 -w0 < "$csr")"

  curl --silent --show-error \
       --cacert ejbca-management-ca.pem \
       --cert  ejbca-mgmt-client.pem \
       --key   ejbca-mgmt-client.key \
       -X POST \
       https://ejbca.example.com:8443/ejbca/ejbca-rest-api/v1/certificate/pkcs10enroll \
       -H 'Content-Type: application/json' \
       -d "{
            \"certificate_request\": \"${encoded_csr}\",
            \"certificate_profile_name\": \"SplunkServerLeaf\",
            \"end_entity_profile_name\": \"SplunkServerLeaf\",
            \"certificate_authority_name\": \"ExampleIssuingCA\",
            \"username\": \"${host}\",
            \"password\": \"$(< /tmp/ejbca_enrollment_password)\",
            \"include_chain\": true
          }" \
    | jq -r '.certificate' \
    | base64 -d \
    > "splunk-platform-pki-rendered/pki/signed/${host}.pem"
done
```

Then pull the issuing CA chain:

```bash
curl --silent \
     --cacert ejbca-management-ca.pem \
     https://ejbca.example.com:8443/ejbca/ejbca-rest-api/v1/ca/ExampleIssuingCA/certificate/download \
  | openssl pkcs7 -inform DER -print_certs \
  > splunk-platform-pki-rendered/pki/install/cabundle.pem
```

## Submit via CMP

If the operator has CMP set up, use `cmpclient`:

```bash
cmpclient \
    --cmd cr \
    --server https://ejbca.example.com:8443/ejbca/publicweb/cmp \
    --csr splunk-platform-pki-rendered/pki/signed/splunkd-idx01.example.com.csr \
    --ref-num <CMP shared secret reference> \
    --secret file:/tmp/ejbca_cmp_password \
    --certout splunk-platform-pki-rendered/pki/signed/splunkd-idx01.example.com.pem
```

## Verify before installing

```bash
bash splunk-platform-pki-rendered/pki/install/verify-leaf.sh \
    --cert splunk-platform-pki-rendered/pki/signed/splunkd-idx01.example.com.pem \
    --ca   splunk-platform-pki-rendered/pki/install/cabundle.pem
bash splunk-platform-pki-rendered/pki/install/kv-store-eku-check.sh \
    --cert splunk-platform-pki-rendered/pki/signed/splunkd-idx01.example.com.pem \
    --ca   splunk-platform-pki-rendered/pki/install/cabundle.pem
```

If KV Store EKU check fails, the EJBCA Certificate Profile is
missing one of the EKU values (step 8 above).

## Renewal

EJBCA supports SCEP, CMP, and REST renewal. The Splunk-side
rolling restart cadence stays the same — see
[rotation-runbook.md](rotation-runbook.md).

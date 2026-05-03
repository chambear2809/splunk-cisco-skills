# Handoff — Microsoft AD CS

Triggered by `--mode public --public-ca-name adcs`. Most enterprise
Splunk deployments already have Microsoft Active Directory
Certificate Services running for AD-joined workstations. This doc
walks the operator through:

1. Creating an AD CS cert template that matches Splunk's
   requirements.
2. Submitting the CSRs the renderer emitted.
3. Installing the returned PEMs.

## Cert template requirements

Splunk leaf certs need:

- **Key usage** — Digital Signature, Key Encipherment.
- **Extended key usage** — Server Authentication
  (`1.3.6.1.5.5.7.3.1`) AND Client Authentication
  (`1.3.6.1.5.5.7.3.2`). The dual EKU is required for KV Store
  7.0+.
- **Subject Alternative Name** — operator-supplied (typically
  the host FQDN + short name + optional IP).
- **Validity** — 825 days max (preflight refuses higher).
- **Key length** — RSA-2048 minimum.
- **Hash** — SHA-256 minimum (no SHA-1).

In **AD CS Certificate Templates console** (`certtmpl.msc`):

1. Duplicate the built-in **Web Server (Computer)** template.
2. Name it `Splunk-Server-Leaf`.
3. **Compatibility** → CA: Windows Server 2016+; Recipient:
   Windows 10 / Server 2016+.
4. **General** → Validity period 825 days; Renewal 30 days.
5. **Request Handling** → Allow private key to be exported: NO;
   Minimum key size: 2048; CSP: Microsoft RSA SChannel /
   Microsoft Software Key Storage Provider.
6. **Cryptography** → Algorithm: RSA; Min key size: 2048;
   Request hash: SHA256.
7. **Subject Name** → Supply in the request.
8. **Extensions → Application Policies** → Add **Client
   Authentication** alongside **Server Authentication**. ← THIS
   IS WHAT KV STORE NEEDS.
9. **Security** → Grant the Splunk service account "Read" and
   "Enroll".
10. Issue the template via **Certificate Authority** console →
    Certificate Templates → New → Certificate Template to Issue.

## Submit each CSR

For each CSR file the renderer produced:

```powershell
# On a domain-joined Windows host with the AD CS PowerShell module.
$csr = Get-Content "splunk-platform-pki-rendered\pki\signed\splunkd-idx01.example.com.csr" -Raw
$result = Submit-CertificateRequest -CertificateRequest $csr -CertificationAuthority "ca.example.com\Example Issuing CA" -Template "Splunk-Server-Leaf"
$result.Certificate | Export-Certificate -FilePath "signed\splunkd-idx01.example.com.cer" -Type CERT

# Convert DER → PEM
openssl x509 -inform DER -in signed\splunkd-idx01.example.com.cer `
             -out signed\splunkd-idx01.example.com.pem
```

For bulk submission via `certreq.exe`:

```cmd
certreq -submit -attrib "CertificateTemplate:Splunk-Server-Leaf" -config "ca.example.com\Example Issuing CA" splunkd-idx01.example.com.csr splunkd-idx01.example.com.cer
```

## Pull the chain

Export the issuing CA chain (Root + any Intermediates) from the
AD CS console as a `.p7b`, then convert to PEM:

```bash
openssl pkcs7 -inform DER -in adcs-chain.p7b -print_certs -out cabundle.pem
```

Or via certutil:

```cmd
certutil -ca.chain ca-chain.p7b
```

## Verify before installing

```bash
bash splunk-platform-pki-rendered/pki/install/verify-leaf.sh \
    --cert splunk-platform-pki-rendered/pki/signed/splunkd-idx01.example.com.pem \
    --ca   cabundle.pem
bash splunk-platform-pki-rendered/pki/install/kv-store-eku-check.sh \
    --cert splunk-platform-pki-rendered/pki/signed/splunkd-idx01.example.com.pem \
    --ca   cabundle.pem
```

If `kv-store-eku-check.sh` returns "EKU does not include
clientAuth", the AD CS template is missing the Client
Authentication application policy. Re-issue the template (step 8
above).

## Autoenrollment for forwarders

For **AD-joined Universal Forwarder hosts**, the operator can
configure GPO-based autoenrollment so each UF picks up its leaf
cert automatically. The renderer's UF outputs overlay then
references `clientCert` paths the GPO drops into place. Out of
scope for this skill but cleanly composable with
`splunk-universal-forwarder-setup` and
`splunk-agent-management-setup`.

## Renewal

AD CS supports auto-renewal via GPO when the template's renewal
period (default 30 days) is set. The Splunk-side rolling restart
still has to happen manually — wire it to the AD CS renewal event
via SCOM / Splunk monitoring + the rotation runbook.

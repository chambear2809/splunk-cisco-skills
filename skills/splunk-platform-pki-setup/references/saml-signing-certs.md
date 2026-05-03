# SAML SP Signing Certificate

The SAML Service Provider (SP) signing certificate is a separate
trust domain from inter-Splunk TLS. Splunk Web uses it to sign
SAML AuthnRequests it sends to the IdP, and to verify the
signature on assertions the IdP returns.

> Anchor:
> [Configure SAML SSO using configuration files](https://docs.splunk.com/Documentation/Splunk/9.4.2/Security/ConfigureSAMLSSO).

## Two cert identities, do not confuse

| Identity | Purpose | Where it lives | Whose key signs |
|---|---|---|---|
| **SP signing cert** (this skill mints) | Splunk → IdP signs AuthnRequest; IdP verifies signature | SP cert distributed to IdP via SP metadata | Splunk's private key |
| **IdP cert** (operator obtains from IdP) | IdP → Splunk signs assertion; Splunk verifies signature | `$SPLUNK_HOME/etc/auth/idpCerts/<idp>.crt` referenced by `idpCertPath` | IdP's private key |

This skill mints the SP cert when `--saml-sp=true`. It does NOT
mint or rotate the IdP cert (that's an IdP operator action).

## SP signing cert profile

```
[v3_saml]
basicConstraints       = critical, CA:FALSE
keyUsage               = critical, digitalSignature, nonRepudiation
# No EKU — signing-only, not transport TLS
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid:always, issuer
subjectAltName         = @alt_names

[alt_names]
DNS.1 = splunk.example.com
```

Note: no `extendedKeyUsage`. SAML signatures are XML-DSig, not
TLS, so the EKU constraint doesn't apply. Many IdPs explicitly
reject certs with `serverAuth` / `clientAuth` EKUs in the SP
signing role.

## Signature algorithm

`authentication.conf [<saml-authSettings>]`:

```
[saml_settings]
signAuthnRequest               = true
signedAssertion                = true
signatureAlgorithm             = RSA-SHA384
InboundSignatureAlgorithm      = RSA-SHA384;RSA-SHA512
idpCertPath                    = /opt/splunk/etc/auth/idpCerts/azure-idp.crt
```

Splunk supports `RSA-SHA1`, `RSA-SHA256`, `RSA-SHA384`,
`RSA-SHA512`. The skill defaults to **RSA-SHA384** and refuses
SHA-1 (the latter is forbidden in modern security baselines).

Set `InboundSignatureAlgorithm` to a semicolon-separated list of
algorithms Splunk accepts on incoming signed responses. The
defaults shown accept SHA-384 or SHA-512 from the IdP.

## Generation

In Private mode, the renderer's `pki/private-ca/sign-saml-sp.sh`
mints the SP signing cert signed by the Intermediate CA (or Root
if no Intermediate). In Public mode, the renderer emits
`pki/csr-templates/saml-sp.cnf` and the operator submits to the
CA (the SP cert can be signed by any CA the operator trusts; it
doesn't need to be a public CA because the IdP only validates
against the cert in SP metadata, not against a chain).

## Distribution

```
splunk-platform-pki-rendered/pki/distribute/saml-sp/
├── sp-signing.crt
├── sp-signing.key.placeholder
└── README.md
```

Operator copies to:

```
$SPLUNK_HOME/etc/auth/myssl/saml/sp-signing.crt
$SPLUNK_HOME/etc/auth/myssl/saml/sp-signing.key
```

And references via:

```
authentication.conf [<saml-authSettings>]:
    samlSpSigningCertPath = $SPLUNK_HOME/etc/auth/myssl/saml/sp-signing.crt
    samlSpSigningKeyPath  = $SPLUNK_HOME/etc/auth/myssl/saml/sp-signing.key
```

(The exact setting names vary by Splunk version — the renderer
emits the right ones based on `--splunk-version`.)

## Rotation = re-upload SP metadata at the IdP

This is the critical operator step. After installing the new SP
signing cert:

1. **Splunk Web → Settings → Authentication → SAML → Generate
   metadata**. Splunk regenerates SP metadata XML using the new
   signing cert.
2. Copy the metadata XML to the IdP (Okta / Entra / AD FS / etc).
3. The IdP re-imports the metadata and accepts the new signing
   key.
4. Test SSO with a non-admin account before completing the
   rotation.
5. Once SSO works, deactivate the old SP cert at the IdP.

If the operator skips step 2, every signed AuthnRequest fails at
the IdP with "Signature verification failed".

## Encryption

If the IdP encrypts assertions, Splunk needs an encryption cert
to decrypt them. By convention the encryption cert can be the
same as the signing cert OR a separate cert. The skill mints
just the signing cert; if the operator needs a separate
encryption cert, run the skill twice with different `--saml-sp`
identities.

## Public-exposure-hardening overlap

`splunk-enterprise-public-exposure-hardening` already accepts
`--saml-signing-cert-file` (operator-supplied existing cert
path). The PKI skill MINTS the cert when none exists, places it
where the hardening skill expects, and the two skills coexist:

- PKI skill renders + installs the cert.
- Hardening skill consumes the cert path in
  `authentication.conf` overlay.

## SAML and FIPS

In FIPS 140-3 mode, RSA-SHA1 is forbidden. The skill defaults to
RSA-SHA384 and refuses SHA-1, so FIPS posture is preserved. If
the operator's IdP only supports SHA-1 signing (rare in 2026),
flag the IdP for upgrade rather than weakening the signature
algorithm.

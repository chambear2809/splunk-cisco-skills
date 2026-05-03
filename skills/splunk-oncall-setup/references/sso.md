# Splunk On-Call Single Sign-On (SAML)

SAML SSO for Splunk On-Call cannot be activated through the public API. The
skill renders a `handoff` with the SP-initiated URL pattern, the IdP
metadata XML drop-off steps, and a Splunk Support ticket template.

## SP-initiated URL

```
https://portal.victorops.com/auth/sso/<companyId>
```

- `<companyId>` is the alphanumeric ID Splunk Support provisions for the
  org. It is **not** the org slug.
- Configure this URL as the **Default Relay State** in the IdP.

## Activation steps (operator)

1. Choose an IdP: Okta, Google Apps, Azure AD, ADFS, OneLogin, or any
   generic SAML 2.0 provider.
2. Export the IdP metadata as XML.
3. Open a ticket with Splunk On-Call Support and attach the metadata file.
   Request SAML activation for the org and supply:
   - The org name and Splunk On-Call admin contact.
   - The IdP issuer URL and entity ID.
   - The companyId (if already provisioned) or a request to provision one.
4. Splunk Support enables SAML and replies with the SP entity ID, ACS URL,
   and `<companyId>`.
5. In the IdP, finish the SAML application configuration:
   - Audience / SP Entity ID — value from Splunk Support.
   - ACS / Single Sign-On URL — value from Splunk Support.
   - NameID format — Email Address.
   - Default Relay State — `https://portal.victorops.com/auth/sso/<companyId>`.
6. Assign users in the IdP and verify login at the SP-initiated URL.

## Beta Okta SSO + user provisioning

A self-service Okta integration is available in beta and is documented at
`https://docs.splunk.com/observability/en/sp-oncall/spoc-integrations/setup-single-sign-on-sso-and-user-provisioning-with-okta-beta.html`.
The skill renders the Okta-specific deeplinks when `sso.kind: okta_beta` is
set in the spec.

## Spec shape

```yaml
sso:
  kind: saml          # or okta_beta
  company_id: ""      # optional; left blank for new requests
  idp:
    name: Okta
    metadata_path: /tmp/idp-metadata.xml
    issuer: https://example.okta.com
    entity_id: http://www.okta.com/exk1abc
  contacts:
    - email: oncall-admin@example.com
```

The renderer never reads `metadata_path` to send anywhere — it only emits a
checklist for the operator to attach the file to the support ticket.

## Source

- https://help.splunk.com/en/splunk-cloud-platform/alert-and-respond/splunk-on-call/introduction-to-splunk-on-call/single-sign-on/configure-single-sign-on-for-splunk-on-call
- https://docs.splunk.com/observability/en/sp-oncall/admin/sso/single-sign-sso.html
- https://saml-doc.okta.com/SAML_Docs/How-to-Configure-SAML-2.0-for-VictorOps.html

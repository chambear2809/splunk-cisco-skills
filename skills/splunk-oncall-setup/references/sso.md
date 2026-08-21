# Splunk On-Call Single Sign-On (SAML)

SAML SSO for Splunk On-Call cannot be activated through the public API. The
skill renders a `handoff` with the SP-initiated URL pattern, the IdP
metadata XML drop-off steps, and a Splunk Support ticket template.

## SP-initiated URL

```
https://portal.victorops.com/auth/sso/<org-slug>
```

- `<org-slug>` is the organization slug from the Splunk On-Call portal.
  Splunk's per-IdP guides use the org slug in this URL for Okta, Google
  Apps, OneLogin, Azure AD, and AWS IAM Identity Center.
- Configure this URL as the **Default Relay State** in the IdP. Azure AD
  and AWS IAM Identity Center also use it as the sign-on / start URL.

## Activation steps (operator)

1. Choose an IdP: Okta, Google Apps, Azure AD, ADFS, OneLogin, AWS IAM
   Identity Center, or any generic SAML 2.0 provider.
2. Export the IdP metadata as XML.
3. Open a ticket with Splunk On-Call Support and attach the metadata file.
   Request SAML activation for the org and supply:
   - The org name and Splunk On-Call admin contact.
   - The IdP issuer URL and entity ID.
   - The org slug the SP-initiated URL will use.
4. A Splunk On-Call support specialist completes the back-end setup and
   replies with confirmation. IdPs that import SP metadata (ADFS) receive
   an updated metadata file to import.
5. In the IdP, finish the SAML application configuration. Splunk publishes
   the service-provider values, so they do not have to be requested:
   - Audience / SP Entity ID — `victorops.com`. Azure AD calls this the
     Identifier and expects `https://victorops.com`.
   - ACS / Reply URL — `https://sso.victorops.com/sp/ACS.saml2`. The Google
     Apps guide writes the same endpoint with an explicit `:443`.
   - NameID format — Email Address. ADFS maps the `E-Mail-Addresses` LDAP
     attribute to the `Name ID` outgoing claim type.
   - Default Relay State — `https://portal.victorops.com/auth/sso/<org-slug>`.
6. Assign users in the IdP and verify login at the SP-initiated URL.

## Beta Okta SSO + user provisioning

A beta Okta integration adds SCIM 2.0 user provisioning on top of SAML SSO.
It is documented at
`https://help.splunk.com/en/splunk-observability-cloud/splunk-on-call/integrations-with-splunk-on-call/sso-beta-integration-for-splunk-on-call`.
The page carries a full beta disclaimer: Splunk offers the feature for
evaluation only, disclaims warranties, and states it is not subject to
support, update, or upgrade commitments.

This is **not** a self-service setup. Splunk states that configuring SCIM
single sign-on and the initial activation of Okta provisioning "is currently
not a self-service process and requires contacting the Support team." Budget
for a support case, not an operator-only workflow.

Operator notes:

- The Okta application is named **VictorOps (Beta)**. Search that name in
  the Okta application catalog.
- Provisioning covers Push New Users, Push User Deactivation, and Reactivate
  Users. A reactivated user still needs manual reconfiguration in On-Call.
- The requester must be a Global Admin of the Splunk On-Call org and must
  supply the IdP metadata URL plus the list of users to be assigned. Splunk
  asks that users are **not** assigned to the app until Support finishes its
  side.
- Deprovisioning is destructive. Removing a user permanently deletes their
  On-Call contact methods not present in Okta, mobile device registration,
  paging policies, team membership, and on-call rotation membership, and
  removes them from escalation policies and scheduled overrides. Reassigning
  the user does not restore any of it.

The skill renders the Okta-specific deeplinks when `sso.kind: okta_beta` is
set in the spec.

## Spec shape

```yaml
sso:
  kind: saml          # or okta_beta
  company_id: ""      # vestigial; the renderer never reads it. The
                      # SP-initiated URL is built from the top-level org_slug.
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

- https://help.splunk.com/en/splunk-observability-cloud/splunk-on-call/introduction-to-splunk-on-call/single-sign-on
- https://help.splunk.com/en/splunk-observability-cloud/splunk-on-call/introduction-to-splunk-on-call/single-sign-on/configure-single-sign-on-for-okta-and-splunk-on-call
- https://help.splunk.com/en/splunk-observability-cloud/splunk-on-call/introduction-to-splunk-on-call/single-sign-on/configure-single-sign-on-for-splunk-on-call
- https://help.splunk.com/en/splunk-observability-cloud/splunk-on-call/introduction-to-splunk-on-call/single-sign-on/configure-single-sign-on-for-splunk-on-call-other-idps
- https://help.splunk.com/en/splunk-observability-cloud/splunk-on-call/introduction-to-splunk-on-call/single-sign-on/configure-active-directory-federation-services-single-sign-on-for-splunk-on-call
- https://help.splunk.com/en/splunk-observability-cloud/splunk-on-call/integrations-with-splunk-on-call/sso-beta-integration-for-splunk-on-call
- https://saml-doc.okta.com/SAML_Docs/How-to-Configure-SAML-2.0-for-VictorOps.html

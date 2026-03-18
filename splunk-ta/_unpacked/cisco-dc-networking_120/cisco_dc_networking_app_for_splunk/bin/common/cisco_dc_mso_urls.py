# Authentication APIs
LOGIN_URL = "mso/api/v1/auth/login"
ND_LOGIN_URL = "login"
LOGIN_DOMAIN = "mso/api/v1/auth/login-domains"
API_RETURNING_SITE_ID = "mso/api/v1/sites"

# Audit API
AUDIT_RECORDS = {"splunk_field": "msoAuditRecords", "api": "mso/api/v1/audit-records"}

# Fabric API
# here id is the site id
FABRIC_API = {"fabricDetails": "mso/api/v1/sites/{id}/fabric-connectivity"}

# Policy APIs
POLICY_APIS = {"policyDetails": "mso/api/v1/policies"}
# here id is the policy id, that we get in response of policyDetails api call
SPECIFIC_POLICY_APIS = {"policyUsage": "mso/api/v1/policies/usage/{id}"}

# Site APIs
# here id is the site id
SPECIFIC_SITE_APIS = {"siteLabels": "mso/api/v1/sites/{id}/labels", "siteHealth": "mso/api/v1/sites/{id}"}

# Schema APIs
SCHEMA_APIS = {"schemaDetails": "mso/api/v1/schemas"}
# here id is the schema id, that we get in response of schemaDetails api call
SPECIFIC_SCHEMA_APIS = {
    "schemaHealthFaults": "mso/api/v1/schemas/{id}/health-faults",
    "schemaTenants": "mso/api/v1/schemas/{id}/tenants",
}

# Tenant APIs
TENANT_APIS = {"tenantDetails": "mso/api/v1/tenants"}
# here id is the tenant id, that we get in response of tenantDetails api call
SPECIFIC_TENANT_APIS = {"tenantNetworkMapping": "mso/api/v1/tenants/{id}/infra"}

# User APIs
USER_APIS = {"userDetails": "mso/api/v1/users", "userAllowedRoles": "mso/api/v1/users/allowed-roles"}
# here id is the user id, that we get in response of userDetails api call
SPECIFIC_USER_APIS = {
    "userPermissions": "mso/api/v1/users/{id}/permissions",
    "userRoles": "mso/api/v1/users/{id}/roles",
}

---
name: splunk-appdynamics-controller-admin-setup
description: >-
  Render, validate, and optionally apply API-backed Splunk AppDynamics
  Controller administration workflows, including SaaS and on-prem account
  checks, API clients, OAuth token-file flow, users, groups, roles, SAML, LDAP,
  account permissions, licensing, license rules, sensitive data collection
  controls, privacy settings, audit readiness, and data collection dashboards. Use when the user asks for
  AppDynamics Controller administration, API clients, OAuth, RBAC, SAML, LDAP,
  user/group/role management, account permissions, licensing, license rules,
  sensitive data controls, SQL/log masking, environment variable filtering, or
  privacy validation.
---

# Splunk AppDynamics Controller Admin Setup

Controller administration uses documented APIs where available and renders
runbooks for IdP-side, tenant-side, or UI-only operations.

```bash
bash skills/splunk-appdynamics-controller-admin-setup/scripts/setup.sh --render
bash skills/splunk-appdynamics-controller-admin-setup/scripts/validate.sh
```

Secrets such as OAuth client secrets and passwords must be referenced by
chmod-600 files.

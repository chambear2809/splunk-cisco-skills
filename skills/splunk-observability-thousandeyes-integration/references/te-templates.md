# ThousandEyes Templates

Source: `developer.cisco.com/docs/thousandeyes/create-template` and `developer.cisco.com/docs/thousandeyes/alertruleconfigurationtemplate`.

TE Templates are the recommended way to deploy related assets in one shot. A single template body deploys, **in this exact order**:

1. Labels
2. Tests
3. Endpoint Tests
4. Tags
5. Alert Rules
6. Dashboard Filters
7. Dashboards

ThousandEyes ships pre-built templates for common services (Office365, Webex, Atlassian, Slack, custom HTTP / network / API). User-authored templates become visible to other users in the account group with `View Templates Read` permission.

## Handlebars placeholders for credentials

The TE Templates API **rejects plain-text credentials with HTTP 400.** The skill's renderer enforces this at render time so the operator catches it before the network call.

Valid placeholder shape: `{{<context>.<key>}}`. Examples:

- `{{te_credentials.api_key}}` — references a credential the operator selects at deploy time.
- `{{user_inputs.application_url}}` — references a user input declared elsewhere in the template body.

Invalid (rejected by the renderer):

- `"password": "mySecret123"` (plain text)
- `"api_key": "abcd-1234-..."` (plain text, even when scrambled)
- `"token": ""` (empty string is allowed; the renderer treats empty as "not set")
- `"authorization": "Bearer abcdef"` (plain Bearer header)

The render-time enforcement walks the entire `template_body` tree and matches keys whose normalized name is one of `password, secret, token, api_key, client_secret, bearer, authorization`. If you need a literal string in one of those fields (rare; usually a non-credential value), set the value via a Handlebars constant (`{{constants.policy_id}}`) so it visibly looks like a placeholder.

## Deploying a template

The skill's apply-template.sh:

1. POST `/v7/templates` with the template body — TE returns the new template ID.
2. (If `--deploy-templates` was passed) POST `/v7/templates/{id}/deploy` with an empty body to materialize the assets.

Operators can also deploy templates through the TE UI (Manage > Templates > Deploy) which is preferable for first-time deployments because the UI surfaces dependent inputs and confirmations.

## Spec shape

```yaml
templates:
  - name: "RAG service health"
    description: "Synthetic monitoring for the RAG inference path."
    template_body:
      schema_version: "1.0"
      labels:
        - name: "rag-service"
      tests:
        - type: http-server
          name: "RAG /health"
          target: "{{user_inputs.application_url}}/health"
          interval: 60
          agents:
            - "{{user_inputs.primary_agent_id}}"
      alert_rules:
        - name: "RAG availability < 99%"
          # ...
      dashboards:
        - name: "RAG service health"
          # ...
      user_inputs:
        - id: application_url
          label: "Application URL"
          type: string
        - id: primary_agent_id
          label: "Primary TE agent ID"
          type: agent
      credentials:
        - id: api_key
          label: "Application API key"
          type: token
```

The `credentials` block is the standard TE Templates pattern for deferring credential entry to deploy time. References inside the template body use `{{te_credentials.<id>}}` to interpolate the credential's value at deploy time only.

## Pre-built TE templates

Use `bash scripts/list-templates.sh` (after the skill renders) to enumerate the templates the account group can deploy. Common pre-built names include:

- `Microsoft Office 365`
- `Cisco Webex`
- `Atlassian Cloud`
- `Slack`
- `Generic HTTP service`
- `Generic network test`
- `Generic API test`

Pre-built templates can be deployed without authoring a custom `template_body`; pass `--deploy-templates` and reference the pre-built template ID in the spec instead.

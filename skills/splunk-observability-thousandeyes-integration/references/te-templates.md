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
- `"authorization": "Bearer abcdef"` (plain Bearer header)

An empty credential value such as `"token": ""` is treated as not set and is allowed at render time.

The render-time enforcement walks the entire `template_body` tree and matches keys whose normalized name is one of `password, secret, token, api_key, client_secret, bearer, authorization`. If you need a literal string in one of those fields (rare; usually a non-credential value), set the value via a Handlebars constant (`{{constants.policy_id}}`) so it visibly looks like a placeholder.

## Deploying a template

The skill's `apply-template.sh`:

1. Preflights the template collection, POSTs `/v7/templates`, retains the returned template ID, and verifies that ID by collection readback.
2. If `--deploy-templates` was passed, POSTs `/v7/templates/{id}/deploy` once per retained state and confirms that the template resource is still readable. This readback does not prove every asynchronous child asset finished deploying.

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

## Existing templates

Use `bash scripts/list-templates.sh` after rendering to enumerate templates visible to the account group. This skill's spec creates templates from `templates[].template_body`; it does not accept a pre-built template ID as a substitute for that body. Deploy an existing/pre-built template through the TE UI or another documented workflow.

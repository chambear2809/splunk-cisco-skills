# Galileo MCP Troubleshooting

## Endpoint

Default URL:

```text
https://api.galileo.ai/mcp/http/mcp
```

Self-hosted URL derivation:

1. Start with the Galileo console URL.
2. Replace the first `console` label with `api`.
3. Append `/mcp/http/mcp`.

## Required Headers

Direct HTTP clients need:

```text
Galileo-API-Key: <provided by client secret store>
Accept: text/event-stream
```

Do not inline the API key into rendered files.

## Expected Protocol Checks

No-secret checks:

- `initialize` should return server info with name `EvalsInIDEServer`.
- `tools/list` should return the public tool schemas.
- `prompts/list` and `resources/list` are currently empty.

Optional key check:

- `GET /v2/current_user` should return 200 with a valid key and 401 without
  authentication.

## Common Failures

- **Connection hangs on GET**: use JSON-RPC POST for MCP methods; a plain GET
  against the stream endpoint can wait for events.
- **Method Not Allowed on OPTIONS**: the endpoint supports GET, POST, and
  DELETE; use POST for JSON-RPC method calls.
- **Authentication required from tenant tools**: set the API key in the client
  config or local `.env.galileo-mcp`; no-secret `tools/list` can still succeed.
- **Key-file permission failure**: `--galileo-api-key-file` must point to a
  chmod-600 file. Use `--allow-loose-key-perms` only for disposable lab tests.
- **Self-hosted endpoint not found**: confirm the hostname is the API host, not
  the console host, and that `/mcp/http/mcp` was appended.
- **Unexpected tool names**: run `probe_mcp.py`; unknown tools are
  manual-approval-only until `references/tool-catalog.md` is reviewed.

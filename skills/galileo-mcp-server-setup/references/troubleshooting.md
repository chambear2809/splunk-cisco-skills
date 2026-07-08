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
Accept: application/json, text/event-stream
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
- **HTTP 406 during initialize**: do not send an SSE-only Accept header. MCP
  Streamable HTTP clients must advertise both `application/json` and
  `text/event-stream` for POST responses.
- **Local bridge initialize timeout**: re-render the current dependency-free
  bridge. Older rendered assets delegated to `mcp-remote` and could hang during
  initialize against Galileo. Confirm the bridge does not contain
  `mcp-remote`, then run the focused pytest fake-server regression.
- **Secret-file permission failure**: run `chmod 600` on
  `.env.galileo-mcp` and `GALILEO_API_KEY_FILE`. Use
  `GALILEO_MCP_ALLOW_LOOSE_KEY_PERMS=1` only in a disposable lab.
- **Redirect rejected**: this is intentional. Resolve the canonical MCP URL;
  neither the bridge nor authenticated probe forwards the Galileo API key
  across redirects.
- **Remote HTTP URL rejected**: use HTTPS. Cleartext HTTP is allowed only for
  loopback validation fixtures and cannot be rendered into a remote direct
  client configuration.
- **Server notification stream repeatedly closes**: the bridge reconnects with
  capped exponential backoff and bounds each SSE event independently. A 400,
  401, 403, 404, 405, redirect, or non-SSE GET response disables only the
  optional event stream; JSON-RPC POST methods remain available.
- **Cancellation appears delayed**: use the current bridge. It serializes only
  initialize/initialized; later requests and notifications are concurrent so
  `notifications/cancelled` is not queued behind the target tool call.
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

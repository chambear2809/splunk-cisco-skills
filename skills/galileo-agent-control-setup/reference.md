# Galileo Agent Control Setup Reference

## Official References

- Agent Control overview: `https://docs.agentcontrol.dev/core/overview`
- Agent Control controls: `https://docs.agentcontrol.dev/concepts/controls`
- Agent Control repository: `https://github.com/agentcontrol/agent-control`
- Galileo Agent Observability Controls handoff owner:
  `../galileo-platform-setup/reference.md#agent-observability-controls`

Re-check these docs before changing server env names, control policy shape,
SDK snippets, or sink configuration.

## Apply Sections

This skill owns standalone/external Agent Control runtime, server, and sink
assets. It does not own the Galileo Agent Observability `Controls` console tab
or Log stream control attachment workflow; use `galileo-platform-setup`
`observability-controls` for that platform surface. It also does not own the
packaged Galileo On-Prem Agent Control chart, migrations, route, or UI proxy;
use `galileo-on-prem-agent-control-setup` for that deployment lifecycle.

| Section | Owner | Purpose |
| --- | --- | --- |
| `server` | `galileo-agent-control-setup` | Render Docker/external server readiness and health endpoint notes. |
| `auth` | `galileo-agent-control-setup` | Render file-backed Agent Control API/admin key env templates. |
| `controls` | `galileo-agent-control-setup` | Render starter observe and deny policy templates. |
| `python-runtime` | `galileo-agent-control-setup` | Provide Python `@control()` runtime snippets. |
| `typescript-runtime` | `galileo-agent-control-setup` | Provide TypeScript runtime skeleton snippets. |
| `otel-sink` | `galileo-agent-control-setup` | Render OTel sink env configuration. |
| `splunk-sink` | `galileo-agent-control-setup` | Render custom Splunk HEC control-event sink code. |
| `splunk-hec` | `splunk-hec-service-setup` | Prepare Splunk HEC service/token configuration. |
| `otel-collector` | `splunk-observability-otel-collector-setup` | Render Splunk OTel Collector assets for OTel sink export. |
| `dashboards` | `splunk-observability-dashboard-builder` | Render/apply Observability dashboard specs. |
| `detectors` | `splunk-observability-native-ops` | Render/apply Observability detector specs. |

## Control Policy Notes

Agent Control scopes can target `step_types`, exact `step_names`,
`step_name_regex`, and `stages` such as `pre` and `post`. Actions include
`observe`, `deny`, and `steer`. Deny decisions win over other matching controls,
so production rollout should usually start in observe mode.

## Sink Notes

The OTel sink uses Agent Control SDK environment settings:

- `AGENT_CONTROL_OBSERVABILITY_SINK_NAME=otel`
- `AGENT_CONTROL_OTEL_ENABLED=true`
- `AGENT_CONTROL_OTEL_ENDPOINT=<otlp-http-endpoint>`

The custom Splunk sink reads `SPLUNK_HEC_TOKEN_FILE` at runtime and sends JSON
objects to `/services/collector/event` with `sourcetype=agent_control:events:json`.
It validates both rendered and runtime `SPLUNK_HEC_URL` values, rejects embedded
credentials, ambiguous paths, invalid ports, and plaintext remote destinations,
and disables redirects so the `Authorization` header stays on the reviewed
origin. Root and `/services/collector` inputs normalize to the exact event path.

`AGENT_CONTROL_BASE_URL` follows the same credential-bound transport policy: it
must be a credential-free HTTP(S) origin, use a valid port, contain no path,
query, or fragment, and use HTTPS unless the hostname is loopback. The rendered
Python and TypeScript snippets revalidate environment overrides before use.

## Troubleshooting

- Agent Control health fails: verify `server/external-server-readiness.md`, URL,
  port, TLS, and network reachability.
- Auth failures: verify API key files, admin key files, the credential-free
  HTTPS server origin, server-side auth enablement, and key rotation policy.
- Controls do not fire: confirm the agent name, registered steps, scope, stages,
  and whether the policy is enabled.
- OTel sink is silent: confirm the OTLP endpoint and that the SDK was installed
  with the OTel extra where required.
- Splunk HEC sink fails: verify HEC token file, allowed indexes, exact HEC event
  URL, HTTPS/TLS, and sourcetype/index settings. Redirect responses are rejected.

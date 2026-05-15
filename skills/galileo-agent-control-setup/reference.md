# Galileo Agent Control Setup Reference

## Official References

- Agent Control overview: `https://docs.agentcontrol.dev/core/overview`
- Agent Control controls: `https://docs.agentcontrol.dev/concepts/controls`
- Agent Control repository: `https://github.com/agentcontrol/agent-control`

Re-check these docs before changing server env names, control policy shape,
SDK snippets, or sink configuration.

## Apply Sections

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

## Troubleshooting

- Agent Control health fails: verify `server/external-server-readiness.md`, URL,
  port, TLS, and network reachability.
- Auth failures: verify API key files, admin key files, server-side auth
  enablement, and key rotation policy.
- Controls do not fire: confirm the agent name, registered steps, scope, stages,
  and whether the policy is enabled.
- OTel sink is silent: confirm the OTLP endpoint and that the SDK was installed
  with the OTel extra where required.
- Splunk HEC sink fails: verify HEC token file, allowed indexes, HEC URL, and
  sourcetype/index settings.

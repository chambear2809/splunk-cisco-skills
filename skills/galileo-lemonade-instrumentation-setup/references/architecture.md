# Architecture and compatibility

## Contents

- [Verified Lemonade v10.10 behavior](#verified-lemonade-v1010-behavior)
- [Mode A: server fan-out](#mode-a-server-fan-out)
- [Mode B: client fan-out](#mode-b-client-fan-out)
- [Exact endpoint intake](#exact-endpoint-intake)
- [Queue policy](#queue-policy)
- [Duplicate and stitch boundary](#duplicate-and-stitch-boundary)

## Verified Lemonade v10.10 behavior

- `telemetry.otlp.endpoint` is one scalar destination.
- OTLP transport is HTTP protobuf or JSON; native telemetry is traces only.
- Both `openinference` and `otel_genai` semantics can be emitted together.
- Successful chat spans include `openinference.span.kind=LLM`, input/output,
  model, token fields, `gen_ai.operation.name=chat`, and
  `gen_ai.provider.name=lemonade`.
- `hide_inputs`, `hide_outputs`, and `hide_thinking` replace content before the
  collector receives the span. Collector fan-out cannot recover hidden data.
- Each request gets a new trace/span ID. No incoming `traceparent`, parent span,
  or workflow/tool hierarchy is created.
- Native error spans lack Galileo's documented `error.type`; native text
  completion uses `completion` rather than documented `text_completion`.

Therefore successful chat spans are suitable for Galileo LLM ingestion, but
native telemetry is not full agent instrumentation.

## Mode A: server fan-out

Use for zero-code operational inference telemetry. Add a separate
Galileo-only pipeline that shares the reviewed receiver set but drops every
span whose resource `service.name` is not exactly `lemonade-server`. The
existing Splunk exporters stay unchanged; its only added behavior is
conditional Lemonade error-message redaction. The filter is attribute-based,
not source authentication. Keep every shared network receiver loopback-bound;
otherwise another sender can spoof `service.name`. A Galileo queue failure can
also make the shared receiver reject after Splunk accepted, so retries can
duplicate Splunk spans. Production use requires an explicit risk acceptance.

Do not disable native hiding merely to make Galileo evaluators work: the same
raw prompt, response, system text, and possibly reasoning would flow to every
exporter on that pipeline.

## Mode B: client fan-out

Use for agent/workflow/tool/session context or selective content policy. Keep
the native Lemonade pipeline Splunk-only. Instrument the calling application
and send its OpenInference spans to a dedicated loopback receiver whose trace
pipeline exports to Galileo only by default. This gives Splunk one native LLM
record and Galileo one caller-side LLM record. Mirroring caller spans to native
exporters is opt-in because it duplicates LLM/cost records in Splunk and may
broaden content exposure.

OpenInference's OpenAI instrumentor can identify the LLM system/provider as
OpenAI because the caller uses an OpenAI-compatible API. The client pipeline
upserts `service.name` after inherited resource detection, then upserts
`llm.provider` and `gen_ai.provider.name` to `lemonade`, fills missing message
roles, deletes known content-bearing attributes, and redacts
status/exception text before export. For the pinned OpenInference semantic
conventions, deletion includes scalar message content, multimodal
`message.contents.<index>.message_content` text/image/data/encrypted/signature
values, legacy function arguments, indexed tool-call arguments/reasoning
signatures, tool results carried as message content, legacy prompts/choices,
prompt-template values, embedding text/vectors, retrieval/reranker content, and
arbitrary OpenInference metadata. It also drops `user.id` and arbitrary
`tag.tags`; neither is required for model/agent evaluation and both can contain
identifying data. It retains `session.id` because session grouping is a core
documented agent-observability semantic, so callers must use an opaque,
non-personal session identifier. It intentionally keeps roles, content types,
other structural IDs, function names, model names, providers, token/cost
fields, document scores, and reranker controls. Source instrumentation still
hides all inputs, outputs, invocation parameters, tools, and messages.

The exact defensive policy also removes current GenAI `input.messages`,
`output.messages`, `system_instructions`, tool definitions/descriptions,
retrieval documents/query text, standalone and nested audio/image/prompt URLs,
and their flattened forms from resource, span, and event attributes. It then
restores only constant `[REDACTED]` Agent/Tool input/output and tool-call
argument/result fields required for Galileo hierarchy. A final processor on
both Galileo pipelines deletes every case-insensitive `galileo.*` resource,
span, and event attribute, including project/Log stream/experiment and dataset
overrides, before export.

The caller's OpenAI-compatible base URL must be discovered from the live
Lemonade service. Common ports are examples, not defaults. Streaming clients
must drain the iterator and request usage fields when supported.

## Exact endpoint intake

Current Galileo documentation shows `/otel/v1/traces` for direct raw OTLP POST
and `/otel/traces` for several exporter/SDK integrations. Hosted deployments
serve both, while Enterprise routing can differ. Treat the user/tenant's exact
endpoint as intake rather than deriving a path from collector versus SDK. The
renderer uses `traces_endpoint` so the collector never appends `/v1/traces`.

Collector v0.156 follows redirects. Because the Galileo key is a custom header,
it can be copied to a redirect target. The managed exporter therefore uses the
v0.156 top-level `proxy_url` field to reach one dedicated loopback tinyproxy.
The proxy is deny-by-default and permits only the anchored, regex-escaped exact
host derived from the separately pinned expected origin. Its config and filter
exclude upstream/include/alternate ACL escape hatches and allow CONNECT only on
443. Splunk exporters do not receive a `proxy_url` and remain direct.

Production requires a protected target-bound identity record for the installed
tinyproxy binary, config, and filter. Startup compares canonical path, device,
inode, size, modification time, owner, mode, and SHA-256, then issues bounded
credential-free CONNECT probes: an unlisted reserved host must return 403 and
the exact Galileo host must establish with 2xx. A label, ambient `HTTPS_PROXY`,
or one-time endpoint probe is not a lasting control.

## Queue policy

The production renderer uses an explicit 256 MiB byte-sized persistent queue,
a bounded one-GiB fsync-backed `file_storage` database, and a 30-minute retry
window. Both the database and an explicit `compaction` subdirectory live under
the configured private queue directory; this avoids the Collector's independent
`/var/lib/otelcol` compaction default. The collector service identity needs the
whole tree to be private and writable. Memory queue mode is deterministic but
loses queued spans on restart and is rejected by production validation.

The queue directory is namespaced by a SHA-256 of the canonical endpoint and
exact ID/name selector pair. This prevents a target change from reopening old
records under new exporter headers. Changing targets requires draining the old
queue to zero or quarantining it with the old routing environment, then creating
a new empty fingerprint directory. Reusing, renaming, or copying the old queue
is prohibited.

Required raw OTLP headers are `Galileo-API-Key` plus one project and one Log
stream selector. Prefer `projectid`/`logstreamid`; names are supported for
operator-friendly bootstrap.

## Duplicate and stitch boundary

Caller spans can form a proper agent hierarchy internally, but the native
Lemonade span cannot join it because the server ignores W3C trace context. If
both sources reach one Galileo Log stream, one model call appears twice in
unrelated traces and may duplicate evaluation/cost accounting.

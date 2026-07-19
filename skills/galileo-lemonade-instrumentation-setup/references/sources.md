# Primary sources

Research baseline: 2026-07-11.

- Lemonade v10.10 telemetry guide:
  `https://github.com/lemonade-sdk/lemonade/blob/v10.10.0/docs/guide/telemetry.md`
- Lemonade v10.10 telemetry implementation:
  `https://github.com/lemonade-sdk/lemonade/blob/v10.10.0/src/cpp/server/telemetry.cpp`
- Lemonade OpenAI-compatible API:
  `https://github.com/lemonade-sdk/lemonade/blob/v10.10.0/docs/api/openai.md`
- Galileo OpenTelemetry/OpenInference guide:
  `https://docs.galileo.ai/sdk-api/third-party-integrations/opentelemetry-and-openinference`
- Galileo integration recommendations and raw OTLP requirements:
  `https://docs.galileo.ai/sdk-api/third-party-integrations/opentelemetry-and-openinference/integration-recommendations`
- Galileo OpenAI wrapper:
  `https://docs.galileo.ai/sdk-api/third-party-integrations/openai/openai`
- Galileo trace search API:
  `https://docs.galileo.ai/api-reference/trace/query-traces`
- Galileo Get Trace API and nested span schema:
  `https://docs.galileo.ai/api-reference/trace/get-trace`
- Galileo paginated project listing API:
  `https://docs.galileo.ai/api-reference/projects/get-projects-v2`
- Galileo project create/get/delete APIs:
  `https://docs.galileo.ai/api-reference/projects/create-project`,
  `https://docs.galileo.ai/api-reference/projects/get-project`, and
  `https://docs.galileo.ai/api-reference/projects/delete-project`
- Galileo paginated project Log stream listing API:
  `https://docs.galileo.ai/api-reference/log_stream/list-log-streams-paginated`
- Galileo Log stream create/get/delete APIs:
  `https://docs.galileo.ai/api-reference/log_stream/create-log-stream`,
  `https://docs.galileo.ai/api-reference/log_stream/get-log-stream`, and
  `https://docs.galileo.ai/api-reference/log_stream/delete-log-stream`
- Galileo current-user and API-key create/list/delete APIs:
  `https://docs.galileo.ai/api-reference/users/current-user`,
  `https://docs.galileo.ai/api-reference/api_keys/create-api-key`,
  `https://docs.galileo.ai/api-reference/api_keys/get-api-keys`, and
  `https://docs.galileo.ai/api-reference/api_keys/delete-api-key`
- Galileo distributed tracing:
  `https://docs.galileo.ai/sdk-api/logging/distributed-tracing-otel`
- OpenInference privacy configuration:
  `https://arize-ai.github.io/openinference/spec/configuration.html`
- Pinned OpenInference semantic conventions 0.1.30:
  `https://github.com/Arize-ai/openinference/blob/python-openinference-semantic-conventions-v0.1.30/python/openinference-semantic-conventions/src/openinference/semconv/trace/__init__.py`
- OTel Collector OTLP/HTTP exporter configuration:
  `https://pkg.go.dev/go.opentelemetry.io/collector/exporter/otlphttpexporter`
- OTel Collector v0.156 HTTP client configuration (`proxy_url`):
  `https://pkg.go.dev/go.opentelemetry.io/collector/config/confighttp@v0.156.0#ClientConfig`
- Tinyproxy filter, ACL, bind, and CONNECT-port directives:
  `https://tinyproxy.github.io/`
- Tinyproxy 1.11.1 startup, privilege-drop, logging, and safe PID-file source:
  `https://github.com/tinyproxy/tinyproxy/blob/1.11.1/src/main.c`,
  `https://github.com/tinyproxy/tinyproxy/blob/1.11.1/src/log.c`, and
  `https://github.com/tinyproxy/tinyproxy/blob/1.11.1/src/utils.c`
- systemd execution sandbox and runtime-directory semantics:
  `https://man7.org/linux/man-pages/man5/systemd.exec.5.html`
- systemd v255 private-device namespace implementation (including the local
  syslog socket link):
  `https://github.com/systemd/systemd/blob/v255/src/core/namespace.c`
- OTel Collector v0.156 file-storage defaults and compaction configuration:
  `https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/v0.156.0/extension/storage/filestorage/factory.go`
  and
  `https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/v0.156.0/extension/storage/filestorage/config.go`
- OTel Collector filter and transform processors:
  `https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/processor/filterprocessor`
  and
  `https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/processor/transformprocessor`
- Splunk Distribution of the OpenTelemetry Collector source:
  `https://github.com/signalfx/splunk-otel-collector`
- Splunk Distribution of the OpenTelemetry Collector v0.156.0 release:
  `https://github.com/signalfx/splunk-otel-collector/releases/tag/v0.156.0`

Source commits inspected:

- Lemonade v10.10.0: `8929d7063098e036af4cf5e80350ba7e69b68aff`
- Galileo Python SDK v2.4.0 research checkout:
  `6ccd06a3e077d66ef3606d82c73f81c773f2848d`

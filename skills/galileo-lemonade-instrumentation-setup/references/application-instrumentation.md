# Application-side instrumentation

## Preferred: OpenInference through the collector

Use `openinference-instrumentation-openai` with the normal OpenAI client, an
OTel SDK tracer provider, and an OTLP/HTTP exporter aimed at the dedicated
loopback receiver. This supports sync/async and OTel context propagation while
keeping the Galileo key in the collector.

Create an application-local environment and install the reviewed lock-style
example before adapting the client:

```bash
python3 -m venv .venv-lemonade-galileo
.venv-lemonade-galileo/bin/python -m pip install \
  -r skills/galileo-lemonade-instrumentation-setup/assets/lemonade_openinference_client.requirements.txt
```

Re-resolve and scan these pins under the application's normal dependency
process; do not install them into the system interpreter.

Before making a model request, set the discovered loopback Lemonade and caller
OTLP endpoints and run the dependency/transport/key-file preflight:

```bash
LEMONADE_BASE_URL=http://127.0.0.1:13305/api/v1 \
LEMONADE_DEPLOYMENT_ENVIRONMENT=production \
LEMONADE_MODEL=REPLACE_WITH_DISCOVERED_MODEL \
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://127.0.0.1:14318/v1/traces \
  .venv-lemonade-galileo/bin/python \
  skills/galileo-lemonade-instrumentation-setup/assets/lemonade_openinference_client.py \
  --check
```

Derive the Lemonade origin and model from the live service; the example port is
not a default. The preflight emits no key, endpoint, or response body. A real
canary emits only its trace ID, fixed Agent operation name, and UTC time bounds;
use those values for exact Splunk and Galileo backend readback.

Start with strict `TraceConfig` hide controls. OpenInference also supports:

- `OPENINFERENCE_HIDE_INPUTS` / `OPENINFERENCE_HIDE_OUTPUTS`
- input/output message and text hiding
- LLM invocation-parameter hiding
- tool-definition hiding

The packaged client sets every hide boolean available in the pinned
OpenInference `TraceConfig`—including images, embeddings, prompts, and
choices—and sets `enable_genai_semconv=False` explicitly. This prevents an
ambient `OPENINFERENCE_ENABLE_GENAI_SEMCONV=true` from creating a second set of
content-bearing GenAI attributes. Re-audit the signature when changing the pin.

Hidden values become redacted markers. Review the packaged client and pin
dependencies in the application's lock file after testing against its Python
runtime.

Strict message hiding can remove OpenInference message attributes that Galileo
documents for LLM spans. The rendered client pipeline keeps source hiding
strict, adds only non-content role/provider normalization, deletes known
content-bearing attributes defensively, and redacts status plus exception
message/stack fields before the Galileo exporter. It restores required
Agent/Tool input/output and tool-call argument/result attributes only as the
constant `[REDACTED]`.

## Galileo OpenAI wrapper

`from galileo.openai import openai` is the smallest synchronous change and can
target an OpenAI-compatible Lemonade base URL. Use a Galileo context/decorator
around multiple model calls and flush before process exit. Automatic
instrumentation does not cover `AsyncOpenAI`, and wrapper capture includes raw
input/output by default; require explicit content approval.

## OpenAI Agents

When the caller uses OpenAI Agents, Galileo's tracing processor can capture
agent events, generations, tools, and handoffs. Configure an `AsyncOpenAI`
client with Lemonade's discovered base URL and an OpenAI Chat Completions model;
local providers often do not implement the full Responses surface.

## Manual Galileo logging

Use Galileo `@log` or `GalileoLogger` for custom frameworks and explicit
workflow/agent/LLM/tool/retriever spans. Manual APIs are also appropriate when
raw and redacted fields must be controlled independently. Redacted Galileo
attributes do not imply the original was omitted; exclude sensitive source
content before logging when strict privacy is required.

## Package baseline researched 2026-07-11

- `galileo` 2.4.0, Python >=3.10,<3.15
- `openinference-instrumentation-openai` 0.1.52
- OpenInference base instrumentation 0.1.54
- Galileo OpenAI Agents instrumentor 1.6.1

Treat these as research pins, not an instruction to install unreviewed latest
packages. Resolve and lock a tested set for the target application.

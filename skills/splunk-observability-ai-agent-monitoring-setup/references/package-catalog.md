# Package Catalog Reference

The renderer has a checked-in package snapshot and can refresh live PyPI metadata into rendered output with `--refresh-package-catalog`.

## First-Class Splunk AI Agent Monitoring Packages

| Package | Purpose | Python floor snapshot |
|---------|---------|-----------------------|
| `splunk-opentelemetry` | Splunk Distribution of OpenTelemetry Python | `>=3.9` |
| `splunk-otel-util-genai` | GenAI data model, handlers, emitters | `>=3.9` |
| `splunk-otel-genai-emitters-splunk` | Splunk evaluation aggregation / emitter | `>=3.9` |
| `splunk-otel-genai-evals-deepeval` | DeepEval instrumentation-side evaluations | `>=3.9` |
| `splunk-otel-instrumentation-crewai` | CrewAI orchestration instrumentation | `>=3.9` |
| `splunk-otel-instrumentation-langchain` | LangChain and LangGraph instrumentation | `>=3.9` |
| `splunk-otel-instrumentation-llamaindex` | LlamaIndex instrumentation | `>=3.9` |
| `splunk-otel-instrumentation-openai` | OpenAI instrumentation | `>=3.9` |
| `splunk-otel-instrumentation-openai-agents` | OpenAI Agents instrumentation | `>=3.9` |
| `splunk-otel-instrumentation-fastmcp` | FastMCP client/server instrumentation | `>=3.10` |
| `splunk-otel-instrumentation-weaviate` | Weaviate instrumentation | `>=3.9` |
| `splunk-otel-instrumentation-aidefense` | Cisco AI Defense instrumentation | `>=3.9` |
| `splunk-otel-util-genai-translator-langsmith` | LangSmith translator | `>=3.9` |
| `splunk-otel-util-genai-translator-openlit` | OpenLit translator | `>=3.9` |
| `splunk-otel-util-genai-translator-traceloop` | Traceloop translator | `>=3.9` |

## Provider Adjunct Packages

Use these only as adjunct provider instrumentation when selected and PyPI-resolvable:

- `opentelemetry-instrumentation-openai-v2`
- `opentelemetry-instrumentation-anthropic`
- `opentelemetry-instrumentation-vertexai`
- `opentelemetry-instrumentation-bedrock`
- `opentelemetry-instrumentation-cohere`
- `opentelemetry-instrumentation-mistralai`
- `opentelemetry-instrumentation-google-genai`

## Blocked Names

Reject these names because they were not present on PyPI during review:

- `splunk-otel-instrumentation-openai-v2`
- `splunk-otel-instrumentation-vertexai`
- `opentelemetry-instrumentation-litellm`

## Caveats To Preserve

- Splunk zero-code docs state Python 3.10+ for AI Agent Monitoring setup; package metadata varies by package.
- OpenAI evaluations require `OTEL_INSTRUMENTATION_GENAI_EVALS_SEPARATE_PROCESS=true`.
- LangChain and LangGraph can duplicate evaluation results when multiple instrumentation paths are enabled.
- LangGraph `1.1.7` is excluded due to a callback bug in upstream notes.
- CrewAI async is not supported in the current instrumentation notes.
- FastMCP over stdio must not write logs to stdout.

# Coverage Reference

Reviewed on 2026-05-05 against current Splunk Observability Cloud AI Agent Monitoring and AI Infrastructure Monitoring documentation.

## AI Agent Monitoring

| Area | Status | Owner |
|------|--------|-------|
| Collector deployment | `delegated_apply` | `splunk-observability-otel-collector-setup` |
| Agent page histogram readiness | `validate` | this skill |
| Zero-code Python instrumentation | `render` | this skill |
| Code-based instrumentation examples | `render` | this skill |
| Third-party translators | `render` | this skill |
| Instrumentation-side evaluations | `render` plus `delegated_apply` for HEC/LOC prerequisites | this skill plus HEC/LOC child skills |
| Log Observer Connect platform-side user/role/workload | `delegated_apply` | `splunk-observability-cloud-integration-setup` |
| Log Observer Connect wizard and AI Agent Monitoring connection/index selection | `deeplink` | Observability UI |
| Dashboards | `delegated_apply` for classic custom dashboards; native pages are `deeplink` | `splunk-observability-dashboard-builder` |
| Detectors | `delegated_apply` | `splunk-observability-native-ops` |

## AI Infrastructure Monitoring Products

Every product in the current Splunk AI Infrastructure Monitoring navigation must appear in `coverage-report.json`:

- agentgateway LLM proxy
- Amazon Bedrock
- Amazon Bedrock AgentCore Gateway
- Azure OpenAI
- Cisco AI PODs
- Kong AI Gateway Proxy
- ChromaDB
- GCP VertexAI
- KServe
- Kubeflow Pipelines
- LiteLLM AI Gateway / LiteLLM Proxy
- Milvus
- NVIDIA GPU
- NVIDIA NIM
- OpenAI
- Pinecone
- Ray
- Seldon Core
- TensorFlow Serving
- Weaviate

Use `delegated_apply` only where an existing repo skill owns the live workflow. Cisco AI PODs and NVIDIA GPU have dedicated repo skills. Other products render collector/dashboard/detector handoffs unless a dedicated skill or documented public API is added.

## Source URLs

- https://help.splunk.com/en/splunk-observability-cloud/observability-for-ai/splunk-ai-agent-monitoring/set-up-ai-agent-monitoring
- https://help.splunk.com/en/splunk-observability-cloud/observability-for-ai/splunk-ai-agent-monitoring/set-up-ai-agent-monitoring/zero-code-instrumentation
- https://help.splunk.com/en/splunk-observability-cloud/observability-for-ai/splunk-ai-agent-monitoring/set-up-ai-agent-monitoring/code-based-instrumentation
- https://help.splunk.com/en/splunk-observability-cloud/observability-for-ai/splunk-ai-agent-monitoring/set-up-ai-agent-monitoring/configure-the-python-agent
- https://help.splunk.com/en/splunk-observability-cloud/observability-for-ai/splunk-ai-agent-monitoring/set-up-ai-agent-monitoring/translate-data-from-third-party-instrumentation-libraries
- https://help.splunk.com/en/splunk-observability-cloud/observability-for-ai/splunk-ai-infrastructure-monitoring
- https://github.com/signalfx/splunk-otel-python-contrib
- https://github.com/open-telemetry/semantic-conventions-genai

#!/usr/bin/env python3
"""Render Splunk Observability AI Agent Monitoring setup assets."""

from __future__ import annotations

import argparse
import json
import re
import stat
import sys
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - JSON specs work without PyYAML
    yaml = None


REVIEWED_AT = "2026-05-05"
API_VERSION = "splunk-observability-ai-agent-monitoring-setup/v1"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
ALLOWED_STATUSES = {
    "delegated_apply",
    "render",
    "validate",
    "deeplink",
    "handoff",
    "not_applicable",
}

SOURCE_URLS = {
    "aam_setup": "https://help.splunk.com/en/splunk-observability-cloud/observability-for-ai/splunk-ai-agent-monitoring/set-up-ai-agent-monitoring",
    "zero_code": "https://help.splunk.com/en/splunk-observability-cloud/observability-for-ai/splunk-ai-agent-monitoring/set-up-ai-agent-monitoring/zero-code-instrumentation",
    "code_based": "https://help.splunk.com/en/splunk-observability-cloud/observability-for-ai/splunk-ai-agent-monitoring/set-up-ai-agent-monitoring/code-based-instrumentation",
    "python_agent": "https://help.splunk.com/en/splunk-observability-cloud/observability-for-ai/splunk-ai-agent-monitoring/set-up-ai-agent-monitoring/configure-the-python-agent",
    "translators": "https://help.splunk.com/en/splunk-observability-cloud/observability-for-ai/splunk-ai-agent-monitoring/set-up-ai-agent-monitoring/translate-data-from-third-party-instrumentation-libraries",
    "ai_infra": "https://help.splunk.com/en/splunk-observability-cloud/observability-for-ai/splunk-ai-infrastructure-monitoring",
    "splunk_genai_contrib": "https://github.com/signalfx/splunk-otel-python-contrib",
    "otel_genai_semconv": "https://github.com/open-telemetry/semantic-conventions-genai",
}

PACKAGE_CATALOG: list[dict[str, str]] = [
    {"name": "splunk-opentelemetry", "version": "2.10.1", "requires_python": ">=3.9", "kind": "first_class", "purpose": "Splunk Distribution of OpenTelemetry Python"},
    {"name": "splunk-otel-util-genai", "version": "0.1.11", "requires_python": ">=3.9", "kind": "first_class", "purpose": "GenAI utility data model and emitters"},
    {"name": "splunk-otel-genai-emitters-splunk", "version": "0.1.8", "requires_python": ">=3.9", "kind": "first_class", "purpose": "Splunk evaluation aggregation emitter"},
    {"name": "splunk-otel-genai-evals-deepeval", "version": "0.1.14", "requires_python": ">=3.9", "kind": "first_class", "purpose": "DeepEval instrumentation-side evaluations"},
    {"name": "splunk-otel-instrumentation-crewai", "version": "0.1.3", "requires_python": ">=3.9", "kind": "first_class", "purpose": "CrewAI instrumentation"},
    {"name": "splunk-otel-instrumentation-langchain", "version": "0.1.9", "requires_python": ">=3.9", "kind": "first_class", "purpose": "LangChain and LangGraph instrumentation"},
    {"name": "splunk-otel-instrumentation-llamaindex", "version": "0.1.1", "requires_python": ">=3.9", "kind": "first_class", "purpose": "LlamaIndex instrumentation"},
    {"name": "splunk-otel-instrumentation-openai", "version": "0.1.0", "requires_python": ">=3.9", "kind": "first_class", "purpose": "OpenAI instrumentation"},
    {"name": "splunk-otel-instrumentation-openai-agents", "version": "0.1.3", "requires_python": ">=3.9", "kind": "first_class", "purpose": "OpenAI Agents instrumentation"},
    {"name": "splunk-otel-instrumentation-fastmcp", "version": "0.1.1", "requires_python": ">=3.10", "kind": "first_class", "purpose": "FastMCP client/server instrumentation"},
    {"name": "splunk-otel-instrumentation-weaviate", "version": "0.1.0", "requires_python": ">=3.9", "kind": "first_class", "purpose": "Weaviate instrumentation"},
    {"name": "splunk-otel-instrumentation-aidefense", "version": "0.2.1", "requires_python": ">=3.9", "kind": "first_class", "purpose": "Cisco AI Defense instrumentation"},
    {"name": "splunk-otel-util-genai-translator-langsmith", "version": "0.1.1", "requires_python": ">=3.9", "kind": "translator", "purpose": "LangSmith translator"},
    {"name": "splunk-otel-util-genai-translator-openlit", "version": "0.1.2", "requires_python": ">=3.9", "kind": "translator", "purpose": "OpenLit translator"},
    {"name": "splunk-otel-util-genai-translator-traceloop", "version": "0.1.8", "requires_python": ">=3.9", "kind": "translator", "purpose": "Traceloop translator"},
    {"name": "opentelemetry-instrumentation-openai-v2", "version": "2.4b0", "requires_python": ">=3.10", "kind": "provider_adjunct", "purpose": "OpenAI/Azure OpenAI provider instrumentation adjunct"},
    {"name": "opentelemetry-instrumentation-anthropic", "version": "0.60.0", "requires_python": ">=3.10,<4", "kind": "provider_adjunct", "purpose": "Anthropic provider instrumentation adjunct"},
    {"name": "opentelemetry-instrumentation-vertexai", "version": "0.60.0", "requires_python": ">=3.10,<4", "kind": "provider_adjunct", "purpose": "Vertex AI provider instrumentation adjunct"},
    {"name": "opentelemetry-instrumentation-bedrock", "version": "0.60.0", "requires_python": ">=3.10,<4", "kind": "provider_adjunct", "purpose": "Amazon Bedrock provider instrumentation adjunct"},
    {"name": "opentelemetry-instrumentation-cohere", "version": "0.60.0", "requires_python": ">=3.10,<4", "kind": "provider_adjunct", "purpose": "Cohere provider instrumentation adjunct"},
    {"name": "opentelemetry-instrumentation-mistralai", "version": "0.60.0", "requires_python": ">=3.10,<4", "kind": "provider_adjunct", "purpose": "Mistral AI provider instrumentation adjunct"},
    {"name": "opentelemetry-instrumentation-google-genai", "version": "0.7b0", "requires_python": ">=3.9", "kind": "provider_adjunct", "purpose": "Google GenAI provider instrumentation adjunct"},
]

PACKAGE_BY_NAME = {item["name"]: item for item in PACKAGE_CATALOG}
BLOCKED_PACKAGES = {
    "splunk-otel-instrumentation-openai-v2": "Use splunk-otel-instrumentation-openai or opentelemetry-instrumentation-openai-v2 depending on the scenario.",
    "splunk-otel-instrumentation-vertexai": "Use opentelemetry-instrumentation-vertexai; no Splunk-prefixed VertexAI package was present on PyPI during review.",
    "opentelemetry-instrumentation-litellm": "No PyPI package was present during review; treat LiteLLM as AI Infrastructure Monitoring/proxy coverage.",
}

FRAMEWORKS: dict[str, dict[str, Any]] = {
    "crewai": {
        "label": "CrewAI",
        "packages": ["splunk-otel-instrumentation-crewai"],
        "notes": "Captures crews, tasks, agents, and tools; add provider instrumentation for LLM and embedding details. Async is not supported.",
    },
    "langchain": {
        "label": "LangChain / LangGraph",
        "packages": ["splunk-otel-instrumentation-langchain"],
        "notes": "Avoid duplicate instrumentation; set metadata for agent/workflow naming. LangGraph 1.1.7 is excluded upstream.",
    },
    "llamaindex": {
        "label": "LlamaIndex",
        "packages": ["splunk-otel-instrumentation-llamaindex"],
        "notes": "Captures LLM, embedding, and retrieval operations.",
    },
    "openai": {
        "label": "OpenAI",
        "packages": ["splunk-otel-instrumentation-openai"],
        "notes": "OpenAI evaluations require separate-process mode.",
    },
    "openai-agents": {
        "label": "OpenAI Agents",
        "packages": ["splunk-otel-instrumentation-openai-agents"],
        "notes": "Requires openai-agents-python 0.3.3 or newer.",
    },
    "fastmcp": {
        "label": "FastMCP",
        "packages": ["splunk-otel-instrumentation-fastmcp"],
        "notes": "For stdio MCP, do not write logs to stdout; use separate service names for client/server.",
    },
    "weaviate": {
        "label": "Weaviate",
        "packages": ["splunk-otel-instrumentation-weaviate"],
        "notes": "First-class AAM package and AI Infrastructure Monitoring product.",
    },
    "aidefense": {
        "label": "Cisco AI Defense",
        "packages": ["splunk-otel-instrumentation-aidefense"],
        "notes": "Supports SDK and gateway modes; secrets must be supplied through app runtime secret stores.",
    },
}

TRANSLATORS = {
    "langsmith": "splunk-otel-util-genai-translator-langsmith",
    "openlit": "splunk-otel-util-genai-translator-openlit",
    "traceloop": "splunk-otel-util-genai-translator-traceloop",
}

PROVIDER_ADJUNCTS = {
    "openai-v2": "opentelemetry-instrumentation-openai-v2",
    "anthropic": "opentelemetry-instrumentation-anthropic",
    "vertexai": "opentelemetry-instrumentation-vertexai",
    "bedrock": "opentelemetry-instrumentation-bedrock",
    "cohere": "opentelemetry-instrumentation-cohere",
    "mistralai": "opentelemetry-instrumentation-mistralai",
    "google-genai": "opentelemetry-instrumentation-google-genai",
}

WORKLOAD_KINDS = {
    "deployment": {"api_kind": "Deployment", "resource": "deployment"},
    "statefulset": {"api_kind": "StatefulSet", "resource": "statefulset"},
    "daemonset": {"api_kind": "DaemonSet", "resource": "daemonset"},
}

AI_INFRA_PRODUCTS: dict[str, dict[str, str]] = {
    "agentgateway_llm_proxy": {"label": "agentgateway LLM proxy", "status": "render", "owner": "this skill", "notes": "Render collector/dashboard/detector handoffs for proxy metrics."},
    "amazon_bedrock": {"label": "Amazon Bedrock", "status": "render", "owner": "this skill + AWS integration handoff", "notes": "Render provider adjunct and AWS/collector handoffs."},
    "amazon_bedrock_agentcore_gateway": {"label": "Amazon Bedrock AgentCore Gateway", "status": "render", "owner": "this skill + AWS integration handoff", "notes": "Render AWS/collector handoffs; no dedicated repo skill yet."},
    "azure_openai": {"label": "Azure OpenAI", "status": "render", "owner": "this skill", "notes": "Render provider adjunct package and collector handoffs."},
    "cisco_ai_pods": {"label": "Cisco AI PODs", "status": "delegated_apply", "owner": "splunk-observability-cisco-ai-pod-integration", "notes": "Dedicated umbrella skill owns apply."},
    "kong_ai_gateway_proxy": {"label": "Kong AI Gateway Proxy", "status": "render", "owner": "this skill", "notes": "Render collector/dashboard/detector handoffs."},
    "chromadb": {"label": "ChromaDB", "status": "render", "owner": "this skill", "notes": "Render vector database monitoring handoffs."},
    "gcp_vertexai": {"label": "GCP VertexAI", "status": "render", "owner": "this skill", "notes": "Render provider adjunct and collector handoffs."},
    "kserve": {"label": "KServe", "status": "render", "owner": "this skill", "notes": "Render model-serving metric handoffs with histogram validation."},
    "kubeflow_pipelines": {"label": "Kubeflow Pipelines", "status": "render", "owner": "this skill", "notes": "Render pipeline metrics handoffs."},
    "litellm_proxy": {"label": "LiteLLM AI Gateway / LiteLLM Proxy", "status": "render", "owner": "this skill", "notes": "Treat as proxy infrastructure; do not use nonexistent litellm instrumentation package."},
    "milvus": {"label": "Milvus", "status": "render", "owner": "this skill", "notes": "Render vector database monitoring handoffs."},
    "nvidia_gpu": {"label": "NVIDIA GPU", "status": "delegated_apply", "owner": "splunk-observability-nvidia-gpu-integration", "notes": "Dedicated GPU skill owns collector overlay apply."},
    "nvidia_nim": {"label": "NVIDIA NIM", "status": "render", "owner": "this skill or Cisco AI POD umbrella", "notes": "Render NIM scrape handoff; Cisco AI POD skill owns AI Pod composite apply."},
    "openai": {"label": "OpenAI", "status": "render", "owner": "this skill", "notes": "Render OpenAI package/runtime and dashboard handoffs."},
    "pinecone": {"label": "Pinecone", "status": "render", "owner": "this skill", "notes": "Render vector database monitoring handoffs."},
    "ray": {"label": "Ray", "status": "render", "owner": "this skill", "notes": "Render distributed runtime monitoring handoffs."},
    "seldon_core": {"label": "Seldon Core", "status": "render", "owner": "this skill", "notes": "Render model-serving metric handoffs."},
    "tensorflow_serving": {"label": "TensorFlow Serving", "status": "render", "owner": "this skill", "notes": "Render model-serving metric handoffs."},
    "weaviate": {"label": "Weaviate", "status": "render", "owner": "this skill", "notes": "Render AAM package plus AI infrastructure handoffs."},
}

DEFAULT_SPEC: dict[str, Any] = {
    "api_version": API_VERSION,
    "realm": "us0",
    "deployment": {
        "collector_mode": "kubernetes",
        "cluster_name": "ai-prod-cluster",
        "namespace": "splunk-otel",
        "environment": "prod",
        "send_otlp_histograms": True,
        "workload_kind": "deployment",
        "workload_namespace": "default",
        "workload_name": "ai-agent-service",
        "container_name": "app",
    },
    "ai_agent_monitoring": {
        "service_name": "ai-agent-service",
        "instrumentation_mode": "zero-code",
        "python_version": "3.10",
        "frameworks": ["langchain", "openai"],
        "translators": [],
        "provider_adjuncts": [],
        "additional_packages": [],
        "enable_content_capture": False,
        "accept_content_capture": False,
        "enable_evaluations": False,
        "accept_evaluation_cost": False,
        "evaluation_provider": "openai",
        "evals_separate_process": True,
        "evals_sample_rate": 0.25,
        "evals_rate_limit_rps": 1,
        "hec": {
            "enabled": True,
            "platform": "enterprise",
            "index": "ai_events",
            "token_name": "ai_agent_monitoring_hec",
            "source": "otel",
            "sourcetype": "otel",
        },
        "log_observer_connect": {
            "enabled": True,
            "target": "enterprise",
            "connection_name": "splunk-platform-loc",
            "index": "ai_events",
        },
    },
    "ai_infrastructure": {"include_all_supported": True, "products": []},
    "dashboards": {"enabled": True, "group_name": "AI Agent Monitoring"},
    "detectors": {"enabled": True},
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = json.loads(json.dumps(base))
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def parse_scalar(value: str) -> Any:
    lower = value.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    return value


def list_from_csv(value: str | None) -> list[str] | None:
    if value is None:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


def as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


def normalize_key(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_").replace("/", "_")


def parse_version(version: str) -> tuple[int, int]:
    match = re.match(r"^\s*(\d+)(?:\.(\d+))?", version)
    if not match:
        return (0, 0)
    return (int(match.group(1)), int(match.group(2) or 0))


def minimum_python(requirement: str) -> tuple[int, int] | None:
    matches = re.findall(r">=\s*(\d+)\.(\d+)", requirement or "")
    if not matches:
        return None
    return max((int(major), int(minor)) for major, minor in matches)


def load_spec(path: Path | None) -> dict[str, Any]:
    if path is None:
        return json.loads(json.dumps(DEFAULT_SPEC))
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return json.loads(json.dumps(DEFAULT_SPEC))
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        if yaml is None:
            raise SystemExit(f"YAML spec requires PyYAML: {path}")
        loaded = yaml.safe_load(text)
    if not isinstance(loaded, dict):
        raise SystemExit(f"Spec must be a mapping: {path}")
    return deep_merge(DEFAULT_SPEC, loaded)


def apply_overrides(spec: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    spec = json.loads(json.dumps(spec))
    if args.realm:
        spec["realm"] = args.realm
    if args.collector_mode:
        spec.setdefault("deployment", {})["collector_mode"] = args.collector_mode
    if args.cluster_name:
        spec.setdefault("deployment", {})["cluster_name"] = args.cluster_name
    if args.workload_kind:
        spec.setdefault("deployment", {})["workload_kind"] = args.workload_kind
    if args.workload_namespace:
        spec.setdefault("deployment", {})["workload_namespace"] = args.workload_namespace
    if args.workload_name:
        spec.setdefault("deployment", {})["workload_name"] = args.workload_name
    if args.container_name:
        spec.setdefault("deployment", {})["container_name"] = args.container_name
    if args.service_name:
        spec.setdefault("ai_agent_monitoring", {})["service_name"] = args.service_name
    if args.python_version:
        spec.setdefault("ai_agent_monitoring", {})["python_version"] = args.python_version
    if args.frameworks is not None:
        spec.setdefault("ai_agent_monitoring", {})["frameworks"] = list_from_csv(args.frameworks)
    if args.translators is not None:
        spec.setdefault("ai_agent_monitoring", {})["translators"] = list_from_csv(args.translators)
    if args.provider_adjuncts is not None:
        spec.setdefault("ai_agent_monitoring", {})["provider_adjuncts"] = list_from_csv(args.provider_adjuncts)
    if args.ai_infra_products is not None:
        spec.setdefault("ai_infrastructure", {})["products"] = list_from_csv(args.ai_infra_products)
        spec.setdefault("ai_infrastructure", {})["include_all_supported"] = False
    if args.enable_content_capture:
        spec.setdefault("ai_agent_monitoring", {})["enable_content_capture"] = True
    if args.accept_content_capture:
        spec.setdefault("ai_agent_monitoring", {})["accept_content_capture"] = True
    if args.enable_evaluations:
        spec.setdefault("ai_agent_monitoring", {})["enable_evaluations"] = True
    if args.accept_evaluation_cost:
        spec.setdefault("ai_agent_monitoring", {})["accept_evaluation_cost"] = True
    if args.send_otlp_histograms is not None:
        spec.setdefault("deployment", {})["send_otlp_histograms"] = parse_scalar(args.send_otlp_histograms)
    if args.hec_index:
        spec.setdefault("ai_agent_monitoring", {}).setdefault("hec", {})["index"] = args.hec_index
        spec.setdefault("ai_agent_monitoring", {}).setdefault("log_observer_connect", {})["index"] = args.hec_index
    if args.hec_platform:
        spec.setdefault("ai_agent_monitoring", {}).setdefault("hec", {})["platform"] = args.hec_platform
    return spec


def selected_packages(spec: dict[str, Any]) -> list[str]:
    aam = spec["ai_agent_monitoring"]
    packages = ["splunk-opentelemetry", "splunk-otel-util-genai"]
    for framework in as_list(aam.get("frameworks")):
        info = FRAMEWORKS.get(framework.strip().lower().replace("_", "-")) or FRAMEWORKS.get(framework.strip().lower())
        if info:
            packages.extend(info["packages"])
    for translator in as_list(aam.get("translators")):
        package = TRANSLATORS.get(translator.strip().lower())
        if package:
            packages.append(package)
    for adjunct in as_list(aam.get("provider_adjuncts")):
        package = PROVIDER_ADJUNCTS.get(adjunct.strip().lower())
        if package:
            packages.append(package)
    if aam.get("enable_evaluations"):
        packages.extend(["splunk-otel-genai-evals-deepeval", "splunk-otel-genai-emitters-splunk"])
    packages.extend(as_list(aam.get("additional_packages")))
    seen = set()
    ordered = []
    for package in packages:
        if package not in seen:
            ordered.append(package)
            seen.add(package)
    return ordered


def validate_spec(spec: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    aam = spec.get("ai_agent_monitoring", {})
    deployment = spec.get("deployment", {})

    if spec.get("api_version") != API_VERSION:
        warnings.append(f"Spec api_version is {spec.get('api_version')!r}; renderer expects {API_VERSION}.")

    collector_mode = str(deployment.get("collector_mode", "")).lower()
    if collector_mode not in {"kubernetes", "linux"}:
        errors.append("deployment.collector_mode must be kubernetes or linux.")

    workload_kind = str(deployment.get("workload_kind", "deployment")).lower()
    if workload_kind not in WORKLOAD_KINDS:
        errors.append("deployment.workload_kind must be deployment, statefulset, or daemonset.")

    for field in ("workload_namespace", "workload_name", "container_name"):
        if not str(deployment.get(field, "")).strip():
            errors.append(f"deployment.{field} is required for the Kubernetes runtime handoff patch.")

    if deployment.get("send_otlp_histograms") is not True:
        errors.append("deployment.send_otlp_histograms must be true; AI Agent Monitoring Agents page requires histogram metrics.")

    py_version = str(aam.get("python_version", ""))
    runtime_version = parse_version(py_version)
    if runtime_version < (3, 10) and str(aam.get("instrumentation_mode")) == "zero-code":
        errors.append("Splunk AI Agent Monitoring zero-code documentation requires Python 3.10+.")

    for framework in as_list(aam.get("frameworks")):
        key = framework.strip().lower().replace("_", "-")
        if key not in FRAMEWORKS:
            errors.append(f"Unsupported framework: {framework}. Supported: {', '.join(sorted(FRAMEWORKS))}.")

    for translator in as_list(aam.get("translators")):
        if translator.strip().lower() not in TRANSLATORS:
            errors.append(f"Unsupported translator: {translator}. Supported: {', '.join(sorted(TRANSLATORS))}.")

    for adjunct in as_list(aam.get("provider_adjuncts")):
        if adjunct.strip().lower() not in PROVIDER_ADJUNCTS:
            errors.append(f"Unsupported provider adjunct: {adjunct}. Supported: {', '.join(sorted(PROVIDER_ADJUNCTS))}.")

    if aam.get("enable_content_capture") and not aam.get("accept_content_capture"):
        errors.append("Content capture requires accept_content_capture=true or --accept-content-capture.")

    if aam.get("enable_evaluations") and not aam.get("accept_evaluation_cost"):
        errors.append("Instrumentation-side evaluations require accept_evaluation_cost=true or --accept-evaluation-cost.")

    if aam.get("enable_evaluations") and str(aam.get("evaluation_provider", "")).lower() == "openai" and not aam.get("evals_separate_process"):
        errors.append("OpenAI instrumentation-side evaluations require evals_separate_process=true.")

    products = selected_ai_infra_products(spec)
    for product in products:
        if product not in AI_INFRA_PRODUCTS:
            errors.append(f"Unsupported AI Infrastructure Monitoring product: {product}.")

    for package in selected_packages(spec):
        if package in BLOCKED_PACKAGES:
            errors.append(f"Unsupported package {package}: {BLOCKED_PACKAGES[package]}")
            continue
        info = PACKAGE_BY_NAME.get(package)
        if info is None:
            errors.append(f"Package {package} is not in the verified package catalog; run --refresh-package-catalog before adding it.")
            continue
        floor = minimum_python(info.get("requires_python", ""))
        if floor and runtime_version < floor:
            errors.append(f"Package {package} requires Python {info['requires_python']}; spec python_version is {py_version}.")

    if "langchain" in as_list(aam.get("frameworks")) and "openai" in as_list(aam.get("frameworks")):
        warnings.append("LangChain can suppress or duplicate provider telemetry depending on instrumentation order; review duplicate-evaluation guidance.")
    if "crewai" in as_list(aam.get("frameworks")):
        warnings.append("CrewAI instrumentation does not directly instrument LLM/embedding calls; add provider adjunct packages as needed.")
    if "fastmcp" in as_list(aam.get("frameworks")):
        warnings.append("FastMCP stdio servers must not write application logs to stdout.")

    return errors, warnings


def selected_ai_infra_products(spec: dict[str, Any]) -> list[str]:
    ai_infra = spec.get("ai_infrastructure", {})
    if ai_infra.get("include_all_supported"):
        return list(AI_INFRA_PRODUCTS)
    products = []
    for item in as_list(ai_infra.get("products")):
        key = normalize_key(item)
        aliases = {
            "agentgateway": "agentgateway_llm_proxy",
            "bedrock": "amazon_bedrock",
            "bedrock_agentcore": "amazon_bedrock_agentcore_gateway",
            "azure_openai": "azure_openai",
            "cisco_ai_pod": "cisco_ai_pods",
            "cisco_ai_pods": "cisco_ai_pods",
            "kong": "kong_ai_gateway_proxy",
            "litellm": "litellm_proxy",
            "gpu": "nvidia_gpu",
            "nim": "nvidia_nim",
            "tensorflow": "tensorflow_serving",
            "vertexai": "gcp_vertexai",
            "gcp_vertex_ai": "gcp_vertexai",
        }
        products.append(aliases.get(key, key))
    return products


def coverage_entry(area: str, key: str, title: str, status: str, owner: str, source_url: str, notes: str) -> dict[str, str]:
    if status not in ALLOWED_STATUSES:
        raise ValueError(f"Invalid coverage status for {key}: {status}")
    return {
        "area": area,
        "key": key,
        "title": title,
        "status": status,
        "owner": owner,
        "source_url": source_url,
        "notes": notes,
    }


def build_coverage(spec: dict[str, Any]) -> list[dict[str, str]]:
    aam = spec["ai_agent_monitoring"]
    deployment = spec["deployment"]
    hec_enabled = bool(aam.get("hec", {}).get("enabled"))
    loc_enabled = bool(aam.get("log_observer_connect", {}).get("enabled"))
    dashboards_enabled = bool(spec.get("dashboards", {}).get("enabled"))
    detectors_enabled = bool(spec.get("detectors", {}).get("enabled"))

    coverage = [
        coverage_entry("AI Agent Monitoring", "aam.collector", "Collector deployment", "delegated_apply", "splunk-observability-otel-collector-setup", SOURCE_URLS["aam_setup"], f"Delegates to --apply-{deployment.get('collector_mode') if deployment.get('collector_mode') == 'linux' else 'k8s'}."),
        coverage_entry("AI Agent Monitoring", "aam.histograms", "Agent page histogram readiness", "validate", "this skill", SOURCE_URLS["aam_setup"], "Requires signalfx.send_otlp_histograms: true."),
        coverage_entry("AI Agent Monitoring", "aam.zero_code", "Zero-code instrumentation", "render", "this skill", SOURCE_URLS["zero_code"], "Renders runtime package and env guidance."),
        coverage_entry("AI Agent Monitoring", "aam.code_based", "Code-based instrumentation", "render", "this skill", SOURCE_URLS["code_based"], "Renders manual GenAI handler references and package set."),
        coverage_entry("AI Agent Monitoring", "aam.translators", "Third-party translators", "render", "this skill", SOURCE_URLS["translators"], "Renders LangSmith/OpenLit/Traceloop translator packages when selected."),
        coverage_entry("AI Agent Monitoring", "aam.content_capture", "Prompt and response content capture", "render" if aam.get("enable_content_capture") else "not_applicable", "this skill", SOURCE_URLS["python_agent"], "Off by default; requires explicit acceptance."),
        coverage_entry("AI Agent Monitoring", "aam.evaluations", "Instrumentation-side evaluations", "render" if aam.get("enable_evaluations") else "not_applicable", "this skill", SOURCE_URLS["python_agent"], "DeepEval and Splunk emitter packages; gated for content and cost risk."),
        coverage_entry("AI Agent Monitoring", "aam.hec", "Splunk Platform HEC prerequisites", "delegated_apply" if hec_enabled else "not_applicable", "splunk-hec-service-setup", SOURCE_URLS["aam_setup"], "Creates HEC/indexing assets for log/event correlation."),
        coverage_entry("AI Agent Monitoring", "aam.loc_platform", "Log Observer Connect platform prerequisites", "delegated_apply" if loc_enabled else "not_applicable", "splunk-observability-cloud-integration-setup", SOURCE_URLS["aam_setup"], "Delegates user/role/workload pieces; allowlist and TLS may remain handoff."),
        coverage_entry("AI Agent Monitoring", "aam.loc_wizard", "Log Observer Connect wizard", "deeplink" if loc_enabled else "not_applicable", "Observability UI", SOURCE_URLS["aam_setup"], "UI workflow; do not mark as API apply."),
        coverage_entry("AI Agent Monitoring", "aam.connection_index", "AI Agent Monitoring connection/index selection", "deeplink" if loc_enabled else "not_applicable", "Observability UI", SOURCE_URLS["aam_setup"], "Settings > AI Agent Monitoring > Connection selection / Index selection."),
        coverage_entry("AI Agent Monitoring", "aam.dashboards", "Custom dashboards", "delegated_apply" if dashboards_enabled else "not_applicable", "splunk-observability-dashboard-builder", SOURCE_URLS["ai_infra"], "Classic API custom dashboards; native pages are deeplink/handoff."),
        coverage_entry("AI Agent Monitoring", "aam.detectors", "Detectors and alerting", "delegated_apply" if detectors_enabled else "not_applicable", "splunk-observability-native-ops", SOURCE_URLS["ai_infra"], "Detector API handoff."),
    ]

    for product in selected_ai_infra_products(spec):
        info = AI_INFRA_PRODUCTS.get(product)
        if info is None:
            coverage.append(coverage_entry("AI Infrastructure Monitoring", f"ai_infra.{product}", product, "handoff", "operator", SOURCE_URLS["ai_infra"], "Unsupported product requested; validation will fail."))
            continue
        coverage.append(
            coverage_entry(
                "AI Infrastructure Monitoring",
                f"ai_infra.{product}",
                info["label"],
                info["status"],
                info["owner"],
                SOURCE_URLS["ai_infra"],
                info["notes"],
            )
        )
    return coverage


def coverage_summary(coverage: list[dict[str, str]]) -> dict[str, Any]:
    by_status: dict[str, int] = {}
    for entry in coverage:
        by_status[entry["status"]] = by_status.get(entry["status"], 0) + 1
    return {"total": len(coverage), "by_status": by_status}


def write_text(path: Path, text: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if executable:
        current = path.stat().st_mode
        path.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def write_json(path: Path, data: Any) -> None:
    write_text(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def runtime_env(spec: dict[str, Any]) -> str:
    aam = spec["ai_agent_monitoring"]
    deployment = spec["deployment"]
    emitters = "span_metric"
    if aam.get("enable_content_capture") or aam.get("enable_evaluations"):
        emitters = "span_metric_event,splunk"
    lines = [
        "# Splunk AI Agent Monitoring runtime environment",
        "# Review content/evaluation gates before applying to workloads.",
        f"OTEL_SERVICE_NAME={aam.get('service_name')}",
        f"OTEL_RESOURCE_ATTRIBUTES=deployment.environment={deployment.get('environment')}",
        "SPLUNK_OTEL_AGENT=localhost",
        "OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317",
        "OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE=delta",
        "OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED=true",
        f"OTEL_INSTRUMENTATION_GENAI_EMITTERS={emitters}",
        f"OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT={str(bool(aam.get('enable_content_capture'))).lower()}",
    ]
    if aam.get("enable_content_capture"):
        lines.append("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT_MODE=SPAN_AND_EVENT")
    if aam.get("enable_evaluations"):
        lines.extend(
            [
                "OTEL_INSTRUMENTATION_GENAI_EVALS_RESULTS_AGGREGATION=true",
                "OTEL_INSTRUMENTATION_GENAI_EMITTERS_EVALUATION=replace-category:SplunkEvaluationResults",
                f"OTEL_INSTRUMENTATION_GENAI_EVALS_SEPARATE_PROCESS={str(bool(aam.get('evals_separate_process'))).lower()}",
                f"OTEL_INSTRUMENTATION_GENAI_EVALUATION_SAMPLE_RATE={aam.get('evals_sample_rate', 1)}",
                "OTEL_INSTRUMENTATION_GENAI_EVALUATION_RATE_LIMIT_ENABLE=true",
                f"OTEL_INSTRUMENTATION_GENAI_EVALUATION_RATE_LIMIT_RPS={aam.get('evals_rate_limit_rps', 1)}",
                "OTEL_INSTRUMENTATION_GENAI_EVALUATION_RATE_LIMIT_BURST=4",
                "OTEL_INSTRUMENTATION_GENAI_EVALS_USE_SINGLE_METRIC=true",
                "DEEPEVAL_FILE_SYSTEM=READ_ONLY",
            ]
        )
    return "\n".join(lines) + "\n"


def requirements_txt(spec: dict[str, Any]) -> str:
    return "\n".join(selected_packages(spec)) + "\n"


def collector_values(spec: dict[str, Any]) -> str:
    return """# Splunk AI Agent Monitoring collector overlay
# Minimal Helm values overlay for the Splunk OTel Collector chart.
agent:
  config:
    exporters:
      signalfx:
        send_otlp_histograms: true
gateway:
  enabled: true
"""


def hec_overlay(spec: dict[str, Any]) -> str:
    hec = spec["ai_agent_monitoring"].get("hec", {})
    return f"""# Splunk HEC logs/events overlay for AI Agent Monitoring evaluation/content events.
exporters:
  splunk_hec:
    token: "${{SPLUNK_PLATFORM_HEC_TOKEN}}"
    endpoint: "${{SPLUNK_PLATFORM_HEC_ENDPOINT}}"
    source: "{hec.get('source', 'otel')}"
    sourcetype: "{hec.get('sourcetype', 'otel')}"
    index: "{hec.get('index', 'ai_events')}"
service:
  pipelines:
    logs:
      receivers: [fluentforward, otlp]
      processors: [memory_limiter, batch, resourcedetection]
      exporters: [splunk_hec]
"""


def k8s_patch(spec: dict[str, Any]) -> str:
    aam = spec["ai_agent_monitoring"]
    deployment = spec["deployment"]
    workload_kind = str(deployment.get("workload_kind", "deployment")).lower()
    api_kind = WORKLOAD_KINDS.get(workload_kind, WORKLOAD_KINDS["deployment"])["api_kind"]
    workload_name = str(deployment.get("workload_name") or aam.get("service_name"))
    container_name = str(deployment.get("container_name", "app"))
    env_lines = []
    for line in runtime_env(spec).splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key == "SPLUNK_OTEL_AGENT":
            continue
        if key == "OTEL_EXPORTER_OTLP_ENDPOINT":
            value = "http://$(SPLUNK_OTEL_AGENT):4317"
        env_lines.append(f"            - name: {key}\n              value: {json.dumps(value)}")
    env_block = "\n".join(env_lines)
    return f"""apiVersion: apps/v1
kind: {api_kind}
metadata:
  name: {workload_name}
spec:
  template:
    spec:
      containers:
        - name: {container_name}
          env:
            - name: SPLUNK_OTEL_AGENT
              valueFrom:
                fieldRef:
                  fieldPath: status.hostIP
{env_block}
"""


def apply_plan(spec: dict[str, Any], output_dir: Path, token_file: str = "", platform_hec_token_file: str = "", service_account_password_file: str = "") -> list[dict[str, Any]]:
    realm = str(spec.get("realm", ""))
    deployment = spec["deployment"]
    aam = spec["ai_agent_monitoring"]
    hec = aam.get("hec", {})
    loc = aam.get("log_observer_connect", {})
    mode = str(deployment.get("collector_mode", "kubernetes")).lower()
    collector_mode_flag = "--apply-linux" if mode == "linux" else "--apply-k8s"
    collector_cmd = [
        "bash",
        "skills/splunk-observability-otel-collector-setup/scripts/setup.sh",
        collector_mode_flag,
        "--realm",
        realm,
        "--output-dir",
        str(output_dir / "delegated" / "otel-collector"),
    ]
    if mode == "kubernetes":
        collector_cmd.extend(
            [
                "--cluster-name",
                str(deployment.get("cluster_name", "")),
                "--namespace",
                str(deployment.get("namespace", "splunk-otel")),
                "--extra-values-file",
                str(output_dir / "collector" / "values-ai-agent-monitoring.yaml"),
                "--deployment-environment",
                str(deployment.get("environment", "prod")),
            ]
        )
    else:
        collector_cmd.extend(["--deployment-environment", str(deployment.get("environment", "prod")), "--service-name", str(aam.get("service_name", ""))])
    if token_file:
        collector_cmd.extend(["--o11y-token-file", token_file])
    if platform_hec_token_file:
        collector_cmd.extend(["--platform-hec-token-file", platform_hec_token_file])

    hec_cmd = [
        "bash",
        "skills/splunk-hec-service-setup/scripts/setup.sh",
        "--platform",
        str(hec.get("platform", "enterprise")),
        "--phase",
        "apply",
        "--output-dir",
        str(output_dir / "delegated" / "hec-service"),
        "--token-name",
        str(hec.get("token_name", "ai_agent_monitoring_hec")),
        "--default-index",
        str(hec.get("index", "ai_events")),
        "--allowed-indexes",
        str(hec.get("index", "ai_events")),
        "--source",
        str(hec.get("source", "otel")),
        "--sourcetype",
        str(hec.get("sourcetype", "otel")),
    ]
    if platform_hec_token_file:
        if str(hec.get("platform", "enterprise")) == "cloud":
            hec_cmd.extend(["--write-token-file", platform_hec_token_file])
        else:
            hec_cmd.extend(["--token-file", platform_hec_token_file])

    loc_cmd = [
        "bash",
        "skills/splunk-observability-cloud-integration-setup/scripts/setup.sh",
        "--apply",
        "log_observer_connect",
        "--spec",
        str(output_dir / "handoffs" / "cloud-integration-loc.spec.json"),
        "--realm",
        realm,
        "--output-dir",
        str(output_dir / "delegated" / "cloud-integration-loc"),
    ]
    if token_file:
        loc_cmd.extend(["--token-file", token_file])
    if service_account_password_file:
        loc_cmd.extend(["--service-account-password-file", service_account_password_file])

    dashboard_cmd = [
        "bash",
        "skills/splunk-observability-dashboard-builder/scripts/setup.sh",
        "--apply",
        "--spec",
        str(output_dir / "dashboards" / "handoff-dashboard.spec.json"),
        "--realm",
        realm,
        "--output-dir",
        str(output_dir / "delegated" / "dashboards"),
    ]
    if token_file:
        dashboard_cmd.extend(["--token-file", token_file])

    detector_cmd = [
        "bash",
        "skills/splunk-observability-native-ops/scripts/setup.sh",
        "--apply",
        "--spec",
        str(output_dir / "detectors" / "handoff-native-ops.spec.json"),
        "--realm",
        realm,
        "--output-dir",
        str(output_dir / "delegated" / "native-ops"),
    ]
    if token_file:
        detector_cmd.extend(["--token-file", token_file])

    ai_infra_cmd = [
        "bash",
        str(output_dir / "scripts" / "apply-ai-infra-collector.sh"),
    ]

    hec_enabled = bool(hec.get("enabled"))
    loc_enabled = bool(loc.get("enabled"))
    dashboards_enabled = bool(spec.get("dashboards", {}).get("enabled"))
    detectors_enabled = bool(spec.get("detectors", {}).get("enabled"))

    return [
        {"section": "collector", "coverage": "delegated_apply", "command": collector_cmd},
        {"section": "hec", "coverage": "delegated_apply" if hec_enabled else "not_applicable", "command": hec_cmd if hec_enabled else ["bash", str(output_dir / "scripts" / "apply-hec.sh")]},
        {"section": "loc", "coverage": "delegated_apply" if loc_enabled else "not_applicable", "command": loc_cmd if loc_enabled else ["bash", str(output_dir / "scripts" / "apply-loc.sh")], "ui_handoff": "Settings > AI Agent Monitoring connection/index remains deeplink."},
        {"section": "python-runtime", "coverage": "handoff", "command": ["bash", str(output_dir / "scripts" / "apply-python-runtime.sh")]},
        {"section": "kubernetes-runtime", "coverage": "handoff", "command": ["bash", str(output_dir / "scripts" / "apply-kubernetes-runtime.sh")]},
        {"section": "ai-infra-collector", "coverage": "delegated_apply", "command": ai_infra_cmd},
        {"section": "dashboards", "coverage": "delegated_apply" if dashboards_enabled else "not_applicable", "command": dashboard_cmd if dashboards_enabled else ["bash", str(output_dir / "scripts" / "apply-dashboards.sh")]},
        {"section": "detectors", "coverage": "delegated_apply" if detectors_enabled else "not_applicable", "command": detector_cmd if detectors_enabled else ["bash", str(output_dir / "scripts" / "apply-detectors.sh")]},
    ]


def command_script(command: list[str]) -> str:
    quoted = " ".join(shell_quote(part) for part in command)
    project_root = shell_quote(str(PROJECT_ROOT))
    return f"""#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT={project_root}
cd "${{PROJECT_ROOT}}"
exec {quoted}
"""


def write_apply_scripts(output_dir: Path, plan: list[dict[str, Any]], spec: dict[str, Any]) -> None:
    for step in plan:
        section = step["section"]
        if section in {"python-runtime", "kubernetes-runtime", "ai-infra-collector"}:
            continue
        if step.get("coverage") == "not_applicable":
            write_text(
                output_dir / "scripts" / f"apply-{section}.sh",
                f"""#!/usr/bin/env bash
set -euo pipefail
echo "Section {section} is not applicable for this normalized spec; no live changes made."
""",
                executable=True,
            )
            continue
        write_text(output_dir / "scripts" / f"apply-{section}.sh", command_script(step["command"]), executable=True)

    write_text(
        output_dir / "scripts" / "apply-python-runtime.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail
echo "Python runtime apply is an application handoff, not a live mutation owned by this skill."
echo "Review and apply: {output_dir / 'runtime' / 'requirements.txt'}"
echo "Review and apply: {output_dir / 'runtime' / 'python.env'}"
""",
        executable=True,
    )
    deployment = spec["deployment"]
    workload_kind = str(deployment.get("workload_kind", "deployment")).lower()
    workload_resource = WORKLOAD_KINDS.get(workload_kind, WORKLOAD_KINDS["deployment"])["resource"]
    workload_namespace = str(deployment.get("workload_namespace", "default"))
    workload_name = str(deployment.get("workload_name") or spec["ai_agent_monitoring"].get("service_name"))
    patch_path = str(output_dir / "kubernetes" / "deployment-env-patch.yaml")
    dry_run_cmd = (
        f"kubectl -n {shell_quote(workload_namespace)} patch {shell_quote(workload_resource)} "
        f"{shell_quote(workload_name)} --type strategic --patch-file {shell_quote(patch_path)} --dry-run=server"
    )
    apply_cmd = (
        f"kubectl -n {shell_quote(workload_namespace)} patch {shell_quote(workload_resource)} "
        f"{shell_quote(workload_name)} --type strategic --patch-file {shell_quote(patch_path)}"
    )
    write_text(
        output_dir / "scripts" / "apply-kubernetes-runtime.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail
echo "Kubernetes runtime apply is a workload-owner handoff because this skill does not own application Deployments."
echo "Review and patch selectively: {output_dir / 'kubernetes' / 'deployment-env-patch.yaml'}"
echo "Dry run:"
echo "{dry_run_cmd}"
echo "Apply:"
echo "{apply_cmd}"
""",
        executable=True,
    )

    product_lines = []
    products = selected_ai_infra_products(spec)
    if "cisco_ai_pods" in products:
        product_lines.append("echo 'Cisco AI PODs: delegate to skills/splunk-observability-cisco-ai-pod-integration/scripts/setup.sh --render/--apply as appropriate.'")
    if "nvidia_gpu" in products:
        product_lines.append("echo 'NVIDIA GPU: delegate to skills/splunk-observability-nvidia-gpu-integration/scripts/setup.sh --render --validate, then apply via that skill when approved.'")
    product_lines.append(f"echo 'Review AI infrastructure collector handoffs under {output_dir / 'ai-infrastructure'}.'")
    write_text(
        output_dir / "scripts" / "apply-ai-infra-collector.sh",
        "#!/usr/bin/env bash\nset -euo pipefail\n" + "\n".join(product_lines) + "\n",
        executable=True,
    )


def render_markdown_table(entries: list[dict[str, str]]) -> str:
    lines = ["| Key | Title | Status | Owner | Notes |", "|-----|-------|--------|-------|-------|"]
    for entry in entries:
        notes = entry["notes"].replace("|", "\\|")
        lines.append(f"| `{entry['key']}` | {entry['title']} | `{entry['status']}` | {entry['owner']} | {notes} |")
    return "\n".join(lines)


def render_coverage_md(coverage: list[dict[str, str]]) -> str:
    by_area: dict[str, list[dict[str, str]]] = {}
    for entry in coverage:
        by_area.setdefault(entry["area"], []).append(entry)
    parts = [
        "# Coverage Report",
        "",
        f"Reviewed at: `{REVIEWED_AT}`",
        "",
        "Statuses: `delegated_apply`, `render`, `validate`, `deeplink`, `handoff`, `not_applicable`.",
    ]
    for area, entries in by_area.items():
        parts.extend(["", f"## {area}", "", render_markdown_table(entries)])
    return "\n".join(parts) + "\n"


def render_package_md(packages: list[str]) -> str:
    lines = [
        "# Package Catalog",
        "",
        f"Reviewed at: `{REVIEWED_AT}`",
        "",
        "| Package | Version snapshot | Python | Kind | Purpose |",
        "|---------|------------------|--------|------|---------|",
    ]
    for package in packages:
        info = PACKAGE_BY_NAME.get(package, {})
        lines.append(
            f"| `{package}` | {info.get('version', 'unknown')} | `{info.get('requires_python', 'unknown')}` | `{info.get('kind', 'unknown')}` | {info.get('purpose', '')} |"
        )
    return "\n".join(lines) + "\n"


def handoff_md(spec: dict[str, Any], plan: list[dict[str, Any]]) -> str:
    loc = spec["ai_agent_monitoring"].get("log_observer_connect", {})
    lines = [
        "# AI Agent Monitoring Handoff",
        "",
        "## Review First",
        "",
        "- `coverage-report.json` is the source of truth for API-backed versus UI-only surfaces.",
        "- `runtime/python.env` keeps content capture off unless explicitly accepted.",
        "- `collector/values-ai-agent-monitoring.yaml` enforces `send_otlp_histograms: true`.",
        "",
        "## Apply Commands",
        "",
    ]
    for step in plan:
        lines.append(f"### {step['section']}")
        lines.append("")
        lines.append("```bash")
        lines.append(" ".join(shell_quote(part) for part in step["command"]))
        lines.append("```")
        lines.append("")
    if loc.get("enabled"):
        lines.extend(
            [
                "## UI Deeplink Handoff",
                "",
                "After LOC prerequisites are applied, complete the UI-only AI Agent Monitoring settings:",
                "",
                "1. Open Splunk Observability Cloud.",
                "2. Go to Settings > AI Agent Monitoring.",
                f"3. Select connection `{loc.get('connection_name')}`.",
                f"4. Select index `{loc.get('index')}`.",
                "5. Select Apply.",
                "",
            ]
        )
    return "\n".join(lines)


def doctor_report(errors: list[str], warnings: list[str], spec: dict[str, Any], plan: list[dict[str, Any]]) -> str:
    lines = ["# Doctor Report", "", f"Reviewed at: `{REVIEWED_AT}`", ""]
    if not errors and not warnings:
        lines.extend(["No blocking findings in the rendered plan.", ""])
    if errors:
        lines.extend(["## Failures", ""])
        for error in errors:
            lines.append(f"- FAIL: {error}")
        lines.append("")
    if warnings:
        lines.extend(["## Warnings", ""])
        for warning in warnings:
            lines.append(f"- WARN: {warning}")
        lines.append("")
    lines.extend(["## Fix Commands", ""])
    lines.append("- Collector: `bash skills/splunk-observability-ai-agent-monitoring-setup/scripts/setup.sh --apply collector --spec <spec>`")
    if spec["ai_agent_monitoring"].get("hec", {}).get("enabled"):
        lines.append("- HEC: `bash skills/splunk-observability-ai-agent-monitoring-setup/scripts/setup.sh --apply hec --spec <spec>`")
    if spec["ai_agent_monitoring"].get("log_observer_connect", {}).get("enabled"):
        lines.append("- LOC: `bash skills/splunk-observability-ai-agent-monitoring-setup/scripts/setup.sh --apply loc --spec <spec>`")
        lines.append("- UI: Observability Cloud > Settings > AI Agent Monitoring > select connection and index.")
    return "\n".join(lines) + "\n"


def render_handoffs(spec: dict[str, Any], output_dir: Path) -> None:
    aam = spec["ai_agent_monitoring"]
    hec = aam.get("hec", {})
    loc = aam.get("log_observer_connect", {})
    write_json(
        output_dir / "handoffs" / "cloud-integration-loc.spec.json",
        {
            "api_version": "splunk-observability-cloud-integration-setup/v1",
            "target": loc.get("target", "enterprise"),
            "realm": spec.get("realm"),
            "log_observer_connect": {
                "enable": bool(loc.get("enabled")),
                "connection_name": loc.get("connection_name"),
                "indexes": [loc.get("index", hec.get("index", "ai_events"))],
                "role": {"name": "log_observer_connect", "indexes": [loc.get("index", hec.get("index", "ai_events"))]},
            },
        },
    )
    write_json(
        output_dir / "dashboards" / "handoff-dashboard.spec.json",
        {
            "mode": "classic-api",
            "realm": spec.get("realm"),
            "dashboard_group": {"name": spec.get("dashboards", {}).get("group_name", "AI Agent Monitoring")},
            "dashboard": {"name": f"AI Agent Monitoring - {aam.get('service_name')}", "description": "Rendered handoff from AI Agent Monitoring setup."},
            "charts": [
                {"name": "GenAI token usage", "type": "TimeSeriesChart", "programText": "data('gen_ai.client.token.usage').publish(label='tokens')"},
                {"name": "GenAI operation duration", "type": "TimeSeriesChart", "programText": "data('gen_ai.client.operation.duration').publish(label='duration')"},
                {"name": "Evaluation score", "type": "TimeSeriesChart", "programText": "data('gen_ai.evaluation.score').publish(label='score')"},
            ],
        },
    )
    write_json(
        output_dir / "detectors" / "handoff-native-ops.spec.json",
        {
            "api_version": "splunk-observability-native-ops/v1",
            "realm": spec.get("realm"),
            "detectors": [
                {
                    "name": f"AI Agent high operation latency - {aam.get('service_name')}",
                    "programText": "A = data('gen_ai.client.operation.duration').mean().publish(label='A')",
                    "rules": [{"severity": "Warning", "detectLabel": "A", "threshold": 5}],
                }
            ],
        },
    )


def render_ai_infra_handoffs(spec: dict[str, Any], output_dir: Path) -> None:
    products = selected_ai_infra_products(spec)
    rows = []
    for product in products:
        info = AI_INFRA_PRODUCTS.get(product, {"label": product, "status": "handoff", "owner": "operator", "notes": ""})
        rows.append(f"- **{info['label']}** (`{product}`): `{info['status']}` via {info['owner']}. {info['notes']}")
    write_text(output_dir / "ai-infrastructure" / "handoff.md", "# AI Infrastructure Monitoring Handoffs\n\n" + "\n".join(rows) + "\n")


def render(output_dir: Path, spec: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    errors, warnings = validate_spec(spec)
    coverage = build_coverage(spec)
    summary = coverage_summary(coverage)
    packages = selected_packages(spec)
    plan = apply_plan(spec, output_dir, args.o11y_token_file or "", args.platform_hec_token_file or "", args.service_account_password_file or "")

    result = {
        "api_version": API_VERSION,
        "reviewed_at": REVIEWED_AT,
        "output_dir": str(output_dir),
        "errors": errors,
        "warnings": warnings,
        "coverage_summary": summary,
        "package_count": len(packages),
    }

    if args.dry_run:
        return result

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "metadata.json", result)
    write_json(output_dir / "normalized-spec.json", spec)
    write_json(output_dir / "coverage-report.json", {"reviewed_at": REVIEWED_AT, "source_urls": SOURCE_URLS, "coverage": coverage, "summary": summary})
    write_text(output_dir / "coverage-report.md", render_coverage_md(coverage))
    write_json(output_dir / "package-catalog.json", {"reviewed_at": REVIEWED_AT, "selected_packages": packages, "catalog": PACKAGE_CATALOG, "blocked_packages": BLOCKED_PACKAGES})
    write_text(output_dir / "package-catalog.md", render_package_md(packages))
    write_json(output_dir / "apply-plan.json", {"reviewed_at": REVIEWED_AT, "steps": plan})
    write_text(output_dir / "runtime" / "python.env", runtime_env(spec))
    write_text(output_dir / "runtime" / "requirements.txt", requirements_txt(spec))
    write_text(output_dir / "collector" / "values-ai-agent-monitoring.yaml", collector_values(spec))
    write_text(output_dir / "collector" / "splunk-hec-logs-overlay.yaml", hec_overlay(spec))
    write_text(output_dir / "kubernetes" / "deployment-env-patch.yaml", k8s_patch(spec))
    render_handoffs(spec, output_dir)
    render_ai_infra_handoffs(spec, output_dir)
    write_apply_scripts(output_dir, plan, spec)
    write_text(output_dir / "handoff.md", handoff_md(spec, plan))
    write_text(output_dir / "doctor-report.md", doctor_report(errors, warnings, spec, plan))
    return result


def discover_payload() -> dict[str, Any]:
    return {
        "reviewed_at": REVIEWED_AT,
        "source_urls": SOURCE_URLS,
        "frameworks": {key: {"label": value["label"], "packages": value["packages"], "notes": value["notes"]} for key, value in FRAMEWORKS.items()},
        "translators": TRANSLATORS,
        "provider_adjuncts": PROVIDER_ADJUNCTS,
        "ai_infrastructure_products": AI_INFRA_PRODUCTS,
        "blocked_packages": BLOCKED_PACKAGES,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("splunk-observability-ai-agent-monitoring-rendered"))
    parser.add_argument("--realm")
    parser.add_argument("--collector-mode")
    parser.add_argument("--cluster-name")
    parser.add_argument("--workload-kind")
    parser.add_argument("--workload-namespace")
    parser.add_argument("--workload-name")
    parser.add_argument("--container-name")
    parser.add_argument("--service-name")
    parser.add_argument("--python-version")
    parser.add_argument("--frameworks")
    parser.add_argument("--translators")
    parser.add_argument("--provider-adjuncts")
    parser.add_argument("--ai-infra-products")
    parser.add_argument("--send-otlp-histograms")
    parser.add_argument("--hec-index")
    parser.add_argument("--hec-platform")
    parser.add_argument("--enable-content-capture", action="store_true")
    parser.add_argument("--accept-content-capture", action="store_true")
    parser.add_argument("--enable-evaluations", action="store_true")
    parser.add_argument("--accept-evaluation-cost", action="store_true")
    parser.add_argument("--o11y-token-file")
    parser.add_argument("--platform-hec-token-file")
    parser.add_argument("--service-account-password-file")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--discover", action="store_true")
    args = parser.parse_args()

    if args.discover:
        print(json.dumps(discover_payload(), indent=2, sort_keys=True))
        return 0

    spec = apply_overrides(load_spec(args.spec), args)
    output_dir = args.output_dir.expanduser().resolve()
    result = render(output_dir, spec, args)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        status = "FAIL" if result["errors"] else "OK"
        counts = ", ".join(f"{k}={v}" for k, v in sorted(result["coverage_summary"]["by_status"].items()))
        print(f"render: {status} -> {result['output_dir']} ({counts})")
        for warning in result["warnings"]:
            print(f"WARN: {warning}", file=sys.stderr)
        for error in result["errors"]:
            print(f"FAIL: {error}", file=sys.stderr)
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

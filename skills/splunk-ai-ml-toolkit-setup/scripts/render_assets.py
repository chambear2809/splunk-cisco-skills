#!/usr/bin/env python3
"""Render Splunk AI/ML Toolkit coverage and handoff artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - exercised in shell wrappers
    yaml = None


API_VERSION = "splunk-ai-ml-toolkit-setup/v1"
RESEARCH_VERIFIED = "2026-08-20"
ALLOWED_STATUSES = {
    "planned",
    "validated",
    "delegated",
    "manual_handoff",
    "eol_migration",
    "blocked",
    "not_applicable",
}
ALLOWED_PRODUCT_STAGES = {
    "alpha",
    "available",
    "deprecated",
    "feature_preview",
    "ga",
}

DOC_BASE_CLOUD = "https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit/6.0.2"
DOC_BASE_ENTERPRISE = "https://help.splunk.com/en/splunk-enterprise/apply-machine-learning/use-ai-toolkit/6.0.2"

AI_TOOLKIT = {
    "app_id": "2890",
    "app_name": "Splunk_ML_Toolkit",
    "version": "6.0.2",
    "date": "August 10, 2026",
    "required_psc_version": "4.3.4",
    "python_version": "3.13",
    "platform_versions": "Splunk Enterprise 9.3.x-10.5.x or Splunk Cloud Platform",
    "source_url": "https://splunkbase.splunk.com/app/2890",
    "docs_root_url": "https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit",
    "install_doc_url": f"{DOC_BASE_CLOUD}/install-and-upgrade-the-ai-toolkit/install-the-ai-toolkit",
    "version_dependencies_url": f"{DOC_BASE_CLOUD}/install-and-upgrade-the-ai-toolkit/splunk-ai-toolkit-version-dependencies",
    "release_notes_url": f"{DOC_BASE_CLOUD}/release-notes/whats-new-in-the-ai-toolkit",
    "cdtsm_url": f"{DOC_BASE_CLOUD}/ai-toolkit-models/cisco-deep-time-series-model",
    "cdtsm_on_prem_url": f"{DOC_BASE_ENTERPRISE}/ai-toolkit-models/cisco-deep-time-series-model-on--premises-installation",
    "connections_url": f"{DOC_BASE_CLOUD}/ai-toolkit-connections-containers-and-agents/connections-in-the-ai-toolkit",
    "container_management_url": f"{DOC_BASE_CLOUD}/ai-toolkit-connections-containers-and-agents/container-management-in-the-ai-toolkit",
    "ml_spl_commands_url": f"{DOC_BASE_CLOUD}/ai-toolkit-commands-macros-and-visualizations/search-commands-for-machine-learning",
    "permissions_url": f"{DOC_BASE_CLOUD}/ai-toolkit-commands-macros-and-visualizations/permissions-for-machine-learning-commands",
    "safeguards_url": f"{DOC_BASE_CLOUD}/ai-toolkit-commands-macros-and-visualizations/search-commands-for-machine-learning-safeguards",
    "ai_command_url": f"{DOC_BASE_CLOUD}/ai-toolkit-commands-macros-and-visualizations/about-the-ai-command",
    "onnx_url": f"{DOC_BASE_CLOUD}/ai-toolkit-models/upload-and-inference-pre-trained-onnx-models-in-the-ai-toolkit",
    "model_permissions_url": f"{DOC_BASE_CLOUD}/ai-toolkit-models/model-permissions-in-the-ai-toolkit",
    "assistants_url": f"{DOC_BASE_CLOUD}/smart-assistant-guided-workflows",
    "experiments_url": f"{DOC_BASE_CLOUD}/experiment-assistant-guided-workflows",
    "agent_launchpad_url": f"{DOC_BASE_CLOUD}/ai-toolkit-connections-containers-and-agents/ai-toolkit-agent-launchpad",
    "agent_launchpad_on_prem_url": f"{DOC_BASE_CLOUD}/ai-toolkit-connections-containers-and-agents/agent-launchpad-for-on-premises-users",
    "product_url": "https://www.splunk.com/en_us/products/ai-toolkit.html",
}

# Package-derived command surface from Splunk_ML_Toolkit 6.0.2
# `default/commands.conf`. DOCUMENTED_ML_SPL_COMMANDS is the operator-facing set
# listed in the 6.0.2 "Search commands for machine learning" table.
# PACKAGE_ONLY_ML_SPL_COMMANDS also ship in commands.conf but are absent from
# that table, so they back app internals rather than documented operator use.
DOCUMENTED_ML_SPL_COMMANDS = (
    "ai",
    "aiagent",
    "apply",
    "deletemodel",
    "fit",
    "listmodels",
    "sample",
    "score",
    "summary",
)
PACKAGE_ONLY_ML_SPL_COMMANDS = (
    "agentstatus",
    "externalendpointinventory",
    "kvstorelookup",
    "logexperiment",
    "mltkmanage",
)
RISKY_ML_SPL_COMMANDS = ("agentstatus", "ai", "aiagent", "apply", "deletemodel", "fit", "mltkmanage")

TIME_SERIES_MODELS = {
    "ctsm_open_1_0": {
        "name": "Cisco Time Series Model 1.0",
        "product_stage": "available",
        "model_id": "cisco-ai/cisco-time-series-model-1.0",
        "license": "Apache-2.0",
        "source_url": "https://huggingface.co/cisco-ai/cisco-time-series-model-1.0",
        "github_url": "https://github.com/splunk/cisco-time-series-model",
        "dsdl_url": "https://lantern.splunk.com/Platform_Data_Management/Analysis_with_AI/Using_the_Cisco_Time_Series_Model_1.0_on_DSDL_5.2.3",
    },
    "cdtsm_integrated": {
        "name": "Cisco Deep Time Series Model",
        "product_stage": "ga",
        "ga_since": "6.0.0",
        "source_url": AI_TOOLKIT["cdtsm_url"],
        "on_prem_url": AI_TOOLKIT["cdtsm_on_prem_url"],
        "rate_limit": "50 model requests per minute, managed by the AI Toolkit",
        "opt_out_setting": "mlspl.conf [CTSM] ctsm_opt_out with the aitk_ctsm_opt_out capability",
    },
}

AGENT_LAUNCHPAD = {
    "name": "Splunk AI Toolkit Agent Launchpad",
    "product_stage": "ga",
    "ga_since": "6.0.0",
    "status_as_of": RESEARCH_VERIFIED,
    "doc_url": AI_TOOLKIT["agent_launchpad_url"],
    "on_prem_doc_url": AI_TOOLKIT["agent_launchpad_on_prem_url"],
    "release_notes_url": AI_TOOLKIT["release_notes_url"],
    "supported_llm_providers": "OpenAI, Anthropic, Azure OpenAI, Amazon Bedrock, or Splunk-hosted models",
    "unsupported_llm_providers": "custom LLM and Ollama connections",
    "unsupported_llm_sentence": "Custom LLM and Ollama connections are not supported by Agent Launchpad, even though the Connections tab can hold them.",
    "supported_mcp_providers": "Splunk, Atlassian, Slack, PagerDuty, GitHub, and GitLab, plus custom MCP with Basic Auth, API key, Bearer Token, or OAuth 2.0",
    "run_history_index_setting": "mlspl.conf [ai:AgentIntegrations] agent_run_index, which the package ships as _audit",
    "allowed_domains_setting": "mlspl.conf [ai:AllowedDomains] allowed_domains with enforce_domain_validation",
    "cloud_control_studio_url": "https://www.cisco.com/site/us/en/solutions/artificial-intelligence/agentic-ops/cloud-control-studio/index.html",
}

DSDL = {
    "app_id": "4607",
    "app_name": "mltk-container",
    "version": "5.2.4",
    "date": "May 22, 2026",
    "source_url": "https://splunkbase.splunk.com/app/4607",
    "components_doc_url": "https://help.splunk.com/en/splunk-enterprise/apply-machine-learning/use-splunk-app-for-data-science-and-deep-learning/5.2/about-the-splunk-app-for-data-science-and-deep-learning/splunk-app-for-data-science-and-deep-learning-components",
}

PSC_TARGETS = {
    "linux64": {
        "app_id": "2882",
        "app_name": "Splunk_SA_Scientific_Python_linux_x86_64",
        "label": "PSC Linux 64-bit",
        "version": "4.3.4",
        "date": "July 22, 2026",
        "source_url": "https://splunkbase.splunk.com/app/2882",
        "legacy": False,
    },
    "windows64": {
        "app_id": "2883",
        "app_name": "Splunk_SA_Scientific_Python_windows_x86_64",
        "label": "PSC Windows 64-bit",
        "version": "4.3.4",
        "date": "July 22, 2026",
        "source_url": "https://splunkbase.splunk.com/app/2883",
        "legacy": False,
    },
    "mac-intel": {
        "app_id": "2881",
        "app_name": "Splunk_SA_Scientific_Python_darwin_x86_64",
        "label": "PSC Mac Intel",
        "version": "4.3.4",
        "date": "July 22, 2026",
        "source_url": "https://splunkbase.splunk.com/app/2881",
        "legacy": False,
    },
    "mac-arm": {
        "app_id": "6785",
        "app_name": "Splunk_SA_Scientific_Python_darwin_arm64",
        "label": "PSC Mac Apple Silicon",
        "version": "4.3.4",
        "date": "July 22, 2026",
        "source_url": "https://splunkbase.splunk.com/app/6785",
        "legacy": False,
    },
    "linux32": {
        "app_id": "2884",
        "app_name": "Splunk_SA_Scientific_Python_linux_x86",
        "label": "PSC Linux 32-bit",
        "version": "1.3",
        "date": "July 27, 2018",
        "source_url": "https://splunkbase.splunk.com/app/2884",
        "legacy": True,
    },
}

LEGACY_APPS = {
    "legacy_anomaly_app": {
        "app_id": "6843",
        "app_name": "Splunk App for Anomaly Detection",
        "version": "1.1.2",
        "date": "November 15, 2023",
        "source_url": "https://splunkbase.splunk.com/app/6843",
    },
    "smart_alerts_beta": {
        "app_id": "6415",
        "app_name": "Smart_Alerts_Assistant",
        "version": "0.1.20",
        "date": "June 14, 2022",
        "source_url": "https://splunkbase.splunk.com/app/6415",
    },
}

DSDL_RUNTIME_NOTES = {
    "handoff": "Generic external runtime handoff; operator supplies Docker, Kubernetes, OpenShift, HPC, GPU, or air-gapped details.",
    "docker": "Docker runtime handoff; require image provenance, network isolation, persistence, and TLS review.",
    "kubernetes": "Kubernetes runtime handoff; require namespace, RBAC, storage, image registry, service endpoint, and resource quota review.",
    "openshift": "OpenShift runtime handoff; require SCC, route/TLS, namespace, RBAC, storage, and image registry review.",
    "hpc": "HPC runtime handoff; require scheduler, shared storage, model artifact, and data movement review.",
    "gpu": "GPU runtime handoff; require accelerator node pool, driver/runtime readiness, quotas, and image selection review.",
    "airgap": "Air-gapped runtime handoff; require mirrored images, checksums, registry credentials by file, and offline notebook package review.",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", default="")
    parser.add_argument("--output-dir", default="splunk-ai-ml-toolkit-rendered")
    parser.add_argument("--platform", choices=["enterprise", "cloud"], default="")
    parser.add_argument("--splunk-version", default="")
    parser.add_argument("--psc-target", default="")
    parser.add_argument("--include-dsdl", action="store_true")
    parser.add_argument("--no-dsdl", action="store_true")
    parser.add_argument("--dsdl-runtime", default="")
    parser.add_argument("--legacy-anomaly-audit", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--discover", action="store_true")
    return parser.parse_args()


def load_spec(path: str) -> dict[str, Any]:
    if not path:
        return {}
    spec_path = Path(path)
    if not spec_path.is_file():
        raise SystemExit(f"ERROR: spec does not exist: {path}")
    text = spec_path.read_text(encoding="utf-8")
    if spec_path.suffix.lower() == ".json":
        payload = json.loads(text)
    else:
        if yaml is None:
            raise SystemExit("ERROR: YAML specs require PyYAML. Install requirements-agent.txt.")
        payload = yaml.safe_load(text) or {}
    if not isinstance(payload, dict):
        raise SystemExit("ERROR: spec must be a JSON/YAML object")
    return payload


def to_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def choose_psc_target(raw_target: str, platform: str, warnings: list[str]) -> str:
    target = (raw_target or "linux64").strip().lower()
    aliases = {
        "auto": "linux64",
        "linux": "linux64",
        "linux-x64": "linux64",
        "linux_64": "linux64",
        "windows": "windows64",
        "windows-x64": "windows64",
        "win64": "windows64",
        "mac": "mac-intel",
        "macos": "mac-intel",
        "darwin-x64": "mac-intel",
        "darwin-arm64": "mac-arm",
        "mac-apple-silicon": "mac-arm",
        "mac-arm64": "mac-arm",
        "linux-32": "linux32",
    }
    target = aliases.get(target, target)
    if target not in PSC_TARGETS:
        valid = ", ".join(sorted(PSC_TARGETS))
        raise SystemExit(f"ERROR: unsupported --psc-target {raw_target!r}. Use one of: {valid}.")
    if raw_target in {"", "auto"} and platform == "enterprise":
        warnings.append(
            "PSC target defaulted to linux64. For live Enterprise installs, set --psc-target to the actual search-head OS."
        )
    if PSC_TARGETS[target]["legacy"]:
        warnings.append(
            "PSC Linux 32-bit (Splunkbase 2884) is legacy/migration-only and must not be installed on Splunk 10.5."
        )
    return target


def normalize_runtime(raw_runtime: str) -> str:
    runtime = (raw_runtime or "handoff").strip().lower()
    aliases = {"k8s": "kubernetes", "ocp": "openshift", "openshift4": "openshift"}
    runtime = aliases.get(runtime, runtime)
    if runtime not in DSDL_RUNTIME_NOTES:
        valid = ", ".join(sorted(DSDL_RUNTIME_NOTES))
        raise SystemExit(f"ERROR: unsupported --dsdl-runtime {raw_runtime!r}. Use one of: {valid}.")
    return runtime


def coverage_entry(
    key: str,
    title: str,
    status: str,
    source_url: str,
    summary: str,
    owner: str = "splunk-ai-ml-toolkit-setup",
    product_stage: str = "available",
) -> dict[str, str]:
    if status not in ALLOWED_STATUSES:
        raise ValueError(f"invalid coverage status for {key}: {status}")
    if product_stage not in ALLOWED_PRODUCT_STAGES:
        raise ValueError(f"invalid product stage for {key}: {product_stage}")
    return {
        "key": key,
        "title": title,
        "status": status,
        "product_stage": product_stage,
        "source_url": source_url,
        "summary": summary,
        "owner": owner,
    }


def build_context(args: argparse.Namespace) -> dict[str, Any]:
    spec = load_spec(args.spec)
    warnings: list[str] = []

    platform = args.platform or str(spec.get("platform") or "enterprise").lower()
    if platform not in {"enterprise", "cloud"}:
        raise SystemExit("ERROR: platform must be enterprise or cloud.")

    include_dsdl = to_bool(spec.get("include_dsdl"), default=False)
    if args.include_dsdl:
        include_dsdl = True
    if args.no_dsdl:
        include_dsdl = False

    psc_target = choose_psc_target(args.psc_target or str(spec.get("psc_target") or ""), platform, warnings)
    dsdl_runtime = normalize_runtime(args.dsdl_runtime or str(spec.get("dsdl_runtime") or "handoff"))
    legacy_audit = args.legacy_anomaly_audit or to_bool(spec.get("legacy_anomaly_audit"), default=False)
    splunk_version = args.splunk_version or str(spec.get("splunk_version") or "")

    if include_dsdl and PSC_TARGETS[psc_target]["legacy"]:
        raise SystemExit("ERROR: DSDL cannot be planned with legacy PSC Linux 32-bit.")
    if include_dsdl and dsdl_runtime == "docker":
        warnings.append(
            "DSDL Docker runtime selected. Treat this as a development or tightly controlled runtime unless TLS, image provenance, and network isolation are explicitly handled."
        )

    return {
        "api_version": API_VERSION,
        "platform": platform,
        "splunk_version": splunk_version,
        "psc_target": psc_target,
        "include_dsdl": include_dsdl,
        "dsdl_runtime": dsdl_runtime,
        "legacy_anomaly_audit": legacy_audit,
        "warnings": warnings,
        "spec": spec,
    }


def build_coverage(ctx: dict[str, Any]) -> list[dict[str, str]]:
    psc_target = ctx["psc_target"]
    include_dsdl = ctx["include_dsdl"]
    dsdl_runtime = ctx["dsdl_runtime"]
    legacy_audit = ctx["legacy_anomaly_audit"]
    # Agent Launchpad is GA on Splunk Cloud Platform in supported regions. On
    # Splunk Enterprise it is reached through the Splunk Cloud Connect app, so
    # Enterprise is a documented handoff rather than an unavailable surface.
    agent_launchpad_repo_status = "manual_handoff"
    agent_launchpad_doc_url = (
        AGENT_LAUNCHPAD["doc_url"] if ctx["platform"] == "cloud" else AGENT_LAUNCHPAD["on_prem_doc_url"]
    )
    coverage: list[dict[str, str]] = []

    coverage.append(
        coverage_entry(
            "ai_toolkit.package",
            "Splunk AI Toolkit / MLTK package",
            "planned",
            AI_TOOLKIT["source_url"],
            f"Install or update latest compatible {AI_TOOLKIT['app_name']} from Splunkbase app {AI_TOOLKIT['app_id']}; latest audited release is {AI_TOOLKIT['version']}.",
            product_stage="ga",
        )
    )
    coverage.append(
        coverage_entry(
            "ai_toolkit.compatibility",
            "AI Toolkit and PSC compatibility",
            "manual_handoff",
            AI_TOOLKIT["version_dependencies_url"],
            f"AI Toolkit {AI_TOOLKIT['version']} requires PSC {AI_TOOLKIT['required_psc_version']} (Python {AI_TOOLKIT['python_version']}) on {AI_TOOLKIT['platform_versions']}. Remove earlier PSC versions and perform a clean install; custom algorithms that link PSC libraries need refitting after the upgrade.",
        )
    )
    coverage.append(
        coverage_entry(
            "ai_toolkit.ml_spl_commands",
            "ML-SPL command surface",
            "manual_handoff",
            AI_TOOLKIT["ml_spl_commands_url"],
            f"Validate the documented {AI_TOOLKIT['version']} ML-SPL commands ({', '.join(DOCUMENTED_ML_SPL_COMMANDS)}) after install. The package also ships {', '.join(PACKAGE_ONLY_ML_SPL_COMMANDS)} in commands.conf without listing them in the documented command table; treat those as app internals rather than supported operator syntax.",
        )
    )
    coverage.append(
        coverage_entry(
            "ai_toolkit.permissions_and_safeguards",
            "ML command permissions and safeguards",
            "manual_handoff",
            AI_TOOLKIT["permissions_url"],
            f"Review ML command permissions, algorithm access, and performance-cost settings for production users. The package marks {', '.join(RISKY_ML_SPL_COMMANDS)} as is_risky, so each one triggers SPL safeguards and needs an explicit run-anyway decision or a role that carries the safeguard capability.",
        )
    )
    coverage.append(
        coverage_entry(
            "ai_toolkit.assistants",
            "AI Toolkit assistants and experiments",
            "manual_handoff",
            AI_TOOLKIT["assistants_url"],
            "Cover prediction, clustering, forecasting, outlier, anomaly, and experiment-management workflows.",
        )
    )
    coverage.append(
        coverage_entry(
            "ai_toolkit.anomaly_cisco_deep_time_series",
            "Cisco Deep Time Series Model",
            "manual_handoff",
            AI_TOOLKIT["cdtsm_url"],
            f"CDTSM forecasting, anomaly detection, and predictive alerting are generally available as of AI Toolkit {TIME_SERIES_MODELS['cdtsm_integrated']['ga_since']} and are no longer a feature preview. Cloud uses the Splunk-hosted model in a supported region; Enterprise requires a separately self-hosted open Cisco Time Series Model service. Invoke it as `apply CDTSM <fields_to_forecast>`, with wildcard forecast fields supported from 6.0.0. Usage is limited to {TIME_SERIES_MODELS['cdtsm_integrated']['rate_limit']}, and the opt-out is {TIME_SERIES_MODELS['cdtsm_integrated']['opt_out_setting']}. Do not treat the integrated experience as the open model release itself.",
            product_stage="ga",
        )
    )
    coverage.append(
        coverage_entry(
            "ai_toolkit.open_cisco_time_series_model_1_0",
            "Cisco Time Series Model 1.0 open-weight release",
            "manual_handoff",
            TIME_SERIES_MODELS["ctsm_open_1_0"]["source_url"],
            "Cisco Time Series Model 1.0 is an available Apache-2.0 open-weight model on Hugging Face, with source and self-hosting assets on GitHub. Model/runtime deployment is separate from enabling the AI Toolkit CDTSM integration.",
            product_stage="available",
        )
    )
    coverage.append(
        coverage_entry(
            "ai_toolkit.hosted_foundation_models",
            "Hosted foundation model readiness",
            "manual_handoff",
            AI_TOOLKIT["connections_url"],
            "Review Splunk-hosted LLM availability for Foundation-Sec and GPT-OSS in the Connections tab. CDTSM is a separate time-series integration and is not an LLM connection option. No external API keys are rendered by this skill.",
            product_stage="ga",
        )
    )
    coverage.append(
        coverage_entry(
            "ai_toolkit.agent_launchpad",
            "Splunk AI Toolkit Agent Launchpad",
            agent_launchpad_repo_status,
            agent_launchpad_doc_url,
            f"Agent Launchpad replaced the Agent Builder feature preview and is generally available as of AI Toolkit {AGENT_LAUNCHPAD['ga_since']}. Splunk Cloud Platform requires a supported AWS region plus the documented per-region egress IP in the stack apiAllowlistIP; Splunk Enterprise reaches it through the Splunk Cloud Connect app. It is distinct from Cisco Cloud Control Studio Agent Builder.",
            product_stage="ga",
        )
    )
    coverage.append(
        coverage_entry(
            "ai_toolkit.agent_launchpad_knowledge_base_connections",
            "Agent Launchpad LLM and knowledge connections",
            agent_launchpad_repo_status,
            AI_TOOLKIT["connections_url"],
            f"Agent creation requires at least one supported LLM connection: {AGENT_LAUNCHPAD['supported_llm_providers']}. {AGENT_LAUNCHPAD['unsupported_llm_sentence']} Adding knowledge-base and MCP connections requires the edit_agent_connections capability, which the package grants to mltk_admin. Validate provider, region, and identifier values in the UI or secret store; render no credential values.",
            product_stage="ga",
        )
    )
    coverage.append(
        coverage_entry(
            "ai_toolkit.agent_launchpad_mcp_connections",
            "Agent Launchpad MCP server connections",
            agent_launchpad_repo_status,
            agent_launchpad_doc_url,
            f"Supported MCP providers are {AGENT_LAUNCHPAD['supported_mcp_providers']}. A single agent can hold multiple connections of the same provider type. Validate endpoint consent, tool scope, the edit_agent_connections capability, and the {AGENT_LAUNCHPAD['allowed_domains_setting']} egress allowlist without rendering authorization tokens.",
            product_stage="ga",
        )
    )
    coverage.append(
        coverage_entry(
            "ai_toolkit.agent_skills",
            "Agent Launchpad Agent Skills",
            agent_launchpad_repo_status,
            agent_launchpad_doc_url,
            "Agent Skills are reusable named instruction sets that grant agents specialized capabilities. Validate skill naming, instruction review, and ownership before attaching a skill to a production agent.",
            product_stage="ga",
        )
    )
    coverage.append(
        coverage_entry(
            "ai_toolkit.aiagent_command",
            "aiagent ML-SPL command",
            agent_launchpad_repo_status,
            AI_TOOLKIT["ml_spl_commands_url"],
            f"The aiagent command is generally available as of AI Toolkit {AGENT_LAUNCHPAD['ga_since']} and ships in the public package; it is no longer preview-gated. Documented parameters are agent_name (required) and prompt (optional when the agent defines a task prompt). Invocation needs the run_agents capability and an agent in the Available and enabled state. The command is marked is_risky, so it trips SPL safeguards. Validate against representative non-sensitive input.",
            product_stage="ga",
        )
    )
    coverage.append(
        coverage_entry(
            "ai_toolkit.agent_run_history",
            "Agent Launchpad run history",
            agent_launchpad_repo_status,
            agent_launchpad_doc_url,
            f"Run history is an in-product page filtered by time range, agent name, and owner, and it is visible only to the agent owner or a shared role. The package stores run history through {AGENT_LAUNCHPAD['run_history_index_setting']}, so no customer-created run-history index is required. If the index is redirected away from the default, review capacity, retention, ACLs, and sensitive prompt or tool content with the index owner; this skill does not create or modify indexes.",
            product_stage="ga",
        )
    )
    coverage.append(
        coverage_entry(
            "ai_toolkit.llm_ai_command",
            "LLM and ai command readiness",
            "manual_handoff",
            AI_TOOLKIT["ai_command_url"],
            "Render provider setup handoffs for OpenAI-compatible, AWS Bedrock, AWS SageMaker, GCP Vertex AI, and private model endpoints; secrets stay file-backed.",
        )
    )
    coverage.append(
        coverage_entry(
            "ai_toolkit.connections_tab",
            "Connections tab readiness",
            "manual_handoff",
            AI_TOOLKIT["connections_url"],
            "Validate AI Toolkit Connections entries for LLM providers and DSDL container endpoints without exposing provider secrets. In 6.0.2 this page lives under the Connections, containers, and agents documentation section.",
        )
    )
    coverage.append(
        coverage_entry(
            "ai_toolkit.container_management",
            "Container Management tab readiness",
            "manual_handoff",
            AI_TOOLKIT["container_management_url"],
            "Confirm container connection visibility, DSDL linkage, and runtime ownership before enabling container-backed workflows.",
        )
    )
    coverage.append(
        coverage_entry(
            "ai_toolkit.onnx",
            "ONNX model upload and apply",
            "manual_handoff",
            AI_TOOLKIT["onnx_url"],
            "Validate ONNX upload/apply readiness and multi-output model behavior in AI Toolkit. Uploads require the upload_onnx_model_file capability alongside upload_lookup_files.",
        )
    )
    coverage.append(
        coverage_entry(
            "ai_toolkit.model_inventory",
            "Model inventory and retraining risk",
            "manual_handoff",
            AI_TOOLKIT["model_permissions_url"],
            "Inventory trained models and flag MLTK pre-5.3 models for retraining compatibility review. Refit models built against an earlier PSC release after upgrading to PSC 4.3.4.",
        )
    )
    coverage.append(
        coverage_entry(
            "ai_toolkit.alerting",
            "Alerts from ML and anomaly outputs",
            "manual_handoff",
            AI_TOOLKIT["experiments_url"],
            "Review saved searches, scheduled retraining, adaptive thresholds, alert ownership, and downstream ITSI/ES/SOAR handoffs. Agents can also be wired as a Run AI Agent alert trigger action, which needs the same alert-ownership review.",
        )
    )

    for target, psc in PSC_TARGETS.items():
        if psc["legacy"]:
            status = "eol_migration"
            summary = "Legacy 32-bit PSC is cataloged for migration only and is blocked for new AI Toolkit installs."
        elif target == psc_target:
            status = "planned"
            summary = f"Selected compatible PSC target for this plan: {psc['app_name']} {psc['version']}."
        else:
            status = "not_applicable"
            summary = "Current PSC variant is covered but not selected for this target search-head OS."
        coverage.append(
            coverage_entry(
                f"psc.{target}",
                psc["label"],
                status,
                psc["source_url"],
                summary,
                product_stage="deprecated" if psc["legacy"] else "ga",
            )
        )

    coverage.append(
        coverage_entry(
            "dsdl.package",
            "Splunk App for Data Science and Deep Learning package",
            "planned" if include_dsdl else "not_applicable",
            DSDL["source_url"],
            f"Install latest compatible DSDL app 4607 after AI Toolkit and PSC when custom model runtimes are in scope; latest audited release is {DSDL['version']}."
            if include_dsdl
            else "DSDL is covered by this skill but not selected in this plan.",
        )
    )
    coverage.append(
        coverage_entry(
            "dsdl.setup_page",
            "DSDL setup and app configuration",
            "manual_handoff" if include_dsdl else "not_applicable",
            DSDL["components_doc_url"],
            "Validate setup-page configuration, app-to-runtime mapping, endpoint reachability, and search-head placement.",
        )
    )
    coverage.append(
        coverage_entry(
            f"dsdl.runtime.{dsdl_runtime}",
            f"DSDL runtime handoff: {dsdl_runtime}",
            "manual_handoff" if include_dsdl else "not_applicable",
            "https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-splunk-app-for-data-science-and-deep-learning",
            DSDL_RUNTIME_NOTES[dsdl_runtime],
        )
    )
    for surface in (
        "jupyter_notebooks",
        "custom_images",
        "gpu_hpc",
        "airgap",
        "llm_rag",
        "model_governance",
    ):
        coverage.append(
            coverage_entry(
                f"dsdl.{surface}",
                f"DSDL {surface.replace('_', ' ')}",
                "manual_handoff" if include_dsdl else "not_applicable",
                "https://splunkbase.splunk.com/app/4607",
                "Render an operator handoff for this DSDL runtime/model-development surface.",
            )
        )
    for surface, summary in {
        "api_endpoint": "Validate DSDL API endpoint reachability, auth boundary, TLS posture, and search-head to runtime network path.",
        "container_health": "Validate container health checks, JupyterLab availability, notebook server ownership, and model execution logs.",
        "hec_observability": "Plan HEC and Splunk Observability handoffs for inference results, runtime logs, and container performance telemetry.",
    }.items():
        coverage.append(
            coverage_entry(
                f"dsdl.{surface}",
                f"DSDL {surface.replace('_', ' ')}",
                "manual_handoff" if include_dsdl else "not_applicable",
                DSDL["components_doc_url"],
                summary,
            )
        )

    for key, app in LEGACY_APPS.items():
        coverage.append(
            coverage_entry(
                f"legacy.{key}",
                app["app_name"],
                "eol_migration" if legacy_audit else "not_applicable",
                app["source_url"],
                "Audit existing installs and migrate new anomaly work to current AI Toolkit workflows; do not install by default."
                if legacy_audit
                else "Legacy app is covered by the skill but audit was not requested.",
                product_stage="deprecated",
            )
        )

    return coverage


def build_apply_plan(ctx: dict[str, Any]) -> dict[str, Any]:
    psc = PSC_TARGETS[ctx["psc_target"]]
    steps: list[dict[str, Any]] = []
    if not psc["legacy"]:
        steps.append(
            install_step(
                "psc",
                psc["app_id"],
                psc["app_name"],
                f"Install/update latest compatible {psc['label']}; latest audited release is {psc['version']}.",
            )
        )
    steps.append(
        install_step(
            "ai-toolkit",
            AI_TOOLKIT["app_id"],
            AI_TOOLKIT["app_name"],
            f"Install/update latest compatible Splunk AI Toolkit; latest audited release is {AI_TOOLKIT['version']}.",
        )
    )
    if ctx["include_dsdl"]:
        steps.append(
            install_step(
                "dsdl",
                DSDL["app_id"],
                DSDL["app_name"],
                f"Install/update latest compatible DSDL; latest audited release is {DSDL['version']}.",
            )
        )
        steps.append(
            {
                "section": "dsdl-runtime",
                "automation": "manual_handoff",
                "summary": DSDL_RUNTIME_NOTES[ctx["dsdl_runtime"]],
                "command": [],
            }
        )
    if ctx["legacy_anomaly_audit"]:
        steps.append(
            {
                "section": "legacy-anomaly-migration",
                "automation": "audit_only",
                "summary": "Audit legacy anomaly apps and migrate workflows to AI Toolkit. No install command is emitted.",
                "command": [],
            }
        )
    return {
        "workflow": "splunk-ai-ml-toolkit-setup",
        "api_version": API_VERSION,
        "platform": ctx["platform"],
        "psc_target": ctx["psc_target"],
        "steps": steps,
    }


def install_step(section: str, app_id: str, app_name: str, summary: str) -> dict[str, Any]:
    return {
        "section": section,
        "automation": "delegated",
        "summary": summary,
        "app_id": app_id,
        "app_name": app_name,
        "command": [
            "bash",
            "skills/splunk-app-install/scripts/install_app.sh",
            "--source",
            "splunkbase",
            "--app-id",
            app_id,
            "--update",
        ],
    }


def validate_coverage(coverage: list[dict[str, str]]) -> list[str]:
    errors: list[str] = []
    for entry in coverage:
        key = entry.get("key", "")
        status = entry.get("status", "")
        product_stage = entry.get("product_stage", "")
        if status not in ALLOWED_STATUSES:
            errors.append(f"{key}: unsupported status {status!r}")
        if status == "unknown":
            errors.append(f"{key}: unknown status is not allowed")
        if product_stage not in ALLOWED_PRODUCT_STAGES:
            errors.append(f"{key}: unsupported product_stage {product_stage!r}")
        if not entry.get("source_url"):
            errors.append(f"{key}: missing source_url")
    return errors


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_coverage_markdown(path: Path, coverage: list[dict[str, str]]) -> None:
    lines = [
        "# Splunk AI/ML Toolkit Coverage Report",
        "",
        f"- Research verified: `{RESEARCH_VERIFIED}`",
        "- `Product stage` records the upstream lifecycle; `Repo status` records what this skill automates.",
        "",
        "| Key | Product stage | Repo status | Summary |",
        "| --- | --- | --- | --- |",
    ]
    for entry in coverage:
        lines.append(
            f"| `{entry['key']}` | `{entry['product_stage']}` | `{entry['status']}` | {entry['summary']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_doctor_report(path: Path, ctx: dict[str, Any], coverage: list[dict[str, str]]) -> None:
    counts: dict[str, int] = {}
    product_stage_counts: dict[str, int] = {}
    for entry in coverage:
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
        product_stage = entry["product_stage"]
        product_stage_counts[product_stage] = product_stage_counts.get(product_stage, 0) + 1
    lines = [
        "# Splunk AI/ML Toolkit Doctor Report",
        "",
        f"- Research verified: `{RESEARCH_VERIFIED}`",
        f"- Platform: `{ctx['platform']}`",
        f"- PSC target: `{ctx['psc_target']}`",
        f"- Include DSDL: `{str(ctx['include_dsdl']).lower()}`",
        f"- DSDL runtime: `{ctx['dsdl_runtime']}`",
        f"- Legacy anomaly audit: `{str(ctx['legacy_anomaly_audit']).lower()}`",
        "",
        "## Coverage Counts",
    ]
    for status in sorted(counts):
        lines.append(f"- `{status}`: {counts[status]}")
    lines.extend(["", "## Product Lifecycle Counts"])
    for product_stage in sorted(product_stage_counts):
        lines.append(f"- `{product_stage}`: {product_stage_counts[product_stage]}")
    if ctx["warnings"]:
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {warning}" for warning in ctx["warnings"])
    lines.extend(
        [
            "",
            "## Next Checks",
            "- Run live validation after package install.",
            f"- Confirm the AI Toolkit `{AI_TOOLKIT['version']}` and PSC `{AI_TOOLKIT['required_psc_version']}` pairing, then refit models built against an earlier PSC release.",
            "- Confirm AI Toolkit model permissions and retraining risk.",
            "- Confirm Agent Launchpad region eligibility, egress allowlist, and supported LLM provider before treating agent workflows as ready.",
            "- Keep open Cisco Time Series Model 1.0 deployment separate from the AI Toolkit Cisco Deep Time Series Model integration.",
            "- Confirm any DSDL runtime through the rendered handoff before production use.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_dsdl_handoff(path: Path, ctx: dict[str, Any]) -> None:
    runtime = ctx["dsdl_runtime"]
    lines = [
        "# DSDL Runtime Handoff",
        "",
        f"- Runtime mode: `{runtime}`",
        f"- Status: `{('manual_handoff' if ctx['include_dsdl'] else 'not_applicable')}`",
        f"- Guidance: {DSDL_RUNTIME_NOTES[runtime]}",
        "",
        "## Operator Checklist",
        "- Confirm AI Toolkit and compatible PSC are installed on the search tier.",
        "- Confirm DSDL package is installed only when custom model/runtime workflows are in scope.",
        "- Keep registry credentials, access tokens, and TLS keys in local files or Kubernetes Secrets.",
        "- Validate image provenance, RBAC, storage, network path, and resource limits.",
        "- Validate notebook/model ownership, permissions, and promotion workflow.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_agent_launchpad_handoff(path: Path, ctx: dict[str, Any]) -> None:
    is_cloud = ctx["platform"] == "cloud"
    lines = [
        "# Splunk AI Toolkit Agent Launchpad Handoff",
        "",
        f"- Product stage: `{AGENT_LAUNCHPAD['product_stage']}` as of `{AGENT_LAUNCHPAD['status_as_of']}`",
        f"- Lifecycle label: generally available since AI Toolkit `{AGENT_LAUNCHPAD['ga_since']}`; it replaced the Agent Builder feature preview.",
        f"- Target platform: `{ctx['platform']}`",
        "- Repo status: `manual_handoff`",
        "- Product boundary: this is an AI Toolkit feature inside Splunk, not Cisco Cloud Control Studio Agent Builder.",
        f"- Agent Launchpad source: {AGENT_LAUNCHPAD['doc_url']}",
        f"- Splunk Enterprise source: {AGENT_LAUNCHPAD['on_prem_doc_url']}",
        f"- GA release note source: {AGENT_LAUNCHPAD['release_notes_url']}",
        f"- Cloud Control Studio boundary source: {AGENT_LAUNCHPAD['cloud_control_studio_url']}",
        "",
        "## Availability Gate",
        f"- Installing public AI Toolkit `{AI_TOOLKIT['version']}` ships the Agent Launchpad views and the `aiagent` command. Enrolling in a preview program is not part of the path.",
        "- Splunk Cloud Platform must be in a documented supported AWS region, and the region's Agent Launchpad egress IP must be added to the stack spec `accessRules.apiAllowlistIP`.",
        "- Splunk Enterprise reaches Agent Launchpad through the Splunk Cloud Connect app rather than the AI Toolkit package alone.",
        f"- Confirm the PSC pairing: AI Toolkit `{AI_TOOLKIT['version']}` requires PSC `{AI_TOOLKIT['required_psc_version']}` on Python `{AI_TOOLKIT['python_version']}`.",
        "- Require `edit_agent_connections` to add knowledge-base or MCP connections and `run_agents` to create or invoke agents; the package grants both to `mltk_admin`.",
        "",
        "## Connection Gate",
        f"- Configure at least one supported LLM connection before creating an agent: {AGENT_LAUNCHPAD['supported_llm_providers']}.",
        f"- Agent Launchpad does not support {AGENT_LAUNCHPAD['unsupported_llm_providers']}; pick a supported provider instead of reusing an unsupported Connections entry.",
        f"- Supported MCP providers are {AGENT_LAUNCHPAD['supported_mcp_providers']}.",
        "- A single agent can use multiple MCP connections of the same provider type; confirm which environment each connection targets before sharing the agent.",
        f"- Review the {AGENT_LAUNCHPAD['allowed_domains_setting']} egress allowlist so agent traffic is constrained to approved domains.",
        "- Enter authorization tokens and provider credentials only in the approved UI or secret store. This renderer never writes those values.",
        "",
        "## Agent and Invocation Gate",
        "- Agents are private by default. Review ownership and sharing before broader use.",
        "- Validate agent name, description, LLM connection, temperature, max tokens, reasoning effort, system prompt, default prompt, attached Agent Skills, and MCP connections.",
        "- An agent must reach the `Available` state and stay enabled before `aiagent` can invoke it.",
        "- Test `aiagent` with `agent_name` and an optional `prompt` on representative non-sensitive data; the command is `is_risky`, so expect the SPL safeguard prompt.",
        "- Review any `Run AI Agent` alert trigger action the same way as the search that carries it, because alert name, time, results, and search are passed to the agent automatically.",
        "",
        "## Run-History Gate",
        f"- Run history is an in-product page, not a customer-provisioned index. The package stores it through {AGENT_LAUNCHPAD['run_history_index_setting']}.",
        "- Run history is visible only to the agent owner or a role the agent is shared with; confirm that matches the intended review audience.",
        "- If the run-history index is redirected away from the package default, obtain index-owner approval for capacity, retention, ACLs, and sensitive prompt or tool content.",
        "- This skill does not create or modify indexes and does not mutate agent state.",
    ]
    if not is_cloud:
        lines.extend(
            [
                "",
                "## Splunk Enterprise Gate",
                "- Treat Splunk Cloud Connect as a separate product decision with its own install, connectivity, and data-governance review.",
                "- Do not report Agent Launchpad as ready on Splunk Enterprise until Splunk Cloud Connect is installed and its region is confirmed.",
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_time_series_model_handoff(path: Path, ctx: dict[str, Any]) -> None:
    ctsm = TIME_SERIES_MODELS["ctsm_open_1_0"]
    cdtsm = TIME_SERIES_MODELS["cdtsm_integrated"]
    lines = [
        "# Cisco Time-Series Model Handoff",
        "",
        f"- Target platform: `{ctx['platform']}`",
        f"- Research verified: `{RESEARCH_VERIFIED}`",
        "",
        "## Cisco Time Series Model 1.0",
        f"- Product stage: `{ctsm['product_stage']}` open-weight release",
        f"- Model ID: `{ctsm['model_id']}`",
        f"- License: `{ctsm['license']}`",
        f"- Model card: {ctsm['source_url']}",
        f"- Source and self-hosting assets: {ctsm['github_url']}",
        f"- Documented DSDL example: {ctsm['dsdl_url']}",
        "- The open model can be self-hosted or used through a reviewed DSDL runtime. Installing AI Toolkit does not itself install the open model weights or runtime.",
        "",
        "## Cisco Deep Time Series Model",
        f"- Product stage: `{cdtsm['product_stage']}` since AI Toolkit `{cdtsm['ga_since']}`; earlier releases documented it as a feature preview.",
        f"- Feature documentation: {cdtsm['source_url']}",
        f"- Enterprise self-hosting documentation: {cdtsm['on_prem_url']}",
        "- This is the AI Toolkit-integrated forecasting, anomaly-detection, and predictive-alerting experience powered by Cisco time-series model technology.",
        "- Splunk Cloud uses the Splunk-hosted model on dedicated GPU capacity in a supported region. Splunk Enterprise requires a separately deployed open Cisco Time Series Model service, endpoint configuration, and a matching bearer token stored in Splunk encrypted storage.",
        "- Invoke it as `apply CDTSM <fields_to_forecast>`; wildcard forecast fields are supported from `6.0.0`, and `by` plus `fill_null` are supported from `5.7.4`.",
        f"- Usage control: {cdtsm['rate_limit']}. Opt out with {cdtsm['opt_out_setting']}.",
        "- Region, model-server health, capacity, TLS, and air-gapped model provenance require validation.",
        "",
        "## No-Conflation Gate",
        "- Open model availability and the AI Toolkit CDTSM integration are still separately governed layers, even though both are now generally available.",
        "- CDTSM access does not grant a generic hosted-LLM connection or install DSDL; the hosted LLM list in Connections does not include CDTSM.",
        "- Keep model weights, model service, DSDL container execution, hosted Splunk execution, and AI Toolkit UI/command availability as separately validated layers.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_legacy_migration(path: Path, ctx: dict[str, Any]) -> None:
    lines = [
        "# Legacy Anomaly Migration",
        "",
        f"- Audit requested: `{str(ctx['legacy_anomaly_audit']).lower()}`",
        "- Splunk App for Anomaly Detection (`6843`) is migration-only and must not be installed on Splunk 10.5.",
        "- Smart Alerts Assistant beta (`6415`) is migration-only and must not be installed on Splunk 10.5.",
        "- PSC Linux 32-bit (`2884`) is migration-only; use a supported 64-bit PSC package on Splunk 10.5.",
        "- New anomaly work should route to Splunk AI Toolkit assistants, ML-SPL searches, or Cisco Deep Time Series anomaly workflows.",
        "",
        "## Audit Targets",
        "- Installed app metadata and version",
        "- Saved searches and alerts owned by legacy apps",
        "- Model lookups and dependencies",
        "- Dashboard links or scheduled reports used by operators",
        "- Replacement AI Toolkit workflow and validation owner",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def discover() -> dict[str, Any]:
    return {
        "api_version": API_VERSION,
        "research_verified": RESEARCH_VERIFIED,
        "ai_toolkit": AI_TOOLKIT,
        "agent_launchpad": AGENT_LAUNCHPAD,
        "time_series_models": TIME_SERIES_MODELS,
        "psc_targets": PSC_TARGETS,
        "dsdl": DSDL,
        "legacy_apps": LEGACY_APPS,
        "dsdl_runtimes": DSDL_RUNTIME_NOTES,
        "documented_ml_spl_commands": list(DOCUMENTED_ML_SPL_COMMANDS),
        "package_only_ml_spl_commands": list(PACKAGE_ONLY_ML_SPL_COMMANDS),
        "risky_ml_spl_commands": list(RISKY_ML_SPL_COMMANDS),
        "allowed_statuses": sorted(ALLOWED_STATUSES),
        "allowed_product_stages": sorted(ALLOWED_PRODUCT_STAGES),
    }


def render(args: argparse.Namespace) -> dict[str, Any]:
    ctx = build_context(args)
    coverage = build_coverage(ctx)
    errors = validate_coverage(coverage)
    if errors:
        raise SystemExit("ERROR: coverage validation failed: " + "; ".join(errors))
    apply_plan = build_apply_plan(ctx)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        output_dir / "coverage-report.json",
        {
            "api_version": API_VERSION,
            "research_verified": RESEARCH_VERIFIED,
            "coverage": coverage,
        },
    )
    write_coverage_markdown(output_dir / "coverage-report.md", coverage)
    write_json(output_dir / "apply-plan.json", apply_plan)
    write_doctor_report(output_dir / "doctor-report.md", ctx, coverage)
    write_dsdl_handoff(output_dir / "dsdl-runtime-handoff.md", ctx)
    write_agent_launchpad_handoff(output_dir / "agent-launchpad-handoff.md", ctx)
    write_time_series_model_handoff(output_dir / "time-series-model-handoff.md", ctx)
    write_legacy_migration(output_dir / "legacy-anomaly-migration.md", ctx)
    return {
        "api_version": API_VERSION,
        "research_verified": RESEARCH_VERIFIED,
        "output_dir": str(output_dir),
        "coverage_count": len(coverage),
        "status_counts": status_counts(coverage),
        "product_stage_counts": product_stage_counts(coverage),
        "apply_steps": len(apply_plan["steps"]),
        "warnings": ctx["warnings"],
    }


def status_counts(coverage: list[dict[str, str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in coverage:
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    return counts


def product_stage_counts(coverage: list[dict[str, str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in coverage:
        stage = entry["product_stage"]
        counts[stage] = counts.get(stage, 0) + 1
    return counts


def main() -> int:
    args = parse_args()
    if args.discover:
        print(json.dumps(discover(), indent=2, sort_keys=True))
        return 0
    summary = render(args)
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(f"Rendered Splunk AI/ML Toolkit plan to {summary['output_dir']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        sys.exit(0)

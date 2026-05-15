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
ALLOWED_STATUSES = {
    "planned",
    "validated",
    "delegated",
    "manual_handoff",
    "eol_migration",
    "blocked",
    "not_applicable",
}

AI_TOOLKIT = {
    "app_id": "2890",
    "app_name": "Splunk_ML_Toolkit",
    "version": "5.7.3",
    "date": "April 19, 2026",
    "source_url": "https://splunkbase.splunk.com/app/2890",
    "install_doc_url": "https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit/5.7.3/install-and-upgrade-the-ai-toolkit/install-the-ai-toolkit",
}

DSDL = {
    "app_id": "4607",
    "app_name": "mltk-container",
    "version": "5.2.3",
    "date": "February 5, 2026",
    "source_url": "https://splunkbase.splunk.com/app/4607",
    "components_doc_url": "https://help.splunk.com/en/splunk-enterprise/apply-machine-learning/use-splunk-app-for-data-science-and-deep-learning/5.2/about-the-splunk-app-for-data-science-and-deep-learning/splunk-app-for-data-science-and-deep-learning-components",
}

PSC_TARGETS = {
    "linux64": {
        "app_id": "2882",
        "app_name": "Splunk_SA_Scientific_Python_linux_x86_64",
        "label": "PSC Linux 64-bit",
        "version": "4.3.1",
        "date": "February 27, 2026",
        "source_url": "https://splunkbase.splunk.com/app/2882",
        "legacy": False,
    },
    "windows64": {
        "app_id": "2883",
        "app_name": "Splunk_SA_Scientific_Python_windows_x86_64",
        "label": "PSC Windows 64-bit",
        "version": "4.3.1",
        "date": "February 27, 2026",
        "source_url": "https://splunkbase.splunk.com/app/2883",
        "legacy": False,
    },
    "mac-intel": {
        "app_id": "2881",
        "app_name": "Splunk_SA_Scientific_Python_darwin_x86_64",
        "label": "PSC Mac Intel",
        "version": "4.3.1",
        "date": "February 27, 2026",
        "source_url": "https://splunkbase.splunk.com/app/2881",
        "legacy": False,
    },
    "mac-arm": {
        "app_id": "6785",
        "app_name": "Splunk_SA_Scientific_Python_darwin_arm64",
        "label": "PSC Mac Apple Silicon",
        "version": "4.3.1",
        "date": "February 27, 2026",
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
        warnings.append("PSC Linux 32-bit is legacy-only and must not be used for new AI Toolkit installs.")
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
) -> dict[str, str]:
    if status not in ALLOWED_STATUSES:
        raise ValueError(f"invalid coverage status for {key}: {status}")
    return {
        "key": key,
        "title": title,
        "status": status,
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
    coverage: list[dict[str, str]] = []

    coverage.append(
        coverage_entry(
            "ai_toolkit.package",
            "Splunk AI Toolkit / MLTK package",
            "planned",
            AI_TOOLKIT["source_url"],
            f"Install or update latest compatible {AI_TOOLKIT['app_name']} from Splunkbase app {AI_TOOLKIT['app_id']}; latest audited release is {AI_TOOLKIT['version']}.",
        )
    )
    coverage.append(
        coverage_entry(
            "ai_toolkit.compatibility",
            "AI Toolkit and PSC compatibility",
            "manual_handoff",
            AI_TOOLKIT["install_doc_url"],
            f"Validate AI Toolkit {AI_TOOLKIT['version']} with PSC 4.3.1 and supported Splunk platform versions before upgrade.",
        )
    )
    coverage.append(
        coverage_entry(
            "ai_toolkit.ml_spl_commands",
            "ML-SPL command surface",
            "manual_handoff",
            "https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit",
            "Validate fit/apply/summary/score/listmodels/deletemodel/sample and app-owned ML-SPL metadata after install.",
        )
    )
    coverage.append(
        coverage_entry(
            "ai_toolkit.permissions_and_safeguards",
            "ML command permissions and safeguards",
            "manual_handoff",
            "https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit/5.7.3",
            "Review ML command permissions, algorithm access, search safeguards, and performance-cost settings for production users.",
        )
    )
    coverage.append(
        coverage_entry(
            "ai_toolkit.assistants",
            "AI Toolkit assistants and experiments",
            "manual_handoff",
            "https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit",
            "Cover prediction, clustering, forecasting, outlier, anomaly, and experiment-management workflows.",
        )
    )
    coverage.append(
        coverage_entry(
            "ai_toolkit.anomaly_cisco_deep_time_series",
            "Cisco Deep Time Series anomaly detection",
            "manual_handoff",
            AI_TOOLKIT["source_url"],
            "AI Toolkit 5.7.3 introduced anomaly detection through Cisco Deep Time Series Model; validate workflow availability in the app UI.",
        )
    )
    coverage.append(
        coverage_entry(
            "ai_toolkit.llm_ai_command",
            "LLM and ai command readiness",
            "manual_handoff",
            "https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit",
            "Render provider setup handoffs for OpenAI-compatible, AWS Bedrock, AWS SageMaker, and private model endpoints; secrets stay file-backed.",
        )
    )
    coverage.append(
        coverage_entry(
            "ai_toolkit.connections_tab",
            "Connections tab readiness",
            "manual_handoff",
            "https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit/5.7.3",
            "Validate AI Toolkit Connections entries for LLM providers and DSDL container endpoints without exposing provider secrets.",
        )
    )
    coverage.append(
        coverage_entry(
            "ai_toolkit.container_management",
            "Container Management tab readiness",
            "manual_handoff",
            "https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit/5.7.3",
            "Confirm container connection visibility, DSDL linkage, and runtime ownership before enabling container-backed workflows.",
        )
    )
    coverage.append(
        coverage_entry(
            "ai_toolkit.onnx",
            "ONNX model upload and apply",
            "manual_handoff",
            "https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit",
            "Validate ONNX upload/apply readiness and multi-output model behavior in AI Toolkit.",
        )
    )
    coverage.append(
        coverage_entry(
            "ai_toolkit.model_inventory",
            "Model inventory and retraining risk",
            "manual_handoff",
            "https://splunkbase.splunk.com/app/2890",
            "Inventory trained models and flag MLTK pre-5.3 models for retraining compatibility review.",
        )
    )
    coverage.append(
        coverage_entry(
            "ai_toolkit.alerting",
            "Alerts from ML and anomaly outputs",
            "manual_handoff",
            "https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit/5.7.3",
            "Review saved searches, scheduled retraining, adaptive thresholds, alert ownership, and downstream ITSI/ES/SOAR handoffs.",
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
        if status not in ALLOWED_STATUSES:
            errors.append(f"{key}: unsupported status {status!r}")
        if status == "unknown":
            errors.append(f"{key}: unknown status is not allowed")
        if not entry.get("source_url"):
            errors.append(f"{key}: missing source_url")
    return errors


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_coverage_markdown(path: Path, coverage: list[dict[str, str]]) -> None:
    lines = [
        "# Splunk AI/ML Toolkit Coverage Report",
        "",
        "| Key | Status | Summary |",
        "| --- | --- | --- |",
    ]
    for entry in coverage:
        lines.append(f"| `{entry['key']}` | `{entry['status']}` | {entry['summary']} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_doctor_report(path: Path, ctx: dict[str, Any], coverage: list[dict[str, str]]) -> None:
    counts: dict[str, int] = {}
    for entry in coverage:
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    lines = [
        "# Splunk AI/ML Toolkit Doctor Report",
        "",
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
    if ctx["warnings"]:
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {warning}" for warning in ctx["warnings"])
    lines.extend(
        [
            "",
            "## Next Checks",
            "- Run live validation after package install.",
            "- Confirm AI Toolkit model permissions and retraining risk.",
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


def write_legacy_migration(path: Path, ctx: dict[str, Any]) -> None:
    lines = [
        "# Legacy Anomaly Migration",
        "",
        f"- Audit requested: `{str(ctx['legacy_anomaly_audit']).lower()}`",
        "- Splunk App for Anomaly Detection (`6843`) is migration-only in this skill.",
        "- Smart Alerts Assistant beta (`6415`) is migration-only in this skill.",
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
        "ai_toolkit": AI_TOOLKIT,
        "psc_targets": PSC_TARGETS,
        "dsdl": DSDL,
        "legacy_apps": LEGACY_APPS,
        "dsdl_runtimes": DSDL_RUNTIME_NOTES,
        "allowed_statuses": sorted(ALLOWED_STATUSES),
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
    write_json(output_dir / "coverage-report.json", {"api_version": API_VERSION, "coverage": coverage})
    write_coverage_markdown(output_dir / "coverage-report.md", coverage)
    write_json(output_dir / "apply-plan.json", apply_plan)
    write_doctor_report(output_dir / "doctor-report.md", ctx, coverage)
    write_dsdl_handoff(output_dir / "dsdl-runtime-handoff.md", ctx)
    write_legacy_migration(output_dir / "legacy-anomaly-migration.md", ctx)
    return {
        "api_version": API_VERSION,
        "output_dir": str(output_dir),
        "coverage_count": len(coverage),
        "status_counts": status_counts(coverage),
        "apply_steps": len(apply_plan["steps"]),
        "warnings": ctx["warnings"],
    }


def status_counts(coverage: list[dict[str, str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in coverage:
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
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

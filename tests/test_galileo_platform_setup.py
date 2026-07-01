"""Regression coverage for galileo-platform-setup."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import importlib.util
from argparse import Namespace
from pathlib import Path
from types import ModuleType


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills/galileo-platform-setup"
SETUP = SKILL_DIR / "scripts/setup.sh"
VALIDATE = SKILL_DIR / "scripts/validate.sh"
RENDER = SKILL_DIR / "scripts/render_assets.py"
BRIDGE = SKILL_DIR / "scripts/galileo_to_splunk_hec.py"
LIFECYCLE = SKILL_DIR / "scripts/galileo_object_lifecycle.py"
LUNA = SKILL_DIR / "scripts/galileo_luna_scorers.py"
GALILEO_CONSOLE_ARGS = ("--galileo-console-url", "https://console.demo-v2.galileocloud.io/")


def run_cmd(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(args),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if check:
        assert result.returncode == 0, result.stdout + result.stderr
    return result


def rendered_text(root: Path) -> str:
    chunks: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            chunks.append(path.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def load_bridge() -> ModuleType:
    spec = importlib.util.spec_from_file_location("galileo_to_splunk_hec", BRIDGE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_setup_help_lists_apply_sections() -> None:
    result = run_cmd("bash", str(SETUP), "--help")
    combined = result.stdout + result.stderr

    assert "--o11y-only" in combined
    assert "--luna-list-only" in combined
    for section in [
        "readiness",
        "object-lifecycle",
        "luna-scorers",
        "observe-export",
        "observe-runtime",
        "protect-runtime",
        "evaluate-assets",
        "multimodal-assets",
        "splunk-hec",
        "splunk-otlp",
        "otel-collector",
        "dashboards",
        "detectors",
    ]:
        assert section in combined


def test_default_render_emits_plan_coverage_and_handoff_scripts(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    result = run_cmd(
        "bash",
        str(SETUP),
        "--render",
        "--output-dir",
        str(output_dir),
        *GALILEO_CONSOLE_ARGS,
        "--json",
    )
    payload = json.loads(result.stdout)

    assert payload["output_dir"] == str(output_dir.resolve())
    assert (output_dir / "apply-plan.json").is_file()
    assert (output_dir / "coverage-report.json").is_file()
    assert (output_dir / "handoff.md").is_file()
    assert (output_dir / "readiness/readiness-report.json").is_file()
    assert (output_dir / "lifecycle/object-lifecycle-manifest.example.json").is_file()
    assert (output_dir / "lifecycle/luna-scorer-map.example.json").is_file()
    assert (output_dir / "lifecycle/product-coverage-matrix.json").is_file()
    assert (output_dir / "lifecycle/product-coverage-matrix.md").is_file()
    assert (output_dir / "runtime/python-opentelemetry-env.sh").is_file()
    assert (output_dir / "runtime/codex-notify-galileo-handoff.md").is_file()
    assert (output_dir / "runtime/python-galileo-protect.py").is_file()
    assert (output_dir / "evaluate/evaluate-assets.yaml").is_file()
    assert (output_dir / "evaluate/multimodal-metrics-handoff.yaml").is_file()
    assert (output_dir / "multimodal/multimodal-observability.md").is_file()
    assert (output_dir / "multimodal/multimodal-intake.example.json").is_file()
    assert (output_dir / "splunk-platform/hec-event-sample.json").is_file()
    assert (output_dir / "splunk-platform/export-records-request.json").is_file()
    assert (output_dir / "splunk-platform/multimodal-search-examples.spl").is_file()
    assert (output_dir / "otel/collector-galileo-fanout.yaml").is_file()
    matrix = json.loads((output_dir / "lifecycle/product-coverage-matrix.json").read_text(encoding="utf-8"))
    surfaces = {item["surface"] for item in matrix}
    for surface in [
        "API keys, auth, users, groups, and RBAC",
        "REST API base URL, custom deployments, and healthcheck",
        "SSO, OIDC, SAML, and enterprise identity",
        "Dataset query, preview, content mutation, and bulk maintenance",
        "Prompt templates, rendering, and version utilities",
        "Evaluate workflow runs",
        "Python and TypeScript SDK parity",
        "Experiment columns, metrics APIs, and paginated search",
        "Metric taxonomy, autotune, and use-case categories",
        "Custom scorers and scorer validation",
        "Scorer governance, health scores, and restore flows",
        "Luna and model/provider integrations",
        "Luna-2 fine-tuning and metric evaluation workflows",
        "Luna Studio UI and SDK training lifecycle",
        "Provider integrations, model aliases, costs, and pricing",
        "Provider integration selection, status, and Databricks helpers",
        "Codex notify turn logging",
        "Tags, metadata, run labels, and filter hygiene",
        "Enterprise data retention, TTL, redaction, and privacy controls",
        "Trace query, columns, recompute, update, and delete maintenance",
        "Trace metrics, counts, partial queries, and live logging APIs",
        "Agent Graph, Logs UI, Messages UI, and console debugging views",
        "Distributed tracing and multi-service propagation",
        "Multimodal observability",
        "OpenTelemetry and OpenInference",
        "Third-party framework integrations and wrappers",
        "MCP tool-call logging and tool spans",
        "Galileo alerts and notifications",
        "Annotation templates, ratings, and queues",
        "Feedback templates and ratings",
        "Trends dashboards, widgets, sections, Signals, and insights",
        "Run insights, health scores, and token usage",
        "Jobs, async tasks, validation status, and progress polling",
        "Enterprise deployment, system users, and organization jobs",
        "Galileo MCP Server and IDE developer tooling",
        "Playgrounds, sample projects, unit tests, and CI experiments",
        "Cookbooks, use-case guides, and starter examples",
        "Error catalog, troubleshooting, and support diagnostics",
        "Release notes and version compatibility",
        "Splunk destinations",
    ]:
        assert surface in surfaces
    codex_notify = (output_dir / "runtime/codex-notify-galileo-handoff.md").read_text(encoding="utf-8")
    assert "Galileo MCP server" in codex_notify
    assert "POST /v2/projects/{project_id}/traces" in codex_notify
    assert "traces/count" in codex_notify
    for script in [
        "apply-readiness.sh",
        "apply-object-lifecycle.sh",
        "apply-luna-scorers.sh",
        "apply-observe-export.sh",
        "apply-observe-runtime.sh",
        "apply-protect-runtime.sh",
        "apply-evaluate-assets.sh",
        "apply-multimodal-assets.sh",
        "apply-splunk-hec.sh",
        "apply-splunk-otlp.sh",
        "apply-otel-collector.sh",
        "apply-dashboards.sh",
        "apply-detectors.sh",
        "apply-selected.sh",
    ]:
        assert (output_dir / "scripts" / script).is_file()
        assert (output_dir / "scripts" / script).stat().st_mode & 0o111

    run_cmd("bash", str(VALIDATE), "--output-dir", str(output_dir))


def test_hec_handoff_delegates_to_hec_service_with_token_file_only(tmp_path: Path) -> None:
    secret = "SPLUNK_HEC_SECRET_SHOULD_NOT_RENDER"
    token_file = tmp_path / "hec.token"
    token_file.write_text(secret, encoding="utf-8")
    output_dir = tmp_path / "rendered"

    run_cmd(
        "bash",
        str(SETUP),
        "--render",
        "--output-dir",
        str(output_dir),
        *GALILEO_CONSOLE_ARGS,
        "--splunk-hec-token-file",
        str(token_file),
        "--splunk-index",
        "galileo_prod",
    )

    script = (output_dir / "scripts/apply-splunk-hec.sh").read_text(encoding="utf-8")
    assert "splunk-hec-service-setup/scripts/setup.sh" in script
    assert "--token-file" in script
    assert not re.search(r"--splunk-hec-token(?:=|\s)", script)
    assert secret not in rendered_text(output_dir)
    assert str(token_file) in script


def test_otlp_handoff_delegates_to_splunk_connect_for_otlp(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    run_cmd("bash", str(SETUP), "--render", "--output-dir", str(output_dir), *GALILEO_CONSOLE_ARGS)

    script = (output_dir / "scripts/apply-splunk-otlp.sh").read_text(encoding="utf-8")
    assert "splunk-connect-for-otlp-setup/scripts/setup.sh" in script
    assert "--hec-token-file" in script
    assert "--configure-input" in script


def test_otel_collector_handoff_delegates_to_splunk_otel_collector(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    run_cmd(
        "bash",
        str(SETUP),
        "--render",
        "--output-dir",
        str(output_dir),
        *GALILEO_CONSOLE_ARGS,
        "--realm",
        "us0",
    )

    script = (output_dir / "scripts/apply-otel-collector.sh").read_text(encoding="utf-8")
    assert "splunk-observability-otel-collector-setup/scripts/setup.sh" in script
    assert "--o11y-token-file" in script
    assert "--platform-hec-token-file" in script
    assert "--render-platform-hec-helper" in script


def test_o11y_only_otel_collector_handoff_omits_platform_hec(tmp_path: Path) -> None:
    output_dir = tmp_path / "rendered"
    run_cmd(
        "bash",
        str(SETUP),
        "--render",
        "--output-dir",
        str(output_dir),
        *GALILEO_CONSOLE_ARGS,
        "--o11y-only",
        "--realm",
        "us0",
    )

    script = (output_dir / "scripts/apply-otel-collector.sh").read_text(encoding="utf-8")
    assert "splunk-observability-otel-collector-setup/scripts/setup.sh" in script
    assert "--o11y-token-file" in script
    assert "SPLUNK_HEC_TOKEN_FILE" not in script
    assert "--render-platform-hec-helper" not in script
    assert "--platform-hec-token-file" not in script
    assert "--platform-hec-url" not in script
    assert "--platform-hec-index" not in script

    plan = json.loads((output_dir / "apply-plan.json").read_text(encoding="utf-8"))
    assert plan["modes"] == {
        "o11y_only": True,
        "splunk_platform_hec_enabled": False,
    }
    assert plan["selected_sections"] == [
        "readiness",
        "object-lifecycle",
        "luna-scorers",
        "observe-runtime",
        "protect-runtime",
        "evaluate-assets",
        "multimodal-assets",
        "observability-controls",
        "otel-collector",
        "dashboards",
        "detectors",
    ]


def test_o11y_only_default_apply_dry_run_selects_cloud_sections(tmp_path: Path) -> None:
    result = run_cmd(
        "bash",
        str(SETUP),
        "--apply",
        "--o11y-only",
        "--dry-run",
        "--json",
        *GALILEO_CONSOLE_ARGS,
        "--output-dir",
        str(tmp_path / "rendered"),
    )
    payload = json.loads(result.stdout)

    assert payload["modes"]["o11y_only"] is True
    assert payload["modes"]["splunk_platform_hec_enabled"] is False
    assert payload["selected_sections"] == [
        "readiness",
        "object-lifecycle",
        "luna-scorers",
        "observe-runtime",
        "protect-runtime",
        "evaluate-assets",
        "multimodal-assets",
        "observability-controls",
        "otel-collector",
        "dashboards",
        "detectors",
    ]
    for platform_section in ["splunk-hec", "observe-export", "splunk-otlp"]:
        assert platform_section not in payload["selected_sections"]


def test_o11y_only_apply_all_uses_cloud_sections_before_apply(tmp_path: Path) -> None:
    result = run_cmd(
        "bash",
        str(SETUP),
        "--apply",
        "all",
        "--o11y-only",
        "--realm",
        "us0",
        *GALILEO_CONSOLE_ARGS,
        "--output-dir",
        str(tmp_path / "rendered"),
        check=False,
    )
    combined = result.stdout + result.stderr

    assert result.returncode != 0
    assert "Unknown apply section: all" not in combined
    assert "--galileo-api-key-file is required" in combined


def test_o11y_only_rejects_explicit_platform_sections(tmp_path: Path) -> None:
    result = run_cmd(
        "bash",
        str(SETUP),
        "--apply",
        "observe-export",
        "--o11y-only",
        "--dry-run",
        *GALILEO_CONSOLE_ARGS,
        "--output-dir",
        str(tmp_path / "rendered"),
        check=False,
    )
    combined = result.stdout + result.stderr

    assert result.returncode != 0
    assert "--o11y-only" in combined
    assert "Splunk Platform" in combined
    assert "observe-export" in combined


def test_direct_secret_flags_are_rejected_without_echoing_values(tmp_path: Path) -> None:
    secret = "DIRECT_GALILEO_SECRET_SHOULD_NOT_ECHO"
    result = run_cmd(
        "bash",
        str(SETUP),
        "--render",
        "--output-dir",
        str(tmp_path / "rendered"),
        "--galileo-api-key",
        secret,
        check=False,
    )

    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert secret not in combined
    assert "--galileo-api-key-file" in combined


def test_rendered_files_do_not_contain_token_values_or_direct_authorization(tmp_path: Path) -> None:
    galileo_secret = "GALILEO_SECRET_SHOULD_NOT_RENDER"
    hec_secret = "HEC_SECRET_SHOULD_NOT_RENDER"
    o11y_secret = "O11Y_SECRET_SHOULD_NOT_RENDER"
    galileo_file = tmp_path / "galileo.token"
    hec_file = tmp_path / "hec.token"
    o11y_file = tmp_path / "o11y.token"
    galileo_file.write_text(galileo_secret, encoding="utf-8")
    hec_file.write_text(hec_secret, encoding="utf-8")
    o11y_file.write_text(o11y_secret, encoding="utf-8")
    output_dir = tmp_path / "rendered"

    run_cmd(
        "bash",
        str(SETUP),
        "--render",
        "--output-dir",
        str(output_dir),
        "--galileo-api-key-file",
        str(galileo_file),
        *GALILEO_CONSOLE_ARGS,
        "--splunk-hec-token-file",
        str(hec_file),
        "--o11y-token-file",
        str(o11y_file),
        "--splunk-hec-url",
        "https://splunk.example.com:8088/services/collector/event",
        "--realm",
        "us0",
    )
    text = rendered_text(output_dir)

    assert galileo_secret not in text
    assert hec_secret not in text
    assert o11y_secret not in text
    assert "Authorization: Splunk" not in text
    assert "Authorization: Bearer" not in text
    assert str(galileo_file) in text
    assert str(hec_file) in text
    assert str(o11y_file) in text


def test_export_records_request_shape_defaults_to_jsonl_and_redaction() -> None:
    bridge = load_bridge()
    args = bridge.parse_args(
        [
            "--project-id",
            "00000000-0000-4000-8000-000000000001",
            "--log-stream-id",
            "00000000-0000-4000-8000-000000000002",
            "--experiment-id",
            "00000000-0000-4000-8000-000000000003",
            "--metrics-testing-id",
            "00000000-0000-4000-8000-000000000004",
            "--galileo-api-key-file",
            "/tmp/galileo",
            "--splunk-hec-token-file",
            "/tmp/hec",
            "--splunk-hec-url",
            "https://splunk.example.com:8088",
            "--since",
            "2026-05-01T00:00:00Z",
        ]
    )
    body = bridge.build_export_records_request(args, args.since)

    assert body["root_type"] == "trace"
    assert body["export_format"] == "jsonl"
    assert body["redact"] is True
    assert body["log_stream_id"].endswith("0002")
    assert body["experiment_id"].endswith("0003")
    assert body["metrics_testing_id"].endswith("0004")
    assert body["filters"][0] == {
        "column_id": "updated_at",
        "operator": "gte",
        "type": "date",
        "value": "2026-05-01T00:00:00Z",
    }


def test_hec_envelope_extracts_flat_dotted_control_attributes() -> None:
    bridge = load_bridge()
    args = Namespace(
        include_raw=False,
        indexed_fields=True,
        log_stream_id="log-stream-1",
        project_id="project-1",
        root_type="span",
        splunk_host=None,
        splunk_index="galileo",
        splunk_source="galileo",
        splunk_sourcetype="galileo:observe:json",
        time_field="updated_at",
    )
    record = {
        "id": "span-1",
        "type": "span",
        "project_id": "project-1",
        "run_id": "log-stream-1",
        "trace_id": "trace-1",
        "updated_at": "2026-06-18T00:00:00Z",
        "attributes": {
            "control.id": "control-1",
            "control.name": "block-output-pii",
            "control.step": "LLM",
            "control.stage": "Post",
            "control.action.decision": "deny",
            "control.matched": True,
            "control.source": "custom",
            "control.evaluator.name": "pii-detector",
            "control.selector.path": "output",
        },
    }

    envelope = bridge.hec_envelope(record, args)
    event = envelope["event"]

    assert event["control_info"] == {
        "control_id": "control-1",
        "stage": "Post",
        "step_type": "LLM",
        "action": "deny",
        "matched": True,
        "evaluator_name": "pii-detector",
        "selector_path": "output",
        "source": "custom",
        "control_name": "block-output-pii",
    }
    assert event["galileo_control_id"] == "control-1"
    assert event["galileo_control_name"] == "block-output-pii"
    assert event["galileo_control_step_type"] == "LLM"
    assert event["galileo_control_source"] == "custom"
    assert envelope["fields"]["galileo_control_matched"] == "true"


def test_hec_envelope_extracts_multimodal_metadata_without_raw_payloads() -> None:
    bridge = load_bridge()
    args = Namespace(
        include_raw=False,
        indexed_fields=True,
        log_stream_id="log-stream-1",
        project_id="project-1",
        root_type="trace",
        splunk_host=None,
        splunk_index="galileo",
        splunk_source="galileo",
        splunk_sourcetype="galileo:observe:json",
        time_field="updated_at",
    )
    record = {
        "id": "trace-1",
        "type": "trace",
        "project_id": "project-1",
        "run_id": "log-stream-1",
        "trace_id": "trace-1",
        "updated_at": "2026-06-18T00:00:00Z",
        "input": [
            {"type": "text", "text": "Analyze these files"},
            {
                "modality": "image",
                "mime_type": "image/png",
                "url": "https://example.com/customer-photo.png",
                "source": "/private/customer-photo.png",
                "width": 640,
                "height": 480,
            },
            {
                "modality": "audio",
                "mime_type": "audio/wav",
                "base64": "RAW_AUDIO_BASE64_SHOULD_NOT_RENDER",
                "duration_ms": 1200,
            },
            {
                "modality": "document",
                "mime_type": "application/pdf",
                "file_name": "case-file.pdf",
                "page_count": 3,
                "data": "RAW_PDF_BYTES_SHOULD_NOT_RENDER",
            },
        ],
        "output": {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "The image is readable and the audio is clear."},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "https://example.com/generated-image.png",
                        "mime_type": "image/png",
                    },
                },
            ],
        },
        "metrics": {
            "visual_quality": True,
            "interruption_detection": False,
        },
    }

    envelope = bridge.hec_envelope(record, args)
    event = envelope["event"]
    serialized = json.dumps(envelope)

    assert event["galileo_has_multimodal"] is True
    assert event["galileo_modalities"] == ["audio", "document", "image"]
    assert event["galileo_input_modalities"] == ["audio", "document", "image"]
    assert event["galileo_output_modalities"] == ["image"]
    assert event["galileo_multimodal_asset_count"] == 4
    assert event["galileo_multimodal_metrics"] == ["interruption_detection", "visual_quality"]
    assert event["multimodal_info"]["asset_counts"] == {
        "audio": 1,
        "document": 1,
        "image": 2,
    }
    assert "RAW_AUDIO_BASE64_SHOULD_NOT_RENDER" not in serialized
    assert "RAW_PDF_BYTES_SHOULD_NOT_RENDER" not in serialized
    assert "https://example.com/customer-photo.png" not in serialized
    assert "https://example.com/generated-image.png" not in serialized
    assert "/private/customer-photo.png" not in serialized
    assert event["multimodal_info"]["assets"][0]["has_source"] is True
    assert envelope["fields"]["galileo_has_multimodal"] == "true"
    assert envelope["fields"]["galileo_modalities"] == "audio,document,image"


def test_object_lifecycle_dry_run_covers_core_galileo_objects(tmp_path: Path) -> None:
    manifest = tmp_path / "lifecycle.json"
    output = tmp_path / "result.json"
    manifest.write_text(
        json.dumps(
            {
                "project": {"name": "enterprise-ops"},
                "log_stream": {"name": "production", "metrics": ["correctness"]},
                "datasets": [{"name": "eval-cases", "content": [{"input": "hi"}]}],
                "prompts": [{"name": "triage", "template": [{"role": "user", "content": "{{input}}"}]}],
                "experiments": [{"name": "baseline"}],
                "protect_stages": [{"name": "production", "create": True}],
                "agent_control_targets": [{"target_type": "log_stream"}],
            }
        ),
        encoding="utf-8",
    )

    result = run_cmd(
        sys.executable,
        str(LIFECYCLE),
        "--dry-run",
        "--galileo-api-key-file",
        str(tmp_path / "galileo.token"),
        "--manifest",
        str(manifest),
        "--output",
        str(output),
    )
    payload = json.loads(result.stdout)

    assert payload["status"] == "ok"
    assert payload["project"]["status"] == "planned"
    assert payload["log_stream"]["status"] == "planned"
    assert payload["metrics"]["status"] == "planned"
    assert payload["datasets"][0]["status"] == "planned"
    assert payload["prompts"][0]["status"] == "planned"
    assert payload["experiments"][0]["status"] == "planned"
    assert payload["protect_stages"][0]["status"] == "planned"
    assert payload["agent_control_targets"][0]["status"] == "planned"
    assert output.is_file()


def test_luna_scorer_script_dry_run_builds_partial_replacement_plan(tmp_path: Path) -> None:
    token_file = tmp_path / "galileo.token"
    token_file.write_text("unused", encoding="utf-8")
    output = tmp_path / "luna-result.json"
    module = importlib.util.module_from_spec(
        importlib.util.spec_from_file_location("galileo_luna_scorers", LUNA)
    )
    assert module.__spec__ and module.__spec__.loader
    module.__spec__.loader.exec_module(module)

    settings = {
        "scorers": [
            {
                "id": "00000000-0000-4000-8000-000000000001",
                "name": "completeness",
                "scorer_type": "preset",
                "model_type": "llm",
                "input_type": "llm_spans",
                "output_type": "percentage",
                "filters": [{"name": "old_filter"}],
                "num_judges": 3,
                "scoreable_node_types": ["llm", "chat"],
            },
            {
                "id": "00000000-0000-4000-8000-000000000002",
                "name": "correctness",
                "scorer_type": "preset",
                "model_type": "llm",
                "input_type": "llm_spans",
                "output_type": "boolean_multilabel",
                "scoreable_node_types": ["llm", "chat"],
            },
            {
                "id": "00000000-0000-4000-8000-000000000005",
                "name": "agent_efficiency",
                "scorer_type": "preset",
                "model_type": "llm",
                "input_type": "sessions_normalized",
                "output_type": "boolean_multilabel",
                "scoreable_node_types": ["session"],
            },
        ],
        "segment_filters": None,
    }
    targets = {
        "completeness_luna": {
                "id": "00000000-0000-4000-8000-000000000003",
                "name": "completeness_luna",
                "scorer_type": "preset",
                "model_type": "slm",
                "output_type": "percentage",
                "defaults": {
                    "filters": [{"name": "luna_filter"}],
                    "num_judges": 1,
                    "scoreable_node_types": ["session"],
                },
            }
        }

    plan = module.build_metric_settings_plan(
        settings,
        module.normalize_replacements(
            {
                "strict": "false",
                "replacements": module.DEFAULT_REPLACEMENTS
                + [{"from": "agent_efficiency", "remove": True}],
                "custom_luna_scorer_ids": [
                    {
                        "from": "correctness",
                        "to_id": "00000000-0000-4000-8000-000000000004",
                        "scorer_type": "luna",
                        "model_type": "slm",
                    },
                    {"from": "agent_efficiency", "to_id": ""},
                ],
            }
        ),
        targets,
        strict=False,
    )

    assert plan["errors"] == []
    assert plan["applied"][0]["from"]["name"] == "completeness"
    assert plan["applied"][0]["to"]["name"] == "completeness_luna"
    assert plan["applied"][1]["from"]["name"] == "correctness"
    assert plan["applied"][1]["to"]["id"].endswith("0004")
    assert plan["unavailable"] == []
    assert plan["patch_body"]["scorers"][0]["id"].endswith("0003")
    assert plan["patch_body"]["scorers"][0]["model_type"] == "slm"
    assert plan["patch_body"]["scorers"][0]["input_type"] == "llm_spans"
    assert plan["patch_body"]["scorers"][0]["filters"] == [{"name": "luna_filter"}]
    assert plan["patch_body"]["scorers"][0]["num_judges"] == 1
    assert plan["patch_body"]["scorers"][0]["scoreable_node_types"] == ["session"]
    assert plan["patch_body"]["scorers"][1]["id"].endswith("0004")
    assert plan["patch_body"]["scorers"][1]["scorer_type"] == "luna"
    assert "scoreable_node_types" not in plan["patch_body"]["scorers"][1]
    assert [item["status"] for item in plan["applied"]] == ["planned", "planned", "removed"]
    assert all(not item["id"].endswith("0005") for item in plan["patch_body"]["scorers"])
    module.write_result(str(output), {"status": "planned"})
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "planned"


def test_repo_has_no_legacy_galileo_skill_references() -> None:
    legacy = "splunk-" + "galileo-integration"
    result = run_cmd("git", "grep", "-n", legacy, "--", ".", check=False)
    assert result.returncode == 1, result.stdout + result.stderr


def test_python_scripts_compile() -> None:
    run_cmd(sys.executable, "-m", "py_compile", str(RENDER), str(BRIDGE), str(LIFECYCLE), str(LUNA))

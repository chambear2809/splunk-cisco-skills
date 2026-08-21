"""Regression coverage for the Cisco Data Fabric architecture router."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills/cisco-data-fabric-setup"
SETUP = SKILL_DIR / "scripts/setup.sh"
VALIDATE = SKILL_DIR / "scripts/validate.sh"
RENDER = SKILL_DIR / "scripts/render_assets.py"
TEMPLATE = SKILL_DIR / "template.example"
PRODUCT_RESOLVER = REPO_ROOT / "skills/cisco-product-setup/scripts/resolve_product.sh"
PRODUCT_CATALOG = REPO_ROOT / "skills/cisco-product-setup/catalog.json"


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


def render(tmp_path: Path, spec: Path = TEMPLATE) -> Path:
    output = tmp_path / "rendered"
    run_cmd(
        "bash", str(SETUP), "--render", "--validate", "--spec", str(spec),
        "--output-dir", str(output),
    )
    return output


def test_help_advertises_render_doctor_execute_and_validate() -> None:
    for script in (SETUP, VALIDATE):
        result = run_cmd("bash", str(script), "--help")
        text = (result.stdout + result.stderr).lower()
        assert "render" in text
        assert "validate" in text
    setup_help = run_cmd("bash", str(SETUP), "--help").stdout.lower()
    assert "doctor" in setup_help
    assert "execute" in setup_help
    assert "storage-catalog" in setup_help
    assert "handoff-only" in setup_help


def test_render_template_creates_complete_artifact_contract(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    result = run_cmd(
        "bash", str(SETUP), "--render", "--validate", "--json",
        "--spec", str(TEMPLATE), "--output-dir", str(output),
    )
    payload = json.loads(result.stdout)
    assert payload["output_dir"] == str(output.resolve())

    required = {
        ".cisco-data-fabric-setup",
        "coverage-report.json",
        "coverage-report.md",
        "product-matrix.json",
        "product-matrix.md",
        "availability-matrix.md",
        "source-ledger.json",
        "apply-plan.json",
        "metadata.json",
        "gap-register.md",
        "gap-register.json",
        "doctor-report.md",
        "handoff.md",
        "architecture/layer-model.md",
        "data-management/pipeline-readiness.md",
        "federation/target-matrix.md",
        "storage-catalog/tiering-and-catalog-readiness.md",
        "ai/activation-readiness.md",
        "governance/trust-readiness.md",
        "experience/cross-domain-handoff.md",
    }
    for rel in required:
        assert (output / rel).is_file(), rel
    for section in {
        "data-management", "federation", "storage-catalog", "ai-activation",
        "context-governance", "experience",
    }:
        script = output / "scripts" / f"execute-{section}.sh"
        assert script.is_file()
        assert script.stat().st_mode & 0o111
    plan = json.loads((output / "apply-plan.json").read_text())
    assert plan["selected_sections"] == [
        "data-management", "federation", "ai-activation", "context-governance"
    ]
    selected_script = (output / "scripts/execute-selected.sh").read_text()
    assert "'storage-catalog'" not in selected_script.split("sections=(", 1)[1].split(")", 1)[0]
    assert "'experience'" not in selected_script.split("sections=(", 1)[1].split(")", 1)[0]


def test_feature_coverage_is_complete_and_lifecycle_aware(tmp_path: Path) -> None:
    output = render(tmp_path)
    payload = json.loads((output / "coverage-report.json").read_text())
    rows = payload["coverage"]
    by_key = {row["key"]: row for row in rows}
    assert len(by_key) == len(rows)
    required = {
        "cdf_architecture",
        "data_inputs",
        "edge_processor",
        "ingest_processor",
        "spl2_pipelines",
        "automated_field_extraction",
        "guided_onboarding_auto_schematization",
        "ingest_monitoring",
        "fss2s",
        "federated_s3",
        "federated_azure",
        "federated_databricks",
        "federated_snowflake",
        "federated_ddss",
        "federated_amazon_security_lake",
        "aws_glue_catalog",
        "iceberg_rest_catalog",
        "splunk_native_dataset_catalog",
        "delta_lake_table_format",
        "iceberg_table_format",
        "legacy_fss3_migration",
        "splunk_index",
        "machine_data_lake",
        "global_catalog",
        "machine_data_lake_catalog",
        "promote_s3",
        "knowledge_graph",
        "business_context",
        "ai_toolkit",
        "cdtsm",
        "ctsm_open_model",
        "splunk_agent_builder",
        "agent_builder_connections",
        "agent_builder_aiagent",
        "agent_builder_run_history",
        "splunk_mcp_server",
        "mcp_auth_tool_controls",
        "ai_canvas_splunk",
        "ai_canvas_splunk_limits",
        "cloud_control_studio_agent_builder",
        "cisco_sal_boundary",
    }
    assert required <= set(by_key)
    assert by_key["cdf_architecture"]["product_stage"] == "architecture"
    assert by_key["machine_data_lake"]["product_stage"] == "alpha"
    assert by_key["machine_data_lake"]["repo_status"] == "ui_handoff"
    assert by_key["legacy_fss3_migration"]["product_stage"] == "deprecated"
    assert by_key["splunk_agent_builder"]["product_stage"] == "ga"
    assert by_key["splunk_agent_builder"]["title"] == "Splunk AI Toolkit Agent Launchpad"
    assert "6.0.0" in by_key["splunk_agent_builder"]["boundary"]
    assert "apiAllowlistIP" in by_key["splunk_agent_builder"]["boundary"]
    assert "Splunk Cloud Connect" in by_key["splunk_agent_builder"]["platforms"]
    assert by_key["splunk_agent_builder"]["source_url"].endswith("ai-toolkit-agent-launchpad")
    for key in ("agent_builder_connections", "agent_builder_aiagent", "agent_builder_run_history"):
        assert by_key[key]["product_stage"] == "ga"
        assert "preview" not in by_key[key]["platforms"].lower()
    assert "ai_agent_run_history_index" not in by_key["agent_builder_run_history"]["boundary"]
    assert "agent_run_index" in by_key["agent_builder_run_history"]["boundary"]
    assert by_key["cloud_control_studio_agent_builder"]["key"] != "splunk_agent_builder"
    assert by_key["cloud_control_studio_agent_builder"]["product_stage"] == "roadmap"
    cisco_builder_boundary = by_key["cloud_control_studio_agent_builder"]["boundary"]
    assert "2026-06-02" in cisco_builder_boundary
    assert "2026-08-20" in cisco_builder_boundary
    assert by_key["ctsm_open_model"]["product_stage"] == "available"
    assert by_key["cdtsm"]["product_stage"] == "ga"
    assert "6.0.0" in by_key["cdtsm"]["boundary"]
    assert by_key["cdtsm"]["source_url"].endswith("ai-toolkit-models/cisco-deep-time-series-model")
    assert "feature-preview" not in by_key["cdtsm"]["source_url"]
    assert "Cisco Time Series Model" in by_key["cdtsm"]["boundary"]
    assert by_key["ai_toolkit"]["title"] == "Splunk AI Toolkit 6.0.2 and PSC 4.3.4"
    assert "4.3.4" in by_key["ai_toolkit"]["boundary"]
    assert by_key["ai_toolkit"]["source_url"].startswith(
        "https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit/6.0.2/"
    )
    assert by_key["splunk_mcp_server"]["product_stage"] == "ga"
    assert by_key["splunk_mcp_server"]["repo_status"] == "delegated_render"
    assert by_key["federated_s3"]["product_stage"] == "ga"
    assert by_key["federated_s3"]["access_requirement"] == "sales_activation_and_scan_entitlement"
    assert by_key["federated_amazon_security_lake"]["product_stage"] == "ga"
    assert by_key["federated_amazon_security_lake"]["access_requirement"] == "premium_add_on_activation_and_scan_entitlement"
    assert all("access_requirement" in row for row in rows)
    assert all(row["retrieved_at"] in {"2026-07-03", "2026-08-20"} for row in rows)
    assert by_key["splunk_agent_builder"]["retrieved_at"] == "2026-08-20"


def test_federation_matrix_has_every_current_target_and_no_generic_asl_route(tmp_path: Path) -> None:
    output = render(tmp_path)
    text = (output / "federation/target-matrix.md").read_text()
    for term in (
        "Splunk Cloud / Enterprise",
        "Amazon S3",
        "Microsoft Azure Blob / ADLS Gen2",
        "Azure Databricks Unity Catalog",
        "Snowflake tables and views",
        "DDSS in Amazon S3",
        "Amazon Security Lake",
    ):
        assert term in text
    assert "Do not route Amazon Security Lake as a generic Amazon S3 provider" in text
    assert "Cisco SAL" in text


def test_product_matrix_distinguishes_architecture_products_and_experience(tmp_path: Path) -> None:
    output = render(tmp_path)
    payload = json.loads((output / "product-matrix.json").read_text())
    by_key = {row["key"]: row for row in payload["products"]}
    assert by_key["cisco_data_fabric"]["product_stage"] == "architecture"
    assert by_key["machine_data_lake"]["product_stage"] == "alpha"
    assert by_key["ctsm"]["product_stage"] == "available"
    assert by_key["agent_builder"]["product_stage"] == "ga"
    assert by_key["agent_builder"]["title"] == "Splunk AI Toolkit Agent Launchpad"
    assert by_key["cloud_control"]["product_stage"] == "controlled_availability"
    assert "not the Data Fabric" in by_key["cloud_control"]["relationship"]
    assert "Separate Cisco logging product" in by_key["cisco_sal"]["relationship"]


def test_source_ledger_has_claim_metadata_and_reconciled_primary_sources(tmp_path: Path) -> None:
    output = render(tmp_path)
    payload = json.loads((output / "source-ledger.json").read_text())
    rows = payload["sources"]
    by_id = {row["claim_id"]: row for row in rows}
    for claim_id in {
        "cdf_launch", "data_management_guide", "federated_overview",
        "federated_asl", "federated_asl_ga", "federated_ga",
        "federated_legacy", "catalog", "promote",
        "data_inputs", "ai_toolkit", "ai_toolkit_dependencies",
        "cdtsm", "cdtsm_on_prem", "ctsm", "mcp",
        "agent_launchpad", "agent_launchpad_on_prem",
        "cloud_control_splunk", "ai_canvas", "sal",
        "cloud_control_agent_builder", "cloud_control_release_notes",
    }:
        assert claim_id in by_id
    assert "agent_builder_preview" not in by_id
    assert by_id["agent_launchpad"]["source_version"] == "6.0.2"
    assert by_id["agent_launchpad"]["retrieved_at"] == "2026-08-20"
    assert "5.6.4" not in by_id["agent_launchpad_on_prem"]["url"]
    for claim_id in ("ai_toolkit", "ai_toolkit_dependencies", "cdtsm", "cdtsm_on_prem"):
        assert by_id[claim_id]["source_version"] == "6.0.2"
        assert by_id[claim_id]["retrieved_at"] == "2026-08-20"
        assert "/5.7.4/" not in by_id[claim_id]["url"]
    assert by_id["cloud_control_release_notes"]["retrieved_at"] == "2026-08-20"
    assert by_id["cloud_control_agent_builder"]["source_type"] == "announcement"
    for row in rows:
        assert row["url"].startswith("https://")
        assert row["source_type"]
        assert row["source_version"]
        assert row["retrieved_at"] in {"2026-07-03", "2026-08-20"}


def test_default_dry_run_does_not_invoke_canned_ingest_or_unconfigured_federation(tmp_path: Path) -> None:
    result = run_cmd(
        "bash", str(SETUP), "--execute",
        "data-management,federation,ai-activation,context-governance",
        "--dry-run", "--json", "--spec", str(TEMPLATE),
        "--output-dir", str(tmp_path / "rendered"),
    )
    payload = json.loads(result.stdout)
    by_name = {section["name"]: section for section in payload["sections"]}
    command_text = json.dumps(
        [command for section in payload["sections"] for command in section["commands"]]
    )
    assert "splunk-ingest-processor-setup" not in command_text
    assert "splunk-federated-search-setup" not in command_text
    assert "splunk-edge-processor-setup" not in command_text
    assert "splunk-spl2-pipeline-kit" in command_text
    assert "splunk-ai-ml-toolkit-setup" in command_text
    assert '"--platform", "cloud"' in command_text
    assert '"--splunk-version", "10.5.2605.3"' in command_text
    assert by_name["storage-catalog"]["handoff_only"] is True
    assert by_name["experience"]["handoff_only"] is True
    assert by_name["federation"]["commands"] == []


def test_reviewed_child_inputs_are_propagated_as_argv_arrays(tmp_path: Path) -> None:
    spec = tmp_path / "spec.json"
    federation_spec = tmp_path / "federation.yaml"
    ai_spec = tmp_path / "ai.yaml"
    evidence = tmp_path / "evidence.json"
    spec.write_text(json.dumps({
        "api_version": "cisco-data-fabric-setup/v1",
        "data_management": {"edge_processor": {"enabled": True, "tenant_url": "https://ep.example.test", "name": "edge-prod"}},
        "federation": {"enabled": True, "child_spec": str(federation_spec)},
        "ai_activation": {"ai_toolkit": {"enabled": True, "child_spec": str(ai_spec)}},
        "context_governance": {"child_specs": {"data_source_readiness": str(evidence)}},
    }), encoding="utf-8")
    result = run_cmd(
        "bash", str(SETUP), "--execute", "all", "--dry-run", "--json",
        "--spec", str(spec), "--output-dir", str(tmp_path / "rendered"),
    )
    payload = json.loads(result.stdout)
    text = json.dumps(payload)
    assert "splunk-edge-processor-setup" in text
    assert "https://ep.example.test" in text
    assert "edge-prod" in text
    assert "splunk-federated-search-setup" in text
    assert str(federation_spec) in text
    assert str(ai_spec) in text
    assert "splunk-data-source-readiness-doctor" in text
    assert str(evidence) in text
    for section in payload["sections"]:
        for command in section["commands"]:
            assert isinstance(command, list)
            assert command


def test_cloud_platform_and_version_reach_ai_child_and_unknowns_are_reported(tmp_path: Path) -> None:
    spec = tmp_path / "cloud.json"
    spec.write_text(json.dumps({
        "api_version": "cisco-data-fabric-setup/v1",
        "platform": {
            "deployment": "splunk-cloud",
            "version": "10.5",
            "cloud_provider": "aws",
            "region": "",
        },
        "data_management": {"enabled": False},
        "federation": {"enabled": False},
        "storage_catalog": {"enabled": False},
        "ai_activation": {
            "enabled": True,
            "ai_toolkit": {"enabled": True},
            "mcp_server": {"enabled": False},
            "agent_observability": {"enabled": False},
        },
        "context_governance": {"enabled": False},
        "experience": {"enabled": False},
    }), encoding="utf-8")
    output = render(tmp_path, spec)
    gaps = (output / "gap-register.md").read_text()
    assert "| error | platform_version_precision |" in gaps
    assert "| error | platform_region |" in gaps

    plan = json.loads((output / "apply-plan.json").read_text())
    ai = next(section for section in plan["sections"] if section["name"] == "ai-activation")
    toolkit = next(command for command in ai["commands"] if "splunk-ai-ml-toolkit-setup" in " ".join(command))
    assert toolkit[toolkit.index("--platform") + 1] == "cloud"
    assert toolkit[toolkit.index("--splunk-version") + 1] == "10.5"

    blocked = run_cmd(
        "bash", str(SETUP), "--execute", "ai-activation", "--accept-execute",
        "--spec", str(spec), "--output-dir", str(output),
        check=False,
    )
    assert blocked.returncode != 0
    assert "blocking intake gap" in blocked.stdout + blocked.stderr
    assert not (output / "delegated").exists()

    valid_spec = tmp_path / "valid-cloud.json"
    valid_payload = json.loads(spec.read_text())
    valid_payload["platform"]["version"] = "10.5.2605.3"
    valid_payload["platform"]["region"] = "us-east-1"
    valid_spec.write_text(json.dumps(valid_payload), encoding="utf-8")
    valid_output = tmp_path / "valid-rendered"
    run_cmd(
        "bash", str(SETUP), "--execute", "ai-activation", "--accept-execute",
        "--spec", str(valid_spec), "--output-dir", str(valid_output),
    )
    child = valid_output / "delegated/ai-ml-toolkit"
    child_plan = json.loads((child / "apply-plan.json").read_text())
    assert child_plan["platform"] == "cloud"
    agent_handoff = (child / "agent-launchpad-handoff.md").read_text()
    assert "Target platform: `cloud`" in agent_handoff
    assert "Repo status: `manual_handoff`" in agent_handoff


def test_selected_executor_preflights_empty_sections_before_partial_run(tmp_path: Path) -> None:
    output = render(tmp_path)
    selected = output / "scripts/execute-selected.sh"
    result = run_cmd("bash", str(selected), check=False)
    assert result.returncode == 2
    combined = result.stdout + result.stderr
    assert "before any delegated command runs" in combined
    assert "federation" in combined
    assert "context-governance" in combined
    assert not (output / "delegated").exists()


def test_ai_canvas_prerequisites_and_limits_are_rendered(tmp_path: Path) -> None:
    output = render(tmp_path)
    rows = json.loads((output / "coverage-report.json").read_text())["coverage"]
    by_key = {row["key"]: row for row in rows}
    assert "mcp_tool_execute" in by_key["ai_canvas_splunk"]["boundary"]
    assert "100 rows per card" in by_key["ai_canvas_splunk_limits"]["boundary"]
    assert "forbidden" in by_key["ai_canvas_splunk_limits"]["boundary"]
    gaps = (output / "gap-register.md").read_text()
    assert "mcp_tool_execute" in gaps
    assert "100 rows per card" in gaps


def test_experience_toggles_disable_cloud_control_and_ai_canvas_independently(tmp_path: Path) -> None:
    spec = tmp_path / "experience.json"
    spec.write_text(json.dumps({
        "api_version": "cisco-data-fabric-setup/v1",
        "platform": {
            "deployment": "splunk-cloud",
            "version": "10.5.2605",
            "cloud_provider": "aws",
            "region": "us-east-1",
        },
        "experience": {
            "enabled": True,
            "cloud_control": False,
            "ai_canvas": False,
        },
    }), encoding="utf-8")
    output = render(tmp_path, spec)
    rows = json.loads((output / "coverage-report.json").read_text())["coverage"]
    by_key = {row["key"]: row for row in rows}
    assert by_key["cloud_control_studio_agent_builder"]["repo_status"] == "not_applicable"
    assert by_key["ai_canvas_splunk"]["repo_status"] == "not_applicable"
    assert by_key["ai_canvas_splunk_limits"]["repo_status"] == "not_applicable"
    gaps = (output / "gap-register.md").read_text()
    assert "ai_canvas_stack_version" not in gaps
    assert "cloud_control_ca" not in gaps
    assert "ai_canvas_ca" not in gaps


def test_disabled_sections_are_consistent_in_json_and_markdown(tmp_path: Path) -> None:
    spec = tmp_path / "disabled.json"
    spec.write_text(json.dumps({
        "api_version": "cisco-data-fabric-setup/v1",
        "data_management": {"enabled": False},
        "federation": {"enabled": False},
        "storage_catalog": {"enabled": False},
        "ai_activation": {"enabled": False},
        "context_governance": {"enabled": False},
        "experience": {"enabled": False},
    }), encoding="utf-8")
    output = render(tmp_path, spec)
    rows = json.loads((output / "coverage-report.json").read_text())["coverage"]
    by_key = {row["key"]: row for row in rows}
    for key in {
        "edge_processor", "federated_s3", "machine_data_lake", "ai_toolkit",
        "business_context", "ai_canvas_splunk",
    }:
        assert by_key[key]["repo_status"] == "not_applicable"
    text = (output / "coverage-report.md").read_text()
    assert "not_applicable" in text


def test_handoff_only_mixed_execution_refuses_before_child_commands(tmp_path: Path) -> None:
    output = tmp_path / "rendered"
    result = run_cmd(
        "bash", str(SETUP), "--execute", "data-management,storage-catalog",
        "--accept-execute", "--spec", str(TEMPLATE), "--output-dir", str(output),
        check=False,
    )
    assert result.returncode == 2
    assert "No delegated sections were executed" in result.stdout + result.stderr
    assert not (output / "delegated").exists()


def test_execute_without_accept_fails_closed(tmp_path: Path) -> None:
    result = run_cmd(
        "bash", str(SETUP), "--execute", "data-management",
        "--output-dir", str(tmp_path / "rendered"), check=False,
    )
    assert result.returncode != 0
    assert "--accept-execute" in result.stdout + result.stderr


def test_direct_secret_flags_and_secret_looking_spec_keys_are_rejected(tmp_path: Path) -> None:
    secret = "DIRECT_SECRET_SHOULD_NOT_ECHO"
    result = run_cmd(
        "bash", str(SETUP), "--render", "--api-key", secret,
        "--output-dir", str(tmp_path / "rendered"), check=False,
    )
    assert result.returncode != 0
    assert secret not in result.stdout + result.stderr

    for flag in ("--llm-api-key", "--openai-api-key", "--model_api_key"):
        result = run_cmd(
            "bash", str(SETUP), "--render", f"{flag}=LLM_SECRET_SHOULD_NOT_ECHO",
            "--output-dir", str(tmp_path / "llm-rendered"), check=False,
        )
        combined = result.stdout + result.stderr
        assert result.returncode != 0
        assert "LLM_SECRET_SHOULD_NOT_ECHO" not in combined
        assert "Direct secret values are not accepted" in combined
        assert "Unknown option" not in combined

    spec = tmp_path / "bad.yaml"
    spec.write_text(
        "api_version: cisco-data-fabric-setup/v1\nai_activation:\n  token: SHOULD_NOT_RENDER\n",
        encoding="utf-8",
    )
    result = run_cmd(
        "bash", str(SETUP), "--render", "--spec", str(spec),
        "--output-dir", str(tmp_path / "bad-output"), check=False,
    )
    assert result.returncode != 0
    assert "SHOULD_NOT_RENDER" not in result.stdout + result.stderr
    assert "raw secret-looking key" in result.stdout + result.stderr

    disguised = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd"
    spec = tmp_path / "disguised.json"
    spec.write_text(json.dumps({
        "api_version": "cisco-data-fabric-setup/v1",
        "organization": {"name": disguised},
    }), encoding="utf-8")
    result = run_cmd(
        "bash", str(SETUP), "--render", "--spec", str(spec),
        "--output-dir", str(tmp_path / "disguised-output"), check=False,
    )
    assert result.returncode != 0
    assert disguised not in result.stdout + result.stderr
    assert "credential signature" in result.stdout + result.stderr
    assert not (tmp_path / "disguised-output").exists()


def test_unrelated_nonempty_output_directory_is_refused(tmp_path: Path) -> None:
    output = tmp_path / "occupied"
    output.mkdir()
    (output / "user-file.txt").write_text("keep", encoding="utf-8")
    result = run_cmd(
        "bash", str(SETUP), "--render", "--output-dir", str(output),
        check=False,
    )
    assert result.returncode != 0
    assert "Refusing unrelated non-empty output directory" in result.stdout + result.stderr
    assert (output / "user-file.txt").read_text() == "keep"


def test_skill_docs_keep_critical_product_boundaries() -> None:
    text = "\n".join(
        (SKILL_DIR / rel).read_text(encoding="utf-8")
        for rel in (
            "SKILL.md", "reference.md", "references/feature-matrix.md",
            "references/research-ledger.md",
        )
    )
    for term in (
        "not as a single", "Machine Data Lake", "alpha", "Global Splunk Catalog",
        "Amazon Security Lake", "Cisco Security Analytics and Logging",
        "Cisco Time Series Model 1.0", "Cisco Deep Time Series Model",
        "Splunk AI Toolkit Agent Launchpad", "Cloud Control Studio Agent Builder",
        "10.5.2605.3",
    ):
        assert term in text
    assert "GA target Fall 2026" not in text
    assert "GA target of Fall\n  2026" not in text
    assert "5.6.4/ai-toolkit-commands-macros-and-visualizations" not in text
    unwrapped = " ".join(text.split())
    assert "Splunk AI Toolkit Agent Launchpad at alpha" not in unwrapped
    assert "Splunk Cloud Connect" in unwrapped
    assert "apiAllowlistIP" in unwrapped


def test_python_renderer_compiles() -> None:
    run_cmd(sys.executable, "-m", "py_compile", str(RENDER))


def test_product_router_resolves_data_fabric_architecture_aliases() -> None:
    for query in (
        "Cisco Data Fabric",
        "Machine Data Lake",
        "Splunk Catalog",
        "Federated Analytics",
        "AI-powered Data Management",
    ):
        result = run_cmd(
            "bash", str(PRODUCT_RESOLVER), "--catalog", str(PRODUCT_CATALOG),
            "--json", query,
        )
        payload = json.loads(result.stdout)
        assert payload["status"] == "resolved", query
        assert payload["matches"][0]["id"] == "cisco_data_fabric", query
        assert payload["matches"][0]["primary_skill"] == "cisco-data-fabric-setup", query

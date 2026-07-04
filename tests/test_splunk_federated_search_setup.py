"""Offline regressions for splunk-federated-search-setup."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "skills/splunk-federated-search-setup"
RENDER_SCRIPT = SKILL_ROOT / "scripts/render_assets.py"
SETUP_SCRIPT = SKILL_ROOT / "scripts/setup.sh"
VALIDATE_SCRIPT = SKILL_ROOT / "scripts/validate.sh"


def _load_render_module():
    spec = importlib.util.spec_from_file_location("fss_render_assets", RENDER_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("fss_render_assets", module)
    spec.loader.exec_module(module)
    return module


render_module = _load_render_module()


def run_render(*args: str, **kwargs) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(RENDER_SCRIPT), *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=False, **kwargs)


def run_setup(*args: str, **kwargs) -> subprocess.CompletedProcess[str]:
    cmd = ["bash", str(SETUP_SCRIPT), *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=REPO_ROOT, **kwargs)


def run_validate(*args: str, **kwargs) -> subprocess.CompletedProcess[str]:
    cmd = ["bash", str(VALIDATE_SCRIPT), *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=REPO_ROOT, **kwargs)


def write_spec(tmp_path: Path, name: str, payload: dict) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def write_supported_fake_splunk_home(path: Path) -> None:
    binary = path / "bin/splunk"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"${1:-}\" == version ]]; then\n"
        "  echo 'Splunk 10.4.1 (build test)'\n"
        "  exit 0\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    binary.chmod(0o755)


def render_rest_apply_fixture(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    admin_password = tmp_path / "admin-password"
    provider_password = tmp_path / "provider-password"
    admin_password.write_text("admin-test-password", encoding="utf-8")
    provider_password.write_text("provider-test-password", encoding="utf-8")
    admin_password.chmod(0o600)
    provider_password.chmod(0o600)
    spec = {
        "providers": [
            {
                "name": "alpha",
                "type": "splunk",
                "mode": "standard",
                "host_port": "remote.example.test:8089",
                "service_account": "federated_svc",
                "password_file": str(provider_password),
            }
        ],
        "federated_indexes": [
            {
                "name": "alpha_idx",
                "provider": "alpha",
                "dataset_type": "index",
                "dataset_name": "main",
            }
        ],
    }
    spec_path = write_spec(tmp_path, "rest-spec.json", spec)
    output = tmp_path / "rest-output"
    result = run_render("--output-dir", str(output), "--spec", str(spec_path))
    assert result.returncode == 0, result.stderr
    render_dir = output / "federated-search"
    env = {
        **os.environ,
        "SPLUNK_REST_USER": "admin",
        "SPLUNK_REST_PASSWORD_FILE": str(admin_password),
    }
    env.pop("SPLUNK_ALLOW_INSECURE_HTTP", None)
    return render_dir, env


def run_rest_apply(
    render_dir: Path,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(render_dir / "apply-rest.sh")],
        cwd=render_dir,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )


# ---------------------------------------------------------------------------
# Single-provider back-compat
# ---------------------------------------------------------------------------


def test_single_provider_back_compat_renders_standard_mode_assets(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(
        "--output-dir", str(out),
        "--mode", "standard",
        "--remote-host-port", "remote-sh.example.com:8089",
        "--service-account", "federated_svc",
        "--password-file", str(tmp_path / "pw"),
        "--provider-name", "remote_prod",
        "--federated-index-name", "remote_main",
        "--dataset-type", "index",
        "--dataset-name", "main",
    )
    assert result.returncode == 0, result.stderr
    render_dir = out / "federated-search"
    assert (render_dir / "federated.conf.template").read_text().count("[provider://remote_prod]") == 1
    assert "mode = standard" in (render_dir / "federated.conf.template").read_text()
    assert "[federated:remote_main]" in (render_dir / "indexes.conf").read_text()
    assert "federated.dataset = index:main" in (render_dir / "indexes.conf").read_text()


def test_back_compat_transparent_skips_federated_index(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(
        "--output-dir", str(out),
        "--mode", "transparent",
        "--remote-host-port", "remote-sh.example.com:8089",
        "--service-account", "federated_svc",
        "--password-file", str(tmp_path / "pw"),
        "--provider-name", "hybrid",
    )
    assert result.returncode == 0, result.stderr
    indexes = (out / "federated-search/indexes.conf").read_text()
    assert "No FSS2S federated indexes" in indexes
    fed = (out / "federated-search/federated.conf.template").read_text()
    assert "useFSHKnowledgeObjects = 1" in fed
    assert "appContext" not in fed


# ---------------------------------------------------------------------------
# Multi-provider via spec
# ---------------------------------------------------------------------------


def test_multi_provider_spec_renders_all_stanzas(tmp_path: Path) -> None:
    spec = {
        "splunk_home": "/opt/splunk",
        "app_name": "ZZZ_test",
        "shc_replication": True,
        "providers": [
            {
                "name": "remote_prod",
                "type": "splunk",
                "mode": "standard",
                "host_port": "remote-sh.example.com:8089",
                "service_account": "fed_svc",
                "password_file": str(tmp_path / "pw_prod"),
                "app_context": "search",
            },
            {
                "name": "remote_prod_es",
                "type": "splunk",
                "mode": "standard",
                "host_port": "remote-sh.example.com:8089",
                "service_account": "fed_svc",
                "password_file": str(tmp_path / "pw_prod"),
                "app_context": "SplunkEnterpriseSecuritySuite",
            },
        ],
        "federated_indexes": [
            {
                "name": "remote_main",
                "provider": "remote_prod",
                "dataset_type": "index",
                "dataset_name": "main",
            },
            {
                "name": "remote_es_notable",
                "provider": "remote_prod_es",
                "dataset_type": "savedsearch",
                "dataset_name": "Access - Authentication Failures - Rule",
            },
        ],
    }
    spec_path = write_spec(tmp_path, "spec.json", spec)
    out = tmp_path / "out"
    result = run_render("--output-dir", str(out), "--spec", str(spec_path))
    assert result.returncode == 0, result.stderr
    fed = (out / "federated-search/federated.conf.template").read_text()
    assert "[provider://remote_prod]" in fed
    assert "[provider://remote_prod_es]" in fed
    assert fed.count("appContext = ") == 2
    indexes = (out / "federated-search/indexes.conf").read_text()
    assert "[federated:remote_main]" in indexes
    assert "[federated:remote_es_notable]" in indexes
    assert "federated.dataset = savedsearch:Access - Authentication Failures - Rule" in indexes


# ---------------------------------------------------------------------------
# FSS3
# ---------------------------------------------------------------------------


def _fss3_provider_spec(tmp_path: Path) -> dict:
    return {
        "providers": [
            {
                "name": "aws_logs",
                "type": "aws_s3",
                "aws_account_id": "123456789012",
                "aws_region": "us-west-2",
                "database": "my_glue_db",
                "data_catalog": "arn:aws:glue:us-west-2:123456789012:catalog",
                "aws_glue_tables_allowlist": ["access_logs", "app_logs"],
                "aws_s3_paths_allowlist": ["s3://my-bucket/access/", "s3://my-bucket/app/"],
                "aws_kms_keys_arn_allowlist": [
                    "arn:aws:kms:us-west-2:123456789012:key/abc-1234"
                ],
            }
        ],
        "federated_indexes": [
            {
                "name": "aws_access_logs",
                "provider": "aws_logs",
                "dataset_type": "glue_table",
                "dataset_name": "access_logs",
            }
        ],
    }


def test_fss3_provider_renders_rest_payload_and_aws_readme(tmp_path: Path) -> None:
    spec = _fss3_provider_spec(tmp_path)
    spec_path = write_spec(tmp_path, "fss3.json", spec)
    out = tmp_path / "out"
    result = run_render("--output-dir", str(out), "--spec", str(spec_path))
    assert result.returncode == 0, result.stderr
    payload_path = out / "federated-search/aws-s3-providers/aws_logs.json"
    assert payload_path.is_file()
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    assert payload["type"] == "aws_s3"
    assert payload["aws_account_id"] == "123456789012"
    assert payload["aws_region"] == "us-west-2"
    assert payload["database"] == "my_glue_db"
    assert payload["data_catalog"] == "arn:aws:glue:us-west-2:123456789012:catalog"
    assert payload["aws_glue_tables_allowlist"] == "access_logs,app_logs"
    assert payload["aws_s3_paths_allowlist"] == "s3://my-bucket/access/,s3://my-bucket/app/"
    assert "aws_kms_keys_arn_allowlist" in payload
    readme = (out / "federated-search/aws-s3-providers/README.md").read_text()
    assert "FSS3" in readme or "Federated Search for Amazon S3" in readme
    assert "aws-s3-providers/aws_logs.json" in readme
    assert "phased deprecation" in readme
    assert "Management app" in readme
    metadata = json.loads((out / "federated-search/metadata.json").read_text())
    legacy_provider = metadata["providers"]["amazon_s3"][0]
    assert legacy_provider["provider_type"] == "aws_s3"
    assert legacy_provider["lifecycle"] == "legacy_phased_deprecation"
    assert legacy_provider["automation"] == "rendered_migration_evidence_only"
    assert metadata["legacy_fss3"]["automation"] == "rendered_migration_evidence_only"
    assert metadata["legacy_fss3"]["preferred_replacement"].startswith(
        "Federated Search for Amazon S3 through Data Management"
    )
    assert any("phased-deprecation" in warning for warning in metadata["warnings"])
    migration = (out / "federated-search/legacy-fss3-migration.md").read_text()
    assert "legacy_phased_deprecation" in migration
    assert "`aws_logs`" in migration
    assert "AWS Glue, Apache Iceberg REST, or Splunk-native" in migration
    # FSS2S federated.conf.template should NOT contain the FSS3 provider name
    fed = (out / "federated-search/federated.conf.template").read_text()
    assert "aws_logs" not in fed
    # Legacy-only plans are inventory/migration evidence, never runnable CRUD.
    dry_run = run_render(
        "--output-dir", str(tmp_path / "dry"), "--spec", str(spec_path), "--dry-run", "--json"
    )
    assert dry_run.returncode == 0, dry_run.stderr
    assert json.loads(dry_run.stdout)["commands"]["apply"] == []
    render_dir = out / "federated-search"
    for script_name in ("apply-search-head.sh", "apply-rest.sh"):
        script = (render_dir / script_name).read_text()
        assert "HANDOFF ONLY" in script
        assert "exit 2" in script
        assert "aws-s3-providers/" not in script
        assert "aws_logs" not in script
        refused = subprocess.run(
            ["bash", str(render_dir / script_name)],
            cwd=render_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        assert refused.returncode == 2
    assert "/services/data/federated/provider" not in (
        render_dir / "apply-rest.sh"
    ).read_text()
    assert "/services/data/federated/index" not in (
        render_dir / "apply-rest.sh"
    ).read_text()
    validate = run_validate("--output-dir", str(out))
    assert validate.returncode == 0, validate.stderr + validate.stdout


def test_setup_apply_refuses_legacy_fss3_before_rest_credentials_or_network(
    tmp_path: Path,
) -> None:
    spec_path = write_spec(tmp_path, "fss3.json", _fss3_provider_spec(tmp_path))
    out = tmp_path / "out"
    result = run_setup(
        "--phase", "apply",
        "--apply-target", "rest",
        "--output-dir", str(out),
        "--spec", str(spec_path),
    )
    assert result.returncode == 2
    assert "HANDOFF ONLY" in result.stderr
    assert "SPLUNK_REST_URI" not in result.stderr


def test_mixed_plan_validation_uses_structural_legacy_exclusion(
    tmp_path: Path,
) -> None:
    """A legacy name that occurs in generic prose must not cause a false failure."""
    spec = _fss3_provider_spec(tmp_path)
    spec["providers"][0]["name"] = "provider"
    spec["federated_indexes"][0]["provider"] = "provider"
    spec["providers"].insert(
        0,
        {
            "name": "remote_prod",
            "type": "splunk",
            "mode": "standard",
            "host_port": "remote.example.test:8089",
            "service_account": "federated_svc",
            "password_file": str(tmp_path / "provider-password"),
        },
    )
    spec["federated_indexes"].insert(
        0,
        {
            "name": "remote_main",
            "provider": "remote_prod",
            "dataset_type": "index",
            "dataset_name": "main",
        },
    )
    spec_path = write_spec(tmp_path, "mixed.json", spec)
    out = tmp_path / "out"
    result = run_render("--output-dir", str(out), "--spec", str(spec_path))
    assert result.returncode == 0, result.stderr
    validate = run_validate("--output-dir", str(out))
    assert validate.returncode == 0, validate.stderr + validate.stdout
    apply_rest = (out / "federated-search/apply-rest.sh").read_text()
    assert "'name': \"remote_prod\"" in apply_rest
    assert "'name': \"provider\"" not in apply_rest
    assert "'federated.provider': \"provider\"" not in apply_rest


def test_cloud_10_5_data_management_handoff_covers_new_federation_surfaces(
    tmp_path: Path,
) -> None:
    spec_path = write_spec(tmp_path, "fss3.json", _fss3_provider_spec(tmp_path))
    out = tmp_path / "out"
    result = run_render("--output-dir", str(out), "--spec", str(spec_path))
    assert result.returncode == 0, result.stderr

    handoff = (out / "federated-search/data-management-federation-handoff.md").read_text()
    metadata = json.loads((out / "federated-search/metadata.json").read_text())
    expected = {
        "amazon_s3_data_management",
        "microsoft_azure",
        "azure_databricks",
        "snowflake",
        "ddss",
    }
    assert expected == {
        item["key"] for item in metadata["data_management_federation_handoffs"]
    }
    assert {
        item["key"] for item in metadata["specialized_federation_handoffs"]
    } == {
        "amazon_security_lake_federated_analytics",
        "cisco_security_analytics_and_logging",
    }
    assert {
        item["key"] for item in metadata["federation_handoffs"]
    } == expected | {
        "amazon_security_lake_federated_analytics",
        "cisco_security_analytics_and_logging",
    }
    handoffs = {
        item["key"]: item for item in metadata["data_management_federation_handoffs"]
    }
    assert "available by activation" in handoffs["snowflake"]["stage"]
    assert "available by activation" in handoffs["ddss"]["stage"]
    assert "Contact Splunk sales for activation" in handoffs["snowflake"]["activation"]
    assert "Contact Splunk sales for activation" in handoffs["ddss"]["activation"]
    for label in ("Microsoft Azure", "Azure Databricks", "Snowflake", "DDSS"):
        assert f"Federated Search for {label}" in handoff
    assert "edit_connections" in handoff
    assert "edit_datasets" in handoff
    assert "required federated-search activation and Data Scan Unit entitlement" not in handoff
    assert "do not infer one universal Data Scan Unit model" in handoff

    # Snowflake 10.5 provider-side prerequisites.
    assert "`USAGE` on the warehouse, database, and schema" in handoff
    assert "Splunk-region IPv4 ingress network rule" in handoff
    assert "Snowflake network policy" in handoff
    assert "service-user authentication policy" in handoff
    assert "programmatic access token (PAT) kept outside this repository" in handoff

    # DDSS 10.5 catalog synchronization and access-policy prerequisites.
    assert "associated DDSS index" in handoff
    assert "SQS queue and S3 event notification" in handoff
    assert "generated S3 bucket and SQS queue policies" in handoff
    assert "does not support DDSS locations in Azure or GCP" in handoff

    catalogs = {
        item["key"]: item for item in metadata["amazon_s3_data_catalog_options"]
    }
    assert set(catalogs) == {"aws_glue", "iceberg_rest", "splunk_native"}
    assert "apache_iceberg" in catalogs["aws_glue"]["formats"]
    assert "delta_lake" in catalogs["aws_glue"]["formats"]
    assert "Apache Iceberg REST catalog" in handoff
    assert "Splunk-native data catalog" in handoff
    assert "non_table_json_or_parquet" in handoff


def test_specialized_asl_and_sal_provider_types_render_handoffs_without_crud(
    tmp_path: Path,
) -> None:
    spec = write_spec(
        tmp_path,
        "specialized.json",
        {
            "providers": [
                {"name": "security_lake", "type": "aws_lake"},
                {"name": "cisco_sal", "type": "aws_s3_sal"},
            ],
            "federated_indexes": [],
        },
    )
    out = tmp_path / "out"
    dry_run = run_render(
        "--output-dir", str(out), "--spec", str(spec), "--dry-run", "--json"
    )
    assert dry_run.returncode == 0, dry_run.stderr
    assert json.loads(dry_run.stdout)["commands"]["apply"] == []
    result = run_render("--output-dir", str(out), "--spec", str(spec))
    assert result.returncode == 0, result.stderr

    render_dir = out / "federated-search"
    metadata = json.loads((render_dir / "metadata.json").read_text())
    requested = {
        item["name"]: item for item in metadata["providers"]["specialized_handoffs"]
    }
    assert requested["security_lake"] == {
        "name": "security_lake",
        "provider_type": "aws_lake",
        "lifecycle": "available_by_activation",
        "automation": "ui_handoff",
        "disabled": False,
    }
    assert requested["cisco_sal"] == {
        "name": "cisco_sal",
        "provider_type": "aws_s3_sal",
        "lifecycle": "documented_conditional",
        "automation": "ui_handoff",
        "disabled": False,
    }
    handoff = (render_dir / "specialized-federation-handoff.md").read_text()
    assert "Federated Analytics for Amazon Security Lake" in handoff
    assert "Federated Search for Cisco Security Analytics and Logging" in handoff
    assert "`security_lake` -> `aws_lake`" in handoff
    assert "`cisco_sal` -> `aws_s3_sal`" in handoff
    assert "must not be represented" in handoff
    assert "generic `aws_s3`" in handoff
    assert not (render_dir / "aws-s3-providers").exists()
    apply_rest = (render_dir / "apply-rest.sh").read_text()
    assert "security_lake" not in apply_rest
    assert "cisco_sal" not in apply_rest
    assert "POST /services/data/federated" not in apply_rest
    assert "HANDOFF ONLY" in apply_rest
    assert "no supported REST CRUD contract" in apply_rest
    apply_local = (render_dir / "apply-search-head.sh").read_text()
    assert "HANDOFF ONLY" in apply_local
    assert "no supported local apply contract" in apply_local
    for script in ("apply-search-head.sh", "apply-rest.sh"):
        refused = subprocess.run(
            ["bash", str(render_dir / script)],
            cwd=render_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        assert refused.returncode == 2
    validate = run_validate("--output-dir", str(out))
    assert validate.returncode == 0, validate.stderr + validate.stdout


def test_specialized_handoff_provider_refuses_federated_index_crud(
    tmp_path: Path,
) -> None:
    spec = write_spec(
        tmp_path,
        "bad-specialized-index.json",
        {
            "providers": [{"name": "security_lake", "type": "aws_lake"}],
            "federated_indexes": [
                {
                    "name": "asl_findings",
                    "provider": "security_lake",
                    "dataset_type": "glue_table",
                    "dataset_name": "ocsf_findings",
                }
            ],
        },
    )
    result = run_render(
        "--output-dir", str(tmp_path / "out"), "--spec", str(spec)
    )
    assert result.returncode != 0
    assert "handoff-only provider 'security_lake'" in result.stderr
    assert "no stable public CRUD contract" in result.stderr


def test_fss3_payload_omits_kms_when_not_provided(tmp_path: Path) -> None:
    spec = _fss3_provider_spec(tmp_path)
    spec["providers"][0].pop("aws_kms_keys_arn_allowlist")
    spec_path = write_spec(tmp_path, "fss3_nokms.json", spec)
    out = tmp_path / "out"
    result = run_render("--output-dir", str(out), "--spec", str(spec_path))
    assert result.returncode == 0, result.stderr
    payload = json.loads((out / "federated-search/aws-s3-providers/aws_logs.json").read_text())
    assert "aws_kms_keys_arn_allowlist" not in payload


def test_fss3_glue_table_must_be_in_allowlist(tmp_path: Path) -> None:
    spec = _fss3_provider_spec(tmp_path)
    spec["federated_indexes"][0]["dataset_name"] = "not_in_allowlist"
    spec_path = write_spec(tmp_path, "fss3_bad.json", spec)
    out = tmp_path / "out"
    result = run_render("--output-dir", str(out), "--spec", str(spec_path))
    assert result.returncode != 0
    assert "aws_glue_tables_allowlist" in result.stderr


# ---------------------------------------------------------------------------
# Validation gates
# ---------------------------------------------------------------------------


def test_transparent_provider_rejects_federated_index(tmp_path: Path) -> None:
    spec = {
        "providers": [
            {
                "name": "hybrid",
                "type": "splunk",
                "mode": "transparent",
                "host_port": "h:8089",
                "service_account": "u",
                "password_file": str(tmp_path / "pw"),
            }
        ],
        "federated_indexes": [
            {
                "name": "bad",
                "provider": "hybrid",
                "dataset_type": "index",
                "dataset_name": "main",
            }
        ],
    }
    spec_path = write_spec(tmp_path, "bad.json", spec)
    out = tmp_path / "out"
    result = run_render("--output-dir", str(out), "--spec", str(spec_path))
    assert result.returncode != 0
    assert "transparent" in result.stderr.lower()


def test_duplicate_transparent_endpoint_rejected(tmp_path: Path) -> None:
    spec = {
        "providers": [
            {
                "name": "a",
                "type": "splunk",
                "mode": "transparent",
                "host_port": "h:8089",
                "service_account": "u",
                "password_file": str(tmp_path / "pw"),
            },
            {
                "name": "b",
                "type": "splunk",
                "mode": "transparent",
                "host_port": "h:8089",
                "service_account": "u",
                "password_file": str(tmp_path / "pw"),
            },
        ]
    }
    spec_path = write_spec(tmp_path, "dupe.json", spec)
    out = tmp_path / "out"
    result = run_render("--output-dir", str(out), "--spec", str(spec_path))
    assert result.returncode != 0
    assert "transparent-mode providers sharing" in result.stderr


def test_mixed_mode_same_endpoint_rejected(tmp_path: Path) -> None:
    spec = {
        "providers": [
            {
                "name": "a",
                "type": "splunk",
                "mode": "standard",
                "host_port": "h:8089",
                "service_account": "u",
                "password_file": str(tmp_path / "pw"),
                "app_context": "search",
            },
            {
                "name": "b",
                "type": "splunk",
                "mode": "transparent",
                "host_port": "h:8089",
                "service_account": "u",
                "password_file": str(tmp_path / "pw"),
            },
        ]
    }
    spec_path = write_spec(tmp_path, "mixed.json", spec)
    out = tmp_path / "out"
    result = run_render("--output-dir", str(out), "--spec", str(spec_path))
    assert result.returncode != 0
    assert "Mixed standard+transparent" in result.stderr


def test_duplicate_app_context_same_endpoint_rejected(tmp_path: Path) -> None:
    spec = {
        "providers": [
            {
                "name": "a",
                "type": "splunk",
                "mode": "standard",
                "host_port": "h:8089",
                "service_account": "u",
                "password_file": str(tmp_path / "pw"),
                "app_context": "search",
            },
            {
                "name": "b",
                "type": "splunk",
                "mode": "standard",
                "host_port": "h:8089",
                "service_account": "u",
                "password_file": str(tmp_path / "pw"),
                "app_context": "search",
            },
        ]
    }
    spec_path = write_spec(tmp_path, "dup_ctx.json", spec)
    out = tmp_path / "out"
    result = run_render("--output-dir", str(out), "--spec", str(spec_path))
    assert result.returncode != 0
    assert "same app_context" in result.stderr


def test_invalid_aws_account_rejected(tmp_path: Path) -> None:
    spec = _fss3_provider_spec(tmp_path)
    spec["providers"][0]["aws_account_id"] = "12345"
    spec_path = write_spec(tmp_path, "bad_account.json", spec)
    out = tmp_path / "out"
    result = run_render("--output-dir", str(out), "--spec", str(spec_path))
    assert result.returncode != 0
    assert "12-digit AWS account ID" in result.stderr


def test_invalid_s3_path_rejected(tmp_path: Path) -> None:
    spec = _fss3_provider_spec(tmp_path)
    spec["providers"][0]["aws_s3_paths_allowlist"] = ["http://nope/"]
    spec_path = write_spec(tmp_path, "bad_s3.json", spec)
    out = tmp_path / "out"
    result = run_render("--output-dir", str(out), "--spec", str(spec_path))
    assert result.returncode != 0
    assert "Amazon S3 URIs" in result.stderr


# ---------------------------------------------------------------------------
# Apply scripts
# ---------------------------------------------------------------------------


def test_rendered_apply_search_head_substitutes_passwords(tmp_path: Path) -> None:
    pw_a = tmp_path / "pw_a"
    pw_b = tmp_path / "pw_b"
    pw_a.write_text("password-a-VALUE", encoding="utf-8")
    pw_b.write_text("password-b-VALUE", encoding="utf-8")
    os.chmod(pw_a, 0o600)
    os.chmod(pw_b, 0o600)
    fake_home = tmp_path / "splunk"
    write_supported_fake_splunk_home(fake_home)
    # When --spec is set, CLI single-provider flags are NOT used. The spec must
    # carry splunk_home / app_name / restart_splunk for the apply test.
    spec = {
        "splunk_home": str(fake_home),
        "app_name": "ZZZ_test_apply",
        "restart_splunk": False,
        "providers": [
            {
                "name": "alpha",
                "type": "splunk",
                "mode": "standard",
                "host_port": "h1:8089",
                "service_account": "u",
                "password_file": str(pw_a),
            },
            {
                "name": "beta",
                "type": "splunk",
                "mode": "standard",
                "host_port": "h2:8089",
                "service_account": "u",
                "password_file": str(pw_b),
                "app_context": "search",
            },
        ],
        "federated_indexes": [
            {"name": "alpha_idx", "provider": "alpha", "dataset_type": "index", "dataset_name": "main"}
        ],
    }
    spec_path = write_spec(tmp_path, "spec.json", spec)
    out = tmp_path / "out"
    result = run_render("--output-dir", str(out), "--spec", str(spec_path))
    assert result.returncode == 0, result.stderr
    apply_script = out / "federated-search/apply-search-head.sh"
    apply_result = subprocess.run(
        ["bash", str(apply_script)],
        cwd=str(out / "federated-search"),
        capture_output=True,
        text=True,
        check=False,
    )
    assert apply_result.returncode == 0, apply_result.stderr
    rendered_conf = (
        fake_home / "etc/apps/ZZZ_test_apply/local/federated.conf"
    ).read_text(encoding="utf-8")
    assert "password = password-a-VALUE" in rendered_conf
    assert "password = password-b-VALUE" in rendered_conf
    assert "__FEDERATED_PASSWORD_FILE_BASE64__" not in rendered_conf
    # Ensure the deployed conf is locked down to the operator only.
    mode = (fake_home / "etc/apps/ZZZ_test_apply/local/federated.conf").stat().st_mode & 0o777
    assert mode == 0o600


def test_rendered_apply_fails_loudly_when_password_file_missing(tmp_path: Path) -> None:
    fake_home = tmp_path / "splunk"
    write_supported_fake_splunk_home(fake_home)
    spec = {
        "splunk_home": str(fake_home),
        "restart_splunk": False,
        "providers": [
            {
                "name": "alpha",
                "type": "splunk",
                "mode": "standard",
                "host_port": "h:8089",
                "service_account": "u",
                "password_file": str(tmp_path / "missing"),
            }
        ],
        "federated_indexes": [
            {"name": "alpha_idx", "provider": "alpha", "dataset_type": "index", "dataset_name": "main"}
        ],
    }
    spec_path = write_spec(tmp_path, "spec.json", spec)
    out = tmp_path / "out"
    run_render("--output-dir", str(out), "--spec", str(spec_path))
    apply_script = out / "federated-search/apply-search-head.sh"
    apply_result = subprocess.run(
        ["bash", str(apply_script)],
        cwd=str(out / "federated-search"),
        capture_output=True,
        text=True,
        check=False,
    )
    assert apply_result.returncode != 0
    assert "password_file missing" in apply_result.stderr or "password_file missing" in apply_result.stdout


# ---------------------------------------------------------------------------
# Global toggle and status scripts
# ---------------------------------------------------------------------------


def test_global_toggle_scripts_post_correct_payload(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = run_render(
        "--output-dir", str(out),
        "--remote-host-port", "remote-sh.example.com:8089",
        "--service-account", "u",
        "--password-file", str(tmp_path / "pw"),
    )
    assert result.returncode == 0, result.stderr
    enable = (out / "federated-search/global-enable.sh").read_text()
    disable = (out / "federated-search/global-disable.sh").read_text()
    assert "disabled=false" in enable
    assert "disabled=true" in disable
    assert "/services/data/federated/settings/general" in enable
    assert "SPLUNK_REST_PASSWORD_FILE" in enable
    # Status script must hit all three documented endpoints.
    status = (out / "federated-search/status.sh").read_text()
    assert "/services/data/federated/provider" in status
    assert "/services/data/federated/index" in status
    assert "/services/data/federated/settings/general" in status


def test_apply_rest_payload_includes_password_substitution(tmp_path: Path) -> None:
    pw = tmp_path / "pw"
    pw.write_text("admin-pw-VALUE", encoding="utf-8")
    spec = {
        "providers": [
            {
                "name": "alpha",
                "type": "splunk",
                "mode": "standard",
                "host_port": "h:8089",
                "service_account": "u",
                "password_file": str(pw),
            }
        ],
        "federated_indexes": [
            {"name": "alpha_idx", "provider": "alpha", "dataset_type": "index", "dataset_name": "main"}
        ],
    }
    spec_path = write_spec(tmp_path, "spec.json", spec)
    out = tmp_path / "out"
    run_render("--output-dir", str(out), "--spec", str(spec_path))
    rest = (out / "federated-search/apply-rest.sh").read_text()
    # The rendered REST apply must read passwords from the password_file at
    # apply time, not embed the value at render time.
    assert "admin-pw-VALUE" not in rest
    assert "password_file" in rest
    assert "SPLUNK_REST_PASSWORD_FILE" in rest
    assert "/services/data/federated/provider" in rest
    assert "/services/data/federated/index" in rest


def test_apply_rest_refuses_http_without_explicit_lab_opt_in(tmp_path: Path) -> None:
    render_dir, env = render_rest_apply_fixture(tmp_path)
    env["SPLUNK_REST_URI"] = "http://127.0.0.1:9"
    result = run_rest_apply(render_dir, env)
    assert result.returncode != 0
    assert "refuses plaintext HTTP" in result.stderr


def test_apply_rest_allows_explicit_lab_http_with_warning(tmp_path: Path) -> None:
    authorization_headers: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            authorization_headers.append(self.headers.get("Authorization", ""))
            content_length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(content_length)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        render_dir, env = render_rest_apply_fixture(tmp_path)
        env.update(
            {
                "SPLUNK_REST_URI": f"http://127.0.0.1:{server.server_port}",
                "SPLUNK_ALLOW_INSECURE_HTTP": "true",
            }
        )
        result = run_rest_apply(render_dir, env)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "LAB ONLY" in result.stderr
        assert len(authorization_headers) == 2
        assert all(value.startswith("Basic ") for value in authorization_headers)
    finally:
        server.shutdown()
        server.server_close()


def test_apply_rest_rejects_uri_userinfo_without_echoing_secret(tmp_path: Path) -> None:
    render_dir, env = render_rest_apply_fixture(tmp_path)
    env["SPLUNK_REST_URI"] = "https://embedded:uri-secret@example.test:8089"
    result = run_rest_apply(render_dir, env)
    assert result.returncode != 0
    assert "userinfo" in result.stderr
    assert "uri-secret" not in result.stderr


def test_apply_rest_refuses_redirect_without_forwarding_credentials(tmp_path: Path) -> None:
    target_authorization: list[str] = []

    class TargetHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            target_authorization.append(self.headers.get("Authorization", ""))
            self.send_response(200)
            self.end_headers()

        def do_POST(self) -> None:  # noqa: N802
            self.do_GET()

        def log_message(self, _format: str, *_args: object) -> None:
            return

    target = ThreadingHTTPServer(("127.0.0.1", 0), TargetHandler)

    class RedirectHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            self.send_response(302)
            self.send_header(
                "Location",
                f"http://127.0.0.1:{target.server_port}/credential-target",
            )
            self.end_headers()

        def log_message(self, _format: str, *_args: object) -> None:
            return

    redirect = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
    threads = [
        threading.Thread(target=server.serve_forever, daemon=True)
        for server in (target, redirect)
    ]
    for thread in threads:
        thread.start()
    try:
        render_dir, env = render_rest_apply_fixture(tmp_path)
        env.update(
            {
                "SPLUNK_REST_URI": f"http://127.0.0.1:{redirect.server_port}",
                "SPLUNK_ALLOW_INSECURE_HTTP": "true",
            }
        )
        result = run_rest_apply(render_dir, env)
        assert result.returncode != 0
        assert "HTTP 302" in result.stderr
        assert target_authorization == []
    finally:
        for server in (redirect, target):
            server.shutdown()
            server.server_close()


# ---------------------------------------------------------------------------
# setup.sh + validate.sh wrappers
# ---------------------------------------------------------------------------


def test_setup_help_documents_new_flags() -> None:
    result = run_setup("--help")
    assert result.returncode == 0
    for token in (
        "--spec",
        "--provider",
        "--federated-index",
        "--apply-target search-head|shc-deployer|rest",
        "--global-toggle",
        "aws_lake",
        "aws_s3_sal",
        "phased-deprecation",
        "SPLUNK_REST_URI",
        "SPLUNK_REST_PASSWORD_FILE",
    ):
        assert token in result.stdout, f"--help is missing '{token}'"


def test_setup_rejects_unknown_flag() -> None:
    result = run_setup("--bogus")
    assert result.returncode == 1
    assert "Unknown option" in result.stderr or "Unknown option" in result.stdout


def test_setup_rejects_global_toggle_without_direction() -> None:
    result = run_setup("--phase", "global-toggle")
    assert result.returncode == 1
    assert "global-toggle" in result.stdout


def test_validate_passes_for_freshly_rendered_spec(tmp_path: Path) -> None:
    spec = _fss3_provider_spec(tmp_path)
    spec["providers"].append(
        {
            "name": "remote_prod",
            "type": "splunk",
            "mode": "standard",
            "host_port": "remote:8089",
            "service_account": "u",
            "password_file": str(tmp_path / "pw"),
        }
    )
    spec["federated_indexes"].append(
        {
            "name": "remote_main",
            "provider": "remote_prod",
            "dataset_type": "index",
            "dataset_name": "main",
        }
    )
    spec_path = write_spec(tmp_path, "spec.json", spec)
    out = tmp_path / "out"
    run_render("--output-dir", str(out), "--spec", str(spec_path))
    validate = run_validate("--output-dir", str(out))
    assert validate.returncode == 0, validate.stderr or validate.stdout


def test_validate_detects_missing_password_placeholder(tmp_path: Path) -> None:
    out = tmp_path / "out"
    run_render(
        "--output-dir", str(out),
        "--remote-host-port", "h:8089",
        "--service-account", "u",
        "--password-file", str(tmp_path / "pw"),
        "--provider-name", "alpha",
    )
    fed = out / "federated-search/federated.conf.template"
    text = fed.read_text(encoding="utf-8")
    # Corrupt the placeholder to simulate a renderer regression.
    fed.write_text(
        re.sub(r"__FEDERATED_PASSWORD_FILE_BASE64__[A-Z_]+__", "REDACTED", text),
        encoding="utf-8",
    )
    validate = run_validate("--output-dir", str(out))
    assert validate.returncode != 0
    combined = validate.stderr + validate.stdout
    assert "password placeholder" in combined or "missing placeholder" in combined


def test_validate_detects_corrupt_fss3_payload(tmp_path: Path) -> None:
    spec = _fss3_provider_spec(tmp_path)
    spec_path = write_spec(tmp_path, "spec.json", spec)
    out = tmp_path / "out"
    run_render("--output-dir", str(out), "--spec", str(spec_path))
    payload = out / "federated-search/aws-s3-providers/aws_logs.json"
    # Strip a required key to simulate drift.
    data = json.loads(payload.read_text())
    data.pop("aws_account_id")
    payload.write_text(json.dumps(data), encoding="utf-8")
    validate = run_validate("--output-dir", str(out))
    assert validate.returncode != 0
    combined = validate.stderr + validate.stdout
    assert "FSS3 keys" in combined or "schema check" in combined


def test_validate_detects_specialized_provider_identity_drift(tmp_path: Path) -> None:
    out = tmp_path / "out"
    run_render(
        "--output-dir", str(out),
        "--remote-host-port", "remote:8089",
        "--service-account", "u",
        "--password-file", str(tmp_path / "pw"),
    )
    metadata_path = out / "federated-search/metadata.json"
    metadata = json.loads(metadata_path.read_text())
    metadata["specialized_federation_handoffs"][0]["provider_type"] = "aws_s3"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    validate = run_validate("--output-dir", str(out))
    assert validate.returncode != 0
    combined = validate.stderr + validate.stdout
    assert "lifecycle metadata/handoff contract" in combined


# ---------------------------------------------------------------------------
# Repeated CLI flag form
# ---------------------------------------------------------------------------


def test_repeated_provider_flags_render_multi_provider(tmp_path: Path) -> None:
    out = tmp_path / "out"
    pw = tmp_path / "pw"
    pw.write_text("x", encoding="utf-8")
    result = run_render(
        "--output-dir", str(out),
        "--provider", f"name=remote_a,type=splunk,mode=standard,host_port=ha:8089,service_account=u,password_file={pw},app_context=search",
        "--provider", f"name=remote_b,type=splunk,mode=standard,host_port=hb:8089,service_account=u,password_file={pw},app_context=search",
        "--federated-index", "name=idx_a,provider=remote_a,dataset_type=index,dataset_name=main",
        "--federated-index", "name=idx_b,provider=remote_b,dataset_type=metricindex,dataset_name=cpu",
    )
    assert result.returncode == 0, result.stderr
    fed = (out / "federated-search/federated.conf.template").read_text()
    assert "[provider://remote_a]" in fed
    assert "[provider://remote_b]" in fed
    indexes = (out / "federated-search/indexes.conf").read_text()
    assert "[federated:idx_a]" in indexes
    assert "[federated:idx_b]" in indexes
    assert "federated.dataset = metricindex:cpu" in indexes

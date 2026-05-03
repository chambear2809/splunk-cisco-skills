"""Offline regressions for splunk-federated-search-setup."""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
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
    # FSS2S federated.conf.template should NOT contain the FSS3 provider name
    fed = (out / "federated-search/federated.conf.template").read_text()
    assert "aws_logs" not in fed


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
    fake_home = tmp_path / "splunk"
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

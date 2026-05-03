"""Regressions for the Splunk Platform <-> Splunk Observability Cloud integration skill.

Covers:
- Secret-leak scans across every rendered file
- Multi-org default-org renders as `deeplink` (not `api_apply`)
- Cloud vs Enterprise coverage gating
- SIM Add-on `SAMPLE_` modular-input rejection
- chmod-600 enforcement (via setup.sh) plus the --allow-loose-token-perms override
- --i-accept-rbac-cutover guard on enable-centralized-rbac
- Handoff text references the partner skills by exact relative path
- Region/realm mismatch preflight (FAIL on bad realm string)
- GovCloud + GCP carve-out collapses UID sections to not_applicable
- Idempotency: re-render against the same spec is a no-op
- --doctor renders the doctor-report.md catalog
- MTS sizing preflight rejects oversized SignalFlow programs
- apply-state.json bookkeeping captures every step
- --rollback renders reverse commands

The tests import the renderer module directly to keep CI fast; only chmod and
setup.sh-wrapper assertions spawn the bash entrypoint.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills/splunk-observability-cloud-integration-setup"
SETUP = SKILL_DIR / "scripts/setup.sh"
SCRIPTS_DIR = SKILL_DIR / "scripts"
TEMPLATE = SKILL_DIR / "template.example"


def _load_renderer():
    """Import render_assets.py without polluting sys.path globally."""
    spec = importlib.util.spec_from_file_location(
        "soics_render_assets", SCRIPTS_DIR / "render_assets.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_apply_state():
    spec = importlib.util.spec_from_file_location(
        "soics_apply_state", SCRIPTS_DIR / "_apply_state.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _spec(**overrides):
    base = {
        "api_version": "splunk-observability-cloud-integration-setup/v1",
        "target": "cloud",
        "realm": "us0",
        "splunk_cloud_stack": "test-stack",
    }
    base.update(overrides)
    return base


def _rendered_text(root: Path) -> str:
    chunks: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(chunks)


def test_render_succeeds_for_default_spec(tmp_path: Path) -> None:
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec())
    result = renderer.render(spec, tmp_path)
    assert (tmp_path / "00-prerequisites.md").exists()
    assert (tmp_path / "09-handoff.md").exists()
    assert (tmp_path / "coverage-report.json").exists()
    assert (tmp_path / "apply-plan.json").exists()
    assert (tmp_path / "scripts/apply-pairing.sh").exists()
    assert (tmp_path / "sim-addon/mts-sizing.md").exists()
    assert (tmp_path / "support-tickets/cross-region-pairing.md").exists()
    assert "coverage" in result


def test_rendered_artifacts_never_include_token_values(tmp_path: Path) -> None:
    """Every rendered file must reference token files by path, never inline secrets."""
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec())
    renderer.render(spec, tmp_path)
    text = _rendered_text(tmp_path)
    # Look for plausible secret patterns: JWTs, bearer tokens, etc.
    for marker in ("eyJ", "Bearer ABC", "Bearer xyz123", "BAD_LITERAL_TOKEN_VALUE"):
        assert marker not in text, f"rendered tree leaked marker: {marker!r}"
    # Sanity: the renderer must reference the env-var path, not a file name.
    assert "${SPLUNK_O11Y_TOKEN_FILE}" in text or "${SPLUNK_O11Y_ADMIN_TOKEN_FILE}" in text


def test_multi_org_default_renders_as_deeplink(tmp_path: Path) -> None:
    """Make Default has no public API; it must render as deeplink."""
    renderer = _load_renderer()
    spec = renderer.validate_spec(
        _spec(
            pairing={
                "mode": "unified_identity",
                "multi_org": [
                    {"realm": "us0", "label": "prod", "make_default": True},
                    {"realm": "us1", "label": "staging"},
                ],
            }
        )
    )
    renderer.render(spec, tmp_path)
    coverage = json.loads((tmp_path / "coverage-report.json").read_text())["coverage"]
    assert coverage["pairing.multi_org_default"]["status"] == "deeplink"
    plan = (tmp_path / "02-pairing.md").read_text()
    assert "Make Default" in plan
    assert "no public api" in plan.lower()


def test_enterprise_target_collapses_uid_sections_to_not_applicable(tmp_path: Path) -> None:
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec(target="enterprise"))
    spec.pop("splunk_cloud_stack", None)
    renderer.render(spec, tmp_path)
    coverage = json.loads((tmp_path / "coverage-report.json").read_text())["coverage"]
    assert coverage["pairing.uid"]["status"] == "not_applicable"
    assert coverage["centralized_rbac.capabilities"]["status"] == "not_applicable"
    assert coverage["centralized_rbac.cutover"]["status"] == "not_applicable"
    assert coverage["discover_app.related_discovery"]["status"] == "not_applicable"
    # SE keeps SA pairing + Related Content + SIM and switches LOC to TLS path.
    assert coverage["pairing.sa"]["status"] == "api_apply"
    assert coverage["sim_addon.account"]["status"] == "api_apply"
    assert coverage["log_observer_connect.tls_cert"]["status"] == "handoff"
    assert coverage["sim_addon.victoria_hec"]["status"] == "not_applicable"


def test_govcloud_or_gcp_carve_out_disables_uid(tmp_path: Path) -> None:
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec(realm="us2-gcp"))
    renderer.render(spec, tmp_path)
    coverage = json.loads((tmp_path / "coverage-report.json").read_text())["coverage"]
    assert coverage["pairing.uid"]["status"] == "not_applicable"
    assert coverage["centralized_rbac.capabilities"]["status"] == "not_applicable"
    assert coverage["centralized_rbac.cutover"]["status"] == "not_applicable"
    # Service Account pairing is still available as the fallback.
    assert coverage["pairing.sa"]["status"] == "api_apply"


def test_unknown_realm_fails_validation() -> None:
    renderer = _load_renderer()
    with pytest.raises(renderer.RenderError, match="realm 'eu999'"):
        renderer.validate_spec(_spec(realm="eu999"))


def test_sample_prefix_modinput_rejected() -> None:
    renderer = _load_renderer()
    with pytest.raises(renderer.RenderError, match="SAMPLE_"):
        renderer.validate_spec(_spec(sim_addon={"modular_inputs": ["SAMPLE_AWS_EC2"]}))


def test_unknown_modinput_template_rejected() -> None:
    renderer = _load_renderer()
    with pytest.raises(renderer.RenderError, match="unknown templates"):
        renderer.validate_spec(_spec(sim_addon={"modular_inputs": ["not_a_template"]}))


def test_mts_sizing_preflight_fails_oversized(tmp_path: Path) -> None:
    """Spec that would exceed 250k MTS per modular input FAILs render."""
    renderer = _load_renderer()
    # Force os_hosts (18 MTS/entity) with an unrealistic 100,000 entities = 1.8M MTS.
    spec = renderer.validate_spec(
        _spec(
            sim_addon={
                "modular_inputs": ["os_hosts"],
                "expected_entities_per_input": 100000,
            }
        )
    )
    with pytest.raises(renderer.RenderError, match="exceeds hard cap"):
        renderer.render(spec, tmp_path)


def test_mts_sizing_preflight_passes_default(tmp_path: Path) -> None:
    """Default entities-per-input keeps every catalog template under the 250k cap."""
    renderer = _load_renderer()
    spec = renderer.validate_spec(
        _spec(sim_addon={"modular_inputs": list(renderer.SIGNALFLOW_CATALOG.keys())})
    )
    result = renderer.render(spec, tmp_path)
    for row in result["mts"]:
        assert row["mts_total"] < renderer.MTS_PER_MODULAR_INPUT_CAP, row


def test_handoff_references_partner_skills(tmp_path: Path) -> None:
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec())
    renderer.render(spec, tmp_path)
    handoff = (tmp_path / "09-handoff.md").read_text()
    assert "skills/splunk-app-install" in handoff
    assert "skills/splunk-cloud-acs-allowlist-setup" in handoff
    assert "skills/splunk-itsi-config" in handoff
    assert "skills/splunk-observability-otel-collector-setup" in handoff
    assert "skills/splunk-oncall-setup" in handoff


def test_apply_pairing_script_includes_all_realms(tmp_path: Path) -> None:
    renderer = _load_renderer()
    spec = renderer.validate_spec(
        _spec(
            pairing={
                "mode": "unified_identity",
                "multi_org": [
                    {"realm": "us0", "make_default": True},
                    {"realm": "us1"},
                    {"realm": "eu0"},
                ],
            }
        )
    )
    renderer.render(spec, tmp_path)
    apply_pairing = (tmp_path / "scripts/apply-pairing.sh").read_text()
    assert "--o11y-realm us0" in apply_pairing
    assert "--o11y-realm us1" in apply_pairing
    assert "--o11y-realm eu0" in apply_pairing


def test_apply_rbac_script_guards_destructive_step(tmp_path: Path) -> None:
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec(centralized_rbac={"enable_centralized_rbac": True}))
    renderer.render(spec, tmp_path)
    rbac = (tmp_path / "scripts/apply-rbac.sh").read_text()
    assert "SOICS_RBAC_CUTOVER_ACK" in rbac
    assert "--i-accept-rbac-cutover" in rbac


def test_doctor_renders_report_when_doctor_data_supplied(tmp_path: Path) -> None:
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec())
    doctor = [
        {"severity": "FAIL", "check": "Token authentication enabled", "fix": "setup.sh --enable-token-auth"},
        {"severity": "WARN", "check": "Pairing exists for target realm", "fix": "(none)"},
    ]
    renderer.render(spec, tmp_path, doctor_data=doctor)
    report = (tmp_path / "doctor-report.md").read_text()
    assert "FAIL" in report
    assert "setup.sh --enable-token-auth" in report


def test_discover_writes_current_state(tmp_path: Path) -> None:
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec())
    snapshot = {"timestamp": "2026-05-03T00:00:00Z", "pairings": []}
    renderer.render(spec, tmp_path, discover_data=snapshot)
    state = json.loads((tmp_path / "current-state.json").read_text())
    assert state["timestamp"] == "2026-05-03T00:00:00Z"


def test_idempotent_double_render(tmp_path: Path) -> None:
    """Rendering twice into the same dir yields the same file set."""
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec())
    renderer.render(spec, tmp_path)
    first = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())
    renderer.render(spec, tmp_path)
    second = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())
    assert first == second


def test_apply_state_records_step(tmp_path: Path) -> None:
    apply_state = _load_apply_state()
    state_dir = tmp_path / "state"
    apply_state.append_step(
        state_dir,
        section="pairing",
        step="pair",
        idempotency_key="pairing:us0:test-stack",
        result="success",
        response={"id": "abc123"},
    )
    state = json.loads((state_dir / "apply-state.json").read_text())
    assert state["steps"][0]["section"] == "pairing"
    assert state["steps"][0]["result"] == "success"
    assert apply_state.has_step(state_dir, "pairing:us0:test-stack")


def test_apply_state_redacts_secrets() -> None:
    apply_state = _load_apply_state()
    redacted = apply_state.redact({
        "Authorization": "Bearer eyJabc.def.ghi",
        "o11y-access-token": "abcdef123",
        "realm": "us0",
        "nested": {"password": "supersecret"},
    })
    assert redacted["Authorization"] == "[REDACTED]"
    assert redacted["o11y-access-token"] == "[REDACTED]"
    assert redacted["realm"] == "us0"
    assert redacted["nested"]["password"] == "[REDACTED]"


def test_setup_sh_help_runs() -> None:
    """The bash entrypoint must at least print --help without error."""
    result = subprocess.run(
        ["bash", str(SETUP), "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Splunk Platform <-> Splunk Observability Cloud" in result.stdout


def test_setup_sh_rejects_direct_secret_token_flag() -> None:
    result = subprocess.run(
        ["bash", str(SETUP), "--token", "BAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "--token-file" in result.stderr or "--token-file" in result.stdout
    assert "Refusing direct-secret flag" in result.stderr or "Refusing direct-secret flag" in result.stdout


def test_setup_sh_rejects_admin_token_direct_flag() -> None:
    result = subprocess.run(
        ["bash", str(SETUP), "--admin-token", "BAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "Refusing direct-secret flag" in (result.stdout + result.stderr)


def test_setup_sh_chmod_600_enforced(tmp_path: Path) -> None:
    """Loose-permission token files refuse without --allow-loose-token-perms."""
    token = tmp_path / "loose.token"
    token.write_text("nope", encoding="utf-8")
    os.chmod(token, 0o644)
    result = subprocess.run(
        [
            "bash", str(SETUP),
            "--apply", "pairing",
            "--realm", "us0",
            "--admin-token-file", str(token),
            "--output-dir", str(tmp_path / "out"),
            "--spec", str(TEMPLATE),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "loose permissions" in combined or "chmod 600" in combined


def test_setup_sh_list_sim_templates() -> None:
    result = subprocess.run(
        ["bash", str(SETUP), "--list-sim-templates"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "aws_ec2" in result.stdout
    assert "kubernetes" in result.stdout
    assert "MTS/entity" in result.stdout


def test_setup_sh_rollback_pairing_renders_handoff(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            "bash", str(SETUP),
            "--rollback", "pairing",
            "--output-dir", str(tmp_path / "out"),
            "--spec", str(TEMPLATE),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "no public API for unpair" in result.stdout
    assert "Discover Splunk Observability Cloud" in result.stdout


def test_setup_sh_explain_prints_coverage(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            "bash", str(SETUP),
            "--explain",
            "--output-dir", str(tmp_path / "out"),
            "--spec", str(TEMPLATE),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "pairing.uid" in result.stdout
    assert "centralized_rbac.cutover" in result.stdout
    assert "sim_addon.account" in result.stdout


def test_smoke_offline_runs() -> None:
    """The bundled smoke script must complete cleanly."""
    result = subprocess.run(
        ["bash", str(SKILL_DIR / "scripts/smoke_offline.sh")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "smoke_offline: OK" in result.stdout


def test_validate_json_mode_is_well_formed(tmp_path: Path) -> None:
    """validate.sh --json must emit a parseable JSON document, not a Python NameError."""
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec())
    renderer.render(spec, tmp_path)
    result = subprocess.run(
        [
            "bash", str(SKILL_DIR / "scripts/validate.sh"),
            "--output-dir", str(tmp_path),
            "--json",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["output_dir"].endswith(tmp_path.name)
    assert payload["live"] is False
    assert payload["doctor"] is False
    assert payload["failures"] == []


def test_validate_secret_leak_scan_catches_injected_jwt(tmp_path: Path) -> None:
    """Injecting a JWT-looking string into a rendered file must FAIL validation."""
    renderer = _load_renderer()
    spec = renderer.validate_spec(_spec())
    renderer.render(spec, tmp_path)
    # Inject a plausible JWT.
    target = tmp_path / "02-pairing.md"
    target.write_text(target.read_text() + "\neyJABCDEFG1234567890ABCDEFGHIJKLMNOP\n")
    result = subprocess.run(
        ["bash", str(SKILL_DIR / "scripts/validate.sh"), "--output-dir", str(tmp_path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "secret-looking content" in (result.stdout + result.stderr)


def test_skill_is_registered_in_all_catalogs() -> None:
    """README + AGENTS + CLAUDE catalog tables must include the skill row."""
    expected = "splunk-observability-cloud-integration-setup"
    for doc in ("README.md", "AGENTS.md", "CLAUDE.md"):
        text = (REPO_ROOT / doc).read_text(encoding="utf-8")
        assert f"`{expected}`" in text, f"{doc}: missing catalog row for {expected}"


def test_skill_has_real_cursor_symlink() -> None:
    """The .cursor/skills/<skill> entry must be a real symlink to ../../skills/<skill>."""
    link = REPO_ROOT / ".cursor/skills/splunk-observability-cloud-integration-setup"
    assert link.is_symlink(), f"{link} must be a symlink"
    assert link.readlink().as_posix() == "../../skills/splunk-observability-cloud-integration-setup"


def test_claude_command_stub_references_skill_md() -> None:
    """The Claude slash-command stub must reference the SKILL.md path."""
    stub = REPO_ROOT / ".claude/commands/splunk-observability-cloud-integration-setup.md"
    assert stub.exists()
    text = stub.read_text(encoding="utf-8")
    assert "skills/splunk-observability-cloud-integration-setup/SKILL.md" in text


def test_app_registry_includes_splunk_ta_sim() -> None:
    """The Splunk_TA_sim app entry (Splunkbase 5247) must be in app_registry.json."""
    registry = json.loads((REPO_ROOT / "skills/shared/app_registry.json").read_text())
    splunkbase_ids = {entry.get("splunkbase_id") for entry in registry["apps"]}
    assert "5247" in splunkbase_ids
    sim_entries = [e for e in registry["apps"] if e.get("app_name") == "Splunk_TA_sim"]
    assert sim_entries, "Splunk_TA_sim must be registered in app_registry.json"
    assert sim_entries[0]["skill"] == "splunk-observability-cloud-integration-setup"


def test_credentials_example_documents_new_token_files() -> None:
    """credentials.example must document SPLUNK_O11Y_ADMIN_TOKEN_FILE + SPLUNK_O11Y_ORG_TOKEN_FILE."""
    creds = (REPO_ROOT / "credentials.example").read_text(encoding="utf-8")
    assert "SPLUNK_O11Y_ADMIN_TOKEN_FILE" in creds
    assert "SPLUNK_O11Y_ORG_TOKEN_FILE" in creds
    assert "PROFILE_o11y_pair__SPLUNK_O11Y_ADMIN_TOKEN_FILE" in creds


def test_gitignore_excludes_rendered_dir() -> None:
    """The rendered output dir must be in .gitignore so artifacts cannot be committed."""
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "/splunk-observability-cloud-integration-rendered/" in gitignore
